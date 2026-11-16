"""Inventory explicitly registered formal file links and match fixed RAW records."""
from hashlib import sha256
from pathlib import Path
import os
from ai_lib_qor.versions.store import validate


def build_snapshot(formal_root,metadata,link_mapping,deliveries):
    root=Path(formal_root).resolve(strict=True)
    if not root.is_dir():raise ValueError('正式来源不是目录')
    seen=set();files=[]
    def onerror(e):raise e
    for current,dirs,names in os.walk(root,followlinks=False,onerror=onerror):
        for name in dirs:
            if (Path(current)/name).is_symlink():raise ValueError('不支持目录符号链接，请明确展开扫描范围')
        for name in names:seen.add((Path(current)/name).relative_to(root).as_posix())
    if metadata.get('scope_confirmed') and seen!=set(link_mapping):raise ValueError('确认完整范围与实际盘点文件不一致')
    if set(link_mapping)-seen:raise ValueError('正式范围中有不存在的路径')
    for delivery in deliveries:validate(delivery,'delivery_record')
    ids=set()
    for rel,key in sorted(link_mapping.items()):
        path=root/rel
        if Path(rel).is_absolute() or '..' in Path(rel).parts or not path.is_symlink():raise ValueError(f'只接受范围内明确的文件链接: {rel}')
        resolved=path.resolve(strict=True)
        if not resolved.is_file():raise ValueError(f'正式链接目标不可读取: {rel}')
        candidates=[]
        for delivery in deliveries:
            base=Path(delivery['source_root']).resolve()
            for f in delivery['files']:
                source=(base/f['relative_path']).resolve()
                if source.is_relative_to(base) and source==resolved and f['file_key']==key and f['classification']=='RESOLVED':
                    candidates.append({'kind':'delivery_file','source_library_id':delivery['source_library_id'],'delivery_id':delivery['delivery_id'],'file_id':f['file_id']})
        if key is not None and key in ids:raise ValueError('正式快照 file_key 重复')
        ids.add(key);matched=candidates[0] if len(candidates)==1 else None
        files.append({'file_id':'nf_'+sha256(rel.encode()).hexdigest()[:24],'file_key':key,'link_path':rel,'resolved_path':str(resolved),'source_match':'MATCHED_RAW' if matched else 'UNMATCHED','source_ref':matched})
    result={'schema_version':'formal_snapshot.v1','formal_nl_id':metadata['formal_nl_id'],'formal_snapshot_id':metadata['formal_snapshot_id'],'previous_snapshot_id':metadata['previous_snapshot_id'],'observed_at':metadata['observed_at'],'source_root':str(root),'coverage':'COMPLETE_IN_SCOPE' if metadata.get('scope_confirmed') else 'PARTIAL','scope':{'source_library_ids':metadata['source_library_ids'],'views':metadata['views'],'note':metadata['note']},'linked_files':files}
    validate(result,'formal_snapshot');return result
