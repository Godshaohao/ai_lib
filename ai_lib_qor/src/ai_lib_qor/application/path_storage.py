"""Read-only storage breakdown & safe rebuildable cache cleanup for path-based work directories."""
from collections import OrderedDict
from copy import deepcopy
import json
import os
from pathlib import Path
import re
from threading import Lock
from time import monotonic
import zlib

from ai_lib_qor.sources.layout import SAFE, library_folder
from ai_lib_qor.versions.store import locked, validate

_SEG = r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}'
_RUN_TAG = r'(?:run_[a-f0-9]{32}|[0-9]{8}(?:_[0-9]+)?)'
_LAZY_EXCEL_RE = re.compile(rf'^check(?:__{_SEG}__|_{_SEG}_|_)rev_[0-9]+_{_RUN_TAG}\.xlsx\Z')

AUTHORITATIVE_BUCKETS = ('delivery', 'formal', 'effective', 'check_json', 'audit', 'config')
REBUILDABLE_BUCKETS = ('file_index', 'facts_pool', 'excel_cache')
ALL_BUCKETS = (*AUTHORITATIVE_BUCKETS, *REBUILDABLE_BUCKETS, 'other')


def _classify_file(folder: Path, path: Path) -> str:
    name = path.name
    parent_name = path.parent.name
    if name == 'ip_partition.json':
        return 'config'
    if name.startswith('delivery_') and name.endswith('.json'):
        return 'delivery'
    if name.startswith('formal_') and name.endswith('.json'):
        return 'formal'
    if name.startswith('effective_') and name.endswith('.json'):
        return 'effective'
    if (
        name in ('file_index.json', '.file_index_manifest.json', '.auto_effective_state.json', '.view_extensions_state.json')
        or (name.startswith('.auto_effective_state__') and name.endswith('.json'))
    ):
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


def _stat_stamp(st):
    return st.st_dev, st.st_ino, st.st_mode, st.st_size, st.st_mtime_ns, st.st_ctime_ns


def _storage_stamp(path: Path):
    try:
        return _stat_stamp(path.stat(follow_symlinks=False))
    except OSError:
        return None


def _measure_folder(folder: Path, *, watched=None):
    bytes_by_kind = {k: 0 for k in ALL_BUCKETS}
    files_by_kind = {k: 0 for k in ALL_BUCKETS}
    legacy_root_files = []
    allowed_root = {'file_index.json', '.file_index_manifest.json', '.versions.lock', '.auto_effective_state.json', 'ip_partition.json'}
    stack = [folder]
    while stack:
        cur = stack.pop()
        if watched is not None:
            watched[cur] = _storage_stamp(cur)
        try:
            with os.scandir(cur) as it:
                for entry in it:
                    if entry.is_symlink():
                        continue
                    if entry.is_dir(follow_symlinks=False):
                        stack.append(Path(entry.path))
                        continue
                    if not entry.is_file(follow_symlinks=False):
                        continue
                    p = Path(entry.path)
                    kind = _classify_file(folder, p)
                    stat = entry.stat(follow_symlinks=False)
                    bytes_by_kind[kind] += stat.st_size
                    files_by_kind[kind] += 1
                    # Audit files append in place, so their parent directory may not change.
                    if watched is not None and kind == 'audit':
                        watched[p] = _stat_stamp(stat)
                    if cur == folder and entry.name not in allowed_root:
                        legacy_root_files.append(entry.name)
        except OSError:
            if watched is not None:
                watched[cur] = None
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


class StorageStatsCache:
    """Per-library storage measurements with staggered expiry and batched safety rechecks."""

    def __init__(self, *, max_age=60, max_entries=2048, recheck_budget=25, stagger_ratio=0.0):
        self._max_age = float(max_age)
        self._max_entries = max_entries
        self.recheck_budget = None if recheck_budget is None else max(1, int(recheck_budget))
        self._stagger_ratio = max(0.0, float(stagger_ratio))
        self._entries = OrderedDict()
        self._lock = Lock()

    def _next_recheck_at(self, folder: Path, started: float) -> float:
        if self._max_age <= 0:
            return started
        if self._stagger_ratio <= 0:
            return started + self._max_age
        bucket = (zlib.crc32(str(folder).encode('utf-8')) & 0xFFFF) / 65536.0
        return started + self._max_age * (1.0 + bucket * self._stagger_ratio)

    def measure(self, folder: Path, *, _recheck_budget=None):
        with self._lock:
            started = monotonic()
            entry = self._entries.pop(folder, None)
            if entry is not None:
                next_recheck_at, observed, totals = entry
                if self._matches(observed):
                    if started < next_recheck_at:
                        self._entries[folder] = entry
                        return deepcopy(totals)
                    # Watched directory/audit stamps still match; rate-limit TTL safety rechecks per scan
                    # so simultaneous expiry across hundreds of libraries cannot trigger a full rescan spike.
                    if _recheck_budget is not None:
                        if _recheck_budget[0] <= 0:
                            self._entries[folder] = entry
                            return deepcopy(totals)
                        _recheck_budget[0] -= 1
            watched = {}
            totals = _measure_folder(folder, watched=watched)
            if self._matches(watched):
                self._entries[folder] = (self._next_recheck_at(folder, started), watched, totals)
                while len(self._entries) > self._max_entries:
                    self._entries.popitem(last=False)
            return deepcopy(totals)

    @staticmethod
    def _matches(observed):
        return all(stamp is not None and _storage_stamp(path) == stamp for path, stamp in observed.items())


