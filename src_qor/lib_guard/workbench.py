"""Loopback-only UI for the persistent per-IP review registry."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import ipaddress
import json
from pathlib import Path
import re
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4

try:
    import yaml
except ImportError:  # pragma: no cover - exercised only in intentionally minimal installs
    yaml = None

from flask import Blueprint, Flask, abort, render_template, request, send_file, url_for
from werkzeug.exceptions import HTTPException

from .review_runner import CHECK_NAMES, _json_read, _library_dir, run
from .raw_discovery import discover_raw_report, write_discovery_artifacts
from .effective_file_tracker import run as run_formal_nl


def _read_registry(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"ips": []}
    if yaml is None:
        raise RuntimeError("读取工作台 YAML 配置需要 PyYAML")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict) or not isinstance(data.get("ips", []), list):
        raise ValueError("IP 清单必须是包含 ips 列表的 YAML 对象")
    ids = [str(item.get("id") or "") for item in data["ips"] if isinstance(item, dict)]
    if len(ids) != len(set(ids)):
        raise ValueError("IP 清单中存在重复 id")
    return data


def _write_registry(path: Path, data: dict[str, Any]) -> None:
    if yaml is None:
        raise RuntimeError("写入工作台 YAML 配置需要 PyYAML")
    payload = yaml.safe_dump(data, allow_unicode=True, sort_keys=False)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        temporary.write_text(payload, encoding="utf-8")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _write_json(path: Path, data: dict[str, Any]) -> None:
    payload = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        temporary.write_text(payload, encoding="utf-8")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _text(form: Any, key: str) -> str:
    return str(form.get(key, "")).strip()


def _resolve_registry_path(value: str, registry_file: Path) -> str:
    path = Path(value).expanduser()
    return str((path if path.is_absolute() else registry_file.parent / path).resolve())


def _version_sort_key(value: str) -> tuple[tuple[int, Any], ...]:
    """Natural sort for sidebar labels only; this does not establish release order."""
    return tuple((0, int(part)) if part.isdigit() else (1, part.casefold())
                 for part in re.split(r"(\d+)", value))


def _entry_from_form(form: Any, previous: dict[str, Any] | None = None) -> dict[str, Any]:
    selected = set(form.getlist("checks"))
    unknown = selected - CHECK_NAMES
    if unknown:
        raise ValueError(f"不支持的检查名：{', '.join(sorted(unknown))}")
    ip_id = _text(form, "id") or str((previous or {}).get("id") or "")
    library_id = _text(form, "library_id") or str((previous or {}).get("library_id") or "")
    if not ip_id or not library_id:
        raise ValueError("IP 标识和库标识不能为空")
    entry = {
        "id": ip_id,
        "library_id": library_id,
        "name": _text(form, "name") or ip_id,
        "raw_version": _text(form, "raw_version"),
        "formal_stage": _text(form, "formal_stage"),
        "publish_latest": form.get("publish_latest") == "on",
        "checks": {},
    }
    specs = {
        "formal_nl": {"config": "formal_config", "report_json": "formal_report_json"},
        "macro_index": {"report_json": "macro_report_json", "filemap_json": "macro_filemap_json",
                         "root": "macro_root", "parser_facts_json": "macro_parser_facts_json",
                         "version": "macro_version", "library_id": "macro_library_id"},
        "lef_review": {"report_json": "lef_report_json", "old_file": "lef_old_file", "new_file": "lef_new_file"},
        "lef_liberty_check": {"report_json": "ll_report_json", "lef_analysis_json": "ll_lef_analysis_json",
                              "lef_library_id": "ll_lef_library_id"},
    }
    for check_name in sorted(selected):
        spec = {key: _text(form, field) for key, field in specs[check_name].items() if _text(form, field)}
        if check_name == "lef_liberty_check":
            liberty_paths = [line.strip() for line in _text(form, "ll_liberty_files").splitlines() if line.strip()]
            if liberty_paths:
                spec["liberty_files"] = liberty_paths
            spec["include_matching_cells"] = form.get("ll_include_matching_cells") == "on"
        entry["checks"][check_name] = spec
    if previous:
        entry["context_type"] = previous.get("context_type", "LIBRARY_REVIEW")
        for key in ("vendor", "middle_path", "library_name", "raw_root", "raw_versions", "formal_nl_root",
                    "formal_nl_stages", "formal_nl_scan_at", "formal_nl_report_status"):
            if key in previous:
                entry[key] = previous[key]
    return entry


def _validate_for_run(entry: dict[str, Any]) -> None:
    checks = entry.get("checks") or {}
    if not checks:
        raise ValueError("至少勾选一项检查")
    requirements = {
        "formal_nl": lambda spec: bool(spec.get("config") or spec.get("report_json")),
        "macro_index": lambda spec: bool(spec.get("report_json") or spec.get("filemap_json") or spec.get("root")),
        "lef_review": lambda spec: bool(spec.get("report_json") or (spec.get("old_file") and spec.get("new_file"))),
        "lef_liberty_check": lambda spec: bool(spec.get("report_json") or (spec.get("liberty_files") and
            ((checks.get("lef_review") is not None) or (spec.get("lef_analysis_json") and spec.get("lef_library_id"))))),
    }
    for name, spec in checks.items():
        if not requirements[name](spec):
            raise ValueError(f"{name} 已勾选，但缺少所需路径或报告输入")


def _save_entry(registry: dict[str, Any], entry: dict[str, Any]) -> None:
    ips = registry.setdefault("ips", [])
    for index, old in enumerate(ips):
        if old.get("id") == entry["id"]:
            ips[index] = entry
            break
    else:
        ips.append(entry)


def _history(output: Path, library_id: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    library_dir = output / "libraries" / _library_dir(library_id)
    latest = {}
    latest_path = library_dir / "latest.json"
    if latest_path.is_file():
        latest = _json_read(latest_path)
    records = []
    runs_dir = library_dir / "runs"
    if runs_dir.is_dir():
        for result_path in runs_dir.glob("*/review_result.json"):
            record = _json_read(result_path)
            record["workbook_url"] = url_for("ip_review.download", library_id=library_id,
                                              review_id=record.get("review_id", ""))
            records.append(record)
    records.sort(key=lambda item: str(item.get("generated_at", "")), reverse=True)
    return latest, records[:10]


def _formal_nl_latest(output: Path, library_id: str) -> dict[str, Any]:
    formal_dir = output / "formal_nl" / _library_dir(library_id)
    latest_path = formal_dir / "latest.json"
    if not latest_path.is_file():
        return {}
    try:
        latest = _json_read(latest_path)
        report_path = Path(str(latest.get("report_json") or "")).resolve()
        if not report_path.is_relative_to(output.resolve()) or not report_path.is_file():
            return {}
        report = _json_read(report_path)
    except (OSError, ValueError, json.JSONDecodeError):
        return {}
    stages = []
    for match in report.get("matches") or []:
        stage = str(match.get("nl_version") or "")
        inventory = (report.get("inventories") or {}).get(stage) or {}
        filename_coverage = (report.get("filename_coverage") or {}).get(stage) or {}
        classification = {
            "LATEST": "目录名排序靠前",
            "SECOND_LATEST": "目录名排序第二",
            "OLDER": "其他正式阶段",
            "SELECTED_STAGE": "指定阶段",
        }.get(str(match.get("classification") or ""), "已发现")
        corner_rows = []
        for view, counts in (filename_coverage.get("corner_counts") or {}).items():
            for label, count in counts.items():
                corner_rows.append({"view": view, "label": label, "count": count})
        stages.append({**match, "stage": stage, "classification_label": classification,
                       "inventory": inventory,
                       "corner_rows": corner_rows})
    latest["report"] = report
    latest["stages"] = stages
    latest["ambiguous_versions"] = report.get("ambiguous_versions") or []
    latest["broken_links"] = report.get("broken_links") or []
    latest["formal_sources"] = report.get("formal_sources") or {}
    return latest


def _is_loopback_request() -> bool:
    remote = request.remote_addr
    if remote:
        try:
            if not ipaddress.ip_address(remote).is_loopback:
                return False
        except ValueError:
            return False
    origin = request.headers.get("Origin")
    return not origin or urlsplit(origin).netloc == request.host


def create_blueprint(registry_path: str | Path, output_dir: str | Path) -> Blueprint:
    registry_file = Path(registry_path).expanduser().resolve()
    output = Path(output_dir).expanduser().resolve()
    blueprint = Blueprint("ip_review", __name__, template_folder="templates")

    def page(selected_id: str = "", message: str = "", error: str = "", run_record: dict[str, Any] | None = None,
             new_ip: bool = False, discovered: list[dict[str, Any]] | None = None,
             raw_root: str = "", active_tab: str = "catalog", discovery_artifacts: bool = False):
        registry = _read_registry(registry_file)
        ips = registry.get("ips") or []
        sidebar_ips = []
        for source_ip in ips:
            sidebar_ip = dict(source_ip)
            sidebar_ip["sidebar_raw_versions"] = sorted(
                list(source_ip.get("raw_versions") or []),
                key=lambda item: _version_sort_key(str(item.get("id") or "")),
            )
            sidebar_ip["sidebar_formal_stages"] = sorted(
                [str(stage) for stage in source_ip.get("formal_nl_stages") or []],
                key=_version_sort_key,
            )
            sidebar_ips.append(sidebar_ip)
        selected = {} if new_ip else next((item for item in ips if item.get("id") == selected_id), ips[0] if ips else {})
        vendors = sorted({str(item.get("vendor") or "未指定 Vendor") for item in ips}, key=str.casefold)
        latest, records = _history(output, str(selected.get("library_id") or "")) if selected else ({}, [])
        raw_root = raw_root or str(registry.get("raw_root") or "")
        if raw_root:
            raw_root = _resolve_registry_path(raw_root, registry_file)
        formal_nl = _formal_nl_latest(output, str(selected.get("library_id") or "")) if selected else {}
        environment_label = (
            "模拟数据 · 不可用于 EDA 或发布"
            if registry.get("environment") == "SIMULATION"
            else "独立服务 · 配置保存在 IP 清单"
        )
        return render_template("workbench.html", ips=ips, sidebar_ips=sidebar_ips, selected=selected, latest=latest,
                               history=records, message=message, error=error, run_record=run_record,
                               checks=sorted(CHECK_NAMES), discovered=discovered or [], raw_root=raw_root,
                               active_tab=active_tab, discovery_artifacts=discovery_artifacts,
                               environment_label=environment_label, formal_nl=formal_nl, vendors=vendors)

    @blueprint.get("/")
    def index():
        try:
            registry = _read_registry(registry_file)
            requested = request.args.get("ip", "")
            ids = {str(item.get("id")) for item in registry.get("ips", [])}
            return page(requested if requested in ids else "", new_ip=request.args.get("new") == "1",
                        active_tab=request.args.get("tab", "catalog"))
        except Exception as exc:
            return render_template("workbench.html", ips=[], sidebar_ips=[], selected={}, latest={}, history=[],
                                   message="", error=str(exc), run_record=None, checks=sorted(CHECK_NAMES),
                                   vendors=[]), 400

    @blueprint.post("/save")
    def save():
        if not _is_loopback_request():
            abort(403)
        try:
            registry = _read_registry(registry_file)
            previous = next((item for item in registry.get("ips", []) if item.get("id") == _text(request.form, "id")), None)
            entry = _entry_from_form(request.form, previous)
            _save_entry(registry, entry)
            _write_registry(registry_file, registry)
            return page(entry["id"], message="IP 配置已保存。", active_tab="review")
        except Exception as exc:
            return page(_text(request.form, "id"), error=str(exc)), 400

    @blueprint.post("/discover")
    def discover():
        if not _is_loopback_request():
            abort(403)
        raw_root = _text(request.form, "raw_root")
        try:
            raw_root = _resolve_registry_path(raw_root, registry_file)
            report = discover_raw_report(raw_root)
            candidates = report["candidates"]
            write_discovery_artifacts(report, output / "discovery")
            message = f"发现 {len(candidates)} 个库候选；状态均为待确认，尚未登记。"
            if report["truncated"]:
                message += " 扫描达到目录上限，结果可能不完整。"
            return page(message=message, discovered=candidates, raw_root=raw_root,
                        active_tab="discover", discovery_artifacts=True)
        except Exception as exc:
            return page(error=str(exc), raw_root=raw_root, active_tab="discover"), 400

    @blueprint.post("/register-discovered")
    def register_discovered():
        if not _is_loopback_request():
            abort(403)
        raw_root = _text(request.form, "raw_root")
        try:
            raw_root = _resolve_registry_path(raw_root, registry_file)
            candidates = discover_raw_report(raw_root)["candidates"]
            selected_ids = set(request.form.getlist("library_ids"))
            by_id = {item["library_id"]: item for item in candidates}
            missing = selected_ids - by_id.keys()
            if missing:
                raise ValueError(f"候选库已变化或不属于该 RAW 根目录：{', '.join(sorted(missing))}")
            if not selected_ids:
                raise ValueError("请至少勾选一个库")
            registry = _read_registry(registry_file)
            registry["raw_root"] = raw_root
            ips = registry.setdefault("ips", [])
            for library_id in sorted(selected_ids):
                candidate = by_id[library_id]
                entry = next((item for item in ips if item.get("library_id") == library_id), None)
                if entry is None:
                    entry = {"id": library_id, "library_id": library_id,
                             "name": candidate["library_name"], "checks": {}}
                    ips.append(entry)
                entry.update({"vendor": candidate["vendor"], "middle_path": candidate["middle_path"],
                              "library_name": candidate["library_name"],
                              "raw_root": candidate["root"], "raw_versions": candidate["versions"]})
            _write_registry(registry_file, registry)
            first_id = sorted(selected_ids)[0]
            return page(first_id, message=f"已登记 {len(selected_ids)} 个库及其 RAW 版本。", active_tab="catalog")
        except Exception as exc:
            return page(error=str(exc), raw_root=raw_root, active_tab="discover"), 400

    @blueprint.get("/discovery-artifact/<artifact_name>")
    def discovery_artifact(artifact_name: str):
        artifact_names = {
            "library.list": "library.list",
            "library_discovery.json": "library_discovery.json",
            "library_discovery.html": "library_discovery.html",
        }
        filename = artifact_names.get(artifact_name)
        if not filename:
            abort(404)
        artifact_path = output / "discovery" / filename
        if not artifact_path.is_file():
            abort(404)
        return send_file(artifact_path, as_attachment=artifact_name.endswith(".json") or artifact_name.endswith(".list"))

    @blueprint.post("/formal-nl")
    def scan_formal_nl():
        if not _is_loopback_request():
            abort(403)
        ip_id = _text(request.form, "id")
        formal_root_input = _text(request.form, "formal_nl_root")
        try:
            registry = _read_registry(registry_file)
            entry = next((item for item in registry.get("ips", []) if item.get("id") == ip_id), None)
            if entry is None:
                abort(404)
            if not formal_root_input:
                raise ValueError("请填写正式 NL 根目录")
            formal_root = _resolve_registry_path(formal_root_input, registry_file)
            entry["formal_nl_root"] = formal_root
            _write_registry(registry_file, registry)
            if not Path(formal_root).is_dir():
                raise NotADirectoryError(f"正式 NL 根目录不存在或不是目录：{formal_root}")
            library_id = str(entry.get("library_id") or entry.get("id") or "")
            ip_name = str(entry.get("library_name") or entry.get("name") or entry.get("id") or "").strip()
            if not ip_name:
                raise ValueError("当前 IP 缺少正式目录匹配名称")
            run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid4().hex[:8]
            run_dir = output / "formal_nl" / _library_dir(library_id) / "runs" / run_id
            run_dir.mkdir(parents=True, exist_ok=False)
            report_json = run_dir / "formal_nl.json"
            report_md = run_dir / "formal_nl.md"
            config_path = run_dir / "formal_nl_config.yml"
            config = {
                "library": {"id": library_id, "root": str(entry.get("raw_root") or ""),
                            "ip_directory_name": ip_name},
                "formal_nl": {"root": formal_root},
                "output": {"report_json": str(report_json), "report_md": str(report_md)},
            }
            if yaml is None:
                raise RuntimeError("运行正式 NL 盘点需要 PyYAML")
            config_path.write_text(yaml.safe_dump(config, allow_unicode=True, sort_keys=False), encoding="utf-8")
            report = run_formal_nl(config_path)
            if not report_json.is_file() or not report_md.is_file():
                raise RuntimeError("正式 NL 脚本未生成预期报告")
            latest = {"generated_at": datetime.now(timezone.utc).isoformat(),
                      "report_status": report.get("report_status", "INCOMPLETE"),
                      "report_json": str(report_json), "report_md": str(report_md)}
            _write_json(run_dir.parent.parent / "latest.json", latest)
            entry["formal_nl_stages"] = [str(item.get("nl_version")) for item in report.get("matches", [])
                                         if item.get("nl_version")]
            entry["formal_nl_scan_at"] = latest["generated_at"]
            entry["formal_nl_report_status"] = latest["report_status"]
            _write_registry(registry_file, registry)
            return page(ip_id, message="正式 NL 只读盘点已完成；结果不代表交付放行。",
                        active_tab="formal-nl")
        except HTTPException:
            raise
        except Exception as exc:
            message = str(exc)
            latest = _formal_nl_latest(output, str(next((item.get("library_id") for item in _read_registry(registry_file).get("ips", []) if item.get("id") == ip_id), "")))
            if latest:
                message += "；上次成功盘点仍保留。"
            return page(ip_id, error=message, active_tab="formal-nl"), 400

    @blueprint.get("/formal-report/<kind>")
    def formal_report(kind: str):
        if kind not in {"json", "md"}:
            abort(404)
        registry = _read_registry(registry_file)
        ip_id = request.args.get("id", "")
        entry = next((item for item in registry.get("ips", []) if item.get("id") == ip_id), None)
        if entry is None:
            abort(404)
        formal_dir = output / "formal_nl" / _library_dir(str(entry.get("library_id") or entry.get("id") or ""))
        latest_path = formal_dir / "latest.json"
        if not latest_path.is_file():
            abort(404)
        latest = _json_read(latest_path)
        report_path = Path(str(latest.get(f"report_{kind}") or "")).resolve()
        if not report_path.is_relative_to(output.resolve()) or not report_path.is_file():
            abort(404)
        return send_file(report_path, as_attachment=True, download_name=report_path.name)

    @blueprint.post("/run")
    def run_selected():
        if not _is_loopback_request():
            abort(403)
        try:
            registry = _read_registry(registry_file)
            previous = next((item for item in registry.get("ips", []) if item.get("id") == _text(request.form, "id")), None)
            entry = _entry_from_form(request.form, previous)
            _save_entry(registry, entry)
            _write_registry(registry_file, registry)
            _validate_for_run(entry)
            reviews, _ = run({"_config_path": str(registry_file), "ips": [entry],
                              "registry_ips": registry.get("ips") or []}, output)
            return page(entry["id"], message="本次选择的检查已运行。", run_record=reviews[0], active_tab="review")
        except Exception as exc:
            return page(_text(request.form, "id"), error=str(exc)), 400

    @blueprint.get("/download")
    def download():
        registry = _read_registry(registry_file)
        library_id = request.args.get("library_id", "")
        review_id = request.args.get("review_id", "")
        if library_id not in {str(item.get("library_id") or item.get("id")) for item in registry.get("ips", [])}:
            abort(404)
        if not re.fullmatch(r"review_[A-Za-z0-9_-]+", review_id):
            abort(404)
        library_dir = output / "libraries" / _library_dir(library_id)
        result_path = library_dir / "runs" / review_id / "review_result.json"
        workbook_path = result_path.parent / "ip_review.xlsx"
        if not result_path.is_file() or not workbook_path.is_file():
            abort(404)
        return send_file(workbook_path, as_attachment=True, download_name=f"{library_id.replace('/', '_')}_{review_id}.xlsx")

    @blueprint.get("/health")
    def health():
        return {"status": "ok"}

    return blueprint


def create_app(registry_path: str | Path, output_dir: str | Path) -> Flask:
    """Create the independent IP-review service without Catalog dependencies."""
    app = Flask(__name__, template_folder="templates", static_folder=str(Path(__file__).parent / "static"))
    app.register_blueprint(create_blueprint(registry_path, output_dir))
    return app


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="启动本机 IP 检查工作台")
    parser.add_argument("--registry", required=True, help="持久 IP 清单 YAML")
    parser.add_argument("--out-dir", required=True, help="每 IP 报告与运行历史目录")
    parser.add_argument("--port", type=int, default=5078)
    args = parser.parse_args(argv)
    app = create_app(args.registry, args.out_dir)
    print(f"IP Review Workbench: http://127.0.0.1:{args.port}/", flush=True)
    app.run(host="127.0.0.1", port=args.port, debug=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
