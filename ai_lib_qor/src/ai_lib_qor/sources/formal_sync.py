"""Immutable formal-link observations, separate from v3 formal snapshots."""
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from ai_lib_qor.versions.store import write_atomic


def formal_sources(work):
    path=Path(work)/'formal_sources.json'
    if not path.is_file() or path.is_symlink(): return []
    data=json.loads(path.read_text(encoding='utf-8'))['sources']
    if not isinstance(data,list) or len({x['formal_nl_id'] for x in data})!=len(data): raise ValueError('正式来源配置无效或重复')
    return data


def formal_history(runs, config):
    rows=[]
    for p in (Path(runs)/'formal_observations').glob('formal_*.json'):
        if p.is_symlink(): continue
        try:
            item=json.loads(p.read_text(encoding='utf-8'))
            if item['formal_nl_id']==config['formal_nl_id'] and item['root']==str(Path(config['root']).resolve()): rows.append(item)
        except (OSError,ValueError,KeyError): continue
    return sorted(rows,key=lambda x:x['observed_at'],reverse=True)


def sync_formal(runs, config, deliveries, work=None):
    from lib_guard.release.inventory import inventory_directory
    root=Path(config['root']).resolve(); now=datetime.now(timezone.utc).isoformat()
    result={'observation_id':'formal_'+uuid.uuid4().hex,'formal_nl_id':config['formal_nl_id'],
            'root':str(root),'observed_at':now,'status':'COMPLETE','files':[],'errors':[]}
    try:
        legacy=inventory_directory(root,{'libraries':[]})
        by_path={}
        for d in deliveries:
            base=Path(d['source_root']).resolve()
            for f in d['files']:
                path=(base/f['relative_path']).resolve()
                if path.is_relative_to(base): by_path.setdefault(str(path),[]).append((d,f))
        for file in legacy['files']:
            state={'链接正常':'OK','链接失效':'BROKEN','普通文件':'REGULAR'}.get(file['link_status'],'UNKNOWN')
            candidates=by_path.get(file['source_path'],[]) if state=='OK' else []
            source=None
            if len(candidates)==1:
                d,f=candidates[0];source={'vendor':d['vendor_id'],'library':d['source_library_id'],'version':d['supplier_version'],'delivery_id':d['delivery_id'],'file_id':f['file_id'],'file_key':f['file_key']}
            result['files'].append({'path':file['relative_path'],'target':file['source_path'], 'link_status':state,
                                    'source_status':'MATCHED_RAW' if source else 'AMBIGUOUS' if len(candidates)>1 else 'UNKNOWN','source':source})
        if legacy.get('ignored_directory_links'):
            result['errors'].append('存在未扫描的目录链接');result['status']='PARTIAL'
        if any(x['link_status'] in ('BROKEN','REGULAR','UNKNOWN') for x in result['files']): result['status']='PARTIAL'
    except (OSError, ValueError) as exc:
        result['status']='FAILED';result['errors'].append(str(exc))
    prior=next((x for x in formal_history(runs,config) if x['status']=='COMPLETE'),None)
    result['previous_success_id']=prior['observation_id'] if prior else None
    result['changes']=None
    if prior and result['status']=='COMPLETE':
        old={x['path']:x['target'] for x in prior['files']};new={x['path']:x['target'] for x in result['files']}
        result['changes']={'added':sorted(new.keys()-old.keys()),'changed':sorted(k for k in old.keys() & new.keys() if old[k]!=new[k]),'removed':sorted(old.keys()-new.keys())}
    result['snapshot_id']=None
    result['snapshot_note']='未满足发布条件；观察保留'
    keys=[f['source']['file_key'] for f in result['files'] if f['source']]
    if work and result['status']=='COMPLETE' and result['files'] and len(keys)==len(result['files']) and all(keys) and len(set(keys))==len(keys):
        try:
            from ai_lib_qor.sources.snapshot_builder import build_snapshot
            from ai_lib_qor.workbench.registration import SAFE
            from ai_lib_qor.versions.store import read_json, locked
            nl=config['formal_nl_id']
            if not SAFE.fullmatch(nl) or nl in ('.','..'): raise ValueError('正式库标识不安全')
            base=Path(work).resolve(strict=True)
            if base.is_relative_to(root): raise ValueError('工作目录不能位于正式来源内')
            formal_root=base/'formal_nl';nl_root=formal_root/nl;folder=nl_root/'snapshots'
            if any(p.is_symlink() for p in (formal_root,nl_root,folder)) or not folder.resolve().is_relative_to(base): raise ValueError('正式快照目录越界')
            with locked(folder):
                snapshots=[]
                for path in folder.glob('*/snapshot.json'):
                    if path.is_symlink() or path.parent.is_symlink(): continue
                    item=read_json(path,'formal_snapshot')
                    if item['formal_nl_id']==nl: snapshots.append(item)
                previous=max(snapshots,key=lambda x:x['observed_at']) if snapshots else None
                sid='snap_'+uuid.uuid4().hex
                metadata={'formal_nl_id':nl,'formal_snapshot_id':sid,'previous_snapshot_id':previous['formal_snapshot_id'] if previous else None,
                          'observed_at':now,'scope_confirmed':config.get('scope_confirmed') is True,
                          'source_library_ids':sorted({f['source']['library'] for f in result['files']}),'views':[],
                          'note':'自动链接观察；来源匹配不证明内容一致'}
                snapshot=build_snapshot(root,metadata,{f['path']:f['source']['file_key'] for f in result['files']},deliveries)
                for observed,linked in zip(sorted(result['files'],key=lambda x:x['path']),snapshot['linked_files']):
                    if observed['target']!=linked['resolved_path'] or linked['source_match']!='MATCHED_RAW' or linked['source_ref']['delivery_id']!=observed['source']['delivery_id']:
                        raise ValueError('正式链接在观察与快照之间变化')
                write_atomic(folder/sid/'snapshot.json',snapshot,immutable=True)
                result['snapshot_id']=sid;result['snapshot_note']='已发布可信范围内的正式快照'
        except (OSError,ValueError,KeyError,TypeError) as exc:
            result['snapshot_note']=f'快照未发布：{exc}'
    write_atomic(Path(runs)/'formal_observations'/f"{result['observation_id']}.json",result,immutable=True)
    return result
