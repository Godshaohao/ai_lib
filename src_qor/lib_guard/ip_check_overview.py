"""Render a lightweight, read-only index of per-IP review runs."""

from __future__ import annotations

from html import escape
from typing import Any


def render_overview(reviews: list[dict[str, Any]]) -> str:
    rows = []
    for item in reviews:
        summary = item.get("latest_summary") or {}
        counts = summary.get("counts") or {}
        requested = ", ".join(item.get("attempt_checks") or item.get("latest_complete_checks") or item.get("requested_checks") or []) or "未选择检查"
        status = str(item.get("attempt_status") or item.get("execution_status") or "NOT_RUN")
        status_text = {"COMPLETE": "本次所选检查已完成", "FAILED": "有检查执行失败",
                       "INCOMPLETE": "本次检查未完整", "NOT_RUN": "尚无运行记录",
                       "PENDING": "排队中", "RUNNING": "运行中", "INTERRUPTED": "已中断"}.get(status, status)
        assessment = item.get("attempt_quality_assessment") or {}
        if assessment.get("label"):
            status_text += f"；质量判断：{assessment['label']}"
        mismatch = int((counts.get("MISMATCH") or {}).get("affected_objects", summary.get("confirmed_mismatches", 0)))
        changed = int((counts.get("CHANGED") or {}).get("affected_objects", summary.get("confirmed_changes", 0)))
        unverified = int((counts.get("UNVERIFIED") or {}).get("affected_objects", summary.get("unverified", 0)))
        finding_summary = f"变化 {changed}；不一致 {mismatch} 项；待核实 {unverified}"
        latest_href = item.get("latest_xlsx_href") or ""
        report_link = (f'<a href="{escape(str(latest_href), quote=True)}">最近完整 Excel</a>'
                       if latest_href else "暂无完整报告")
        versions = item.get("raw_versions") or []
        if versions:
            version_items = "".join(
                "<li><strong>" + escape(str(version.get("id") or "")) + "</strong><br><small>" +
                escape(str(version.get("path") or "")) + "</small></li>"
                for version in versions
            )
            version_labels = f"<ul>{version_items}</ul>"
        else:
            version_labels = "未登记"
        view_labels = " · ".join(str(view) for view in item.get("view_types") or []) or "—"
        attempt_id = item.get("attempt_id") or item.get("review_id") or ""
        attempt_time = item.get("attempt_time") or ""
        complete_id = item.get("latest_complete_id") or item.get("latest_review_id") or ""
        complete_time = item.get("latest_complete_time") or ""
        complete_quality = (summary.get("quality_assessment") or {}).get("label")
        complete_text = (f"最近成功：{escape(finding_summary)}<br><small>质量判断：{escape(str(complete_quality or '未形成质量结论'))}；"
                         f"{escape(str(complete_id))} "
                         f"{escape(str(complete_time))}</small>" if complete_id else
                         "最近完整工作簿已存在，运行身份未提供" if latest_href else "尚无成功记录")
        identity = item.get("name") or item.get("library_id") or ""
        vendor = item.get("vendor") or "—"
        middle_path = item.get("middle_path") or ""
        raw_root = item.get("raw_root") or ""
        source_details = (f"<details><summary>版本与原始路径</summary>{version_labels}"
                          f"<small>{escape(str(raw_root))}</small></details>") if versions or raw_root else version_labels
        # Keep a single IP row; expanded path evidence is for locating inputs, not a second result table.
        rows.append(
            "<tr>"
            f"<td><strong>{escape(str(identity))}</strong><small>{escape(str(vendor))}"
            f"{(' / ' + escape(str(middle_path))) if middle_path else ''} · {escape(str(item.get('library_id') or ''))}</small></td>"
            f"<td>{len(versions)} 个版本<br>{source_details}</td>"
            f"<td>{escape(view_labels)}</td>"
            f"<td>{escape(requested)}</td>"
            f"<td>{escape(status_text)}<small>{escape(str(attempt_id))} {escape(str(attempt_time))}</small></td>"
            f"<td>{complete_text}</td>"
            f"<td>{report_link}</td>"
            "</tr>"
        )
    body = "\n".join(rows) or '<tr><td colspan="7">当前没有登记库。</td></tr>'
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
a{color:#126b70;font-weight:600}td:first-child{min-width:140px}td:nth-child(2){min-width:130px}code{overflow-wrap:anywhere}
details summary{cursor:pointer;color:#126b70;font-weight:600}ul{max-height:180px;overflow:auto;padding-left:18px}li{margin:5px 0}td small{display:block}
</style>
</head>
<body>
<h1>IP 检查总览</h1>
<p>每行一个 IP。最近尝试与最近完整报告分开显示；接口不一致按文件×Cell 计数，其他检查按各自对象计数，均不等于独立根因数。任务完成不代表质量通过或正式放行。</p>
<table>
<thead><tr><th>IP / Vendor</th><th>RAW 版本</th><th>View</th><th>检查范围</th><th>最近尝试</th><th>最近完整检查报告</th><th>报告</th></tr></thead>
<tbody>__ROWS__</tbody>
</table>
</body>
</html>
""".replace("__ROWS__", body)
