"""Catalog HTML renderer using the shared Review Navigation theme.

Catalog is the user entry. It should help users find a library, open the library
Diff Timeline, then enter a selected comparison and File Diff result. Scan and
Release remain evidence pages, not the primary navigation path.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping
import json
import re

from lib_guard.review import build_review_state, build_review_tasks
from lib_guard.review.io import as_file_href, read_json, write_json
from lib_guard.render import product_theme as ui


def _safe(value: Any) -> str:
    text = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value or "item")).strip("._")
    return text or "item"


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _version_links(version: Mapping[str, Any]) -> Mapping[str, Any]:
    return version.get("links") or {}


def _href(path: Any) -> str:
    return as_file_href(path) if path else ""


def _raw_link_trace(links: Mapping[str, Any]) -> str:
    raw = [links.get("scan_html"), links.get("diff_html"), links.get("pairwise_html"), links.get("release_html")]
    return "".join(f"<span class='muted'>{ui.esc(item)}</span>" for item in raw if item)


def _status_key(value: Any) -> str:
    return str(value or "UNKNOWN").strip().upper()


def _version_tags(version: Mapping[str, Any]) -> set[str]:
    tags: set[str] = set()
    overall = _status_key(version.get("overall_status"))
    scan = _status_key(version.get("scan_status"))
    diff = _status_key(version.get("diff_status"))
    pair = _status_key(version.get("pairwise_status"))
    release = _status_key(version.get("release_status"))
    if overall in {"BLOCK", "BLOCKED", "FAILED", "ERROR"}:
        tags.add("block")
    if overall in {"REVIEW", "NEEDS_REVIEW", "MANUAL_REVIEW"} or diff in {"DIFF", "CHANGED", "REVIEW_REQUIRED"}:
        tags.add("review")
    if scan in {"NOT_SCANNED", "SCAN_MISSING"}:
        tags.add("not_scanned")
    if diff in {"DIFF", "CHANGED", "REVIEW_REQUIRED", "NEEDS_FILE_DIFF"}:
        tags.add("changed")
    if pair in {"PAIRWISE_PENDING", "PAIRWISE_PARTIAL", "FILE_DIFF_PENDING", "NEEDS_FILE_DIFF"}:
        tags.add("file_diff_pending")
    if release in {"RELEASED", "APPLIED", "PASS"}:
        tags.add("released")
    if not tags:
        tags.add("clear")
    return tags


def _library_tags(lib: Mapping[str, Any]) -> set[str]:
    tags: set[str] = set()
    for version in lib.get("versions", []) or []:
        tags.update(_version_tags(version))
    if not tags:
        tags.add("clear")
    return tags


def _pairwise_text(version: Mapping[str, Any]) -> str:
    pair = version.get("pairwise_summary") or {}
    total = int(pair.get("total", 0) or 0)
    done = int(pair.get("done", 0) or 0)
    if total:
        return f"{done}/{total}"
    return ui.status_label(version.get("pairwise_status"))


def _build_comparisons_for_library(lib: Mapping[str, Any]) -> list[dict[str, Any]]:
    comparisons: list[dict[str, Any]] = []
    versions = list(lib.get("versions", []) or [])
    prev_version = None
    for version in versions:
        links = _version_links(version)
        diff = version.get("diff") or {}
        version_id = version.get("version_id") or version.get("version") or "-"
        base_version = version.get("base_version") or diff.get("base_version") or diff.get("cumulative_base_version")
        adjacent_old = diff.get("adjacent_old_version") or prev_version
        for mode, old in [("adjacent", adjacent_old), ("base", base_version)]:
            if not old or str(old) == str(version_id):
                continue
            pair = version.get("pairwise_summary") or {}
            comparisons.append({
                "comparison_id": f"{mode}__{old}__{version_id}",
                "library_id": lib.get("library_id"),
                "old_version": old,
                "new_version": version_id,
                "mode": mode,
                "status": version.get("diff_status") or "COMPARE_PENDING",
                "review_level": version.get("overall_status") or version.get("diff_status") or "UNKNOWN",
                "diff_html": _href(links.get("diff_html")),
                "pairwise_total": int(pair.get("total", 0) or 0),
                "pairwise_done": int(pair.get("done", 0) or 0),
                "release_impact": version.get("release_status") or "RELEASE_CHECK_REQUIRED",
            })
        prev_version = version_id
    return comparisons


def _render_library_diff_timeline(out: Path, lib: Mapping[str, Any]) -> str:
    lib_id = str(lib.get("library_id") or lib.get("display_name") or "library")
    safe = _safe(lib_id)
    html_path = out / "libraries" / safe / "diff_timeline.html"
    comparisons = _build_comparisons_for_library(lib)
    (html_path.parent / "diff_index.json").write_text(json.dumps({
        "schema_version": "library_diff_index.v1",
        "library_id": lib_id,
        "display_name": lib.get("display_name"),
        "comparisons": comparisons,
    }, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
    changed = sum(1 for c in comparisons if _status_key(c.get("status")) in {"DIFF", "CHANGED", "REVIEW_REQUIRED", "NEEDS_FILE_DIFF"})
    pending = sum(1 for c in comparisons if int(c.get("pairwise_total", 0) or 0) > int(c.get("pairwise_done", 0) or 0))
    nav = "<a href='../../index.html'>Catalog</a><a class='active' href='#'>Diff Timeline</a><a href='#'>Selected Diff</a><a href='#'>File Diff</a>"
    body = (
        ui.panel(
            "库级 Diff Timeline",
            "一个 library 的多版本 comparison 入口。普通用户先看这里，再进入 Selected Diff Review。",
            ui.metric_grid([
                ("Versions", len(lib.get("versions", []) or []), "catalog versions", "PASS"),
                ("Comparisons", len(comparisons), "adjacent / base", "PASS" if comparisons else "WARNING"),
                ("Changed", changed, "有变化的 comparison", "WARNING" if changed else "PASS"),
                ("File Diff 待完成", pending, "pairwise pending", "WARNING" if pending else "PASS"),
            ]) + ui.compact_meta([
                ("Library", lib_id),
                ("Vendor", lib.get("vendor") or "-"),
                ("Path", lib.get("middle_path") or lib.get("library_root") or "-"),
            ]),
        )
        + ui.panel("筛选 / 滑动", "横向滑动查看多个 comparison。", ui.comparison_filter_bar() + ui.timeline(comparisons))
        + ui.collapsible_panel(
            "Comparison 明细",
            "用于定位每次 old → new 的状态和 File Diff 完成情况。",
            ui.filterable_table(
                f"cmp-{safe}",
                ["Mode", "Old", "New", "Status", "File Diff", "Release", "Open"],
                [
                    "<tr>"
                    f"<td><code>{ui.esc(c.get('mode'))}</code></td>"
                    f"<td><code>{ui.esc(c.get('old_version'))}</code></td>"
                    f"<td><code>{ui.esc(c.get('new_version'))}</code></td>"
                    f"<td>{ui.badge(c.get('status'))}</td>"
                    f"<td>{ui.esc(c.get('pairwise_done', 0))}/{ui.esc(c.get('pairwise_total', 0))}</td>"
                    f"<td>{ui.badge(c.get('release_impact'))}</td>"
                    f"<td>{ui.button('打开 Diff', c.get('diff_html'), 'primary', disabled=not bool(c.get('diff_html')), target='_blank')}</td>"
                    "</tr>"
                    for c in comparisons
                ],
                "暂无 comparison",
                "筛选 old / new / mode / status",
            ),
            open=True,
        )
    )
    html = ui.review_page_shell(
        f"{lib.get('display_name') or lib_id} / Diff Timeline",
        "DIFF TIMELINE",
        "库级版本变化导航。Scan / Release 是证据页，Selected Diff 和 File Diff 是主要审阅入口。",
        body,
        decision="REVIEW" if changed or pending else "PASS",
        nav=nav,
        meta=ui.compact_meta([("Library", lib_id), ("Comparisons", len(comparisons)), ("Pending File Diff", pending)]),
    )
    _write_text(html_path, html)
    return str(html_path)


def _version_row(lib: Mapping[str, Any], version: Mapping[str, Any], latest: Any) -> str:
    links = _version_links(version)
    version_id = str(version.get("version_id") or version.get("version") or "-")
    is_latest = "1" if str(version_id) == str(latest) else "0"
    command = str(version.get("next_command") or "")
    tags = ",".join(sorted(_version_tags(version)))
    actions = ui.action_strip([
        ui.button("Review", _href(links.get("version_review_html")), "primary", disabled=not links.get("version_review_html"), target="_blank"),
        ui.button("Scan", _href(links.get("scan_html")), disabled=not links.get("scan_html"), target="_blank"),
        ui.button("Diff", _href(links.get("diff_html")), disabled=not links.get("diff_html"), target="_blank"),
        ui.button("File Diff", _href(links.get("pairwise_html")), disabled=not links.get("pairwise_html"), target="_blank"),
        ui.button("Release", _href(links.get("release_html")), disabled=not links.get("release_html"), target="_blank"),
    ])
    return (
        f"<div class='version-row' data-tags='{ui.esc(tags)}' data-latest='{is_latest}'>"
        f"<div><div class='version-name'>{ui.esc(version_id)}</div><div class='version-path' title='{ui.esc(version.get('raw_path'))}'>{ui.esc(version.get('raw_path') or '-')}</div></div>"
        f"<div>{ui.badge(version.get('scan_status'))}</div>"
        f"<div>{ui.badge(version.get('diff_status'))}</div>"
        f"<div>{ui.badge(version.get('pairwise_status'), _pairwise_text(version))}</div>"
        f"<div>{ui.badge(version.get('release_status'))}</div>"
        f"<div class='version-next'>{ui.command_chip(command)}<span class='muted'>{ui.esc(version.get('next_reason') or '')}</span></div>"
        f"<div>{actions}{_raw_link_trace(links)}</div>"
        "</div>"
    )


def _library_card(out: Path, lib: Mapping[str, Any]) -> str:
    versions = list(lib.get("versions", []) or [])
    latest = lib.get("latest_version") or (versions[-1].get("version_id") if versions else "-")
    approved = lib.get("approved_version") or lib.get("current_version") or "-"
    status = lib.get("overall_status") or "UNKNOWN"
    vendor = str(lib.get("vendor") or "Unknown")
    middle = str(lib.get("middle_path") or lib.get("library_root") or "-")
    stages = sorted({str(v.get("stage") or "unknown") for v in versions})
    tags = _library_tags(lib)
    timeline_path = _render_library_diff_timeline(out, lib)
    actions = ui.action_strip([
        ui.button("Diff Timeline", _href(timeline_path), "primary", target="_blank"),
        ui.button("Latest Scan", _href((versions[-1].get("links") or {}).get("scan_html") if versions else ""), disabled=not versions or not (versions[-1].get("links") or {}).get("scan_html"), target="_blank"),
        ui.button("Latest Diff", _href((versions[-1].get("links") or {}).get("diff_html") if versions else ""), disabled=not versions or not (versions[-1].get("links") or {}).get("diff_html"), target="_blank"),
    ])
    version_rows = "".join(_version_row(lib, v, latest) for v in reversed(versions))
    return (
        f"<section class='library-card' data-overall='{ui.esc(status)}' data-vendor='{ui.esc(vendor)}' data-stages='{ui.esc(','.join(stages))}' data-tags='{ui.esc(','.join(sorted(tags)))}'>"
        "<div class='library-main'>"
        f"<div><div class='library-title'>{ui.esc(lib.get('display_name') or lib.get('library_name') or lib.get('library_id'))}</div><div class='library-path' title='{ui.esc(lib.get('library_id'))}'>{ui.esc(lib.get('library_id') or '-')}</div></div>"
        f"<div><b>{ui.esc(vendor)}</b><div class='library-path' title='{ui.esc(middle)}'>{ui.esc(middle)}</div></div>"
        f"<div><span class='muted'>latest</span><br><b>{ui.esc(latest)}</b></div>"
        f"<div><span class='muted'>current</span><br><b>{ui.esc(approved)}</b></div>"
        f"<div class='library-status'>{ui.badge(status)}<span class='browser-count'>{len(versions)} versions</span>{actions}</div>"
        "</div>"
        f"<details class='version-drawer'><summary>Versions / 版本明细</summary><div class='version-list'>{version_rows or '<div class=\'catalog-empty\'>暂无 version</div>'}</div></details>"
        "</section>"
    )


def _group_libraries(libraries: list[Mapping[str, Any]]) -> dict[tuple[str, str], list[Mapping[str, Any]]]:
    grouped: dict[tuple[str, str], list[Mapping[str, Any]]] = {}
    for lib in libraries:
        key = (str(lib.get("vendor") or "Unknown"), str(lib.get("middle_path") or lib.get("library_root") or "-"))
        grouped.setdefault(key, []).append(lib)
    return dict(sorted(grouped.items(), key=lambda kv: (kv[0][0], kv[0][1])))


def _library_browser(out: Path, state: Mapping[str, Any]) -> str:
    libraries = list(state.get("libraries", []) or [])
    groups = _group_libraries(libraries)
    group_html = []
    for (vendor, middle), libs in groups.items():
        cards = "".join(_library_card(out, lib) for lib in libs)
        has_attention = any((_library_tags(lib) & {"review", "block", "file_diff_pending", "not_scanned"}) for lib in libs)
        group_html.append(
            f"<details class='library-group' {'open' if has_attention else ''}>"
            f"<summary><div class='library-group-title'><b>{ui.esc(vendor)}</b><span>{ui.esc(middle)}</span></div><span class='browser-count'>{len(libs)} libraries</span></summary>"
            f"<div class='library-group-body'>{cards}</div>"
            "</details>"
        )
    return "<div class='library-browser' data-catalog-browser data-status-filter='all'>" + ("".join(group_html) or "<div class='catalog-empty'>暂无 library</div>") + "</div>"


def _catalog_filter_panel(state: Mapping[str, Any]) -> str:
    libraries = list(state.get("libraries", []) or [])
    vendors = sorted({str(lib.get("vendor") or "Unknown") for lib in libraries})
    stages = sorted({str(v.get("stage") or "unknown") for lib in libraries for v in (lib.get("versions", []) or [])})
    vendor_opts = "<option value='all'>全部 Vendor</option>" + "".join(f"<option value='{ui.esc(v)}'>{ui.esc(v)}</option>" for v in vendors)
    stage_opts = "<option value='all'>全部 Stage</option>" + "".join(f"<option value='{ui.esc(s)}'>{ui.esc(s)}</option>" for s in stages)
    chips = [
        ("all", "全部"), ("review", "需审阅"), ("block", "阻塞"), ("not_scanned", "未 Scan"),
        ("changed", "有变化"), ("file_diff_pending", "File Diff 待完成"), ("released", "已 Release"), ("clear", "无关注项"),
    ]
    chip_html = "".join(f"<button type='button' class='filter-chip {'active' if k == 'all' else ''}' data-catalog-status-chip='{k}' onclick=\"setCatalogStatusFilter('{k}', this)\">{ui.esc(v)}</button>" for k, v in chips)
    body = (
        "<div class='search'><span>搜索</span><input id='catalog-search' type='search' placeholder='library / version / vendor / path' oninput='filterCatalogBrowser()'></div>"
        "<div class='filter-group-title'>Vendor</div>"
        f"<select id='catalog-vendor' onchange='filterCatalogBrowser()'>{vendor_opts}</select>"
        "<div class='filter-group-title'>Stage</div>"
        f"<select id='catalog-stage' onchange='filterCatalogBrowser()'>{stage_opts}</select>"
        "<label style='display:flex;gap:8px;align-items:center;margin:10px 0;color:#667085;font-size:13px'><input id='catalog-latest' type='checkbox' onchange='filterCatalogBrowser()'> 只看 latest version</label>"
        "<div class='filter-group-title'>状态</div>"
        f"<div class='catalog-chips'>{chip_html}</div>"
        "<div class='filter-group-title'>操作</div>"
        + ui.action_strip([
            "<button class='btn secondary' type='button' onclick=\"catalogExpand('review')\">展开关注项</button>",
            "<button class='btn secondary' type='button' onclick=\"catalogExpand('collapse')\">折叠全部</button>",
            "<button class='btn secondary' type='button' onclick='resetCatalogFilters()'>重置</button>",
        ])
        + "<div id='catalog-visible-count' class='browser-count' style='margin-top:12px'>-</div>"
        + "<script>setTimeout(filterCatalogBrowser,0)</script>"
    )
    return ui.panel("筛选", "按库、版本、Vendor、Stage、状态快速定位。", body)


def _task_rows(tasks: Mapping[str, Any]) -> list[str]:
    rows = []
    for task in tasks.get("tasks", []) or []:
        rows.append(
            "<tr>"
            f"<td>{ui.badge(task.get('priority'), task.get('priority'))}</td>"
            f"<td><code>{ui.esc(task.get('task_type'))}</code></td>"
            f"<td><b>{ui.esc(task.get('display_name'))}</b><div class='muted'>{ui.esc(task.get('version_id'))}</div></td>"
            f"<td>{ui.esc(task.get('reason'))}</td>"
            f"<td>{ui.command_chip(task.get('command'))}</td>"
            "</tr>"
        )
    return rows


def _summary_metrics(state: Mapping[str, Any], tasks: Mapping[str, Any]) -> list[tuple[str, Any, str, Any]]:
    libs = list(state.get("libraries", []) or [])
    versions = [v for lib in libs for v in lib.get("versions", []) or []]
    file_diff_pending = sum(1 for v in versions if "file_diff_pending" in _version_tags(v))
    changed = sum(1 for v in versions if "changed" in _version_tags(v))
    return [
        ("Libraries", len(libs), "library count", "PASS"),
        ("Versions", len(versions), "version count", "PASS"),
        ("Changed", changed, "有变化版本", "WARNING" if changed else "PASS"),
        ("File Diff 待完成", file_diff_pending, "需要进入 File Diff 的版本", "WARNING" if file_diff_pending else "PASS"),
        ("Tasks", len(tasks.get("tasks", []) or []), "自动生成的下一步任务", "WARNING" if tasks.get("tasks") else "PASS"),
    ]


def _render_version_page(out: Path, lib: Mapping[str, Any], version: Mapping[str, Any]) -> str:
    lib_id = str(lib.get("library_id") or lib.get("display_name") or "library")
    version_id = str(version.get("version_id") or version.get("version") or "version")
    safe_lib = _safe(lib_id)
    safe_ver = _safe(version_id)
    page = out / "libraries" / safe_lib / "versions" / safe_ver / "index.html"
    links = _version_links(version)
    tags = _version_tags(version)
    timeline = out / "libraries" / safe_lib / "diff_timeline.html"
    rail = ui.status_rail([
        ("Catalog", "DISCOVERED", "版本已进入 catalog"),
        ("Scan", version.get("scan_status") or "NOT_SCANNED", "单版本证据页"),
        ("Diff", version.get("diff_status") or "COMPARE_PENDING", "进入 Diff Timeline 选择 comparison"),
        ("File Diff", version.get("pairwise_status") or "PAIRWISE_EMPTY", _pairwise_text(version)),
        ("Release", version.get("release_status") or "RELEASE_CHECK_REQUIRED", "发布一致性检查"),
    ])
    body = (
        ui.panel(
            "版本导航",
            "普通用户优先打开 Diff Timeline；Scan / Release 作为证据页。",
            ui.metric_grid([
                ("Scan", ui.status_label(version.get("scan_status")), "单版本扫描", version.get("scan_status")),
                ("Diff", ui.status_label(version.get("diff_status")), "版本变化", version.get("diff_status")),
                ("File Diff", _pairwise_text(version), "文件级任务", version.get("pairwise_status")),
                ("Release", ui.status_label(version.get("release_status")), "发布检查", version.get("release_status")),
            ]) + ui.compact_meta([
                ("Library", lib_id), ("Version", version_id), ("Raw Path", version.get("raw_path") or "-"), ("Stage", version.get("stage") or "-"),
            ]),
        )
        + ui.panel("主要入口", "先看库级版本变化，再打开 Selected Diff / File Diff。", ui.action_strip([
            ui.button("Diff Timeline", _href(timeline), "primary", target="_blank"),
            ui.button("Scan Review", _href(links.get("scan_html")), disabled=not links.get("scan_html"), target="_blank"),
            ui.button("Selected Diff", _href(links.get("diff_html")), disabled=not links.get("diff_html"), target="_blank"),
            ui.button("File Diff", _href(links.get("pairwise_html")), disabled=not links.get("pairwise_html"), target="_blank"),
            ui.button("Release Review", _href(links.get("release_html")), disabled=not links.get("release_html"), target="_blank"),
        ]))
        + ui.next_action_panel("下一步", str(version.get("next_command") or ""), str(version.get("next_reason") or "优先进入 Diff Timeline 查看版本变化。"), status=version.get("overall_status") or "INFO")
        + ui.collapsible_panel("Trace Links", "证据链接默认折叠。", ui.trace_link_list([
            ("scan_html", _href(links.get("scan_html")), "单版本 Scan Review"),
            ("diff_html", _href(links.get("diff_html")), "Selected Diff Review"),
            ("pairwise_html", _href(links.get("pairwise_html")), "File Diff 汇总或结果"),
            ("release_html", _href(links.get("release_html")), "Release Review"),
        ]), open=False)
    )
    html = ui.review_page_shell(
        f"{lib.get('display_name') or lib_id} / {version_id}",
        "VERSION REVIEW",
        "版本入口页。面向使用者的主要路径是 Diff Timeline → Selected Diff → File Diff。",
        body,
        decision=version.get("overall_status") or ("REVIEW" if tags - {"clear"} else "PASS"),
        rail=rail,
        nav=f"<a href='../../../index.html'>Catalog</a><a class='active' href='#'>Version</a><a href='../diff_timeline.html'>Diff Timeline</a>",
        meta=ui.compact_meta([("Library", lib_id), ("Version", version_id), ("Tags", ', '.join(sorted(tags)))]),
    )
    _write_text(page, html)
    return str(page)


def _copy_version_alias(out: Path, source: str, legacy_rel: Any) -> None:
    if not legacy_rel:
        return
    legacy = out / str(legacy_rel)
    src = Path(source)
    if legacy.resolve() == src.resolve():
        return
    _write_text(legacy, src.read_text(encoding="utf-8"))


def _render_legacy_library_page(out: Path, lib: Mapping[str, Any]) -> None:
    display = lib.get("display_name") or lib.get("library_name") or lib.get("library_id") or "library"
    page = out / "libraries" / f"{_safe(display)}.html"
    rows: list[str] = []
    safe_lib = _safe(lib.get("library_id") or display)
    timeline = out / "libraries" / safe_lib / "diff_timeline.html"
    for version in lib.get("versions", []) or []:
        links = version.get("links") or {}
        actions = ui.action_strip([
            ui.button("Review", _href(links.get("version_review_html")), "primary", disabled=not links.get("version_review_html"), target="_blank"),
            ui.button("Scan", _href(links.get("scan_html")), disabled=not links.get("scan_html"), target="_blank"),
            ui.button("Diff", _href(links.get("diff_html")), disabled=not links.get("diff_html"), target="_blank"),
            ui.button("File Diff", _href(links.get("pairwise_html")), disabled=not links.get("pairwise_html"), target="_blank"),
            ui.button("Release", _href(links.get("release_html")), disabled=not links.get("release_html"), target="_blank"),
        ])
        rows.append(
            "<tr>"
            f"<td><b>{ui.esc(version.get('version_id'))}</b></td>"
            f"<td>{ui.badge(version.get('scan_status'))}</td>"
            f"<td>{ui.badge(version.get('diff_status'))}</td>"
            f"<td>{ui.badge(version.get('pairwise_status'), _pairwise_text(version))}</td>"
            f"<td>{ui.badge(version.get('release_status'))}</td>"
            f"<td>{actions}{_raw_link_trace(links)}</td>"
            "</tr>"
        )
    body = (
        ui.panel(
            "版本结构 / 证据 / 返回 Catalog",
            "兼容旧入口；新的主路径请打开 Diff Timeline。",
            ui.action_strip([ui.button("Catalog", "../index.html", "secondary"), ui.button("Diff Timeline", _href(timeline), "primary", target="_blank")])
            + ui.table(["Version", "Scan", "Diff", "File Diff", "Release", "Action"], rows, "暂无版本"),
        )
    )
    html = ui.review_page_shell(
        f"{display} Library Review",
        "LIBRARY",
        "Library compatibility page. Primary review path: Diff Timeline → Selected Diff → File Diff.",
        body,
        decision=lib.get("overall_status") or "REVIEW",
        nav="<a href='../index.html'>Catalog</a><a class='active' href='#'>Library</a>",
    )
    _write_text(page, html)


def render_catalog_html(
    catalog_json: str | Path,
    out_dir: str | Path,
    *,
    render_library_pages: bool = True,
    max_attention_items: int = 100,
    max_report_rows: int = 16,
) -> dict[str, Any]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    catalog = read_json(catalog_json, default={}) or {}
    state = build_review_state(catalog, out_dir=out)
    tasks = build_review_tasks(state)
    _ = (max_attention_items, max_report_rows)
    for lib in state.get("libraries", []) or []:
        for version in lib.get("versions", []) or []:
            links = version.setdefault("links", {})
            legacy_review = links.get("version_review_html")
            links["version_review_html"] = _render_version_page(out, lib, version)
            _copy_version_alias(out, links["version_review_html"], legacy_review)
        if render_library_pages:
            _render_legacy_library_page(out, lib)
    write_json(out / "review_state.json", state)
    write_json(out / "review_tasks.json", tasks)
    body = (
        ui.panel(
            "Catalog 总览 / Global Summary / 管理概览",
            "普通用户路径：搜索 library → 打开 Diff Timeline → 进入 Selected Diff → 查看 File Diff。Scan / Release 是证据页。",
            ui.metric_grid(_summary_metrics(state, tasks)),
        )
        + "<div class='catalog-layout'>"
        + f"<div class='catalog-filter-panel'>{_catalog_filter_panel(state)}</div>"
        + f"<div>{ui.panel('Library Browser', '默认按 Vendor / 中间路径分组。版本明细折叠，避免 50 libraries / 500 versions 场景下平铺。', _library_browser(out, state))}</div>"
        + "</div>"
        + ui.collapsible_panel("Review Tasks / Review Queue / 待审阅队列", "系统生成的建议动作。命令用于进入 Scan / Diff / File Diff / Release，不代表自动签核。", ui.filterable_table("catalog-task-table", ["优先级", "类型", "Library / Version", "原因", "命令"], _task_rows(tasks), "暂无任务", "筛选 task / command"), open=False)
        + ui.collapsible_panel("Trace Evidence / Evidence Files / 证据文件", "Catalog 原始证据。", ui.trace_link_list([
            ("review_state.json", _href(out / "review_state.json"), "Catalog 页面使用的状态模型"),
            ("review_tasks.json", _href(out / "review_tasks.json"), "建议动作列表"),
            ("catalog.json", _href(catalog_json), "原始 catalog"),
        ]), open=False)
    )
    html = ui.review_page_shell(
        "ai_lib Library Catalog",
        "CATALOG",
        "库版本变化导航入口。主要价值是找到版本变化和 File Diff 入口。",
        body,
        decision="REVIEW" if tasks.get("tasks") else "PASS",
        nav="<a class='active' href='#'>Catalog</a><a href='#'>Diff Timeline</a><a href='#'>Selected Diff</a><a href='#'>File Diff</a><a href='#'>Release</a>",
        meta=ui.compact_meta([("Libraries", len(state.get("libraries", []) or [])), ("Tasks", len(tasks.get("tasks", []) or []))]),
    )
    index = out / "index.html"
    _write_text(index, html)
    return {
        "status": "PASS",
        "catalog_path": str(catalog_json),
        "html_dir": str(out),
        "index_html": str(index),
        "review_state": str(out / "review_state.json"),
        "review_tasks": str(out / "review_tasks.json"),
    }