def storage_stats(work, *, vendor=None, library=None, cache=None):
    """Read-only disk usage breakdown across libraries, separating authoritative history from rebuildable caches."""
    root = Path(work).resolve(strict=True)
    libs = []
    totals_bytes = {k: 0 for k in ALL_BUCKETS}
    totals_files = {k: 0 for k in ALL_BUCKETS}
    budget_state = (
        [cache.recheck_budget]
        if (cache is not None and getattr(cache, 'recheck_budget', None) is not None)
        else None
    )

    for v, lib, folder in _iter_libraries(root, vendor=vendor, library=library):
        m = cache.measure(folder, _recheck_budget=budget_state) if cache is not None else _measure_folder(folder)
        libs.append({'vendor': v, 'library': lib, **m})
        for k in ALL_BUCKETS:
            totals_bytes[k] += m['bytes_by_kind'][k]
            totals_files[k] += m['files_by_kind'][k]

    root_files = {}
    catalog_bytes = 0
    catalog_files = 0
    if not vendor:
        for p in sorted(root.iterdir()):
            if p.is_file() and not p.is_symlink():
                root_files[p.name] = p.stat().st_size
        cat_dir = root / '.catalog'
        if cat_dir.is_dir() and not cat_dir.is_symlink():
            for cp in sorted(cat_dir.iterdir()):
                if cp.is_file() and not cp.is_symlink():
                    sz = cp.stat().st_size
                    catalog_bytes += sz
                    catalog_files += 1

    root_bytes = sum(root_files.values())
    auth_total = sum(totals_bytes[k] for k in AUTHORITATIVE_BUCKETS)
    cache_total = sum(totals_bytes[k] for k in REBUILDABLE_BUCKETS) + catalog_bytes

    return {
        'work': str(root),
        'library_count': len(libs),
        'total_bytes': sum(totals_bytes.values()) + root_bytes + catalog_bytes,
        'libraries_total_bytes': sum(totals_bytes.values()),
        'workspace_root_bytes': root_bytes,
        'catalog_cache_bytes': catalog_bytes,
        'catalog_cache_files': catalog_files,
        'authoritative_bytes': auth_total,
        'rebuildable_cache_bytes': cache_total,
        'bytes_by_kind': totals_bytes,
        'files_by_kind': totals_files,
        'workspace_root_files': root_files,
        'libraries': libs,
    }


def clean_cache(work, *, clean_excel=True, clean_orphan_facts=False, clean_catalog=False, dry_run=True, vendor=None, library=None):
    """Safely prune ONLY rebuildable derived caches; never deletes delivery/formal/effective/check JSON or audit logs."""
    root = Path(work).resolve(strict=True)
    removed = []
    freed_bytes = 0
    skipped = []

    for v, lib, folder in _iter_libraries(root, vendor=vendor, library=library):
        with locked(folder):
            log_dir = folder / 'log'
            if clean_excel and log_dir.is_dir() and not log_dir.is_symlink():
                excel_candidates = sorted(log_dir.glob('check_*.xlsx'))
                for xlsx in excel_candidates:
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
                        ptr_name = f"latest_check__{report['business_ip']}.xlsx" if report.get('business_ip') else 'latest_check.xlsx'
                        latest_xlsx = folder / ptr_name
                        if latest_xlsx.is_symlink() and os.readlink(latest_xlsx) == f'log/{xlsx.name}':
                            latest_xlsx.unlink()
                    removed.append({'vendor': v, 'library': lib, 'kind': 'excel_cache', 'file': f'log/{xlsx.name}', 'bytes': size})
                    freed_bytes += size

            if clean_orphan_facts:
                facts_dir = folder / 'facts'
                if facts_dir.is_dir() and not facts_dir.is_symlink():
                    referenced = set()
                    check_globs = [
                        *folder.glob('check_run_*.json'),
                        *(log_dir.glob('check_*.json') if log_dir.is_dir() else []),
                    ]
                    for cj in check_globs:
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

    if clean_catalog and not vendor:
        cat_dir = root / '.catalog'
        if cat_dir.is_dir() and not cat_dir.is_symlink():
            with locked(cat_dir):
                for cp in sorted(cat_dir.iterdir()):
                    if cp.is_symlink() or not cp.is_file():
                        continue
                    if cp.name.startswith('projection.sqlite'):
                        size = cp.stat().st_size
                        if not dry_run:
                            cp.unlink()
                        removed.append({'vendor': '', 'library': '', 'kind': 'catalog_cache', 'file': f'.catalog/{cp.name}', 'bytes': size})
                        freed_bytes += size
            if not dry_run:
                from .catalog_projection import invalidate_projection_freshness_cache
                invalidate_projection_freshness_cache(root)

    return {
        'work': str(root),
        'dry_run': dry_run,
        'options': {'clean_excel': clean_excel, 'clean_orphan_facts': clean_orphan_facts, 'clean_catalog': clean_catalog},
        'removed_count': len(removed),
        'freed_bytes': freed_bytes,
        'removed': removed,
        'skipped': skipped,
    }
