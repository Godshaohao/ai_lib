"""Read-only storage breakdown & safe rebuildable cache cleanup for path-based work directories."""
import json
import os
from pathlib import Path
import re

from ai_lib_qor.sources.layout import SAFE, library_folder
from ai_lib_qor.versions.store import locked, validate

_LAZY_EXCEL_RE = re.compile(r'^check_rev_[0-9]+_run_[a-f0-9]{32}\.xlsx\Z')

AUTHORITATIVE_BUCKETS = ('delivery', 'formal', 'effective', 'check_json', 'audit')
REBUILDABLE_BUCKETS = ('file_index', 'facts_pool', 'excel_cache')
ALL_BUCKETS = (*AUTHORITATIVE_BUCKETS, *REBUILDABLE_BUCKETS, 'other')


def _classify_file(folder: Path, path: Path) -> str:
    name = path.name
    parent_name = path.parent.name
    if name.startswith('delivery_') and name.endswith('.json'):
        return 'delivery'
    if name.startswith('formal_') and name.endswith('.json'):
        return 'formal'
    if name.startswith('effective_') and name.endswith('.json'):
        return 'effective'
    if name in ('file_index.json', '.file_index_manifest.json'):
        return 'file_index'
    if parent_name == 'facts' or name.startswith('fact_ca_') or (name.startswith('facts_') and name.endswith('.json')):
        return 'facts_pool'
    if (name.startswith('check_') or name.startswith('overall_')) and name.endswith('.json'):
        return 'check_json'
    if name.endswith('.xlsx'):
        return 'excel_cache'
    if name.endswith('.tsv') or name.endswith('.jsonl'):
        return 'audit'
    return 'other'


def _iter_libraries(work: Path, vendor=None, library=None):
    if bool(vendor) != bool(library):
        raise ValueError('vendor 和 library 必须同时指定或同时省略')
    if vendor:
        folder = library_folder(work, vendor, library)
        if not folder.is_dir():
            raise ValueError('指定库目录不存在')
        return [(vendor, library, folder)]
    libs_root = work / 'libraries'
    if not libs_root.is_dir():
        return []
    result = []
    for v_dir in sorted(libs_root.iterdir()):
        if v_dir.is_symlink() or not v_dir.is_dir() or not SAFE.fullmatch(v_dir.name):
            continue
        for l_dir in sorted(v_dir.iterdir()):
            if l_dir.is_symlink() or not l_dir.is_dir() or not SAFE.fullmatch(l_dir.name):
                continue
            result.append((v_dir.name, l_dir.name, l_dir))
    return result


def _measure_folder(folder: Path):
    bytes_by_kind = {k: 0 for k in ALL_BUCKETS}
    files_by_kind = {k: 0 for k in ALL_BUCKETS}
    legacy_root_files = []
    for p in folder.rglob('*'):
        if p.is_symlink() or not p.is_file():
            continue
        kind = _classify_file(folder, p)
        bytes_by_kind[kind] += p.stat().st_size
        files_by_kind[kind] += 1
        if p.parent == folder and p.name not in ('file_index.json', '.file_index_manifest.json', '.versions.lock', '.auto_effective_state.json'):
            legacy_root_files.append(p.name)
    auth_bytes = sum(bytes_by_kind[k] for k in AUTHORITATIVE_BUCKETS)
    cache_bytes = sum(bytes_by_kind[k] for k in REBUILDABLE_BUCKETS)
    return {
        'total_bytes': sum(bytes_by_kind.values()),
        'total_files': sum(files_by_kind.values()),
        'authoritative_bytes': auth_bytes,
        'rebuildable_cache_bytes': cache_bytes,
        'bytes_by_kind': bytes_by_kind,
        'files_by_kind': files_by_kind,
        'legacy_root_file_count': len(legacy_root_files),
    }


