"""Team-oriented catalog and version review HTML renderer."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping
import html
import json
import re

from lib_guard.review import build_review_state, build_review_tasks
from lib_guard.review.io import as_file_href, read_json, write_json
from lib_guard.review.status import label, tone


def _esc(value: Any) -> str:
    return html.escape("" if value is None else str(value))


def _safe(value: Any) -> str:
    text = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value or "item")).strip("._")
    return text or "item"


def _badge(status: Any, text: Any | None = None) -> str:
    return f"<span class='badge {tone(status)}'>{_esc(text if text is not None else label(status))}</span>"


def _button(text: str, href: str = "", *, disabled: bool = False, kind: str = "") -> str:
    cls = f"btn {kind}".strip()
    if disabled or not href:
        return f"<span class='{cls} disabled'>{_esc(text)}</span>"
    return f"<a class='{cls}' href='{_esc(href)}'>{_esc(text)}</a>"


def _trace(value: Any) -> str:
    return f"<span class='muted trace'>{_esc(value)}</span>" if value else ""


def _copy(command: str) -> str:
    if not command:
        return "<span class='muted'>需要人工确认后生成命令</span>"
    payload = json.dumps(command, ensure_ascii=False)
    return f"<div class='command'><code>{_esc(command)}</code><button onclick='copyText({payload}, this)'>复制</button></div>"


def _css() -> str:
    return """
