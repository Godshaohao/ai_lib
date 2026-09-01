"""Read-only view model for the Lib Guard web console.

The web layer reads the existing catalog/runtime projection. It does not
discover RAW directories and it does not write catalog or scan facts.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping
import json
import re

from lib_guard.catalog.runtime import (
    inspect_catalog_runtime,
    load_catalog_runtime,
    merge_catalog_runtime,
)
from lib_guard.effective.pointer import load_current_pointer
from lib_guard.project_config import BINARY_METADATA_ONLY_TYPES, DEFAULT_FILE_DIFF_TYPES, SUMMARY_ONLY_TYPES
from lib_guard.short_cli_config import load_config
from lib_guard.window.resolver import default_window_path


_SYNTHETIC_PACKAGE_ROOT_RE = re.compile(r"^(?:upstream_[0-9a-f]{8,}|.+_source_package)$", re.IGNORECASE)


def load_web_state(
    *,
    config_path: str | Path | None = None,
    cwd: str | Path | None = None,
    config: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Load the existing workspace state without refreshing or discovering."""

    root = Path(cwd or Path.cwd()).resolve()
    cfg = dict(config) if config is not None else load_config(root, config_path)
    catalog_path = Path(str(cfg.get("catalog") or "catalog/catalog.json")).expanduser().resolve()
    if not catalog_path.exists():
        raise FileNotFoundError(f"catalog not found: {catalog_path}")
    try:
        raw_catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError) as exc:
        raise OSError(f"catalog 无法读取或格式已损坏: {catalog_path}") from exc
    if not isinstance(raw_catalog, Mapping):
        raise OSError(f"catalog 顶层必须是 JSON 对象: {catalog_path}")
    runtime = load_catalog_runtime(catalog_path, raw_catalog)
    catalog = merge_catalog_runtime(raw_catalog, runtime)
    return {
        "config": cfg,
        "catalog_path": catalog_path,
        "runtime_state": inspect_catalog_runtime(catalog_path, raw_catalog),
        "catalog_html": Path(str(cfg.get("catalog_html") or catalog_path.parent / "html")).expanduser().resolve(),
        "workspace": Path(str(cfg.get("workspace") or catalog_path.parent.parent)).expanduser().resolve(),
        "paths": {
            "workspace": str(Path(str(cfg.get("workspace") or catalog_path.parent.parent)).expanduser().resolve()),
            "raw_root": str(Path(str(cfg.get("raw_root") or "")).expanduser().resolve()),
            "catalog": str(catalog_path),
            "catalog_html": str(Path(str(cfg.get("catalog_html") or catalog_path.parent / "html")).expanduser().resolve()),
            "reports": str(Path(str(cfg.get("reports") or catalog_path.parent.parent / "reports")).expanduser().resolve()),
            "diff": str(Path(str(cfg.get("diff") or catalog_path.parent.parent / "diff")).expanduser().resolve()),
        },
        "scan_strategy": {
            "hash_policy": str(cfg.get("hash_policy") or "smart"),
            "parse_jobs": str(cfg.get("parse_jobs") or "8"),
            "parse_file_types": str(cfg.get("parse_file_types") or ""),
            "parse_exclude_file_types": str(cfg.get("parse_exclude_file_types") or ""),
            "render_detail": str(cfg.get("render_detail") or "true").lower() not in {"0", "false", "no"},
        },
        "catalog": catalog,
    }


def _sort_key(version: Mapping[str, Any]) -> tuple[int, str]:
    version_id = str(version.get("version_id") or "")
    match = re.search(r"(20\d{6})", version_id)
    return (int(match.group(1)) if match else 0, version_id)


def _scan_status(version: Mapping[str, Any]) -> str:
    return str((version.get("scan") or {}).get("status") or "NOT_SCANNED")


def _diff_status(version: Mapping[str, Any], mode: str = "adjacent") -> str:
    diff = version.get("diff") or {}
    if mode == "cumulative" and diff.get("cumulative_base_version"):
        return str(diff.get("cumulative_status") or "NOT_APPLICABLE")
    if mode != "cumulative" and diff.get("adjacent_old_version"):
        return str(diff.get("adjacent_status") or "NOT_APPLICABLE")
    if diff.get("base_version"):
        return str(diff.get("base_status") or "NOT_APPLICABLE")
    return "NOT_APPLICABLE"


