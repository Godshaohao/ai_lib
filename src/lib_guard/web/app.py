"""Flask entrypoint for the small Lib Guard desktop console."""

from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import Any, Mapping
import json
import os
import secrets
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

from .read_model import _pending_window, list_file_diff_rows, list_file_tree_rows, list_library_rows, list_version_rows, load_web_state
from lib_guard.atomic import atomic_write_json
from lib_guard.project_config import BINARY_METADATA_ONLY_TYPES, DEFAULT_FILE_DIFF_TYPES, SUMMARY_ONLY_TYPES
from lib_guard.short_cli_config import load_config


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(path, dict(payload), lock=True)


def _safe_component(value: str) -> str:
    if not value or value in {".", ".."} or "/" in value or "\\" in value:
        raise ValueError("invalid path component")
    return value


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


_HASH_POLICIES = {"none", "smart", "full"}
_COMPARE_MODES = {"adjacent", "cumulative"}
_MARK_TYPES = {"FULL", "FIX", "HOTFIX", "UNKNOWN"}
_PACKAGE_TYPES = {"FULL_PACKAGE", "PARTIAL_UPDATE", "HOTFIX", "DOC_UPDATE", "UNKNOWN_PACKAGE"}
_COMPARE_DEFAULTS = {"previous_effective", "full_baseline", "none"}
_STAGES = {"initial", "stable", "final", "ad-hoc", "dated", "unknown"}
_JOB_STATUSES = {"QUEUED", "RUNNING", "COMPLETED", "FAILED", "UNKNOWN"}
_MAX_BROWSE_CHILDREN = 500


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
                return f"{label}：{str(value).strip()}"[:240]

    for line in reversed(text.splitlines()):
        clean = line.strip()
        if "scan_error" in clean.lower() or clean.lower().startswith(("error:", "fatal:")):
            return clean[:240]
    return "底层任务失败；请打开运行日志查看完整输出。"


