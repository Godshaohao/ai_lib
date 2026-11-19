"""Read saved v3 records for the workbench; never scan source libraries."""
from pathlib import Path
from ai_lib_qor.versions.store import read_json, events, revisions
from .source_repository import SourceRepository


def _read(path, schema, warnings, reader):
    try:
        if path.is_symlink() or not path.is_file(): return None
        return reader(path, schema)
    except (OSError, ValueError, KeyError) as exc:
        warnings.append(f'{path.name}: {exc}')
        return None


def load_catalog(work_root, *, reader=None):
    if work_root is None: return [], [], []
    if reader is None: reader=read_json
    root = Path(work_root).resolve()
    warnings, entries, formal = [], [], []
    stored_deliveries=SourceRepository(root,reader=reader,warnings=warnings).deliveries()
    for index_path in sorted(root.glob('vendors/*/libraries/*/ips/*/effective/index.json')):
        if any(p.is_symlink() for p in [index_path, *list(index_path.parents)[:6]]): continue
        index = _read(index_path, 'effective_index', warnings, reader)
        if not index: continue
        ipdir = index_path.parent.parent
        libdir = ipdir.parent.parent
        vendordir = libdir.parent.parent
        owner = index['owner']
        if owner.get('owner_id') != ipdir.name or owner.get('home_source_library_id') != libdir.name:
            warnings.append(f'{index_path}: 有效集所有者与目录不一致'); continue
        deliveries=[x['record'] for x in stored_deliveries
                    if x['record']['source_library_id']==libdir.name and x['record']['vendor_id']==vendordir.name]
        versions = []
        for path in sorted((index_path.parent / 'versions').glob('*.json')):
            item = _read(path, 'effective_version', warnings, reader)
            if item and item['effective_set_id'] == index['effective_set_id'] and item['owner'] == owner: versions.append(item)
        versions.sort(key=lambda item: int(item['revision_id'][4:]) if item['revision_id'].startswith('rev_') and item['revision_id'][4:].isdigit() else -1)
        try:
            event_path = index_path.parent / 'acceptance.jsonl'
            if event_path.is_symlink(): raise ValueError('采纳日志为符号链接')
            acceptance = events(index_path.parent)
            if any(e['effective_set_id'] != index['effective_set_id'] for e in acceptance):
                raise ValueError('采纳事件与有效集不一致')
        except (OSError, ValueError, KeyError) as exc:
            warnings.append(f'{index_path.parent}: 采纳事件不可用: {exc}')
            acceptance = None
        entries.append({'vendor': vendordir.name, 'library': libdir.name, 'ip': ipdir.name,
                        'index': index, 'deliveries': deliveries, 'versions': versions, 'acceptance': acceptance})
    for path in sorted(root.glob('libraries/*/*/effective_*_index.json')):
        if any(p.is_symlink() for p in [path,*path.parents] if p != root and p.is_relative_to(root)):continue
        item=_read(path,'effective_index',warnings,reader)
        if not item:continue
        vendor,library=path.relative_to(root).parts[1:3]
        effective_name=path.name[:-len('_index.json')]
        if effective_name != 'effective_'+item['effective_set_id'] or item['owner'].get('home_source_library_id')!=library:
            warnings.append(f'{path}: 有效集身份与目录不一致');continue
        try:
            effective_dir=path.parent/effective_name
            versions=revisions(effective_dir);acceptance=events(effective_dir)
            if any(v['owner']!=item['owner'] or v['effective_set_id']!=item['effective_set_id'] for v in versions):raise ValueError('有效集成员身份不一致')
            if any(e['effective_set_id']!=item['effective_set_id'] for e in acceptance):raise ValueError('采纳事件与有效集不一致')
        except (OSError,ValueError,KeyError) as exc:
            warnings.append(f'{path}: 有效集不可读取: {exc}');continue
        deliveries=[x['record'] for x in stored_deliveries if x['record']['vendor_id']==vendor and x['record']['source_library_id']==library]
        candidate={'vendor':vendor,'library':library,'ip':item['owner']['owner_id'],
                   'index':item,'deliveries':deliveries,'versions':versions,'acceptance':acceptance}
        duplicates=[e for e in entries if (e['vendor'],e['library'],e['index']['effective_set_id'])==(vendor,library,item['effective_set_id'])]
        if duplicates:
            if len(duplicates)!=1 or any(duplicates[0][k]!=candidate[k] for k in ('index','versions','acceptance')):
                warnings.append(f'{path}: 有效集跨布局冲突')
                entries=[e for e in entries if e not in duplicates]
            continue
        entries.append(candidate)
    formal=[x['record'] for x in SourceRepository(root,reader=reader,warnings=warnings).formal()]
    return entries, formal, warnings


