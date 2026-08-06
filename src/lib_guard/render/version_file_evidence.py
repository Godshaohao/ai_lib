"""Human-readable file evidence for one Version Detail page.

The Version Detail page is the decision surface.  This page is only the
complete, filterable file inventory behind that decision, so large evidence
lists do not inflate the primary review page.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from lib_guard.render import catalog_render_common as common
from lib_guard.render import catalog_workspace_report as workspace
from lib_guard.render import product_theme as ui
from lib_guard.view_types import canonical_view_type, usage_area_for_view, view_label


def _as_mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _change_label(value: Any) -> str:
    return {
        "added": "新增",
        "removed": "删除",
        "changed": "修改",
        "current": "当前文件",
    }.get(str(value or "").lower(), str(value or "-"))


def _lane_label(value: Any) -> str:
    return {
        "P0": "P0",
        "P1": "P1",
        "Review": "人工审查",
        "Summary-only": "摘要级证据（Summary-only）",
        "Metadata-only": "元数据级证据（Metadata-only）",
    }.get(str(value or ""), str(value or "人工审查"))


def _match_label(value: Any) -> str:
    return {
        "matched_move": "已匹配迁移",
        "candidate_match": "候选匹配",
        "same_path": "同路径",
        "not_applicable": "不适用",
        "true_added": "真实新增",
        "true_removed": "真实删除",
        "unmatched": "未匹配",
    }.get(str(value or "").lower(), str(value or "-"))


def _evidence_rows(model: Mapping[str, Any]) -> list[str]:
    changes = [item for item in model.get("file_changes", []) or [] if isinstance(item, Mapping)]
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in changes:
        path = str(item.get("path") or "-")
        seen.add(path)
        view_type = canonical_view_type(item.get("file_type"))
        rows.append(
            {
                "change": str(item.get("change") or ""),
                "view": view_label(view_type),
                "path": path,
                "lane": _lane_label(item.get("review_lane")),
                "match": _match_label(item.get("match_status")),
                "meaning": str(item.get("hint") or "按视图变化和证据等级确认。"),
                "area": usage_area_for_view(view_type),
            }
        )

    scan_evidence = _as_mapping(model.get("scan_evidence"))
    inventory = _as_mapping(scan_evidence.get("inventory"))
    for item in inventory.get("files", []) or []:
        if not isinstance(item, Mapping):
            continue
        path = str(item.get("path") or item.get("relpath") or item.get("file") or "-")
        if path in seen:
            continue
        view_type = canonical_view_type(item.get("file_type"))
        rows.append(
            {
                "change": "current",
                "view": view_label(view_type),
                "path": path,
                "lane": _lane_label(item.get("review_lane")),
                "match": "-",
                "meaning": "当前扫描交付文件；未在本次文件级变化中列出。",
                "area": usage_area_for_view(view_type),
            }
        )

    rows.sort(key=lambda item: (item["view"], item["path"]))
    return [
        "<tr>"
        f"<td>{ui.badge(str(item['change']).upper(), _change_label(item['change']))}</td>"
        f"<td>{ui.esc(item['view'])}<small class='evidence-area'>{ui.esc(item['area'])}</small></td>"
        f"<td><code>{ui.esc(item['path'])}</code></td>"
        f"<td>{ui.esc(item['lane'])}</td>"
        f"<td>{ui.esc(item['match'])}</td>"
        f"<td>{ui.esc(item['meaning'])}</td>"
        "</tr>"
        for item in rows
    ]


def render_version_file_evidence_page(
    out: str | Path,
    lib: Mapping[str, Any],
    version: Mapping[str, Any],
    model: Mapping[str, Any],
) -> str:
    page = Path(out)
    rows = _evidence_rows(model)
    library = str(lib.get("display_name") or lib.get("library_name") or lib.get("library_id") or "库")
    version_id = str(version.get("version_id") or version.get("version") or model.get("version_id") or "版本")
    base = str(model.get("base_version") or "-")
    body = (
        "<style>"
        ".evidence-page{max-width:1700px}.evidence-page .table-wrap{max-height:calc(100vh - 270px);overflow:auto}"
        ".evidence-page table{min-width:1180px}.evidence-page th{position:sticky;top:0;z-index:2}"
        ".evidence-page td code{white-space:normal}.evidence-area{display:block;color:#667085;font-size:11px;margin-top:3px}"
        ".evidence-page .panel-body{padding-top:12px}"
        "</style>"
        "<main class='evidence-page'>"
        + ui.panel(
            "文件证据清单",
            "完整列出当前版本的变化文件和扫描交付文件；这里适合检索、核对和导出，不承担主审查结论。",
            ui.faceted_table(
                "version-file-evidence",
                ["变化", "视图 / 使用场景", "文件路径", "证据策略", "匹配说明", "审查含义"],
                rows,
                "当前没有可展示的文件证据。",
                "搜索文件路径、类型或审查含义",
                facets=[(0, "变化"), (1, "视图"), (3, "证据策略"), (4, "匹配说明")],
                wrap_class="table-wrap",
            ),
        )
        + "</main>"
    )
    nav = "<a href='index.html'>版本详情</a><a class='active' href='#'>文件证据</a><a href='../index.html'>库工作台</a>"
    html = ui.review_page_shell(
        f"{library} / {version_id} / 文件证据",
        "文件证据",
        "按文件路径、视图、证据策略和匹配说明检索当前版本。",
        workspace.catalog_browser_styles() + body,
        decision="INFO",
        nav=nav,
        meta=ui.compact_meta([("版本", version_id), ("对比基准", base), ("文件数", len(rows))]),
    )
    common.write_text(page, html)
    return str(page)

