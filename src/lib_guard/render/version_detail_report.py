"""Version detail report renderer.

This module owns the version detail surface and the current-library update
detail model. The Markdown export is evidence generated from the same model as
the HTML panel; the HTML renderer never reads Markdown.
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Mapping

from lib_guard.diff.file_match import default_path_match_evidence, path_match_evidence as build_path_match_evidence
from lib_guard.project_config import BINARY_METADATA_ONLY_TYPES, DEFAULT_FILE_DIFF_TYPES, SUMMARY_ONLY_TYPES
from lib_guard.review.io import read_json
from lib_guard.review.evidence_state import build_version_evidence_state
from lib_guard.review.model_rules import (
    classify_review_lane,
    comparison_semantics_for_package,
    resolve_review_base,
)
from lib_guard.review.update_notes import load_update_note, note_is_available, review_notes_root
from lib_guard.scan.report import load_parser_results
from lib_guard.render.catalog_workspace_report import catalog_browser_styles
from lib_guard.render import catalog_render_common as common
from lib_guard.render import catalog_report as catalog
from lib_guard.render import product_theme as ui
from lib_guard.render.version_detail_context import build_version_detail_review_context
from lib_guard.render.version_file_evidence import render_version_file_evidence_section
from lib_guard.render.version_review_model import build_version_review_model, build_ip_change_projection
from lib_guard.render.version_review_render import render_ip_user_view, render_review_report
from lib_guard.view_types import canonical_file_type, canonical_view_type, package_view_type, view_label


STANDARD_BASE_REFS = {"current_effective", "previous_effective", "explicit", "review_window"}
FALLBACK_BASE_REFS = {"adjacent_fallback", "recorded_base", "recorded_base_fallback", "unknown"}
UPDATE_STATUS_COPY = {
    "DIFF_NOT_RUN": "尚未生成版本对比，不能据此判断无变化；请向报告提供者确认。",
    "NEEDS_BASE_CONFIRM": "无法确定基准版；请先确认当前有效版或上一有效版。",
    "FIRST_VERSION_REVIEW": "当前无可比基准版；按首版/单版本交付内容审查。",
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
        return "修改"
    if text == 'unmatched_new':
        return '本版待核对'
    if text == 'unmatched_base':
        return '基准版待核对'
    return text or "-"


def _cn_review_lane(value: Any) -> str:
    text = str(value or "").strip()
    return {
        "Review": "审查",
        "Summary-only": "摘要级证据",
        "Metadata-only": "元数据级证据",
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
        "summary-only": "摘要级证据",
        "metadata-only": "元数据级证据",
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


def _iter_path_changes_same_content(
    file_diff: Mapping[str, Any],
    *,
    raw_path: Any = None,
) -> list[dict[str, Any]]:
    """Project confirmed path changes without treating them as content edits."""

    changes: list[dict[str, Any]] = []
    for source in file_diff.get("renamed_or_moved", []) or []:
        if not isinstance(source, Mapping):
            continue
        old_path = common.relative_display_path(
            source.get("old_logical_path") or source.get("old") or "-",
            base=raw_path,
        )
        new_path = common.relative_display_path(
            source.get("new_logical_path") or source.get("new") or "-",
            base=raw_path,
        )
        file_type = _infer_file_type(new_path, source.get("file_type") or source.get("type"))
        changes.append(
            {
                "change": "path_changed_same_content",
                "file_type": file_type,
                "path": new_path,
                "old": old_path,
                "new": new_path,
                "reason": str(source.get("reason") or "confirmed_same_content"),
                "content_hash": str(source.get("hash") or ""),
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
    return UPDATE_STATUS_COPY.get(key, f"更新详情状态：{ui.status_label(key) if key else '待确认'}。")


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
    return load_parser_results(scan_dir) if scan_dir else {}


def _build_scan_evidence_model(version: Mapping[str, Any]) -> dict[str, Any]:
    scan_dir = _version_scan_dir(version)
    scan_meta = read_json(scan_dir / "scan_meta.json", default={}) if scan_dir else {}
    inventory = _scan_inventory(scan_dir)
    parser_manifest = _scan_parser_manifest(scan_dir)
    parser_results = _scan_parser_results(scan_dir)
    release_readiness = read_json(scan_dir / "summary" / "release_readiness.json", default={}) if scan_dir else {}
    counts = _as_mapping(inventory.get("file_type_counts"))
    if not counts and scan_dir:
        scan_summary = read_json(scan_dir / "scan_summary.json", default={})
        counts = _as_mapping(scan_summary.get("file_type_counts"))
    if not counts and scan_dir:
        manifest = read_json(scan_dir / "manifest.json", default={})
        counts = _as_mapping(manifest.get("file_type_counts"))
    if not counts:
        inferred: Counter[str] = Counter()
        files = inventory.get("files", []) or []
        if isinstance(files, list):
            for item in files:
                if isinstance(item, Mapping):
                    inferred[canonical_file_type(item.get("file_type"))] += 1
        counts = dict(inferred)
    parser_task_count = sum(
        1
        for file_entry in (parser_manifest.get("files", []) or [])
        for task in (file_entry.get("parser_tasks", []) or [])
        if task.get("parser_name")
    )
    file_total = sum(_as_int(v) for v in counts.values())
    scan = _as_mapping(version.get("scan"))
    review_dir = scan_dir / "review" if scan_dir else None
    review_links = {}
    if review_dir:
        for key, name in {
            "files_by_view": "files_by_view.tsv",
            "unknown_files": "unknown_files.tsv",
            "view_coverage": "view_coverage.tsv",
        }.items():
            path = review_dir / name
            if path.exists() and path.is_file():
                review_links[key] = str(path)
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
        "review_links": review_links,
        "required_view_status": release_readiness.get("required_view_status") or release_readiness.get("bundle_status"),
    }


def _scan_evidence_has_files(scan_evidence: Mapping[str, Any]) -> bool:
    if _as_int(scan_evidence.get("file_total")):
        return True
    counts = _as_mapping(scan_evidence.get("counts"))
    if any(_as_int(value) for value in counts.values()):
        return True
    inventory = _as_mapping(scan_evidence.get("inventory"))
    files = inventory.get("files", []) or []
    return isinstance(files, list) and bool(files)


def _scan_evidence_file_total(scan_evidence: Mapping[str, Any]) -> int:
    if _as_int(scan_evidence.get("file_total")):
        return _as_int(scan_evidence.get("file_total"))
    counts = _as_mapping(scan_evidence.get("counts"))
    total = sum(_as_int(value) for value in counts.values())
    if total:
        return total
    inventory = _as_mapping(scan_evidence.get("inventory"))
    files = inventory.get("files", []) or []
    return len(files) if isinstance(files, list) else 0


def _scan_evidence_unknown_total(scan_evidence: Mapping[str, Any]) -> int:
    if _as_int(scan_evidence.get("unknown_count")):
        return _as_int(scan_evidence.get("unknown_count"))
    counts = _as_mapping(scan_evidence.get("counts"))
    if _as_int(counts.get("unknown")):
        return _as_int(counts.get("unknown"))
    inventory = _as_mapping(scan_evidence.get("inventory"))
    files = inventory.get("files", []) or []
    if not isinstance(files, list):
        return 0
    return sum(1 for item in files if isinstance(item, Mapping) and canonical_file_type(item.get("file_type")) == "unknown")


def _is_partial_update(version: Mapping[str, Any]) -> bool:
    pkg = common.package_type(version)
    if pkg == "FULL_PACKAGE":
        return False
    if pkg in {"PARTIAL_UPDATE", "HOTFIX", "DOC_UPDATE", "DOC_ONLY"}:
        return True
    if common.truthy(version.get("base_required")):
        return True
    return bool(version.get("update_scope"))


def _is_first_version_review(version: Mapping[str, Any], *, base_ref: str, scan_evidence: Mapping[str, Any]) -> bool:
    if base_ref != "NEEDS_BASE_CONFIRM":
        return False
    if _is_partial_update(version):
        return False
    if not _scan_evidence_has_files(scan_evidence):
        return False
    pkg = common.package_type(version)
    return bool(common.truthy(version.get("standalone")) or pkg == "FULL_PACKAGE")


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


def _package_root_unmatched_counts(file_diff: Mapping[str, Any], path_restructure: Mapping[str, Any]) -> dict[str, int]:
    """Return files that sit under a migrated package root but lack an old/new mate.

    These are not proven content additions or deletions.  They are review facts:
    the new side has files the current base evidence cannot match, or vice
    versa.  Keeping this bucket separate prevents package wrapper changes from
    being read as true add/remove churn.
    """

    counts = _as_mapping(file_diff.get("counts"))
    added = _as_int(counts.get("unmatched_added_under_package_root"))
    removed = _as_int(counts.get("unmatched_removed_under_package_root"))
    if file_diff.get('inventory_coverage'):
        return {'new': added, 'base': removed}
    if added or removed:
        return {"new": added, "base": removed}
    if not path_restructure.get("suspected"):
        return {"new": 0, "base": 0}

    new_root = str(path_restructure.get("new_root") or "")
    old_root = str(path_restructure.get("old_root") or "")

    def under_root(path: Any, root: str) -> bool:
        text = str(path or "").strip("/")
        return bool(root) and text.startswith(root.strip("/") + "/")

    added_items = _path_items(file_diff.get("added"))
    removed_items = _path_items(file_diff.get("removed"))
    return {
        "new": sum(1 for path in added_items if under_root(path, new_root)),
        "base": sum(1 for path in removed_items if under_root(path, old_root)),
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


def _version_update_headline(
    base_ref: str,
    added_files: int,
    removed_files: int,
    changed_files: int,
    recommended_count: int,
    reviewed_count: int,
    path_changed_same_content: int = 0,
    unmatched_new_files: int = 0,
    unmatched_base_files: int = 0,
) -> str:
    true_added = max(0, added_files - unmatched_new_files)
    true_removed = max(0, removed_files - unmatched_base_files)
    delta_parts = [f"修改文件 {changed_files} 个"]
    if unmatched_new_files or unmatched_base_files:
        delta_parts.append(f"真实新增 {true_added} 个")
        delta_parts.append(f"真实删除 {true_removed} 个")
        if unmatched_new_files:
            delta_parts.append(f"未匹配新侧 {unmatched_new_files} 个")
        if unmatched_base_files:
            delta_parts.append(f"未匹配基准侧 {unmatched_base_files} 个")
    else:
        delta_parts.append(f"新增 {added_files} 个")
        delta_parts.append(f"删除 {removed_files} 个")
    path_copy = (
        f"路径变化且内容相同 {path_changed_same_content} 个；"
        if path_changed_same_content
        else ""
    )
    return (
        f"当前版本相对 {_cn_base_ref(base_ref)}：{'，'.join(delta_parts)}；"
        f"{path_copy}"
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


_IP_USAGE_IGNORED_GATE_CATEGORIES = {"release", "metadata", "metadata_only"}


def _ip_usage_gate_blocking_items(review_gate: Mapping[str, Any] | None) -> list[Mapping[str, Any]]:
    """Keep formal-release blockers out of the IP usage decision.

    The review gate is also consumed by release checking, so its blocking list
    can contain administrative release evidence and metadata-only acceptance
    tasks. Those are valid release concerns, but neither proves that the IP is
    technically unusable. Unknown categories remain conservative and continue
    to affect the usage decision.
    """

    gate = review_gate if isinstance(review_gate, Mapping) else {}
    result: list[Mapping[str, Any]] = []
    for item in gate.get("blocking_items", []) or []:
        if not isinstance(item, Mapping):
            continue
        category = str(item.get("category") or "").strip().lower()
        if category in _IP_USAGE_IGNORED_GATE_CATEGORIES:
            continue
        result.append(item)
    return result


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
    blocking = len(_ip_usage_gate_blocking_items(gate))

    if status_key == "FIRST_VERSION_REVIEW":
        reasons.append("first_version_review")
        if blocking:
            reasons.append("review_gate_blocking")
            return "BLOCKED", reasons
        return "USAGE_REVIEW_REQUIRED", reasons
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
    render_output = out_path / "libraries" / safe_lib / "versions" / safe_ver / "index.html"
    evidence_state = build_version_evidence_state(
        library=lib,
        version=version,
        review_context=review_context,
        render_output=render_output,
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
    evidence_semantics = str(summary.get("comparison_semantics") or "")
    if evidence_semantics in {"overlay", "needs_package_confirmation"}:
        comparison_semantics = evidence_semantics
    file_diff = dict(common.version_file_diff(diff_dir))
    view_diff = dict(common.version_diff_json(diff_dir, "view_diff.json"))
    type_diff = dict(common.version_diff_json(diff_dir, "type_diff.json"))
    release_readiness_diff = dict(common.version_diff_json(diff_dir, "release_readiness_diff.json"))
    release_evidence_diff = dict(common.version_diff_json(diff_dir, "release_evidence_diff.json"))
    diff_issues = dict(common.version_diff_json(diff_dir, "diff_issues.json"))
    file_changes = _iter_file_changes(file_diff, raw_path=version.get("raw_path"))
    path_changes_same_content = _iter_path_changes_same_content(file_diff, raw_path=version.get("raw_path"))
    path_match_evidence = build_path_match_evidence(file_diff, raw_path=version.get("raw_path"))
    for item in file_changes:
        path = str(item.get("path") or "")
        change = str(item.get("change") or "")
        item.update(path_match_evidence.get(path) or default_path_match_evidence(change, path))
    from lib_guard.review.publication import load_current_file_checks, load_semantic_projection
    from lib_guard.review.engineering import build_engineering_report, file_check_alignment
    notes_root = review_notes_root(catalog_html_out=out_path)
    evidence_library = str(lib.get('library_id') or lib_id)
    selected_checks = load_current_file_checks(notes_root, evidence_library, version_id)
    semantic_check = load_semantic_projection(notes_root, evidence_library, version_id)
    if evidence_library != lib_id:
        selected_checks = selected_checks or load_current_file_checks(notes_root, lib_id, version_id)
        semantic_check = semantic_check or load_semantic_projection(notes_root, lib_id, version_id)
    scan_evidence = _build_scan_evidence_model(version)
    source_roots = {
        'current': str(version.get('raw_path') or ''),
        'base': next((str(row.get('raw_path') or '') for row in lib.get('versions', []) or []
                      if isinstance(row, Mapping) and row.get('version_id') == base_version), ''),
    }
    evidence_conflicts, confirmed_unchanged = [], []
    inventory_cache = {}
    logical_pairs = {
        (str(item.get('old') or ''), str(item.get('new') or '')): str(item.get('logical_path') or '')
        for item in file_diff.get('logical_path_changes', [])
        if isinstance(item, Mapping)
    }
    for check in selected_checks:
        if not source_roots['base'] and check.get('base_version') == base_version:
            source_roots['base'] = str(check.get('base_raw_path') or '')
        check['report_alignment'] = file_check_alignment({
            'base_version': base_version, 'source_roots': source_roots,
            'diff_meta': diff_meta, 'scan_evidence': scan_evidence,
        }, check, inventory_cache)
        if check.get('source_content_status') != 'SAME' or check.get('freshness') != '文件状态未改变':
            continue
        old_file = Path(str(check.get('old_file') or '')).resolve()
        base_roots = [Path(str(item.get('raw_path'))).resolve() for item in lib.get('versions', []) or []
                      if isinstance(item, Mapping) and item.get('version_id') == base_version and item.get('raw_path')]
        if not base_roots and check.get('base_raw_path'):
            base_roots = [Path(str(check['base_raw_path'])).resolve()]
        base_matches = check.get('base_version') == base_version and any(
            old_file.is_relative_to(root) for root in base_roots
        )
        if not base_matches:
            continue
        current_root = Path(str(version.get('raw_path') or '')).resolve()
        new_file = Path(str(check.get('new_file') or '')).resolve()
        if not new_file.is_relative_to(current_root):
            continue
        old_root = next((root for root in base_roots if old_file.is_relative_to(root)), None)
        old_relative = old_file.relative_to(old_root).as_posix() if old_root else ''
        new_relative = new_file.relative_to(current_root).as_posix()
        relative = logical_pairs.get((old_relative, new_relative), new_relative)
        for item in file_changes:
            if item.get('path') == relative and item.get('change') == 'changed':
                evidence_conflicts.append(relative)
                hashes = check.get('content_sha256') or {}
                if (check['report_alignment'] == 'ALIGNED' and len(str(hashes.get('old') or '')) == 64
                        and hashes.get('old') == hashes.get('new')):
                    item['change'] = 'confirmed_same'
                    confirmed_unchanged.append(relative)
    file_changes = [item for item in file_changes if item.get('change') != 'confirmed_same']
    added_files = _as_int(summary.get("added_files", _as_mapping(file_diff.get("counts")).get("added")))
    removed_files = _as_int(summary.get("removed_files", _as_mapping(file_diff.get("counts")).get("removed")))
    changed_files = summary.get("changed_files")
    if changed_files is None:
        changed_files = sum(
            1
            for item in file_changes
            if str(item.get("change") or "").upper() in {"CHANGED", "MODIFIED"}
        )
    else:
        changed_files = max(0, _as_int(changed_files) - len(confirmed_unchanged))
    path_restructure = _path_restructure_summary(file_diff, summary)
    first_version_review = _is_first_version_review(version, base_ref=base_ref, scan_evidence=scan_evidence)
    summary_status = str(summary.get("status") or "").upper()
    if first_version_review:
        status = "FIRST_VERSION_REVIEW"
    elif base_ref == "NEEDS_BASE_CONFIRM":
        status = "NEEDS_BASE_CONFIRM"
    elif diff_dir and not summary:
        status = "NO_DIFF_SUMMARY"
    elif not summary and not diff_dir:
        status = "DIFF_NOT_RUN"
    elif summary_status in {"DIFF", "CHANGED"} or _as_int(changed_files):
        status = "CHANGED"
    else:
        status = summary_status or "SAME"
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
    package_root_unmatched = _package_root_unmatched_counts(file_diff, path_restructure)
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
    base_trust_status = "INFO" if first_version_review else _base_trust_status(base_ref)
    usage_decision, usage_reasons = _usage_decision_result(
        status=status,
        base_trust_status=base_trust_status,
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
        "diff_report": str(diff_dir / "diff_html" / "index.html") if diff_dir and (diff_dir / "diff_html" / "index.html").exists() else "",
        "markdown_export": str(md_path),
    }
    update_note = load_update_note(review_notes_root(catalog_html_out=out_path), lib_id, version_id)
    from lib_guard.scan.artifacts import build_lib_db_correspondence
    scan_inventory = _as_mapping(scan_evidence.get('inventory'))
    model = {
        "schema_version": "version_update_detail.v1",
        "library_id": lib_id,
        "formal_library_id": lib_id,
        "typed_library_id": lib.get("typed_library_id") or lib.get("library_id"),
        "report_slug": safe_lib,
        "library_name": _library_name(lib),
        "version_id": version_id,
        "target_version": version_id,
        "source_roots": source_roots,
        "base_ref": base_ref,
        "base_version": base_version,
        "base_source": base_source,
        "base_trust_status": base_trust_status,
        "base_trust_note": "当前无可比基准版；按首版/单版本交付内容审查。" if first_version_review else _base_trust_note(base_ref),
        "review_mode": "first_version" if first_version_review else ("blocked_base" if base_ref == "NEEDS_BASE_CONFIRM" else "baseline"),
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
        "candidate_effective_inventory": {
            "file_count": _as_int(review_context.get("candidate_effective_file_count")),
            "file_type_counts": dict(_as_mapping(review_context.get("candidate_effective_file_type_counts"))),
            "manifest": str(review_context.get("candidate_effective_manifest") or ""),
        },
        "evidence_state": evidence_state,
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
        "path_changes_same_content": path_changes_same_content,
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
        "package_root_unmatched": package_root_unmatched,
        "trace_links": trace_links,
        "update_note": update_note,
        "representative_files": selected_checks,
        "evidence_conflicts": evidence_conflicts,
        "confirmed_unchanged_files": confirmed_unchanged,
        "semantic_check": semantic_check,
        "lib_db_correspondence": build_lib_db_correspondence(scan_inventory.get('files', []), scan_inventory.get('root_path') or version.get('raw_path') or ''),
        "render_context": {
            "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "render_scope": "single_version_detail",
            "refresh_policy": "scan/cmp refresh this Version Detail directly; catalog and library navigation pages may be deferred",
            "write_mode": "atomic_replace",
            "render_output": str(render_output),
        },
    }
    if first_version_review:
        model["headline"] = (
            f"首版审查：当前无可比基准版，展示版本自身 view 覆盖、文件分类和证据等级；"
            f"扫描文件 {_scan_evidence_file_total(scan_evidence)} 个，未知文件 {_scan_evidence_unknown_total(scan_evidence)} 个。"
        )
        model["confidence_note"] = "没有基准版时不做新增/删除/修改判断；FULL/独立包可先做版本自身覆盖审查。"
    else:
        model["headline"] = _version_update_headline(
            base_ref,
            added_files,
            removed_files,
            _as_int(changed_files),
            recommended_count,
            reviewed_count,
            len(path_changes_same_content),
            _as_int(package_root_unmatched.get("new")),
            _as_int(package_root_unmatched.get("base")),
        )
        model["confidence_note"] = _version_update_confidence_note(model)
    model["primary_next_action"] = _primary_next_action(status, recommended_count, len(commands))
    model["version_review_model"] = build_version_review_model(model)
    model["ip_user_view_model"] = _as_mapping(model["version_review_model"].get("ip_user_view"))
    model["review_report"] = _as_mapping(model["version_review_model"].get("review_report"))
    model['review_contact'] = (version.get('review_owner') or _as_mapping(version.get('review_packet')).get('review_owner')
                               or lib.get('review_owner') or lib.get('owner') or '')
    model['engineering_report'] = build_engineering_report(model)
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
    unmatched = _as_mapping(model.get("package_root_unmatched"))
    unmatched_new = _as_int(unmatched.get("new"))
    unmatched_base = _as_int(unmatched.get("base"))
    true_added = max(0, _as_int(model.get("added_files")) - unmatched_new)
    true_removed = max(0, _as_int(model.get("removed_files")) - unmatched_base)
    return [
        f"<tr><td>完整变化文件</td><td>{ui.esc(len(file_changes))}</td><td>见 file_diff.json；详情页只保留重点变化表。</td></tr>",
        f"<tr><td>真实新增</td><td>{ui.esc(true_added)}</td><td>排除包根迁移下未匹配的新侧文件。</td></tr>",
        f"<tr><td>真实删除</td><td>{ui.esc(true_removed)}</td><td>排除包根迁移下未匹配的基准侧文件。</td></tr>",
        f"<tr><td>未匹配新侧</td><td>{ui.esc(unmatched_new)}</td><td>新包根下未找到唯一旧侧匹配；需要确认是否为旧版漏扫、交付范围扩展或真实新增。</td></tr>",
        f"<tr><td>未匹配基准侧</td><td>{ui.esc(unmatched_base)}</td><td>旧包根下未找到唯一新侧匹配；需要确认是否为本包不携带或真实删除。</td></tr>",
        f"<tr><td>修改</td><td>{ui.esc(model.get('changed_files') or 0)}</td><td>按视图变化矩阵聚合展示。</td></tr>",
        f"<tr><td>P0/P1 重点</td><td>{ui.esc(len(model.get('recommended_file_diff', []) or []))}</td><td>主页面的变化文件明细只展示 P0/P1/审查项。</td></tr>",
    ]


def _focus_file_change_rows(model: Mapping[str, Any]) -> list[str]:
    projection = build_ip_change_projection(model, [item for item in model.get('file_changes', []) or [] if isinstance(item, Mapping)])
    focus = [
        item
        for item in projection['visible_changes']
        if isinstance(item, Mapping) and str(item.get("review_lane") or "") in {"P0", "P1", "Review"}
    ]
    if not focus:
        focus = projection['visible_changes']
    rows: list[str] = []
    for item in focus[:120]:
        if not isinstance(item, Mapping):
            continue
        rows.append(
            "<tr>"
            f"<td>{ui.badge(str(item.get('display_change') or item.get('change') or '').upper(), _cn_change_kind(item.get('display_change') or item.get('change')))}</td>"
            f"<td><b>{ui.esc(_view_label(str(item.get('file_type') or 'unknown')))}</b></td>"
            f"<td><code>{ui.esc(item.get('path') or '-')}</code></td>"
            f"<td>{ui.badge(item.get('review_lane') or 'Review', _cn_review_lane(item.get('review_lane') or 'Review'))}</td>"
            f"<td><span class='match-status'>{ui.esc(_cn_match_status(item.get('match_status')))}</span>"
            f"<small class='match-candidates'>"
            f"{ui.esc('基准候选: ' + str(item.get('base_candidate'))) if item.get('base_candidate') else ''}"
            f"{'；' if item.get('base_candidate') and item.get('target_candidate') else ''}"
            f"{ui.esc('目标文件: ' + str(item.get('target_candidate'))) if item.get('target_candidate') else ''}"
            f"</small></td>"
            f"<td>{ui.esc(item.get('hint') or '按该视图变化确认使用影响。')}</td>"
            "</tr>"
        )
    return rows


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
    if text == "overlay":
        return "增量包叠加（未提供不等于删除）"
    if text == "needs_package_confirmation":
        return "包范围待确认（暂不判定删除）"
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
.version-overview{margin-bottom:18px;border:1px solid #d9e0ea;border-radius:12px;background:#fff;box-shadow:0 8px 22px rgba(16,24,40,.05);overflow:hidden}
.overview-head{display:flex;justify-content:space-between;align-items:center;padding:15px 18px;border-bottom:1px solid #e4e8ef;background:#f8fafc}
.overview-title{display:flex;align-items:center;gap:10px}.overview-title h2{margin:0;font-size:16px}.overview-title:before{content:"";display:block;width:4px;height:22px;border-radius:2px;background:#0f766e}
.overview-title .badge{font-size:11px;min-height:22px}.overview-context-note{display:flex;gap:9px;align-items:flex-start;padding:12px 16px;border-top:1px solid #e4e8ef;color:#60727b;background:#fbfdfc;font-size:12px;line-height:1.55}.overview-context-note b{flex:0 0 auto;color:#284254}
.review-summary-strip{display:grid;grid-template-columns:minmax(280px,1.45fr) repeat(3,minmax(130px,1fr));background:#fff}
.overview-cell{min-height:76px;padding:12px 16px;border-right:1px solid #e4e8ef}.overview-cell:last-child{border-right:0}.overview-cell b{display:block;color:#667085;font-size:12px}.overview-cell em{display:block;margin-top:6px;font-style:normal;font-weight:800;color:#172033;line-height:1.35;overflow-wrap:anywhere}.overview-cell span{display:block;margin-top:4px;color:#667085;font-size:12px;line-height:1.3}
.review-layout{display:grid;grid-template-columns:minmax(0,1fr) minmax(300px,320px);gap:16px;align-items:start}.review-primary-column,.review-secondary-column{min-width:0}.review-secondary-column>.panel{margin-bottom:12px;box-shadow:0 5px 16px rgba(16,24,40,.04)}.review-secondary-column .panel-head{padding:12px 14px}.review-secondary-column .panel-body{padding:12px 14px}.review-secondary-column .metric-grid{grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}.review-secondary-column .metric-card{padding:9px}.review-secondary-column .metric-value{font-size:18px}.review-secondary-column .metric-hint{line-height:1.35}.review-secondary-column .table-wrap{max-height:320px;overflow:auto}
.review-primary-column>.panel{margin-bottom:0}.review-primary-column>.panel .panel-body{padding:16px 18px}.review-primary-column .panel-head{padding:16px 18px}.review-primary-column .panel-head h2{font-size:17px}.review-top-layout{display:grid;grid-template-columns:minmax(0,1.9fr) minmax(310px,.76fr);gap:16px;align-items:start;margin-bottom:16px}.review-top-layout>.panel,.review-top-summary>.version-overview{margin-bottom:0}.review-top-summary .summary-window{grid-template-columns:1fr}.review-top-summary .summary-window>div{min-height:0;padding:10px 14px}.review-top-summary .summary-window>div+div{border-left:0;border-top:1px solid #e4e8ef}.review-top-summary .review-summary-strip{grid-template-columns:repeat(2,minmax(0,1fr))}.review-top-summary .overview-cell{min-height:62px;padding:10px 12px}.review-top-summary .overview-cell em,.review-top-summary .overview-cell:first-child em{font-size:14px}.review-top-summary .overview-cell span{font-size:11px}.review-top-summary .lineage-strip{padding:9px 14px;flex-wrap:wrap}.review-top-summary .overview-context-note{padding:10px 14px}
.view-delta-scroll{max-height:430px;overflow:auto;scrollbar-gutter:stable}.view-delta-table{min-width:720px;table-layout:fixed}.view-delta-table th{position:sticky;top:0;z-index:2;background:#eef3f7;border-bottom:2px solid #cbd5e1;color:#27364a}.view-delta-table th:nth-child(1){width:31%}.view-delta-table th:nth-child(2){width:24%}.view-delta-table th:nth-child(3){width:21%}.view-delta-table th:nth-child(4){width:24%}.view-delta-table tbody tr:hover{background:#f8fbfc}.view-delta-table td{padding:9px 10px;vertical-align:middle}.view-use{display:block;margin-top:3px;color:#667085;font-size:11px;font-weight:600}.evidence-line{display:flex;align-items:baseline;gap:6px;flex-wrap:wrap}.evidence-level{display:inline-block;margin-bottom:0;color:#475467;font-size:12px;line-height:1.35}.evidence-status{margin-top:5px}.evidence-counts{display:inline;color:#667085;font-size:11px;line-height:1.35}.view-delta-scroll-note{margin:-5px 0 9px;color:#667085;font-size:11px}.delta-summary-cell{white-space:nowrap}.delta-delivery-count{display:inline-flex;align-items:baseline;gap:5px;color:#1849a9}.delta-delivery-count b{font-size:16px;font-variant-numeric:tabular-nums}.delta-delivery-count span{color:#667085;font-size:11px}.delta-compact-counts{display:flex;flex-wrap:wrap;gap:4px;margin-top:5px}.delta-compact-count{display:inline-flex;align-items:baseline;gap:3px;padding:2px 5px;border-radius:5px;background:#f2f4f7;color:#98a2b3;font-variant-numeric:tabular-nums}.delta-compact-count b{font-size:11px}.delta-compact-count small{font-size:10px}.delta-compact-count.added{background:#ecfdf3;color:#087443}.delta-compact-count.removed{background:#fff1f0;color:#b42318}.delta-compact-count.changed{background:#fff7e8;color:#a15c00}.delta-compact-count.path-changed{background:#eef4ff;color:#315ea8}.delta-compact-count.unmatched{background:#f4f0ff;color:#6f3f8f}
.focus-change-scroll{max-height:480px;overflow:auto;scrollbar-gutter:stable}.review-fold{margin-top:16px;border-top:1px solid #e4e8ef;padding-top:13px}.review-fold>summary{font-size:13px}.review-fold .quality-note{margin:10px 0}.pending-facts{margin-top:14px}.pending-facts>b{display:block;margin-bottom:7px;font-size:12px;color:#344054}.pending-fact-list{gap:6px}.pending-fact-list .context-row{padding:8px 10px}
.summary-window{display:grid;grid-template-columns:minmax(0,1.2fr) minmax(280px,1fr);gap:0;border-bottom:1px solid #e4e8ef;background:#fbfdfc}.summary-window>div{padding:12px 18px;min-height:70px}.summary-window>div+div{border-left:1px solid #e4e8ef}.summary-window b{display:block;color:#667085;font-size:12px}.summary-window strong{display:block;margin-top:4px;color:#172033;font-size:13px}.summary-window p{margin:5px 0 0;color:#172033;line-height:1.45;font-size:13px}.decision-next-action{background:#f0f8f4}.lineage-strip{display:flex;align-items:center;gap:10px;padding:9px 18px;border-top:1px solid #e4e8ef;color:#667085;font-size:12px}.lineage-strip b{color:#172033;overflow-wrap:anywhere}.lineage-strip i{color:#14866e;font-style:normal;font-weight:900}.review-sidebar-stack .quality-note{margin-top:10px}.fact-summary-row{display:flex;justify-content:space-between;gap:12px;align-items:baseline;margin-top:10px;padding:9px 10px;border:1px solid var(--review-line);background:#f7fbf8;color:var(--review-muted);font-size:12px}.fact-summary-row b{color:var(--review-ink)}.file-entry-links{display:flex;flex-wrap:wrap;gap:6px}.file-entry-link{white-space:nowrap}
.refresh-status-list{display:grid;gap:0;border:1px solid var(--review-line);border-radius:8px;overflow:hidden;background:#fff}.refresh-status-row{display:grid;grid-template-columns:72px minmax(78px,.7fr) minmax(0,1.4fr);gap:8px;align-items:start;padding:9px 10px;border-bottom:1px solid var(--review-line);font-size:12px}.refresh-status-row:last-child{border-bottom:0}.refresh-status-row b{color:var(--review-muted);font-weight:800}.refresh-status-row strong{color:var(--review-ink);font-weight:800;overflow-wrap:anywhere}.refresh-status-row span{color:var(--review-muted);line-height:1.35}
.update-note-panel{margin-bottom:16px;border-top:4px solid #6b4eff;background:#fff}.update-note-head{display:flex;justify-content:space-between;gap:18px;align-items:flex-start;padding:16px 18px;border-bottom:1px solid var(--review-line);background:linear-gradient(90deg,#fbfbff,#f8fbf8)}.update-note-head h2{margin:2px 0 4px;font-size:18px;color:var(--review-ink)}.update-note-head p{margin:0;color:var(--review-muted);font-size:12px}.section-kicker{color:#6b4eff;font-size:11px;font-weight:900;letter-spacing:.08em}.update-note-status{display:flex;gap:7px;align-items:center;flex-wrap:wrap;justify-content:flex-end}.update-note-body{padding:15px 18px 17px}.update-note-summary{display:grid;grid-template-columns:90px minmax(0,1fr) minmax(190px,.34fr);gap:12px;align-items:start;padding:12px 14px;border:1px solid #dcd9ff;border-radius:10px;background:#fbfbff}.update-note-summary>b{color:#5b54a4;font-size:12px}.update-note-summary p{margin:0;color:var(--review-ink);font-size:14px;line-height:1.55}.update-note-tags{display:flex;gap:6px;flex-wrap:wrap;justify-content:flex-end}.update-note-tags span{display:inline-flex;align-items:center;min-height:23px;padding:2px 8px;border-radius:999px;background:#eef6f3;color:#116957;font-size:11px;font-weight:800}.update-note-tags .muted{background:#f2f4f7;color:#667085}.update-note-columns{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px;margin-top:12px}.update-note-list{border:1px solid var(--review-line);border-radius:10px;background:#fff}.update-note-list h3{margin:0;padding:9px 11px;border-bottom:1px solid var(--review-line);font-size:13px;color:var(--review-ink-soft);background:#f8fafc}.update-note-list ul{margin:0;padding:10px 11px 10px 25px;max-height:148px;overflow:auto}.update-note-list li{margin:0 0 6px;color:var(--review-ink);font-size:12px;line-height:1.45}.update-note-list li:last-child{margin-bottom:0}.update-note-warning{display:flex;gap:12px;align-items:flex-start;margin:14px 18px 0;padding:10px 12px;border:1px solid #f5b4a9;border-radius:10px;background:#fff4f2;color:#893328}.update-note-warning b{flex:0 0 210px}.update-note-warning span{font-size:12px;line-height:1.45}.update-note-evidence{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-top:12px;color:var(--review-muted);font-size:12px}.update-note-evidence code{padding:3px 6px;border-radius:6px;background:#f2f4f7;color:#344054}.update-note-meta{margin-top:10px;color:var(--review-muted);font-size:11px}
@media(max-width:1180px){.review-layout{grid-template-columns:1fr}.review-secondary-column{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}.review-secondary-column>.panel{margin-bottom:0}.review-summary-strip{grid-template-columns:repeat(2,minmax(0,1fr))}.overview-cell:nth-child(2n){border-right:0}.overview-cell{border-bottom:1px solid #e4e8ef}}
@media(max-width:1080px){.review-top-layout{grid-template-columns:1fr}.review-top-summary .summary-window{grid-template-columns:repeat(2,minmax(0,1fr))}.review-top-summary .summary-window>div+div{border-left:1px solid #e4e8ef;border-top:0}}
@media(max-width:760px){.review-secondary-column{display:block}.review-secondary-column>.panel{margin-bottom:14px}.review-summary-strip{grid-template-columns:1fr}.overview-cell{border-right:0}.overview-cell:last-child{border-bottom:0}}
:root{--review-ink:#142635;--review-ink-soft:#284254;--review-canvas:#eef3f1;--review-paper:#fff;--review-line:#d6e1dd;--review-muted:#60727b;--review-teal:#14866e;--review-teal-soft:#e8f6f0;--review-amber:#b76612;--review-amber-soft:#fff4e3;--review-red:#b54537;--review-red-soft:#fff0ed}
.evidence-counts{display:inline;color:var(--review-muted);font-size:11px;line-height:1.4;margin:0}
body{background:var(--review-canvas);color:var(--review-ink)}
.hero{background:var(--review-ink);border-bottom:4px solid var(--review-teal);padding:27px 36px 25px;box-shadow:0 8px 20px rgba(20,38,53,.16)}.hero .kicker{color:#8ad7ba;letter-spacing:.12em}.hero h1{color:#fff;font-size:28px;font-weight:760}.hero p{color:#b9c9d1}.hero .compact-meta span{background:rgba(255,255,255,.07);border-color:rgba(215,236,228,.25);color:#dce9e5}.hero .compact-meta b{color:#f0fbf6}.hero .compact-meta em{color:#b9c9d1}.hero-status{display:flex;flex-direction:column;align-items:flex-end;gap:7px}.hero-status:before{content:"IP 使用判断";color:#8ad7ba;font-size:11px;font-weight:800;letter-spacing:.08em}.hero .badge{background:rgba(255,255,255,.1);border-color:rgba(255,255,255,.42);color:#f8fffb;box-shadow:none}.hero .badge.warn{background:#f5b55f;color:#3e260d;border-color:#ffd798}.hero .badge.bad{background:#e97867;color:#fff;border-color:#ffb3a9}.hero .badge.ok{background:#4fc49b;color:#082e21;border-color:#b4f0d8}
.workspace{max-width:1500px;padding:24px 32px 48px}.panel{border-color:var(--review-line);border-radius:10px;box-shadow:0 7px 20px rgba(20,52,55,.06)}.panel-head{background:var(--review-paper);border-bottom-color:var(--review-line)}.panel-head h2{color:var(--review-ink);letter-spacing:0}.panel-head p{color:var(--review-muted)}
.version-overview{border-color:var(--review-line);border-top:4px solid var(--review-teal);border-radius:10px;box-shadow:0 8px 22px rgba(20,52,55,.07)}.overview-head{background:var(--review-paper);border-bottom-color:var(--review-line);padding:12px 18px}.overview-title:before{background:var(--review-teal);height:18px}.overview-title h2{color:var(--review-ink);font-size:15px}.review-summary-strip{background:var(--review-paper)}.overview-cell{border-right-color:var(--review-line);min-height:76px}.overview-cell:first-child{background:var(--review-teal-soft)}.overview-cell b{color:var(--review-muted)}.overview-cell em{color:var(--review-ink)}.overview-cell:first-child em{font-size:14px}.overview-cell:not(:first-child) em{font-size:18px;line-height:1.2;font-variant-numeric:tabular-nums}.overview-cell span{color:var(--review-muted)}.summary-window{background:#f7fbf8}.summary-window>div{min-height:66px}.summary-window p{font-size:13px}
.review-layout{gap:16px}.review-secondary-column{position:sticky;top:16px}.review-primary-column>.panel,.review-top-matrix>.panel{border-top:3px solid var(--review-ink-soft)}.review-primary-column>.panel .panel-head,.review-top-matrix>.panel .panel-head{padding:14px 18px 12px}.review-primary-column .panel-head h2:before,.review-top-matrix .panel-head h2:before{content:"";display:inline-block;width:4px;height:18px;margin:0 9px -3px 0;border-radius:2px;background:var(--review-teal)}.review-primary-column>.panel .panel-body,.review-top-matrix>.panel .panel-body{padding:14px 18px 16px}
.view-delta-toolbar{display:flex;justify-content:space-between;gap:18px;align-items:center;padding:0 0 14px;border-bottom:1px solid var(--review-line);margin-bottom:14px}.view-delta-toolbar b{display:block;color:var(--review-ink);font-size:12px}.view-delta-toolbar>div:first-child span{display:block;margin-top:2px;color:var(--review-muted);font-size:12px}.delta-legend{display:flex;gap:12px;align-items:center;flex-wrap:wrap;color:var(--review-muted);font-size:11px;font-weight:650}.delta-legend span{display:inline-flex;align-items:center;gap:5px;white-space:nowrap}.legend-dot{display:inline-block;width:8px;height:8px;border-radius:50%;background:#a9b4b9}.legend-dot.current{background:#3d78cc}.legend-dot.added{background:#2b9b74}.legend-dot.removed{background:#c85545}.legend-dot.changed{background:#d4862a}.legend-dot.path-changed{background:#4f73b7}.legend-dot.unmatched{background:#8b5fc7}
.view-delta-scroll{border-color:var(--review-line);border-radius:8px;background:var(--review-paper)}.view-delta-table{min-width:720px}.view-delta-table th{background:#edf3f3;color:#29404a;border-bottom:2px solid #bfd0cb;text-transform:none}.view-delta-table td{border-bottom-color:#e1e9e6;padding:10px 10px}.view-delta-table tbody tr:nth-child(even){background:#fbfdfc}.view-delta-table tbody tr:hover{background:#f0f8f4}.view-delta-table tbody tr{border-left:3px solid transparent}.view-delta-table tbody tr:has(.delta-compact-count.added){border-left-color:#43a782}.view-delta-table tbody tr:has(.delta-compact-count.changed){border-left-color:#d4862a}.view-delta-table tbody tr:has(.delta-compact-count.removed){border-left-color:#c85545}.view-use{color:var(--review-muted);font-weight:600}.evidence-level{padding:2px 6px;border:1px solid #d7e3df;border-radius:5px;background:#f5faf8;color:#48636a}.evidence-counts{color:var(--review-muted)}.view-delta-scroll-note{color:var(--review-muted)}.delta-delivery-count{color:#1e5baa}.delta-compact-count{border:1px solid transparent}.delta-compact-count.added{background:#e9f7f0;color:#087443}.delta-compact-count.removed{background:#fff0ed;color:#ae3b2c}.delta-compact-count.changed{background:#fff3df;color:#a35c08}.inline-file-evidence summary{display:inline-flex;align-items:center;gap:5px;padding:4px 7px;border:1px solid #d7e3df;border-radius:5px;background:#f5faf8;color:#245d50;font-size:12px;font-weight:700;cursor:pointer}.inline-file-evidence summary:hover{background:#e8f6f0}.inline-file-evidence[open]{padding:7px;border:1px solid #d7e3df;border-radius:7px;background:#fbfdfc}.inline-file-evidence[open] summary{margin-bottom:6px}
.review-secondary-column>.panel{border-radius:10px;box-shadow:0 6px 18px rgba(20,52,55,.055)}.review-secondary-column>.panel:first-child{border-top:3px solid var(--review-teal)}.review-secondary-column .panel-head{padding:14px 16px}.review-secondary-column .panel-head h2{font-size:15px}.review-secondary-column .panel-body{padding:14px 16px}.review-secondary-column .metric-grid{gap:0;border:1px solid var(--review-line);border-radius:8px;overflow:hidden;background:var(--review-paper)}.review-secondary-column .metric-card{border:0;border-right:1px solid var(--review-line);border-bottom:1px solid var(--review-line);border-radius:0;box-shadow:none;padding:13px 12px;background:var(--review-paper)}.review-secondary-column .metric-card:nth-child(2n){border-right:0}.review-secondary-column .metric-card:nth-last-child(-n+2){border-bottom:0}.review-secondary-column .metric-card.ok{border-top:3px solid #3da47d}.review-secondary-column .metric-card.warn{border-top:3px solid #d4862a}.review-secondary-column .metric-card.bad{border-top:3px solid #c85545}.review-secondary-column .metric-value{color:var(--review-ink);font-size:20px}.review-secondary-column .metric-hint{color:var(--review-muted)}.review-secondary-column>details .panel-head{background:#fbfdfc}.review-secondary-column>details[open] .panel-head{border-bottom-color:var(--review-line)}
.review-fold{border-color:var(--review-line);background:#fbfdfc}.review-fold>summary{color:#245d50}.quality-note{border-color:var(--review-line);background:#f4f8f6;color:var(--review-muted)}
@media(max-width:1180px){.review-secondary-column{position:static}}
@media(max-width:760px){.hero{padding:24px 22px 22px}.workspace{padding:22px}.view-delta-toolbar{display:block}.delta-legend{margin-top:10px}}
@media(prefers-reduced-motion:reduce){*,*::before,*::after{scroll-behavior:auto!important;transition:none!important}}
.hero{padding:14px 24px;box-shadow:none;border-bottom-width:2px}.hero h1{font-size:22px;margin:3px 0 4px}.hero p{font-size:12px}.hero .compact-meta{margin-top:6px;gap:12px}.hero .compact-meta span{border:0;background:transparent;border-radius:0;padding:0}.hero .kicker,.hero-status:before{letter-spacing:0}.workspace{padding:16px 24px 32px;margin:0 auto}
.panel,.version-overview{border-radius:6px;box-shadow:none}.review-secondary-column>.panel{border-radius:6px;box-shadow:none}.review-top-layout{grid-template-columns:minmax(0,1.8fr) minmax(300px,.8fr);gap:16px}.view-delta-table{min-width:0}.review-layout{grid-template-columns:minmax(0,1fr) 300px}.view-delta-table td{overflow-wrap:anywhere}.review-top-matrix>.panel .panel-head,.review-top-matrix>.panel .panel-body{padding:12px 14px}.review-top-summary .overview-cell{min-height:0;padding:8px 12px}
.update-note-panel{border-top:3px solid var(--review-teal);border-radius:6px;margin-bottom:16px}.update-note-head{padding:10px 14px;background:#fff;align-items:center}.update-note-head h2{font-size:16px;margin:0}.update-note-head .section-kicker{display:none}.update-note-body{padding:10px 14px}.update-note-summary{border:0;border-radius:0;padding:0;background:#fff;grid-template-columns:72px minmax(0,1fr) minmax(150px,.3fr)}.update-note-summary>b{color:var(--review-muted)}.update-note-summary p{font-size:13px}.update-note-columns{gap:12px;margin-top:10px}.update-note-list{border:0;border-radius:0}.update-note-list h3{padding:5px 0;background:#fff}.update-note-list ul{padding:6px 0 0 16px;max-height:110px}.update-note-provenance{margin-top:8px;border-top:1px solid var(--review-line);padding-top:6px;font-size:12px;color:var(--review-muted)}.update-note-provenance summary{cursor:pointer}.update-note-provenance .update-note-meta{overflow-wrap:anywhere}
.update-note-more{margin-top:10px;padding-top:8px;border-top:1px solid var(--review-line)}.update-note-more>summary{cursor:pointer;color:#245d50;font-size:12px;font-weight:700}.update-note-more[open] .update-note-columns{margin-top:8px}
.review-secondary-column .refresh-status-list{border:0}.review-secondary-column .refresh-status-row{grid-template-columns:72px minmax(0,1fr)}.review-secondary-column .refresh-status-row span{grid-column:1 / -1}.review-secondary-column .metric-value{font-size:15px;white-space:normal}
.view-delta-toolbar{padding-bottom:8px;margin-bottom:8px}.view-delta-filter-bar{grid-template-columns:minmax(0,1fr);padding:8px;border-radius:4px;gap:6px}.view-delta-filter-head{display:none}.view-delta-totals{grid-column:1}.view-delta-search{min-width:140px;flex:1 1 170px}.view-delta-select select{min-width:105px}.view-delta-filter-controls{gap:6px}.view-delta-search,.view-delta-select{border-radius:4px}.view-delta-scroll-note{display:none}
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
    blocking = len(_ip_usage_gate_blocking_items(gate))
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


def _management_gate_release_status(version: Mapping[str, Any]) -> tuple[str, str, str]:
    gate = version.get("review_gate") if isinstance(version.get("review_gate"), Mapping) else {}
    status = str((gate or {}).get("status") or "NOT_BUILT").upper()
    blocking = len((gate or {}).get("blocking_items", []) or [])
    attention = len((gate or {}).get("attention_items", []) or [])
    if blocking:
        return "待发布处理", f"{blocking} 个管理阻塞项；不替代 IP 技术判断", "WARNING"
    if status in {"REVIEW_REQUIRED", "NEEDS_REVIEW", "ATTENTION"} or attention:
        return "待发布确认", f"{attention} 个管理关注项；不替代 IP 技术判断", "WARNING"
    if status in {"READY", "PASS", "OK"}:
        return "放行通过", "管理门禁已关闭", "PASS"
    return "未建立", "未发现正式放行门禁证据", "INFO"


def _management_gate_item_label(item: Mapping[str, Any]) -> str:
    item_id = str(item.get("id") or "")
    title = str(item.get("title") or item_id or "未命名事项")
    if item_id == "gate.release_note" or "release note" in title.lower():
        return "发布说明缺失"
    return title


def _review_context_is_active(ctx: Mapping[str, Any]) -> bool:
    return str(ctx.get("status") or "").upper() == "IN_ACTIVE_WINDOW"


def _one_sentence(value: Any, fallback: str) -> str:
    text = " ".join(str(value or "").split()).strip()
    if not text:
        return fallback
    if "。" in text:
        text = text.split("。", 1)[0] + "。"
    if len(text) > 96:
        text = text[:93].rstrip("，；、 ") + "..."
    return text


def _version_overview_panel(model: Mapping[str, Any]) -> str:
    ip_model = _as_mapping(model.get("ip_user_view_model"))
    comparison = _as_mapping(ip_model.get("comparison"))
    counts = _as_mapping(comparison.get("visible_counts"))
    first = str(model.get("review_mode") or "") == "first_version"
    missing = str(model.get("status") or "").upper() in {"DIFF_NOT_RUN", "NO_DIFF_SUMMARY", "NEEDS_BASE_CONFIRM"}
    new_pending = _as_int(counts.get("unmatched_new"))
    base_pending = _as_int(counts.get("unmatched_base"))
    pending_text = f"本版 {new_pending} / 基准版 {base_pending}"
    confirmed = " / ".join(f"{label} {_as_int(counts.get(key))}" for key, label in
                           (("added", "新增"), ("removed", "删除"), ("changed", "修改")))
    if first:
        summary = f"首版交付，已记录 {_scan_evidence_file_total(_as_mapping(model.get('scan_evidence')))} 个文件。没有基准版，不作新增、删除或修改判断。"
    elif missing:
        summary = "尚未完成可靠的版本对比；当前报告可以查看本版交付，不能据此判断无变化。"
    else:
        summary = f"已确认变化：{confirmed}。"
        if new_pending or base_pending:
            summary += f"待核对文件：{pending_text}，暂不计为新增或删除。"
        path_count = _as_int(counts.get("path_changed_same_content"))
        if path_count:
            summary += f"另有 {path_count} 个文件仅相对路径变化，内容已确认相同。"
    usage_rows = []
    usage_groups: dict[str, dict[str, Any]] = {}
    for row in ip_model.get("view_rows", []) or []:
        if not isinstance(row, Mapping):
            continue
        confirmed_count = sum(_as_int(row.get(key)) for key in ("added", "removed", "changed"))
        uncertain = _as_int(row.get("unmatched_new")) + _as_int(row.get("unmatched_base"))
        if not confirmed_count and not uncertain and not first:
            continue
        area = str(row.get("usage_area") or "其他")
        view = str(row.get("view") or row.get("view_type") or "-")
        group = usage_groups.setdefault(area, {'views': [], 'confirmed': 0, 'uncertain': 0})
        group['views'].append(view)
        group['confirmed'] += confirmed_count
        group['uncertain'] += uncertain
    for area, group in usage_groups.items():
        if first:
            meaning = '已交付这些视图，未作版本对比'
        elif group['confirmed'] and group['uncertain']:
            meaning = '部分文件已确认变化，其余待核对；查看对应变化文件和核查结果'
        elif group['uncertain']:
            meaning = '尚未确定文件对应关系，不能据此推断内容变化'
        else:
            meaning = '已确认存在变化，需结合变化字段判断对当前流程的影响'
        usage_rows.append(f"<li><b>{ui.esc(area)}</b><span>{ui.esc('、'.join(group['views']))}：{ui.esc(meaning)}</span></li>")
    question = ("确认交付视图是否满足当前使用场景。" if first else
                "先核对待核对文件，再阅读已确认变化；路径不同本身不代表内容变化。" if new_pending or base_pending else
                "基准版尚未确定或对比结果未生成，请向报告提供者确认。" if missing else
                "结合具体变化文件与代表文件核查结果判断；没有自动阻塞不等于已验证全部内容。")
    pending = [item for item in ip_model.get("pending_fact_items", []) or []
               if isinstance(item, Mapping) and str(item.get("kind") or "").upper() != "VIEW_DELTA"]
    questions = "".join(f"<li>{ui.esc(item.get('summary') or item.get('label') or '')}</li>" for item in pending)
    baseline_only = _as_int(comparison.get("baseline_only_count"))
    return (
        '<section data-section="decision-summary" class="version-overview">'
        "<div class='overview-head'><div class='overview-title'><h2>版本摘要</h2></div></div>"
        "<div class='summary-window'><div><b>主要变化</b>"
        f"<p>{ui.esc(summary)}</p></div>"
        '<div data-section="impact-summary"><b>使用影响</b>'
        f"<ul class='reader-usage-list'>{''.join(usage_rows) or '<li>尚无足够结果判断使用影响。</li>'}</ul></div>"
        "<div data-next-action='true' class='decision-next-action'><b>需要确认</b>"
        f"<p>{ui.esc(question)}</p>{'<ul>' + questions + '</ul>' if questions else ''}</div></div>"
        '<div data-section="comparison-context" class="lineage-strip"><span>版本关系 / 对比基准</span>'
        f"<b>{ui.esc('首版交付' if first else comparison.get('base_label') or '基准版未确定')}</b>"
        f"<i>→</i><b>{ui.esc(model.get('version_id') or '-')}</b></div>"
        + (f"<p class='scope-note'>对比范围：{'增量对比' if comparison.get('scope') in {'incremental', 'partial'} else '全量对比'}；基准来源：{ui.esc(comparison.get('base_source_label') or '见基准版本说明')}。</p>" if not first else '')
        + (f"<p class='scope-note'>基准版另有 {baseline_only} 个文件未随本包交付，未计为删除。</p>" if baseline_only else "")
        + "<style>.reader-usage-list{list-style:none;padding:0;margin:8px 0}.reader-usage-list li{display:grid;grid-template-columns:110px minmax(0,1fr);gap:8px;padding:6px 0;border-bottom:1px solid var(--line);font-size:12px}.reader-usage-list span{overflow-wrap:anywhere}.delta-unverified{display:flex;flex-direction:column;gap:2px;color:#70510e;font-size:12px}.reader-evidence-key{font-size:12px;margin-top:10px;color:var(--muted)}.reader-evidence-key summary{cursor:pointer}</style>"
        "</section>"
    )


def _reader_summary(model: Mapping[str, Any], version: Mapping[str, Any]) -> str:
    from lib_guard.render.version_semantic_checks import _no_delta_base, semantic_reader_totals
    engineering = _as_mapping(model.get('engineering_report'))
    comparison = _as_mapping(_as_mapping(model.get('ip_user_view_model')).get('comparison'))
    visible = _as_mapping(comparison.get('visible_counts'))
    has_comparison = (str(model.get('review_mode') or '') != 'first_version'
                      and str(model.get('status') or '').upper() not in {'DIFF_NOT_RUN', 'NO_DIFF_SUMMARY', 'NEEDS_BASE_CONFIRM'})
    added, removed, modified = (_as_int(visible.get(key)) for key in ('added', 'removed', 'changed'))
    unmatched = _as_int(visible.get('unmatched_new')) + _as_int(visible.get('unmatched_base'))
    has_file_changes = has_comparison and any((added, removed, modified, unmatched))
    file_context = ''
    if has_file_changes:
        pending = f'；另有待核对 {unmatched} 项' if unmatched else ''
        file_context = (f'<details class="reader-file-counts"><summary>查看文件变化数量</summary>'
                        f'<p class="reader-file-context"><strong>文件范围</strong> '
                        f'新增 {added}、删除 {removed}、修改 {modified}{pending}；'
                        '文件变化不等同于已确认的单元或接口变化。</p></details>')
    release, _, _ = _management_gate_release_status(version)
    semantic = _as_mapping(model.get('semantic_check'))
    if semantic.get('status') == 'CURRENT':
        counts = semantic_reader_totals(semantic)
        if _no_delta_base(semantic):
            version_changes = '版本变化未执行：未选择基准组合'
        elif not counts['delta_executed'] and not counts['delta_pending']:
            version_changes = '版本变化尚无检查结果'
        else:
            version_changes = f"版本变化 {counts['changed']} 项 / 变化证据不足 {counts['delta_pending']} 项"
        technical = (f"组合检查：{counts['current_failed']} 项未通过 / {counts['current_pending']} 项未确认；"
                     + version_changes)
        if not counts['current_executed'] and not counts['current_pending']:
            technical = '尚未执行当前版独立检查；' + technical
    elif semantic:
        technical = '组合检查结果已过期，当前范围尚未确认'
    else:
        technical = '跨视图对应与组合检查尚未执行'
    if engineering.get('delivery', {}).get('missing') or engineering.get('delivery', {}).get('contract_missing'):
        next_action = '补齐所列必需视图，并确认目标流程需要的模式与工艺角。'
    elif engineering.get('failures') or engineering.get('changed'):
        next_action = ' '.join(dict.fromkeys(item['advice'] for item in engineering.get('findings', [])
                                            if item['status'] in {'CHANGED', 'FAIL'}))[:240]
    elif any('不代表整库交付齐全' in item for item in engineering.get('limitations', [])):
        next_action = '先确认该 IP 的完整交付要求，再核对本版文件变化中与使用相关的视图。'
    elif has_file_changes:
        next_action = '先核对本版文件变化中与使用相关的视图，再按需检查代表文件或完整组合。'
    elif engineering.get('same_files'):
        next_action = '所选文件内容一致；更新引用路径时可沿用该文件的已有定义，其余视图与组合尚需按使用范围检查。'
    else:
        next_action = '先核对下方单元与接口规格；需要版本影响结论时选择代表文件对比。'
    facts = '<br>'.join(ui.esc(item) for item in engineering.get('key_facts', [])[:3])
    limits = '；'.join(engineering.get('limitations', [])[:2])
    limit_note = f'<small>未完成核查：{ui.esc(limits)}</small>' if limits else ''
    return (
        '<section data-section="reader-summary" class="reader-summary">'
        '<h2>阅读要点</h2>'
        '<div class="reader-summary-lead">'
        f'<div class="reader-action"><strong>建议动作</strong><p>{ui.esc(next_action)}</p></div>'
        f'<div class="reader-fact"><strong>已确认</strong><p>{facts or "尚无工程结论"}</p></div>'
        '</div>'
        '<div class="reader-summary-grid">'
        f'<div><span>交付情况</span><b>{ui.esc(engineering.get("delivery_summary") or "交付要求待确认")}</b></div>'
        f'<div><span>检查范围</span><b>{ui.esc(technical)}</b>{limit_note}</div>'
        f'<div><span>正式放行</span><b>{ui.esc(release)}</b></div>'
        '</div>'
        f'{file_context}'
        f'<p class="reader-contact">处理联系：{ui.esc(engineering.get("contact") or "未登记")}</p>'
        '<style>.reader-summary{margin-bottom:16px;background:#fff;border-top:2px solid #138675}'
        '.reader-summary h2{margin:0;padding:12px 16px 8px;font-size:16px}'
        '.reader-summary-lead{display:grid;grid-template-columns:minmax(0,1.25fr) minmax(0,1fr);gap:0;border-bottom:1px solid #e4e8ef}'
        '.reader-summary-lead>div{padding:12px 16px}.reader-summary-lead>div+div{border-left:1px solid #e4e8ef}'
        '.reader-summary-lead strong{display:block;color:#526574;font-size:12px}.reader-summary-lead p{margin:6px 0 0;font-size:14px;line-height:1.5}'
        '.reader-action{background:#f1f8f4}.reader-action p{font-weight:700;color:#17392f}'
        '.reader-summary-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr))}'
        '.reader-summary-grid>div{padding:10px 16px;border-right:1px solid #e4e8ef}'
        '.reader-summary-grid>div:last-child{border-right:0}.reader-summary-grid span{display:block;font-size:11px;color:#667085}'
        '.reader-summary-grid b{display:block;margin-top:3px;font-size:12px;line-height:1.4;color:#172033;font-weight:650}'
        '.reader-summary-grid small{display:block;margin-top:6px;font-size:11px;color:#526574}'
        '.reader-summary .reader-contact{margin:0;padding:8px 16px;border-top:1px solid #e4e8ef;color:#526574;font-size:11px}'
        '.reader-file-counts{padding:8px 16px;border-top:1px solid #e4e8ef;font-size:12px;color:#526574}'
        '.reader-file-counts summary{cursor:pointer;color:#245d50;font-weight:700}.reader-file-context{margin:8px 0 2px}'
        '@media(max-width:900px){.reader-summary-lead,.reader-summary-grid{grid-template-columns:1fr}'
        '.reader-summary-lead>div+div{border-left:0;border-top:1px solid #e4e8ef}}</style></section>'
    )


def _note_status_label(status: Any) -> str:
    value = str(status or "").lower()
    return {"published": "备注已发布", "draft": "草稿", "missing": "暂无", "invalid": "格式异常"}.get(value, value or "暂无")


def _note_conflict_warning(model: Mapping[str, Any], note: Mapping[str, Any]) -> str:
    if not note_is_available(note):
        return ""
    suggestion = str(note.get("use_suggestion") or "")
    ip_model = _as_mapping(model.get("ip_user_view_model"))
    decision = _as_mapping(ip_model.get("decision"))
    machine_status = str(decision.get("status") or model.get("usage_decision") or "").upper()
    if suggestion == "推荐使用" and machine_status not in {"READY", "PASS", "OK"}:
        return (
            "<div class='update-note-warning'>"
            "<b>人工备注与机器证据不一致，需要复核</b>"
            f"<span>备注建议“推荐使用”，但当前机器判断为“{ui.esc(ui.status_label(machine_status))}”。请确认备注是否已覆盖最新扫描和对比结果。</span>"
            "</div>"
        )
    return ""


def _note_list(title: str, values: Any, *, empty: str) -> str:
    items = [str(item).strip() for item in values or [] if str(item).strip()]
    body = "".join(f"<li>{ui.esc(item)}</li>" for item in items[:8]) or f"<li class='muted'>{ui.esc(empty)}</li>"
    return f"<div class='update-note-list'><h3>{ui.esc(title)}</h3><ul>{body}</ul></div>"


def _version_update_note_panel(model: Mapping[str, Any]) -> str:
    note = _as_mapping(model.get("update_note"))
    available = note_is_available(note)
    status = str(note.get("status") or "missing")
    suggestion = str(note.get("use_suggestion") or "待确认")
    summary = str(note.get("summary") or "").strip()
    if not summary:
        summary = "暂无版本备注。建议由库负责人补充本次交付意图、影响范围、风险提醒和必须确认项。"
    impact_tags = "".join(f"<span>{ui.esc(item)}</span>" for item in (note.get("impact_areas") or [])[:10])
    if not impact_tags:
        impact_tags = "<span class='muted'>未标注影响场景</span>"
    meta = []
    if note.get("updated_by"):
        meta.append(f"更新人：{ui.esc(note.get('updated_by'))}")
    if note.get("updated_at"):
        meta.append(f"时间：{ui.esc(note.get('updated_at'))}")
    path = str(note.get("path") or "")
    if path:
        meta.append(f"文件：{ui.esc(common.short_path(path, 96))}")
    meta_html = "；".join(meta) if meta else "人工备注与扫描/对比证据分开保存。"
    evidence_refs = [str(item).strip() for item in note.get("evidence_refs", []) or [] if str(item).strip()]
    evidence_html = ""
    if evidence_refs:
        evidence_html = (
            "<div class='update-note-evidence'><b>备注引用</b>"
            + "".join(f"<code>{ui.esc(item)}</code>" for item in evidence_refs[:6])
            + "</div>"
        )
    status_html = ui.badge(status.upper(), _note_status_label(status)) + ui.badge("INFO" if available else "WARNING", suggestion)
    return "".join([
        "<section data-section='version-update-note' class='panel update-note-panel'>"
        "<div class='update-note-head'>"
        "<div><span class='section-kicker'>人工备注</span><h2>版本更新备注</h2>"
        "</div>"
        f"<div class='update-note-status'>{status_html}</div>"
        "</div>",
        _note_conflict_warning(model, note),
        "<div class='update-note-body'>",
        f"<div class='update-note-summary'><b>备注摘要</b><p>{ui.esc(summary)}</p><div class='update-note-tags'>{impact_tags}</div></div>",
        '<details class="update-note-more"><summary>查看关键变化、风险与必须确认项</summary><div class="update-note-columns">',
        _note_list("关键变化", note.get("key_changes"), empty="未填写关键变化"),
        _note_list("风险提醒", note.get("risks"), empty="未填写风险提醒"),
        _note_list("必须确认", note.get("must_check"), empty="未填写必须确认项"),
        "</div></details>",
        "<details class='update-note-provenance'><summary>备注来源与更新时间</summary>",
        evidence_html,
        f"<div class='update-note-meta'>{meta_html}</div></details>",
        "</div></section>",
    ])


def _review_gate_summary_panel(version: Mapping[str, Any], model: Mapping[str, Any]) -> str:
    gate = version.get("review_gate") if isinstance(version.get("review_gate"), Mapping) else {}
    if gate.get("packet_id") and str(gate.get("status") or "").upper() in {"WAITING", "BLOCKED", "APPROVED"}:
        # Static domain review has its own compact panel below.  Do not
        # relabel it as release-owner management or render it twice.
        return ""
    release_status, detail, status = _management_gate_release_status(version)
    blocking_items = [item for item in (gate or {}).get("blocking_items", []) or [] if isinstance(item, Mapping)]
    attention_items = [item for item in (gate or {}).get("attention_items", []) or [] if isinstance(item, Mapping)]
    release_notes = [item for item in model.get("release_notes", []) or [] if isinstance(item, Mapping)]
    gate_status = str((gate or {}).get("status") or "NOT_BUILT").upper()
    if gate_status == "NOT_BUILT" and not blocking_items and not attention_items and not release_notes:
        return ""
    item_rows = [
        f"<tr><td>{ui.esc('管理阻塞')}</td><td>{ui.esc(_management_gate_item_label(item))}</td></tr>"
        for item in blocking_items
    ]
    item_rows.extend(
        f"<tr><td>{ui.esc('管理关注')}</td><td>{ui.esc(_management_gate_item_label(item))}</td></tr>"
        for item in attention_items
    )
    item_rows.extend(
        f"<tr><td>{ui.esc('发布说明')}</td><td><code>{ui.esc(item.get('path') or item.get('name') or '-')}</code></td></tr>"
        for item in release_notes[:3]
    )
    items_html = ui.table(["类型", "事项"], item_rows, "暂无管理阻塞或关注事项")
    return ui.collapsible_panel(
        "正式放行管理",
        "发布负责人信息；不参与 IP 使用判断。",
        ui.metric_grid(
            [
                ("放行状态", release_status, detail, status),
                ("管理阻塞", len(blocking_items), "需要发布负责人关闭、接受或豁免", "WARNING" if blocking_items else "PASS"),
                ("管理关注", len(attention_items), "建议补充发布证据", "WARNING" if attention_items else "PASS"),
                ("发布说明", f"{len(release_notes)} 份" if release_notes else "缺失", "来自现有 scan/catalog 证据", "PASS" if release_notes else "WARNING"),
            ]
        )
        + items_html,
        open=False,
    )


def _static_domain_review_panel(version: Mapping[str, Any], model: Mapping[str, Any]) -> str:
    """Show the current static Review Packet without turning the page into a form."""

    gate = version.get("review_gate") if isinstance(version.get("review_gate"), Mapping) else {}
    packet_id = str(gate.get("packet_id") or "")
    if not packet_id:
        return ""
    status = str(gate.get("status") or "WAITING").upper()
    labels = {"WAITING": "待部门审查", "BLOCKED": "存在阻塞", "APPROVED": "部门审查通过"}
    tone = {"WAITING": "WARNING", "BLOCKED": "BLOCK", "APPROVED": "PASS"}.get(status, "WARNING")
    rows: list[str] = []
    for item in gate.get("items", []) or []:
        if not isinstance(item, Mapping):
            continue
        decision = str(item.get("decision") or "WAITING").upper()
        decision_label = {"PASS": "通过", "BLOCK": "阻塞", "QUESTION": "待回答", "WAITING": "待审查", "WAIVED": "已豁免"}.get(decision, decision)
        note_or_question = item.get("question") or "-"
        if decision in {"BLOCK", "QUESTION"} and item.get("note"):
            note_or_question = "已附备注；详见完整审查报告"
        rows.append(
            f"<tr><td>{ui.esc(item.get('department') or '-')}</td>"
            f"<td>{ui.badge(decision_label, 'pass' if decision in {'PASS', 'WAIVED'} else 'block' if decision == 'BLOCK' else 'warn')}</td>"
            f"<td>{ui.esc(note_or_question)}</td></tr>"
        )
    body = ui.metric_grid(
        [
            ("整体", labels.get(status, status), "部门审查 Gate，不等价于正式发布", tone),
            ("阻塞项", gate.get("blocking_open", 0), "机器或人工阻塞", "BLOCK" if gate.get("blocking_open") else "PASS"),
            ("待回答", gate.get("attention_count", 0), "QUESTION 或尚未完成的必需项", "WARNING" if gate.get("attention_count") else "PASS"),
            ("过期反馈", gate.get("stale_response_count", 0), "不参与当前 Gate", "WARNING" if gate.get("stale_response_count") else "PASS"),
        ]
    )
    if rows:
        body += ui.table(["部门", "决策", "备注/问题"], rows, "暂无部门审查项")
    packet = version.get("review_packet") if isinstance(version.get("review_packet"), Mapping) else {}
    report_path = packet.get("review_report") or gate.get("review_report")
    if report_path:
        body += f"<div class='evidence-actions'>{ui.button('查看完整审查报告', common.href(report_path), 'secondary')}</div>"
    return '<div data-section="review-gate">' + ui.panel("部门审查", f"Packet {ui.esc(packet_id)}；完整意见下沉到审查报告。", body) + "</div>"


def _scope_for_file_type(file_type: str) -> str:
    scope = package_view_type(file_type)
    return "未知" if scope == "unknown" else scope


def _view_label(file_type: str) -> str:
    key = canonical_file_type(file_type)
    if key == "unknown":
        return "未知文件"
    return view_label(canonical_view_type(key))


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
        "<div class='muted-box'>未知文件不是最终分类；这里按扩展名和无扩展名聚合，方便补规则或人工确认。</div>"
        + catalog._scroll_table(["类型线索", "数量", "代表文件", "审查动作"], rows, "当前没有未知文件", "unknown-detail-scroll")
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
            ("完整性判断", ui.status_label(status), f"发布级别候选：{readiness.get('release_level_candidate') or '-'}", status),
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
        empty += "<div class='empty-guidance'><b>当前原始扫描没有识别到 PVT 工艺角文件名</b>只有文件名中带 PVT 信息的库文件会进入工艺角汇总。</div>"
    corner_rows = catalog._version_corner_rows(corner_summary and {"corner_filename_summary": corner_summary} or {})
    corner_detail = (
        "<details class='detail-fold review-fold corner-detail'>"
        "<summary>PVT 工艺角明细</summary>"
        + catalog._scroll_table(["文件类型", "工艺", "电压", "温度", "路径"], corner_rows, "当前原始扫描没有识别到 PVT 工艺角文件名", "corner-detail-scroll")
        + "</details>"
    )
    return ui.collapsible_panel(
        "大文件与工艺角线索",
        "Liberty、SPEF、DB、GDS、Verilog 等大/多文件默认用数量、路径、哈希和 PVT 文件名线索辅助判断。",
        "<div class='quality-note'><b>默认策略</b> GDS/Liberty/SPEF/DB/OAS/Verilog 等大文件默认只看数量、路径、哈希和文件名工艺角线索。</div>"
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
        ("文件清单", f"{file_total} 个文件"),
        ("解析器任务", f"{parser_task_count} 个"),
        ("对比状态", ui.status_label(diff_status)),
        ("发布说明", f"{rn_count} 个"),
        ("证据分层", f"{evidence_label} - {evidence_detail}"),
    ]
    evidence_context = "<div class='context-list'>" + "".join(
        f"<div class='context-row'><b>{ui.esc(label)}</b><em>{ui.esc(value)}</em></div>" for label, value in evidence_rows
    ) + "</div>"
    trace_items = [
        ("scan_dir", common.href(scan_dir), "原始扫描输出目录"),
        ("file_inventory.json", common.href(scan_dir / "file_inventory.json") if scan_dir else "", "文件清单来源"),
        ("parser_manifest.json", common.href(scan_dir / "parser_manifest.json") if scan_dir else "", "解析器任务清单"),
    ]
    if scan_dir and (scan_dir / "parser_results.json").exists():
        trace_items.append(("parser_results.json", common.href(scan_dir / "parser_results.json"), "兼容/调试用聚合解析器结果"))
    elif scan_dir and (scan_dir / "review" / "parser_evidence.tsv").exists():
        trace_items.append(("review/parser_evidence.tsv", common.href(scan_dir / "review" / "parser_evidence.tsv"), "逐文件解析器证据索引"))
    trace_links = ui.trace_link_list(trace_items)
    return ui.collapsible_panel(
        "证据入口 / 调试",
        "",
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
        + catalog._scroll_table(
            ["指标", "数值"],
            _metric_rows(model),
            "暂无自动对比结果；请先运行 lg cmp。只有缺少扫描证据时，才选择缺失补扫。",
            "metric-scroll",
        )
        + "</details>"
        "<details><summary>完整变化文件入口</summary>"
        "<div class='quality-note'><b>减噪策略</b> 完整逐文件变化不再内嵌到详情页；请打开 file_diff.json 查看全量清单。主页面仅保留重点变化文件。</div>"
        + catalog._scroll_table(
            ["范围", "数量", "说明"],
            _file_change_artifact_rows(model),
            "暂无文件级 diff 摘要。请先运行 lg cmp；需要单文件深度核对时再运行 lg fd。",
            "change-summary-scroll",
        )
        + "</details>"
        "<details><summary>摘要级 / 元数据级证据摘要</summary>"
        + "<div class='quality-note'><b>证据分层</b> 摘要级证据 / 元数据级证据是正常证据策略，不自动代表不完整；这里按类型聚合，完整文件列表见 file_diff.json。</div>"
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
        "完整文件、扫描和对比证据。",
        body,
        open=False,
    )


def _review_evidence_sidebar(model: Mapping[str, Any], version: Mapping[str, Any], *, evidence_href: str = "#file-structure") -> str:
    """Render compact secondary evidence without importing scan debug payloads."""
    scan_evidence = _as_mapping(model.get("scan_evidence"))
    scan_context = _as_mapping(model.get("scan_context"))
    comparison_context = _as_mapping(model.get("comparison_context"))
    raw_scan_status = str(scan_context.get("scan_status") or "").upper()
    scan_has_files = _scan_evidence_has_files(scan_evidence)
    if not raw_scan_status:
        raw_scan_status = "SCANNED" if scan_has_files else "SCAN_EMPTY" if scan_context.get("scan_id") else "NOT_SCANNED"
    scan_status_label = {
        "SCAN_EMPTY": "扫描为空",
        "SCAN_PASS": "扫描通过",
        "SCANNED": "已扫描",
        "NOT_SCANNED": "未扫描",
        "FAILED": "扫描失败",
    }.get(raw_scan_status, ui.status_label(raw_scan_status))
    scan_badge = ui.badge("EMPTY", scan_status_label) if raw_scan_status == "SCAN_EMPTY" else ui.badge(raw_scan_status, scan_status_label)
    raw_diff_status = str(comparison_context.get("diff_status") or model.get("status") or "UNKNOWN").upper()
    diff_status_label = {
        "SAME": "无变化",
        "CHANGED": "有变化",
        "NEEDS_BASE_CONFIRM": "需确认基准版",
        "DIFF_NOT_RUN": "尚未对比",
        "NO_DIFF_SUMMARY": "缺少对比摘要",
        "FIRST_VERSION_REVIEW": "首版审查",
    }.get(raw_diff_status, ui.status_label(raw_diff_status))
    diff_badge_status = "PASS" if raw_diff_status == "SAME" else "WARNING" if raw_diff_status not in {"PASS", "READY", "OK"} else "PASS"
    diff_badge = ui.badge(diff_badge_status, diff_status_label)
    scan_has_no_files = bool(scan_context.get("scan_id")) and not scan_has_files
    scan_hint = {
        "SCAN_EMPTY": "未获得可用的交付文件清单",
        "EMPTY": "未获得可用的交付文件清单",
        "NOT_SCANNED": "未找到扫描证据",
        "FAILED": "扫描失败；请查看扫描错误",
    }.get(
        raw_scan_status,
        "未获得可用的交付文件清单"
        if scan_has_no_files
        else "扫描结果已记录"
        if scan_context.get("scan_id")
        else "未找到扫描证据",
    )
    context_body = ui.metric_grid(
        [
            ("扫描", scan_status_label, scan_hint, "WARNING" if raw_scan_status in {"SCAN_EMPTY", "NOT_SCANNED", "FAILED"} else "PASS"),
            ("对比", diff_status_label, comparison_context.get("base_version") or "未建立基准", diff_badge_status),
            ("未知", _scan_evidence_unknown_total(scan_evidence), "需要分类" if _scan_evidence_unknown_total(scan_evidence) else "无未知文件", "WARNING" if _scan_evidence_unknown_total(scan_evidence) else "PASS"),
        ]
    )
    ip_model = _as_mapping(model.get("ip_user_view_model"))
    completeness = _as_mapping(ip_model.get("delivery_completeness"))
    completeness_status = str(completeness.get("status") or "UNKNOWN").upper()
    if completeness_status != "UNKNOWN":
        required_total = _as_int(completeness.get("required_total"))
        required_present = _as_int(completeness.get("required_present"))
        missing = [str(item) for item in completeness.get("missing", []) or []]
        incomplete = bool(missing) or (required_total > 0 and required_present < required_total) or completeness_status in {"MISSING", "INCOMPLETE", "BLOCKED"}
        if not incomplete:
            missing = []
        if incomplete:
            missing_text = "、".join(missing[:3]) if missing else "未满足配置要求"
            if len(missing) > 3:
                missing_text += f" 等 {len(missing)} 项"
            completeness_value = (
                f"{required_present} / {required_total}"
                if required_total
                else "待确认"
            )
            completeness_hint = f"缺失：{missing_text}"
            context_body += (
                f"<div class='fact-summary-row'><b>交付完整度</b><span>{ui.esc(completeness_value)}；{ui.esc(completeness_hint)}</span></div>"
            )
    evidence_rows = [
        f"<tr><td>扫描结果</td><td>{scan_badge}</td><td>文件清单和扫描摘要</td></tr>",
        f"<tr><td>版本对比</td><td>{diff_badge}</td><td>主变化表</td></tr>",
        f"<tr><td>重点文件</td><td>{ui.esc(_as_int(model.get('lane_counts', {}).get('recommended_file_diff')))}</td><td>重点变化文件表</td></tr>",
        f"<tr><td>文件结构</td><td>当前交付 {_scan_evidence_file_total(scan_evidence)}</td><td>{ui.button('查看文件树', evidence_href, 'secondary', disabled=not evidence_href)}</td></tr>",
    ]
    evidence_body = ui.table(["证据类别", "状态", "入口"], evidence_rows, "暂无证据摘要")
    return (
        "<div class='review-sidebar-stack'>"
        + _render_freshness_panel(model)
        + '<div data-section="evidence-status">'
        + ui.panel("检查记录", "扫描与对比的完成情况；未识别类型的文件仍需核对。", context_body)
        + "</div>"
        + _static_domain_review_panel(version, model)
        + _review_gate_summary_panel(version, model)
        + ui.collapsible_panel("原始证据", "扫描、对比和文件结构的追溯入口。", evidence_body, open=False)
        + "</div>"
    )


def _render_freshness_panel(model: Mapping[str, Any]) -> str:
    render_context = _as_mapping(model.get("render_context"))
    review_context = _as_mapping(model.get("review_context"))
    freshness = _as_mapping(review_context.get("freshness"))
    scan_context = _as_mapping(model.get("scan_context"))
    comparison_context = _as_mapping(model.get("comparison_context"))
    generated_at = str(render_context.get("generated_at") or "-")
    scan_status = str(scan_context.get("scan_status") or "NOT_SCANNED").upper()
    diff_status = str(comparison_context.get("diff_status") or model.get("status") or "UNKNOWN").upper()
    context_status = str(freshness.get("status") or "PARTIAL").upper()
    rows = [
        ("报告生成", generated_at, "报告反映生成时的检查结果。"),
        ("本版扫描", ui.status_label(scan_status), "检查深度见视图变化表和代表文件核查。"),
        ("版本对比", ui.status_label(diff_status), "基准版本及选择依据见版本摘要。"),
        ("检查限制", '已有结果可能不齐全' if context_status != 'FRESH' else '已有结果已记录', "本报告不保证生成后源文件没有再次变更。"),
    ]
    return ui.collapsible_panel(
        "报告来源",
        f"生成于 {generated_at}",
        "<div class='refresh-status-list'>"
        + "".join(
            "<div class='refresh-status-row'><b>{label}</b><strong>{value}</strong><span>{hint}</span></div>".format(
                label=ui.esc(label),
                value=ui.esc(value),
                hint=ui.esc(hint),
            )
            for label, value, hint in rows
        )
        + "</div>",
        open=False,
    )


def render_version_update_detail_panel(model: Mapping[str, Any], *, href_base: Path | None = None) -> str:
    base_version = model.get("base_version") or "-"
    base_ref = model.get("base_ref") or "NEEDS_BASE_CONFIRM"
    review_model = _as_mapping(model.get("version_review_model")) or build_version_review_model(model)
    ip_model = _as_mapping(model.get("ip_user_view_model")) or _as_mapping(review_model.get("ip_user_view"))
    first_version = str(model.get("review_mode") or "") == "first_version"
    focus_rows = _focus_file_change_rows(model)
    focus_changes = (
        '<details data-section="focus-files" class="detail-fold review-fold">'
        "<summary>重点变化文件</summary>"
        "<div class='quality-note'>仅列出 P0/P1/审查文件，最多 120 行；用于快速定位变化，不替代文件结构。</div>"
        + catalog._scroll_table(
            ["变化", "类型 / 视图", "路径 / 文件", "审查级别", "匹配状态", "建议 / 说明"],
            focus_rows,
            "暂无重点变化文件。",
            "focus-change-scroll",
        )
        + "</details>"
    )
    if first_version:
        panel_title = "视图覆盖矩阵"
        panel_subtitle = "当前无可比基准版，展示本次交付包自身的视图覆盖和文件证据。"
    elif str(model.get("status") or "").upper() in {"DIFF_NOT_RUN", "NO_DIFF_SUMMARY", "NEEDS_BASE_CONFIRM"}:
        panel_title = "视图变化矩阵"
        panel_subtitle = "对比证据尚未完成；空表不代表没有变化，请先补齐可信对比。"
    else:
        panel_title = "视图变化矩阵"
        panel_subtitle = f"相对 {_cn_base_ref(base_ref)} / {base_version}；仅显示有变化或待分类的视图。"
    return ui.panel(
        panel_title,
        panel_subtitle,
        '<section data-section="view-delta">'
        + render_ip_user_view({**ip_model, 'representative_files': model.get('representative_files', [])}, href_base=href_base, show_pending=False)
        + "</section>"
        + focus_changes,
    )

def export_current_lib_diff_markdown(model: Mapping[str, Any], out_md: str | Path) -> str:
    from lib_guard.render.version_engineering import engineering_markdown
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
        "# 当前库变化",
        "",
        engineering_markdown(model.get('engineering_report') or {}),
        "",
        f"{model.get('headline') or '-'}",
        "",
        f"{model.get('confidence_note') or '-'}",
        "",
        "## 审查上下文",
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
        "## 对比上下文",
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
        "## 汇总指标",
        "",
    ]
    for item in model.get("summary_metrics", []) or []:
        if isinstance(item, Mapping):
            lines.append(f"- {item.get('metric')}: {item.get('value')}")
    lines.extend(["", "## 文件变化", ""])
    for item in model.get("file_changes", []) or []:
        if isinstance(item, Mapping):
            lines.append(f"- [{item.get('review_lane')}] {item.get('change')} {item.get('file_type')} {item.get('path')}")
    lines.extend(["", "## 重点文件审查", ""])
    for item in model.get("recommended_file_diff", []) or []:
        if isinstance(item, Mapping):
            lines.append(f"- [{item.get('review_lane')}] {item.get('change')} {item.get('file_type')} {item.get('path')}")
    lines.extend(["", "## 摘要级证据", ""])
    for item in model.get("summary_only_reviewed", []) or []:
        if isinstance(item, Mapping):
            lines.append(f"- [{item.get('review_lane')}] {item.get('change')} {item.get('file_type')} {item.get('path')} - {item.get('hint')}")
    lines.extend(["", "## 元数据级证据", ""])
    for item in model.get("metadata_only_reviewed", []) or []:
        if isinstance(item, Mapping):
            lines.append(f"- [{item.get('review_lane')}] {item.get('change')} {item.get('file_type')} {item.get('path')} - {item.get('hint')}")
    lines.extend(["", "## 视图变化", ""])
    view_diff = _as_mapping(model.get("view_diff"))
    for item in view_diff.get("views", []) or []:
        if isinstance(item, Mapping):
            lines.append(f"- {item.get('view') or item.get('file_type')}: {item.get('status')}")
    if not view_diff.get("views"):
        lines.append(f"- summary: {view_diff.get('summary') or {}}")
    lines.extend(["", "## 文件类型变化", ""])
    type_diff = _as_mapping(model.get("type_diff"))
    for file_type, item in (_as_mapping(type_diff.get("by_type"))).items():
        if isinstance(item, Mapping):
            lines.append(f"- {file_type}: {item.get('status')} changed={item.get('changed_count', 0)} added={item.get('added_count', 0)} removed={item.get('removed_count', 0)}")
    if not type_diff.get("by_type"):
        lines.append(f"- summary: {type_diff.get('summary') or {}}")
    lines.extend(["", "## 发布准备变化", ""])
    lines.append(f"- {model.get('release_readiness_diff') or {}}")
    lines.extend(["", "## 对比问题", ""])
    for item in (_as_mapping(model.get("diff_issues"))).get("issues", []) or []:
        if isinstance(item, Mapping):
            lines.append(f"- {item.get('severity', '-')}: {item.get('category', '-')} - {item.get('title') or item.get('message') or '-'}")
    lines.extend(["", "## 建议动作", ""])
    for action in model.get("recommended_actions", []) or []:
        lines.append(f"- {action}")
    if model.get("release_notes"):
        lines.extend(["", "## 发布说明", ""])
        for item in model.get("release_notes", []) or []:
            if isinstance(item, Mapping):
                lines.append(f"- {item.get('path')}: {item.get('summary')}")
    report = _as_mapping(model.get("review_report"))
    if report:
        lines.extend(["", "## 结构化审查报告", ""])
        for section in (
            "base_analysis", "delivery_analysis", "view_delta_analysis",
            "focus_file_analysis", "unknown_analysis", "evidence_assessment",
        ):
            value = _as_mapping(report.get(section))
            lines.append(f"### {section}")
            for key, item in value.items():
                if key in {"rows", "items", "examples"}:
                    continue
                lines.append(f"- {key}: {item}")
        for label, values in (("待回答问题", report.get("open_questions")), ("建议动作", report.get("recommended_actions"))):
            lines.extend(["", f"### {label}"])
            for item in values or []:
                lines.append(f"- {item}")
    if model.get('representative_files'):
        lines.extend(['', '## 代表文件深度核查', '', '仅代表人工选定文件，不代表整个视图通过。', ''])
        for row in model['representative_files']:
            lines.extend([f"### {row['file_type']}", f"- 旧文件：{row['old_file']}", f"- 新文件：{row['new_file']}", f"- 结构字段变化：{row['change_count']} 项；{row['freshness']}", f"- 人工备注：{row['note'] or '未填写'}", f"- 详细证据：{row['evidence_dir']}", ''])
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return str(path)


def render_version_detail_page(
    out: str | Path,
    lib: Mapping[str, Any],
    version: Mapping[str, Any],
    *,
    export_markdown: bool = False,
    catalog_navigation_available: bool = True,
) -> str:
    out_path = Path(out)
    lib_id = _library_id(lib)
    version_id = _version_id(version)
    safe_lib = _library_report_slug(lib)
    safe_ver = common.safe(version_id)
    page = out_path / "libraries" / safe_lib / "versions" / safe_ver / "index.html"
    model = build_version_update_detail_model(out_path, lib, version)
    stale_evidence_page = page.parent / "file-evidence.html"
    md_path = page.parent / "current_lib_diff.md"
    model["markdown_export_path"] = str(md_path)
    if export_markdown:
        export_current_lib_diff_markdown(model, md_path)
    from lib_guard.render.version_file_checks import render_file_checks
    from lib_guard.render.version_semantic_checks import render_semantic_check
    from lib_guard.render.version_engineering import render_engineering_report
    body = (
        _version_detail_styles()
        + "<main class='version-main'>"
        + _version_update_note_panel(model)
        + _reader_summary(model, version)
        + render_engineering_report(model['engineering_report'], page)
        + "<details class='reader-file-sources' data-section='file-sources'><summary>文件与来源</summary>"
        + "<div class='review-top-layout'>"
        + "<section class='review-top-matrix'>"
        + render_version_update_detail_panel(model, href_base=page.parent)
        + "</section>"
        + "<section class='review-top-summary'>"
        + _version_overview_panel(model)
        + "</section>"
        + "</div>"
        + render_review_report(_as_mapping(model.get("review_report")))
        + render_semantic_check(model.get('semantic_check', {}), page)
        + render_file_checks(model.get('representative_files', []), model.get('lib_db_correspondence', {}), page)
        + "<div class='review-layout'>"
        + "<section class='review-primary-column'>"
        + render_version_file_evidence_section(model)
        + "</section>"
        + "<aside class='review-secondary-column'>"
        + _review_evidence_sidebar(model, version)
        + "</aside>"
        + "</div>"
        + "</details>"
        + "</main>"
    )
    ip_model = _as_mapping(model.get("ip_user_view_model"))
    decision_model = _as_mapping(ip_model.get("decision"))
    usage_decision = str(decision_model.get("status") or "BLOCKED")
    usage_decision_label = str(decision_model.get("label") or "暂不可判断")
    if catalog_navigation_available:
        catalog_nav = "<a href='../../../../index.html'>总目录</a><a href='../../index.html'>库概览</a>"
    else:
        catalog_nav = (
            "<span class='nav-unavailable' title='单版本刷新不会重建目录页'>总目录（刷新目录后可用）</span>"
            "<span class='nav-unavailable' title='单版本刷新不会重建目录页'>库概览（刷新目录后可用）</span>"
        )
    html = ui.review_page_shell(
        f"{lib.get('display_name') or lib_id} / {version_id}",
        "版本报告",
        "交付内容、版本变化与文件核查结果。",
        catalog_browser_styles() + body,
        decision=usage_decision,
        decision_label=usage_decision_label,
        nav=catalog_nav + "<a class='active' href='#'>版本详情</a><a href='#engineering-content'>库内容</a><a href='#engineering-results'>工程检查</a><a href='#file-structure' onclick=\"document.querySelector('.reader-file-sources').open=true\">文件结构</a>",
        meta=ui.compact_meta([("库", lib_id), ("版本", version_id), ("基准版", model.get("base_version") or "-")]),
    )
    from lib_guard.atomic import atomic_write_text
    atomic_write_text(page, html)
    if stale_evidence_page.is_file():
        stale_evidence_page.unlink()
    return str(page)