def file_rows(deliveries):
    grouped = {}
    for delivery in sorted(deliveries, key=lambda d: d['delivery_order'], reverse=True):
        for f in delivery['files']:
            key = f.get('file_key')
            if not key: continue
            grouped.setdefault(key, []).append((delivery, f))
    rows = []
    for key, occurrences in sorted(grouped.items()):
        groups = []
        for delivery, file in occurrences:
            if not groups or groups[-1]['delivery']['delivery_id'] != delivery['delivery_id']:
                groups.append({'delivery':delivery, 'files':[]})
            groups[-1]['files'].append(file)
        first=groups[0];primary=first['files'][0]
        orders=[g['delivery']['delivery_order'] for g in groups]
        order_ambiguous=len(orders)!=len(set(orders))
        rows.append({'key':key, 'view':primary['view'] if not order_ambiguous else '未知',
                     'latest':first['delivery']['delivery_id'] if not order_ambiguous else None,
                     'previous':groups[1]['delivery']['delivery_id'] if len(groups)>1 and not order_ambiguous else None,
                     'path':('交付顺序不唯一' if order_ambiguous else primary['relative_path'] if len(first['files'])==1 else '文件位不唯一'),
                     'history':[{'delivery_id':g['delivery']['delivery_id'],'version':g['delivery']['supplier_version'],
                                 'order':g['delivery']['delivery_order'],
                                 'path':g['files'][0]['relative_path'] if len(g['files'])==1 else '文件位不唯一',
                                 'corner':g['files'][0].get('corner'),'mode':g['files'][0].get('mode')} for g in groups],
                     'ambiguous':any(len(g['files'])>1 for g in groups), 'order_ambiguous':order_ambiguous,
                     'corner':primary.get('corner') if len(first['files'])==1 and not order_ambiguous else None})
    return rows


def compare_rows(deliveries, base_id, target_id):
    by_id = {d['delivery_id']:d for d in deliveries}
    if base_id not in by_id or target_id not in by_id: return []
    def files(d):
        result={}
        for f in d['files']:
            if f.get('file_key') and f['classification']=='RESOLVED': result.setdefault(f['file_key'],[]).append(f)
        return result
    base, target = files(by_id[base_id]), files(by_id[target_id])
    rows=[]
    for key in sorted(base.keys() | target.keys()):
        a,b=base.get(key,[]),target.get(key,[])
        relation=('文件位不唯一' if len(a)>1 or len(b)>1 else '两次均列出' if a and b else '目标交付未列出' if a else '基准交付未列出')
        rows.append({'key':key,'base':a[0] if len(a)==1 else None,'target':b[0] if len(b)==1 else None,'relation':relation,'base_ambiguous':len(a)>1,'target_ambiguous':len(b)>1})
    return rows


