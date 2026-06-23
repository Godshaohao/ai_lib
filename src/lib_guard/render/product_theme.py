from __future__ import annotations

from typing import Any, Mapping, Sequence
import html
import json


def esc(value: Any) -> str:
    return html.escape("" if value is None else str(value))


def _norm(value: Any) -> str:
    return str(value or "").strip().upper()


def status_class(value: Any) -> str:
    text = _norm(value)
    ok = {
        "PASS", "READY", "OK", "DONE", "SCANNED", "SCAN_READY", "DIFF_DONE", "SAME", "FOUND",
        "RELEASED", "APPLIED", "DRY_RUN", "FINISHED", "READY_FOR_DIFF", "FILE_DIFF_DONE",
        "COMPARE_READY", "TARGET_MATCH", "LINKED", "CLEAR", "COMPLETE",
    }
    warn = {
        "WARNING", "WARN", "PASS_WITH_WARNING", "PENDING", "NOT_SCANNED", "NEEDS_REVIEW",
        "REVIEW", "MANUAL_REVIEW", "NEEDS_FILE_DIFF", "FILE_DIFF_RECOMMENDED", "FILE_DIFF_PENDING",
        "PAIRWISE_PENDING", "PAIRWISE_PARTIAL", "DIFF", "CHANGED", "METADATA_ONLY", "MISSING",
        "EXTRA", "UNKNOWN", "NEEDS_BASE_CONFIRM", "RELEASE_CHECK_REQUIRED", "SCAN_NEEDS_REVIEW",
        "REVIEW_REQUIRED", "COMPARE_PENDING", "NOT_READY",
    }
    bad = {
        "FAILED", "FAIL", "ERROR", "BLOCK", "BLOCKED", "BROKEN", "MISMATCH", "TARGET_MISMATCH",
        "BLOCKER", "LOW", "HIGH", "RELEASE_BLOCKED", "SCAN_BLOCKED", "DIFF_BLOCKED",
    }
    muted = {"NA", "N/A", "EMPTY", "PAIRWISE_EMPTY", "NOT_APPLICABLE", "DISABLED", "SKIPPED", "NONE"}
    if text in ok:
        return "ok"
    if text in bad:
        return "bad"
    if text in muted:
        return "muted"
    if text in warn:
        return "warn"
    return "neutral"


def status_label(value: Any) -> str:
    text = str(value or "")
    labels = {
        "PASS": "通过", "READY": "可用", "OK": "正常", "DONE": "完成", "SCANNED": "已扫描",
        "SCAN_READY": "Scan 可用", "READY_FOR_DIFF": "可进入 Diff", "SCAN_NEEDS_REVIEW": "Scan 需确认",
        "SCAN_BLOCKED": "Scan 阻塞", "NOT_SCANNED": "未扫描", "COMPARE_READY": "可对比",
        "COMPARE_PENDING": "待对比", "SAME": "无变化", "DIFF": "有差异", "CHANGED": "有变化",
        "NEEDS_FILE_DIFF": "建议查看 File Diff", "FILE_DIFF_RECOMMENDED": "建议 File Diff",
        "FILE_DIFF_PENDING": "File Diff 待完成", "FILE_DIFF_DONE": "File Diff 已完成",
        "PAIRWISE_PENDING": "Pairwise 待完成", "PAIRWISE_PARTIAL": "Pairwise 部分完成",
        "PAIRWISE_EMPTY": "无 Pairwise", "METADATA_ONLY": "仅 metadata", "REVIEW": "需审阅",
        "NEEDS_REVIEW": "需审阅", "REVIEW_REQUIRED": "需审阅", "MANUAL_REVIEW": "需人工确认",
        "NEEDS_BASE_CONFIRM": "需确认 base", "RELEASE_CHECK_REQUIRED": "发布前检查",
        "RELEASED": "已发布", "RELEASE_BLOCKED": "发布阻塞", "APPLIED": "已应用", "DRY_RUN": "预演",
        "PASS_WITH_WARNING": "通过有注意项", "WARNING": "注意", "WARN": "注意", "PENDING": "待处理",
        "MISSING": "缺失", "EXTRA": "多余", "BROKEN": "断链", "MISMATCH": "不匹配",
        "TARGET_MATCH": "目标一致", "TARGET_MISMATCH": "目标不一致", "FAILED": "失败", "ERROR": "错误",
        "BLOCK": "阻塞", "BLOCKED": "阻塞", "UNKNOWN": "未确认", "FOUND": "已发现", "CLEAR": "无注意项",
        "NOT_APPLICABLE": "不适用", "EMPTY": "空", "NA": "不适用", "INFO": "信息",
        "initial": "initial", "stable": "stable", "final": "final", "ad-hoc": "ad-hoc", "dated": "dated",
    }
    return labels.get(text, labels.get(text.upper(), text))