def _release_status(version: Mapping[str, Any]) -> str:
    release = version.get("release") or {}
    return str(release.get("check_status") or release.get("status") or "UNKNOWN")


def _is_initial_baseline(versions: list[Mapping[str, Any]], version: Mapping[str, Any]) -> bool:
    """A first version is a fact baseline, not an unprocessed comparison."""

    if _base_version(version):
        return False
    ordered = sorted(versions, key=_sort_key)
    return bool(ordered) and ordered[0] is version


def _change_summary(version: Mapping[str, Any], *, is_initial_baseline: bool = False) -> str:
    if is_initial_baseline:
        return "初始基线"
    status = _diff_status(version).upper()
    if status in {"PENDING", "NOT_APPLICABLE"}:
        return "待生成对比"
    if status in {"SAME", "NO_DIFF"}:
        return "无变化"
    diff = version.get("diff") if isinstance(version.get("diff"), Mapping) else {}
    summary = diff.get("summary") if isinstance(diff.get("summary"), Mapping) else {}
    counts = {
        "added": summary.get("added", summary.get("added_count")),
        "removed": summary.get("removed", summary.get("removed_count")),
        "changed": summary.get("changed", summary.get("changed_count")),
    }
    if all(isinstance(value, int) for value in counts.values()):
        return f"+{counts['added']} / -{counts['removed']} / ~{counts['changed']}"
    return "已生成对比"


_SCAN_READY_STATUSES = {"PASS", "PASSED", "SCANNED"}
_COMPLETED_STATUSES = _SCAN_READY_STATUSES | {"DIFF_DONE", "CHECKED", "SAME", "NO_DIFF", "COMPLETED", "COMPLETE", "NOT_APPLICABLE"}


def scan_status_ready(status: str) -> bool:
    return str(status or "").upper() in _SCAN_READY_STATUSES


def scan_evidence_ready(version: Mapping[str, Any]) -> bool:
    """Require a scan status and identity-matching scan evidence.

    ``scan_meta.json`` is the cheap readiness index emitted beside every
    modern scan.  Do not parse the full inventory just to decide whether a
    scan exists; older outputs without metadata retain the inventory fallback.
    """

    if not scan_status_ready(_scan_status(version)):
        return False
    scan = version.get("scan") if isinstance(version.get("scan"), Mapping) else {}
    scan_dir = scan.get("scan_dir") or version.get("scan_dir")
    if not scan_dir:
        return False
    scan_path = Path(str(scan_dir))
    inventory_path = scan_path / "file_inventory.json"
    if not scan_path.is_dir() or not inventory_path.is_file():
        return False
    meta_path = scan_path / "scan_meta.json"
    if meta_path.is_file():
        try:
            metadata = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, TypeError, ValueError):
            return False
        if not isinstance(metadata, Mapping):
            return False
        if str(metadata.get("status") or "PASS").upper() not in _SCAN_READY_STATUSES:
            return False
        expected_scan_id = str(scan.get("scan_id") or "").strip()
        metadata_scan_id = str(metadata.get("scan_id") or "").strip()
        if expected_scan_id and metadata_scan_id != expected_scan_id:
            return False
        expected_root = str(version.get("raw_path") or "").strip()
        metadata_root = str(metadata.get("root_path") or "").strip()
        if expected_root and metadata_root:
            try:
                if Path(expected_root).expanduser().resolve() != Path(metadata_root).expanduser().resolve():
                    return False
            except OSError:
                return False
        return True
    try:
        inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError):
        return False
    if not isinstance(inventory, Mapping) or not isinstance(inventory.get("files"), list):
        return False
    expected_scan_id = str(scan.get("scan_id") or "").strip()
    inventory_scan_id = str(inventory.get("scan_id") or "").strip()
    if expected_scan_id and inventory_scan_id != expected_scan_id:
        return False
    expected_root = str(version.get("raw_path") or "").strip()
    inventory_root = str(inventory.get("root_path") or "").strip()
    if expected_root and inventory_root:
        try:
            if Path(expected_root).expanduser().resolve() != Path(inventory_root).expanduser().resolve():
                return False
        except OSError:
            return False
    return True


