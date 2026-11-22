"""Effective revisions over the path-based Delivery and Formal snapshots."""
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import csv
import os
import uuid

from ai_lib_qor.sources.layout import library_folder,archive_files,storage_dir,log_file
from ai_lib_qor.sources.root_inventory import update_pointer
from ai_lib_qor.sources.timestamps import utc_text
from ai_lib_qor.versions.store import locked,write_atomic,validate


def _deliveries(folder,vendor,library):
    result={}
    for path in archive_files(folder,'delivery','delivery_*.json'):
        if path.is_symlink():raise ValueError('交付文件不能是软链接')
        item=json.loads(path.read_text(encoding='utf-8'))
        validate(item,'delivery_minimal')
        if set(item)!={'vendor','library','version','version_date','directory_created_at','root','views'} or (item['vendor'],item['library'])!=(vendor,library):raise ValueError('交付格式或来源范围不正确')
        if item['version'] in result:raise ValueError('来源版本不唯一')
        result[item['version']]=item
    return result


def _history(folder,library):
    regex=re.compile(r'^effective_'+re.escape(library)+r'_(\d+)\.json$')
    rows=[]
    for path in archive_files(folder,'effective','effective_'+library+'_*.json'):
        match=regex.fullmatch(path.name)
        if not match:continue
        if path.is_symlink():raise ValueError('有效版本不能是软链接')
        row=json.loads(path.read_text(encoding='utf-8'))
        validate(row,'effective_path')
        if row.get('revision')!=f'rev_{int(match.group(1)):04d}':raise ValueError('有效版本与文件名不一致')
        rows.append((int(match.group(1)),path,row))
    rows.sort()
    if [r[0] for r in rows]!=list(range(1,len(rows)+1)):raise ValueError('有效版本序列不连续')
    return rows


def _make(vendor,library,number,views):
    return {'vendor':vendor,'library':library,'revision':f'rev_{number:04d}',
            'created_at':utc_text(),
            'views':{view:{ver:sorted(paths) for ver,paths in sorted(versions.items()) if paths}
                     for view,versions in sorted(views.items()) if any(versions.values())}}


def _audit(folder,operation,actor,action,parent,revision,status,changes,detail=''):
    if not isinstance(actor,str) or not actor.strip() or len(actor)>128:raise ValueError('操作来源无效')
    path=log_file(folder,'effective_operations.tsv')
    if path.is_symlink():raise ValueError('操作审计不能为软链接')
    new=not path.exists()
    with path.open('a',encoding='utf-8',newline='') as stream:
        writer=csv.writer(stream,delimiter='\t',lineterminator='\n')
        if new:writer.writerow(['operation','time','actor','action','parent','revision','status','changes','detail'])
        writer.writerow([operation,utc_text(),actor,action,parent or '',revision,status,json.dumps(changes,ensure_ascii=False,sort_keys=True),detail])
        stream.flush();os.fsync(stream.fileno())


def _audit_recover(folder,revision):
    path=log_file(folder,'effective_operations.tsv')
    if path.is_symlink():raise ValueError('操作审计不能为软链接')
    if not path.is_file():return
    with path.open(encoding='utf-8',newline='') as stream:
        rows=[x for x in csv.DictReader(stream,delimiter='\t') if x.get('revision')==revision]
    if rows and rows[-1].get('status') in ('INTENT','INTERRUPTED'):
        item=rows[-1]
        _audit(folder,item['operation'],item['actor'],item['action'],item['parent'],revision,'RECOVERED',json.loads(item['changes']),'已修复指针并刷新索引')


def _save(folder,library,number,row,work,*,actor='local',action='update'):
    validate(row,'effective_path')
    target=storage_dir(folder,'effective')/f'effective_{library}_{number:03d}.json'
    history=_history(folder,library);parent=history[-1][2] if history else None
    before=_flat(parent['views']) if parent else {};after=_flat(row['views'])
    changes=[{'view':v,'path':p,'before':before.get((v,p)),'after':after.get((v,p))}
             for v,p in sorted(before.keys()|after.keys()) if before.get((v,p))!=after.get((v,p))]
    operation=uuid.uuid4().hex;parent_rev=parent['revision'] if parent else None
    _audit(folder,operation,actor,action,parent_rev,row['revision'],'INTENT',changes)
    try:
        write_atomic(target,row,immutable=True)
        update_pointer(folder,'latest_effective.json',str(target.relative_to(folder)))
    except (OSError,ValueError,KeyError,TypeError) as exc:
        _audit(folder,operation,actor,action,parent_rev,row['revision'],'INTERRUPTED',changes,str(exc))
        raise
    result={'state':'PUBLISHED','revision':row['revision'],'path':str(target)}
    try:
        from .minimal_file_index import refresh_index_locked
        result['index']=refresh_index_locked(work,row['vendor'],library)
    except (OSError,ValueError,KeyError,TypeError) as exc:
        result.update(state='PUBLISHED_INDEX_STALE',index_error=str(exc))
    _audit(folder,operation,actor,action,parent_rev,row['revision'],result['state'],changes,result.get('index_error',''))
    return result


