"""Inventory RAW and Formal roots without fabricating file or delivery identities."""
from collections import defaultdict
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import uuid
import csv

from .minimal_delivery import directory_birthtime, version_date
from .timestamps import utc_text,instant
from .source_discovery import _DEFAULT_VERSION, natural_version_key
from .layout import SAFE, library_folder, next_filename
from ai_lib_qor.versions.store import locked, write_atomic


def _view(path):
    name=path.lower().removesuffix('.gz')
    ext=Path(name).suffix
    return {'.lef':'LEF','.lib':'LIBERTY','.gds':'GDS','.sp':'SPICE','.spice':'SPICE',
            '.cdl':'CDL','.v':'VERILOG','.sv':'VERILOG','.sdc':'SDC','.db':'DB',
            '.spef':'SPEF','.upf':'UPF','.cpf':'CPF','.pdf':'DOC','.txt':'DOC',
            '.md':'DOC','.xlsx':'DOC','.xls':'DOC'}.get(ext,'OTHER')


def infer_nl_version(root):
    match=re.search(r'(?i)NL[\d._-]+',Path(root).name)
    if not match:raise ValueError('无法从 NL 目录名识别版本，请使用 --nl-version')
    return re.sub(r'[_-]','.',match.group()).upper()


def _version_directory(name):
    if re.match(r'^\d{8}(?:$|[_-])',name):return version_date(name) is not None
    return bool(_DEFAULT_VERSION.fullmatch(name))


def _inventory_raw(raw,warnings,observations=None):
    records=[];lookup={}
    for vendor in sorted(raw.iterdir()):
        if vendor.is_symlink() or not vendor.is_dir() or not SAFE.fullmatch(vendor.name):continue
        for library in sorted(vendor.iterdir()):
            if library.is_symlink() or not library.is_dir() or not SAFE.fullmatch(library.name):continue
            children=[x for x in library.iterdir() if not x.is_symlink() and x.is_dir()]
            versions=[x for x in children if SAFE.fullmatch(x.name) and _version_directory(x.name)]
            if versions:
                for item in children:
                    if item not in versions:warnings.append(f'未识别为版本目录，已跳过: {item}')
            for version in sorted(versions,key=lambda p:natural_version_key(p.name)):
                files=[];errors=[];metadata={}
                for current,dirs,names in os.walk(version,followlinks=False,onerror=lambda e:errors.append(str(e))):
                    dirs.sort();names.sort()
                    for name in list(dirs):
                        if (Path(current)/name).is_symlink():errors.append('目录链接未扫描: '+str(Path(current)/name));dirs.remove(name)
                    for name in names:
                        p=Path(current)/name
                        if p.is_symlink() or not p.is_file():errors.append('非普通文件未扫描: '+str(p));continue
                        rel=p.relative_to(version).as_posix()
                        try:info=p.stat()
                        except OSError as exc:errors.append(str(exc));continue
                        files.append(rel);metadata[rel]=(info.st_size,info.st_mtime_ns)
                if errors:
                    warnings.extend(errors);warnings.append(f'{version}: 盘点不完整，不发布');continue
                if not files:continue
                views=defaultdict(list)
                for path in files:views[_view(path)].append(path)
                row={'vendor':vendor.name,'library':library.name,'version':version.name,
                     'version_date':version_date(version.name),'directory_created_at':directory_birthtime(version),
                     'root':str(version),'views':dict(sorted(views.items()))}
                records.append(row)
                if observations is not None:observations[(vendor.name,library.name,version.name)]=metadata
                for path in files:lookup.setdefault(str(version/path),[]).append((vendor.name,library.name,version.name,_view(path)))
    return records,lookup


