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
        "REVIEW_REQUIRED", "USAGE_REVIEW_REQUIRED", "COMPARE_PENDING", "NOT_READY", "LARGE_CHANGE", "DIFF_EXPLOSION", "PATH_RESTRUCTURE", "SCAN_EVIDENCE_INCOMPLETE",
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
        "SCAN_READY": "扫描可用", "READY_FOR_DIFF": "可进入对比", "SCAN_NEEDS_REVIEW": "扫描需确认",
        "SCAN_BLOCKED": "扫描阻塞", "NOT_SCANNED": "未扫描", "COMPARE_READY": "可对比",
        "COMPARE_PENDING": "待对比", "SAME": "无变化", "DIFF": "有差异", "CHANGED": "有变化",
        "NEEDS_FILE_DIFF": "建议查看重点文件", "FILE_DIFF_RECOMMENDED": "建议查看重点文件",
        "FILE_DIFF_PENDING": "重点文件待确认", "FILE_DIFF_DONE": "重点文件已确认",
        "PAIRWISE_PENDING": "文件配对待完成", "PAIRWISE_PARTIAL": "文件配对部分完成",
        "PAIRWISE_EMPTY": "无重点建议", "METADATA_ONLY": "仅元数据", "REVIEW": "需审阅",
        "NEEDS_REVIEW": "需审阅", "REVIEW_REQUIRED": "需审阅", "USAGE_REVIEW_REQUIRED": "需审查后使用", "MANUAL_REVIEW": "需人工确认",
        "NEEDS_BASE_CONFIRM": "需确认基准版", "LARGE_CHANGE": "变化过大", "DIFF_EXPLOSION": "变化异常", "PATH_RESTRUCTURE": "疑似目录重组", "SCAN_EVIDENCE_INCOMPLETE": "扫描证据不完整", "FILE_DIFF_RECOMMENDED": "建议查看重点文件", "RELEASE_CHECK_REQUIRED": "发布前检查",
        "RELEASED": "已发布", "RELEASE_BLOCKED": "发布阻塞", "RELEASE_NOT_APPLICABLE": "未接入正式发布", "APPLIED": "已应用", "DRY_RUN": "预演",
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


def command_chip(command: Any, *, label: str = "命令", disabled_text: str = "待生成命令") -> str:
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
    return faceted_table(table_id, headers, rows, empty, placeholder)