def initialize_from_formal(work,vendor,library,formal_path,*,include=None,actor='local'):
    folder=library_folder(work,vendor,library)
    with locked(folder):
        path=Path(formal_path)
        if (folder/'formal').is_symlink() or path.is_symlink() or not path.is_file() or path.parent.resolve() not in (folder.resolve(),(folder/'formal').resolve()):raise ValueError('正式快照必须为当前库的普通文件')
        formal=json.loads(path.read_text(encoding='utf-8'))
        validate(formal,'formal_path')
        if set(formal)!={'version','vendor','library','root','observed_at','views'} or (formal['vendor'],formal['library'])!=(vendor,library):raise ValueError('正式快照格式或归属不匹配')
        deliveries=_deliveries(folder,vendor,library);views={};matched=set()
        selected=set(include) if include is not None else None
        if selected is not None and (not selected or len(selected)!=len(include)):raise ValueError('初始成员选择为空或重复')
        for view,versions in formal['views'].items():
            for version,links in versions.items():
                if version not in deliveries:raise ValueError('正式来源版本不存在')
                delivery=deliveries[version];root=Path(delivery['root'])
                for link in links:
                    resolved=Path(link['resolved'])
                    if not root.is_absolute() or not resolved.is_absolute() or not resolved.is_relative_to(root):raise ValueError('正式目标不在来源版本内')
                    raw=resolved.relative_to(root).as_posix()
                    if raw not in delivery['views'].get(view,[]):raise ValueError('正式目标不在对应的交付 View 中')
                    if selected is not None and (view,raw) not in selected:continue
                    if (view,raw) in matched:raise ValueError('正式来源中同一文件位有多个版本，请先处理来源冲突')
                    matched.add((view,raw))
                    bucket=views.setdefault(view,{}).setdefault(version,[])
                    if raw in bucket:raise ValueError('多个正式链接指向同一个 RAW 成员')
                    bucket.append(raw)
        if not views or (selected is not None and selected!=matched):raise ValueError('初始成员不在正式来源中或不唯一')
        row=_make(vendor,library,1,views);history=_history(folder,library)
        if history:
            if history[0][2]['views']==row['views']:
                return {'state':'UNCHANGED','revision':history[-1][2]['revision']}
            raise ValueError('有效版本已初始化，不覆盖历史')
        return _save(folder,library,1,row,work,actor=actor,action='INITIALIZE')


def _candidate(folder,vendor,library,operations,expected_parent=None,work=None):
    if not isinstance(operations,dict) or set(operations)!={'set','remove'} or not isinstance(operations['set'],list) or not isinstance(operations['remove'],list):raise ValueError('操作必须包含 set 与 remove 数组')
    history=_history(folder,library)
    if not history:raise ValueError('需要先初始化有效版本')
    last=history[-1][2]
    if expected_parent is not None and last['revision']!=expected_parent:raise ValueError('父版本已变化，请重新预览')
    deliveries=_deliveries(folder,vendor,library);views=deepcopy(last['views']);touched=set()
    from .path_config import excluded_versions
    excluded=excluded_versions(work,vendor,library) if work is not None else set()
    for item in operations['set']:
        if not isinstance(item,dict) or set(item)!={'view','version','path'}:raise ValueError('set 需要 view、version、path')
        view,version,path=item['view'],item['version'],item['path'];key=(view,path)
        if key in touched:raise ValueError('操作包含重复成员')
        touched.add(key)
        if version in excluded:raise ValueError('来源版本已被排除')
        if version not in deliveries or path not in deliveries[version]['views'].get(view,[]):raise ValueError('所选路径不在对应交付中')
        bucket=views.setdefault(view,{})
        for paths in bucket.values():
            if path in paths:paths.remove(path)
        bucket.setdefault(version,[]).append(path)
    for item in operations['remove']:
        if not isinstance(item,dict) or set(item)!={'view','path'}:raise ValueError('remove 需要 view、path')
        key=(item['view'],item['path'])
        if key in touched:raise ValueError('操作包含重复成员')
        touched.add(key)
        for paths in views.get(item['view'],{}).values():
            if item['path'] in paths:paths.remove(item['path'])
    row=_make(vendor,library,history[-1][0]+1,views)
    return history,last,row


def _flat(views):
    return {(view,path):version for view,versions in views.items() for version,paths in versions.items() for path in paths}


def preview_update(work,vendor,library,operations):
    folder=library_folder(work,vendor,library)
    with locked(folder):
        _,last,row=_candidate(folder,vendor,library,operations,work=work)
        before=_flat(last['views']);after=_flat(row['views'])
        changes=[{'view':key[0],'path':key[1],'before':before.get(key),'after':after.get(key)}
                 for key in sorted(before.keys()|after.keys()) if before.get(key)!=after.get(key)]
        return {'parent':last['revision'],'changes':changes,'views':row['views']}


