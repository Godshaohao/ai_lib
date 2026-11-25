"""Self-contained offline HTML report renderers for single-version CheckResult and multi-version Overall summaries."""
from html import escape


_OFFLINE_CSS = """
:root{--bg:#f7f8fa;--surface:#fff;--muted:#fafbfc;--border:#e3e7ee;--ink:#111827;--sub:#4b5563;--accent:#0d5659;--accent-soft:#edf6f6;--green:#136935;--green-soft:#ecfdf3;--amber:#944505;--amber-soft:#fffbeb;--red:#b42318;--red-soft:#fef3f2;--blue:#1d4ed8;--blue-soft:#eff6ff}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font-family:"IBM Plex Sans","Inter",-apple-system,BlinkMacSystemFont,"Segoe UI","Noto Sans CJK SC","PingFang SC","Microsoft YaHei",sans-serif;font-size:13.5px;line-height:1.55;padding:24px}
.wrap{max-width:1200px;margin:0 auto}
.head{display:flex;justify-content:space-between;align-items:flex-end;gap:16px;flex-wrap:wrap;padding-bottom:14px;border-bottom:1px solid var(--border);margin-bottom:18px}
.eyebrow{font-size:11.5px;font-weight:700;color:var(--sub);letter-spacing:.03em;margin-bottom:4px}
h1{margin:0;font-size:22px;line-height:1.25}
h2{margin:0;font-size:15px}
.sub{color:var(--sub);font-size:12.5px;margin:4px 0 0}
.mono{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:12.5px}
.num{font-variant-numeric:tabular-nums}
.kpis{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:0;background:var(--surface);border:1px solid var(--border);border-radius:10px;overflow:hidden;margin-bottom:16px}
.kpi{padding:14px 16px;border-right:1px solid var(--border)}
.kpi:last-child{border-right:0}
.kpi-lbl{font-size:12px;color:var(--sub);font-weight:600}
.kpi-val{font-size:22px;font-weight:700;margin:4px 0 2px}
.kpi-sub{font-size:12px;color:var(--sub)}
.card{background:var(--surface);border:1px solid var(--border);border-radius:10px;overflow:hidden;margin-bottom:16px}
.card-h{padding:12px 16px;background:var(--muted);border-bottom:1px solid var(--border);display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap}
.card-b{padding:14px 16px}
.tag{display:inline-flex;align-items:center;gap:5px;padding:2px 8px;border-radius:999px;font-size:12px;font-weight:600;border:1px solid transparent;white-space:nowrap}
.tag-new{background:var(--green-soft);color:var(--green);border-color:#b7ebc9}
.tag-partial{background:var(--amber-soft);color:var(--amber);border-color:#f8dfa0}
.tag-failed{background:var(--red-soft);color:var(--red);border-color:#fecdca}
.tag-updated{background:var(--blue-soft);color:var(--blue);border-color:#bfdbfe}
.tag-accent{background:var(--accent-soft);color:var(--accent);border-color:#b9d8d9}
.tag-inherited{background:#f1f3f6;color:var(--sub);border-color:var(--border)}
.chip{display:inline-block;padding:1px 7px;border-radius:5px;font-size:12px;background:#f8fafc;border:1px solid #dce3ec;color:#273449}
.cov-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(210px,1fr));gap:10px}
.cov-card{border:1px solid var(--border);border-radius:8px;padding:10px 12px;background:var(--muted)}
.cov-top{display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;font-size:12.5px}
.bar{height:6px;border-radius:99px;background:#e5e7eb;overflow:hidden}
.bar-fill{height:100%;background:var(--accent);border-radius:99px}
.bar-fill.fail{background:var(--red)}
.bar-fill.skip{background:#94a3b8}
table{width:100%;border-collapse:collapse;font-size:12.5px}
th,td{text-align:left;padding:9px 12px;border-bottom:1px solid var(--border);vertical-align:top}
th{background:var(--muted);color:var(--sub);font-weight:600;font-size:12px}
tr:last-child td{border-bottom:0}
.filter-bar{display:flex;gap:8px;align-items:center;flex-wrap:wrap;padding:10px 16px;border-bottom:1px solid var(--border);background:var(--muted)}
.filter-bar input,.filter-bar select{height:30px;padding:0 10px;border:1px solid #cbd5e1;border-radius:6px;font:inherit;font-size:12.5px;background:#fff}
.foot{font-size:12px;color:var(--sub);text-align:right;margin-top:16px}
@media(max-width:800px){.kpis{grid-template-columns:repeat(2,minmax(0,1fr))}}
@media print{body{background:#fff;padding:0}.filter-bar{display:none}}
""".strip()


