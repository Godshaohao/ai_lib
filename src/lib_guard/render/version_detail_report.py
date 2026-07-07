"""Version detail report renderer.

This module owns the version detail surface and the current-library update
detail model. The Markdown export is evidence generated from the same model as
the HTML panel; the HTML renderer never reads Markdown.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Mapping

from lib_guard.diff.file_match import default_path_match_evidence, path_match_evidence as build_path_match_evidence
from lib_guard.project_config import BINARY_METADATA_ONLY_TYPES, DEFAULT_FILE_DIFF_TYPES, SUMMARY_ONLY_TYPES
from lib_guard.review.io import read_json
from lib_guard.review.model_rules import (
    classify_review_lane,
    comparison_semantics_for_package,
    resolve_review_base,
)
from lib_guard.render.catalog_workspace_report import catalog_browser_styles
from lib_guard.render import catalog_render_common as common
from lib_guard.render import catalog_report as catalog
from lib_guard.render import product_theme as ui
from lib_guard.render.version_detail_context import build_version_detail_review_context
from lib_guard.render.version_review_model import build_version_review_model
from lib_guard.render.version_review_render import render_ip_user_view
from lib_guard.view_types import canonical_file_type, package_view_type


STANDARD_BASE_REFS = {"current_effective", "previous_effective", "explicit", "review_window"}
FALLBACK_BASE_REFS = {"adjacent_fallback", "recorded_base", "recorded_base_fallback", "unknown"}
UPDATE_STATUS_COPY = {
    "DIFF_NOT_RUN": "尚未生成更新详情；请运行 lg cat <LIB> --update-detail。",
    "NEEDS_BASE_CONFIRM": "无法确定基准版；请先确认当前有效版或上一有效版。",
    "NO_DIFF_SUMMARY": "找到对比输出目录，但缺少 diff_summary.json；请检查对比产物。",
    "CHANGED": "已完成比较，有变化。",
    "SAME": "已完成比较，无变化。",
}
RELEASE_NOTE_EVIDENCE_TOKENS = {
    "release_note",
    "release note",
    "release-notes",
    "releasenote",
    "changelog",
    "change_log",
    "change log",
    "update_note",
    "update note",
}


def _version_id(version: Mapping[str, Any]) -> str:
    return str(version.get("version_id") or version.get("version") or "version")


def _library_id(lib: Mapping[str, Any]) -> str:
    return str(lib.get("formal_library_id") or lib.get("library_name") or lib.get("library_id") or lib.get("display_name") or "library")


def _library_report_slug(lib: Mapping[str, Any]) -> str:
    return str(lib.get("report_slug") or common.safe(lib.get("typed_library_id") or lib.get("library_id") or _library_id(lib)))


def _library_name(lib: Mapping[str, Any]) -> str:
    lib_id = _library_id(lib)
    return str(lib.get("library_name") or lib.get("display_name") or lib_id.rsplit("/", 1)[-1] or lib_id)


def _as_mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _as_int(value: Any) -> int:
    try:
        return int(value or 0)
    except Exception:
        return 0


def _infer_file_type(path: str, file_type: Any = None) -> str:
    explicit = str(file_type or "").strip().lower()
    if explicit and explicit not in {"-", "gz"}:
        return explicit
    name = Path(str(path or "")).name.lower()
    if name.endswith((".lef", ".lef.gz", ".tlef", ".tlef.gz")):
        return "lef"
    if name.endswith((".lib", ".lib.gz")):
        return "liberty"
    if name.endswith((".v", ".v.gz", ".sv", ".sv.gz", ".vg", ".vg.gz", ".vp", ".vp.gz", ".vh", ".vh.gz", ".svh", ".svh.gz")):
        return "systemverilog" if name.endswith((".sv", ".sv.gz", ".svh", ".svh.gz")) else "verilog"
    if name.endswith((".cdl", ".cdl.gz", ".sp", ".sp.gz", ".spi", ".spi.gz", ".spice", ".spice.gz")):
        return "cdl"
    if name.endswith((".sdc", ".sdc.gz")):
        return "sdc"
    if name.endswith((".upf", ".upf.gz")):
        return "upf"
    if name.endswith((".cpf", ".cpf.gz")):
        return "cpf"
    if name.endswith((".sdf", ".sdf.gz")):
        return "sdf"
    if name.endswith((".spef", ".spef.gz")):
        return "spef"
    if name.endswith((".db", ".db.gz", ".ndm", ".ndm.gz")):
        return "db"
    if name.endswith((".gds", ".gds.gz", ".gdsii", ".gdsii.gz")):
        return "gds"
    if name.endswith((".oas", ".oas.gz", ".oasis", ".oasis.gz")):
        return "oas"
    suffix = Path(name).suffix.lower().lstrip(".")
    return {
        "v": "verilog",
        "sv": "systemverilog",
        "sp": "cdl",
        "spi": "cdl",
        "lib": "liberty",
    }.get(suffix, suffix or "-")


def _file_identity(path: str, item: Mapping[str, Any], file_type: str) -> dict[str, Any]:
    name = Path(str(path or "")).name
    suffixes = [suffix.lower() for suffix in Path(name).suffixes]
    if len(suffixes) >= 2 and suffixes[-1] in {".gz", ".bz2", ".xz", ".zip"}:
        suffix = "".join(suffixes[-2:])
    else:
        suffix = suffixes[-1] if suffixes else ""
    size = item.get("size", item.get("bytes"))
    sha256 = item.get("sha256") or item.get("content_hash") or item.get("hash") or item.get("checksum") or ""
    parser_signature = item.get("parser_signature") or item.get("signature") or ""
    key_parts = [
        str(file_type or "-").lower(),
        name,
        str(size or ""),
        str(parser_signature or sha256 or ""),
    ]
    return {
        "basename": name,
        "suffix": suffix,
        "size": size,
        "sha256": sha256,
        "parser_signature": parser_signature,
        "match_key": ":".join(key_parts),
    }


def _cn_change_kind(value: Any) -> str:
    text = str(value or "").lower()
    if text == "added":
        return "新增"
    if text == "removed":
        return "删除"
    if text == "changed":
        return "变化"
    return text or "-"


def _cn_review_lane(value: Any) -> str:
    text = str(value or "").strip()
    return {
        "Review": "审查",
        "Summary-only": "摘要级证据（Summary-only）",
        "Metadata-only": "元数据级证据（Metadata-only）",
        "P0": "P0",
        "P1": "P1",
    }.get(text, text or "审查")


def _cn_match_status(value: Any) -> str:
    text = str(value or "").strip().lower()
    return {
        "matched_move": "已匹配迁移",
        "candidate_match": "候选匹配",
        "not_applicable": "不适用",
        "same_path": "同路径",
        "unmatched": "未匹配",
        "true_added": "真实新增",
        "true_removed": "真实删除",
    }.get(text, text or "-")


def _cn_evidence_mode(value: Any) -> str:
    text = str(value or "").strip()
    return {
        "summary-only": "摘要级证据（Summary-only）",
        "metadata-only": "元数据级证据（Metadata-only）",
        "structured + raw": "结构化 + 原始文本",
    }.get(text, text or "-")


def _iter_file_changes(file_diff: Mapping[str, Any], *, raw_path: Any = None) -> list[dict[str, Any]]:
    changes: list[dict[str, Any]] = []
    for kind in ["added", "removed", "changed"]:
        value = file_diff.get(kind)
        if isinstance(value, Mapping):
            iterable = [{"path": key, **(item if isinstance(item, Mapping) else {})} for key, item in value.items()]
        elif isinstance(value, list):
            iterable = value
        else:
            iterable = []
        for item in iterable:
            if isinstance(item, Mapping):
                path = common.relative_display_path(item.get("path") or item.get("relpath") or item.get("file") or "-", base=raw_path)
                file_type = _infer_file_type(path, item.get("file_type") or item.get("type"))
            else:
                path = common.relative_display_path(item, base=raw_path)
                file_type = _infer_file_type(path)
            lane_rule = classify_review_lane(file_type)
            lane, hint = lane_rule["lane"], lane_rule["hint"]
            if kind in {"added", "removed"} and lane in {"P0", "P1"}:
                hint = "先按文件名 / 哈希 / 解析签名匹配旧版/新版；匹配成功再确认文件证据，否则标记为真实新增/删除"
            changes.append(
                {
                    "change": kind,
                    "file_type": file_type,
                    "path": path,
                    "identity": _file_identity(path, item if isinstance(item, Mapping) else {}, file_type),
                    "review_lane": lane,
                    "hint": hint,
                }
            )
    return changes


def _is_release_note_evidence(item: Mapping[str, Any]) -> bool:
    text = " ".join(
        str(item.get(key) or "")
        for key in ["path", "relpath", "file", "name", "role", "doc_type", "file_type"]
    ).lower()
    return any(token in text for token in RELEASE_NOTE_EVIDENCE_TOKENS)


def _release_note_path(item: Mapping[str, Any]) -> str:
    return str(item.get("path") or item.get("relpath") or item.get("file") or item.get("name") or "-")


def _release_note_summary(item: Mapping[str, Any]) -> str:
    for key in ["summary", "description", "title", "message"]:
        value = item.get(key)
        if value:
            return str(value)
    role = item.get("doc_type") or item.get("role") or "发布证据"
    return f"扫描证据：{role}"


def _add_release_note(notes: list[dict[str, str]], seen: set[str], item: Mapping[str, Any], *, limit: int) -> None:
    if len(notes) >= limit or not _is_release_note_evidence(item):
        return
    path = _release_note_path(item)
    if path in seen:
        return
    seen.add(path)
    notes.append({"path": path, "summary": _release_note_summary(item)})


def _release_notes_from_existing_evidence(version: Mapping[str, Any], *, limit: int = 3) -> list[dict[str, str]]:
    notes: list[dict[str, str]] = []
    seen: set[str] = set()

    explicit_notes = version.get("release_notes") or []
    if isinstance(explicit_notes, list):
        for raw in explicit_notes:
            item = raw if isinstance(raw, Mapping) else {"path": str(raw), "summary": "库目录发布证据"}
            _add_release_note(notes, seen, item, limit=limit)

    scan_dir = _version_scan_dir(version)
    if scan_dir and len(notes) < limit:
        release_readiness = read_json(scan_dir / "summary" / "release_readiness.json", default={}) or {}
        doc_summary = _as_mapping(release_readiness.get("doc_summary"))
        for item in doc_summary.get("files", []) or []:
            if isinstance(item, Mapping):
                _add_release_note(notes, seen, item, limit=limit)
                if len(notes) >= limit:
                    break

    if scan_dir and len(notes) < limit:
        inventory = _scan_inventory(scan_dir)
        for item in inventory.get("files", []) or []:
            if isinstance(item, Mapping):
                _add_release_note(notes, seen, item, limit=limit)
                if len(notes) >= limit:
                    break

    return notes


def _base_trust_status(base_ref: str) -> str:
    if base_ref == "NEEDS_BASE_CONFIRM":
        return "BLOCKING"
    if base_ref in STANDARD_BASE_REFS:
        return "PASS"
    if base_ref in FALLBACK_BASE_REFS or not base_ref:
        return "WARNING"
    return "WARNING"


def _base_trust_note(base_ref: str) -> str:
    if base_ref == "NEEDS_BASE_CONFIRM":
        return "无法确定基准版；请先确认当前有效版或上一有效版。"
    if base_ref in STANDARD_BASE_REFS:
        return "基准版已确认；该结果可作为标准更新详情。"
    return "该结果不是标准当前有效版更新详情，仅供手动对比/调试；正式发布前请确认基准版。"


def _update_status_message(status: Any) -> str:
    key = str(status or "").upper()
    return UPDATE_STATUS_COPY.get(key, f"更新详情状态：{key or 'UNKNOWN'}。")


def _path_if_exists(value: Any) -> Path | None:
    if not value:
        return None
    path = Path(str(value))
    return path if path.exists() else None


def _version_scan_dir(version: Mapping[str, Any]) -> Path | None:
    scan = version.get("scan") or {}
    value = scan.get("scan_dir") if isinstance(scan, Mapping) else None
    if not value:
        value = version.get("scan_dir")
    return _path_if_exists(value)


def _scan_inventory(scan_dir: Path | None) -> Mapping[str, Any]:
    return read_json(scan_dir / "file_inventory.json", default={}) if scan_dir else {}


def _scan_parser_manifest(scan_dir: Path | None) -> Mapping[str, Any]:
    return read_json(scan_dir / "parser_manifest.json", default={}) if scan_dir else {}


def _scan_parser_results(scan_dir: Path | None) -> Mapping[str, Any]:
    return read_json(scan_dir / "parser_results.json", default={}) if scan_dir else {}


def _build_scan_evidence_model(version: Mapping[str, Any]) -> dict[str, Any]:
    scan_dir = _version_scan_dir(version)
    scan_meta = read_json(scan_dir / "scan_meta.json", default={}) if scan_dir else {}
    inventory = _scan_inventory(scan_dir)
    parser_manifest = _scan_parser_manifest(scan_dir)
    parser_results = _scan_parser_results(scan_dir)
    release_readiness = read_json(scan_dir / "summary" / "release_readiness.json", default={}) if scan_dir else {}
    counts = _as_mapping(inventory.get("file_type_counts"))
    parser_task_count = sum(
        1
        for file_entry in (parser_manifest.get("files", []) or [])
        for task in (file_entry.get("parser_tasks", []) or [])
        if task.get("parser_name")
    )
    file_total = sum(_as_int(v) for v in counts.values())
    scan = _as_mapping(version.get("scan"))
    return {
        "context": {
            "scan_dir": str(scan_dir or ""),
            "scan_id": scan_meta.get("scan_id") or scan.get("scan_id") or "",
            "scan_status": version.get("scan_status") or scan.get("status") or "",
            "library_id": scan_meta.get("library_id") or scan_meta.get("library_name") or "",
            "version": scan_meta.get("release_version") or scan_meta.get("version") or "",
            "raw_path": scan_meta.get("root_path") or version.get("raw_path") or "",
            "input_fingerprint": scan_meta.get("input_fingerprint") or scan_meta.get("content_fingerprint") or "",
            "tool_version": scan_meta.get("tool_version") or "",
        },
        "inventory": inventory,
        "parser_manifest": parser_manifest,
        "parser_results": parser_results,
        "release_readiness": release_readiness,
        "counts": counts,
        "corner_summary": inventory.get("corner_filename_summary") or {},
        "parser_task_count": parser_task_count,
        "file_total": file_total,
        "unknown_count": _as_int(counts.get("unknown")),
        "required_view_status": release_readiness.get("required_view_status") or release_readiness.get("bundle_status"),
    }


def _comparison_context(
    *,
    diff_dir: Path | None,
    diff_meta: Mapping[str, Any],
    base_ref: str,
    base_version: str,
    base_source: str,
    status: str,
) -> dict[str, Any]:
    relation = _as_mapping(diff_meta.get("version_relation"))
    return {
        "base_ref": base_ref,
        "base_version": base_version,
        "base_source": base_source,
        "relation_kind": relation.get("kind") or relation.get("diff_mode") or diff_meta.get("diff_type") or "",
        "diff_dir": str(diff_dir or ""),
        "diff_status": status,
        "old_scan": diff_meta.get("old_scan") or "",
        "new_scan": diff_meta.get("new_scan") or "",
        "old_scan_id": diff_meta.get("old_scan_id") or "",
        "new_scan_id": diff_meta.get("new_scan_id") or "",
    }


def _scan_compatibility(scan_context: Mapping[str, Any], comparison_context: Mapping[str, Any]) -> dict[str, Any]:
    current_scan_dir = str(scan_context.get("scan_dir") or "")
    diff_new_scan = str(comparison_context.get("new_scan") or "")
    has_scan = bool(current_scan_dir)
    has_diff = bool(comparison_context.get("diff_dir"))
    new_scan_matches = not (has_scan and diff_new_scan) or Path(diff_new_scan) == Path(current_scan_dir)
    status = "PASS" if has_scan and (not has_diff or new_scan_matches) else "WARNING"
    if not has_scan:
        status = "MISSING_SCAN"
    return {
        "status": status,
        "current_scan_dir": current_scan_dir,
        "diff_new_scan": diff_new_scan,
        "new_scan_matches_current": new_scan_matches,
    }


def _select_diff_dir(version: Mapping[str, Any], *, base_ref: str, base_version: str) -> Path | None:
    diff = _as_mapping(version.get("diff"))
    keyed_candidates: list[tuple[str, tuple[str, ...]]] = [
        ("explicit", ("base_diff_dir", "current_effective_diff_dir", "diff_dir")),
        ("current_effective", ("current_effective_diff_dir", "base_diff_dir", "diff_dir")),
        ("previous_effective", ("previous_effective_diff_dir", "current_effective_diff_dir", "base_diff_dir", "diff_dir")),
        ("review_window", ()),
        ("base_full", ("cumulative_diff_dir", "base_diff_dir", "diff_dir")),
        ("recorded_base", ("base_diff_dir", "diff_dir")),
        ("adjacent_fallback", ("adjacent_diff_dir", "diff_dir")),
    ]
    for ref, keys in keyed_candidates:
        if base_ref != ref:
            continue
        for key in keys:
            path = _path_if_exists(diff.get(key))
            if path:
                return path
    matching_legacy = [
        ("base_version", "base_diff_dir"),
        ("current_effective", "current_effective_diff_dir"),
        ("current_effective_ref", "current_effective_diff_dir"),
        ("latest_effective_ref", "current_effective_diff_dir"),
        ("adjacent_old_version", "adjacent_diff_dir"),
        ("cumulative_base_version", "cumulative_diff_dir"),
    ]
    for version_key, dir_key in matching_legacy:
        if base_version and str(diff.get(version_key) or "") == str(base_version):
            path = _path_if_exists(diff.get(dir_key))
            if path:
                return path
    inferred = _infer_diff_dir_for_base(diff, base_version)
    if inferred:
        return inferred
    return None


def _infer_diff_dir_for_base(diff: Mapping[str, Any], base_version: str) -> Path | None:
    if not base_version:
        return None
    known: list[Path] = []
    for key in [
        "base_diff_dir",
        "current_effective_diff_dir",
        "previous_effective_diff_dir",
        "adjacent_diff_dir",
        "cumulative_diff_dir",
        "diff_dir",
    ]:
        path = _path_if_exists(diff.get(key))
        if path:
            known.append(path)
    if not known:
        return None
    candidates: list[Path] = []
    for path in known:
        parent = path.parent if path.name == "adjacent" or path.name.startswith("base_") else path
        candidates.append(parent / f"base_{base_version}")
        candidates.append(parent / f"base_{common.safe(base_version)}")
    for candidate in candidates:
        path = _path_if_exists(candidate)
        if path:
            return path
    return None


def _summary_metrics(summary: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    preferred = [
        "status",
        "risk_level",
        "added_files",
        "removed_files",
        "changed_files",
        "view_changes",
        "type_changes",
        "release_evidence_changes",
        "parser_regressions",
        "parser_status_regressions",
        "readiness_regressions",
        "manual_pairwise_tasks",
        "manual_review_items",
        "breaking_changes",
    ]
    seen: set[str] = set()
    for key in preferred:
        if key in summary:
            rows.append({"metric": key, "value": summary.get(key)})
            seen.add(key)
    for key, value in summary.items():
        if key in seen or key in {"schema_version", "recommended_actions"}:
            continue
        if isinstance(value, (str, int, float, bool)) or value is None:
            rows.append({"metric": str(key), "value": value})
    return rows


def _file_diff_commands(lib: Mapping[str, Any], version: Mapping[str, Any], base_version: str, changes: list[dict[str, Any]]) -> list[dict[str, str]]:
    del lib, version, base_version, changes
    return []


def _path_items(value: Any, key: str = "path") -> list[str]:
    if isinstance(value, Mapping):
        return [str(item.get(key) or path) if isinstance(item, Mapping) else str(path) for path, item in value.items()]
    if isinstance(value, list):
        out: list[str] = []
        for item in value:
            if isinstance(item, Mapping):
                out.append(str(item.get(key) or item.get("path") or item.get("relpath") or ""))
            else:
                out.append(str(item))
        return [item for item in out if item]
    return []


def _dominant_root(paths: Iterable[str]) -> str:
    roots: Counter[str] = Counter()
    for path in paths:
        text = str(path or "").strip("/")
        if "/" not in text:
            continue
        root = text.split("/", 1)[0]
        if root and root not in {".", ".."}:
            roots[root] += 1
    return roots.most_common(1)[0][0] if roots else "-"


def _path_restructure_summary(file_diff: Mapping[str, Any], summary: Mapping[str, Any]) -> dict[str, Any]:
    counts = _as_mapping(file_diff.get("counts"))
    migrations = [item for item in file_diff.get("package_root_migrations", []) or [] if isinstance(item, Mapping)]
    moved_items = file_diff.get("renamed_or_moved", []) or []
    moved_count = _as_int(summary.get("renamed_or_moved", counts.get("renamed_or_moved", len(moved_items))))
    added = _as_int(summary.get("added_files", counts.get("added")))
    removed = _as_int(summary.get("removed_files", counts.get("removed")))
    changed = _as_int(summary.get("changed_files", counts.get("changed")))
    primary_migration = migrations[0] if migrations else {}
    moved_old = _path_items(moved_items, "old")
    moved_new = _path_items(moved_items, "new")
    old_root = str(primary_migration.get("old_root") or _dominant_root(moved_old or _path_items(file_diff.get("removed"))))
    new_root = str(primary_migration.get("new_root") or _dominant_root(moved_new or _path_items(file_diff.get("added"))))
    matched = _as_int(
        summary.get(
            "package_root_migration_matched_files",
            counts.get("package_root_migration_matched_files", primary_migration.get("matched_logical_paths")),
        )
    )
    suspected = bool(migrations or (moved_count and changed == 0 and (added or removed) and (old_root != "-" or new_root != "-")))
    return {
        "suspected": suspected,
        "old_root": old_root,
        "new_root": new_root,
        "renamed_or_moved": moved_count,
        "package_root_migrations": _as_int(summary.get("package_root_migrations", counts.get("package_root_migrations", len(migrations)))),
        "package_root_migration_matched_files": matched,
        "old_root_file_count": _as_int(primary_migration.get("old_root_file_count")),
        "new_root_file_count": _as_int(primary_migration.get("new_root_file_count")),
        "raw_added_under_new_root": _as_int(primary_migration.get("raw_added_under_new_root")),
        "raw_removed_under_old_root": _as_int(primary_migration.get("raw_removed_under_old_root")),
        "added_files": added,
        "removed_files": removed,
        "changed_files": changed,
    }


def _group_file_changes_by_review_mode(file_changes: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    lane_priority = {"P0": 0, "P1": 1}
    recommended = [
        item
        for item in file_changes
        if item.get("review_lane") in lane_priority
        and str(item.get("file_type") or "").lower() in DEFAULT_FILE_DIFF_TYPES
    ]
    recommended = sorted(
        recommended,
        key=lambda item: (
            lane_priority.get(str(item.get("review_lane") or ""), 99),
            str(item.get("path") or ""),
        ),
    )
    summary_only = [item for item in file_changes if item.get("review_lane") == "Summary-only"]
    metadata_only = [item for item in file_changes if item.get("review_lane") == "Metadata-only"]
    return recommended, summary_only, metadata_only


def _cn_base_ref(value: Any) -> str:
    text = str(value or "")
    return {
        "current_effective": "当前有效版",
        "previous_effective": "上一有效版",
        "latest_effective_ref": "最新有效版",
        "latest_effective": "最新有效版",
        "base_full": "完整包基线",
        "review_window": "审查窗口基准",
        "explicit": "手动指定基准版",
        "adjacent": "相邻版本",
        "adjacent_fallback": "相邻上一版",
        "recorded_base": "已记录对比基准",
        "recorded_base_fallback": "已记录对比基准",
        "NEEDS_BASE_CONFIRM": "待确认基准版",
    }.get(text, text or "待确认基准版")


def _cn_base_source(value: Any) -> str:
    text = str(value or "")
    return {
        "current_effective_ref": "当前有效版引用",
        "previous_effective_version": "上一有效版",
        "base_full_version": "完整包基线",
        "catalog_recorded_base": "目录记录基线",
        "full_baseline": "完整包基线",
        "previous_full": "上一完整包",
        "latest_effective_ref": "最新有效版引用",
        "explicit": "手动指定",
        "manual": "手动指定",
        "diff.base_version:explicit": "对比记录：手动指定",
        "diff.base_version:current_effective": "对比记录：当前有效版",
        "diff.base_version:previous_effective": "对比记录：上一有效版",
        "diff.base_version:full_baseline": "对比记录：完整包基线",
        "diff.base_version:previous_full": "对比记录：上一完整包",
        "diff.base_version:fallback": "已记录对比结果",
        "diff_summary": "对比记录",
        "review_window.compare_old": "审查窗口对比对象",
    }.get(text, text or "-")


def _version_update_headline(base_ref: str, added_files: int, removed_files: int, changed_files: int, recommended_count: int, reviewed_count: int) -> str:
    return (
        f"当前版本相对 {_cn_base_ref(base_ref)}：修改文件 {changed_files} 个，新增 {added_files} 个，删除 {removed_files} 个；"
        f"其中 {recommended_count} 个需要优先下钻，{reviewed_count} 个按摘要级/元数据级证据处理。"
    )


def _reviewed_count_for_headline(summary_only: list[dict[str, Any]], metadata_only: list[dict[str, Any]]) -> int:
    review_units: set[tuple[str, str]] = set()
    for item in metadata_only:
        file_type = str(item.get("file_type") or "").lower()
        path = str(item.get("path") or "")
        if file_type in {"gds", "oas", "layout", "milkyway", "ndm"}:
            review_units.add(("layout", str(Path(path).with_suffix("")) if path else file_type))
        else:
            review_units.add((file_type, path))
    return len(summary_only) + len(review_units)


def _version_update_confidence_note(model: Mapping[str, Any]) -> str:
    return (
        f"基准来源：{_cn_base_ref(model.get('base_ref'))} / {_cn_base_source(model.get('base_source'))}；"
        f"基准版本：{model.get('base_version') or '-'}；"
        f"对比口径：{_cn_semantics(model.get('comparison_semantics'))}；"
        f"删除口径：{_cn_delete_semantics(model.get('delete_semantics'))}"
    )


def _primary_next_action(status: str, recommended_count: int, command_count: int) -> dict[str, Any]:
    del command_count
    if str(status or "").upper() == "NEEDS_BASE_CONFIRM":
        return {
            "kind": "base_confirm_required",
            "label": "审查前确认基准版",
            "command_count": 0,
        }
    if recommended_count > 0:
        return {
            "kind": "file_diff_recommended",
            "label": "审查重点文件证据",
            "command_count": 0,
        }
    return {
        "kind": "review_evidence",
        "label": "审查证据",
        "command_count": 0,
    }


def _normalize_recommended_action(action: Any) -> str:
    text = str(action or "").strip()
    lowered = text.lower()
    if "手动两两" in text or "两两对比" in text or "pairwise" in lowered:
        return "确认重点文件证据，并把确认结果作为发布证据归档。"
    return text


def _usage_decision_result(
    *,
    status: Any,
    base_trust_status: Any,
    lane_counts: Mapping[str, Any],
    release_notes: list[Any],
    review_gate: Mapping[str, Any] | None = None,
) -> tuple[str, list[str]]:
    reasons: list[str] = []
    status_key = str(status or "").upper()
    base_key = str(base_trust_status or "").upper()
    gate = review_gate if isinstance(review_gate, Mapping) else {}
    gate_status = str(gate.get("status") or "").upper()
    blocking = len(gate.get("blocking_items", []) or [])

    if status_key in {"NEEDS_BASE_CONFIRM", "SCAN_BLOCKED", "DIFF_BLOCKED"} or base_key in {"BLOCK", "BLOCKING", "BLOCKED"}:
        reasons.append("base_not_confirmed")
        return "BLOCKED", reasons
    if status_key in {"CHANGED", "DIFF", "REVIEW", "DIFF_REVIEW"}:
        reasons.append("diff_changed")
    if status_key in {"NO_DIFF_SUMMARY", "DIFF_NOT_RUN"}:
        reasons.append("diff_incomplete")
    if blocking:
        reasons.append("review_gate_blocking")
        return "BLOCKED", reasons
    if gate_status in {"REVIEW_REQUIRED", "NEEDS_REVIEW", "ATTENTION"}:
        reasons.append("review_gate_attention")
    if _as_int(lane_counts.get("recommended_file_diff")):
        reasons.append("recommended_file_diff")
    if not release_notes:
        reasons.append("release_note_missing")
    if reasons:
        return "USAGE_REVIEW_REQUIRED", reasons
    return "READY", []


def _target_ref_id(value: Any) -> str:
    text = str(value or "").strip()
    if ":" in text:
        return text.split(":", 1)[1].strip()
    return text


def _review_context_base_rule(review_context: Mapping[str, Any]) -> dict[str, str] | None:
    if not _review_context_is_active(review_context):
        return None
    old_target = str(review_context.get("compare_old") or review_context.get("old_target") or "").strip()
    base_version = _target_ref_id(old_target)
    if not base_version:
        return None
    return {
        "base_ref": "review_window",
        "base_version": base_version,
        "base_source": "review_window.compare_old",
    }


def build_version_update_detail_model(out: str | Path, lib: Mapping[str, Any], version: Mapping[str, Any]) -> dict[str, Any]:
    out_path = Path(out)
    lib_id = _library_id(lib)
    version_id = _version_id(version)
    safe_lib = _library_report_slug(lib)
    safe_ver = common.safe(version_id)
    review_context = build_version_detail_review_context(
        catalog_html_out=out_path,
        library_row=lib,
        version_row=version,
    )
    base_rule = _review_context_base_rule(review_context) or resolve_review_base(version, lib)
    base_ref = base_rule["base_ref"]
    base_version = base_rule["base_version"]
    base_source = base_rule["base_source"]
    comparison_rule = comparison_semantics_for_package(common.package_type(version), common.node_package_type(version))
    comparison_semantics = comparison_rule["comparison_scope"]
    compare_strategy = comparison_rule["compare_strategy"]
    delete_semantics = comparison_rule["delete_semantics"]
    diff_dir = _select_diff_dir(version, base_ref=base_ref, base_version=base_version)
    diff_meta = dict(common.version_diff_json(diff_dir, "diff_meta.json"))
    summary = dict(common.version_diff_summary(diff_dir))
    file_diff = dict(common.version_file_diff(diff_dir))
    view_diff = dict(common.version_diff_json(diff_dir, "view_diff.json"))
    type_diff = dict(common.version_diff_json(diff_dir, "type_diff.json"))
    release_readiness_diff = dict(common.version_diff_json(diff_dir, "release_readiness_diff.json"))
    release_evidence_diff = dict(common.version_diff_json(diff_dir, "release_evidence_diff.json"))
    diff_issues = dict(common.version_diff_json(diff_dir, "diff_issues.json"))
    file_changes = _iter_file_changes(file_diff, raw_path=version.get("raw_path"))
    path_match_evidence = build_path_match_evidence(file_diff, raw_path=version.get("raw_path"))
    for item in file_changes:
        path = str(item.get("path") or "")
        change = str(item.get("change") or "")
        item.update(path_match_evidence.get(path) or default_path_match_evidence(change, path))
    added_files = _as_int(summary.get("added_files", _as_mapping(file_diff.get("counts")).get("added")))
    removed_files = _as_int(summary.get("removed_files", _as_mapping(file_diff.get("counts")).get("removed")))
    changed_files = summary.get("changed_files")
    if changed_files is None:
        changed_files = len(file_changes)
    path_restructure = _path_restructure_summary(file_diff, summary)
    summary_status = str(summary.get("status") or "").upper()
    if base_ref == "NEEDS_BASE_CONFIRM":
        status = "NEEDS_BASE_CONFIRM"
    elif diff_dir and not summary:
        status = "NO_DIFF_SUMMARY"
    elif not summary and not diff_dir:
        status = "DIFF_NOT_RUN"
    elif summary_status in {"DIFF", "CHANGED"} or _as_int(changed_files):
        status = "CHANGED"
    else:
        status = summary_status or "SAME"
    scan_evidence = _build_scan_evidence_model(version)
    comparison_context = _comparison_context(
        diff_dir=diff_dir,
        diff_meta=diff_meta,
        base_ref=base_ref,
        base_version=base_version,
        base_source=base_source,
        status=status,
    )
    scan_context = _as_mapping(scan_evidence.get("context"))
    scan_compatibility = _scan_compatibility(scan_context, comparison_context)
    release_notes = _release_notes_from_existing_evidence(version)
    recommended_file_diff, summary_only_reviewed, metadata_only_reviewed = _group_file_changes_by_review_mode(file_changes)
    commands = _file_diff_commands(lib, version, base_version, file_changes)
    recommended_count = len(recommended_file_diff)
    reviewed_count = _reviewed_count_for_headline(summary_only_reviewed, metadata_only_reviewed)
    metadata_only_changes = summary_only_reviewed + metadata_only_reviewed
    blocking_issues = 0
    for issue in _as_mapping(diff_issues).get("issues", []) or []:
        if isinstance(issue, Mapping) and str(issue.get("severity") or "").lower() in {"blocker", "blocking", "error"}:
            blocking_issues += 1
    lane_counts = {
        "recommended_file_diff": recommended_count,
        "summary_only": len(summary_only_reviewed),
        "metadata_only": len(metadata_only_reviewed),
        "blocking_issues": blocking_issues,
    }
    usage_decision, usage_reasons = _usage_decision_result(
        status=status,
        base_trust_status=_base_trust_status(base_ref),
        lane_counts=lane_counts,
        release_notes=release_notes,
        review_gate=version.get("review_gate") if isinstance(version.get("review_gate"), Mapping) else {},
    )
    md_path = out_path / "libraries" / safe_lib / "versions" / safe_ver / "current_lib_diff.md"
    trace_links = {
        "diff_summary": str(diff_dir / "diff_summary.json") if diff_dir else "",
        "file_diff": str(diff_dir / "file_diff.json") if diff_dir else "",
        "view_diff": str(diff_dir / "view_diff.json") if diff_dir else "",
        "type_diff": str(diff_dir / "type_diff.json") if diff_dir else "",
        "release_readiness_diff": str(diff_dir / "release_readiness_diff.json") if diff_dir else "",
        "release_evidence_diff": str(diff_dir / "release_evidence_diff.json") if diff_dir else "",
        "diff_issues": str(diff_dir / "diff_issues.json") if diff_dir else "",
        "markdown_export": str(md_path),
    }
    model = {
        "schema_version": "version_update_detail.v1",
        "library_id": lib_id,
        "formal_library_id": lib_id,
        "typed_library_id": lib.get("typed_library_id") or lib.get("library_id"),
        "report_slug": safe_lib,
        "library_name": _library_name(lib),
        "version_id": version_id,
        "target_version": version_id,
        "base_ref": base_ref,
        "base_version": base_version,
        "base_source": base_source,
        "base_trust_status": _base_trust_status(base_ref),
        "base_trust_note": _base_trust_note(base_ref),
        "usage_decision": usage_decision,
        "usage_decision_reasons": usage_reasons,
        "package_type": common.package_type(version),
        "compare_strategy": compare_strategy,
        "comparison_semantics": comparison_semantics,
        "delete_semantics": delete_semantics,
        "status": status,
        "status_message": _update_status_message(status),
        "diff_dir": str(diff_dir or ""),
        "diff_summary_path": str(diff_dir / "diff_summary.json") if diff_dir else "",
        "file_diff_path": str(diff_dir / "file_diff.json") if diff_dir else "",
        "markdown_export_path": str(md_path),
        "scan_context": scan_context,
        "comparison_context": comparison_context,
        "review_context": review_context,
        "scan_compatibility": scan_compatibility,
        "scan_evidence": scan_evidence,
        "diff_meta": diff_meta,
        "diff_summary": summary,
        "view_diff": view_diff,
        "type_diff": type_diff,
        "release_readiness_diff": release_readiness_diff,
        "release_evidence_diff": release_evidence_diff,
        "diff_issues": diff_issues,
        "file_diff": file_diff,
        "path_match_evidence": path_match_evidence,
        "added_files": added_files,
        "removed_files": removed_files,
        "changed_files": _as_int(changed_files),
        "summary_metrics": _summary_metrics(summary),
        "file_changes": file_changes,
        "recommended_file_diff": recommended_file_diff,
        "summary_only_reviewed": summary_only_reviewed,
        "metadata_only_reviewed": metadata_only_reviewed,
        "lane_counts": lane_counts,
        "reviewed_units_for_headline": reviewed_count,
        "summary_only_changes": summary_only_reviewed,
        "metadata_only_reviewed_changes": metadata_only_reviewed,
        "release_notes": release_notes,
        "review_gate": version.get("review_gate") if isinstance(version.get("review_gate"), Mapping) else {},
        "recommended_actions": [_normalize_recommended_action(action) for action in (summary.get("recommended_actions", []) or []) if str(action).strip()],
        "file_diff_recommendations": commands,
        "metadata_only_changes": metadata_only_changes,
        "path_restructure": path_restructure,
        "trace_links": trace_links,
    }
    model["headline"] = _version_update_headline(base_ref, added_files, removed_files, _as_int(changed_files), recommended_count, reviewed_count)
    model["confidence_note"] = _version_update_confidence_note(model)
    model["primary_next_action"] = _primary_next_action(status, recommended_count, len(commands))
    model["version_review_model"] = build_version_review_model(model)
    model["ip_user_view_model"] = _as_mapping(model["version_review_model"].get("ip_user_view"))
    return model


def _metric_rows(model: Mapping[str, Any]) -> list[str]:
    rows: list[str] = []
    for item in model.get("summary_metrics", []) or []:
        if not isinstance(item, Mapping):
            continue
        rows.append(f"<tr><td><code>{ui.esc(item.get('metric'))}</code></td><td>{ui.esc(item.get('value'))}</td></tr>")
    return rows


def _summary_metric_value(model: Mapping[str, Any], key: str, default: Any = 0) -> Any:
    for item in model.get("summary_metrics", []) or []:
        if isinstance(item, Mapping) and item.get("metric") == key:
            return item.get("value")
    return default


def _file_change_rows_for(items: Any) -> list[str]:
    rows: list[str] = []
    for item in items or []:
        if not isinstance(item, Mapping):
            continue
        rows.append(
            "<tr>"
            f"<td>{ui.badge(str(item.get('change') or '').upper(), _cn_change_kind(item.get('change')))}</td>"
            f"<td><code>{ui.esc(item.get('file_type') or '-')}</code></td>"
            f"<td><code>{ui.esc(item.get('path') or '-')}</code></td>"
            f"<td>{ui.badge(item.get('review_lane') or 'Review', _cn_review_lane(item.get('review_lane') or 'Review'))}</td>"
            f"<td><code>{ui.esc(_cn_match_status(item.get('match_status')))}</code></td>"
            f"<td><code>{ui.esc(item.get('base_candidate') or '-')}</code></td>"
            f"<td><code>{ui.esc(item.get('target_candidate') or '-')}</code></td>"
            f"<td>{ui.esc(item.get('hint') or '-')}</td>"
            "</tr>"
        )
    return rows


def _file_change_rows(model: Mapping[str, Any]) -> list[str]:
    return _file_change_rows_for(model.get("file_changes", []))


def _lane_summary_rows(items: list[Any], *, evidence_keys: tuple[str, ...], default_evidence: str) -> list[str]:
    grouped: dict[str, dict[str, Any]] = {}
    for item in items:
        if not isinstance(item, Mapping):
            continue
        file_type = str(item.get("file_type") or "unknown")
        group = grouped.setdefault(file_type, {"count": 0, "examples": [], "evidence": []})
        group["count"] += 1
        path = str(item.get("path") or "")
        if path and len(group["examples"]) < 3:
            group["examples"].append(path)
        for key in evidence_keys:
            text = str(item.get(key) or "").strip()
            if text and text not in group["evidence"] and len(group["evidence"]) < 2:
                group["evidence"].append(text)
    rows: list[str] = []
    for file_type, group in sorted(grouped.items(), key=lambda pair: (-int(pair[1]["count"]), pair[0])):
        examples = ", ".join(group["examples"]) if group["examples"] else "-"
        evidence = "；".join(group["evidence"]) if group["evidence"] else default_evidence
        rows.append(
            "<tr>"
            f"<td><code>{ui.esc(file_type)}</code></td>"
            f"<td>{ui.esc(group['count'])}</td>"
            f"<td><code>{ui.esc(examples)}</code></td>"
            f"<td>{ui.esc(evidence)}</td>"
            "</tr>"
        )
    return rows


def _summary_only_summary_rows(model: Mapping[str, Any]) -> list[str]:
    return _lane_summary_rows(
        list(model.get("summary_only_reviewed", []) or []),
        evidence_keys=("summary_evidence", "hint", "reason"),
        default_evidence="摘要级审查；默认不做文件级深度比较",
    )


def _metadata_only_summary_rows(model: Mapping[str, Any]) -> list[str]:
    return _lane_summary_rows(
        list(model.get("metadata_only_reviewed", []) or []),
        evidence_keys=("metadata_evidence", "hint", "reason"),
        default_evidence="元数据级审查；默认只看元数据/哈希/规模",
    )


def _file_change_artifact_rows(model: Mapping[str, Any]) -> list[str]:
    file_changes = [item for item in model.get("file_changes", []) or [] if isinstance(item, Mapping)]
    return [
        f"<tr><td>完整变化文件</td><td>{ui.esc(len(file_changes))}</td><td>见 file_diff.json；详情页只保留重点变化表。</td></tr>",
        f"<tr><td>新增</td><td>{ui.esc(model.get('added_files') or 0)}</td><td>按视图变化矩阵聚合展示。</td></tr>",
        f"<tr><td>删除</td><td>{ui.esc(model.get('removed_files') or 0)}</td><td>按视图变化矩阵聚合展示。</td></tr>",
        f"<tr><td>修改</td><td>{ui.esc(model.get('changed_files') or 0)}</td><td>按视图变化矩阵聚合展示。</td></tr>",
        f"<tr><td>P0/P1 重点</td><td>{ui.esc(len(model.get('recommended_file_diff', []) or []))}</td><td>主页面的变化文件明细只展示 P0/P1/审查项。</td></tr>",
    ]


def _focus_file_change_rows(model: Mapping[str, Any]) -> list[str]:
    focus = [
        item
        for item in model.get("file_changes", []) or []
        if isinstance(item, Mapping) and str(item.get("review_lane") or "") in {"P0", "P1", "Review"}
    ]
    if not focus:
        focus = [item for item in model.get("file_changes", []) or [] if isinstance(item, Mapping)]
    return _file_change_rows_for(focus[:120])


def _lane_count(model: Mapping[str, Any], key: str) -> int:
    return _as_int(_as_mapping(model.get("lane_counts")).get(key))


def _summary_value(model: Mapping[str, Any], key: str) -> int:
    return _as_int(_summary_metric_value(model, key))


def _release_note_rows(model: Mapping[str, Any]) -> list[str]:
    rows: list[str] = []
    for item in model.get("release_notes", []) or []:
        if not isinstance(item, Mapping):
            continue
        rows.append(
            "<tr>"
            f"<td><code>{ui.esc(common.relative_display_path(item.get('path') or '-'))}</code></td>"
            f"<td>{ui.esc(item.get('summary') or '-')}</td>"
            "</tr>"
        )
    return rows


def _recommended_action_rows(model: Mapping[str, Any]) -> list[str]:
    return [f"<tr><td>{ui.esc(action)}</td></tr>" for action in model.get("recommended_actions", []) or []]


def _review_brief_callouts(model: Mapping[str, Any]) -> str:
    items: list[str] = []
    base_ref = str(model.get("base_ref") or "")
    if base_ref == "adjacent_fallback":
        items.append("该结果不是标准当前有效版更新详情，仅供手动对比/调试；正式发布前请确认基准版。")
    status_message = str(model.get("status_message") or _update_status_message(model.get("status")) or "").strip()
    if status_message:
        items.append(status_message)
    path = _as_mapping(model.get("path_restructure"))
    if path.get("suspected"):
        old_root = path.get("old_root") or "-"
        new_root = path.get("new_root") or "-"
        matched = _as_int(path.get("package_root_migration_matched_files"))
        items.append(
            f"包装目录变化：旧包根={old_root}，新包根={new_root}，逻辑路径匹配 {matched} 个；该信息用于解释新增/删除统计，不默认代表 IP 使用风险。"
        )
    scan_evidence = _as_mapping(model.get("scan_evidence"))
    counts = _as_mapping(scan_evidence.get("counts"))
    count_only_total = sum(_as_int(counts.get(item)) for item in catalog.VERSION_COUNT_ONLY_TYPES)
    if (
        str(model.get("comparison_semantics") or "") == "incremental"
        and not _as_int(scan_evidence.get("parser_task_count"))
        and not count_only_total
        and not _as_int(model.get("changed_files"))
    ):
        items.append("当前版本是增量包：本页原始扫描只统计本次交付内容；继承文件请查看有效版或基准版视图。")
        items.append("当前原始扫描没有发现大文件计数项。")
        items.append("当前扫描没有生成可展示的解析器结果。")
    release_notes = [
        common.relative_display_path(item.get("path") or "-")
        for item in model.get("release_notes", []) or []
        if isinstance(item, Mapping)
    ][:3]
    if release_notes:
        items.append("发布说明：" + "，".join(release_notes))
    else:
        items.append("发布说明：缺失")
    if not items:
        return ""
    rows = "".join(f"<div class='context-row'><b>审查提示</b><em>{ui.esc(item)}</em></div>" for item in items)
    return "<div class='context-list review-brief-callouts'>" + rows + "</div>"


def _mapping_rows(value: Mapping[str, Any], *, prefix: str = "") -> list[str]:
    rows: list[str] = []
    for key, item in value.items():
        label = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(item, (Mapping, list)):
            display = json.dumps(item, ensure_ascii=False, sort_keys=True)
        else:
            display = item
        rows.append(f"<tr><td><code>{ui.esc(label)}</code></td><td><code>{ui.esc(display)}</code></td></tr>")
    return rows


def _compact_json_summary(value: Mapping[str, Any]) -> str:
    if not value:
        return "缺失"
    parts: list[str] = []
    status = value.get("status")
    if status:
        parts.append(f"status={status}")
    summary = value.get("summary")
    if isinstance(summary, Mapping):
        for key, item in summary.items():
            if isinstance(item, (Mapping, list)):
                continue
            parts.append(f"{key}={item}")
            if len(parts) >= 6:
                break
    for key in ["views", "by_type", "by_role", "issues"]:
        item = value.get(key)
        if isinstance(item, Mapping):
            parts.append(f"{key}={len(item)}")
        elif isinstance(item, list):
            parts.append(f"{key}={len(item)}")
    return "；".join(parts[:8]) if parts else "有证据，详见原始 JSON"


def _evidence_artifact_links(model: Mapping[str, Any]) -> str:
    links = _as_mapping(model.get("trace_links"))
    items = [
        ("diff_summary.json", common.href(links.get("diff_summary") or ""), "对比总指标"),
        ("file_diff.json", common.href(links.get("file_diff") or ""), "完整变化文件"),
        ("view_diff.json", common.href(links.get("view_diff") or ""), "视图级变化证据"),
        ("type_diff.json", common.href(links.get("type_diff") or ""), "原始文件类型变化证据"),
        ("release_readiness_diff.json", common.href(links.get("release_readiness_diff") or ""), "发布就绪度变化"),
        ("release_evidence_diff.json", common.href(links.get("release_evidence_diff") or ""), "发布证据变化"),
        ("diff_issues.json", common.href(links.get("diff_issues") or ""), "对比问题明细"),
    ]
    return ui.trace_link_list(items)


def _evidence_json_summary_rows(model: Mapping[str, Any]) -> list[str]:
    items = [
        ("view_diff", _compact_json_summary(_as_mapping(model.get("view_diff")))),
        ("type_diff", _compact_json_summary(_as_mapping(model.get("type_diff")))),
        ("release_readiness_diff", _compact_json_summary(_as_mapping(model.get("release_readiness_diff")))),
        ("release_evidence_diff", _compact_json_summary(_as_mapping(model.get("release_evidence_diff")))),
    ]
    return [f"<tr><td><code>{ui.esc(label)}</code></td><td>{ui.esc(summary)}</td></tr>" for label, summary in items]


def _diff_issue_rows(model: Mapping[str, Any]) -> list[str]:
    issues = _as_mapping(model.get("diff_issues")).get("issues", [])
    rows: list[str] = []
    for item in issues or []:
        if not isinstance(item, Mapping):
            continue
        title = item.get("title") or item.get("message") or "-"
        message = item.get("message") or "-"
        rows.append(
            "<tr>"
            f"<td>{ui.badge(item.get('severity') or 'INFO')}</td>"
            f"<td><code>{ui.esc(item.get('category') or '-')}</code></td>"
            f"<td><b>{ui.esc(title)}</b><br><span class='muted'>{ui.esc(message)}</span></td>"
            "</tr>"
        )
    return rows


def _cn_compare_strategy(value: Any) -> str:
    text = str(value or "")
    if text == "incremental compare":
        return "增量对比 (incremental compare)"
    if text == "full compare":
        return "全量对比 (full compare)"
    return text or "-"


def _cn_semantics(value: Any) -> str:
    text = str(value or "")
    if text == "incremental":
        return "增量"
    if text == "full":
        return "全量"
    return text or "-"


def _cn_delete_semantics(value: Any) -> str:
    text = str(value or "")
    if text == "out_of_scope_missing":
        return "缺失文件不视为删除"
    if text == "real_delete":
        return "缺失文件视为真实删除"
    return text or "-"


def _version_detail_styles() -> str:
    return """
