"""Render a self-contained, read-only index of per-IP review results."""

from __future__ import annotations

from html import escape
from typing import Any


CHECKS = (
    ("formal_nl", "正式目录盘点"),
    ("macro_index", "Macro / View 索引"),
    ("lef_review", "LEF 双文件核查"),
    ("lef_liberty_check", "LEF–Liberty 接口核查"),
)

ATTEMPT_LABELS = {
    "COMPLETE": "任务已结束",
    "FAILED": "执行失败",
    "INCOMPLETE": "结果不完整",
    "NOT_RUN": "尚未运行",
    "PENDING": "排队中",
    "QUEUED": "排队中",
    "RUNNING": "运行中",
    "INTERRUPTED": "已中断",
}

QUALITY_LABELS = {
    "MISMATCH": "发现已确认不一致",
    "UNVERIFIED": "存在待核实项",
    "CHANGED": "发现已确认变化",
    "NO_FINDINGS": "本次范围未发现问题",
    "NO_REPORT": "尚无完整报告",
    "SUMMARY_INCOMPLETE": "质量汇总字段不完整",
}


def _count(summary: dict[str, Any], kind: str) -> int | None:
    counts = summary.get("counts") or {}
    item = counts.get(kind)
    if isinstance(item, dict) and "affected_objects" in item:
        try:
            return max(0, int(item["affected_objects"]))
        except (TypeError, ValueError):
            return None
    fallback = {"MISMATCH": "confirmed_mismatches", "CHANGED": "confirmed_changes",
                "UNVERIFIED": "unverified"}.get(kind)
    if fallback and fallback in summary:
        try:
            return max(0, int(summary[fallback]))
        except (TypeError, ValueError):
            return None
    return None


def _quality(summary: dict[str, Any], has_report: bool) -> tuple[str, str, dict[str, int | None]]:
    if not has_report:
        return "NO_REPORT", QUALITY_LABELS["NO_REPORT"], {kind: None for kind in ("CHANGED", "MISMATCH", "UNVERIFIED")}
    counts = {kind: _count(summary, kind) for kind in ("CHANGED", "MISMATCH", "UNVERIFIED")}
    recorded = str((summary.get("quality_assessment") or {}).get("status") or "")
    if counts["MISMATCH"] is not None and counts["MISMATCH"] > 0:
        return "MISMATCH", QUALITY_LABELS["MISMATCH"], counts
    if recorded == "ISSUES_FOUND":
        if counts["MISMATCH"] == 0:
            counts["MISMATCH"] = None
        return "MISMATCH", QUALITY_LABELS["MISMATCH"], counts
    if counts["UNVERIFIED"] is not None and counts["UNVERIFIED"] > 0:
        return "UNVERIFIED", QUALITY_LABELS["UNVERIFIED"], counts
    if recorded == "REVIEW_REQUIRED":
        return "UNVERIFIED", QUALITY_LABELS["UNVERIFIED"], counts
    if counts["CHANGED"] is not None and counts["CHANGED"] > 0:
        return "CHANGED", QUALITY_LABELS["CHANGED"], counts
    if recorded == "CHANGES_FOUND":
        return "CHANGED", QUALITY_LABELS["CHANGED"], counts
    if all(value == 0 for value in counts.values()):
        return "NO_FINDINGS", QUALITY_LABELS["NO_FINDINGS"], counts
    if recorded == "NO_FINDINGS_WITHIN_SCOPE":
        return "NO_FINDINGS", QUALITY_LABELS["NO_FINDINGS"], counts
    return "SUMMARY_INCOMPLETE", QUALITY_LABELS["SUMMARY_INCOMPLETE"], counts


