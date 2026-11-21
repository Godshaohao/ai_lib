#!/usr/bin/env python3
"""Build one rich, complete, rebuildable per-library RAW file timeline from many Delivery JSON files.

No RAW directory scanning, no content hashing, no third-party packages, and no
JSON filenames in the generated index. The index is an expendable projection,
not the source of truth. Historical Delivery JSON records must be immutable.
"""
from __future__ import annotations

import argparse
import contextlib
from datetime import datetime
from copy import deepcopy
import json
import os
from pathlib import Path, PurePosixPath
import posixpath
import re
import tempfile
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

SCHEMA = "file_index.v2"


class IndexErrorValue(ValueError):
    """Invalid source records, business order, or index state."""


def _path(value: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise IndexErrorValue(f"无效的文件相对路径: {value!r}")
    p = PurePosixPath(value)
    if p.is_absolute() or any(part in ("", ".", "..") for part in value.split("/")):
        raise IndexErrorValue(f"文件路径不得为绝对路径或包含点/回退分量: {value!r}")
    return value


def _view(view: str, path: str) -> str:
    # Match the existing LibraryDataQuery normalization where possible.
    value = (view or "OTHER").upper()
    stem = path.lower()
    if stem.endswith(".gz"):
        stem = stem[:-3]
    ext = PurePosixPath(stem).suffix
    if value == "CDL" and ext in (".spice", ".sp"):
        return "SPICE"
    if value not in ("OTHER", "UNKNOWN"):
        return value
    return {
        ".lef": "LEF", ".lib": "LIBERTY", ".gds": "GDS",
        ".sp": "SPICE", ".spice": "SPICE", ".cdl": "CDL", ".db": "DB",
        ".v": "VERILOG", ".sv": "VERILOG", ".pdf": "DOC",
        ".xlsx": "DOC", ".xls": "DOC", ".txt": "DOC", ".md": "DOC",
    }.get(ext, value)


def _paths_in_view(node):
    if isinstance(node, list):
        for value in node:
            yield _path(value)
    elif isinstance(node, dict):
        for value in node.values():
            yield from _paths_in_view(value)
    else:
        raise IndexErrorValue("RAW views 的叶子必须为文件路径数组")


def _read_delivery(path: Path):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise IndexErrorValue(f"无法读取 Delivery JSON: {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise IndexErrorValue(f"Delivery JSON 必须是对象: {path}")
    if set(data)=={'vendor','library','version','version_date','directory_created_at','root','views'}:
        from ai_lib_qor.versions.store import read_json
        try:data=read_json(path,'delivery_record')
        except (OSError,ValueError,KeyError,TypeError) as exc:raise IndexErrorValue(f'简化交付无法读取: {path}: {exc}') from exc
    if data.get("schema_version") == "delivery_record.v1":
        version = data.get("supplier_version")
        scope = (data.get("vendor_id"), data.get("source_library_id"))
        root = data.get("source_root")
        recorded = data.get("received_at")
        rows = []
        for file in data.get("files", []):
            rel = _path(file.get("relative_path"))
            row = {
                "view": _view(file.get("view"), rel),
                "path": rel,
                "file_id": file.get("file_id"),
                "file_key": file.get("file_key"),
                "classification": file.get("classification") or "UNKNOWN",
            }
            if file.get("corner") is not None:
                row["corner"] = file["corner"]
            if file.get("mode") is not None:
                row["mode"] = file["mode"]
            rows.append(row)
        order = data.get("delivery_order")
    elif data.get("schema") == "raw.simple.v1":
        ctx = data.get("context") or {}
        version = ctx.get("version")
        scope = (ctx.get("vendor"), ctx.get("library"))
        root = ctx.get("root")
        recorded = ctx.get("recorded_at")
        rows = []
        for view, group in (data.get("views") or {}).items():
            for path_value in _paths_in_view(group):
                rows.append({"view": _view(view, path_value), "path": path_value,
                             "file_id": None, "file_key": None,
                             "classification": "UNKNOWN"})
        order = None
    else:
        raise IndexErrorValue(f"不支持的源文件契约（只接收 Delivery，不接收 Formal/Effective）: {path}")
    ident = data.get("delivery_id")
    if not all(isinstance(x, str) and x for x in (*scope, ident, version, root)):
        raise IndexErrorValue(f"Delivery 身份、版本、范围或根路径不完整: {path}")
    if not posixpath.isabs(root):
        raise IndexErrorValue(f"Delivery root 必须是绝对路径: {path}")
    if order is not None and (type(order) is not int or order < 0):
        raise IndexErrorValue(f"delivery_order 必须是非负整数: {path}")
    seen = set()
    for row in rows:
        key = row["view"], row["path"]
        if key in seen:
            raise IndexErrorValue(f"同一次交付中 View + path 重复: {path}: {key}")
        seen.add(key)
    return {
        "delivery_id": ident, "version": version, "vendor": scope[0],
        "library": scope[1], "root": root, "recorded_at": recorded,
        "source_order": order, "rows": rows,
    }


def _discover(dirs: list[Path], files: list[Path]):
    paths = set()
    for folder in dirs:
        if not folder.is_dir():
            raise IndexErrorValue(f"输入目录不存在: {folder}")
        for path in list(folder.glob("delivery_*.json")) + list(folder.glob("deliveries/*/delivery.json")):
            if path.is_file() and not any(part.is_symlink() for part in (path,*path.parents) if part!=folder and part.is_relative_to(folder)):
                paths.add(path.resolve())
    for p in files:
        if not p.is_file() or p.is_symlink():
            raise IndexErrorValue(f"指定输入无效或是软链接: {p}")
        paths.add(p.resolve())
    if not paths:
        raise IndexErrorValue("没有找到任何 Delivery JSON")
    return sorted(paths)


def load_records(paths: list[Path]):
    by_id = {}
    scope = None
    for p in paths:
        row = _read_delivery(p)
        current = (row["vendor"], row["library"])
        if scope is None:
            scope = current
        if current != scope:
            raise IndexErrorValue(f"不同 Library 的 Delivery 不能混入同一 Index: {p}")
        if row["delivery_id"] in by_id:
            raise IndexErrorValue(f"交付 ID 重复（哪怕两个 JSON 内容相同也要清理重复输入）: {row['delivery_id']}")
        by_id[row["delivery_id"]] = row
    return by_id


def resolve_order(records, *, order_ids=None, trust_delivery_order=False,
                  date_prefix_order=False, scan_sources=None):
    """Return delivery IDs newest first; never infer order from filenames/mtime."""
    ids = set(records)
    if order_ids:
        seq = [s.strip() for s in order_ids.split(",")]
        if len(seq) != len(ids) or set(seq) != ids or len(seq) != len(set(seq)):
            raise IndexErrorValue("--order-ids 必须完整且不重复列出所有真实 delivery_id（从新到旧）")
        return seq
    if scan_sources:
        conf = json.loads(Path(scan_sources).read_text(encoding="utf-8"))
        vendor, library = next(iter(records.values()))["vendor"], next(iter(records.values()))["library"]
        matches = [s for s in conf.get("sources", [])
                   if (s.get("vendor_id"), s.get("source_library_id")) == (vendor, library)]
        if len(matches) != 1:
            raise IndexErrorValue("scan_sources.json 中未找到唯一对应的 SourceLibrary 配置")
        items=[{'record':{'delivery_id':r['delivery_id'],'delivery_order':r['source_order'],
                          'supplier_version':r['version']},'ordering_status':'UNCONFIRMED'} for r in records.values()]
        ordered,_=repository_order(items,matches[0])
        if ordered is not None:return [x['record']['delivery_id'] for x in reversed(ordered)]
        raise IndexErrorValue('配置未能确定全部交付的唯一顺序；同名版本请使用 --order-ids')
    if len(records) == 1:
        return list(records)
    if trust_delivery_order:
        orders = [r["source_order"] for r in records.values()]
        if any(o is None for o in orders) or len(set(orders)) != len(orders):
            raise IndexErrorValue("记录中 delivery_order 缺失或重复")
        return sorted(ids, key=lambda i: records[i]["source_order"], reverse=True)
    if date_prefix_order:
        from .simple_sources import version_date_order
        try:
            return list(reversed(version_date_order([{'delivery_id':i,'context':{'version':r['version']}} for i,r in records.items()])))
        except ValueError as exc:raise IndexErrorValue(str(exc)) from exc
    raise IndexErrorValue("交付顺序未确认：使用 --order-ids、--scan-sources、--trust-delivery-order 或 --date-prefix-order")


def _delivery_info(rec):
    info = {"delivery_id": rec["delivery_id"], "version": rec["version"],
            "root": rec["root"], "recorded_at": rec["recorded_at"]}
    return info


def _occurrence(rec, f):
    value = {"delivery_id": rec["delivery_id"],
             "file_id": f["file_id"], "file_key": f["file_key"],
             "classification": f["classification"]}
    for field in ("corner", "mode"):
        if field in f:
            value[field] = f[field]
    return value


def _add_occurrences(views, recs):
    for rec in recs:  # supplied newest-first
        for f in rec["rows"]:
            bucket = views.setdefault(f["view"], {}).setdefault(f["path"], {"timeline": []})
            item = _occurrence(rec, f)
            bucket["timeline"].append(item)


def _sorted_views(views):
    return {view: {path: entries[path] for path in sorted(entries)}
            for view, entries in sorted(views.items())}


def build_index(records, order):
    if not order:
        raise IndexErrorValue("空的交付顺序")
    head = records[order[0]]
    views = {}
    _add_occurrences(views, [records[ident] for ident in order])
    return {"schema": SCHEMA,
            "scope": {"vendor": head["vendor"], "library": head["library"]},
            "deliveries": [_delivery_info(records[ident]) for ident in order],
            "views": _sorted_views(views)}


def update_index(existing, records, order):
    """Incremental append when safe; otherwise rebuild solely from archived JSON.

    Existing deliveries are always revalidated against archived JSON to reject
    in-place historical manifest edits. This doesn't touch the RAW files.
    """
    if existing is None:
        return build_index(records, order), "REBUILD"
    if not isinstance(existing, dict) or existing.get("schema") != SCHEMA:
        raise IndexErrorValue('旧索引格式无效或版本不支持；确认后可显式重建')
    old_deliveries = existing.get("deliveries")
    if not isinstance(old_deliveries, list) or not old_deliveries:
        raise IndexErrorValue('旧索引缺少交付列表；确认后可显式重建')
    old_ids = [d.get("delivery_id") for d in old_deliveries]
    if len(old_ids) != len(set(old_ids)) or not set(old_ids).issubset(records):
        raise IndexErrorValue("旧 Index 引用缺失或重复的 Delivery，拒绝静默删除历史")
    reference=build_index(records,old_ids);migrated=False
    if reference != existing:
        # Accept only the exact former v2 representation, validating every redundant
        # value against its archived Delivery before eliminating it.
        legacy=deepcopy(reference)
        for item in legacy['deliveries']:
            rec=records[item['delivery_id']];item['file_count']=len(rec['rows'])
            if rec['source_order'] is not None:item['delivery_order']=rec['source_order']
        for files in legacy['views'].values():
            for bucket in files.values():
                for occurrence in bucket['timeline']:
                    occurrence['version']=records[occurrence['delivery_id']]['version']
        if legacy!=existing:
            raise IndexErrorValue("旧 Index 与已归档 Delivery 不一致（记录可能被改写或索引损坏）；拒绝悄悄覆盖")
        existing=reference;migrated=True
    if order == old_ids:
        return existing, "MIGRATE" if migrated else "UNCHANGED"
    if order[-len(old_ids):] == old_ids:
        new_ids = order[:len(order) - len(old_ids)]
        result = deepcopy(existing)
        result["deliveries"] = [_delivery_info(records[i]) for i in new_ids] + result["deliveries"]
        # Prefix all new occurrences in business order, leaving old history intact.
        additions = build_index(records, new_ids)["views"]
        for view, files in additions.items():
            target = result["views"].setdefault(view, {})
            for path, item in files.items():
                previous = target.get(path, {"timeline": []})["timeline"]
                target[path] = {"timeline": item["timeline"] + previous}
        result["views"] = _sorted_views(result["views"])
        if result != build_index(records, order):
            raise IndexErrorValue("增量更新与完整重建不一致")
        return result, "APPEND"
    return build_index(records, order), "REORDER_REBUILD"


def _date_then_registered(items,source):
    """Sort mixed date-only versions and explicitly recorded timestamps without guessing."""
    values=source.get('delivery_registration_times')
    if not isinstance(values,dict):return None
    try:zone=ZoneInfo(source['order_timezone'])
    except (KeyError,TypeError,ValueError,ZoneInfoNotFoundError):return None
    rows=[];days={}
    for item in items:
        record=item['record'];version=record['supplier_version'];ident=record['delivery_id']
        match=re.fullmatch(r'(20\d{6})(?:[_-].+)?',version)
        if match:
            try:day=datetime.strptime(match.group(1),'%Y%m%d').date()
            except ValueError:return None
            exact=None
        else:
            # Invalid date-looking versions must not quietly fall back to another time.
            if re.match(r'^20\d{6}(?:[_-]|$)',version):return None
            value=values.get(ident)
            if not isinstance(value,str):return None
            try:
                exact=datetime.fromisoformat(value.replace('Z','+00:00'))
                if exact.tzinfo is None or exact.utcoffset() is None:return None
                exact=exact.astimezone(zone);day=exact.date()
            except (ValueError,OverflowError):return None
        days.setdefault(day,[]).append(exact);rows.append((day,exact,item))
    for group in days.values():
        if len(group)>1 and (any(x is None for x in group) or len(set(group))!=len(group)):return None
    rows.sort(key=lambda x:(x[0],x[1].timestamp() if x[1] else 0))
    return [x[2] for x in rows]


def repository_order(items, source):
    """Use the same confirmed ordering for both registration and queries; oldest first."""
    from .simple_sources import version_date_order
    if 'delivery_order_ids' in source:
        ids=source['delivery_order_ids'];by_id={x['record']['delivery_id']:x for x in items}
        if (isinstance(ids,list) and all(isinstance(i,str) for i in ids)
            and len(ids)==len(items)==len(by_id) and len(set(ids))==len(ids) and set(ids)==set(by_id)):
            return [by_id[i] for i in reversed(ids)],'EXPLICIT_DELIVERY_IDS'
        return None,None
    if len(items) == 1:
        return list(items), 'ONLY_REGISTERED_DELIVERY'
    if not items:
        return None, None
    if source.get('order_rule')=={'type':'VERSION_DATE_PREFIX','confirmed':True}:
        try:
            ids=version_date_order([{'delivery_id':x['record']['delivery_id'],'context':{'version':x['record']['supplier_version']}} for x in items])
            by_id={x['record']['delivery_id']:x for x in items}
            if len(by_id)==len(items):return [by_id[i] for i in ids], 'CONFIRMED_VERSION_DATE_PREFIX'
        except (ValueError,KeyError):pass
        ordered=_date_then_registered(items,source)
        return (ordered,'CONFIRMED_DATE_AND_REGISTERED_TIME') if ordered is not None else (None,None)
    mapping=source.get('delivery_orders',{})
    versions=[x['record']['supplier_version'] for x in items]
    if (isinstance(mapping,dict) and len(set(versions))==len(versions)
        and all(type(mapping.get(v)) is int and mapping[v]>=0 for v in versions)
        and len({mapping[v] for v in versions})==len(versions)):
        return sorted(items,key=lambda x:mapping[x['record']['supplier_version']]), 'CONFIGURED_SEQUENCE'
    if all(x['ordering_status'] == 'CONFIRMED' for x in items):
        values=[x['record']['delivery_order'] for x in items]
        if len(set(values)) == len(values):
            return sorted(items,key=lambda x:x['record']['delivery_order']), 'CONFIRMED_DELIVERY_ORDER'
    return None, None


def repository_index_state(items, source, existing):
    ordered,basis=repository_order(items,source)
    if ordered is None:
        return None, 'ORDER_UNCONFIRMED', basis
    records=load_records([Path(x['path']) for x in items])
    order=[x['record']['delivery_id'] for x in reversed(ordered)]
    index,action=update_index(existing,records,order)
    return index,action,basis


def refresh_library_index_locked(work, vendor, library, source, *, force_rebuild=False):
    """Caller must hold the existing Library lock; never opens a RAW file."""
    from ai_lib_qor.application.source_repository import SourceRepository
    from ai_lib_qor.sources.layout import library_folder
    from ai_lib_qor.versions.store import write_atomic
    folder=library_folder(work,vendor,library);path=folder/'file_index.json'
    if path.is_symlink():raise IndexErrorValue('Index 不能是软链接')
    items=[x for x in SourceRepository(work).deliveries()
           if (x['record']['vendor_id'],x['record']['source_library_id'])==(vendor,library)]
    existing=json.loads(path.read_text(encoding='utf-8')) if path.exists() else None
    if path.exists() and existing is None:raise IndexErrorValue('旧索引为空值；确认后可显式重建')
    ordered,basis=repository_order(items,source)
    if not ordered:return {'action':'ORDER_UNCONFIRMED','order_basis':basis,'path':None}
    from .file_index_v3 import build_library_index,preserves_history
    index=build_library_index(work,vendor,library,source=source)
    if force_rebuild and existing is not None:
        if not isinstance(existing,dict) or existing.get('schema') not in ('file_index.v2','file_index.v3'):
            raise IndexErrorValue('拒绝覆盖未知格式的文件')
        action='FORCED_REBUILD'
    elif existing is None:action='REBUILD'
    elif isinstance(existing,dict) and existing.get('schema')=='file_index.v2':
        # Validate the complete old projection against archived Delivery before upgrading.
        repository_index_state(items,source,existing);action='MIGRATE_V3'
    elif existing==index:action='UNCHANGED'
    elif preserves_history(existing,index):
        old_ids=[x['delivery_id'] for x in existing['deliveries']]
        current_ids=[x['delivery_id'] for x in index['deliveries']]
        action='APPEND' if current_ids[-len(old_ids):]==old_ids else 'REORDER_REBUILD'
    else:raise IndexErrorValue('旧索引与已归档历史不一致，拒绝覆盖；需核验后显式重建')
    if action!='UNCHANGED':write_atomic(path,index)
    return {'action':action,'order_basis':basis,'path':str(path)}


def _write_atomic(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".file-index-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(name, path)
        dfd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(dfd)
        finally:
            os.close(dfd)
    finally:
        if os.path.exists(name):
            os.unlink(name)


@contextlib.contextmanager
def _library_lock(folder: Path):
    """Use ai_lib_qor's existing per-Library lock; do not introduce another lock."""
    from ai_lib_qor.versions.store import locked
    with locked(folder):
        yield


def main(argv=None):
    parser = argparse.ArgumentParser(description="从同一库的多份 Delivery JSON 构建完整 RAW 文件时间线")
    parser.add_argument("--input-dir", type=Path, action="append", default=[], help="读取该目录下 delivery_*.json；可重复")
    parser.add_argument("--input", type=Path, action="append", default=[], help="显式指定单份 Delivery JSON；可重复")
    parser.add_argument("--output", type=Path, required=True, help="同一 Library 下的 file_index.json")
    parser.add_argument("--order-ids", help="从新到旧的 delivery_id，逗号分隔；必须完整覆盖输入")
    parser.add_argument("--scan-sources", type=Path, help="复用现有 scan_sources.json 的确认顺序配置")
    parser.add_argument("--trust-delivery-order", action="store_true", help="明确声明输入的 delivery_order 可信")
    parser.add_argument("--date-prefix-order", action="store_true", help="明确声明 YYYYMMDD 前缀代表业务顺序")
    parser.add_argument("--rebuild", action="store_true", help="人工确认后强制从所有 Delivery JSON 重建，覆盖损坏/不一致的旧索引")
    args = parser.parse_args(argv)
    # Single CLI writer takes the existing Library lock. Repository integration
    # should call update_index while holding locked(folder), not re-enter this CLI.
    with _library_lock(args.output.parent):
        return _run_locked(args)


def _run_locked(args):
    records = load_records(_discover(args.input_dir, args.input))
    output=args.output.resolve()
    if any(output.is_relative_to(Path(rec['root']).resolve()) for rec in records.values()):
        raise IndexErrorValue('输出不能位于 RAW 来源目录')
    if output in _discover(args.input_dir,args.input):
        raise IndexErrorValue('输出不能覆盖 Delivery')
    order = resolve_order(records, order_ids=args.order_ids,
                          trust_delivery_order=args.trust_delivery_order,
                          date_prefix_order=args.date_prefix_order,
                          scan_sources=args.scan_sources)
    if args.output.is_symlink():
        raise IndexErrorValue("不得用输出覆盖软链接")
    existing = None
    if args.output.exists() and not args.rebuild:
        try:
            existing = json.loads(args.output.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise IndexErrorValue(f"旧 Index 损坏，须人工确认后使用 --rebuild: {exc}") from exc
        if existing is None:
            raise IndexErrorValue('旧 Index 为空值，须人工确认后使用 --rebuild')
    result, action = (build_index(records, order), "FORCED_REBUILD") if args.rebuild else update_index(existing, records, order)
    if action != "UNCHANGED":
        _write_atomic(args.output, result)
    file_count = sum(len(files) for files in result["views"].values())
    occurrence_count = sum(len(v["timeline"]) for f in result["views"].values() for v in f.values())
    print(json.dumps({"action": action, "output": str(args.output), "deliveries": len(order),
                      "unique_files": file_count, "occurrences": occurrence_count}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except IndexErrorValue as exc:
        raise SystemExit("ERROR: " + str(exc))
