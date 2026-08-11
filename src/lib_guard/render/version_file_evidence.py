"""Human-readable file structure and evidence section for Version Detail.

The Version Detail page remains the only user-facing review projection. This
module renders its structural file tree and complete evidence table without
creating a second HTML page or a second data source.
"""

from __future__ import annotations

from typing import Any, Mapping

from lib_guard.render import product_theme as ui
from lib_guard.view_types import canonical_view_type, usage_area_for_view, view_label


def _as_mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _evidence_records(model: Mapping[str, Any]) -> list[dict[str, Any]]:
    changes = [item for item in model.get("file_changes", []) or [] if isinstance(item, Mapping)]
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in changes:
        path = str(item.get("path") or "-")
        seen.add(path)
        view_type = canonical_view_type(item.get("file_type"))
        rows.append(
            {
                "change": str(item.get("change") or ""),
                "view": view_label(view_type),
                "path": path,
                "area": usage_area_for_view(view_type),
            }
        )

    scan_evidence = _as_mapping(model.get("scan_evidence"))
    inventory = _as_mapping(scan_evidence.get("inventory"))
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
                "view": view_label(view_type),
                "path": path,
                "area": usage_area_for_view(view_type),
            }
        )

    rows.sort(key=lambda item: (item["view"], item["path"]))
    return rows


def _tree_status(value: Any) -> str:
    text = str(value or "current").strip().lower()
    return text if text in {"added", "removed", "changed", "current"} else "current"


def _tree_status_label(value: str) -> str:
    return {"added": "新增", "removed": "删除", "changed": "修改", "current": "当前"}.get(value, "当前")


def _tree_node() -> dict[str, Any]:
    return {"dirs": {}, "files": [], "counts": {"added": 0, "removed": 0, "changed": 0, "current": 0}}


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
    return " / ".join(parts) or "空目录"


def _tree_file_html(record: Mapping[str, Any]) -> str:
    status = _tree_status(record.get("status"))
    view = str(record.get("view") or "-")
    area = str(record.get("area") or "-")
    searchable = " ".join(str(record.get(key) or "") for key in ("path", "view", "area", "lane", "meaning"))
    return (
        "<li class='tree-file' "
        f"data-tree-status='{ui.esc(status)}' data-tree-search='{ui.esc(searchable.lower())}'>"
        f"<span class='tree-file-mark {ui.esc(status)}'>{ui.esc(_tree_status_label(status))}</span>"
        f"<code title='{ui.esc(record.get('path'))}'>{ui.esc(record.get('name'))}</code>"
        f"<span class='tree-file-meta'>{ui.esc(view)} / {ui.esc(area)}</span>"
        "</li>"
    )


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


def _file_tree_html(model: Mapping[str, Any]) -> str:
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
    return "<ul class='file-tree' data-file-tree>" + "".join(children) + "</ul>"


def _file_tree_controls(total: int) -> str:
    chips = "".join(
        f"<button type='button' class='tree-filter-chip{' active' if status == 'all' else ''}' data-tree-filter='{status}' onclick=\"filterFileTree('{status}', this)\">{label}</button>"
        for status, label in (("all", "全部"), ("added", "新增"), ("removed", "删除"), ("changed", "修改"), ("current", "当前"))
    )
    return (
        "<div class='file-tree-toolbar'>"
        "<label class='tree-search'><span>搜索</span><input id='file-tree-search' type='search' placeholder='搜索目录、文件名或视图' oninput=\"filterFileTree()\"></label>"
        f"<div class='tree-filters'>{chips}</div>"
        "<div class='tree-actions'><button type='button' class='btn secondary' onclick=\"setFileTreeOpen(true)\">全部展开</button><button type='button' class='btn secondary' onclick=\"setFileTreeOpen(false)\">全部收起</button></div>"
        f"<div class='tree-count'><span id='file-tree-visible'>{total}</span> / {total} 项</div>"
        "</div>"
    )


