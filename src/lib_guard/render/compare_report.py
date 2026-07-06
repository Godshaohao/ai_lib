from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any, Mapping


def esc(value: Any) -> str:
    return html.escape(str(value if value is not None else ""))


def short(value: Any, head: int = 34, tail: int = 22) -> str:
    text = str(value or "-")
    return text if len(text) <= head + tail + 3 else f"{text[:head]}...{text[-tail:]}"


def target_label(target: Mapping[str, Any]) -> str:
    return str(target.get("label") or f"{target.get('type') or 'target'}:{target.get('id') or '-'}")


def badge(value: Any, label: Any | None = None) -> str:
    raw = str(value or "INFO").lower()
    cls = {
        "add": "pass",
        "keep": "neutral",
        "replace": "warn",
        "remove": "fail",
        "pass": "pass",
        "ok": "pass",
        "risk": "warn",
        "warning": "warn",
        "fail": "fail",
        "error": "fail",
    }.get(raw, "neutral")
    return f"<span class='badge {cls}'>{esc(label if label is not None else value)}</span>"


def metric(label: str, value: Any, hint: str, tone: str = "neutral") -> str:
    return (
        f"<div class='metric {esc(tone)}'>"
        f"<div class='metric-label'>{esc(label)}</div>"
        f"<div class='metric-value'>{esc(value)}</div>"
        f"<div class='metric-hint'>{esc(hint)}</div>"
        "</div>"
    )


def panel(title: str, note: str, body: str, *, panel_id: str = "") -> str:
    pid = f" id='{esc(panel_id)}'" if panel_id else ""
    return (
        f"<section class='panel'{pid}>"
        f"<div class='panel-head'><div><h2>{esc(title)}</h2><p>{esc(note)}</p></div></div>"
        f"<div class='panel-body'>{body}</div>"
        "</section>"
    )


def target_card(title: str, target: Mapping[str, Any]) -> str:
    manifest = target.get("manifest") or target.get("path") or target.get("html") or ""
    details = [
        ("类型", target.get("type") or "-"),
        ("标识", target.get("id") or "-"),
        ("基线", target.get("base_full_version") or "-"),
        ("吸收更新", ", ".join(str(x) for x in target.get("accepted_updates", []) or []) or "-"),
    ]
    rows = "".join(f"<span><b>{esc(k)}</b><em title='{esc(v)}'>{esc(short(v, 26, 14))}</em></span>" for k, v in details)
    return (
        "<article class='target-card'>"
        f"<div class='target-title'>{esc(title)}</div>"
        f"<h3 title='{esc(target_label(target))}'>{esc(short(target_label(target)))}</h3>"
        f"<div class='target-grid'>{rows}</div>"
        f"<code class='path-line' title='{esc(manifest)}'>{esc(short(manifest, 42, 30))}</code>"
        "</article>"
    )


def file_type_summary(summary: Mapping[str, Any]) -> str:
    by_type = summary.get("by_type", {}) or {}
    if not by_type:
        return "<div class='empty'>没有文件类型统计。</div>"
    rows = []
    for file_type, actions in sorted(by_type.items()):
        action_tags = "".join(badge(action, f"{action}:{count}") for action, count in sorted((actions or {}).items()))
        rows.append(f"<tr><td><code>{esc(file_type)}</code></td><td>{action_tags}</td></tr>")
    return table(["文件类型", "动作统计"], rows, empty="没有文件类型统计。")


def source_transitions(summary: Mapping[str, Any]) -> str:
    data = summary.get("source_transitions", {}) or {}
    if not data:
        return "<div class='empty'>没有来源迁移。</div>"
    rows = []
    for idx, (transition, count) in enumerate(list(data.items())[:40], 1):
        rows.append(
            "<tr>"
            f"<td class='num'>{idx}</td>"
            f"<td><code class='long-token' title='{esc(transition)}'>{esc(short(transition, 42, 24))}</code></td>"
            f"<td class='num'>{esc(count)}</td>"
            "</tr>"
        )
    return table(["#", "来源迁移", "文件数"], rows, empty="没有来源迁移。")


