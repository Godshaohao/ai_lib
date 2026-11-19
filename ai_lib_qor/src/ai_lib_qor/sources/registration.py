"""Register explicitly mapped files from a verified scan as an immutable delivery."""
import re
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
    from .layout import library_folder, next_filename, evidence_path
    from ai_lib_qor.application.source_repository import SourceRepository
    from ai_lib_qor.versions.store import locked
    parent=library_folder(work_root,vendor,library)
    with locked(parent):
        existing=SourceRepository(work_root).deliveries()
        if any(x['record']['delivery_id']==delivery_id and x['record']['vendor_id']==vendor and x['record']['source_library_id']==library for x in existing):
            raise ValueError('交付 ID 已存在')
        target=parent/next_filename(parent,'delivery',with_evidence=True);ep=evidence_path(target)
        evidence_created=False
        try:
            write_atomic(ep,{'schema_version':'delivery_source_evidence.v1','scan_id':scan['scan_id'],'files':current2['files'],
                             'order_basis':'manual_confirmation',
                             'classification':{path:{'basis':'explicit'} for path in mapping}},immutable=True)
            evidence_created=True
            write_atomic(target,record,immutable=True)
        except Exception:
            if evidence_created and not target.exists(): ep.unlink(missing_ok=True)
            raise
        from ai_lib_qor.application.latest_pointers import refresh_library_locked
        refresh_library_locked(work_root,vendor,library)
    return target


def registered_deliveries(work, source):
    from ai_lib_qor.application.source_repository import SourceRepository
    if not work or not all(SAFE.fullmatch(source.get(k,'')) for k in ('vendor_id','source_library_id')): return []
    root=Path(work).resolve()
    result=[x['record'] for x in SourceRepository(root).deliveries() if
            (x['record']['vendor_id'],x['record']['source_library_id'])==(source['vendor_id'],source['source_library_id'])]
    return sorted(result,key=lambda x:x['delivery_order'],reverse=True)
