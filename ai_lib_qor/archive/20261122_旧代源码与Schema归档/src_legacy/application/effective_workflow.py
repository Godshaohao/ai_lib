"""Conservative Effective update using archived, explicitly confirmed identities."""
from copy import deepcopy
import re
from pathlib import Path

from .data_query import LibraryDataQuery, _subgroup, _view
from .effective_json import _flat_views
from .file_index import repository_order
from .latest_pointers import _config
from ai_lib_qor.sources.layout import SAFE, library_folder
from ai_lib_qor.versions.store import now, read_json, validate


def _history(folder, set_id):
    if not SAFE.fullmatch(set_id) or set_id in ('.','..'): raise ValueError('有效集标识无效')
    result=[]
    for path in folder.glob(f'effective_{set_id}_[0-9]*.json'):
        match=re.fullmatch(re.escape(f'effective_{set_id}_')+r'(\d+)\.json',path.name)
        if not match: continue
        if path.is_symlink(): raise ValueError('有效版本不能是符号链接')
        data=read_json(path,'effective_simple_v2')
        if data['revision'] != f"rev_{int(match.group(1)):04d}": raise ValueError('版本文件与身份不一致')
        result.append(data)
    result.sort(key=lambda x:int(x['revision'][4:]))
    for i,row in enumerate(result):
        if row['parent'] != (result[i-1]['revision'] if i else None): raise ValueError('版本父链不连续')
    return result