def _inventory_formal(root,lookup,nl_version,warnings,unresolved):
    groups=defaultdict(lambda:defaultdict(lambda:defaultdict(list)))
    def onerror(exc):
        warnings.append('NL 目录不可读取: '+str(exc))
        unresolved.append({'path':str(getattr(exc,'filename','') or ''),'target':None,'resolved':None,'reason':'DIRECTORY_ERROR'})
    for current,dirs,names in os.walk(root,followlinks=False,onerror=onerror):
        dirs.sort();names.sort()
        for name in list(dirs):
            p=Path(current)/name
            if p.is_symlink():
                rel=p.relative_to(root).as_posix();warnings.append('NL 目录链接未展开: '+rel)
                unresolved.append({'path':rel,'target':os.readlink(p),'resolved':None,'reason':'DIRECTORY_SYMLINK'});dirs.remove(name)
        for name in names:
            path=Path(current)/name;rel=path.relative_to(root).as_posix()
            if not path.is_symlink():warnings.append('NL 普通文件未归属: '+rel);continue
            try:target=os.readlink(path)
            except OSError as exc:
                warnings.append(f'NL 链接不可读取: {rel}: {exc}')
                unresolved.append({'path':rel,'target':None,'resolved':None,'reason':'READLINK_ERROR'});continue
            try:
                resolved=path.resolve(strict=True)
                if not resolved.is_file():raise OSError('目标不是普通文件')
            except (OSError,RuntimeError) as exc:
                warnings.append(f'NL 链接失效: {rel}: {exc}')
                unresolved.append({'path':rel,'target':target,'resolved':None,'reason':'UNRESOLVED'});continue
            matches=lookup.get(str(resolved),[])
            if len(matches)!=1:
                warnings.append(f'NL 来源无法唯一归属: {rel} → {resolved}')
                unresolved.append({'path':rel,'target':target,'resolved':str(resolved),'reason':'UNMATCHED' if not matches else 'AMBIGUOUS'});continue
            vendor,library,version,view=matches[0]
            groups[(vendor,library)][view][version].append({'path':rel,'target':target,'resolved':str(resolved)})
    at=utc_text()
    return [{'version':nl_version,'vendor':vendor,'library':library,'root':str(root),'observed_at':at,
             'views':{v:dict(sorted(versions.items())) for v,versions in sorted(views.items())}}
            for (vendor,library),views in sorted(groups.items())]


def update_pointer(folder,name,target):
    pointer=folder/name
    if pointer.exists() and not pointer.is_symlink():raise ValueError(f'拒绝覆盖非软链接指针: {pointer}')
    if Path(target).name!=str(target):raise ValueError('指针目标必须在本库目录')
    if not (folder/target).is_file() or (folder/target).is_symlink():raise ValueError('指针目标无效')
    if pointer.is_symlink() and os.readlink(pointer)==target:return
    tmp=folder/('.pointer_'+uuid.uuid4().hex)
    try:os.symlink(target,tmp);os.replace(tmp,pointer)
    finally:tmp.unlink(missing_ok=True)


def _latest_delivery(folder,warnings,work,vendor,library):
    items=[]
    for path in folder.glob('delivery_*.json'):
        if path.is_symlink():raise ValueError('交付文件不能是链接')
        value=json.loads(path.read_text(encoding='utf-8'));items.append((path,value))
    if not items:return
    if len(items)==1:chosen=items[0][0]
    else:
      try:
        from ai_lib_qor.application.minimal_file_index import _ordered,_configured_times
        ordered=_ordered([value for _,value in items],_configured_times(work,vendor,library))
        chosen=next(path for path,value in items if value['version']==ordered[-1]['version'])
      except ValueError:
        pointer=folder/'latest_delivery.json'
        if pointer.is_symlink():pointer.unlink()
        warnings.append(f'{folder}: 版本日期缺失或重复，最新交付次序未确认')
        return
    update_pointer(folder,'latest_delivery.json',chosen.name)


