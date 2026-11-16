"""Register explicitly mapped files from a verified scan as an immutable delivery."""
import re
import errno
from datetime import datetime, timezone
from pathlib import Path
from ai_lib_qor.sources.update_scan import scan_library
from ai_lib_qor.sources.delivery_builder import build_delivery
from ai_lib_qor.versions.store import write_atomic

SAFE = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z')


def register_delivery(work, source, scan, version_dir, metadata, mapping):
    vendor, library = source['vendor_id'], source['source_library_id']
    delivery_id = metadata['delivery_id']
    if not all(SAFE.fullmatch(x) and x not in ('.','..') for x in (vendor,library,delivery_id,version_dir)):
        raise ValueError('供应商、库、交付和目录名称只能使用安全标识')
    raw = Path(source['root']).resolve(strict=True)
    if Path(work).resolve().is_relative_to(raw): raise ValueError('工作目录不能位于 RAW 内')
    if scan.get('comparison_method') != 'size_mtime_ns': raise ValueError('请使用快速扫描重新扫描来源')
    if scan['status'] != 'COMPLETE' or (scan['vendor_id'],scan['source_library_id'],scan['root']) != (vendor,library,str(raw)):
        raise ValueError('扫描记录与来源不一致或未完成')
    candidate = raw / version_dir
    if candidate.is_symlink() or not candidate.is_dir(): raise ValueError('交付目录不可用')
    before = {f['path'][len(version_dir)+1:]:(f['size'],f['mtime_ns']) for f in scan['files'] if f['path'].startswith(version_dir+'/')}
    current = scan_library(candidate,vendor,library,metadata_only=True)
    after = {f['path']:(f['size'],f['mtime_ns']) for f in current['files']}
    if not before or current['status'] != 'COMPLETE' or before != after: raise ValueError('交付文件自扫描后发生变化或扫描不完整，请重新扫描')
    if set(mapping) != set(after) or any(not m.get('file_key') for m in mapping.values()):
        raise ValueError('必须逐项确认所有文件的文件位')
    info={'delivery_id':delivery_id,'vendor_id':vendor,'source_library_id':library,
          'supplier_version':metadata['supplier_version'],'delivery_order':int(metadata['delivery_order']),
          'received_at':datetime.now(timezone.utc).isoformat(),'package_mode':metadata['package_mode'],
          'scope_confirmed':True}
    record=build_delivery(candidate,info,mapping)
    current2=scan_library(candidate,vendor,library,metadata_only=True)
    if current2['status'] != 'COMPLETE' or {f['path']:(f['size'],f['mtime_ns']) for f in current2['files']} != after:
        raise ValueError('登记期间来源发生变化，请重新扫描')
    work_root=Path(work).resolve(strict=True)
    parent=work_root/'vendors'/vendor/'libraries'/library/'deliveries'
    for part in (work_root/'vendors',work_root/'vendors'/vendor,work_root/'vendors'/vendor/'libraries',work_root/'vendors'/vendor/'libraries'/library,parent):
        if part.is_symlink(): raise ValueError('工作目录包含符号链接')
    parent.mkdir(parents=True,exist_ok=True)
    if not parent.resolve().is_relative_to(work_root): raise ValueError('交付目录越过工作目录')
    target=parent/delivery_id
    target.mkdir()  # exclusive create, never replace an existing delivery
    try:
        write_atomic(target/'source_evidence.json',{'schema_version':'delivery_source_evidence.v1','scan_id':scan['scan_id'],'files':current2['files']},immutable=True)
        write_atomic(target/'delivery.json',record,immutable=True)
    except Exception:
        (target/'source_evidence.json').unlink(missing_ok=True)
        (target/'delivery.json').unlink(missing_ok=True)
        target.rmdir()
        raise
    return target/'delivery.json'


def registered_deliveries(work, source):
    from ai_lib_qor.versions.store import read_json
    if not work or not all(SAFE.fullmatch(source.get(k,'')) for k in ('vendor_id','source_library_id')): return []
    root=Path(work).resolve()
    parent=root/'vendors'/source['vendor_id']/'libraries'/source['source_library_id']/'deliveries'
    if not parent.resolve().is_relative_to(root): return []
    result=[]
    for path in sorted(parent.glob('*/delivery.json')):
        if path.is_symlink() or path.parent.is_symlink(): continue
        try:
            item=read_json(path,'delivery_record')
            if item['vendor_id']==source['vendor_id'] and item['source_library_id']==source['source_library_id']:result.append(item)
        except (OSError,ValueError,KeyError): continue
    return sorted(result,key=lambda x:x['delivery_order'],reverse=True)
