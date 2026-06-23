from __future__ import annotations

from typing import Any, Mapping
import html


def esc(value: Any) -> str:
    return html.escape("" if value is None else str(value))


def status_class(value: Any) -> str:
    text = str(value or "").upper()
    if text in {"PASS", "READY", "SCANNED", "DONE", "DIFF_DONE", "SAME", "DIFF", "OK", "FINISHED", "DRY_RUN", "APPLIED"}:
        return "ok"
    if text in {"PASS_WITH_WARNING", "WARNING", "WARN", "PENDING", "NOT_SCANNED", "NEEDS_REVIEW", "PASS_EMPTY", "MANUAL_REVIEW", "MISSING", "EXTRA", "DRY_RUN"}:
        return "warn"
    if text in {"BLOCK", "BLOCKED", "FAILED", "ERROR", "LOW", "BLOCKER", "MANUAL_REVIEW", "HIGH", "BROKEN", "MISMATCH"}:
        return "bad"
    return "neutral"


def status_label(value: Any) -> str:
    text = str(value or "")
    labels = {
        "PASS": "通过",
        "READY": "可用",
        "SCANNED": "已扫描",
        "DONE": "完成",
        "DIFF_DONE": "已比较",
        "DIFF": "有差异",
        "DRY_RUN": "预演",
        "APPLIED": "已应用",
        "PASS_WITH_WARNING": "通过有警告",
        "WARNING": "需关注",
        "WARN": "需关注",
        "PENDING": "待处理",
        "NOT_SCANNED": "未扫描",
        "NEEDS_REVIEW": "需人工确认",
        "PASS_EMPTY": "空结果",
        "BLOCK": "阻塞",
        "BLOCKED": "阻塞",
        "FAILED": "失败",
        "ERROR": "错误",
        "BLOCKER": "阻塞项",
        "MANUAL_REVIEW": "需人工确认",
        "UNKNOWN": "未确认",
        "NOT_APPLICABLE": "不适用",
        "INFO": "信息",
        "manual_review": "需人工确认",
        "scan_then_diff": "先扫描再比较",
        "stage_unknown": "阶段未识别",
        "unknown": "未确认",
        "ad-hoc": "临时版本",
        "dated": "日期版本",
        "stable": "稳定版",
        "initial": "初始版",
        "final": "正式版",
    }
    return labels.get(text, labels.get(text.upper(), text))


def badge(value: Any, label: str | None = None) -> str:
    text = label if label is not None else status_label(value)
    return f"<span class='badge {status_class(value)}'><span class='badge-dot'></span>{esc(text)}</span>"


def metric(label: str, value: Any, hint: str = "", status: Any = None) -> str:
    cls = status_class(status if status is not None else value)
    return (
        "<div class='metric'>"
        f"<div class='metric-label'>{esc(label)}</div>"
        f"<div class='metric-value {cls}'>{esc(value)}</div>"
        f"<div class='metric-hint'>{esc(hint)}</div>"
        "</div>"
    )


def table(headers: list[str], rows: list[str], empty: str = "暂无数据") -> str:
    head = "".join(f"<th>{esc(h)}</th>" for h in headers)
    body = "".join(rows) if rows else f"<tr><td colspan='{len(headers)}' class='empty'>{esc(empty)}</td></tr>"
    return f"<div class='table-wrap'><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>"


def filterable_table(table_id: str, headers: list[str], rows: list[str], empty: str = "暂无数据", placeholder: str = "筛选表格") -> str:
    safe_id = esc(table_id)
    count = len(rows)
    return (
        f"<div class='table-tools' data-table-tools='{safe_id}'>"
        f"<div class='search'><span>筛选</span><input type='search' placeholder='{esc(placeholder)}' oninput=\"filterTable('{safe_id}', this.value)\" /></div>"
        f"<div class='table-count'><span id='{safe_id}-count'>{count}</span> / {count} 行</div>"
        "</div>"
        f"<div id='{safe_id}-wrap' data-empty='{esc(empty)}'>"
        + table(headers, rows, empty)
        + "</div>"
    )


def faceted_table(
    table_id: str,
    headers: list[str],
    rows: list[str],
    facets: list[tuple[str, str, list[tuple[str, str]]]],
    empty: str = "暂无数据",
) -> str:
    safe_id = esc(table_id)
    count = len(rows)
    groups = []
    for key, label, options in facets:
        safe_key = esc(key)
        chips = [
            f"<button class='filter-chip active' type='button' data-value='__all__' onclick=\"setFacetFilter('{safe_id}', '{safe_key}', '__all__', this)\">全部</button>"
        ]
        for value, text in options:
            chips.append(
                f"<button class='filter-chip' type='button' data-value='{esc(value)}' onclick=\"setFacetFilter('{safe_id}', '{safe_key}', '{esc(value)}', this)\">{esc(text)}</button>"
            )
        groups.append(
            f"<div class='filter-group' data-filter-group='{safe_key}'>"
            f"<span>{esc(label)}</span>"
            f"<div class='filter-options'>{''.join(chips)}</div>"
            "</div>"
        )
    return (
        f"<div class='facet-tools' data-table-tools='{safe_id}'>"
        + "".join(groups)
        + f"<div class='table-count'><span id='{safe_id}-count'>{count}</span> / {count} 行</div>"
        + "</div>"
        f"<div id='{safe_id}-wrap' data-empty='{esc(empty)}'>"
        + table(headers, rows, empty)
        + "</div>"
    )


def collapsible_panel(title: str, note: str, body: str, open: bool = False, action: str = "") -> str:
    opened = " open" if open else ""
    return (
        f"<details class='panel collapsible'{opened}>"
        "<summary class='panel-head'><div>"
        f"<h2 class='panel-title'>{esc(title)}</h2>"
        f"<div class='panel-note'>{esc(note)}</div>"
        f"</div>{action}<span class='chevron'>展开</span></summary>"
        f"<div class='panel-body'>{body}</div></details>"
    )


def button(label: str, href: str = "#", kind: str = "secondary") -> str:
    return f"<a class='btn {esc(kind)}' href='{esc(href)}'>{esc(label)}</a>"


def action_bar(items: list[tuple[str, str, str]]) -> str:
    if not items:
        return ""
    return "<div class='action-bar'>" + "".join(button(label, href, kind) for label, href, kind in items) + "</div>"


def product_summary(items: list[tuple[str, Any, str, Any]]) -> str:
    cards = []
    for label, value, hint, status in items:
        cards.append(
            "<div class='summary-card'>"
            f"<div class='summary-label'>{esc(label)}</div>"
            f"<div class='summary-value {status_class(status if status is not None else value)}'>{esc(value)}</div>"
            f"<div class='summary-hint'>{esc(hint)}</div>"
            "</div>"
        )
    return "<div class='product-summary'>" + "".join(cards) + "</div>"