def badge(value: Any, label: str | None = None) -> str:
    shown = status_label(value) if label is None else label
    return f"<span class='badge {status_class(value)}' title='{esc(value)}'>{esc(shown)}</span>"


def quiet_badge(value: Any, count: int) -> str:
    if int(count or 0) == 0:
        return "<span class='muted-dash'>-</span>"
    return badge(value, str(count))


def button(label: str, href: str = "#", kind: str = "secondary", *, disabled: bool = False, target: str = "") -> str:
    cls = f"btn {esc(kind)}".strip()
    if disabled or not href:
        return f"<span class='{cls} disabled'>{esc(label)}</span>"
    tgt = f" target='{esc(target)}'" if target else ""
    return f"<a class='{cls}' href='{esc(href)}'{tgt}>{esc(label)}</a>"


def action_strip(items: Sequence[str]) -> str:
    return "<div class='action-strip'>" + "".join(items) + "</div>"


def command_chip(command: Any, *, label: str = "复制", disabled_text: str = "待生成命令") -> str:
    cmd = str(command or "").strip()
    if not cmd:
        return f"<span class='cmd-chip disabled'><code>{esc(disabled_text)}</code></span>"
    payload = json.dumps(cmd, ensure_ascii=False)
    return (
        "<div class='cmd-chip'>"
        f"<code title='{esc(cmd)}'>{esc(cmd)}</code>"
        f"<button type='button' onclick='copyText({payload}, this)'>{esc(label)}</button>"
        "</div>"
    )


def command_box(command: Any, *, title: str = "下一步命令", note: str = "") -> str:
    cmd = str(command or "").strip()
    if not cmd:
        return "<div class='command-box muted-box'>暂无可执行命令。通常需要先确认 base / parent 或补充 scan 证据。</div>"
    payload = json.dumps(cmd, ensure_ascii=False)
    note_html = f"<div class='command-note'>{esc(note)}</div>" if note else ""
    return (
        "<div class='command-box'>"
        f"<div class='command-title'>{esc(title)}</div>"
        f"<div class='command-line'><code>{esc(cmd)}</code><button type='button' onclick='copyText({payload}, this)'>复制</button></div>"
        f"{note_html}"
        "</div>"
    )


def table(headers: list[str], rows: list[str], empty: str = "暂无数据") -> str:
    head = "".join(f"<th>{esc(h)}</th>" for h in headers)
    body = "".join(rows) if rows else f"<tr><td colspan='{len(headers)}' class='empty'>{esc(empty)}</td></tr>"
    return f"<div class='table-wrap'><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>"


def filterable_table(table_id: str, headers: list[str], rows: list[str], empty: str = "暂无数据", placeholder: str = "筛选") -> str:
    safe_id = esc(table_id)
    count = len(rows)
    return (
        f"<div class='table-tools' data-table-tools='{safe_id}'>"
        f"<div class='search'><span>搜索</span><input type='search' placeholder='{esc(placeholder)}' oninput=\"filterTable('{safe_id}', this.value)\"></div>"
        f"<div class='table-count'><span id='{safe_id}-count'>{count}</span> / {count} 行</div>"
        "</div>"
        f"<div id='{safe_id}-wrap' data-empty='{esc(empty)}'>" + table(headers, rows, empty) + "</div>"
    )