def _resolve_member(ref, key, deliveries, snapshots):
    matches = []
    if ref['kind'] == 'delivery_file':
        for delivery in deliveries:
            if delivery['source_library_id'] == ref['source_library_id'] and delivery['delivery_id'] == ref['delivery_id']:
                for f in delivery['files']:
                    if f['file_id'] == ref['file_id'] and f['file_key'] == key:
                        matches.append({'path': f['relative_path'], 'version': delivery['supplier_version'], 'view':f['view'], 'corner':f.get('corner'), 'mode':f.get('mode')})
        label = f"交付 {ref['delivery_id']} / {ref['file_id']}"
    else:
        for snap in snapshots:
            if snap['formal_nl_id'] == ref['formal_nl_id'] and snap['formal_snapshot_id'] == ref['formal_snapshot_id']:
                for f in snap['linked_files']:
                    if f['file_id'] == ref['file_id'] and f['file_key'] == key:
                        view = None; corner = None; mode = None
                        raw = f.get('source_ref')
                        if raw and raw.get('kind') == 'delivery_file':
                            raw_matches = [(d, x) for d in deliveries for x in d['files'] if d['source_library_id']==raw['source_library_id'] and d['delivery_id']==raw['delivery_id'] and x['file_id']==raw['file_id'] and x['file_key']==key]
                            if len(raw_matches)==1:
                                raw_file = raw_matches[0][1]; view = raw_file['view']; corner = raw_file.get('corner'); mode = raw_file.get('mode')
                        matches.append({'path':f['link_path'], 'version':ref['formal_nl_id'], 'view':view or '未知', 'corner':corner, 'mode':mode})
        label = f"正式 {ref['formal_nl_id']} / {ref['formal_snapshot_id']} / {ref['file_id']}"
    return label, (matches[0] if len(matches)==1 else None), ('已定位记录' if len(matches)==1 else ('未提供来源记录' if not matches else '来源记录不唯一'))


def member_rows(revision, deliveries, snapshots):
    if not revision: return []
    changes = {c['file_key']:c for c in revision['changes']}
    rows=[]
    for member in revision['members']:
        ref=member['source_ref']; label, detail, status=_resolve_member(ref, member['file_key'], deliveries, snapshots)
        change=changes.get(member['file_key'])
        old=change.get('old_source_ref') if change else None
        old_label=_resolve_member(old, member['file_key'], deliveries, snapshots)[0] if old else None
        rows.append({'key':member['file_key'], 'label':label, 'detail':detail, 'status':status,
                     'source_kind':'RAW' if ref['kind']=='delivery_file' else 'FORMAL',
                     'file_view':detail['view'] if detail else '未知',
                     'action':change['action'] if change else 'UNCHANGED', 'old_label':old_label})
    return rows


def formal_comparison(revision, snapshot, snapshots=()):
    """Compare recorded identity, never infer content equality from provenance."""
    if not revision or not snapshot: return []
    members = {m['file_key']: m['source_ref'] for m in revision['members']}
    formal = {}
    for item in snapshot['linked_files']:
        if item.get('file_key'): formal.setdefault(item['file_key'], []).append(item)
    result = []
    for key in sorted(members.keys() | formal.keys()):
        ref, matches = members.get(key), formal.get(key, [])
        if not ref: relation = '有效版本未列出'
        elif not matches: relation = '快照未列出'
        elif len(matches) != 1: relation = '文件位不唯一'
        else:
            f = matches[0]
            direct = {'kind':'formal_file','formal_nl_id':snapshot['formal_nl_id'],'formal_snapshot_id':snapshot['formal_snapshot_id'],'file_id':f['file_id']}
            raw_ref = ref
            if ref.get('kind') == 'formal_file' and ref != direct:
                candidates = [x for snap in snapshots if snap['formal_nl_id'] == ref['formal_nl_id'] and snap['formal_snapshot_id'] == ref['formal_snapshot_id'] for x in snap['linked_files'] if x['file_id'] == ref['file_id'] and x.get('file_key') == key]
                raw_ref = candidates[0].get('source_ref') if len(candidates) == 1 else None
            if ref == direct or (raw_ref and f.get('source_ref') and raw_ref == f['source_ref']): relation = '来源一致'
            elif raw_ref and f.get('source_ref'): relation = '来源不同'
            else: relation = '来源未知'
        result.append({'key':key, 'relation':relation})
    return result
