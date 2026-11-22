"""L1 classification: reuse lib_guard metadata classifier, no RAW content reads.

File-slot inference is conservative: only a unique LEF/Liberty basename in one
version is assigned an automatic slot; directory or version prefixes are not
part of the key. Explicit mapping takes priority. Renames require a mapping.
"""
from __future__ import annotations

import re
from collections import Counter
from pathlib import PurePosixPath

from lib_guard.scan.inventory import FileClassifier
from .source_discovery import discover_version_paths

_VIEWS = {'lef': 'LEF', 'liberty': 'LIBERTY', 'verilog': 'VERILOG',
          'cdl': 'CDL', 'sdc': 'SDC', 'upf': 'UPF', 'cpf': 'CPF',
          'spef': 'SPEF', 'db': 'DB', 'gds': 'GDS'}
_SLOT_SUFFIXES = ('.lef.gz', '.tlef.gz', '.lib.gz', '.lef', '.tlef', '.lib')
_MODE_RE = re.compile(r'(?<![a-z0-9])(scan_capture|scan_shift|scancapture|scanshift|functional|func|scan)(?![a-z0-9])', re.I)


def _slot_from_name(path, view, library):
    if view not in ('LEF', 'LIBERTY'):
        return None
    name = PurePosixPath(path).name.lower()
    stem = next((name[:-len(suffix)] for suffix in _SLOT_SUFFIXES if name.endswith(suffix)), None)
    if not stem:
        return None
    stem = re.sub('[^a-z0-9]+', '_', stem).strip('_')
    # Retain meaningful path context such as IP_A/ and IP_B/, but omit common
    # view folders so lib/foo.lib and liberty/foo.lib keep the same slot.
    ignore = {'lef', 'tlef', 'lib', 'libs', 'liberty', 'timing', 'physical', 'views', 'models'}
    context = [re.sub('[^a-z0-9]+', '_', x.lower()).strip('_')
               for x in PurePosixPath(path).parts[:-1] if x.lower() not in ignore]
    context = [x for x in context if x]
    identity = '_'.join(context + [stem])
    return f'{library}:{view.lower()}:{identity}' if stem else None


def _mode_hint(path):
    tokens = [t.lower().replace('_', '') for t in _MODE_RE.findall(path)]
    tokens = set(tokens)
    if 'scancapture' in tokens:
        return 'scancapture'
    if 'scanshift' in tokens:
        return 'scanshift'
    if 'functional' in tokens or 'func' in tokens:
        return 'func'
    if 'scan' in tokens:
        return 'scan'
    return None


def classify_observation(scan, config):
    if scan.get('status') != 'COMPLETE' or scan.get('comparison_method') != 'size_mtime_ns':
        raise ValueError('分类需要完整的元数据扫描')
    versions, warnings = discover_version_paths(scan, config)
    prefixes = [(version, prefix) for version, prefix in versions.items()]
    classifier = FileClassifier()
    mappings = config.get('file_mapping', {})
    if not isinstance(mappings, dict):
        raise ValueError('file_mapping 必须是路径到映射对象的字典')
    rows = []
    for entry in scan['files']:
        path = entry['path']
        matches = [(v, prefix) for v, prefix in prefixes if path.startswith(prefix + '/')]
        hint = classifier.classify({'path': path, 'name': PurePosixPath(path).name})
        view = _VIEWS.get(hint['file_type'], 'OTHER')
        unique = len(matches) == 1
        version, prefix = matches[0] if unique else (None, None)
        relative = path[len(prefix) + 1:] if unique else None
        explicit = mappings.get(path, {})
        if not isinstance(explicit, dict):
            raise ValueError(f'file_mapping 中存在非对象条目: {path}')
        explicit_key = explicit.get('file_key')
        key = explicit_key if isinstance(explicit_key, str) and explicit_key.strip() else None
        basis = 'explicit' if key else None
        if unique and not key and config.get('infer_file_slots', True):
            library = config.get('source_library_id') or scan.get('source_library_id')
            key = _slot_from_name(relative, view, library) if library else None
            basis = 'filename_unique_candidate' if key else None
        if not unique:
            key = None
            basis = None
        mode = explicit.get('mode') or _mode_hint(path)
        corner_hint = hint.get('corner')
        # Only exact process token may be copied to v3 corner; PVT hints remain
        # in classification evidence for a later, explicit normalization rule.
        corner = explicit.get('corner') or (corner_hint or {}).get('process')
        rows.append({**entry,
                     'supplier_version': version, 'relative_in_version': relative,
                     'view': view, 'file_type': hint['file_type'], 'role': hint['role'],
                     'corner_hint': corner_hint, 'corner': corner, 'mode': mode,
                     'file_key': key, 'identity_basis': basis,
                     'classification': 'RESOLVED' if key else 'UNRESOLVED',
                     'reason': None if key else ('版本范围重叠或未找到' if not unique else '文件位未识别')})
    # Same key twice within a delivery is not unambiguous, including explicit aliases.
    counts = Counter((r['supplier_version'], r['file_key']) for r in rows if r['file_key'])
    signatures = {}
    for r in rows:
        if r['identity_basis'] != 'filename_unique_candidate': continue
        path = PurePosixPath(r['relative_in_version'])
        name = path.name.lower()
        stem = next((name[:-len(s)] for s in _SLOT_SUFFIXES if name.endswith(s)), name)
        ignored = {'lef', 'tlef', 'lib', 'libs', 'liberty', 'timing', 'physical', 'views', 'models'}
        signature = tuple(x.lower() for x in path.parts[:-1] if x.lower() not in ignored) + (stem,)
        signatures.setdefault(r['file_key'], set()).add(signature)
    basenames = Counter((r['supplier_version'], PurePosixPath(r['relative_in_version']).name.lower())
                        for r in rows if r['supplier_version'] and r['relative_in_version'])
    for row in rows:
        duplicate_name = (row['identity_basis'] == 'filename_unique_candidate' and
                          basenames[(row['supplier_version'], PurePosixPath(row['relative_in_version']).name.lower())] > 1)
        normalized_collision = row['identity_basis'] == 'filename_unique_candidate' and len(signatures[row['file_key']]) > 1
        if row['file_key'] and (counts[(row['supplier_version'], row['file_key'])] > 1 or duplicate_name or normalized_collision):
            row.update(file_key=None, identity_basis=None, classification='UNRESOLVED', reason='同一交付文件位冲突')
    return {'scan_id': scan.get('scan_id'), 'version_paths': versions,
            'warnings': warnings, 'files': rows}
