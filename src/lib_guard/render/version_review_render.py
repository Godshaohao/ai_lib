from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from lib_guard.render import catalog_render_common as common
from lib_guard.render import product_theme as ui


def _as_mapping(value: Any) -> Mapping[str, Any]:
    """Treat optional model sections as mappings without leaking None into HTML."""
    return value if isinstance(value, Mapping) else {}


def _fact_table(facts: list[Mapping[str, Any]]) -> str:
    rows = []
    for fact in facts:
        rows.append(
            "<tr>"
            f"<td>{ui.esc(fact.get('label') or '-')}</td>"
            f"<td>{ui.esc(fact.get('value') or '-')}</td>"
            "</tr>"
        )
    if not rows:
        rows.append("<tr><td colspan='2'><span class='muted'>暂无字段</span></td></tr>")
    return "<table class='compact-table review-group-facts'><thead><tr><th>字段</th><th>值</th></tr></thead><tbody>" + "".join(rows) + "</tbody></table>"


def _fact_value(facts: list[Mapping[str, Any]], label: str) -> str:
    for fact in facts:
        if str(fact.get("label") or "") == label:
            return str(fact.get("value") or "-")
    return "-"


def _status_class(status: Any) -> str:
    key = str(status or "").upper()
    if key in {"BLOCKED", "BAD", "ERROR", "FAIL", "FAILED"}:
        return "judgment-bad"
    if key in {"WARNING", "WARN", "USAGE_REVIEW_REQUIRED", "REVIEW", "REVIEW_REQUIRED", "ATTENTION"}:
        return "judgment-warn"
    if key in {"PASS", "READY", "OK"}:
        return "judgment-ok"
    return "judgment-neutral"


def _simple_table(
    headers: list[str],
    rows: list[str],
    empty: str,
    *,
    table_class: str = "",
    wrap_class: str = "table-wrap",
) -> str:
    if not rows:
        body = f"<tr><td colspan='{len(headers)}' class='empty'>{ui.esc(empty)}</td></tr>"
    else:
        body = "".join(rows)
    table_attr = f" class='{ui.esc(table_class)}'" if table_class else ""
    return (
        f"<div class='{ui.esc(wrap_class)}'>"
        f"<table{table_attr}><thead><tr>"
        + "".join(f"<th>{ui.esc(header)}</th>" for header in headers)
        + "</tr></thead><tbody>"
        + body
        + "</tbody></table></div>"
    )


def _example_list(title: str, values: Any) -> str:
    if not isinstance(values, list) or not values:
        return ""
    body = "<br>".join(f"<code>{ui.esc(item)}</code>" for item in values[:8])
    return f"<b>{ui.esc(title)}</b><br>{body}"


