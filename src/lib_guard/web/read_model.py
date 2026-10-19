"""Read-only view model for the Lib Guard web console.

The web layer reads the existing catalog/runtime projection. It does not
discover RAW directories and it does not write catalog or scan facts.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping
import hashlib
import json
import os
import re
from datetime import datetime, timezone

from lib_guard.catalog.runtime import (
    inspect_catalog_runtime,
    load_catalog_runtime,
    merge_catalog_runtime,
)
from lib_guard.effective.pointer import load_current_pointer
from lib_guard.library_registry import read_library_list, suggest_formal_library_id
from lib_guard.package.types import package_kind
from lib_guard.project_config import (
    BINARY_METADATA_ONLY_TYPES,
    DEFAULT_FILE_DIFF_TYPES,
    SUMMARY_ONLY_TYPES,
    default_discovery_strategy,
    default_scan_strategy,
)
from lib_guard.render.catalog_render_common import safe as report_safe
from lib_guard.short_cli_config import load_config
from lib_guard.window.resolver import default_window_path


_SYNTHETIC_PACKAGE_ROOT_RE = re.compile(r"^(?:upstream_[0-9a-f]{8,}|.+_source_package)$", re.IGNORECASE)


def load_web_state(
    *,
    config_path: str | Path | None = None,
    cwd: str | Path | None = None,
    config: Mapping[str, Any] | None = None,
    allow_missing_catalog: bool = False,
) -> dict[str, Any]:
    """Load the existing workspace state without refreshing or discovering."""

    root = Path(cwd or Path.cwd()).resolve()
    cfg = dict(config) if config is not None else load_config(root, config_path)
    catalog_path = Path(str(cfg.get("catalog") or "catalog/catalog.json")).expanduser().resolve()
    if not catalog_path.exists():
        if not allow_missing_catalog:
            raise FileNotFoundError(f"catalog not found: {catalog_path}")
        raw_catalog: Mapping[str, Any] = {"libraries": []}
        catalog_state = "NOT_INITIALIZED"
    else:
        try:
            loaded_catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
        except (OSError, TypeError, ValueError) as exc:
            raise OSError(f"catalog 无法读取或格式已损坏: {catalog_path}") from exc
        if not isinstance(loaded_catalog, Mapping):
            raise OSError(f"catalog 顶层必须是 JSON 对象: {catalog_path}")
        raw_catalog = loaded_catalog
        catalog_state = "READY"
    runtime = load_catalog_runtime(catalog_path, raw_catalog)
    catalog = merge_catalog_runtime(raw_catalog, runtime)
    scan_defaults = default_scan_strategy()
    discovery_defaults = default_discovery_strategy()
    return {
        "config": cfg,
        "catalog_path": catalog_path,
        "catalog_state": catalog_state,
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
            "release_root": str(Path(str(cfg.get("release_root") or catalog_path.parent.parent / "release_area")).expanduser().resolve()),
            "release_library_index": str(Path(str(cfg.get("release_library_index") or catalog_path.parent.parent / "config" / "release_libraries" / "latest.json")).expanduser().resolve()),
        },
        "scan_strategy": {
            "hash_policy": str(cfg.get("hash_policy") or scan_defaults["hash_policy"]),
            "parse_jobs": str(cfg.get("parse_jobs") or scan_defaults["parse_jobs"]),
            "force_hash_file_types": str(cfg.get("force_hash_file_types") or ""),
            "skip_hash_file_types": str(cfg.get("skip_hash_file_types") or ""),
            "parse_file_types": str(cfg.get("parse_file_types") or ""),
            "parse_exclude_file_types": str(cfg.get("parse_exclude_file_types") or ""),
            "render_detail": str(cfg.get("render_detail") or scan_defaults["render_detail"]).lower() not in {"0", "false", "no"},
        },
        "discovery_strategy": {
            "max_depth": str(cfg.get("discover_max_depth") or discovery_defaults["max_depth"]),
            "min_versions": str(cfg.get("discover_min_versions") or discovery_defaults["min_versions"]),
            "max_dirs": str(cfg.get("discover_max_dirs") or discovery_defaults["max_dirs"]),
            "max_candidates": str(cfg.get("discover_max_candidates") or discovery_defaults["max_candidates"]),
        },
        "catalog": catalog,
    }


def _candidate_id(library_id: str, root_abs: str) -> str:
    """Return a stable browser-safe identity for one persisted candidate row."""

    source = f"{library_id}\0{Path(root_abs).expanduser().resolve()}"
    return hashlib.sha256(source.encode("utf-8")).hexdigest()[:20]


def _version_raw_root_hint(library: Mapping[str, Any]) -> str:
    """Return a display-only common parent when the catalog lacks a library root."""

    version_paths = [
        Path(str(version.get("raw_path") or "")).expanduser()
        for version in library.get("versions", []) or []
        if isinstance(version, Mapping) and str(version.get("raw_path") or "").strip()
    ]
    if not version_paths:
        return ""
    resolved = [str(path.resolve()) for path in version_paths]
    try:
        common = Path(os.path.commonpath(resolved))
    except ValueError:
        return ""
    # A single version path names a version directory, not a library root.
    if len(resolved) == 1 or str(common) in resolved:
        common = common.parent
    return str(common)


def list_library_candidate_rows(state: Mapping[str, Any]) -> dict[str, Any]:
    """Read the saved library-candidate snapshot without rediscovering RAW.

    Discovery is intentionally a separate, bounded job.  The console only
    projects its persisted TSV/JSON evidence so selecting a candidate cannot
    accidentally walk a large library tree again.
    """

    config = state.get("config") if isinstance(state.get("config"), Mapping) else {}
    candidates_path = Path(str(config.get("library_candidates") or "config/library_candidates/latest.tsv")).expanduser()
    registry_path = Path(str(config.get("library_registry") or "config/library_registry.tsv")).expanduser()
    result: dict[str, Any] = {
        "status": "MISSING",
        "source": str(candidates_path.resolve()),
        "evidence": str(candidates_path.with_suffix(".json").resolve()),
        "registry": str(registry_path.resolve()),
        "candidates": [],
        "count": 0,
        "warnings": [],
        "truncated": False,
    }
    if not candidates_path.is_file():
        return result
    try:
        rows = read_library_list(candidates_path)
    except (OSError, ValueError) as exc:
        result.update({"status": "INVALID", "error": f"候选库快照无法读取：{exc}"})
        return result

    metadata_by_key: dict[tuple[str, str], Mapping[str, Any]] = {}
    evidence_path = candidates_path.with_suffix(".json")
    if evidence_path.is_file():
        try:
            loaded = json.loads(evidence_path.read_text(encoding="utf-8"))
        except (OSError, TypeError, ValueError):
            loaded = None
            result["warnings"].append("候选库补充证据无法读取；仍显示 TSV 中的可登记项。")
        if isinstance(loaded, Mapping):
            result['start_root'] = str(loaded.get('start_root') or loaded.get('raw_root') or '')
            result["warnings"].extend(str(item) for item in loaded.get("warnings", []) if str(item).strip())
            result["truncated"] = bool(loaded.get("truncated"))
            for item in loaded.get("candidates", []) or []:
                if isinstance(item, Mapping):
                    library_id = str(item.get("library_id") or "").strip()
                    root_abs = str(item.get("root_abs") or "").strip()
                    if library_id and root_abs:
                        metadata_by_key[(library_id, str(Path(root_abs).expanduser().resolve()))] = item

    registry_roots: set[str] = set()
    registry_roots_by_id: dict[str, set[str]] = {}
    if registry_path.is_file():
        try:
            for row in read_library_list(registry_path):
                if str(row.get("status") or "").upper() not in {"OK", "ENABLE", "ENABLED"}:
                    continue
                library_id = str(row.get("library_id") or "").strip()
                root_abs = str(row.get("root_abs") or "").strip()
                if root_abs:
                    root_key = str(Path(root_abs).expanduser().resolve())
                    registry_roots.add(root_key)
                    if library_id:
                        registry_roots_by_id.setdefault(library_id, set()).add(root_key)
        except (OSError, ValueError):
            result["warnings"].append("人工登记表无法读取；未标记已登记状态。")

    candidates: list[dict[str, Any]] = []
    for row in rows:
        library_id = str(row.get("library_id") or "").strip()
        root_abs = str(row.get("root_abs") or "").strip()
        if not library_id or not root_abs:
            continue
        root_key = str(Path(root_abs).expanduser().resolve())
        metadata = metadata_by_key.get((library_id, root_key), {})
        row_for_suggestion = {
            "library_id": library_id,
            "display_name": str(row.get("display_name") or ""),
            "vendor": str(row.get("vendor") or ""),
            "middle_path": str(row.get("middle_path") or ""),
        }
        example_versions = metadata.get("example_versions") if isinstance(metadata, Mapping) else []
        same_id_roots = registry_roots_by_id.get(library_id, set())
        already_registered = root_key in registry_roots
        candidates.append(
            {
                "candidate_id": _candidate_id(library_id, root_key),
                "status": str(row.get("status") or "REVIEW").upper(),
                "library_id": library_id,
                "suggested_library_id": suggest_formal_library_id(row_for_suggestion),
                "root_abs": root_key,
                "display_name": str(row.get("display_name") or ""),
                "vendor": str(row.get("vendor") or ""),
                "middle_path": str(row.get("middle_path") or ""),
                "version_count": int(metadata.get("version_count") or 0) if isinstance(metadata, Mapping) else 0,
                "example_versions": [str(item) for item in example_versions[:5]] if isinstance(example_versions, list) else [],
                "version_names": [str(item) for item in metadata.get("version_names", [])] if isinstance(metadata.get("version_names"), list) else [],
                "view_types": [str(item) for item in metadata.get("view_types", [])] if isinstance(metadata.get("view_types"), list) else [],
                "confidence": metadata.get("confidence") if isinstance(metadata, Mapping) else None,
                "reason": str(metadata.get("reason") or "") if isinstance(metadata, Mapping) else "",
                "already_registered": already_registered,
                "name_conflict": bool(same_id_roots and root_key not in same_id_roots),
            }
        )
    result.update({"status": "READY", "candidates": candidates, "count": len(candidates)})
    return result


def list_release_library_rows(state: Mapping[str, Any]) -> dict[str, Any]:
    """Project published release history separately from the RAW catalog.

    A formal release record is evidence of a past publication.  It is not a
    candidate RAW library and must never contribute scan or worklist status.
    """

    from lib_guard.release.library_index import load_release_library_index

    config = state.get("config") if isinstance(state.get("config"), Mapping) else {}
    source = Path(str(config.get("release_library_index") or "config/release_libraries/latest.json")).expanduser()
    try:
        index = load_release_library_index(source)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return {
            "status": "INVALID",
            "source": str(source.resolve()),
            "libraries": [],
            "count": 0,
            "error": f"正式发布库索引无法读取：{exc}",
        }
    if index.get("status") == "MISSING":
        return {
            "status": "MISSING",
            "source": str(source.resolve()),
            "libraries": [],
            "count": 0,
            "message": "尚未读取正式发布目录。刷新后可查询发布历史，不会扫描 RAW。",
        }

    catalog_by_id: dict[str, tuple[str, str]] = {}
    for item in state.get("catalog", {}).get("libraries", []) or []:
        if not isinstance(item, Mapping):
            continue
        library_name = str(item.get("library_name") or "").strip()
        library_id = str(item.get("typed_library_id") or item.get("library_id") or "").strip()
        if library_id and library_name:
            catalog_by_id[library_id] = (library_id, library_name)

    rows: list[dict[str, Any]] = []
    for item in index.get("libraries", []):
        if not isinstance(item, Mapping):
            continue
        library_id = str(item.get("library_id") or "").strip()
        current = item.get("current") if isinstance(item.get("current"), Mapping) else {}
        catalog_match = catalog_by_id.get(library_id)
        rows.append(
            {
                "library_id": library_id,
                "source_type": "正式发布库",
                "release_count": int(item.get("release_count") or 0),
                "current_release": str(current.get("release_id") or ""),
                "current_version": str(current.get("version_id") or ""),
                "current_alias": str(current.get("alias") or ""),
                "current_link_mode": str(current.get("link_mode") or ""),
                "current_published_at": str(current.get("published_at") or ""),
                "current_source": str(current.get("source") or "manifest_fallback"),
                # A formal release can prepare an overwrite only for the same
                # typed library.  A tail-name fallback (for example ip/ucie ->
                # stdcell/ucie) would make an unrelated library actionable.
                "raw_catalog_match": catalog_match[0] if catalog_match else "",
                "raw_catalog_name": catalog_match[1] if catalog_match else "",
                "history": [dict(row) for row in item.get("releases", []) if isinstance(row, Mapping)],
            }
        )
    return {
        "status": "READY",
        "source": index.get("source", str(source.resolve())),
        "release_root": index.get("release_root", ""),
        "refreshed_at": index.get("refreshed_at", ""),
        "summary": index.get("summary", {}),
        "libraries": rows,
        "stages": index.get('stages', []),
        "unregistered_deliveries": index.get('unregistered_deliveries', []),
        "count": len(rows),
        "warnings": index.get("warnings", []),
        "truncated": bool(index.get("truncated")),
    }


def release_stage_detail(state: Mapping[str, Any], name: str, *, query: str = '',
                         library: str = '', view: str = '', link_status: str = '',
                         offset: int = 0, limit: int = 100) -> dict[str, Any]:
    """Read the installed delivery, not a reconstructed current effective."""
    snapshot = list_release_library_rows(state)
    stage = next((row for row in snapshot.get('stages', []) if row.get('publish_name') == name), None)
    if stage is None:
        raise ValueError('未找到发布阶段，请刷新发布库目录')
    root = Path(snapshot['release_root']).resolve()
    directory = Path(stage['path'])
    manifest_path = directory / 'release_manifest.json'
    if directory.resolve().parent != root or not manifest_path.resolve().is_relative_to(root):
        raise ValueError('发布阶段路径越界')
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    if not isinstance(manifest, Mapping):
        raise ValueError('发布清单必须是 JSON 对象')
    delivery_files = manifest.get('files', [])
    components = manifest.get('release_components') or manifest.get('libraries') or []
    if not isinstance(delivery_files, list) or not all(isinstance(item, Mapping) for item in delivery_files):
        raise ValueError('发布清单的文件列表格式错误')
    if not isinstance(components, list) or not all(isinstance(item, Mapping) for item in components):
        raise ValueError('发布清单的库列表格式错误')
    latest_name = str(manifest.get('latest_name') or 'latest')
    pointer = root / latest_name
    stage = {**stage, 'libraries': components, 'library_count': len(components),
             'file_count': len(delivery_files), 'latest_name': latest_name,
             'delivery_status': manifest.get('delivery_status') or 'APPLIED',
             'skipped_count': len(manifest.get('skipped_files') or []),
             'is_latest': pointer.is_symlink() and pointer.resolve() == directory.resolve(),
             'published_at': manifest.get('published_at') or manifest.get('created_at') or ''}
    inventory = {}
    view_inventory = {}
    for component in components:
        key = str(component.get('library_id') or f"{component.get('library_type', 'ip')}/{component.get('library_name', '')}")
        inventory[key] = {**component, 'library_id': key, 'file_count': 0, 'views': {},
                          'corners': set(), 'corner_unrecorded': 0, 'source_versions': set(), 'delivery_actions': {}}
    for item in delivery_files:
        key = str(item.get('library_id') or f"{item.get('library_type', 'ip')}/{item.get('library_name', '')}")
        row = inventory.setdefault(key, {'library_id': key, 'file_count': 0, 'views': {},
                                        'corners': set(), 'corner_unrecorded': 0, 'source_versions': set(), 'delivery_actions': {}})
        view_name = str(item.get('view') or str(item.get('target_relpath') or '').split('/')[0] or '未记录')
        corner = item.get('corner')
        corner_label = str(corner).strip() if isinstance(corner, (str, int, float)) else ''
        row['file_count'] += 1
        action = str(item.get('delivery_action') or 'UNRECORDED')
        row['delivery_actions'][action] = row['delivery_actions'].get(action, 0) + 1
        row['views'][view_name] = row['views'].get(view_name, 0) + 1
        if corner_label:
            row['corners'].add(corner_label)
        else:
            row['corner_unrecorded'] += 1
        if item.get('source_version'):
            row['source_versions'].add(str(item['source_version']))
        view_row = view_inventory.setdefault(view_name, {'view': view_name, 'file_count': 0, 'libraries': set(), 'corners': set()})
        view_row['file_count'] += 1
        view_row['libraries'].add(key)
        if corner_label:
            view_row['corners'].add(corner_label)
    for row in inventory.values():
        row['views'] = [{'view': key, 'count': count} for key, count in sorted(row['views'].items())]
        row['corners'] = sorted(row['corners'])
        row['source_versions'] = sorted(row['source_versions'])
    for row in view_inventory.values():
        row['libraries'] = sorted(row['libraries'])
        row['corners'] = sorted(row['corners'])
    files = []
    views = sorted({str(item.get('target_relpath') or '').split('/')[0] for item in delivery_files} - {''})
    if link_status not in {'', 'abnormal', 'READY', 'MISSING', 'MISMATCH', 'COPIED'}:
        raise ValueError('不支持的链接核查筛选')
    query = query.casefold().strip()
    for item in delivery_files:
        rel = Path(str(item.get('target_relpath') or ''))
        if rel.is_absolute() or '..' in rel.parts or str(rel) == '.':
            raise ValueError('发布文件路径越界或为空')
        if view and rel.parts[0] != view:
            continue
        component = str(item.get('library_id') or f"{item.get('library_type', 'ip')}/{item.get('library_name', '')}")
        if library and library != component:
            continue
        source = str(item.get('source_path') or item.get('source_abs') or item.get('source') or '')
        if query and query not in f'{rel} {source} {component}'.casefold():
            continue
        files.append({**item, 'library_id': component, 'target_relpath': str(rel), 'source_abs': source})
    def check_link(item: dict[str, Any]) -> None:
        target = directory / item['target_relpath']
        # Parent containment permits the expected final RAW file symlink.
        if not target.parent.resolve().is_relative_to(directory.resolve()):
            raise ValueError('发布文件父目录越界')
        exists = target.is_file()
        source = item['source_abs']
        correct = exists and bool(source) and target.resolve() == Path(source).resolve()
        item.update({'target_abs': str(target), 'actual_target': str(target.resolve()),
                     'is_symlink': target.is_symlink(),
                     'link_status': 'READY' if correct else 'COPIED' if exists and manifest.get('link_mode') == 'copy' and not target.is_symlink() else 'MISMATCH' if exists else 'MISSING'})
    scope_count = len(files)
    if link_status:
        for item in files:
            check_link(item)
        checked = list(files)
        files = [item for item in files if item['link_status'] in {'MISSING', 'MISMATCH'}] if link_status == 'abnormal' else [item for item in files if item['link_status'] == link_status]
    offset, limit = max(0, offset), max(1, min(limit, 100))
    if files and offset >= len(files):
        offset = ((len(files) - 1) // limit) * limit
    page = files[offset:offset + limit]
    if not link_status:
        for item in page:
            check_link(item)
        checked = page
    return {'status': 'READY', 'stage': stage, 'files': page, 'total': len(files),
            'inventory': list(inventory.values()), 'view_inventory': list(view_inventory.values()),
            'check': {'checked_count': len(checked), 'scope_count': scope_count,
                      'complete': len(checked) == scope_count,
                      'abnormal_count': sum(item['link_status'] in {'MISSING', 'MISMATCH'} for item in checked)},
            'offset': offset, 'has_more': offset + len(page) < len(files), 'source': str(manifest_path), 'views': views}


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
        if (
            diff.get("base_version") == diff.get("adjacent_old_version")
            and str(diff.get("base_status") or "").upper() not in {"", "PENDING", "NOT_APPLICABLE"}
        ):
            return str(diff.get("base_status"))
        return str(diff.get("adjacent_status") or "NOT_APPLICABLE")
    if diff.get("base_version"):
        return str(diff.get("base_status") or "NOT_APPLICABLE")
    return "NOT_APPLICABLE"


def _release_status(version: Mapping[str, Any]) -> str:
    release = version.get("release") or {}
    return str(release.get("check_status") or release.get("status") or "UNKNOWN")


def _is_initial_baseline(versions: list[Mapping[str, Any]], version: Mapping[str, Any]) -> bool:
    """A first version is a fact baseline, not an unprocessed comparison."""

    if _base_version(version) or package_kind(version) != "FULL":
        return False
    ordered = sorted(versions, key=_sort_key)
    return bool(ordered) and ordered[0] is version


def _change_summary(
    version: Mapping[str, Any],
    *,
    is_initial_baseline: bool = False,
    scan_ready: bool | None = None,
) -> str:
    if is_initial_baseline:
        return "初始基线"
    if scan_ready is None:
        scan_ready = scan_evidence_ready(version)
    if not _base_version(version) and package_kind(version) in {"FIX", "DOC"}:
        return "基准待确认"
    status = _diff_status(version).upper()
    if status in {"PENDING", "NOT_APPLICABLE"}:
        return "待生成对比"
    if not scan_ready:
        return "对比记录待验证"
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
    expected_root = str(version.get("raw_path") or "").strip()
    if expected_root and not Path(expected_root).expanduser().is_dir():
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


def list_file_diff_page(
    web_state: Mapping[str, Any],
    library_name: str,
    version_id: str,
    *,
    change: str | None = None,
    file_type: str | None = None,
    query: str | None = None,
    offset: int = 0,
    limit: int = 100,
) -> dict[str, Any]:
    """Project existing file-diff evidence into one bounded browser page.

    ``file_diff.json`` remains the source artifact.  The console deliberately
    does not inspect RAW files here: filtering and pagination only reduce the
    data transferred to the browser and the number of DOM rows it renders.
    Counts are calculated from the same complete evidence set before filters
    are applied, so filter chips never invent a second set of facts.
    """

    rows = list_file_diff_rows(web_state, library_name, version_id)
    diff_semantics = "complete_snapshot"
    omitted_from_overlay = 0
    raw_removed = 0
    catalog = web_state.get("catalog") if isinstance(web_state.get("catalog"), Mapping) else {}
    library = next(
        (item for item in catalog.get("libraries", []) or [] if isinstance(item, Mapping) and str(item.get("library_name")) == library_name),
        None,
    )
    version = next(
        (item for item in (library or {}).get("versions", []) or [] if isinstance(item, Mapping) and str(item.get("version_id")) == version_id),
        None,
    )
    if isinstance(version, Mapping):
        diff_path = _diff_file_path(version)
        if diff_path is not None:
            try:
                summary = json.loads((diff_path.parent / "diff_summary.json").read_text(encoding="utf-8"))
            except (OSError, TypeError, ValueError):
                summary = {}
            if isinstance(summary, Mapping):
                diff_semantics = str(summary.get("comparison_semantics") or diff_semantics)
                omitted_from_overlay = int(summary.get("omitted_from_overlay_files") or 0)
                raw_removed = int(summary.get("raw_removed_files") or 0)
    by_change: dict[str, int] = {}
    by_file_type: dict[str, int] = {}
    for row in rows:
        row_change = str(row.get("change") or "UNKNOWN").upper()
        row_file_type = str(row.get("file_type") or "unknown").lower()
        by_change[row_change] = by_change.get(row_change, 0) + 1
        by_file_type[row_file_type] = by_file_type.get(row_file_type, 0) + 1

    selected_change = str(change or "").strip().upper()
    selected_file_type = str(file_type or "").strip().lower()
    needle = str(query or "").strip().casefold()
    filtered = [
        row
        for row in rows
        if (not selected_change or str(row.get("change") or "").upper() == selected_change)
        and (not selected_file_type or str(row.get("file_type") or "").lower() == selected_file_type)
        and (
            not needle
            or needle in str(row.get("old_path") or "").casefold()
            or needle in str(row.get("new_path") or "").casefold()
        )
    ]
    page_offset = max(0, int(offset))
    page_limit = max(1, int(limit))
    page_rows = filtered[page_offset : page_offset + page_limit]
    next_offset = page_offset + len(page_rows)
    return {
        "rows": page_rows,
        "total": len(filtered),
        "next_offset": next_offset if next_offset < len(filtered) else None,
        "counts": {
            "total": len(rows),
            "by_change": dict(sorted(by_change.items())),
            "by_file_type": dict(sorted(by_file_type.items())),
        },
        "comparison_semantics": diff_semantics,
        "omitted_from_overlay": omitted_from_overlay,
        "raw_removed": raw_removed,
    }


def list_file_tree_rows(web_state: Mapping[str, Any], library_name: str, version_id: str) -> dict[str, Any]:
    """Return the current version's file structure from scan evidence.

    The operation console must not walk RAW just to draw a tree.  The scanner
    already records the bounded, relative-path inventory that the UI needs.
    Tree rows keep scan-relative paths for selection and copying. The paired
    Liberty/DB checklist deliberately exposes absolute evidence paths.
    ``path`` remains the exact
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
    raw_path = str(version.get("raw_path") or "")
    if inventory_path is None or not inventory_path.is_file():
        return {
            "status": "NOT_READY",
            "library": library_name,
            "version": version_id,
            "root_path": raw_path,
            "files": [],
            "file_count": 0,
            "message": "当前版本还没有可用的扫描文件清单。",
        }
    if not scan_evidence_ready(version):
        return {
            "status": "STALE",
            "library": library_name,
            "version": version_id,
            "root_path": raw_path,
            "files": [],
            "file_count": 0,
            "message": "扫描记录与当前原始目录不匹配；请重新扫描。",
        }
    try:
        inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError):
        return {
            "status": "INVALID",
            "library": library_name,
            "version": version_id,
            "root_path": raw_path,
            "files": [],
            "file_count": 0,
            "message": "扫描文件清单无法读取。",
        }
    if not isinstance(inventory, Mapping) or not isinstance(inventory.get("files"), list):
        return {
            "status": "INVALID",
            "library": library_name,
            "version": version_id,
            "root_path": raw_path,
            "files": [],
            "file_count": 0,
            "message": "扫描文件清单格式不完整。",
        }

    raw_files = [item for item in inventory["files"] if isinstance(item, Mapping)]
    from lib_guard.scan.artifacts import build_lib_db_correspondence
    pairing = build_lib_db_correspondence(raw_files, inventory.get('root_path') or raw_path)
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
        "lib_db_correspondence": pairing,
    }


