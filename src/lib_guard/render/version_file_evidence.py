"""Human-readable file structure and evidence section for Version Detail.

The Version Detail page remains the only user-facing review projection. This
module renders its structural file tree and complete evidence table without
creating a second HTML page or a second data source.
"""

from __future__ import annotations

from typing import Any, Mapping
from pathlib import Path

from lib_guard.render import product_theme as ui
from lib_guard.view_types import canonical_view_type, usage_area_for_view, view_label
from lib_guard.render.version_review_model import build_ip_change_projection


def _as_mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _evidence_records(model: Mapping[str, Any]) -> list[dict[str, Any]]:
    scan_evidence = _as_mapping(model.get("scan_evidence"))
    inventory = _as_mapping(scan_evidence.get("inventory"))
    roots = _as_mapping(model.get("source_roots"))
    current_root = roots.get("current") or inventory.get("root_path") or _as_mapping(scan_evidence.get("context")).get("raw_path")
    scanned_paths = {
        str(item.get("path") or item.get("relpath") or item.get("file") or "-"): str(item.get("abs_path") or "")
        for item in inventory.get("files", []) or [] if isinstance(item, Mapping)
    }
    logical_paths = {
        str(item.get("logical_path") or ""): item
        for item in _as_mapping(model.get("file_diff")).get("logical_path_changes", []) or []
        if isinstance(item, Mapping)
    }

    def source_path(path: str, change: str) -> str:
        if path == "-":
            return ""
        mapping = _as_mapping(logical_paths.get(path))
        path = str(mapping.get("old" if change == "removed" else "new") or path)
        if change != "removed" and scanned_paths.get(path):
            return scanned_paths[path]
        root = roots.get("base") if change == "removed" else current_root
        if Path(path).is_absolute():
            return path
        if not root or not Path(str(root)).is_absolute() or ".." in Path(path).parts:
            return ""
        return str(Path(str(root)) / path)

    raw_changes = [item for item in model.get("file_changes", []) or [] if isinstance(item, Mapping)]
    projection = build_ip_change_projection(model, raw_changes)
    changes = projection['visible_changes'] + projection['baseline_only_changes']
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in changes:
        original_path = str(item.get("path") or "-")
        raw_change = str(item.get('change') or '').lower()
        mapped = _as_mapping(logical_paths.get(original_path))
        path = str(mapped.get('old' if raw_change == 'removed' else 'new') or original_path)
        seen.add(path)
        view_type = canonical_view_type(item.get("file_type"))
        rows.append(
            {
                "change": str(item.get("display_change") or item.get("change") or "").lower(),
                "view_type": view_type,
                "view": view_label(view_type),
                "path": path,
                "source_path": source_path(original_path, raw_change),
                "area": usage_area_for_view(view_type),
            }
        )

    for item in inventory.get("files", []) or []:
        if not isinstance(item, Mapping):
            continue
        path = str(item.get("path") or item.get("relpath") or item.get("file") or "-")
        if path in seen:
            continue
        view_type = canonical_view_type(item.get("file_type"))
        rows.append(
            {
                "change": "current",
                "view_type": view_type,
                "view": view_label(view_type),
                "path": path,
                "source_path": source_path(path, "current"),
                "area": usage_area_for_view(view_type),
            }
        )

    rows.sort(key=lambda item: (item["view"], item["path"]))
    return rows


def _tree_status(value: Any) -> str:
    text = str(value or "current").strip().lower()
    return text if text in TREE_STATUS_LABELS else "current"


TREE_STATUS_LABELS = {
    'added': '新增', 'removed': '删除', 'changed': '修改', 'current': '本版文件',
    'unmatched_new': '本版待核对', 'unmatched_base': '基准版待核对',
    'baseline_only': '本包未交付',
}
BASELINE_STATUSES = {'removed', 'unmatched_base', 'baseline_only'}