def panel(title: str, note: str, body: str, action: str = "") -> str:
    return (
        "<section class='panel'>"
        "<div class='panel-head'><div>"
        f"<h2>{esc(title)}</h2><p>{esc(note)}</p>"
        f"</div><div class='panel-actions'>{action}</div></div>"
        f"<div class='panel-body'>{body}</div></section>"
    )


def collapsible_panel(title: str, note: str, body: str, open: bool = False, action: str = "") -> str:
    opened = " open" if open else ""
    return (
        f"<details class='panel collapsible'{opened}>"
        "<summary class='panel-head'><div>"
        f"<h2>{esc(title)}</h2><p>{esc(note)}</p>"
        f"</div><div class='panel-actions'>{action}<span class='chevron'>⌄</span></div></summary>"
        f"<div class='panel-body'>{body}</div></details>"
    )


def kv_table(items: Sequence[tuple[str, Any]]) -> str:
    rows = [f"<tr><th>{esc(k)}</th><td>{esc(v if v not in (None, '') else '-')}</td></tr>" for k, v in items]
    return table(["字段", "值"], rows, "暂无信息")


def compact_meta(items: Sequence[tuple[str, Any]]) -> str:
    return "<div class='compact-meta'>" + "".join(
        f"<span><b>{esc(k)}</b><em>{esc(v if v not in (None, '') else '-')}</em></span>" for k, v in items
    ) + "</div>"


def metric_card(label: str, value: Any, hint: str = "", status: Any = None) -> str:
    st = status if status is not None else value
    return (
        f"<div class='metric-card {status_class(st)}'>"
        f"<div class='metric-label'>{esc(label)}</div>"
        f"<div class='metric-value'>{esc(value)}</div>"
        f"<div class='metric-hint'>{esc(hint)}</div>"
        "</div>"
    )


def metric_grid(items: Sequence[tuple[str, Any, str, Any]]) -> str:
    return "<div class='metric-grid'>" + "".join(metric_card(*item) for item in items) + "</div>"


def product_summary(items: list[tuple[str, Any, str, Any]]) -> str:
    return metric_grid(items)


def brief_grid(items: list[tuple[str, Any, str, Any]]) -> str:
    return metric_grid(items)


def tile_grid(items: list[Mapping[str, Any]]) -> str:
    cells = []
    for item in items:
        status = item.get("status") or "UNKNOWN"
        count = item.get("count", 0)
        cells.append(
            f"<div class='review-tile {status_class(status)}'>"
            f"<div class='tile-top'><div><b>{esc(item.get('title') or '-')}</b><span>{esc(item.get('subtitle') or '')}</span></div>{badge(status, item.get('status_label'))}</div>"
            f"<div class='tile-count'>{esc(count)}</div>"
            f"<p>{esc(item.get('hint') or '')}</p>"
            "</div>"
        )
    return "<div class='review-tile-grid'>" + "".join(cells) + "</div>"


def impact_grid(items: list[Mapping[str, Any]]) -> str:
    cells = []
    for item in items:
        status = item.get("status") or "UNKNOWN"
        cells.append(
            f"<div class='impact-card {status_class(status)}'>"
            f"<div class='impact-head'><b>{esc(item.get('domain'))}</b>{badge(status, item.get('label'))}</div>"
            f"<div class='impact-count'>{esc(item.get('count', '-'))}</div>"
            f"<p>{esc(item.get('hint') or '')}</p>"
            "</div>"
        )
    return "<div class='impact-grid'>" + "".join(cells) + "</div>"


def attention_items(items: list[tuple[Any, str, str, str]]) -> str:
    if not items:
        return "<div class='attention-empty'>暂无优先关注项。</div>"
    rows = []
    for severity, title, detail, evidence in items:
        rows.append(
            f"<div class='attention-item {status_class(severity)}'>"
            f"<div>{badge(severity)}</div>"
            f"<div><b>{esc(title)}</b><p>{esc(detail)}</p></div>"
            f"<code>{esc(evidence)}</code>"
            "</div>"
        )
    return "<div class='attention-list'>" + "".join(rows) + "</div>"


