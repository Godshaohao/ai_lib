"""Read-only content observations; no delivery or acceptance is inferred."""
import hashlib
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path


def _time():
    return datetime.now(timezone.utc).isoformat()


def scan_library(root, vendor_id, source_library_id, *, metadata_only=False):
    started = _time()
    root = Path(root).resolve()
    if not root.is_dir():
        return {'schema_version':'scan_observation.v1','scan_id':'scan_'+uuid.uuid4().hex,
                'vendor_id':vendor_id,'source_library_id':source_library_id,'root':str(root),
                'started_at':started,'finished_at':_time(),'status':'FAILED','files':[],
                'errors':['扫描根目录不存在、不可访问或不是目录']}
    files, errors = [], []
    def onerror(exc):
        errors.append(str(exc))
    for current, dirs, names in os.walk(root, followlinks=False, onerror=onerror):
        dirs.sort(); names.sort()
        for name in list(dirs):
            path = Path(current) / name
            if path.is_symlink():
                errors.append(f'目录符号链接未扫描: {path.relative_to(root)}')
                dirs.remove(name)
        for name in names:
            path = Path(current) / name
            rel = path.relative_to(root).as_posix()
            try:
                if path.is_symlink() or not path.is_file():
                    raise ValueError('不是普通文件或是符号链接')
                before = path.stat()
                if metadata_only:
                    files.append({'path':rel,'size':before.st_size,'mtime_ns':before.st_mtime_ns})
                    continue
                digest = hashlib.sha256()
                with path.open('rb') as stream:
                    while chunk := stream.read(1024 * 1024): digest.update(chunk)
                after = path.stat()
                if (before.st_ino, before.st_size, before.st_mtime_ns) != (after.st_ino, after.st_size, after.st_mtime_ns):
                    raise ValueError('读取时文件发生变化')
                files.append({'path':rel, 'size':after.st_size, 'sha256':digest.hexdigest()})
            except (OSError, ValueError) as exc:
                errors.append(f'{rel}: {exc}')
    return {'schema_version':'scan_observation.v1', 'scan_id':'scan_'+uuid.uuid4().hex,
            'vendor_id':vendor_id, 'source_library_id':source_library_id, 'root':str(root),
            'started_at':started, 'finished_at':_time(), 'status':'PARTIAL' if errors else 'COMPLETE',
            'files':files, 'errors':errors, 'comparison_method':'size_mtime_ns' if metadata_only else 'sha256'}


def compare_scans(previous, current):
    if any(x.get('status') != 'COMPLETE' for x in (previous, current)):
        raise ValueError('不完整扫描不能用于判定新增或删除')
    if any(previous.get(k) != current.get(k) for k in ('vendor_id','source_library_id','root')):
        raise ValueError('扫描范围不一致')
    method = current.get('comparison_method','sha256')
    if previous.get('comparison_method','sha256') != method: raise ValueError('扫描方法不同，不能比较')
    def identity(f): return (f['size'], f['mtime_ns']) if method == 'size_mtime_ns' else f['sha256']
    old = {f['path']:identity(f) for f in previous['files']}
    new = {f['path']:identity(f) for f in current['files']}
    return {'added':sorted(new.keys()-old.keys()), 'changed':sorted(k for k in old.keys() & new.keys() if old[k] != new[k]), 'removed':sorted(old.keys()-new.keys())}
