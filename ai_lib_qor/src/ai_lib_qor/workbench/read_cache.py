"""Thread-safe mtime-signature in-memory read cache for workbench display projections.

Zero staleness design:
- Before serving a cached value, computes a lightweight `os.stat`/`os.scandir` signature over
  the work directory's key files and per-library archive/log directories (~1-3ms).
- Whenever ANY delivery, formal snapshot, effective revision, file_index, check, acceptance,
  partition, or config file changes, the directory/file mtime_ns changes and the cache misses
  automatically.
"""
from collections import OrderedDict
import os
from pathlib import Path
import threading


def _safe_stat_sig(path: Path):
    try:
        st = os.stat(path, follow_symlinks=False)
        return (st.st_mtime_ns, st.st_ctime_ns, st.st_size, st.st_ino)
    except OSError:
        return None


def compute_work_signature(work: Path) -> tuple:
    """Compute a fast, deterministic stat-based fingerprint of all mutable state under `work`."""
    parts = [
        _safe_stat_sig(work),
        _safe_stat_sig(work / 'path_sources.json'),
        _safe_stat_sig(work / 'refresh_history.jsonl'),
        _safe_stat_sig(work / 'corner_acceptance.json'),
    ]
    # Include legacy work/ip_partition_*.json files if present (covers in-place edits).
    try:
        with os.scandir(work) as w_it:
            legacy_parts = sorted(
                (e.name, _safe_stat_sig(Path(e.path)))
                for e in w_it
                if e.name.startswith('ip_partition_') and e.name.endswith('.json')
            )
            if legacy_parts:
                parts.append(tuple(legacy_parts))
    except OSError:
        pass
    libs_root = work / 'libraries'
    parts.append(_safe_stat_sig(libs_root))
    if libs_root.is_dir():
        lib_sigs = []
        try:
            with os.scandir(libs_root) as v_it:
                for v_ent in sorted(v_it, key=lambda e: e.name):
                    if v_ent.is_symlink() or not v_ent.is_dir(follow_symlinks=False):
                        continue
                    v_path = Path(v_ent.path)
                    lib_sigs.append((v_ent.name, _safe_stat_sig(v_path)))
                    try:
                        with os.scandir(v_path) as l_it:
                            for l_ent in sorted(l_it, key=lambda e: e.name):
                                if l_ent.is_symlink() or not l_ent.is_dir(follow_symlinks=False):
                                    continue
                                lp = Path(l_ent.path)
                                lib_sigs.append((
                                    v_ent.name,
                                    l_ent.name,
                                    _safe_stat_sig(lp),
                                    _safe_stat_sig(lp / 'delivery'),
                                    _safe_stat_sig(lp / 'formal'),
                                    _safe_stat_sig(lp / 'effective'),
                                    _safe_stat_sig(lp / 'log'),
                                    _safe_stat_sig(lp / 'facts'),
                                    _safe_stat_sig(lp / 'ip_partition.json'),
                                    _safe_stat_sig(lp / 'file_index.json'),
                                    _safe_stat_sig(lp / '.file_index_manifest.json'),
                                    _safe_stat_sig(lp / 'auto_effective_state.json'),
                                    _safe_stat_sig(lp / 'log' / 'runs.jsonl'),
                                    _safe_stat_sig(lp / 'log' / 'acceptance_events.jsonl'),
                                ))
                    except OSError:
                        continue
        except OSError:
            pass
        parts.append(tuple(lib_sigs))
    return tuple(parts)


class WorkbenchReadCache:
    """Bounded LRU cache keyed by `(work_signature, logical_key)`."""

    def __init__(self, work: Path, *, max_entries: int = 128):
        self.work = Path(work)
        self._max = max(16, int(max_entries))
        self._lock = threading.Lock()
        self._store: OrderedDict = OrderedDict()

    def signature(self) -> tuple:
        return compute_work_signature(self.work)

    def get_or_compute(self, logical_key, fn, *, sig: tuple | None = None):
        cur_sig = sig if sig is not None else self.signature()
        full_key = (cur_sig, logical_key)
        with self._lock:
            if full_key in self._store:
                self._store.move_to_end(full_key)
                return self._store[full_key]
        val = fn()
        with self._lock:
            self._store[full_key] = val
            self._store.move_to_end(full_key)
            while len(self._store) > self._max:
                self._store.popitem(last=False)
        return val

    def invalidate(self) -> None:
        with self._lock:
            self._store.clear()