def _tree_status_label(value: str) -> str:
    return TREE_STATUS_LABELS.get(value, '本版文件')


def _tree_node() -> dict[str, Any]:
    return {"dirs": {}, "files": [], "counts": dict.fromkeys(TREE_STATUS_LABELS, 0)}


def _tree_add_record(root: dict[str, Any], record: Mapping[str, Any]) -> None:
    path = str(record.get("path") or "-").replace("\\", "/").strip("/") or "-"
    parts = [part for part in path.split("/") if part]
    if not parts:
        parts = ["-"]
    status = _tree_status(record.get("change"))
    node = root
    node["counts"][status] += 1
    for part in parts[:-1]:
        node = node["dirs"].setdefault(part, _tree_node())
        node["counts"][status] += 1
    node["files"].append({**record, "path": path, "name": parts[-1], "status": status})


def _tree_count_text(counts: Mapping[str, Any]) -> str:
    parts = []
    for status, marker in (("added", "+"), ("removed", "-"), ("changed", "~"), ("current", "")):
        count = int(counts.get(status) or 0)
        if count:
            parts.append(f"{marker}{count}" if marker else f"{count} 文件")
    for status in ('unmatched_new', 'unmatched_base', 'baseline_only'):
        if counts.get(status):
            parts.append(f"{TREE_STATUS_LABELS[status]} {counts[status]}")
    return " / ".join(parts) or "空目录"


def _tree_file_html(record: Mapping[str, Any]) -> str:
    status = _tree_status(record.get("status"))
    view = str(record.get("view") or "-")
    area = str(record.get("area") or "-")
    searchable = " ".join(str(record.get(key) or "") for key in ("path", "view", "area", "lane", "meaning"))
    raw = str(record.get("source_path") or "")
    location = (
        "<details class='tree-source-path'><summary>原始路径</summary>"
        + _source_path_row("基准版文件" if status in BASELINE_STATUSES else "本版文件", raw)
        + "</details>"
    ) if raw else ""
    return (
        "<li class='tree-file' "
        f"data-tree-status='{ui.esc(status)}' data-tree-view-type='{ui.esc(record.get('view_type') or '')}' "
        f"data-tree-area='{ui.esc(area)}' data-tree-search='{ui.esc(searchable.lower())}'>"
        f"<span class='tree-file-mark {ui.esc(status)}'>{ui.esc(_tree_status_label(status))}</span>"
        f"<code title='{ui.esc(record.get('path'))}'>{ui.esc(record.get('name'))}</code>"
        f"<span class='tree-file-meta'>{ui.esc(view)} / {ui.esc(area)}</span>"
        + location +
        "</li>"
    )


def _source_path_row(label: str, path: str) -> str:
    return (
        f"<div class='source-path-row'><span>{ui.esc(label)}</span><code>{ui.esc(path)}</code>"
        f"<button type='button' class='btn secondary' title='复制{ui.esc(label)}路径' "
        f"aria-label='复制{ui.esc(label)}路径' data-source-path='{ui.esc(path)}' "
        "onclick='copyText(this.dataset.sourcePath, this)'>复制</button></div>"
    )


def _source_roots_html(model: Mapping[str, Any]) -> str:
    roots = _as_mapping(model.get("source_roots"))
    inventory = _as_mapping(_as_mapping(model.get("scan_evidence")).get("inventory"))
    current = roots.get("current") or inventory.get("root_path")
    return "<div class='source-roots'>" + "".join(
        _source_path_row(label, str(path))
        for label, path in (("本版源目录", current), ("基准版源目录", roots.get("base"))) if path
    ) + "</div>" if current or roots.get("base") else ""


