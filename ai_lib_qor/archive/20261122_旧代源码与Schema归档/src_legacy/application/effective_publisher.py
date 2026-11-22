"""Publish an explicitly scoped v2 revision and refresh per-library pointers."""
import json
import re
from pathlib import Path
from .effective_json import _flat_views
from .data_query import _view
from .source_repository import SourceRepository
from .latest_pointers import refresh_library_locked
from ai_lib_qor.sources.layout import SAFE, library_folder
from ai_lib_qor.versions.store import locked, write_atomic, read_json, events, now, validate
from ai_lib_qor.versions.index_projector import project_simple


def publish_v2(work,out,record,parent=None,*,auto_accept=False,delivery_guard=None,acceptance_actor='automatic',acceptance_reason='自动发布时生效'):
    root=Path(work).resolve(strict=True);scope=record['scope'];folder=library_folder(root,scope['vendor'],scope['library'])
    path=Path(out)
    if path.parent.resolve()!=folder.resolve() or path.is_symlink():raise ValueError('v2 输出必须位于对应库目录且不能是符号链接')
    match=re.fullmatch(r'effective_(.+)_(\d+)\.json',path.name)
    if not match or not SAFE.fullmatch(match.group(1)) or record['revision']!=f'rev_{int(match.group(2)):04d}':
        raise ValueError('v2 输出文件名与版本不一致')
    set_id=match.group(1)
    with locked(folder):
        if delivery_guard is not None:
            from .effective_workflow import excluded_deliveries
            guards={delivery_guard} if isinstance(delivery_guard,str) else set(delivery_guard)
            if guards & excluded_deliveries(root,scope['vendor'],scope['library'],set_id):
                raise ValueError('该交付已被排除，不能发布')
        if parent is not None:
            number=int(parent['revision'][4:]);previous=folder/f'effective_{set_id}_{number:03d}.json'
            if previous.is_symlink() or not previous.is_file() or read_json(previous,'effective_simple_v2')!=parent:
                raise ValueError('父版本必须与同一有效集的已保存 v2 一致')
        elif list(folder.glob(f'effective_{set_id}_[0-9]*.json')):
            raise ValueError('有效集已有版本，不能重新初始化')
        repository=SourceRepository(root)
        cached={}
        for (kind,rel),source in _flat_views(record).items():
            key=(source['vendor'],source['library'])
            if key not in cached:cached[key]=repository.deliveries(vendor=key[0],library=key[1])
            matches=[item for item in cached[key] if item['record']['supplier_version']==source['version'] and
                     (item['record']['delivery_id']==source['delivery'] or Path(item['path']).stem==source['delivery'])]
            if len(matches)!=1:raise ValueError('v2 来源交付未登记或不唯一')
            files=[f for f in matches[0]['files'] if f['relative_path']==rel and _view(f['view'],rel)==kind]
            if len(files)!=1:raise ValueError('v2 来源文件未登记或不唯一')
        if path.exists():raise FileExistsError(f'版本文件已存在: {path}')
        index_path=folder/f'effective_{set_id}_index.json'
        history=[]
        for candidate in folder.glob(f'effective_{set_id}_[0-9]*.json'):
            m=re.fullmatch(re.escape(f'effective_{set_id}_')+r'(\d+)\.json',candidate.name)
            if m:
                if candidate.is_symlink():raise ValueError('版本文件不能是符号链接')
                item=read_json(candidate,'effective_simple_v2')
                if item['revision']!=f'rev_{int(m.group(1)):04d}':raise ValueError('版本文件名不一致')
                history.append(item)
        history.sort(key=lambda x:int(x['revision'][4:]))
        event_log=events(folder/f'effective_{set_id}')
        if index_path.is_symlink():raise ValueError('有效索引不能是符号链接')
        if index_path.exists():
            if not history:raise ValueError('已有索引但没有对应历史，不能覆盖')
            previous_index=read_json(index_path,'effective_index')
            previous_projection=project_simple(history,event_log,set_id,now())
            keys=('effective_set_id','owner','latest_calculated_revision','current_accepted_revision')
            if any(previous_index[k]!=previous_projection[k] for k in keys):raise ValueError('现有索引与版本历史不一致')
        history.append(record)
        automatic_event=None
        if auto_accept:
            from ai_lib_qor.versions.acceptance import create_event
            automatic_event=create_event(set_id,record['revision'],'ACCEPT',acceptance_actor,acceptance_reason,now())
        index=project_simple(history,event_log+([automatic_event] if automatic_event else []),set_id,now())
        validate(index,'effective_index')
        write_atomic(path,record,immutable=True)
        if automatic_event:
            from ai_lib_qor.versions.store import append_event
            append_event(folder/f'effective_{set_id}',automatic_event)
        write_atomic(index_path,index)
        refresh_library_locked(root,scope['vendor'],scope['library'])
        try:
            from .file_index import refresh_library_index_locked
            from .latest_pointers import _config
            refresh_library_index_locked(root,scope['vendor'],scope['library'],_config(root,scope['vendor'],scope['library']))
        except (OSError,ValueError,KeyError,TypeError) as exc:
            import warnings
            warnings.warn(f'有效版本已发布，文件索引未刷新：{exc}',RuntimeWarning,stacklevel=2)
    return path