def apply_update(work,vendor,library,operations,*,expected_parent,actor='local'):
    folder=library_folder(work,vendor,library)
    with locked(folder):
        try:history,last,row=_candidate(folder,vendor,library,operations,expected_parent,work)
        except (ValueError,KeyError,TypeError) as exc:
            _audit(folder,uuid.uuid4().hex,actor,'UPDATE',expected_parent,'','REJECTED',[],str(exc));raise
        if row['views']==last['views']:
            _audit(folder,uuid.uuid4().hex,actor,'UPDATE',last['revision'],last['revision'],'UNCHANGED',[])
            return {'state':'UNCHANGED','revision':last['revision']}
        return _save(folder,library,history[-1][0]+1,row,work,actor=actor,action='UPDATE')


def update_effective(work,vendor,library,operations,*,actor='local'):
    folder=library_folder(work,vendor,library)
    with locked(folder):
        try:history,last,row=_candidate(folder,vendor,library,operations,work=work)
        except (ValueError,KeyError,TypeError) as exc:
            _audit(folder,uuid.uuid4().hex,actor,'UPDATE',None,'','REJECTED',[],str(exc));raise
        if row['views']==last['views']:
            _audit(folder,uuid.uuid4().hex,actor,'UPDATE',last['revision'],last['revision'],'UNCHANGED',[])
            return {'state':'UNCHANGED','revision':last['revision']}
        return _save(folder,library,history[-1][0]+1,row,work,actor=actor,action='UPDATE')


def preview_delivery(work,vendor,library,version):
    """Replace existing members present in this delivery; never infer new scope."""
    folder=library_folder(work,vendor,library)
    with locked(folder):
        history=_history(folder,library);deliveries=_deliveries(folder,vendor,library)
        if not history:raise ValueError('需要先初始化有效版本')
        if version not in deliveries:raise ValueError('来源版本不存在')
        from .path_config import excluded_versions
        if version in excluded_versions(work,vendor,library):raise ValueError('来源版本已被排除')
        old=_flat(history[-1][2]['views']);delivery=deliveries[version]
        operations={'set':[{'view':v,'version':version,'path':p} for v,p in sorted(old)
                           if p in delivery['views'].get(v,[]) and old[(v,p)]!=version], 'remove':[]}
        _,last,row=_candidate(folder,vendor,library,operations,work=work)
        after=_flat(row['views'])
        changes=[{'view':v,'path':p,'before':old.get((v,p)),'after':after.get((v,p))}
                 for v,p in sorted(old.keys()|after.keys()) if old.get((v,p))!=after.get((v,p))]
        return {'parent':last['revision'],'changes':changes,'views':row['views'],'operations':operations}


def restore_issues(work,vendor,library,views):
    from .path_config import excluded_versions
    folder=library_folder(work,vendor,library);deliveries=_deliveries(folder,vendor,library)
    excluded=excluded_versions(work,vendor,library);issues=[]
    for (view,path),version in sorted(_flat(views).items()):
        if version in excluded:issues.append(f'已排除来源：{version} · {path}')
        delivery=deliveries.get(version)
        if not delivery or path not in delivery['views'].get(view,[]):
            issues.append(f'来源交付不可用：{version} · {path}');continue
        absolute=Path(delivery['root'])/path
        if not absolute.is_file():issues.append(f'来源文件不可用：{absolute}')
    return sorted(issues)


def restore_revision(work,vendor,library,revision,*,expected_parent,actor='local',expected_issues=None):
    folder=library_folder(work,vendor,library)
    with locked(folder):
        history=_history(folder,library)
        if not history or history[-1][2]['revision']!=expected_parent:
            _audit(folder,uuid.uuid4().hex,actor,'RESTORE:'+str(revision),expected_parent,'','REJECTED',[],'父版本已变化')
            raise ValueError('父版本已变化，请重新选择')
        matches=[item[2] for item in history if item[2]['revision']==revision]
        if len(matches)!=1:
            _audit(folder,uuid.uuid4().hex,actor,'RESTORE:'+str(revision),expected_parent,'','REJECTED',[],'有效版本不存在')
            raise ValueError('有效版本不存在')
        if expected_issues is not None and restore_issues(work,vendor,library,matches[0]['views'])!=expected_issues:
            _audit(folder,uuid.uuid4().hex,actor,'RESTORE:'+str(revision),expected_parent,'','REJECTED',[],'来源状态已变化')
            raise ValueError('来源状态已变化，请重新预览')
        row=_make(vendor,library,history[-1][0]+1,matches[0]['views'])
        if row['views']==history[-1][2]['views']:
            _audit(folder,uuid.uuid4().hex,actor,'RESTORE:'+str(revision),expected_parent,expected_parent,'UNCHANGED',[])
            return {'state':'UNCHANGED','revision':expected_parent}
        return _save(folder,library,history[-1][0]+1,row,work,actor=actor,action='RESTORE:'+revision)