def faceted_table(
    table_id: str,
    headers: list[str],
    rows: list[str],
    empty: str = "暂无数据",
    placeholder: str = "筛选",
    facets: Sequence[tuple[int, str] | int] = (),
    *,
    wrap_class: str = "table-wrap",
    table_class: str = "",
) -> str:
    safe_id = esc(table_id)
    head = "".join(f"<th>{esc(h)}</th>" for h in headers)
    body = "".join(rows) if rows else f"<tr><td colspan='{len(headers)}' class='empty'>{esc(empty)}</td></tr>"
    facet_tokens: list[str] = []
    for item in facets:
        if isinstance(item, tuple):
            index, label = item
        else:
            index, label = item, headers[item] if 0 <= int(item) < len(headers) else f"列 {item}"
        if 0 <= int(index) < len(headers):
            facet_tokens.append(f"{int(index)}:{str(label)}")
    facet_attr = esc("|".join(facet_tokens))
    cls_attr = f" class='{esc(table_class)}'" if table_class else ""
    total = len(rows)
    return (
        f"<div class='table-tools faceted-table-tools' data-table-tools='{safe_id}'>"
        f"<div class='search'><span>搜索</span><input id='{safe_id}-search' type='search' placeholder='{esc(placeholder)}' oninput=\"applyTableFilters('{safe_id}')\"></div>"
        f"<div class='facet-selects' id='{safe_id}-facets'></div>"
        f"<button type='button' class='btn secondary table-reset' onclick=\"resetTableFilters('{safe_id}')\">清空</button>"
        f"<div class='table-count'><span id='{safe_id}-count'>{total}</span> / <span id='{safe_id}-total'>{total}</span> 行</div>"
        "</div>"
        f"<div id='{safe_id}-wrap' class='{esc(wrap_class)}'>"
        f"<table id='{safe_id}'{cls_attr} data-filterable-table data-filter-columns='{facet_attr}'><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"
        "</div>"
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


def _recommendation_summary(item: Mapping[str, Any]) -> str:
    rec = item.get("file_diff_recommendation") if isinstance(item.get("file_diff_recommendation"), Mapping) else item
    recommended = rec.get("recommended_total", rec.get("recommended", 0))
    generated = rec.get("result_generated", rec.get("generated_total", 0))
    candidates = rec.get("candidate_total", rec.get("changed_file_total", 0))
    quality = rec.get("comparison_quality") or item.get("comparison_quality") or "NORMAL"
    parts = [f"重点 {recommended}", f"已生成 {generated}"]
    if int(candidates or 0):
        parts.append(f"候选 {candidates}")
    if str(quality).upper() not in {"", "NORMAL", "PASS", "OK"}:
        parts.append(status_label(quality))
    return " · ".join(esc(x) for x in parts)


def timeline(comparisons: list[Mapping[str, Any]]) -> str:
    if not comparisons:
        return "<div class='empty'>暂无对比记录。</div>"
    nodes = []
    for item in comparisons:
        status = item.get("comparison_quality") or item.get("status") or item.get("review_level") or "UNKNOWN"
        old_v = item.get("old_version") or "-"
        new_v = item.get("new_version") or "-"
        mode = item.get("mode") or "selected"
        href = item.get("diff_html") or item.get("href") or ""
        open_link = button("打开选定对比", str(href), "primary", disabled=not bool(href))
        nodes.append(
            f"<div class='timeline-card {status_class(status)}' data-mode='{esc(mode)}' data-status='{esc(status)}'>"
            f"<div class='timeline-mode'>{esc(mode)}</div>"
            f"<div class='timeline-vers'><span>{esc(old_v)}</span><b>→</b><span>{esc(new_v)}</span></div>"
            f"<div>{badge(status)}</div>"
            f"<div class='timeline-sub'>{_recommendation_summary(item)}</div>"
            f"{open_link}"
            "</div>"
        )
    return "<div class='timeline-viewport'><div class='timeline-track'>" + "".join(nodes) + "</div></div>"


def comparison_filter_bar() -> str:
    modes = [
        ("all", "全部"), ("adjacent", "相邻版本"), ("base", "基准版"), ("cumulative", "累计"), ("release", "发布"), ("custom", "自定义"),
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
a{color:inherit;text-decoration:none} p{margin:0;color:var(--muted)} code,.mono,.mono-path{font-family:var(--mono);font-size:12px;overflow-wrap:anywhere;word-break:break-word}.app{display:block;min-height:100vh}.main{min-width:0}.hero{display:flex;justify-content:space-between;gap:20px;align-items:flex-start;background:var(--surface);border-bottom:1px solid var(--line);padding:30px 36px}.hero h1{margin:4px 0 7px;font-size:26px;letter-spacing:-.02em}.kicker{font-size:12px;color:var(--muted);font-weight:700;letter-spacing:.08em;text-transform:uppercase}.hero-status{flex:0 0 auto}.workspace{padding:28px 36px 56px;max-width:1500px}.compact-meta{display:flex;gap:8px;flex-wrap:wrap;margin-top:10px}.compact-meta span{display:inline-flex;gap:6px;align-items:center;border:1px solid var(--line);border-radius:999px;padding:5px 9px;background:var(--surface-2);font-size:12px}.compact-meta b{color:#344054}.compact-meta em{font-style:normal;color:var(--muted);max-width:320px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.badge{display:inline-flex;align-items:center;justify-content:center;max-width:190px;min-height:24px;border-radius:999px;border:1px solid var(--line);padding:3px 9px;font-size:12px;font-weight:700;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.badge.ok{color:var(--green);background:var(--green-bg);border-color:#b9dfc8}.badge.warn{color:var(--amber);background:var(--amber-bg);border-color:#f1cf99}.badge.bad{color:var(--red);background:var(--red-bg);border-color:#efb3ac}.badge.muted{color:#667085;background:#f2f4f7;border-color:#d5dbe5}.badge.neutral{color:#344054;background:#f8fafc}.muted,.muted-dash{color:var(--light)}.panel{background:var(--surface);border:1px solid var(--line);border-radius:var(--radius);box-shadow:var(--shadow);margin-bottom:18px;overflow:hidden}.panel-head{display:flex;justify-content:space-between;gap:12px;align-items:flex-start;padding:17px 20px;border-bottom:1px solid var(--line);background:linear-gradient(180deg,#fff,#fbfcff)}.panel-head h2{font-size:16px;margin:0 0 4px}.panel-head p{font-size:13px}.panel-body{padding:18px 20px}.panel-actions{display:flex;gap:8px;align-items:center;flex:0 0 auto}.collapsible>summary{cursor:pointer;list-style:none}.collapsible>summary::-webkit-details-marker{display:none}.collapsible[open] .chevron{transform:rotate(180deg)}.chevron{transition:transform .2s}.metric-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px}.metric-card,.review-tile,.impact-card,.evidence-card{border:1px solid var(--line);border-radius:12px;background:var(--surface);padding:14px;box-shadow:0 1px 2px rgba(16,24,40,.03)}.metric-card.ok,.review-tile.ok,.impact-card.ok{border-left:4px solid var(--green)}.metric-card.warn,.review-tile.warn,.impact-card.warn{border-left:4px solid var(--amber)}.metric-card.bad,.review-tile.bad,.impact-card.bad{border-left:4px solid var(--red)}.metric-label{color:var(--muted);font-size:12px}.metric-value{font-size:24px;font-weight:800;letter-spacing:-.02em;margin-top:4px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.metric-hint{font-size:12px;color:var(--light)}.review-tile-grid,.impact-grid,.evidence-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:12px}.tile-top,.impact-head,.evidence-top{display:flex;justify-content:space-between;gap:10px;align-items:flex-start}.tile-top span{display:block;color:var(--light);font-size:12px}.tile-count,.impact-count{font-size:28px;font-weight:800;margin-top:12px}.review-tile p,.impact-card p,.evidence-card p{font-size:12px;margin-top:6px}.table-wrap{overflow:auto;border:1px solid var(--line);border-radius:10px}.table-tools{display:flex;justify-content:space-between;gap:12px;align-items:center;margin-bottom:10px;flex-wrap:wrap}.search{display:flex;gap:8px;align-items:center;min-width:260px;border:1px solid var(--line);background:#fff;border-radius:999px;padding:6px 12px}.search span{font-size:12px;color:var(--muted);font-weight:700}.search input{border:0;outline:0;background:transparent;width:100%;font-size:13px}table{width:100%;border-collapse:collapse;text-align:left;background:#fff}th,td{padding:10px 12px;border-bottom:1px solid var(--line);vertical-align:top}th{font-size:12px;color:#344054;background:#f8fafc;white-space:nowrap}td{font-size:13px}.empty{text-align:center;color:var(--muted);padding:30px}.is-hidden-by-filter{display:none!important}.btn{display:inline-flex;align-items:center;justify-content:center;min-height:30px;border:1px solid var(--line-strong);border-radius:8px;background:#fff;padding:6px 10px;font-size:12px;font-weight:700;color:#344054;white-space:nowrap;cursor:pointer}.btn.primary{background:var(--blue);border-color:var(--blue);color:#fff}.btn.disabled{opacity:.45;cursor:not-allowed}.action-strip{display:flex;gap:8px;overflow-x:auto;white-space:nowrap;padding-bottom:2px}.action-strip .btn{flex:0 0 auto}.cmd-chip{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:8px;align-items:center;max-width:100%;min-width:0;border:1px solid var(--line);border-radius:9px;background:#f8fafc;padding:5px}.cmd-chip code{display:block;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;word-break:normal;overflow-wrap:normal;padding:0 6px}.cmd-chip button,.command-line button{border:1px solid var(--line-strong);background:#fff;border-radius:7px;padding:5px 8px;font-size:12px;cursor:pointer;white-space:nowrap}.cmd-chip.disabled{display:inline-flex;color:var(--light);padding:7px 10px}.command-box{border:1px solid var(--line);border-radius:12px;background:#f8fafc;padding:14px}.command-title{font-size:12px;color:var(--muted);font-weight:800;margin-bottom:8px}.command-line{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:8px;align-items:start}.command-line code{display:block;background:#fff;border:1px solid var(--line);border-radius:8px;padding:10px;white-space:pre-wrap}.command-note{color:var(--muted);font-size:12px;margin-top:8px}.muted-box{color:var(--muted)}.status-rail{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin-bottom:18px}.rail-step{position:relative;border:1px solid var(--line);border-radius:12px;background:#fff;padding:13px 13px 13px 36px}.rail-mark{position:absolute;left:14px;top:18px;width:12px;height:12px;border-radius:50%;background:var(--line-strong)}.rail-step.ok .rail-mark{background:var(--green)}.rail-step.warn .rail-mark{background:var(--amber)}.rail-step.bad .rail-mark{background:var(--red)}.rail-step b{display:block;font-size:13px}.rail-step span{display:block;font-size:12px;color:#344054;margin-top:2px}.rail-step p{font-size:12px}.attention-list{display:flex;flex-direction:column;gap:10px}.attention-item{display:grid;grid-template-columns:100px minmax(0,1fr) minmax(160px,.45fr);gap:12px;align-items:start;border:1px solid var(--line);border-radius:12px;background:#fff;padding:12px}.attention-item.warn{background:var(--amber-bg);border-color:#f1cf99}.attention-item.bad{background:var(--red-bg);border-color:#efb3ac}.attention-item p{font-size:12px}.attention-item code{color:var(--muted)}.attention-empty{border:1px dashed var(--line);border-radius:12px;padding:18px;text-align:center;color:var(--muted)}.trace-links{display:flex;flex-direction:column;gap:8px}.trace-link-row{display:flex;justify-content:space-between;gap:12px;align-items:center;border:1px solid var(--line);border-radius:12px;background:#fff;padding:12px}.trace-link-row p{font-size:12px}.timeline-viewport{overflow-x:auto;overflow-y:hidden;border:1px solid var(--line);border-radius:12px;background:#fff}.timeline-track{display:grid;grid-auto-flow:column;grid-auto-columns:220px;gap:14px;min-width:max-content;padding:16px}.timeline-card{border:1px solid var(--line);border-radius:12px;padding:12px;background:#fff}.timeline-card.ok{border-top:4px solid var(--green)}.timeline-card.warn{border-top:4px solid var(--amber)}.timeline-card.bad{border-top:4px solid var(--red)}.timeline-mode{font-size:11px;font-weight:800;color:var(--muted);text-transform:uppercase}.timeline-vers{display:flex;gap:6px;align-items:center;margin:8px 0}.timeline-vers span{max-width:88px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.timeline-sub{font-size:12px;color:var(--muted);margin:6px 0}.comparison-filter{display:flex;justify-content:space-between;gap:10px;align-items:center;margin-bottom:10px}.filter-chips{display:flex;gap:8px;overflow-x:auto}.filter-chip{border:1px solid var(--line);background:#fff;border-radius:999px;padding:6px 10px;font-size:12px;cursor:pointer;white-space:nowrap}.filter-chip.active{background:var(--blue-bg);border-color:#9cc2ff;color:#1849a9;font-weight:800}.detail-fold summary{cursor:pointer;color:var(--blue);font-weight:700}.intent-banner,.callout{border:1px solid var(--line);background:#fff;border-radius:12px;padding:14px;margin-bottom:12px}.callout.warn{background:var(--amber-bg)}.callout.bad{background:var(--red-bg)}
.catalog-layout{display:grid;grid-template-columns:280px minmax(0,1fr);gap:18px;align-items:start}.catalog-filter-panel{position:sticky;top:18px}.catalog-filter-panel .search{min-width:0;width:100%;margin-bottom:10px}.catalog-filter-panel select{width:100%;border:1px solid var(--line);border-radius:9px;background:#fff;padding:8px 10px;margin:5px 0 10px;color:#344054}.filter-group-title{font-size:12px;font-weight:800;color:var(--muted);margin:12px 0 6px}.catalog-chips{display:flex;flex-wrap:wrap;gap:7px}.catalog-chips .filter-chip{padding:6px 9px}.library-browser{height:min(74vh,820px);overflow:auto;padding-right:4px;scrollbar-gutter:stable}.library-group{border:1px solid var(--line);border-radius:14px;background:#fff;margin-bottom:14px;box-shadow:var(--shadow);overflow:hidden}.library-group>summary{list-style:none;cursor:pointer;padding:14px 16px;display:flex;justify-content:space-between;gap:12px;align-items:center;background:linear-gradient(180deg,#fff,#fbfcff);border-bottom:1px solid var(--line)}.library-group>summary::-webkit-details-marker{display:none}.library-group-title{display:flex;flex-direction:column}.library-group-title b{font-size:15px}.library-group-title span{font-size:12px;color:var(--muted)}.library-group-body{padding:12px;background:#fbfcff}.library-card{border:1px solid var(--line);border-radius:13px;background:#fff;margin-bottom:10px;overflow:hidden}.library-main{display:grid;grid-template-columns:minmax(220px,1.35fr) minmax(160px,.9fr) minmax(130px,.65fr) minmax(130px,.65fr) minmax(260px,1fr);gap:12px;align-items:center;padding:13px 14px}.library-title{font-size:16px;font-weight:800}.library-path,.version-path{font-size:12px;color:var(--muted);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.library-status{display:flex;gap:8px;justify-content:flex-end;align-items:center;flex-wrap:wrap}.version-drawer{border-top:1px solid var(--line);background:#fbfcff}.version-drawer>summary{list-style:none;cursor:pointer;padding:10px 14px;font-weight:800;color:#344054}.version-drawer>summary::-webkit-details-marker{display:none}.version-list{display:flex;flex-direction:column;gap:8px;padding:0 12px 12px}.version-row{display:grid;grid-template-columns:minmax(190px,1.15fr) .58fr .58fr .58fr .58fr minmax(220px,1.2fr) minmax(250px,1.1fr);gap:10px;align-items:center;border:1px solid var(--line);background:#fff;border-radius:11px;padding:10px}.version-name{font-weight:800}.version-next{display:flex;flex-direction:column;gap:4px}.version-next .muted{font-size:12px}.browser-count{font-size:12px;color:var(--muted);font-weight:700}.catalog-empty{border:1px dashed var(--line);border-radius:14px;padding:26px;text-align:center;color:var(--muted);background:#fff}@media(max-width:1100px){.catalog-layout{grid-template-columns:1fr}.catalog-filter-panel{position:static}.library-browser{height:auto}.library-main,.version-row{grid-template-columns:1fr}.library-status{justify-content:flex-start}}
@media(max-width:980px){.hero,.workspace{padding:22px}.attention-item{grid-template-columns:1fr}.command-line{grid-template-columns:1fr}}
.faceted-table-tools{position:sticky;top:0;z-index:5;background:rgba(247,248,251,.94);backdrop-filter:blur(8px);border:1px solid var(--line);border-radius:12px;padding:8px;align-items:center}.facet-selects{display:flex;gap:8px;align-items:center;flex-wrap:wrap;flex:1 1 auto}.facet-selects select{max-width:190px;border:1px solid var(--line);background:#fff;border-radius:9px;padding:7px 9px;color:#344054;font-size:12px}.table-count{font-size:12px;color:#667085;font-weight:800;white-space:nowrap}.table-reset{min-height:32px}.faceted-table-tools+.version-scroll-table,.faceted-table-tools+.table-wrap{margin-top:0}
@media(max-width:760px){.faceted-table-tools{align-items:stretch}.faceted-table-tools .search,.facet-selects,.facet-selects select,.table-reset{width:100%;max-width:none}.facet-selects{display:grid;grid-template-columns:1fr}}
"""


def _js() -> str:
    return r"""

function setCatalogStatusFilter(status, btn){
  document.querySelectorAll('[data-catalog-status-chip]').forEach(function(x){x.classList.remove('active')});
  if(btn) btn.classList.add('active');
  var root=document.querySelector('[data-catalog-browser]'); if(root) root.setAttribute('data-status-filter', status||'all');
  filterCatalogBrowser();
}
function filterCatalogBrowser(){
  var root=document.querySelector('[data-catalog-browser]'); if(!root) return;
  var q=(document.getElementById('catalog-search')&&document.getElementById('catalog-search').value||'').toLowerCase().trim();
  var vendor=(document.getElementById('catalog-vendor')&&document.getElementById('catalog-vendor').value||'all');
  var stage=(document.getElementById('catalog-stage')&&document.getElementById('catalog-stage').value||'all');
  var onlyLatest=document.getElementById('catalog-latest')&&document.getElementById('catalog-latest').checked;
  var st=root.getAttribute('data-status-filter')||'all';
  var visibleLib=0, visibleVer=0;
  root.querySelectorAll('.library-card').forEach(function(card){
    var text=card.textContent.toLowerCase();
    var hit=!q || text.indexOf(q)>=0;
    var vhit=vendor==='all' || card.getAttribute('data-vendor')===vendor;
    var shit=stage==='all' || card.getAttribute('data-stages').split(',').indexOf(stage)>=0;
    var statusHit=st==='all' || card.getAttribute('data-overall')===st || card.getAttribute('data-tags').split(',').indexOf(st)>=0;
    var show=hit && vhit && shit && statusHit;
    card.style.display=show?'':'none';
    if(show){visibleLib++;}
    card.querySelectorAll('.version-row').forEach(function(row){
      var rowShow=show;
      if(onlyLatest && row.getAttribute('data-latest')!=='1') rowShow=false;
      row.style.display=rowShow?'':'none';
      if(rowShow) visibleVer++;
    });
  });
  root.querySelectorAll('.library-group').forEach(function(group){
    var any=Array.from(group.querySelectorAll('.library-card')).some(function(x){return x.style.display!== 'none'});
    group.style.display=any?'':'none';
  });
  var c=document.getElementById('catalog-visible-count'); if(c) c.textContent=visibleLib+' libraries / '+visibleVer+' versions';
}
function catalogExpand(mode){
  var root=document.querySelector('[data-catalog-browser]'); if(!root) return;
  root.querySelectorAll('details.version-drawer').forEach(function(d){
    if(mode==='collapse') d.open=false;
    else if(mode==='all') d.open=true;
    else if(mode==='review'){
      var card=d.closest('.library-card');
      d.open=!!card && (card.getAttribute('data-tags').indexOf('review')>=0 || card.getAttribute('data-tags').indexOf('block')>=0 || card.getAttribute('data-tags').indexOf('file_diff_pending')>=0);
    }
  });
}
function resetCatalogFilters(){
  var s=document.getElementById('catalog-search'); if(s) s.value='';
  var v=document.getElementById('catalog-vendor'); if(v) v.value='all';
  var g=document.getElementById('catalog-stage'); if(g) g.value='all';
  var l=document.getElementById('catalog-latest'); if(l) l.checked=false;
  setCatalogStatusFilter('all', document.querySelector('[data-catalog-status-chip="all"]'));
}

function copyText(text, btn){
  function done(){ if(btn){ var old=btn.textContent; btn.textContent='已复制'; setTimeout(function(){btn.textContent=old},1200); } }
  if(navigator.clipboard && window.isSecureContext){ navigator.clipboard.writeText(text).then(done); return; }
  var ta=document.createElement('textarea'); ta.value=text; document.body.appendChild(ta); ta.select(); document.execCommand('copy'); document.body.removeChild(ta); done();
}
function filterTable(tableId, query){
  var advanced=document.getElementById(tableId);
  if(advanced && advanced.hasAttribute('data-filterable-table')){
    var input=document.getElementById(tableId+'-search'); if(input && typeof query !== 'undefined') input.value=query;
    applyTableFilters(tableId); return;
  }
  var wrap=document.getElementById(tableId+'-wrap'); if(!wrap) return;
  var rows=Array.from(wrap.querySelectorAll('tbody tr')); var q=String(query||'').toLowerCase().trim(); var visible=0;
  rows.forEach(function(row){ if(row.querySelector('.empty')){row.classList.toggle('is-hidden-by-filter', !!q); return;} var show=!q || row.textContent.toLowerCase().indexOf(q)>=0; row.classList.toggle('is-hidden-by-filter', !show); if(show) visible++; });
  var count=document.getElementById(tableId+'-count'); if(count) count.textContent=visible;
}
function cellFilterText(row, index){
  var cell=row.children[index]; if(!cell) return '';
  return String(cell.textContent||'').replace(/\s+/g,' ').trim();
}
function parseFacetSpec(table){
  var raw=table.getAttribute('data-filter-columns')||'';
  return raw.split('|').map(function(token){
    var parts=token.split(':'); var index=parseInt(parts.shift(),10);
    return isNaN(index) ? null : {index:index,label:parts.join(':')||('列 '+(index+1))};
  }).filter(Boolean);
}
function initFacetedTable(table){
  if(table.getAttribute('data-filters-ready')==='1') return;
  var id=table.id; if(!id) return;
  var holder=document.getElementById(id+'-facets'); if(!holder) return;
  holder.innerHTML='';
  parseFacetSpec(table).forEach(function(facet){
    var values=[];
    table.querySelectorAll('tbody tr').forEach(function(row){
      if(row.querySelector('.empty')) return;
      var text=cellFilterText(row, facet.index);
      if(text && values.indexOf(text)<0) values.push(text);
    });
    values.sort(function(a,b){return a.localeCompare(b,'zh-Hans-CN',{numeric:true,sensitivity:'base'});});
    if(!values.length) return;
    var select=document.createElement('select');
    select.id=id+'-facet-'+facet.index;
    select.setAttribute('data-column-index', String(facet.index));
    select.onchange=function(){applyTableFilters(id)};
    var all=document.createElement('option'); all.value=''; all.textContent=facet.label+'：全部'; select.appendChild(all);
    values.slice(0, 300).forEach(function(value){
      var option=document.createElement('option'); option.value=value; option.textContent=value.length>42?value.slice(0,39)+'...':value; option.title=value; select.appendChild(option);
    });
    holder.appendChild(select);
  });
  table.setAttribute('data-filters-ready','1');
  applyTableFilters(id);
}
function applyTableFilters(tableId){
  var table=document.getElementById(tableId); if(!table) return;
  if(table.getAttribute('data-filters-ready')!=='1') initFacetedTable(table);
  var q=((document.getElementById(tableId+'-search')||{}).value||'').toLowerCase().trim();
  var facetHolder=document.getElementById(tableId+'-facets');
  var facets=Array.from(facetHolder ? facetHolder.querySelectorAll('select') : []).map(function(select){
    return {index:parseInt(select.getAttribute('data-column-index'),10), value:select.value};
  }).filter(function(item){return item.value && !isNaN(item.index)});
  var visible=0,total=0;
  table.querySelectorAll('tbody tr').forEach(function(row){
    if(row.querySelector('.empty')){row.classList.toggle('is-hidden-by-filter', !!q || facets.length>0); return;}
    total++;
    var text=String(row.textContent||'').toLowerCase();
    var show=!q || text.indexOf(q)>=0;
    if(show){
      show=facets.every(function(facet){return cellFilterText(row, facet.index)===facet.value;});
    }
    row.classList.toggle('is-hidden-by-filter', !show);
    if(show) visible++;
  });
  var count=document.getElementById(tableId+'-count'); if(count) count.textContent=visible;
  var totalEl=document.getElementById(tableId+'-total'); if(totalEl) totalEl.textContent=total;
}
function resetTableFilters(tableId){
  var input=document.getElementById(tableId+'-search'); if(input) input.value='';
  var facetHolder=document.getElementById(tableId+'-facets');
  Array.from(facetHolder ? facetHolder.querySelectorAll('select') : []).forEach(function(select){select.value='';});
  applyTableFilters(tableId);
}
function initFacetedTables(){
  document.querySelectorAll('table[data-filterable-table]').forEach(initFacetedTable);
}
if(document.readyState==='loading') document.addEventListener('DOMContentLoaded', initFacetedTables); else initFacetedTables();
function filterComparisons(mode, btn){
  document.querySelectorAll('.filter-chip').forEach(function(x){x.classList.remove('active')}); if(btn) btn.classList.add('active');
  document.querySelectorAll('.timeline-card').forEach(function(card){ var show=mode==='all' || card.getAttribute('data-mode')===mode; card.style.display=show?'':'none'; });
}
function scrollTimeline(dir){
  var vp=document.querySelector('.timeline-viewport'); if(vp) vp.scrollBy({left:dir*520, behavior:'smooth'});
}
"""