def _check_coverage(last_complete: dict[str, Any]) -> tuple[int, str, list[tuple[str, str, str]]]:
    requested = set(last_complete.get("requested_checks") or [])
    results = last_complete.get("checks") or {}
    completed = sum(results.get(name, {}).get("execution_status") == "COMPLETE" for name in requested)
    chips = []
    for name, label in CHECKS:
        status = (results.get(name) or {}).get("execution_status") or "NOT_RUN"
        if name not in requested:
            short, css_status = "未选", "not-selected"
        elif status == "COMPLETE":
            short, css_status = "完成", "complete"
        elif status == "FAILED":
            short, css_status = "失败", "failed"
        else:
            short, css_status = "不完整", "incomplete"
        chips.append((name, label, f'<span class="check-chip {css_status}" title="{escape(label)}：{short}">{escape(label)}：{short}</span>'))
    return completed, f"{len(requested)} / {len(CHECKS)} 项", chips


def render_overview(reviews: list[dict[str, Any]], *, simulation: bool = False) -> str:
    """Render rows normalized as {ip, last_attempt, last_complete}.

    Only last_complete contributes findings, coverage, scope and workbook links.
    last_attempt contributes execution status and time only.
    """
    rows: list[str] = []
    metrics = {"complete": 0, "mismatch": 0, "unverified": 0}
    for item in reviews:
        ip = item.get("ip") or {}
        attempt = item.get("last_attempt") or {}
        complete = item.get("last_complete") or {}
        summary = complete.get("summary") or {}
        has_complete = bool(complete.get("id"))
        quality, quality_label, counts = _quality(summary, has_complete)
        has_mismatch = ((counts["MISMATCH"] is not None and counts["MISMATCH"] > 0)
                        or (counts["MISMATCH"] is None and quality == "MISMATCH"))
        has_unverified = ((counts["UNVERIFIED"] is not None and counts["UNVERIFIED"] > 0)
                          or (counts["UNVERIFIED"] is None and quality == "UNVERIFIED"))
        has_changed = ((counts["CHANGED"] is not None and counts["CHANGED"] > 0)
                       or (counts["CHANGED"] is None and quality == "CHANGED"))
        metrics["complete"] += int(has_complete)
        metrics["mismatch"] += int(has_mismatch)
        metrics["unverified"] += int(has_unverified)
        completed, coverage_text, coverage_chips = _check_coverage(complete) if has_complete else (0, "0 / 4 项", [
            (name, label, f'<span class="check-chip not-selected" title="{escape(label)}：无完整报告">{escape(label)}：—</span>')
            for name, label in CHECKS
        ])

        identity = str(ip.get("name") or ip.get("id") or ip.get("library_id") or "未命名 IP")
        vendor = str(ip.get("vendor") or "未分组")
        group = str(ip.get("group") or "")
        library_id = str(ip.get("library_id") or ip.get("id") or "")
        attempt_status = str(attempt.get("status") or "NOT_RUN")
        attempt_label = ATTEMPT_LABELS.get(attempt_status, attempt_status)
        execution_status = str(attempt.get("execution_status") or "")
        execution_label = {"COMPLETE": "检查执行完整", "FAILED": "检查执行有失败",
                           "INCOMPLETE": "检查结果不完整"}.get(execution_status, "")
        attempt_time = str(attempt.get("time") or "时间未记录")
        attempt_id = str(attempt.get("id") or "")
        requested_attempt = "、".join(str(name) for name in attempt.get("checks") or [])
        execution_markup = f"<small>{escape(execution_label)}</small>" if execution_label else ""
        attempt_markup = (f'<span class="status-badge status-{escape(attempt_status.lower())}">{escape(attempt_label)}</span>'
                          f'{execution_markup}'
                          f'<small>{escape(attempt_time)}</small>'
                          f'<small>{escape(attempt_id)}</small>'
                          f'<small>本次选择：{escape(requested_attempt or "未记录")}</small>')

        complete_id = str(complete.get("id") or "")
        complete_time = str(complete.get("time") or "")
        scope_bits = []
        context = complete.get("context") or {}
        raw_versions = context.get("target_raw_versions") or []
        if raw_versions:
            scope_bits.append(f"RAW 输入：{len(raw_versions)} 个版本")
        elif context.get("raw_version"):
            scope_bits.append("RAW 输入：1 个版本")
        if context.get("formal_stage"):
            scope_bits.append("正式阶段：" + str(context["formal_stage"]))
        scope = "；".join(scope_bits) or "输入范围见展开详情"
        paths = complete.get("input_paths") or []
        raw_version_labels = [
            str(value.get("id") or value.get("version") or "") if isinstance(value, dict) else str(value)
            for value in raw_versions
        ]
        if not raw_version_labels and context.get("raw_version"):
            raw_version_labels = [str(context["raw_version"])]
        detail_parts = []
        if raw_version_labels:
            detail_parts.append("<p><strong>RAW 版本：</strong>" +
                                "、".join(escape(value) for value in raw_version_labels) + "</p>")
        if paths:
            detail_parts.append("<ul>" + "".join(
                f"<li><code>{escape(str(path))}</code></li>" for path in paths
            ) + "</ul>")
        detail_parts.append(f"<small>Review ID：{escape(complete_id or '未记录')}</small>")
        revision = complete.get("source_revision") or {}
        revision_label = str(revision.get("commit") or "未记录")
        if revision.get("working_tree_dirty") is True:
            revision_label += "（生成时工作区有未提交修改）"
        elif revision.get("working_tree_dirty") is None:
            revision_label += "（工作区状态未知）"
        detail_parts.append(f"<small>源提交：{escape(revision_label)}</small>")
        input_scope = complete.get("input_scope") or {}
        if input_scope:
            scope_checks = "、".join(str(item.get("name") or "") for item in input_scope.get("checks") or []) or "无"
            scope_versions = "、".join(str(value) for value in input_scope.get("target_raw_versions") or []) or "未记录"
            scope_stage = str(input_scope.get("formal_stage") or "未指定")
            detail_parts.append(
                f"<p><strong>输入范围：</strong>检查 {escape(scope_checks)}；RAW {escape(scope_versions)}；"
                f"正式阶段 {escape(scope_stage)}；来源 {int(input_scope.get('source_count') or 0)} 项。</p>")
        path_detail = '<details><summary>查看完整范围、路径与 Review 标识</summary>' + "".join(detail_parts) + "</details>"
        complete_markup = (f'<strong>{escape(complete_time or "时间未记录")}</strong>'
                           f'<small>{escape(scope)}</small>{path_detail}' if has_complete else "尚无完整检查报告")

        def show_count(value: int | None) -> str:
            return str(value) if value is not None else "未确认"

        primary_markup = ""
        primary_findings = summary.get("primary_findings") or []
        if primary_findings:
            primary_text = "；".join(
                f"{str(item.get('category') or '发现')}：{str(item.get('label') or '—')} ({int(item.get('count') or 0)})"
                for item in primary_findings[:2])
            primary_markup = f'<small class="primary-finding">主要发现：{escape(primary_text)}</small>'
        findings_markup = (
            f'<span class="finding changed">变化 {show_count(counts["CHANGED"])}</span>'
            f'<span class="finding mismatch">不一致 {show_count(counts["MISMATCH"])}</span>'
            f'<span class="finding unverified">待核实 {show_count(counts["UNVERIFIED"])}</span>'
            f'{primary_markup}'
        )
        quality_markup = (f'<span class="quality-badge quality-{quality.lower()}">{escape(quality_label)}</span>'
                          '<small>仅代表该完整报告的已选范围，不是发布放行结论</small>')
        workbook = str(complete.get("xlsx_href") or "")
        workbook_markup = (f'<a class="excel-link" href="{escape(workbook, quote=True)}">打开 Excel</a>'
                           if workbook and has_complete else '<span class="muted">暂无可用 Excel</span>')
        selected_ids = set(complete.get("requested_checks") or [])
        search = " ".join((identity, vendor, group, library_id)).casefold()
        row = (
            f'<tr data-ip-row data-search="{escape(search, quote=True)}" '
            f'data-attempt="{escape(attempt_status, quote=True)}" data-quality="{quality}" '
            f'data-has-mismatch="{str(has_mismatch).lower()}" '
            f'data-has-unverified="{str(has_unverified).lower()}" '
            f'data-has-changed="{str(has_changed).lower()}" '
            f'data-checks="{escape(",".join(sorted(selected_ids)), quote=True)}">'
            f'<td><strong>{escape(identity)}</strong><small>{escape(vendor)}'
            f'{(" / " + escape(group)) if group else ""} · {escape(library_id)}</small></td>'
            f'<td>{attempt_markup}</td>'
            f'<td><strong>{completed} / 4 完成</strong><small>{coverage_text} 已选择</small>'
            f'<div class="coverage">{"".join(chip for _, _, chip in coverage_chips)}</div></td>'
            f'<td>{complete_markup}</td>'
            f'<td><div class="findings">{findings_markup}</div></td>'
            f'<td>{quality_markup}</td>'
            f'<td>{workbook_markup}</td>'
            '</tr>'
        )
        rows.append((has_mismatch, attempt_status, quality, row))

    priority = {"MISMATCH": 0, "FAILED": 1, "UNVERIFIED": 2, "CHANGED": 3,
                "NO_FINDINGS": 4, "NO_REPORT": 5, "SUMMARY_INCOMPLETE": 2}
    def sort_key(entry: tuple[bool, str, str, str]) -> tuple[int, int]:
        mismatch, attempt_status, quality, _ = entry
        if mismatch:
            return 0, 0
        if attempt_status == "FAILED":
            return 1, 0
        return priority.get(quality, 6), 0

    rows.sort(key=sort_key)
    body = "\n".join(row for _, _, _, row in rows) or '<tr><td colspan="7" class="empty">没有已登记 IP</td></tr>'
    banner = ('<div class="simulation-banner">模拟数据 · 用于验证页面和报表链路，不代表 EDA 质量验收</div>'
              if simulation else "")
    page_count = len(reviews)
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>IP Library · 检查报告总览</title>
<style>
:root{{color-scheme:light;--ink:#1d2b34;--muted:#61717b;--line:#d9e1e5;--paper:#fff;--canvas:#f3f6f7;--teal:#087e80;--red:#a23a32;--amber:#8a5b00;--green:#216947}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--canvas);color:var(--ink);font:14px/1.45 system-ui,-apple-system,"Segoe UI",sans-serif}}
main{{max-width:1680px;margin:0 auto;padding:28px 32px 44px}}header{{display:flex;align-items:flex-end;justify-content:space-between;gap:24px;margin-bottom:18px}}
h1{{font-size:24px;line-height:1.2;margin:0 0 6px}}.subtitle{{margin:0;color:var(--muted)}}.generated{{color:var(--muted);white-space:nowrap;font-size:12px}}
.simulation-banner{{margin:0 0 16px;padding:9px 12px;border:1px solid #ead5a7;background:#fff8e7;color:#714e0a;border-radius:5px;font-weight:600}}
.metrics{{display:grid;grid-template-columns:repeat(4,minmax(150px,1fr));border:1px solid var(--line);background:var(--paper);margin-bottom:18px}}
.metric{{padding:13px 16px;border-right:1px solid var(--line)}}.metric:last-child{{border:0}}.metric span{{display:block;color:var(--muted);font-size:12px}}.metric strong{{display:block;font-size:25px;line-height:1.15;margin-top:3px;font-variant-numeric:tabular-nums}}
.filters{{display:grid;grid-template-columns:minmax(220px,1.4fr) repeat(3,minmax(150px,.8fr)) auto;gap:10px;padding:12px;border:1px solid var(--line);background:var(--paper);margin-bottom:10px}}
input,select,button{{font:inherit;color:var(--ink);border:1px solid #c8d3d8;background:#fff;border-radius:4px;padding:8px 10px;min-height:38px}}input:focus,select:focus,button:focus-visible{{outline:2px solid #5aa9a7;outline-offset:1px}}
button{{cursor:pointer;font-weight:600}}.result-count{{align-self:center;color:var(--muted);white-space:nowrap}}
.table-wrap{{background:var(--paper);border:1px solid var(--line);overflow:auto}}table{{width:100%;border-collapse:collapse;min-width:1340px}}th,td{{padding:12px 13px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}}th{{position:sticky;top:0;background:#eaf0f2;color:#344953;font-size:12px;z-index:1}}tbody tr:hover{{background:#f8fbfb}}td:first-child{{min-width:180px}}td:nth-child(2){{min-width:170px}}td:nth-child(3){{min-width:250px}}td:nth-child(4){{min-width:235px}}td:nth-child(5){{min-width:175px}}td:nth-child(6){{min-width:180px}}td:nth-child(7){{min-width:110px}}
td small{{display:block;margin-top:4px;color:var(--muted);font-size:12px;overflow-wrap:anywhere}}.status-badge,.quality-badge{{display:inline-block;border-radius:3px;padding:3px 7px;font-size:12px;font-weight:700;white-space:nowrap}}
.status-complete{{color:#175d3d;background:#e7f4eb}}.status-failed,.quality-mismatch{{color:#8a2f2a;background:#fbe9e7}}.status-running,.status-queued,.status-pending{{color:#705000;background:#fff2ce}}.status-incomplete,.status-interrupted,.status-not_run,.quality-unverified,.quality-summary_incomplete{{color:#795300;background:#fff3d7}}.quality-changed{{color:#285b78;background:#e8f2f8}}.quality-no_findings{{color:#216947;background:#e7f4eb}}.quality-no_report{{color:#5d6970;background:#eef1f2}}
.coverage{{display:flex;flex-wrap:wrap;gap:4px;margin-top:7px}}.check-chip{{display:inline-block;font-size:11px;border-radius:3px;padding:2px 5px;background:#eef1f2;color:#58666c;white-space:nowrap}}.check-chip.complete{{background:#e7f4eb;color:#216947}}.check-chip.failed,.check-chip.incomplete{{background:#fbe9e7;color:#8a2f2a}}.check-chip.not-selected{{background:#f0f2f3;color:#6b777d}}
.findings{{display:flex;flex-direction:column;gap:5px;font-variant-numeric:tabular-nums}}.finding{{white-space:nowrap}}.finding.changed{{color:#285b78}}.finding.mismatch{{color:#8a2f2a;font-weight:700}}.finding.unverified{{color:#795300}}.primary-finding{{max-width:380px;color:var(--ink);font-size:12px;white-space:normal}}.excel-link{{display:inline-block;background:var(--teal);color:#fff;text-decoration:none;border-radius:4px;padding:8px 11px;font-weight:700;white-space:nowrap}}.excel-link:hover{{background:#06696b}}.muted{{color:var(--muted)}}details{{margin-top:5px}}summary{{cursor:pointer;color:#146e70;font-weight:600;font-size:12px}}details ul{{max-height:170px;overflow:auto;padding-left:18px;margin:8px 0}}code{{font:12px/1.4 ui-monospace,monospace;overflow-wrap:anywhere}}.empty{{padding:28px;color:var(--muted);text-align:center}}
@media(max-width:900px){{main{{padding:20px 16px}}header{{display:block}}.generated{{display:block;margin-top:8px}}.metrics{{grid-template-columns:repeat(2,1fr)}}.metric:nth-child(2){{border-right:0}}.metric:nth-child(-n+2){{border-bottom:1px solid var(--line)}}.filters{{grid-template-columns:1fr 1fr}}}}
</style>
</head>
<body>
<main>
<header><div><h1>IP Library · 检查报告总览</h1><p class="subtitle">按 IP 查看最近任务、完整报告范围、工程发现与 Excel 证据。</p></div><div class="generated">登记 IP：{page_count} · 任务完成不等于质量通过或正式放行</div></header>
{banner}
<section class="metrics" aria-label="检查概况">
<div class="metric"><span>已登记 IP</span><strong id="metric-ip-count">{page_count}</strong></div>
<div class="metric"><span>有完整检查报告</span><strong id="metric-complete-count">{metrics['complete']}</strong></div>
<div class="metric"><span>存在明确不一致的 IP</span><strong id="metric-mismatch-count">{metrics['mismatch']}</strong></div>
<div class="metric"><span>存在待核实项的 IP</span><strong id="metric-unverified-count">{metrics['unverified']}</strong></div>
</section>
<section class="filters" aria-label="筛选检查结果">
<input id="ip-search" type="search" placeholder="搜索 IP、Vendor 或库标识" aria-label="搜索 IP、Vendor 或库标识">
<select id="attempt-filter" aria-label="按最近任务状态筛选"><option value="">全部任务状态</option><option value="COMPLETE">任务已结束</option><option value="FAILED">执行失败</option><option value="RUNNING">运行中</option><option value="QUEUED">排队中</option><option value="INCOMPLETE">结果不完整</option><option value="INTERRUPTED">已中断</option><option value="NOT_RUN">尚未运行</option></select>
<select id="quality-filter" aria-label="按质量状态筛选"><option value="">全部质量状态</option><option value="MISMATCH">有不一致</option><option value="UNVERIFIED">有待核实</option><option value="CHANGED">有变化</option><option value="NO_FINDINGS">范围内无发现</option><option value="NO_REPORT">无完整报告</option></select>
<select id="check-filter" aria-label="按检查类型筛选"><option value="">全部检查类型</option>{''.join(f'<option value="{name}">{label}</option>' for name, label in CHECKS)}</select>
<button id="clear-filters" type="button">清除筛选</button><span id="result-count" class="result-count">显示 {page_count} / {page_count}</span>
</section>
<div class="table-wrap"><table>
<thead><tr><th>IP / Vendor</th><th>最近尝试</th><th>检查覆盖</th><th>最近完整报告范围</th><th>工程发现</th><th>质量判断</th><th>报告</th></tr></thead>
<tbody id="ip-rows">{body}<tr id="empty-row" hidden><td colspan="7" class="empty">没有符合筛选条件的 IP</td></tr></tbody>
</table></div>
<p class="subtitle" style="margin-top:10px">四项检查状态仅表示同一份完整 Review 的执行覆盖。变化、不一致、待核实分别计数；数量口径见对应 Excel，不代表独立根因数。</p>
</main>
<script>
(() => {{
  const search = document.getElementById('ip-search');
  const attempt = document.getElementById('attempt-filter');
  const quality = document.getElementById('quality-filter');
  const check = document.getElementById('check-filter');
  const rows = [...document.querySelectorAll('[data-ip-row]')];
  const count = document.getElementById('result-count');
  const empty = document.getElementById('empty-row');
  function applyFilters() {{
    const query = search.value.trim().toLocaleLowerCase();
    let visible = 0;
    for (const row of rows) {{
      const statusOk = !attempt.value || row.dataset.attempt === attempt.value;
      const qualityOk = !quality.value || (quality.value === 'MISMATCH' ? row.dataset.hasMismatch === 'true' :
        quality.value === 'UNVERIFIED' ? row.dataset.hasUnverified === 'true' :
        quality.value === 'CHANGED' ? row.dataset.hasChanged === 'true' : row.dataset.quality === quality.value);
      const checkOk = !check.value || row.dataset.checks.split(',').includes(check.value);
      const searchOk = !query || row.dataset.search.includes(query);
      const show = statusOk && qualityOk && checkOk && searchOk;
      row.hidden = !show;
      visible += Number(show);
    }}
    empty.hidden = visible > 0;
    count.textContent = `显示 ${{visible}} / ${{rows.length}}`;
  }}
  search.addEventListener('input', applyFilters);
  for (const control of [attempt, quality, check]) control.addEventListener('change', applyFilters);
  document.getElementById('clear-filters').addEventListener('click', () => {{
    search.value = ''; attempt.value = ''; quality.value = ''; check.value = ''; applyFilters(); search.focus();
  }});
}})();
</script>
</body>
</html>
"""