def _base_version(version: Mapping[str, Any], mode: str = "adjacent") -> str:
    diff = version.get("diff") or {}
    if mode == "cumulative":
        values = (diff.get("cumulative_base_version"), diff.get("base_version"), diff.get("adjacent_old_version"))
    else:
        values = (diff.get("adjacent_old_version"), diff.get("base_version"), diff.get("cumulative_base_version"))
    return next((str(value) for value in values if value), "")


_FILE_TYPE_BY_SUFFIX = {
    ".lef": "lef",
    ".lib": "liberty",
    ".v": "verilog",
    ".sv": "systemverilog",
    ".cdl": "cdl",
    ".sp": "sp",
    ".spi": "spice",
    ".sdc": "sdc",
    ".upf": "upf",
    ".cpf": "cpf",
    ".spef": "spef",
    ".db": "db",
    ".gds": "gds",
    ".gds2": "gds",
    ".oas": "oas",
    ".ibis": "ibis",
    ".pwl": "pwl",
    ".snp": "snp",
}


def _file_type_for_path(path: str) -> str:
    suffix = Path(str(path or "")).suffix.lower()
    return _FILE_TYPE_BY_SUFFIX.get(suffix, "unknown")


def _diff_entry_path(value: Any, *, side: str = "new") -> str:
    if isinstance(value, Mapping):
        for key in (("path", "relpath", "new") if side == "new" else ("path", "relpath", "old")):
            candidate = value.get(key)
            if candidate:
                return str(candidate)
    return str(value or "")


def _diff_file_path(version: Mapping[str, Any]) -> Path | None:
    diff = version.get("diff") if isinstance(version.get("diff"), Mapping) else {}
    for key in ("adjacent_diff_dir", "base_diff_dir", "cumulative_diff_dir"):
        directory = diff.get(key)
        if not directory:
            continue
        path = Path(str(directory)).expanduser() / "file_diff.json"
        if path.is_file():
            return path
    return None


def list_file_diff_rows(web_state: Mapping[str, Any], library_name: str, version_id: str) -> list[dict[str, Any]]:
    """Expose the existing file-level diff as bounded UI rows.

    This reads only ``file_diff.json`` for the selected version. It never walks
    RAW and never opens the compared files.
    """

    catalog = web_state.get("catalog") if isinstance(web_state.get("catalog"), Mapping) else {}
    library = next(
        (item for item in catalog.get("libraries", []) or [] if isinstance(item, Mapping) and str(item.get("library_name")) == library_name),
        None,
    )
    if not isinstance(library, Mapping):
        return []
    version = next(
        (item for item in library.get("versions", []) or [] if isinstance(item, Mapping) and str(item.get("version_id")) == version_id),
        None,
    )
    if not isinstance(version, Mapping):
        return []
    diff_path = _diff_file_path(version)
    if diff_path is None:
        return []
    try:
        diff = json.loads(diff_path.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError):
        return []
    if not isinstance(diff, Mapping):
        return []

    path_pairs: dict[str, tuple[str, str]] = {}
    for key in ("renamed_or_moved", "logical_path_changes"):
        for item in diff.get(key, []) or []:
            if not isinstance(item, Mapping):
                continue
            old_path = _diff_entry_path(item, side="old")
            new_path = _diff_entry_path(item, side="new")
            logical_path = str(item.get("logical_path") or "")
            if old_path and new_path:
                path_pairs[new_path] = (old_path, new_path)
                if logical_path:
                    path_pairs[logical_path] = (old_path, new_path)

    rows: list[dict[str, Any]] = []
    sections = (("added", "ADDED"), ("removed", "REMOVED"), ("changed", "CHANGED"), ("renamed_or_moved", "PATH_CHANGED"), ("logical_path_changes", "PATH_CHANGED"), ("unverified", "PATH_CHANGED"))
    seen: set[tuple[str, str, str]] = set()
    for section, change in sections:
        for raw_item in diff.get(section, []) or []:
            item = raw_item if isinstance(raw_item, Mapping) else {}
            new_path = _diff_entry_path(raw_item, side="new") if change != "REMOVED" else ""
            old_path = _diff_entry_path(raw_item, side="old") if change != "ADDED" else ""
            if change == "CHANGED" and new_path in path_pairs:
                old_path, new_path = path_pairs[new_path]
            if change == "PATH_CHANGED" and not new_path and item.get("logical_path"):
                new_path = str(item.get("logical_path"))
            if change == "PATH_CHANGED" and new_path in path_pairs:
                old_path, new_path = path_pairs[new_path]
            path = new_path or old_path
            if not path:
                continue
            key = (change, old_path, new_path)
            if key in seen:
                continue
            seen.add(key)
            file_type = str(item.get("file_type") or item.get("view_type") or item.get("type") or _file_type_for_path(path)).lower()
            deep_available = bool(old_path and new_path and file_type != "unknown" and file_type in (DEFAULT_FILE_DIFF_TYPES | SUMMARY_ONLY_TYPES | BINARY_METADATA_ONLY_TYPES))
            rows.append({
                "change": change,
                "old_path": old_path or None,
                "new_path": new_path or None,
                "file_type": file_type,
                "evidence_mode": str(item.get("evidence_mode") or item.get("comparison") or ("metadata-only" if file_type in BINARY_METADATA_ONLY_TYPES else "summary-only" if file_type in SUMMARY_ONLY_TYPES else "file-level")),
                "review_lane": str(item.get("review_lane") or item.get("lane") or "default"),
                "deep_diff_available": deep_available,
                "requires_force_large": file_type in (SUMMARY_ONLY_TYPES | BINARY_METADATA_ONLY_TYPES),
                "reason": str(item.get("reason") or ""),
            })
    return rows