def _tree_folder_html(name: str, node: Mapping[str, Any], depth: int = 0) -> str:
    folder_search = " ".join([name, _tree_count_text(_as_mapping(node.get("counts")))])
    open_attr = " open" if depth < 2 else ""
    children = []
    for child_name in sorted(_as_mapping(node.get("dirs")).keys(), key=str.casefold):
        child = _as_mapping(_as_mapping(node.get("dirs")).get(child_name))
        children.append(_tree_folder_html(str(child_name), child, depth + 1))
    for item in sorted(node.get("files", []) or [], key=lambda value: str(_as_mapping(value).get("name") or "").casefold()):
        children.append(_tree_file_html(_as_mapping(item)))
    return (
        f"<li class='tree-folder' data-tree-search='{ui.esc(folder_search.lower())}'>"
        f"<details{open_attr}><summary><span class='tree-folder-name'><span class='tree-folder-icon' aria-hidden='true'>▸</span>{ui.esc(name)}</span>"
        f"<span class='tree-folder-count'>{ui.esc(_tree_count_text(_as_mapping(node.get('counts'))))}</span></summary>"
        f"<ul>{''.join(children)}</ul></details></li>"
    )


def _file_tree_html(model: Mapping[str, Any], default_filter: str) -> str:
    root = _tree_node()
    for record in _evidence_records(model):
        _tree_add_record(root, record)
    children = []
    for name in sorted(root["dirs"], key=str.casefold):
        children.append(_tree_folder_html(str(name), _as_mapping(root["dirs"][name])))
    for item in sorted(root["files"], key=lambda value: str(_as_mapping(value).get("name") or "").casefold()):
        children.append(_tree_file_html(_as_mapping(item)))
    if not children:
        return "<div class='tree-empty'>当前没有可展示的文件结构。</div>"
    return f"<ul class='file-tree' data-file-tree data-tree-filter='{ui.esc(default_filter)}'>" + "".join(children) + "</ul>"


def _file_tree_controls(records: list[Mapping[str, Any]], current_total: int, change_total: int, default_filter: str) -> str:
    total = len(records)
    labels = {
        "changes": f"变化文件 <b>{change_total}</b>",
        "current": f"当前交付 <b>{current_total}</b>",
        "all": f"全部证据 <b>{total}</b>",
    }
    chips = "".join(
        f"<button type='button' class='tree-filter-chip{' active' if status == default_filter else ''}' data-tree-filter='{status}' onclick=\"filterFileTree('{status}', this)\">{labels[status]}</button>"
        for status in ("changes", "current", "all")
    )
    view_options = {}
    area_options = set()
    change_counts = dict.fromkeys(TREE_STATUS_LABELS, 0)
    for record in records:
        view_type = str(record.get("view_type") or "other")
        view_options[view_type] = str(record.get("view") or view_type)
        area = str(record.get("area") or "其他场景")
        if area and area != "-":
            area_options.add(area)
        change_counts[_tree_status(record.get("change"))] += 1
    view_select = "<option value='all'>全部视图</option>" + "".join(
        f"<option value='{ui.esc(value)}'>{ui.esc(label)}</option>"
        for value, label in sorted(view_options.items(), key=lambda item: item[1])
    )
    area_select = "<option value='all'>全部场景</option>" + "".join(
        f"<option value='{ui.esc(value)}'>{ui.esc(value)}</option>"
        for value in sorted(area_options)
    )
    change_labels = TREE_STATUS_LABELS
    change_select = "<option value='all'>全部类型</option>" + "".join(
        f"<option value='{status}'>{change_labels[status]}（{change_counts[status]}）</option>"
        for status in TREE_STATUS_LABELS
        if change_counts[status]
    )
    return (
        "<div class='file-tree-toolbar'>"
        "<label class='tree-search'><span>搜索</span><input id='file-tree-search' type='search' placeholder='搜索目录、文件名或视图' oninput=\"filterFileTree()\"></label>"
        f"<div class='tree-filters'>{chips}</div>"
        f"<label class='tree-select'><span>变化类型</span><select id='file-tree-change-filter' data-tree-change-filter onchange=\"filterFileTree()\">{change_select}</select></label>"
        f"<label class='tree-select'><span>视图类型</span><select id='file-tree-view-filter' data-tree-view-filter onchange=\"filterFileTree()\">{view_select}</select></label>"
        f"<label class='tree-select'><span>使用场景</span><select id='file-tree-area-filter' data-tree-area-filter onchange=\"filterFileTree()\">{area_select}</select></label>"
        "<div class='tree-actions'><button type='button' class='btn secondary' data-tree-reset onclick=\"resetFileTreeFilters()\">清除筛选</button><button type='button' class='btn secondary' onclick=\"setFileTreeOpen(true)\">全部展开</button><button type='button' class='btn secondary' onclick=\"setFileTreeOpen(false)\">全部收起</button></div>"
        f"<div class='tree-count'><span id='file-tree-visible'>{current_total if default_filter == 'current' else change_total}</span> 项；当前交付 <b>{current_total}</b>；全部证据 <b>{total}</b></div>"
        "</div>"
    )


