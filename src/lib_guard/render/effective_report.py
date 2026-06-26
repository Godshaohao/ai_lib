from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any, Mapping

try:
    from lib_guard.effective.manifest import compare_matrix, short_name, update_scope_heatmap
except Exception:  # pragma: no cover
    compare_matrix = None
    update_scope_heatmap = None

    def short_name(name: str, head: int = 20, tail: int = 16) -> str:
        text = str(name or "")
        return text if len(text) <= head + tail + 3 else f"{text[:head]}...{text[-tail:]}"


def esc(value: Any) -> str:
    return html.escape(str(value if value is not None else ""))


def _json_script(id_: str, data: Any) -> str:
    raw = json.dumps(data, ensure_ascii=False)
    return f'<script id="{esc(id_)}" type="application/json">{html.escape(raw)}</script>'


def _badge(text: Any, cls: str = "") -> str:
    return f'<span class="badge {esc(cls)}">{esc(text)}</span>'


def _long(value: Any, cls: str = "") -> str:
    text = str(value or "")
    return f'<span class="long-name {esc(cls)}" title="{esc(text)}">{esc(short_name(text))}</span>'


def _kpi(label: str, value: Any, sub: str = "") -> str:
    return f"""
    <div class="kpi-card">
      <div class="kpi-label">{esc(label)}</div>
      <div class="kpi-value">{esc(value)}</div>
      <div class="kpi-sub">{esc(sub)}</div>
    </div>
    """


def _component_stack(manifest: Mapping[str, Any]) -> str:
    comps = manifest.get("components", []) or []
    chips = []
    for comp in comps:
        role = str(comp.get("role") or "")
        cls = "base" if role == "base_full" else "update"
        scope = ",".join(comp.get("scope", []) or [])
        chips.append(
            f'<div class="stack-chip {cls}">'
            f'<div class="stack-role">{esc("基线" if role == "base_full" else "更新")}</div>'
            f'<div class="stack-name" title="{esc(comp.get("version_id"))}">{esc(short_name(str(comp.get("version_id") or ""), 18, 12))}</div>'
            f'<div class="stack-scope">{esc(scope or "-")}</div>'
            f'</div>'
        )
    if not chips:
        chips.append('<div class="empty-note">未设置当前可用组合</div>')
    joiners = '<span class="stack-plus">+</span>'.join(chips)
    return f'<div class="stack-row">{joiners}</div>'


def _summary_tags(data: Mapping[str, Any] | None) -> str:
    if not data:
        return '<span class="muted">-</span>'
    tags = []
    for key, value in sorted(data.items()):
        if isinstance(value, (dict, list)):
            continue
        tags.append(f'<span class="tiny-tag">{esc(key)}:{esc(value)}</span>')
    return "".join(tags) or '<span class="muted">-</span>'


def _version_evidence_panel(manifest: Mapping[str, Any]) -> str:
    evidence = manifest.get("version_evidence", {}) or {}
    rows = evidence.get("components", []) or []
    if not rows:
        return '<div class="empty-note">No source version evidence has been attached to this effective manifest.</div>'
    body = []
    for row in rows:
        diff_html = str(row.get("adjacent_diff_html") or "")
        diff_cell = (
            f'<a class="link-pill" href="{esc(diff_html)}">diff html</a>'
            if diff_html
            else _badge(row.get("diff_status") or "-", "soft")
        )
        body.append(f"""
        <tr data-search="{esc(str(row.get('version_id')).lower())} {esc(str(row.get('scan_status')).lower())} {esc(str(row.get('diff_status')).lower())}">
          <td>{_long(row.get('version_id'))}<div class="muted mini">{esc(row.get('role') or '')}</div></td>
          <td>{_badge(row.get('scan_status') or '-', 'soft')}<div class="muted mini">{esc(row.get('scan_mode') or '')}</div></td>
          <td>{diff_cell}<div class="muted mini">adjacent_old_version: {esc(row.get('adjacent_old_version') or '-')}</div></td>
          <td>{_summary_tags(row.get('parser_summary') or {})}</td>
          <td>{_summary_tags(row.get('diff_summary') or {})}</td>
          <td class="path-cell muted" title="{esc(row.get('raw_path'))}">{esc(short_name(str(row.get('raw_path') or ''), 34, 20))}</td>
        </tr>
        """)
    summary = evidence.get("summary", {}) or {}
    return f"""
    <div class="table-toolbar">
      <span class="muted">scanned {esc(summary.get('scanned_components', 0))} / diff-ready {esc(summary.get('diff_ready_components', 0))} / parser {esc(summary.get('parser_components', 0))}</span>
      <input class="table-filter" data-target="version-evidence" placeholder="Filter version evidence..." />
    </div>
    <div class="table-scroll compact-scroll">
      <table class="data-table" id="version-evidence">
        <thead><tr><th>source version</th><th>scan</th><th>update detail</th><th>parser_summary</th><th>diff_summary</th><th>raw path</th></tr></thead>
        <tbody>{''.join(body)}</tbody>
      </table>
    </div>
    """