def storage_stats(work, *, vendor=None, library=None):
    """Read-only disk usage breakdown across libraries, separating authoritative history from rebuildable caches."""
    root = Path(work).resolve(strict=True)
    libs = []
    totals_bytes = {k: 0 for k in ALL_BUCKETS}
    totals_files = {k: 0 for k in ALL_BUCKETS}

    for v, lib, folder in _iter_libraries(root, vendor=vendor, library=library):
        m = _measure_folder(folder)
        libs.append({'vendor': v, 'library': lib, **m})
        for k in ALL_BUCKETS:
            totals_bytes[k] += m['bytes_by_kind'][k]
            totals_files[k] += m['files_by_kind'][k]

    root_files = {}
    if not vendor:
        for p in sorted(root.iterdir()):
            if p.is_file() and not p.is_symlink():
                root_files[p.name] = p.stat().st_size

    root_bytes = sum(root_files.values())
    auth_total = sum(totals_bytes[k] for k in AUTHORITATIVE_BUCKETS)
    cache_total = sum(totals_bytes[k] for k in REBUILDABLE_BUCKETS)

    return {
        'work': str(root),
        'library_count': len(libs),
        'total_bytes': sum(totals_bytes.values()) + root_bytes,
        'libraries_total_bytes': sum(totals_bytes.values()),
        'workspace_root_bytes': root_bytes,
        'authoritative_bytes': auth_total,
        'rebuildable_cache_bytes': cache_total,
        'bytes_by_kind': totals_bytes,
        'files_by_kind': totals_files,
        'workspace_root_files': root_files,
        'libraries': libs,
    }


def clean_cache(work, *, clean_excel=True, clean_orphan_facts=False, dry_run=True, vendor=None, library=None):
    """Safely prune ONLY rebuildable derived caches; never deletes delivery/formal/effective/check JSON or audit logs."""
    root = Path(work).resolve(strict=True)
    removed = []
    freed_bytes = 0
    skipped = []

    for v, lib, folder in _iter_libraries(root, vendor=vendor, library=library):
        with locked(folder):
            log_dir = folder / 'log'
            if clean_excel and log_dir.is_dir() and not log_dir.is_symlink():
                for xlsx in sorted(log_dir.glob('check_rev_*_run_*.xlsx')):
                    if xlsx.is_symlink() or not xlsx.is_file() or not _LAZY_EXCEL_RE.fullmatch(xlsx.name):
                        continue
                    backing = xlsx.with_suffix('.json')
                    if not backing.is_file() or backing.is_symlink():
                        skipped.append({'path': str(xlsx), 'reason': 'missing_backing_json'})
                        continue
                    try:
                        report = json.loads(backing.read_text(encoding='utf-8'))
                        validate(report, 'check_result_path')
                    except (OSError, ValueError, TypeError):
                        skipped.append({'path': str(xlsx), 'reason': 'invalid_backing_json'})
                        continue
                    size = xlsx.stat().st_size
                    if not dry_run:
                        xlsx.unlink()
                        latest_xlsx = folder / 'latest_check.xlsx'
                        if latest_xlsx.is_symlink() and os.readlink(latest_xlsx) == f'log/{xlsx.name}':
                            latest_xlsx.unlink()
                    removed.append({'vendor': v, 'library': lib, 'kind': 'excel_cache', 'file': f'log/{xlsx.name}', 'bytes': size})
                    freed_bytes += size

            if clean_orphan_facts:
                facts_dir = folder / 'facts'
                if facts_dir.is_dir() and not facts_dir.is_symlink():
                    referenced = set()
                    for cj in [*folder.glob('check_run_*.json'), *(log_dir.glob('check_rev_*_run_*.json') if log_dir.is_dir() else [])]:
                        if cj.is_symlink() or not cj.is_file():
                            continue
                        try:
                            data = json.loads(cj.read_text(encoding='utf-8'))
                            for ptr in (data.get('facts_evidence') or {}).values():
                                if isinstance(ptr, dict) and ptr.get('pool_file'):
                                    referenced.add(Path(ptr['pool_file']).name)
                        except (OSError, ValueError, TypeError):
                            # Conservative: if any check JSON cannot be read, do not delete pool files in this library.
                            referenced = None
                            break
                    if referenced is not None:
                        for fp in sorted(facts_dir.glob('fact_ca_*.json.gz')):
                            if fp.is_symlink() or not fp.is_file():
                                continue
                            if fp.name not in referenced:
                                size = fp.stat().st_size
                                if not dry_run:
                                    fp.unlink()
                                removed.append({'vendor': v, 'library': lib, 'kind': 'orphan_facts_pool', 'file': f'facts/{fp.name}', 'bytes': size})
                                freed_bytes += size

    return {
        'work': str(root),
        'dry_run': dry_run,
        'options': {'clean_excel': clean_excel, 'clean_orphan_facts': clean_orphan_facts},
        'removed_count': len(removed),
        'freed_bytes': freed_bytes,
        'removed': removed,
        'skipped': skipped,
    }