def _tag(text: str, cls: str = 'tag-inherited') -> str:
    return f'<span class="tag {escape(cls)}">{escape(text)}</span>'


def _check_status_tag(status: str) -> str:
    s = (status or '').upper()
    if s == 'PASS':
        return _tag('通过 (PASS)', 'tag-new')
    if s == 'FAIL':
        return _tag('失败 (FAIL)', 'tag-failed')
    if s in ('NOT_EXECUTED', 'INCONCLUSIVE'):
        return _tag(s, 'tag-partial')
    return _tag(s or 'UNKNOWN', 'tag-inherited')


def render_check_html_report(data: dict) -> str:
    """Render a self-contained offline HTML report from `build_check_view()` data."""
    report = data['report']
    vendor = data['vendor']
    library = data['library']
    ip = data.get('business_ip')
    scope_label = f'{vendor} / {library}' + (f' :: {ip}' if ip else '')
    rev = report.get('revision') or ''
    base = report.get('baseline')
    title = f'质量检查报告 · {library}' + (f' ({ip})' if ip else '') + f' · {rev}'
    quality = data['quality']
    src_counts = data.get('source_counts') or {}
    parse_counts = data.get('parse_counts') or {}
    file_rows = data.get('file_rows') or []
    changed_src = src_counts.get('NEW', 0) + src_counts.get('UPDATED', 0) + src_counts.get('REMOVED', 0)
    summ = report.get('summary') or {}

    cov_cards = []
    for vc in data.get('view_coverage') or []:
        fill_cls = 'fail' if vc['failed'] > 0 else ('skip' if vc['is_skipped_policy'] else '')
        pct = vc['parsed_pct']
        note_bits = [f"已解析 {vc['parsed']}/{vc['total']}"]
        if vc['is_skipped_policy']:
            note_bits.append('按策略跳过')
        if vc['failed']:
            note_bits.append(f"失败 {vc['failed']}")
        if vc['diff_count']:
            note_bits.append(f"内容有变 {vc['diff_count']}")
        cov_cards.append(
            f'<div class="cov-card">'
            f'<div class="cov-top"><strong class="mono">{escape(vc["view"])}</strong><span class="num">{pct:.0f}%</span></div>'
            f'<div class="bar"><div class="bar-fill {fill_cls}" style="width:{min(100, max(0, pct))}%"></div></div>'
            f'<div class="sub num">{" · ".join(escape(x) for x in note_bits)}</div>'
            f'</div>'
        )

    rule_rows = []
    for c in data.get('checks') or []:
        c_res = str(c.get('result') or c.get('status') or 'INCONCLUSIVE')
        c_detail = str(c.get('detail') or c.get('message') or c.get('summary') or '')
        scope_files = ', '.join(str(x) for x in (c.get('scope_file_keys') or []))
        detail_html = escape(c_detail) + (f'<div class="sub mono">{escape(scope_files)}</div>' if scope_files else '')
        rule_rows.append(
            f'<tr>'
            f'<td class="mono"><strong>{escape(str(c.get("check_id") or ""))}</strong></td>'
            f'<td>{_check_status_tag(c_res)}</td>'
            f'<td>{detail_html or "—"}</td>'
            f'<td class="mono">{escape(", ".join(r["name"] for r in (c.get("resolved_refs") or [])) or "—")}</td>'
            f'</tr>'
        )

    file_trs = []
    for r in file_rows:
        src_map = {
            'NEW': ('新增', 'tag-new'),
            'UPDATED': ('来源更新', 'tag-updated'),
            'REMOVED': ('已移除', 'tag-failed'),
            'INHERITED': ('继承', 'tag-inherited'),
        }
        s_txt, s_cls = src_map.get(r['source_status'], ('当前成员', 'tag-inherited'))
        p_cls = 'tag-accent' if r['parse_status'] == 'PARSED' else ('tag-failed' if r['parse_status'] == 'FAILED' else 'tag-inherited')
        c_map = {
            'CURRENT_CONTENT_DIFF': ('内容有变', 'tag-partial'),
            'CURRENT_CONTENT_MATCH': ('内容一致', 'tag-new'),
            'PARTIAL_DIFF': ('部分差异', 'tag-partial'),
            'PARTIAL_MATCH': ('部分一致', 'tag-inherited'),
        }
        c_txt, c_cls = c_map.get(r['content_status'], ('未比对', 'tag-inherited'))
        ver_arrow = f'{r["baseline_version"]} → {r["target_version"] or "移除"}' if r['baseline_version'] else (r['target_version'] or '')
        hay = escape(f'{r["view"]} {r["path"]} {r["target_version"]} {r["baseline_version"]}'.lower())
        file_trs.append(
            f'<tr data-view="{escape(r["view"])}" data-src="{escape(r["source_status"])}" data-content="{escape(r["content_status"])}" data-q="{hay}">'
            f'<td><span class="chip">{escape(r["view"])}</span></td>'
            f'<td class="mono">{escape(r["path"])}</td>'
            f'<td>{_tag(s_txt, s_cls)}<div class="sub mono">{escape(ver_arrow)}</div></td>'
            f'<td>{_tag(r["parse_status"], p_cls)}<div class="sub">{escape(r.get("parse_note") or "")}</div></td>'
            f'<td>{_tag(c_txt, c_cls)}</td>'
            f'</tr>'
        )

    view_opts = ''.join(f'<option value="{escape(v)}">{escape(v)}</option>' for v in (data.get('views_present') or []))
    tooling = report.get('tooling') if isinstance(report.get('tooling'), dict) else {}
    skipped = tooling.get('skipped_views') or []
    policy_notes = [f'<strong>检查范围说明：</strong>{escape(str(report.get("note") or ""))}']
    if skipped:
        policy_notes.append(f'<strong>跳过解析视图：</strong><span class="mono">{escape(", ".join(skipped))}</span>')

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{escape(title)}</title>
<style>{_OFFLINE_CSS}</style>
</head>
<body>
<div class="wrap">
  <div class="head">
    <div>
      <div class="eyebrow">AI LIB 离线质量检查报告 · {escape(scope_label)}</div>
      <h1><span class="mono">{escape(rev)}</span> {escape(f'vs {base}' if base else '（无基线）')}</h1>
      <p class="sub num">执行时间 {escape(str(report.get('run_at') or '')[:19].replace('T', ' '))} UTC · 批次号 <span class="mono">{escape(str(report.get('run_id') or ''))}</span> · 来源文件 <span class="mono">{escape(data['check_name'])}</span></p>
    </div>
    <div>{_tag(quality['text'], quality['cls'])}</div>
  </div>

  <div class="kpis num">
    <div class="kpi"><div class="kpi-lbl">来源变动</div><div class="kpi-val">{changed_src} 项</div><div class="kpi-sub">新增 {src_counts.get('NEW', 0)} · 更新 {src_counts.get('UPDATED', 0)} · 移除 {src_counts.get('REMOVED', 0)}</div></div>
    <div class="kpi"><div class="kpi-lbl">文件解析覆盖</div><div class="kpi-val">{parse_counts.get('PARSED', 0)} / {len(file_rows)}</div><div class="kpi-sub">未检查 {parse_counts.get('NOT_CHECKED', 0)} · 失败 {parse_counts.get('FAILED', 0)}</div></div>
    <div class="kpi"><div class="kpi-lbl">确认内容差异</div><div class="kpi-val">{summ.get('files_with_confirmed_content_change', 0)} 文件</div><div class="kpi-sub">对象变化 {len(data.get('changes') or [])} 条</div></div>
    <div class="kpi"><div class="kpi-lbl">规则检查结论</div><div class="kpi-val">{summ.get('failed_checks', 0)} 失败 · {summ.get('inconclusive_checks', 0)} 无结论</div><div class="kpi-sub">共 {len(data.get('checks') or [])} 条规则结论</div></div>
  </div>

  <div class="card">
    <div class="card-h"><h2>View 解析覆盖与检查策略</h2></div>
    <div class="card-b">
      <div class="cov-grid">{''.join(cov_cards) or '<span class="sub">无文件记录</span>'}</div>
      <div class="sub" style="margin-top:12px">{'<br>'.join(policy_notes)}</div>
    </div>
  </div>

  <div class="card">
    <div class="card-h"><h2>规则检查结论</h2><span class="sub num">共 {len(rule_rows)} 条</span></div>
    <table>
      <thead><tr><th style="width:240px">规则标识</th><th style="width:140px">状态</th><th>结论说明</th><th style="width:220px">关联证据</th></tr></thead>
      <tbody>{''.join(rule_rows) or '<tr><td colspan="4" class="sub">暂无规则检查记录</td></tr>'}</tbody>
    </table>
  </div>

  <div class="card">
    <div class="card-h"><h2>文件变更与内容比对</h2><span id="f-cnt" class="sub num">共 {len(file_trs)} 个文件</span></div>
    <div class="filter-bar">
      <select id="f-view" onchange="filterFiles()"><option value="">全部 View</option>{view_opts}</select>
      <select id="f-mode" onchange="filterFiles()"><option value="all">全部文件</option><option value="changed">仅来源变动</option><option value="diff">仅内容有变</option></select>
      <input id="f-q" type="search" placeholder="搜索路径或版本…" oninput="filterFiles()">
    </div>
    <table>
      <thead><tr><th style="width:96px">View</th><th>相对路径</th><th style="width:180px">来源变动</th><th style="width:170px">解析状态</th><th style="width:130px">内容比对</th></tr></thead>
      <tbody id="f-body">{''.join(file_trs)}</tbody>
    </table>
  </div>

  <div class="foot">AI LIB 库质量工作台 · 自包含离线 HTML 报告（基于已归档 JSON 渲染，无外部依赖）</div>