def status_rail(items: list[tuple[str, Any, str]]) -> str:
    steps = []
    for label, status, note in items:
        cls = status_class(status)
        steps.append(
            f"<div class='rail-step {cls}'>"
            f"<div class='rail-mark'></div>"
            f"<div class='rail-title'>{esc(label)}</div>"
            f"<div class='rail-status'>{esc(status)}</div>"
            f"<div class='rail-note'>{esc(note)}</div>"
            "</div>"
        )
    return "<div class='status-rail'>" + "".join(steps) + "</div>"


def evidence_grid(items: list[tuple[str, Any, str, str]]) -> str:
    cards = []
    for title, status, body, href in items:
        link = f"<a class='evidence-link' href='{esc(href)}'>打开</a>" if href else "<span class='sub'>未生成</span>"
        cards.append(
            f"<div class='evidence-card {status_class(status)}'>"
            f"<div class='evidence-top'>{badge(status)}{link}</div>"
            f"<div class='evidence-title'>{esc(title)}</div>"
            f"<div class='evidence-body'>{esc(body)}</div>"
            "</div>"
        )
    return "<div class='evidence-grid'>" + "".join(cards) + "</div>"


def muted(text: Any) -> str:
    return f"<span class='muted'>{esc(text)}</span>"


def mono_path(path: Any) -> str:
    if not path:
        return "<span class='muted'>Not available</span>"
    return f"<code class='mono-path'>{esc(path)}</code>"


def evidence_link(label: str, href: Any, *, missing: str = "Missing") -> str:
    if not href:
        return f"<span class='evidence-missing'>{esc(missing)}</span>"
    return f"<a class='evidence-link compact' href='{esc(href)}'>{esc(label)}</a>"


def details_block(summary: str, content: Any) -> str:
    if not content:
        return "<span class='muted'>-</span>"
    return (
        "<details class='detail-fold'>"
        f"<summary>{esc(summary)}</summary>"
        f"<div class='detail-fold-body'>{content}</div>"
        "</details>"
    )


def compact_meta(items: list[tuple[str, Any]]) -> str:
    cells = []
    for label, value in items:
        cells.append(
            "<span class='compact-meta-item'>"
            f"<b>{esc(label)}</b>"
            f"<span>{esc(value if value not in (None, '') else '-')}</span>"
            "</span>"
        )
    return "<div class='compact-meta'>" + "".join(cells) + "</div>"


def brief_grid(items: list[tuple[str, Any, str, Any]]) -> str:
    cells = []
    for label, value, hint, status in items:
        raw_value = str(value if value not in (None, "") else "-")
        if len(raw_value) > 80 or "/" in raw_value or "\\" in raw_value:
            value_html = (
                "<details class='brief-fold'>"
                f"<summary>{esc(raw_value[:76] + ('...' if len(raw_value) > 76 else ''))}</summary>"
                f"<code>{esc(raw_value)}</code>"
                "</details>"
            )
        else:
            value_html = esc(raw_value)
        cells.append(
            f"<div class='brief-item {status_class(status)}'>"
            f"<div class='brief-label'>{esc(label)}</div>"
            f"<div class='brief-value'>{value_html}</div>"
            f"<div class='brief-hint'>{esc(hint)}</div>"
            "</div>"
        )
    return "<div class='brief-grid'>" + "".join(cells) + "</div>"


def tile_grid(items: list[Mapping[str, Any]]) -> str:
    tiles = []
    for item in items:
        status = item.get("status") or "NOT_EVALUATED"
        tiles.append(
            f"<div class='review-tile {status_class(status)}'>"
            "<div class='review-tile-head'>"
            f"<div><div class='review-tile-title'>{esc(item.get('title') or '-')}</div>"
            f"<div class='review-tile-sub'>{esc(item.get('subtitle') or '')}</div></div>"
            f"{badge(status, item.get('status_label'))}"
            "</div>"
            f"<div class='review-tile-count'>{esc(item.get('count', 0))}</div>"
            f"<div class='review-tile-hint'>{esc(item.get('hint') or '')}</div>"
            "</div>"
        )
    return "<div class='review-tile-grid'>" + "".join(tiles) + "</div>"


def attention_items(items: list[tuple[Any, str, str, str]]) -> str:
    if not items:
        return "<div class='attention-empty'>暂无需要优先处理的审阅关注项。</div>"
    rows = []
    for severity, title, detail, evidence in items:
        rows.append(
            f"<div class='attention-item {status_class(severity)}'>"
            f"<div class='attention-severity'>{badge(severity)}</div>"
            f"<div><div class='attention-title'>{esc(title)}</div>"
            f"<div class='attention-detail'>{esc(detail)}</div></div>"
            f"<div class='attention-evidence'>{esc(evidence)}</div>"
            "</div>"
        )
    return "<div class='attention-list'>" + "".join(rows) + "</div>"


def trace_link_list(items: list[tuple[str, Any, str]]) -> str:
    links = []
    for label, href, note in items:
        if href:
            action = f"<a class='trace-link' href='{esc(href)}'>打开证据</a>"
        else:
            action = "<span class='muted'>未生成</span>"
        links.append(
            "<div class='trace-link-row'>"
            f"<div><b>{esc(label)}</b><span>{esc(note)}</span></div>"
            f"{action}"
            "</div>"
        )
    return "<div class='trace-links'>" + "".join(links) + "</div>"


def intent_banner(title: str, points: list[tuple[str, str]]) -> str:
    """Render a compact page-intent banner for cross-team review pages."""
    rows = []
    for label, body in points:
        rows.append(
            "<div class='intent-item'>"
            f"<div class='intent-label'>{esc(label)}</div>"
            f"<div class='intent-body'>{esc(body)}</div>"
            "</div>"
        )
    return (
        "<div class='intent-banner'>"
        f"<div class='intent-title'>{esc(title)}</div>"
        "<div class='intent-grid'>" + "".join(rows) + "</div>"
        "</div>"
    )


def callout(title: str, body: str, status: Any = "INFO") -> str:
    return (
        f"<div class='callout {status_class(status)}'>"
        f"<div class='callout-title'>{esc(title)}</div>"
        f"<div class='callout-body'>{body}</div>"
        "</div>"
    )


def _nav_items(nav: str) -> str:
    if nav:
        return nav
    return "<a class='active' href='#'>总览</a><a href='#'>证据</a><a href='#'>明细</a>"