<style>
.version-dashboard{display:grid;grid-template-columns:minmax(0,1fr) 320px;gap:18px;align-items:start}.version-main,.version-side{display:flex;flex-direction:column;gap:18px}.version-side{position:sticky;top:18px}.version-overview{border:1px solid #d8dee8;border-radius:14px;background:#fff;box-shadow:var(--shadow);padding:18px 20px;margin-bottom:18px}.overview-head{display:flex;justify-content:space-between;gap:14px;align-items:flex-start;border-bottom:1px solid var(--line);padding-bottom:14px;margin-bottom:14px}.overview-title h2{margin:0 0 4px;font-size:20px}.overview-title p{font-size:13px}.overview-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px}.compact-overview-grid{grid-template-columns:1.25fr 1fr 1fr 1fr 1fr}.overview-cell{border:1px solid var(--line);border-radius:10px;background:#f8fafc;padding:10px 12px;min-width:0}.overview-cell b{display:block;font-size:12px;color:#667085}.overview-cell em{display:block;font-style:normal;font-weight:800;color:#172033;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.overview-cell span{display:block;margin-top:3px;color:#667085;font-size:12px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.overview-actions{display:flex;justify-content:flex-end;margin-top:12px}.overview-context{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:12px;align-items:start;border:1px solid var(--line);border-radius:10px;background:#fbfcff;padding:12px 14px;margin-top:12px}.overview-context h3{margin:0 0 8px;font-size:13px;color:#344054}.overview-context-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px}.overview-context-item b{display:block;font-size:11px;color:#667085}.overview-context-item code,.overview-context-item em{display:block;font-style:normal;color:#344054;overflow-wrap:anywhere}.overview-context-actions{display:flex;gap:8px;flex-wrap:wrap;justify-content:flex-end}.judgment-strip{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:8px;margin-top:14px}.judgment-item{border:1px solid #d8dee8;border-left-width:4px;border-radius:10px;background:#fff;padding:10px 12px;min-height:76px}.judgment-item b{display:block;font-size:11px;text-transform:uppercase;color:#667085;margin-bottom:6px}.judgment-item strong{display:block;color:#172033;font-size:15px;line-height:1.2;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.judgment-item span{display:block;color:#667085;font-size:12px;margin-top:5px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.judgment-ok{border-left-color:#067647}.judgment-warn{border-left-color:#b54708}.judgment-bad{border-left-color:#b42318}.judgment-neutral{border-left-color:#98a2b3}.change-brief{display:grid;grid-template-columns:1.2fr 1fr;gap:10px;margin:12px 0}.change-brief-block{border:1px solid var(--line);border-radius:10px;background:#fff;padding:12px 14px}.change-brief-block b{display:block;color:#344054;margin-bottom:5px}.change-brief-block p{margin:0;color:#667085;font-size:13px}.change-brief-tags{display:flex;gap:6px;flex-wrap:wrap;margin-top:8px}.change-brief-tags code{background:#f2f4f7;border:1px solid #e4e7ec;border-radius:6px;padding:2px 6px}.version-update-lead{border:1px solid var(--line);border-radius:10px;background:#f8fafc;padding:12px 14px;margin-bottom:12px}.version-update-lead b{display:block;color:#172033;margin-bottom:5px}.version-update-lead p{margin:0;color:#667085;font-size:13px}.version-review-model{margin-top:12px}.review-group-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:12px;margin:12px 0}.review-group-card{border:1px solid var(--line);border-radius:10px;background:#fff;padding:12px 14px;min-width:0}.review-group-head{display:flex;align-items:flex-start;justify-content:space-between;gap:10px;margin-bottom:8px}.review-group-head h3{margin:0;font-size:14px;color:#344054}.review-group-card p{font-size:13px;margin:0 0 10px;color:#667085}.review-group-facts{font-size:12px}.review-group-facts th,.review-group-facts td{padding:7px 8px}.base-trust-context{border:1px solid var(--line);border-radius:10px;background:#fff;padding:12px 14px;margin-bottom:12px}.base-trust-head{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin-bottom:8px}.base-trust-head b{color:#344054}.base-trust-context p{margin:0 0 10px;color:#667085;font-size:13px}.context-list{display:flex;flex-direction:column;gap:8px}.context-row{border:1px solid var(--line);border-radius:9px;background:#f8fafc;padding:9px 10px}.context-row b{display:block;font-size:12px;color:#667085}.context-row code,.context-row em{display:block;font-style:normal;color:#344054;overflow-wrap:anywhere}.section-label{margin:18px 0 8px;font-weight:900;color:#344054}.empty-guidance{border:1px dashed #d3dae6;border-radius:10px;background:#fbfcff;color:#667085;padding:12px 14px;margin:10px 0}.quality-note{border:1px solid var(--line);border-radius:10px;background:#f8fafc;padding:12px 14px;margin:12px 0;color:#667085}.quality-note b{color:#344054}.panel-body>h3{font-size:14px;margin:18px 0 8px;color:#344054}.version-scroll-table.focus-change-scroll,.version-scroll-table.change-scroll{height:420px;max-height:420px;overflow:scroll}.version-scroll-table.change-scroll td:nth-child(5),.version-scroll-table.focus-change-scroll td:nth-child(5){min-width:220px}.version-scroll-table.change-scroll table,.version-scroll-table.focus-change-scroll table{min-width:1780px}.version-scroll-table.change-scroll td:nth-child(3) code,.version-scroll-table.focus-change-scroll td:nth-child(3) code,.version-scroll-table.summary-only-scroll td:nth-child(2) code,.version-scroll-table.metadata-only-scroll td:nth-child(2) code{min-width:640px}.version-scroll-table.summary-only-scroll table,.version-scroll-table.metadata-only-scroll table{min-width:980px}.version-scroll-table.corner-detail-scroll{max-height:320px}.version-scroll-table.corner-detail-scroll table{min-width:980px}.version-scroll-table.unknown-detail-scroll{max-height:260px}.version-scroll-table.unknown-detail-scroll table{min-width:860px}.detail-fold.review-fold{border:1px solid var(--line);border-radius:10px;background:#fbfcff;padding:10px 12px;margin-top:12px}.detail-fold.review-fold summary{color:#344054}.raw-scan-note{border-left:4px solid #b85c00;background:#fff7e8;border-radius:10px;padding:12px 14px;margin:12px 0;color:#664000}.raw-scan-note b{display:block;color:#4f2f00}.side-panel .panel{box-shadow:none}.evidence-actions{display:grid;gap:8px}.evidence-actions .btn{justify-content:flex-start}.evidence-detail-stack{display:flex;flex-direction:column;gap:14px}.evidence-detail-stack details{border:1px solid var(--line);border-radius:10px;background:#fff;padding:10px 12px}.evidence-detail-stack summary{font-weight:800;color:#344054;cursor:pointer}@media(max-width:1200px){.compact-overview-grid{grid-template-columns:repeat(3,minmax(0,1fr))}}@media(max-width:1100px){.version-dashboard{grid-template-columns:1fr}.version-side{position:static}.overview-grid,.overview-context-grid,.compact-overview-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.overview-context{grid-template-columns:1fr}.overview-context-actions,.overview-actions{justify-content:flex-start}.judgment-strip{grid-template-columns:1fr 1fr}.change-brief{grid-template-columns:1fr}}@media(max-width:640px){.overview-head{display:block}.overview-grid,.overview-context-grid,.compact-overview-grid,.judgment-strip{grid-template-columns:1fr}.version-dashboard{gap:12px}.panel-head{display:block}.panel-actions{margin-top:10px}.version-scroll-table.change-scroll,.version-scroll-table.focus-change-scroll{height:360px}}
</style>
"""


def _raw_scan_scope_note(model: Mapping[str, Any], *, parser_task_count: int, count_only_total: int) -> str:
    if model.get("comparison_semantics") != "incremental":
        return ""
    if parser_task_count or count_only_total or _as_int(model.get("changed_files")):
        return ""
    return (
        "<div class='raw-scan-note'>"
        "<b>当前版本是增量包</b>"
        "本页原始扫描只统计本次交付内容；继承文件请查看有效版或基准版视图。"
        "</div>"
    )


def _judgment_class(status: Any) -> str:
    key = str(status or "").upper()
    if key in {"PASS", "OK", "READY", "SAME"}:
        return "ok"
    if key in {"FAIL", "FAILED", "ERROR", "BLOCK", "BLOCKING", "BLOCKED", "NEEDS_BASE_CONFIRM", "SCAN_BLOCKED", "DIFF_BLOCKED"}:
        return "bad"
    if key in {"WARNING", "WARN", "REVIEW", "CHANGED", "DIFF", "DIFF_REVIEW", "DIFF_NOT_RUN", "NO_DIFF_SUMMARY", "MISSING"}:
        return "warn"
    return "neutral"


def _judgment_strip(items: list[tuple[str, Any, str, Any]]) -> str:
    return "<div class='judgment-strip'>" + "".join(
        "<div class='judgment-item judgment-{cls}'>"
        "<b>{label}</b>"
        "<strong title='{value}'>{value}</strong>"
        "<span title='{detail}'>{detail}</span>"
        "</div>".format(
            cls=_judgment_class(status),
            label=ui.esc(label),
            value=ui.esc(value),
            detail=ui.esc(detail),
        )
        for label, value, detail, status in items
    ) + "</div>"


def _top_file_type_text(model: Mapping[str, Any], *, limit: int = 4) -> str:
    counts: Counter[str] = Counter()
    for item in model.get("file_changes", []) or []:
        if not isinstance(item, Mapping):
            continue
        counts[str(item.get("file_type") or "-").lower()] += 1
    if not counts:
        return "无文件变化"
    return ", ".join(f"{name}:{count}" for name, count in counts.most_common(limit))


def _evidence_judgment(model: Mapping[str, Any]) -> tuple[str, str, str]:
    summary_only = _lane_count(model, "summary_only")
    metadata_only = _lane_count(model, "metadata_only")
    release_notes = len(model.get("release_notes", []) or [])
    if metadata_only or summary_only:
        label = "混合证据"
        status = "INFO"
    else:
        label = "内容级证据"
        status = "PASS"
    detail = f"摘要级 {summary_only} / 元数据级 {metadata_only} / 发布说明 {release_notes}"
    return label, detail, status


def _usage_decision(model: Mapping[str, Any], version: Mapping[str, Any]) -> str:
    if model.get("usage_decision"):
        return str(model.get("usage_decision"))
    status = str(model.get("status") or "").upper()
    base_status = str(model.get("base_trust_status") or "").upper()
    gate = version.get("review_gate") if isinstance(version.get("review_gate"), Mapping) else {}
    gate_status = str((gate or {}).get("status") or "").upper()
    blocking = len((gate or {}).get("blocking_items", []) or [])
    if status in {"NEEDS_BASE_CONFIRM", "SCAN_BLOCKED", "DIFF_BLOCKED"} or base_status in {"BLOCK", "BLOCKING", "BLOCKED"}:
        return "BLOCKED"
    if (
        status in {"CHANGED", "DIFF", "REVIEW", "DIFF_REVIEW", "NO_DIFF_SUMMARY", "DIFF_NOT_RUN"}
        or gate_status in {"REVIEW_REQUIRED", "NEEDS_REVIEW", "ATTENTION"}
        or blocking
        or _lane_count(model, "recommended_file_diff")
        or not model.get("release_notes")
    ):
        return "USAGE_REVIEW_REQUIRED"
    return "READY"


def _management_gate_user_impact(version: Mapping[str, Any]) -> tuple[str, str, str]:
    gate = version.get("review_gate") if isinstance(version.get("review_gate"), Mapping) else {}
    status = str((gate or {}).get("status") or "NOT_BUILT").upper()
    blocking = len((gate or {}).get("blocking_items", []) or [])
    attention = len((gate or {}).get("attention_items", []) or [])
    if blocking:
        return "影响使用", f"{blocking} 个管理阻塞项", "BLOCKED"
    if status in {"REVIEW_REQUIRED", "NEEDS_REVIEW", "ATTENTION"} or attention:
        return "需管理确认", f"{attention} 个关注项", "WARNING"
    if status in {"READY", "PASS", "OK"}:
        return "不影响使用", "管理门禁已关闭", "PASS"
    return "未建立", "无管理门禁证据", "INFO"


def _review_context(model: Mapping[str, Any]) -> Mapping[str, Any]:
    return _as_mapping(model.get("review_context"))


def _review_context_is_active(ctx: Mapping[str, Any]) -> bool:
    return str(ctx.get("status") or "").upper() == "IN_ACTIVE_WINDOW"


def _review_context_role_label(role: Any) -> str:
    return {
        "candidate_base": "候选完整基线",
        "candidate_overlay": "候选叠加版本",
        "intermediate": "窗口中间版本",
        "standalone": "独立版本",
    }.get(str(role or ""), str(role or "独立版本"))


def _base_context_label(model: Mapping[str, Any]) -> str:
    return f"{_cn_base_ref(model.get('base_ref') or 'NEEDS_BASE_CONFIRM')} / {model.get('base_version') or '-'}"


def _display_target_ref(value: Any) -> str:
    text = str(value or "").strip()
    if text.startswith("raw:"):
        return f"原始版 {text[4:] or '-'}"
    if text.startswith("effective:"):
        return f"有效版 {text[len('effective:'):] or '-'}"
    return text or "-"


def _review_context_compare_label(ctx: Mapping[str, Any], model: Mapping[str, Any]) -> str:
    if _review_context_is_active(ctx):
        old = str(ctx.get("compare_old") or ctx.get("old_label") or "-")
        new = str(ctx.get("compare_new") or "")
        if not new and ctx.get("candidate_effective_id"):
            new = f"effective:{ctx.get('candidate_effective_id')}"
        return f"{_display_target_ref(old)} → {_display_target_ref(new)}"
    return _base_context_label(model)


def _review_context_freshness_label(ctx: Mapping[str, Any]) -> str:
    freshness = _as_mapping(ctx.get("freshness"))
    status = str(freshness.get("status") or "STALE_OR_MISSING")
    return {
        "FRESH": "证据齐全",
        "PARTIAL": "证据部分存在",
        "STALE_OR_MISSING": "证据缺失或陈旧",
    }.get(status, status)


def _overview_window_context(ctx: Mapping[str, Any], model: Mapping[str, Any]) -> str:
    if not _review_context_is_active(ctx):
        return ""
    rows = [
        ("窗口角色", _review_context_role_label(ctx.get("role_in_window"))),
        ("对比", _review_context_compare_label(ctx, model)),
        ("候选有效版", ctx.get("candidate_effective_id") or "-"),
        ("证据新鲜度", _review_context_freshness_label(ctx)),
    ]
    row_html = "".join(
        "<div class='overview-context-item'>"
        f"<b>{ui.esc(label)}</b><em title='{ui.esc(value)}'>{ui.esc(value)}</em>"
        "</div>"
        for label, value in rows
    )
    return (
        "<div class='overview-context'>"
        "<div><h3>当前审查窗口 / 有效版证据</h3>"
        f"<div class='overview-context-grid'>{row_html}</div></div>"
        "</div>"
    )


def _review_context_panel(model: Mapping[str, Any]) -> str:
    ctx = _review_context(model)
    if not ctx:
        return ""
    freshness = _as_mapping(ctx.get("freshness"))
    items = ctx.get("window_items") if isinstance(ctx.get("window_items"), list) else []
    item_labels = []
    for item in items:
        if not isinstance(item, Mapping):
            continue
        role = _review_context_role_label(item.get("role"))
        item_labels.append(f"{item.get('version') or item.get('version_id') or '-'} ({role})")
    overlays = ctx.get("candidate_effective_overlays") if isinstance(ctx.get("candidate_effective_overlays"), list) else []
    compare_label = _review_context_compare_label(ctx, model)
    body = ui.kv_table(
        [
            ("状态", ctx.get("status") or "STANDALONE"),
            ("窗口状态", ctx.get("window_state") or "-"),
            ("目标角色", _review_context_role_label(ctx.get("role_in_window"))),
            ("窗口成员", ", ".join(item_labels) or "-"),
            ("上一有效对象", _display_target_ref(ctx.get("old_label"))),
            ("候选有效版", ctx.get("candidate_effective_id") or "-"),
            ("候选完整基线", ctx.get("candidate_effective_base_full") or "-"),
            ("候选叠加版本", ", ".join(str(item) for item in overlays) or "-"),
            ("对比范围", compare_label),
            ("证据状态", _review_context_freshness_label(ctx)),
            ("窗口文件", ctx.get("window_file") or "-"),
            ("有效版清单", ctx.get("candidate_effective_manifest") or "-"),
            ("对比清单", ctx.get("compare_manifest") or "-"),
            ("对比页面", ctx.get("compare_html") or "-"),
        ]
    )
    checks = ui.metric_grid(
        [
            ("窗口", "存在" if freshness.get("window_exists") else "缺失", "pending_window.json", "PASS" if freshness.get("window_exists") else "WARNING"),
            (
                "有效版",
                "存在" if freshness.get("candidate_manifest_exists") else "缺失",
                "候选有效版清单",
                "PASS" if freshness.get("candidate_manifest_exists") else "WARNING",
            ),
            (
                "对比",
                "存在" if freshness.get("compare_manifest_exists") else "缺失",
                "对比清单/页面",
                "PASS" if freshness.get("compare_manifest_exists") and freshness.get("compare_html_exists") else "WARNING",
            ),
            (
                "扫描",
                "存在" if freshness.get("scan_evidence_exists") else "缺失",
                "目标版本扫描证据",
                "PASS" if freshness.get("scan_evidence_exists") else "WARNING",
            ),
        ]
    )
    warnings = ctx.get("warnings") if isinstance(ctx.get("warnings"), list) else []
    warning_html = ""
    if warnings:
        warning_html = "<div class='quality-note'><b>窗口提示</b><br>" + "<br>".join(ui.esc(item) for item in warnings) + "</div>"
    return ui.collapsible_panel(
        "当前审查窗口 / 有效版证据",
        "版本详情的投影上下文：窗口、候选有效版、对比结果和证据新鲜度只用于解释当前页面是否陈旧。",
        checks + body + warning_html,
        open=True,
    )


def _version_overview_panel(
    out_path: Path,
    safe_lib: str,
    version: Mapping[str, Any],
    model: Mapping[str, Any],
    *,
    scan_dir: Path | None,
) -> str:
    ip_model = _as_mapping(model.get("ip_user_view_model"))
    decision = str(ip_model.get("ip_use_decision") or _usage_decision(model, version))
    review_text = str(ip_model.get("ip_use_label") or ui.status_label(decision))
    file_change_total = (
        _summary_value(model, "added_files")
        + _summary_value(model, "removed_files")
        + _summary_value(model, "changed_files")
    )
    base_status = model.get("base_trust_status") or "WARNING"
    base_label = "已确认" if str(base_status).upper() == "PASS" else "待确认"
    delta_text = ip_model.get("delta_summary") or f"{file_change_total} 个变化"
    top_view_delta = ip_model.get("top_view_delta") or _top_file_type_text(model, limit=2)
    ctx = _review_context(model)
    if _review_context_is_active(ctx):
        object_value = f"{model.get('version_id') or '-'} / {_review_context_role_label(ctx.get('role_in_window'))}"
        compare_value = _review_context_compare_label(ctx, model)
        compare_hint = f"窗口角色={_review_context_role_label(ctx.get('role_in_window'))}"
        evidence_value = _review_context_freshness_label(ctx)
        evidence_hint = "窗口 / 有效版 / 对比 / 扫描证据新鲜度"
    else:
        object_value = f"{model.get('version_id') or '-'} / 独立版本"
        compare_value = f"{base_label}: {_base_context_label(model)}"
        compare_hint = "未命中当前审查窗口时回退普通基准版选择"
        evidence_value = ip_model.get("evidence_summary") or _review_context_freshness_label(ctx)
        evidence_hint = "轻量证据不自动代表不完整"
    overview_items = [
        ("接入判断", review_text, ip_model.get("main_reason") or ui.status_label(decision)),
        ("审查对象", object_value, "版本详情是唯一审查投影"),
        ("对比上下文", compare_value, compare_hint),
        ("视图变化", delta_text, top_view_delta),
        ("证据状态", evidence_value, evidence_hint),
    ]
    overview_cells = "".join(
        "<div class='overview-cell'><b>{label}</b><em title='{value}'>{value}</em><span title='{hint}'>{hint}</span></div>".format(
            label=ui.esc(label),
            value=ui.esc(value),
            hint=ui.esc(hint),
        )
        for label, value, hint in overview_items
    )
    actions = ui.action_strip(
        [
            ui.button("库工作台", common.href(out_path / "libraries" / safe_lib / "index.html"), "primary", target="_blank"),
            ui.button("扫描目录", common.href(scan_dir), "secondary", disabled=not bool(scan_dir), target="_blank"),
        ]
    )
    return (
        "<section class='version-overview'>"
        "<div class='overview-head'>"
        f"<div class='overview-title'><h2>版本使用结论</h2><p>面向 IP 使用者：先判断能否接入，再看视图变化矩阵；管理审计和证据入口默认折叠。</p></div>{ui.badge(decision, review_text)}</div>"
        f"<div class='overview-grid compact-overview-grid'>{overview_cells}</div>"
        f"{_overview_window_context(ctx, model)}"
        f"<div class='overview-actions'>{actions}</div></section>"
    )


def _review_gate_summary_panel(version: Mapping[str, Any]) -> str:
    gate = version.get("review_gate") if isinstance(version.get("review_gate"), Mapping) else {}
    impact, detail, status = _management_gate_user_impact(version)
    blocking = len((gate or {}).get("blocking_items", []) or [])
    attention = len((gate or {}).get("attention_items", []) or [])
    return ui.collapsible_panel(
        "正式放行管理",
        "面向发布负责人的 gate 状态；默认折叠，不作为 IP 使用者主线。",
        ui.metric_grid(
            [
                ("使用影响", impact, detail, status),
                ("管理阻塞", blocking, "需要发布负责人关闭 / 接受 / 豁免", "BLOCKED" if blocking else "PASS"),
                ("管理关注", attention, "建议补充证据", "WARNING" if attention else "PASS"),
            ]
        ),
        open=False,
    )


def _scope_for_file_type(file_type: str) -> str:
    scope = package_view_type(file_type)
    return "未知" if scope == "unknown" else scope


def _view_label(file_type: str) -> str:
    key = canonical_file_type(file_type)
    if key == "unknown":
        return "未知 / 待确认"
    return f"{_scope_for_file_type(key)} / {key}"


def _parser_status_by_file_type(parser_manifest: Mapping[str, Any]) -> dict[str, str]:
    priority = ["FAILED", "PASS_EMPTY", "UNSUPPORTED", "SKIPPED", "METADATA_ONLY", "PASS"]
    found: dict[str, set[str]] = {}
    for file_entry in parser_manifest.get("files", []) or []:
        file_type = canonical_file_type(file_entry.get("file_type"))
        for task in file_entry.get("parser_tasks", []) or []:
            status = str(task.get("result_status") or task.get("status") or "SKIPPED").upper()
            found.setdefault(file_type, set()).add(status)
    out: dict[str, str] = {}
    for file_type, statuses in found.items():
        out[file_type] = next((status for status in priority if status in statuses), sorted(statuses)[0] if statuses else "-")
    return out


def _first_file_for_type(inventory: Mapping[str, Any], file_type: str) -> str:
    wanted = canonical_file_type(file_type)
    for item in inventory.get("files", []) or []:
        if canonical_file_type(item.get("file_type")) == wanted:
            return str(item.get("path") or "-")
    return "-"


def _unknown_kind(path: str) -> str:
    suffixes = [part.lower() for part in Path(path).suffixes if part]
    if suffixes:
        if len(suffixes) >= 2 and suffixes[-1] in {".gz", ".bz2", ".xz", ".zip"}:
            return "".join(suffixes[-2:])
        return suffixes[-1]
    return "无扩展名"


def _unknown_file_breakdown_rows(inventory: Mapping[str, Any]) -> list[str]:
    buckets: dict[str, dict[str, Any]] = {}
    for item in inventory.get("files", []) or []:
        if str(item.get("file_type") or "unknown").lower() != "unknown":
            continue
        path = str(item.get("path") or "-")
        kind = _unknown_kind(path)
        bucket = buckets.setdefault(kind, {"count": 0, "examples": []})
        bucket["count"] += 1
        if len(bucket["examples"]) < 4:
            bucket["examples"].append(path)
    rows: list[str] = []
    for kind, data in sorted(buckets.items(), key=lambda pair: (-int(pair[1]["count"]), pair[0])):
        examples = "<br>".join(f"<code>{ui.esc(path)}</code>" for path in data["examples"])
        rows.append(
            "<tr>"
            f"<td><code>{ui.esc(kind)}</code></td>"
            f"<td>{ui.esc(data['count'])}</td>"
            f"<td>{examples}</td>"
            "<td>补充分类规则、确认是否应纳入 doc/package/flow_config，或标记为可忽略证据。</td>"
            "</tr>"
        )
    return rows


def _unknown_file_breakdown_html(inventory: Mapping[str, Any]) -> str:
    rows = _unknown_file_breakdown_rows(inventory)
    if not rows:
        return ""
    return (
        "<details class='detail-fold review-fold unknown-detail'>"
        "<summary>未知文件细分</summary>"
        "<div class='muted-box'>unknown 不是最终分类；这里按扩展名和无扩展名聚合，方便补规则或人工确认。</div>"
        + catalog._scroll_table(["类型线索", "数量", "代表文件", "审查动作"], rows, "当前没有 unknown 文件", "unknown-detail-scroll")
        + "</details>"
    )


def _required_optional_view_maps(readiness: Mapping[str, Any]) -> tuple[dict[str, Mapping[str, Any]], dict[str, Mapping[str, Any]]]:
    required: dict[str, Mapping[str, Any]] = {}
    optional: dict[str, Mapping[str, Any]] = {}
    for component in readiness.get("components", []) or []:
        if not isinstance(component, Mapping):
            continue
        for view in component.get("required_views", []) or []:
            key = canonical_file_type(view)
            result = (component.get("required_view_results") or {}).get(view) or {}
            required[key] = result if isinstance(result, Mapping) else {}
        for view in component.get("optional_views", []) or []:
            key = canonical_file_type(view)
            result = (component.get("optional_view_results") or {}).get(view) or {}
            optional.setdefault(key, result if isinstance(result, Mapping) else {})
        for view, result in (component.get("required_view_results") or {}).items():
            required[canonical_file_type(view)] = result if isinstance(result, Mapping) else {}
        for view, result in (component.get("optional_view_results") or {}).items():
            optional.setdefault(canonical_file_type(view), result if isinstance(result, Mapping) else {})
    return required, optional


def _view_coverage_rows(
    inventory: Mapping[str, Any],
    parser_manifest: Mapping[str, Any],
    readiness: Mapping[str, Any],
    counts: Mapping[str, int],
) -> list[str]:
    required, optional = _required_optional_view_maps(readiness)
    parser_status = _parser_status_by_file_type(parser_manifest)
    canonical_counts: Counter[str] = Counter()
    for file_type, count in counts.items():
        canonical_counts[canonical_file_type(file_type)] += int(count or 0)
    keys = set(canonical_counts) | set(required) | set(optional)
    view_order = ["verilog", "lef", "liberty", "db", "gds", "oas", "cdl", "sdc", "upf", "cpf", "spef", "sdf", "flow_config", "tech_config", "doc", "waiver", "package", "unknown"]
    rows: list[str] = []
    for file_type in sorted(keys, key=lambda item: (view_order.index(item) if item in view_order else 999, package_view_type(item), item)):
        result = required.get(file_type) or optional.get(file_type) or {}
        requirement = "必需" if file_type in required else "可选" if file_type in optional else "检测到"
        count = int(canonical_counts.get(file_type, 0) or 0)
        found = result.get("found")
        status = str(result.get("status") or ("FOUND" if count else "MISSING")).upper()
        parser = result.get("parser_status") or parser_status.get(file_type) or "-"
        validation = result.get("validation_level") or ("metadata_required" if file_type in SUMMARY_ONLY_TYPES | BINARY_METADATA_ONLY_TYPES else "manual_review" if file_type in {"flow_config", "tech_config"} else "-")
        example = _first_file_for_type(inventory, file_type)
        note = result.get("message")
        if not note:
            if file_type == "unknown":
                note = "需要补充分类规则或人工确认"
            elif file_type in {"flow_config", "tech_config"}:
                note = "流程/技术配置需要人工审查"
            elif found is False and requirement == "必需":
                note = "必需 view 缺失"
            else:
                note = "已纳入交付视图"
        rows.append(
            "<tr>"
            f"<td><b>{ui.esc(_view_label(file_type))}</b></td>"
            f"<td>{ui.badge(requirement, requirement)}</td>"
            f"<td>{ui.esc(count)}</td>"
            f"<td>{ui.badge(status)}</td>"
            f"<td>{ui.esc(parser)}</td>"
            f"<td><code>{ui.esc(validation)}</code></td>"
            f"<td><code>{ui.esc(example)}</code><br><span class='muted'>{ui.esc(note)}</span></td>"
            "</tr>"
        )
    return rows


def _view_coverage_panel(
    inventory: Mapping[str, Any],
    parser_manifest: Mapping[str, Any],
    readiness: Mapping[str, Any],
    counts: Mapping[str, int],
) -> str:
    required, optional = _required_optional_view_maps(readiness)
    canonical_counts: Counter[str] = Counter()
    for file_type, count in counts.items():
        canonical_counts[canonical_file_type(file_type)] += int(count or 0)
    unknown_count = int(canonical_counts.get("unknown", 0) or 0)
    manual_count = int(canonical_counts.get("flow_config", 0) or 0) + int(canonical_counts.get("tech_config", 0) or 0)
    rows = _view_coverage_rows(inventory, parser_manifest, readiness, counts)
    status = readiness.get("required_view_status") or readiness.get("bundle_status") or ("PASS" if rows else "UNKNOWN")
    coverage_judgment = _judgment_strip(
        [
            ("完整性判断", ui.status_label(status), f"release_level={readiness.get('release_level_candidate') or '-'}", status),
            ("必需视图", "已配置" if required else "未配置", ", ".join(sorted(required)) or "未配置", "PASS" if required else "WARNING"),
            ("未知文件", str(unknown_count), "需要补分类或人工确认" if unknown_count else "无未知文件", "WARNING" if unknown_count else "PASS"),
            ("人工审查", str(manual_count), "flow_config / tech_config", "WARNING" if manual_count else "PASS"),
        ]
    )
    return ui.collapsible_panel(
        "必需视图覆盖证据",
        "原始扫描的视图覆盖证据；主判断已汇总到顶部结论和视图变化矩阵。",
        coverage_judgment
        + catalog._scroll_table(
            ["视图 / 范围", "要求", "文件数", "状态", "解析器", "校验级别", "代表路径 / 说明"],
            rows,
            "当前扫描没有可展示的视图覆盖信息",
            "view-coverage-scroll",
        )
        + _unknown_file_breakdown_html(inventory),
        open=False,
    )


def _count_only_panel(counts: Mapping[str, int], corner_summary: Mapping[str, Any], count_only_total: int) -> str:
    empty = ""
    if not count_only_total:
        empty += "<div class='empty-guidance'><b>当前原始扫描没有发现大文件计数项</b>如果这是增量包，基准版/有效版中的 .lib/.db/.gds/.spef 不会在本页重复统计。</div>"
    if not (corner_summary or {}).get("total_corner_files"):
        empty += "<div class='empty-guidance'><b>当前原始扫描没有识别到 PVT Corner 文件名</b>只有文件名中带 PVT 信息的库文件会进入 Corner 汇总。</div>"
    corner_rows = catalog._version_corner_rows(corner_summary and {"corner_filename_summary": corner_summary} or {})
    corner_detail = (
        "<details class='detail-fold review-fold corner-detail'>"
        "<summary>PVT Corner 明细</summary>"
        + catalog._scroll_table(["文件类型", "工艺", "电压", "温度", "路径"], corner_rows, "当前原始扫描没有识别到 PVT Corner 文件名", "corner-detail-scroll")
        + "</details>"
    )
    return ui.collapsible_panel(
        "大文件与 Corner 线索",
        "Liberty、SPEF、DB、GDS、Verilog 等大/多文件默认用数量、路径、哈希和 PVT 文件名线索辅助判断。",
        "<div class='quality-note'><b>默认策略</b> GDS/Liberty/SPEF/DB/OAS/Verilog 等大文件默认只看数量、路径、哈希和文件名 corner 线索。</div>"
        + empty
        + ui.faceted_table(
            "count-only-files",
            ["文件类型", "数量", "默认处理"],
            catalog._version_count_only_rows(counts),
            "当前原始扫描没有发现大文件计数项",
            "搜索大文件类型 / 处理方式",
            [(0, "文件类型"), (2, "默认处理")],
        )
        + corner_detail,
        open=False,
    )


def _parser_panel(parser_manifest: Mapping[str, Any], parser_results: Mapping[str, Any]) -> str:
    rows = catalog._version_parser_aggregate_rows(parser_manifest, parser_results)
    empty = ""
    if not rows:
        empty = "<div class='empty-guidance'><b>当前扫描没有生成可展示的解析器结果</b>常见原因：本次 raw 包只包含文档/脚本，或相关文件类型没有解析器任务。</div>"
    return ui.collapsible_panel(
        "解析证据",
        "按文件类型聚合解析器结果；代表对象和来源文件作为追溯证据折叠展示。",
        empty
        + ui.faceted_table(
            "parser-aggregate",
            ["解析器", "状态", "文件数", "任务状态", "聚合摘要", "来源"],
            rows,
            "当前扫描没有生成可展示的解析器结果",
            "搜索解析器 / 对象 / 来源文件",
            [(0, "解析器"), (1, "状态"), (3, "任务状态")],
        ),
    )


def _quality_panel(
    parser_task_count: int,
    file_total: int,
    model: Mapping[str, Any],
    version: Mapping[str, Any],
    scan_dir: Path | None,
) -> str:
    evidence_label, evidence_detail, _ = _evidence_judgment(model)
    diff_status = model.get("status") or "UNKNOWN"
    rn_count = len(model.get("release_notes", []) or [])
    scan_id = (version.get("scan") or {}).get("scan_id") or version.get("scan_id") or "-"
    evidence_rows = [
        ("scan_id", scan_id),
        ("扫描目录", scan_dir or "-"),
        ("绝对原始路径", version.get("raw_path") or "-"),
        ("文件清单", f"{file_total} files"),
        ("解析器任务", f"{parser_task_count} 个"),
        ("对比状态", ui.status_label(diff_status)),
        ("发布说明", f"{rn_count} 个"),
        ("证据分层", f"{evidence_label} - {evidence_detail}"),
    ]
    evidence_context = "<div class='context-list'>" + "".join(
        f"<div class='context-row'><b>{ui.esc(label)}</b><em>{ui.esc(value)}</em></div>" for label, value in evidence_rows
    ) + "</div>"
    trace_links = ui.trace_link_list(
        [
            ("scan_dir", common.href(scan_dir), "原始扫描输出目录"),
            ("file_inventory.json", common.href(scan_dir / "file_inventory.json") if scan_dir else "", "文件清单来源"),
            ("parser_manifest.json", common.href(scan_dir / "parser_manifest.json") if scan_dir else "", "解析器任务清单"),
            ("parser_results.json", common.href(scan_dir / "parser_results.json") if scan_dir else "", "解析器结果数据"),
        ]
    )
    return ui.collapsible_panel(
        "证据入口 / 调试",
        "追溯扫描、解析器、对比和原始路径；这些是证据入口，不作为 IP 使用者主屏结论。",
        trace_links + evidence_context,
        open=False,
    )


def _audit_evidence_panel(model: Mapping[str, Any]) -> str:
    body = (
        "<div class='evidence-detail-stack'>"
        "<details><summary>原始 JSON 链接</summary>"
        "<div class='quality-note'><b>减噪策略</b> 主页面只保留摘要和入口；完整 JSON 不再内嵌，避免浏览器搜索被 debug 数据污染。</div>"
        + _evidence_artifact_links(model)
        + "</details>"
        "<details><summary>完整对比指标</summary>"
        + catalog._scroll_table(["指标", "数值"], _metric_rows(model), "暂无自动对比结果；下一步运行 lg cmp 或 lg lib-diff。", "metric-scroll")
        + "</details>"
        "<details><summary>完整变化文件入口</summary>"
        "<div class='quality-note'><b>减噪策略</b> 完整逐文件变化不再内嵌到详情页；请打开 file_diff.json 查看全量清单。主页面仅保留重点变化文件。</div>"
        + catalog._scroll_table(
            ["范围", "数量", "说明"],
            _file_change_artifact_rows(model),
            "暂无文件级 diff 摘要。请先运行 lg cmp 或 lg lib-diff。",
            "change-summary-scroll",
        )
        + "</details>"
        "<details><summary>摘要级 / 元数据级证据摘要</summary>"
        + "<div class='quality-note'><b>证据分层</b> 摘要级证据（Summary-only）/ 元数据级证据（Metadata-only）是正常证据策略，不自动代表不完整；这里按类型聚合，完整文件列表见 file_diff.json。</div>"
        + "<h3>摘要级证据按类型汇总</h3>"
        + catalog._scroll_table(
            ["文件类型", "数量", "代表文件", "证据"],
            _summary_only_summary_rows(model),
            "暂无摘要级审查项。",
            "summary-only-scroll",
        )
        + "<h3>元数据级证据按类型汇总</h3>"
        + catalog._scroll_table(
            ["文件类型", "数量", "代表文件", "证据"],
            _metadata_only_summary_rows(model),
            "暂无元数据级审查项。",
            "metadata-only-scroll",
        )
        + "</details>"
        "<details><summary>发布说明与结构变化证据</summary>"
        + "<h3>发布说明</h3>"
        + ui.faceted_table(
            "release-note-table",
            ["发布说明", "摘要"],
            _release_note_rows(model),
            "暂无发布说明 / changelog 摘要",
            "搜索 release note / changelog",
            [(0, "文件")],
        )
        + "<h3>结构变化摘要</h3>"
        + catalog._scroll_table(
            ["证据", "摘要"],
            _evidence_json_summary_rows(model),
            "暂无结构变化证据。",
            "evidence-json-summary-scroll",
        )
        + "</details>"
        "<details><summary>对比问题 / 建议动作</summary>"
        + "<h3>对比问题</h3>"
        + ui.faceted_table(
            "diff-issue-table",
            ["级别", "类别", "问题"],
            _diff_issue_rows(model),
            "暂无 diff_issues.json 问题。",
            "搜索 issue / category / severity",
            [(0, "级别"), (1, "类别")],
        )
        + "<h3>建议动作</h3>"
        + ui.faceted_table(
            "recommended-action-table",
            ["建议动作"],
            _recommended_action_rows(model),
            "暂无建议动作",
            "搜索建议动作",
        )
        + "</details>"
        "</div>"
    )
    return ui.collapsible_panel(
        "审计证据",
        "完整指标、完整变化文件入口、摘要级/元数据级证据、发布证据和对比问题默认折叠，供发布负责人追溯。",
        body,
        open=False,
    )


def render_version_update_detail_panel(model: Mapping[str, Any]) -> str:
    base_version = model.get("base_version") or "-"
    base_ref = model.get("base_ref") or "NEEDS_BASE_CONFIRM"
    review_model = _as_mapping(model.get("version_review_model")) or build_version_review_model(model)
    ip_model = _as_mapping(model.get("ip_user_view_model")) or _as_mapping(review_model.get("ip_user_view"))
    lead = (
        "<div class='version-update-lead'>"
        f"<b>本次变化一句话</b>"
        f"<p>{ui.esc(model.get('headline') or '-')}</p>"
        f"<p>{ui.esc(model.get('confidence_note') or '-')}</p>"
        "</div>"
    )
    callouts = _review_brief_callouts(model)
    focus_changes = (
        "<details class='detail-fold review-fold'>"
        "<summary>变化文件明细（按需展开）</summary>"
        "<div class='quality-note'><b>显示范围</b> 默认不把完整文件清单作为 IP 使用者主线；这里只显示 P0/P1/审查重点变化，最多 120 行。</div>"
        + catalog._scroll_table(
            ["变化", "类型", "路径", "审查级别", "匹配状态", "基准候选", "目标文件", "建议"],
            _focus_file_change_rows(model),
            "暂无重点变化文件；可打开 file_diff.json 查看全量变化。",
            "focus-change-scroll",
        )
        + "</details>"
    )
    return ui.panel(
        f"视图变化矩阵（vs {_cn_base_ref(base_ref)} / {base_version}）",
        "默认面向 IP 使用者：按视图聚合新增、删除、修改和证据等级；调试证据只保留在 JSON/扫描报告中。",
        lead + callouts + render_ip_user_view(ip_model) + focus_changes,
    )

def export_current_lib_diff_markdown(model: Mapping[str, Any], out_md: str | Path) -> str:
    path = Path(out_md)
    path.parent.mkdir(parents=True, exist_ok=True)
    primary_next_action = _as_mapping(model.get("primary_next_action"))
    comparison_context = _as_mapping(model.get("comparison_context"))
    scan_context = _as_mapping(model.get("scan_context"))
    scan_compatibility = _as_mapping(model.get("scan_compatibility"))
    lines = [
        "---",
        "schema_version: version_update_detail.v1",
        "source_model: version_update_detail_model",
        f"library: {model.get('library_name') or model.get('library_id') or '-'}",
        f"version: {model.get('version_id') or '-'}",
        f"base_ref: {model.get('base_ref') or '-'}",
        f"base_version: {model.get('base_version') or '-'}",
        f"comparison_semantics: {model.get('comparison_semantics') or '-'}",
        f"delete_semantics: {model.get('delete_semantics') or '-'}",
        f"status: {model.get('status') or '-'}",
        f"usage_decision: {model.get('usage_decision') or '-'}",
        "usage_decision_reasons: " + ", ".join(str(item) for item in model.get("usage_decision_reasons", []) or []),
        f"changed_files: {_as_int(model.get('changed_files'))}",
        f"recommended_file_diff: {len(model.get('recommended_file_diff', []) or [])}",
        f"summary_only_reviewed: {len(model.get('summary_only_reviewed', []) or [])}",
        f"metadata_only_reviewed: {len(model.get('metadata_only_reviewed', []) or [])}",
        "---",
        "",
        "# Current Library Diff",
        "",
        f"{model.get('headline') or '-'}",
        "",
        f"{model.get('confidence_note') or '-'}",
        "",
        "## Reviewer Context",
        "",
        f"- primary_next_action: {primary_next_action.get('kind') or 'review_evidence'}",
        f"- primary_next_action_label: {primary_next_action.get('label') or '审查证据'}",
        f"- command_count: {primary_next_action.get('command_count') or 0}",
        f"- base_trust_status: {model.get('base_trust_status') or '-'}",
        f"- base_trust_note: {model.get('base_trust_note') or '-'}",
        f"- status_message: {model.get('status_message') or _update_status_message(model.get('status'))}",
        f"- usage_decision: {model.get('usage_decision') or '-'}",
        "- usage_decision_reasons: " + ", ".join(str(item) for item in model.get("usage_decision_reasons", []) or []),
        "",
        "## Compare Context",
        "",
        f"- strategy: {model.get('compare_strategy') or '-'}",
        f"- base: {model.get('base_ref') or '-'} / {model.get('base_version') or '-'}",
        f"- target: {model.get('target_version') or model.get('version_id') or '-'}",
        f"- diff_dir: {comparison_context.get('diff_dir') or '-'}",
        f"- old_scan_id: {comparison_context.get('old_scan_id') or '-'}",
        f"- new_scan_id: {comparison_context.get('new_scan_id') or '-'}",
        f"- scan_compatibility: {scan_compatibility.get('status') or '-'}",
        f"- target_scan_id: {scan_context.get('scan_id') or '-'}",
        "",
        "## Summary Metrics",
        "",
    ]
    for item in model.get("summary_metrics", []) or []:
        if isinstance(item, Mapping):
            lines.append(f"- {item.get('metric')}: {item.get('value')}")
    lines.extend(["", "## File Changes", ""])
    for item in model.get("file_changes", []) or []:
        if isinstance(item, Mapping):
            lines.append(f"- [{item.get('review_lane')}] {item.get('change')} {item.get('file_type')} {item.get('path')}")
    lines.extend(["", "## Focused File Review", ""])
    for item in model.get("recommended_file_diff", []) or []:
        if isinstance(item, Mapping):
            lines.append(f"- [{item.get('review_lane')}] {item.get('change')} {item.get('file_type')} {item.get('path')}")
    lines.extend(["", "## Summary-only Reviewed", ""])
    for item in model.get("summary_only_reviewed", []) or []:
        if isinstance(item, Mapping):
            lines.append(f"- [{item.get('review_lane')}] {item.get('change')} {item.get('file_type')} {item.get('path')} - {item.get('hint')}")
    lines.extend(["", "## Metadata-only Reviewed", ""])
    for item in model.get("metadata_only_reviewed", []) or []:
        if isinstance(item, Mapping):
            lines.append(f"- [{item.get('review_lane')}] {item.get('change')} {item.get('file_type')} {item.get('path')} - {item.get('hint')}")
    lines.extend(["", "## View Diff", ""])
    view_diff = _as_mapping(model.get("view_diff"))
    for item in view_diff.get("views", []) or []:
        if isinstance(item, Mapping):
            lines.append(f"- {item.get('view') or item.get('file_type')}: {item.get('status')}")
    if not view_diff.get("views"):
        lines.append(f"- summary: {view_diff.get('summary') or {}}")
    lines.extend(["", "## Type Diff", ""])
    type_diff = _as_mapping(model.get("type_diff"))
    for file_type, item in (_as_mapping(type_diff.get("by_type"))).items():
        if isinstance(item, Mapping):
            lines.append(f"- {file_type}: {item.get('status')} changed={item.get('changed_count', 0)} added={item.get('added_count', 0)} removed={item.get('removed_count', 0)}")
    if not type_diff.get("by_type"):
        lines.append(f"- summary: {type_diff.get('summary') or {}}")
    lines.extend(["", "## Release Readiness Diff", ""])
    lines.append(f"- {model.get('release_readiness_diff') or {}}")
    lines.extend(["", "## Diff Issues", ""])
    for item in (_as_mapping(model.get("diff_issues"))).get("issues", []) or []:
        if isinstance(item, Mapping):
            lines.append(f"- {item.get('severity', '-')}: {item.get('category', '-')} - {item.get('title') or item.get('message') or '-'}")
    lines.extend(["", "## Recommended Actions", ""])
    for action in model.get("recommended_actions", []) or []:
        lines.append(f"- {action}")
    if model.get("release_notes"):
        lines.extend(["", "## Release Notes", ""])
        for item in model.get("release_notes", []) or []:
            if isinstance(item, Mapping):
                lines.append(f"- {item.get('path')}: {item.get('summary')}")
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return str(path)


def render_version_detail_page(out: str | Path, lib: Mapping[str, Any], version: Mapping[str, Any], *, export_markdown: bool = False) -> str:
    out_path = Path(out)
    lib_id = _library_id(lib)
    version_id = _version_id(version)
    safe_lib = _library_report_slug(lib)
    safe_ver = common.safe(version_id)
    page = out_path / "libraries" / safe_lib / "versions" / safe_ver / "index.html"
    tags = catalog._version_tags(version)
    model = build_version_update_detail_model(out_path, lib, version)
    md_path = page.parent / "current_lib_diff.md"
    model["markdown_export_path"] = str(md_path)
    if export_markdown:
        export_current_lib_diff_markdown(model, md_path)
    scan_context = _as_mapping(model.get("scan_context"))
    scan_dir_text = str(scan_context.get("scan_dir") or "")
    scan_dir = Path(scan_dir_text) if scan_dir_text else None
    body = (
        _version_detail_styles()
        + _version_overview_panel(
            out_path,
            safe_lib,
            version,
            model,
            scan_dir=scan_dir,
        )
        + "<main class='version-main'>"
        + render_version_update_detail_panel(model)
        + "</main>"
    )
    ip_model = _as_mapping(model.get("ip_user_view_model"))
    usage_decision = str(ip_model.get("ip_use_decision") or _usage_decision(model, version))
    html = ui.review_page_shell(
        f"{lib.get('display_name') or lib_id} / {version_id}",
        "版本审查",
        "面向 IP 使用者展示基准对比、视图变化、证据等级和使用场景影响。",
        catalog_browser_styles() + body,
        decision=usage_decision,
        nav="<a href='../../../index.html'>目录</a><a class='active' href='#'>版本详情</a><a href='../index.html'>库工作台</a>",
        meta=ui.compact_meta([("库", lib_id), ("版本", version_id), ("基准版", model.get("base_version") or "-")]),
    )
    common.write_text(page, html)
    return str(page)