def trace_link_list(items: list[tuple[str, Any, str]]) -> str:
    rows = []
    for label, href, note in items:
        link = button("打开", str(href), "secondary", disabled=not bool(href), target="_blank")
        rows.append(
            "<div class='trace-link-row'>"
            f"<div><b>{esc(label)}</b><p>{esc(note)}</p></div>{link}"
            "</div>"
        )
    return "<div class='trace-links'>" + "".join(rows) + "</div>"


def evidence_grid(items: list[tuple[str, Any, str, str]]) -> str:
    cards = []
    for title, status, body, href in items:
        cards.append(
            f"<div class='evidence-card {status_class(status)}'>"
            f"<div class='evidence-top'>{badge(status)}{button('打开', href, disabled=not bool(href), target='_blank')}</div>"
            f"<b>{esc(title)}</b><p>{esc(body)}</p>"
            "</div>"
        )
    return "<div class='evidence-grid'>" + "".join(cards) + "</div>"


def status_rail(items: list[tuple[str, Any, str]]) -> str:
    steps = []
    for label, status, note in items:
        steps.append(
            f"<div class='rail-step {status_class(status)}'>"
            f"<div class='rail-mark'></div><b>{esc(label)}</b>"
            f"<span>{esc(status_label(status))}</span><p>{esc(note)}</p>"
            "</div>"
        )
    return "<div class='status-rail'>" + "".join(steps) + "</div>"


def next_action_panel(action: str, command: str, reason: str, *, status: Any = "INFO") -> str:
    body = f"<div class='next-action-title'>{badge(status)}<b>{esc(action or '下一步')}</b></div>" + command_box(command, note=reason)
    return panel("下一步", "建议动作和命令。命令仅作为工具入口，最终判断仍需人工确认。", body)


def timeline(comparisons: list[Mapping[str, Any]]) -> str:
    if not comparisons:
        return "<div class='empty'>暂无 comparison。</div>"
    nodes = []
    for item in comparisons:
        status = item.get("status") or item.get("review_level") or "UNKNOWN"
        old_v = item.get("old_version") or "-"
        new_v = item.get("new_version") or "-"
        mode = item.get("mode") or "selected"
        href = item.get("diff_html") or item.get("href") or ""
        open_link = button("打开 Diff", str(href), "primary", disabled=not bool(href))
        nodes.append(
            f"<div class='timeline-card {status_class(status)}' data-mode='{esc(mode)}' data-status='{esc(status)}'>"
            f"<div class='timeline-mode'>{esc(mode)}</div>"
            f"<div class='timeline-vers'><span>{esc(old_v)}</span><b>→</b><span>{esc(new_v)}</span></div>"
            f"<div>{badge(status)}</div>"
            f"<div class='timeline-sub'>Pairwise {esc(item.get('pairwise_done', 0))}/{esc(item.get('pairwise_total', 0))}</div>"
            f"{open_link}"
            "</div>"
        )
    return "<div class='timeline-viewport'><div class='timeline-track'>" + "".join(nodes) + "</div></div>"


def comparison_filter_bar() -> str:
    modes = [
        ("all", "全部"), ("adjacent", "Adjacent"), ("base", "Base"), ("cumulative", "Cumulative"), ("release", "Release"), ("custom", "Custom"),
    ]
    chips = "".join(f"<button type='button' class='filter-chip {'active' if k == 'all' else ''}' onclick=\"filterComparisons('{k}', this)\">{v}</button>" for k, v in modes)
    return f"<div class='comparison-filter'><div class='filter-chips'>{chips}</div><button type='button' class='btn secondary' onclick='scrollTimeline(-1)'>←</button><button type='button' class='btn secondary' onclick='scrollTimeline(1)'>→</button></div>"


def muted(text: Any) -> str:
    return f"<span class='muted'>{esc(text)}</span>"


