"""Build a rebuildable three-timeline index strictly from archived records."""
import json
import posixpath
import re
from collections import defaultdict
from pathlib import Path

from ai_lib_qor.application.data_query import LibraryDataQuery, _subgroup, _view
from ai_lib_qor.application.effective_json import _flat_views
from ai_lib_qor.application.file_index import build_index, load_records
from ai_lib_qor.sources.layout import SAFE, library_folder
from ai_lib_qor.versions.store import read_json


def _chain(records, ident, parent):
    by_id={r[ident]:r for r in records}
    if len(by_id)!=len(records):raise ValueError('历史标识重复')
    children=defaultdict(list)
    for r in records:
        p=r[parent]
        if p is not None and p not in by_id:raise ValueError('历史父记录缺失')
        children[p].append(r[ident])
    if len(children[None])!=1 or any(len(v)>1 for v in children.values()):
        raise ValueError('历史不是唯一的父子链')
    result=[];cursor=children[None][0]
    while cursor:
        result.append(by_id[cursor]);cursor=next(iter(children.get(cursor,[])),None)
        if len(result)>len(records):raise ValueError('历史链循环')
    if len(result)!=len(records):raise ValueError('历史链不完整')
    return list(reversed(result))


def build_library_index(work,vendor,library,*,query=None,source=None):
    """Return v3 projection; reject uncertain ordering or incomplete references."""
    q=query or LibraryDataQuery(work,Path(work)/'.index-no-runs')
    from .file_index import repository_order
    items=[x for x in q.deliveries if (x['record']['vendor_id'],x['record']['source_library_id'])==(vendor,library)]
    ordered,_=repository_order(items,source if source is not None else q._source_configs.get((vendor,library),{}))
    if not ordered:raise ValueError('交付顺序未确认或没有交付')
    raw=build_index(load_records([Path(x['path']) for x in items]),[x['record']['delivery_id'] for x in reversed(ordered)])
    out={'schema':'file_index.v3','scope':{'vendor':vendor,'library':library},
         'deliveries':raw['deliveries'],'formal_nl':{},'effective_sets':{},'views':{}}
    def node(kind,path):
        group=out['views'].setdefault(kind,{'files':{}})
        item=group['files'].setdefault(path,{'raw':[]})
        model=_subgroup(kind,path)
        if kind=='LIBERTY' and model and model!='UNKNOWN':item['model']=model
        return item
    for kind,paths in raw['views'].items():
        for path,entry in paths.items():
            occurrences=[]
            for original in entry['timeline']:
                row=dict(original)
                candidates=[f for source,f in q._history.get((vendor,library,kind,path),[])
                            if source['record']['delivery_id']==row['delivery_id'] and f['file_id']==row['file_id']]
                if len(candidates)!=1:raise ValueError('RAW 文件身份不唯一')
                # RESOLVED means parser classification, not human-confirmed identity.
                if candidates[0]['identity_status']!='CONFIRMED':row['file_key']=None
                occurrences.append(row)
            node(kind,path)['raw']=occurrences

    grouped=defaultdict(list)
    for snap in q.snapshots:
        if library not in snap['scope']['source_library_ids']:continue
        owner=q._snapshot_owners.get((snap['formal_nl_id'],snap['formal_snapshot_id']))
        if owner and owner!=(vendor,library):continue
        if not owner:
            refs=[q._raw_reference(f.get('source_ref')) for f in snap['linked_files'] if f.get('source_ref')]
            if not any(r and (r['vendor'],r['library'])==(vendor,library) for r in refs):continue
            if snap['scope']['source_library_ids']!=[library]:raise ValueError('公共 Formal 快照归属不唯一')
        grouped[snap['formal_nl_id']].append(snap)
    for nl,snaps in sorted(grouped.items()):
        chain=_chain(snaps,'formal_snapshot_id','previous_snapshot_id')
        out['formal_nl'][nl]={'snapshots':[{'snapshot_id':s['formal_snapshot_id'],'parent':s['previous_snapshot_id'],
            'root':s['source_root'],'observed_at':s['observed_at'],'coverage':s['coverage']} for s in chain]}
        for snap in chain:
            for f in snap['linked_files']:
                ref=f.get('source_ref');rawref=q._raw_reference(ref) if ref else None
                valid=bool(rawref and (rawref['vendor'],rawref['library'])==(vendor,library)
                           and f['source_match']=='MATCHED_RAW' and rawref['file_key']==f['file_key'])
                if valid:
                    delivery=q._delivery(vendor,library,rawref['version'],rawref['delivery_id'])['record']
                    valid=(posixpath.isabs(delivery['source_root']) and posixpath.isabs(f['resolved_path']) and
                           posixpath.normpath(posixpath.join(delivery['source_root'],rawref['path']))==posixpath.normpath(f['resolved_path']))
                row={'nl':nl,'snapshot_id':snap['formal_snapshot_id'],'link_path':f['link_path'],
                     'link_target':f.get('link_target'),'resolved_path':f['resolved_path'],'source_match':f['source_match']}
                if 'link_target' not in f:row['link_target_status']='NOT_RECORDED'
                if valid:
                    kind,path=rawref['view'],rawref['path'];target=node(kind,path)
                    if not any(x['delivery_id']==rawref['delivery_id'] and x['file_id']==ref['file_id'] for x in target['raw']):
                        raise ValueError('Formal 引用未包含在对应 RAW 时间线')
                    row['raw_source']={'delivery_id':rawref['delivery_id'],'file_id':ref['file_id']}
                    target.setdefault('formal',[]).append(row)
                else:
                    kind=rawref['view'] if rawref else _view(None,f['link_path'])
                    if ref:row['raw_reference']=ref
                    if f['source_match']=='MATCHED_RAW':row['match_issue']='ARCHIVED_REFERENCE_UNCONFIRMED'
                    out['views'].setdefault(kind,{'files':{}}).setdefault('unmatched_formal',[]).append(row)

    folder=library_folder(work,vendor,library);sets=defaultdict(list);legacy_sets=set()
    for path in folder.glob('effective_*_[0-9]*.json'):
        match=re.fullmatch(r'effective_(.+)_(\d+)\.json',path.name)
        if not match:continue
        if path.is_symlink() or not SAFE.fullmatch(match.group(1)):raise ValueError('有效版本路径无效')
        probe=json.loads(path.read_text(encoding='utf-8'))
        if isinstance(probe,dict) and probe.get('schema_version')=='effective_version.v1':
            read_json(path,'effective_version');legacy_sets.add(match.group(1));continue
        record=read_json(path,'effective_simple_v2')
        if record['scope']!={'vendor':vendor,'library':library} or record['revision']!=f'rev_{int(match.group(2)):04d}':
            raise ValueError('有效版本归属或文件名不一致')
        sets[match.group(1)].append(record)
    for entry in q.entries:
        if (entry['vendor'],entry['library'])!=(vendor,library):continue
        set_id=entry['index']['effective_set_id']
        if set_id in sets:raise ValueError('有效集同时存在 v1 和 v2 历史，不能猜测来源')
        sets[set_id]=[q._simple_revision(vendor,library,set_id,r['revision_id']) for r in entry['versions']]
        legacy_sets.discard(set_id)
    if legacy_sets:raise ValueError('旧有效版本缺少有效索引或无法解析')
    for set_id,revisions in sorted(sets.items()):
        chain=_chain(revisions,'revision','parent')
        owner=chain[0]['owner']
        if any(r['owner']!=owner or r['scope']!=chain[0]['scope'] for r in chain):raise ValueError('有效集所有者或范围不一致')
        out['effective_sets'][set_id]={'owner':owner,'revisions':[{'revision':r['revision'],'parent':r['parent']} for r in chain]}
        for revision in chain:
            for (kind,path),src in _flat_views(revision).items():
                loc=q._source_location(src,kind,path)
                if loc['resolution']!='RECORDED':raise ValueError('有效版本引用交付或文件不存在、不唯一')
                row={'revision':revision['revision'],'delivery_id':loc['delivery_id']}
                if (src['vendor'],src['library'])!=(vendor,library):
                    row.update(source_scope={'vendor':src['vendor'],'library':src['library']},source_path=path)
                elif not any(x['delivery_id']==loc['delivery_id'] and x['file_id']==loc['file_id'] for x in node(kind,path)['raw']):
                    raise ValueError('有效版本引用不在本库 RAW 时间线')
                node(kind,path).setdefault('effective',{}).setdefault(set_id,[]).append(row)
    return out