def _scope_heatmap(manifest: Mapping[str, Any]) -> str:
    data = update_scope_heatmap(manifest) if update_scope_heatmap else {"views": [], "rows": []}
    views = data.get("views", []) or []
    rows = data.get("rows", []) or []
    if not views or not rows:
        return '<div class="empty-note">无 scope heatmap 数据</div>'
    head = ''.join(f'<th>{esc(v)}</th>' for v in views)
    body = []
    max_count = 1
    for row in rows:
        max_count = max(max_count, max((row.get("counts", {}) or {}).values() or [0]))
    for row in rows:
        cells = []
        for v in views:
            count = int((row.get("counts", {}) or {}).get(v, 0) or 0)
            level = 0 if count == 0 else min(5, 1 + int((count / max_count) * 4))
            label = "" if count == 0 else str(count)
            cells.append(f'<td><span class="heat-cell level-{level}" title="{esc(v)}: {count}">{esc(label)}</span></td>')
        scope = ",".join(row.get("scope", []) or [])
        role = "基线" if row.get("role") == "base_full" else "更新"
        body.append(
            f'<tr><th class="sticky-col">{_long(row.get("version_id"))}<div class="muted mini">{esc(role)} · {esc(scope or "-")}</div></th>{"".join(cells)}</tr>'
        )
    return f"""
    <div class="table-scroll heatmap-wrap">
      <table class="matrix-table heatmap-table">
        <thead><tr><th class="sticky-col">版本</th>{head}</tr></thead>
        <tbody>{''.join(body)}</tbody>
      </table>
    </div>
    """


def _compare_matrix(manifest: Mapping[str, Any]) -> str:
    data = compare_matrix(manifest) if compare_matrix else {"rows": []}
    rows = data.get("rows", []) or []
    if not rows:
        return '<div class="empty-note">无 Compare Matrix 数据</div>'
    body = []
    for row in rows:
        by_type = row.get("by_type", {}) or {}
        type_tags = ''.join(f'<span class="tiny-tag">{esc(k)}:{esc(v)}</span>' for k, v in by_type.items())
        role = "基线" if row.get("role") == "base_full" else "更新"
        body.append(f"""
        <tr>
          <td>{_long(row.get('version_id'))}<div class="muted mini">{esc(role)}</div></td>
          <td class="num">{esc(row.get('base', 0))}</td>
          <td class="num good">{esc(row.get('add', 0))}</td>
          <td class="num warn">{esc(row.get('replace', 0))}</td>
          <td class="num danger">{esc(row.get('delete', 0))}</td>
          <td>{type_tags}</td>
        </tr>
        """)
    return f"""
    <div class="table-scroll compact-scroll">
      <table class="data-table">
        <thead><tr><th>组件版本</th><th>base</th><th>add</th><th>replace</th><th>delete</th><th>按类型</th></tr></thead>
        <tbody>{''.join(body)}</tbody>
      </table>
    </div>
    """


def _effective_file_table(manifest: Mapping[str, Any]) -> str:
    files = manifest.get("effective_files", {}) or {}
    rows = []
    for rel, info in sorted(files.items()):
        op = str(info.get("operation") or "")
        rows.append(f"""
        <tr data-search="{esc(str(rel).lower())} {esc(str(info.get('source_version')).lower())} {esc(str(info.get('file_type')).lower())} {esc(op.lower())}">
          <td class="path-cell" title="{esc(rel)}">{esc(rel)}</td>
          <td>{_badge(info.get('file_type', 'other'), 'soft')}</td>
          <td>{_long(info.get('source_version'))}</td>
          <td>{_badge(op, 'op-' + op)}</td>
          <td>{_long(info.get('replaced_from') or '-')}</td>
          <td class="path-cell muted" title="{esc(info.get('source_path'))}">{esc(short_name(str(info.get('source_path') or ''), 28, 18))}</td>
        </tr>
        """)
    return f"""
    <div class="table-toolbar">
      <input class="table-filter" data-target="effective-files" placeholder="搜索文件 / 来源版本 / 类型..." />
      <span class="muted">共 {len(rows)} 个有效文件；表格固定高度，可滚动。</span>
    </div>
    <div class="table-scroll tall-scroll">
      <table class="data-table" id="effective-files">
        <thead><tr><th>有效文件</th><th>类型</th><th>来源版本</th><th>操作</th><th>替换自</th><th>source path</th></tr></thead>
        <tbody>{''.join(rows)}</tbody>
      </table>
    </div>
    """


