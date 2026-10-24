"""Render a lightweight, read-only index of per-IP review runs."""

from __future__ import annotations

from html import escape
from typing import Any


def render_overview(reviews: list[dict[str, Any]]) -> str:
    rows = []
    for item in reviews:
        summary = item.get("latest_summary") or item.get("summary") or {}
        counts = summary.get("counts") or {}
        requested = ", ".join(item.get("requested_checks") or []) or "未选择检查"
        status = str(item.get("execution_status") or "未执行")
        status_text = {"COMPLETE": "本次所选检查已完成", "FAILED": "有检查执行失败",
                       "INCOMPLETE": "本次检查未完整", "NOT_RUN": "尚无运行记录"}.get(status, status)
        latest = "有最近成功记录" if item.get("latest") else "尚无成功记录"
        finding_summary = "；".join(
            f"{label} {int((counts.get(kind) or {}).get('affected_objects', summary.get(alias, 0)))} 个对象 / "
            f"{int((counts.get(kind) or {}).get('finding_records', 0))} 条记录"
            for kind, alias, label in (("CHANGED", "confirmed_changes", "变化"),
                                       ("MISMATCH", "confirmed_mismatches", "不一致"),
                                       ("UNVERIFIED", "unverified", "待核实"),
                                       ("SCOPE_INFO", "scope_notes", "范围说明")))
        report_href = item.get("xlsx_href") or ""
        report_link = (f'<a href="{escape(str(report_href), quote=True)}">打开单 IP Excel</a>'
                       if report_href else "暂无报告")
        rows.append(
            "<tr>"
            f"<td>{escape(str(item.get('name') or item.get('library_id') or ''))}<br>"
            f"<small>{escape(str(item.get('library_id') or ''))}</small></td>"
            f"<td>{escape(requested)}</td>"
            f"<td>{escape(status_text)}<br><small>{escape(latest)}</small></td>"
            f"<td>{escape(finding_summary)}</td>"
            f"<td>{report_link}</td>"
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
<p>每行对应配置中的一个 IP。检查运行状态与工程发现分开显示；对象数与发现记录数分开统计。执行完成不等于质量通过或正式放行。</p>
<table>
<thead><tr><th>IP / 库标识</th><th>检查范围</th><th>最近执行</th><th>最近成功结果：对象数 / 记录数</th><th>报告</th></tr></thead>
<tbody>__ROWS__</tbody>
</table>
</body>
</html>
""".replace("__ROWS__", body)