def _current_effective_pointer(state: Mapping[str, Any], library: Mapping[str, Any]) -> dict[str, Any]:
    library_id = str(library.get("library_id") or library.get("library_name") or "")
    try:
        return load_current_pointer(state["catalog_html"], library_id)
    except (OSError, TypeError, ValueError) as exc:
        return {"_invalid": True, "error": str(exc)}


def _source_label(source: str) -> str:
    labels = {
        "current_effective_pointer": "当前有效指针",
        "effective_manifest": "有效组合清单",
        "catalog_runtime": "目录运行状态",
        "catalog_summary": "目录摘要",
        "latest_full_fallback": "自动回退：最新完整包",
        "first_catalog_version": "自动回退：首个版本",
        "uninitialized": "未建立当前有效版",
        "missing_current_effective": "当前有效版本未设置",
        "manual": "人工确认",
        "manual_selection": "人工选择",
        "fallback": "自动回退",
    }
    return labels.get(str(source or ""), str(source or "未知来源"))


def _effective_stack_from_pointer(pointer: Mapping[str, Any]) -> dict[str, Any]:
    if not pointer:
        return {
            "available": False,
            "source": "missing_current_effective",
            "source_label": _source_label("missing_current_effective"),
            "current_effective_id": "",
            "base_full_version": "",
            "accepted_updates": [],
            "effective_digest": "",
            "manifest": "",
            "html": "",
            "pointer_revision": 0,
        }
    if pointer.get("_invalid"):
        return {
            "available": False,
            "source": "invalid_current_effective_pointer",
            "source_label": "当前有效指针异常",
            "current_effective_id": "",
            "base_full_version": "",
            "accepted_updates": [],
            "effective_digest": "",
            "manifest": "",
            "html": "",
            "pointer_revision": 0,
            "error": str(pointer.get("error") or ""),
        }
    source = "current_effective_pointer" if pointer.get("current_effective_id") else "missing_current_effective"
    return {
        "available": bool(pointer.get("current_effective_id")),
        "source": source,
        "source_label": _source_label(source),
        "current_effective_id": str(pointer.get("current_effective_id") or ""),
        "base_full_version": str(pointer.get("base_full_version") or ""),
        "accepted_updates": [str(item) for item in pointer.get("accepted_updates", []) or [] if str(item)],
        "effective_digest": str(pointer.get("effective_digest") or ""),
        "manifest_sha256": str(pointer.get("manifest_sha256") or ""),
        "manifest": str(pointer.get("manifest") or ""),
        "html": str(pointer.get("html") or ""),
        "release_preview": str(pointer.get("release_preview") or ""),
        "pointer_revision": int(pointer.get("revision") or 0),
        "integrity_status": str(pointer.get("effective_integrity_status") or ""),
        "evidence_source": str(pointer.get("effective_evidence_source") or ""),
        "evidence_trust": str(pointer.get("effective_evidence_trust") or ""),
    }