def _release_delta_table(preview: Mapping[str, Any] | None) -> str:
    if not preview:
        return '<div class="empty-note">未生成 Release Delta Preview</div>'
    delta = preview.get("delta", []) or []
    rows = []
    for row in delta:
        action = str(row.get("action") or "")
        rows.append(f"""
        <tr data-search="{esc(str(row.get('relpath')).lower())} {esc(str(row.get('source_version')).lower())} {esc(str(row.get('file_type')).lower())} {esc(action.lower())}">
          <td>{_badge(action, 'op-' + action)}</td>
          <td class="path-cell" title="{esc(row.get('relpath'))}">{esc(row.get('relpath'))}</td>
          <td>{_badge(row.get('file_type', 'other'), 'soft')}</td>
          <td>{_long(row.get('source_version'))}</td>
          <td class="path-cell muted" title="{esc(row.get('release_path'))}">{esc(short_name(str(row.get('release_path') or ''), 34, 20))}</td>
        </tr>
        """)
    return f"""
    <div class="table-toolbar">
      <input class="table-filter" data-target="release-delta" placeholder="搜索 release delta..." />
      <span class="muted">本次变化 {len(rows)} 个文件；keep 文件默认不列出。</span>
    </div>
    <div class="table-scroll tall-scroll">
      <table class="data-table" id="release-delta">
        <thead><tr><th>动作</th><th>release 文件</th><th>类型</th><th>来源版本</th><th>release path</th></tr></thead>
        <tbody>{''.join(rows)}</tbody>
      </table>
    </div>
    """


def _conflicts(manifest: Mapping[str, Any]) -> str:
    conflicts = manifest.get("conflicts", []) or []
    if not conflicts:
        return '<div class="ok-panel">无冲突。partial 缺文件不会被视为删除；删除只接受显式 tombstone。</div>'
    rows = []
    for c in conflicts:
        rows.append(f"<tr><td>{esc(c.get('type'))}</td><td>{_long(c.get('version_id') or c.get('file') or '-')}</td><td>{esc(c.get('message'))}</td></tr>")
    return f"""
    <div class="alert-panel">检测到 {len(conflicts)} 个需要确认的问题。release apply 前建议先处理。</div>
    <div class="table-scroll compact-scroll"><table class="data-table"><thead><tr><th>类型</th><th>对象</th><th>说明</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div>
    """


def _command_examples(manifest: Mapping[str, Any], preview: Mapping[str, Any] | None) -> str:
    lib = manifest.get("library_name") or manifest.get("library_id") or "ucie"
    eid = manifest.get("effective_id") or "E3"
    return f"""
    <details class="command-panel">
      <summary>命令示例</summary>
      <pre><code># 构建 effective manifest\n$PROJ/scripts/lg_effective.csh build --catalog catalog/catalog.json --library {esc(lib)} --base-full BASE_FULL --include ADHOC_01 --scope ADHOC_01:liberty --effective-id {esc(eid)}\n\n# 在当前 effective 上追加一次 adhoc\n$PROJ/scripts/lg_effective.csh add --catalog catalog/catalog.json --current catalog/effective/{esc(lib)}/{esc(eid)}/effective_manifest.json --version ADHOC_02 --scope lef --effective-id E_NEXT\n\n# 生成 release preview，不直接发布\n$PROJ/scripts/lg_effective.csh release-preview --effective catalog/effective/{esc(lib)}/{esc(eid)}/effective_manifest.json --release-root $WORK/release_area --release-id R_NEXT --out-dir catalog/effective/{esc(lib)}/{esc(eid)}/release_preview</code></pre>
    </details>
    """


def render_effective_report(manifest: Mapping[str, Any], release_preview: Mapping[str, Any] | None = None) -> str:
    summary = manifest.get("summary", {}) or {}
    preview_summary = (release_preview or {}).get("summary", {}) if release_preview else {}
    conflicts = manifest.get("conflicts", []) or []
    kpis = ''.join([
        _kpi("有效文件", summary.get("file_count", len(manifest.get("effective_files", {}) or {})), "effective_files"),
        _kpi("组件数", summary.get("component_count", len(manifest.get("components", []) or [])), "base + updates"),
        _kpi("Release Delta", preview_summary.get("delta_files", "-"), "相对上次发布变化"),
        _kpi("冲突", len(conflicts), "scope / repeated replace"),
    ])
    html_doc = f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>Effective Release Preview · {esc(manifest.get('library_name') or manifest.get('library_id'))}</title>
