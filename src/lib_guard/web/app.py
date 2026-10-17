"""Flask entrypoint for the small Lib Guard desktop console."""

from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import Any, Mapping
import json
import os
import secrets
import shlex
import subprocess
import sys
import threading
import time

try:
    from flask import Flask, jsonify, render_template, request, send_from_directory
except ModuleNotFoundError as exc:  # pragma: no cover - exercised by dependency smoke
    raise ModuleNotFoundError(
        "Flask is required for the web console. Install with: python -m pip install -r requirements-web.txt"
    ) from exc

from .read_model import (
    _pending_window,
    list_file_diff_page,
    list_file_tree_rows,
    list_library_candidate_rows,
    list_library_rows,
    list_release_library_rows,
    release_stage_detail,
    list_version_rows,
    load_web_state,
)
from .release_actions import build_release_web_args
from .semantic_actions import prepare_semantic_job, semantic_review_options
from lib_guard.atomic import atomic_write_json, atomic_write_text
from lib_guard.effective.release_set import (
    build_release_set_manifest,
    compare_release_sets,
    write_release_set_manifest,
)
from lib_guard.library_registry import LIST_COLUMNS, write_library_rows
from lib_guard.project_config import (
    HASH_POLICIES,
    MAX_PARSE_JOBS,
    MIN_PARSE_JOBS,
    WEB_ACTION_SPECS,
    WEB_COMPARE_DEFAULTS,
    WEB_COMPARE_MODES,
    WEB_MARK_TYPES,
    WEB_MUTATING_ACTIONS,
    WEB_PACKAGE_TYPES,
    WEB_STAGES,
    default_discovery_strategy,
    default_scan_strategy,
    file_diff_allowed,
    file_diff_requires_force_large,
    web_action_catalog,
)
from lib_guard.review.update_notes import load_update_note, review_notes_root, save_update_note
from lib_guard.short_cli_config import find_config, load_config, update_config_file, write_default_config


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(path, dict(payload), lock=True)


def _safe_component(value: str) -> str:
    if not value or value in {".", ".."} or "/" in value or "\\" in value:
        raise ValueError("invalid path component")
    return value


def _safe_library_token(value: str) -> str:
    """Validate a catalog library identifier without treating it as a path.

    Typed library IDs (for example ``ip/vendor.ucie``) are stable Catalog
    tokens and are valid CLI arguments.  They must not be passed to helpers
    that create filesystem paths, but catalog lookups still require every
    component to be non-empty and non-traversing.
    """

    text = str(value or "").strip()
    parts = text.split("/")
    if not text or "\\" in text or any(part in {"", ".", ".."} for part in parts):
        raise ValueError("invalid library token")
    return text


def _safe_relative_path(value: Any, *, label: str = "相对路径") -> str:
    text = _bounded_text(value, label=label, limit=500).replace("\\", "/")
    path = PurePosixPath(text)
    if not text or path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError(f"{label}必须是库版本目录内的相对路径")
    return path.as_posix()


def _bounded_int(value: Any, *, label: str, minimum: int, maximum: int, default: int) -> int:
    if value is None or value == "":
        return default
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label}必须是整数") from exc
    if not minimum <= number <= maximum:
        raise ValueError(f"{label}必须在 {minimum} 到 {maximum} 之间")
    return number


_JOB_STATUSES = {"QUEUED", "RUNNING", "COMPLETED", "FAILED"}
_MAX_BROWSE_CHILDREN = 500
_MAX_MACHINE_RESULT_BYTES = 8 * 1024 * 1024


def _bounded_text(value: Any, *, label: str, limit: int = 400) -> str:
    text = str(value or "").strip()
    if len(text) > limit:
        raise ValueError(f"{label} 过长，最多 {limit} 个字符")
    return text


def _payload_bool(payload: Mapping[str, Any], key: str, *, default: bool = False) -> bool:
    """Keep JSON boolean options from being changed by Python truthiness."""

    if key not in payload:
        return default
    value = payload[key]
    if not isinstance(value, bool):
        raise ValueError(f"{key} 必须是 JSON 布尔值 true 或 false")
    return value


def _read_tail(path: Path, *, max_bytes: int = 16_000, max_lines: int = 120) -> str:
    """Read only the tail of a job log so polling stays bounded for long runs."""

    try:
        with path.open("rb") as handle:
            handle.seek(0, 2)
            size = handle.tell()
            handle.seek(max(0, size - max_bytes))
            content = handle.read().decode("utf-8", errors="replace")
    except OSError:
        return ""
    lines = content.replace("\r", "\n").splitlines()
    return "\n".join(lines[-max_lines:])


def _browse_roots(web_state: Mapping[str, Any]) -> list[Path]:
    """Return the only filesystem roots the web directory picker may expose."""

    paths = web_state.get("paths") if isinstance(web_state.get("paths"), Mapping) else {}
    roots: list[Path] = []
    seen: set[Path] = set()
    for key in ("raw_root", "workspace"):
        value = str(paths.get(key) or "").strip()
        if not value:
            continue
        root = Path(value).expanduser().resolve()
        if root.is_dir() and root not in seen:
            seen.add(root)
            roots.append(root)
    return roots


def _path_is_within(path: Path, roots: list[Path]) -> bool:
    return any(path == root or root in path.parents for root in roots)


def _safe_existing_json_path(path_text: Any, roots: list[Path], *, label: str) -> Path:
    text = _bounded_text(path_text, label=label, limit=1000)
    if not text:
        raise ValueError(f"{label}不能为空")
    path = Path(text).expanduser().resolve()
    if not _path_is_within(path, roots):
        raise ValueError(f"{label}不在当前工作区允许范围内")
    if not path.is_file():
        raise FileNotFoundError(f"{label}不存在：{path}")
    if path.suffix.lower() != ".json":
        raise ValueError(f"{label}必须是 JSON 文件")
    return path


def _safe_existing_file_path(path_text: Any, roots: list[Path], *, label: str) -> Path:
    text = _bounded_text(path_text, label=label, limit=1000)
    if not text:
        raise ValueError(f"{label}不能为空")
    path = Path(text).expanduser()
    if not path.is_absolute():
        raise ValueError(f"{label}必须使用绝对路径")
    resolved = path.resolve()
    if not _path_is_within(resolved, roots):
        allowed = "；".join(str(root) for root in roots) or "未配置"
        raise ValueError(f"{label}不在当前允许范围内。当前允许范围：{allowed}")
    if not resolved.is_file():
        raise FileNotFoundError(f"{label}不存在或不是文件：{resolved}")
    return resolved


def _browse_directory(path_text: str | None, roots: list[Path]) -> dict[str, Any]:
    if not roots:
        raise OSError("没有可浏览的配置目录")
    if path_text:
        requested = Path(path_text).expanduser()
        if not requested.is_absolute():
            raise ValueError("浏览目录必须使用绝对路径")
        current = requested.resolve()
    else:
        current = roots[0]
    if not _path_is_within(current, roots):
        raise ValueError("目录不在允许范围内：只能浏览原始库根和工作区")
    if not current.exists():
        raise FileNotFoundError(f"目录不存在：{current}")
    if not current.is_dir():
        raise NotADirectoryError(f"不是目录：{current}")

    children: list[dict[str, str]] = []
    try:
        entries = sorted(current.iterdir(), key=lambda item: item.name.casefold())
    except OSError as exc:
        raise OSError(f"无法读取目录：{current}") from exc
    for entry in entries:
        if entry.name.startswith(".") or not entry.is_dir():
            continue
        resolved = entry.resolve()
        if not _path_is_within(resolved, roots):
            continue
        children.append({"name": entry.name, "path": str(resolved)})
        if len(children) >= _MAX_BROWSE_CHILDREN:
            break

    parent = current.parent.resolve()
    parent_path = str(parent) if parent != current and _path_is_within(parent, roots) else None
    return {
        "current_path": str(current),
        "parent_path": parent_path,
        "roots": [str(root) for root in roots],
        "children": children,
        "truncated": len(children) >= _MAX_BROWSE_CHILDREN,
    }


def _workspace_setup_payload(cwd: str | Path | None, error: Exception) -> dict[str, Any]:
    cwd_path = Path(cwd or Path.cwd()).expanduser().resolve()
    scan_defaults = default_scan_strategy()
    discovery_defaults = default_discovery_strategy()
    return {
        "status": "NEEDS_INIT",
        "setup_required": True,
        "catalog_state": "CONFIG_MISSING",
        "catalog_source": "not_initialized",
        "message": "未能连接工作区配置。已有库和扫描记录无需重做：请连接原工作区目录，或启动时用 --config 指定原 lib_guard.yml；仅新工作区需要初始化。",
        "error": str(error),
        "paths": {
            "workspace": "",
            "raw_root": "",
            "catalog": "",
            "catalog_html": "",
            "reports": "",
            "diff": "",
            "cwd": str(cwd_path),
        },
        "scan_strategy": {
            "hash_policy": scan_defaults["hash_policy"],
            "parse_jobs": scan_defaults["parse_jobs"],
            "force_hash_file_types": scan_defaults["force_hash_file_types"],
            "skip_hash_file_types": scan_defaults["skip_hash_file_types"],
            "parse_file_types": scan_defaults["parse_file_types"],
            "parse_exclude_file_types": scan_defaults["parse_exclude_file_types"],
            "render_detail": scan_defaults["render_detail"].lower() == "true",
        },
        "discovery_strategy": {
            "max_depth": discovery_defaults["max_depth"],
            "min_versions": discovery_defaults["min_versions"],
            "max_dirs": discovery_defaults["max_dirs"],
            "max_candidates": discovery_defaults["max_candidates"],
        },
        "runtime_state": {},
        "write_policy": "web_actions_are_allowlisted",
        "web_actions": web_action_catalog(),
    }


def _progress_files(roots: Any) -> list[Path]:
    """Resolve bounded scan progress locations recorded by the Web job creator."""

    if not isinstance(roots, list):
        return []
    files: list[Path] = []
    seen: set[str] = set()
    for value in roots[:8]:
        if not isinstance(value, str) or not value:
            continue
        root = Path(value).expanduser()
        candidates = [root] if root.name == "scan_progress_latest.json" else [
            root / "logs" / "scan_progress_latest.json",
            *root.glob("*/logs/scan_progress_latest.json"),
        ]
        for candidate in candidates:
            key = str(candidate)
            if key not in seen and candidate.is_file():
                seen.add(key)
                files.append(candidate)
    return files


def _load_progress(request_data: Mapping[str, Any]) -> dict[str, Any]:
    observability = request_data.get("observability")
    roots = None
    if isinstance(observability, Mapping):
        # progress_paths keeps older Web job records observable after an upgrade.
        roots = observability.get("progress_roots") or observability.get("progress_paths")
    candidates = _progress_files(roots)
    newest = max(candidates, key=lambda path: path.stat().st_mtime, default=None)
    if newest is not None:
        try:
            loaded = json.loads(newest.read_text(encoding="utf-8"))
        except (OSError, TypeError, ValueError):
            loaded = None
        if isinstance(loaded, Mapping):
            keys = (
                "event", "stage", "message", "status", "done", "total", "percent",
                "summary", "by_type", "active_workers", "performance", "scan_id", "out_dir",
            )
            progress = {key: loaded[key] for key in keys if key in loaded}
            progress["source"] = str(newest)
            return progress
    return {
        "event": "waiting",
        "stage": "等待子任务输出",
        "message": "尚未收到阶段进度；可查看运行日志尾部。",
        "done": None,
        "total": None,
        "percent": None,
        "source": None,
    }


def _job_observation(job_dir: Path, status: Mapping[str, Any]) -> dict[str, Any]:
    request_data: Mapping[str, Any] = {}
    request_path = job_dir / "request.json"
    try:
        loaded = json.loads(request_path.read_text(encoding="utf-8")) if request_path.exists() else {}
        if isinstance(loaded, Mapping):
            request_data = loaded
    except (OSError, TypeError, ValueError):
        pass
    started = status.get("started_epoch") or status.get("created_epoch")
    finished = status.get("finished_epoch")
    end = finished if isinstance(finished, (int, float)) else time.time()
    elapsed = round(max(0.0, end - started), 3) if isinstance(started, (int, float)) else None
    log_path = job_dir / "stdout.log"
    return {
        "elapsed_seconds": elapsed,
        "log_tail": _read_tail(log_path, max_bytes=8_000, max_lines=80),
        "log_bytes": log_path.stat().st_size if log_path.is_file() else 0,
        "progress": _load_progress(request_data),
    }


def _job_failure_summary(output: str) -> str:
    """Turn structured CLI failure output into a short operator-facing reason."""

    text = output.strip()
    loaded: Mapping[str, Any] | None = None
    if text:
        try:
            candidate = json.loads(text)
        except (TypeError, ValueError):
            candidate = None
        if isinstance(candidate, Mapping):
            loaded = candidate

    if loaded is not None:
        release_status = str(loaded.get("release_check_status") or "").upper()
        if release_status in {"BLOCK", "BLOCKED", "FAILED", "FAIL"}:
            reasons = [str(item).strip() for item in loaded.get("block_reasons", []) if str(item).strip()]
            if reasons:
                return "发布检查被阻塞：" + "；".join(reasons[:3])
            return "发布检查被阻塞；请查看完整运行日志中的门禁项。"
        for key, label in (("scan_error", "扫描失败"), ("error", "任务失败"), ("message", "任务结果")):
            value = loaded.get(key)
            if value:
                if isinstance(value, Mapping):
                    message = str(value.get("message") or value.get("type") or "未知错误")
                    if value.get("type") == "PermissionError":
                        return f"{label}：无权读取文件或目录；请联系目录负责人授予读取权限。具体路径：{message}"[:500]
                    return f"{label}：{message}"[:240]
                return f"{label}：{str(value).strip()}"[:240]

    for line in reversed(text.splitlines()):
        clean = line.strip()
        if "scan_error" in clean.lower() or clean.lower().startswith(("error:", "fatal:")):
            return clean[:240]
    return "底层任务失败；请打开运行日志查看完整输出。"


