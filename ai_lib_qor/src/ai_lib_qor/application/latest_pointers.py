"""Rebuild two per-library pointers from saved records; never scan RAW or Formal."""
from pathlib import Path
import json
import re
from ai_lib_qor.application.source_repository import SourceRepository
from ai_lib_qor.sources.layout import SAFE, library_folder
from ai_lib_qor.sources.source_discovery import load_scan_sources
from ai_lib_qor.versions.store import locked, now, write_atomic, read_json, revisions, events, revision_path, validate
from ai_lib_qor.versions.index_projector import project, project_simple


def _config(work,vendor,library):
    matches=[x for x in load_scan_sources(work) if (x['vendor_id'],x['source_library_id'])==(vendor,library)]
    return matches[0] if matches else {}


def _latest_delivery(work,folder,vendor,library):
    warnings=[];records=SourceRepository(work,warnings=warnings).deliveries(vendor=vendor,library=library)
    result={'schema':'latest_delivery.v1','vendor':vendor,'library':library,'status':'NO_DELIVERY',
            'basis':None,'latest':None,'updated_at':now()}
    if warnings:
        result.update(status='UNAVAILABLE',reason='来源记录存在冲突或无法读取');return result
    if not records:return result
    ordered=None;basis=None
    if len(records)==1:
        ordered=records;basis='ONLY_REGISTERED_DELIVERY'
    elif all(x['order_basis'] in ('configured_order','manual_confirmation') for x in records):
        orders=[x['record']['delivery_order'] for x in records]
        if len(set(orders))==len(orders):ordered=sorted(records,key=lambda x:x['record']['delivery_order']);basis='CONFIRMED_DELIVERY_ORDER'
    if ordered is None and _config(work,vendor,library).get('order_rule')=={'type':'VERSION_DATE_PREFIX','confirmed':True}:
        from ai_lib_qor.application.simple_sources import version_date_order
        data=[{'delivery_id':x['record']['delivery_id'],'context':{'version':x['record']['supplier_version']}} for x in records]
        try:
            order=version_date_order(data);by_id={x['record']['delivery_id']:x for x in records}
            if len(by_id)==len(records):ordered=[by_id[x] for x in order];basis='CONFIRMED_VERSION_DATE_PREFIX'
        except (ValueError,KeyError):pass
    if ordered is None:
        result.update(status='ORDER_UNCONFIRMED',reason='多个交付的业务顺序未确认或存在歧义');return result
    item=ordered[-1];record=item['record'];path=Path(item['path'])
    if path.parent!=folder:
        result.update(status='UNAVAILABLE',reason='最新交付不在库集中目录，不能生成相对路径');return result
    result.update(status='READY',basis=basis,latest={'version':record['supplier_version'],
                  'delivery_id':record['delivery_id'],'file':path.name})
    return result


def _latest_effective(folder,vendor,library):
    result={'schema':'latest_effective.v1','vendor':vendor,'library':library,
            'status':'NO_EFFECTIVE_VERSION','sets':{},'updated_at':now()}
    set_ids={p.name[len('effective_'):-len('_index.json')] for p in folder.glob('effective_*_index.json')}
    for candidate in folder.glob('effective_*_[0-9]*.json'):
        match=re.fullmatch(r'effective_(.+)_(\d+)\.json',candidate.name)
        if match:set_ids.add(match.group(1))
    for set_id in sorted(set_ids):
        if not SAFE.fullmatch(set_id):continue
        path=folder/f'effective_{set_id}_index.json'
        entry={'status':'UNAVAILABLE','revision':None,'file':None}
        try:
            if path.is_symlink():raise ValueError('索引是符号链接')
            index=read_json(path,'effective_index') if path.exists() else None
            effective=folder/f'effective_{set_id}'
            if index and (index['effective_set_id']!=set_id or index['owner']['home_source_library_id']!=library):raise ValueError('索引归属不一致')
            files=[]
            for candidate in folder.glob(f'effective_{set_id}_[0-9]*.json'):
                match=re.fullmatch(re.escape(f'effective_{set_id}_')+r'(\d+)\.json',candidate.name)
                if match:files.append((int(match.group(1)),candidate))
            files.sort(key=lambda x:x[0]);evts=events(effective)
            if not files:raise ValueError('没有有效版本文件')
            if any(p.is_symlink() for _,p in files):raise ValueError('版本文件是符号链接')
            first=json.loads(files[0][1].read_text(encoding='utf-8'))
            if not isinstance(first,dict):raise ValueError('版本 JSON 不是对象')
            if first.get('schema')=='effective.simple.v2':
                history=[]
                for number,file in files:
                    item=read_json(file,'effective_simple_v2')
                    if item['revision']!=f'rev_{number:04d}' or item['scope']!={'vendor':vendor,'library':library}:
                        raise ValueError('v2 版本身份或归属不一致')
                    history.append(item)
                current=project_simple(history,evts,set_id,now())
            else:
                history=revisions(effective);current=project(history,evts,now())
            keys=('effective_set_id','owner','latest_calculated_revision','current_accepted_revision')
            if current['owner']['home_source_library_id']!=library:raise ValueError('有效版本归属不一致')
            if index and any(index[k]!=current[k] for k in keys):raise ValueError('索引与历史不一致')
            target=revision_path(effective,current['latest_calculated_revision'])
            if target.is_symlink() or not target.is_file():raise ValueError('版本记录缺失')
            entry={'status':'READY','revision':current['latest_calculated_revision'],'file':target.name,
                   'owner_type':current['owner']['owner_type'],'owner_id':current['owner']['owner_id']}
        except (OSError,ValueError,KeyError,TypeError) as exc:entry['reason']=str(exc)
        result['sets'][set_id]=entry
    if result['sets']:result['status']='READY' if all(x['status']=='READY' for x in result['sets'].values()) else 'PARTIAL'
    return result


def refresh_library_locked(work,vendor,library):
    """Caller holds the same library lock used by delivery and version writers."""
    work=Path(work).resolve(strict=True);folder=library_folder(work,vendor,library)
    folder.mkdir(parents=True,exist_ok=True)
    delivery=_latest_delivery(work,folder,vendor,library);effective=_latest_effective(folder,vendor,library)
    validate(delivery,'latest_delivery');validate(effective,'latest_effective')
    for name in ('latest_delivery.json','latest_effective.json'):
        if (folder/name).is_symlink():raise ValueError('最新指针文件不能是符号链接')
    for name,value in (('latest_delivery.json',delivery),('latest_effective.json',effective)):
        path=folder/name
        write_atomic(path,value)
    return {'vendor':vendor,'library':library,'delivery_status':delivery['status'],'effective_status':effective['status']}


def refresh_library(work,vendor,library):
    folder=library_folder(work,vendor,library)
    with locked(folder):return refresh_library_locked(work,vendor,library)


def refresh_all(work):
    root=Path(work).resolve(strict=True)
    scopes={(s['vendor_id'],s['source_library_id']) for s in load_scan_sources(root)}
    for folder in root.glob('libraries/*/*'):
        if folder.is_dir() and not folder.is_symlink():scopes.add((folder.parent.name,folder.name))
    return [refresh_library(root,v,l) for v,l in sorted(scopes)]