def raw_compat(index):
    """Adapt validated v3 RAW timelines for existing v2 read consumers."""
    return {'schema':'file_index.v2','scope':index['scope'],'deliveries':index['deliveries'],
            'views':{view:{path:{'timeline':item['raw']} for path,item in group['files'].items() if item.get('raw')}
                     for view,group in index['views'].items()}}


def preserves_history(old,new):
    """Reject changed/deleted previous facts while allowing additional observations."""
    if not isinstance(old,dict) or old.get('schema')!='file_index.v3' or old.get('scope')!=new['scope']:return False
    def contains_rows(previous,current,key):
        if not isinstance(previous,list):return False
        values={x[key]:x for x in current}
        return len({x[key] for x in previous})==len(previous) and all(values.get(x[key])==x for x in previous)
    try:
        if not contains_rows(old['deliveries'],new['deliveries'],'delivery_id'):return False
        for nl,group in old['formal_nl'].items():
            if nl not in new['formal_nl'] or not contains_rows(group['snapshots'],new['formal_nl'][nl]['snapshots'],'snapshot_id'):return False
        for sid,group in old['effective_sets'].items():
            current=new['effective_sets'].get(sid)
            if not current or group['owner']!=current['owner'] or not contains_rows(group['revisions'],current['revisions'],'revision'):return False
        for view,group in old['views'].items():
            current=new['views'].get(view)
            if not current:return False
            for row in group.get('unmatched_formal',[]):
                if row not in current.get('unmatched_formal',[]):return False
            for path,item in group['files'].items():
                target=current['files'].get(path)
                if target is None or item.get('model')!=target.get('model'):return False
                for row in item.get('raw',[]):
                    if row in target.get('raw',[]):continue
                    # A previously unconfirmed file_key can be explicitly confirmed later.
                    if row.get('file_key') is not None or not any(
                        {**candidate,'file_key':None}==row and candidate.get('file_key') is not None
                        for candidate in target.get('raw',[])):return False
                if any(r not in target.get('formal',[]) for r in item.get('formal',[])):return False
                for sid,rows in item.get('effective',{}).items():
                    if any(r not in target.get('effective',{}).get(sid,[]) for r in rows):return False
        return True
    except (KeyError,TypeError,AttributeError):return False