def _view_delta_items(ip_model: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    """Return only facts that change the IP user's review decision."""
    items: list[Mapping[str, Any]] = []
    first_version = str(ip_model.get("review_mode") or "").lower() == "first_version"
    for item in ip_model.get("view_rows", []) or []:
        if not isinstance(item, Mapping):
            continue
        has_change = int(item.get("delta_total") or 0) > 0
        has_delivery = int(item.get("delivery_count") or 0) > 0 or int(item.get("current_count") or 0) > 0
        needs_classification = (
            str(item.get("view_type") or item.get("file_type") or "").lower() == "unknown"
            and has_delivery
        )
        # A first version has no baseline delta. Its useful output is the
        # package's own view coverage, limited to views actually delivered.
        if not first_version and not has_change and not needs_classification:
            continue
        if first_version and not has_delivery and not needs_classification:
            continue
        items.append(item)
    return items


def _evidence_href(value: Any, href_base: Path | None) -> str:
    """Keep evidence links portable when the catalog is moved to another host."""
    text = str(value or "")
    if not text or text.startswith(("#", "http://", "https://")):
        return text
    if href_base is None:
        return text.replace("\\", "/")
    try:
        return common.rel_href(href_base, text)
    except (OSError, ValueError, TypeError):
        return text.replace("\\", "/")


def _view_delta_file_evidence(item: Mapping[str, Any], href_base: Path | None = None) -> str:
    changed_examples = _example_list("本次变化", item.get("changed_examples"))
    current_examples = _example_list("本包文件", item.get("current_examples"))
    baseline_examples = _example_list("基准存在、本包未携带", item.get("baseline_only_examples"))
    body = "<br>".join(part for part in [changed_examples, current_examples, baseline_examples] if part)
    full_evidence = _evidence_href(item.get("full_evidence_href"), href_base)
    sample_count = int(item.get("sample_count") or 0)
    total_count = int(item.get("total_evidence_count") or 0)
    visible_count = min(sample_count, total_count) if total_count else sample_count
    sample_copy = f"代表文件 {visible_count} / {total_count}" if total_count else "代表文件"
    if not body:
        if full_evidence:
            return f"<a href='{ui.esc(full_evidence)}' target='_blank'>完整变化证据</a>"
        return "<span class='muted'>暂无文件证据</span>"
    full_link = f"<br><a href='{ui.esc(full_evidence)}' target='_blank'>完整变化证据</a>" if full_evidence else ""
    return (
        "<details class='inline-file-evidence'>"
        "<summary>展开文件</summary>"
        f"<div class='muted'>{ui.esc(sample_copy)}</div>"
        f"{body}"
        f"{full_link}"
        "</details>"
    )


def _view_delta_rows(ip_model: Mapping[str, Any], href_base: Path | None = None) -> list[str]:
    rows: list[str] = []
    first_version = str(ip_model.get("review_mode") or "").lower() == "first_version"
    for item in _view_delta_items(ip_model):
        delivery_count = int(item.get("delivery_count") or item.get("current_count") or 0)
        evidence = str(item.get("evidence_level") or "-")
        status_code = str(item.get("status") or "")
        status_label = str(item.get("status_label") or ui.status_label(status_code) or "待确认")
        status_html = ui.badge(status_code or "INFO", status_label)
        evidence_counts = item.get("evidence_counts") if isinstance(item.get("evidence_counts"), Mapping) else {}
        evidence_count_text = "；".join(
            f"{ui.esc(label)} {int(count)}" for label, count in evidence_counts.items() if int(count or 0)
        )
        evidence_count_html = f"<small class='evidence-counts'>{evidence_count_text}</small>" if evidence_count_text else ""
        usage = str(item.get("usage_area") or "")
        view_label = ui.esc(item.get("view") or item.get("view_type") or "-")
        usage_html = f"<span class='view-use'>{ui.esc(usage)}</span>" if usage else ""
        def count_cell(value: Any, kind: str) -> str:
            number = int(value or 0)
            return f"<span class='delta-number {kind}{' nonzero' if number else ''}'>{number}</span>"

        rows.append(
            f"<tr data-view-type='{ui.esc(item.get('view_type') or item.get('file_type') or '')}'>"
            f"<td><b>{view_label}</b>{usage_html}</td>"
            f"<td class='numeric-cell'>{count_cell(delivery_count, 'current')}</td>"
            f"<td class='numeric-cell'>{count_cell(item.get('added'), 'added')}</td>"
            f"<td class='numeric-cell'>{count_cell(item.get('removed'), 'removed')}</td>"
            f"<td class='numeric-cell'>{count_cell(item.get('changed'), 'changed')}</td>"
            f"<td><span class='evidence-level'>{ui.esc(evidence)}</span>{evidence_count_html}<br>{status_html}</td>"
            f"<td>{_view_delta_file_evidence(item, href_base)}</td>"
            "</tr>"
        )
    return rows


def _pending_fact_list(ip_model: Mapping[str, Any]) -> str:
    rows: list[str] = []
    for item in ip_model.get("pending_fact_items", []) or []:
        if not isinstance(item, Mapping):
            continue
        rows.append(
            "<div class='context-row'>"
            f"<b>{ui.esc(item.get('label') or '待确认事实')}</b>"
            f"<em>{ui.esc(item.get('summary') or '-')}</em>"
            "</div>"
        )
    return "<div class='context-list pending-fact-list'>" + "".join(rows) + "</div>"


def _baseline_only_note(ip_model: Mapping[str, Any]) -> str:
    count = sum(int(item.get("baseline_only_count") or 0) for item in ip_model.get("view_rows", []) or [] if isinstance(item, Mapping))
    if not count:
        return ""
    return f"<div class='scope-note'>基准中另有 {count} 个文件未随本包交付，未计为删除。</div>"


def _impact_scope_html(ip_model: Mapping[str, Any]) -> str:
    """Show observed usage-area deltas without inferring severity."""
    changed = [
        item
        for item in ip_model.get("view_rows", []) or []
        if isinstance(item, Mapping) and int(item.get("delta_total") or 0) > 0
    ]
    usage_impact = ip_model.get("usage_impact") if isinstance(ip_model.get("usage_impact"), Mapping) else {}
    if not changed:
        summary = str(usage_impact.get("summary") or "未识别到视图变化；当前页面不推断额外使用风险。")
        return (
            "<div class='impact-scope impact-scope-empty'>"
            "<b>影响范围</b>"
            f"<span>{ui.esc(summary)}</span>"
            "</div>"
        )

    groups: dict[str, dict[str, Any]] = {}
    for item in changed:
        area = str(item.get("usage_area") or "其他 / 证据")
        group = groups.setdefault(area, {"count": 0, "views": []})
        group["count"] += int(item.get("delta_total") or 0)
        view = str(item.get("view") or item.get("view_type") or "-")
        if view not in group["views"]:
            group["views"].append(view)
    cards = []
    for area, group in groups.items():
        cards.append(
            "<div class='impact-card'>"
            f"<b>{ui.esc(area)}</b>"
            f"<strong>{ui.esc(group['count'])} 个变化</strong>"
            f"<span>{ui.esc('、'.join(group['views'][:4]))}</span>"
            "</div>"
        )
    return "<div class='impact-scope'><b>影响范围</b><div class='impact-grid'>" + "".join(cards) + "</div></div>"


def render_ip_user_view(
    ip_model: Mapping[str, Any],
    *,
    href_base: Path | None = None,
    show_pending: bool = True,
) -> str:
    if not ip_model:
        return "<div class='muted-box'>暂无 IP 使用者视图模型。</div>"
    # View deltas already have a dedicated row above. Keep this list for facts
    # that require a separate decision, such as missing base or real deletion.
    pending = [
        item
        for item in ip_model.get("pending_fact_items", []) or []
        if isinstance(item, Mapping) and str(item.get("kind") or "").upper() != "VIEW_DELTA"
    ]
    pending_html = ""
    if pending and show_pending:
        pending_html = "<div class='pending-facts'><b>需确认</b>" + _pending_fact_list({"pending_fact_items": pending}) + "</div>"
    delta_toolbar = (
        "<div class='view-delta-toolbar'>"
        "<div><b>交付视角</b><span>按 IP 使用场景聚合本次版本的文件变化。</span></div>"
        "<div class='delta-legend' aria-label='变化类型图例'>"
        "<span><i class='legend-dot current'></i>当前文件</span>"
        "<span><i class='legend-dot added'></i>新增</span>"
        "<span><i class='legend-dot removed'></i>删除</span>"
        "<span><i class='legend-dot changed'></i>修改</span>"
        "</div></div>"
    )
    decision = _as_mapping(ip_model.get("decision"))
    change_summary = _as_mapping(ip_model.get("change_summary"))
    blocked_without_diff = (
        str(decision.get("status") or "").upper() == "BLOCKED"
        and str(change_summary.get("status") or "").upper() in {"UNKNOWN", "DIFF_NOT_RUN", "NO_DIFF_SUMMARY"}
    )
    empty_copy = "对比证据尚未完成，不能据此判断无变化。" if blocked_without_diff else "没有需要关注的视图变化。"
    return (
        "<div class='ip-user-view'>"
        + delta_toolbar
        + _impact_scope_html(ip_model)
        + _simple_table(
            ["视图 / 用途", "当前文件", "新增", "删除", "修改", "证据 / 状态", "代表文件"],
            _view_delta_rows(ip_model, href_base),
            empty_copy,
            table_class="view-delta-table",
            wrap_class="table-wrap view-delta-scroll",
        )
        + _baseline_only_note(ip_model)
        + pending_html
        + "</div>"
    )


def _package_root_callout(group: Mapping[str, Any], facts: list[Mapping[str, Any]]) -> str:
    if group.get("key") != "package_root_migration" or str(group.get("status") or "").upper() == "PASS":
        return ""
    old_root = _fact_value(facts, "旧包根")
    new_root = _fact_value(facts, "新包根")
    matched = _fact_value(facts, "逻辑路径匹配")
    moved = _fact_value(facts, "文件级一一匹配")
    old_count = _fact_value(facts, "旧包根文件数")
    new_count = _fact_value(facts, "新包根文件数")
    package_counts = ""
    if old_count not in {"", "-", "0"} or new_count not in {"", "-", "0"}:
        package_counts = f"旧包根内 {ui.esc(old_count)} 个文件，新包根内 {ui.esc(new_count)} 个文件；"
    return (
        "<div class='quality-note path-restructure-note'>"
        f"<b>包装目录变化</b> 旧包根：<code>{ui.esc(old_root)}</code>，"
        f"新包根：<code>{ui.esc(new_root)}</code>；逻辑路径匹配 {ui.esc(matched)}，"
        f"{package_counts}文件级一一匹配 {ui.esc(moved)}。此信息用于解释上一版对比，不默认作为 IP 使用阻塞。"
        "</div>"
    )


def render_version_review_groups(review_model: Mapping[str, Any]) -> str:
    groups = [group for group in review_model.get("groups", []) or [] if isinstance(group, Mapping)]
    cards = []
    for group in groups:
        facts = [fact for fact in group.get("facts", []) or [] if isinstance(fact, Mapping)]
        cards.append(
            "<section class='review-group-card'>"
            "<div class='review-group-head'>"
            f"<h3>{ui.esc(group.get('label') or '-')}</h3>"
            f"{ui.badge(group.get('status') or 'INFO', group.get('status') or 'INFO')}"
            "</div>"
            f"<p>{ui.esc(group.get('summary') or '-')}</p>"
            + _package_root_callout(group, facts)
            + _fact_table(facts)
            + "</section>"
        )
    if not cards:
        cards.append("<div class='muted-box'>暂无更新详情分组。</div>")
    return (
        "<div class='version-review-model'>"
        "<div class='quality-note'><b>高级审查字段</b> 保留对比范围、包根匹配、文件匹配质量、内容变化和原始审计判断，默认作为证据/管理层信息，不抢占 IP 使用者主线。</div>"
        "<div class='review-group-grid'>"
        + "".join(cards)
        + "</div></div>"
    )
