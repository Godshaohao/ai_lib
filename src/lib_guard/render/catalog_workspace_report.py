"""Catalog index and library workspace report renderer."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from lib_guard.render import catalog_render_common as common
from lib_guard.render import catalog_report as catalog
from lib_guard.render import library_workspace_model as workspace_model
from lib_guard.render import product_theme as ui


def render_library_workspace_page(
    out: str | Path,
    lib: Mapping[str, Any],
    effective_items: list[dict[str, Any]],
    compare_items: list[dict[str, Any]] | None = None,
) -> str:
    return _render_library_home(Path(out), lib, effective_items, compare_items)


def catalog_browser_styles() -> str:
    return _catalog_browser_styles()


def build_library_report_index_entry(
    out: str | Path,
    lib: Mapping[str, Any],
    effective_items: list[dict[str, Any]],
    compare_items: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    out_path = Path(out)
    lib_id = str(lib.get("library_id") or lib.get("display_name") or lib.get("library_name") or "")
    timeline, latest_effective_ref = catalog._library_timeline(lib, effective_items)
    versions: dict[str, Any] = {}
    for version in lib.get("versions", []) or []:
        version_id = str(version.get("version_id") or version.get("version") or "")
        links = common.version_links(version)
        refs = catalog._version_effective_refs(version_id, effective_items)
        versions[version_id] = {
            "home": common.rel_href(out_path, links.get("version_review_html")),
            "scan": common.rel_href(out_path, links.get("scan_html")),
            "diffs": [common.rel_href(out_path, links.get("diff_html"))] if links.get("diff_html") else [],
            "contributes_to_effective": [str(item.get("effective_id")) for item in refs],
        }
    effective = {
        str(item.get("effective_id")): {
            "html": common.rel_href(out_path, item.get("html")),
            "manifest": common.rel_href(out_path, item.get("manifest")),
            "release_preview": common.rel_href(out_path, item.get("release_preview")),
            "release_manifest": common.rel_href(out_path, item.get("release_manifest")),
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
    current_effective = catalog._latest_effective_item(effective_items) or {}
    compare_reports = {
        str(item.get("compare_id")): {
            "mode": item.get("mode"),
            "old_target": item.get("old_target", {}),
            "new_target": item.get("new_target", {}),
            "owner_target": item.get("owner_target") or "",
            "html": common.rel_href(out_path, item.get("html")),
            "manifest": common.rel_href(out_path, item.get("manifest")),
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
        "home": common.rel_href(out_path, lib.get("library_home_html")),
        "versions": versions,
        "effective": effective,
        "current_effective": str(current_effective.get("effective_id") or "") if current_effective else "",
        "latest_effective_ref": latest_effective_ref,
        "timeline": catalog._timeline_for_report_index(out_path, timeline),
        "compare_reports": compare_reports,
    }


_safe = common.safe
_write_text = common.write_text
_href = common.href
_short_path = common.short_path


def _version_display_text(version: Mapping[str, Any]) -> str:
    return catalog._version_display_text(version)


def _timeline_rows(out: Path, timeline: list[dict[str, Any]], latest_effective_ref: str) -> list[str]:
    rows = []
    for node in reversed(timeline):
        node_kind = str(node.get("node_kind") or "-")
        package_type = str(node.get("package_type") or "-")
        version_id = str(node.get("version_id") or "-")
        usage = str(node.get("usage_status") or "-")
        pointer = "current" if latest_effective_ref and version_id == latest_effective_ref else "-"
        detail_href = node.get("html") or node.get("home")
        if node_kind == "raw" and not detail_href:
            detail_href = node.get("scan") or ((node.get("diffs") or [""])[0])
        source_text = ", ".join(str(v) for v in node.get("sources", []) or []) or ", ".join(str(v) for v in node.get("used_by", []) or []) or node.get("base_ref") or "-"
        rows.append(
            "<tr>"
            f"<td>{ui.esc(node.get('event_time') or '-')}</td>"
            f"<td><b title='{ui.esc(version_id)}'>{ui.esc(common.short_name(version_id))}</b></td>"
            f"<td>{ui.badge(node_kind, node_kind)} {ui.badge(package_type, package_type)}</td>"
            f"<td>{ui.badge(usage, usage.replace('_', ' '))}</td>"
            f"<td>{ui.badge('CURRENT' if pointer == 'current' else 'INFO', pointer)}</td>"
            f"<td><span title='{ui.esc(source_text)}'>{ui.esc(common.short_name(source_text))}</span></td>"
            f"<td>{ui.action_strip([ui.button('Open', _href(detail_href), 'primary' if pointer == 'current' else 'secondary', disabled=not bool(detail_href), target='_blank')])}</td>"
            "</tr>"
        )
    return rows


def _version_primary_action(version: Mapping[str, Any]) -> tuple[str, str, str, bool]:
    links = common.version_links(version)
    relation = common.relation_status(version)
    version_review = _href(links.get("version_review_html"))
    if relation == "NEED_BINDING":
        return "绑定", version_review, "primary", not bool(version_review)
    if links.get("diff_html"):
        return "差异", _href(links.get("diff_html")), "primary", False
    if links.get("scan_html"):
        return "扫描", _href(links.get("scan_html")), "secondary", False
    if version_review:
        return "详情", version_review, "secondary", False
    return "待处理", "", "secondary", True


def _compare_target_label(target: Mapping[str, Any]) -> str:
    if not isinstance(target, Mapping):
        return "-"
    return str(target.get("label") or f"{target.get('type') or 'target'}:{target.get('id') or '-'}")


def _compare_index_rows(lib: Mapping[str, Any], compare_items: list[dict[str, Any]] | None = None) -> list[str]:
    rows = []
    for item in compare_items or []:
        old_label = _compare_target_label(item.get("old_target", {}) or {})
        new_label = _compare_target_label(item.get("new_target", {}) or {})
        actions = item.get("actions", {}) or {}
        status = "RISK" if item.get("risk_count") else ("CHANGED" if item.get("changed_files") else "OK")
        rows.append(
            "<tr>"
            f"<td><code>{ui.esc(item.get('mode') or '-')}</code><div class='muted'>{ui.esc(item.get('compare_id') or '-')}</div></td>"
            f"<td><span title='{ui.esc(old_label)}'>{ui.esc(common.short_name(old_label))}</span></td>"
            f"<td><span title='{ui.esc(new_label)}'>{ui.esc(common.short_name(new_label))}</span></td>"
            f"<td>{ui.badge(status, {'RISK': '需复核', 'CHANGED': '有变化', 'OK': '无变化'}.get(status, status))}</td>"
            f"<td>{ui.esc(item.get('changed_files', 0))}</td>"
            f"<td>{ui.esc(actions.get('replace', 0))}</td>"
            f"<td><span title='{ui.esc(item.get('owner_target') or '')}'>{ui.esc(common.short_name(item.get('owner_target') or '-'))}</span></td>"
        f"<td>{ui.action_strip([ui.button('打开报告', _href(item.get('html')), 'primary', disabled=not bool(item.get('html')), target='_blank'), ui.button('清单', _href(item.get('manifest')), 'secondary', disabled=not bool(item.get('manifest')), target='_blank')])}</td>"
            "</tr>"
        )
    if rows:
        return rows
    for item in catalog._build_comparisons_for_library(lib):
        old_version = str(item.get("old_version") or "-")
        new_version = str(item.get("new_version") or "-")
        diff_html = item.get("diff_html")
        rows.append(
            "<tr>"
            f"<td><code>{ui.esc(item.get('mode') or '-')}</code></td>"
            f"<td><span title='{ui.esc(old_version)}'>{ui.esc(common.short_name(old_version))}</span></td>"
            f"<td><span title='{ui.esc(new_version)}'>{ui.esc(common.short_name(new_version))}</span></td>"
            f"<td>{ui.badge(item.get('status') or 'COMPARE_PENDING')}</td>"
            f"<td>{ui.esc(item.get('recommended_total', 0))}</td>"
            f"<td>{ui.esc(item.get('candidate_total', 0))}</td>"
            f"<td>{ui.badge(item.get('comparison_quality') or 'NORMAL')}</td>"
            f"<td>{ui.button('对比', diff_html, 'primary', disabled=not bool(diff_html), target='_blank')}</td>"
            "</tr>"
        )
    return rows


def _version_id(version: Mapping[str, Any] | None) -> str:
    return workspace_model.version_id(version)


def _diff_label(version: Mapping[str, Any] | None) -> tuple[str, str]:
    return workspace_model.diff_label(version)


def _display_badge(status: Any, label: Any) -> str:
    text = ui.esc(label or ui.status_label(status) or "-")
    return f"<span class='badge {ui.status_class(status)}' title='{text}'>{text}</span>"


def _version_detail_href(version: Mapping[str, Any] | None) -> str:
    if not isinstance(version, Mapping):
        return ""
    links = common.version_links(version)
    return _href(links.get("version_review_html") or links.get("scan_html") or links.get("diff_html"))


def _candidate_action_text(candidate: Mapping[str, Any] | None, current_ref: str) -> str:
    return workspace_model.candidate_action_text(candidate, current_ref)


def _library_entry_summary(
    lib: Mapping[str, Any],
    effective_items: list[dict[str, Any]],
    timeline: list[dict[str, Any]],
    latest_effective_ref: str,
) -> dict[str, Any]:
    model = workspace_model.build_library_workspace_model(
        lib,
        effective_items,
        timeline=timeline,
        latest_effective_ref=latest_effective_ref,
    )
    return {
        "current_ref": model["current_effective_ref"],
        "current_source": model["current_effective_source"],
        "current_confirmed": model["current_effective_confirmed"],
        "current_version": model["current_effective_version"],
        "candidate_ref": model["latest_candidate_ref"],
        "candidate": model["latest_candidate_version"],
        "candidate_hint": model["candidate_action_text"],
        "base_ref": model["base_ref"],
        "scan_status": model["scan_status"],
        "scan_text": model["scan_text"],
        "scan_note": model["scan_note"],
        "diff_status": model["diff_status"],
        "diff_text": model["diff_text"],
        "diff_note": model["diff_note"],
        "release_status": model["release_status"],
        "decision": model["decision"],
        "needs_review": model["needs_review"],
        "timeline_count": model["timeline_count"],
        "version_count": model["version_count"],
        "effective_ref": model["effective_evidence_ref"],
        "effective_manifest": _href(model["effective_evidence_manifest"]),
        "current_effective_html": _href(model["effective_evidence_html"]),
        "release_preview_html": _href(model["effective_evidence_release_preview"]),
        "candidate_detail_href": _version_detail_href(model["latest_candidate_version"]),
    }


def _focus_card(label: str, value: Any, hint: str, status: str, href: str = "", action: str = "打开") -> str:
    button = ui.button(action, href, "primary" if href else "secondary", disabled=not bool(href), target="_blank")
    return (
        f"<div class='library-focus-card {ui.esc(status.lower())}'>"
        f"<div class='focus-label'>{ui.esc(label)}</div>"
        f"<div class='focus-value long-token' title='{ui.esc(value)}'>{ui.esc(value or '-')}</div>"
        f"<p>{ui.esc(hint)}</p>"
        f"<div class='focus-action'>{button}</div>"
        "</div>"
    )


def _library_focus_panel(summary: Mapping[str, Any]) -> str:
    candidate = summary.get("candidate") if isinstance(summary.get("candidate"), Mapping) else {}
    current_hint = {
        "effective_manifest": "来自当前有效版 manifest",
        "catalog_current": "来自库目录当前指针",
        "version_flag": "来自版本 current_effective 标记",
        "latest_full_fallback": "未设置 effective，退到最新完整包",
        "latest_version_fallback": "未设置 effective，退到最新版本",
        "missing": "未找到当前有效版",
        "unconfirmed": "当前有效版未确认；请先通过库覆盖或审查窗口确认",
    }.get(str(summary.get("current_source")), str(summary.get("current_source") or "-"))
    effective_ref = str(summary.get("effective_ref") or "")
    if effective_ref and summary.get("current_source") != "effective_manifest":
        current_hint = f"{current_hint}；已发现有效版证据 {effective_ref}"
    body = (
        "<div class='library-focus-grid'>"
        + _focus_card("当前有效版", summary.get("current_ref"), current_hint, "ok" if summary.get("current_confirmed") else "warn", summary.get("current_effective_html") or _version_detail_href(summary.get("current_version") if isinstance(summary.get("current_version"), Mapping) else None))
        + _focus_card("最新待审版", summary.get("candidate_ref"), summary.get("candidate_hint") or _candidate_action_text(candidate, str(summary.get("current_ref") or "")), "warn" if summary.get("needs_review") else "ok", str(summary.get("candidate_detail_href") or ""))
        + _focus_card("正式发布", ui.status_label(summary.get("release_status")) or summary.get("release_status"), "正式放行状态只作入口提示，不覆盖 IP 接入判断", "neutral", summary.get("release_preview_html"), "查看发布")
        + "</div>"
    )
    return ui.panel("库入口", "只显示当前有效版、最新待审版和必要证据入口；历史扫描/对比下沉到折叠区。", body)


def _review_now_panel(summary: Mapping[str, Any]) -> str:
    rows = [
        ("对比范围", f"{summary.get('candidate_ref')} vs {summary.get('base_ref')}", "最新待审版相对当前/上一有效版"),
        ("扫描", summary.get("scan_text"), summary.get("scan_note")),
        ("对比", summary.get("diff_text"), summary.get("diff_note")),
        ("判断", summary.get("decision"), "是否需要进入版本详情审查"),
    ]
    row_html = "".join(
        "<tr>"
        f"<td>{ui.esc(name)}</td>"
        f"<td><b>{ui.esc(value)}</b></td>"
        f"<td>{ui.esc(hint)}</td>"
        "</tr>"
        for name, value, hint in rows
    )
    actions = ui.action_strip([
        ui.button("打开最新版本详情", summary.get("candidate_detail_href"), "primary", disabled=not bool(summary.get("candidate_detail_href")), target="_blank"),
        ui.button("打开当前有效版", summary.get("current_effective_html"), "secondary", disabled=not bool(summary.get("current_effective_html")), target="_blank"),
    ])
    return ui.panel(
        "本次审查",
        "库页只回答当前该看哪一版；视图变化、文件变化和解析证据留在版本详情。",
        "<div class='library-review-now'>"
        f"<div class='table-wrap'><table><thead><tr><th>项目</th><th>值</th><th>说明</th></tr></thead><tbody>{row_html}</tbody></table></div>"
        f"<div class='review-actions'>{actions}</div>"
        "</div>",
    )


def _history_version_rows(lib: Mapping[str, Any], versions: list[Mapping[str, Any]]) -> list[str]:
    rows = []
    latest = lib.get("latest_version") or (_version_id(versions[-1]) if versions else "")
    for version in reversed(versions):
        version_id = _version_id(version)
        pkg_status, pkg_label = catalog._package_label(version)
        scan_status, scan_text = catalog._scan_label(version)
        diff_status, diff_text = _diff_label(version)
        relation = common.relation_label(common.relation_status(version))
        action = ui.button("详情", _version_detail_href(version), "secondary", disabled=not bool(_version_detail_href(version)), target="_blank")
        rows.append(
            "<tr>"
            f"<td><b title='{ui.esc(version_id)}'>{ui.esc(common.short_name(version_id))}</b>{' ' + _display_badge('INFO', '最新') if version_id == str(latest) else ''}</td>"
            f"<td>{_display_badge(pkg_status, pkg_label)}</td>"
            f"<td>{_display_badge(scan_status, scan_text)}</td>"
            f"<td>{_display_badge(diff_status, diff_text)}</td>"
            f"<td>{ui.esc(relation)}</td>"
            f"<td>{action}</td>"
            "</tr>"
        )
    return rows


def _library_version_ledger_panel(lib: Mapping[str, Any], versions: list[Mapping[str, Any]]) -> str:
    rows = _history_version_rows(lib, versions)
    row_html = "".join(rows) if rows else "<tr><td class='empty' colspan='6'>暂无版本</td></tr>"
    body = (
        "<div class='library-version-ledger table-wrap'>"
        "<table><thead><tr><th>版本</th><th>包类型</th><th>扫描</th><th>对比</th><th>关系</th><th>入口</th></tr></thead>"
        f"<tbody>{row_html}</tbody></table>"
        "</div>"
    )
    return ui.panel(
        "库版本清单",
        f"保留该库全部 {len(versions)} 个版本的定位入口；版本详情仍只在需要时刷新，不在库页展开所有 scan/diff 明细。",
        body,
    )


def _render_library_home(out: Path, lib: Mapping[str, Any], effective_items: list[dict[str, Any]], compare_items: list[dict[str, Any]] | None = None) -> str:
    lib_id = str(lib.get("library_id") or lib.get("display_name") or "library")
    safe = _safe(lib_id)
    html_path = out / "libraries" / safe / "index.html"
    versions = list(lib.get("versions", []) or [])
    timeline, latest_effective_ref = catalog._library_timeline(lib, effective_items)
    summary = _library_entry_summary(lib, effective_items, timeline, latest_effective_ref)
    del compare_items
    body = (
        _catalog_browser_styles()
        + _library_focus_styles()
        + _library_focus_panel(summary)
        + _review_now_panel(summary)
        + _library_version_ledger_panel(lib, versions)
    )
    html = ui.review_page_shell(
        f"{lib.get('display_name') or lib_id} / 库工作台",
        "库工作台",
        "库目录的下钻主页：先确认当前有效版，再审查最新待审版。",
        body,
        decision="REVIEW" if summary.get("needs_review") else (lib.get("overall_status") or "PASS"),
        nav="<a href='../../index.html'>库目录</a><a class='active' href='#'>库工作台</a>",
        meta=ui.compact_meta([
            ("库", lib.get("formal_library_id") or lib.get("library_name") or lib_id),
            ("当前有效版", summary.get("current_ref") or "-"),
            ("最新待审版", summary.get("candidate_ref") or "-"),
            ("历史版本", summary.get("version_count")),
        ]),
    )
    _write_text(html_path, html)
    return str(html_path)


def _latest_full_version(versions: list[Mapping[str, Any]]) -> str:
    for version in reversed(versions):
        if common.is_full_baseline(version):
            return str(version.get("version_id") or version.get("version") or "-")
    return "-"


def _latest_effective_version(lib: Mapping[str, Any], versions: list[Mapping[str, Any]], effective_items: list[dict[str, Any]]) -> str:
    current_ref, _current_version, source = workspace_model.current_effective_version(lib, versions, effective_items)
    if source in {"unconfirmed", "missing"} or not current_ref:
        return "未确认"
    return current_ref


def _version_row(lib: Mapping[str, Any], version: Mapping[str, Any], latest: Any) -> str:
    version_id = str(version.get("version_id") or version.get("version") or "-")
    is_latest = "1" if str(version_id) == str(latest) else "0"
    tags = ",".join(sorted(catalog._version_tags(version)))
    stage = str(version.get("stage") or "-")
    pkg_status, pkg_label = catalog._package_label(version)
    scan_status, scan_text = catalog._scan_label(version)
    file_status = common.file_review_status(version)
    base_full = common.base_full_version(version)
    prev_eff = common.previous_effective_version(version)
    label, href, kind, disabled = _version_primary_action(version)
    release_html = f"<span class='release-mini'>{ui.badge(version.get('release_status'), '发布')}</span>" if catalog._release_is_visible(version, lib) else ""
    review_hint = ui.badge(file_status, common.file_review_text(version)) if file_status != "PAIRWISE_EMPTY" else ""
    stage_html = "" if stage.lower() in {"", "-", "unknown"} else ui.badge(stage, stage)
    scan_html = "" if scan_status == "NOT_SCANNED" else ui.badge(scan_status, scan_text)
    relation_html = "<div class='version-relation version-relation-empty' aria-hidden='true'></div>"
    if base_full or prev_eff:
        relation_html = (
            "<div class='version-relation'>"
            f"<span><b>基线</b><em title='{ui.esc(base_full or '-')}'>{ui.esc(base_full or '-')}</em></span>"
            f"<span><b>前版</b><em title='{ui.esc(prev_eff or '-')}'>{ui.esc(prev_eff or '-')}</em></span>"
            "</div>"
        )
    return (
        f"<div class='version-row' data-tags='{ui.esc(tags)}' data-latest='{is_latest}' data-search='{ui.esc(_version_display_text(version))}'>"
        "<div class='version-id-cell'>"
        f"<div class='version-name long-token' title='{ui.esc(version_id)}'>{ui.esc(version_id)}</div>"
        f"<div class='version-path' title='{ui.esc(version.get('raw_path'))}'>{ui.esc(_short_path(version.get('raw_path')))}</div>"
        "</div>"
        "<div class='version-badges'>"
        f"{ui.badge(pkg_status, pkg_label)}{stage_html}{scan_html}{review_hint}{release_html}"
        "</div>"
        f"{relation_html}"
        f"<div class='version-action'>{ui.button(label, href, kind, disabled=disabled, target='_blank')}</div>"
        "</div>"
    )


def _library_card(out: Path, lib: Mapping[str, Any], effective_items: list[dict[str, Any]]) -> str:
    versions = list(lib.get("versions", []) or [])
    latest = lib.get("latest_version") or (versions[-1].get("version_id") if versions else "-")
    latest_full = _latest_full_version(versions)
    latest_effective = _latest_effective_version(lib, versions, effective_items)
    _current_ref, _current_version, current_source = workspace_model.current_effective_version(lib, versions, effective_items)
    current_confirmed = bool(versions) and current_source not in {"unconfirmed", "missing"}
    status = lib.get("overall_status") or "UNKNOWN"
    vendor = str(lib.get("vendor") or "Unknown")
    middle = str(lib.get("middle_path") or lib.get("library_root") or "-")
    stages = sorted({str(v.get("stage") or "unknown") for v in versions})
    tags = catalog._library_tags(lib)
    if versions and not current_confirmed:
        tags.discard("clear")
        tags.add("review")
    home_path = str(lib.get("library_home_html") or "")
    latest_effective_item = catalog._latest_effective_item(effective_items)
    changed = sum(1 for v in versions if "changed" in catalog._version_tags(v))
    version_rows = "".join(_version_row(lib, v, latest) for v in reversed(versions))
    user_library_id = lib.get("formal_library_id") or lib.get("library_name") or lib.get("library_id")
    library_label = lib.get("display_name") or user_library_id
    empty_versions = "<div class='catalog-empty'>暂无 version</div>"
    version_list_html = version_rows or empty_versions
    actions = ui.action_strip([
        ui.button("进入库工作台", _href(home_path), "primary", disabled=not bool(home_path), target="_blank"),
        ui.button("有效版", _href((latest_effective_item or {}).get("html")), "secondary", disabled=not bool((latest_effective_item or {}).get("html")), target="_blank"),
    ])
    effective_label = str((latest_effective_item or {}).get("effective_id") or latest_effective)
    status_for_display = "REVIEW" if versions and not current_confirmed and common.status_key(status) == "UNKNOWN" else status
    status_badge = "" if common.status_key(status_for_display) == "UNKNOWN" else ui.badge(status_for_display)
    changed_badge = ui.quiet_badge("CHANGED", changed) if changed else ""
    return (
        f"<section class='library-card' data-overall='{ui.esc(status_for_display)}' data-vendor='{ui.esc(vendor)}' data-stages='{ui.esc(','.join(stages))}' data-tags='{ui.esc(','.join(sorted(tags)))}'>"
        "<div class='library-main'>"
        f"<div class='library-name-row'><div class='library-title long-token' title='{ui.esc(library_label)}'>{ui.esc(library_label)}</div></div>"
        f"<div class='library-path-row'><span class='muted'>库名</span><code title='{ui.esc(user_library_id)}'>{ui.esc(user_library_id or '-')}</code></div>"
        f"<div class='library-path-row'><span class='muted'>路径</span><code title='{ui.esc(middle)}'>{ui.esc(middle)}</code></div>"
        f"<div><span class='muted'>供应方</span><br><b>{ui.esc(vendor)}</b></div>"
        f"<div><span class='muted'>完整基线</span><br><b title='{ui.esc(latest_full)}'>{ui.esc(latest_full)}</b></div>"
        f"<div><span class='muted'>当前有效</span><br><b title='{ui.esc(effective_label)}'>{ui.esc(effective_label)}</b></div>"
        "<div class='library-status'>"
        f"{status_badge}<span class='browser-count'>{len(versions)} 版</span>{changed_badge}{actions}"
        "</div></div>"
        f"<details class='version-drawer' {'open' if changed else ''}><summary>版本明细 / 默认展开有更新库</summary><div class='version-list'>{version_list_html}</div></details>"
        "</section>"
    )


def _group_libraries(libraries: list[Mapping[str, Any]]) -> dict[tuple[str, str], list[Mapping[str, Any]]]:
    grouped: dict[tuple[str, str], list[Mapping[str, Any]]] = {}
    for lib in libraries:
        key = (str(lib.get("vendor") or "Unknown"), str(lib.get("middle_path") or lib.get("library_root") or "-"))
        grouped.setdefault(key, []).append(lib)
    return dict(sorted(grouped.items(), key=lambda kv: (kv[0][0], kv[0][1])))


def _library_browser(out: Path, state: Mapping[str, Any], effective_by_lib: Mapping[str, list[dict[str, Any]]]) -> str:
    libraries = list(state.get("libraries", []) or [])
    groups = _group_libraries(libraries)
    group_html = []
    for (vendor, middle), libs in groups.items():
        cards = "".join(_library_card(out, lib, catalog._effective_items_for_lib(effective_by_lib, lib)) for lib in libs)
        has_attention = any((catalog._library_tags(lib) & {"review", "block", "file_review_pending", "file_review_recommended", "not_scanned", "needs_comparison_confirm"}) for lib in libs)
        group_html.append(
            f"<details class='library-group' {'open' if has_attention else ''}>"
            f"<summary><div class='library-group-title'><b>{ui.esc(vendor)}</b><span>{ui.esc(middle)}</span></div><span class='browser-count'>{len(libs)} 库</span></summary>"
            f"<div class='library-group-body'>{cards}</div></details>"
        )
    return "<div class='library-browser' data-catalog-browser data-status-filter='all'>" + ("".join(group_html) or "<div class='catalog-empty'>暂无 library</div>") + "</div>"


def _catalog_filter_panel(state: Mapping[str, Any]) -> str:
    libraries = list(state.get("libraries", []) or [])
    vendors = sorted({str(lib.get("vendor") or "Unknown") for lib in libraries})
    stages = sorted(
        {
            str(v.get("stage") or "unknown")
            for lib in libraries
            for v in (lib.get("versions", []) or [])
            if str(v.get("stage") or "unknown").lower() not in {"", "-", "unknown"}
        }
    )
    vendor_opts = "<option value='all'>全部供应方</option>" + "".join(f"<option value='{ui.esc(v)}'>{ui.esc(v)}</option>" for v in vendors)
    stage_opts = "<option value='all'>全部阶段</option>" + "".join(f"<option value='{ui.esc(s)}'>{ui.esc(s)}</option>" for s in stages)
    chips = [("all", "全部"), ("changed", "有更新"), ("file_review_recommended", "重点文件"), ("not_scanned", "待补证据"), ("review", "需审查"), ("block", "阻塞"), ("clear", "正常")]
    chip_html = "".join(f"<button type='button' class='filter-chip {'active' if k == 'all' else ''}' data-catalog-status-chip='{k}' onclick=\"setCatalogStatusFilter('{k}', this)\">{ui.esc(v)}</button>" for k, v in chips)
    body = (
        "<div class='search'><span>搜索</span><input id='catalog-search' type='search' placeholder='库 / 版本 / 供应方 / 路径' oninput='filterCatalogBrowser()'></div>"
        "<div class='filter-group-title'>供应方</div>" + f"<select id='catalog-vendor' onchange='filterCatalogBrowser()'>{vendor_opts}</select>"
        "<div class='filter-group-title'>阶段</div>" + f"<select id='catalog-stage' onchange='filterCatalogBrowser()'>{stage_opts}</select>"
        "<label style='display:flex;gap:8px;align-items:center;margin:10px 0;color:#667085;font-size:13px'><input id='catalog-latest' type='checkbox' onchange='filterCatalogBrowser()'> 只看最新版本</label>"
        "<div class='filter-group-title'>状态</div>" + f"<div class='catalog-chips'>{chip_html}</div>"
        "<div class='filter-group-title'>操作</div>"
        + ui.action_strip(["<button class='btn secondary' type='button' onclick=\"catalogExpand('review')\">展开关注</button>", "<button class='btn secondary' type='button' onclick=\"catalogExpand('collapse')\">折叠</button>", "<button class='btn secondary' type='button' onclick='resetCatalogFilters()'>重置</button>"])
        + "<div id='catalog-visible-count' class='browser-count' style='margin-top:12px'>-</div><script>setTimeout(filterCatalogBrowser,0)</script>"
    )
    return ui.panel("筛选", "按库、版本、供应方、阶段、状态快速定位。", body)


def _task_rows(tasks: Mapping[str, Any], limit: int = 50) -> list[str]:
    rows = []
    skipped_file_diff = 0
    for task in tasks.get("tasks", []) or []:
        task_type = str(task.get("task_type") or "")
        command = str(task.get("command") or "")
        if "release" in task_type.lower() or " release " in f" {command.lower()} ":
            continue
        if ("file" in task_type.lower() and "diff" in task_type.lower()) or " file-diff " in f" {command} ":
            skipped_file_diff += 1
            continue
        if len(rows) >= limit:
            break
        rows.append(
            "<tr>"
            f"<td>{ui.badge(task.get('priority'), task.get('priority'))}</td>"
            f"<td><code>{ui.esc(task_type)}</code></td>"
            f"<td><b>{ui.esc(task.get('display_name'))}</b><div class='muted'>{ui.esc(task.get('version_id'))}</div></td>"
            f"<td>{ui.esc(task.get('reason'))}</td>"
            f"<td><span class='muted'>按下方命令示例执行</span></td></tr>"
        )
    if skipped_file_diff:
        rows.append("<tr><td><span class='muted'>-</span></td><td><code>file-diff</code></td><td><b>文件深度对比命令已下沉</b></td>" + f"<td>共 {ui.esc(skipped_file_diff)} 条文件深度对比候选命令不在库目录展开；请进入版本更新详情里的重点文件建议。</td><td><span class='muted'>不在库目录生成全量命令</span></td></tr>")
    return rows


def _command_examples() -> str:
    examples = [("刷新目录", "$PROJ/scripts/lg.csh cat"), ("扫描版本", "$PROJ/scripts/lg.csh scan <library> <version>"), ("绑定关系", "$PROJ/scripts/lg.csh library override <library> <version> --package-type PARTIAL_UPDATE --update-scope lib,lef --base-full <full_version> --previous-effective <prev_version> --note \"manual confirmed\""), ("执行对比", "$PROJ/scripts/lg.csh cmp <library> <version> --scan-if-missing"), ("发布检查", "$PROJ/scripts/lg.csh rel <library> <version> --check-first"), ("PowerShell", ".\\scripts\\lg.ps1 cmp <library> <version> --scan-if-missing")]
    boxes = "".join(ui.command_box(command, title=title, note="示例命令。实际执行时替换 <library> / <version> / <relpath>。") for title, command in examples)
    return "<div class='command-example-grid'>" + boxes + "</div>"


def _library_focus_styles() -> str:
    return """