def build_from_roots(raw_root,nl_root,output,*,nl_version=None,update_raw=True,update_formal=True,update_index=True,auto_effective=True,vendor=None,library=None):
    if not any((update_raw,update_formal,update_index)):raise ValueError('至少选择一项更新')
    if bool(vendor)!=bool(library) or any(x and (not SAFE.fullmatch(x) or x in ('.','..')) for x in (vendor,library)):raise ValueError('供应商和库必须同时指定且名称安全')
    raw=Path(raw_root).resolve(strict=True) if (update_raw or update_formal) and raw_root else None
    nl=Path(nl_root).resolve(strict=True) if update_formal and nl_root else None
    out=Path(output).resolve()
    if (update_raw or update_formal) and (raw is None or not raw.is_dir()):raise ValueError('需要 RAW 总目录')
    if update_formal and (nl is None or not nl.is_dir()):raise ValueError('需要 NL 总目录')
    if any(out.is_relative_to(p) or p.is_relative_to(out) for p in (raw,nl) if p is not None):raise ValueError('输出目录不得与 RAW 或 NL 目录重叠')
    version=(nl_version or infer_nl_version(nl)) if update_formal else None
    if version and (not SAFE.fullmatch(version) or version in ('.','..')):raise ValueError('NL 版本名称不安全')
    observations={}
    warnings=[];deliveries,lookup=_inventory_raw(raw,warnings,observations) if raw else ([],{})
    unresolved=[]
    formals=_inventory_formal(nl,lookup,version,warnings,unresolved) if update_formal else []
    out.mkdir(parents=True,exist_ok=True)
    result={'delivery_created':0,'delivery_unchanged':0,'formal_created':0,'formal_unchanged':0,'indexes_updated':0,'indexes_unchanged':0,'indexes_failed':0,'effective_published':0,'effective_pending':0,'warnings':warnings}
    if update_formal:
        status='PARTIAL' if unresolved else 'COMPLETE'
        result.update(formal_observation_status=status,formal_unresolved=unresolved)
        log=out/'formal_observations.tsv'
        with locked(out):
            if log.is_symlink():raise ValueError('正式来源观察日志不能为软链接')
            with log.open('a',encoding='utf-8',newline='') as stream:
                writer=csv.writer(stream,delimiter='\t',lineterminator='\n')
                stamp=utc_text();run=uuid.uuid4().hex
                writer.writerow([stamp,str(nl),version,status,'','','','',run])
                for formal in formals:
                    for kind,versions in formal['views'].items():
                        for source_version,links in versions.items():
                            for link in links:
                                writer.writerow([stamp,str(nl),version,status,link['path'],link['target'],link['resolved'],f"MATCHED:{formal['vendor']}/{formal['library']}/{source_version}/{kind}",run])
                for item in unresolved:writer.writerow([stamp,str(nl),version,status,item['path'],item['target'] or '',item['resolved'] or '',item['reason'],run])
                stream.flush();os.fsync(stream.fileno())
    grouped=defaultdict(lambda:{'deliveries':[],'formals':[]})
    for row in deliveries if update_raw else []:grouped[(row['vendor'],row['library'])]['deliveries'].append(row)
    for row in formals:grouped[(row['vendor'],row['library'])]['formals'].append(row)
    if update_index and (out/'libraries').is_dir():
        for folder in (out/'libraries').glob('*/*'):
            if folder.is_dir() and not folder.is_symlink():grouped[(folder.parent.name,folder.name)]
    if vendor:grouped={key:row for key,row in grouped.items() if key==(vendor,library)}
    for (vendor,library),rows in sorted(grouped.items()):
        folder=library_folder(out,vendor,library)
        with locked(folder):
            observation_path=folder/'raw_observations.tsv'
            if observation_path.is_symlink():raise ValueError('RAW 观察记录不能为软链接')
            baseline={}
            if observation_path.exists():
                with observation_path.open(encoding='utf-8',newline='') as stream:
                    for record in csv.reader(stream,delimiter='\t'):
                        if len(record)!=5:raise ValueError('RAW 观察记录格式无效')
                        old_version,old_path,size,mtime,_=record
                        baseline.setdefault(old_version,{})[old_path]=(int(size),int(mtime))
            new_observations=[]
            for delivery in rows['deliveries']:
                version_name=delivery['version'];current=observations[(vendor,library,version_name)]
                if version_name in baseline:
                    changed=[name for name,stat in current.items() if name in baseline[version_name] and baseline[version_name][name]!=stat]
                    if changed:warnings.append(f'{vendor}/{library}/{version_name}: {len(changed)} 个文件大小或修改时间变化，疑似原地修改；不证明内容相同或历史可还原')
                else:
                    stamp=utc_text()
                    new_observations.extend([version_name,path,size,mtime,stamp] for path,(size,mtime) in sorted(current.items()))
            if new_observations:
                with observation_path.open('a',encoding='utf-8',newline='') as stream:
                    csv.writer(stream,delimiter='\t',lineterminator='\n').writerows(new_observations)
                    stream.flush();os.fsync(stream.fileno())
            from ai_lib_qor.application.minimal_effective import _history
            history=_history(folder,library)
            state_path=folder/'.auto_effective_state.json'
            if state_path.is_symlink():raise ValueError('自动更新状态不能为软链接')
            state=json.loads(state_path.read_text(encoding='utf-8')) if state_path.exists() else {'pending':[]}
            if not isinstance(state,dict) or set(state)!={'pending'} or not isinstance(state['pending'],list) or any(not isinstance(x,str) for x in state['pending']):raise ValueError('自动更新状态无效')
            for delivery in rows['deliveries']:
                prior=[]
                for p in sorted(folder.glob('delivery_*.json')):
                    if p.is_symlink():raise ValueError('交付文件不能是链接')
                    value=json.loads(p.read_text(encoding='utf-8'))
                    if set(value)!={'vendor','library','version','version_date','directory_created_at','root','views'}:raise ValueError('输出目录含非七字段交付，需使用独立目录')
                    if value['version']==delivery['version']:prior.append(value)
                if len(prior)>1:raise ValueError('输出含重复版本交付')
                if prior:
                    former=dict(prior[0]);current=dict(delivery)
                    for value in (former,current):
                        if value.get('directory_created_at'):value['directory_created_at']=utc_text(value['directory_created_at'])
                    if former!=current:
                        changed=[key for key in former if former.get(key)!=current.get(key)]
                        names={'directory_created_at':'目录创建时间','views':'文件清单','root':'来源目录'}
                        warnings.append(f'{vendor}/{library}/{delivery["version"]}: '+ '、'.join(names.get(key,key) for key in changed)+'与已登记交付不同；保留历史，未比较文件内容')
                    else:result['delivery_unchanged']+=1
                    continue
                stamp=delivery['version_date'].replace('-','') if delivery['version_date'] else 'undated'
                prefix=f'delivery_{library}_{stamp}'
                if history and delivery['version'] not in state['pending']:
                    state['pending'].append(delivery['version']);write_atomic(state_path,state)
                write_atomic(folder/next_filename(folder,prefix),delivery,immutable=True);result['delivery_created']+=1
            if update_raw:_latest_delivery(folder,warnings,out,vendor,library)
            for formal in rows['formals']:
                previous=[]
                for p in sorted(folder.glob('formal_'+version+'_*.json')):
                    if p.is_symlink():raise ValueError('正式快照文件不能是链接')
                    value=json.loads(p.read_text(encoding='utf-8'))
                    previous.append((instant(value['observed_at']),p,value))
                # New snapshots have second precision. Treat legacy fractional times
                # in the same second as ties, then use the stable name/sequence.
                previous.sort(key=lambda x:(utc_text(x[0]),x[1].name))
                if unresolved:
                    warnings.append(f'{vendor}/{library}: 正式来源观察不完整，暂不发布快照')
                    continue
                compare=lambda x:{k:v for k,v in x.items() if k!='observed_at'}
                if previous and compare(previous[-1][2])==compare(formal):
                    result['formal_unchanged']+=1
                    update_pointer(folder,'latest_formal_'+version+'.json',previous[-1][1].name)
                    continue
                stamp=instant(formal['observed_at']).strftime('%Y%m%dT%H%M%SZ')
                target=folder/next_filename(folder,'formal_'+version+'_'+stamp)
                write_atomic(target,formal,immutable=True);result['formal_created']+=1
                update_pointer(folder,'latest_formal_'+version+'.json',target.name)
            index_ok=False
            if update_index:
                try:
                    from ai_lib_qor.application.minimal_file_index import refresh_index_locked
                    index_result=refresh_index_locked(out,vendor,library)
                    index_ok=True
                    result['indexes_unchanged' if index_result['state']=='UNCHANGED' else 'indexes_updated']+=1
                except (OSError,ValueError,KeyError,TypeError) as exc:
                    result['indexes_failed']+=1
                    warnings.append(f'{vendor}/{library}: 文件索引未刷新: {exc}')
            if update_raw and auto_effective and update_index and index_ok and state['pending']:
                try:
                    from ai_lib_qor.application.minimal_effective import _deliveries,_flat,_candidate,_save,_audit_recover
                    from ai_lib_qor.application.minimal_file_index import _ordered,_configured_times
                    from ai_lib_qor.application.path_config import excluded_versions
                    deliveries=_deliveries(folder,vendor,library)
                    ordered=_ordered(list(deliveries.values()),_configured_times(out,vendor,library))
                    ranks={d['version']:n for n,d in enumerate(ordered)}
                    if any(v not in ranks for v in state['pending']):raise ValueError('待处理交付尚未完成登记')
                    excluded=excluded_versions(out,vendor,library)
                    for pending in sorted(state['pending'],key=lambda v:ranks[v]):
                        history=_history(folder,library)
                        if history:
                            update_pointer(folder,'latest_effective.json',history[-1][1].name)
                            _audit_recover(folder,history[-1][2]['revision'])
                        if pending not in excluded and history:
                            members=_flat(history[-1][2]['views']);delivery=deliveries[pending]
                            ops={'set':[{'view':view,'version':pending,'path':path} for view,path in sorted(members)
                                        if path in delivery['views'].get(view,[]) and ranks[pending]>ranks[members[(view,path)]]], 'remove':[]}
                            if ops['set']:
                                hist,last,row=_candidate(folder,vendor,library,ops,work=out)
                                published=_save(folder,library,hist[-1][0]+1,row,out,actor='automatic',action='AUTO_UPDATE')
                                result['effective_published']+=1
                                if published['state']=='PUBLISHED_INDEX_STALE':raise ValueError('有效版本已发布，但索引刷新失败: '+published['index_error'])
                        state['pending'].remove(pending);write_atomic(state_path,state)
                except (OSError,ValueError,KeyError,TypeError) as exc:
                    warnings.append(f'{vendor}/{library}: 自动发布未完成: {exc}')
            if state['pending']:
                result['effective_pending']+=len(state['pending'])
                if update_raw and auto_effective and not update_index:warnings.append(f'{vendor}/{library}: 自动发布需要刷新索引，交付保持待处理')
    return result
