"""Convert one legacy library to a separate path-contract workspace."""
import json
import os
import tempfile
from pathlib import Path
from ai_lib_qor.sources.layout import library_folder, next_filename
from ai_lib_qor.sources.root_inventory import update_pointer
from ai_lib_qor.sources.timestamps import utc_text, instant
from ai_lib_qor.versions.store import locked, validate, write_atomic
from .minimal_file_index import refresh_index
from .path_config import registration_times


def migrate_legacy_library(source, destination, vendor, library):
    source=Path(source).resolve(strict=True);destination=Path(destination).resolve()
    if source==destination or source.is_relative_to(destination) or destination.is_relative_to(source):
        raise ValueError('迁移源与目标必须为独立工作目录')
    source_folder=library_folder(source,vendor,library)
    destination.mkdir(parents=True,exist_ok=True)
    target=library_folder(destination,vendor,library)
    with locked(destination):
        if target.exists():raise ValueError('目标库已存在，不能覆盖')
        with tempfile.TemporaryDirectory(prefix='.path-migration-',dir=destination) as temp:
            stage=Path(temp);folder=stage/'libraries'/vendor/library;folder.mkdir(parents=True)
            refs={};known={};deliveries=[]
            for path in sorted(source_folder.glob('delivery_*.json')):
                if path.is_symlink():raise ValueError('旧交付不能为软链接')
                delivery=json.loads(path.read_text(encoding='utf-8'))
                validate(delivery,'delivery_minimal')
                if (delivery['vendor'],delivery['library'])!=(vendor,library):raise ValueError('交付范围不匹配')
                evidence_path=path.with_name('evidence_'+path.stem+'.json')
                if evidence_path.is_symlink() or not evidence_path.is_file():raise ValueError('旧交付缺少身份映射')
                evidence=json.loads(evidence_path.read_text(encoding='utf-8'))['legacy_compatibility']
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
            snapshots=0;latest_formal={}
            for path in sorted(source_folder.glob('formal_*.json')):
                if path.is_symlink():raise ValueError('旧正式快照不能为软链接')
                old=json.loads(path.read_text(encoding='utf-8'))
                if set(old)=={'version','vendor','library','root','observed_at','views'}:
                    formal=old
                else:
                    views={}
                    for link in old['linked_files']:
                        matches=known.get(link['resolved_path'],[])
                        if len(matches)!=1:raise ValueError('正式链接未能唯一映射旧交付：'+link['link_path'])
                        view,version,_=matches[0]
                        target_text=link.get('link_target')
                        if not target_text:raise ValueError('旧正式链接缺少原始目标：'+link['link_path'])
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
            for nl,(_,name) in latest_formal.items():update_pointer(folder,'latest_formal_'+nl+'.json',name)
            revisions=0
            for path in sorted(source_folder.glob('effective_'+library+'_*.json')):
                suffix=path.stem.rsplit('_',1)[-1]
                if not suffix.isdigit():continue
                if path.is_symlink():raise ValueError('旧有效版本不能为软链接')
                old=json.loads(path.read_text(encoding='utf-8'))
                if 'views' in old and 'revision' in old:
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
            times=registration_times(source,vendor,library)
            if times:write_atomic(stage/'path_sources.json',{'libraries':{vendor:{library:{'version_registration_times':times}}}})
            result=refresh_index(stage,vendor,library)
            index=json.loads((folder/'file_index.json').read_text(encoding='utf-8'))
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
                    'revisions':revisions,'path':str(target),'index':result['state']}
