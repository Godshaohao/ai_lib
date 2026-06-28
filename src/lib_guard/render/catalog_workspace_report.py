"""Catalog index and library workspace report renderer."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from lib_guard.render import product_theme as ui


def _cr():
    from lib_guard.render import catalog_report as cr

    return cr


def render_library_workspace_page(
    out: str | Path,
    lib: Mapping[str, Any],
    effective_items: list[dict[str, Any]],
    compare_items: list[dict[str, Any]] | None = None,
) -> str:
    cr = _cr()
    return cr._render_library_home(Path(out), lib, effective_items, compare_items)


def build_library_report_index_entry(
    out: str | Path,
    lib: Mapping[str, Any],
    effective_items: list[dict[str, Any]],
    compare_items: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    cr = _cr()
    out_path = Path(out)
    lib_id = str(lib.get("library_id") or lib.get("display_name") or lib.get("library_name") or "")
    timeline, latest_effective_ref = cr._library_timeline(lib, effective_items)
    versions: dict[str, Any] = {}
    for version in lib.get("versions", []) or []:
        version_id = str(version.get("version_id") or version.get("version") or "")
        links = cr._version_links(version)
        refs = cr._version_effective_refs(version_id, effective_items)
        versions[version_id] = {
            "home": cr._rel_href(out_path, links.get("version_review_html")),
            "scan": cr._rel_href(out_path, links.get("scan_html")),
            "diffs": [cr._rel_href(out_path, links.get("diff_html"))] if links.get("diff_html") else [],
            "contributes_to_effective": [str(item.get("effective_id")) for item in refs],
        }
    effective = {
        str(item.get("effective_id")): {
            "html": cr._rel_href(out_path, item.get("html")),
            "manifest": cr._rel_href(out_path, item.get("manifest")),
            "release_preview": cr._rel_href(out_path, item.get("release_preview")),
            "release_manifest": cr._rel_href(out_path, item.get("release_manifest")),
            "summary": {
                "file_count": item.get("file_count", 0),
                "component_count": item.get("component_count", 0),
                "conflict_count": item.get("conflict_count", 0),
                "operation_summary": item.get("operation_summary", {}),
                "file_type_summary": item.get("file_type_summary", {}),
            },
        }
        for item in effective_items
    }
    current_effective = cr._latest_effective_item(effective_items) or {}
    compare_reports = {
        str(item.get("compare_id")): {
            "mode": item.get("mode"),
            "old_target": item.get("old_target", {}),
            "new_target": item.get("new_target", {}),
            "owner_target": item.get("owner_target") or "",
            "html": cr._rel_href(out_path, item.get("html")),
            "manifest": cr._rel_href(out_path, item.get("manifest")),
            "summary": {
                "changed_files": item.get("changed_files", 0),
                "risk_count": item.get("risk_count", 0),
                "actions": item.get("actions", {}),
            },
        }
        for item in (compare_items or [])
        if item.get("compare_id")
    }
    return {
        "library_id": lib_id,
        "home": cr._rel_href(out_path, lib.get("library_home_html")),
        "versions": versions,
        "effective": effective,
        "current_effective": str(current_effective.get("effective_id") or "") if current_effective else "",
        "latest_effective_ref": latest_effective_ref,
        "timeline": cr._timeline_for_report_index(out_path, timeline),
        "compare_reports": compare_reports,
    }


def render_catalog_index_page(
    out: str | Path,
    state: Mapping[str, Any],
    tasks: Mapping[str, Any],
    effective_by_lib: Mapping[str, list[dict[str, Any]]],
    compare_by_lib: Mapping[str, list[dict[str, Any]]] | None = None,
    *,
    max_attention_items: int = 10,
    max_report_rows: int = 16,
    report_index: str | Path | None = None,
    catalog_json: str | Path | None = None,
) -> str:
    del compare_by_lib, max_attention_items, max_report_rows
    cr = _cr()
    out_path = Path(out)
    body = (
        cr._catalog_browser_styles()
        + ui.panel(
            "Catalog 总览",
            "面向 IP 使用者：先搜索库，再进入库工作台查看更新文件和可执行脚本。库管理者证据放在下方折叠区。",
            ui.metric_grid(cr._summary_metrics(state, tasks))
            + "<p class='catalog-note'>主流程是获取库更新信息、更新文件和执行脚本；管理补证据不作为普通使用者的首要任务。</p>",
        )
        + "<div class='catalog-layout'>"
        + f"<div class='catalog-filter-panel'>{cr._catalog_filter_panel(state)}</div>"
        + f"<div>{ui.panel('Library Browser', '中文紧凑摘要：只显示库身份、当前有效组合和进入库工作台；scan/diff/effective/release preview 由库工作台串联。', cr._library_browser(out_path, state, effective_by_lib))}</div>"
        + "</div>"
        + ui.collapsible_panel(
            "管理建议 / Suggested Commands",
            "manager_tasks.json 是有效的管理者任务列表，用于补 scan、diff 或关系确认；普通 IP 使用者通常不需要处理。",
            ui.filterable_table("catalog-task-table", ["优先级", "类型", "Library / Version", "原因", "执行"], cr._task_rows(tasks), "暂无建议", "筛选 task / reason"),
            open=False,
        )
        + ui.collapsible_panel(
            "Trace Evidence",
            "Catalog 原始证据和统一报告索引。manager_tasks.json 的定位是管理者任务证据。",
            ui.trace_link_list(
                [
                    ("report_index.json", cr._href(report_index), "Catalog / Scan / Diff / Effective / Release Preview 的链接索引"),
                    ("catalog_state.json", cr._href(out_path / "catalog_state.json"), "Catalog 页面使用的状态模型"),
                    ("manager_tasks.json", cr._href(out_path / "manager_tasks.json"), "管理者建议动作列表"),
                    ("catalog.json", cr._href(catalog_json), "原始 catalog"),
                ]
            ),
            open=True,
        )
        + ui.collapsible_panel("命令示例", "所有常用命令集中折叠在最下面。Browser 行内只保留状态和入口，不再放待生成命令。", cr._command_examples(), open=False)
    )
    return ui.review_page_shell(
        "Library Catalog",
        "CATALOG",
        "库版本变化导航入口。Catalog 是地图，不是命令控制台。",
        body,
        decision="REVIEW" if tasks.get("tasks") else "PASS",
        nav="<a class='active' href='#'>Catalog</a><a href='#'>Library Workspace</a><a href='#'>Scan Evidence</a><a href='#'>Release Evidence</a>",
        meta=ui.compact_meta([("Libraries", len(state.get("libraries", []) or [])), ("Tasks", len(tasks.get("tasks", []) or []))]),
    )