def mono_path(path: Any) -> str:
    if not path:
        return "<span class='muted'>-</span>"
    return f"<code class='mono-path' title='{esc(path)}'>{esc(path)}</code>"


def evidence_link(label: str, href: Any, *, missing: str = "未生成") -> str:
    if not href:
        return f"<span class='muted'>{esc(missing)}</span>"
    return f"<a class='evidence-link compact' href='{esc(href)}' target='_blank'>{esc(label)}</a>"


def intent_banner(title: str, points: list[tuple[str, str]]) -> str:
    body = "".join(f"<div><b>{esc(k)}</b><p>{esc(v)}</p></div>" for k, v in points)
    return f"<div class='intent-banner'><h3>{esc(title)}</h3><div>{body}</div></div>"


def callout(title: str, body: str, status: Any = "INFO") -> str:
    return f"<div class='callout {status_class(status)}'><b>{esc(title)}</b><p>{body}</p></div>"


def details_block(summary: str, content: Any) -> str:
    return f"<details class='detail-fold'><summary>{esc(summary)}</summary><div>{content}</div></details>" if content else muted("-")


def _default_nav(nav: str = "") -> str:
    if nav:
        return nav
    return "<a class='active' href='#'>总览</a><a href='#'>证据</a>"


def review_page_shell(
    title: str,
    page_type: str,
    subtitle: str,
    body: str,
    *,
    decision: Any = "INFO",
    nav: str = "",
    rail: str = "",
    meta: str = "",
) -> str:
    nav_html = _default_nav(nav)
    rail_html = rail or ""
    meta_html = meta or ""
    return f"""<!doctype html>
<html lang='zh-CN'>
<head>
<meta charset='utf-8'>
<meta name='viewport' content='width=device-width, initial-scale=1.0'>
<title>{esc(title)}</title>
<style>{_css()}</style>
</head>
<body>
<div class='app'>
  <aside class='sidebar'>
    <div class='brand'><div class='logo'>LG</div><div><b>lib_guard</b><span>Library Review</span></div></div>
    <nav class='side-nav'>{nav_html}</nav>
    <div class='side-card'><b>{esc(page_type)}</b><p>{esc(subtitle)}</p></div>
  </aside>
  <main class='main'>
    <header class='hero'>
      <div>
        <div class='kicker'>{esc(page_type)}</div>
        <h1>{esc(title)}</h1>
        <p>{esc(subtitle)}</p>
        {meta_html}
      </div>
      <div class='hero-status'>{badge(decision)}</div>
    </header>
    <section class='workspace'>
      {rail_html}
      {body}
    </section>
  </main>
</div>
<script>{_js()}</script>
</body>
</html>"""


def page_shell(title: str, kicker: str, subtitle: str, body: str, nav: str = "") -> str:
    return review_page_shell(title, kicker, subtitle, body, decision="INFO", nav=nav)


