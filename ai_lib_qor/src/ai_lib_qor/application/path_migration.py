"""Convert one legacy library to a separate path-contract workspace."""
import json
import os
import tempfile
import csv
from collections import Counter
from pathlib import Path
from ai_lib_qor.sources.layout import library_folder, next_filename
from ai_lib_qor.sources.root_inventory import update_pointer
from ai_lib_qor.sources.timestamps import utc_text, instant
from ai_lib_qor.versions.store import locked, validate, write_atomic
from .minimal_file_index import refresh_index
from .path_config import registration_times


def _reconcile_index(old,index,refs,vendor,library,report):
    if old.get('schema')!='file_index.v3' or old.get('scope')!={'vendor':vendor,'library':library}:
        raise ValueError('旧文件索引格式或范围不受支持，不能声称完成对账')
    old_rows=[];new_rows=[];unresolved=[];order_issues=[]
    snapshots={(nl,s['snapshot_id']):s for nl,g in old.get('formal_nl',{}).items() for s in g.get('snapshots',[])}
    deliveries={d['delivery_id']:d for d in old.get('deliveries',[])}
    for d in old.get('deliveries',[]):old_rows.append(('delivery','','',d['version'],d['root']))
    for d in index.get('deliveries',[]):new_rows.append(('delivery','','',d['version'],d['root']))
    for (nl,_),snap in snapshots.items():
        old_rows.append(('snapshot','','',nl,json.dumps([utc_text(snap['observed_at']),snap['root']],ensure_ascii=False)))
    for snap in index.get('nl_snapshots',[]):
        new_rows.append(('snapshot','','',snap['nl_version'],json.dumps([utc_text(snap['observed_at']),snap['root']],ensure_ascii=False)))
    old_revisions=[]
    for owner,group in old.get('effective_sets',{}).items():
        if owner!=library:
            unresolved.append(('revision','',owner,'旧索引包含其他有效集，当前迁移仅支持本库'));continue
        for item in group.get('revisions',[]):
            old_revisions.append(item['revision']);old_rows.append(('revision','','',item['revision'],''))
    for revision in index.get('revisions',[]):new_rows.append(('revision','','',revision,''))
    for kind,before,after in (
        ('delivery',[x['version'] for x in reversed(old.get('deliveries',[]))],[x['version'] for x in index.get('deliveries',[])]),
        ('revision',list(reversed(old_revisions)),index.get('revisions',[]))):
        common=set(before)&set(after);left=[x for x in before if x in common];right=[x for x in after if x in common]
        if left!=right:order_issues.append((kind,'','',json.dumps({'old_oldest_first':left,'new_oldest_first':right},ensure_ascii=False)))
    for view,group in old['views'].items():
        for relative,history in group['files'].items():
            old_raw_order=[];old_eff_order=[]
            for item in history.get('raw',[]):
                ref=refs.get((item.get('delivery_id'),item.get('file_id')))
                if not ref:unresolved.append(('raw',view,relative,str(item)));continue
                kind,version,path=ref
                if (kind,path)!=(view,relative):
                    unresolved.append(('raw',view,relative,'旧索引路径与交付引用不一致: '+str(item)));continue
                meta=deliveries.get(item['delivery_id'])
                if not meta or not isinstance(meta.get('root'),str):unresolved.append(('raw',view,relative,'旧索引缺少交付根目录'));continue
                old_rows.append(('raw',kind,path,version,os.path.normpath(os.path.join(meta['root'],path))))
                old_raw_order.append(version)
            for item in history.get('formal',[]):
                snap=snapshots.get((item.get('nl'),item.get('snapshot_id')))
                if not snap:unresolved.append(('formal',view,relative,str(item)));continue
                link=os.path.normpath(os.path.join(snap['root'],item['link_path']))
                detail=json.dumps([utc_text(snap['observed_at']),link,item.get('link_target'),item.get('resolved_path')],ensure_ascii=False)
                old_rows.append(('formal',view,relative,item['nl'],detail))
            for owner,entries in history.get('effective',{}).items():
                for item in entries:
                    candidates=[ref for (d,_),ref in refs.items() if d==item.get('delivery_id') and ref[0]==view and ref[2]==relative]
                    if len(candidates)!=1:unresolved.append(('effective',view,relative,str(item)));continue
                    old_rows.append(('effective',view,relative,item['revision'],candidates[0][1]))
                    old_eff_order.append(item['revision'])
            new_history=index['views'].get(view,{}).get(relative,{})
            for kind,old_order,new_order in (
                ('raw',old_raw_order,[x['version'] for x in new_history.get('raw',[])]),
                ('effective',old_eff_order,[x['revision'] for x in new_history.get('effective',[])])):
                common=set(old_order)&set(new_order)
                before=[x for x in reversed(old_order) if x in common]
                after=[x for x in new_order if x in common]
                if before!=after:order_issues.append((kind,view,relative,json.dumps({'old_oldest_first':before,'new_oldest_first':after},ensure_ascii=False)))
    for view,group in index['views'].items():
        for relative,history in group.items():
            new_rows.extend(('raw',view,relative,x['version'],x['path']) for x in history['raw'])
            new_rows.extend(('formal',view,relative,x['version'],json.dumps([utc_text(x['observed_at']),x['link_path'],x['link_target'],x['resolved_path']],ensure_ascii=False)) for x in history['nl'])
            new_rows.extend(('effective',view,relative,x['revision'],x['version']) for x in history['effective'])
    a=Counter(old_rows);b=Counter(new_rows);missing=a-b;added=b-a;matched=a&b
    with report.open('w',encoding='utf-8',newline='') as stream:
        writer=csv.writer(stream,delimiter='\t',lineterminator='\n');writer.writerow(['status','category','view','path','version_or_revision','detail'])
        for status,items in [('MATCH',matched),('MISSING',missing),('ADDED',added)]:
            for row,count in sorted(items.items()):
                for _ in range(count):writer.writerow([status,*row])
        for category,view,path,detail in unresolved:writer.writerow(['UNRESOLVED',category,view,path,'',detail])
        for category,view,path,detail in order_issues:writer.writerow(['ORDER_DIFFERENT',category,view,path,'',detail])
        stream.flush();os.fsync(stream.fileno())
    return {'matched':sum(matched.values()),'missing':sum(missing.values()),'added':sum(added.values()),'unresolved':len(unresolved),'order_differences':len(order_issues)}