def _list_setting(value: Any, *, label: str) -> str:
    if isinstance(value, (list, tuple, set)):
        value = ",".join(str(item).strip() for item in value if str(item).strip())
    text = _bounded_text(value, label=label, limit=300)
    if text and any(char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.,- " for char in text):
        raise ValueError(f"{label} 只允许文件类型名称、逗号、空格和连字符")
    return text


_UPDATE_NOTE_TEXT_LIMITS = {
    "summary": ("备注摘要", 1200),
    "updated_by": ("更新人", 80),
}
_UPDATE_NOTE_LIST_LIMITS = {
    "impact_areas": ("影响场景", 24, 120),
    "key_changes": ("关键变化", 24, 300),
    "risks": ("风险提醒", 24, 300),
    "must_check": ("必须确认", 24, 300),
    "evidence_refs": ("证据引用", 24, 240),
}


def _validate_update_note_payload(payload: Mapping[str, Any]) -> None:
    """Reject invalid note input before it can overwrite useful human notes."""

    for key, (label, limit) in _UPDATE_NOTE_TEXT_LIMITS.items():
        _bounded_text(payload.get(key), label=label, limit=limit)
    suggestion = _bounded_text(payload.get("use_suggestion") or "待确认", label="使用建议", limit=40)
    if suggestion not in {"推荐使用", "条件使用", "暂缓使用", "待确认"}:
        raise ValueError("使用建议只能是：推荐使用、条件使用、暂缓使用、待确认")
    for key, (label, max_items, item_limit) in _UPDATE_NOTE_LIST_LIMITS.items():
        value = payload.get(key)
        if value is None or value == "":
            continue
        items = value if isinstance(value, list) else str(value).replace("；", "\n").replace(";", "\n").splitlines()
        if not isinstance(items, list):
            raise ValueError(f"{label}必须是列表或文本")
        if len(items) > max_items:
            raise ValueError(f"{label}最多 {max_items} 条")
        for index, item in enumerate(items, start=1):
            text = item.get("text") if isinstance(item, Mapping) else item
            _bounded_text(text, label=f"{label}第 {index} 条", limit=item_limit)


def _append_effective_selection(args: list[str], payload: Mapping[str, Any]) -> None:
    base = payload.get("base_full")
    includes = payload.get("includes", [])
    if not isinstance(includes, list) or any(not isinstance(vid, str) for vid in includes):
        raise ValueError("增量包选择必须是有序版本列表")
    if includes and not base:
        raise ValueError("请先选择完整包基线")
    if base is not None:
        args.extend(["--base-full", _safe_component(_bounded_text(base, label="完整包基线", limit=180))])
        args.append("--json")
    for vid in includes:
        args.extend(["--include", _safe_component(_bounded_text(vid, label="叠加版本", limit=180))])


def _append_scan_settings(args: list[str], payload: Mapping[str, Any], *, include_no_render: bool = True) -> None:
    hash_policy = _bounded_text(payload.get("hash_policy"), label="哈希策略")
    if hash_policy:
        if hash_policy not in HASH_POLICIES:
            raise ValueError("哈希策略只能是 none、smart 或 full")
        args.extend(["--hash-policy", hash_policy])
    parse_jobs = payload.get("parse_jobs")
    if parse_jobs not in {None, ""}:
        try:
            jobs = int(parse_jobs)
        except (TypeError, ValueError) as exc:
            raise ValueError("解析并发数必须是 1 到 32 的整数") from exc
        if not MIN_PARSE_JOBS <= jobs <= MAX_PARSE_JOBS:
            raise ValueError(f"解析并发数必须是 {MIN_PARSE_JOBS} 到 {MAX_PARSE_JOBS} 的整数")
        args.extend(["--parse-jobs", str(jobs)])
    for key, flag, label in (
        ("force_hash_file_types", "--force-hash-file-types", "强制完整哈希类型"),
        ("skip_hash_file_types", "--skip-hash-file-types", "跳过完整哈希类型"),
        ("parse_file_types", "--parse-file-types", "解析文件类型"),
        ("parse_exclude_file_types", "--parse-exclude-file-types", "排除文件类型"),
    ):
        value = _list_setting(payload.get(key), label=label)
        if value:
            args.extend([flag, value])
    if include_no_render and _payload_bool(payload, "no_render"):
        args.append("--no-render")


def parse_machine_result(stdout_path: Path) -> dict[str, Any] | None:
    """Read the final structured CLI result without interpreting log prose."""

    try:
        with stdout_path.open("rb") as handle:
            handle.seek(0, 2)
            size = handle.tell()
            handle.seek(max(0, size - _MAX_MACHINE_RESULT_BYTES))
            text = handle.read().decode("utf-8", errors="replace")
    except OSError:
        return None

    decoder = json.JSONDecoder()
    starts: list[int] = []
    offset = 0
    for line in text.splitlines(keepends=True):
        stripped = line.lstrip()
        if stripped.startswith("{"):
            starts.append(offset + len(line) - len(stripped))
        offset += len(line)
    for start in reversed(starts):
        try:
            value, end = decoder.raw_decode(text, start)
        except json.JSONDecodeError:
            continue
        if isinstance(value, Mapping) and not text[end:].strip():
            return dict(value)
    return None


def _record_machine_result(job_dir: Path, return_code: int) -> dict[str, Any] | None:
    result = parse_machine_result(job_dir / "stdout.log")
    if result is None:
        return None
    result_path = job_dir / "result.json"
    _write_json(
        result_path,
        {
            "schema_version": "web_job_result.v1",
            "result": "ok" if return_code == 0 else "failed",
            "exit_code": return_code,
            "cli_result": result,
        },
    )
    return result


def _load_cli_result(job_dir: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads((job_dir / "result.json").read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError):
        return None
    result = payload.get("cli_result") if isinstance(payload, Mapping) else None
    return dict(result) if isinstance(result, Mapping) else None


def _job_artifact_map(job_dir: Path) -> dict[str, dict[str, Any]]:
    """Return human-facing files produced by a completed job.

    The CLI is still the source of truth.  The web layer only projects known
    result fields into bounded links, and the serving route validates the final
    path against configured workspace roots.
    """

    result = _load_cli_result(job_dir)
    if not result:
        return {}
    candidates: list[tuple[str, str, Any, str]] = []
    if result.get('schema_version') == 'semantic_summary.v1':
        report_root = job_dir / 'semantic_review'
        files = result.get('artifacts') or {}
        candidates.extend([
            ('markdown', '下载技术检查摘要（Markdown）', report_root / files['markdown'], 'markdown'),
            ('semantic_checks', '下载完整检查结果（JSON）', report_root / files['check_results'], 'json'),
            ('semantic_index', '下载对象与来源索引（JSON）', report_root / files['semantic_effective_index'], 'json'),
        ])
    scan_html = result.get("scan_html")
    if isinstance(scan_html, Mapping):
        candidates.append(("scan_html", "扫描 HTML 报告", scan_html.get("index_html"), "html"))
    out_dir = result.get("out_dir")
    if out_dir:
        out_root = Path(str(out_dir)).expanduser()
        candidates.append(("raw_text_diff", "双栏文本对比", out_root / "raw_text_diff.html", "html"))
    candidates.extend([
        ("html", "HTML 对比报告", result.get("html"), "html"),
        ("markdown", "Markdown 摘要", result.get("markdown"), "markdown"),
        ("export", "导出对比结果", result.get("export"), "zip"),
        ("pairwise_result", "结构化结果 JSON", result.get("pairwise_result"), "json"),
        ("release_manifest", "发布计划清单", result.get("manifest"), "json"),
    ])
    if result.get("manifest"):
        manifest_path = Path(str(result["manifest"])).expanduser()
        candidates.extend([
            ("release_result", "发布结果", manifest_path.parent / "release_result.json", "json"),
            ("release_link_result", "发布链接清单", manifest_path.parent / "release_link_result.json", "json"),
        ])
    if out_dir:
        candidates.extend(
            [
                ("semantic_diff", "语义差异 JSON", out_root / "semantic_diff.json", "json"),
            ]
        )
    artifacts: dict[str, dict[str, Any]] = {}
    for artifact_id, label, value, kind in candidates:
        if not value:
            continue
        path = Path(str(value)).expanduser().resolve()
        if not path.is_file():
            continue
        artifacts[artifact_id] = {
            "id": artifact_id,
            "label": label,
            "kind": kind,
            "path": str(path),
            "url": f"/api/runs/{job_dir.name}/artifact/{artifact_id}",
        }
        if result.get('schema_version') == 'semantic_summary.v1':
            artifacts[artifact_id]['download'] = True
    return artifacts


def _release_plan_projection(result: Mapping[str, Any], request_data: Mapping[str, Any]) -> dict[str, Any] | None:
    """Project CLI preview or publication facts without implementing release logic."""

    if not bool(result.get("dry_run")) and request_data.get("action") not in {"release-apply", "release-force", "release-set-apply"}:
        return None
    link_result = result.get("link_result") if isinstance(result.get("link_result"), Mapping) else {}
    if not link_result and not result.get("manifest"):
        return None
    summary = link_result.get("summary") if isinstance(link_result.get("summary"), Mapping) else {}
    link_status = str(result.get("link_status") or link_result.get("status") or "UNKNOWN").upper()
    args = request_data.get("args") if isinstance(request_data.get("args"), list) else []
    rel_index = next((index for index, item in enumerate(args) if item == "rel"), -1)
    final_args = [str(item) for item in args[rel_index:] if rel_index >= 0 and item != "--no-render"]
    if final_args and "--apply" not in final_args:
        final_args.append("--apply")
    formal_release_target = request_data.get("formal_release_target")
    target = (
        {
            "library_id": str(formal_release_target.get("library_id") or ""),
            "release_id": str(formal_release_target.get("release_id") or ""),
            "version_id": str(formal_release_target.get("version_id") or ""),
            "source": str(formal_release_target.get("source") or ""),
        }
        if isinstance(formal_release_target, Mapping)
        else None
    )
    return {
        "status": link_status,
        "scope": "release_set" if request_data.get("action") in {"release-set-plan", "release-set-apply"} else "version",
        "dry_run": bool(result.get("dry_run")),
        "verify_status": str(result.get("verify_status") or "未执行"),
        "library": str(request_data.get("library") or ""),
        "version": str(request_data.get("version") or ""),
        "release_root": str(result.get("release_root") or link_result.get("release_root") or ""),
        "alias": str(result.get("alias") or link_result.get("alias") or "current"),
        "link_mode": str(link_result.get("mode") or "symlink"),
        "overwrite": bool(result.get("overwrite") or link_result.get("overwrite")),
        "planned_files": int(summary["planned_files"]) if summary.get("planned_files") is not None else None,
        "failed_files": int(summary["failed_files"]) if summary.get("failed_files") is not None else None,
        "skipped_files": int(summary.get("skipped_files") or 0),
        "excluded_files": int(summary.get("excluded_files") or 0),
        "excluded_rows": [
            {key: str(row.get(key) or "") for key in ("source_path", "reason")}
            for row in link_result.get("excluded_files", []) if isinstance(row, Mapping)
        ],
        "created_files": int(summary.get("created_files") or 0),
        "manifest": str(result.get("manifest") or link_result.get("manifest_path") or ""),
        "target_alias": str(link_result.get("target_alias") or ""),
        "release_dir": str(link_result.get("release_dir") or ""),
        "daily_backup": str(link_result.get("daily_backup") or ""),
        "publish_name": str(link_result.get("publish_name") or ""),
        "latest_name": str(link_result.get("latest_name") or ""),
        "link_rows": [
            {key: str(row.get(key) or "") for key in (
                "relative_path", "file_type", "status", "link_action", "link_path", "target_path", "previous_target", "warning", "error", "library_name", "version_id"
            )}
            for row in [*(link_result.get("created_links") or []), *(link_result.get("failed_links") or []), *(link_result.get("skipped_links") or [])]
            if isinstance(row, Mapping)
        ],
        "final_cli_command": "lg " + shlex.join(final_args) if final_args else "",
        "formal_release_target": target,
        "issues": list({
            (str(issue.get("message") or issue.get("error") or ""), str(issue.get("file") or issue.get("relative_path") or "")): {
                "message": str(issue.get("message") or issue.get("error") or ""),
                "file": str(issue.get("file") or issue.get("relative_path") or ""),
            }
            for issue in [*(result.get("verify_issues") or []), *((link_result.get("verify") or {}).get("issues") or []), *(link_result.get("failed_links") or []), *(link_result.get("skipped_links") or [])]
            if isinstance(issue, Mapping) and (issue.get("message") or issue.get("error"))
        }.values()),
    }


def _job_result_summary(job_dir: Path) -> str:
    """Return one bounded operator-facing sentence from the structured result."""

    result = _load_cli_result(job_dir)
    if not result:
        return ""

    link = result.get("link_result")
    if result.get('schema_version') == 'semantic_summary.v1':
        return '技术检查任务完成，报告文件已保存；执行成功不代表检查全部通过。'
    if isinstance(link, Mapping):
        link_status = str(link.get("status") or result.get("link_status") or "").upper()
        verification = str(result.get("verify_status") or (link.get("verify") or {}).get("status") or "")
        count = (link.get("summary") or {}).get("planned_files")
        count_text = f" · {count} 个文件" if count is not None else ""
        if link_status in {"PARTIAL_DRY_RUN", "PARTIAL_APPLIED"}:
            skipped = (link.get("summary") or {}).get("skipped_files", 0)
            created = (link.get("summary") or {}).get("created_files", 0)
            return f"{'预演完成，尚未发布' if result.get('dry_run') else '部分发布完成'} · {'拟交付' if result.get('dry_run') else '已交付'} {created} 个文件 · 同名冲突跳过 {skipped} 个文件"
        if bool(result.get("dry_run")):
            return ("预演完成，尚未发布" if link_status in {"DRY_RUN", "FORCE_DRY_RUN"} else "预演未通过，未发布") + count_text
        if link_status in {"APPLIED", "FORCED_APPLIED"}:
            return "已执行发布" + count_text + (" · 链接校验通过" if verification in {"PASS", "PASS_WITH_WARNING"} else " · 链接校验未完成或未通过")
        return "发布未完成 · 请核对异常及原发布入口"

    release_status = str(result.get("release_check_status") or "").upper()
    release_labels = {
        "PASS": "发布检查通过",
        "PASS_WITH_WARNING": "发布检查通过（有提醒）",
        "BLOCK": "发布检查未通过",
        "BLOCKED": "发布检查未通过",
        "FAILED": "发布检查失败",
    }
    if release_status:
        summary = release_labels.get(release_status, f"发布检查：{release_status}")
        version = str(result.get("version") or "").strip()
        reasons = [str(item).strip() for item in result.get("block_reasons", []) or [] if str(item).strip()]
        if version:
            summary += f" · {version}"
        if reasons:
            summary += " · " + "；".join(reasons[:2])
        return summary[:240]

    status = str(result.get("status") or "").upper()
    if status in {"FAILED", "ERROR", "UNSUPPORTED", "EMPTY"}:
        operation = "扫描" if result.get("scan_dir") else "版本对比" if result.get("old_version") else "深度核对" if result.get("pairwise_result") else "任务"
        outcome = "失败" if status in {"FAILED", "ERROR"} else "未完成"
        reason = result.get("scan_error") or result.get("message") or "请查看运行日志中的具体原因"
        return f"{operation}{outcome} · {reason}"[:240]
    pairwise = result.get("summary")
    if result.get("pairwise_result") and isinstance(pairwise, Mapping):
        file_type = str(pairwise.get("file_type") or "文件").upper()
        comparison = str(pairwise.get("status") or status).upper()
        changed = "内容相同" if comparison == "SAME" else "内容有变化" if pairwise.get("changed") is True else "未确认内容一致"
        return f"深度核对完成 · {file_type} · {changed}"[:240]
    if result.get("old_version") and result.get("new_version"):
        return f"版本对比完成 · {result['old_version']} → {result['new_version']}"[:240]
    if result.get("scan_dir") and result.get("version"):
        return f"扫描完成 · {result.get('library') or result.get('library_name') or ''} / {result['version']}"[:240]
    candidate = result.get("candidate_effective")
    if isinstance(candidate, Mapping) and candidate.get("effective_id"):
        updates = " → ".join(candidate.get("overlays", []) or []) or "无叠加更新"
        state_label = "候选已生成，待核对" if result.get("plan_state") == "DONE" else "组合预览"
        return f"{state_label} · 完整包 {candidate.get('base_full') or '未选择'} · 叠加 {updates} · 需补扫 {len(result.get('scan_versions', []) or [])} 个版本"[:400]
    if result.get("current_effective"):
        return "已设为当前可用版本"
    message = str(result.get("message") or "").strip()
    if message:
        return message[:240]
    if status:
        return f"任务结果：{status}"[:240]
    return ""


def _semantic_quality_projection(result: Mapping[str, Any]) -> dict[str, Any] | None:
    """Project a bounded operator summary from the semantic report.

    The semantic CLI remains the only source of truth.  This projection is
    deliberately not a release decision: it only tells the operator whether
    the generated report is complete enough to read and what to do next.
    """

    if result.get("schema_version") != "semantic_summary.v1":
        return None
    counts: dict[str, int] = {}
    delta_counts: dict[str, int] = {}
    for source_key, target in (("counts", counts), ("delta_counts", delta_counts)):
        source = result.get(source_key)
        if not isinstance(source, Mapping):
            continue
        for key, value in source.items():
            try:
                number = int(value)
            except (TypeError, ValueError):
                continue
            if number > 0:
                target[str(key)] = target.get(str(key), 0) + number
    all_counts = {key: counts.get(key, 0) + delta_counts.get(key, 0)
                  for key in set(counts) | set(delta_counts)}

    scope = result.get("scope")
    current = scope.get("current") if isinstance(scope, Mapping) else None
    current = current if isinstance(current, Mapping) else {}
    base = scope.get("base") if isinstance(scope, Mapping) else None
    base_selected = isinstance(base, Mapping)
    coverage = {
        "selected_files": int(current.get("selected_files") or 0),
        "effective_files": int(current.get("effective_files") or 0),
    }
    if all_counts.get("FAIL", 0):
        verdict, label = "FAIL", "发现问题"
        next_action = "先查看报告中的问题明细，再决定是否补证据或修正配置。"
    elif (all_counts.get("INCOMPLETE", 0) or all_counts.get("NOT_CHECKED", 0)
          or all_counts.get("UNKNOWN", 0)):
        verdict, label = "INCOMPLETE", "需要补齐检查"
        next_action = (
            "已选择基准，先补齐未检查项并重新生成报告。"
            if base_selected else
            "当前只核查了目标版本，未形成版本变化结论；选择变化基准后重新生成报告。"
        )
    elif all_counts.get("REVIEW_REQUIRED", 0):
        verdict, label = "REVIEW_REQUIRED", "需要人工确认"
        next_action = "查看人工确认项；这只是技术检查摘要，不代表正式放行。"
    elif result.get("delta_context") == "NO_BASE_EFFECTIVE":
        verdict, label = "INCOMPLETE", "仅检查当前版"
        next_action = "当前版独立检查已形成结果，但未形成版本变化结论；需要变化判断时请选择基准。"
    elif all_counts:
        verdict, label = "PASS", "检查项已形成结果"
        next_action = "可下载 Markdown 摘要核对结果；正式放行仍按既有流程执行。"
    else:
        verdict, label = "EMPTY", "尚未形成结论"
        next_action = "确认检查对象和检查项目后重新生成报告。"
    return {
        "schema_version": "web_quality_summary.v1",
        "verdict": verdict,
        "verdict_label": label,
        "counts": all_counts,
        "detail_counts": counts,
        "delta_counts": delta_counts,
        "coverage": coverage,
        "base_selected": base_selected,
        "next_action": next_action,
        "note": "任务完成只表示报告生成成功，不代表质量通过或正式放行。",
    }


def _job_status(job_dir: Path, process: subprocess.Popen[str] | None) -> dict[str, Any]:
    status_path = job_dir / "status.json"
    status_file_valid = False
    try:
        loaded = json.loads(status_path.read_text(encoding="utf-8")) if status_path.exists() else None
        if isinstance(loaded, Mapping):
            status = dict(loaded)
            status_file_valid = True
        else:
            status = {}
    except (OSError, TypeError, ValueError):
        status = {}
    if process is not None:
        return_code = process.poll()
        if return_code is None:
            status.update({"status": "RUNNING", "pid": process.pid})
        else:
            status.update({
                "status": "COMPLETED" if return_code == 0 else "FAILED",
                "return_code": return_code,
                "finished_epoch": status.get("finished_epoch") or time.time(),
            })
            log_path = job_dir / "stdout.log"
            if log_path.exists():
                text = _read_tail(log_path, max_bytes=64_000, max_lines=1_000)
                machine_result = _record_machine_result(job_dir, return_code)
                if machine_result is not None:
                    status["result_file"] = str(job_dir / "result.json")
                    if machine_result.get("run_manifest"):
                        status["run_manifest"] = str(machine_result["run_manifest"])
                if return_code != 0:
                    failure_source = json.dumps(machine_result, ensure_ascii=False) if machine_result is not None else text
                    status["error"] = _job_failure_summary(failure_source)
            _write_json(status_path, status)
    else:
        current_status = str(status.get("status") or "").upper()
        if current_status in {"QUEUED", "RUNNING"}:
            status.update({
                "status": "FAILED",
                "message": "服务重启后未接管此任务，执行结果无法确认。",
            })
        elif not status_file_valid or not current_status:
            status = {
                "status": "FAILED",
                "message": "任务状态文件缺失或格式损坏，无法确认最终结果。",
            }
        elif current_status not in _JOB_STATUSES:
            status = {
                "status": "FAILED",
                "message": f"任务状态未知（{current_status}），无法确认最终结果。",
            }
        _write_json(status_path, status)
    if str(status.get("status") or "").upper() == "FAILED" and not status.get("error"):
        status["error"] = _job_failure_summary(_read_tail(job_dir / "stdout.log", max_bytes=64_000, max_lines=1_000))
        _write_json(status_path, status)
    result_summary = _job_result_summary(job_dir)
    if result_summary:
        status["result_summary"] = result_summary
    artifacts = list(_job_artifact_map(job_dir).values())
    if artifacts:
        status["artifacts"] = artifacts
    cli_result = _load_cli_result(job_dir)
    request_data: Mapping[str, Any] = {}
    try:
        loaded_request = json.loads((job_dir / "request.json").read_text(encoding="utf-8"))
        if isinstance(loaded_request, Mapping):
            request_data = loaded_request
    except (OSError, TypeError, ValueError):
        pass
    if cli_result is not None:
        if request_data.get('action') == 'file-diff':
            status['file_diff_review'] = {
                'library': request_data.get('library'), 'version': request_data.get('version'),
                'file_type': (cli_result.get('summary') or {}).get('file_type'),
                'eligible': status.get('return_code') == 0 and cli_result.get('status') in {'SAME', 'DIFF'},
            }
        release_plan = _release_plan_projection(cli_result, request_data)
        if release_plan is not None:
            status["release_plan"] = release_plan
        quality_summary = _semantic_quality_projection(cli_result)
        if quality_summary is not None:
            status["quality_summary"] = quality_summary
    status.update(_job_observation(job_dir, status))
    return status


def create_app(
    config_path: str | Path | None = None,
    cwd: str | Path | None = None,
    *,
    test_config: Mapping[str, Any] | None = None,
) -> Flask:
    app = Flask(__name__)
    app.config.from_mapping(
        LIB_GUARD_CONFIG=str(config_path) if config_path else None,
        LIB_GUARD_CWD=str(cwd or Path.cwd()),
        TESTING=False,
        JOB_ROOT=None,
    )
    if test_config:
        app.config.update(test_config)
    jobs: dict[str, subprocess.Popen[str]] = {}
    job_targets: dict[str, str] = {}
    jobs_lock = threading.Lock()
    app.extensions["lib_guard_jobs"] = jobs
    app.extensions["lib_guard_jobs_lock"] = jobs_lock
    workspace_pointer = Path(app.config["LIB_GUARD_CWD"]).resolve() / "work" / "web_workspace.json"

    def workspace_config_path() -> str | None:
        configured = app.config.get("LIB_GUARD_CONFIG")
        if configured or os.environ.get("LIB_GUARD_CONFIG"):
            return configured
        try:
            return str(find_config(app.config["LIB_GUARD_CWD"]).resolve())
        except FileNotFoundError:
            if not workspace_pointer.exists():
                return None
            try:
                saved = json.loads(workspace_pointer.read_text(encoding="utf-8"))
                path = saved["config"]
                if not isinstance(path, str) or not Path(path).is_absolute():
                    raise ValueError("配置路径必须是绝对路径")
            except (ValueError, KeyError, TypeError) as exc:
                raise OSError(f"上次工作区记录无法读取：{workspace_pointer}；请用 --config 指定已有配置。") from exc
            app.config["LIB_GUARD_CONFIG"] = path
            return path

    def state() -> dict[str, Any]:
        return load_web_state(
            config_path=workspace_config_path(),
            cwd=app.config.get("LIB_GUARD_CWD"),
            allow_missing_catalog=True,
        )

    def job_root(web_state: Mapping[str, Any]) -> Path:
        configured = app.config.get("JOB_ROOT") or app.config.get("job_root")
        return Path(configured).expanduser().resolve() if configured else Path(web_state["workspace"]) / "web_jobs"

    def job_root_without_catalog() -> Path:
        configured = app.config.get("JOB_ROOT") or app.config.get("job_root")
        if configured:
            return Path(configured).expanduser().resolve()
        cfg = load_config(app.config.get("LIB_GUARD_CWD") or Path.cwd(), workspace_config_path())
        return Path(cfg["workspace"]).expanduser().resolve() / "web_jobs"

    def request_payload() -> Mapping[str, Any]:
        payload = request.get_json(silent=True)
        if payload is None:
            if request.is_json:
                raise ValueError("请求体中的 JSON 格式无效")
            if request.data:
                raise ValueError("请求体必须是 JSON 对象")
            return {}
        if not isinstance(payload, Mapping):
            raise ValueError("请求体必须是 JSON 对象")
        return payload

    def find_version(web_state: Mapping[str, Any], library: str, version: str) -> dict[str, Any] | None:
        for row in list_version_rows(web_state, library):
            if row["version_id"] == version:
                return row
        return None

    def find_catalog_library(web_state: Mapping[str, Any], library: str) -> Mapping[str, Any] | None:
        """Find a raw catalog library without calculating every library summary."""

        for item in web_state.get("catalog", {}).get("libraries", []) or []:
            if isinstance(item, Mapping) and library in {
                str(item.get("library_name") or ""),
                str(item.get("library_id") or ""),
                str(item.get("typed_library_id") or ""),
            }:
                return item
        return None

    def resolve_catalog_library_id(web_state: Mapping[str, Any], library: str) -> str:
        """Resolve a web-facing library token to the catalog library_id.

        The browser usually works with ``library_name`` because it is readable,
        while effective pointers are stored under the stable ``library_id``
        such as ``ip/vendor.foo``.  Release-set manifests must use the stable
        id so the current effective pointer can be found reliably.
        """

        target = str(library or "").strip()
        for item in web_state.get("catalog", {}).get("libraries", []) or []:
            if not isinstance(item, Mapping):
                continue
            candidates = {
                str(item.get("library_id") or "").strip(),
                str(item.get("library_name") or "").strip(),
                str(item.get("display_name") or "").strip(),
            }
            typed = str(item.get("typed_library_name") or "").strip()
            if typed:
                candidates.add(typed)
            if target in {value for value in candidates if value}:
                return str(item.get("library_id") or item.get("library_name") or target)
        return target

    def find_catalog_version(web_state: Mapping[str, Any], library: str, version: str) -> Mapping[str, Any] | None:
        library_item = find_catalog_library(web_state, library)
        if not isinstance(library_item, Mapping):
            return None
        for item in library_item.get("versions", []) or []:
            if isinstance(item, Mapping) and str(item.get("version_id")) == version:
                return item
        return None

    def resolve_catalog_file(web_state: Mapping[str, Any], library: str, version: str, relpath: str, *, label: str) -> Path:
        """Resolve a selected catalog file without accepting arbitrary paths."""

        version_item = find_catalog_version(web_state, library, version)
        raw_path = str((version_item or {}).get("raw_path") or "")
        if not raw_path:
            raise ValueError(f"{label}版本没有可用的库根目录")
        root = Path(raw_path).expanduser().resolve()
        candidate = (root / Path(*PurePosixPath(relpath).parts)).resolve()
        if root != candidate and root not in candidate.parents:
            raise ValueError(f"{label}文件必须位于已登记版本目录内")
        if not candidate.is_file():
            raise ValueError(f"{label}文件不存在：{relpath}")
        return candidate

    def validate_compare_request(
        web_state: Mapping[str, Any],
        library: str,
        version: str,
        payload: Mapping[str, Any],
        version_row: Mapping[str, Any],
    ) -> str:
        """Reject impossible compare jobs before creating a job directory."""

        mode = str(payload.get("mode") or "adjacent")
        if mode not in WEB_COMPARE_MODES:
            raise ValueError("对比模式只能是 adjacent 或 cumulative")
        scan_if_missing = _payload_bool(payload, "scan_if_missing")
        rescan = _payload_bool(payload, "rescan")
        if scan_if_missing and rescan:
            raise ValueError("扫描缺失证据和强制重扫只能选择一个")

        current_ready = bool(version_row.get("scan_evidence_ready"))
        allow_scan = scan_if_missing or rescan
        if not current_ready and not allow_scan:
            raise RuntimeError("请先完成扫描，或勾选对比前补扫缺失证据。")

        versions = list_version_rows(web_state, library)
        version_ids = {str(row.get("version_id")) for row in versions}
        base = str(payload.get("base") or "").strip()
        if not base:
            default_base = version_row.get("cumulative_base_version") if mode == "cumulative" else version_row.get("adjacent_base_version")
            base = str(default_base or "").strip()
        if not base:
            raise RuntimeError("缺少对比基准；请先在页面填写基准版本。")
        if base not in version_ids:
            raise RuntimeError(f"对比基准不属于当前库：{base}")
        if base == version:
            raise RuntimeError("对比基准不能与当前版本相同")

        base_row = next(row for row in versions if row.get("version_id") == base)
        if not base_row.get("scan_evidence_ready") and not allow_scan:
            raise RuntimeError(f"对比基准尚未完成扫描：{base}")
        return base

    def progress_roots_for(
        library: str | None,
        version: str | None,
        web_state: Mapping[str, Any],
        *,
        action: str,
        payload: Mapping[str, Any],
    ) -> list[str]:
        """Return fixed scan run locations for live progress observation.

        A scan id is generated by the CLI, so the Web layer records the
        version's existing run directory and its sibling run directories. It
        never walks the RAW tree or accepts a browser-supplied progress path.
        Non-scan jobs must not reuse a previous scan's final progress event.
        """

        if not library or not version:
            return []
        if action in {"compare", "cmp"}:
            if not (payload.get("scan_if_missing") is True or payload.get("rescan") is True):
                return []
        elif action != "scan":
            return []
        roots: list[Path] = []
        item = find_version(web_state, library, version)
        if item:
            scan = item.get("scan") if isinstance(item.get("scan"), Mapping) else {}
            scan_dir = scan.get("scan_dir") or item.get("scan_dir")
            if scan_dir:
                current = Path(str(scan_dir)).expanduser()
                roots.extend([current, current.parent])
        config = web_state.get("config") if isinstance(web_state.get("config"), Mapping) else {}
        workspace = Path(str(web_state.get("workspace") or config.get("workspace") or Path.cwd())).expanduser()
        scan_root = Path(str(config.get("scan_out") or workspace / "scan_out")).expanduser()
        library_type = str((item or {}).get("library_type") or config.get("library_type") or "ip")
        roots.append(scan_root / library_type / library / version / "runs")
        unique: list[str] = []
        seen: set[str] = set()
        for root in roots:
            value = str(root.resolve())
            if value not in seen:
                seen.add(value)
                unique.append(value)
        return unique

    def create_job(action: str, library: str, version: str | None, payload: Mapping[str, Any], web_state: Mapping[str, Any]) -> dict[str, Any]:
        action_spec = WEB_ACTION_SPECS.get(action)
        if action_spec is None:
            raise ValueError(f"网页不允许执行该动作: {action}")
        if action_spec.scope in {"library", "version"} and library is None:
            raise ValueError(f"{action} 需要库")
        if action_spec.scope == "version" and version is None:
            raise ValueError(f"{action} 需要版本")
        if library is not None:
            _safe_library_token(library)
        if version is not None:
            _safe_component(version)
        job_id = f"{action}_{secrets.token_hex(6)}"
        root = job_root(web_state) / job_id
        selected_candidates: list[dict[str, str]] = []
        candidate_selection: dict[str, Any] | None = None
        selected_candidate_input: Path | None = None
        args = [sys.executable, "-m", "lib_guard.short_cli"]
        config_value = app.config.get("LIB_GUARD_CONFIG")
        if config_value:
            args.extend(["--config", str(config_value)])
        cli_action = action_spec.cli_action
        multi_release_request = None
        semantic_documents = None
        if action == 'semantic-review':
            args, semantic_documents = prepare_semantic_job(web_state, find_catalog_library(web_state, library), payload, root)
        elif action in {'release-set-plan', 'release-set-apply'}:
            from lib_guard.release.bundle import validate_release_name
            if action == 'release-set-apply' and not _payload_bool(payload, 'acknowledged'):
                raise ValueError('实际发布必须确认阶段目录、所选库及覆盖设置')
            if any(key in payload for key in ('force', 'no_verify', 'release_root')):
                raise ValueError('多库发布根使用工作区配置，不允许跳过校验或隐式强制')
            selected = payload.get('libraries')
            if not isinstance(selected, list) or not 1 <= len(selected) <= 500:
                raise ValueError('请勾选 1 到 500 个已登记库')
            libraries = list(dict.fromkeys(resolve_catalog_library_id(web_state, str(item)) for item in selected))
            publish_name = validate_release_name(payload.get('publish_name'))
            latest_name = validate_release_name(payload.get('latest_name') or 'latest')
            if publish_name == latest_name:
                raise ValueError('阶段目录与最新指针名不能相同')
            multi_release_request = {
                'catalog_html': str(web_state['catalog_html']), 'libraries': libraries,
                'release_root': str(web_state['paths']['release_root']),
                'publish_name': publish_name, 'latest_name': latest_name,
                'out_dir': str(root / 'delivery'), 'apply': action == 'release-set-apply',
            }
            args = [sys.executable, '-m', 'lib_guard.release.set_publish', '--request', str(root / 'delivery_request.json')]
        elif action == "catalog-refresh":
            if library is None:
                raise ValueError("目录刷新需要库")
            args.extend(["cat", library])
        elif action == "worklist":
            args.append("worklist")
        elif action == "library-discover":
            args.extend(["library", "discover"])
        elif action == "library-accept":
            args.extend(["library", "accept", "--apply", "--refresh-catalog"])
        elif action == "library-apply":
            args.extend(["library", "apply", "--refresh-catalog"])
        elif action == "library-add":
            args.extend(["library", "add"])
        elif action == "file-diff":
            if library is None or version is None:
                raise ValueError("文件对比需要库和版本")
        elif action == "review-gate":
            if library is None or version is None:
                raise ValueError("Review Gate 需要库和版本")
            args.extend(["rv", "check", library, version])
        elif action == "review-packet":
            if library is None or version is None:
                raise ValueError("Review Packet 需要库和版本")
            args.extend(["review", "prepare", library, version])
        elif action == "effective-rollback":
            if library is None:
                raise ValueError("当前可用版本回退需要库")
            args.extend(["effective", "rollback", library])
        elif action == "action-file":
            if library is None:
                raise ValueError("动作文件需要库")
            args.extend(["action", library])
        elif cli_action in {"scan", "cmp", "rel", "mark"}:
            if version is None:
                raise ValueError(f"{action} 需要版本")
            args.extend([cli_action, library, version])
        elif cli_action in {"next", "intake", "window", "accept-window"}:
            args.extend([cli_action, library])
        elif cli_action == "override":
            if version is None:
                raise ValueError("override 需要版本")
            args.extend(["library", "override", library, version])
        else:
            raise ValueError(f"网页不支持该动作: {action}")

        if action == "catalog-refresh":
            args.append("--refresh-catalog")
            if _payload_bool(payload, "with_evidence"):
                args.append("--with-evidence")
            if _payload_bool(payload, "full"):
                args.append("--full")
        elif action == "worklist":
            if _payload_bool(payload, "ready"):
                args.append("--ready")
            if _payload_bool(payload, "blocked"):
                args.append("--blocked")
            if _payload_bool(payload, "json"):
                args.append("--json")
        elif action == "library-discover":
            discover_root_text = _bounded_text(payload.get("root"), label="发现起点", limit=1000)
            if discover_root_text:
                discover_root = Path(discover_root_text).expanduser().resolve()
                allowed_roots = _browse_roots(web_state)
                if not discover_root.is_dir():
                    raise ValueError("发现起点不存在或不是目录；请填写原始库根下的目录")
                if not _path_is_within(discover_root, allowed_roots):
                    allowed = "；".join(str(item) for item in allowed_roots) or "未配置"
                    raise ValueError(f"发现起点不在允许范围内。当前允许范围：{allowed}")
                args.extend(["--root", str(discover_root)])
            discovery = web_state.get("discovery_strategy") if isinstance(web_state.get("discovery_strategy"), Mapping) else {}
            discovery_defaults = default_discovery_strategy()
            options = (
                ("max_depth", "--max-depth", "发现深度", 1, 8, int(str(discovery.get("max_depth") or discovery_defaults["max_depth"]))),
                ("min_versions", "--min-versions", "最少版本数", 1, 100, int(str(discovery.get("min_versions") or discovery_defaults["min_versions"]))),
                ("max_dirs", "--max-dirs", "最大目录数", 1, 100000, int(str(discovery.get("max_dirs") or discovery_defaults["max_dirs"]))),
                ("max_candidates", "--max-candidates", "最大候选数", 1, 10000, int(str(discovery.get("max_candidates") or discovery_defaults["max_candidates"]))),
            )
            for key, flag, label, minimum, maximum, default in options:
                args.extend([flag, str(_bounded_int(payload.get(key), label=label, minimum=minimum, maximum=maximum, default=default))])
        elif action == "library-accept" and "candidate_ids" in payload:
            candidate_ids = payload.get("candidate_ids")
            if not isinstance(candidate_ids, list):
                raise ValueError("候选库必须以勾选列表提交")
            if not 1 <= len(candidate_ids) <= 200:
                raise ValueError("每次登记候选库数量必须在 1 到 200 之间")
            normalized_ids: list[str] = []
            for value in candidate_ids:
                candidate_id = _bounded_text(value, label="候选库标识", limit=64)
                if not candidate_id or candidate_id in normalized_ids:
                    raise ValueError("候选库勾选项无效或重复")
                normalized_ids.append(candidate_id)
            snapshot = list_library_candidate_rows(web_state)
            if snapshot.get("status") != "READY":
                raise ValueError("没有可用的候选库快照；请先执行“发现候选库”")
            by_id = {
                str(row.get("candidate_id")): row
                for row in snapshot.get("candidates", [])
                if isinstance(row, Mapping)
            }
            missing = [candidate_id for candidate_id in normalized_ids if candidate_id not in by_id]
            if missing:
                raise ValueError("候选库快照已变化；请重新读取列表后再登记")
            unavailable = [
                candidate_id
                for candidate_id in normalized_ids
                if bool(by_id[candidate_id].get("already_registered")) or bool(by_id[candidate_id].get("name_conflict"))
            ]
            if unavailable:
                raise ValueError("所选候选库已经登记或与现有库名冲突；请取消勾选后重试")
            selected_candidates = [
                {
                    "status": "OK",
                    **{column: str(by_id[candidate_id].get(column) or "") for column in LIST_COLUMNS if column != "status"},
                }
                for candidate_id in normalized_ids
            ]
            selected_candidate_input = root / "selected_candidates.tsv"
            args.extend(["--input", str(selected_candidate_input)])
            candidate_selection = {
                "count": len(selected_candidates),
                "candidate_ids": normalized_ids,
                "source": str(snapshot.get("source") or ""),
                "selected_input": str(selected_candidate_input),
            }
        elif action == "library-add":
            library_id = _bounded_text(payload.get("library_id"), label="正式库名", limit=180)
            root_path = _bounded_text(payload.get("root"), label="库根目录", limit=1000)
            if not library_id or not root_path:
                raise ValueError("新增库需要填写正式库名和库根目录")
            library_root = Path(root_path).expanduser().resolve()
            browse_roots = _browse_roots(web_state)
            if not library_root.is_dir():
                raise ValueError("库根目录不存在或不是目录；请点击“浏览目录”选择")
            if not _path_is_within(library_root, browse_roots):
                allowed = "；".join(str(item) for item in browse_roots) or "未配置"
                raise ValueError(
                    "库根目录不在当前允许范围内。当前可登记范围："
                    f"{allowed}。请点击“浏览目录”从原始库根中选择真实库交付目录；项目代码根目录不能直接登记为库。"
                )
            args.extend([library_id, "--root", root_path])
            for key, flag, label in (
                ("display_name", "--display-name", "显示名称"),
                ("vendor", "--vendor", "厂商"),
                ("middle_path", "--middle-path", "中间路径"),
            ):
                value = _bounded_text(payload.get(key), label=label, limit=180)
                if value:
                    args.extend([flag, value])
            if _payload_bool(payload, "apply"):
                args.append("--apply")
            if _payload_bool(payload, "refresh_catalog"):
                args.append("--refresh-catalog")
        elif action == "file-diff":
            explicit_old = _bounded_text(payload.get("old_file"), label="旧文件", limit=1000)
            explicit_new = _bounded_text(payload.get("new_file"), label="新文件", limit=1000)
            file_type = _bounded_text(payload.get("type"), label="文件类型", limit=80).lower()
            if not file_type:
                raise ValueError("文件对比需要填写文件类型")
            if not file_diff_allowed(file_type):
                raise ValueError(f"不支持的文件类型：{file_type}。请使用已登记的视图类型。")
            force_large = _payload_bool(payload, "force_large")
            if explicit_old or explicit_new:
                if not explicit_old or not explicit_new:
                    raise ValueError("任意两文件对比需要同时填写旧文件和新文件")
                if payload.get("base") or payload.get("relpath") or payload.get("old_relpath"):
                    raise ValueError("任意两文件对比不能混用版本相对路径参数")
                roots = _browse_roots(web_state)
                old_file = _safe_existing_file_path(explicit_old, roots, label="旧文件")
                new_file = _safe_existing_file_path(explicit_new, roots, label="新文件")
                if file_diff_requires_force_large(file_type) and not force_large:
                    raise ValueError(f"{file_type} 属于轻量证据类型；深度文件对比需要显式勾选 force-large。")
                args.extend(["fd", "--old", str(old_file), "--new", str(new_file), "--type", file_type])
            else:
                base = _bounded_text(payload.get("base"), label="对比基准", limit=180)
                relpath = _safe_relative_path(payload.get("relpath"), label="文件相对路径")
                if not base:
                    raise ValueError("文件对比需要填写基准版本")
                base = _safe_component(base)
                old_relpath = _bounded_text(payload.get("old_relpath"), label="旧文件相对路径", limit=500)
                if old_relpath:
                    old_relpath = _safe_relative_path(old_relpath, label="旧文件相对路径")
                    if base == version:
                        raise ValueError("旧文件基准版本不能与当前版本相同")
                    old_file = resolve_catalog_file(web_state, library, base, old_relpath, label="旧文件")
                    new_file = resolve_catalog_file(web_state, library, version, relpath, label="新文件")
                    if file_diff_requires_force_large(file_type) and not force_large:
                        raise ValueError(f"{file_type} 属于轻量证据类型；深度文件对比需要显式勾选 force-large。")
                    args.extend(["fd", "--old", str(old_file), "--new", str(new_file), "--type", file_type])
                else:
                    args.extend(["fd", library, version, relpath, "--base", base, "--type", file_type])
            if force_large:
                args.append("--force-large")
        elif action == "review-gate":
            operation = _bounded_text(payload.get("operation") or "check", label="Review Gate 操作", limit=30).lower()
            if operation not in {"build", "check", "list", "accept", "waive"}:
                raise ValueError("Review Gate 操作只能是 build、check、list、accept 或 waive")
            args[args.index("check")] = operation
            gate = _bounded_text(payload.get("gate") or "current", label="Gate", limit=30)
            if gate not in {"stage", "current", "approved"}:
                raise ValueError("Gate 只能是 stage、current 或 approved")
            args.extend(["--gate", gate])
            if operation in {"accept", "waive"}:
                item = _bounded_text(payload.get("item"), label="Gate 项目", limit=180)
                by = _bounded_text(payload.get("by"), label="处理人", limit=80)
                reason = _bounded_text(payload.get("reason"), label="处理原因", limit=500)
                if not item or not by or not reason:
                    raise ValueError("Gate 接受或豁免需要填写项目、处理人和原因")
                args.extend(["--item", item, "--by", by, "--reason", reason])
        elif action == "review-packet":
            operation = _bounded_text(payload.get("operation") or "prepare", label="审查包操作", limit=30).lower()
            if operation not in {"prepare", "submit", "collect"}:
                raise ValueError("审查包操作只能是 prepare、submit 或 collect")
            args[args.index("prepare")] = operation
            if operation == "prepare":
                base = _bounded_text(payload.get("base"), label="对比基准", limit=180)
                owner = _bounded_text(payload.get("review_owner"), label="审查负责人", limit=80)
                if base:
                    args.extend(["--base", _safe_component(base)])
                if owner:
                    args.extend(["--review-owner", owner])
            elif operation == "submit":
                review_id = _bounded_text(payload.get("review_id"), label="审查编号", limit=180)
                decision = _bounded_text(payload.get("decision"), label="审查结论", limit=30).upper()
                note = _bounded_text(payload.get("note"), label="审查说明", limit=500)
                reviewer = _bounded_text(payload.get("reviewer"), label="审查人", limit=80)
                if not review_id or decision not in {"PASS", "BLOCK", "QUESTION"}:
                    raise ValueError("提交审查结果需要审查编号和 PASS/BLOCK/QUESTION 结论")
                args.extend(["--review-id", review_id, "--decision", decision, "--note", note])
                if reviewer:
                    args.extend(["--reviewer", reviewer])
            if _payload_bool(payload, "no_render"):
                args.append("--no-render")
        elif action == "effective-rollback":
            target = _bounded_text(payload.get("to"), label="目标版本组合", limit=180)
            by = _bounded_text(payload.get("by"), label="回退人", limit=80)
            reason = _bounded_text(payload.get("reason"), label="回退原因", limit=500)
            if not target or not by or not reason:
                raise ValueError("当前可用版本回退需要填写目标、处理人和原因")
            args.extend(["--to", target, "--by", by, "--reason", reason])
        elif action == "cmp":
            base = str(payload.get("base") or "").strip()
            if base:
                args.extend(["--base", _safe_component(base)])
            mode = _bounded_text(payload.get("mode") or "adjacent", label="对比模式")
            if mode not in WEB_COMPARE_MODES:
                raise ValueError("对比模式只能是 adjacent 或 cumulative")
            args.extend(["--mode", mode])
            scan_if_missing = _payload_bool(payload, "scan_if_missing")
            rescan = _payload_bool(payload, "rescan")
            if scan_if_missing and rescan:
                raise ValueError("扫描缺失证据和强制重扫只能选择一个")
            if scan_if_missing:
                args.append("--scan-if-missing")
            if rescan:
                args.append("--rescan")
        elif action == "scan":
            _append_scan_settings(args, payload)
        elif action == "rel":
            args.append("--check-only")
        elif action in {"release-plan", "release-overwrite-preview", "release-force", "release-apply"}:
            args.extend(build_release_web_args(action, payload))
        elif action == "next":
            _append_effective_selection(args, payload)
            actions = [name for name in ("apply", "accept", "fix") if _payload_bool(payload, name)]
            plan_only = _payload_bool(payload, "plan_only")
            if len(actions) > 1:
                raise ValueError("下一步只能选择预演、执行、接受或修正中的一个动作")
            if not actions or plan_only:
                args.append("--plan-only")
            else:
                args.append(f"--{actions[0]}")
            if _payload_bool(payload, "rebuild"):
                args.append("--rebuild")
            if payload.get("since"):
                args.extend(["--since", _safe_component(_bounded_text(payload["since"], label="起始版本", limit=180))])
            _append_scan_settings(args, payload, include_no_render=False)
            if _payload_bool(payload, "accept"):
                accepted_by = _bounded_text(payload.get("accepted_by"), label="接受人", limit=80)
                if not accepted_by:
                    raise ValueError("设为当前可用版本必须填写确认人")
                args.extend(["--by", accepted_by])
                note = _bounded_text(payload.get("note"), label="接受说明")
                if note:
                    args.extend(["--note", note])
        elif action == "intake":
            _append_effective_selection(args, payload)
            if _payload_bool(payload, "plan_only", default=True):
                args.append("--plan-only")
            if _payload_bool(payload, "rebuild"):
                args.append("--rebuild")
            if payload.get("since"):
                args.extend(["--since", _safe_component(_bounded_text(payload["since"], label="起始版本", limit=180))])
            _append_scan_settings(args, payload, include_no_render=False)
        elif action == "window":
            args.append("--json")
        elif action == "accept-window":
            if payload.get("expected_effective_id"):
                args.extend(["--expected-effective-id", _safe_component(_bounded_text(payload["expected_effective_id"], label="已核对候选", limit=240))])
            accepted_by = _bounded_text(payload.get("accepted_by"), label="接受人", limit=80)
            if not accepted_by:
                raise ValueError("设为当前可用版本必须填写确认人")
            args.extend(["--accepted-by", accepted_by])
            note = _bounded_text(payload.get("note"), label="接受说明")
            if note:
                args.extend(["--note", note])
        elif action == "mark":
            package_type = _bounded_text(payload.get("type"), label="版本类型")
            if package_type not in WEB_MARK_TYPES:
                raise ValueError("版本类型只能是 FULL、FIX、HOTFIX 或 UNKNOWN")
            args.extend(["--type", package_type])
            note = _bounded_text(payload.get("note"), label="修正说明")
            if note:
                args.extend(["--note", note])
        elif action == "override":
            values = (
                ("stage", WEB_STAGES, "阶段"),
                ("package_type", WEB_PACKAGE_TYPES, "包类型"),
                ("compare_default", WEB_COMPARE_DEFAULTS, "默认对比"),
            )
            for key, allowed, label in values:
                value = _bounded_text(payload.get(key), label=label)
                if value:
                    if value not in allowed:
                        raise ValueError(f"{label}不是允许的值")
                    args.extend([f"--{key.replace('_', '-')}", value])
            for key, flag, label in (
                ("base_full", "--base-full", "完整包基线"),
                ("previous_effective", "--previous-effective", "上一有效版"),
            ):
                value = _bounded_text(payload.get(key), label=label, limit=180)
                if value:
                    args.extend([flag, _safe_component(value)])
            note = _bounded_text(payload.get("note"), label="修正说明")
            if note:
                args.extend(["--note", note])
        request_payload = {
            "job_id": job_id,
            "action": action,
            "library": library,
            "version": version,
            "args": args,
            "payload": dict(payload),
            "observability": {
                "progress_roots": progress_roots_for(
                    library,
                    version,
                    web_state,
                    action=action,
                    payload=payload,
                )
            },
            "created_by": "web_console",
        }
        if candidate_selection is not None:
            request_payload["candidate_selection"] = candidate_selection
        formal_release_target = payload.get("formal_release_target")
        if isinstance(formal_release_target, Mapping):
            request_payload["formal_release_target"] = {
                "library_id": str(formal_release_target.get("library_id") or ""),
                "release_id": str(formal_release_target.get("release_id") or ""),
                "version_id": str(formal_release_target.get("version_id") or ""),
                "source": str(formal_release_target.get("source") or ""),
            }
        with jobs_lock:
            if not app.config.get("TESTING"):
                if any(process.poll() is None and job_targets.get(existing) == library for existing, process in jobs.items()):
                    raise RuntimeError(f"库正在执行其他动作，请等待当前任务结束：{library}")
            created_epoch = time.time()
            root.mkdir(parents=True, exist_ok=False)
            if semantic_documents is not None:
                for name, content in semantic_documents.items():
                    atomic_write_text(root / name, content)
            if multi_release_request is not None:
                _write_json(root / 'delivery_request.json', multi_release_request)
            if selected_candidate_input is not None:
                write_library_rows(
                    selected_candidate_input,
                    selected_candidates,
                    header_note="网页勾选的候选库；仅用于本次登记任务，原始候选快照未改写。",
                )
            _write_json(root / "request.json", request_payload)
            _write_json(root / "status.json", {"job_id": job_id, "status": "QUEUED", "action": action, "created_epoch": created_epoch})

            if not app.config.get("TESTING"):
                env = os.environ.copy()
                source_root = str(Path(__file__).resolve().parents[2])
                env["PYTHONPATH"] = source_root + os.pathsep + env.get("PYTHONPATH", "")
                env["PYTHONUNBUFFERED"] = "1"
                try:
                    with (root / "stdout.log").open("w", encoding="utf-8") as log:
                        process = subprocess.Popen(args, cwd=app.config["LIB_GUARD_CWD"], env=env, stdout=log, stderr=subprocess.STDOUT, text=True)
                except OSError as exc:
                    _write_json(root / "status.json", {"job_id": job_id, "status": "FAILED", "action": action, "error": str(exc)})
                    raise
                jobs[job_id] = process
                job_targets[job_id] = library
                _write_json(root / "status.json", {"job_id": job_id, "status": "RUNNING", "pid": process.pid, "action": action, "created_epoch": created_epoch, "started_epoch": time.time()})
        return {"job_id": job_id, "status": "QUEUED" if app.config.get("TESTING") else "RUNNING", "request": str(root / "request.json")}

    @app.get("/")
    def index() -> str:
        return render_template("index.html")

    @app.get("/api/health")
    def health() -> Any:
        return jsonify({"status": "PASS", "service": "lib_guard_web", "pid": os.getpid()})

    @app.get("/api/workspace")
    def workspace() -> Any:
        try:
            web_state = state()
        except (FileNotFoundError, OSError) as exc:
            return jsonify(_workspace_setup_payload(app.config.get("LIB_GUARD_CWD"), exc))
        catalog_index = Path(web_state["catalog_html"]) / "index.html"
        report_available = catalog_index.is_file()
        return jsonify({
            "status": "PASS",
            "setup_required": False,
            "paths": web_state["paths"],
            "catalog_report": {
                "available": report_available,
                "path": str(catalog_index),
                "url": "/artifacts/index.html" if report_available else None,
            },
            "scan_strategy": web_state["scan_strategy"],
            "discovery_strategy": web_state["discovery_strategy"],
            "runtime_state": web_state["runtime_state"],
            "release_settings": {
                "publish_name": web_state["config"].get("release_publish_name", ""),
                "latest_name": web_state["config"].get("release_latest_name", "latest"),
            },
            "catalog_state": web_state["catalog_state"],
            "catalog_source": "existing_catalog" if web_state["catalog_state"] == "READY" else "not_initialized",
            "write_policy": "web_actions_are_allowlisted",
            "web_actions": web_action_catalog(),
        })

    @app.post("/api/workspace/init")
    def workspace_init() -> Any:
        try:
            payload = request_payload()
            workspace_text = _bounded_text(payload.get("workspace"), label="工作区目录", limit=1000)
            raw_root_text = _bounded_text(payload.get("raw_root"), label="原始库根", limit=1000)
            library_type = _bounded_text(payload.get("library_type") or "ip", label="库类型", limit=40)
            if not workspace_text:
                raise ValueError("工作区目录不能为空")
            if not raw_root_text:
                raise ValueError("原始库根不能为空")
            raw_root = Path(raw_root_text).expanduser().resolve()
            if not raw_root.exists() or not raw_root.is_dir():
                raise ValueError(f"原始库根不存在或不是目录：{raw_root}")
            if not library_type.replace("_", "").replace("-", "").isalnum():
                raise ValueError("库类型只能包含字母、数字、下划线或短横线")
            config_file = Path(workspace_text).expanduser().resolve() / "lib_guard.yml"
            reconnect = config_file.is_file()
            if reconnect:
                load_config(app.config["LIB_GUARD_CWD"], config_file)
            else:
                config_file = write_default_config(workspace_text, raw_root=raw_root, library_type=library_type)
            app.config["LIB_GUARD_CONFIG"] = str(config_file)
            web_state = state()
            _write_json(workspace_pointer, {"config": str(config_file.resolve())})
        except (ValueError, OSError) as exc:
            return jsonify({"status": "ERROR", "error": str(exc)}), 400
        return jsonify({
            "status": "PASS",
            "config": str(config_file),
            "paths": web_state["paths"],
            "scan_strategy": web_state["scan_strategy"],
            "discovery_strategy": web_state["discovery_strategy"],
            "catalog_state": web_state["catalog_state"],
            "web_actions": web_action_catalog(),
            "message": "已连接原工作区，配置和已有记录保持不变，无需重新登记或扫描。" if reconnect else "工作区已初始化。下一步可以登记库根，或发现候选库。",
        })

    @app.post("/api/workspace/config")
    def workspace_config_update() -> Any:
        try:
            payload = request_payload()
            config_file = find_config(app.config.get("LIB_GUARD_CWD") or Path.cwd(), app.config.get("LIB_GUARD_CONFIG"))
            allowed_keys = (
                "raw_root",
                "release_root",
                "release_publish_name",
                "release_latest_name",
                "library_type",
                "parse_jobs",
                "hash_policy",
                "force_hash_file_types",
                "skip_hash_file_types",
                "parse_file_types",
                "parse_exclude_file_types",
                "render_detail",
                "discover_max_depth",
                "discover_min_versions",
                "discover_max_dirs",
                "discover_max_candidates",
            )
            unknown = sorted(str(key) for key in payload if str(key) not in allowed_keys)
            if unknown:
                raise ValueError(f"网页配置不支持这些字段：{', '.join(unknown)}")
            updates = {key: payload[key] for key in allowed_keys if key in payload}
            if not updates:
                raise ValueError("没有可保存的配置项")
            result = update_config_file(config_file, updates)
            web_state = state()
        except (FileNotFoundError, ValueError, OSError) as exc:
            return jsonify({"status": "ERROR", "error": str(exc)}), 400
        return jsonify({
            **result,
            "paths": web_state["paths"],
            "scan_strategy": web_state["scan_strategy"],
            "discovery_strategy": web_state["discovery_strategy"],
            "release_settings": {
                "publish_name": web_state["config"].get("release_publish_name", ""),
                "latest_name": web_state["config"].get("release_latest_name", "latest"),
            },
        })

    @app.get("/api/path-children")
    def path_children() -> Any:
        """Browse configured library roots for the new-library form only."""

        try:
            web_state = state()
            payload = _browse_directory(request.args.get("path"), _browse_roots(web_state))
        except (FileNotFoundError, NotADirectoryError) as exc:
            return jsonify({"status": "NOT_FOUND", "error": str(exc)}), 404
        except ValueError as exc:
            return jsonify({"status": "ERROR", "error": str(exc)}), 400
        except OSError as exc:
            return jsonify({"status": "ERROR", "error": f"目录浏览暂不可用：{exc}"}), 503
        return jsonify({"status": "PASS", **payload})

    @app.get("/api/libraries")
    def libraries() -> Any:
        try:
            web_state = state()
        except (FileNotFoundError, OSError) as exc:
            return jsonify({"status": "ERROR", "error": str(exc)}), 503
        return jsonify({"status": "PASS", "libraries": list_library_rows(web_state)})

    @app.get("/api/library-candidates")
    def library_candidates() -> Any:
        try:
            web_state = state()
            return jsonify(list_library_candidate_rows(web_state))
        except (FileNotFoundError, OSError) as exc:
            return jsonify({"status": "ERROR", "error": f"工作区暂不可用：{exc}"}), 503

    @app.get('/api/formal-directory')
    def formal_directory() -> Any:
        try:
            path = Path(state()['workspace']) / 'config/formal_directory_inventory.json'
            snapshot = json.loads(path.read_text()) if path.is_file() else {'status':'MISSING','libraries':[],'files':[]}
            rows = snapshot.get('files', [])
            library, version, view, check = (request.args.get(key, '') for key in ('library','version','type','check'))
            versions = sorted({row['version'] for row in rows if row['version'] and (not library or row['library']==library)})
            query = request.args.get('query','').lower()
            rows = [row for row in rows if (not library or (row['library'] == library if library != '__unknown__' else not row['library']))
                    and (not view or row['file_type']==view)
                    and (not version or row['version']==version)
                    and (check != 'unknown' or not row['library']) and (check != 'broken' or row['link_status']=='链接失效')
                    and (not query or query in (row['path']+' '+row['source_path']).lower())]
            offset = _bounded_int(request.args.get('offset'), label='页偏移', minimum=0, maximum=1_000_000, default=0)
            return jsonify({**snapshot,'files':rows[offset:offset+100],'matched_count':len(rows),'offset':offset,'versions':versions})
        except (OSError, ValueError) as exc:
            return jsonify({'status':'ERROR','error':str(exc)}), 400

    @app.post('/api/formal-directory/refresh')
    def formal_directory_refresh() -> Any:
        try:
            from lib_guard.release.inventory import audit_formal_directory
            from lib_guard.atomic import atomic_write_text
            web_state = state()
            root = _bounded_text(request_payload().get('root'), label='正式目录', limit=1000)
            if not root or not Path(root).is_absolute():
                raise ValueError('请选择正式目录的绝对路径；与临时发布输出目录独立。')
            snapshot = audit_formal_directory(root, web_state['catalog'])
            output = Path(web_state['workspace']) / 'config/formal_directory_inventory.json'
            atomic_write_text(output, json.dumps(snapshot, ensure_ascii=False, indent=2), lock=True)
            return jsonify({key:value for key,value in snapshot.items() if key!='files'})
        except (OSError, ValueError) as exc:
            return jsonify({'status':'ERROR','error':str(exc)}), 400

    @app.get("/api/release-libraries")
    def release_libraries() -> Any:
        """List a persisted formal-release projection, never RAW candidates."""

        try:
            return jsonify(list_release_library_rows(state()))
        except (FileNotFoundError, OSError) as exc:
            return jsonify({"status": "ERROR", "error": f"工作区暂不可用：{exc}"}), 503

    @app.get('/api/release-stages/<name>/files')
    def release_stage_files(name: str) -> Any:
        try:
            return jsonify(release_stage_detail(state(), name,
                query=request.args.get('query', ''), library=request.args.get('library', ''),
                view=request.args.get('view', ''), link_status=request.args.get('link_status', ''),
                offset=int(request.args.get('offset', 0)), limit=int(request.args.get('limit', 100))))
        except ValueError as exc:
            return jsonify({'status': 'ERROR', 'error': str(exc)}), 400
        except OSError as exc:
            return jsonify({'status': 'ERROR', 'error': f'交付清单无法读取：{exc}；请刷新发布目录'}), 503

    @app.post("/api/release-libraries/refresh")
    def release_libraries_refresh() -> Any:
        """Refresh the bounded release-manifest index; this is not a release action."""

        try:
            from lib_guard.release.library_index import build_release_library_index, write_release_library_index

            web_state = state()
            payload = request_payload()
            paths = web_state.get("paths") if isinstance(web_state.get("paths"), Mapping) else {}
            configured_root = Path(str(paths.get("release_root") or "")).expanduser().resolve()
            requested_root = _bounded_text(payload.get("root"), label="正式发布根目录", limit=1000)
            release_root = Path(requested_root).expanduser().resolve() if requested_root else configured_root
            if not configured_root.is_dir():
                raise FileNotFoundError(f"配置的正式发布根目录不存在：{configured_root}")
            if not _path_is_within(release_root, [configured_root]):
                raise ValueError("正式发布根目录必须位于当前配置的 release_root 内")
            if not release_root.is_dir():
                raise FileNotFoundError(f"正式发布根目录不存在或不是目录：{release_root}")
            output = Path(str(paths.get("release_library_index") or "")).expanduser().resolve()
            workspace_root = Path(str(web_state["workspace"])).expanduser().resolve()
            if not _path_is_within(output, [workspace_root]):
                raise ValueError("正式发布库索引必须写入当前工作区")
            max_depth = _bounded_int(payload.get("max_depth"), label="发布目录深度", minimum=0, maximum=16, default=8)
            max_manifests = _bounded_int(payload.get("max_manifests"), label="发布清单上限", minimum=1, maximum=10_000, default=2000)
            index = build_release_library_index(release_root, max_depth=max_depth, max_manifests=max_manifests)
            write_release_library_index(output, index)
            return jsonify(
                {
                    "status": "PASS",
                    "message": "正式发布库目录已更新；未扫描 RAW，也未执行发布。",
                    "index": str(output),
                    "release_root": str(release_root),
                    "summary": index["summary"],
                    "warnings": index["warnings"],
                    "truncated": index["truncated"],
                }
            )
        except (FileNotFoundError, OSError, ValueError) as exc:
            return jsonify({"status": "ERROR", "error": str(exc)}), 400

    @app.get("/api/libraries/<library>/versions")
    def versions(library: str) -> Any:
        try:
            web_state = state()
        except (FileNotFoundError, OSError) as exc:
            return jsonify({"status": "ERROR", "error": str(exc)}), 503
        if find_catalog_library(web_state, library) is None:
            return jsonify({"status": "NOT_FOUND", "error": f"库不存在: {library}"}), 404
        try:
            offset = _bounded_int(request.args.get("offset"), label="offset", minimum=0, maximum=1_000_000, default=0)
            limit = _bounded_int(request.args.get("limit"), label="limit", minimum=1, maximum=200, default=100)
        except ValueError as exc:
            return jsonify({"status": "ERROR", "error": str(exc)}), 400
        library_item = find_catalog_library(web_state, library) or {}
        total = sum(1 for item in library_item.get("versions", []) or [] if isinstance(item, Mapping))
        rows = list_version_rows(web_state, library, offset=offset, limit=limit)
        next_offset = offset + len(rows) if offset + len(rows) < total else None
        return jsonify({
            "status": "PASS",
            "library": library,
            "versions": rows,
            "pagination": {"offset": offset, "limit": limit, "total": total, "next_offset": next_offset},
        })

    @app.get("/api/libraries/<library>/versions/<version>/file-changes")
    def file_changes(library: str, version: str) -> Any:
        try:
            web_state = state()
        except (FileNotFoundError, OSError) as exc:
            return jsonify({"status": "ERROR", "error": f"工作区暂不可用：{exc}"}), 503
        if find_catalog_version(web_state, library, version) is None:
            return jsonify({"status": "NOT_FOUND", "error": f"版本不存在: {library}/{version}"}), 404
        try:
            offset = _bounded_int(request.args.get("offset"), label="offset", minimum=0, maximum=1_000_000, default=0)
            limit = _bounded_int(request.args.get("limit"), label="limit", minimum=1, maximum=200, default=100)
            change = _bounded_text(request.args.get("change"), label="变化类型", limit=32).upper()
            file_type = _bounded_text(request.args.get("file_type"), label="视图类型", limit=64).lower()
            query = _bounded_text(request.args.get("query"), label="文件搜索词", limit=240)
        except ValueError as exc:
            return jsonify({"status": "ERROR", "error": str(exc)}), 400
        page = list_file_diff_page(
            web_state,
            library,
            version,
            change=change or None,
            file_type=file_type or None,
            query=query or None,
            offset=offset,
            limit=limit,
        )
        version_item = find_catalog_version(web_state, library, version) or {}
        diff = version_item.get("diff") if isinstance(version_item.get("diff"), Mapping) else {}
        base_version = next(
            (str(diff.get(key)) for key in ("adjacent_old_version", "base_version", "cumulative_base_version") if diff.get(key)),
            None,
        )
        return jsonify({
            "status": "PASS",
            "library": library,
            "version": version,
            "base_version": base_version,
            "rows": page["rows"],
            "count": page["total"],
            "pagination": {"offset": offset, "limit": limit, "total": page["total"], "next_offset": page["next_offset"]},
            "counts": page["counts"],
            "comparison_semantics": page.get("comparison_semantics", "complete_snapshot"),
            "omitted_from_overlay": page.get("omitted_from_overlay", 0),
            "raw_removed": page.get("raw_removed", 0),
            "source": "existing_file_diff_evidence",
        })

    @app.get("/api/libraries/<library>/versions/<version>/file-tree")
    def file_tree(library: str, version: str) -> Any:
        try:
            web_state = state()
        except (FileNotFoundError, OSError) as exc:
            return jsonify({"status": "ERROR", "error": f"工作区暂不可用：{exc}"}), 503
        result = list_file_tree_rows(web_state, library, version)
        if result.get("status") == "NOT_FOUND":
            return jsonify(result), 404
        return jsonify(result)

    @app.get("/api/libraries/<library>/versions/<version>/update-note")
    def version_update_note(library: str, version: str) -> Any:
        try:
            web_state = state()
        except (FileNotFoundError, OSError) as exc:
            return jsonify({"status": "ERROR", "error": f"工作区暂不可用：{exc}"}), 503
        if find_catalog_version(web_state, library, version) is None:
            return jsonify({"status": "NOT_FOUND", "error": f"版本不存在: {library}/{version}"}), 404
        root = review_notes_root(workdir=web_state["workspace"])
        return jsonify({"status": "PASS", "library": library, "version": version, "note": load_update_note(root, library, version)})

    @app.route('/api/libraries/<library>/versions/<version>/representative-files', methods=['GET', 'POST'])
    def representative_files(library: str, version: str) -> Any:
        from lib_guard.review.representative_files import load_representative_files, save_representative_file

        try:
            web_state = state()
            if find_catalog_version(web_state, library, version) is None:
                return jsonify({'status': 'NOT_FOUND', 'error': '库或版本不存在'}), 404
            notes_root = review_notes_root(catalog_html_out=web_state['catalog_html'])
            if request.method == 'GET':
                return jsonify({'status': 'PASS', 'rows': load_representative_files(notes_root, library, version)})
            payload = request_payload()
            job_id = _safe_component(_bounded_text(payload.get('job_id'), label='文件对比任务', limit=100))
            root = job_root(web_state) / job_id
            recorded = json.loads((root / 'request.json').read_text(encoding='utf-8'))
            if recorded.get('action') != 'file-diff' or recorded.get('library') != library or recorded.get('version') != version:
                raise ValueError('只能加入属于当前库和版本的深度文件对比任务')
            result_record = json.loads((root / 'result.json').read_text(encoding='utf-8'))
            if result_record.get('exit_code') != 0 or result_record.get('result') != 'ok':
                raise ValueError('文件对比尚未成功完成，请先查看任务结果')
            result = result_record['cli_result']
            if not result.get('generated_at'):
                raise ValueError('旧任务未记录产物身份，请重新运行这组文件对比后加入详情页。')
            out = Path(str(result.get('out_dir') or '')).resolve()
            if not _path_is_within(out, [Path(web_state['workspace']).resolve()]):
                raise ValueError('对比产物不在当前工作区内')
            pair = json.loads((out / 'pairwise_result.json').read_text(encoding='utf-8'))
            if pair.get('generated_at') != result['generated_at']:
                raise ValueError('这次任务的对比产物已被后续任务替换，请重新对比后加入详情页。')
            target = find_catalog_version(web_state, library, version) or {}
            target_root = target.get('raw_path')
            old_roots = [Path(row['raw_path']).resolve() for lib in web_state['catalog'].get('libraries', [])
                         if target in lib.get('versions', [])
                         for row in lib.get('versions', []) if row.get('raw_path')]
            if not target_root or not _path_is_within(Path(str(pair.get('new_file') or '')).resolve(), [Path(target_root).resolve()]):
                raise ValueError('新侧文件不属于当前版本；任意文件对比仍可查看，但不能加入这个版本详情。')
            if not _path_is_within(Path(str(pair.get('old_file') or '')).resolve(), old_roots):
                raise ValueError('旧侧文件不属于当前库，请选择同库基准文件后加入详情。')
            save_representative_file(
                notes_root, library, version, out,
                note=_bounded_text(payload.get('note'), label='核查备注', limit=1000),
                updated_by=_bounded_text(payload.get('updated_by') or 'web', label='核查人', limit=80),
                expected_generation=result['generated_at'],
            )
            try:
                from lib_guard.render.version_detail_fast import render_version_detail_only

                rendered = render_version_detail_only(catalog_path=web_state['catalog_path'], out_dir=web_state['catalog_html'], library=library, version=version, export_markdown=True)
            except Exception as exc:
                rendered = {'status': 'FAILED', 'error': str(exc)}
            return jsonify({'status': 'PASS', 'rows': load_representative_files(notes_root, library, version), 'render': rendered})
        except (ValueError, TypeError, KeyError) as exc:
            return jsonify({'status': 'ERROR', 'error': str(exc)}), 400
        except OSError as exc:
            return jsonify({'status': 'ERROR', 'error': f'记录或产物不可读：{exc}'}), 503

    @app.post("/api/libraries/<library>/versions/<version>/update-note")
    def save_version_update_note(library: str, version: str) -> Any:
        try:
            web_state = state()
            if find_catalog_version(web_state, library, version) is None:
                return jsonify({"status": "NOT_FOUND", "error": f"版本不存在: {library}/{version}"}), 404
            payload = request_payload()
            _validate_update_note_payload(payload)
            updated_by = _bounded_text(payload.get("updated_by") or payload.get("author") or "web", label="更新人", limit=80)
            status = str(payload.get("status") or "").lower()
            publish = status == "published" or _payload_bool(payload, "publish", default=False)
            note = save_update_note(
                review_notes_root(workdir=web_state["workspace"]),
                library,
                version,
                payload,
                updated_by=updated_by,
                publish=publish,
            )
            render_result: dict[str, Any]
            try:
                from lib_guard.render.version_detail_fast import render_version_detail_only

                render_result = render_version_detail_only(
                    catalog_path=web_state["catalog_path"],
                    out_dir=web_state["catalog_html"],
                    library=library,
                    version=version,
                )
            except Exception as exc:  # pragma: no cover - depends on external evidence state
                render_result = {
                    "status": "FAILED",
                    "error": str(exc),
                    "reason": "备注已保存，但当前详情页刷新失败；请稍后重新读取或手动刷新目录。",
                }
        except (FileNotFoundError, OSError) as exc:
            return jsonify({"status": "ERROR", "error": f"工作区暂不可用：{exc}"}), 503
        except (ValueError, TypeError) as exc:
            return jsonify({"status": "ERROR", "error": str(exc)}), 400
        return jsonify({"status": "PASS", "library": library, "version": version, "note": note, "render": render_result})

    @app.post("/api/release-set/build")
    def release_set_build() -> Any:
        try:
            web_state = state()
            payload = request_payload()
            raw_libraries = payload.get("libraries")
            if raw_libraries is None:
                raw_libraries = [row.get("library_name") for row in list_library_rows(web_state)]
            if not isinstance(raw_libraries, list):
                raise ValueError("多库组合必须提交库名列表")
            libraries = [_bounded_text(item, label="库名", limit=180) for item in raw_libraries]
            libraries = [resolve_catalog_library_id(web_state, item) for item in libraries if item]
            if not 1 <= len(libraries) <= 500:
                raise ValueError("多库组合的库数量必须在 1 到 500 之间")
            set_id = _bounded_text(payload.get("set_id"), label="组合名称", limit=120)
            note = _bounded_text(payload.get("note"), label="组合说明", limit=500)
            manifest = build_release_set_manifest(web_state["catalog_html"], libraries, set_id=set_id or None, note=note)
            out_dir = Path(web_state["catalog_html"]) / "release_sets" / _safe_component(str(manifest["set_id"]))
            manifest_path = write_release_set_manifest(out_dir / "release_set_manifest.json", manifest)
        except (FileNotFoundError, OSError) as exc:
            return jsonify({"status": "ERROR", "error": f"工作区暂不可用：{exc}"}), 503
        except (ValueError, TypeError) as exc:
            return jsonify({"status": "ERROR", "error": str(exc)}), 400
        return jsonify({"status": "PASS", "manifest": manifest, "manifest_path": str(manifest_path)})

    @app.post('/api/release-set/plan')
    @app.post('/api/release-set/apply')
    def release_set_publish() -> Any:
        try:
            action = 'release-set-apply' if request.path.endswith('/apply') else 'release-set-plan'
            return jsonify(create_job(action, None, None, request_payload(), state())), 202
        except RuntimeError as exc:
            return jsonify({'status': 'BLOCKED', 'error': str(exc)}), 409
        except (OSError, ValueError, TypeError) as exc:
            return jsonify({'status': 'ERROR', 'error': str(exc)}), 400

    @app.post("/api/release-set/compare")
    def release_set_compare() -> Any:
        try:
            web_state = state()
            payload = request_payload()
            roots = [Path(web_state["workspace"]).resolve(), Path(web_state["catalog_html"]).resolve()]
            old_path = _safe_existing_json_path(payload.get("old_manifest"), roots, label="旧组合清单")
            new_path = _safe_existing_json_path(payload.get("new_manifest"), roots, label="新组合清单")
            old = json.loads(old_path.read_text(encoding="utf-8"))
            new = json.loads(new_path.read_text(encoding="utf-8"))
            if not isinstance(old, Mapping) or not isinstance(new, Mapping):
                raise ValueError("组合清单必须是 JSON 对象")
            compare = compare_release_sets(old, new)
            out_dir = Path(web_state["catalog_html"]) / "release_sets" / "compare" / _safe_component(str(compare["compare_id"]))
            compare_path = _write_json(out_dir / "release_set_compare.json", compare) or out_dir / "release_set_compare.json"
        except (FileNotFoundError, OSError) as exc:
            return jsonify({"status": "ERROR", "error": f"组合清单无法读取：{exc}"}), 404
        except (ValueError, TypeError) as exc:
            return jsonify({"status": "ERROR", "error": str(exc)}), 400
        return jsonify({"status": "PASS", "compare": compare, "compare_path": str(compare_path)})

    @app.get("/api/runs/<job_id>")
    def run_status(job_id: str) -> Any:
        try:
            root = job_root_without_catalog() / _safe_component(job_id)
        except (FileNotFoundError, OSError, ValueError) as exc:
            return jsonify({"status": "ERROR", "error": str(exc)}), 503
        if not root.exists():
            return jsonify({"status": "NOT_FOUND", "error": f"运行记录不存在: {job_id}"}), 404
        with jobs_lock:
            process = jobs.get(job_id)
        return jsonify(_job_status(root, process) | {"job_id": job_id, "request": str(root / "request.json"), "log_url": f"/api/runs/{job_id}/log"})

    @app.get("/api/runs/<job_id>/log")
    def run_log(job_id: str) -> Any:
        try:
            root = job_root_without_catalog() / _safe_component(job_id)
        except (FileNotFoundError, OSError, ValueError) as exc:
            return jsonify({"status": "ERROR", "error": str(exc)}), 503
        log_path = root / "stdout.log"
        if not log_path.is_file():
            return jsonify({"status": "NOT_FOUND", "error": "运行日志尚未生成"}), 404
        return send_from_directory(root, "stdout.log", mimetype="text/plain")

    @app.get("/api/runs/<job_id>/artifact/<artifact_id>")
    def run_artifact(job_id: str, artifact_id: str) -> Any:
        try:
            root = job_root_without_catalog() / _safe_component(job_id)
            artifact_key = _safe_component(artifact_id)
            web_state = state()
        except (FileNotFoundError, OSError, ValueError) as exc:
            return jsonify({"status": "ERROR", "error": f"运行产物暂不可用：{exc}"}), 503
        artifacts = _job_artifact_map(root)
        artifact_info = artifacts.get(artifact_key)
        if not artifact_info:
            result = _load_cli_result(root) or {}
            out_dir = result.get("out_dir")
            if out_dir:
                inline_candidate = (Path(str(out_dir)).expanduser() / artifact_key).resolve()
                if inline_candidate.is_file():
                    artifact_info = {"path": str(inline_candidate)}
        if not artifact_info:
            return jsonify({"status": "NOT_FOUND", "error": "运行产物不存在或尚未生成"}), 404
        candidate = Path(artifact_info["path"]).resolve()
        allowed_roots = _browse_roots(web_state)
        if not _path_is_within(candidate, allowed_roots):
            return jsonify({"status": "ERROR", "error": "运行产物不在当前工作区允许范围内"}), 400
        download = (_load_cli_result(root) or {}).get('schema_version') == 'semantic_summary.v1'
        return send_from_directory(candidate.parent, candidate.name, as_attachment=download)

    def action_route(action: str, library: str, version: str) -> Any:
        try:
            web_state = state()
            version_row = find_version(web_state, library, version)
            if version_row is None:
                return jsonify({"status": "NOT_FOUND", "error": f"版本不存在: {library}/{version}"}), 404
            payload = request_payload()
            readiness = version_row.get("action_readiness") or {}
            if action == "cmp":
                payload = dict(payload)
                payload["base"] = validate_compare_request(web_state, library, version, payload, version_row)
            if action == "file-diff":
                payload = dict(payload)
                explicit_old = _bounded_text(payload.get("old_file"), label="旧文件", limit=1000)
                explicit_new = _bounded_text(payload.get("new_file"), label="新文件", limit=1000)
                if not (explicit_old or explicit_new):
                    base = _bounded_text(payload.get("base"), label="对比基准", limit=180)
                    versions = list_version_rows(web_state, library)
                    version_ids = {str(row.get("version_id")) for row in versions}
                    if not base:
                        raise RuntimeError("文件对比缺少基准版本")
                    if base not in version_ids:
                        raise RuntimeError(f"文件对比基准不属于当前库：{base}")
                    if base == version:
                        raise RuntimeError("文件对比基准不能与当前版本相同")
                    payload["base"] = base
            if action in {"rel", "release-plan", "release-overwrite-preview", "release-force", "release-apply"} and not (readiness.get("release-check") or {}).get("enabled"):
                return jsonify({"status": "BLOCKED", "error": "请先完成扫描，再进行发布检查。"}), 409
            return jsonify(create_job(action, library, version, payload, web_state)), 202
        except RuntimeError as exc:
            return jsonify({"status": "BLOCKED", "error": str(exc)}), 409
        except (FileNotFoundError, OSError) as exc:
            return jsonify({"status": "ERROR", "error": f"工作区暂不可用：{exc}"}), 503
        except (ValueError, TypeError) as exc:
            return jsonify({"status": "ERROR", "error": str(exc)}), 400

    def library_action_route(action: str, library: str) -> Any:
        try:
            web_state = state()
            library_item = find_catalog_library(web_state, library)
            if library_item is None:
                return jsonify({"status": "NOT_FOUND", "error": f"库不存在: {library}"}), 404
            payload = request_payload()
            if action == "accept-window":
                window = _pending_window(web_state, library_item)
                window_state = str(window.get("state") or "MISSING").upper()
                candidate = str(window.get("candidate_effective_id") or "")
                if window_state == "INVALID":
                    return jsonify({"status": "ERROR", "error": "接入建议文件无法读取，请重新生成处理建议。"}), 422
                if window_state != "PENDING" or not candidate:
                    return jsonify({"status": "BLOCKED", "error": "当前没有可确认的新版本；请先生成处理建议。"}), 409
                if not window.get("candidate_manifest_exists", False):
                    return jsonify({"status": "BLOCKED", "error": "候选版本尚未生成完整清单；请先生成处理计划。"}), 409
            return jsonify(create_job(action, library, None, payload, web_state)), 202
        except (FileNotFoundError, OSError) as exc:
            return jsonify({"status": "ERROR", "error": f"工作区暂不可用：{exc}"}), 503
        except RuntimeError as exc:
            return jsonify({"status": "BLOCKED", "error": str(exc)}), 409
        except (ValueError, TypeError) as exc:
            return jsonify({"status": "ERROR", "error": str(exc)}), 400

    def workspace_action_route(action: str) -> Any:
        try:
            web_state = state()
            payload = request_payload()
            return jsonify(create_job(action, None, None, payload, web_state)), 202
        except (FileNotFoundError, OSError) as exc:
            return jsonify({"status": "ERROR", "error": f"工作区暂不可用：{exc}"}), 503
        except RuntimeError as exc:
            return jsonify({"status": "BLOCKED", "error": str(exc)}), 409
        except (ValueError, TypeError) as exc:
            return jsonify({"status": "ERROR", "error": str(exc)}), 400

    @app.post("/api/worklist")
    def worklist() -> Any:
        return workspace_action_route("worklist")

    @app.post("/api/library/discover")
    def library_discover() -> Any:
        return workspace_action_route("library-discover")

    @app.post("/api/library/accept")
    def library_accept() -> Any:
        return workspace_action_route("library-accept")

    @app.post("/api/library/apply")
    def library_apply() -> Any:
        return workspace_action_route("library-apply")

    @app.post("/api/library/add")
    def library_add() -> Any:
        return workspace_action_route("library-add")

    @app.post("/api/libraries/<library>/catalog")
    def catalog_refresh(library: str) -> Any:
        try:
            web_state = state()
            if find_catalog_library(web_state, library) is None:
                return jsonify({"status": "NOT_FOUND", "error": f"库不存在: {library}"}), 404
            return jsonify(create_job("catalog-refresh", library, None, request_payload(), web_state)), 202
        except (FileNotFoundError, OSError) as exc:
            return jsonify({"status": "ERROR", "error": f"工作区暂不可用：{exc}"}), 503
        except (RuntimeError, ValueError, TypeError) as exc:
            return jsonify({"status": "ERROR", "error": str(exc)}), 400

    @app.post("/api/libraries/<library>/versions/<version>/scan")
    def scan(library: str, version: str) -> Any:
        return action_route("scan", library, version)

    @app.post("/api/libraries/<library>/versions/<version>/compare")
    def compare(library: str, version: str) -> Any:
        return action_route("cmp", library, version)

    @app.post("/api/libraries/<library>/versions/<version>/release-check")
    def release_check(library: str, version: str) -> Any:
        return action_route("rel", library, version)

    @app.post("/api/libraries/<library>/versions/<version>/release-plan")
    def release_plan(library: str, version: str) -> Any:
        return action_route("release-plan", library, version)

    @app.post("/api/libraries/<library>/versions/<version>/release-apply")
    def release_apply(library: str, version: str) -> Any:
        return action_route("release-apply", library, version)

    def formal_release_action_route(action: str, formal_library: str, version: str) -> Any:
        """Map one indexed formal release target to a tightly scoped release action."""

        try:
            web_state = state()
            payload = dict(request_payload())
            if action == "release-overwrite-preview":
                forbidden = [key for key in ("apply", "force", "force_reason", "force_by", "acknowledged", "no_verify") if key in payload]
                if forbidden:
                    raise ValueError(f"正式库覆盖预演不允许提交：{'、'.join(forbidden)}")
            elif action == "release-force":
                forbidden = [key for key in ("apply", "force", "overwrite", "no_verify") if key in payload]
                if forbidden:
                    raise ValueError(f"受控强制发布不允许提交：{'、'.join(forbidden)}；这些参数由服务端固定控制")
            else:  # pragma: no cover - callers below are fixed routes
                raise ValueError(f"不支持的正式发布动作: {action}")
            snapshot = list_release_library_rows(web_state)
            if str(snapshot.get("status") or "").upper() != "READY":
                raise RuntimeError("尚未生成正式发布库索引；请先刷新正式发布库目录")
            formal_row = next(
                (
                    row for row in snapshot.get("libraries", [])
                    if isinstance(row, Mapping) and str(row.get("library_id") or "") == formal_library
                ),
                None,
            )
            if formal_row is None:
                return jsonify({"status": "NOT_FOUND", "error": f"正式发布库不存在: {formal_library}"}), 404
            library = str(formal_row.get("raw_catalog_match") or "")
            if not library:
                return jsonify({"status": "BLOCKED", "error": "正式发布库尚未精确关联 Catalog 库，不能执行覆盖操作。"}), 409
            version_row = find_version(web_state, library, version)
            if version_row is None:
                return jsonify({"status": "NOT_FOUND", "error": f"候选版本不存在: {library}/{version}"}), 404
            readiness = version_row.get("action_readiness") or {}
            if not (readiness.get("release-check") or {}).get("enabled"):
                return jsonify({"status": "BLOCKED", "error": "请先完成扫描，再进行正式库覆盖操作。"}), 409
            payload["formal_release_target"] = {
                "library_id": formal_library,
                "release_id": str(formal_row.get("current_release") or ""),
                "version_id": str(formal_row.get("current_version") or ""),
                "source": str(formal_row.get("current_source") or formal_row.get("source") or ""),
            }
            return jsonify(create_job(action, library, version, payload, web_state)), 202
        except (FileNotFoundError, OSError) as exc:
            return jsonify({"status": "ERROR", "error": f"工作区暂不可用：{exc}"}), 503
        except RuntimeError as exc:
            return jsonify({"status": "BLOCKED", "error": str(exc)}), 409
        except (ValueError, TypeError) as exc:
            return jsonify({"status": "ERROR", "error": str(exc)}), 400

    @app.post("/api/release-libraries/<path:formal_library>/versions/<version>/preview-overwrite")
    def formal_release_overwrite_preview(formal_library: str, version: str) -> Any:
        """Prepare an overwrite preview without creating a formal delivery."""

        return formal_release_action_route("release-overwrite-preview", formal_library, version)

    @app.post("/api/release-libraries/<path:formal_library>/versions/<version>/force-overwrite")
    def formal_release_force_overwrite(formal_library: str, version: str) -> Any:
        """Execute a confirmed formal overwrite through the normal release checker."""

        return formal_release_action_route("release-force", formal_library, version)

    @app.post("/api/libraries/<library>/next")
    def next_step(library: str) -> Any:
        return library_action_route("next", library)

    @app.route('/api/libraries/<library>/semantic-review', methods=['GET', 'POST'])
    def semantic_review(library: str) -> Any:
        if request.method == 'POST':
            return library_action_route('semantic-review', library)
        try:
            web_state = state()
            item = find_catalog_library(web_state, library)
            if item is None:
                return jsonify({'status': 'NOT_FOUND', 'error': '库不存在'}), 404
            return jsonify(semantic_review_options(web_state, item))
        except (OSError, ValueError, TypeError) as exc:
            return jsonify({'status': 'ERROR', 'error': f'读取技术检查选项失败：{exc}'}), 400

    @app.post("/api/libraries/<library>/intake")
    def intake(library: str) -> Any:
        return library_action_route("intake", library)

    @app.post("/api/libraries/<library>/window")
    def window(library: str) -> Any:
        return library_action_route("window", library)

    @app.post("/api/libraries/<library>/accept-window")
    def accept_window(library: str) -> Any:
        return library_action_route("accept-window", library)

    @app.post("/api/libraries/<library>/versions/<version>/mark")
    def mark(library: str, version: str) -> Any:
        return action_route("mark", library, version)

    @app.post("/api/libraries/<library>/versions/<version>/override")
    def override(library: str, version: str) -> Any:
        return action_route("override", library, version)

    @app.post("/api/libraries/<library>/versions/<version>/file-diff")
    def file_diff(library: str, version: str) -> Any:
        return action_route("file-diff", library, version)

    @app.post("/api/libraries/<library>/versions/<version>/review-gate")
    def review_gate(library: str, version: str) -> Any:
        return action_route("review-gate", library, version)

    @app.post("/api/libraries/<library>/versions/<version>/review-packet")
    def review_packet(library: str, version: str) -> Any:
        return action_route("review-packet", library, version)

    @app.post("/api/libraries/<library>/action")
    def action_file(library: str) -> Any:
        return library_action_route("action-file", library)

    @app.post("/api/libraries/<library>/effective-rollback")
    def effective_rollback(library: str) -> Any:
        return library_action_route("effective-rollback", library)

    @app.get("/artifacts/<path:artifact_path>")
    def artifact(artifact_path: str) -> Any:
        try:
            web_state = state()
        except (FileNotFoundError, OSError) as exc:
            return jsonify({"status": "ERROR", "error": f"工作区暂不可用：{exc}"}), 503
        root = Path(web_state["catalog_html"]).resolve()
        candidate = (root / artifact_path).resolve()
        if root != candidate and root not in candidate.parents:
            return jsonify({"status": "ERROR", "error": "artifact path outside catalog html"}), 400
        if not candidate.is_file():
            return jsonify({"status": "NOT_FOUND", "error": "artifact not found"}), 404
        return send_from_directory(root, candidate.relative_to(root).as_posix())

    return app


def start_background_server(config: str | Path | None, host: str, port: int) -> dict[str, Any]:
    import socket
    from urllib.request import urlopen
    from lib_guard.atomic import atomic_write_json

    if host not in {'127.0.0.1','localhost'}:
        raise ValueError('后台模式只支持本机地址 127.0.0.1 或 localhost。')
    if not 1 <= port <= 65535:
        raise ValueError('端口必须在 1 到 65535 之间。')
    config_path=Path(config).expanduser().resolve() if config else None
    if config_path and not config_path.is_file():
        raise ValueError(f'配置不存在：{config_path}；请指定已有 lib_guard.yml。')
    try:
        with socket.socket() as probe:
            probe.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
            probe.bind((host,port))
    except OSError as exc:
        raise ValueError(f'端口 {port} 无法监听，可能已占用或权限不足：{exc}；不会自动换端口。') from exc
    directory=config_path.parent if config_path else Path.cwd()/'work'
    directory.mkdir(parents=True,exist_ok=True)
    log=directory/f'web_server_{port}.log'
    state_file=directory/f'web_server_{port}.json'
    command=[sys.executable,'-m','lib_guard.web.app','--host',host,'--port',str(port)]
    if config_path:
        command.extend(['--config',str(config_path)])
    with log.open('a',encoding='utf-8') as stream:
        process=subprocess.Popen(command,stdin=subprocess.DEVNULL,stdout=stream,stderr=subprocess.STDOUT,
                                 start_new_session=True,env={**os.environ,'PYTHONUNBUFFERED':'1'})
    url=f'http://{host}:{port}/'
    deadline=time.monotonic()+10
    while time.monotonic()<deadline:
        if process.poll() is not None:
            raise RuntimeError(f'工作台启动失败，返回码 {process.returncode}；请查看日志：{log}')
        try:
            with urlopen(url+'api/health',timeout=0.5) as response:
                health=json.load(response)
            if health.get('status')=='PASS' and health.get('service')=='lib_guard_web' and health.get('pid')==process.pid:
                result={'status':'READY','url':url,'pid':process.pid,'config':str(config_path or ''),'log':str(log),'state':str(state_file)}
                atomic_write_json(state_file,result)
                return result
        except (OSError,ValueError):
            pass
        time.sleep(0.1)
    process.terminate()
    try:
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()
    raise RuntimeError(f'工作台启动超过 10 秒仍未就绪，已停止本次子进程；日志：{log}')


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Lib Guard Web 控制台")
    parser.add_argument("--config", help="lib_guard.yml 路径")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument('--background',action='store_true',help='后台启动并验证服务就绪，关闭启动终端不会结束服务')
    args = parser.parse_args()
    if args.config and not Path(args.config).expanduser().is_file():
        parser.error(f'配置不存在：{args.config}；请指定已有 lib_guard.yml。')
    if args.background:
        try:
            result=start_background_server(args.config,args.host,args.port)
        except (OSError,ValueError,RuntimeError) as exc:
            print(f'启动失败：{exc}',file=sys.stderr)
            return 1
        print('工作台已就绪（后台运行）。请使用包含端口的完整地址：')
        print(json.dumps(result,ensure_ascii=False,indent=2))
        return 0
    app = create_app(config_path=args.config)
    app.run(host=args.host, port=args.port, debug=False)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