def _css() -> str:
    return r"""
:root{
  --bg:#f7f8fb;--surface:#fff;--surface-2:#fbfcff;--line:#e4e8ef;--line-strong:#d3dae6;
  --text:#172033;--muted:#667085;--light:#98a2b3;--blue:#155eef;--blue-bg:#eef4ff;
  --green:#168253;--green-bg:#edf9f1;--amber:#a15c00;--amber-bg:#fff7e8;--red:#c0332b;--red-bg:#fff1f0;
  --shadow:0 12px 28px rgba(16,24,40,.06);--radius:12px;--radius-sm:8px;--mono:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
}
*{box-sizing:border-box;min-width:0} html{scroll-behavior:smooth} body{margin:0;background:var(--bg);color:var(--text);font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",Arial,sans-serif;font-size:14px;line-height:1.6;-webkit-font-smoothing:antialiased}
a{color:inherit;text-decoration:none} p{margin:0;color:var(--muted)} code,.mono,.mono-path{font-family:var(--mono);font-size:12px;overflow-wrap:anywhere;word-break:break-word}.app{display:grid;grid-template-columns:248px minmax(0,1fr);min-height:100vh}.sidebar{position:sticky;top:0;height:100vh;background:var(--surface);border-right:1px solid var(--line);padding:28px 20px;overflow:auto}.brand{display:flex;gap:12px;align-items:center;margin-bottom:24px}.brand .logo{width:36px;height:36px;border-radius:10px;background:#111827;color:#fff;display:grid;place-items:center;font-weight:700}.brand b{display:block}.brand span,.side-card p{font-size:12px;color:var(--muted)}.side-nav{display:flex;flex-direction:column;gap:5px}.side-nav a{display:flex;align-items:center;padding:8px 10px;border-radius:8px;color:var(--muted)}.side-nav a:hover,.side-nav a.active{background:var(--bg);color:var(--text);font-weight:600}.side-card{margin-top:22px;border:1px solid var(--line);border-radius:12px;padding:14px;background:var(--surface-2)}.main{min-width:0}.hero{display:flex;justify-content:space-between;gap:20px;align-items:flex-start;background:var(--surface);border-bottom:1px solid var(--line);padding:30px 36px}.hero h1{margin:4px 0 7px;font-size:26px;letter-spacing:-.02em}.kicker{font-size:12px;color:var(--muted);font-weight:700;letter-spacing:.08em;text-transform:uppercase}.hero-status{flex:0 0 auto}.workspace{padding:28px 36px 56px;max-width:1500px}.compact-meta{display:flex;gap:8px;flex-wrap:wrap;margin-top:10px}.compact-meta span{display:inline-flex;gap:6px;align-items:center;border:1px solid var(--line);border-radius:999px;padding:5px 9px;background:var(--surface-2);font-size:12px}.compact-meta b{color:#344054}.compact-meta em{font-style:normal;color:var(--muted);max-width:320px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.badge{display:inline-flex;align-items:center;justify-content:center;max-width:190px;min-height:24px;border-radius:999px;border:1px solid var(--line);padding:3px 9px;font-size:12px;font-weight:700;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.badge.ok{color:var(--green);background:var(--green-bg);border-color:#b9dfc8}.badge.warn{color:var(--amber);background:var(--amber-bg);border-color:#f1cf99}.badge.bad{color:var(--red);background:var(--red-bg);border-color:#efb3ac}.badge.muted{color:#667085;background:#f2f4f7;border-color:#d5dbe5}.badge.neutral{color:#344054;background:#f8fafc}.muted,.muted-dash{color:var(--light)}.panel{background:var(--surface);border:1px solid var(--line);border-radius:var(--radius);box-shadow:var(--shadow);margin-bottom:18px;overflow:hidden}.panel-head{display:flex;justify-content:space-between;gap:12px;align-items:flex-start;padding:17px 20px;border-bottom:1px solid var(--line);background:linear-gradient(180deg,#fff,#fbfcff)}.panel-head h2{font-size:16px;margin:0 0 4px}.panel-head p{font-size:13px}.panel-body{padding:18px 20px}.panel-actions{display:flex;gap:8px;align-items:center;flex:0 0 auto}.collapsible>summary{cursor:pointer;list-style:none}.collapsible>summary::-webkit-details-marker{display:none}.collapsible[open] .chevron{transform:rotate(180deg)}.chevron{transition:transform .2s}.metric-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px}.metric-card,.review-tile,.impact-card,.evidence-card{border:1px solid var(--line);border-radius:12px;background:var(--surface);padding:14px;box-shadow:0 1px 2px rgba(16,24,40,.03)}.metric-card.ok,.review-tile.ok,.impact-card.ok{border-left:4px solid var(--green)}.metric-card.warn,.review-tile.warn,.impact-card.warn{border-left:4px solid var(--amber)}.metric-card.bad,.review-tile.bad,.impact-card.bad{border-left:4px solid var(--red)}.metric-label{color:var(--muted);font-size:12px}.metric-value{font-size:24px;font-weight:800;letter-spacing:-.02em;margin-top:4px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.metric-hint{font-size:12px;color:var(--light)}.review-tile-grid,.impact-grid,.evidence-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:12px}.tile-top,.impact-head,.evidence-top{display:flex;justify-content:space-between;gap:10px;align-items:flex-start}.tile-top span{display:block;color:var(--light);font-size:12px}.tile-count,.impact-count{font-size:28px;font-weight:800;margin-top:12px}.review-tile p,.impact-card p,.evidence-card p{font-size:12px;margin-top:6px}.table-wrap{overflow:auto;border:1px solid var(--line);border-radius:10px}.table-tools{display:flex;justify-content:space-between;gap:12px;align-items:center;margin-bottom:10px;flex-wrap:wrap}.search{display:flex;gap:8px;align-items:center;min-width:260px;border:1px solid var(--line);background:#fff;border-radius:999px;padding:6px 12px}.search span{font-size:12px;color:var(--muted);font-weight:700}.search input{border:0;outline:0;background:transparent;width:100%;font-size:13px}table{width:100%;border-collapse:collapse;text-align:left;background:#fff}th,td{padding:10px 12px;border-bottom:1px solid var(--line);vertical-align:top}th{font-size:12px;color:#344054;background:#f8fafc;white-space:nowrap}td{font-size:13px}.empty{text-align:center;color:var(--muted);padding:30px}.is-hidden-by-filter{display:none!important}.btn{display:inline-flex;align-items:center;justify-content:center;min-height:30px;border:1px solid var(--line-strong);border-radius:8px;background:#fff;padding:6px 10px;font-size:12px;font-weight:700;color:#344054;white-space:nowrap;cursor:pointer}.btn.primary{background:var(--blue);border-color:var(--blue);color:#fff}.btn.disabled{opacity:.45;cursor:not-allowed}.action-strip{display:flex;gap:8px;overflow-x:auto;white-space:nowrap;padding-bottom:2px}.action-strip .btn{flex:0 0 auto}.cmd-chip{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:8px;align-items:center;max-width:100%;min-width:0;border:1px solid var(--line);border-radius:9px;background:#f8fafc;padding:5px}.cmd-chip code{display:block;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;word-break:normal;overflow-wrap:normal;padding:0 6px}.cmd-chip button,.command-line button{border:1px solid var(--line-strong);background:#fff;border-radius:7px;padding:5px 8px;font-size:12px;cursor:pointer;white-space:nowrap}.cmd-chip.disabled{display:inline-flex;color:var(--light);padding:7px 10px}.command-box{border:1px solid var(--line);border-radius:12px;background:#f8fafc;padding:14px}.command-title{font-size:12px;color:var(--muted);font-weight:800;margin-bottom:8px}.command-line{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:8px;align-items:start}.command-line code{display:block;background:#fff;border:1px solid var(--line);border-radius:8px;padding:10px;white-space:pre-wrap}.command-note{color:var(--muted);font-size:12px;margin-top:8px}.muted-box{color:var(--muted)}.status-rail{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin-bottom:18px}.rail-step{position:relative;border:1px solid var(--line);border-radius:12px;background:#fff;padding:13px 13px 13px 36px}.rail-mark{position:absolute;left:14px;top:18px;width:12px;height:12px;border-radius:50%;background:var(--line-strong)}.rail-step.ok .rail-mark{background:var(--green)}.rail-step.warn .rail-mark{background:var(--amber)}.rail-step.bad .rail-mark{background:var(--red)}.rail-step b{display:block;font-size:13px}.rail-step span{display:block;font-size:12px;color:#344054;margin-top:2px}.rail-step p{font-size:12px}.attention-list{display:flex;flex-direction:column;gap:10px}.attention-item{display:grid;grid-template-columns:100px minmax(0,1fr) minmax(160px,.45fr);gap:12px;align-items:start;border:1px solid var(--line);border-radius:12px;background:#fff;padding:12px}.attention-item.warn{background:var(--amber-bg);border-color:#f1cf99}.attention-item.bad{background:var(--red-bg);border-color:#efb3ac}.attention-item p{font-size:12px}.attention-item code{color:var(--muted)}.attention-empty{border:1px dashed var(--line);border-radius:12px;padding:18px;text-align:center;color:var(--muted)}.trace-links{display:flex;flex-direction:column;gap:8px}.trace-link-row{display:flex;justify-content:space-between;gap:12px;align-items:center;border:1px solid var(--line);border-radius:12px;background:#fff;padding:12px}.trace-link-row p{font-size:12px}.timeline-viewport{overflow-x:auto;overflow-y:hidden;border:1px solid var(--line);border-radius:12px;background:#fff}.timeline-track{display:grid;grid-auto-flow:column;grid-auto-columns:220px;gap:14px;min-width:max-content;padding:16px}.timeline-card{border:1px solid var(--line);border-radius:12px;padding:12px;background:#fff}.timeline-card.ok{border-top:4px solid var(--green)}.timeline-card.warn{border-top:4px solid var(--amber)}.timeline-card.bad{border-top:4px solid var(--red)}.timeline-mode{font-size:11px;font-weight:800;color:var(--muted);text-transform:uppercase}.timeline-vers{display:flex;gap:6px;align-items:center;margin:8px 0}.timeline-vers span{max-width:88px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.timeline-sub{font-size:12px;color:var(--muted);margin:6px 0}.comparison-filter{display:flex;justify-content:space-between;gap:10px;align-items:center;margin-bottom:10px}.filter-chips{display:flex;gap:8px;overflow-x:auto}.filter-chip{border:1px solid var(--line);background:#fff;border-radius:999px;padding:6px 10px;font-size:12px;cursor:pointer;white-space:nowrap}.filter-chip.active{background:var(--blue-bg);border-color:#9cc2ff;color:#1849a9;font-weight:800}.detail-fold summary{cursor:pointer;color:var(--blue);font-weight:700}.intent-banner,.callout{border:1px solid var(--line);background:#fff;border-radius:12px;padding:14px;margin-bottom:12px}.callout.warn{background:var(--amber-bg)}.callout.bad{background:var(--red-bg)}@media(max-width:980px){.app{grid-template-columns:1fr}.sidebar{display:none}.hero,.workspace{padding:22px}.attention-item{grid-template-columns:1fr}.command-line{grid-template-columns:1fr}}
"""