def risk_panel(manifest: Mapping[str, Any]) -> str:
    risks = manifest.get("risk_flags", []) or []
    if not risks:
        return "<div class='notice pass'><b>未发现文件映射级风险。</b><span>当前报告做文件映射比较；内容级 deep diff 需要进入下方命令区。</span></div>"
    readable_messages = {
        "REMOVED_FILES": "对比目标缺少基准目标中存在的文件。",
        "REPLACED_FILES": "存在来源、哈希或大小变化的文件。",
        "HASH_INCOMPLETE": "部分替换文件缺少哈希，当前以来源/大小兜底判断。",
    }
    readable_labels = {
        "REMOVED_FILES": "文件删除",
        "REPLACED_FILES": "文件替换",
        "HASH_INCOMPLETE": "Hash 不完整",
    }
    rows = []
    for risk in risks:
        risk_type = str(risk.get("type") or "RISK")
        message = readable_messages.get(risk_type, str(risk.get("message") or ""))
        rows.append(
            "<tr>"
            f"<td><span title='{esc(risk_type)}'>{badge('risk', readable_labels.get(risk_type, risk_type))}</span></td>"
            f"<td class='num'>{esc(risk.get('count') or '-')}</td>"
            f"<td>{esc(message)}</td>"
            "</tr>"
        )
    return "<div class='notice warn'><b>需要人工确认。</b><span>这些风险通常表示目标选择或源文件变化需要复核。</span></div>" + table(["风险", "数量", "说明"], rows)


def command_chip(command: Any, idx: int) -> str:
    cmd = str(command or "").strip()
    if not cmd:
        return ""
    payload = json.dumps(cmd, ensure_ascii=False)
    return (
        "<div class='command-row'>"
        f"<span class='num'>{idx}</span>"
        f"<code title='{esc(cmd)}'>{esc(cmd)}</code>"
        f"<button type='button' onclick='copyText({payload}, this)' aria-label='复制命令'>复制</button>"
        "</div>"
    )


def commands_panel(manifest: Mapping[str, Any]) -> str:
    commands = [str(cmd) for cmd in manifest.get("deep_diff_commands", []) or [] if str(cmd).strip()]
    if not commands:
        return panel(
            "重点文件确认项",
            "只记录可定位两端来源的重点文件，不在页面展开脚本命令。",
            "<div class='empty'>当前没有重点文件确认项。</div>",
            panel_id="commands",
        )
    body = (
        "<div class='notice warn'><b>重点文件确认项</b>"
        f"<span>检测到 {esc(len(commands))} 个历史 deep_diff 候选；页面不再展开脚本命令，请回到版本详情页查看证据入口。</span></div>"
    )
    return panel("重点文件确认项", "保留候选数量，不展示可复制脚本命令。", body, panel_id="commands")


def changed_table(manifest: Mapping[str, Any]) -> str:
    rows = []
    changed = manifest.get("changed_files", []) or []
    action_labels = {"add": "新增", "remove": "删除", "replace": "替换", "keep": "保持"}
    for idx, row in enumerate(changed, 1):
        rel = row.get("relpath") or "-"
        action = str(row.get("action") or "")
        search = " ".join(
            str(row.get(k) or "")
            for k in ["relpath", "file_type", "old_source_version", "new_source_version", "old_source_path", "new_source_path", "action"]
        ).lower()
        rows.append(
            f"<tr id='file-{idx}' data-search='{esc(search)}'>"
            f"<td class='num'><a href='#file-{idx}'>{idx}</a></td>"
            f"<td>{badge(action, action_labels.get(action, action))}</td>"
            f"<td><code class='relpath' title='{esc(rel)}'>{esc(rel)}</code></td>"
            f"<td>{badge(row.get('file_type') or 'other')}</td>"
            f"<td><code class='long-token' title='{esc(row.get('old_source_version'))}'>{esc(short(row.get('old_source_version')))}</code></td>"
            f"<td><code class='long-token' title='{esc(row.get('new_source_version'))}'>{esc(short(row.get('new_source_version')))}</code></td>"
            f"<td><code class='path-line' title='{esc(row.get('old_source_path'))}'>{esc(short(row.get('old_source_path'), 26, 18))}</code></td>"
            f"<td><code class='path-line' title='{esc(row.get('new_source_path'))}'>{esc(short(row.get('new_source_path'), 26, 18))}</code></td>"
            "</tr>"
        )
    tools = (
        "<div class='table-tools'>"
        "<label><span>筛选</span><input id='changed-filter' type='search' placeholder='路径 / 来源版本 / 类型 / 动作' oninput=\"filterRows('changed-table', this.value)\"></label>"
        f"<div><b id='changed-count'>{len(rows)}</b><span> / {len(rows)} 个变化文件</span></div>"
        "</div>"
    )
    return tools + table(
        ["#", "动作", "文件", "类型", "基准来源", "对比来源", "基准路径", "对比路径"],
        rows,
        table_id="changed-table",
        empty="没有变化文件。",
        tall=True,
    )


