"""Version detail report renderer.

This module owns the version detail surface and the current-library update
detail model. The Markdown export is evidence generated from the same model as
the HTML panel; the HTML renderer never reads Markdown.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from lib_guard.project_config import BINARY_METADATA_ONLY_TYPES, DEFAULT_FILE_DIFF_TYPES, SUMMARY_ONLY_TYPES
from lib_guard.render.catalog_workspace_report import catalog_browser_styles
from lib_guard.render import product_theme as ui


P0_REVIEW_TYPES = {"lef", "cdl", "spice", "sp"}
P1_REVIEW_TYPES = {"sdc", "upf", "cpf", "waiver", "ibis", "pwl", "snp", "touchstone", "cpm"}
STANDARD_BASE_REFS = {"current_effective", "previous_effective", "explicit"}
FALLBACK_BASE_REFS = {"adjacent_fallback", "recorded_base", "recorded_base_fallback", "unknown"}


def _cr():
    from lib_guard.render import catalog_report as cr

    return cr


def _version_id(version: Mapping[str, Any]) -> str:
    return str(version.get("version_id") or version.get("version") or "version")


def _library_id(lib: Mapping[str, Any]) -> str:
    return str(lib.get("library_id") or lib.get("display_name") or lib.get("library_name") or "library")


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
    if explicit and explicit != "-":
        return explicit
    suffix = Path(path).suffix.lower().lstrip(".")
    return {
        "v": "verilog",
        "sv": "systemverilog",
        "sp": "cdl",
        "spi": "cdl",
        "lib": "liberty",
    }.get(suffix, suffix or "-")


def _review_lane(file_type: str) -> tuple[str, str]:
    key = str(file_type or "").lower()
    if key in SUMMARY_ONLY_TYPES:
        return "Summary-only", "摘要级审查；默认不生成文件级 Diff 命令"
    if key in BINARY_METADATA_ONLY_TYPES:
        return "Metadata-only", "metadata-only 审查；默认不生成文件级 Diff 命令"
    if key in P0_REVIEW_TYPES:
        return "P0", "建议优先做文件级 Diff"
    if key in P1_REVIEW_TYPES:
        return "P1", "建议定向审查"
    return "Review", "按需人工检查"


def _cn_change_kind(value: Any) -> str:
    text = str(value or "").lower()
    if text == "added":
        return "新增"
    if text == "removed":
        return "删除"
    if text == "changed":
        return "变化"
    return text or "-"


def _iter_file_changes(file_diff: Mapping[str, Any], *, raw_path: Any = None) -> list[dict[str, Any]]:
    cr = _cr()
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
                path = cr._relative_display_path(item.get("path") or item.get("relpath") or item.get("file") or "-", base=raw_path)
                file_type = _infer_file_type(path, item.get("file_type") or item.get("type"))
            else:
                path = cr._relative_display_path(item, base=raw_path)
                file_type = _infer_file_type(path)
            lane, hint = _review_lane(file_type)
            changes.append(
                {
                    "change": kind,
                    "file_type": file_type,
                    "path": path,
                    "review_lane": lane,
                    "hint": hint,
                }
            )
    return changes


def _select_base(version: Mapping[str, Any]) -> tuple[str, str, str]:
    diff = _as_mapping(version.get("diff"))
    lineage = _as_mapping(version.get("lineage"))
    explicit = (
        version.get("explicit_base_version")
        or diff.get("explicit_base_version")
        or lineage.get("explicit_base_version")
    )
    if explicit:
        return "explicit", str(explicit), "catalog_recorded_base"
    for key in ["current_effective", "current_effective_ref", "latest_effective_ref"]:
        value = version.get(key) or diff.get(key) or lineage.get(key)
        if value and not isinstance(value, bool):
            return "current_effective", str(value), key
    previous = version.get("previous_effective_version") or version.get("parent_version") or lineage.get("parent_candidate")
    if previous:
        return "previous_effective", str(previous), "previous_effective_version"
    diff_base = diff.get("base_version")
    diff_base_source = str(diff.get("base_source") or diff.get("base_version_source") or "").lower()
    diff_kind = str(diff.get("kind") or diff.get("diff_kind") or "").lower()
    if diff_base and (diff_base_source in {"explicit", "current_effective"} or diff_kind == "current_library_diff"):
        base_ref = "current_effective" if diff_base_source == "current_effective" or diff_kind == "current_library_diff" else "explicit"
        return base_ref, str(diff_base), f"diff.base_version:{diff_base_source or diff_kind}"
    cr = _cr()
    full_base = cr._base_full_version(version)
    if full_base:
        return "base_full", str(full_base), "base_full_version"
    adjacent = diff.get("adjacent_old_version")
    if adjacent:
        return "adjacent_fallback", str(adjacent), "adjacent_old_version"
    if diff_base:
        return "recorded_base", str(diff_base), "diff.base_version:fallback"
    return "NEEDS_BASE_CONFIRM", "", "missing_base"


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
        return "无法确定 base；请先确认 current_effective 或 previous_effective。"
    if base_ref in STANDARD_BASE_REFS:
        return "Base 已确认；该结果可作为标准更新详情。"
    return "该结果不是标准 current-effective 更新详情，仅供手动 compare/debug；release 前请确认 base。"


def _path_if_exists(value: Any) -> Path | None:
    if not value:
        return None
    path = Path(str(value))
    return path if path.exists() else None


def _select_diff_dir(version: Mapping[str, Any], *, base_ref: str, base_version: str) -> Path | None:
    diff = _as_mapping(version.get("diff"))
    keyed_candidates: list[tuple[str, tuple[str, ...]]] = [
        ("explicit", ("base_diff_dir", "current_effective_diff_dir", "diff_dir")),
        ("current_effective", ("current_effective_diff_dir", "base_diff_dir", "diff_dir")),
        ("previous_effective", ("previous_effective_diff_dir", "current_effective_diff_dir", "base_diff_dir", "diff_dir")),
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
    return None


def _comparison_semantics(version: Mapping[str, Any]) -> tuple[str, str, str]:
    cr = _cr()
    package = cr._package_type(version)
    node_type = cr._node_package_type(version)
    if package in {"PARTIAL_UPDATE", "PARTIAL", "HOTFIX", "DOC_UPDATE", "DOC_ONLY"} or node_type in {"partial", "hotfix", "doc"}:
        return "incremental", "incremental compare", "out_of_scope_missing"
    return "full", "full compare", "real_delete"


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
    library = _library_name(lib)
    version_id = _version_id(version)
    commands: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in changes:
        lane = str(item.get("review_lane") or "")
        if lane not in {"P0", "P1"}:
            continue
        if str(item.get("file_type") or "").lower() not in DEFAULT_FILE_DIFF_TYPES:
            continue
        path = str(item.get("path") or "")
        if not path or path in seen:
            continue
        seen.add(path)
        base = f" --base {base_version}" if base_version else ""
        commands.append(
            {
                "lane": lane,
                "path": path,
                "command": f"$PROJ/scripts/lg.csh fd {library} {version_id} {path}{base}",
            }
        )
    return commands


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


def _version_update_headline(base_ref: str, changed_files: int, recommended_count: int, reviewed_count: int) -> str:
    return (
        f"当前版本相对 {base_ref or 'NEEDS_BASE_CONFIRM'} 有 {changed_files} 个变化文件，"
        f"{recommended_count} 个建议下钻，{reviewed_count} 个已按 Summary/Metadata-only 审查。"
    )


def _version_update_confidence_note(model: Mapping[str, Any]) -> str:
    return (
        f"Base source={model.get('base_ref') or '-'}"
        f" ref={model.get('base_version') or '-'}"
        f" source_detail={model.get('base_source') or '-'}"
        f"; comparison_semantics={model.get('comparison_semantics') or '-'}"
        f"; delete_semantics={model.get('delete_semantics') or '-'}"
    )


def _primary_next_action(status: str, recommended_count: int, command_count: int) -> dict[str, Any]:
    if str(status or "").upper() == "NEEDS_BASE_CONFIRM":
        return {
            "kind": "base_confirm_required",
            "label": "Confirm base before review",
            "command_count": 0,
        }
    if recommended_count > 0:
        return {
            "kind": "file_diff_recommended",
            "label": "Run recommended File Diff",
            "command_count": command_count,
        }
    return {
        "kind": "review_evidence",
        "label": "Review evidence",
        "command_count": 0,
    }


def build_version_update_detail_model(out: str | Path, lib: Mapping[str, Any], version: Mapping[str, Any]) -> dict[str, Any]:
    cr = _cr()
    out_path = Path(out)
    lib_id = _library_id(lib)
    version_id = _version_id(version)
    safe_lib = cr._safe(lib_id)
    safe_ver = cr._safe(version_id)
    base_ref, base_version, base_source = _select_base(version)
    comparison_semantics, compare_strategy, delete_semantics = _comparison_semantics(version)
    diff_dir = _select_diff_dir(version, base_ref=base_ref, base_version=base_version)
    summary = dict(cr._version_diff_summary(diff_dir))
    file_diff = dict(cr._version_file_diff(diff_dir))
    view_diff = dict(cr._version_diff_json(diff_dir, "view_diff.json"))
    type_diff = dict(cr._version_diff_json(diff_dir, "type_diff.json"))
    release_readiness_diff = dict(cr._version_diff_json(diff_dir, "release_readiness_diff.json"))
    release_evidence_diff = dict(cr._version_diff_json(diff_dir, "release_evidence_diff.json"))
    diff_issues = dict(cr._version_diff_json(diff_dir, "diff_issues.json"))
    file_changes = _iter_file_changes(file_diff, raw_path=version.get("raw_path"))
    changed_files = summary.get("changed_files")
    if changed_files is None:
        changed_files = len(file_changes)
    summary_status = str(summary.get("status") or "").upper()
    if base_ref == "NEEDS_BASE_CONFIRM":
        status = "NEEDS_BASE_CONFIRM"
    elif not summary and not diff_dir:
        status = "DIFF_NOT_RUN"
    elif summary_status in {"DIFF", "CHANGED"} or _as_int(changed_files):
        status = "CHANGED"
    else:
        status = summary_status or "SAME"
    release_notes = cr._version_release_notes(version.get("raw_path"))
    recommended_file_diff, summary_only_reviewed, metadata_only_reviewed = _group_file_changes_by_review_mode(file_changes)
    metadata_only = summary_only_reviewed + metadata_only_reviewed
    commands = _file_diff_commands(lib, version, base_version, file_changes)
    recommended_count = len(recommended_file_diff)
    reviewed_count = len(summary_only_reviewed) + len(metadata_only_reviewed)
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
        "library_name": _library_name(lib),
        "version_id": version_id,
        "target_version": version_id,
        "base_ref": base_ref,
        "base_version": base_version,
        "base_source": base_source,
        "base_trust_status": _base_trust_status(base_ref),
        "base_trust_note": _base_trust_note(base_ref),
        "package_type": cr._package_type(version),
        "compare_strategy": compare_strategy,
        "comparison_semantics": comparison_semantics,
        "delete_semantics": delete_semantics,
        "status": status,
        "diff_dir": str(diff_dir or ""),
        "diff_summary_path": str(diff_dir / "diff_summary.json") if diff_dir else "",
        "file_diff_path": str(diff_dir / "file_diff.json") if diff_dir else "",
        "markdown_export_path": str(md_path),
        "diff_summary": summary,
        "view_diff": view_diff,
        "type_diff": type_diff,
        "release_readiness_diff": release_readiness_diff,
        "release_evidence_diff": release_evidence_diff,
        "diff_issues": diff_issues,
        "file_diff": file_diff,
        "changed_files": _as_int(changed_files),
        "summary_metrics": _summary_metrics(summary),
        "file_changes": file_changes,
        "recommended_file_diff": recommended_file_diff,
        "summary_only_reviewed": summary_only_reviewed,
        "metadata_only_reviewed": metadata_only_reviewed,
        "release_notes": release_notes,
        "recommended_actions": list(summary.get("recommended_actions", []) or []),
        "file_diff_recommendations": commands,
        "metadata_only_changes": metadata_only,
        "trace_links": trace_links,
    }
    model["headline"] = _version_update_headline(base_ref, _as_int(changed_files), recommended_count, reviewed_count)
    model["confidence_note"] = _version_update_confidence_note(model)
    model["primary_next_action"] = _primary_next_action(status, recommended_count, len(commands))
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
            f"<td>{ui.badge(item.get('review_lane') or 'Review', item.get('review_lane') or 'Review')}</td>"
            f"<td>{ui.esc(item.get('hint') or '-')}</td>"
            "</tr>"
        )
    return rows


def _file_change_rows(model: Mapping[str, Any]) -> list[str]:
    return _file_change_rows_for(model.get("file_changes", []))


def _release_note_rows(model: Mapping[str, Any]) -> list[str]:
    cr = _cr()
    rows: list[str] = []
    for item in model.get("release_notes", []) or []:
        if not isinstance(item, Mapping):
            continue
        rows.append(
            "<tr>"
            f"<td><code>{ui.esc(cr._relative_display_path(item.get('path') or '-'))}</code></td>"
            f"<td>{ui.esc(item.get('summary') or '-')}</td>"
            "</tr>"
        )
    return rows


def _recommended_action_rows(model: Mapping[str, Any]) -> list[str]:
    return [f"<tr><td>{ui.esc(action)}</td></tr>" for action in model.get("recommended_actions", []) or []]


def _command_rows(model: Mapping[str, Any]) -> list[str]:
    rows: list[str] = []
    for item in model.get("file_diff_recommendations", []) or []:
        if not isinstance(item, Mapping):
            continue
        rows.append(
            "<tr>"
            f"<td>{ui.badge(item.get('lane') or 'Review')}</td>"
            f"<td><code>{ui.esc(item.get('path') or '-')}</code></td>"
            f"<td>{ui.command_chip(item.get('command'), label='复制')}</td>"
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
.version-dashboard{display:grid;grid-template-columns:minmax(0,1fr) 360px;gap:18px;align-items:start}.version-main,.version-side{display:flex;flex-direction:column;gap:18px}.version-side{position:sticky;top:18px}.version-overview{border:1px solid var(--line);border-radius:14px;background:#fff;box-shadow:var(--shadow);padding:18px 20px;margin-bottom:18px}.overview-head{display:flex;justify-content:space-between;gap:14px;align-items:flex-start;border-bottom:1px solid var(--line);padding-bottom:14px;margin-bottom:14px}.overview-title h2{margin:0 0 4px;font-size:20px}.overview-title p{font-size:13px}.overview-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px}.overview-cell{border:1px solid var(--line);border-radius:10px;background:#f8fafc;padding:10px 12px}.overview-cell b{display:block;font-size:12px;color:#667085}.overview-cell em{display:block;font-style:normal;font-weight:800;color:#172033;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.version-update-lead{border:1px solid var(--line);border-radius:10px;background:#f8fafc;padding:12px 14px;margin-bottom:12px}.version-update-lead b{display:block;color:#172033;margin-bottom:5px}.version-update-lead p{margin:0 0 10px;color:#667085;font-size:13px}.primary-action-line{display:flex;gap:8px;align-items:center;flex-wrap:wrap}.primary-action-line em{font-style:normal;color:#667085;font-size:12px}.base-trust-context{border:1px solid var(--line);border-radius:10px;background:#fff;padding:12px 14px;margin-bottom:12px}.base-trust-head{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin-bottom:8px}.base-trust-head b{color:#344054}.base-trust-context p{margin:0 0 10px;color:#667085;font-size:13px}.context-list{display:flex;flex-direction:column;gap:8px}.context-row{border:1px solid var(--line);border-radius:9px;background:#f8fafc;padding:9px 10px}.context-row b{display:block;font-size:12px;color:#667085}.context-row code,.context-row em{display:block;font-style:normal;color:#344054;overflow-wrap:anywhere}.section-label{margin:18px 0 8px;font-weight:900;color:#344054}.empty-guidance{border:1px dashed #d3dae6;border-radius:10px;background:#fbfcff;color:#667085;padding:12px 14px;margin:10px 0}.empty-guidance b{display:block;color:#344054;margin-bottom:3px}.quality-note{border:1px solid var(--line);border-radius:10px;background:#f8fafc;padding:12px 14px;margin:12px 0;color:#667085}.quality-note b{color:#344054}.panel-body>h3{font-size:14px;margin:18px 0 8px;color:#344054}.version-scroll-table.change-scroll td:nth-child(5){min-width:220px}.version-scroll-table.change-scroll td:nth-child(3) code{min-width:860px}.version-scroll-table.corner-detail-scroll{max-height:320px}.version-scroll-table.corner-detail-scroll table{min-width:980px}.version-scroll-table.unknown-detail-scroll{max-height:260px}.version-scroll-table.unknown-detail-scroll table{min-width:860px}.detail-fold.review-fold{border:1px solid var(--line);border-radius:10px;background:#fbfcff;padding:10px 12px;margin-top:12px}.detail-fold.review-fold summary{color:#344054}.raw-scan-note{border-left:4px solid #a15c00;background:#fff7e8;border-radius:10px;padding:12px 14px;margin:12px 0;color:#664000}.raw-scan-note b{display:block;color:#4f2f00}.side-panel .panel{box-shadow:none}.evidence-actions{display:grid;gap:8px}.evidence-actions .btn{justify-content:flex-start}@media(max-width:1100px){.version-dashboard{grid-template-columns:1fr}.version-side{position:static}.overview-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}@media(max-width:640px){.overview-head{display:block}.overview-grid{grid-template-columns:1fr}.version-dashboard{gap:12px}.panel-head{display:block}.panel-actions{margin-top:10px}.version-scroll-table.change-scroll{height:360px}}
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
        "本页 Raw Scan 只统计本次交付内容；继承文件请查看 effective 或 base 视图。"
        "</div>"
    )


def _version_overview_panel(
    lib_id: str,
    version_id: str,
    version: Mapping[str, Any],
    model: Mapping[str, Any],
    *,
    relation: str,
    parser_task_count: int,
    count_only_total: int,
    file_total: int,
) -> str:
    decision = model.get("status") or version.get("overall_status") or "REVIEW"
    review_text = "可审查"
    if str(decision).upper() in {"NEEDS_BASE_CONFIRM", "DIFF_NOT_RUN", "SCAN_BLOCKED", "DIFF_BLOCKED"}:
        review_text = "需补证据"
    elif str(decision).upper() in {"CHANGED", "DIFF", "REVIEW"}:
        review_text = "有变化，需审查"
    return (
        "<section class='version-overview'>"
        "<div class='overview-head'>"
        f"<div class='overview-title'><h2>版本审查总览</h2><p>先确认状态、Base/Target 和证据状态，再进入变化文件和 Parser 细节。</p></div>{ui.badge(decision, review_text)}</div>"
        "<div class='overview-grid'>"
        f"<div class='overview-cell'><b>库</b><em title='{ui.esc(lib_id)}'>{ui.esc(lib_id)}</em></div>"
        f"<div class='overview-cell'><b>版本</b><em title='{ui.esc(version_id)}'>{ui.esc(version_id)}</em></div>"
        f"<div class='overview-cell'><b>Base → Target</b><em title='{ui.esc(model.get('base_version') or '-')}'>{ui.esc(model.get('base_ref') or '-')} → 当前版本</em></div>"
        f"<div class='overview-cell'><b>证据</b><em>{ui.esc(file_total)} 文件 / {ui.esc(parser_task_count)} Parser / {ui.esc(count_only_total)} 大文件</em></div>"
        f"<div class='overview-cell'><b>Scan</b><em>{ui.esc(ui.status_label(version.get('scan_status')))}</em></div>"
        f"<div class='overview-cell'><b>Diff</b><em>{ui.esc(ui.status_label(version.get('diff_status') or model.get('status')))}</em></div>"
        f"<div class='overview-cell'><b>关系</b><em>{ui.esc(_cr()._relation_label(relation))}</em></div>"
        f"<div class='overview-cell'><b>包类型</b><em>{ui.esc(model.get('package_type') or '-')}</em></div>"
        "</div></section>"
    )


def _version_context_panel(
    out_path: Path,
    safe_lib: str,
    lib_id: str,
    version_id: str,
    version: Mapping[str, Any],
    model: Mapping[str, Any],
    scan_dir: Path | None,
) -> str:
    cr = _cr()
    rows = [
        ("库", lib_id),
        ("版本", version_id),
        ("Base", f"{model.get('base_ref') or '-'} / {model.get('base_version') or '-'}"),
        ("对比语义", _cn_semantics(model.get("comparison_semantics"))),
        ("删除语义", _cn_delete_semantics(model.get("delete_semantics"))),
        ("scan_id", (version.get("scan") or {}).get("scan_id") or version.get("scan_id") or "-"),
        ("Raw Relpath", cr._raw_relpath(version.get("raw_path"))),
    ]
    body = "<div class='context-list'>" + "".join(
        f"<div class='context-row'><b>{ui.esc(label)}</b><em>{ui.esc(value)}</em></div>" for label, value in rows
    ) + "</div>"
    body += cr._absolute_path_box("绝对 Raw 路径", version.get("raw_path"))
    body += ui.action_strip([
        ui.button("库工作台", cr._href(out_path / "libraries" / safe_lib / "index.html"), "primary", target="_blank"),
        ui.button("Scan 目录", cr._href(scan_dir), "secondary", disabled=not bool(scan_dir), target="_blank"),
    ])
    return ui.panel("版本上下文", "固定查看当前版本的来源、Base 和证据入口。", body)


def _review_gate_summary_panel(version: Mapping[str, Any]) -> str:
    gate = version.get("review_gate") if isinstance(version.get("review_gate"), Mapping) else {}
    status = str((gate or {}).get("status") or "NOT_BUILT")
    blocking = len((gate or {}).get("blocking_items", []) or [])
    attention = len((gate or {}).get("attention_items", []) or [])
    body = ui.metric_grid([
        ("门禁状态", ui.status_label(status), "review gate", status),
        ("阻塞项", blocking, "需要修复 / 接受 / 豁免", "BLOCK" if blocking else "PASS"),
        ("关注项", attention, "建议补充证据", "WARNING" if attention else "PASS"),
    ])
    return ui.panel("审查门禁", "用于确认当前版本是否还有必须处理的发布风险。", body)


def _scope_for_file_type(file_type: str) -> str:
    key = str(file_type or "unknown").lower()
    return {
        "verilog": "rtl",
        "systemverilog": "rtl",
        "v": "rtl",
        "sv": "rtl",
        "lef": "lef",
        "liberty": "lib",
        "lib": "lib",
        "db": "db",
        "gds": "gds",
        "oas": "oas",
        "cdl": "cdl",
        "spice": "cdl",
        "sdc": "sdc",
        "upf": "upf",
        "cpf": "cpf",
        "spef": "spef",
        "sdf": "sdf",
        "doc": "doc",
        "waiver": "waiver",
        "package": "doc",
        "flow_config": "flow",
        "tech_config": "tech",
    }.get(key, "未知")


def _view_label(file_type: str) -> str:
    key = str(file_type or "unknown").lower()
    if key == "unknown":
        return "未知 / 待确认"
    return f"{_scope_for_file_type(key)} / {key}"


def _parser_status_by_file_type(parser_manifest: Mapping[str, Any]) -> dict[str, str]:
    priority = ["FAILED", "PASS_EMPTY", "UNSUPPORTED", "SKIPPED", "METADATA_ONLY", "PASS"]
    found: dict[str, set[str]] = {}
    for file_entry in parser_manifest.get("files", []) or []:
        file_type = str(file_entry.get("file_type") or "unknown").lower()
        for task in file_entry.get("parser_tasks", []) or []:
            status = str(task.get("result_status") or task.get("status") or "SKIPPED").upper()
            found.setdefault(file_type, set()).add(status)
    out: dict[str, str] = {}
    for file_type, statuses in found.items():
        out[file_type] = next((status for status in priority if status in statuses), sorted(statuses)[0] if statuses else "-")
    return out


def _first_file_for_type(inventory: Mapping[str, Any], file_type: str) -> str:
    for item in inventory.get("files", []) or []:
        if str(item.get("file_type") or "unknown").lower() == file_type:
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


def _unknown_file_breakdown_html(cr: Any, inventory: Mapping[str, Any]) -> str:
    rows = _unknown_file_breakdown_rows(inventory)
    if not rows:
        return ""
    return (
        "<details class='detail-fold review-fold unknown-detail'>"
        "<summary>未知文件细分</summary>"
        "<div class='muted-box'>unknown 不是最终分类；这里按扩展名和无扩展名聚合，方便补规则或人工确认。</div>"
        + cr._scroll_table(["类型线索", "数量", "代表文件", "审查动作"], rows, "当前没有 unknown 文件", "unknown-detail-scroll")
        + "</details>"
    )


def _required_optional_view_maps(readiness: Mapping[str, Any]) -> tuple[dict[str, Mapping[str, Any]], dict[str, Mapping[str, Any]]]:
    required: dict[str, Mapping[str, Any]] = {}
    optional: dict[str, Mapping[str, Any]] = {}
    for component in readiness.get("components", []) or []:
        if not isinstance(component, Mapping):
            continue
        for view in component.get("required_views", []) or []:
            key = str(view).lower()
            result = (component.get("required_view_results") or {}).get(view) or {}
            required[key] = result if isinstance(result, Mapping) else {}
        for view in component.get("optional_views", []) or []:
            key = str(view).lower()
            result = (component.get("optional_view_results") or {}).get(view) or {}
            optional.setdefault(key, result if isinstance(result, Mapping) else {})
        for view, result in (component.get("required_view_results") or {}).items():
            required[str(view).lower()] = result if isinstance(result, Mapping) else {}
        for view, result in (component.get("optional_view_results") or {}).items():
            optional.setdefault(str(view).lower(), result if isinstance(result, Mapping) else {})
    return required, optional


def _view_coverage_rows(
    inventory: Mapping[str, Any],
    parser_manifest: Mapping[str, Any],
    readiness: Mapping[str, Any],
    counts: Mapping[str, int],
) -> list[str]:
    required, optional = _required_optional_view_maps(readiness)
    parser_status = _parser_status_by_file_type(parser_manifest)
    keys = set(str(k).lower() for k in counts) | set(required) | set(optional)
    view_order = ["verilog", "lef", "liberty", "db", "gds", "oas", "cdl", "sdc", "upf", "cpf", "spef", "sdf", "flow_config", "tech_config", "doc", "waiver", "package", "unknown"]
    rows: list[str] = []
    for file_type in sorted(keys, key=lambda item: (view_order.index(item) if item in view_order else 999, item)):
        result = required.get(file_type) or optional.get(file_type) or {}
        requirement = "必需" if file_type in required else "可选" if file_type in optional else "检测到"
        count = int(counts.get(file_type, 0) or 0)
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
    cr: Any,
    inventory: Mapping[str, Any],
    parser_manifest: Mapping[str, Any],
    readiness: Mapping[str, Any],
    counts: Mapping[str, int],
) -> str:
    required, optional = _required_optional_view_maps(readiness)
    unknown_count = int(counts.get("unknown", 0) or 0)
    manual_count = int(counts.get("flow_config", 0) or 0) + int(counts.get("tech_config", 0) or 0)
    rows = _view_coverage_rows(inventory, parser_manifest, readiness, counts)
    status = readiness.get("required_view_status") or readiness.get("bundle_status") or ("PASS" if rows else "UNKNOWN")
    return ui.panel(
        "交付 View 覆盖",
        "按真实交付视图检查 scope、必需/可选关系、Parser 状态和需要人工确认的文件类型。",
        ui.metric_grid([
            ("完整性判断", ui.status_label(status), f"release_level={readiness.get('release_level_candidate') or '-'}", status),
            ("必需 View", len(required), ", ".join(sorted(required)) or "未配置", "PASS" if required else "WARNING"),
            ("可选 View", len(optional), ", ".join(sorted(optional)[:6]) + (" ..." if len(optional) > 6 else "") if optional else "未配置", "INFO"),
            ("未知文件", unknown_count, "需要补分类或人工确认", "WARNING" if unknown_count else "PASS"),
            ("流程/技术配置", manual_count, "flow_config / tech_config", "WARNING" if manual_count else "INFO"),
        ])
        + cr._scroll_table(
            ["View / Scope", "要求", "文件数", "状态", "Parser", "校验级别", "代表路径 / 说明"],
            rows,
            "当前 Scan 没有可展示的 view 覆盖信息",
            "view-coverage-scroll",
        )
        + _unknown_file_breakdown_html(cr, inventory),
    )


def _count_only_panel(cr: Any, counts: Mapping[str, int], corner_summary: Mapping[str, Any], count_only_total: int) -> str:
    empty = ""
    if not count_only_total:
        empty += "<div class='empty-guidance'><b>当前 Raw Scan 没有发现大文件计数项</b>如果这是增量包，base/effective 中的 .lib/.db/.gds/.spef 不会在本页重复统计。</div>"
    if not (corner_summary or {}).get("total_corner_files"):
        empty += "<div class='empty-guidance'><b>当前 Raw Scan 没有识别到 PVT Corner 文件名</b>只有文件名中带 PVT 信息的库文件会进入 Corner 汇总。</div>"
    corner_rows = cr._version_corner_rows(corner_summary and {"corner_filename_summary": corner_summary} or {})
    corner_detail = (
        "<details class='detail-fold review-fold corner-detail'>"
        "<summary>PVT Corner 明细</summary>"
        + cr._scroll_table(["文件类型", "工艺", "电压", "温度", "路径"], corner_rows, "当前 Raw Scan 没有识别到 PVT Corner 文件名", "corner-detail-scroll")
        + "</details>"
    )
    return ui.panel(
        "大文件与 PVT Corner",
        "GDS/SPEF/Liberty/DB/OAS/Verilog 默认按大文件/多文件策略处理：统计数量、识别文件名 PVT，不在常规版本审查中读取完整内容。",
        ui.metric_grid([
            ("大文件计数", count_only_total, ", ".join(f"{k}:{counts[k]}" for k in sorted(cr.VERSION_COUNT_ONLY_TYPES) if counts.get(k)) or "无", "INFO" if count_only_total else "PASS"),
            ("工艺角", len((corner_summary or {}).get("process_counts") or {}), ", ".join(f"{k}:{v}" for k, v in ((corner_summary or {}).get("process_counts") or {}).items()) or "无", "PASS" if (corner_summary or {}).get("process_counts") else "INFO"),
            ("电压角", len((corner_summary or {}).get("voltage_counts") or {}), ", ".join(f"{k}:{v}" for k, v in ((corner_summary or {}).get("voltage_counts") or {}).items()) or "无", "PASS" if (corner_summary or {}).get("voltage_counts") else "INFO"),
            ("温度角", len((corner_summary or {}).get("temperature_counts") or {}), ", ".join(f"{k}:{v}" for k, v in ((corner_summary or {}).get("temperature_counts") or {}).items()) or "无", "PASS" if (corner_summary or {}).get("temperature_counts") else "INFO"),
        ])
        + empty
        + ui.faceted_table(
            "count-only-files",
            ["文件类型", "数量", "默认处理"],
            cr._version_count_only_rows(counts),
            "当前 Raw Scan 没有发现大文件计数项",
            "搜索大文件类型 / 处理方式",
            [(0, "文件类型"), (2, "默认处理")],
        )
        + corner_detail,
    )


def _parser_panel(cr: Any, parser_manifest: Mapping[str, Any], parser_results: Mapping[str, Any]) -> str:
    rows = cr._version_parser_aggregate_rows(parser_manifest, parser_results)
    empty = ""
    if not rows:
        empty = "<div class='empty-guidance'><b>当前 Scan 没有生成可展示的 Parser 结果</b>常见原因：本次 raw 包只包含文档/脚本，或相关文件类型没有 parser 任务。</div>"
    return ui.panel(
        "Parser 覆盖汇总",
        "按文件类型聚合 Parser 结果。先看覆盖和对象数量，需要时再展开代表性对象。",
        empty
        + ui.faceted_table(
            "parser-aggregate",
            ["Parser", "状态", "文件数", "任务状态", "聚合摘要", "来源"],
            rows,
            "当前 Scan 没有生成可展示的 Parser 结果",
            "搜索 Parser / 对象 / 来源文件",
            [(0, "Parser"), (1, "状态"), (3, "任务状态")],
        ),
    )


def _quality_panel(parser_task_count: int, count_only_total: int, file_total: int, corner_summary: Mapping[str, Any], model: Mapping[str, Any]) -> str:
    return ui.panel(
        "证据质量",
        "判断本页数据是否足够支撑后续 Diff 和人工审查。",
        ui.metric_grid([
            ("文件清单", file_total, "Raw Scan inventory", "PASS" if file_total else "WARNING"),
            ("Parser 覆盖", parser_task_count, "LEF / RTL / CDL / SDC / UPF", "PASS" if parser_task_count else "WARNING"),
            ("大文件计数", count_only_total, ".lib / .db / .spef / layout", "INFO" if count_only_total else "PASS"),
            ("PVT Corner", (corner_summary or {}).get("total_corner_files", 0), "filename PVT hints", "PASS" if (corner_summary or {}).get("total_corner_files") else "INFO"),
            ("Diff 状态", ui.status_label(model.get("status")), "当前版本更新详情", model.get("status")),
        ])
    )


def render_version_update_detail_panel(model: Mapping[str, Any]) -> str:
    cr = _cr()
    base_version = model.get("base_version") or "-"
    base_ref = model.get("base_ref") or "NEEDS_BASE_CONFIRM"
    diff_hint = model.get("diff_summary_path") or "请运行 lg lib-diff / lg cmp 生成 diff_summary.json"
    empty_next = "暂无文件级 diff 明细。请先运行 lg cmp 或 lg lib-diff 生成当前库对比结果。"
    status = str(model.get("status") or "UNKNOWN")
    meta = ui.compact_meta(
        [
            ("Base source", f"{base_ref} / {model.get('base_source') or '-'}"),
            ("Base version", base_version),
            ("Target version", model.get("target_version") or model.get("version_id") or "-"),
            ("Comparison semantics", model.get("comparison_semantics") or "-"),
            ("Delete semantics", model.get("delete_semantics") or "-"),
            ("Markdown export", model.get("markdown_export_path") or "-"),
        ]
    )
    metadata_note = ""
    if model.get("metadata_only_changes"):
        metadata_note = "<div class='quality-note'><b>metadata-only</b> 变化会展示在表格中，但 DB/GDS/OAS/大 Liberty/SPEF 等不会生成默认文件级 Diff 命令。</div>"
    primary_next_action = _as_mapping(model.get("primary_next_action"))
    primary_action_html = (
        "<div class='version-update-lead'>"
        f"<b>{ui.esc(model.get('headline') or '-')}</b>"
        f"<p>{ui.esc(model.get('confidence_note') or '-')}</p>"
        "<div class='primary-action-line'>"
        f"{ui.badge(primary_next_action.get('kind') or 'review_evidence', primary_next_action.get('label') or 'Review evidence')}"
        f"<em>command_count={ui.esc(primary_next_action.get('command_count') or 0)}</em>"
        "</div></div>"
    )
    trust_context_html = (
        "<div class='base-trust-context'>"
        "<div class='base-trust-head'>"
        "<b>Base trust</b>"
        f"{ui.badge(model.get('base_trust_status') or 'WARNING', model.get('base_trust_status') or 'WARNING')}"
        "</div>"
        f"<p>{ui.esc(model.get('base_trust_note') or '-')}</p>"
        f"{meta}"
        "</div>"
    )
    added_files = _as_int(_summary_metric_value(model, "added_files"))
    removed_files = _as_int(_summary_metric_value(model, "removed_files"))
    changed_files = _as_int(_summary_metric_value(model, "changed_files", model.get("changed_files")))
    file_change_total = added_files + removed_files + changed_files
    return ui.panel(
        f"更新详情（vs {base_ref} / {base_version}）",
        "先看本次版本相对 Base 的变化、风险和下一步动作；文件级 Diff 只展示 P0/P1 推荐。",
        primary_action_html
        + trust_context_html
        + ui.metric_grid(
            [
                (
                    "对比策略",
                    _cn_compare_strategy(model.get("compare_strategy")),
                    _cn_delete_semantics(model.get("delete_semantics")),
                    "WARNING" if model.get("comparison_semantics") == "incremental" else "PASS",
                ),
                ("Diff 摘要", ui.status_label(status), diff_hint, status),
                ("文件变化", file_change_total, f"+{added_files} / -{removed_files} / ~{changed_files}", "WARNING" if file_change_total else "INFO"),
                ("Release note", len(model.get("release_notes", []) or []), "release_note / changelog / update_note", "PASS" if model.get("release_notes") else "INFO"),
            ]
        )
        + "<h3>Diff 指标</h3>"
        + cr._scroll_table(["指标", "数值"], _metric_rows(model), "暂无自动 Diff 结果；下一步运行 lg cmp 或 lg lib-diff。", "metric-scroll")
        + "<h3>变化文件</h3>"
        + metadata_note
        + cr._scroll_table(["变化", "类型", "路径", "审查级别", "建议"], _file_change_rows(model), empty_next, "change-scroll")
        + "<h3>Recommended File Diff</h3>"
        + cr._scroll_table(
            ["变化", "类型", "路径", "审查级别", "建议"],
            _file_change_rows_for(model.get("recommended_file_diff", [])),
            "暂无 P0/P1 文件级 Diff 建议。",
            "change-scroll",
        )
        + "<h3>Summary-only Reviewed</h3>"
        + "<div class='quality-note'>已完成摘要级审查；默认无需展开全文。</div>"
        + cr._scroll_table(
            ["变化", "类型", "路径", "审查级别", "建议"],
            _file_change_rows_for(model.get("summary_only_reviewed", [])),
            "暂无 summary-only 审查项。",
            "change-scroll",
        )
        + "<h3>Metadata-only Reviewed</h3>"
        + "<div class='quality-note'>已完成 metadata-only 审查；二进制/版图文件默认不做全文 diff。</div>"
        + cr._scroll_table(
            ["变化", "类型", "路径", "审查级别", "建议"],
            _file_change_rows_for(model.get("metadata_only_reviewed", [])),
            "暂无 metadata-only 审查项。",
            "change-scroll",
        )
        + "<h3>Release note</h3>"
        + ui.faceted_table(
            "release-note-table",
            ["Release note", "摘要"],
            _release_note_rows(model),
            "暂无 release_note / changelog 摘要",
            "搜索 release note / changelog",
            [(0, "文件")],
        )
        + "<h3>建议动作</h3>"
        + ui.faceted_table(
            "recommended-action-table",
            ["建议动作"],
            _recommended_action_rows(model),
            "暂无建议动作",
            "搜索建议动作",
        )
        + "<h3>文件级 Diff 命令</h3>"
        + ui.faceted_table(
            "file-diff-command-table",
            ["级别", "路径", "命令"],
            _command_rows(model),
            "暂无 P0/P1 文件级 Diff 建议；metadata-only 文件不会生成默认 fd 命令。",
            "搜索级别 / 路径 / 命令",
            [(0, "级别")],
        ),
    )


def export_current_lib_diff_markdown(model: Mapping[str, Any], out_md: str | Path) -> str:
    path = Path(out_md)
    path.parent.mkdir(parents=True, exist_ok=True)
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
        f"changed_files: {_as_int(model.get('changed_files'))}",
        "---",
        "",
        "# Current Library Diff",
        "",
        "## Compare Context",
        "",
        f"- strategy: {model.get('compare_strategy') or '-'}",
        f"- base: {model.get('base_ref') or '-'} / {model.get('base_version') or '-'}",
        f"- target: {model.get('target_version') or model.get('version_id') or '-'}",
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
    lines.extend(["", "## Metadata-only Changes", ""])
    for item in model.get("metadata_only_changes", []) or []:
        if isinstance(item, Mapping):
            lines.append(f"- {item.get('file_type')} {item.get('path')}")
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
    lines.extend(["", "## Recommended File Diff", ""])
    for item in model.get("file_diff_recommendations", []) or []:
        if isinstance(item, Mapping):
            lines.append(f"- {item.get('lane')} `{item.get('command')}`")
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
    cr = _cr()
    out_path = Path(out)
    lib_id = _library_id(lib)
    version_id = _version_id(version)
    safe_lib = cr._safe(lib_id)
    safe_ver = cr._safe(version_id)
    page = out_path / "libraries" / safe_lib / "versions" / safe_ver / "index.html"
    tags = cr._version_tags(version)
    relation = cr._relation_status(version)
    rail = ui.status_rail(
        [
            ("Catalog", "DISCOVERED", "Version is registered in the catalog"),
            ("Scan", version.get("scan_status") or "NOT_SCANNED", "Single-version scan evidence"),
            ("Relation", relation, cr._relation_label(relation)),
            ("Compare", version.get("diff_status") or "COMPARE_PENDING", "Current-library update detail"),
            ("File Review", cr._file_review_status(version), cr._file_review_text(version)),
        ]
    )
    model = build_version_update_detail_model(out_path, lib, version)
    md_path = page.parent / "current_lib_diff.md"
    model["markdown_export_path"] = str(md_path)
    if export_markdown:
        export_current_lib_diff_markdown(model, md_path)
    scan_dir = cr._version_scan_dir(version)
    inventory = cr._scan_inventory(scan_dir)
    parser_manifest = cr._scan_parser_manifest(scan_dir)
    parser_results = cr._scan_parser_results(scan_dir)
    release_readiness = cr.read_json(scan_dir / "summary" / "release_readiness.json", default={}) if scan_dir else {}
    counts = cr._version_file_type_counts(inventory)
    count_only_total = sum(int(counts.get(item, 0) or 0) for item in cr.VERSION_COUNT_ONLY_TYPES)
    parser_task_count = sum(
        1
        for file_entry in (parser_manifest.get("files", []) or [])
        for task in (file_entry.get("parser_tasks", []) or [])
        if task.get("parser_name")
    )
    corner_summary = inventory.get("corner_filename_summary") or {}
    file_total = sum(int(v or 0) for v in counts.values())
    body = (
        _version_detail_styles()
        + _version_overview_panel(
            lib_id,
            version_id,
            version,
            model,
            relation=relation,
            parser_task_count=parser_task_count,
            count_only_total=count_only_total,
            file_total=file_total,
        )
        + "<div class='version-dashboard'><main class='version-main'>"
        + render_version_update_detail_panel(model)
        + _raw_scan_scope_note(model, parser_task_count=parser_task_count, count_only_total=count_only_total)
        + _view_coverage_panel(cr, inventory, parser_manifest, release_readiness, counts)
        + _count_only_panel(cr, counts, corner_summary, count_only_total)
        + _parser_panel(cr, parser_manifest, parser_results)
        + "</main><aside class='version-side'>"
        + _version_context_panel(out_path, safe_lib, lib_id, version_id, version, model, scan_dir)
        + _quality_panel(parser_task_count, count_only_total, file_total, corner_summary, model)
        + _review_gate_summary_panel(version)
        + ui.panel(
            "对比前检查",
            "确认 Scan、Base 和 Diff 状态是否足够支撑当前审查。",
            ui.metric_grid(
                [
                    ("Parser 视图", parser_task_count, "LEF / RTL / CDL / SDC / UPF", "PASS" if parser_task_count else "WARNING"),
                    ("大文件计数", count_only_total, "常规审查不读取完整内容", "INFO" if count_only_total else "PASS"),
                    ("Diff 状态", ui.status_label(version.get("diff_status") or model.get("status")), "当前版本更新详情", version.get("diff_status") or model.get("status")),
                    ("文件审查", cr._file_review_text(version), "优先查看 P0/P1 文件级 Diff", cr._file_review_status(version)),
                ]
            ),
        )
        + "</aside></div>"
        + ui.collapsible_panel(
            "原始证据",
            "原始 JSON、Scan 目录和 Markdown 导出默认折叠，便于人工追溯。",
            ui.trace_link_list(
                [
                    ("scan_dir", cr._href(scan_dir), "Raw Scan 输出目录"),
                    ("file_inventory.json", cr._href(scan_dir / "file_inventory.json") if scan_dir else "", "本页文件清单来源"),
                    ("parser_manifest.json", cr._href(scan_dir / "parser_manifest.json") if scan_dir else "", "Parser 任务清单"),
                    ("parser_results.json", cr._href(scan_dir / "parser_results.json") if scan_dir else "", "Parser 结果数据"),
                    ("current_lib_diff.md", cr._href(md_path) if md_path.exists() else "", "显式导出时由 version_update_detail_model 生成"),
                ]
            ),
            open=False,
        )
    )
    rail = ui.status_rail(
        [
            ("目录", "DISCOVERED", "版本已进入 catalog"),
            ("Scan", version.get("scan_status") or "NOT_SCANNED", "单版本扫描证据"),
            ("关系", relation, cr._relation_label(relation)),
            ("Diff", version.get("diff_status") or model.get("status") or "COMPARE_PENDING", "当前版本对比状态"),
            ("文件审查", cr._file_review_status(version), cr._file_review_text(version)),
        ]
    )
    html = ui.review_page_shell(
        f"{lib.get('display_name') or lib_id} / {version_id}",
        "版本审查",
        "先看更新结论、证据状态和下一步动作，再展开 Parser 与原始证据。",
        catalog_browser_styles() + body,
        decision=version.get("overall_status") or ("REVIEW" if tags - {"clear"} else "PASS"),
        rail=rail,
        nav="<a href='../../../index.html'>目录</a><a class='active' href='#'>版本详情</a><a href='../index.html'>库工作台</a>",
        meta=ui.compact_meta([("库", lib_id), ("版本", version_id), ("标签", ", ".join(sorted(tags)))]),
    )
    cr._write_text(page, html)
    return str(page)
