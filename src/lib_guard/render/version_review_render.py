from __future__ import annotations

from typing import Any, Mapping

from lib_guard.render import product_theme as ui


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


def _summary_tile(label: str, value: Any, hint: Any, status: Any) -> str:
    return (
        f"<div class='judgment-item {_status_class(status)}'>"
        f"<b>{ui.esc(label)}</b>"
        f"<strong title='{ui.esc(value)}'>{ui.esc(value)}</strong>"
        f"<span title='{ui.esc(hint)}'>{ui.esc(hint)}</span>"
        "</div>"
    )


def _simple_table(headers: list[str], rows: list[str], empty: str) -> str:
    if not rows:
        body = f"<tr><td colspan='{len(headers)}' class='empty'>{ui.esc(empty)}</td></tr>"
    else:
        body = "".join(rows)
    return (
        "<div class='table-wrap'>"
        "<table><thead><tr>"
        + "".join(f"<th>{ui.esc(header)}</th>" for header in headers)
        + "</tr></thead><tbody>"
        + body
        + "</tbody></table></div>"
    )


def _view_delta_rows(ip_model: Mapping[str, Any]) -> list[str]:
    rows: list[str] = []
    for item in ip_model.get("view_delta_rows", []) or []:
        if not isinstance(item, Mapping):
            continue
        if not int(item.get("delta_total") or 0) and not int(item.get("current_count") or 0):
            continue
        delta = f"+{item.get('added') or 0} / -{item.get('removed') or 0} / ~{item.get('changed') or 0}"
        raw_types = str(item.get("raw_types") or "-")
        raw_delta_types = str(item.get("raw_delta_types") or "-")
        if raw_delta_types not in {"-", raw_types}:
            raw_text = f"当前 {raw_types}; 更新 {raw_delta_types}"
        else:
            raw_text = raw_types
        rows.append(
            "<tr>"
            f"<td><b>{ui.esc(item.get('view') or item.get('view_type') or '-')}</b><br><code>{ui.esc(item.get('view_type') or item.get('file_type') or '-')}</code></td>"
            f"<td>{ui.esc(item.get('current_count') or 0)}</td>"
            f"<td><code>{ui.esc(delta)}</code></td>"
            f"<td>{ui.esc(item.get('evidence_level') or '-')}</td>"
            f"<td><code>{ui.esc(raw_text)}</code></td>"
            f"<td>{ui.esc(item.get('usage_area') or '-')}</td>"
            f"<td>{ui.badge(item.get('status') or 'INFO', item.get('status_label') or item.get('status') or 'INFO')}</td>"
            "</tr>"
        )
    return rows


def _usage_area_cards(ip_model: Mapping[str, Any]) -> str:
    cards: list[str] = []
    for section in ip_model.get("usage_area_sections", []) or []:
        if not isinstance(section, Mapping):
            continue
        cards.append(
            "<section class='review-group-card'>"
            "<div class='review-group-head'>"
            f"<h3>{ui.esc(section.get('area') or '-')}</h3>"
            f"{ui.badge(section.get('status') or 'INFO')}"
            "</div>"
            f"<p>{ui.esc(section.get('summary') or '-')}</p>"
            f"<div class='quality-note'><b>证据等级</b> {ui.esc(section.get('evidence') or '-')}</div>"
            "</section>"
        )
    return "<div class='review-group-grid'>" + "".join(cards) + "</div>"


def _must_check_list(ip_model: Mapping[str, Any]) -> str:
    rows: list[str] = []
    for idx, item in enumerate(ip_model.get("must_check_items", []) or [], start=1):
        rows.append(
            "<div class='context-row'>"
            f"<b>{idx}. IP 使用者确认项</b>"
            f"<em>{ui.esc(item)}</em>"
            "</div>"
        )
    if not rows:
        rows.append("<div class='context-row'><b>确认项</b><em>暂无必须确认项。</em></div>")
    return "<div class='context-list'>" + "".join(rows) + "</div>"


def render_ip_user_view(ip_model: Mapping[str, Any]) -> str:
    if not ip_model:
        return "<div class='muted-box'>暂无 IP 使用者视图模型。</div>"
    return (
        "<div class='ip-user-view'>"
        "<div class='quality-note'><b>IP 使用者默认视图</b> 主表只回答基准版到当前版的视图变化、证据等级和使用场景影响；管理门禁、包根匹配算法、原始 JSON 默认下沉。</div>"
        "<h3>各视图影响</h3>"
        + _simple_table(
            ["视图类别", "当前数量", "新增/删除/修改", "证据等级", "原始类型", "使用场景", "状态"],
            _view_delta_rows(ip_model),
            "暂无视图变化。",
        )
        + "<h3>按使用场景查看影响</h3>"
        + _usage_area_cards(ip_model)
        + "<h3>你需要确认</h3>"
        + _must_check_list(ip_model)
        + f"<div class='quality-note'><b>非阻塞说明</b> {ui.esc(ip_model.get('non_blocker_note') or '-')}</div>"
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