def list_file_tree_rows(web_state: Mapping[str, Any], library_name: str, version_id: str) -> dict[str, Any]:
    """Return the current version's file structure from scan evidence.

    The operation console must not walk RAW just to draw a tree.  The scanner
    already records the bounded, relative-path inventory that the UI needs.
    ``abs_path`` is intentionally omitted so the browser only exposes paths
    that are useful for selection and copying. ``path`` remains the exact
    scan-relative path; ``display_path`` may hide one known packaging wrapper
    such as ``upstream_<commit>`` without changing the evidence identity.
    """

    catalog = web_state.get("catalog") if isinstance(web_state.get("catalog"), Mapping) else {}
    library = next(
        (item for item in catalog.get("libraries", []) or [] if isinstance(item, Mapping) and str(item.get("library_name")) == library_name),
        None,
    )
    if not isinstance(library, Mapping):
        return {"status": "NOT_FOUND", "library": library_name, "version": version_id, "files": [], "file_count": 0}
    version = next(
        (item for item in library.get("versions", []) or [] if isinstance(item, Mapping) and str(item.get("version_id")) == version_id),
        None,
    )
    if not isinstance(version, Mapping):
        return {"status": "NOT_FOUND", "library": library_name, "version": version_id, "files": [], "file_count": 0}
    scan = version.get("scan") if isinstance(version.get("scan"), Mapping) else {}
    scan_dir = scan.get("scan_dir") or version.get("scan_dir")
    inventory_path = Path(str(scan_dir)).expanduser() / "file_inventory.json" if scan_dir else None
    if inventory_path is None or not inventory_path.is_file():
        return {
            "status": "NOT_READY",
            "library": library_name,
            "version": version_id,
            "root_path": str(version.get("raw_path") or ""),
            "files": [],
            "file_count": 0,
            "message": "当前版本还没有可用的扫描文件清单。",
        }
    try:
        inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError):
        return {
            "status": "INVALID",
            "library": library_name,
            "version": version_id,
            "root_path": str(version.get("raw_path") or ""),
            "files": [],
            "file_count": 0,
            "message": "扫描文件清单无法读取。",
        }
    if not isinstance(inventory, Mapping) or not isinstance(inventory.get("files"), list):
        return {
            "status": "INVALID",
            "library": library_name,
            "version": version_id,
            "root_path": str(version.get("raw_path") or ""),
            "files": [],
            "file_count": 0,
            "message": "扫描文件清单格式不完整。",
        }

    raw_files = [item for item in inventory["files"] if isinstance(item, Mapping)]
    raw_files.sort(key=lambda item: str(item.get("path") or "").casefold())
    normalized_files: list[tuple[Mapping[str, Any], str]] = []
    for item in raw_files[:20_000]:
        path = str(item.get("path") or "").replace("\\", "/").strip("/")
        if not path or path.startswith("../") or "/../" in path:
            continue
        normalized_files.append((item, path))

    first_parts = {path.split("/", 1)[0] for _, path in normalized_files if "/" in path}
    display_prefix = next(iter(first_parts), "") if len(first_parts) == 1 else ""
    if not _SYNTHETIC_PACKAGE_ROOT_RE.fullmatch(display_prefix):
        display_prefix = ""

    files: list[dict[str, Any]] = []
    for item, path in normalized_files:
        file_type = str(item.get("file_type") or item.get("view_type") or _file_type_for_path(path)).lower()
        large_hash_skipped = bool(item.get("is_large_hash_skipped"))
        if large_hash_skipped:
            evidence = "大文件未读取完整内容"
        elif str(item.get("hash_status") or "").upper() == "CALCULATED":
            evidence = "已记录内容指纹"
        else:
            evidence = "仅记录文件清单"
        files.append(
            {
                "path": path,
                "display_path": path[len(display_prefix) + 1 :] if display_prefix else path,
                "name": str(item.get("name") or Path(path).name),
                "file_type": file_type,
                "size_bytes": int(item.get("size_bytes") or 0),
                "role": str(item.get("role") or ""),
                "domain": str(item.get("domain") or ""),
                "change_status": str(item.get("change_status") or "unchanged").lower(),
                "large_hash_skipped": large_hash_skipped,
                "evidence": evidence,
            }
        )
    return {
        "status": "PASS",
        "library": library_name,
        "version": version_id,
        "root_path": str(inventory.get("root_path") or version.get("raw_path") or ""),
        "files": files,
        "file_count": len(raw_files),
        "returned_count": len(files),
        "truncated": len(raw_files) > 20_000,
        "source": "scan_file_inventory",
    }