def render_version_file_evidence_section(model: Mapping[str, Any]) -> str:
    records = _evidence_records(model)
    body = (
        "<style>"
        ".file-evidence-section .panel-body{padding-top:12px}"
        ".file-tree-scroll{max-height:min(68vh,760px);overflow:auto;border:1px solid var(--line);border-radius:10px;background:#fbfcff;padding:10px 12px;scrollbar-gutter:stable}"
        ".file-tree,.file-tree ul{list-style:none;margin:0;padding:0}.file-tree ul{padding-left:22px}.tree-folder{margin:1px 0}.tree-folder details{border-left:1px solid #d9e2ea}.tree-folder summary{display:flex;align-items:center;justify-content:space-between;gap:12px;min-height:34px;padding:5px 8px;cursor:pointer;border-radius:7px;color:#243746}.tree-folder summary:hover{background:#eef5f5}.tree-folder summary:focus-visible,.tree-filter-chip:focus-visible,.tree-search:focus-within{outline:3px solid rgba(21,94,239,.22);outline-offset:1px}.tree-folder-name{display:flex;align-items:center;gap:7px;font-weight:800;min-width:0}.tree-folder-icon{display:inline-flex;align-items:center;justify-content:center;width:14px;color:#5b7280;font-size:14px;transition:transform .15s}.tree-folder details[open]>summary .tree-folder-icon{transform:rotate(90deg)}.tree-folder-count{flex:0 0 auto;color:#758594;font:12px var(--mono);white-space:nowrap}.tree-file{display:grid;grid-template-columns:54px minmax(260px,1fr) minmax(230px,.8fr);gap:9px;align-items:center;min-height:32px;padding:4px 8px 4px 22px;border-left:1px solid #d9e2ea}.tree-file:hover{background:#f0f7f7}.tree-file code{overflow-wrap:anywhere;word-break:break-word;color:#1e3b4b}.tree-file-meta{color:#71808b;font-size:12px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.tree-file-mark{display:inline-flex;justify-content:center;width:46px;border-radius:4px;padding:2px 4px;font-size:11px;font-weight:800}.tree-file-mark.added{color:#087443;background:#e9f7f0}.tree-file-mark.removed{color:#ae3b2c;background:#fff0ed}.tree-file-mark.changed{color:#a35c08;background:#fff3df}.tree-file-mark.current{color:#1e5baa;background:#e9f1ff}.tree-hidden{display:none!important}.tree-empty{padding:24px;text-align:center;color:var(--muted);border:1px dashed var(--line);border-radius:9px}.file-tree-toolbar{display:grid;grid-template-columns:minmax(280px,1.2fr) minmax(350px,1fr) auto auto;gap:10px;align-items:center;margin-bottom:10px}.tree-search{display:flex;align-items:center;gap:8px;min-width:0;border:1px solid var(--line);border-radius:999px;background:#fff;padding:7px 12px}.tree-search span{font-size:12px;color:var(--muted);font-weight:800}.tree-search input{width:100%;border:0;outline:0;background:transparent;font-size:13px}.tree-filters{display:flex;gap:6px;flex-wrap:wrap}.tree-filter-chip{border:1px solid var(--line);border-radius:999px;background:#fff;color:#344054;padding:6px 10px;font-size:12px;font-weight:700;cursor:pointer}.tree-filter-chip.active{border-color:#9cc2ff;background:#eef4ff;color:#1849a9}.tree-actions{display:flex;gap:6px}.tree-actions .btn{min-height:32px}.tree-count{color:var(--muted);font-size:12px;font-weight:800;white-space:nowrap}.file-tree-note{margin:0 0 12px;color:var(--muted);font-size:12px}.file-tree-legend{display:flex;gap:12px;flex-wrap:wrap;margin-top:10px;color:var(--muted);font-size:12px}.file-tree-legend span{display:inline-flex;align-items:center;gap:5px}.file-tree-legend i{display:inline-block;width:9px;height:9px;border-radius:2px}.file-tree-legend .added{background:#43a782}.file-tree-legend .removed{background:#c85545}.file-tree-legend .changed{background:#d4862a}.file-tree-legend .current{background:#4b86c5}@media(max-width:1100px){.file-tree-toolbar{grid-template-columns:1fr 1fr}.tree-actions{justify-content:flex-start}.tree-count{justify-self:end}}@media(max-width:760px){.tree-file{grid-template-columns:54px minmax(0,1fr)}.tree-file-meta{grid-column:2}.file-tree-toolbar{grid-template-columns:1fr}.tree-count{justify-self:start}}"
        "</style>"
        "<section id='file-structure' class='file-evidence-section'>"
        + ui.panel(
            "文件结构",
            "按当前交付路径展示目录层级；删除项保留在原路径，颜色只表示本次变化。",
            "<p class='file-tree-note'>目录默认展开前两层；文件节点直接显示状态、视图和使用场景，超过千项时在树内滚动。</p>"
            + _file_tree_controls(len(records))
            + "<div class='file-tree-scroll'>"
            + _file_tree_html(model)
            + "</div>"
            + "<div class='file-tree-legend'><span><i class='added'></i>新增</span><span><i class='removed'></i>删除</span><span><i class='changed'></i>修改</span><span><i class='current'></i>当前文件</span></div>",
        )
        + "<script>"
        + r"""
function setFileTreeOpen(open){
  document.querySelectorAll('[data-file-tree] details').forEach(function(item){item.open=!!open;});
}
function filterFileTree(status, button){
  var tree=document.querySelector('[data-file-tree]'); if(!tree) return;
  if(status){
    tree.setAttribute('data-tree-filter', status);
    document.querySelectorAll('.tree-filter-chip').forEach(function(item){item.classList.toggle('active', item===button || item.getAttribute('data-tree-filter')===status);});
  }
  var query=((document.getElementById('file-tree-search')||{}).value||'').toLowerCase().trim();
  var wanted=tree.getAttribute('data-tree-filter')||'all';
  var visible=0;
  tree.querySelectorAll('.tree-file').forEach(function(file){
    var text=file.getAttribute('data-tree-search')||'';
    var show=(wanted==='all'||file.getAttribute('data-tree-status')===wanted)&&(!query||text.indexOf(query)>=0);
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
"""
        + "</script>"
        + "</section>"
    )
    return body
