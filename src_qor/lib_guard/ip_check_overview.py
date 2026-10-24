"""Render a lightweight, read-only index of per-IP review runs."""

from __future__ import annotations

from html import escape
from typing import Any


def render_overview(reviews: list[dict[str, Any]]) -> str:
    rows = []
    for item in reviews:
        summary = item.get("summary") or {}
        requested = ", ".join(item.get("requested_checks") or []) or "未选择检查"
        status = str(item.get("execution_status") or "未执行")
        status_text = {"COMPLETE": "本次所选检查已完成", "FAILED": "有检查执行失败",
                       "INCOMPLETE": "本次检查未完整"}.get(status, status)
        latest = "当前记录" if item.get("latest") else "仅本次运行"
        rows.append(
            "<tr>"
            f"<td>{escape(str(item.get('name') or item.get('library_id') or ''))}<br>"
            f"<small>{escape(str(item.get('library_id') or ''))}</small></td>"
            f"<td>{escape(requested)}</td>"
            f"<td>{escape(status_text)}<br><small>{escape(latest)}</small></td>"
            f"<td>已提取变化 {int(summary.get('confirmed_changes', 0))}；"
            f"已确认差异 {int(summary.get('confirmed_mismatches', 0))}；"
            f"证据不足 {int(summary.get('unverified', 0))}；"
            f"范围说明 {int(summary.get('scope_notes', 0))}</td>"
            f"<td><a href=\"{escape(str(item.get('xlsx_href') or ''), quote=True)}\">打开单 IP Excel</a></td>"
            "</tr>"
        )
    body = "\n".join(rows) or '<tr><td colspan="5">当前没有检查记录。</td></tr>'
    return """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>IP 检查总览</title>
<style>
body{font:14px/1.5 system-ui,sans-serif;color:#1b2730;margin:32px auto;padding:0 24px;max-width:1440px}
h1{font-size:22px;margin:0 0 8px}p{color:#526271;margin:0 0 20px}
table{width:100%;border-collapse:collapse}th,td{border-bottom:1px solid #d6dee5;padding:10px 12px;text-align:left;vertical-align:top}
th{background:#edf2f6;color:#263d4e}tr:hover td{background:#f7fafc}small{color:#60717e;overflow-wrap:anywhere}
a{color:#126b70;font-weight:600}td:first-child{min-width:220px}td:nth-child(2){min-width:150px}
</style>
</head>
<body>
<h1>IP 检查总览</h1>
<p>每行对应一个独立 IP 检查记录。此页只汇总本次运行，不合并 IP 的明细；执行完成不等于质量通过或正式放行。</p>
<table>
<thead><tr><th>IP / 库标识</th><th>本次选择的检查</th><th>执行状态</th><th>结果摘要</th><th>报告</th></tr></thead>
<tbody>__ROWS__</tbody>
</table>
</body>
</html>
""".replace("__ROWS__", body)
