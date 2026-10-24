"""Render a lightweight, read-only index of per-IP review runs."""

from __future__ import annotations

from html import escape
from typing import Any


def render_overview(reviews: list[dict[str, Any]]) -> str:
    rows = []
    catalog_rows = []
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
        latest_href = item.get("latest_xlsx_href") or ""
        current_href = item.get("current_xlsx_href") or ""
        links = []
        if latest_href:
            links.append(f'<a href="{escape(str(latest_href), quote=True)}">最新 Excel</a>')
        if current_href and current_href != latest_href:
            links.append(f'<a href="{escape(str(current_href), quote=True)}">本次 Excel</a>')
        report_link = " · ".join(links) if links else "暂无报告"
        rows.append(
            "<tr>"
            f"<td>{escape(str(item.get('name') or item.get('library_id') or ''))}<br>"
            f"<small>{escape(str(item.get('library_id') or ''))}</small></td>"
            f"<td>{escape(requested)}</td>"
            f"<td>{escape(status_text)}<br><small>{escape(latest)}</small></td>"
            f"<td>{escape(finding_summary)}</td>"
            "</tr>"
        )
        versions = item.get("raw_versions") or []
        if versions:
            version_items = "".join(
                "<li><strong>" + escape(str(version.get("id") or "")) + "</strong><br><small>" +
                escape(str(version.get("path") or "")) + "</small></li>"
                for version in versions
            )
            version_labels = (f"<details><summary>{len(versions)} 个 RAW 版本</summary>"
                              f"<ul>{version_items}</ul></details>")
        else:
            version_labels = "未登记"
        view_labels = " · ".join(str(view) for view in item.get("view_types") or []) or "—"
        catalog_rows.append(
            "<tr>"
            f"<td>{escape(str(item.get('vendor') or '—'))}</td>"
            f"<td>{escape(str(item.get('middle_path') or '—'))}</td>"
            f"<td><strong>{escape(str(item.get('name') or item.get('library_id') or ''))}</strong><br>"
            f"<small>{escape(str(item.get('library_id') or ''))}</small></td>"
            f"<td>{version_labels}</td>"
            f"<td>{escape(view_labels)}</td>"
            f"<td><small>{escape(str(item.get('raw_root') or '—'))}</small></td>"
            f"<td>{report_link}</td>"
            "</tr>"
        )
    body = "\n".join(rows) or '<tr><td colspan="4">当前没有检查记录。</td></tr>'
    catalog_body = "\n".join(catalog_rows) or '<tr><td colspan="7">当前没有登记库。</td></tr>'
    return """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>IP 检查总览</title>
<style>
body{font:14px/1.5 system-ui,sans-serif;color:#1b2730;margin:32px auto;padding:0 24px;max-width:1440px}
h1{font-size:22px;margin:0 0 8px}h2{font-size:17px;margin:30px 0 10px}p{color:#526271;margin:0 0 20px}
table{width:100%;border-collapse:collapse}th,td{border-bottom:1px solid #d6dee5;padding:10px 12px;text-align:left;vertical-align:top}
th{background:#edf2f6;color:#263d4e}tr:hover td{background:#f7fafc}small{color:#60717e;overflow-wrap:anywhere}
a{color:#126b70;font-weight:600}td:first-child{min-width:140px}td:nth-child(2){min-width:130px}code{overflow-wrap:anywhere}
details summary{cursor:pointer;color:#126b70;font-weight:600}ul{max-height:180px;overflow:auto;padding-left:18px}li{margin:5px 0}td small{display:block}
</style>
</head>
<body>
<h1>IP 检查总览</h1>
<p>每行对应配置中的一个 IP。检查运行状态与工程发现分开显示；对象数与发现记录数分开统计。执行完成不等于质量通过或正式放行。</p>
<h2>库目录</h2>
<table>
<thead><tr><th>Vendor</th><th>分组</th><th>IP / 库标识</th><th>RAW 版本</th><th>View</th><th>RAW 根路径</th><th>工作簿</th></tr></thead>
<tbody>__CATALOG__</tbody>
</table>
<h2>检查结果</h2>
<table>
<thead><tr><th>IP / 库标识</th><th>检查范围</th><th>最近执行</th><th>最近成功结果：对象数 / 记录数</th></tr></thead>
<tbody>__ROWS__</tbody>
</table>
</body>
</html>
""".replace("__ROWS__", body).replace("__CATALOG__", catalog_body)