def _js() -> str:
    return r"""
function copyText(text, btn){
  function done(){ if(btn){ var old=btn.textContent; btn.textContent='已复制'; setTimeout(function(){btn.textContent=old},1200); } }
  if(navigator.clipboard && window.isSecureContext){ navigator.clipboard.writeText(text).then(done); return; }
  var ta=document.createElement('textarea'); ta.value=text; document.body.appendChild(ta); ta.select(); document.execCommand('copy'); document.body.removeChild(ta); done();
}
function filterTable(tableId, query){
  var wrap=document.getElementById(tableId+'-wrap'); if(!wrap) return;
  var rows=Array.from(wrap.querySelectorAll('tbody tr')); var q=String(query||'').toLowerCase().trim(); var visible=0;
  rows.forEach(function(row){ if(row.querySelector('.empty')){row.classList.toggle('is-hidden-by-filter', !!q); return;} var show=!q || row.textContent.toLowerCase().indexOf(q)>=0; row.classList.toggle('is-hidden-by-filter', !show); if(show) visible++; });
  var count=document.getElementById(tableId+'-count'); if(count) count.textContent=visible;
}
function filterComparisons(mode, btn){
  document.querySelectorAll('.filter-chip').forEach(function(x){x.classList.remove('active')}); if(btn) btn.classList.add('active');
  document.querySelectorAll('.timeline-card').forEach(function(card){ var show=mode==='all' || card.getAttribute('data-mode')===mode; card.style.display=show?'':'none'; });
}
function scrollTimeline(dir){
  var vp=document.querySelector('.timeline-viewport'); if(vp) vp.scrollBy({left:dir*520, behavior:'smooth'});
}
"""