:root{--ink:#172033;--muted:#667085;--line:#d9e2ec;--wash:#f6f8fb;--panel:#fff;--blue:#155eef;--green:#168253;--amber:#a15c00;--red:#c0332b;--shadow:0 14px 38px rgba(16,24,40,.08)}
*{box-sizing:border-box} body{margin:0;background:#f7f9fc;color:var(--ink);font-family:"Microsoft YaHei","Segoe UI",Arial,sans-serif}
.shell{max-width:1480px;margin:0 auto;padding:22px 24px 56px}.top{display:flex;justify-content:space-between;gap:18px;align-items:flex-end;margin-bottom:16px}
h1{font-size:25px;margin:0 0 7px;font-weight:760}.sub{color:var(--muted);font-size:13px;line-height:1.55}.mini{display:flex;gap:8px;flex-wrap:wrap;justify-content:flex-end}
.stat{border:1px solid var(--line);background:#fff;border-radius:999px;padding:7px 10px;font-size:12px;color:#344054}
.toolbar{display:grid;grid-template-columns:minmax(260px,1fr) auto;gap:12px;margin:12px 0 16px}.search{width:100%;border:1px solid var(--line);border-radius:8px;padding:11px 12px;font-size:14px;background:#fff}
.chips{display:flex;gap:8px;flex-wrap:wrap}.chip{border:1px solid var(--line);background:#fff;border-radius:999px;padding:8px 11px;font-size:12px;cursor:pointer}.chip.active{border-color:#9cc2ff;background:#eef5ff;color:#1849a9}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:8px;box-shadow:var(--shadow);margin:14px 0}.panel-head{padding:15px 16px;border-bottom:1px solid var(--line);display:flex;justify-content:space-between;gap:12px;align-items:center}.panel-body{padding:14px 16px}
details.panel>summary{list-style:none;cursor:pointer;padding:15px 16px;font-weight:720}details.panel>summary::-webkit-details-marker{display:none}
.library{border:1px solid var(--line);border-radius:8px;background:#fff;margin:10px 0;overflow:hidden}.lib-main{display:grid;grid-template-columns:minmax(220px,1.25fr) 1fr .8fr .7fr auto;gap:12px;align-items:center;padding:13px 14px}.lib-title{font-size:17px;font-weight:760}.path{font-size:12px;color:var(--muted);line-height:1.55;word-break:break-all}.actions{display:flex;gap:7px;flex-wrap:wrap;justify-content:flex-end}
.versions{border-top:1px solid var(--line);background:#fbfcfe}.version{display:grid;grid-template-columns:minmax(200px,1.2fr) .7fr .7fr .7fr .7fr 1.45fr auto;gap:10px;align-items:center;padding:10px 14px;border-top:1px solid #edf1f5}.version:first-child{border-top:0}
.badge{display:inline-flex;align-items:center;min-height:24px;border-radius:999px;border:1px solid #d0d7e2;background:#f5f7fa;color:#344054;padding:3px 8px;font-size:12px;white-space:nowrap}.badge.ok{border-color:#b7dfc8;background:#eefaf3;color:var(--green)}.badge.warn{border-color:#f1cf99;background:#fff7e8;color:var(--amber)}.badge.bad{border-color:#efb3ac;background:#fff1f0;color:var(--red)}.badge.muted{border-color:#d5dbe5;background:#f3f5f8;color:#667085}
.btn{display:inline-flex;align-items:center;justify-content:center;min-height:30px;padding:6px 9px;border-radius:6px;border:1px solid #cfd8e6;background:#fff;color:#155eef;text-decoration:none;font-size:12px;white-space:nowrap}.btn.primary{background:#155eef;color:#fff;border-color:#155eef}.btn.disabled{color:#98a2b3;background:#f4f6f8}
table{width:100%;border-collapse:collapse;font-size:13px}th,td{border-bottom:1px solid var(--line);padding:9px 10px;text-align:left;vertical-align:top}th{background:var(--wash);color:#344054}.muted{color:var(--muted);font-size:12px}.command{display:flex;gap:8px;align-items:center;max-width:680px}.command code{background:#f2f5f9;border:1px solid #dce4ee;border-radius:6px;padding:6px 8px;white-space:normal;word-break:break-word;font-size:12px}.command button{border:1px solid #b9c7da;background:#fff;border-radius:6px;padding:6px 9px;cursor:pointer}
.review-grid{display:grid;grid-template-columns:1.25fr .85fr;gap:14px}.kv{display:grid;grid-template-columns:160px 1fr;gap:8px;font-size:13px}.kv div:nth-child(odd){color:#667085}.nav{display:flex;gap:8px;flex-wrap:wrap;margin:10px 0 0}.nav a{color:#155eef;text-decoration:none;border:1px solid var(--line);background:#fff;border-radius:999px;padding:6px 10px;font-size:12px}
@media(max-width:980px){.toolbar,.lib-main,.version,.review-grid{grid-template-columns:1fr}.actions{justify-content:flex-start}.mini{justify-content:flex-start}}
"""


def _script() -> str:
    return """
function copyText(text, btn){navigator.clipboard&&navigator.clipboard.writeText(text); if(btn){var old=btn.textContent;btn.textContent='已复制';setTimeout(function(){btn.textContent=old},1200)}}
function filterCatalog(){
  var q=(document.getElementById('search').value||'').toLowerCase();
  var active=document.querySelector('.chip.active');
  var status=active?active.getAttribute('data-status'):'all';
  document.querySelectorAll('.library').forEach(function(lib){
    var text=lib.textContent.toLowerCase();
    var hit=!q||text.indexOf(q)>=0;
    var st=status==='all'||lib.getAttribute('data-overall')===status;
    lib.style.display=(hit&&st)?'':'none';
  });
}
function setStatusFilter(el){document.querySelectorAll('.chip').forEach(function(x){x.classList.remove('active')});el.classList.add('active');filterCatalog()}
"""


def _page(title: str, subtitle: str, body: str, *, nav: str = "") -> str:
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{_esc(title)}</title>
  <style>{_css()}</style>
</head>
<body>
<main class="shell">
  <div class="top">
    <div><h1>{_esc(title)}</h1><div class="sub">{_esc(subtitle)}</div>{nav}</div>
  </div>
  {body}
</main>
<script>{_script()}</script>
</body>
</html>"""


def _library_rows(state: Mapping[str, Any]) -> str:
    rows = []
    for lib in state.get("libraries", []) or []:
        versions = lib.get("versions", []) or []
        latest = lib.get("latest_version") or "-"
        approved = lib.get("approved_version") or "-"
        status = lib.get("overall_status") or "UNKNOWN"
        version_rows = []
        for ver in versions:
            links = ver.get("links") or {}
            pair = ver.get("pairwise_summary") or {}
            pair_text = f"{pair.get('done', 0)}/{pair.get('total', 0)}" if pair.get("total") else label(ver.get("pairwise_status"))
            command = str(ver.get("next_command") or "")
            version_rows.append(
                "<div class='version'>"
                f"<div><b>{_esc(ver.get('version_id'))}</b><div class='path'>{_esc(ver.get('raw_path'))}</div></div>"
                f"<div>{_badge(ver.get('scan_status'))}</div>"
                f"<div>{_badge(ver.get('diff_status'))}</div>"
                f"<div>{_badge(ver.get('pairwise_status'), pair_text)}</div>"
                f"<div>{_badge(ver.get('release_status'))}</div>"
                f"<div>{_copy(command)}<div class='muted'>{_esc(ver.get('next_reason'))}</div></div>"
                "<div class='actions'>"
                f"{_button('Review', links.get('version_review_html'), kind='primary')}"
                f"{_button('Scan', as_file_href(links.get('scan_html')), disabled=not links.get('scan_html'))}"
                f"{_button('Diff', as_file_href(links.get('diff_html')), disabled=not links.get('diff_html'))}"
                f"{_button('Pairwise', as_file_href(links.get('pairwise_html')), disabled=not links.get('pairwise_html'))}"
                f"{_button('Release', as_file_href(links.get('release_html')), disabled=not links.get('release_html'))}"
                "</div>"
                f"{_trace(links.get('scan_html'))}{_trace(links.get('diff_html'))}{_trace(links.get('release_html'))}</div>"
            )
        rows.append(
            f"<section class='library' data-overall='{_esc(status)}'>"
            "<div class='lib-main'>"
            f"<div><div class='lib-title'>{_esc(lib.get('display_name'))}</div><div class='path'>{_esc(lib.get('library_id'))}</div></div>"
            f"<div><b>{_esc(lib.get('vendor') or '-')}</b><div class='path'>{_esc(lib.get('middle_path') or lib.get('library_root') or '-')}</div></div>"
            f"<div><span class='muted'>latest</span><br><b>{_esc(latest)}</b></div>"
            f"<div><span class='muted'>current</span><br><b>{_esc(approved)}</b></div>"
            f"<div class='actions'>{_badge(status)}<span class='stat'>{_esc(len(versions))} versions</span></div>"
            "</div>"
            f"<div class='versions'>{''.join(version_rows)}</div>"
            "</section>"
        )
    return "".join(rows) or "<div class='panel'><div class='panel-body muted'>暂无库。</div></div>"


def _task_rows(tasks: Mapping[str, Any]) -> list[str]:
    rows = []
    for task in tasks.get("tasks", []) or []:
        rows.append(
            "<tr>"
            f"<td>{_badge(task.get('priority'), task.get('priority'))}</td>"
            f"<td>{_esc(task.get('task_type'))}</td>"
            f"<td><b>{_esc(task.get('display_name'))}</b><div class='muted'>{_esc(task.get('version_id'))}</div></td>"
            f"<td>{_esc(task.get('reason'))}</td>"
            f"<td>{_copy(str(task.get('command') or ''))}</td>"
            "</tr>"
        )
    return rows


def _table(headers: list[str], rows: list[str], empty: str) -> str:
    head = "".join(f"<th>{_esc(h)}</th>" for h in headers)
    body = "".join(rows) or f"<tr><td colspan='{len(headers)}' class='muted'>{_esc(empty)}</td></tr>"
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def _summary(state: Mapping[str, Any], tasks: Mapping[str, Any]) -> dict[str, int]:
    libs = list(state.get("libraries", []) or [])
    versions = [v for lib in libs for v in lib.get("versions", []) or []]
    return {
        "libraries": len(libs),
        "versions": len(versions),
        "review": sum(1 for v in versions if v.get("overall_status") == "REVIEW"),
        "block": sum(1 for v in versions if v.get("overall_status") == "BLOCK"),
        "not_scanned": sum(1 for v in versions if v.get("scan_status") == "NOT_SCANNED"),
        "diff_pending": sum(1 for v in versions if v.get("diff_status") in {"DIFF_PENDING", "DIFF_NOT_READY"}),
        "pairwise_pending": sum(1 for v in versions if v.get("pairwise_status") in {"PAIRWISE_PENDING", "PAIRWISE_PARTIAL"}),
        "tasks": len(tasks.get("tasks", []) or []),
    }


def _render_version_page(out: Path, lib: Mapping[str, Any], version: Mapping[str, Any]) -> None:
    links = version.get("links") or {}
    page = out / str(links.get("version_review_html"))
    page.parent.mkdir(parents=True, exist_ok=True)
    pair = version.get("pairwise_summary") or {}
    nav = (
        "<nav class='nav'>"
        "<a href='../../../index.html'>Catalog</a>"
        f"<a href='{_esc(as_file_href(links.get('scan_html')))}'>Scan</a>"
        f"<a href='{_esc(as_file_href(links.get('diff_html')))}'>Diff</a>"
        f"<a href='{_esc(as_file_href(links.get('pairwise_html')))}'>Pairwise</a>"
        f"<a href='{_esc(as_file_href(links.get('release_html')))}'>Release</a>"
        "</nav>"
    )
    kv = [
        ("Library", lib.get("display_name")),
        ("Vendor", lib.get("vendor") or "-"),
        ("Path", lib.get("library_root") or "-"),
        ("Version", version.get("version_id")),
        ("Stage", version.get("stage")),
        ("Parent", version.get("parent_version") or "-"),
        ("Base", version.get("base_version") or "-"),
        ("Raw Path", version.get("raw_path") or "-"),
    ]
    kv_html = "<div class='kv'>" + "".join(f"<div>{_esc(k)}</div><div>{_esc(v)}</div>" for k, v in kv) + "</div>"
    task_rows = []
    for task in version.get("pairwise_tasks", []) or []:
        result = task.get("result") or {}
        task_rows.append(
            "<tr>"
            f"<td>{_badge(task.get('status'))}</td>"
            f"<td>{_esc(task.get('file_type'))}</td>"
            f"<td>{_esc(task.get('reason'))}</td>"
            f"<td>{_copy(str(task.get('command') or ''))}</td>"
            f"<td>{_button('Open', as_file_href(result.get('html')), disabled=not result.get('html'))}</td>"
            "</tr>"
        )
    body = (
        "<section class='panel'><div class='panel-head'><b>Status Strip</b>"
        f"<div class='actions'>{_badge(version.get('catalog_status'))}{_badge(version.get('scan_status'))}{_badge(version.get('diff_status'))}{_badge(version.get('pairwise_status'), str(pair.get('done', 0)) + '/' + str(pair.get('total', 0)) if pair.get('total') else None)}{_badge(version.get('release_status'))}</div></div>"
        f"<div class='panel-body review-grid'><div>{kv_html}</div><div><h3>Next Action</h3>{_badge(version.get('next_action'), version.get('next_action'))}{_copy(str(version.get('next_command') or ''))}<p class='sub'>{_esc(version.get('next_reason'))}</p></div></div></section>"
        "<section class='panel'><div class='panel-head'><b>Evidence Links</b></div><div class='panel-body actions'>"
        f"{_button('Scan Report', as_file_href(links.get('scan_html')), disabled=not links.get('scan_html'))}"
        f"{_button('Diff Report', as_file_href(links.get('diff_html')), disabled=not links.get('diff_html'))}"
        f"{_button('Pairwise Review', as_file_href(links.get('pairwise_html')), disabled=not links.get('pairwise_html'))}"
        f"{_button('Release Report', as_file_href(links.get('release_html')), disabled=not links.get('release_html'))}"
        f"{_button('Raw Path', as_file_href(version.get('raw_path')), disabled=not version.get('raw_path'))}"
        "</div></section>"
        "<section class='panel' id='pairwise'><div class='panel-head'><b>Pairwise Review Tasks</b></div><div class='panel-body'>"
        + _table(["Status", "Type", "Reason", "Command", "Result"], task_rows, "暂无 pairwise 任务。")
        + "</div></section>"
    )
    page.write_text(_page(f"{lib.get('display_name')} / {version.get('version_id')}", "Version Review Workspace", body, nav=nav), encoding="utf-8")


def _render_legacy_library_page(out: Path, lib: Mapping[str, Any]) -> None:
    page = out / "libraries" / f"{_safe(lib.get('display_name'))}.html"
    page.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for ver in lib.get("versions", []) or []:
        links = ver.get("links") or {}
        rows.append(
            "<tr>"
            f"<td><b>{_esc(ver.get('version_id'))}</b></td>"
            f"<td>{_badge(ver.get('scan_status'))}</td>"
            f"<td>{_badge(ver.get('diff_status'))}</td>"
            f"<td>{_badge(ver.get('release_status'))}</td>"
            f"<td>{_button('Review', '../' + str(links.get('version_review_html') or ''))}"
            f"{_button('Scan', as_file_href(links.get('scan_html')), disabled=not links.get('scan_html'))}"
            f"{_button('Diff', as_file_href(links.get('diff_html')), disabled=not links.get('diff_html'))}"
            f"{_button('Release', as_file_href(links.get('release_html')), disabled=not links.get('release_html'))}"
            f"{_trace(links.get('scan_html'))}{_trace(links.get('diff_html'))}{_trace(links.get('release_html'))}</td>"
            "</tr>"
        )
    body = "<section class='panel'><div class='panel-head'><b>版本结构 / 证据 / 返回 Catalog</b></div><div class='panel-body'>" + _table(["Version", "Scan", "Diff", "Release", "Action"], rows, "暂无版本") + "</div></section>"
    page.write_text(_page(f"{lib.get('display_name')} Library Review", "Library version list", body, nav="<nav class='nav'><a href='../index.html'>Catalog</a></nav>"), encoding="utf-8")


def render_catalog_html(
    catalog_path: str | Path,
    out_dir: str | Path,
    *,
    render_library_pages: bool = True,
    max_attention_items: int = 100,
    max_report_rows: int = 16,
) -> dict[str, Any]:
    catalog_file = Path(catalog_path)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    catalog = read_json(catalog_file, {}) or {}
    state = build_review_state(catalog, out_dir=out)
    tasks = build_review_tasks(state)
    write_json(out / "review_state.json", state)
    write_json(out / "review_tasks.json", tasks)

    for lib in state.get("libraries", []) or []:
        for version in lib.get("versions", []) or []:
            _render_version_page(out, lib, version)
        if render_library_pages:
            _render_legacy_library_page(out, lib)

    metrics = _summary(state, tasks)
    stat_bar = (
        "<div class='mini'>"
        f"<span class='stat'>{metrics['libraries']} libraries</span>"
        f"<span class='stat'>{metrics['versions']} versions</span>"
        f"<span class='stat'>{metrics['review']} need review</span>"
        f"<span class='stat'>{metrics['block']} blocked</span>"
        "</div>"
    )
    manager_rows = [
        f"<tr><td>Total libraries</td><td>{metrics['libraries']}</td></tr>",
        f"<tr><td>Total versions</td><td>{metrics['versions']}</td></tr>",
        f"<tr><td>Not scanned</td><td>{metrics['not_scanned']}</td></tr>",
        f"<tr><td>Diff pending</td><td>{metrics['diff_pending']}</td></tr>",
        f"<tr><td>Pairwise pending</td><td>{metrics['pairwise_pending']}</td></tr>",
        f"<tr><td>Review tasks</td><td>{metrics['tasks']}</td></tr>",
    ]
    body = (
        stat_bar
        + "<section class='toolbar'><input id='search' class='search' oninput='filterCatalog()' placeholder='搜索 library / vendor / path / version'>"
        + "<div class='chips'><button class='chip active' data-status='all' onclick='setStatusFilter(this)'>全部</button><button class='chip' data-status='OK' onclick='setStatusFilter(this)'>正常</button><button class='chip' data-status='REVIEW' onclick='setStatusFilter(this)'>待审阅</button><button class='chip' data-status='BLOCK' onclick='setStatusFilter(this)'>阻断</button><button class='chip' data-status='UNKNOWN' onclick='setStatusFilter(this)'>未知</button></div></section>"
        + "<section class='panel'><div class='panel-head'><b>Library Browser</b><span class='sub'>默认团队视图：先找库、看版本、进入证据页和复制下一步命令。</span></div><div class='panel-body'>"
        + _library_rows(state)
        + "</div></section>"
        + "<details class='panel'><summary>Global Summary / 管理概览</summary><div class='panel-body'>"
        + _table(["Metric", "Value"], manager_rows, "暂无统计")
        + "</div></details>"
        + "<details class='panel'><summary>Review Queue / 待审阅队列</summary><div class='panel-body'>"
        + _table(["Priority", "Type", "Library", "Reason", "Command"], _task_rows(tasks), "暂无待审阅任务")
        + "</div></details>"
        + "<details class='panel'><summary>Evidence Files / 证据文件</summary><div class='panel-body actions'>"
        + _button("catalog.json", as_file_href(catalog_file))
        + _button("review_state.json", as_file_href(out / "review_state.json"))
        + _button("review_tasks.json", as_file_href(out / "review_tasks.json"))
        + "</div></details>"
    )
    html_text = _page("ai_lib Library Catalog", f"Last updated: {state.get('generated_at')}", body)
    (out / "index.html").write_text(html_text, encoding="utf-8")
    return {
        "status": "PASS",
        "catalog_path": str(catalog_file),
        "html_dir": str(out),
        "index_html": str(out / "index.html"),
        "review_state": str(out / "review_state.json"),
        "review_tasks": str(out / "review_tasks.json"),
    }
