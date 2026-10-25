"""Loopback-only UI for the persistent per-IP review registry."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import fcntl
import ipaddress
import json
import logging
import os
from pathlib import Path
import re
from threading import BoundedSemaphore, Lock
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4

try:
    import yaml
except ImportError:  # pragma: no cover - exercised only in intentionally minimal installs
    yaml = None

from flask import Blueprint, Flask, abort, redirect, render_template, request, send_file, url_for
from werkzeug.exceptions import HTTPException

from .review_runner import (CHECK_NAMES, _json_read, _latest_complete_run, _library_dir,
                           refresh_ip_overview, run)
from .raw_discovery import discover_raw_report, write_discovery_artifacts
from . import effective_file_tracker
from .effective_file_tracker import run as run_formal_nl


_REVIEW_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="ip-review")
_REVIEW_TASK_SLOTS = BoundedSemaphore(8)
_SUBMISSION_LOCK = Lock()
_WORKBENCH_SESSION_ID = uuid4().hex
_LOG = logging.getLogger(__name__)


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
    library_ids = [str(item.get("library_id") or "") for item in data["ips"] if isinstance(item, dict)]
    if len(library_ids) != len(set(library_ids)):
        raise ValueError("IP 清单中存在重复 library_id")
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


def _refresh_overview(registry_file: Path, output: Path) -> None:
    """Refresh the read-only HTML projection without affecting task results."""
    try:
        refresh_ip_overview(_read_registry(registry_file), output)
    except Exception:
        _LOG.exception("IP 检查总览刷新失败；任务与检查结果保持不变")


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


def _files_for_selection(root_value: str, suffixes: tuple[str, ...]) -> tuple[list[str], str]:
    root = Path(root_value)
    if not root.is_dir():
        return [], ""
    found: list[str] = []
    visited = 0
    directories = 0
    walk_errors = []

    def record_walk_error(error: OSError) -> None:
        walk_errors.append(error)

    def reasons(*, limited: bool = False) -> str:
        values = []
        if walk_errors:
            values.append("ACCESS_ERROR")
        if limited:
            values.append("LIMIT")
        return "+".join(values)

    for current, dirs, files in os.walk(root, followlinks=False, onerror=record_walk_error):
        directories += 1
        if directories > 200 or len(Path(current).relative_to(root).parts) > 8:
            return found, reasons(limited=True)
        dirs[:] = sorted(name for name in dirs if not (Path(current) / name).is_symlink())
        for name in sorted(files):
            visited += 1
            if name.lower().endswith(suffixes):
                found.append(str(Path(current) / name))
            if visited >= 2000 or len(found) >= 200:
                return found, reasons(limited=True)
    return found, reasons()


def _reason_has(reason: str, marker: str) -> bool:
    return marker in reason.split("+")


def _quick_linked_checks(selected: dict[str, Any], target_version: str, base_version: str,
                         target_lef_choice: str, base_lef_choice: str) -> tuple[dict[str, dict[str, Any]], list[str]]:
    """Build the common Macro/LEF/Liberty review inputs from registered RAW versions."""
    versions = {str(item.get("id") or ""): str(item.get("path") or "")
                for item in selected.get("raw_versions") or []}
    target_root = versions.get(target_version)
    if not target_root or not Path(target_root).is_dir():
        raise ValueError("目标 RAW 版本无效或目录不可访问；请刷新 RAW 登记后重试。")
    target_root_path = Path(target_root).expanduser().resolve()
    target_lefs, target_lefs_truncated = _files_for_selection(str(target_root_path), (".lef", ".lef.gz"))
    liberty_files, liberty_truncated = _files_for_selection(str(target_root_path), (".lib", ".lib.gz"))
    if target_lefs_truncated:
        reason = "；".join(value for marker, value in (
            ("ACCESS_ERROR", "存在目录不可读"), ("LIMIT", "超过工作台枚举上限"))
            if _reason_has(target_lefs_truncated, marker))
        raise ValueError(f"目标版本 LEF 文件列表不完整（{reason}），无法保证联动核查范围；请检查权限或缩小版本目录后重试。")
    if liberty_truncated:
        reason = "；".join(value for marker, value in (
            ("ACCESS_ERROR", "存在目录不可读"), ("LIMIT", "超过工作台枚举上限"))
            if _reason_has(liberty_truncated, marker))
        raise ValueError(f"Liberty 文件列表不完整（{reason}），无法保证 Corner 核查范围；请检查权限或缩小版本目录后重试。")
    checks: dict[str, dict[str, Any]] = {
        "macro_index": {"root": str(target_root_path), "version": target_version,
                        "library_id": str(selected.get("library_id") or selected.get("id") or "")}
    }
    notes = [f"Macro / View：扫描目标版本下支持的文件；LEF：{len(target_lefs)} 个；Liberty：{len(liberty_files)} 个。"]

    def choose(value: str, choices: list[str], label: str) -> str:
        if value:
            resolved = str(Path(value).expanduser().resolve())
            if resolved not in choices:
                raise ValueError(f"所选{label}不属于当前 RAW 版本，请重新载入版本文件。")
            return resolved
        return choices[0] if len(choices) == 1 else ""

    target_lef = choose(target_lef_choice, target_lefs, "目标 LEF")
    base_lef = ""
    if base_version:
        base_root = versions.get(base_version)
        if not base_root or not Path(base_root).is_dir():
            raise ValueError("基准 RAW 版本无效或目录不可访问；请刷新 RAW 登记后重试。")
        base_root_path = Path(base_root).expanduser().resolve()
        base_lefs, base_lefs_truncated = _files_for_selection(base_root, (".lef", ".lef.gz"))
        if base_lefs_truncated:
            reason = "；".join(value for marker, value in (
                ("ACCESS_ERROR", "存在目录不可读"), ("LIMIT", "超过工作台枚举上限"))
                if _reason_has(base_lefs_truncated, marker))
            raise ValueError(f"基准版本 LEF 文件列表不完整（{reason}），无法保证配对；请检查权限或缩小版本目录后重试。")
        base_lef = choose(base_lef_choice, base_lefs, "基准 LEF")
        if not target_lef and len(target_lefs) > 1:
            base_by_relative: dict[str, list[str]] = {}
            for old in base_lefs:
                relative = Path(old).relative_to(base_root_path).as_posix()
                base_by_relative.setdefault(relative, []).append(old)
            common = [path for path in target_lefs
                      if len(base_by_relative.get(Path(path).relative_to(target_root_path).as_posix(), [])) == 1]
            if len(common) == 1:
                target_lef = common[0]
                relative = Path(target_lef).relative_to(target_root_path).as_posix()
                if not base_lef:
                    base_lef = base_by_relative[relative][0]
        if not target_lef and len(target_lefs) == 1:
            target_lef = target_lefs[0]
        if target_lef and not base_lef:
            relative = Path(target_lef).relative_to(target_root_path).as_posix()
            matches = [old for old in base_lefs if
                       Path(old).relative_to(base_root_path).as_posix() == relative]
            if len(matches) == 1:
                base_lef = matches[0]
        if target_lef and base_lef:
            checks["lef_review"] = {"old_file": base_lef, "new_file": target_lef}
            notes.append("LEF：已按相同相对路径配对基准与目标文件，执行差异核查。")
        elif target_lef:
            notes.append("LEF：未找到唯一基准配对；执行目标 LEF 接口核查，不生成 LEF 差异结论。")
        elif target_lefs:
            raise ValueError("目标版本有多个 LEF 且无法唯一配对，请明确选择目标和基准文件后再运行。")
        else:
            notes.append("LEF：基准和目标版本均未发现 LEF，本次不执行 LEF 检查。")
    elif target_lef:
        notes.append("LEF：没有选择基准版本；以目标 LEF 做接口核查，不生成版本差异结论。")
    elif target_lefs:
        raise ValueError("目标版本有多个 LEF，请明确选择一个目标 LEF 后再运行联动核查。")
    else:
        notes.append("LEF：目标版本没有发现 LEF，本次不执行接口核查。")

    if target_lef and liberty_files:
        liberty_spec: dict[str, Any] = {"liberty_files": liberty_files}
        if "lef_review" not in checks:
            liberty_spec["lef_file"] = target_lef
        checks["lef_liberty_check"] = liberty_spec
    elif target_lef:
        notes.append("Liberty：目标版本没有发现 .lib/.lib.gz，本次不执行 LEF–Liberty 核查。")
    return checks, notes


def _formal_discovery_status(report: dict[str, Any]) -> str:
    if not report.get("matches"):
        return "NOT_FOUND"
    if report.get("broken_links") or any(item.get("status") != "COMPLETE" for item in
                                          (report.get("inventories") or {}).values()):
        return "PARTIAL"
    return "DISCOVERED"


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
                              "lef_library_id": "ll_lef_library_id", "lef_file": "ll_lef_file"},
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
        for key in ("vendor", "middle_path", "library_name"):
            if key in form:
                entry[key] = _text(form, key)
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
            ((checks.get("lef_review") is not None) or spec.get("lef_file") or
             (spec.get("lef_analysis_json") and spec.get("lef_library_id"))))),
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


def _task_paths(output: Path, library_id: str, task_id: str) -> tuple[Path, Path]:
    library_dir = output / "libraries" / _library_dir(library_id)
    return library_dir / "tasks" / f"{task_id}.json", library_dir / "latest_attempt.json"


def _acquire_library_lock(output: Path, library_id: str):
    library_dir = output / "libraries" / _library_dir(library_id)
    library_dir.mkdir(parents=True, exist_ok=True)
    handle = (library_dir / ".review.lock").open("a+")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return handle
    except BlockingIOError:
        handle.close()
        return None


def _release_library_lock(handle) -> None:
    if handle is None:
        return
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    finally:
        handle.close()


def _update_task(task_path: Path, latest_attempt_path: Path, task: dict[str, Any]) -> None:
    try:
        latest = _json_read(latest_attempt_path)
    except (OSError, ValueError, json.JSONDecodeError):
        latest = {}
    if task.get("status") == "QUEUED" or not latest or latest.get("task_id") == task.get("task_id"):
        _write_json(latest_attempt_path, task)
    _write_json(task_path, task)


def _task_event(task: dict[str, Any], phase: str, message: str) -> dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    events = list(task.get("events") or [])
    events.append({"at": now, "message": message})
    return {**task, "phase": phase, "progress_message": message, "updated_at": now,
            "events": events[-12:]}


def _interrupt_stale_task(task_path: Path, latest_attempt_path: Path, task: dict[str, Any]) -> dict[str, Any]:
    if task.get("status") not in {"QUEUED", "RUNNING"} or task.get("worker_session") == _WORKBENCH_SESSION_ID:
        return task
    interrupted = _task_event(
        {**task, "status": "INTERRUPTED", "execution_status": "INTERRUPTED",
         "finished_at": datetime.now(timezone.utc).isoformat(),
         "error": "工作台进程重启，任务未自动恢复；请确认输入后重新提交。"},
        "已中断", "工作台进程重启，任务未自动恢复。请确认输入后重新提交。")
    _update_task(task_path, latest_attempt_path, interrupted)
    return interrupted


def _formal_nl_latest(output: Path, library_id: str) -> dict[str, Any]:
    formal_dir = output / "formal_nl" / _library_dir(library_id)
    latest_path = formal_dir / "latest.json"
    check_path = formal_dir / "latest_check.json"
    latest = {}
    report = {}
    latest_is_single_stage = False
    for pointer_path, is_single_stage in ((latest_path, False), (check_path, True)):
        if not pointer_path.is_file():
            continue
        try:
            candidate = _json_read(pointer_path)
            report_path = Path(str(candidate.get("report_json") or "")).resolve()
            if not report_path.is_relative_to(output.resolve()) or not report_path.is_file():
                continue
            candidate_report = _json_read(report_path)
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        latest, report, latest_is_single_stage = candidate, candidate_report, is_single_stage
        if not is_single_stage:
            break
    if not latest:
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
    if latest_is_single_stage:
        latest["latest_check"] = dict(latest)
        if len(stages) == 1:
            latest["latest_check_stage"] = stages[0]["stage"]
    latest["report"] = report
    latest["stages"] = stages
    latest["ambiguous_versions"] = report.get("ambiguous_versions") or []
    latest["broken_links"] = report.get("broken_links") or []
    latest["formal_sources"] = report.get("formal_sources") or {}
    if not latest_is_single_stage and check_path.is_file():
        check = _json_read(check_path)
        check_report_path = Path(str(check.get("report_json") or "")).resolve()
        if check_report_path.is_relative_to(formal_dir.resolve()) and check_report_path.is_file():
            latest["latest_check"] = check
            check_report = _json_read(check_report_path)
            matches = check_report.get("matches") or []
            if len(matches) == 1:
                latest["latest_check_stage"] = matches[0].get("nl_version")
    return latest


def _formal_nl_directory_overview(ips: list[dict[str, Any]], registry_file: Path) -> dict[str, Any]:
    """Read each configured formal stage once and summarize its flattened links."""
    stage_roots: dict[Path, str] = {}
    warnings: list[str] = []
    stage_pattern = re.compile(r"^lib_NL[A-Za-z0-9_.-]+$", re.IGNORECASE)
    for ip in ips:
        root_value = str(ip.get("formal_nl_root") or "").strip()
        if not root_value:
            continue
        root = Path(_resolve_registry_path(root_value, registry_file))
        if not root.is_dir():
            warnings.append(f"{ip.get('id') or ip.get('library_id') or '未命名 IP'}：正式目录不存在 {root}")
            continue

        candidates: list[tuple[str, Path]] = []
        if root.name.casefold() == "ip" and stage_pattern.fullmatch(root.parent.name):
            candidates.append((root.parent.name, root))
        elif stage_pattern.fullmatch(root.name) and (root / "IP").is_dir():
            candidates.append((root.name, root / "IP"))

        for stage in ip.get("formal_nl_stages") or []:
            stage_name = str(stage)
            if not stage_pattern.fullmatch(stage_name):
                continue
            candidate = root / stage_name / "IP"
            if candidate.is_dir():
                candidates.append((stage_name, candidate))

        try:
            children = list(root.iterdir())
        except OSError as exc:
            warnings.append(f"{ip.get('id') or ip.get('library_id') or '未命名 IP'}：无法读取目录 {root}（{exc}）")
            children = []
        for child in children:
            candidate = child / "IP"
            if stage_pattern.fullmatch(child.name) and candidate.is_dir():
                candidates.append((child.name, candidate))

        for stage, candidate in candidates:
            stage_roots.setdefault(candidate.resolve(), stage)

    if not stage_roots:
        return {
            "status": "NOT_FOUND", "stages": [], "stage_labels": [], "libraries": [], "files": [],
            "view_counts": {}, "stage_count": 0, "library_count": 0,
            "registered_library_count": 0, "unregistered_library_count": 0,
            "raw_version_count": 0, "file_count": 0, "unmapped_file_count": 0,
            "issues": [], "warnings": warnings,
        }

    registered_versions: list[tuple[Path, dict[str, Any]]] = []
    registered_roots: list[tuple[Path, dict[str, Any]]] = []
    registered_keys: set[tuple[str, str]] = set()
    for ip in ips:
        vendor = str(ip.get("vendor") or "").strip()
        library = str(ip.get("library_name") or ip.get("name") or "").strip()
        if not vendor or not library:
            library_id = str(ip.get("library_id") or ip.get("id") or "")
            vendor, _, library = library_id.partition(".")
        identity = {
            "vendor": vendor or "未识别 Vendor",
            "library_name": library or str(ip.get("id") or "未识别 IP"),
            "library_id": str(ip.get("library_id") or ip.get("id") or ""),
        }
        registered_keys.add((identity["vendor"].casefold(), identity["library_name"].casefold()))
        raw_root_value = str(ip.get("raw_root") or "").strip()
        if raw_root_value:
            registered_roots.append((Path(_resolve_registry_path(raw_root_value, registry_file)), identity))
        for version in ip.get("raw_versions") or []:
            version_path = str(version.get("path") or "").strip()
            version_id = str(version.get("id") or "").strip()
            if version_path:
                registered_versions.append((Path(_resolve_registry_path(version_path, registry_file)),
                                            {**identity, "raw_version": version_id}))

    raw_root_value = str(_read_registry(registry_file).get("raw_root") or "").strip()
    common_raw_root = (Path(_resolve_registry_path(raw_root_value, registry_file))
                       if raw_root_value else None)

    def source_identity(source_value: str) -> dict[str, str] | None:
        source = Path(source_value)
        for version_root, identity in sorted(registered_versions, key=lambda item: len(item[0].parts), reverse=True):
            try:
                source.relative_to(version_root)
                return {**identity, "registration_status": "已登记"}
            except ValueError:
                continue
        for library_root, identity in sorted(registered_roots, key=lambda item: len(item[0].parts), reverse=True):
            try:
                relative = source.relative_to(library_root)
            except ValueError:
                continue
            return {**identity, "raw_version": relative.parts[0] if relative.parts else "未标版本",
                    "registration_status": "已登记"}
        if common_raw_root is not None:
            try:
                relative = source.relative_to(common_raw_root)
            except ValueError:
                return None
            if len(relative.parts) >= 4:
                vendor, library, version = relative.parts[:3]
                key = (vendor.casefold(), library.casefold())
                return {"vendor": vendor, "library_name": library,
                        "library_id": f"{vendor}.{library}", "raw_version": version,
                        "registration_status": "已登记" if key in registered_keys else "未登记"}
        return None

    stages: list[dict[str, Any]] = []
    library_rows: dict[tuple[str, str], dict[str, Any]] = {}
    file_rows: list[dict[str, str]] = []
    issue_rows: list[dict[str, str]] = []
    view_counts: dict[str, int] = {}
    version_keys: set[tuple[str, str, str]] = set()
    unmapped_file_count = 0
    for stage_root, stage_name in sorted(
            stage_roots.items(), key=lambda item: (_version_sort_key(item[1]), str(item[0]).casefold())):
        inventory = effective_file_tracker.inventory_for_ip_target(stage_root)
        stage_libraries: dict[tuple[str, str], dict[str, Any]] = {}
        for view, count in (inventory.get("view_counts") or {}).items():
            view_counts[view] = view_counts.get(view, 0) + int(count)
        for file in inventory.get("files") or []:
            identity = source_identity(str(file.get("source_path") or ""))
            row = {**file, "stage": stage_name}
            if identity:
                row.update(identity)
                key = (identity["vendor"].casefold(), identity["library_name"].casefold())
                raw_version = identity.get("raw_version") or "未标版本"
                version_keys.add((*key, raw_version))
                for target in (library_rows, stage_libraries):
                    item = target.setdefault(key, {
                        "vendor": identity["vendor"], "library_name": identity["library_name"],
                        "library_id": identity.get("library_id", ""),
                        "registration_status": identity["registration_status"],
                        "versions": set(), "stages": set(), "file_count": 0, "view_counts": {},
                    })
                    item["versions"].add(raw_version)
                    item["stages"].add(stage_name)
                    item["file_count"] += 1
                    view = str(file.get("view") or "other")
                    item["view_counts"][view] = item["view_counts"].get(view, 0) + 1
            else:
                unmapped_file_count += 1
                row["vendor"] = "无法归属"
                row["library_name"] = "无法归属"
                row["raw_version"] = "无法识别"
                row["registration_status"] = "来源不在登记 RAW 路径内"
            file_rows.append(row)
        for issue in inventory.get("issues") or []:
            issue_rows.append({"stage": stage_name, **issue})
        stages.append({
            "stage": stage_name, "root": str(stage_root),
            "file_count": inventory.get("file_count", 0),
            "unique_source_count": inventory.get("unique_source_count", 0),
            "view_counts": inventory.get("view_counts") or {},
            "library_count": len(stage_libraries),
            "status": inventory.get("status", "INCOMPLETE"),
        })

    def finish_library(row: dict[str, Any]) -> dict[str, Any]:
        return {**row, "versions": sorted(row["versions"], key=_version_sort_key),
                "stages": sorted(row["stages"], key=_version_sort_key),
                "view_counts": dict(sorted(row["view_counts"].items()))}

    libraries = [finish_library(row) for row in library_rows.values()]
    libraries.sort(key=lambda row: (row["vendor"].casefold(), row["library_name"].casefold()))
    file_rows.sort(key=lambda row: (row.get("stage", ""), row.get("view", ""), row.get("relative_path", "")))
    return {
        "status": "INCOMPLETE" if issue_rows or warnings or unmapped_file_count else "COMPLETE",
        "stages": stages, "stage_labels": sorted({row["stage"] for row in stages}, key=_version_sort_key),
        "libraries": libraries, "files": file_rows,
        "view_counts": dict(sorted(view_counts.items())), "stage_count": len(stages),
        "library_count": len(libraries),
        "registered_library_count": sum(row["registration_status"] == "已登记" for row in libraries),
        "unregistered_library_count": sum(row["registration_status"] == "未登记" for row in libraries),
        "raw_version_count": len(version_keys), "file_count": sum(row["file_count"] for row in stages),
        "unmapped_file_count": unmapped_file_count, "issues": issue_rows, "warnings": warnings,
    }


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
    _refresh_overview(registry_file, output)
    blueprint = Blueprint("ip_review", __name__, template_folder="templates")

    def page(selected_id: str = "", message: str = "", error: str = "", run_record: dict[str, Any] | None = None,
             new_ip: bool = False, discovered: list[dict[str, Any]] | None = None,
             raw_root: str = "", active_tab: str = "catalog", discovery_artifacts: bool = False,
             identity_conflicts: list[str] | None = None, partial_discovery: bool = False,
             discovery_warnings: list[str] | None = None):
        registry = _read_registry(registry_file)
        ips = registry.get("ips") or []
        catalog_ips = []
        sidebar_ips = []
        for source_ip in ips:
            sidebar_ip = dict(source_ip)
            sidebar_ip.setdefault("vendor", "未指定 Vendor")
            library_id = str(source_ip.get("library_id") or source_ip.get("id") or "")
            latest_success, _ = _history(output, library_id) if library_id else ({}, [])
            latest_complete, _ = _latest_complete_run(
                output / "libraries" / _library_dir(library_id)) if library_id else ({}, None)
            if latest_success.get("execution_status") != "COMPLETE":
                latest_success = latest_complete
            if library_id:
                library_dir = output / "libraries" / _library_dir(library_id)
                workbook_pointer_path = library_dir / "latest_workbook.json"
                if workbook_pointer_path.is_file():
                    try:
                        workbook_review_id = str(_json_read(workbook_pointer_path).get("review_id") or "")
                        if re.fullmatch(r"review_[A-Za-z0-9_-]+", workbook_review_id):
                            workbook_result_path = library_dir / "runs" / workbook_review_id / "review_result.json"
                            if workbook_result_path.is_file():
                                workbook_result = _json_read(workbook_result_path)
                                if workbook_result.get("execution_status") == "COMPLETE":
                                    latest_success = workbook_result
                    except (OSError, ValueError, json.JSONDecodeError):
                        pass
            _, attempt_path = _task_paths(output, library_id, "") if library_id else (Path(), Path())
            try:
                latest_attempt = _json_read(attempt_path) if attempt_path.is_file() else {}
            except (OSError, ValueError, json.JSONDecodeError):
                latest_attempt = {}
            if library_id and latest_attempt.get("task_id"):
                task_path, latest_attempt_path = _task_paths(output, library_id, str(latest_attempt["task_id"]))
                latest_attempt = _interrupt_stale_task(task_path, latest_attempt_path, latest_attempt)
            catalog_ip = dict(source_ip)
            catalog_ip["latest_success"] = latest_success
            catalog_ip["latest_attempt"] = latest_attempt
            catalog_ip["latest_quality_label"] = str(
                ((latest_success.get("summary") or {}).get("quality_assessment") or {}).get("label") or
                latest_success.get("quality_label") or "未形成质量结论"
            )
            if library_id:
                stable_workbook = output / "libraries" / _library_dir(library_id) / "latest.xlsx"
                catalog_ip["latest_excel_url"] = (
                    url_for("ip_review.review_artifact",
                            artifact=f"libraries/{_library_dir(library_id)}/latest.xlsx")
                    if stable_workbook.is_file() else "")
            catalog_ips.append(catalog_ip)
            sidebar_ip["sidebar_raw_count"] = len(source_ip.get("raw_versions") or [])
            sidebar_ip["sidebar_formal_count"] = len(source_ip.get("formal_nl_stages") or [])
            attempt_status = str(latest_attempt.get("status") or "")
            sidebar_ip["sidebar_task_label"] = {
                "QUEUED": "排队中", "RUNNING": "运行中", "COMPLETE": "最近任务完成",
                "FAILED": "最近任务失败", "INTERRUPTED": "任务中断",
            }.get(attempt_status, "尚无检查")
            quality_status = str(latest_attempt.get("quality_status") or "")
            quality_labels = {
                "INCOMPLETE": "检查未完整", "REVIEW_REQUIRED": "存在待核实项",
                "ISSUES_FOUND": "发现已确认不一致", "CHANGES_FOUND": "发现已确认变化",
                "NO_FINDINGS_WITHIN_SCOPE": "本次范围未发现问题", "NOT_ASSESSED": "未形成质量结论",
            }
            sidebar_ip["sidebar_quality_label"] = (
                quality_labels.get(quality_status) if quality_status else catalog_ip["latest_quality_label"]
            )
            sidebar_ips.append(sidebar_ip)
        selected = {} if new_ip else next((item for item in ips if item.get("id") == selected_id), ips[0] if ips else {})
        chosen_version = request.args.get("raw_version", "") if request.method == "GET" else ""
        if selected and chosen_version:
            versions = [item for item in selected.get("raw_versions") or [] if str(item.get("id")) == chosen_version]
            if len(versions) == 1:
                selected = dict(selected)
                selected["raw_version"] = chosen_version
                selected["formal_stage"] = ""
                selected["checks"] = {}
        vendors = sorted({str(item.get("vendor") or "未指定 Vendor") for item in ips}, key=str.casefold)
        latest, records = _history(output, str(selected.get("library_id") or "")) if selected else ({}, [])
        latest_attempt = {}
        if selected:
            _, attempt_path = _task_paths(output, str(selected.get("library_id") or ""), "")
            if attempt_path.is_file():
                try:
                    latest_attempt = _json_read(attempt_path)
                except (OSError, ValueError, json.JSONDecodeError):
                    latest_attempt = {}
            if latest_attempt.get("task_id"):
                task_path, latest_attempt_path = _task_paths(
                    output, str(selected.get("library_id") or ""), str(latest_attempt["task_id"]))
                latest_attempt = _interrupt_stale_task(task_path, latest_attempt_path, latest_attempt)
        raw_root = raw_root or str(registry.get("raw_root") or "")
        if raw_root:
            raw_root = _resolve_registry_path(raw_root, registry_file)
        formal_nl = _formal_nl_latest(output, str(selected.get("library_id") or "")) if selected else {}
        formal_overview = _formal_nl_directory_overview(ips, registry_file)
        raw_choices = {str(item.get("id")): str(item.get("path")) for item in selected.get("raw_versions") or []}
        base_version = request.args.get("base_raw_version", "") if request.method == "GET" else ""
        base_root = raw_choices.get(base_version, "")
        target_root = raw_choices.get(chosen_version, "")
        old_lefs, old_limit = _files_for_selection(base_root, (".lef", ".lef.gz")) if base_root else ([], "")
        new_lefs, new_limit = _files_for_selection(target_root, (".lef", ".lef.gz")) if target_root else ([], "")
        liberty_files, lib_limit = _files_for_selection(target_root, (".lib", ".lib.gz")) if target_root else ([], "")
        file_choice_reasons = [(label, reason) for label, reason in (
            ("基准 LEF", old_limit), ("目标 LEF", new_limit), ("Liberty", lib_limit)) if reason]
        file_choices_notice = ""
        if file_choice_reasons:
            labels = "、".join(label for label, _ in file_choice_reasons)
            causes = []
            if any(_reason_has(reason, "ACCESS_ERROR") for _, reason in file_choice_reasons):
                causes.append("部分目录不可读")
            if any(_reason_has(reason, "LIMIT") for _, reason in file_choice_reasons):
                causes.append("达到工作台枚举上限")
            file_choices_notice = f"{labels} 文件清单不完整（{'；'.join(causes)}）；请检查目录权限，或直接填写完整文件路径。"
        quick_checks, quick_notes = ({}, [])
        if chosen_version:
            try:
                quick_checks, quick_notes = _quick_linked_checks(
                    selected, chosen_version, base_version, "", "")
            except ValueError as exc:
                quick_notes = [str(exc)]
        default_target_lef = (
            (quick_checks.get("lef_review") or {}).get("new_file") or
            (quick_checks.get("lef_liberty_check") or {}).get("lef_file") or ""
        )
        default_base_lef = (quick_checks.get("lef_review") or {}).get("old_file") or ""
        chosen_stage = request.args.get("formal_stage", "") if request.method == "GET" else ""
        check = formal_nl.get("latest_check") or {}
        if selected and chosen_stage and check.get("report_status") == "COMPLETE":
            check_report = _json_read(Path(check["report_json"]))
            matches = check_report.get("matches") or []
            if check_report.get("formal_scope") == "SINGLE_STAGE" and len(matches) == 1 and matches[0].get("nl_version") == chosen_stage:
                selected = dict(selected)
                selected["formal_stage"] = chosen_stage
                selected["raw_version"] = ""
                selected["checks"] = {"formal_nl": {"report_json": check["report_json"]}}
        environment_label = (
            "模拟数据 · 不可用于 EDA 或发布"
            if registry.get("environment") == "SIMULATION"
            else "独立服务 · 配置保存在 IP 清单"
        )
        library_id = str(selected.get("library_id") or "") if selected else ""
        library_dir = output / "libraries" / _library_dir(library_id) if library_id else None
        workbook_review_id = ""
        workbook_pointer_path = library_dir / "latest_workbook.json" if library_dir else None
        if workbook_pointer_path is not None and workbook_pointer_path.is_file():
            try:
                pointer_id = str(_json_read(workbook_pointer_path).get("review_id") or "")
            except (OSError, ValueError, json.JSONDecodeError):
                pointer_id = ""
            if (re.fullmatch(r"review_[A-Za-z0-9_-]+", pointer_id)
                    and (library_dir / "runs" / pointer_id / "ip_review.xlsx").is_file()):
                workbook_review_id = pointer_id
        if not workbook_review_id:
            workbook_review_id = next((
                str(record.get("review_id") or "") for record in records
                if record.get("review_id") and record.get("execution_status") == "COMPLETE"
                and library_dir is not None
                and (library_dir / "runs" / str(record["review_id"]) / "ip_review.xlsx").is_file()
            ), "")
        if not workbook_review_id and latest.get("review_id") and library_dir is not None:
            pointer_workbook = library_dir / "runs" / str(latest["review_id"]) / "ip_review.xlsx"
            if pointer_workbook.is_file():
                workbook_review_id = str(latest["review_id"])
        latest_display = latest
        if workbook_review_id and str(latest.get("review_id") or "") != workbook_review_id:
            latest_display = next(
                (record for record in records if str(record.get("review_id") or "") == workbook_review_id),
                {"review_id": workbook_review_id},
            )
        stable_workbook = library_dir / "latest.xlsx" if library_dir else None
        stable_workbook_url = (
            url_for("ip_review.review_artifact", artifact=f"libraries/{_library_dir(library_id)}/latest.xlsx")
            if stable_workbook is not None and (stable_workbook.is_file() or workbook_review_id) else "")
        if selected:
            selected = dict(selected)
            selected["latest_excel_url"] = stable_workbook_url
        latest_workbook_url = (
            stable_workbook_url if stable_workbook_url else
            (url_for("ip_review.download", library_id=library_id, review_id=workbook_review_id)
             if workbook_review_id else "")
        )
        task_review_id = str((run_record or latest_attempt).get("review_id") or "")
        task_workbook_url = ""
        if task_review_id and re.fullmatch(r"review_[A-Za-z0-9_-]+", task_review_id) and library_dir is not None:
            task_workbook_path = library_dir / "runs" / task_review_id / "ip_review.xlsx"
            if task_workbook_path.is_file():
                task_workbook_url = url_for(
                    "ip_review.review_artifact",
                    artifact=f"libraries/{_library_dir(library_id)}/runs/{task_review_id}/ip_review.xlsx")
        review_overview_path = output / "ip_checks" / "index.html"
        review_overview_url = (url_for("ip_review.review_artifact", artifact="ip_checks/index.html")
                               if review_overview_path.is_file() else "")
        return render_template("workbench.html", ips=catalog_ips, sidebar_ips=sidebar_ips, selected=selected, latest=latest_display,
                               history=records, latest_attempt=latest_attempt,
                               message=message, error=error, run_record=run_record,
                               checks=sorted(CHECK_NAMES), discovered=discovered or [], raw_root=raw_root,
                               active_tab=active_tab, discovery_artifacts=discovery_artifacts,
                               environment_label=environment_label, formal_nl=formal_nl, vendors=vendors,
                               identity_conflicts=identity_conflicts or [], partial_discovery=partial_discovery,
                               formal_overview=formal_overview,
                               discovery_warnings=discovery_warnings or [],
                               registered_ids={str(item.get("library_id") or "") for item in ips},
                               selected_raw_version=chosen_version, base_raw_version=base_version,
                               old_lefs=old_lefs, new_lefs=new_lefs, liberty_choices=liberty_files,
                               default_target_lef=default_target_lef, default_base_lef=default_base_lef,
                               quick_checks=quick_checks, quick_notes=quick_notes,
                               latest_workbook_url=latest_workbook_url,
                               task_workbook_url=task_workbook_url,
                               review_overview_url=review_overview_url,
                               file_choices_limited=bool(file_choice_reasons),
                               file_choices_notice=file_choices_notice)

    @blueprint.get("/")
    def index():
        try:
            registry = _read_registry(registry_file)
            requested = request.args.get("ip", "")
            ids = {str(item.get("id")) for item in registry.get("ips", [])}
            message = "检查任务已提交到后台；可离开页面，完成后在运行记录中查看。" \
                if request.args.get("submitted") == "1" else ""
            default_tab = "review" if ids or request.args.get("new") == "1" else "discover"
            requested_tab = request.args.get("tab") or default_tab
            if requested_tab not in {"review", "catalog", "discover", "formal-nl"}:
                requested_tab = default_tab
            return page(requested if requested in ids else "", new_ip=request.args.get("new") == "1",
                        active_tab=requested_tab, message=message)
        except Exception as exc:
            return render_template("workbench.html", ips=[], sidebar_ips=[], selected={}, latest={}, history=[],
                                   message="", error=str(exc), run_record=None, checks=sorted(CHECK_NAMES),
                                   vendors=[], identity_conflicts=[], partial_discovery=False,
                                   selected_raw_version="", base_raw_version="", old_lefs=[], new_lefs=[],
                                   liberty_choices=[], file_choices_limited=False), 400

    @blueprint.post("/save")
    def save():
        if not _is_loopback_request():
            abort(403)
        try:
            registry = _read_registry(registry_file)
            previous = next((item for item in registry.get("ips", []) if item.get("id") == _text(request.form, "id")), None)
            entry = _entry_from_form(request.form, previous)
            if previous and entry["library_id"] != previous["library_id"]:
                raise ValueError("库标识与已登记记录不一致")
            if any(item.get("library_id") == entry["library_id"] and item.get("id") != entry["id"]
                   for item in registry.get("ips", [])):
                raise ValueError("库标识已被其他 IP 使用")
            _save_entry(registry, entry)
            _write_registry(registry_file, registry)
            _refresh_overview(registry_file, output)
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
            message = f"扫描完成：识别到 {len(candidates)} 个库；请筛选后直接登记或更新登记信息。"
            if report["partial_discovery"]:
                warnings = report.get("warnings") or ["发现范围不完整；请查看扫描产物中的告警明细。"]
                message += " " + " ".join(str(warning) for warning in warnings)
            if report["identity_conflicts"]:
                message += " 存在库标识冲突，冲突库不可登记。"
            return page(message=message, discovered=candidates, raw_root=raw_root,
                        identity_conflicts=report["identity_conflicts"],
                        partial_discovery=report["partial_discovery"],
                        discovery_warnings=report.get("warnings") or [],
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
            discovery = discover_raw_report(raw_root)
            candidates = discovery["candidates"]
            selected_ids = set(request.form.getlist("library_ids"))
            register_one = _text(request.form, "register_one")
            if register_one:
                selected_ids.add(register_one)
            conflicts = selected_ids.intersection(discovery["identity_conflicts"])
            if conflicts:
                raise ValueError(f"库标识冲突，不能登记：{', '.join(sorted(conflicts))}")
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
                if entry is not None and entry.get("raw_root") and Path(entry["raw_root"]).resolve() != Path(candidate["root"]).resolve():
                    raise ValueError(f"库 {library_id} 已登记其他 RAW 根目录；请先核对库身份")
                if entry is None:
                    entry = {"id": library_id, "library_id": library_id,
                             "name": candidate["library_name"], "checks": {}}
                    ips.append(entry)
                entry.update({"vendor": candidate["vendor"], "middle_path": candidate["middle_path"],
                              "library_name": candidate["library_name"],
                              "raw_root": candidate["root"], "raw_versions": candidate["versions"]})
            _write_registry(registry_file, registry)
            _refresh_overview(registry_file, output)
            first_id = sorted(selected_ids)[0]
            return page(first_id, message=f"已登记 {len(selected_ids)} 个库及其 RAW 版本。", active_tab="catalog")
        except Exception as exc:
            return page(error=str(exc), raw_root=raw_root, active_tab="discover"), 400

    @blueprint.post("/unregister")
    def unregister():
        if not _is_loopback_request():
            abort(403)
        ip_id = _text(request.form, "id")
        if not ip_id:
            abort(400)
        registry = _read_registry(registry_file)
        ips = registry.get("ips") or []
        if not any(str(item.get("id") or "") == ip_id for item in ips):
            abort(404)
        registry["ips"] = [item for item in ips if str(item.get("id") or "") != ip_id]
        _write_registry(registry_file, registry)
        _refresh_overview(registry_file, output)
        return page(message="已移除库登记；RAW 文件和历史检查结果均未删除。", active_tab="catalog")

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
        if artifact_name in {"library.list", "library_discovery.html"}:
            report_path = output / "discovery" / "library_discovery.json"
            if not report_path.is_file():
                abort(404)
            report = _json_read(report_path)
            requested_format = "list" if artifact_name == "library.list" else "html"
            write_discovery_artifacts(report, report_path.parent, human_formats={requested_format})
        if not artifact_path.is_file():
            abort(404)
        return send_file(artifact_path, as_attachment=artifact_name.endswith(".json") or artifact_name.endswith(".list"))

    @blueprint.post("/formal-nl")
    def scan_formal_nl():
        if not _is_loopback_request():
            abort(403)
        ip_id = _text(request.form, "id")
        formal_root_input = _text(request.form, "formal_nl_root")
        stage = _text(request.form, "formal_stage")
        try:
            registry = _read_registry(registry_file)
            entry = next((item for item in registry.get("ips", []) if item.get("id") == ip_id), None)
            if entry is None:
                abort(404)
            if not formal_root_input:
                raise ValueError("请填写正式 NL 根目录")
            formal_root = _resolve_registry_path(formal_root_input, registry_file)
            if not Path(formal_root).is_dir():
                raise NotADirectoryError(f"正式 NL 根目录不存在或不是目录：{formal_root}")
            scan_root = formal_root
            if stage:
                if not re.fullmatch(r"lib_NL[A-Za-z0-9_.-]+", stage):
                    raise ValueError("正式阶段名称无效")
                configured_root = Path(formal_root)
                if (configured_root.name.casefold() == "ip"
                        and configured_root.parent.name.casefold() == stage.casefold()):
                    stage_root = configured_root
                else:
                    stage_root = configured_root / stage / "IP"
                if not stage_root.is_dir():
                    raise NotADirectoryError(f"正式阶段 IP 目录不存在：{stage_root}")
                scan_root = str(stage_root)
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
                "formal_nl": {"root": scan_root},
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
                      "discovery_status": _formal_discovery_status(report) if
                          report.get("formal_scope") != "SINGLE_STAGE" else "SINGLE_STAGE",
                      "report_json": str(report_json), "report_md": str(report_md)}
            if report.get("formal_scope") == "SINGLE_STAGE":
                if latest["report_status"] == "COMPLETE":
                    _write_json(run_dir.parent.parent / "latest_check.json", latest)
            else:
                _write_json(run_dir.parent.parent / "latest.json", latest)
            entry["formal_nl_root"] = formal_root
            if not stage:
                entry["formal_nl_stages"] = [str(item.get("nl_version")) for item in report.get("matches", [])
                                             if item.get("nl_version")]
            entry["formal_nl_scan_at"] = latest["generated_at"]
            entry["formal_nl_report_status"] = latest["report_status"]
            _write_registry(registry_file, registry)
            return page(ip_id, message="正式 NL 目录已浏览；单阶段核查状态请看报告。",
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
        latest_path = formal_dir / ("latest_check.json" if request.args.get("scope") == "check" else "latest.json")
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
        slot_reserved = False
        library_lock = None
        try:
            registry = _read_registry(registry_file)
            previous = next((item for item in registry.get("ips", []) if item.get("id") == _text(request.form, "id")), None)
            entry = _entry_from_form(request.form, previous)
            _validate_for_run(entry)
            if previous and entry["library_id"] != previous["library_id"]:
                raise ValueError("库标识与已登记记录不一致")
            with _SUBMISSION_LOCK:
                library_id = entry["library_id"]
                if not _REVIEW_TASK_SLOTS.acquire(blocking=False):
                    return page(entry["id"], error="检查队列已满（最多 8 个排队或运行任务），请稍后提交。",
                                active_tab="review"), 429
                slot_reserved = True
                library_lock = _acquire_library_lock(output, library_id)
                if library_lock is None:
                    _REVIEW_TASK_SLOTS.release()
                    slot_reserved = False
                    return page(entry["id"], error="该 IP 已有检查任务正在其他工作台中运行；请等待完成后再提交。",
                                active_tab="review"), 409
                _, latest_attempt_path = _task_paths(output, library_id, "")
                try:
                    latest_attempt = _json_read(latest_attempt_path)
                except (OSError, ValueError, json.JSONDecodeError):
                    latest_attempt = {}
                if latest_attempt.get("status") in {"QUEUED", "RUNNING"}:
                    if latest_attempt.get("worker_session") == _WORKBENCH_SESSION_ID:
                        _release_library_lock(library_lock)
                        library_lock = None
                        _REVIEW_TASK_SLOTS.release()
                        slot_reserved = False
                        return page(entry["id"], error="该 IP 已有检查任务正在排队或运行；请等待完成后再提交。",
                                    active_tab="review"), 409
                    stale_task_path, _ = _task_paths(output, library_id, str(latest_attempt.get("task_id") or ""))
                    _interrupt_stale_task(stale_task_path, latest_attempt_path, latest_attempt)
                task_id = f"task_{uuid4().hex}"
                task_path, latest_attempt_path = _task_paths(output, library_id, task_id)
                task = _task_event({
                    "task_id": task_id, "library_id": library_id, "ip_id": entry["id"],
                    "status": "QUEUED", "execution_status": "PENDING",
                    "worker_session": _WORKBENCH_SESSION_ID,
                    "submitted_at": datetime.now(timezone.utc).isoformat(),
                    "requested_checks": sorted(entry["checks"]),
                }, "排队中", "任务已登记，等待后台执行资源。")
                _update_task(task_path, latest_attempt_path, task)
                _refresh_overview(registry_file, output)

            def execute(lock_handle=library_lock) -> None:
                check_labels = {
                    "formal_nl": "正式目录盘点", "macro_index": "Macro / View 文件索引",
                    "lef_review": "LEF 双文件核查", "lef_liberty_check": "LEF–Liberty 接口核查",
                }
                running = _task_event({
                    **task, "status": "RUNNING", "started_at": datetime.now(timezone.utc).isoformat(),
                }, "执行检查", "正在执行：" + "、".join(
                    check_labels.get(name, name) for name in task["requested_checks"]))
                try:
                    _update_task(task_path, latest_attempt_path, running)
                    _refresh_overview(registry_file, output)
                    reviews, _ = run({"_config_path": str(registry_file), "ips": [entry],
                                      "registry_ips": registry.get("ips") or []}, output)
                    if not reviews:
                        raise RuntimeError("检查 Runner 未返回结果")
                    review = reviews[0]
                    conclusion = review.get("execution_status", "INCOMPLETE")
                    quality = (review.get("summary") or {}).get("quality_assessment") or {}
                    quality_label = quality.get("label") or "未形成质量结论"
                    finished = _task_event({
                        **running, "status": "COMPLETE", "execution_status": conclusion,
                        "quality_status": quality.get("status", "NOT_ASSESSED"),
                        "summary": review.get("summary", {}),
                        "finished_at": datetime.now(timezone.utc).isoformat(),
                        "review_id": review.get("review_id"),
                    }, "已完成", f"检查完成；任务执行：{conclusion}；质量判断：{quality_label}。"
                       f"{quality.get('boundary') or '不等同于正式发布放行。'} 报告 {review.get('review_id') or '已生成'}。")
                    _update_task(task_path, latest_attempt_path, finished)
                    _refresh_overview(registry_file, output)
                except Exception as exc:
                    failed = _task_event({
                        **running, "status": "FAILED", "execution_status": "FAILED",
                        "finished_at": datetime.now(timezone.utc).isoformat(), "error": str(exc),
                    }, "已失败", f"任务失败：{exc}")
                    _update_task(task_path, latest_attempt_path, failed)
                    _refresh_overview(registry_file, output)
                finally:
                    _REVIEW_TASK_SLOTS.release()
                    _release_library_lock(lock_handle)

            _REVIEW_EXECUTOR.submit(execute)
            slot_reserved = False
            library_lock = None
            return redirect(url_for("ip_review.index", ip=entry["id"], tab="review",
                                    raw_version=entry.get("raw_version") or None,
                                    base_raw_version=_text(request.form, "quick_base_raw_version") or None,
                                    submitted="1"), code=303)
        except Exception as exc:
            if slot_reserved:
                _REVIEW_TASK_SLOTS.release()
            _release_library_lock(library_lock)
            return page(_text(request.form, "id"), error=str(exc)), 400

    @blueprint.get("/tasks/<task_id>")
    def task_status(task_id: str):
        if not _is_loopback_request():
            abort(403)
        if not re.fullmatch(r"task_[0-9a-f]{32}", task_id):
            abort(404)
        library_id = request.args.get("library_id", "")
        if not library_id:
            abort(404)
        task_path, _ = _task_paths(output, library_id, task_id)
        if not task_path.is_file():
            abort(404)
        _, latest_attempt_path = _task_paths(output, library_id, task_id)
        task = _json_read(task_path)
        return _interrupt_stale_task(task_path, latest_attempt_path, task)

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
        safe_library_name = re.sub(r"[^A-Za-z0-9._-]+", "_", library_id).strip("._-") or "library"
        return send_file(workbook_path, as_attachment=True,
                         download_name=f"{safe_library_name}_{review_id}.xlsx")

    @blueprint.get("/review-reports/<path:artifact>")
    def review_artifact(artifact: str):
        registry = _read_registry(registry_file)
        allowed_libraries = {
            _library_dir(str(item.get("library_id") or item.get("id") or "")):
            str(item.get("library_id") or item.get("id") or "")
            for item in registry.get("ips", [])
        }
        relative = Path(artifact)
        if relative.is_absolute() or ".." in relative.parts:
            abort(404)
        if relative.as_posix() == "ip_checks/index.html":
            target = output / relative
            if not target.is_file():
                abort(404)
            try:
                target.resolve().relative_to(output)
            except ValueError:
                abort(404)
            return send_file(target, mimetype="text/html", as_attachment=False)
        parts = relative.parts
        if len(parts) < 3 or parts[0] != "libraries" or parts[1] not in allowed_libraries:
            abort(404)
        library_id = allowed_libraries[parts[1]]
        if parts[2:] == ("latest.xlsx",):
            target = output / relative
            safe_library_name = re.sub(r"[^A-Za-z0-9._-]+", "_", library_id).strip("._-") or "library"
            download_name = f"{safe_library_name}_latest.xlsx"
            if not target.is_file():
                _, legacy_workbook = _latest_complete_run(output / "libraries" / parts[1])
                if legacy_workbook is None:
                    abort(404)
                target = legacy_workbook
        elif len(parts) == 5 and parts[2] == "runs" and re.fullmatch(r"review_[A-Za-z0-9_-]+", parts[3]) and parts[4] == "ip_review.xlsx":
            target = output / relative
            safe_library_name = re.sub(r"[^A-Za-z0-9._-]+", "_", library_id).strip("._-") or "library"
            download_name = f"{safe_library_name}_{parts[3]}.xlsx"
        else:
            abort(404)
        try:
            target.resolve().relative_to(output)
        except ValueError:
            abort(404)
        if not target.is_file():
            abort(404)
        return send_file(target, as_attachment=True, download_name=download_name)

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