def table(headers: list[str], rows: list[str], *, table_id: str = "", empty: str = "暂无数据", tall: bool = False) -> str:
    tid = f" id='{esc(table_id)}'" if table_id else ""
    cls = "table-wrap tall" if tall else "table-wrap"
    head = "".join(f"<th>{esc(h)}</th>" for h in headers)
    body = "".join(rows) if rows else f"<tr><td colspan='{len(headers)}' class='empty-cell'>{esc(empty)}</td></tr>"
    return f"<div class='{cls}'><table{tid}><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>"


def render_compare_report(manifest: Mapping[str, Any]) -> str:
    summary = manifest.get("summary", {}) or {}
    actions = summary.get("actions", {}) or {}
    risk_count = int(summary.get("risk_count", len(manifest.get("risk_flags", []) or [])) or 0)
    changed_count = int(summary.get("changed_files", len(manifest.get("changed_files", []) or [])) or 0)
    decision_key = "RISK" if risk_count else ("REVIEW" if changed_count else "PASS")
    decision_label = {"RISK": "需复核", "REVIEW": "有变化", "PASS": "无变化"}[decision_key]
    metrics = "".join(
        [
            metric("变化文件", changed_count, "新增 / 删除 / 替换", "warn" if changed_count else "pass"),
            metric("新增", actions.get("add", 0), "仅在对比目标中出现", "pass"),
            metric("删除", actions.get("remove", 0), "对比目标缺失", "fail" if actions.get("remove") else "neutral"),
            metric("替换", actions.get("replace", 0), "来源、哈希或大小变化", "warn" if actions.get("replace") else "neutral"),
            metric("保持", actions.get("keep", 0), "文件映射未变化", "neutral"),
        ]
    )
    json_payload = html.escape(json.dumps(manifest, ensure_ascii=False))
    nav = (
        "<nav class='page-nav'>"
        "<a href='#overview'>总览</a><a href='#risk'>风险</a><a href='#changed'>变化文件</a><a href='#commands'>文件深度对比建议</a>"
        "</nav>"
    )
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>对比审查报告 / {esc(manifest.get('compare_id'))}</title>
<style>
:root{{--bg:#f6f8fb;--panel:#fff;--text:#172033;--muted:#667085;--line:#d9e0ea;--line-soft:#eef2f6;--blue:#1d4ed8;--green:#087443;--amber:#a15c07;--red:#b42318;--mono:"Cascadia Mono",Consolas,monospace}}
*{{box-sizing:border-box}}html{{scroll-behavior:smooth}}body{{margin:0;background:var(--bg);color:var(--text);font-family:"Segoe UI",Arial,sans-serif;font-size:14px;line-height:1.5;letter-spacing:0;overflow-x:hidden}}
a{{color:var(--blue);text-decoration:none}}a:hover{{text-decoration:underline}}.app{{display:grid;grid-template-columns:240px minmax(0,1fr);min-height:100vh}}
.side{{position:sticky;top:0;height:100vh;max-width:100vw;min-width:0;border-right:1px solid var(--line);background:#fff;padding:18px;display:flex;flex-direction:column;gap:18px;overflow-x:hidden}}
.brand{{display:flex;gap:10px;align-items:center}}.logo{{width:34px;height:34px;border-radius:8px;background:#172033;color:#fff;display:grid;place-items:center;font-weight:800}}.brand b{{display:block}}.brand span,.side-note,.muted{{color:var(--muted)}}.side-note{{max-width:100%;overflow-wrap:anywhere;word-break:break-all}}.page-nav{{display:flex;flex-direction:column;gap:6px;max-width:100%;min-width:0}}.page-nav a{{min-height:40px;display:flex;align-items:center;padding:8px 10px;border-radius:8px;color:#344054}}.page-nav a:hover{{background:#f2f4f7;text-decoration:none}}
.main{{min-width:0;max-width:100vw;padding:22px 24px 34px;overflow-x:hidden}}.title-band{{background:#fff;border:1px solid var(--line);border-radius:8px;padding:18px;display:flex;justify-content:space-between;gap:16px;align-items:flex-start}}.kicker{{font-size:12px;font-weight:800;color:var(--blue);text-transform:uppercase}}h1{{font-size:24px;line-height:1.25;margin:4px 0 6px;overflow-wrap:anywhere}}h2{{font-size:17px;margin:0}}h3{{font-size:15px;margin:5px 0 10px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}p{{margin:0;color:var(--muted)}}
.decision{{display:flex;gap:8px;align-items:center;white-space:nowrap;flex-wrap:wrap}}.meta{{display:flex;gap:8px;flex-wrap:wrap;margin-top:10px}}.meta span{{min-width:0;max-width:100%;border:1px solid var(--line);border-radius:8px;background:#f8fafc;padding:5px 8px;color:#475467;overflow-wrap:anywhere}}.grid-targets{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px;margin:14px 0}}.metric-grid{{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:10px;margin:14px 0}}
.metric,.target-card,.panel{{background:var(--panel);border:1px solid var(--line);border-radius:8px}}.metric{{padding:13px;min-width:0}}.metric-label{{font-size:12px;color:var(--muted)}}.metric-value{{font-size:26px;line-height:1.1;font-weight:850;margin-top:5px}}.metric-hint{{font-size:12px;color:var(--muted);margin-top:4px}}.metric.pass{{border-color:#b7e4c7}}.metric.warn{{border-color:#f6c76f}}.metric.fail{{border-color:#f7b4ad}}
.target-card{{padding:14px;min-width:0}}.target-title{{font-size:12px;color:var(--muted);font-weight:700}}.target-grid{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:6px;margin:8px 0}}.target-grid span{{min-width:0;border:1px solid var(--line-soft);border-radius:8px;background:#f8fafc;padding:6px 7px}}.target-grid b{{display:block;color:#667085;font-size:11px}}.target-grid em{{display:block;font-style:normal;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
.panel{{margin-top:14px;overflow:hidden;min-width:0}}.panel-head{{display:flex;justify-content:space-between;gap:12px;padding:14px 16px;border-bottom:1px solid var(--line-soft);background:#fbfcfe}}.panel-body{{padding:14px 16px;min-width:0}}.two-col{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}}
.badge{{display:inline-flex;align-items:center;min-height:24px;border-radius:999px;padding:3px 8px;font-size:12px;font-weight:750;background:#eef2ff;color:#344054;white-space:nowrap}}.badge.pass{{background:#dcfce7;color:#166534}}.badge.warn{{background:#fef3c7;color:#92400e}}.badge.fail{{background:#fee2e2;color:#991b1b}}.badge.neutral{{background:#f2f4f7;color:#344054}}
.notice{{border:1px solid var(--line);border-radius:8px;padding:12px;display:flex;gap:8px;flex-wrap:wrap}}.notice.pass{{background:#f0fdf4;border-color:#bbf7d0;color:#166534}}.notice.warn{{background:#fff7ed;border-color:#fed7aa;color:#9a3412}}.empty{{border:1px dashed var(--line);border-radius:8px;padding:14px;color:var(--muted);background:#f8fafc}}
.table-tools{{display:flex;justify-content:space-between;gap:12px;align-items:end;margin-bottom:10px}}.table-tools label{{display:grid;gap:4px;min-width:min(420px,100%);font-size:12px;color:var(--muted)}}input{{min-height:44px;border:1px solid var(--line);border-radius:8px;padding:10px 12px;font:inherit;background:#fff;color:var(--text)}}.table-wrap{{max-width:100%;overflow:auto;border:1px solid var(--line);border-radius:8px;background:#fff}}.table-wrap.tall{{max-height:560px}}table{{width:100%;border-collapse:separate;border-spacing:0;min-width:0}}.table-wrap.tall table{{min-width:980px}}th,td{{padding:9px 10px;border-bottom:1px solid var(--line-soft);text-align:left;vertical-align:top}}th{{position:sticky;top:0;z-index:2;background:#f8fafc;color:#475467;font-size:12px;font-weight:800;letter-spacing:0}}tbody tr:target{{outline:2px solid var(--blue);outline-offset:-2px;background:#eff6ff}}.empty-cell{{color:var(--muted);text-align:center}}
code{{font-family:var(--mono);font-size:12px}}.relpath{{display:block;min-width:220px;max-width:520px;white-space:normal;overflow-wrap:anywhere}}.path-line,.long-token{{display:inline-block;max-width:100%;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;vertical-align:bottom}}.num{{font-variant-numeric:tabular-nums;text-align:right;color:#475467}}
.command-list{{display:grid;gap:8px}}.command-row{{display:grid;grid-template-columns:34px minmax(0,1fr) 64px;gap:8px;align-items:center;min-width:0;border:1px solid var(--line);border-radius:8px;background:#101828;color:#e5e7eb;padding:8px}}.command-row code{{min-width:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;color:#e5e7eb}}.command-row button{{min-height:34px;border:0;border-radius:7px;background:#e5e7eb;color:#101828;font-weight:750;cursor:pointer}}.command-row button:focus-visible,input:focus-visible,a:focus-visible{{outline:3px solid #93c5fd;outline-offset:2px}}
@media(max-width:1100px){{.app{{grid-template-columns:minmax(0,1fr);max-width:100vw;overflow-x:hidden}}.side{{position:static;height:auto;width:100%;border-right:0;border-bottom:1px solid var(--line)}}.page-nav{{flex-direction:row;flex-wrap:wrap}}.metric-grid{{grid-template-columns:repeat(2,minmax(0,1fr))}}.grid-targets,.two-col{{grid-template-columns:1fr}}}}
@media(max-width:620px){{.main{{padding:14px;width:100%;max-width:100vw}}.title-band{{flex-direction:column}}.metric-grid{{grid-template-columns:1fr}}.table-tools{{align-items:stretch;flex-direction:column}}.target-grid{{grid-template-columns:1fr}}.table-wrap.tall table{{min-width:860px}}}}
</style>
</head>
<body>
<div class="app">
  <aside class="side">
    <div class="brand"><div class="logo">LG</div><div><b>lib_guard</b><span>对比审查</span></div></div>
    {nav}
    <div class="side-note">文件映射级比较。大规模变化先确认基准/对比目标。</div>
  </aside>
  <main class="main">
    <header class="title-band" id="overview">
      <div>
        <div class="kicker">对比审查报告</div>
        <h1>{esc(manifest.get('compare_id') or '-')}</h1>
        <p>{esc(manifest.get('mode') or 'manual_compare')} / {esc(manifest.get('library_id') or '-')}</p>
        <div class="meta">
          <span>检查对象: {esc(manifest.get('owner_target') or '-')}</span>
          <span>生成时间: {esc(manifest.get('created_at') or '-')}</span>
          <span>Schema: {esc(manifest.get('schema_version') or '-')}</span>
        </div>
      </div>
      <div class="decision">{badge(decision_key, decision_label)}{badge('risk' if risk_count else 'ok', f"风险 {risk_count}")}</div>
    </header>
    <section class="grid-targets">{target_card('基准目标', manifest.get('old_target', {}) or {})}{target_card('对比目标', manifest.get('new_target', {}) or {})}</section>
    <section class="metric-grid">{metrics}</section>
    <section class="two-col">
      {panel('文件类型摘要', '按类型聚合新增、删除、替换和保持。', file_type_summary(summary))}
      {panel('来源迁移', '按来源版本迁移聚合，帮助定位补丁来源。', source_transitions(summary))}
    </section>
    {panel('风险复核', '风险只来自文件映射层；内容语义风险需要进入语义解析或内容级 diff。', risk_panel(manifest), panel_id='risk')}
    {panel('变化文件', '支持按路径、类型、来源版本和动作过滤；点击编号可定位到单行。', changed_table(manifest), panel_id='changed')}
    {commands_panel(manifest)}
  </main>
</div>
<script id="compare-json" type="application/json">{json_payload}</script>
<script>
function filterRows(id, q) {{
  q = (q || '').toLowerCase();
  var shown = 0;
  document.querySelectorAll('#' + id + ' tbody tr').forEach(function(row) {{
    var text = row.getAttribute('data-search') || row.textContent.toLowerCase();
    var visible = text.indexOf(q) >= 0;
    row.style.display = visible ? '' : 'none';
    if (visible) shown += 1;
  }});
  var counter = document.getElementById('changed-count');
  if (counter) counter.textContent = shown;
}}
function copyText(text, btn) {{
  navigator.clipboard.writeText(text).then(function() {{
    var old = btn.textContent;
    btn.textContent = '已复制';
    setTimeout(function() {{ btn.textContent = old; }}, 900);
  }});
}}
</script>
</body>
</html>"""


def write_compare_report(manifest: Mapping[str, Any], out_html: str | Path) -> Path:
    out = Path(out_html)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_compare_report(manifest), encoding="utf-8")
    return out