def page_shell(title: str, kicker: str, subtitle: str, body: str, nav: str = "") -> str:
    nav_html = _nav_items(nav)
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>{esc(title)}</title>
<style>
:root {{
  --bg: #f6f8fb;
  --panel: #ffffff;
  --panel-2: #fbfcff;
  --ink: #152033;
  --muted: #64748b;
  --muted-2: #94a3b8;
  --line: #e4e9f2;
  --line-2: #d5ddea;
  --brand: #355cff;
  --brand-2: #0ea5e9;
  --nav: #0f172a;
  --nav-2: #111c33;
  --ok: #16a34a;
  --ok-bg: #ecfdf5;
  --warn: #d97706;
  --warn-bg: #fff7ed;
  --bad: #dc2626;
  --bad-bg: #fef2f2;
  --neutral: #475569;
  --neutral-bg: #f1f5f9;
  --shadow: 0 10px 30px rgba(15, 23, 42, .08);
  --shadow-sm: 0 5px 18px rgba(15, 23, 42, .06);
}}
* {{ box-sizing: border-box; }}
html {{ scroll-behavior: smooth; }}
body {{
  margin: 0;
  background: var(--bg);
  color: var(--ink);
  font-family: "Aptos", "Microsoft YaHei", "PingFang SC", "Segoe UI", Arial, sans-serif;
  font-size: 14px;
  line-height: 1.55;
}}
a {{ color: inherit; text-decoration: none; }}
.muted {{
  color: var(--muted);
}}
.app {{
  display: grid;
  grid-template-columns: 268px minmax(0, 1fr);
  min-height: 100vh;
}}
.sidebar {{
  position: sticky;
  top: 0;
  height: 100vh;
  padding: 22px 18px;
  overflow: auto;
  background: linear-gradient(180deg, var(--nav) 0%, var(--nav-2) 56%, #0b1222 100%);
  color: #dbeafe;
}}
.brand {{
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 22px;
}}
.logo {{
  width: 38px;
  height: 38px;
  border-radius: 8px;
  display: grid;
  place-items: center;
  color: white;
  font-weight: 900;
  background: linear-gradient(135deg, var(--brand), var(--brand-2));
  box-shadow: 0 12px 28px rgba(53, 92, 255, .32);
}}
.brand h1 {{
  margin: 0;
  color: #fff;
  font-size: 15px;
  line-height: 1.25;
}}
.brand p {{
  margin: 2px 0 0;
  color: #94a3b8;
  font-size: 12px;
}}
.nav-title {{
  margin: 20px 10px 8px;
  color: #7dd3fc;
  font-size: 11px;
  font-weight: 900;
  letter-spacing: .08em;
  text-transform: uppercase;
}}
.side-nav a {{
  display: flex;
  align-items: center;
  gap: 10px;
  margin: 2px 0;
  padding: 9px 10px;
  border-radius: 8px;
  color: #cbd5e1;
}}
.side-nav a:hover, .side-nav a.active {{
  background: rgba(255, 255, 255, .08);
  color: #fff;
}}
.side-nav a::before {{
  content: "";
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: #64748b;
}}
.side-nav a.active::before, .side-nav a:hover::before {{
  background: #38bdf8;
  box-shadow: 0 0 0 4px rgba(56, 189, 248, .14);
}}
.side-card {{
  margin-top: 18px;
  padding: 14px;
  border: 1px solid rgba(255,255,255,.12);
  border-radius: 8px;
  background: rgba(255,255,255,.06);
}}
.side-card b {{ display: block; color: #fff; margin-bottom: 4px; }}
.side-card p {{ margin: 0; color: #b6c2d3; font-size: 12px; }}
.main {{ min-width: 0; }}
.hero {{
  padding: 28px 34px 22px;
  background:
    linear-gradient(135deg, #ffffff 0%, #f5f7ff 56%, #eef8ff 100%);
  border-bottom: 1px solid var(--line);
}}
.topbar {{
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 20px;
}}
.kicker {{
  display: inline-flex;
  align-items: center;
  gap: 8px;
  color: var(--brand);
  font-size: 11px;
  font-weight: 900;
  letter-spacing: .08em;
  text-transform: uppercase;
}}
.kicker::before {{
  content: "";
  width: 28px;
  height: 2px;
  background: var(--brand-2);
}}
h1 {{
  margin: 6px 0;
  font-size: 28px;
  line-height: 1.14;
  font-weight: 850;
  letter-spacing: 0;
}}
.subtitle {{
  max-width: 860px;
  color: var(--muted);
}}
.hero-badges {{
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 8px;
}}
.confirm-strip {{
  margin-top: 18px;
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 16px;
  align-items: center;
  padding: 14px 16px;
  border: 1px solid #bfdbfe;
  border-radius: 8px;
  background: rgba(239, 246, 255, .82);
  box-shadow: var(--shadow-sm);
}}
.confirm-strip b {{ color: #1e3a8a; }}
.confirm-strip span {{ color: #475569; }}
.workspace {{
  padding: 26px 34px 48px;
}}
.action-bar {{
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  align-items: center;
  margin-bottom: 16px;
}}
.btn {{
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-height: 34px;
  padding: 7px 11px;
  border-radius: 8px;
  border: 1px solid var(--line-2);
  background: #fff;
  color: #334155;
  font-size: 12px;
  font-weight: 850;
  box-shadow: 0 2px 8px rgba(15, 23, 42, .04);
}}
.btn.primary {{ background: var(--brand); border-color: var(--brand); color: #fff; }}
.btn.success {{ background: var(--ok); border-color: var(--ok); color: #fff; }}
.btn.warning {{ background: var(--warn-bg); border-color: #fed7aa; color: #9a3412; }}
.btn:hover {{ transform: translateY(-1px); }}
.panel {{
  margin-bottom: 18px;
  overflow: hidden;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--panel);
  box-shadow: var(--shadow-sm);
}}
.panel-head {{
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 16px;
  padding: 15px 16px;
  border-bottom: 1px solid var(--line);
  background: linear-gradient(180deg, #fff, #fbfcff);
}}
.panel-title {{
  margin: 0;
  font-size: 16px;
  font-weight: 850;
}}
.panel-note {{
  margin-top: 4px;
  color: var(--muted);
  font-size: 13px;
}}
.panel-body {{ padding: 16px; }}
.collapsible {{
  display: block;
}}
.collapsible > summary {{
  cursor: pointer;
  list-style: none;
}}
.collapsible > summary::-webkit-details-marker {{
  display: none;
}}
.chevron {{
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 44px;
  min-height: 28px;
  padding: 4px 9px;
  border: 1px solid var(--line-2);
  border-radius: 999px;
  background: #fff;
  color: #475569;
  font-size: 12px;
  font-weight: 850;
}}
.collapsible[open] .chevron::before {{ content: "收起"; }}
.collapsible:not([open]) .chevron::before {{ content: "展开"; }}
.collapsible .chevron {{ font-size: 0; }}
.product-summary {{
  display: grid;
  grid-template-columns: 1.35fr repeat(3, minmax(150px, .8fr));
  gap: 12px;
  margin-bottom: 16px;
}}
.summary-card {{
  min-height: 118px;
  padding: 16px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: #fff;
  box-shadow: var(--shadow-sm);
}}
.summary-card:first-child {{
  background: linear-gradient(135deg, #16213a, #254cb8 70%, #0ea5e9 100%);
  color: #fff;
}}
.summary-label {{
  color: var(--muted);
  font-size: 12px;
  font-weight: 850;
}}
.summary-value {{
  margin-top: 8px;
  font-size: 28px;
  line-height: 1.1;
  font-weight: 850;
}}
.summary-hint {{
  margin-top: 8px;
  color: var(--muted);
  font-size: 12px;
}}
.summary-card:first-child .summary-label,
.summary-card:first-child .summary-hint,
.summary-card:first-child .summary-value {{
  color: #fff;
}}
.status-rail {{
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(190px, 1fr));
  gap: 10px;
  margin-bottom: 16px;
}}
.rail-step {{
  position: relative;
  min-height: 104px;
  padding: 13px 13px 13px 38px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: #fff;
  box-shadow: var(--shadow-sm);
}}
.rail-step::before {{
  content: "";
  position: absolute;
  left: 18px;
  top: 28px;
  bottom: 18px;
  width: 1px;
  background: var(--line);
}}
.rail-mark {{
  position: absolute;
  left: 12px;
  top: 16px;
  width: 13px;
  height: 13px;
  border-radius: 50%;
  border: 3px solid currentColor;
  background: #fff;
}}
.rail-title {{ font-size: 13px; font-weight: 850; }}
.rail-status {{ margin-top: 5px; font-size: 12px; font-weight: 850; }}
.rail-note {{ margin-top: 7px; color: var(--muted); font-size: 12px; }}
.metrics {{
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(172px, 1fr));
  gap: 12px;
}}
.metric {{
  min-height: 112px;
  padding: 16px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--panel-2);
  box-shadow: var(--shadow-sm);
}}
.metric-label {{ color: var(--muted); font-size: 12px; font-weight: 850; }}
.metric-value {{ margin-top: 6px; font-size: 28px; line-height: 1.08; font-weight: 850; }}
.metric-hint {{ margin-top: 7px; min-height: 16px; color: var(--muted); font-size: 12px; }}
.ok {{ color: var(--ok); }}
.warn {{ color: var(--warn); }}
.bad {{ color: var(--bad); }}
.neutral {{ color: var(--neutral); }}
.badge {{
  display: inline-flex;
  align-items: center;
  gap: 6px;
  min-height: 25px;
  padding: 4px 9px;
  border-radius: 999px;
  border: 1px solid transparent;
  font-size: 12px;
  font-weight: 850;
  white-space: nowrap;
}}
.badge-dot {{ width: 6px; height: 6px; border-radius: 99px; background: currentColor; }}
.badge.ok {{ background: var(--ok-bg); color: #166534; border-color: #bbf7d0; }}
.badge.warn {{ background: var(--warn-bg); color: #9a3412; border-color: #fed7aa; }}
.badge.bad {{ background: var(--bad-bg); color: #991b1b; border-color: #fecaca; }}
.badge.neutral {{ background: var(--neutral-bg); color: #475569; border-color: #cbd5e1; }}
.evidence-grid {{
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(230px, 1fr));
  gap: 12px;
  margin-top: 12px;
}}
.evidence-card {{
  min-height: 132px;
  padding: 13px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: #fff;
}}
.evidence-card.ok {{ border-color: #bbf7d0; }}
.evidence-card.warn {{ border-color: #fed7aa; }}
.evidence-card.bad {{ border-color: #fecaca; }}
.evidence-top {{
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 10px;
}}
.evidence-title {{ margin-top: 12px; font-weight: 850; }}
.evidence-body {{ margin-top: 7px; color: var(--muted); font-size: 12px; }}
.evidence-link {{ color: #1d4ed8; font-weight: 850; font-size: 12px; }}
.split {{
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(340px, .46fr);
  gap: 16px;
}}
.table-wrap {{
  overflow: auto;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: #fff;
}}
.table-tools {{
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  margin-bottom: 10px;
  flex-wrap: wrap;
}}
.facet-tools {{
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 12px 18px;
  align-items: end;
  margin-bottom: 12px;
  padding: 12px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: #fff;
}}
.filter-group {{
  display: grid;
  grid-template-columns: 72px minmax(0, 1fr);
  gap: 8px;
  align-items: center;
}}
.filter-group span {{
  color: var(--muted);
  font-size: 12px;
  font-weight: 850;
}}
.filter-options {{
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}}
.filter-chip {{
  min-height: 28px;
  padding: 5px 10px;
  border: 1px solid var(--line-2);
  border-radius: 999px;
  background: #fff;
  color: #334155;
  font-size: 12px;
  font-weight: 850;
  cursor: pointer;
}}
.filter-chip:hover {{
  background: #eff6ff;
  border-color: #bfdbfe;
  color: #1e40af;
}}
.filter-chip.active {{
  background: #1e40af;
  border-color: #1e40af;
  color: #fff;
}}
.search {{
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 280px;
  padding: 8px 10px;
  border: 1px solid var(--line);
  border-radius: 999px;
  background: #fff;
}}
.search span {{
  color: var(--muted);
  font-size: 12px;
  font-weight: 850;
}}
.search input {{
  width: 100%;
  min-width: 180px;
  border: 0;
  outline: 0;
  background: transparent;
  color: var(--ink);
}}
.table-count {{
  color: var(--muted);
  font-size: 12px;
  font-weight: 850;
}}
.is-hidden-by-filter {{ display: none; }}
table {{
  width: 100%;
  min-width: 760px;
  border-collapse: separate;
  border-spacing: 0;
}}
th, td {{
  padding: 10px 12px;
  border-bottom: 1px solid var(--line);
  text-align: left;
  vertical-align: top;
  font-size: 13px;
}}
th {{
  position: sticky;
  top: 0;
  z-index: 1;
  background: #f8fafc;
  color: #475569;
  font-size: 12px;
  font-weight: 850;
  white-space: nowrap;
}}
tr:last-child td {{ border-bottom: 0; }}
tbody tr:hover td {{ background: #fbfdff; }}
.empty {{ color: var(--muted); text-align: center; padding: 18px; background: #f8fafc; }}
code, .mono {{
  font-family: "Cascadia Mono", "Consolas", "SFMono-Regular", monospace;
  font-size: 12px;
}}
code {{
  display: inline-block;
  max-width: 100%;
  padding: 2px 5px;
  border: 1px solid #dbe3ee;
  border-radius: 6px;
  background: #f1f5f9;
  color: #1e3a8a;
  word-break: break-all;
}}
pre {{
  margin: 0;
  max-height: 460px;
  overflow: auto;
  padding: 14px;
  border-radius: 8px;
  background: #0f172a;
  color: #dbeafe;
}}
.sub {{ color: var(--muted); margin-top: 4px; font-size: 12px; }}
.link-row {{ display: flex; gap: 6px; flex-wrap: wrap; }}
.evidence-links {{
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  align-items: center;
}}
a.link {{
  display: inline-flex;
  align-items: center;
  min-height: 24px;
  padding: 3px 8px;
  border: 1px solid #bfdbfe;
  border-radius: 999px;
  color: #1e40af;
  background: #eff6ff;
  font-weight: 850;
}}
.cmd {{
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}}
.copy {{
  border: 1px solid var(--line-2);
  background: #fff;
  color: #1e40af;
  border-radius: 8px;
  padding: 5px 8px;
  font-weight: 850;
  cursor: pointer;
}}
.copy:hover {{ background: #eff6ff; }}
.evidence-link.compact {{
  display: inline-flex;
  align-items: center;
  min-height: 26px;
  padding: 4px 9px;
  border: 1px solid #bfdbfe;
  border-radius: 999px;
  background: #eff6ff;
  color: #1e40af;
  font-size: 12px;
  font-weight: 850;
}}
.evidence-link.compact:hover {{
  background: #dbeafe;
  border-color: #93c5fd;
}}
.evidence-missing {{
  display: inline-flex;
  align-items: center;
  min-height: 26px;
  padding: 4px 9px;
  border: 1px solid var(--line);
  border-radius: 999px;
  background: #f8fafc;
  color: var(--muted);
  font-size: 12px;
  font-weight: 850;
}}
.trace-path,
.compat-token {{
  display: none !important;
}}
.mono-path {{
  white-space: normal;
  overflow-wrap: anywhere;
  word-break: break-word;
}}
.compact-meta {{
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}}
.compact-meta-item {{
  display: inline-flex;
  align-items: center;
  gap: 6px;
  min-height: 28px;
  padding: 4px 9px;
  border: 1px solid var(--line);
  border-radius: 999px;
  background: #fff;
  color: #334155;
  font-size: 12px;
}}
.compact-meta-item b {{
  color: var(--muted);
  font-weight: 850;
}}
.detail-fold {{
  max-width: 420px;
  padding: 7px 9px !important;
  background: #fbfcff !important;
}}
.detail-fold summary {{
  color: #1e40af;
  font-size: 12px;
}}
.detail-fold-body {{
  margin-top: 8px;
  color: #334155;
  overflow-wrap: anywhere;
}}

.brief-grid {{
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(190px, 1fr));
  gap: 10px;
}}
.brief-item {{
  min-height: 92px;
  padding: 13px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: #fff;
  box-shadow: var(--shadow-sm);
}}
.brief-item.ok {{ border-left: 4px solid var(--ok); }}
.brief-item.warn {{ border-left: 4px solid var(--warn); }}
.brief-item.bad {{ border-left: 4px solid var(--bad); }}
.brief-item.neutral {{ border-left: 4px solid #94a3b8; }}
.brief-label {{
  color: var(--muted);
  font-size: 11px;
  font-weight: 900;
  text-transform: uppercase;
}}
.brief-value {{
  margin-top: 6px;
  color: var(--ink);
  font-size: 15px;
  font-weight: 900;
  overflow-wrap: anywhere;
}}
.brief-hint {{
  margin-top: 6px;
  color: var(--muted);
  font-size: 12px;
}}
.brief-fold {{
  padding: 0 !important;
  border: 0 !important;
  background: transparent !important;
}}
.brief-fold summary {{
  color: var(--ink);
  font-weight: 900;
  overflow-wrap: anywhere;
}}
.brief-fold code {{ margin-top: 8px; }}
.review-tile-grid {{
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(185px, 1fr));
  gap: 12px;
}}
.review-tile {{
  min-height: 154px;
  padding: 14px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: #fff;
  box-shadow: var(--shadow-sm);
}}
.review-tile.ok {{ border-color: #bbf7d0; background: linear-gradient(180deg, #ffffff, #f7fffb); }}
.review-tile.warn {{ border-color: #fed7aa; background: linear-gradient(180deg, #ffffff, #fffaf2); }}
.review-tile.bad {{ border-color: #fecaca; background: linear-gradient(180deg, #ffffff, #fff7f7); }}
.review-tile-head {{
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 10px;
}}
.review-tile-title {{ font-weight: 900; }}
.review-tile-sub {{
  margin-top: 2px;
  color: var(--muted);
  font-size: 12px;
}}
.review-tile-count {{
  margin-top: 18px;
  font-size: 30px;
  line-height: 1;
  font-weight: 900;
}}
.review-tile-hint {{
  margin-top: 10px;
  color: var(--muted);
  font-size: 12px;
}}
.attention-list {{ display: grid; gap: 10px; }}
.attention-item {{
  display: grid;
  grid-template-columns: 132px minmax(0, 1fr) minmax(150px, .34fr);
  gap: 12px;
  align-items: start;
  padding: 12px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: #fff;
}}
.attention-item.warn {{ border-color: #fed7aa; background: #fffaf2; }}
.attention-item.bad {{ border-color: #fecaca; background: #fff7f7; }}
.attention-title {{ font-weight: 900; }}
.attention-detail {{
  margin-top: 3px;
  color: var(--muted);
  font-size: 12px;
}}
.attention-evidence {{
  color: var(--muted);
  font-size: 12px;
  overflow-wrap: anywhere;
}}
.attention-empty {{
  padding: 14px;
  border: 1px solid #bbf7d0;
  border-radius: 8px;
  background: #f0fdf4;
  color: #166534;
  font-weight: 850;
}}
.trace-links {{
  display: grid;
  gap: 8px;
  margin-bottom: 14px;
}}
.trace-link-row {{
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 12px;
  align-items: center;
  padding: 10px 12px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: #fbfcff;
}}
.trace-link-row b {{ display: block; }}
.trace-link-row span {{ display: block; color: var(--muted); font-size: 12px; }}
.trace-link {{ color: #1d4ed8; font-size: 12px; font-weight: 900; }}
.intent-banner {{
  margin-bottom: 14px;
  padding: 14px;
  border: 1px solid #bfdbfe;
  border-radius: 8px;
  background: linear-gradient(135deg, #eff6ff, #f8fbff);
}}
.intent-title {{
  color: #1e3a8a;
  font-weight: 900;
  margin-bottom: 10px;
}}
.intent-grid {{
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 10px;
}}
.intent-item {{
  padding: 10px;
  border: 1px solid #dbeafe;
  border-radius: 8px;
  background: rgba(255,255,255,.78);
}}
.intent-label {{
  color: #1d4ed8;
  font-size: 11px;
  font-weight: 900;
  text-transform: uppercase;
}}
.intent-body {{
  margin-top: 4px;
  color: #334155;
  font-size: 12px;
}}

.callout {{
  padding: 14px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: #fff;
}}
.callout-title {{ margin-bottom: 6px; font-weight: 850; }}
.callout.ok {{ border-color: #bbf7d0; background: #f0fdf4; }}
.callout.warn {{ border-color: #fed7aa; background: #fff7ed; }}
.callout.bad {{ border-color: #fecaca; background: #fef2f2; }}
.callout.neutral {{ background: #f8fafc; }}
details:not(.collapsible) {{
  padding: 10px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: #fff;
}}
summary {{ cursor: pointer; font-weight: 850; color: #334155; }}
.version-map {{
  display: grid;
  gap: 14px;
}}
.library-flow {{
  border: 1px solid var(--line);
  border-radius: 8px;
  background: #fff;
  overflow: hidden;
}}
.flow-head {{
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: center;
  padding: 12px 14px;
  border-bottom: 1px solid var(--line);
  background: #fbfcff;
}}
.flow-title {{ font-weight: 850; }}
.flow-sub {{ color: var(--muted); font-size: 12px; margin-top: 2px; }}
.flow-lane {{
  display: flex;
  gap: 12px;
  overflow-x: auto;
  padding: 16px;
}}
.version-node {{
  position: relative;
  flex: 0 0 210px;
  min-height: 126px;
  padding: 12px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: #fff;
  box-shadow: var(--shadow-sm);
}}
.version-node::after {{
  content: "";
  position: absolute;
  top: 50%;
  right: -13px;
  width: 13px;
  border-top: 2px solid #cbd5e1;
}}
.version-node:last-child::after {{ display: none; }}
.node-title {{ font-weight: 850; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
.node-meta {{ margin-top: 8px; display: flex; gap: 6px; flex-wrap: wrap; }}
.node-links {{ margin-top: 10px; display: grid; gap: 5px; color: var(--muted); font-size: 12px; }}
.node-line {{ display: flex; justify-content: space-between; gap: 8px; }}
.node-line b {{ color: var(--ink); }}
.chain-list {{
  display: grid;
  gap: 12px;
}}
.chain-card {{
  border: 1px solid var(--line);
  border-radius: 8px;
  background: #fff;
  box-shadow: var(--shadow-sm);
  overflow: hidden;
}}
.chain-head {{
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: flex-start;
  padding: 12px 14px;
  border-bottom: 1px solid var(--line);
  background: #fbfcff;
}}
.chain-title {{ font-weight: 900; }}
.chain-note {{ color: var(--muted); font-size: 12px; margin-top: 3px; }}
.chain-body {{
  display: grid;
  gap: 12px;
  padding: 14px;
}}
.pipeline {{
  display: grid;
  grid-template-columns: repeat(5, minmax(130px, 1fr));
  gap: 10px;
  align-items: stretch;
}}
.pipe-step {{
  position: relative;
  min-height: 92px;
  padding: 11px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: #fff;
}}
.pipe-step:not(:last-child)::after {{
  content: "";
  position: absolute;
  top: 50%;
  right: -10px;
  width: 10px;
  border-top: 2px solid #cbd5e1;
}}
.pipe-step.ok {{ border-color: #bbf7d0; background: #fbfffd; }}
.pipe-step.warn {{ border-color: #fed7aa; background: #fffdf8; }}
.pipe-step.bad {{ border-color: #fecaca; background: #fffafa; }}
.pipe-step.neutral {{ background: #f8fafc; }}
.pipe-label {{ color: var(--muted); font-size: 11px; font-weight: 900; text-transform: uppercase; }}
.pipe-value {{ margin-top: 6px; font-weight: 900; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
.pipe-sub {{ margin-top: 6px; color: var(--muted); font-size: 12px; }}
.governance-grid {{
  display: grid;
  grid-template-columns: minmax(0, 1.05fr) minmax(360px, .95fr);
  gap: 14px;
  margin-top: 14px;
}}
.trust-panel,
.next-panel,
.group-card,
.release-card {{
  border: 1px solid var(--line);
  border-radius: 8px;
  background: #fff;
  box-shadow: var(--shadow-sm);
  padding: 14px;
}}
.trust-head,
.next-head {{
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 12px;
  margin-bottom: 12px;
}}
.trust-title,
.next-title,
.group-title {{
  font-weight: 900;
}}
.trust-note,
.next-note,
.group-note {{
  margin-top: 3px;
  color: var(--muted);
  font-size: 12px;
}}
.coverage-list {{
  display: grid;
  gap: 10px;
}}
.coverage-row {{
  display: grid;
  grid-template-columns: 120px minmax(0, 1fr) 54px;
  gap: 10px;
  align-items: center;
}}
.coverage-label {{
  color: #334155;
  font-size: 12px;
  font-weight: 850;
}}
.coverage-track {{
  height: 10px;
  border-radius: 999px;
  background: #e5eaf2;
  overflow: hidden;
}}
.coverage-fill {{
  display: block;
  height: 100%;
  border-radius: 999px;
  background: linear-gradient(90deg, var(--brand), var(--brand-2));
}}
.coverage-fill.ok {{ background: linear-gradient(90deg, #16a34a, #22c55e); }}
.coverage-fill.warn {{ background: linear-gradient(90deg, #d97706, #f59e0b); }}
.coverage-fill.bad {{ background: linear-gradient(90deg, #dc2626, #ef4444); }}
.coverage-fill.neutral {{ background: linear-gradient(90deg, #64748b, #94a3b8); }}
.coverage-value {{
  color: var(--muted);
  font-size: 12px;
  font-weight: 850;
  text-align: right;
}}
.workflow-chart {{
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
}}
.workflow-step {{
  position: relative;
  min-height: 148px;
  padding: 14px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: #fff;
  box-shadow: var(--shadow-sm);
}}
.workflow-step:not(:last-child)::after {{
  content: "";
  position: absolute;
  top: 36px;
  right: -13px;
  width: 13px;
  border-top: 2px solid #cbd5e1;
}}
.workflow-index {{
  width: 28px;
  height: 28px;
  display: grid;
  place-items: center;
  border-radius: 50%;
  background: #eff6ff;
  color: #1d4ed8;
  font-size: 12px;
  font-weight: 900;
}}
.workflow-title {{
  margin-top: 10px;
  color: #334155;
  font-size: 13px;
  font-weight: 900;
}}
.workflow-number {{
  margin: 6px 0 10px;
  color: var(--ink);
  font-size: 24px;
  line-height: 1.1;
  font-weight: 900;
}}
.workflow-number span {{
  margin-left: 3px;
  color: var(--muted);
  font-size: 13px;
}}
.workflow-note {{
  margin-top: 9px;
  color: var(--muted);
  font-size: 12px;
}}
.next-list {{
  display: grid;
  gap: 9px;
  margin: 0;
  padding: 0;
  list-style: none;
}}
.next-item {{
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  gap: 10px;
  align-items: start;
  padding: 10px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: #fbfcff;
}}
.next-index {{
  width: 24px;
  height: 24px;
  display: grid;
  place-items: center;
  border-radius: 50%;
  background: #eff6ff;
  color: #1e40af;
  font-size: 12px;
  font-weight: 900;
}}
.next-item b {{ display: block; }}
.next-item span {{ color: var(--muted); font-size: 12px; }}
.group-overview {{
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 12px;
}}
.library-grid {{
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: 12px;
}}
.library-card {{
  display: grid;
  gap: 12px;
  min-height: 188px;
  padding: 14px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: #fff;
  box-shadow: var(--shadow-sm);
}}
.library-card-head {{
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 10px;
}}
.library-card-title {{
  font-size: 18px;
  font-weight: 900;
}}
.library-card-sub {{
  color: var(--muted);
  font-size: 12px;
}}
.library-card-actions {{
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}}
.group-stats {{
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
  margin-top: 12px;
}}
.group-stat {{
  padding: 8px;
  border-radius: 8px;
  background: #f8fafc;
  color: var(--muted);
  font-size: 12px;
}}
.group-stat b {{
  display: block;
  color: var(--ink);
  font-size: 16px;
}}
.task-board {{
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(270px, 1fr));
  gap: 12px;
}}
.command-grid {{
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
  gap: 12px;
}}
.command-card {{
  display: grid;
  gap: 10px;
  padding: 13px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: #fff;
  box-shadow: var(--shadow-sm);
}}
.command-head {{
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 10px;
}}
.command-head b {{
  font-size: 14px;
}}
.command-card p {{
  margin: 0;
  color: var(--muted);
  font-size: 12px;
}}
.task-column {{
  border: 1px solid var(--line);
  border-radius: 8px;
  background: #fff;
  overflow: hidden;
}}
.task-column-head {{
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 11px 12px;
  border-bottom: 1px solid var(--line);
  background: #fbfcff;
  font-weight: 900;
}}
.task-card {{
  padding: 12px;
  border-bottom: 1px solid var(--line);
}}
.task-card:last-child {{ border-bottom: 0; }}
.task-card b {{ display: block; }}
.task-card p {{ margin: 5px 0 10px; color: var(--muted); font-size: 12px; }}
.task-actions {{ display: flex; gap: 8px; flex-wrap: wrap; }}
.inline-details summary {{
  display: inline-flex;
  cursor: pointer;
  color: #1d4ed8;
  font-weight: 850;
}}
.decision-grid {{
  display: grid;
  gap: 10px;
}}
.decision-row {{
  display: grid;
  grid-template-columns: 86px minmax(170px, .9fr) minmax(0, 1.2fr) minmax(180px, 1fr) auto;
  gap: 10px;
  align-items: center;
  padding: 12px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: #fff;
}}
.decision-label {{
  color: var(--muted);
  font-size: 11px;
  font-weight: 850;
  text-transform: uppercase;
}}
.decision-main b,
.decision-suggest b {{ display: block; }}
.decision-main span,
.decision-suggest span {{ color: var(--muted); font-size: 12px; }}
.compact-table table {{
  min-width: 980px;
}}
.compact-table code {{
  max-width: 360px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}}
.timeline {{
  overflow-x: auto;
  padding: 10px 4px 4px;
}}
.timeline-lane {{
  display: flex;
  gap: 14px;
  min-width: max-content;
  padding: 12px 0 6px;
}}
.timeline-item {{
  position: relative;
  width: 238px;
  min-height: 150px;
  padding: 12px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: #fff;
  box-shadow: var(--shadow-sm);
}}
.timeline-item::before {{
  content: "";
  position: absolute;
  top: -13px;
  left: 18px;
  right: -32px;
  border-top: 2px solid #cbd5e1;
}}
.timeline-item:last-child::before {{
  right: auto;
  width: 32px;
}}
.timeline-dot {{
  position: absolute;
  top: -18px;
  left: 13px;
  width: 12px;
  height: 12px;
  border-radius: 99px;
  background: #1e40af;
  border: 3px solid #dbeafe;
}}
.timeline-date {{
  color: #1e40af;
  font-size: 12px;
  font-weight: 900;
}}
.timeline-title {{
  margin-top: 6px;
  font-weight: 900;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}}
.timeline-meta {{
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 9px;
}}
.timeline-line {{
  margin-top: 8px;
  color: var(--muted);
  font-size: 12px;
}}
.release-workbench {{
  display: grid;
  gap: 12px;
}}
.release-controls {{
  display: grid;
  grid-template-columns: minmax(220px, 1fr) minmax(120px, .35fr) auto auto auto;
  gap: 10px;
  align-items: end;
  padding: 12px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: #f8fafc;
}}
.release-controls label {{
  display: grid;
  gap: 5px;
  color: var(--muted);
  font-size: 12px;
  font-weight: 850;
}}
.release-controls input[type="text"] {{
  min-height: 36px;
  padding: 7px 10px;
  border: 1px solid var(--line-2);
  border-radius: 8px;
  background: #fff;
  color: var(--ink);
  font: inherit;
}}
.release-controls .checkline {{
  display: inline-flex;
  min-height: 36px;
  align-items: center;
  gap: 7px;
  padding: 7px 10px;
  border: 1px solid var(--line-2);
  border-radius: 8px;
  background: #fff;
  color: #334155;
}}
.release-hint {{
  grid-column: 1 / -1;
  color: var(--muted);
  font-size: 12px;
}}
.release-select {{
  width: 18px;
  height: 18px;
  accent-color: var(--brand);
}}
@media (max-width: 1180px) {{
  .app {{ grid-template-columns: 1fr; }}
  .sidebar {{ display: none; }}
  .product-summary {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
  .governance-grid {{ grid-template-columns: 1fr; }}
  .decision-row {{ grid-template-columns: 1fr; }}
  .pipeline {{ grid-template-columns: 1fr; }}
  .pipe-step:not(:last-child)::after {{ display: none; }}
  .workflow-chart {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
  .workflow-step:not(:last-child)::after {{ display: none; }}
  .facet-tools {{ grid-template-columns: 1fr; }}
  .release-controls {{ grid-template-columns: 1fr; }}
}}
@media (max-width: 760px) {{
  .hero, .workspace {{ padding-left: 16px; padding-right: 16px; }}
  .topbar, .confirm-strip, .split {{ display: grid; grid-template-columns: 1fr; }}
  .attention-item, .trace-link-row {{ grid-template-columns: 1fr; }}
  .hero-badges {{ justify-content: flex-start; }}
  .product-summary {{ grid-template-columns: 1fr; }}
  .workflow-chart {{ grid-template-columns: 1fr; }}
  .search {{ min-width: 100%; }}
  .filter-group {{ grid-template-columns: 1fr; }}
  h1 {{ font-size: 24px; }}
}}
</style>
</head>
<body>
<div class="app">
  <aside class="sidebar">
    <div class="brand">
      <div class="logo">LG</div>
      <div><h1>lib_guard</h1><p>Library quality control</p></div>
    </div>
    <div class="nav-title">审阅入口</div>
    <nav class="side-nav">{nav_html}</nav>
    <div class="nav-title">当前页面</div>
    <div class="side-card"><b>{esc(kicker)}</b><p>{esc(subtitle)}</p></div>
  </aside>
  <main class="main">
    <header class="hero">
      <div class="topbar">
        <div>
          <div class="kicker">{esc(kicker)}</div>
          <h1>{esc(title)}</h1>
          <div class="subtitle">{esc(subtitle)}</div>
        </div>
        <div class="hero-badges">
          {badge("READY", "产品化视图")}
          {badge("AUDIT", "证据可追溯")}
        </div>
      </div>
    </header>
    <main class="workspace">
{body}
    </main>
  </main>
</div>
<script>
function copyText(text, btn) {{
  if (navigator.clipboard && window.isSecureContext) {{
    navigator.clipboard.writeText(text).then(function() {{
      var old = btn.textContent;
      btn.textContent = "已复制";
      setTimeout(function() {{ btn.textContent = old; }}, 1100);
    }});
    return;
  }}
  var ta = document.createElement("textarea");
  ta.value = text;
  document.body.appendChild(ta);
  ta.focus();
  ta.select();
  try {{ document.execCommand("copy"); }} catch (e) {{}}
  document.body.removeChild(ta);
  var old = btn.textContent;
  btn.textContent = "已复制";
  setTimeout(function() {{ btn.textContent = old; }}, 1100);
}}
function filterTable(tableId, query) {{
  var wrap = document.getElementById(tableId + "-wrap");
  if (!wrap) return;
  var rows = Array.prototype.slice.call(wrap.querySelectorAll("tbody tr"));
  var q = String(query || "").toLowerCase().trim();
  var visible = 0;
  rows.forEach(function(row) {{
    if (row.querySelector(".empty")) {{
      row.classList.toggle("is-hidden-by-filter", !!q);
      return;
    }}
    var text = row.textContent.toLowerCase();
    var show = !q || text.indexOf(q) !== -1;
    row.classList.toggle("is-hidden-by-filter", !show);
    if (show) visible += 1;
  }});
  var count = document.getElementById(tableId + "-count");
  if (count) count.textContent = visible;
}}
var facetState = {{}};
function setFacetFilter(tableId, group, value, btn) {{
  facetState[tableId] = facetState[tableId] || {{}};
  facetState[tableId][group] = value;
  var container = btn.closest("[data-filter-group]");
  if (container) {{
    Array.prototype.slice.call(container.querySelectorAll(".filter-chip")).forEach(function(item) {{
      item.classList.toggle("active", item === btn);
    }});
  }}
  applyFacetFilters(tableId);
}}
function applyFacetFilters(tableId) {{
  var wrap = document.getElementById(tableId + "-wrap");
  if (!wrap) return;
  var filters = facetState[tableId] || {{}};
  var rows = Array.prototype.slice.call(wrap.querySelectorAll("tbody tr"));
  var visible = 0;
  rows.forEach(function(row) {{
    if (row.querySelector(".empty")) {{
      row.classList.toggle("is-hidden-by-filter", true);
      return;
    }}
    var show = true;
    Object.keys(filters).forEach(function(group) {{
      var value = filters[group];
      if (!value || value === "__all__") return;
      var actual = row.getAttribute("data-" + group) || "";
      if (actual !== value) show = false;
    }});
    row.classList.toggle("is-hidden-by-filter", !show);
    if (show) visible += 1;
  }});
  var count = document.getElementById(tableId + "-count");
  if (count) count.textContent = visible;
}}
function quoteArg(value) {{
  return '"' + String(value || '').replace(/"/g, '\\"') + '"';
}}
function copyReleaseCommand(panelId, btn) {{
  var panel = document.getElementById(panelId);
  if (!panel) return;
  var rootInput = panel.querySelector('[data-release-root]');
  var aliasInput = panel.querySelector('[data-release-alias]');
  var selected = Array.prototype.slice.call(panel.querySelectorAll('.release-select:checked:not(:disabled)'));
  if (!selected.length) {{
    var old = btn.textContent;
    btn.textContent = "请选择版本";
    setTimeout(function() {{ btn.textContent = old; }}, 1200);
    return;
  }}
  var cmd = panel.getAttribute('data-command-seed') || 'python -m lib_guard.cli release-batch';
  cmd += ' --release-root ' + quoteArg(rootInput && rootInput.value ? rootInput.value : '$WORK/release_area');
  cmd += ' --alias ' + quoteArg(aliasInput && aliasInput.value ? aliasInput.value : 'current');
  selected.forEach(function(box) {{
    cmd += ' --version ' + quoteArg(box.getAttribute('data-version'));
  }});
  if (panel.querySelector('[data-release-apply]') && panel.querySelector('[data-release-apply]').checked) cmd += ' --apply';
  if (panel.querySelector('[data-release-overwrite]') && panel.querySelector('[data-release-overwrite]').checked) cmd += ' --overwrite';
  copyText(cmd, btn);
}}
</script>
</body>
</html>"""


def panel(title: str, note: str, body: str, action: str = "") -> str:
    return (
        "<section class='panel'>"
        "<div class='panel-head'><div>"
        f"<h2 class='panel-title'>{esc(title)}</h2>"
        f"<div class='panel-note'>{esc(note)}</div>"
        f"</div>{action}</div><div class='panel-body'>{body}</div></section>"
    )