<style>
.library-focus-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px}
.library-focus-card{border:1px solid var(--line);border-radius:14px;background:#fff;padding:15px;display:flex;flex-direction:column;gap:8px;min-height:178px}
.library-focus-card.ok{border-left:4px solid var(--green);background:linear-gradient(180deg,#fff,#fbfffc)}
.library-focus-card.warn{border-left:4px solid var(--amber);background:linear-gradient(180deg,#fff,#fffaf1)}
.library-focus-card.neutral{border-left:4px solid var(--line-strong);background:linear-gradient(180deg,#fff,#fbfcff)}
.focus-label{font-size:12px;color:#667085;font-weight:800;letter-spacing:.02em}
.focus-value{font-size:19px;line-height:1.25;font-weight:850;color:#172033}
.library-focus-card p{font-size:12px;color:#667085;min-height:38px}
.focus-action{margin-top:auto}
.library-review-now{display:grid;grid-template-columns:minmax(0,1fr);gap:12px}
.review-actions{display:flex;justify-content:flex-start}
.history-ledger .panel-head{background:#fbfcff}
.library-version-ledger{max-height:460px;overflow:auto;scrollbar-gutter:stable}
.library-version-ledger table{min-width:860px}
.library-version-ledger th{position:sticky;top:0;z-index:1}
@media(max-width:980px){.library-focus-grid{grid-template-columns:1fr}.library-focus-card{min-height:auto}}
</style>
"""


def _catalog_browser_styles() -> str:
    return """
<style>
.library-main{grid-template-columns:minmax(140px,.8fr) minmax(128px,.7fr) minmax(128px,.7fr);align-items:start}
.library-main>div{min-width:0}.library-main b[title]{display:inline-block;max-width:100%;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;vertical-align:bottom}.library-name-row,.library-path-row,.library-status{grid-column:1/-1}.library-name-row{padding-bottom:2px}.library-title{font-size:18px;line-height:1.28}.library-path-row{display:grid;grid-template-columns:72px minmax(0,1fr);gap:10px;align-items:start;border:1px solid var(--line);border-radius:9px;background:#f8fafc;padding:7px 9px}.library-path-row span{font-size:12px;font-weight:800}.library-path-row code{display:block;color:#344054;white-space:normal;overflow-wrap:anywhere;word-break:break-word}.library-status{min-width:0;justify-content:flex-start;padding-top:10px;margin-top:2px;border-top:1px dashed var(--line);overflow:visible}.library-status .action-strip{max-width:100%;min-width:0;overflow:visible;white-space:normal;flex-wrap:wrap;padding-bottom:0}.long-token{overflow-wrap:anywhere;word-break:break-word;hyphens:auto}.library-title.long-token{display:block}.version-name.long-token{display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}.version-list{gap:7px}.version-row{display:grid;grid-template-columns:minmax(0,1.35fr) minmax(210px,1fr) minmax(220px,.95fr) minmax(76px,auto);gap:12px;align-items:center;border:1px solid var(--line);background:#fff;border-radius:11px;padding:10px 12px}.version-id-cell{min-width:0}.version-name{font-weight:800;font-size:14px;line-height:1.25}.version-path{font-size:12px;color:var(--muted);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;margin-top:3px}.version-badges{display:flex;gap:6px;align-items:center;flex-wrap:wrap;min-width:0}.version-badges .badge{max-width:132px}.version-relation{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:6px;min-width:0}.version-relation span{border:1px solid var(--line);border-radius:8px;background:#f8fafc;padding:5px 7px;min-width:0}.version-relation b{display:block;color:#667085;font-size:11px;line-height:1.2}.version-relation em{display:block;font-style:normal;font-size:12px;color:#344054;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.version-action{text-align:right;min-width:0}.version-action .btn{max-width:100%}.table-wrap td code{white-space:normal;overflow-wrap:anywhere;word-break:break-word}.absolute-path-box{margin:0 0 18px;border:1px solid var(--line);border-radius:10px;background:#f8fafc;padding:10px 12px}.absolute-path-box b{display:block;font-size:12px;color:#667085;margin-bottom:4px}.absolute-path-box code{display:block;color:#344054;white-space:normal;overflow-wrap:anywhere;word-break:break-word}.version-scroll-table{max-width:100%;overflow:auto;scrollbar-gutter:stable;border:1px solid var(--line);border-radius:10px;background:#fff;margin-top:12px}.version-scroll-table table{min-width:720px}.version-scroll-table.change-scroll table{min-width:1800px}.version-scroll-table.metric-scroll{max-height:300px}.version-scroll-table.change-scroll{height:420px;max-height:420px;overflow:scroll}.version-scroll-table th{position:sticky;top:0;z-index:1}.version-scroll-table td code{white-space:nowrap;overflow-wrap:normal;word-break:normal}.version-scroll-table.change-scroll td:nth-child(3) code{display:inline-block;min-width:1080px}.trace-link-row{min-width:0}.trace-link-row>div{min-width:0}.release-mini{display:inline-flex}.command-example-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:12px}.catalog-note{border:1px solid var(--line);border-radius:12px;background:#f8fafc;padding:12px;color:#667085;font-size:13px}@media(max-width:1180px){.library-main{grid-template-columns:1fr}.library-path-row{grid-template-columns:1fr}.version-row{grid-template-columns:1fr}.version-action{text-align:left}.version-relation{grid-template-columns:1fr}}
.effective-summary{display:flex;flex-direction:column;gap:12px}.effective-head{display:flex;justify-content:space-between;gap:12px;align-items:flex-start}.effective-head h3{margin:3px 0 0;font-size:18px;max-width:680px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.effective-stack{display:flex;gap:8px;overflow-x:auto;padding-bottom:2px}.effective-chip{flex:0 0 220px;border:1px solid var(--line);border-radius:10px;background:#f8fafc;padding:9px}.effective-chip.base{background:#eff6ff;border-color:#bfdbfe}.effective-chip.update{background:#f5f3ff;border-color:#ddd6fe}.effective-chip b{display:block;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.effective-chip em{display:block;font-size:12px;color:#667085;font-style:normal;margin-top:3px}.effective-tags{display:flex;gap:7px;align-items:center;flex-wrap:wrap}.effective-tags>b{font-size:12px;color:#667085;min-width:44px}.effective-mini{display:flex;gap:8px;align-items:center;flex-wrap:wrap;border:1px solid var(--line);border-radius:10px;background:#f8fafc;padding:10px}.tiny-tag{display:inline-flex;border:1px solid var(--line);border-radius:999px;padding:3px 7px;background:#fff;font-size:12px;color:#344054}
</style>
"""


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
    del compare_by_lib, max_attention_items, max_report_rows, report_index, catalog_json
    out_path = Path(out)
    body = (
        _catalog_browser_styles()
        + ui.panel(
            "库目录总览",
            "面向 IP 使用者：先搜索库，再进入库工作台查看当前有效版和最新待审版。",
            ui.metric_grid(catalog._summary_metrics(state, tasks, effective_by_lib))
            + "<p class='catalog-note'>主流程只保留库定位和审查入口；管理证据写入 JSON，不在首页展开。</p>",
        )
        + "<div class='catalog-layout'>"
        + f"<div class='catalog-filter-panel'>{_catalog_filter_panel(state)}</div>"
        + f"<div>{ui.panel('库浏览器', '只显示库身份、当前有效组合和进入库工作台；库工作台默认聚焦当前有效版与最新待审版。', _library_browser(out_path, state, effective_by_lib))}</div>"
        + "</div>"
    )
    return ui.review_page_shell(
        "库目录",
        "库目录",
        "库版本变化导航入口。库目录是地图，不是命令控制台。",
        body,
        decision="REVIEW" if tasks.get("tasks") else "PASS",
        nav="<a class='active' href='#'>库目录</a><a href='#'>库工作台</a><a href='#'>扫描证据</a><a href='#'>发布证据</a>",
        meta=ui.compact_meta([("库", len(state.get("libraries", []) or [])), ("版本", sum(len(lib.get("versions", []) or []) for lib in state.get("libraries", []) or []))]),
    )