def _list_setting(value: Any, *, label: str) -> str:
    text = _bounded_text(value, label=label, limit=300)
    if text and any(char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.,- " for char in text):
        raise ValueError(f"{label} 只允许文件类型名称、逗号、空格和连字符")
    return text


def _append_scan_settings(args: list[str], payload: Mapping[str, Any], *, include_no_render: bool = True) -> None:
    hash_policy = _bounded_text(payload.get("hash_policy"), label="哈希策略")
    if hash_policy:
        if hash_policy not in _HASH_POLICIES:
            raise ValueError("哈希策略只能是 none、smart 或 full")
        args.extend(["--hash-policy", hash_policy])
    parse_jobs = payload.get("parse_jobs")
    if parse_jobs not in {None, ""}:
        try:
            jobs = int(parse_jobs)
        except (TypeError, ValueError) as exc:
            raise ValueError("解析并发数必须是 1 到 32 的整数") from exc
        if not 1 <= jobs <= 32:
            raise ValueError("解析并发数必须是 1 到 32 的整数")
        args.extend(["--parse-jobs", str(jobs)])
    for key, flag, label in (
        ("parse_file_types", "--parse-file-types", "解析文件类型"),
        ("parse_exclude_file_types", "--parse-exclude-file-types", "排除文件类型"),
    ):
        value = _list_setting(payload.get(key), label=label)
        if value:
            args.extend([flag, value])
    if include_no_render and _payload_bool(payload, "no_render"):
        args.append("--no-render")


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
                marker = '"run_manifest"'
                marker_index = text.rfind(marker)
                if marker_index >= 0:
                    value_start = text.find('"', text.find(":", marker_index) + 1)
                    value_end = text.find('"', value_start + 1)
                    if value_start >= 0 and value_end > value_start:
                        status["run_manifest"] = text[value_start + 1:value_end]
                if return_code != 0:
                    status["error"] = _job_failure_summary(text)
            _write_json(status_path, status)
    else:
        current_status = str(status.get("status") or "").upper()
        if current_status in {"QUEUED", "RUNNING"}:
            status.update({
                "status": "UNKNOWN",
                "message": "服务重启后未接管此任务，无法确认最终结果。",
            })
        elif not status_file_valid or not current_status:
            status = {
                "status": "UNKNOWN",
                "message": "任务状态文件缺失或格式损坏，无法确认最终结果。",
            }
        elif current_status not in _JOB_STATUSES:
            status = {
                "status": "UNKNOWN",
                "message": f"任务状态未知（{current_status}），无法确认最终结果。",
            }
        _write_json(status_path, status)
    if str(status.get("status") or "").upper() == "FAILED" and not status.get("error"):
        status["error"] = _job_failure_summary(_read_tail(job_dir / "stdout.log", max_bytes=64_000, max_lines=1_000))
        _write_json(status_path, status)
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

    def state() -> dict[str, Any]:
        return load_web_state(
            config_path=app.config.get("LIB_GUARD_CONFIG"),
            cwd=app.config.get("LIB_GUARD_CWD"),
        )

    def job_root(web_state: Mapping[str, Any]) -> Path:
        configured = app.config.get("JOB_ROOT") or app.config.get("job_root")
        return Path(configured).expanduser().resolve() if configured else Path(web_state["workspace"]) / "web_jobs"

    def job_root_without_catalog() -> Path:
        configured = app.config.get("JOB_ROOT") or app.config.get("job_root")
        if configured:
            return Path(configured).expanduser().resolve()
        cfg = load_config(app.config.get("LIB_GUARD_CWD") or Path.cwd(), app.config.get("LIB_GUARD_CONFIG"))
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
            if isinstance(item, Mapping) and str(item.get("library_name")) == library:
                return item
        return None

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
        if mode not in _COMPARE_MODES:
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
        if library is not None:
            _safe_component(library)
        if version is not None:
            _safe_component(version)
        job_id = f"{action}_{secrets.token_hex(6)}"
        root = job_root(web_state) / job_id
        args = [sys.executable, "-m", "lib_guard.short_cli"]
        config_value = app.config.get("LIB_GUARD_CONFIG")
        if config_value:
            args.extend(["--config", str(config_value)])
        cli_action = "rel" if action == "release-check" else action
        if action == "catalog-refresh":
            if library is None:
                raise ValueError("目录刷新需要库")
            args.extend(["cat", library])
        elif action == "worklist":
            args.append("worklist")
        elif action == "library-discover":
            args.extend(["library", "discover"])
        elif action == "library-accept":
            args.extend(["library", "accept"])
        elif action == "library-apply":
            args.extend(["library", "apply"])
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
                raise ValueError("有效组合回退需要库")
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
            options = (
                ("max_depth", "--max-depth", "发现深度", 1, 8, 4),
                ("min_versions", "--min-versions", "最少版本数", 1, 100, 2),
                ("max_dirs", "--max-dirs", "最大目录数", 1, 100000, 5000),
                ("max_candidates", "--max-candidates", "最大候选数", 1, 10000, 200),
            )
            for key, flag, label, minimum, maximum, default in options:
                args.extend([flag, str(_bounded_int(payload.get(key), label=label, minimum=minimum, maximum=maximum, default=default))])
        elif action == "library-add":
            library_id = _bounded_text(payload.get("library_id"), label="正式库名", limit=180)
            root_path = _bounded_text(payload.get("root"), label="库根目录", limit=1000)
            if not library_id or not root_path:
                raise ValueError("新增库需要填写正式库名和库根目录")
            library_root = Path(root_path).expanduser().resolve()
            if not library_root.is_dir() or not _path_is_within(library_root, _browse_roots(web_state)):
                raise ValueError("库根目录必须是允许范围内的现有目录；请点击“浏览目录”选择")
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
            base = _safe_component(_bounded_text(payload.get("base"), label="对比基准", limit=180))
            relpath = _safe_relative_path(payload.get("relpath"), label="文件相对路径")
            file_type = _bounded_text(payload.get("type"), label="文件类型", limit=80).lower()
            if not base or not file_type:
                raise ValueError("文件对比需要填写基准版本和文件类型")
            allowed_types = DEFAULT_FILE_DIFF_TYPES | SUMMARY_ONLY_TYPES | BINARY_METADATA_ONLY_TYPES
            if file_type not in allowed_types:
                raise ValueError(f"不支持的文件类型：{file_type}。请使用已登记的视图类型。")
            force_large = _payload_bool(payload, "force_large")
            old_relpath = _bounded_text(payload.get("old_relpath"), label="旧文件相对路径", limit=500)
            if old_relpath:
                old_relpath = _safe_relative_path(old_relpath, label="旧文件相对路径")
                if base == version:
                    raise ValueError("旧文件基准版本不能与当前版本相同")
                old_file = resolve_catalog_file(web_state, library, base, old_relpath, label="旧文件")
                new_file = resolve_catalog_file(web_state, library, version, relpath, label="新文件")
                if file_type in (SUMMARY_ONLY_TYPES | BINARY_METADATA_ONLY_TYPES) and not force_large:
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
            target = _bounded_text(payload.get("to"), label="目标有效组合", limit=180)
            by = _bounded_text(payload.get("by"), label="回退人", limit=80)
            reason = _bounded_text(payload.get("reason"), label="回退原因", limit=500)
            if not target or not by or not reason:
                raise ValueError("有效组合回退需要填写目标、处理人和原因")
            args.extend(["--to", target, "--by", by, "--reason", reason])
        elif action == "cmp":
            base = str(payload.get("base") or "").strip()
            if base:
                args.extend(["--base", _safe_component(base)])
            mode = _bounded_text(payload.get("mode") or "adjacent", label="对比模式")
            if mode not in _COMPARE_MODES:
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
        elif action == "next":
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
                    raise ValueError("接受候选有效版必须填写接受人")
                args.extend(["--by", accepted_by])
                note = _bounded_text(payload.get("note"), label="接受说明")
                if note:
                    args.extend(["--note", note])
        elif action == "intake":
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
            accepted_by = _bounded_text(payload.get("accepted_by"), label="接受人", limit=80)
            if not accepted_by:
                raise ValueError("接受候选有效版必须填写接受人")
            args.extend(["--accepted-by", accepted_by])
            note = _bounded_text(payload.get("note"), label="接受说明")
            if note:
                args.extend(["--note", note])
        elif action == "mark":
            package_type = _bounded_text(payload.get("type"), label="版本类型")
            if package_type not in _MARK_TYPES:
                raise ValueError("版本类型只能是 FULL、FIX、HOTFIX 或 UNKNOWN")
            args.extend(["--type", package_type])
            note = _bounded_text(payload.get("note"), label="修正说明")
            if note:
                args.extend(["--note", note])
        elif action == "override":
            values = (
                ("stage", _STAGES, "阶段"),
                ("package_type", _PACKAGE_TYPES, "包类型"),
                ("compare_default", _COMPARE_DEFAULTS, "默认对比"),
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
        with jobs_lock:
            if not app.config.get("TESTING"):
                if any(process.poll() is None and job_targets.get(existing) == library for existing, process in jobs.items()):
                    raise RuntimeError(f"库正在执行其他动作，请等待当前任务结束：{library}")
            created_epoch = time.time()
            root.mkdir(parents=True, exist_ok=False)
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
        return jsonify({"status": "PASS", "service": "lib_guard_web"})

    @app.get("/api/workspace")
    def workspace() -> Any:
        try:
            web_state = state()
        except (FileNotFoundError, OSError) as exc:
            return jsonify({"status": "ERROR", "error": str(exc)}), 503
        return jsonify({
            "status": "PASS",
            "paths": web_state["paths"],
            "scan_strategy": web_state["scan_strategy"],
            "runtime_state": web_state["runtime_state"],
            "catalog_source": "existing_catalog",
            "write_policy": "web_actions_are_allowlisted",
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
        rows = list_file_diff_rows(web_state, library, version)
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
            "rows": rows,
            "count": len(rows),
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
            if action == "rel" and not (readiness.get("release-check") or {}).get("enabled"):
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
                    return jsonify({"status": "ERROR", "error": "接入窗口文件无法读取，请重新生成接入窗口。"}), 422
                if window_state != "PENDING" or not candidate:
                    return jsonify({"status": "BLOCKED", "error": "当前没有处于待接受状态的候选有效版；请先生成接入窗口。"}), 409
                if not window.get("candidate_manifest_exists", False):
                    return jsonify({"status": "BLOCKED", "error": "候选有效版尚未生成完整清单；请先完成接入计划。"}), 409
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

    @app.post("/api/libraries/<library>/next")
    def next_step(library: str) -> Any:
        return library_action_route("next", library)

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


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Lib Guard Web 控制台")
    parser.add_argument("--config", help="lib_guard.yml 路径")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5000)
    args = parser.parse_args()
    app = create_app(config_path=args.config)
    app.run(host=args.host, port=args.port, debug=False)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