<style>
:root {{ --bg:#f5f7fb; --panel:#fff; --text:#172033; --muted:#667085; --line:#d9e0ea; --blue:#2563eb; --purple:#7c3aed; --green:#0f8a5f; --orange:#c76a00; --red:#b42318; --chip:#eef2ff; }}
* {{ box-sizing:border-box; }}
body {{ margin:0; font-family:Inter, "Segoe UI", Arial, sans-serif; color:var(--text); background:var(--bg); }}
.page {{ max-width:1440px; margin:0 auto; padding:24px; }}
.hero {{ background:linear-gradient(135deg,#101828,#243b6b); color:#fff; border-radius:24px; padding:24px; box-shadow:0 20px 60px rgba(16,24,40,.18); }}
.hero h1 {{ margin:0 0 8px; font-size:26px; }}
.hero .sub {{ color:#cfd8ea; line-height:1.6; }}
.hero-grid {{ display:grid; grid-template-columns:1fr auto; gap:18px; align-items:start; }}
.version-pill {{ display:inline-flex; max-width:520px; padding:8px 12px; border-radius:999px; background:rgba(255,255,255,.12); border:1px solid rgba(255,255,255,.18); font-family:Consolas,monospace; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }}
.kpi-grid {{ display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:14px; margin:18px 0; }}
.kpi-card, .card {{ background:var(--panel); border:1px solid var(--line); border-radius:18px; box-shadow:0 10px 30px rgba(16,24,40,.06); }}
.kpi-card {{ padding:18px; }}
.kpi-label {{ color:var(--muted); font-size:13px; }}
.kpi-value {{ margin-top:8px; font-size:28px; font-weight:800; }}
.kpi-sub {{ color:var(--muted); font-size:12px; margin-top:4px; }}
.card {{ padding:18px; margin:16px 0; }}
.card h2 {{ margin:0 0 12px; font-size:18px; }}
.grid-2 {{ display:grid; grid-template-columns:1fr 1fr; gap:16px; }}
.stack-row {{ display:flex; align-items:stretch; gap:10px; overflow-x:auto; padding-bottom:6px; }}
.stack-plus {{ display:flex; align-items:center; color:var(--muted); font-weight:800; }}
.stack-chip {{ flex:0 0 230px; border:1px solid var(--line); border-radius:16px; padding:12px; background:#fafcff; }}
.stack-chip.base {{ border-color:#bfdbfe; background:#eff6ff; }}
.stack-chip.update {{ border-color:#ddd6fe; background:#f5f3ff; }}
.stack-role {{ font-size:12px; color:var(--muted); }}
.stack-name {{ margin-top:4px; font-weight:800; font-family:Consolas,monospace; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }}
.stack-scope {{ margin-top:6px; font-size:12px; color:var(--muted); }}
.badge, .tiny-tag {{ display:inline-flex; align-items:center; border-radius:999px; padding:4px 8px; font-size:12px; font-weight:700; background:#eef2ff; color:#344054; margin:2px; }}
.tiny-tag {{ padding:3px 6px; font-weight:600; }}
.link-pill {{ display:inline-flex; align-items:center; border-radius:999px; padding:4px 8px; font-size:12px; font-weight:700; background:#dcfce7; color:#166534; text-decoration:none; }}
.soft {{ background:#f2f4f7; }}
.op-base {{ background:#e0f2fe; color:#075985; }}
.op-add {{ background:#dcfce7; color:#166534; }}
.op-replace {{ background:#fef3c7; color:#92400e; }}
.op-delete {{ background:#fee2e2; color:#991b1b; }}
.op-keep {{ background:#f2f4f7; color:#475467; }}
.table-toolbar {{ display:flex; justify-content:space-between; align-items:center; gap:12px; margin-bottom:10px; }}
.table-filter {{ width:340px; max-width:100%; border:1px solid var(--line); border-radius:12px; padding:10px 12px; font-size:14px; }}
.table-scroll {{ overflow:auto; border:1px solid var(--line); border-radius:14px; background:#fff; }}
.tall-scroll {{ max-height:460px; }}
.compact-scroll {{ max-height:320px; }}
table {{ border-collapse:separate; border-spacing:0; width:100%; }}
th, td {{ padding:10px 12px; border-bottom:1px solid #eef2f6; text-align:left; vertical-align:top; }}
th {{ position:sticky; top:0; z-index:2; background:#f8fafc; color:#475467; font-size:12px; text-transform:uppercase; letter-spacing:.04em; }}
.sticky-col {{ position:sticky; left:0; z-index:3; background:#fff; min-width:240px; }}
thead .sticky-col {{ background:#f8fafc; z-index:4; }}
.path-cell {{ max-width:460px; font-family:Consolas,monospace; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }}
.long-name {{ display:inline-block; max-width:260px; vertical-align:bottom; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; font-family:Consolas,monospace; }}
.muted {{ color:var(--muted); }}
.mini {{ font-size:12px; margin-top:4px; }}
.num {{ text-align:right; font-variant-numeric:tabular-nums; font-weight:800; }}
.good {{ color:var(--green); }} .warn {{ color:var(--orange); }} .danger {{ color:var(--red); }}
.heatmap-wrap {{ max-height:360px; }}
.heat-cell {{ display:inline-flex; min-width:34px; height:24px; align-items:center; justify-content:center; border-radius:7px; background:#f2f4f7; font-size:12px; font-weight:800; }}
.level-0 {{ background:#f2f4f7; color:transparent; }} .level-1 {{ background:#dbeafe; }} .level-2 {{ background:#bfdbfe; }} .level-3 {{ background:#93c5fd; }} .level-4 {{ background:#60a5fa; color:#fff; }} .level-5 {{ background:#2563eb; color:#fff; }}
.ok-panel, .alert-panel, .empty-note {{ border-radius:14px; padding:14px; background:#f0fdf4; color:#166534; border:1px solid #bbf7d0; }}
.alert-panel {{ background:#fff7ed; color:#9a3412; border-color:#fed7aa; margin-bottom:10px; }}
.empty-note {{ background:#f8fafc; color:var(--muted); border-color:var(--line); }}
.command-panel {{ background:#111827; color:#e5e7eb; border-radius:18px; padding:16px; }}
.command-panel summary {{ cursor:pointer; font-weight:800; }}
pre {{ white-space:pre-wrap; overflow:auto; margin:12px 0 0; }}
@media (max-width: 980px) {{ .kpi-grid, .grid-2, .hero-grid {{ grid-template-columns:1fr; }} .table-toolbar {{ flex-direction:column; align-items:stretch; }} }}
</style>
</head>
<body>
<div class="page">
  <section class="hero">
    <div class="hero-grid">
      <div>
        <h1>{esc(manifest.get('library_name') or manifest.get('library_id'))} · 当前可用组合</h1>
        <div class="sub">基于 effective_files 的文件级来源映射。partial 缺文件不会被视为删除；release 预览基于完整有效文件表，而不是 adhoc 目录。</div>
      </div>
      <div class="version-pill" title="{esc(manifest.get('effective_id'))}">{esc(manifest.get('effective_id'))}</div>
    </div>
  </section>
  <section class="kpi-grid">{kpis}</section>
  <section class="card"><h2>Effective Stack</h2>{_component_stack(manifest)}</section>
  <section class="card"><h2>Version Evidence</h2>{_version_evidence_panel(manifest)}</section>
  <section class="grid-2">
    <div class="card"><h2>Update Scope Heatmap</h2>{_scope_heatmap(manifest)}</div>
    <div class="card"><h2>Compare Matrix</h2>{_compare_matrix(manifest)}</div>
  </section>
  <section class="card"><h2>风险与冲突</h2>{_conflicts(manifest)}</section>
  <section class="card"><h2>有效文件来源表</h2>{_effective_file_table(manifest)}</section>
  <section class="card"><h2>Release Delta Preview</h2>{_release_delta_table(release_preview)}</section>
  {_command_examples(manifest, release_preview)}
</div>
{_json_script('effective-manifest-json', manifest)}
{_json_script('release-preview-json', release_preview or {})}
<script>
document.querySelectorAll('.table-filter').forEach(function(input) {{
  input.addEventListener('input', function() {{
    var target = document.getElementById(input.dataset.target);
    if (!target) return;
    var q = input.value.trim().toLowerCase();
    target.querySelectorAll('tbody tr').forEach(function(row) {{
      var text = row.dataset.search || row.textContent.toLowerCase();
      row.style.display = text.indexOf(q) >= 0 ? '' : 'none';
    }});
  }});
}});
</script>
</body>
</html>"""
    return html_doc


def write_effective_report(manifest: Mapping[str, Any], release_preview: Mapping[str, Any] | None, out_html: str | Path) -> Path:
    out = Path(out_html)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_effective_report(manifest, release_preview), encoding="utf-8")
    return out
