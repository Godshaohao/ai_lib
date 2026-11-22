"""Build a v3 delivery from a read-only scan and explicitly confirmed file mapping."""
from hashlib import sha256
from pathlib import Path
import os
from ai_lib_qor.versions.store import validate

_VIEWS={'.lef':'LEF','.lib':'LIBERTY','.v':'VERILOG','.vhd':'OTHER','.cdl':'CDL','.sdc':'SDC','.upf':'UPF','.cpf':'CPF','.spef':'SPEF','.db':'DB','.gds':'GDS'}


def build_delivery(raw_root, metadata, file_mapping):
    root=Path(raw_root).expanduser().resolve(strict=True)
    if not root.is_dir(): raise ValueError('RAW 来源不是目录')
    records=[]; found=set()
    def onerror(error): raise error
    for current,dirs,names in os.walk(root,followlinks=False,onerror=onerror):
        dirs.sort();names.sort()
        for name in dirs:
            if (Path(current)/name).is_symlink(): raise ValueError('扫描范围存在目录符号链接，需明确处理后重试')
        for name in names:
            path=Path(current)/name
            if path.is_symlink() or not path.is_file(): raise ValueError(f'扫描范围含不可确认的文件: {path}')
            rel=path.relative_to(root).as_posix(); found.add(rel); entry=file_mapping.get(rel)
            view=_VIEWS.get(Path(name[:-3] if name.lower().endswith('.gz') else name).suffix.lower(),'OTHER')
            if entry:
                key=entry.get('file_key'); classification='RESOLVED' if key else 'UNRESOLVED'
                view=entry.get('view',view); corner=entry.get('corner'); mode=entry.get('mode')
            else:key=None;classification='UNRESOLVED';corner=None;mode=None
            records.append({'file_id':'f_'+sha256(rel.encode()).hexdigest()[:24], 'file_key':key,'classification':classification,'relative_path':rel,'view':view,'corner':corner,'mode':mode})
    missing=set(file_mapping)-found
    if missing: raise ValueError(f'确认映射中存在未扫描到的文件: {sorted(missing)}')
    keys=[x['file_key'] for x in records if x['file_key'] is not None]
    if len(keys)!=len(set(keys)):raise ValueError('交付内 file_key 重复')
    scope=metadata.get('scope_file_keys',keys)
    data={'schema_version':'delivery_record.v1',**{k:metadata[k] for k in ('delivery_id','vendor_id','source_library_id','supplier_version','delivery_order','received_at','package_mode')},'source_root':str(root),'package_scope':{'file_keys':scope,'scope_confirmed':metadata.get('scope_confirmed',False)},'explicit_removed_file_keys':metadata.get('explicit_removed_file_keys',[]),'files':records}
    validate(data,'delivery_record');return data
