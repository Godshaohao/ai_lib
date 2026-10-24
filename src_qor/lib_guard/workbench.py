"""Loopback-only UI for the persistent per-IP review registry."""

from __future__ import annotations

import argparse
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

from .review_runner import CHECK_NAMES, _json_read, _library_dir, run


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


def _text(form: Any, key: str) -> str:
    return str(form.get(key, "")).strip()


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
             new_ip: bool = False):
        registry = _read_registry(registry_file)
        ips = registry.get("ips") or []
        selected = {} if new_ip else next((item for item in ips if item.get("id") == selected_id), ips[0] if ips else {})
        latest, records = _history(output, str(selected.get("library_id") or "")) if selected else ({}, [])
        return render_template("workbench.html", ips=ips, selected=selected, latest=latest,
                               history=records, message=message, error=error, run_record=run_record,
                               checks=sorted(CHECK_NAMES))

    @blueprint.get("/")
    def index():
        try:
            registry = _read_registry(registry_file)
            requested = request.args.get("ip", "")
            ids = {str(item.get("id")) for item in registry.get("ips", [])}
            return page(requested if requested in ids else "", new_ip=request.args.get("new") == "1")
        except Exception as exc:
            return render_template("workbench.html", ips=[], selected={}, latest={}, history=[],
                                   message="", error=str(exc), run_record=None, checks=sorted(CHECK_NAMES)), 400

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
            return page(entry["id"], message="IP 配置已保存。")
        except Exception as exc:
            return page(_text(request.form, "id"), error=str(exc)), 400

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
            return page(entry["id"], message="本次选择的检查已运行。", run_record=reviews[0])
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
