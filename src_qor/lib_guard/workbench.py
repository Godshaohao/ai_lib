"""Loopback-only UI for the persistent per-IP review registry."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import fcntl
import hashlib
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

from flask import Blueprint, Flask, abort, jsonify, redirect, render_template, request, send_file, url_for
from werkzeug.exceptions import HTTPException

from .review_runner import (CHECK_NAMES, _json_read, _latest_complete_run, _library_dir,
                           _load_saved_formal_inventory,
                           refresh_ip_overview, run)
from .raw_discovery import discover_raw_report, write_discovery_artifacts
from .file_status import build_file_status, scan_registered_raw_files, TRACKED_VIEWS
from .file_version_projection import build_projection, derive_file_capabilities, publish_projection, reproject_projection
from .content_compare import compare_projection_files
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
    checks: dict[str, dict[str, Any]] = {
        "macro_index": {"root": str(target_root_path), "version": target_version,
                        "library_id": str(selected.get("library_id") or selected.get("id") or "")}
    }
    notes = [f"Macro / View：扫描目标版本下支持的文件；LEF：{len(target_lefs)} 个；Liberty：{len(liberty_files)} 个。"]

    def limit_reason(markers: str) -> str:
        return "；".join(value for marker, value in (
            ("ACCESS_ERROR", "存在目录不可读"), ("LIMIT", "超过工作台枚举上限"))
            if _reason_has(markers, marker))

    if target_lefs_truncated:
        notes.append(f"目标版本 LEF 文件列表不完整（{limit_reason(target_lefs_truncated)}）；暂不自动选择 LEF，不影响 Macro / View 检查。")
        target_lefs = []
    if liberty_truncated:
        notes.append(f"Liberty 文件列表不完整（{limit_reason(liberty_truncated)}）；暂不自动选择 Liberty，不影响其他检查。")
        liberty_files = []

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
            notes.append(f"基准版本 LEF 文件列表不完整（{limit_reason(base_lefs_truncated)}）；暂不自动配对基准 LEF。")
            base_lefs = []
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
            notes.append("目标版本有多个 LEF，需选择目标文件才能核查 LEF；不影响 Macro / View 检查。")
        elif not target_lefs_truncated:
            notes.append("LEF：基准和目标版本均未发现 LEF，本次不执行 LEF 检查。")
    elif target_lef:
        notes.append("LEF：没有选择基准版本；以目标 LEF 做接口核查，不生成版本差异结论。")
    elif target_lefs:
        notes.append("目标版本有多个 LEF，需选择目标文件才能核查 LEF；不影响 Macro / View 检查。")
    elif not target_lefs_truncated:
        notes.append("LEF：目标版本没有发现 LEF，本次不执行接口核查。")

    if target_lef and liberty_files:
        liberty_spec: dict[str, Any] = {"liberty_files": liberty_files}
        if "lef_review" not in checks:
            liberty_spec["lef_file"] = target_lef
        checks["lef_liberty_check"] = liberty_spec
    elif target_lef and not liberty_truncated:
        notes.append("Liberty：目标版本没有发现 .lib/.lib.gz，本次不执行 LEF–Liberty 核查。")
    return checks, notes


def _formal_discovery_status(report: dict[str, Any]) -> str:
    if not report.get("matches"):
        return "NOT_FOUND"
    if report.get("broken_links") or any(item.get("status") != "COMPLETE" for item in
                                          (report.get("inventories") or {}).values()):
        return "PARTIAL"
    return "DISCOVERED"


def _registered_raw_owner(path_value: Any, ips: list[dict[str, Any]], registry_file: Path) -> dict[str, str] | None:
    if not path_value:
        return None
    try:
        source = Path(_resolve_registry_path(str(path_value), registry_file)).resolve()
    except (OSError, RuntimeError, ValueError):
        return None
    candidates: list[tuple[Path, dict[str, Any]]] = []
    for ip in ips:
        library_id = str(ip.get("library_id") or ip.get("id") or "")
        identity = {
            "id": str(ip.get("id") or library_id),
            "library_id": library_id,
            "label": str(ip.get("library_name") or ip.get("name") or library_id),
        }
        for version in ip.get("raw_versions") or []:
            version_path = str(version.get("path") or "").strip()
            if not version_path:
                continue
            try:
                candidates.append((Path(_resolve_registry_path(version_path, registry_file)).resolve(), identity))
            except (OSError, RuntimeError, ValueError):
                continue
    match, ambiguous = effective_file_tracker.longest_registered_path_match(source, candidates)
    if ambiguous or not match:
        return None
    return {key: str(value) for key, value in match[1].items()}


def _lef_comparison_scope(old_file: Any, new_file: Any, ips: list[dict[str, Any]],
                          registry_file: Path) -> dict[str, str] | None:
    old_owner = _registered_raw_owner(old_file, ips, registry_file)
    new_owner = _registered_raw_owner(new_file, ips, registry_file)
    if (not old_owner or not new_owner
            or old_owner.get("library_id") == new_owner.get("library_id")):
        return None
    return {
        "kind": "INDEPENDENT_CROSS_IP",
        "old_library_id": old_owner["library_id"],
        "old_library_label": old_owner["label"],
        "new_library_id": new_owner["library_id"],
        "new_library_label": new_owner["label"],
        "notice": "独立跨 IP 文件对比；不代表所选库的版本变化。",
    }


def _entry_from_form(form: Any, previous: dict[str, Any] | None = None) -> dict[str, Any]:
    selected = set(form.getlist("checks"))
    if "formal_nl" in selected:
        raise ValueError("正式目录链接、来源和 View 统计请在“正式 NL”页面查看；这里不重复运行。")
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
        "macro_index": lambda spec: bool(spec.get("report_json") or spec.get("filemap_json") or spec.get("root")),
        "lef_review": lambda spec: bool(spec.get("pairs") or spec.get("report_json") or (spec.get("old_file") and spec.get("new_file"))),
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
            "stage_file_record_count": 0, "unique_source_count": 0,
            "issues": [], "warnings": warnings,
        }

    registered_versions: list[tuple[Path, dict[str, Any]]] = []
    registered_roots: list[tuple[Path, dict[str, Any]]] = []
    registered_keys: set[tuple[str, str, str]] = set()

    def identity_key(identity: dict[str, Any]) -> tuple[str, str, str]:
        return (str(identity.get("vendor") or "").casefold(),
                str(identity.get("middle_path") or "").casefold(),
                str(identity.get("library_name") or "").casefold())

    for ip in ips:
        vendor = str(ip.get("vendor") or "").strip()
        library = str(ip.get("library_name") or ip.get("name") or "").strip()
        if not vendor or not library:
            library_id = str(ip.get("library_id") or ip.get("id") or "")
            vendor, _, library = library_id.partition(".")
        identity = {
            "vendor": vendor or "未识别 Vendor",
            "middle_path": str(ip.get("middle_path") or "").strip(),
            "library_name": library or str(ip.get("id") or "未识别 IP"),
            "library_id": str(ip.get("library_id") or ip.get("id") or ""),
        }
        registered_keys.add(identity_key(identity))
        raw_root_value = str(ip.get("raw_root") or "").strip()
        if raw_root_value:
            registered_roots.append((Path(_resolve_registry_path(raw_root_value, registry_file)).resolve(), identity))
        for version in ip.get("raw_versions") or []:
            version_path = str(version.get("path") or "").strip()
            version_id = str(version.get("id") or "").strip()
            if version_path:
                registered_versions.append((Path(_resolve_registry_path(version_path, registry_file)).resolve(),
                                            {**identity, "raw_version": version_id}))

    registry_data = _read_registry(registry_file)
    raw_root_value = str(registry_data.get("raw_root") or "").strip()
    common_raw_root = (Path(_resolve_registry_path(raw_root_value, registry_file))
                       if raw_root_value else None)
    discovered_versions: list[tuple[Path, dict[str, Any]]] = []
    if common_raw_root is not None and common_raw_root.is_dir():
        discovery = discover_raw_report(common_raw_root)
        for candidate in discovery.get("candidates") or []:
            candidate_identity = {
                "vendor": str(candidate.get("vendor") or ""),
                "middle_path": str(candidate.get("middle_path") or ""),
                "library_name": str(candidate.get("library_name") or candidate.get("display_name") or ""),
                "library_id": str(candidate.get("library_id") or ""),
            }
            registered_status = "已登记" if identity_key(candidate_identity) in registered_keys else "未登记"
            for version in candidate.get("versions") or []:
                version_path = str(version.get("path") or "").strip()
                if version_path:
                    discovered_versions.append((Path(version_path).resolve(),
                                                {**candidate_identity, "raw_version": str(version.get("id") or "未标版本"),
                                                 "registration_status": registered_status}))

    def source_identity(source_value: str) -> dict[str, str] | None:
        source = Path(source_value).resolve()
        match, ambiguous = effective_file_tracker.longest_registered_path_match(
            source, registered_versions)
        if ambiguous:
            return {"_unresolved": "来源匹配不唯一"}
        if match:
            _, identity = match
            return {**identity, "registration_status": "已登记"}

        root_match, ambiguous = effective_file_tracker.longest_registered_path_match(
            source, registered_roots)
        if ambiguous:
            return {"_unresolved": "来源匹配不唯一"}
        if root_match:
            _, root_identity = root_match
            matching_roots = []
            for library_root, registered_identity in registered_roots:
                try:
                    relative = source.relative_to(library_root)
                except ValueError:
                    continue
                if len(library_root.parts) == max((len(path.parts) for path, _ in registered_roots
                                                   if source.is_relative_to(path)), default=-1):
                    matching_roots.append((registered_identity, relative))
            if len({json.dumps(item[0], sort_keys=True) for item in matching_roots}) != 1:
                return {"_unresolved": "来源匹配不唯一"}
            relative = matching_roots[0][1]
            return {**root_identity, "raw_version": relative.parts[0] if relative.parts else "未标版本",
                    "registration_status": "已登记"}

        if common_raw_root is not None:
            try:
                source.relative_to(common_raw_root.resolve())
            except ValueError:
                return None
            discovered_match, ambiguous = effective_file_tracker.longest_registered_path_match(
                source, discovered_versions)
            if ambiguous:
                return {"_unresolved": "来源匹配不唯一"}
            if discovered_match:
                _, discovered = discovered_match
                return discovered
        return None

    stages: list[dict[str, Any]] = []
    library_rows: dict[tuple[str, str, str], dict[str, Any]] = {}
    file_rows: list[dict[str, str]] = []
    issue_rows: list[dict[str, str]] = []
    view_counts: dict[str, int] = {}
    version_keys: set[tuple[str, str, str]] = set()
    unmapped_file_count = 0
    for stage_root, stage_name in sorted(
            stage_roots.items(), key=lambda item: (_version_sort_key(item[1]), str(item[0]).casefold())):
        inventory = effective_file_tracker.inventory_for_ip_target(stage_root)
        stage_libraries: dict[tuple[str, str, str], dict[str, Any]] = {}
        for view, count in (inventory.get("view_counts") or {}).items():
            view_counts[view] = view_counts.get(view, 0) + int(count)
        for file in inventory.get("files") or []:
            identity = source_identity(str(file.get("source_path") or ""))
            row = {**file, "stage": stage_name}
            if identity and identity.get("_unresolved"):
                unmapped_file_count += 1
                row["vendor"] = "来源未确定"
                row["middle_path"] = ""
                row["library_name"] = "来源未确定"
                row["raw_version"] = "无法识别"
                row["registration_status"] = identity["_unresolved"]
            elif identity:
                row.update(identity)
                key = identity_key(identity)
                raw_version = identity.get("raw_version") or "未标版本"
                version_keys.add((*key, raw_version))
                for target in (library_rows, stage_libraries):
                    item = target.setdefault(key, {
                        "vendor": identity["vendor"], "library_name": identity["library_name"],
                        "middle_path": identity.get("middle_path", ""),
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
                row["middle_path"] = ""
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
    unique_sources = {str(Path(row.get("source_path") or "").resolve())
                      for row in file_rows if row.get("source_path")}
    return {
        "status": "INCOMPLETE" if issue_rows or warnings or unmapped_file_count else "COMPLETE",
        "stages": stages, "stage_labels": sorted({row["stage"] for row in stages}, key=_version_sort_key),
        "libraries": libraries, "files": file_rows,
        "view_counts": dict(sorted(view_counts.items())), "stage_count": len(stages),
        "library_count": len(libraries),
        "registered_library_count": sum(row["registration_status"] == "已登记" for row in libraries),
        "unregistered_library_count": sum(row["registration_status"] == "未登记" for row in libraries),
        "raw_version_count": len(version_keys), "file_count": sum(row["file_count"] for row in stages),
        "stage_file_record_count": sum(row["file_count"] for row in stages),
        "unique_source_count": len(unique_sources),
        "unmapped_file_count": unmapped_file_count, "issues": issue_rows, "warnings": warnings,
    }


def _formal_nl_config_fingerprint(registry: dict[str, Any]) -> str:
    """Fingerprint only the registry fields that determine Formal NL scope."""
    ips = []
    for ip in registry.get("ips") or []:
        ips.append({key: ip.get(key) for key in (
            "id", "library_id", "vendor", "middle_path", "library_name", "name",
            "raw_root", "raw_versions", "formal_nl_root", "formal_nl_stages",
        )})
    payload = {"raw_root": registry.get("raw_root"), "ips": sorted(
        ips, key=lambda item: str(item.get("library_id") or item.get("id") or ""))}
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _file_status_path(output: Path, library_id: str) -> Path:
    return output / "file_status" / _library_dir(library_id) / "latest.json"


def _read_file_version_projection(output: Path, library_id: str, status: dict[str, Any]) -> dict[str, Any]:
    snapshot_id = str(status.get("projection_snapshot_id") or "")
    if not re.fullmatch(r"snapshot_[A-Za-z0-9_-]+", snapshot_id):
        return {}
    path = output / "file_versions" / _library_dir(library_id) / "runs" / snapshot_id / "projection.json"
    try:
        projection = _json_read(path)
    except (OSError, ValueError, json.JSONDecodeError):
        return {}
    if (projection.get("schema_version") not in {"file_version_projection.v1", "file_version_projection.v2"}
            or projection.get("snapshot_id") != snapshot_id or projection.get("library_id") != library_id):
        return {}
    for row in projection.get("files") or []:
        row.setdefault("capabilities", derive_file_capabilities(row))
    return projection


def _read_lef_file_status(output: Path, registry: dict[str, Any], selected: dict[str, Any],
                          formal_overview: dict[str, Any]) -> dict[str, Any]:
    library_id = str(selected.get("library_id") or selected.get("id") or "")
    empty = {"status": "NOT_REFRESHED", "files": [], "stale": False,
             "generated_at": "", "raw_scope": {"registered_deliveries": 0, "scan_status": "UNKNOWN",
                                                     "ordering_basis": "UNKNOWN"},
             "nl_context": {"stage": "", "root": "", "snapshot_generated_at": "", "status": "UNKNOWN"}}
    if not library_id:
        return empty
    path = _file_status_path(output, library_id)
    if not path.is_file():
        return empty
    try:
        saved = _json_read(path)
    except (OSError, ValueError, json.JSONDecodeError):
        return {**empty, "status": "SNAPSHOT_ERROR", "stale": True}
    if saved.get("schema_version") != "lef_file_status.v1":
        return {**empty, "status": "SNAPSHOT_ERROR", "stale": True}
    stale = bool(saved.get("registry_fingerprint") != _formal_nl_config_fingerprint(registry)
                 or (not saved.get("raw_only") and (formal_overview.get("stale")
                 or not formal_overview.get("generated_at")
                 or saved.get("formal_snapshot_generated_at") != formal_overview.get("generated_at"))))
    snapshot_id = str(saved.get("projection_snapshot_id") or "")
    if snapshot_id:
        pointer_path = output / "file_versions" / _library_dir(library_id) / "latest.json"
        try:
            pointer = _json_read(pointer_path)
            stale = stale or not isinstance(pointer, dict) or pointer.get("snapshot_id") != snapshot_id
        except (OSError, ValueError, json.JSONDecodeError):
            stale = True
    return {**saved, "stale": stale, "status": "STALE" if stale else saved.get("status", "COMPLETE")}


def _read_formal_nl_snapshot(output: Path, registry: dict[str, Any]) -> dict[str, Any]:
    empty = {
        "status": "NOT_REFRESHED", "stages": [], "stage_labels": [], "libraries": [], "files": [],
        "view_counts": {}, "stage_count": 0, "library_count": 0, "registered_library_count": 0,
        "unregistered_library_count": 0, "raw_version_count": 0, "file_count": 0,
        "stage_file_record_count": 0, "unique_source_count": 0, "unmapped_file_count": 0,
        "issues": [], "warnings": [], "generated_at": "", "stale": False,
    }
    path = output / "formal_nl" / "overview" / "latest.json"
    if not path.is_file():
        return empty
    try:
        saved = _json_read(path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return {**empty, "status": "SNAPSHOT_ERROR", "warnings": [f"正式 NL 快照无法读取：{exc}"]}
    if not isinstance(saved, dict):
        return {**empty, "status": "SNAPSHOT_ERROR", "warnings": ["正式 NL 快照格式无效：顶层必须是对象"]}
    overview = saved.get("overview")
    if not isinstance(overview, dict):
        return {**empty, "status": "SNAPSHOT_ERROR", "warnings": ["正式 NL 快照缺少 overview 数据"]}
    current_fingerprint = _formal_nl_config_fingerprint(registry)
    stale = saved.get("config_fingerprint") != current_fingerprint
    return {**overview, "files": [], "generated_at": str(saved.get("generated_at") or ""),
            "stale": stale, "source_revision": saved.get("source_revision") or "未记录"}


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
    from .display_labels import projection_label
    blueprint.add_app_template_filter(projection_label, "projection_label")

    def page(selected_id: str = "", message: str = "", error: str = "", run_record: dict[str, Any] | None = None,
             new_ip: bool = False, discovered: list[dict[str, Any]] | None = None,
             raw_root: str = "", active_tab: str = "catalog", active_review_tab: str | None = None,
             discovery_artifacts: bool = False,
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
        chosen_version = (request.args.get("raw_version", "") if request.method == "GET"
                          else _text(request.form, "raw_version"))
        if selected:
            # A registry default is not an explicit selection for this review visit.
            # Keep the saved registration untouched and require a deliberate choice
            # before loading RAW-derived file suggestions.
            selected = dict(selected)
            selected["raw_version"] = ""
        if selected and chosen_version:
            versions = [item for item in selected.get("raw_versions") or [] if str(item.get("id")) == chosen_version]
            if len(versions) == 1:
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
            if not latest_attempt.get("quality_status"):
                legacy_quality = ((latest_attempt.get("summary") or {}).get("quality_assessment") or {}).get("status")
                if legacy_quality:
                    latest_attempt["quality_status"] = legacy_quality
        submitted_checks = (set(latest_attempt.get("requested_checks") or [])
                            if request.args.get("submitted") == "1" else set())
        raw_root = raw_root or str(registry.get("raw_root") or "")
        if raw_root:
            raw_root = _resolve_registry_path(raw_root, registry_file)
        formal_nl = _formal_nl_latest(output, str(selected.get("library_id") or "")) if selected else {}
        review_formal_snapshot = _load_saved_formal_inventory(
            output, str(selected.get("library_id") or "")) if selected else {}
        formal_overview = _read_formal_nl_snapshot(output, registry)
        lef_file_status = _read_lef_file_status(output, registry, selected, formal_overview)
        file_version_projection = _read_file_version_projection(
            output, str(selected.get("library_id") or selected.get("id") or ""), lef_file_status)
        matrix_source_snapshot_id = str(file_version_projection.get("snapshot_id") or "") if file_version_projection else ""
        requested_matrix_review = str(request.args.get("matrix_review") or "")
        matrix_historical = bool(requested_matrix_review)
        matrix_review_id = requested_matrix_review or str(latest_attempt.get("review_id") or "")
        if file_version_projection and re.fullmatch(r"review_[A-Za-z0-9_-]+", matrix_review_id):
            library_id = str(selected.get("library_id") or selected.get("id") or "")
            evidence = output / "libraries" / _library_dir(library_id) / "runs" / matrix_review_id / "evidence" / "file_version_projection.json"
            try:
                reviewed = _json_read(evidence)
                if (reviewed.get("library_id") == library_id and reviewed.get("schema_version") in {"file_version_projection.v1", "file_version_projection.v2"}
                        and (matrix_historical or (reviewed.get("input_snapshot_id") or reviewed.get("source_snapshot_id")) == file_version_projection.get("snapshot_id"))):
                    matrix_source_snapshot_id = str(reviewed.get("input_snapshot_id") or reviewed.get("source_snapshot_id") or matrix_source_snapshot_id)
                    file_version_projection = reviewed
                else:
                    matrix_review_id = ""
                    matrix_historical = False
            except (OSError, ValueError, json.JSONDecodeError, AttributeError):
                matrix_review_id = ""
                matrix_historical = False
        else:
            matrix_review_id = ""
            matrix_historical = False
        file_status_error = request.args.get("file_status_error", "")
        active_review_tab = active_review_tab or request.args.get("review_tab", "files")
        if active_review_tab not in {"files", "config", "history"}:
            active_review_tab = "files"
        raw_choices = {str(item.get("id")): str(item.get("path")) for item in selected.get("raw_versions") or []}
        base_version = (request.args.get("base_raw_version", "") if request.method == "GET"
                        else _text(request.form, "base_raw_version"))
        base_root = raw_choices.get(base_version, "")
        target_root = raw_choices.get(chosen_version, "")
        old_lefs, old_limit = _files_for_selection(base_root, (".lef", ".lef.gz")) if base_root else ([], "")
        new_lefs, new_limit = _files_for_selection(target_root, (".lef", ".lef.gz")) if target_root else ([], "")
        liberty_files, lib_limit = _files_for_selection(target_root, (".lib", ".lib.gz")) if target_root else ([], "")
        old_lef_choices = [{"path": path, "relative": Path(path).relative_to(Path(base_root).resolve()).as_posix()}
                           for path in old_lefs]
        new_lef_choices = [{"path": path, "relative": Path(path).relative_to(Path(target_root).resolve()).as_posix()}
                           for path in new_lefs]
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
        display_lef_spec = ((selected.get("checks") or {}).get("lef_review") or {})
        scope_old_file = (_text(request.form, "lef_old_file") if request.method == "POST"
                          else str(display_lef_spec.get("old_file") or default_base_lef))
        scope_new_file = (_text(request.form, "lef_new_file") if request.method == "POST"
                          else str(display_lef_spec.get("new_file") or default_target_lef))
        lef_comparison_scope = _lef_comparison_scope(scope_old_file, scope_new_file, ips, registry_file)
        chosen_stage = (request.args.get("formal_stage", "") if request.method == "GET"
                        else _text(request.form, "formal_stage"))
        if selected and chosen_stage:
            selected = dict(selected)
            selected["formal_stage"] = chosen_stage
            selected["raw_version"] = ""
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
                               submitted_checks=submitted_checks,
                               message=message, error=error, run_record=run_record,
                               checks=sorted(CHECK_NAMES), discovered=discovered or [], raw_root=raw_root,
                               active_tab=active_tab, discovery_artifacts=discovery_artifacts,
                               environment_label=environment_label, formal_nl=formal_nl, vendors=vendors,
                               review_formal_snapshot=review_formal_snapshot,
                               identity_conflicts=identity_conflicts or [], partial_discovery=partial_discovery,
                               formal_overview=formal_overview,
                               lef_file_status=lef_file_status,
                               file_version_projection=file_version_projection, matrix_source_snapshot_id=matrix_source_snapshot_id,
                               matrix_historical=matrix_historical,
                               matrix_review_id=matrix_review_id,
                               file_status_error=file_status_error,
                               active_review_tab=active_review_tab,
                               discovery_warnings=discovery_warnings or [],
                               registered_ids={str(item.get("library_id") or "") for item in ips},
                               selected_raw_version=chosen_version, base_raw_version=base_version,
                               old_lefs=old_lefs, new_lefs=new_lefs, liberty_choices=liberty_files,
                               old_lef_choices=old_lef_choices, new_lef_choices=new_lef_choices,
                               default_target_lef=default_target_lef, default_base_lef=default_base_lef,
                               quick_checks=quick_checks, quick_notes=quick_notes,
                               lef_comparison_scope=lef_comparison_scope,
                               latest_workbook_url=latest_workbook_url,
                               task_workbook_url=task_workbook_url,
                               review_overview_url=review_overview_url,
                               file_choices_limited=bool(file_choice_reasons),
                               file_choices_notice=file_choices_notice)

    @blueprint.post("/formal-nl/overview/refresh")
    def refresh_formal_nl_overview():
        if not _is_loopback_request():
            abort(403)
        ip_id = _text(request.form, "ip")
        try:
            registry = _read_registry(registry_file)
            overview = _formal_nl_directory_overview(registry.get("ips") or [], registry_file)
            snapshot = {
                "schema_version": "formal_nl_overview.v1",
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "config_fingerprint": _formal_nl_config_fingerprint(registry),
                "overview": overview,
            }
            _write_json(output / "formal_nl" / "overview" / "latest.json", snapshot)
            return redirect(url_for("ip_review.index", ip=ip_id, tab="formal-nl",
                                    formal_refreshed="1"))
        except HTTPException:
            raise
        except Exception as exc:
            return page(ip_id, error=f"正式 NL 总览刷新失败；上次成功快照保留：{exc}",
                        active_tab="formal-nl"), 400

    @blueprint.post("/file-status/refresh")
    def refresh_file_status():
        if not _is_loopback_request():
            abort(403)
        ip_id = _text(request.form, "ip")
        try:
            registry = _read_registry(registry_file)
            entry = next((item for item in registry.get("ips", []) if str(item.get("id")) == ip_id), None)
            if entry is None:
                abort(404)
            if _text(request.form, "raw_only") == "1":
                library_id = str(entry.get("library_id") or entry.get("id") or "")
                versions = [{"id": str(item.get("id") or ""),
                             "path": _resolve_registry_path(str(item.get("path") or ""), registry_file),
                             **{key: item[key] for key in ("delivery_order", "delivery_date", "date") if key in item}}
                            for item in entry.get("raw_versions") or []]
                raw_inventory = scan_registered_raw_files(versions)
                projection = build_projection(library_id, versions, raw_inventory, None,
                    base_version=_text(request.form, "base_version"), target_version=_text(request.form, "target_version"))
                projection["sources"] = {
                    "registry_ref": str(registry_file),
                    "registry_fingerprint": _formal_nl_config_fingerprint(registry),
                    "raw_inventory": [{"version_id": item.get("version_id"), "root": item.get("root"),
                                       "status": item.get("status"), "errors": item.get("errors") or []}
                                      for item in raw_inventory],
                }
                status_path = _file_status_path(output, library_id)
                result = {"schema_version": "lef_file_status.v1", "library_id": library_id,
                          "generated_at": datetime.now(timezone.utc).isoformat(), "status": "COMPLETE" if projection["coverage"]["raw_inventory"] == "COMPLETE" else "INCOMPLETE",
                          "raw_only": True, "files": [], "covered_views": sorted(TRACKED_VIEWS),
                          "registry_fingerprint": _formal_nl_config_fingerprint(registry),
                          "nl_context": {"stage": "", "status": "UNKNOWN"},
                          "raw_scope": {"registered_deliveries": len(versions),
                                        "scan_status": projection["coverage"]["raw_inventory"], "ordering_basis": projection["version_order"]["basis"]}}
                projection_root = output / "file_versions" / _library_dir(library_id)
                projection_root.mkdir(parents=True, exist_ok=True)
                with (projection_root / ".publish.lock").open("a+") as lock:
                    fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
                    old_status = status_path.read_bytes() if status_path.is_file() else None
                    def publish_raw_status(snapshot):
                        result["projection_snapshot_id"] = snapshot["snapshot_id"]
                        _write_json(status_path, result)
                        def rollback():
                            if old_status is None:
                                status_path.unlink(missing_ok=True)
                            else:
                                temporary = status_path.with_name(f".{status_path.name}.{uuid4().hex}.tmp")
                                try:
                                    temporary.write_bytes(old_status)
                                    temporary.replace(status_path)
                                finally:
                                    temporary.unlink(missing_ok=True)
                        return rollback
                    publish_projection(projection_root, projection, before_publish=publish_raw_status)
                return redirect(url_for("ip_review.index", ip=ip_id, tab="review", review_tab="files", file_status_refreshed="1"), code=303)
            formal_snapshot_path = output / "formal_nl" / "overview" / "latest.json"
            if not formal_snapshot_path.is_file():
                raise ValueError("尚无正式 NL 文件来源快照；请先刷新正式目录盘点。")
            formal_snapshot = _json_read(formal_snapshot_path)
            if formal_snapshot.get("config_fingerprint") != _formal_nl_config_fingerprint(registry):
                raise ValueError("正式 NL 盘点已过期；请先刷新正式目录盘点，再刷新文件状态。")
            overview = formal_snapshot.get("overview")
            if not isinstance(overview, dict) or not isinstance(overview.get("files"), list):
                raise ValueError("正式 NL 快照缺少完整文件明细；请重新刷新正式目录盘点。")

            library_id = str(entry.get("library_id") or entry.get("id") or "")
            ip_files = [file for file in overview["files"]
                        if str(file.get("library_id") or "") == library_id]
            configured_root_value = str(entry.get("formal_nl_root") or "").strip()
            configured_root = Path(_resolve_registry_path(configured_root_value, registry_file)) if configured_root_value else None
            stage_pattern = re.compile(r"^lib_NL[A-Za-z0-9_.-]+$", re.IGNORECASE)
            stage_hint = next((part for part in reversed(configured_root.parts)
                               if stage_pattern.fullmatch(part)), "") if configured_root else ""
            stage_rows = overview.get("stages") or []
            scoped_stage_rows = []
            for stage_row in stage_rows:
                stage_root_value = str(stage_row.get("root") or "").strip()
                stage_root = Path(stage_root_value).expanduser().resolve(strict=False) if stage_root_value else None
                if stage_root is None:
                    continue
                if configured_root is not None:
                    if stage_hint and str(stage_row.get("stage")) != stage_hint:
                        continue
                    if not (stage_root == configured_root or stage_root.is_relative_to(configured_root)
                            or configured_root.is_relative_to(stage_root)):
                        continue
                scoped_stage_rows.append(stage_row)
            stages_for_ip = {str(file.get("stage") or "") for file in ip_files if file.get("stage")}
            scoped_stage_names = {str(item.get("stage") or "") for item in scoped_stage_rows}
            if stage_hint:
                selected_stage = stage_hint if stage_hint in scoped_stage_names else ""
            elif len(entry.get("formal_nl_stages") or []) == 1:
                configured_stage = str(entry["formal_nl_stages"][0])
                selected_stage = configured_stage if configured_stage in scoped_stage_names else ""
            elif len(stages_for_ip) == 1:
                selected_stage = next(iter(stages_for_ip))
            elif len(stages_for_ip) > 1:
                selected_stage = ""
            elif len(scoped_stage_rows) == 1:
                selected_stage = str(scoped_stage_rows[0].get("stage") or "")
            else:
                selected_stage = ""

            if not selected_stage:
                versions = [{"id": str(item.get("id") or ""),
                             "path": _resolve_registry_path(str(item.get("path") or ""), registry_file),
                             **{key: item[key] for key in ("delivery_order", "delivery_date", "date") if key in item}}
                            for item in entry.get("raw_versions") or []]
                raw_inventory = scan_registered_raw_files(versions)
                result = build_file_status(
                    [], versions, raw_inventory,
                    context={"library_id": library_id, "stage": "",
                             "root": str(configured_root or ""),
                             "snapshot_generated_at": str(formal_snapshot.get("generated_at") or ""),
                             "status": "NEEDS_CONTEXT"},
                )
                result.update({
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                    "status": "INCOMPLETE",
                    "covered_views": sorted(TRACKED_VIEWS),
                    "warnings": ["正式目录包含多个可能阶段，当前 IP 未指定唯一 NL 上下文；RAW 文件仍可独立查看和比较。"],
                })
                projection = build_projection(
                    library_id, versions, raw_inventory, None,
                    base_version=_text(request.form, "base_version"),
                    target_version=_text(request.form, "target_version"))
                projection.setdefault("coverage", {})["formal_inventory"] = "CONTEXT_REQUIRED"
                for row in projection.get("files") or []:
                    row["formal_usage"] = {"observation_status": "FORMAL_CONTEXT_REQUIRED",
                                            "stage": "", "approved_effective_status": "NOT_CONFIGURED"}
                projection["sources"] = {
                    "registry_ref": str(registry_file),
                    "registry_fingerprint": _formal_nl_config_fingerprint(registry),
                    "formal_snapshot_generated_at": str(formal_snapshot.get("generated_at") or ""),
                    "formal_snapshot_ref": str(formal_snapshot_path),
                    "raw_inventory": [{"version_id": item.get("version_id"), "root": item.get("root"),
                                       "status": item.get("status"), "errors": item.get("errors") or []}
                                      for item in raw_inventory],
                }
            else:
                stage_row = next((item for item in stage_rows
                                  if str(item.get("stage") or "") == selected_stage
                                  and (not configured_root or not scoped_stage_rows
                                       or item in scoped_stage_rows)), {})
                stage_files = [file for file in ip_files
                               if str(file.get("stage") or "") == selected_stage
                               and str(file.get("view") or "").casefold() in TRACKED_VIEWS]
                versions = [{"id": str(item.get("id") or ""),
                             "path": _resolve_registry_path(str(item.get("path") or ""), registry_file),
                             **{key: item[key] for key in ("delivery_order", "delivery_date", "date") if key in item}}
                            for item in entry.get("raw_versions") or []]
                raw_inventory = scan_registered_raw_files(versions)
                result = build_file_status(
                    stage_files, versions, raw_inventory,
                    context={"library_id": library_id, "stage": selected_stage,
                             "root": str(stage_row.get("root") or configured_root or ""),
                             "snapshot_generated_at": str(formal_snapshot.get("generated_at") or ""),
                             "status": str(stage_row.get("status") or overview.get("status") or "UNKNOWN")},
                )
                result["status"] = ("INCOMPLETE" if result["nl_context"]["status"] != "COMPLETE"
                                     or result["raw_scope"]["scan_status"] in {"PARTIAL", "INCOMPLETE"}
                                     else ("NO_LEF_IN_SCOPE" if not result["files"] else "COMPLETE"))
                result["generated_at"] = datetime.now(timezone.utc).isoformat()
                result["covered_views"] = sorted(TRACKED_VIEWS)
                projection = build_projection(
                    library_id, versions, raw_inventory, stage_files,
                    base_version=_text(request.form, "base_version"),
                    target_version=_text(request.form, "target_version"), formal_stage=selected_stage)
                projection["sources"] = {
                    "registry_ref": str(registry_file),
                    "registry_fingerprint": _formal_nl_config_fingerprint(registry),
                    "formal_snapshot_generated_at": str(formal_snapshot.get("generated_at") or ""),
                    "formal_snapshot_ref": str(formal_snapshot_path),
                    "raw_inventory": [{"version_id": item.get("version_id"), "root": item.get("root"),
                                       "status": item.get("status"), "errors": item.get("errors") or []}
                                      for item in raw_inventory],
                }
            result["registry_fingerprint"] = _formal_nl_config_fingerprint(registry)
            result["formal_snapshot_generated_at"] = str(formal_snapshot.get("generated_at") or "")
            status_path = _file_status_path(output, library_id)
            if projection:
                projection_root = output / "file_versions" / _library_dir(library_id)
                projection_root.mkdir(parents=True, exist_ok=True)
                with (projection_root / ".publish.lock").open("a+") as lock:
                    fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
                    old_status = status_path.read_bytes() if status_path.is_file() else None

                    def publish_status(snapshot):
                        result["projection_snapshot_id"] = snapshot["snapshot_id"]
                        _write_json(status_path, result)

                        def rollback_status():
                            if old_status is None:
                                status_path.unlink(missing_ok=True)
                            else:
                                temporary = status_path.with_name(f".{status_path.name}.{uuid4().hex}.tmp")
                                try:
                                    temporary.write_bytes(old_status)
                                    temporary.replace(status_path)
                                finally:
                                    temporary.unlink(missing_ok=True)
                        return rollback_status

                    publish_projection(projection_root, projection, before_publish=publish_status)
            else:
                _write_json(status_path, result)
            return redirect(url_for("ip_review.index", ip=ip_id, tab="review", review_tab="files",
                                    file_status_refreshed="1"), code=303)
        except HTTPException:
            raise
        except Exception as exc:
            return redirect(url_for("ip_review.index", ip=ip_id, tab="review", review_tab="files",
                                    file_status_error=str(exc)), code=303)

    @blueprint.post("/file-status/link-formal")
    def link_saved_formal():
        if not _is_loopback_request():
            abort(403)
        ip_id = _text(request.form, "ip")
        try:
            registry = _read_registry(registry_file)
            entry = next((item for item in registry.get("ips", []) if str(item.get("id")) == ip_id), None)
            if entry is None:
                abort(404)
            library_id = str(entry.get("library_id") or entry.get("id") or "")
            status = _read_lef_file_status(output, registry, entry, _read_formal_nl_snapshot(output, registry))
            projection = _read_file_version_projection(output, library_id, status)
            pointer = _json_read(output / "file_versions" / _library_dir(library_id) / "latest.json")
            if (status.get("registry_fingerprint") != _formal_nl_config_fingerprint(registry)
                    or not projection or projection.get("snapshot_id") != _text(request.form, "snapshot_id")
                    or pointer.get("snapshot_id") != projection.get("snapshot_id")):
                raise ValueError("RAW 快照已变化或过期，请先刷新 RAW 文件清单")
            snapshot_path = output / "formal_nl" / "overview" / "latest.json"
            if not snapshot_path.is_file():
                raise ValueError("尚无正式 NL 快照，请先在正式 NL 页面刷新")
            snapshot = _json_read(snapshot_path)
            if snapshot.get("config_fingerprint") != _formal_nl_config_fingerprint(registry):
                raise ValueError("正式 NL 快照已过期，请先刷新正式 NL")
            overview = snapshot.get("overview") or {}
            if not isinstance(overview.get("files"), list):
                raise ValueError("正式 NL 快照缺少文件明细")
            ip_files = [item for item in overview["files"] if str(item.get("library_id") or "") == library_id]
            stages = {str(item.get("stage") or "") for item in ip_files if item.get("stage")}
            configured = set(str(item) for item in entry.get("formal_nl_stages") or [])
            stage = next(iter(stages)) if len(stages) == 1 else next(iter(stages & configured)) if len(stages & configured) == 1 else ""
            if len(stages) > 1 and not stage:
                raise ValueError("正式 NL 包含多个阶段，无法确定来源；请先明确阶段")
            versions = [{"id": str(item.get("id") or ""), "path": _resolve_registry_path(str(item.get("path") or ""), registry_file),
                         **{key: item[key] for key in ("delivery_order", "delivery_date", "date") if key in item}}
                        for item in entry.get("raw_versions") or []]
            by_version = {item["id"]: [] for item in versions}
            for row in projection.get("files") or []:
                for occurrence in row.get("occurrences") or []:
                    if occurrence.get("version") in by_version:
                        by_version[occurrence["version"]].append(occurrence.get("source_path"))
            inventory_status = projection.get("scope", {}).get("inventory_status") or {}
            inventories = [{"version_id": version, "files": paths, "status": inventory_status.get(version, "UNKNOWN")}
                           for version, paths in by_version.items()]
            scope = projection.get("scope") or {}
            linked = build_projection(library_id, versions, inventories, [item for item in ip_files if not stage or item.get("stage") == stage],
                                      base_version=scope.get("base_version") or "", target_version=scope.get("target_version") or "", formal_stage=stage)
            linked_rows = {row["file_key"]: row for row in linked["files"]}
            existing = {row["file_key"] for row in projection["files"]}
            for row in projection["files"]:
                if row["file_key"] in linked_rows:
                    row["formal_usage"] = linked_rows[row["file_key"]]["formal_usage"]
                    if overview.get("status") != "COMPLETE" and row["formal_usage"].get("observation_status") == "NOT_OBSERVED":
                        row["formal_usage"]["observation_status"] = "UNKNOWN"
                    if row["formal_usage"].get("observation_status") == "AMBIGUOUS":
                        row["identity_status"] = "AMBIGUOUS"
                    row["capabilities"] = derive_file_capabilities(row)
            projection["files"].extend(row for row in linked["files"] if row["file_key"] not in existing)
            projection["unbound_formal_files"] = linked["unbound_formal_files"]
            projection["coverage"]["formal_inventory"] = "SNAPSHOT_ONLY"
            projection["scope"]["formal_stage"] = stage
            projection.setdefault("source_snapshot_id", projection["snapshot_id"])
            projection["input_snapshot_id"] = projection["snapshot_id"]
            projection.setdefault("sources", {}).update({"formal_snapshot_generated_at": snapshot.get("generated_at"), "formal_snapshot_ref": str(snapshot_path)})
            projection_root = output / "file_versions" / _library_dir(library_id)
            status_path = _file_status_path(output, library_id)
            with (projection_root / ".publish.lock").open("a+") as lock:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
                old_status = status_path.read_bytes()
                def publish_link(saved_projection):
                    saved = dict(status)
                    saved["projection_snapshot_id"] = saved_projection["snapshot_id"]
                    saved["raw_only"] = True
                    if saved.get("status") == "STALE":
                        saved["status"] = "COMPLETE" if projection.get("coverage", {}).get("raw_inventory") == "COMPLETE" else "INCOMPLETE"
                    _write_json(status_path, saved)
                    def rollback():
                        temporary = status_path.with_name(f".{status_path.name}.{uuid4().hex}.tmp")
                        try:
                            temporary.write_bytes(old_status)
                            temporary.replace(status_path)
                        finally:
                            temporary.unlink(missing_ok=True)
                    return rollback
                publish_projection(projection_root, projection, before_publish=publish_link)
            return redirect(url_for("ip_review.index", ip=ip_id, tab="review", review_tab="files", file_status_refreshed="1"), code=303)
        except HTTPException:
            raise
        except Exception as exc:
            return redirect(url_for("ip_review.index", ip=ip_id, tab="review", review_tab="files", file_status_error=str(exc)), code=303)

    @blueprint.post("/file-status/range")
    def reproject_file_status_range():
        """Change Base/Target against the existing inventory snapshot only."""
        if not _is_loopback_request():
            abort(403)
        ip_id = _text(request.form, "ip") or _text(request.form, "id")
        try:
            registry = _read_registry(registry_file)
            entry = next((item for item in registry.get("ips", []) if str(item.get("id")) == ip_id), None)
            if entry is None:
                abort(404)
            library_id = str(entry.get("library_id") or entry.get("id") or "")
            status = _read_lef_file_status(output, registry, entry, _read_formal_nl_snapshot(output, registry))
            snapshot_id = _text(request.form, "snapshot_id")
            projection = _read_file_version_projection(output, library_id, status)
            if status.get("stale") or not projection or projection.get("snapshot_id") != snapshot_id:
                raise ValueError("文件矩阵快照已变化或过期；请刷新 RAW 文件清单后重新选择")
            projected = reproject_projection(
                projection,
                base_version=_text(request.form, "base_version"),
                target_version=_text(request.form, "target_version"),
            )
            projection_root = output / "file_versions" / _library_dir(library_id)
            status_path = _file_status_path(output, library_id)
            with (projection_root / ".publish.lock").open("a+") as lock:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
                old_status = status_path.read_bytes() if status_path.is_file() else None

                def publish_range(snapshot):
                    saved = dict(status)
                    saved["projection_snapshot_id"] = snapshot["snapshot_id"]
                    _write_json(status_path, saved)

                    def rollback():
                        if old_status is None:
                            status_path.unlink(missing_ok=True)
                        else:
                            temporary = status_path.with_name(f".{status_path.name}.{uuid4().hex}.tmp")
                            try:
                                temporary.write_bytes(old_status)
                                temporary.replace(status_path)
                            finally:
                                temporary.unlink(missing_ok=True)
                    return rollback

                publish_projection(projection_root, projected, before_publish=publish_range)
            return redirect(url_for("ip_review.index", ip=ip_id, tab="review", review_tab="files",
                                    file_status_refreshed="1"), code=303)
        except HTTPException:
            raise
        except Exception as exc:
            return redirect(url_for("ip_review.index", ip=ip_id, tab="review", review_tab="files",
                                    file_status_error=str(exc)), code=303)

    @blueprint.post("/file-status/compare")
    def compare_file_status():
        if not _is_loopback_request():
            abort(403)
        ip_id = _text(request.form, "ip") or _text(request.form, "id")
        try:
            registry = _read_registry(registry_file)
            entry = next((item for item in registry.get("ips", []) if str(item.get("id")) == ip_id), None)
            if entry is None:
                abort(404)
            library_id = str(entry.get("library_id") or entry.get("id") or "")
            status = _read_lef_file_status(output, registry, entry, _read_formal_nl_snapshot(output, registry))
            projection = _read_file_version_projection(output, library_id, status)
            if status.get("stale") or not projection or projection.get("snapshot_id") != _text(request.form, "snapshot_id"):
                raise ValueError("文件矩阵快照已变化或过期；请刷新后重新选择")
            keys = request.form.getlist("compare_file_key") or request.form.getlist("file_key")
            if not 1 <= len(keys) <= 50 or len(set(keys)) != len(keys):
                raise ValueError("请选择 1 至 50 个唯一文件进行内容比较")
            selected_rows = [row for row in projection.get("files") or [] if row.get("file_key") in set(keys)]
            if len(selected_rows) != len(keys):
                raise ValueError("所选文件不属于当前矩阵")
            if any(not row.get("capabilities", {}).get("content_comparable") for row in selected_rows):
                raise ValueError("所选文件尚未形成唯一 Base / Target 配对；请先应用交付范围")
            projection["input_snapshot_id"] = projection["snapshot_id"]
            projection.setdefault("source_snapshot_id", projection["snapshot_id"])
            compare_projection_files(projection, selected_keys=keys)
            projection_root = output / "file_versions" / _library_dir(library_id)
            status_path = _file_status_path(output, library_id)
            with (projection_root / ".publish.lock").open("a+") as lock:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
                old_status = status_path.read_bytes() if status_path.is_file() else None

                def publish_compare(snapshot):
                    saved = dict(status)
                    saved["projection_snapshot_id"] = snapshot["snapshot_id"]
                    saved["content_comparison"] = snapshot.get("coverage", {}).get("content_comparison")
                    _write_json(status_path, saved)

                    def rollback():
                        if old_status is None:
                            status_path.unlink(missing_ok=True)
                        else:
                            temporary = status_path.with_name(f".{status_path.name}.{uuid4().hex}.tmp")
                            try:
                                temporary.write_bytes(old_status)
                                temporary.replace(status_path)
                            finally:
                                temporary.unlink(missing_ok=True)
                    return rollback

                publish_projection(projection_root, projection, before_publish=publish_compare)
            return redirect(url_for("ip_review.index", ip=ip_id, tab="review", review_tab="files",
                                    file_status_refreshed="1"), code=303)
        except HTTPException:
            raise
        except Exception as exc:
            return redirect(url_for("ip_review.index", ip=ip_id, tab="review", review_tab="files",
                                    file_status_error=str(exc)), code=303)

    @blueprint.get("/formal-nl/overview/files")
    def formal_nl_overview_files():
        registry = _read_registry(registry_file)
        snapshot_path = output / "formal_nl" / "overview" / "latest.json"
        if not snapshot_path.is_file():
            return jsonify({"error": "尚无正式 NL 快照；请先刷新目录清点。"}), 404
        try:
            snapshot = _json_read(snapshot_path)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            return jsonify({"error": f"正式 NL 快照无法读取；请重新刷新目录清点：{exc}"}), 409
        if not isinstance(snapshot, dict) or not isinstance(snapshot.get("overview"), dict):
            return jsonify({"error": "正式 NL 快照结构无效；请重新刷新目录清点。"}), 409
        if snapshot.get("config_fingerprint") != _formal_nl_config_fingerprint(registry):
            return jsonify({"error": "正式 NL 快照已过期；请先刷新目录清点。"}), 409
        overview = snapshot["overview"]
        files = overview.get("files") or []
        if not isinstance(files, list):
            return jsonify({"error": "正式 NL 快照文件明细格式无效；请重新刷新目录清点。"}), 409
        return jsonify({"generated_at": snapshot.get("generated_at") or "",
                        "files": files})

    @blueprint.get("/")
    def index():
        try:
            registry = _read_registry(registry_file)
            requested = request.args.get("ip", "")
            ids = {str(item.get("id")) for item in registry.get("ips", [])}
            message = "检查任务已提交到后台；可离开页面，完成后在运行记录中查看。" \
                if request.args.get("submitted") == "1" else ""
            if request.args.get("file_status_refreshed") == "1":
                message = "文件状态已刷新；来源和日期只提供交付线索，不代表内容变化或已生效。"
            default_tab = "review" if ids or request.args.get("new") == "1" else "discover"
            requested_tab = request.args.get("tab") or default_tab
            if requested_tab not in {"review", "catalog", "discover", "formal-nl"}:
                requested_tab = default_tab
            if request.args.get("formal_refreshed") == "1":
                message = "正式 NL 总览已刷新；统计基于本次只读链接清点。"
            if request.args.get("saved") == "1":
                message = "IP 配置已保存。"
            if request.args.get("registered") == "1":
                message = "登记已完成；RAW 版本清单已更新，未修改源文件。"
            if request.args.get("removed") == "1":
                message = "已移除库登记；RAW 文件和历史检查结果均未删除。"
            if request.args.get("formal_scanned") == "1":
                message = "正式 NL 目录盘点已完成；本次只读检查结果已保存。"

            discovered = []
            discovery_artifacts = False
            identity_conflicts = []
            partial_discovery = False
            discovery_warnings = []
            discovery_raw_root = ""
            if requested_tab == "discover":
                discovery_path = output / "discovery" / "library_discovery.json"
                if discovery_path.is_file():
                    try:
                        discovery = _json_read(discovery_path)
                        if isinstance(discovery, dict) and isinstance(discovery.get("candidates"), list):
                            discovered = discovery["candidates"]
                            discovery_raw_root = str(discovery.get("raw_root") or "")
                            identity_conflicts = list(discovery.get("identity_conflicts") or [])
                            partial_discovery = bool(discovery.get("partial_discovery"))
                            discovery_warnings = list(discovery.get("warnings") or [])
                            discovery_artifacts = True
                            if request.args.get("discovery") == "latest":
                                generated = str(discovery.get("generated_at") or "")
                                suffix = f"（{generated}）" if generated else ""
                                message = f"发现结果已恢复{suffix}；未重新扫描。"
                    except (OSError, ValueError, json.JSONDecodeError):
                        if request.args.get("discovery") == "latest":
                            message = "上次发现结果无法读取；请重新扫描 RAW 根目录。"
            return page(requested if requested in ids else "", new_ip=request.args.get("new") == "1",
                        active_tab=requested_tab, message=message, discovered=discovered,
                        raw_root=discovery_raw_root, discovery_artifacts=discovery_artifacts,
                        identity_conflicts=identity_conflicts, partial_discovery=partial_discovery,
                        discovery_warnings=discovery_warnings)
        except Exception as exc:
            return render_template("workbench.html", ips=[], sidebar_ips=[], selected={}, latest={}, history=[],
                                   message="", error=str(exc), run_record=None, checks=sorted(CHECK_NAMES),
                                   vendors=[], identity_conflicts=[], partial_discovery=False,
                                   selected_raw_version="", base_raw_version="", old_lefs=[], new_lefs=[],
                                   old_lef_choices=[], new_lef_choices=[], liberty_choices=[],
                                   quick_checks={}, quick_notes=[], default_target_lef="", default_base_lef="",
                                   file_choices_limited=False,
                                   active_tab="catalog", active_review_tab="files",
                                   lef_file_status={"status": "NOT_REFRESHED", "files": [], "stale": False,
                                                    "raw_scope": {}, "nl_context": {}},
                                   file_status_error=""), 400

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
            review_tab = _text(request.form, "review_tab") or "config"
            if review_tab not in {"files", "config", "history"}:
                review_tab = "config"
            return redirect(url_for("ip_review.index", ip=entry["id"], tab="review",
                                    raw_version=entry.get("raw_version") or None,
                                    base_raw_version=_text(request.form, "base_raw_version") or None,
                                    review_tab=review_tab, saved="1"), code=303)
        except Exception as exc:
            return page(_text(request.form, "id"), error=str(exc), active_tab="review",
                        active_review_tab=_text(request.form, "review_tab") or "config"), 400

    @blueprint.post("/discover")
    def discover():
        if not _is_loopback_request():
            abort(403)
        raw_root = _text(request.form, "raw_root")
        try:
            raw_root = _resolve_registry_path(raw_root, registry_file)
            report = discover_raw_report(raw_root)
            report["generated_at"] = datetime.now(timezone.utc).isoformat()
            candidates = report["candidates"]
            write_discovery_artifacts(report, output / "discovery")
            return redirect(url_for("ip_review.index", tab="discover", discovery="latest"), code=303)
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
            discovery["generated_at"] = datetime.now(timezone.utc).isoformat()
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
            write_discovery_artifacts(discovery, output / "discovery")
            return redirect(url_for("ip_review.index", ip=first_id, tab="catalog",
                                    registered="1"), code=303)
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
        return redirect(url_for("ip_review.index", tab="catalog", removed="1"), code=303)

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
            return redirect(url_for("ip_review.index", ip=ip_id, tab="formal-nl",
                                    formal_scanned="1", formal_stage=stage or None), code=303)
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
            if _text(request.form, "mode") == "matrix":
                if not previous or str(previous.get("library_id") or previous.get("id")) != _text(request.form, "library_id"):
                    raise ValueError("矩阵检查需要已登记且匹配的库")
                library_id = str(previous.get("library_id") or previous.get("id"))
                overview = _read_formal_nl_snapshot(output, registry)
                status = _read_lef_file_status(output, registry, previous, overview)
                projection = _read_file_version_projection(output, library_id, status)
                if status.get("stale") or not projection or projection.get("snapshot_id") != _text(request.form, "snapshot_id"):
                    raise ValueError("文件矩阵快照已变化或过期；请刷新后重新选择")
                scope = projection.get("scope") or {}
                base, target = str(scope.get("base_version") or ""), str(scope.get("target_version") or "")
                keys = request.form.getlist("file_key")
                if not 1 <= len(keys) <= 50 or len(set(keys)) != len(keys):
                    raise ValueError("请选择 1 至 50 个唯一文件")
                selected_rows = []
                for key in keys:
                    rows = [row for row in projection.get("files") or [] if row.get("file_key") == key]
                    if len(rows) != 1:
                        raise ValueError("所选文件不属于当前矩阵")
                    selected_rows.append(rows[0])
                projection_ref = str(output / "file_versions" / _library_dir(library_id) /
                                     "runs" / projection["snapshot_id"] / "projection.json")
                if base and target:
                    for row in selected_rows:
                        if row.get("view") != "lef" or row.get("identity_status") != "EXACT_RELATIVE_PATH":
                            raise ValueError("所选 LEF 不是可确认的唯一配对；请重新选择")
                    entry = {**previous, "raw_version": target, "formal_stage": scope.get("formal_stage") or "",
                             "projection_json": projection_ref,
                             "checks": {"lef_review": {"pairs": [{"file_key": key} for key in keys]}}}
                else:
                    if len(keys) != 1:
                        raise ValueError("单版本 LEF–Liberty 接口检查一次只能选择一个 LEF 文件")
                    if any(not row.get("capabilities", {}).get("lef_checkable") for row in selected_rows):
                        raise ValueError("所选文件尚未形成可执行的单文件 LEF 检查目标；请先确认交付顺序或选择 Base / Target")
                    target_versions = set()
                    target_paths = []
                    for row in selected_rows:
                        latest = row.get("latest") or {}
                        occurrence = latest if latest.get("version") else ((row.get("occurrences") or [None])[0] or {})
                        target_versions.add(str(occurrence.get("version") or ""))
                        target_paths.append(str(occurrence.get("source_path") or ""))
                    target_versions.discard("")
                    if len(target_versions) != 1 or any(not path for path in target_paths):
                        raise ValueError("单文件 LEF 检查需要同一目标交付中的可定位文件")
                    single_target = next(iter(target_versions))
                    checks, _ = _quick_linked_checks(previous, single_target, "", target_paths[0], "")
                    checks.pop("macro_index", None)
                    if "lef_liberty_check" not in checks:
                        raise ValueError("目标交付未发现可用于 LEF 接口检查的 Liberty 文件；可转到手动检查补充路径")
                    single_projection = reproject_projection(
                        projection, base_version="", target_version=single_target)
                    single_projection["input_snapshot_id"] = projection["snapshot_id"]
                    single_projection["snapshot_id"] = f"{projection['snapshot_id']}_single_{uuid4().hex}"
                    single_projection_path = (output / "file_versions" / _library_dir(library_id) /
                                              "runs" / projection["snapshot_id"] /
                                              f"single_target_{uuid4().hex}.json")
                    _write_json(single_projection_path, single_projection)
                    entry = {**previous, "raw_version": single_target, "formal_stage": scope.get("formal_stage") or "",
                             "projection_json": str(single_projection_path),
                             "checks": {"lef_liberty_check": checks["lef_liberty_check"]}}
            else:
                entry = _entry_from_form(request.form, previous)
            _validate_for_run(entry)
            lef_check = entry["checks"].get("lef_review") or {}
            interface_check = entry["checks"].get("lef_liberty_check") or {}
            if not lef_check.get("report_json") and lef_check.get("new_file") and interface_check.get("lef_file"):
                target = _resolve_registry_path(lef_check["new_file"], registry_file)
                interface = _resolve_registry_path(interface_check["lef_file"], registry_file)
                if target != interface:
                    raise ValueError("接口核查 LEF 与 LEF 对比目标文件不一致；请统一输入或分别运行")
            if previous and entry["library_id"] != previous["library_id"]:
                raise ValueError("库标识与已登记记录不一致")
            lef_spec = entry.get("checks", {}).get("lef_review")
            if lef_spec:
                comparison_scope = _lef_comparison_scope(
                    lef_spec.get("old_file"), lef_spec.get("new_file"),
                    registry.get("ips") or [], registry_file)
                if comparison_scope:
                    lef_spec["comparison_scope"] = comparison_scope
            with _SUBMISSION_LOCK:
                library_id = entry["library_id"]
                if not _REVIEW_TASK_SLOTS.acquire(blocking=False):
                    return page(entry["id"], error="检查队列已满（最多 8 个排队或运行任务），请稍后提交。",
                            active_tab="review", active_review_tab=_text(request.form, "review_tab") or "config"), 429
                slot_reserved = True
                library_lock = _acquire_library_lock(output, library_id)
                if library_lock is None:
                    _REVIEW_TASK_SLOTS.release()
                    slot_reserved = False
                    return page(entry["id"], error="该 IP 已有检查任务正在其他工作台中运行；请等待完成后再提交。",
                                active_tab="review", active_review_tab=_text(request.form, "review_tab") or "config"), 409
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
                                    active_tab="review", active_review_tab=_text(request.form, "review_tab") or "config"), 409
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
                    }, "已完成", f"检查完成；执行结果：{ {'COMPLETE': '完成', 'INCOMPLETE': '不完整', 'FAILED': '失败'}.get(conclusion, '待核实') }；质量判断：{quality_label}。"
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
            review_tab = _text(request.form, "review_tab")
            if review_tab not in {"files", "config", "history"}:
                review_tab = "config"
            return redirect(url_for("ip_review.index", ip=entry["id"], tab="review",
                                    raw_version=entry.get("raw_version") or None,
                                    base_raw_version=_text(request.form, "base_raw_version") or None,
                                    review_tab=review_tab,
                                    submitted="1"), code=303)
        except Exception as exc:
            if slot_reserved:
                _REVIEW_TASK_SLOTS.release()
            _release_library_lock(library_lock)
            return page(_text(request.form, "id"), error=str(exc), active_tab="review",
                        active_review_tab=_text(request.form, "review_tab") or "config"), 400

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

    @blueprint.get("/review-evidence/<review_id>/<pair_id>")
    def review_pair_evidence(review_id: str, pair_id: str):
        library_id = request.args.get("library_id", "")
        registry = _read_registry(registry_file)
        if library_id not in {str(item.get("library_id") or item.get("id")) for item in registry.get("ips", [])}:
            abort(404)
        if not re.fullmatch(r"review_[A-Za-z0-9_-]+", review_id) or not re.fullmatch(r"[0-9a-f]{24}", pair_id):
            abort(404)
        run_dir = output / "libraries" / _library_dir(library_id) / "runs" / review_id
        target = run_dir / "evidence" / "lef_batch" / f"{pair_id}.json"
        if not target.is_file() or not target.resolve().is_relative_to(run_dir.resolve()):
            abort(404)
        return send_file(target, mimetype="application/json", as_attachment=False)

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