def _candidate_effective_stack(window: Mapping[str, Any]) -> dict[str, Any]:
    candidate = window.get("candidate_effective") if isinstance(window.get("candidate_effective"), Mapping) else {}
    base = window.get("base_effective") if isinstance(window.get("base_effective"), Mapping) else {}
    source = str(base.get("source") or window.get("source") or "fallback")
    if candidate.get("rule") == "manual_selection":
        source = "manual_selection"
    return {
        "available": bool(candidate.get("effective_id")),
        "source": source,
        "source_label": _source_label(source),
        "current_base_target": str(base.get("target") or ""),
        "base_full_version": str(candidate.get("base_full") or base.get("base_full") or ""),
        "accepted_updates": [str(item) for item in candidate.get("overlays", []) or [] if str(item)],
        "candidate_effective_id": str(candidate.get("effective_id") or ""),
        "manifest": str(candidate.get("manifest") or ""),
        "html": str(candidate.get("html") or ""),
        "rule": str(candidate.get("rule") or ""),
    }


def _action_readiness(
    version: Mapping[str, Any],
    *,
    scan_ready: bool | None = None,
    base_scan_ready: bool | None = None,
) -> dict[str, dict[str, Any]]:
    """Expose user-facing action gates without changing the underlying CLI."""

    scan_status = _scan_status(version).upper()
    base_version = _base_version(version)
    if scan_ready is None:
        scan_ready = scan_evidence_ready(version)
    scan_record_without_evidence = scan_status_ready(scan_status) and not scan_ready
    diff_ready = bool(base_version) and _diff_status(version).upper() in _COMPLETED_STATUSES
    base_ready = bool(base_version) and (True if base_scan_ready is None else bool(base_scan_ready))
    compare_enabled = bool(base_version) and bool(scan_ready) and base_ready
    return {
        "scan": {
            "enabled": True,
            "label": "已有扫描" if scan_ready else "需补扫" if scan_record_without_evidence else "待扫描",
            "button_label": "按需重扫" if scan_ready else "补扫" if scan_record_without_evidence else "生成扫描",
            "reason": (
                "已有可用扫描证据，无需重复扫描；只有原始目录或扫描策略变化时再重扫。"
                if scan_ready
                else "目录里有扫描记录，但证据文件不可用；请重新扫描补齐证据。"
                if scan_record_without_evidence
                else "尚未生成可用的扫描证据"
            ),
        },
        "compare": {
            "enabled": compare_enabled,
            "label": "无可比基准" if not base_version else "已有对比" if diff_ready else "可对比" if compare_enabled else "待对比",
            "button_label": "按需重跑" if diff_ready else "执行对比",
            "reason": (
                "扫描证据不可用，请先完成扫描"
                if not scan_ready
                else f"对比基准 {base_version} 还没有可用扫描证据；请先扫描基准，或勾选缺失则扫描。"
                if base_version and not base_ready
                else "已有对比结果；默认沿用已有扫描证据，无需重复扫描。仅当基准或扫描策略变化时重新对比。"
                if diff_ready
                else "可直接对比；默认沿用已有扫描证据，不会重复扫描。缺证据时可勾选缺失补扫。"
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


def _workflow_status(
    version: Mapping[str, Any],
    *,
    current_effective: bool | None = None,
    scan_ready: bool | None = None,
    base_scan_ready: bool | None = None,
    is_initial_baseline: bool = False,
) -> dict[str, str]:
    """Return operational fact readiness without making an IP usage decision."""

    if scan_ready is None:
        scan_ready = scan_evidence_ready(version)
    readiness = _action_readiness(version, scan_ready=scan_ready, base_scan_ready=base_scan_ready)
    scan_status = _scan_status(version).upper()
    diff_status = _diff_status(version).upper()
    if "FAIL" in scan_status:
        return {
            "label": "扫描失败",
            "reason": "请先查看扫描结果，再决定是否重新扫描。",
            "next_action": "查看扫描结果",
            "source": "catalog_runtime",
        }
    if not scan_ready:
        if scan_status_ready(scan_status):
            return {
                "label": "需补扫",
                "reason": "扫描记录存在，但证据文件缺失或不可读取；完成补扫前不能可靠对比或进行发布检查。",
                "next_action": "补扫",
                "source": "catalog_runtime",
            }
        return {
            "label": "待生成扫描",
            "reason": "当前版本还没有可用的扫描证据。",
            "next_action": "生成扫描",
            "source": "catalog_runtime",
        }
    if not _base_version(version) and package_kind(version) in {"FIX", "DOC"}:
        return {
            "label": "组合基准待确认",
            "reason": "本版是增量或文档交付，尚无已确认完整包基准；不能把本包当作初始基线。",
            "next_action": "确认完整包基准",
            "source": "catalog_runtime",
        }
    if is_initial_baseline:
        return {
            "label": "初始基线",
            "reason": "这是库内最早版本，当前只检查版本自身事实，无需版本对比。",
            "next_action": "查看详情",
            "source": "catalog_runtime",
        }
    if "FAIL" in diff_status or "ERROR" in diff_status:
        return {
            "label": "对比失败",
            "reason": "扫描证据已存在，但最近一次对比失败；不能按已完成处理。",
            "next_action": "查看对比结果",
            "source": "catalog_runtime",
        }
    is_current = bool(version.get("current_effective")) if current_effective is None else current_effective
    if is_current:
        return {
            "label": "当前可用版本",
            "reason": "这是目录记录的当前可用基线。",
            "next_action": "查看详情",
            "source": "catalog_runtime",
        }
    if not readiness["compare"]["enabled"] and diff_status != "NOT_APPLICABLE":
        base_version = _base_version(version)
        if base_version and base_scan_ready is False:
            return {
                "label": "基准待扫描",
                "reason": f"建议基准 {base_version} 缺少扫描证据；先扫描基准，或对比时勾选缺失则扫描。",
                "next_action": "扫描基准",
                "source": "catalog_runtime",
            }
        return {
            "label": "待确认基准",
            "reason": "当前版本缺少可用的对比基准。",
            "next_action": "补充基准",
            "source": "catalog_runtime",
        }
    if diff_status in {"PENDING", "NOT_APPLICABLE"}:
        return {
            "label": "已读取，待处理",
            "reason": "扫描事实已读取，是否对比取决于版本关系和基准。",
            "next_action": "执行对比" if readiness["compare"]["enabled"] else "查看详情",
            "source": "catalog_runtime",
        }
    return {
        "label": "事实已生成",
        "reason": "扫描和对比已有结果；IP 使用判断请以版本详情页为准。",
        "next_action": "查看详情",
        "source": "catalog_runtime",
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
        "compare_url": "",
        "candidate_html_url": "",
        "saved_combinations": [
            {"effective_id": manifest.parent.name}
            for manifest in sorted((path.parent.parent / "effective").glob("*/effective_manifest.json"))
            if manifest.is_file()
        ],
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
    result["candidate_effective_stack"] = _candidate_effective_stack(window)
    if candidate.get("html") and Path(str(candidate["html"])).is_file():
        try:
            relative = Path(str(candidate["html"])).resolve().relative_to(Path(state["catalog_html"]).resolve())
        except ValueError:
            pass
        else:
            result["candidate_html_url"] = "/artifacts/" + relative.as_posix()
    compare = window.get("compare") if isinstance(window.get("compare"), Mapping) else {}
    compare_path = Path(str(compare.get("html") or ""))
    if compare.get("html") and compare_path.is_file():
        try:
            relative = compare_path.resolve().relative_to(Path(state["catalog_html"]).resolve())
        except ValueError:
            pass
        else:
            result["compare_url"] = "/artifacts/" + relative.as_posix()
    base = window.get("base_effective") if isinstance(window.get("base_effective"), Mapping) else {}
    result["base_source"] = str(base.get("source") or "")
    result["base_source_label"] = _source_label(str(base.get("source") or ""))
    return result


def _focus_version_ids(
    library: Mapping[str, Any],
    ordered_versions: list[Mapping[str, Any]],
    *,
    current_effective: str,
    pending_window: Mapping[str, Any],
) -> set[str]:
    """Return versions that affect the current operator task.

    Historical versions remain browseable, but the main workbench should only
    count the latest candidate, the current effective stack, and the baseline
    versions needed to judge that candidate.
    """

    by_id = {str(item.get("version_id") or ""): item for item in ordered_versions if str(item.get("version_id") or "")}
    focus: set[str] = set()
    latest = str((library.get("summary") or {}).get("latest_version") or "")
    if not latest and ordered_versions:
        latest = str(ordered_versions[-1].get("version_id") or "")
    if latest:
        focus.add(latest)
        base = _base_version(by_id.get(latest, {}))
        if base:
            focus.add(base)
    if current_effective:
        focus.add(current_effective)
    for stack_key in ("current_effective_stack", "candidate_effective_stack"):
        stack = pending_window.get(stack_key) if isinstance(pending_window.get(stack_key), Mapping) else {}
        for version_id in (
            stack.get("base_full_version"),
            stack.get("current_base_target"),
            stack.get("candidate_effective_id"),
            *(stack.get("accepted_updates", []) if isinstance(stack.get("accepted_updates"), list) else []),
        ):
            if str(version_id or "") in by_id:
                focus.add(str(version_id))
    return {version_id for version_id in focus if version_id in by_id}


def _library_directory_updated_at(versions: list[Mapping[str, Any]]) -> str | None:
    times = []
    for version in versions:
        detected = version.get('detected') or {}
        try:
            value = datetime.fromisoformat(str(detected.get('mtime') or '').replace('Z', '+00:00'))
        except ValueError:
            continue
        if value.tzinfo is not None:
            times.append(value.astimezone(timezone.utc))
    return max(times).isoformat().replace('+00:00', 'Z') if times else None


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
        version_by_id = {str(item.get("version_id") or ""): item for item in ordered_versions if str(item.get("version_id") or "")}
        summary = library.get("summary") or {}
        pointer = _current_effective_pointer(state, library)
        effective_stack = _effective_stack_from_pointer(pointer)
        pointer_current = str(pointer.get("current_effective_id") or "")
        pointer_invalid = bool(pointer.get("_invalid"))
        current = pointer_current or (
            None
            if pointer_invalid
            else next((str(item.get("version_id")) for item in versions if item.get("current_effective")), None)
        )
        pending_window = _pending_window(state, library)
        pending_window["current_effective_stack"] = effective_stack
        focus_ids = _focus_version_ids(
            library,
            ordered_versions,
            current_effective=current or "",
            pending_window=pending_window,
        )
        latest_version = str(summary.get("latest_version") or "")
        if not latest_version and ordered_versions:
            latest_version = str(ordered_versions[-1].get("version_id") or "")
        base_for_latest = _base_version(version_by_id.get(latest_version, {})) if latest_version else ""
        actionable_labels = {"扫描失败", "待生成扫描", "需补扫", "对比失败", "基准待扫描", "待确认基准"}
        focus_statuses: list[tuple[Mapping[str, Any], dict[str, str], bool, bool, bool]] = []
        for item in ordered_versions:
            version_id = str(item.get("version_id") or "")
            if version_id not in focus_ids:
                continue
            base_version = _base_version(item)
            status = _workflow_status(
                item,
                scan_ready=cached_scan_ready(item),
                base_scan_ready=(
                    cached_scan_ready(version_by_id[str(base_version)])
                    if base_version and str(base_version) in version_by_id
                    else False
                    if base_version
                    else None
                ),
                is_initial_baseline=_is_initial_baseline(ordered_versions, item),
                current_effective=(
                    version_id == pointer_current
                    if pointer_current
                    else (False if pointer_invalid else bool(item.get("current_effective")))
                ),
            )
            focus_statuses.append(
                (
                    item,
                    status,
                    version_id == (current or ""),
                    version_id == latest_version,
                    bool(base_for_latest and version_id == base_for_latest),
                )
            )
        release_blocked_count = sum(
            1
            for item in versions
            if str(item.get("version_id") or "") in focus_ids
            if str((item.get("release") if isinstance(item.get("release"), Mapping) else {}).get("status") or "").upper()
            in {"RELEASE_BLOCKED", "BLOCKED"}
            or str((item.get("release") if isinstance(item.get("release"), Mapping) else {}).get("check_status") or "").upper()
            in {"RELEASE_BLOCKED", "BLOCKED"}
        )
        registered_root = str(library.get("root_abs") or library.get("root") or library.get("path") or "")
        root_display = registered_root or _version_raw_root_hint(library)
        rows.append(
            {
                "library_name": str(library.get("library_name") or ""),
                "library_id": str(library.get("typed_library_id") or library.get("library_id") or ""),
                "display_name": str(library.get("display_name") or library.get("library_name") or ""),
                "vendor": str(library.get("vendor") or ""),
                "category": str(library.get("category") or ""),
                "library_type": str(library.get("library_type") or library.get("type") or library.get("category") or ""),
                "platform": str(library.get("platform") or library.get("process") or library.get("technology") or ""),
                "root_abs": registered_root,
                "root_display": root_display,
                "root_source": "catalog_root" if registered_root else "version_raw_path" if root_display else "missing",
                "version_count": len(versions),
                "latest_version": str(summary.get("latest_version") or (ordered_versions[-1].get('version_id') if ordered_versions else '') or ''),
                "raw_updated_at": _library_directory_updated_at(versions),
                "raw_updated_at_source": "catalog_version_directory_mtime",
                "focus_version_count": len(focus_ids),
                "current_effective": current,
                "current_effective_id": pointer_current or current or "",
                "scan_pending": int(summary.get("scan_pending") or 0),
                "diff_pending": int(summary.get("diff_pending") or 0),
                "release_blocked_count": release_blocked_count,
                "has_current_effective": bool(pointer_current or current),
                "workflow_pending_count": sum(1 for _, status, *_ in focus_statuses if status["label"] in actionable_labels),
                "new_candidate_pending_count": sum(
                    1
                    for item, status, is_effective, _is_latest, is_base_for_latest in focus_statuses
                    if not is_effective and not is_base_for_latest and status["label"] in actionable_labels
                ),
                "base_scan_pending_count": sum(
                    1
                    for _item, status, is_effective, _is_latest, is_base_for_latest in focus_statuses
                    if not is_effective and is_base_for_latest and status["label"] in actionable_labels
                ),
                "effective_hygiene_count": sum(
                    1
                    for _, status, is_effective, *_ in focus_statuses
                    if is_effective and status["label"] in actionable_labels
                ),
                "effective_pointer_state": "INVALID" if pointer_invalid else ("SET" if pointer_current else "CATALOG"),
                "pending_window": pending_window,
                "current_effective_stack": effective_stack,
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
            if isinstance(item, Mapping)
            and library_name
            in {
                str(item.get("library_name") or ""),
                str(item.get("library_id") or ""),
                str(item.get("typed_library_id") or ""),
            }
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
    version_by_id = {
        str(item.get("version_id") or ""): item
        for item in sorted_versions
        if isinstance(item, Mapping) and str(item.get("version_id") or "")
    }
    pointer = _current_effective_pointer(state, library)
    pointer_current = str(pointer.get("current_effective_id") or "")
    pointer_invalid = bool(pointer.get("_invalid"))
    current = pointer_current or (
        ""
        if pointer_invalid
        else next((str(item.get("version_id")) for item in sorted_versions if isinstance(item, Mapping) and item.get("current_effective")), "")
    )
    pending_window = _pending_window(state, library)
    pending_window["current_effective_stack"] = _effective_stack_from_pointer(pointer)
    focus_ids = _focus_version_ids(
        library,
        [item for item in sorted_versions if isinstance(item, Mapping)],
        current_effective=current,
        pending_window=pending_window,
    )
    start = max(0, int(offset or 0))
    end = None if limit is None else start + max(0, int(limit))
    for version in sorted_versions[start:end]:
        if not isinstance(version, Mapping):
            continue
        report_slug = str(library.get("report_slug") or report_safe(
            library.get("typed_library_id") or library.get("library_id")
            or library.get("formal_library_id") or library.get("library_name")
            or library.get("display_name") or "library"
        ))
        version_id = str(version.get("version_id") or "")
        detail_path = catalog_html / "libraries" / report_slug / "versions" / report_safe(version_id) / "index.html"
        scan = version.get("scan") or {}
        diff = version.get("diff") or {}
        current_effective = version_id == current if current else (False if pointer_invalid else bool(version.get("current_effective")))
        scan_ready = cached_scan_ready(version)
        base_version = _base_version(version)
        base_scan_ready = None
        if base_version:
            base_item = version_by_id.get(str(base_version))
            base_scan_ready = cached_scan_ready(base_item) if isinstance(base_item, Mapping) else False
        initial_baseline = _is_initial_baseline(sorted_versions, version)
        workflow_status = _workflow_status(
            version,
            current_effective=current_effective,
            scan_ready=scan_ready,
            base_scan_ready=base_scan_ready,
            is_initial_baseline=initial_baseline,
        )
        rows.append(
            {
                "version_id": version_id,
                "version_key": str(version.get("version_key") or ""),
                "stage": str(version.get("stage") or "unknown"),
                "package_type": str(version.get("package_type") or "UNKNOWN_PACKAGE"),
                "current_effective": current_effective,
                "focus_scope": version_id in focus_ids,
                "focus_reason": "当前关注版本" if version_id in focus_ids else "历史版本",
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
                "version_detail_path": str(detail_path),
                "version_detail_url": f"/artifacts/{detail_path.relative_to(catalog_html).as_posix()}",
                "version_detail_exists": detail_path.exists(),
                "action_readiness": _action_readiness(version, scan_ready=scan_ready, base_scan_ready=base_scan_ready),
                "workflow_status": workflow_status,
                "usage_decision_source": "version_detail_model",
                "change_summary": _change_summary(
                    version,
                    is_initial_baseline=initial_baseline,
                    scan_ready=scan_ready,
                ),
                "next_action": workflow_status["next_action"],
                "effective_pointer_state": "INVALID" if pointer_invalid else ("SET" if pointer_current else "CATALOG"),
            }
        )
    return rows


__all__ = ["list_file_diff_rows", "list_file_tree_rows", "list_library_rows", "list_version_rows", "load_web_state", "scan_evidence_ready", "scan_status_ready"]