</div>
<script>
function filterFiles(){{
  var v=document.getElementById('f-view').value,m=document.getElementById('f-mode').value,q=(document.getElementById('f-q').value||'').trim().toLowerCase(),vis=0;
  document.querySelectorAll('#f-body tr').forEach(function(tr){{
    var ok=true;
    if(v && tr.getAttribute('data-view')!==v) ok=false;
    var s=tr.getAttribute('data-src'),c=tr.getAttribute('data-content');
    if(m==='changed' && !(s==='NEW'||s==='UPDATED'||s==='REMOVED')) ok=false;
    if(m==='diff' && !(c==='CURRENT_CONTENT_DIFF'||c==='PARTIAL_DIFF')) ok=false;
    if(q && (tr.getAttribute('data-q')||'').indexOf(q)===-1) ok=false;
    tr.style.display=ok?'':'none';
    if(ok) vis++;
  }});
  document.getElementById('f-cnt').textContent='显示 '+vis+' / {len(file_trs)} 个文件';
}}
</script>
</body>
</html>"""


def render_overall_html_report(data: dict) -> str:
    """Render a self-contained offline HTML report from `build_overall_view()` data."""
    vendor = data['vendor']
    library = data['library']
    ip = data.get('business_ip')
    scope_label = f'{vendor} / {library}' + (f' :: {ip}' if ip else '')
    totals = data['totals']
    acc_rev = data.get('accepted_revision')

    trs = []
    for row in data.get('versions') or []:
        acc_badge = ' ' + _tag('当前已采纳', 'tag-new') if row['is_accepted'] else ''
        rules_summary = []
        for c in row.get('checks') or []:
            c_res = c.get('result') or c.get('status') or 'INCONCLUSIVE'
            rules_summary.append(f'{c.get("check_id")}: {c_res}')
        rules_html = '<br>'.join(escape(x) for x in rules_summary) if rules_summary else '<span class="sub">—</span>'
        base_label = f'基线 {row["baseline"]}' if row['baseline'] else '无基线'
        trs.append(
            f'<tr>'
            f'<td class="mono"><strong>{escape(row["revision"])}</strong>{acc_badge}<div class="sub">{escape(base_label)}</div></td>'
            f'<td>{_tag(row["quality"]["text"], row["quality"]["cls"])}<div class="sub mono">{escape(row["run_at"][:19].replace("T", " "))}</div></td>'
            f'<td class="num"><strong>{row["parsed_files"]} / {row["total_files"]}</strong> ({row["parsed_pct"]:.0f}%)<div class="sub">解析失败 {row["failed_files"]}</div></td>'
            f'<td class="num">内容有变 <strong>{row["diff_files"]}</strong> 文件<div class="sub">规则失败 {row["failed_checks"]} · 无结论 {row["inconclusive_checks"]}</div></td>'
            f'<td class="mono" style="font-size:12px">{rules_html}</td>'
            f'</tr>'
        )

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>多版本质量汇总 · {escape(scope_label)}</title>
<style>{_OFFLINE_CSS}</style>
</head>
<body>
<div class="wrap">
  <div class="head">
    <div>
      <div class="eyebrow">AI LIB 离线多版本质量汇总报告 · {escape(scope_label)}</div>
      <h1>{escape(library)}{escape(f' / {ip}' if ip else '')} · 跨版本演进矩阵</h1>
      <p class="sub">来源汇总文件 <span class="mono">{escape(data['overall_name'])}</span> · 人工采纳版本：{escape(acc_rev or '尚未人工采纳')}</p>
    </div>
    <div>{_tag(f'共 {totals["revisions"]} 个有效版本', 'tag-accent')}</div>
  </div>

  <div class="kpis num">
    <div class="kpi"><div class="kpi-lbl">覆盖有效版本</div><div class="kpi-val">{totals['revisions']} 版</div><div class="kpi-sub">已采纳：{escape(acc_rev or '无')}</div></div>
    <div class="kpi"><div class="kpi-lbl">已覆盖范围通过</div><div class="kpi-val">{totals['pass_count']} 版</div><div class="kpi-sub">部分覆盖 / 无结论 {totals['partial_count']} 版</div></div>
    <div class="kpi"><div class="kpi-lbl">存在质检失败</div><div class="kpi-val">{totals['fail_count']} 版</div><div class="kpi-sub">累计失败规则 {totals['failed_checks_total']} 项</div></div>
    <div class="kpi"><div class="kpi-lbl">累计内容差异文件</div><div class="kpi-val">{totals['content_diff_files_total']} 文件</div><div class="kpi-sub">按跨版本对比统计</div></div>
  </div>

  <div class="card">
    <div class="card-h"><h2>各有效版本检查汇总矩阵</h2><span class="sub num">按版本演进顺序</span></div>
    <table>
      <thead><tr><th style="width:180px">有效版本与基线</th><th style="width:200px">质量结论与时间</th><th style="width:150px">文件解析覆盖</th><th style="width:170px">差异与规则统计</th><th>规则明细</th></tr></thead>
      <tbody>{''.join(trs) or '<tr><td colspan="5" class="sub">暂无版本汇总记录</td></tr>'}</tbody>
    </table>
  </div>

  <div class="foot">AI LIB 库质量工作台 · 自包含离线 HTML 汇总报告（基于已归档 JSON 渲染，无外部依赖）</div>
</div>
</body>
</html>"""
