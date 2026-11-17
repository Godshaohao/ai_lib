"""Classify scan metadata with lib_guard without reading source files.

Classification hints are not authoritative file identities; no file_key or IP
is inferred without an explicit business mapping.
"""
from pathlib import PurePosixPath
from collections import Counter
from lib_guard.scan.inventory import FileClassifier

_VIEWS = {'lef':'LEF', 'liberty':'LIBERTY', 'verilog':'VERILOG', 'cdl':'CDL',
          'sdc':'SDC', 'upf':'UPF', 'cpf':'CPF', 'spef':'SPEF', 'db':'DB', 'gds':'GDS'}


def classify_observation(scan, config):
    if scan.get('status') != 'COMPLETE' or scan.get('comparison_method') != 'size_mtime_ns':
        raise ValueError('分类需要完整的元数据扫描')
    versions = config.get('version_paths', {})
    prefixes = []
    for version, raw in versions.items():
        p = PurePosixPath(raw)
        if p.is_absolute() or not p.parts or any(part in ('.', '..') for part in p.parts):
            raise ValueError('版本路径必须为安全的相对路径')
        prefixes.append((version, p.as_posix()))
    classifier = FileClassifier()
    mappings = config.get('file_mapping', {})
    files = []
    for entry in scan['files']:
        path = entry['path']
        matches = [version for version, prefix in prefixes if path.startswith(prefix + '/')]
        hints = classifier.classify({'path':path, 'name':PurePosixPath(path).name})
        reason = '版本范围重叠；文件位未确认' if len(matches) > 1 else '文件位与业务归属未确认'
        mapped = mappings.get(path, {})
        key = mapped.get('file_key') if len(matches) == 1 else None
        if not isinstance(key, str) or not key.strip(): key = None
        files.append({**entry, 'supplier_version':matches[0] if len(matches)==1 else None,
                      'view':_VIEWS.get(hints['file_type'], 'OTHER'),
                      'file_type':hints['file_type'], 'role':hints['role'],
                      'corner_hint':hints['corner'], 'file_key':key,
                      'classification':'RESOLVED' if key else 'UNRESOLVED', 'reason':None if key else reason})
    counts = Counter((row['supplier_version'], row['file_key']) for row in files if row['file_key'])
    for row in files:
        if row['file_key'] and counts[(row['supplier_version'], row['file_key'])] > 1:
            row.update(file_key=None, classification='UNRESOLVED', reason='交付内文件位冲突')
    return {'scan_id':scan.get('scan_id'), 'files':files}