def render_version_file_evidence_section(model: Mapping[str, Any]) -> str:
    records = _evidence_records(model)
    default_filter = "current" if str(model.get("review_mode") or "").lower() == "first_version" else "changes"
    scan_evidence = _as_mapping(model.get("scan_evidence"))
    current_total = int(scan_evidence.get("file_total") or 0)
    if not current_total:
        current_total = sum(1 for item in records if _tree_status(item.get("change")) not in BASELINE_STATUSES)
    change_total = sum(1 for item in records if _tree_status(item.get("change")) != "current")
    body = (
        "<style>"
        ".source-path-row{display:grid;grid-template-columns:90px minmax(0,1fr) 52px;align-items:start;gap:10px;padding:8px 0;font-size:12px}.source-path-row code{overflow-wrap:anywhere;user-select:all}.source-path-row .btn{padding:3px 8px;min-height:26px}.source-roots{border-bottom:1px solid var(--line);margin-bottom:12px}.tree-source-path{grid-column:2 / -1;min-width:0}.tree-source-path summary{cursor:pointer;color:#156b6b;font-size:12px}.tree-source-path .source-path-row{background:#f3f6f7;padding:8px;border-radius:4px}"
        ".file-evidence-section .panel-body{padding-top:12px}"
        ".file-tree-scroll{max-height:min(58vh,560px);overflow:auto;border:1px solid var(--line);border-radius:10px;background:#fbfcff;padding:10px 12px;scrollbar-gutter:stable}"
        ".file-tree,.file-tree ul{list-style:none;margin:0;padding:0}.file-tree ul{padding-left:22px}.tree-folder{margin:1px 0}.tree-folder details{border-left:1px solid #d9e2ea}.tree-folder summary{display:flex;align-items:center;justify-content:space-between;gap:12px;min-height:34px;padding:5px 8px;cursor:pointer;border-radius:7px;color:#243746}.tree-folder summary:hover{background:#eef5f5}.tree-folder summary:focus-visible,.tree-filter-chip:focus-visible,.tree-search:focus-within,.tree-select:focus-within{outline:3px solid rgba(21,94,239,.22);outline-offset:1px}.tree-folder-name{display:flex;align-items:center;gap:7px;font-weight:800;min-width:0}.tree-folder-icon{display:inline-flex;align-items:center;justify-content:center;width:14px;color:#5b7280;font-size:14px;transition:transform .15s}.tree-folder details[open]>summary .tree-folder-icon{transform:rotate(90deg)}.tree-folder-count{flex:0 0 auto;color:#758594;font:12px var(--mono);white-space:nowrap}"
        ".tree-file{display:grid;grid-template-columns:54px minmax(260px,1fr) minmax(230px,.8fr);gap:9px;align-items:center;min-height:32px;padding:4px 8px 4px 22px;border-left:1px solid #d9e2ea}.tree-file:hover{background:#f0f7f7}.tree-file code{overflow-wrap:anywhere;word-break:break-word;color:#1e3b4b}.tree-file-meta{color:#71808b;font-size:12px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.tree-file-mark{display:inline-flex;justify-content:center;width:46px;border-radius:4px;padding:2px 4px;font-size:11px;font-weight:800}.tree-file-mark.added{color:#087443;background:#e9f7f0}.tree-file-mark.removed{color:#ae3b2c;background:#fff0ed}.tree-file-mark.changed{color:#a35c08;background:#fff3df}.tree-file-mark.current{color:#1e5baa;background:#e9f1ff}.tree-hidden{display:none!important}.tree-empty{padding:24px;text-align:center;color:var(--muted);border:1px dashed var(--line);border-radius:9px}"
        ".file-tree-toolbar{display:grid;grid-template-columns:minmax(230px,1.2fr) minmax(210px,1fr) minmax(150px,.7fr) minmax(150px,.7fr);gap:10px;align-items:center;margin-bottom:10px}.tree-search{display:flex;align-items:center;gap:8px;min-width:0;border:1px solid var(--line);border-radius:999px;background:#fff;padding:7px 12px}.tree-search span,.tree-select span{font-size:12px;color:var(--muted);font-weight:800;white-space:nowrap}.tree-search input{width:100%;border:0;outline:0;background:transparent;font-size:13px}.tree-filters{display:flex;gap:6px;flex-wrap:wrap}.tree-filter-chip{border:1px solid var(--line);border-radius:999px;background:#fff;color:#344054;padding:6px 10px;font-size:12px;font-weight:700;cursor:pointer}.tree-filter-chip.active{border-color:#9cc2ff;background:#eef4ff;color:#1849a9}.tree-select{display:flex;align-items:center;gap:6px;min-width:0;border:1px solid var(--line);border-radius:8px;background:#fff;padding:5px 8px}.tree-select select{width:100%;min-width:0;border:0;outline:0;background:transparent;color:#344054;font-size:12px}.tree-actions{display:flex;gap:6px;flex-wrap:wrap}.tree-actions .btn{min-height:32px}.tree-count{grid-column:1 / -1;color:var(--muted);font-size:12px;font-weight:800;white-space:nowrap}.file-tree-note{margin:0 0 12px;color:var(--muted);font-size:12px}.file-tree-legend{display:flex;gap:12px;flex-wrap:wrap;margin-top:10px;color:var(--muted);font-size:12px}.file-tree-legend span{display:inline-flex;align-items:center;gap:5px}.file-tree-legend i{display:inline-block;width:9px;height:9px;border-radius:2px}.file-tree-legend .added{background:#43a782}.file-tree-legend .removed{background:#c85545}.file-tree-legend .changed{background:#d4862a}.file-tree-legend .current{background:#4b86c5}@media(max-width:1100px){.file-tree-toolbar{grid-template-columns:1fr 1fr}.tree-actions{justify-content:flex-start}.tree-count{grid-column:1 / -1}}@media(max-width:760px){.tree-file{grid-template-columns:54px minmax(0,1fr)}.tree-file-meta{grid-column:2}.file-tree-toolbar{grid-template-columns:1fr}.tree-count{grid-column:auto;justify-self:start}}"
        ".tree-file{grid-template-columns:90px minmax(0,1fr) minmax(120px,.65fr) 72px}.tree-file-mark{width:auto}.tree-file-mark.unmatched_new,.tree-file-mark.unmatched_base{color:#70510e;background:#fff3df}.tree-source-path{grid-column:auto}.tree-source-path[open]{grid-column:2 / -1}.tree-source-path summary{white-space:nowrap}"
        "</style>"
        '<section id="file-structure" data-section="file-structure" class="file-evidence-section">'
        + ui.panel(
            "文件结构",
            "查看交付文件、变化分类与原始绝对路径。",
            f"<p class='file-tree-note'>{'默认显示当前交付。' if default_filter == 'current' else '默认显示变化文件及待核对文件。'}待核对：尚未确定两版文件的对应关系，不计为新增或删除。基准版文件只在变化列表或全部文件中显示。</p>"
            + _source_roots_html(model)
            + _file_tree_controls(records, current_total, change_total, default_filter)
            + "<div class='file-tree-scroll'>"
            + _file_tree_html(model, default_filter)
            + "</div>"
            + "<div class='file-tree-legend'><span><i class='added'></i>新增</span><span><i class='removed'></i>删除</span><span><i class='changed'></i>修改</span><span><i class='current'></i>当前文件</span></div>",
        )
        + "<script>"
        + r"""
function setFileTreeOpen(open){
  document.querySelectorAll('[data-file-tree] .tree-folder > details').forEach(function(item){item.open=!!open;});
}
function filterFileTree(status, button){
  var tree=document.querySelector('[data-file-tree]'); if(!tree) return;
  if(status){
    tree.setAttribute('data-tree-filter', status);
    document.querySelectorAll('.tree-filter-chip').forEach(function(item){item.classList.toggle('active', item===button || item.getAttribute('data-tree-filter')===status);});
  }
  var query=((document.getElementById('file-tree-search')||{}).value||'').toLowerCase().trim();
  var wantedChange=(document.getElementById('file-tree-change-filter')||{}).value||'all';
  var wantedView=(document.getElementById('file-tree-view-filter')||{}).value||'all';
  var wantedArea=(document.getElementById('file-tree-area-filter')||{}).value||'all';
  var wanted=tree.getAttribute('data-tree-filter')||'changes';
  var visible=0;
  tree.querySelectorAll('.tree-file').forEach(function(file){
    var text=file.getAttribute('data-tree-search')||'';
    var fileStatus=file.getAttribute('data-tree-status')||'current';
    var baselineOnly=['removed','unmatched_base','baseline_only'].indexOf(fileStatus)>=0;
    var inScope=wanted==='all'||(wanted==='changes'&&fileStatus!=='current')||(wanted==='current'&&!baselineOnly);
    var changeHit=wantedChange==='all'||fileStatus===wantedChange;
    var viewHit=wantedView==='all'||file.getAttribute('data-tree-view-type')===wantedView;
    var areaHit=wantedArea==='all'||file.getAttribute('data-tree-area')===wantedArea;
    var show=inScope&&changeHit&&viewHit&&areaHit&&(!query||text.indexOf(query)>=0);
    file.classList.toggle('tree-hidden', !show);
    if(show) visible++;
  });
  tree.querySelectorAll('.tree-folder').forEach(function(folder){
    var any=Array.from(folder.querySelectorAll('.tree-file')).some(function(file){return !file.classList.contains('tree-hidden');});
    folder.classList.toggle('tree-hidden', !any);
    if(query&&any){var detail=folder.querySelector(':scope > details');if(detail) detail.open=true;}
  });
  var count=document.getElementById('file-tree-visible'); if(count) count.textContent=visible;
}
function selectFileTreeView(view){
  resetFileTreeFilters();
  document.getElementById('file-tree-view-filter').value=view;
  filterFileTree('current');
  setFileTreeOpen(true);
}
function selectFileTreeAllView(view){
  selectFileTreeView(view);
  filterFileTree('all');
}
function resetFileTreeFilters(){
  var input=document.getElementById('file-tree-search'); if(input) input.value='';
  var change=document.getElementById('file-tree-change-filter'); if(change) change.value='all';
  var view=document.getElementById('file-tree-view-filter'); if(view) view.value='all';
  var area=document.getElementById('file-tree-area-filter'); if(area) area.value='all';
  filterFileTree('all', document.querySelector('.tree-filter-chip[data-tree-filter="all"]'));
}
"""
        + f"filterFileTree('{default_filter}', document.querySelector('.tree-filter-chip[data-tree-filter=\"{default_filter}\"]'));"
        + "</script>"
        + "</section>"
    )
    return body