def migrate_legacy_library(source, destination, vendor, library):
    source=Path(source).resolve(strict=True);destination=Path(destination).resolve()
    if source==destination or source.is_relative_to(destination) or destination.is_relative_to(source):
        raise ValueError('迁移源与目标必须为独立工作目录')
    source_folder=library_folder(source,vendor,library)
    acceptance=source_folder/f'effective_{library}_acceptance.jsonl'
    if acceptance.is_symlink():raise ValueError('旧采纳历史不能为软链接')
    events=[]
    if acceptance.is_file():
        for line in acceptance.read_text(encoding='utf-8').splitlines():
            if line.strip():
                event=json.loads(line);validate(event,'acceptance_event');events.append(event)
    destination.mkdir(parents=True,exist_ok=True)
    target=library_folder(destination,vendor,library)
    with locked(destination):
        if target.exists():raise ValueError('目标库已存在，不能覆盖')
        with tempfile.TemporaryDirectory(prefix='.path-migration-',dir=destination) as temp:
            stage=Path(temp);folder=stage/'libraries'/vendor/library;folder.mkdir(parents=True)
            refs={};known={};deliveries=[]
            for path in sorted(source_folder.glob('delivery_*.json')):
                if path.is_symlink():raise ValueError('旧交付不能为软链接')
                original=json.loads(path.read_text(encoding='utf-8'))
                if original.get('schema_version')=='delivery_record.v1':
                    from ai_lib_qor.sources.minimal_delivery import simplify,compatibility
                    validate(original,'delivery_record')
                    delivery=simplify(original)
                    evidence=compatibility(original)
                else:
                    delivery=original
                    evidence_path=path.with_name('evidence_'+path.stem+'.json')
                    if evidence_path.is_symlink() or not evidence_path.is_file():raise ValueError('旧交付缺少身份映射')
                    evidence=json.loads(evidence_path.read_text(encoding='utf-8'))['legacy_compatibility']
                validate(delivery,'delivery_minimal')
                if (delivery['vendor'],delivery['library'])!=(vendor,library):raise ValueError('交付范围不匹配')
                old_id=evidence['metadata']['delivery_id']
                for view,paths in delivery['views'].items():
                    for relative in paths:
                        old=evidence['files'][relative];key=(old_id,old['file_id'])
                        if key in refs:raise ValueError('旧文件身份不唯一')
                        refs[key]=(view,delivery['version'],relative)
                        absolute=os.path.normpath(os.path.join(delivery['root'],relative))
                        known.setdefault(absolute,[]).append((view,delivery['version'],relative))
                stamp=delivery['version_date'].replace('-','') if delivery['version_date'] else 'undated'
                name=next_filename(folder,'delivery_'+library+'_'+stamp)
                write_atomic(folder/name,delivery,immutable=True);deliveries.append((delivery,name))
            if not deliveries:raise ValueError('旧库没有交付')
            snapshots=0;latest_formal={};formal_unresolved=[]
            for path in sorted(source_folder.glob('formal_*.json')):
                if path.is_symlink():raise ValueError('旧正式快照不能为软链接')
                old=json.loads(path.read_text(encoding='utf-8'))
                if set(old)=={'version','vendor','library','root','observed_at','views'}:
                    formal=old
                else:
                    views={}
                    for link in old['linked_files']:
                        matches=known.get(link.get('resolved_path'),[])
                        if len(matches)!=1 or not link.get('link_target'):
                            formal_unresolved.append({'nl':old['formal_nl_id'],'observed_at':old['observed_at'],'root':old['source_root'],
                              'path':link.get('link_path',''),'target':link.get('link_target'),'resolved':link.get('resolved_path'),
                              'reason':'UNMATCHED_OR_AMBIGUOUS' if len(matches)!=1 else 'MISSING_TARGET'})
                            continue
                        view,version,_=matches[0]
                        target_text=link.get('link_target')
                        views.setdefault(view,{}).setdefault(version,[]).append({'path':link['link_path'],'target':target_text,'resolved':link['resolved_path']})
                    formal={'version':old['formal_nl_id'],'vendor':vendor,'library':library,'root':old['source_root'],
                            'observed_at':utc_text(old['observed_at']),'views':views}
                validate(formal,'formal_path')
                if (formal['vendor'],formal['library'])!=(vendor,library):raise ValueError('正式快照范围不匹配')
                stamp=instant(formal['observed_at']).strftime('%Y%m%dT%H%M%SZ')
                name=next_filename(folder,'formal_'+formal['version']+'_'+stamp)
                write_atomic(folder/name,formal,immutable=True)
                key=(instant(formal['observed_at']),name)
                if formal['version'] not in latest_formal or key>latest_formal[formal['version']]:latest_formal[formal['version']]=key
                snapshots+=1
            if formal_unresolved:
                with (folder/'formal_observations.tsv').open('w',encoding='utf-8',newline='') as stream:
                    writer=csv.writer(stream,delimiter='\t',lineterminator='\n')
                    for x in formal_unresolved:writer.writerow([x['observed_at'],x['root'],x['nl'],'PARTIAL',x['path'],x['target'] or '',x['resolved'] or '',x['reason'],'migration'])
                    stream.flush();os.fsync(stream.fileno())
                latest_formal={}
            for nl,(_,name) in latest_formal.items():update_pointer(folder,'latest_formal_'+nl+'.json',name)
            revisions=0
            for path in sorted(source_folder.glob('effective_'+library+'_*.json')):
                suffix=path.stem.rsplit('_',1)[-1]
                if not suffix.isdigit():continue
                if path.is_symlink():raise ValueError('旧有效版本不能为软链接')
                old=json.loads(path.read_text(encoding='utf-8'))
                if old.get('schema')=='effective.simple.v2':
                    from .effective_json import _flat_views
                    if old['owner']!={'type':'SOURCE_LIBRARY','id':library} or old['scope']!={'vendor':vendor,'library':library}:
                        raise ValueError('跨库或非来源库有效集需单独迁移')
                    views={}
                    for (view,relative),ref in _flat_views(old).items():
                        if (ref['vendor'],ref['library'])!=(vendor,library):raise ValueError('跨库有效来源需单独迁移')
                        candidates=[entry for (delivery_id,_),entry in refs.items()
                                    if delivery_id==ref['delivery'] and entry==(view,ref['version'],relative)]
                        if len(candidates)!=1:raise ValueError('有效成员不能唯一映射旧交付')
                        views.setdefault(view,{}).setdefault(ref['version'],[]).append(relative)
                    row={'vendor':vendor,'library':library,'revision':old['revision'],
                         'created_at':utc_text(old['created_at']),'views':views}
                elif 'views' in old and 'revision' in old:
                    row=old
                else:
                    owner=old['owner']
                    if owner.get('owner_type')!='SOURCE_LIBRARY' or owner.get('owner_id')!=library:raise ValueError('跨库或非来源库有效集需单独迁移')
                    views={};seen=set()
                    for member in old['members']:
                        ref=member['source_ref']
                        if ref.get('kind')!='delivery_file' or ref.get('source_library_id')!=library:raise ValueError('跨库或非交付来源需单独迁移')
                        view,version,relative=refs[(ref['delivery_id'],ref['file_id'])]
                        if (view,relative) in seen:raise ValueError('有效成员路径不唯一')
                        seen.add((view,relative));views.setdefault(view,{}).setdefault(version,[]).append(relative)
                    row={'vendor':vendor,'library':library,'revision':old['revision_id'],
                         'created_at':utc_text(old['created_at']),'views':views}
                validate(row,'effective_path')
                if (row['vendor'],row['library'])!=(vendor,library):raise ValueError('有效版本范围不匹配')
                number=int(suffix)
                if number!=revisions+1 or row['revision']!=f'rev_{number:04d}':raise ValueError('有效版本顺序不连续')
                name=f'effective_{library}_{number:03d}.json'
                write_atomic(folder/name,row,immutable=True);update_pointer(folder,'latest_effective.json',name);revisions+=1
            old_accepted=None;notes=[]
            if events:
                from ai_lib_qor.versions.index_projector import project
                adapted=[{'revision_id':f'rev_{number:04d}','effective_set_id':library,
                          'owner':{'owner_type':'SOURCE_LIBRARY','owner_id':library,'home_source_library_id':library}}
                         for number in range(1,revisions+1)]
                old_accepted=project(adapted,events,utc_text())['current_accepted_revision']
                with (folder/'legacy_acceptance.tsv').open('w',encoding='utf-8',newline='') as stream:
                    writer=csv.writer(stream,delimiter='\t',lineterminator='\n')
                    writer.writerow(['acted_at','action','revision','actor','reason'])
                    for event in events:writer.writerow([event['acted_at'],event['action'],event['revision_id'],event['actor'],event['reason']])
                    stream.flush();os.fsync(stream.fileno())
                latest=f'rev_{revisions:04d}' if revisions else None
                if old_accepted!=latest:notes.append(f'旧采纳版本为 {old_accepted or "无"}；新目录最新发布版本为 {latest or "无"}，历史保存在 legacy_acceptance.tsv')
            times=registration_times(source,vendor,library)
            if times:write_atomic(stage/'path_sources.json',{'libraries':{vendor:{library:{'version_registration_times':times}}}})
            result=refresh_index(stage,vendor,library)
            index=json.loads((folder/'file_index.json').read_text(encoding='utf-8'))
            comparison=None
            old_index=source_folder/'file_index.json'
            if old_index.is_symlink():raise ValueError('旧索引不能为软链接')
            if old_index.is_file():
                comparison=_reconcile_index(json.loads(old_index.read_text(encoding='utf-8')),index,refs,vendor,library,folder/'file_index_reconciliation.tsv')
                if comparison['missing'] or comparison['unresolved'] or comparison['order_differences']:notes.append('旧文件索引存在未匹配、顺序不同或无法对账的历史，请检查 file_index_reconciliation.tsv')
            if formal_unresolved:notes.append(f'{len(formal_unresolved)} 条正式链接未归属，已保存在 formal_observations.tsv；未发布最新正式指针')
            latest=index['deliveries'][-1]['version']
            matches=[name for delivery,name in deliveries if delivery['version']==latest]
            if len(matches)!=1:raise ValueError('最新交付不唯一')
            update_pointer(folder,'latest_delivery.json',matches[0])
            target.parent.mkdir(parents=True,exist_ok=True)
            os.rename(folder,target)
            if times:
                from .path_config import load_path_config
                config=load_path_config(destination)
                config.setdefault('libraries',{}).setdefault(vendor,{}).setdefault(library,{})['version_registration_times']=times
                write_atomic(destination/'path_sources.json',config)
            return {'vendor':vendor,'library':library,'deliveries':len(deliveries),'formal_snapshots':snapshots,
                    'revisions':revisions,'path':str(target),'index':result['state'],
                    'legacy_accepted_revision':old_accepted,'warnings':notes,
                    'formal_unresolved':len(formal_unresolved),'index_reconciliation':comparison}