def _current_effective_pointer(state: Mapping[str, Any], library: Mapping[str, Any]) -> dict[str, Any]:
    library_id = str(library.get("library_id") or library.get("library_name") or "")
    try:
        return load_current_pointer(state["catalog_html"], library_id)
    except (OSError, TypeError, ValueError) as exc:
        return {"_invalid": True, "error": str(exc)}


def _action_readiness(
    version: Mapping[str, Any],
    *,
    scan_ready: bool | None = None,
) -> dict[str, dict[str, Any]]:
    """Expose user-facing action gates without changing the underlying CLI."""

    scan_status = _scan_status(version).upper()
    base_version = _base_version(version)
    if scan_ready is None:
        scan_ready = scan_evidence_ready(version)
    return {
        "scan": {
            "enabled": True,
            "label": "重新扫描" if scan_ready else "生成扫描",
            "reason": "可重新生成扫描事实" if scan_ready else "尚未生成可用的扫描证据",
        },
        "compare": {
            "enabled": bool(base_version) and scan_ready,
            "label": "重新对比" if _diff_status(version).upper() in _COMPLETED_STATUSES else "执行对比",
            "reason": (
                "扫描证据不可用，请先完成扫描"
                if not scan_ready
                else "已有对比基准"
                if base_version
                else "缺少对比基准，无法执行对比"
            ),
        },
        "release-check": {
            "enabled": scan_ready,
            "label": "重新检查" if _release_status(version).upper() in _COMPLETED_STATUSES else "发布检查",
            "reason": "扫描证据已就绪" if scan_ready else "请先完成扫描，再进行发布检查",
        },
    }


def _review_decision(
    version: Mapping[str, Any],
    *,
    current_effective: bool | None = None,
    scan_ready: bool | None = None,
    is_initial_baseline: bool = False,
) -> dict[str, str]:
    """Return one explainable workbench decision and its next action."""

    if scan_ready is None:
        scan_ready = scan_evidence_ready(version)
    readiness = _action_readiness(version, scan_ready=scan_ready)
    scan_status = _scan_status(version).upper()
    diff_status = _diff_status(version).upper()
    if "FAIL" in scan_status:
        return {
            "label": "扫描失败",
            "reason": "请先查看扫描结果，再决定是否重新扫描。",
            "next_action": "查看扫描结果",
        }
    if not scan_ready:
        return {
            "label": "待生成扫描",
            "reason": "当前版本还没有可用的扫描证据。",
            "next_action": "生成扫描",
        }
    if is_initial_baseline:
        return {
            "label": "初始基线",
            "reason": "这是库内最早版本，当前只检查版本自身事实，无需版本对比。",
            "next_action": "查看详情",
        }
    if "FAIL" in diff_status or "ERROR" in diff_status:
        return {
            "label": "对比失败",
            "reason": "扫描证据已存在，但最近一次对比失败；不能按已完成处理。",
            "next_action": "查看对比结果",
        }
    is_current = bool(version.get("current_effective")) if current_effective is None else current_effective
    if is_current:
        return {
            "label": "当前有效版",
            "reason": "这是目录记录的当前使用基线。",
            "next_action": "查看详情",
        }
    if not readiness["compare"]["enabled"] and diff_status != "NOT_APPLICABLE":
        return {
            "label": "待确认基准",
            "reason": "当前版本缺少可用的对比基准。",
            "next_action": "补充基准",
        }
    if diff_status in {"PENDING", "NOT_APPLICABLE"}:
        return {
            "label": "已读取，待处理",
            "reason": "扫描事实已读取，是否对比取决于版本关系和基准。",
            "next_action": "执行对比" if readiness["compare"]["enabled"] else "查看详情",
        }
    return {
        "label": "已完成",
        "reason": "扫描和对比已有结果；正式发布状态单独维护，不影响这里的 IP 使用判断。",
        "next_action": "查看详情",
    }