def preview_effective_update(work,vendor,library,set_id,delivery_id,*,include_file_keys=None):
    folder=library_folder(work,vendor,library)
    q=LibraryDataQuery(work,Path(work)/'.query-no-runs')
    history=_history(folder,set_id)
    if not history:return {'state':'NEEDS_REVIEW','reasons':['有效集尚未初始化；需要选择 RAW 或 Formal 基准']}
    parent=history[-1]; scope=parent['scope']
    if scope!={'vendor':vendor,'library':library}:raise ValueError('有效集范围不匹配')
    items=[x for x in q.deliveries if (x['record']['vendor_id'],x['record']['source_library_id'])==(vendor,library)]
    ordered,basis=repository_order(items,_config(work,vendor,library))
    if ordered is None:return {'state':'NEEDS_REVIEW','parent_revision':parent['revision'],'reasons':['交付业务顺序未确认']}
    positions={x['record']['delivery_id']:i for i,x in enumerate(ordered)}
    matches=[x for x in items if x['record']['delivery_id']==delivery_id]
    if len(matches)!=1:raise ValueError('交付不存在或不唯一')
    excluded=excluded_deliveries(work,vendor,library,set_id)
    if delivery_id in excluded:return {'state':'EXCLUDED','parent_revision':parent['revision'],'reasons':['此交付已从该有效集排除']}
    item=matches[0];record=item['record']; old=_flat_views(parent)
    source_records={};groups={}
    def collect_groups(kind,bucket,parents=()):
        for key,value in bucket.items():
            if isinstance(value,dict):collect_groups(kind,value,parents+(key,))
            else:groups[(kind,key)]=parents
    for kind,bucket in parent['views'].items():collect_groups(kind,bucket)
    for (kind,path),src in old.items():
        candidates=[x for x in q.deliveries if (x['record']['vendor_id'],x['record']['source_library_id'])==(src['vendor'],src['library']) and (x['record']['delivery_id']==src['delivery'] or Path(x['path']).stem==src['delivery']) and x['record']['supplier_version']==src['version']]
        if len(candidates)!=1:return {'state':'NEEDS_REVIEW','parent_revision':parent['revision'],'reasons':['父版本来源交付缺失或不唯一']}
        files=[f for f in candidates[0]['files'] if f['relative_path']==path and _view(f['view'],path)==kind]
        if len(files)!=1 or files[0]['identity_status']!='CONFIRMED' or not files[0].get('file_key'):
            return {'state':'NEEDS_REVIEW','parent_revision':parent['revision'],'reasons':[f'父版本文件身份未确认：{kind}/{path}']}
        key=(kind,files[0]['file_key'])
        if key in source_records:return {'state':'NEEDS_REVIEW','parent_revision':parent['revision'],'reasons':['父版本存在重复文件身份']}
        source_records[key]=(path,src,groups[(kind,path)])
    old_positions=[]
    for _,src,_ in source_records.values():
        if (src['vendor'],src['library'])!=(vendor,library):continue
        candidates=[x for x in items if x['record']['delivery_id']==src['delivery'] or Path(x['path']).stem==src['delivery']]
        if len(candidates)!=1:return {'state':'NEEDS_REVIEW','parent_revision':parent['revision'],'reasons':['无法确认父版本交付顺序']}
        old_positions.append(positions[candidates[0]['record']['delivery_id']])
    if old_positions and positions[delivery_id]<max(old_positions):
        return {'state':'NEEDS_REVIEW','parent_revision':parent['revision'],'reasons':['目标交付不晚于当前版本来源']}
    if old_positions and any(ordered[i]['record']['delivery_id'] not in excluded for i in range(max(old_positions)+1,positions[delivery_id])):
        return {'state':'NEEDS_REVIEW','parent_revision':parent['revision'],'reasons':['中间存在尚未处理的交付']}
    if include_file_keys is not None:
        if not isinstance(include_file_keys,(list,tuple,set)) or not include_file_keys or any(not isinstance(x,str) or not x for x in include_file_keys) or len(set(include_file_keys))!=len(include_file_keys):raise ValueError('文件位选择无效')
        include_file_keys=set(include_file_keys)
    incoming={};matched_keys=set()
    for file in item['files']:
        kind=_view(file['view'],file['relative_path']); key=(kind,file.get('file_key'))
        if include_file_keys is not None and key[1] not in include_file_keys:continue
        if file['identity_status']!='CONFIRMED' or file['classification']!='RESOLVED' or not key[1]:
            return {'state':'NEEDS_REVIEW','parent_revision':parent['revision'],'reasons':[f"交付文件身份未确认：{file['relative_path']}"]}
        if include_file_keys is not None and key[1] in matched_keys:raise ValueError('所选文件位在多个 View 中不唯一')
        matched_keys.add(key[1])
        if key in incoming:return {'state':'NEEDS_REVIEW','parent_revision':parent['revision'],'reasons':['交付文件身份冲突']}
        if key not in source_records and include_file_keys is None:
            return {'state':'NEEDS_REVIEW','parent_revision':parent['revision'],'reasons':[f"新增文件的有效集归属未确认：{file['relative_path']}"]}
        incoming[key]=file['relative_path']
    removals=record.get('explicit_removed_file_keys',[])
    selected_removals=[key for key in removals if include_file_keys is None or key in include_file_keys]
    if include_file_keys is not None:
        matched_keys.update(selected_removals)
        if matched_keys!=include_file_keys:raise ValueError('所选文件位不存在或身份未确认')
    for key in selected_removals:
        found=[x for x in source_records if x[1]==key]
        if not found and parent.get('sources',{}).get(record['supplier_version'])==Path(item['path']).stem:
            continue  # This explicit removal was already applied by this delivery.
        if len(found)!=1:return {'state':'NEEDS_REVIEW','parent_revision':parent['revision'],'reasons':[f'删除文件身份不唯一：{key}']}
        if found[0] in incoming:return {'state':'NEEDS_REVIEW','parent_revision':parent['revision'],'reasons':[f'删除和更新冲突：{key}']}
        del source_records[found[0]]
    if not incoming and not selected_removals:
        return {'state':'NO_CHANGE','parent_revision':parent['revision'],'reasons':['交付没有可应用的成员变化']}
    revision=f"rev_{int(parent['revision'][4:])+1:04d}";candidate=deepcopy(parent)
    candidate.update(parent=parent['revision'],revision=revision,created_at=now())
    version=record['supplier_version'];alias=Path(item['path']).stem
    if version in candidate['sources'] and candidate['sources'][version]!=alias:
        return {'state':'NEEDS_REVIEW','parent_revision':parent['revision'],'reasons':['同名版本对应不同交付']}
    candidate['sources'][version]=alias;candidate['views']={}
    for key,path in incoming.items():
        subgroup=_subgroup(key[0],path)
        group=source_records[key][2] if key in source_records else ((subgroup,) if subgroup else ())
        source_records[key]=(path,{'vendor':vendor,'library':library,'version':version,'delivery':alias},group)
    for (kind,_),(path,src,group) in source_records.items():
        src_key=src['version'] if (src['vendor'],src['library'])==(vendor,library) else next((k for k,v in candidate['sources'].items() if isinstance(v,dict) and v==src),None)
        if not src_key:raise ValueError('跨库来源无法解析')
        bucket=candidate['views'].setdefault(kind,{})
        for subgroup in group:bucket=bucket.setdefault(subgroup,{})
        if path in bucket:raise ValueError('有效文件路径冲突')
        bucket[path]=src_key
    if _flat_views(candidate)==old:return {'state':'NO_CHANGE','parent_revision':parent['revision'],'reasons':['目标成员及来源没有变化']}
    validate(candidate,'effective_simple_v2')
    import hashlib,json
    stable={k:v for k,v in candidate.items() if k!='created_at'}
    token=hashlib.sha256(json.dumps({'candidate':stable,'selection':sorted(include_file_keys) if include_file_keys is not None else None},sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
    return {'state':'READY','parent_revision':parent['revision'],'order_basis':basis,'candidate':candidate,'preview_token':token,'reasons':[]}


def apply_effective_update(work,vendor,library,set_id,delivery_id,*,expected_parent_revision,include_file_keys=None,expected_preview_token=None):
    from .effective_publisher import publish_v2
    preview=preview_effective_update(work,vendor,library,set_id,delivery_id,include_file_keys=include_file_keys)
    if preview['state']!='READY':return preview
    if preview['parent_revision']!=expected_parent_revision:raise ValueError('父版本已变化，请重新预览')
    if include_file_keys is not None and (not expected_preview_token or preview['preview_token']!=expected_preview_token):raise ValueError('预览内容或文件选择已变化，请重新预览并确认')
    folder=library_folder(work,vendor,library);candidate=preview['candidate']
    parent=_history(folder,set_id)[-1]
    if parent['revision']!=expected_parent_revision:raise ValueError('父版本已变化，请重新预览')
    target=folder/f"effective_{set_id}_{int(candidate['revision'][4:]):03d}.json"
    try:
        publish_v2(work,target,candidate,parent,auto_accept=True,delivery_guard=delivery_id)
    except FileExistsError:
        raise ValueError('并发发布已创建该版本，请重新预览') from None
    except (OSError,ValueError,KeyError,TypeError) as exc:
        if target.is_file() and not target.is_symlink():
            try:published=read_json(target,'effective_simple_v2')==candidate
            except (OSError,ValueError,KeyError,TypeError):published=False
            if published:return {'state':'PUBLISHED_INDEX_STALE','revision':candidate['revision'],'error':str(exc)}
        raise
    q=LibraryDataQuery(work,Path(work)/'.query-no-runs');status=q.file_index_status(vendor,library)
    return {'state':'PUBLISHED' if status['status']=='VALID' else 'PUBLISHED_INDEX_STALE','revision':candidate['revision'],'index_status':status}


def process_registered_delivery(work,vendor,library,delivery_id):
    """Try each already-established v2 set; never infer an IP or initialize a set."""
    from .data_query import list_effective_v2
    sets=sorted({x['set_id'] for x in list_effective_v2(work,vendor,library)})
    outcomes=[]
    for set_id in sets:
        try:
            preview=preview_effective_update(work,vendor,library,set_id,delivery_id)
            result=apply_effective_update(work,vendor,library,set_id,delivery_id,expected_parent_revision=preview['parent_revision']) if preview['state']=='READY' else preview
        except (OSError,ValueError,KeyError,TypeError) as exc:
            result={'state':'ERROR','reasons':[str(exc)]}
        outcomes.append({'set_id':set_id,**result})
    return outcomes


def excluded_deliveries(work,vendor,library,set_id):
    source=_config(work,vendor,library)
    policy=source.get('excluded_delivery_ids',{})
    if not isinstance(policy,dict):raise ValueError('交付排除配置必须是有效集到交付列表的映射')
    ids=policy.get(set_id,[])
    if not isinstance(ids,list) or any(not isinstance(x,str) or not x for x in ids) or len(set(ids))!=len(ids):
        raise ValueError('交付排除配置无效')
    return set(ids)


def set_delivery_exclusion(work,vendor,library,set_id,delivery_id,*,excluded,actor,reason):
    """Change the per-set policy under global config and library locks; keep audit intent."""
    import json
    import os
    import uuid
    from ai_lib_qor.versions.store import locked,write_atomic
    root=Path(work).resolve(strict=True);folder=library_folder(root,vendor,library)
    if type(excluded) is not bool or not isinstance(actor,str) or not actor.strip() or not isinstance(reason,str) or not reason.strip():
        raise ValueError('排除操作需要明确状态、操作人和原因')
    if not SAFE.fullmatch(set_id or '') or not SAFE.fullmatch(delivery_id or ''):raise ValueError('有效集或交付 ID 无效')
    config_path=root/'scan_sources.json'
    if config_path.is_symlink() or not config_path.is_file():raise ValueError('需要可写的明确来源配置')
    with locked(root):
        with locked(folder):
            if config_path.is_symlink():raise ValueError('来源配置不能是软链接')
            config=json.loads(config_path.read_text(encoding='utf-8'))
            sources=config.get('sources',[])
            matches=[x for x in sources if (x.get('vendor_id'),x.get('source_library_id'))==(vendor,library)]
            if len(matches)!=1:raise ValueError('该库需要唯一的显式来源配置')
            history=_history(folder,set_id)
            if not history:raise ValueError('有效集不存在')
            from .source_repository import SourceRepository
            records=SourceRepository(root).deliveries(vendor=vendor,library=library)
            deliveries=[x for x in records if x['record']['delivery_id']==delivery_id]
            if len(deliveries)!=1:raise ValueError('交付不存在或不唯一')
            item=matches[0];policy=item.setdefault('excluded_delivery_ids',{})
            if not isinstance(policy,dict):raise ValueError('交付排除配置无效')
            ids=policy.get(set_id,[])
            if not isinstance(ids,list) or any(not isinstance(x,str) or not x for x in ids) or len(set(ids))!=len(ids):raise ValueError('交付排除配置无效')
            current=delivery_id in ids
            sources_now=_flat_views(history[-1]);alias=Path(deliveries[0]['path']).stem
            in_use=any((src['vendor'],src['library'])==(vendor,library) and src['delivery'] in (delivery_id,alias) for src in sources_now.values())
            common={'current_revision':history[-1]['revision'],'current_revision_uses_delivery':in_use}
            if current==excluded:return {'state':'UNCHANGED',**common}
            updated=set(ids)
            if excluded:updated.add(delivery_id)
            else:updated.remove(delivery_id)
            policy[set_id]=sorted(updated)
            log=folder/'runs.jsonl'
            if log.is_symlink():raise ValueError('操作日志不能是符号链接')
            event={'kind':'DELIVERY_EXCLUSION_REQUEST','operation_id':uuid.uuid4().hex,'at':now(),'actor':actor,'reason':reason,
                   'set_id':set_id,'delivery_id':delivery_id,'before':current,'after':excluded}
            fd=os.open(log,os.O_WRONLY|os.O_CREAT|os.O_APPEND|getattr(os,'O_NOFOLLOW',0),0o600)
            with os.fdopen(fd,'a',encoding='utf-8') as stream:
                stream.write(json.dumps(event,ensure_ascii=False,separators=(',',':'))+'\n');stream.flush();os.fsync(stream.fileno())
            write_atomic(config_path,config)
            return {'state':'EXCLUDED' if excluded else 'INCLUDED',**common}


def rollback_acceptance(work,vendor,library,set_id,revision,*,actor,reason):
    """Rollback acceptance only; calculated versions and their files remain unchanged."""
    from ai_lib_qor.versions.acceptance import create_event
    from ai_lib_qor.versions.index_projector import project_simple
    from ai_lib_qor.versions.store import locked,events,append_event,write_atomic
    root=Path(work).resolve(strict=True);folder=library_folder(root,vendor,library)
    if not SAFE.fullmatch(set_id or ''):raise ValueError('有效集标识无效')
    with locked(folder):
        history=_history(folder,set_id)
        if not history:raise ValueError('有效集不存在')
        event_root=folder/f'effective_{set_id}';evts=events(event_root)
        index_path=folder/f'effective_{set_id}_index.json'
        if index_path.is_symlink() or not index_path.is_file():raise ValueError('有效集索引不可用')
        previous=read_json(index_path,'effective_index');projected=project_simple(history,evts,set_id,now())
        keys=('effective_set_id','owner','latest_calculated_revision','current_accepted_revision')
        if any(previous[k]!=projected[k] for k in keys):raise ValueError('有效集索引与历史不一致')
        event=create_event(set_id,revision,'ROLLBACK',actor,reason,now())
        index=project_simple(history,evts+[event],set_id,now());validate(index,'effective_index')
        append_event(event_root,event)
        try:write_atomic(index_path,index)
        except OSError as exc:return {'state':'EVENT_RECORDED_INDEX_STALE','event_id':event['event_id'],'error':str(exc)}
        from .latest_pointers import refresh_library_locked
        refresh_library_locked(root,vendor,library)
        return {'state':'ROLLED_BACK','event_id':event['event_id'],'index':index}


def restore_effective_revision(work,vendor,library,set_id,revision,*,expected_parent_revision,actor,reason):
    """Publish a new revision with the historical member combination; never rewrite history."""
    from .effective_publisher import publish_v2
    root=Path(work).resolve(strict=True);folder=library_folder(root,vendor,library)
    if not isinstance(actor,str) or not actor.strip() or not isinstance(reason,str) or not reason.strip():raise ValueError('恢复需要操作人和原因')
    history=_history(folder,set_id)
    if not history or history[-1]['revision']!=expected_parent_revision:raise ValueError('父版本已变化，请重新选择')
    targets=[x for x in history[:-1] if x['revision']==revision]
    if len(targets)!=1:raise ValueError('恢复目标必须是已有历史版本')
    target=targets[0];parent=history[-1]
    if _flat_views(target)==_flat_views(parent):return {'state':'NO_CHANGE','revision':parent['revision']}
    query=LibraryDataQuery(root,root/'.query-no-runs');guards=set()
    for (kind,path),src in _flat_views(target).items():
        matches=[x for x in query.deliveries if (x['record']['vendor_id'],x['record']['source_library_id'],x['record']['supplier_version'])==(src['vendor'],src['library'],src['version']) and src['delivery'] in (x['record']['delivery_id'],Path(x['path']).stem)]
        if len(matches)!=1:raise ValueError(f'恢复来源不唯一：{path}')
        record=matches[0]['record'];files=[f for f in matches[0]['files'] if f['relative_path']==path and _view(f['view'],path)==kind]
        if len(files)!=1:raise ValueError(f'恢复来源文件不存在或不唯一：{path}')
        source_root=Path(record['source_root']).resolve(strict=True);source=(source_root/path).resolve(strict=True)
        if not source.is_relative_to(source_root) or not source.is_file():raise ValueError(f'恢复来源文件不可访问：{path}')
        if (src['vendor'],src['library'])==(vendor,library):guards.add(record['delivery_id'])
    excluded=excluded_deliveries(root,vendor,library,set_id)
    if guards & excluded:raise ValueError('恢复目标引用已排除的交付')
    candidate=deepcopy(target);candidate.update(parent=parent['revision'],revision=f"rev_{int(parent['revision'][4:])+1:04d}",created_at=now())
    target_file=folder/f"effective_{set_id}_{int(candidate['revision'][4:]):03d}.json"
    try:
        publish_v2(root,target_file,candidate,parent,auto_accept=True,delivery_guard=guards,acceptance_actor=actor,acceptance_reason=f'恢复 {revision}: {reason}')
    except FileExistsError:
        raise ValueError('并发发布已创建该版本，请重新选择') from None
    except (OSError,ValueError,KeyError,TypeError) as exc:
        if target_file.is_file() and not target_file.is_symlink():
            try:published=read_json(target_file,'effective_simple_v2')==candidate
            except (OSError,ValueError,KeyError,TypeError):published=False
            if published:return {'state':'PUBLISHED_INDEX_STALE','revision':candidate['revision'],'error':str(exc)}
        raise
    status=LibraryDataQuery(root,root/'.query-no-runs').file_index_status(vendor,library)
    return {'state':'PUBLISHED' if status['status']=='VALID' else 'PUBLISHED_INDEX_STALE','revision':candidate['revision'],'restored_from':revision,'index_status':status}
