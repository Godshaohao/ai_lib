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


def _package_root_callout(group: Mapping[str, Any], facts: list[Mapping[str, Any]]) -> str:
    if group.get("key") != "package_root_migration" or str(group.get("status") or "").upper() == "PASS":
        return ""
    old_root = _fact_value(facts, "Old root")
    new_root = _fact_value(facts, "New root")
    matched = _fact_value(facts, "逻辑路径匹配")
    moved = _fact_value(facts, "文件级一一匹配")
    old_count = _fact_value(facts, "Old 包内文件")
    new_count = _fact_value(facts, "New 包内文件")
    package_counts = ""
    if old_count not in {"", "-", "0"} or new_count not in {"", "-", "0"}:
        package_counts = f"old 包内 {ui.esc(old_count)} 个文件，new 包内 {ui.esc(new_count)} 个文件；"
    return (
        "<div class='quality-note path-restructure-note'>"
        f"<b>疑似重打包 / 目录迁移</b> old root: <code>{ui.esc(old_root)}</code>，"
        f"new root: <code>{ui.esc(new_root)}</code>；包根识别 {ui.esc(matched)}，"
        f"{package_counts}文件级一一匹配 {ui.esc(moved)}。"
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
        cards.append("<div class='muted-box'>暂无 VersionReviewModel 分组。</div>")
    return (
        "<div class='version-review-model'>"
        "<div class='quality-note'><b>VersionReviewModel</b> 更新详情按五组中文字段渲染：对比范围、包根目录迁移、文件匹配质量、内容变化、使用影响。</div>"
        "<div class='review-group-grid'>"
        + "".join(cards)
        + "</div></div>"
    )