def _pending_window(state: Mapping[str, Any], library: Mapping[str, Any]) -> dict[str, Any]:
    report_slug = str(library.get("report_slug") or library.get("library_name") or "")
    path = default_window_path(state["catalog_html"], library, report_slug)
    result: dict[str, Any] = {
        "exists": path.exists(),
        "candidate_effective_id": "",
        "candidate_manifest_exists": False,
        "state": "MISSING",
        "path": str(path),
    }
    if not path.exists():
        return result
    try:
        window = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError):
        result["state"] = "INVALID"
        return result
    candidate = window.get("candidate_effective") if isinstance(window, Mapping) else None
    candidate = candidate if isinstance(candidate, Mapping) else {}
    if not isinstance(window, Mapping):
        result["state"] = "INVALID"
        return result
    result["state"] = str(window.get("state") or "PRESENT").upper()
    result["candidate_effective_id"] = str(candidate.get("effective_id") or "")
    manifest = candidate.get("manifest")
    result["candidate_manifest_exists"] = bool(manifest and Path(str(manifest)).is_file())
    return result


def list_library_rows(state: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Return compact library rows for the left navigation."""

    rows: list[dict[str, Any]] = []
    scan_ready_cache: dict[tuple[str, str, str], bool] = {}

    def cached_scan_ready(version: Mapping[str, Any]) -> bool:
        scan = version.get("scan") if isinstance(version.get("scan"), Mapping) else {}
        key = (
            str(scan.get("scan_dir") or version.get("scan_dir") or ""),
            str(scan.get("scan_id") or ""),
            str(version.get("raw_path") or ""),
        )
        if key not in scan_ready_cache:
            scan_ready_cache[key] = scan_evidence_ready(version)
        return scan_ready_cache[key]

    for library in state.get("catalog", {}).get("libraries", []) or []:
        if not isinstance(library, Mapping):
            continue
        versions = [item for item in library.get("versions", []) or [] if isinstance(item, Mapping)]
        ordered_versions = sorted(versions, key=_sort_key)
        summary = library.get("summary") or {}
        pointer = _current_effective_pointer(state, library)
        pointer_current = str(pointer.get("current_effective_id") or "")
        pointer_invalid = bool(pointer.get("_invalid"))
        current = pointer_current or (
            None
            if pointer_invalid
            else next((str(item.get("version_id")) for item in versions if item.get("current_effective")), None)
        )
        rows.append(
            {
                "library_name": str(library.get("library_name") or ""),
                "display_name": str(library.get("display_name") or library.get("library_name") or ""),
                "vendor": str(library.get("vendor") or ""),
                "category": str(library.get("category") or ""),
                "version_count": int(summary.get("version_count") or len(versions)),
                "latest_version": str(summary.get("latest_version") or ""),
                "current_effective": current,
                "current_effective_id": pointer_current or current or "",
                "scan_pending": int(summary.get("scan_pending") or 0),
                 "diff_pending": int(summary.get("diff_pending") or 0),
                "review_pending_count": sum(
                    1
                    for item in ordered_versions
                    if _review_decision(
                        item,
                        scan_ready=cached_scan_ready(item),
                        is_initial_baseline=_is_initial_baseline(ordered_versions, item),
                        current_effective=(
                            str(item.get("version_id")) == pointer_current
                            if pointer_current
                            else (False if pointer_invalid else bool(item.get("current_effective")))
                        ),
                    )["label"] not in {"已完成", "当前有效版", "初始基线"}
                ),
                "effective_pointer_state": "INVALID" if pointer_invalid else ("SET" if pointer_current else "CATALOG"),
                "pending_window": _pending_window(state, library),
            }
        )
    return sorted(rows, key=lambda row: row["library_name"].lower())


def list_version_rows(
    state: Mapping[str, Any],
    library_name: str,
    *,
    offset: int = 0,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Return version facts and safe links for one formal library name."""

    catalog = state.get("catalog", {})
    library = next(
        (
            item
            for item in catalog.get("libraries", []) or []
            if isinstance(item, Mapping) and str(item.get("library_name")) == library_name
        ),
        None,
    )
    if not library:
        return []

    catalog_html = Path(state["catalog_html"])
    pointer = _current_effective_pointer(state, library)
    pointer_current = str(pointer.get("current_effective_id") or "")
    pointer_invalid = bool(pointer.get("_invalid"))
    rows: list[dict[str, Any]] = []
    scan_ready_cache: dict[tuple[str, str, str], bool] = {}

    def cached_scan_ready(version: Mapping[str, Any]) -> bool:
        scan = version.get("scan") if isinstance(version.get("scan"), Mapping) else {}
        key = (
            str(scan.get("scan_dir") or version.get("scan_dir") or ""),
            str(scan.get("scan_id") or ""),
            str(version.get("raw_path") or ""),
        )
        if key not in scan_ready_cache:
            scan_ready_cache[key] = scan_evidence_ready(version)
        return scan_ready_cache[key]

    sorted_versions = sorted(library.get("versions", []) or [], key=_sort_key, reverse=True)
    start = max(0, int(offset or 0))
    end = None if limit is None else start + max(0, int(limit))
    for version in sorted_versions[start:end]:
        if not isinstance(version, Mapping):
            continue
        report_slug = str(version.get("report_slug") or library.get("report_slug") or "")
        version_id = str(version.get("version_id") or "")
        detail_path = catalog_html / "libraries" / report_slug / "versions" / version_id / "index.html"
        scan = version.get("scan") or {}
        diff = version.get("diff") or {}
        current_effective = (
            version_id == pointer_current
            if pointer_current
            else (False if pointer_invalid else bool(version.get("current_effective")))
        )
        scan_ready = cached_scan_ready(version)
        initial_baseline = _is_initial_baseline(sorted_versions, version)
        review_decision = _review_decision(
            version,
            current_effective=current_effective,
            scan_ready=scan_ready,
            is_initial_baseline=initial_baseline,
        )
        rows.append(
            {
                "version_id": version_id,
                "version_key": str(version.get("version_key") or ""),
                "stage": str(version.get("stage") or "unknown"),
                "package_type": str(version.get("package_type") or "UNKNOWN_PACKAGE"),
                "current_effective": current_effective,
                "scan_status": _scan_status(version),
                "scan_dir": scan.get("scan_dir"),
                "scan_evidence_ready": scan_ready,
                "scan_html": scan.get("scan_html"),
                "diff_status": _diff_status(version),
                "diff_html": (
                    diff.get("adjacent_diff_html")
                    if diff.get("adjacent_old_version")
                    else diff.get("base_diff_html")
                ),
                "base_version": _base_version(version) or None,
                "adjacent_base_version": str(diff.get("adjacent_old_version") or "") or None,
                "cumulative_base_version": str(diff.get("cumulative_base_version") or "") or None,
                "release_status": _release_status(version),
                "raw_path": str(version.get("raw_path") or ""),
                "version_detail_path": str(detail_path) if detail_path.exists() else None,
                "version_detail_url": f"/artifacts/{detail_path.relative_to(catalog_html).as_posix()}" if detail_path.exists() else None,
                "action_readiness": _action_readiness(version, scan_ready=scan_ready),
                "review_decision": review_decision,
                "ip_decision": review_decision["label"],
                "change_summary": _change_summary(version, is_initial_baseline=initial_baseline),
                "next_action": review_decision["next_action"],
                "effective_pointer_state": "INVALID" if pointer_invalid else ("SET" if pointer_current else "CATALOG"),
            }
        )
    return rows


__all__ = ["list_file_diff_rows", "list_file_tree_rows", "list_library_rows", "list_version_rows", "load_web_state", "scan_evidence_ready", "scan_status_ready"]
