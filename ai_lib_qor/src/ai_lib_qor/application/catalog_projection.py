"""Rebuildable SQLite read-projection catalog (ADR-0002) using Python 3.11+ stdlib sqlite3.

Design invariants:
- Authoritative business history remains immutable JSON/JSONL/TSV files under `work/libraries/`.
- The SQLite database is strictly a derived, rebuildable query projection (safe to delete anytime).
- Default location is `work/.catalog/projection.sqlite`, overridable to a local SSD path via
  `AI_LIB_QOR_CATALOG_DB` or `work/path_sources.json -> workbench.catalog_db_path` for NFS deployments.
- Setting `AI_LIB_QOR_CATALOG_SQLITE=0` disables SQLite cleanly and falls back to direct JSON reads.
"""
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import threading
import time
import uuid

from ai_lib_qor.checks.path_plugins import evaluate_check_verdict
from ai_lib_qor.sources.config_reader import load_work_config
from ai_lib_qor.sources.layout import SAFE, archive_files, library_folder
from ai_lib_qor.sources.timestamps import instant, utc_text
from ai_lib_qor.versions.store import locked, read_json_readonly

PROJECTION_VERSION = '2.2'


def load_delivery_discovery_times(work) -> dict[tuple[str, str, str], float]:
    """Read immutable L1 discovery timestamps from work/refresh_history.jsonl (migration-safe vs cp/st_mtime)."""
    log = Path(work) / 'refresh_history.jsonl'
    out: dict[tuple[str, str, str], float] = {}
    if not log.is_file() or log.is_symlink():
        return out
    try:
        with log.open('r', encoding='utf-8') as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(entry, dict) or entry.get('layer') != 'L1':
                    continue
                at_raw = entry.get('at')
                if not isinstance(at_raw, str) or not at_raw:
                    continue
                try:
                    ts = instant(at_raw).timestamp()
                except (ValueError, TypeError):
                    continue
                for ch in (entry.get('libraries_changed') or []):
                    if not isinstance(ch, dict):
                        continue
                    v = ch.get('vendor')
                    lib = ch.get('library')
                    if not (isinstance(v, str) and isinstance(lib, str)):
                        continue
                    for ver in (ch.get('new_deliveries') or []):
                        if isinstance(ver, str) and ver:
                            k = (v, lib, ver)
                            if k not in out or ts < out[k]:
                                out[k] = ts
    except OSError:
        return {}
    return out


def resolve_archived_time(
    vendor: str,
    library: str,
    version: str,
    file_mtime_ts: float,
    discovery_map: dict[tuple[str, str, str], float] | None = None,
) -> float:
    """Resolve migration-safe discovery timestamp: min(refresh_history L1 at, file st_mtime).

    When work/ is copied across machines without preserving mtime (cp -r / zip), file st_mtime jumps
    forward while refresh_history.jsonl keeps the original L1 discovery instant, so min() stays pinned
    to the true discovery time. Legacy workspaces without history fall back cleanly to file st_mtime.
    """
    if discovery_map:
        hist_ts = discovery_map.get((vendor, library, version))
        if hist_ts is not None:
            return min(float(hist_ts), float(file_mtime_ts))
    return float(file_mtime_ts)


def resolve_delivery_time(
    version_date: str | None,
    directory_mtime: str | None,
    archived_ts: float,
) -> tuple[float, str, str]:
    """Return (epoch_ts, display_iso_or_date, source) for a RAW delivery's business delivery time.

    Priority:
    1. version_date (YYYY-MM-DD from RAW version directory name) -> end-of-day UTC so calendar-day
       windows include the full boundary day; display text remains plain 'YYYY-MM-DD'.
    2. directory_mtime / directory_created_at persisted inside delivery_*.json -> exact UTC ISO.
    3. archived_ts fallback when both fields are absent.
    """
    if isinstance(version_date, str):
        vd = version_date.strip()
        if re.fullmatch(r'\d{4}-\d{2}-\d{2}', vd):
            try:
                dt = datetime.strptime(vd, '%Y-%m-%d').replace(hour=23, minute=59, second=59, tzinfo=timezone.utc)
                return dt.timestamp(), vd, 'version_date'
            except ValueError:
                pass
    if isinstance(directory_mtime, str) and directory_mtime.strip():
        try:
            dt = instant(directory_mtime.strip())
            return dt.timestamp(), utc_text(dt), 'directory_mtime'
        except (ValueError, TypeError):
            pass
    ts_val = float(archived_ts)
    return ts_val, utc_text(datetime.fromtimestamp(ts_val, tz=timezone.utc)), 'archived'

_FRESHNESS_LOCK = threading.Lock()
_FRESHNESS_CACHE: dict[tuple[str, str], tuple[float, tuple]] = {}
_DEFAULT_WEB_FRESH_TTL_S = 3.0

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS catalog_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS libraries (
    vendor TEXT NOT NULL,
    library TEXT NOT NULL,
    ip_type TEXT,
    is_multi_track INTEGER NOT NULL DEFAULT 0,
    ip_list_json TEXT NOT NULL DEFAULT '[]',
    tracks_json TEXT NOT NULL DEFAULT '{}',
    delivery_count INTEGER NOT NULL DEFAULT 0,
    formal_count INTEGER NOT NULL DEFAULT 0,
    revision_count INTEGER NOT NULL DEFAULT 0,
    latest_revision TEXT,
    accepted_revision TEXT,
    index_status TEXT NOT NULL DEFAULT 'MISSING',
    index_refreshed_at TEXT,
    unadopted_count INTEGER NOT NULL DEFAULT 0,
    needs_review_count INTEGER NOT NULL DEFAULT 0,
    latest_check_quality TEXT,
    latest_check_at TEXT,
    folder_sig TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (vendor, library)
);

CREATE TABLE IF NOT EXISTS deliveries (
    vendor TEXT NOT NULL,
    library TEXT NOT NULL,
    version TEXT NOT NULL,
    filename TEXT NOT NULL,
    version_date TEXT,
    directory_mtime TEXT,
    archived_at TEXT NOT NULL,
    archived_ts REAL NOT NULL,
    delivery_at TEXT NOT NULL DEFAULT '',
    delivery_ts REAL NOT NULL DEFAULT 0,
    delivery_time_source TEXT NOT NULL DEFAULT 'archived',
    file_count INTEGER NOT NULL DEFAULT 0,
    view_counts_json TEXT NOT NULL DEFAULT '{}',
    is_new_library_ts REAL NOT NULL DEFAULT 0,
    is_new_library_delivery_ts REAL NOT NULL DEFAULT 0,
    track_ip TEXT,
    eff_state TEXT NOT NULL DEFAULT 'PENDING',
    eff_label TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (vendor, library, version)
);

CREATE INDEX IF NOT EXISTS idx_deliveries_ts ON deliveries(archived_ts DESC, vendor, library, version);
CREATE INDEX IF NOT EXISTS idx_deliveries_delivery_ts ON deliveries(delivery_ts DESC, vendor, library, version);
CREATE INDEX IF NOT EXISTS idx_deliveries_lib ON deliveries(vendor, library);

CREATE TABLE IF NOT EXISTS revisions (
    vendor TEXT NOT NULL,
    library TEXT NOT NULL,
    business_ip TEXT NOT NULL DEFAULT '',
    revision TEXT NOT NULL,
    is_latest INTEGER NOT NULL DEFAULT 0,
    is_accepted INTEGER NOT NULL DEFAULT 0,
    latest_check_name TEXT,
    latest_check_quality TEXT,
    latest_check_state TEXT,
    failed_checks INTEGER NOT NULL DEFAULT 0,
    inconclusive_checks INTEGER NOT NULL DEFAULT 0,
    failed_files INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (vendor, library, business_ip, revision)
);

CREATE INDEX IF NOT EXISTS idx_revisions_lib ON revisions(vendor, library, business_ip);

CREATE TABLE IF NOT EXISTS checks (
    vendor TEXT NOT NULL,
    library TEXT NOT NULL,
    check_name TEXT NOT NULL,
    business_ip TEXT NOT NULL DEFAULT '',
    revision TEXT NOT NULL DEFAULT '',
    baseline TEXT,
    run_id TEXT,
    run_at TEXT NOT NULL DEFAULT '',
    state TEXT NOT NULL DEFAULT 'UNKNOWN',
    quality_code TEXT NOT NULL DEFAULT 'PARTIAL',
    quality_text TEXT NOT NULL DEFAULT '',
    failed_checks INTEGER NOT NULL DEFAULT 0,
    inconclusive_checks INTEGER NOT NULL DEFAULT 0,
    failed_files INTEGER NOT NULL DEFAULT 0,
    is_corrupt INTEGER NOT NULL DEFAULT 0,
    corrupt_reason TEXT,
    file_mtime_ns INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (vendor, library, check_name)
);

CREATE INDEX IF NOT EXISTS idx_checks_quality ON checks(quality_code, run_at DESC);
CREATE INDEX IF NOT EXISTS idx_checks_scope ON checks(vendor, library, business_ip, revision);

CREATE TABLE IF NOT EXISTS artifacts (
    vendor TEXT NOT NULL DEFAULT '',
    library TEXT NOT NULL DEFAULT '',
    rel_path TEXT NOT NULL,
    layer TEXT NOT NULL,
    layer_label TEXT NOT NULL,
    category TEXT NOT NULL,
    filename TEXT NOT NULL,
    scope_label TEXT NOT NULL,
    sync_group TEXT NOT NULL DEFAULT 'unchanged',
    status_label TEXT NOT NULL DEFAULT '',
    tag_cls TEXT NOT NULL DEFAULT 'tag-inherited',
    status_note TEXT NOT NULL DEFAULT '',
    pointer_badge TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT '',
    updated_ts REAL NOT NULL DEFAULT 0,
    size_text TEXT NOT NULL DEFAULT '0 B',
    size_bytes INTEGER NOT NULL DEFAULT 0,
    exists_flag INTEGER NOT NULL DEFAULT 1,
    action_kind TEXT NOT NULL DEFAULT 'library',
    revision TEXT NOT NULL DEFAULT '',
    business_ip TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (vendor, library, rel_path)
);

CREATE INDEX IF NOT EXISTS idx_artifacts_layer ON artifacts(layer, sync_group, updated_ts DESC);
CREATE INDEX IF NOT EXISTS idx_artifacts_lib ON artifacts(vendor, library, layer);

-- Layer 2: Medium-granularity summary projections (no per-pin FileFacts bloat)
CREATE TABLE IF NOT EXISTS check_items (
    vendor TEXT NOT NULL,
    library TEXT NOT NULL,
    check_name TEXT NOT NULL,
    item_idx INTEGER NOT NULL,
    business_ip TEXT NOT NULL DEFAULT '',
    revision TEXT NOT NULL DEFAULT '',
    run_at TEXT NOT NULL DEFAULT '',
    is_latest_check INTEGER NOT NULL DEFAULT 0,
    is_latest_revision INTEGER NOT NULL DEFAULT 0,
    check_id TEXT NOT NULL,
    result TEXT NOT NULL,
    coverage TEXT NOT NULL DEFAULT 'UNKNOWN',
    severity TEXT,
    scope_files_count INTEGER NOT NULL DEFAULT 0,
    findings_count INTEGER NOT NULL DEFAULT 0,
    detail TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (vendor, library, check_name, item_idx)
);

CREATE INDEX IF NOT EXISTS idx_check_items_rule ON check_items(check_id, result, is_latest_check, is_latest_revision);
CREATE INDEX IF NOT EXISTS idx_check_items_scope ON check_items(vendor, library, business_ip, revision);

CREATE TABLE IF NOT EXISTS object_change_events (
    vendor TEXT NOT NULL,
    library TEXT NOT NULL,
    check_name TEXT NOT NULL,
    event_idx INTEGER NOT NULL,
    business_ip TEXT NOT NULL DEFAULT '',
    revision TEXT NOT NULL DEFAULT '',
    baseline TEXT,
    run_at TEXT NOT NULL DEFAULT '',
    is_latest_check INTEGER NOT NULL DEFAULT 0,
    is_latest_revision INTEGER NOT NULL DEFAULT 0,
    view TEXT NOT NULL DEFAULT '',
    file_path TEXT NOT NULL DEFAULT '',
    baseline_version TEXT NOT NULL DEFAULT '',
    version TEXT NOT NULL DEFAULT '',
    object_type TEXT NOT NULL DEFAULT '',
    object_name TEXT NOT NULL DEFAULT '',
    change_kind TEXT NOT NULL DEFAULT '',
    old_value TEXT NOT NULL DEFAULT '',
    new_value TEXT NOT NULL DEFAULT '',
    unit TEXT,
    PRIMARY KEY (vendor, library, check_name, event_idx)
);

CREATE INDEX IF NOT EXISTS idx_obj_changes_name ON object_change_events(object_name, change_kind, run_at DESC);
CREATE INDEX IF NOT EXISTS idx_obj_changes_lib ON object_change_events(vendor, library, revision, is_latest_check);

CREATE TABLE IF NOT EXISTS effective_views (
    vendor TEXT NOT NULL,
    library TEXT NOT NULL,
    business_ip TEXT NOT NULL DEFAULT '',
    revision TEXT NOT NULL,
    view TEXT NOT NULL,
    file_path TEXT NOT NULL,
    is_latest INTEGER NOT NULL DEFAULT 0,
    is_accepted INTEGER NOT NULL DEFAULT 0,
    source_version TEXT NOT NULL DEFAULT '',
    filename TEXT NOT NULL DEFAULT '',
    corner_hint TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (vendor, library, business_ip, revision, view, file_path)
);

CREATE INDEX IF NOT EXISTS idx_eff_views_corner ON effective_views(view, corner_hint);
CREATE INDEX IF NOT EXISTS idx_eff_views_scope ON effective_views(vendor, library, business_ip, is_latest, is_accepted);

CREATE TABLE IF NOT EXISTS effective_objects (
    vendor TEXT NOT NULL,
    library TEXT NOT NULL,
    business_ip TEXT NOT NULL DEFAULT '',
    revision TEXT NOT NULL,
    view TEXT NOT NULL,
    object_type TEXT NOT NULL,
    object_name TEXT NOT NULL,
    is_latest INTEGER NOT NULL DEFAULT 0,
    is_accepted INTEGER NOT NULL DEFAULT 0,
    pin_count INTEGER NOT NULL DEFAULT 0,
    width_um REAL,
    height_um REAL,
    area_um2 REAL,
    corner_file_count INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (vendor, library, business_ip, revision, view, object_type, object_name)
);

CREATE INDEX IF NOT EXISTS idx_eff_objects_name ON effective_objects(object_name, object_type);
CREATE INDEX IF NOT EXISTS idx_eff_objects_scope ON effective_objects(vendor, library, business_ip, is_latest, is_accepted);
"""


def catalog_enabled(work=None) -> bool:
    """Return False when explicitly disabled via env or workspace config."""
    env_flag = os.environ.get('AI_LIB_QOR_CATALOG_SQLITE')
    if env_flag is not None and env_flag.strip() != '':
        return env_flag.strip().lower() not in ('0', 'false', 'no', 'off')
    if work is not None:
        try:
            wb = load_work_config(Path(work)).get('workbench') or {}
            if isinstance(wb, dict) and 'catalog_sqlite' in wb:
                return bool(wb['catalog_sqlite'])
        except (OSError, ValueError, TypeError):
            pass
    return True


def catalog_db_path(work) -> Path:
    """Resolve projection SQLite path (env override > workbench.catalog_db_path > work/.catalog/projection.sqlite)."""
    root = Path(work).resolve()
    env_path = (os.environ.get('AI_LIB_QOR_CATALOG_DB') or '').strip()
    if env_path:
        target = Path(env_path).expanduser()
        return target if target.is_absolute() else (root / target)
    try:
        wb = load_work_config(root).get('workbench') or {}
        if isinstance(wb, dict) and isinstance(wb.get('catalog_db_path'), str) and wb['catalog_db_path'].strip():
            cfg_p = Path(wb['catalog_db_path'].strip()).expanduser()
            return cfg_p if cfg_p.is_absolute() else (root / cfg_p)
    except (OSError, ValueError, TypeError):
        pass
    return root / '.catalog' / 'projection.sqlite'


def catalog_web_fresh_ttl() -> float:
    """Return short TTL (seconds) for interactive Web catalog freshness checks (0 disables TTL)."""
    raw = (os.environ.get('AI_LIB_QOR_CATALOG_FRESH_TTL') or '').strip()
    if raw != '':
        try:
            return max(0.0, float(raw))
        except ValueError:
            pass
    return _DEFAULT_WEB_FRESH_TTL_S


def invalidate_projection_freshness_cache(work=None) -> None:
    """Drop in-process freshness TTL entries after writes, rebuilds, config edits, or cache cleanup."""
    with _FRESHNESS_LOCK:
        if work is None:
            _FRESHNESS_CACHE.clear()
            return
        root_str = str(Path(work).resolve())
        for k in [k for k in _FRESHNESS_CACHE if k[0] == root_str]:
            _FRESHNESS_CACHE.pop(k, None)


def _safe_stat_token(path: Path) -> tuple | None:
    try:
        st = os.stat(path, follow_symlinks=False)
        return (st.st_mtime_ns, st.st_ctime_ns, st.st_size, st.st_ino)
    except OSError:
        return None


def _db_stat_token(target: Path) -> tuple:
    return (
        _safe_stat_token(target),
        _safe_stat_token(Path(str(target) + '-wal')),
    )


def _load_work_cfg_safe(work: Path) -> dict:
    try:
        cfg = load_work_config(work)
        return cfg if isinstance(cfg, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def _library_config_slice(work_cfg: dict, vendor: str, library: str) -> dict:
    """Extract only the path_sources.json fields that affect THIS library's projection rows."""
    libs_map = work_cfg.get('libraries') if isinstance(work_cfg, dict) else None
    v_map = libs_map.get(vendor) if isinstance(libs_map, dict) else None
    lib_cfg = v_map.get(library) if isinstance(v_map, dict) else None
    if not isinstance(lib_cfg, dict):
        return {}
    return {
        'ip_type': lib_cfg.get('ip_type'),
        'ip_list': lib_cfg.get('ip_list'),
        'ignored_unadopted_files': lib_cfg.get('ignored_unadopted_files'),
        'excluded_versions': lib_cfg.get('excluded_versions'),
        'version_registration_times': lib_cfg.get('version_registration_times'),
    }


def _library_folder_sig(
    work: Path,
    vendor: str,
    library: str,
    folder: Path,
    *,
    work_cfg: dict | None = None,
) -> str:
    """Compact deterministic SHA-256 over ONE library's mutable directory stamps & its own config slice."""
    cfg = work_cfg if work_cfg is not None else _load_work_cfg_safe(work)
    parts = [
        _library_config_slice(cfg, vendor, library),
        _safe_stat_token(work / f'ip_partition_{vendor}_{library}.json'),
        _safe_stat_token(folder),
        _safe_stat_token(folder / 'delivery'),
        _safe_stat_token(folder / 'formal'),
        _safe_stat_token(folder / 'effective'),
        _safe_stat_token(folder / 'log'),
        _safe_stat_token(folder / 'ip_partition.json'),
        _safe_stat_token(folder / 'file_index.json'),
        _safe_stat_token(folder / '.file_index_manifest.json'),
        _safe_stat_token(folder / 'latest_effective.json'),
        _safe_stat_token(folder / 'accepted_effective.json'),
        _safe_stat_token(folder / 'latest_check.json'),
        _safe_stat_token(folder / 'log' / 'runs.jsonl'),
        _safe_stat_token(folder / 'log' / 'acceptance_events.jsonl'),
    ]
    raw = json.dumps(parts, separators=(',', ':'), sort_keys=True).encode('utf-8')
    return hashlib.sha256(raw).hexdigest()[:24]


def _config_sig(work: Path) -> str:
    parts = [
        _safe_stat_token(work / 'path_sources.json'),
        _safe_stat_token(work / 'refresh_history.jsonl'),
        _safe_stat_token(work / 'formal_observations.tsv'),
    ]
    return hashlib.sha256(json.dumps(parts, separators=(',', ':')).encode('utf-8')).hexdigest()[:24]


def _connect(db_path: Path, *, readonly: bool = False) -> sqlite3.Connection:
    if db_path.is_symlink() or db_path.parent.is_symlink():
        raise ValueError('Catalog 投影数据库路径不能为软链接')
    if readonly:
        uri = f'file:{db_path.as_posix()}?mode=ro'
        conn = sqlite3.connect(uri, uri=True, timeout=5.0)
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA busy_timeout=5000')
        return conn
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA busy_timeout=5000')
    try:
        conn.execute('PRAGMA journal_mode=WAL')
    except sqlite3.OperationalError:
        try:
            conn.execute('PRAGMA journal_mode=DELETE')
        except sqlite3.OperationalError:
            pass
    conn.execute('PRAGMA synchronous=NORMAL')
    conn.execute('PRAGMA temp_store=MEMORY')
    return conn


def _init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(_SCHEMA_SQL)


def _fmt_bytes(n: int) -> str:
    val = float(n)
    for unit in ('B', 'KB', 'MB', 'GB'):
        if val < 1024 or unit == 'GB':
            return f'{val:.1f} {unit}' if unit != 'B' else f'{int(val)} B'
        val /= 1024.0
    return f'{n} B'


def _fmt_mtime(path: Path) -> tuple[str, float, str, int]:
    st = path.stat()
    dt = datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
    return dt, st.st_mtime, _fmt_bytes(st.st_size), st.st_size


def _iter_workspace_libraries(work: Path) -> list[tuple[str, str, Path]]:
    root = work / 'libraries'
    if not root.is_dir() or root.is_symlink():
        return []
    out = []
    for folder in sorted(root.glob('*/*')):
        if folder.is_symlink() or not folder.is_dir() or folder.parent.is_symlink():
            continue
        v, lib = folder.parent.name, folder.name
        if SAFE.fullmatch(v) and SAFE.fullmatch(lib):
            out.append((v, lib, folder))
    return out


def _collect_workspace_artifact_rows(work: Path) -> list[tuple]:
    rows = []
    specs = [
        ('path_sources.json', 'WORKSPACE', '工作区', '来源目录配置', '已生效', 'tag-inherited', '记录 RAW 与 Formal 根目录及默认同步选项', 'config'),
        ('refresh_history.jsonl', 'WORKSPACE', '工作区', '三层同步历史', '持续追加', 'tag-inherited', '记录每次 L1/L2/L3 同步批次与异常摘要', 'history'),
        ('formal_observations.tsv', 'L1', 'L1 来源', 'Formal 观察日志', '持续追加', 'tag-inherited', '记录每次 Formal NL 软链接观察快照', 'history'),
    ]
    for fname, layer, llabel, cat, slabel, tcls, snote, akind in specs:
        p = work / fname
        if p.is_file() and not p.is_symlink():
            dt, ts, sz_txt, sz = _fmt_mtime(p)
            rows.append((
                '', '', fname, layer, llabel, cat, fname, '工作区全局',
                'unchanged', slabel, tcls, snote, '', dt, ts, sz_txt, sz, 1, akind, '', '',
            ))
    return rows


def _collect_library_rows(
    work: Path,
    vendor: str,
    library: str,
    folder: Path,
    *,
    work_cfg: dict | None = None,
    discovery_map: dict[tuple[str, str, str], float] | None = None,
) -> dict:
    """Extract all Layer-1 & Layer-2 derived rows for ONE library from authoritative/saved files."""
    from .ip_partition import active_tracks_for_library
    from .minimal_effective import _flat, fast_library_track_revisions
    from .minimal_file_index import _ignored_unadopted_digest, index_manifest_matches
    from .path_query import _resolve_pointer_in_folder, unadopted_new_files

    now_iso = utc_text()
    sig = _library_folder_sig(work, vendor, library, folder, work_cfg=work_cfg)

    # 1. Track & IP metadata
    ip_type = None
    is_multi_track = False
    ip_list: list[str] = []
    tracks_counts: dict[str, int] = {}
    ver_to_track: dict[str, str] = {}
    nr_versions: set[str] = set()
    needs_review_count = 0
    try:
        tinfo = active_tracks_for_library(work, vendor, library)
        ip_type = tinfo.get('ip_type')
        is_multi_track = bool(tinfo.get('is_multi_track'))
        if is_multi_track:
            ip_list = list(tinfo.get('ip_list') or [])
            tracks_map = tinfo.get('tracks') or {}
            tracks_counts = {k: len(vs) for k, vs in tracks_map.items()}
            for ip_name, vs in tracks_map.items():
                for dv in vs:
                    ver_to_track[dv] = ip_name
            nr = tinfo.get('needs_review') or {}
            c_list = nr.get('conflicts') or []
            u_list = nr.get('unassigned') or []
            needs_review_count = len(c_list) + len(u_list)
            for item in c_list:
                if isinstance(item, dict) and item.get('version'):
                    nr_versions.add(item['version'])
            for item in u_list:
                if isinstance(item, dict) and item.get('version'):
                    nr_versions.add(item['version'])
                elif isinstance(item, str):
                    nr_versions.add(item)
    except (OSError, ValueError, TypeError):
        pass

    # 2. Effective revisions & accepted pointers (zero JSON reads via scandir)
    revs_by_ip, acc_by_ip = fast_library_track_revisions(folder, library)
    all_single_revs = revs_by_ip.get(None, [])
    latest_rev = all_single_revs[-1] if all_single_revs else None
    accepted_rev = acc_by_ip.get(None)
    eff_count = sum(len(vs) for vs in revs_by_ip.values())

    # Resolve adopted versions from latest effective snapshot(s)
    adopted_by_ver: dict[str, list[str]] = {}
    eff_has_any = eff_count > 0
    if is_multi_track:
        for ip_name in sorted(k for k in revs_by_ip if k is not None):
            lptr = _resolve_pointer_in_folder(folder, f'latest_effective__{ip_name}.json')
            if lptr is not None:
                try:
                    row = read_json_readonly(lptr)
                    if isinstance(row, dict) and row.get('revision'):
                        for sv in set(_flat(row.get('views') or {}).values()):
                            adopted_by_ver.setdefault(sv, []).append(f"{ip_name}:{row['revision']}")
                except (OSError, ValueError, TypeError):
                    pass
    elif eff_has_any:
        lptr = _resolve_pointer_in_folder(folder, 'latest_effective.json')
        if lptr is not None:
            try:
                row = read_json_readonly(lptr)
                if isinstance(row, dict) and row.get('revision'):
                    for sv in set(_flat(row.get('views') or {}).values()):
                        adopted_by_ver.setdefault(sv, []).append(row['revision'])
            except (OSError, ValueError, TypeError):
                pass

    # 3. Index status & unadopted count
    index_path = folder / 'file_index.json'
    manifest = None
    if index_path.is_symlink() or not index_path.is_file():
        idx_state, refreshed_at = 'MISSING', None
    else:
        matched, manifest = index_manifest_matches(work, vendor, library, fast=True)
        if matched:
            idx_state, refreshed_at = 'FRESH', manifest.get('refreshed_at')
        else:
            idx_state = 'UNVERIFIED' if manifest is None else 'STALE'
            refreshed_at = manifest.get('refreshed_at') if manifest else None

    unadopted_count = None
    if idx_state == 'FRESH' and isinstance(manifest, dict) and 'unadopted_new_files_count' in manifest:
        _, cur_ign_sha = _ignored_unadopted_digest(work, vendor, library)
        if manifest.get('ignored_unadopted_sha256') == cur_ign_sha:
            unadopted_count = int(manifest['unadopted_new_files_count'])
    if unadopted_count is None:
        try:
            uinfo = unadopted_new_files(work, vendor, library, sample_limit=5)
            unadopted_count = int(uinfo['count']) if uinfo else 0
        except (OSError, ValueError, TypeError):
            unadopted_count = 0

    # 4. Deliveries + L1 artifacts
    artifact_rows: list[tuple] = []
    delivery_rows: list[tuple] = []
    deliv_files = [p for p in archive_files(folder, 'delivery', 'delivery_*.json') if not p.is_symlink() and p.is_file()]
    formal_files = [p for p in archive_files(folder, 'formal', 'formal_*.json') if not p.is_symlink() and p.is_file()]
    scope_lbl = f'{vendor} / {library}'

    deliv_mtimes = []
    for p in deliv_files:
        try:
            deliv_mtimes.append((p, _fmt_mtime(p)))
        except OSError:
            continue
    earliest_ts = min((m[1] for _, m in deliv_mtimes), default=0.0)

    latest_deliv_target = _resolve_pointer_in_folder(folder, 'latest_delivery.json')
    latest_deliv_name = latest_deliv_target.name if latest_deliv_target else None

    if discovery_map is None:
        discovery_map = load_delivery_discovery_times(work)
    pending_delivery_rows: list[tuple] = []
    for p, (dt, ts, sz_txt, sz) in deliv_mtimes:
        rel_path = f'libraries/{vendor}/{library}/{p.relative_to(folder).as_posix()}'
        artifact_rows.append((
            vendor, library, rel_path, 'L1', 'L1 来源', 'RAW 交付归档', p.name, scope_lbl,
            'unchanged', '已归档', 'tag-inherited', '不可变来源交付记录',
            '最新交付' if p.name == latest_deliv_name else '',
            dt, ts, sz_txt, sz, 1, 'library', '', '',
        ))
        try:
            data = read_json_readonly(p)
        except (OSError, ValueError, TypeError):
            continue
        if not isinstance(data, dict) or not isinstance(data.get('version'), str):
            continue
        ver = data['version']
        views_obj = data.get('views') if isinstance(data.get('views'), dict) else {}
        vcounts = {vk: len(vlist) for vk, vlist in sorted(views_obj.items()) if isinstance(vlist, list) and vlist}
        adopted_revs = adopted_by_ver.get(ver) or []
        if ver in nr_versions:
            eff_state, eff_label = 'REVIEW', '分轨待复核'
        elif adopted_revs:
            eff_state, eff_label = 'ADOPTED', '已入版 ' + ', '.join(adopted_revs[:2])
        elif eff_has_any:
            eff_state, eff_label = 'ARCHIVED', '已归档（已被新版覆盖或未选入）'
        else:
            eff_state, eff_label = 'PENDING', '待建有效版'
        vdate = data.get('version_date')
        dmtime = data.get('directory_mtime') or data.get('directory_created_at')
        arch_ts = resolve_archived_time(vendor, library, ver, ts, discovery_map)
        deliv_ts, deliv_at, deliv_src = resolve_delivery_time(vdate, dmtime, arch_ts)
        pending_delivery_rows.append((
            vendor, library, ver, p.name,
            vdate,
            dmtime,
            utc_text(datetime.fromtimestamp(arch_ts, tz=timezone.utc)),
            arch_ts,
            deliv_at,
            deliv_ts,
            deliv_src,
            sum(vcounts.values()),
            json.dumps(vcounts, ensure_ascii=False, sort_keys=True),
            ver_to_track.get(ver),
            eff_state,
            eff_label,
        ))
    earliest_archived_ts = min((r[7] for r in pending_delivery_rows), default=earliest_ts)
    earliest_delivery_ts = min((r[9] for r in pending_delivery_rows), default=0.0)
    for r in pending_delivery_rows:
        delivery_rows.append((
            r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[7],
            r[8], r[9], r[10], r[11], r[12], earliest_archived_ts, earliest_delivery_ts,
            r[13], r[14], r[15],
        ))

    for p in formal_files:
        try:
            dt, ts, sz_txt, sz = _fmt_mtime(p)
        except OSError:
            continue
        rel_path = f'libraries/{vendor}/{library}/{p.relative_to(folder).as_posix()}'
        artifact_rows.append((
            vendor, library, rel_path, 'L1', 'L1 来源', 'Formal (NL) 快照', p.name, scope_lbl,
            'unchanged', '已归档', 'tag-inherited', '不可变正式来源观察快照', '',
            dt, ts, sz_txt, sz, 1, 'library', '', '',
        ))

    # 5. L2 Effective artifacts
    eff_files = [p for p in archive_files(folder, 'effective', f'effective_{library}_*.json') if not p.is_symlink() and p.is_file()]
    rev_single_re = re.compile(rf'^effective_{re.escape(library)}_(\d+)\.json\Z')
    rev_multi_re = re.compile(rf'^effective_{re.escape(library)}__([A-Za-z0-9][A-Za-z0-9_.-]{{0,127}})_(\d+)\.json\Z')
    eff_path_by_scope: dict[tuple[str, str], Path] = {}
    for p in eff_files:
        try:
            dt, ts, sz_txt, sz = _fmt_mtime(p)
        except OSError:
            continue
        m_tr = rev_multi_re.fullmatch(p.name)
        m_sg = rev_single_re.fullmatch(p.name) if not m_tr else None
        bip = m_tr.group(1) if m_tr else ''
        rev_str = f'rev_{int(m_tr.group(2)):04d}' if m_tr else (f'rev_{int(m_sg.group(1)):04d}' if m_sg else '')
        p_badge = ''
        if rev_str:
            eff_path_by_scope[(bip, rev_str)] = p
            ip_key = bip or None
            is_lat = bool(revs_by_ip.get(ip_key) and rev_str == revs_by_ip[ip_key][-1])
            is_acc = bool(acc_by_ip.get(ip_key) and rev_str == acc_by_ip[ip_key])
            if is_lat and is_acc:
                p_badge = '最新 · 已采纳'
            elif is_acc:
                p_badge = '已采纳'
            elif is_lat:
                p_badge = '最新有效版'
        rel_path = f'libraries/{vendor}/{library}/{p.relative_to(folder).as_posix()}'
        artifact_rows.append((
            vendor, library, rel_path, 'L2', 'L2 版本', '有效版本快照', p.name, scope_lbl,
            'unchanged', '已发布', 'tag-inherited', f'轨道 {bip}' if bip else '单轨有效版本', p_badge,
            dt, ts, sz_txt, sz, 1, 'library', rev_str, bip,
        ))

    # 6. L3 FileIndex artifact
    if index_path.is_file() and not index_path.is_symlink():
        try:
            dt, ts, sz_txt, sz = _fmt_mtime(index_path)
            s_grp = 'unchanged' if idx_state == 'FRESH' else 'issue'
            s_lbl = '已同步' if idx_state == 'FRESH' else '待刷新'
            t_cls = 'tag-new' if idx_state == 'FRESH' else 'tag-partial'
            artifact_rows.append((
                vendor, library, f'libraries/{vendor}/{library}/file_index.json',
                'L3', 'L3 索引', '统一文件索引', 'file_index.json', scope_lbl,
                s_grp, s_lbl, t_cls, '由 L1/L2 重建的统一查询投影', '',
                dt, ts, sz_txt, sz, 1, 'download_index', '', '',
            ))
        except OSError:
            pass
    else:
        artifact_rows.append((
            vendor, library, f'libraries/{vendor}/{library}/file_index.json',
            'L3', 'L3 索引', '统一文件索引', 'file_index.json', scope_lbl,
            'issue', '未生成', 'tag-partial', '尚未生成 file_index.json，请刷新 L3', '',
            '', 0.0, '0 B', 0, 0, 'index', '', '',
        ))

    # 7. Checks (strictly Schema-validated; corrupt check JSON explicitly marked)
    check_rows: list[tuple] = []
    valid_checks: list[tuple[str, int, dict]] = []
    latest_valid_check_by_scope: dict[tuple[str, str], tuple[int, str, str, str, int, int, int]] = {}
    latest_valid_doc_by_scope: dict[tuple[str, str], tuple[int, str, dict]] = {}
    latest_lib_check: tuple[int, str, str] | None = None

    log_dir = folder / 'log'
    chk_candidates = [*folder.glob('check_run_*.json')]
    if log_dir.is_dir() and not log_dir.is_symlink():
        chk_candidates.extend(log_dir.glob('check_*.json'))

    for cp in sorted(set(chk_candidates), key=lambda x: x.name):
        if cp.is_symlink() or not cp.is_file():
            continue
        try:
            st = cp.stat()
            mtime_ns = st.st_mtime_ns
        except OSError:
            continue
        try:
            doc = read_json_readonly(cp, 'check_result_path')
            if (doc.get('vendor'), doc.get('library')) != (vendor, library):
                continue
            verdict = evaluate_check_verdict(doc)
            bip = doc.get('business_ip') or ''
            rev = doc.get('revision') or ''
            run_at = doc.get('run_at') or ''
            state = doc.get('state') or 'UNKNOWN'
            q_code = verdict['code']
            q_text = verdict['text']
            fc = int(verdict['failed_checks'])
            ic = int(verdict['inconclusive_checks'])
            ff = int(verdict['failed_files'])
            check_rows.append((
                vendor, library, cp.name, bip, rev, doc.get('baseline'),
                doc.get('run_id'), run_at, state, q_code, q_text, fc, ic, ff,
                0, None, mtime_ns,
            ))
            valid_checks.append((cp.name, mtime_ns, doc))
            scope_k = (bip, rev)
            prev_s = latest_valid_check_by_scope.get(scope_k)
            if prev_s is None or mtime_ns >= prev_s[0]:
                latest_valid_check_by_scope[scope_k] = (mtime_ns, cp.name, q_code, state, fc, ic, ff)
                latest_valid_doc_by_scope[scope_k] = (mtime_ns, cp.name, doc)
            if latest_lib_check is None or mtime_ns >= latest_lib_check[0]:
                latest_lib_check = (mtime_ns, q_code, run_at)
        except ValueError as exc:
            raw_rev, raw_ip = '', ''
            try:
                raw_d = read_json_readonly(cp)
                if isinstance(raw_d, dict):
                    raw_rev = str(raw_d.get('revision') or '')
                    raw_ip = str(raw_d.get('business_ip') or '')
            except (OSError, ValueError):
                pass
            check_rows.append((
                vendor, library, cp.name, raw_ip, raw_rev, None,
                None, '', 'CORRUPT', 'CORRUPT', '记录损坏（Schema 无效）', 0, 0, 0,
                1, str(exc)[:300], mtime_ns,
            ))
        except OSError:
            continue

    # 8. Revisions table rows (single-track & multi-track) + active revision lookup
    revision_rows: list[tuple] = []
    latest_rev_by_bip: dict[str, str] = {}
    accepted_rev_by_bip: dict[str, str] = {}
    active_eff_scopes: dict[tuple[str, str], tuple[int, int]] = {}
    for ip_key, rev_list in sorted(revs_by_ip.items(), key=lambda x: x[0] or ''):
        bip = ip_key or ''
        acc_r = acc_by_ip.get(ip_key)
        lat_r = rev_list[-1] if rev_list else None
        if lat_r:
            latest_rev_by_bip[bip] = lat_r
        if acc_r:
            accepted_rev_by_bip[bip] = acc_r
        for rev in rev_list:
            is_lat = 1 if rev == lat_r else 0
            is_acc = 1 if rev == acc_r else 0
            if is_lat or is_acc:
                active_eff_scopes[(bip, rev)] = (is_lat, is_acc)
            hit = latest_valid_check_by_scope.get((bip, rev))
            revision_rows.append((
                vendor, library, bip, rev,
                is_lat,
                is_acc,
                hit[1] if hit else None,
                hit[2] if hit else None,
                hit[3] if hit else None,
                hit[4] if hit else 0,
                hit[5] if hit else 0,
                hit[6] if hit else 0,
                now_iso,
            ))

    # 9. Layer-2: rule-level check_items & cross-version object_change_events (Delta only)
    def _short_val(val, limit=240) -> str:
        if val is None:
            return ''
        if isinstance(val, (dict, list)):
            s = json.dumps(val, ensure_ascii=False, sort_keys=True)
        else:
            s = str(val)
        return s[:limit]

    check_item_rows: list[tuple] = []
    change_event_rows: list[tuple] = []
    for chk_name, _mtime_ns, doc in valid_checks:
        bip = doc.get('business_ip') or ''
        rev = doc.get('revision') or ''
        run_at = doc.get('run_at') or ''
        baseline = doc.get('baseline')
        hit = latest_valid_check_by_scope.get((bip, rev))
        is_latest_chk = 1 if (hit and hit[1] == chk_name) else 0
        is_latest_rev = 1 if (rev and latest_rev_by_bip.get(bip) == rev) else 0

        for idx, item in enumerate(doc.get('checks') or []):
            if not isinstance(item, dict):
                continue
            check_item_rows.append((
                vendor, library, chk_name, idx, bip, rev, run_at,
                is_latest_chk, is_latest_rev,
                str(item.get('check_id') or ''),
                str(item.get('result') or 'INCONCLUSIVE'),
                str(item.get('coverage') or 'UNKNOWN'),
                item.get('severity'),
                len(item.get('scope_file_keys') or []),
                len(item.get('findings') or []),
                str(item.get('detail') or '')[:500],
            ))

        ev_idx = 0
        for chg in doc.get('changes') or []:
            if not isinstance(chg, dict):
                continue
            change_event_rows.append((
                vendor, library, chk_name, ev_idx, bip, rev, baseline, run_at,
                is_latest_chk, is_latest_rev,
                str(chg.get('view') or ''),
                str(chg.get('path') or ''),
                str(chg.get('baseline_version') or ''),
                str(chg.get('version') or ''),
                str(chg.get('object_type') or ''),
                str(chg.get('object_name') or ''),
                str(chg.get('attribute') or ''),
                _short_val(chg.get('old_value')),
                _short_val(chg.get('new_value')),
                chg.get('unit'),
            ))
            ev_idx += 1

        for pcmp in doc.get('partial_comparisons') or []:
            if not isinstance(pcmp, dict):
                continue
            p_view = str(pcmp.get('view') or '')
            p_path = str(pcmp.get('path') or '')
            p_bver = str(pcmp.get('baseline_version') or '')
            p_ver = str(pcmp.get('version') or '')
            p_otype = 'MODULE' if p_view == 'VERILOG' else ('SUBCKT' if p_view in ('CDL', 'SPICE') else 'OBJECT')
            diffs = pcmp.get('differences') or {}
            if not isinstance(diffs, dict):
                continue
            for kind, payload in diffs.items():
                if isinstance(payload, list):
                    for obj_name in payload:
                        change_event_rows.append((
                            vendor, library, chk_name, ev_idx, bip, rev, baseline, run_at,
                            is_latest_chk, is_latest_rev,
                            p_view, p_path, p_bver, p_ver,
                            p_otype, str(obj_name)[:200], str(kind).upper()[:64],
                            '', _short_val(obj_name), None,
                        ))
                        ev_idx += 1
                elif isinstance(payload, dict):
                    for obj_name, obj_diff in payload.items():
                        old_v = obj_diff.get('old') if isinstance(obj_diff, dict) else None
                        new_v = obj_diff.get('new') if isinstance(obj_diff, dict) else obj_diff
                        change_event_rows.append((
                            vendor, library, chk_name, ev_idx, bip, rev, baseline, run_at,
                            is_latest_chk, is_latest_rev,
                            p_view, p_path, p_bver, p_ver,
                            p_otype, str(obj_name)[:200], str(kind).upper()[:64],
                            _short_val(old_v), _short_val(new_v), None,
                        ))
                        ev_idx += 1

    # 10. Layer-2: effective_views (latest & accepted effective revisions ONLY; no RAW scan)
    def _corner_hint(view_name: str, fname: str) -> str:
        if view_name not in ('LIBERTY', 'DB'):
            return ''
        low = fname.lower()
        for suf in ('.lib.gz', '.db.gz', '.lib', '.db', '.gz'):
            if low.endswith(suf):
                low = low[: -len(suf)]
                break
        return low

    effective_view_rows: list[tuple] = []
    for (bip, rev), (is_lat, is_acc) in sorted(active_eff_scopes.items()):
        eff_p = eff_path_by_scope.get((bip, rev))
        if eff_p is None or not eff_p.is_file():
            continue
        try:
            eff_doc = read_json_readonly(eff_p)
        except (OSError, ValueError):
            continue
        views_map = eff_doc.get('views') if isinstance(eff_doc, dict) else None
        if not isinstance(views_map, dict):
            continue
        for view_name, ver_map in views_map.items():
            if not isinstance(ver_map, dict):
                continue
            v_str = str(view_name)
            for src_ver, paths_list in ver_map.items():
                if not isinstance(paths_list, list):
                    continue
                for rel_p in paths_list:
                    rel_s = str(rel_p)
                    fname = Path(rel_s).name
                    effective_view_rows.append((
                        vendor, library, bip, rev, v_str, rel_s,
                        is_lat, is_acc, str(src_ver), fname, _corner_hint(v_str, fname),
                    ))

    # 11. Layer-2: effective_objects (deduplicated Cell/Macro/Module/Subckt catalog for latest/accepted ONLY,
    #     strictly read from already-saved FileFacts pool blobs; zero RAW parsing, zero per-pin rows)
    from .facts_pool import hydrate_fact
    effective_object_rows: list[tuple] = []
    pool_cache: dict[str, dict] = {}
    for (bip, rev), (is_lat, is_acc) in sorted(active_eff_scopes.items()):
        latest_doc_hit = latest_valid_doc_by_scope.get((bip, rev))
        if latest_doc_hit is None:
            continue
        doc = latest_doc_hit[2]
        facts_evidence = doc.get('facts_evidence') or {}
        dedup_objs: dict[tuple[str, str, str], list] = {}
        seen_fact_refs: set[str] = set()
        for fentry in doc.get('files') or []:
            if not isinstance(fentry, dict) or fentry.get('status') != 'PARSED':
                continue
            fref = fentry.get('facts')
            if not fref or fref in seen_fact_refs:
                continue
            seen_fact_refs.add(fref)
            raw_fact = facts_evidence.get(fref) or facts_evidence.get(Path(str(fref)).name)
            fact_data = None
            if isinstance(raw_fact, dict):
                try:
                    fact_data = hydrate_fact(folder, raw_fact, pool_cache)
                except (OSError, ValueError, TypeError, KeyError):
                    fact_data = None
            else:
                fname_ref = Path(str(fref)).name
                for base in (folder / 'log', folder):
                    fp = base / fname_ref
                    if fp.is_file() and not fp.is_symlink() and fp.resolve().is_relative_to(folder.resolve()):
                        try:
                            fact_data = read_json_readonly(fp)
                        except (OSError, ValueError):
                            fact_data = None
                        break
            if not isinstance(fact_data, dict):
                continue
            f_view = str(fact_data.get('view') or fentry.get('view') or '')
            objs = fact_data.get('objects') or {}
            if not isinstance(objs, dict):
                continue
            extracted: list[tuple[str, str, int, float | None, float | None, float | None]] = []
            if f_view == 'LEF':
                for m in objs.get('macros') or []:
                    if not isinstance(m, dict) or not m.get('name'):
                        continue
                    sz = m.get('size_um')
                    w = float(sz[0]) if isinstance(sz, (list, tuple)) and len(sz) >= 2 else None
                    h = float(sz[1]) if isinstance(sz, (list, tuple)) and len(sz) >= 2 else None
                    area = round(w * h, 4) if (w is not None and h is not None) else None
                    extracted.append(('MACRO', str(m['name']), len(m.get('pins') or []), w, h, area))
            elif f_view == 'LIBERTY':
                for c in objs.get('cells') or []:
                    if not isinstance(c, dict) or not c.get('name'):
                        continue
                    extracted.append(('CELL', str(c['name']), len(c.get('pins') or []), None, None, None))
            elif f_view == 'VERILOG':
                for m in objs.get('modules') or []:
                    if not isinstance(m, dict) or not m.get('name'):
                        continue
                    ports = m.get('ports') or m.get('port_names') or []
                    extracted.append(('MODULE', str(m['name']), len(ports) if isinstance(ports, list) else 0, None, None, None))
            elif f_view in ('CDL', 'SPICE'):
                for s in objs.get('subcircuits') or []:
                    if not isinstance(s, dict) or not s.get('name'):
                        continue
                    ports = s.get('pins') or s.get('ports') or []
                    extracted.append(('SUBCKT', str(s['name']), len(ports) if isinstance(ports, list) else 0, None, None, None))

            for otype, oname, pcnt, w, h, area in extracted:
                ok = (f_view, otype, oname)
                prev_o = dedup_objs.get(ok)
                if prev_o is None:
                    dedup_objs[ok] = [pcnt, w, h, area, 1]
                else:
                    prev_o[4] += 1
                    if pcnt > prev_o[0]:
                        prev_o[0] = pcnt
                    if prev_o[1] is None and w is not None:
                        prev_o[1], prev_o[2], prev_o[3] = w, h, area

        for (f_view, otype, oname), vals in sorted(dedup_objs.items()):
            effective_object_rows.append((
                vendor, library, bip, rev, f_view, otype, oname,
                is_lat, is_acc, int(vals[0]), vals[1], vals[2], vals[3], int(vals[4]),
            ))

    lib_row = (
        vendor, library, ip_type,
        1 if is_multi_track else 0,
        json.dumps(ip_list, ensure_ascii=False),
        json.dumps(tracks_counts, ensure_ascii=False, sort_keys=True),
        len(deliv_files),
        len(formal_files),
        eff_count,
        latest_rev,
        accepted_rev,
        idx_state,
        refreshed_at,
        int(unadopted_count),
        int(needs_review_count),
        latest_lib_check[1] if latest_lib_check else None,
        latest_lib_check[2] if latest_lib_check else None,
        sig,
        now_iso,
    )

    return {
        'library_row': lib_row,
        'delivery_rows': delivery_rows,
        'revision_rows': revision_rows,
        'check_rows': check_rows,
        'artifact_rows': artifact_rows,
        'check_item_rows': check_item_rows,
        'change_event_rows': change_event_rows,
        'effective_view_rows': effective_view_rows,
        'effective_object_rows': effective_object_rows,
    }


def _delete_library_rows_tx(conn: sqlite3.Connection, vendor: str, library: str, *, include_library: bool = False) -> None:
    if include_library:
        conn.execute('DELETE FROM libraries WHERE vendor = ? AND library = ?', (vendor, library))
    for table in (
        'deliveries', 'revisions', 'checks', 'artifacts',
        'check_items', 'object_change_events', 'effective_views', 'effective_objects',
    ):
        conn.execute(f'DELETE FROM {table} WHERE vendor = ? AND library = ?', (vendor, library))


def _upsert_library_tx(conn: sqlite3.Connection, vendor: str, library: str, bundle: dict) -> None:
    _delete_library_rows_tx(conn, vendor, library, include_library=False)
    conn.execute(
        """INSERT OR REPLACE INTO libraries (
            vendor, library, ip_type, is_multi_track, ip_list_json, tracks_json,
            delivery_count, formal_count, revision_count, latest_revision, accepted_revision,
            index_status, index_refreshed_at, unadopted_count, needs_review_count,
            latest_check_quality, latest_check_at, folder_sig, updated_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        bundle['library_row'],
    )
    if bundle['delivery_rows']:
        conn.executemany(
            """INSERT OR REPLACE INTO deliveries (
                vendor, library, version, filename, version_date, directory_mtime,
                archived_at, archived_ts, delivery_at, delivery_ts, delivery_time_source,
                file_count, view_counts_json,
                is_new_library_ts, is_new_library_delivery_ts, track_ip, eff_state, eff_label
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            bundle['delivery_rows'],
        )
    if bundle['revision_rows']:
        conn.executemany(
            """INSERT OR REPLACE INTO revisions (
                vendor, library, business_ip, revision, is_latest, is_accepted,
                latest_check_name, latest_check_quality, latest_check_state,
                failed_checks, inconclusive_checks, failed_files, updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            bundle['revision_rows'],
        )
    if bundle['check_rows']:
        conn.executemany(
            """INSERT OR REPLACE INTO checks (
                vendor, library, check_name, business_ip, revision, baseline,
                run_id, run_at, state, quality_code, quality_text,
                failed_checks, inconclusive_checks, failed_files,
                is_corrupt, corrupt_reason, file_mtime_ns
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            bundle['check_rows'],
        )
    if bundle['artifact_rows']:
        conn.executemany(
            """INSERT OR REPLACE INTO artifacts (
                vendor, library, rel_path, layer, layer_label, category, filename,
                scope_label, sync_group, status_label, tag_cls, status_note, pointer_badge,
                updated_at, updated_ts, size_text, size_bytes, exists_flag, action_kind,
                revision, business_ip
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            bundle['artifact_rows'],
        )
    if bundle.get('check_item_rows'):
        conn.executemany(
            """INSERT OR REPLACE INTO check_items (
                vendor, library, check_name, item_idx, business_ip, revision, run_at,
                is_latest_check, is_latest_revision, check_id, result, coverage,
                severity, scope_files_count, findings_count, detail
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            bundle['check_item_rows'],
        )
    if bundle.get('change_event_rows'):
        conn.executemany(
            """INSERT OR REPLACE INTO object_change_events (
                vendor, library, check_name, event_idx, business_ip, revision, baseline, run_at,
                is_latest_check, is_latest_revision, view, file_path, baseline_version, version,
                object_type, object_name, change_kind, old_value, new_value, unit
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            bundle['change_event_rows'],
        )
    if bundle.get('effective_view_rows'):
        conn.executemany(
            """INSERT OR REPLACE INTO effective_views (
                vendor, library, business_ip, revision, view, file_path,
                is_latest, is_accepted, source_version, filename, corner_hint
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            bundle['effective_view_rows'],
        )
    if bundle.get('effective_object_rows'):
        conn.executemany(
            """INSERT OR REPLACE INTO effective_objects (
                vendor, library, business_ip, revision, view, object_type, object_name,
                is_latest, is_accepted, pin_count, width_um, height_um, area_um2, corner_file_count
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            bundle['effective_object_rows'],
        )


def _upsert_workspace_artifacts_tx(conn: sqlite3.Connection, work: Path) -> None:
    conn.execute("DELETE FROM artifacts WHERE vendor = '' AND library = ''")
    ws_rows = _collect_workspace_artifact_rows(work)
    if ws_rows:
        conn.executemany(
            """INSERT OR REPLACE INTO artifacts (
                vendor, library, rel_path, layer, layer_label, category, filename,
                scope_label, sync_group, status_label, tag_cls, status_note, pointer_badge,
                updated_at, updated_ts, size_text, size_bytes, exists_flag, action_kind,
                revision, business_ip
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            ws_rows,
        )


def rebuild_catalog(work, *, db_path: Path | None = None) -> dict:
    """Atomically rebuild the entire SQLite projection from immutable authoritative files."""
    root = Path(work).resolve()
    target = Path(db_path).resolve() if db_path is not None else catalog_db_path(root)
    if target.is_symlink() or target.parent.is_symlink():
        raise ValueError('Catalog 投影数据库路径不能为软链接')
    target.parent.mkdir(parents=True, exist_ok=True)

    libs = _iter_workspace_libraries(root)
    tmp_db = target.parent / f'.{target.name}.{uuid.uuid4().hex}.tmp'
    totals = {
        'libraries': 0,
        'deliveries': 0,
        'revisions': 0,
        'checks': 0,
        'corrupt_checks': 0,
        'artifacts': 0,
        'check_items': 0,
        'object_change_events': 0,
        'effective_views': 0,
        'effective_objects': 0,
    }
    try:
        conn = _connect(tmp_db, readonly=False)
        try:
            _init_schema(conn)
            with conn:
                work_cfg = _load_work_cfg_safe(root)
                discovery_map = load_delivery_discovery_times(root)
                _upsert_workspace_artifacts_tx(conn, root)
                for v, lib, folder in libs:
                    bundle = _collect_library_rows(root, v, lib, folder, work_cfg=work_cfg, discovery_map=discovery_map)
                    _upsert_library_tx(conn, v, lib, bundle)
                    totals['libraries'] += 1
                    totals['deliveries'] += len(bundle['delivery_rows'])
                    totals['revisions'] += len(bundle['revision_rows'])
                    totals['checks'] += len(bundle['check_rows'])
                    totals['corrupt_checks'] += sum(1 for r in bundle['check_rows'] if r[14] == 1)
                    totals['artifacts'] += len(bundle['artifact_rows'])
                    totals['check_items'] += len(bundle['check_item_rows'])
                    totals['object_change_events'] += len(bundle['change_event_rows'])
                    totals['effective_views'] += len(bundle['effective_view_rows'])
                    totals['effective_objects'] += len(bundle['effective_object_rows'])
                now_iso = utc_text()
                meta_rows = [
                    ('projection_version', PROJECTION_VERSION),
                    ('work_root', str(root)),
                    ('last_rebuild_at', now_iso),
                    ('config_sig', _config_sig(root)),
                    ('full_built', '1'),
                ]
                conn.executemany('INSERT OR REPLACE INTO catalog_meta (key, value) VALUES (?, ?)', meta_rows)
            try:
                conn.execute('PRAGMA wal_checkpoint(TRUNCATE)')
            except sqlite3.OperationalError:
                pass
        finally:
            conn.close()

        with locked(target.parent):
            for suffix in ('-wal', '-shm'):
                Path(str(target) + suffix).unlink(missing_ok=True)
                Path(str(tmp_db) + suffix).unlink(missing_ok=True)
            os.replace(tmp_db, target)
        invalidate_projection_freshness_cache(root)
    finally:
        for p in (tmp_db, Path(str(tmp_db) + '-wal'), Path(str(tmp_db) + '-shm')):
            p.unlink(missing_ok=True)

    return {
        'work': str(root),
        'db_path': str(target),
        'projection_version': PROJECTION_VERSION,
        'rebuilt_at': utc_text(),
        **totals,
    }


def sync_libraries_projection(
    work,
    pairs: list[tuple[str, str]],
    *,
    best_effort: bool = True,
) -> dict | None:
    """Incrementally upsert a batch of changed libraries in ONE lock & ONE SQLite transaction."""
    if not pairs or not catalog_enabled(work):
        return None
    unique_pairs = list(dict.fromkeys((str(v), str(lib)) for v, lib in pairs if v and lib))
    if not unique_pairs:
        return None
    try:
        root = Path(work).resolve()
        target = catalog_db_path(root)
        if not target.is_file():
            # Avoid silently creating a partial DB on write if a full projection hasn't been initialized yet;
            # explicit `catalog-rebuild` or `/api/v1/catalog/*` initializes the full projection cleanly.
            return None
        work_cfg = _load_work_cfg_safe(root)
        discovery_map = load_delivery_discovery_times(root)
        prepared: list[tuple[str, str, dict | None]] = []
        for vendor, library in unique_pairs:
            folder = library_folder(root, vendor, library)
            if not folder.is_dir() or folder.is_symlink():
                prepared.append((vendor, library, None))
            else:
                prepared.append((vendor, library, _collect_library_rows(root, vendor, library, folder, work_cfg=work_cfg, discovery_map=discovery_map)))

        with locked(target.parent):
            conn = _connect(target, readonly=False)
            try:
                meta = dict(conn.execute('SELECT key, value FROM catalog_meta').fetchall())
                if meta.get('projection_version') != PROJECTION_VERSION or meta.get('work_root') != str(root):
                    return None
                with conn:
                    for vendor, library, bundle in prepared:
                        if bundle is None:
                            _delete_library_rows_tx(conn, vendor, library, include_library=True)
                        else:
                            _upsert_library_tx(conn, vendor, library, bundle)
                    _upsert_workspace_artifacts_tx(conn, root)
                    conn.execute(
                        'INSERT OR REPLACE INTO catalog_meta (key, value) VALUES (?, ?)',
                        ('config_sig', _config_sig(root)),
                    )
            finally:
                conn.close()
        invalidate_projection_freshness_cache(root)
        return {'synced': True, 'count': len(prepared), 'libraries': unique_pairs, 'db_path': str(target)}
    except Exception:
        if best_effort:
            return None
        raise


def sync_library_projection(work, vendor: str, library: str, *, best_effort: bool = True) -> dict | None:
    """Incrementally upsert ONE library's derived projection rows after an authoritative commit."""
    res = sync_libraries_projection(work, [(vendor, library)], best_effort=best_effort)
    if res is None:
        return None
    return {'synced': True, 'vendor': vendor, 'library': library, 'db_path': res['db_path']}


def is_projection_fresh_readonly(work) -> bool:
    """Pure read-only check: True iff projection DB exists, matches schema/work_root, and all library sigs match."""
    if not catalog_enabled(work):
        return False
    root = Path(work).resolve()
    target = catalog_db_path(root)
    if not target.is_file() or target.is_symlink() or target.parent.is_symlink():
        return False
    try:
        conn = _connect(target, readonly=True)
        try:
            meta = dict(conn.execute('SELECT key, value FROM catalog_meta').fetchall())
            if (
                meta.get('projection_version') != PROJECTION_VERSION
                or meta.get('work_root') != str(root)
                or meta.get('full_built') != '1'
            ):
                return False
            stored_sigs = {
                (r['vendor'], r['library']): r['folder_sig']
                for r in conn.execute('SELECT vendor, library, folder_sig FROM libraries').fetchall()
            }
        finally:
            conn.close()
    except (sqlite3.Error, OSError, ValueError):
        return False

    current_libs = _iter_workspace_libraries(root)
    if len(current_libs) != len(stored_sigs):
        return False
    work_cfg = _load_work_cfg_safe(root)
    for v, lib, folder in current_libs:
        if stored_sigs.get((v, lib)) != _library_folder_sig(root, v, lib, folder, work_cfg=work_cfg):
            return False
    return True


def ensure_projection_fresh(work, *, check_sigs: bool = True, fresh_ttl_s: float = 0.0) -> Path | None:
    """Ensure SQLite projection exists, matches schema/work_root, and syncs any out-of-band changed libraries.

    When `fresh_ttl_s > 0`, recent verified checks (whose DB/WAL stat token hasn't changed) short-circuit
    without re-statting all library folders, eliminating repeated 7,500+ stat overhead during interactive search.
    """
    if not catalog_enabled(work):
        return None
    root = Path(work).resolve()
    if not root.is_dir():
        return None
    target = catalog_db_path(root)
    if target.is_symlink() or target.parent.is_symlink():
        return None
    if not target.is_file():
        rebuild_catalog(root, db_path=target)
        return target

    cache_key = (str(root), str(target))
    if check_sigs and fresh_ttl_s > 0:
        cur_db_tok = _db_stat_token(target)
        with _FRESHNESS_LOCK:
            cached = _FRESHNESS_CACHE.get(cache_key)
        if cached is not None and (time.monotonic() - cached[0]) <= fresh_ttl_s and cached[1] == cur_db_tok:
            return target

    try:
        conn = _connect(target, readonly=True)
        try:
            meta = dict(conn.execute('SELECT key, value FROM catalog_meta').fetchall())
            if (
                meta.get('projection_version') != PROJECTION_VERSION
                or meta.get('work_root') != str(root)
                or meta.get('full_built') != '1'
            ):
                needs_full = True
                stored_sigs = {}
            else:
                needs_full = False
                stored_sigs = {
                    (r['vendor'], r['library']): r['folder_sig']
                    for r in conn.execute('SELECT vendor, library, folder_sig FROM libraries').fetchall()
                }
        finally:
            conn.close()
    except (sqlite3.Error, OSError, ValueError):
        rebuild_catalog(root, db_path=target)
        return target

    if needs_full:
        rebuild_catalog(root, db_path=target)
        return target

    if not check_sigs:
        return target

    current_libs = _iter_workspace_libraries(root)
    current_map = {(v, lib): folder for v, lib, folder in current_libs}
    removed = [k for k in stored_sigs if k not in current_map]
    work_cfg = _load_work_cfg_safe(root)
    changed = []
    for key, folder in current_map.items():
        cur_sig = _library_folder_sig(root, key[0], key[1], folder, work_cfg=work_cfg)
        if stored_sigs.get(key) != cur_sig:
            changed.append((key[0], key[1], folder))

    cur_cfg_sig = _config_sig(root)
    cfg_changed = meta.get('config_sig') != cur_cfg_sig

    if not removed and not changed and not cfg_changed:
        if fresh_ttl_s > 0:
            with _FRESHNESS_LOCK:
                _FRESHNESS_CACHE[cache_key] = (time.monotonic(), _db_stat_token(target))
        return target

    try:
        with locked(target.parent):
            conn = _connect(target, readonly=False)
            try:
                with conn:
                    discovery_map = load_delivery_discovery_times(root) if changed else {}
                    for v, lib in removed:
                        _delete_library_rows_tx(conn, v, lib, include_library=True)
                    for v, lib, folder in changed:
                        bundle = _collect_library_rows(root, v, lib, folder, work_cfg=work_cfg, discovery_map=discovery_map)
                        _upsert_library_tx(conn, v, lib, bundle)
                    if cfg_changed or removed or changed:
                        _upsert_workspace_artifacts_tx(conn, root)
                        conn.execute(
                            'INSERT OR REPLACE INTO catalog_meta (key, value) VALUES (?, ?)',
                            ('config_sig', cur_cfg_sig),
                        )
            finally:
                conn.close()
    except (sqlite3.Error, OSError, ValueError):
        return None
    if fresh_ttl_s > 0:
        with _FRESHNESS_LOCK:
            _FRESHNESS_CACHE[cache_key] = (time.monotonic(), _db_stat_token(target))
    else:
        invalidate_projection_freshness_cache(root)
    return target


def query_catalog_refresh_status(work, *, limit: int = 10, ensure_fresh: bool = True) -> dict | None:
    """Fast SQLite-backed implementation matching `path_refresh.refresh_status()` contract."""
    from .path_refresh import read_refresh_history

    db = ensure_projection_fresh(work) if ensure_fresh else (catalog_db_path(work) if catalog_enabled(work) else None)
    if db is None or not db.is_file():
        return None
    root = Path(work)
    try:
        conn = _connect(db, readonly=True)
        try:
            rows = conn.execute('SELECT * FROM libraries ORDER BY vendor, library').fetchall()
        finally:
            conn.close()
    except (sqlite3.Error, OSError, ValueError):
        return None

    recent, last_by_layer, source_verifications, index_attempts = read_refresh_history(work, limit=limit)
    libraries = []
    fresh_count = stale_count = missing_count = with_effective = total_revisions = total_deliveries = total_unadopted = 0
    for r in rows:
        v, lib = r['vendor'], r['library']
        d_cnt, f_cnt, e_cnt = int(r['delivery_count']), int(r['formal_count']), int(r['revision_count'])
        total_deliveries += d_cnt
        total_revisions += e_cnt
        if e_cnt > 0:
            with_effective += 1
        idx_st = r['index_status']
        if idx_st == 'FRESH':
            fresh_count += 1
        elif idx_st == 'MISSING':
            missing_count += 1
        else:
            stale_count += 1
        unad = int(r['unadopted_count'])
        total_unadopted += unad
        item = {
            'vendor': v,
            'library': lib,
            'delivery_count': d_cnt,
            'formal_count': f_cnt,
            'revision_count': e_cnt,
            'latest_revision': r['latest_revision'],
            'accepted_revision': r['accepted_revision'],
            'index_status': idx_st,
            'index_refreshed_at': r['index_refreshed_at'],
            'source_verifications': source_verifications.get((v, lib), {}),
            'index_attempt': index_attempts.get((v, lib)),
            'unadopted_new_files_count': unad,
        }
        if r['ip_type'] is not None:
            item['ip_type'] = r['ip_type']
        if r['is_multi_track']:
            item['is_multi_track'] = True
            item['ip_list'] = json.loads(r['ip_list_json'] or '[]')
            item['tracks'] = json.loads(r['tracks_json'] or '{}')
            item['needs_review_count'] = int(r['needs_review_count'])
        libraries.append(item)

    return {
        'work': str(root),
        'totals': {
            'vendors': len({x['vendor'] for x in libraries}),
            'libraries': len(libraries),
            'deliveries': total_deliveries,
            'revisions': total_revisions,
            'libraries_with_effective': with_effective,
            'index_fresh': fresh_count,
            'index_stale_or_unverified': stale_count,
            'index_missing': missing_count,
            'unadopted_new_files': total_unadopted,
        },
        'last_by_layer': last_by_layer,
        'recent_runs': recent,
        'libraries': libraries,
    }


def query_catalog_activity_deliveries(
    work,
    *,
    days: int | None = 7,
    time_basis: str = 'archived',
    now=None,
    max_rows: int | None = 200,
    ensure_fresh: bool = True,
) -> dict | None:
    """Fast SQLite query for recent RAW deliveries + new-library counts (no 15,000-file stat/read loop)."""
    if time_basis not in ('archived', 'delivery'):
        raise ValueError("time_basis 必须是 'delivery' 或 'archived'")
    db = ensure_projection_fresh(work) if ensure_fresh else (catalog_db_path(work) if catalog_enabled(work) else None)
    if db is None or not db.is_file():
        return None
    now_dt = instant(now) if now is not None else datetime.now(timezone.utc)
    cutoff_ts = (now_dt - timedelta(days=days)).timestamp() if days is not None else None
    ts_col = 'delivery_ts' if time_basis == 'delivery' else 'archived_ts'
    new_lib_col = 'is_new_library_delivery_ts' if time_basis == 'delivery' else 'is_new_library_ts'
    try:
        conn = _connect(db, readonly=True)
        try:
            if cutoff_ts is not None:
                stats_row = conn.execute(
                    f"""SELECT COUNT(*) AS cnt,
                               COUNT(DISTINCT vendor || '/' || library) AS libs_touched,
                               COUNT(DISTINCT CASE WHEN {new_lib_col} >= ? THEN vendor || '/' || library END) AS new_libs,
                               SUM(CASE WHEN {new_lib_col} >= ? THEN 1 ELSE 0 END) AS new_lib_delivs
                        FROM deliveries WHERE {ts_col} >= ?""",
                    (cutoff_ts, cutoff_ts, cutoff_ts),
                ).fetchone()
                sql = f"""SELECT d.*, l.ip_type FROM deliveries d
                          LEFT JOIN libraries l ON d.vendor = l.vendor AND d.library = l.library
                          WHERE d.{ts_col} >= ?
                          ORDER BY d.{ts_col} DESC, d.vendor DESC, d.library DESC, d.version DESC"""
                params: list = [cutoff_ts]
            else:
                stats_row = conn.execute(
                    """SELECT COUNT(*) AS cnt,
                              COUNT(DISTINCT vendor || '/' || library) AS libs_touched,
                              0 AS new_libs,
                              0 AS new_lib_delivs
                       FROM deliveries""",
                ).fetchone()
                sql = f"""SELECT d.*, l.ip_type FROM deliveries d
                          LEFT JOIN libraries l ON d.vendor = l.vendor AND d.library = l.library
                          ORDER BY d.{ts_col} DESC, d.vendor DESC, d.library DESC, d.version DESC"""
                params = []
            if max_rows is not None:
                sql += ' LIMIT ?'
                params.append(int(max_rows))
            rows = conn.execute(sql, params).fetchall()
        finally:
            conn.close()
    except (sqlite3.Error, OSError, ValueError):
        return None

    total_cnt = int(stats_row['cnt']) if stats_row else 0
    new_lib_delivs = int(stats_row['new_lib_delivs'] or 0) if stats_row else 0
    raw_changes = []
    for r in rows:
        is_new_lib = bool(cutoff_ts is not None and float(r[new_lib_col]) >= cutoff_ts)
        deliv_at = r['delivery_at'] or r['archived_at']
        deliv_ts = float(r['delivery_ts']) if r['delivery_ts'] else float(r['archived_ts'])
        deliv_src = r['delivery_time_source'] or 'archived'
        event_at = deliv_at if time_basis == 'delivery' else r['archived_at']
        event_ts = deliv_ts if time_basis == 'delivery' else float(r['archived_ts'])
        event_src = deliv_src if time_basis == 'delivery' else 'archived'
        raw_changes.append({
            'vendor': r['vendor'],
            'library': r['library'],
            'ip_type': r['ip_type'],
            'track_ip': r['track_ip'],
            'is_new_library': is_new_lib,
            'change_badge': '新增库' if is_new_lib else '新增交付',
            'version': r['version'],
            'version_date': r['version_date'],
            'directory_mtime': r['directory_mtime'],
            'archived_at': r['archived_at'],
            'archived_ts': float(r['archived_ts']),
            'delivery_at': deliv_at,
            'delivery_ts': deliv_ts,
            'delivery_time_source': deliv_src,
            'event_at': event_at,
            'event_ts': event_ts,
            'event_time_source': event_src,
            'file_count': int(r['file_count']),
            'view_counts': json.loads(r['view_counts_json'] or '{}'),
            'eff_state': r['eff_state'],
            'eff_label': r['eff_label'],
        })
    return {
        'total_raw_deliveries': total_cnt,
        'new_libraries': int(stats_row['new_libs']) if stats_row else 0,
        'new_library_deliveries': new_lib_delivs,
        'existing_library_deliveries': max(0, total_cnt - new_lib_delivs),
        'raw_libraries_touched': int(stats_row['libs_touched']) if stats_row else 0,
        'raw_changes_truncated': bool(max_rows is not None and total_cnt > len(raw_changes)),
        'raw_changes': raw_changes,
    }


def query_catalog_json_inventory(
    work,
    *,
    include_workspace: bool = True,
    vendor: str | None = None,
    library: str | None = None,
    filters=None,
    page_size: int | None = None,
    ensure_fresh: bool = True,
) -> dict | None:
    """SQLite-indexed filter/sort/paginate over workspace or single-library JSON artifacts."""
    from .path_config import workbench_runtime_settings

    db = ensure_projection_fresh(work) if ensure_fresh else (catalog_db_path(work) if catalog_enabled(work) else None)
    if db is None or not db.is_file():
        return None

    root = Path(work)
    filters = filters or {}
    if page_size is None:
        try:
            page_size = workbench_runtime_settings(root)['json_inventory_page_size']
        except (OSError, ValueError, TypeError):
            page_size = 100
    page_size = max(1, min(500, int(page_size)))

    layer_f = (filters.get('json_layer') or '').strip().upper()
    if layer_f not in ('L1', 'L2', 'L3', 'WORKSPACE'):
        layer_f = ''
    status_f = (filters.get('json_status') or '').strip().lower()
    if status_f not in ('updated', 'issue', 'unchanged'):
        status_f = ''
    scope_f = (filters.get('json_scope') or filters.get('json_lib') or '').strip()
    q_raw = str(filters.get('json_q') or '').strip()
    q_f = q_raw.lower()
    sort_f = (filters.get('json_sort') or 'priority').strip().lower()
    if sort_f not in ('newest', 'layer', 'priority'):
        sort_f = 'priority'
    try:
        page = max(1, int(filters.get('json_page') or '1'))
    except (ValueError, TypeError):
        page = 1

    base_where = []
    base_params: list = []
    if vendor and library:
        base_where.append('vendor = ? AND library = ?')
        base_params.extend([vendor, library])
    elif not include_workspace:
        base_where.append("vendor != ''")

    where_all = 'WHERE ' + ' AND '.join(base_where) if base_where else ''

    filt_where = list(base_where)
    filt_params = list(base_params)
    if layer_f:
        filt_where.append('layer = ?')
        filt_params.append(layer_f)
    if status_f:
        filt_where.append('sync_group = ?')
        filt_params.append(status_f)
    if scope_f:
        if scope_f in ('__workspace__', '工作区全局'):
            filt_where.append("vendor = ''")
        elif '/' in scope_f:
            sv, sl = [x.strip() for x in scope_f.split('/', 1)]
            filt_where.append('vendor = ? AND library = ?')
            filt_params.extend([sv, sl])
        else:
            filt_where.append('library = ?')
            filt_params.append(scope_f)
    if q_f:
        like_pat = f'%{q_f}%'
        filt_where.append(
            '(LOWER(filename) LIKE ? OR LOWER(rel_path) LIKE ? OR LOWER(category) LIKE ? '
            'OR LOWER(scope_label) LIKE ? OR LOWER(status_label) LIKE ? OR LOWER(status_note) LIKE ?)'
        )
        filt_params.extend([like_pat] * 6)

    where_filt = 'WHERE ' + ' AND '.join(filt_where) if filt_where else ''
    order_map = {
        'newest': 'updated_ts DESC, rel_path ASC',
        'layer': "CASE layer WHEN 'L1' THEN 0 WHEN 'L2' THEN 1 WHEN 'L3' THEN 2 ELSE 3 END ASC, scope_label ASC, updated_ts DESC, rel_path ASC",
        'priority': "CASE sync_group WHEN 'updated' THEN 0 WHEN 'issue' THEN 1 ELSE 2 END ASC, updated_ts DESC, rel_path ASC",
    }
    order_sql = order_map.get(sort_f, order_map['priority'])

    try:
        conn = _connect(db, readonly=True)
        try:
            layer_counts = dict(
                conn.execute(f'SELECT layer, COUNT(*) FROM artifacts {where_all} GROUP BY layer', base_params).fetchall()
            )
            group_counts = dict(
                conn.execute(f'SELECT sync_group, COUNT(*) FROM artifacts {where_all} GROUP BY sync_group', base_params).fetchall()
            )
            total_all = sum(layer_counts.values())
            filtered_total = int(
                conn.execute(f'SELECT COUNT(*) FROM artifacts {where_filt}', filt_params).fetchone()[0]
            )
            total_pages = max(1, (filtered_total + page_size - 1) // page_size)
            page = min(page, total_pages)
            offset = (page - 1) * page_size
            rows = conn.execute(
                f'SELECT * FROM artifacts {where_filt} ORDER BY {order_sql} LIMIT ? OFFSET ?',
                [*filt_params, page_size, offset],
            ).fetchall()
        finally:
            conn.close()
    except (sqlite3.Error, OSError, ValueError):
        return None

    items = [
        {
            'layer': r['layer'],
            'layer_label': r['layer_label'],
            'category': r['category'],
            'filename': r['filename'],
            'rel_path': r['rel_path'],
            'vendor': r['vendor'],
            'library': r['library'],
            'scope_label': r['scope_label'],
            'sync_group': r['sync_group'],
            'status_label': r['status_label'],
            'tag_cls': r['tag_cls'],
            'status_note': r['status_note'],
            'pointer_badge': r['pointer_badge'],
            'updated_at': r['updated_at'],
            'updated_ts': float(r['updated_ts']),
            'size_text': r['size_text'],
            'size_bytes': int(r['size_bytes']),
            'exists': bool(r['exists_flag']),
            'action_kind': r['action_kind'],
            'revision': r['revision'] or None,
            'business_ip': r['business_ip'] or None,
        }
        for r in rows
    ]

    return {
        'rows': items,
        'counts': {
            'total': total_all,
            'L1': int(layer_counts.get('L1', 0)),
            'L2': int(layer_counts.get('L2', 0)),
            'L3': int(layer_counts.get('L3', 0)),
            'WORKSPACE': int(layer_counts.get('WORKSPACE', 0)),
            'updated': int(group_counts.get('updated', 0)),
            'issue': int(group_counts.get('issue', 0)),
            'unchanged': int(group_counts.get('unchanged', 0)),
        },
        'matched': filtered_total,
        'page': page,
        'pages': total_pages,
        'page_size': page_size,
        'query': {
            'json_layer': layer_f,
            'json_status': status_f,
            'json_scope': scope_f,
            'json_q': q_raw,
            'json_sort': sort_f,
        },
        'backend': 'sqlite',
    }


def query_catalog_checks(
    work,
    *,
    vendor: str | None = None,
    library: str | None = None,
    business_ip: str | None = None,
    quality: str | None = None,
    ip_type: str | None = None,
    q: str | None = None,
    include_corrupt: bool = True,
    limit: int = 100,
    offset: int = 0,
    ensure_fresh: bool = True,
    fresh_ttl_s: float = 0.0,
) -> dict:
    """Cross-workspace SQL query over all saved CheckResult metadata (including FAIL & CORRUPT filters)."""
    db = ensure_projection_fresh(work, fresh_ttl_s=fresh_ttl_s) if ensure_fresh else (catalog_db_path(work) if catalog_enabled(work) else None)
    if db is None or not db.is_file():
        return {'work': str(Path(work).resolve()), 'backend': 'disabled', 'total': 0, 'counts_by_quality': {}, 'items': []}

    where = []
    params: list = []
    if vendor:
        where.append('c.vendor = ?')
        params.append(vendor)
    if library:
        where.append('c.library = ?')
        params.append(library)
    if business_ip is not None:
        where.append('c.business_ip = ?')
        params.append(business_ip)
    if quality:
        where.append('c.quality_code = ?')
        params.append(quality.upper())
    if ip_type:
        where.append('l.ip_type = ?')
        params.append(ip_type)
    if not include_corrupt:
        where.append('c.is_corrupt = 0')
    if q:
        pat = f'%{q.strip().lower()}%'
        where.append('(LOWER(c.vendor) LIKE ? OR LOWER(c.library) LIKE ? OR LOWER(c.revision) LIKE ? OR LOWER(c.check_name) LIKE ?)')
        params.extend([pat] * 4)

    where_sql = 'WHERE ' + ' AND '.join(where) if where else ''
    limit = max(1, min(500, int(limit)))
    offset = max(0, int(offset))

    conn = _connect(db, readonly=True)
    try:
        counts_by_quality = dict(
            conn.execute(
                f'SELECT c.quality_code, COUNT(*) FROM checks c LEFT JOIN libraries l ON c.vendor=l.vendor AND c.library=l.library {where_sql} GROUP BY c.quality_code',
                params,
            ).fetchall()
        )
        total = sum(counts_by_quality.values())
        rows = conn.execute(
            f"""SELECT c.*, l.ip_type FROM checks c
                LEFT JOIN libraries l ON c.vendor = l.vendor AND c.library = l.library
                {where_sql}
                ORDER BY c.file_mtime_ns DESC, c.vendor ASC, c.library ASC
                LIMIT ? OFFSET ?""",
            [*params, limit, offset],
        ).fetchall()
    finally:
        conn.close()

    return {
        'work': str(Path(work).resolve()),
        'backend': 'sqlite',
        'db_path': str(db),
        'total': total,
        'counts_by_quality': counts_by_quality,
        'limit': limit,
        'offset': offset,
        'items': [
            {
                'vendor': r['vendor'],
                'library': r['library'],
                'ip_type': r['ip_type'],
                'business_ip': r['business_ip'] or None,
                'check_name': r['check_name'],
                'revision': r['revision'],
                'baseline': r['baseline'],
                'run_id': r['run_id'],
                'run_at': r['run_at'],
                'state': r['state'],
                'quality_code': r['quality_code'],
                'quality_text': r['quality_text'],
                'failed_checks': int(r['failed_checks']),
                'inconclusive_checks': int(r['inconclusive_checks']),
                'failed_files': int(r['failed_files']),
                'is_corrupt': bool(r['is_corrupt']),
                'corrupt_reason': r['corrupt_reason'],
            }
            for r in rows
        ],
    }


def query_catalog_summary(work, *, ensure_fresh: bool = True, fresh_ttl_s: float = 0.0) -> dict:
    """Fast workspace-wide quality & asset dashboard aggregated directly via SQL."""
    db = ensure_projection_fresh(work, fresh_ttl_s=fresh_ttl_s) if ensure_fresh else (catalog_db_path(work) if catalog_enabled(work) else None)
    if db is None or not db.is_file():
        return {'work': str(Path(work).resolve()), 'backend': 'disabled'}
    conn = _connect(db, readonly=True)
    try:
        meta = dict(conn.execute('SELECT key, value FROM catalog_meta').fetchall())
        lib_tot = conn.execute(
            """SELECT COUNT(*) AS libraries,
                      COUNT(DISTINCT vendor) AS vendors,
                      COALESCE(SUM(delivery_count), 0) AS deliveries,
                      COALESCE(SUM(formal_count), 0) AS formals,
                      COALESCE(SUM(revision_count), 0) AS revisions,
                      SUM(CASE WHEN revision_count > 0 THEN 1 ELSE 0 END) AS with_effective,
                      SUM(CASE WHEN accepted_revision IS NOT NULL THEN 1 ELSE 0 END) AS accepted,
                      SUM(CASE WHEN index_status = 'FRESH' THEN 1 ELSE 0 END) AS index_fresh,
                      SUM(CASE WHEN index_status != 'FRESH' THEN 1 ELSE 0 END) AS index_issues,
                      COALESCE(SUM(needs_review_count), 0) AS needs_review_total
               FROM libraries"""
        ).fetchone()
        by_ip_type = [
            dict(r) for r in conn.execute(
                """SELECT COALESCE(ip_type, 'UNCLASSIFIED') AS ip_type,
                          COUNT(*) AS libraries,
                          COALESCE(SUM(revision_count), 0) AS revisions,
                          SUM(CASE WHEN latest_check_quality = 'FAIL' THEN 1 ELSE 0 END) AS fail_libs,
                          SUM(CASE WHEN latest_check_quality = 'SCOPE_PASS' THEN 1 ELSE 0 END) AS pass_libs
                   FROM libraries GROUP BY COALESCE(ip_type, 'UNCLASSIFIED') ORDER BY libraries DESC"""
            ).fetchall()
        ]
        chk_counts = dict(
            conn.execute('SELECT quality_code, COUNT(*) FROM checks GROUP BY quality_code').fetchall()
        )
        by_check_id = [
            {
                'check_id': r['check_id'],
                'total': int(r['total']),
                'pass_count': int(r['pass_count']),
                'fail_count': int(r['fail_count']),
                'inconclusive_count': int(r['inconclusive_count']),
                'fail_libraries': int(r['fail_libraries']),
            }
            for r in conn.execute(
                """SELECT check_id,
                          COUNT(*) AS total,
                          SUM(CASE WHEN result = 'PASS' THEN 1 ELSE 0 END) AS pass_count,
                          SUM(CASE WHEN result = 'FAIL' THEN 1 ELSE 0 END) AS fail_count,
                          SUM(CASE WHEN result = 'INCONCLUSIVE' THEN 1 ELSE 0 END) AS inconclusive_count,
                          COUNT(DISTINCT CASE WHEN result = 'FAIL' THEN vendor || '/' || library END) AS fail_libraries
                   FROM check_items
                   WHERE is_latest_check = 1 AND is_latest_revision = 1
                   GROUP BY check_id
                   ORDER BY fail_count DESC, inconclusive_count DESC, check_id ASC"""
            ).fetchall()
        ]
        l2_counts = {
            'check_items': int(conn.execute('SELECT COUNT(*) FROM check_items').fetchone()[0]),
            'object_change_events': int(conn.execute('SELECT COUNT(*) FROM object_change_events').fetchone()[0]),
            'effective_views': int(conn.execute('SELECT COUNT(*) FROM effective_views').fetchone()[0]),
            'effective_objects': int(conn.execute('SELECT COUNT(*) FROM effective_objects').fetchone()[0]),
        }
    finally:
        conn.close()
    return {
        'work': str(Path(work).resolve()),
        'backend': 'sqlite',
        'db_path': str(db),
        'projection_version': meta.get('projection_version'),
        'last_rebuild_at': meta.get('last_rebuild_at'),
        'totals': {**({k: int(lib_tot[k] or 0) for k in lib_tot.keys()} if lib_tot else {}), **l2_counts},
        'checks_by_quality': chk_counts,
        'by_check_id': by_check_id,
        'by_ip_type': by_ip_type,
    }


def query_catalog_check_items(
    work,
    *,
    check_id: str | None = None,
    result: str | None = None,
    vendor: str | None = None,
    library: str | None = None,
    business_ip: str | None = None,
    latest_only: bool = True,
    q: str | None = None,
    limit: int = 100,
    offset: int = 0,
    ensure_fresh: bool = True,
    fresh_ttl_s: float = 0.0,
) -> dict:
    """Layer-2 cross-workspace SQL query by check rule (check_id / result) with rule-level scoreboard."""
    db = ensure_projection_fresh(work, fresh_ttl_s=fresh_ttl_s) if ensure_fresh else (catalog_db_path(work) if catalog_enabled(work) else None)
    if db is None or not db.is_file():
        return {'work': str(Path(work).resolve()), 'backend': 'disabled', 'total': 0, 'by_check_id': [], 'items': []}

    where = []
    params: list = []
    if latest_only:
        where.append('ci.is_latest_check = 1 AND ci.is_latest_revision = 1')
    if check_id:
        where.append('ci.check_id = ?')
        params.append(check_id.strip())
    if result:
        where.append('ci.result = ?')
        params.append(result.strip().upper())
    if vendor:
        where.append('ci.vendor = ?')
        params.append(vendor)
    if library:
        where.append('ci.library = ?')
        params.append(library)
    if business_ip is not None:
        where.append('ci.business_ip = ?')
        params.append(business_ip)
    if q:
        pat = f'%{q.strip().lower()}%'
        where.append('(LOWER(ci.check_id) LIKE ? OR LOWER(ci.library) LIKE ? OR LOWER(ci.detail) LIKE ?)')
        params.extend([pat] * 3)

    where_sql = 'WHERE ' + ' AND '.join(where) if where else ''
    limit = max(1, min(500, int(limit)))
    offset = max(0, int(offset))

    conn = _connect(db, readonly=True)
    try:
        scoreboard = [
            {
                'check_id': r['check_id'],
                'total': int(r['total']),
                'pass_count': int(r['pass_count']),
                'fail_count': int(r['fail_count']),
                'inconclusive_count': int(r['inconclusive_count']),
                'fail_libraries': int(r['fail_libraries']),
            }
            for r in conn.execute(
                f"""SELECT ci.check_id,
                           COUNT(*) AS total,
                           SUM(CASE WHEN ci.result = 'PASS' THEN 1 ELSE 0 END) AS pass_count,
                           SUM(CASE WHEN ci.result = 'FAIL' THEN 1 ELSE 0 END) AS fail_count,
                           SUM(CASE WHEN ci.result = 'INCONCLUSIVE' THEN 1 ELSE 0 END) AS inconclusive_count,
                           COUNT(DISTINCT CASE WHEN ci.result = 'FAIL' THEN ci.vendor || '/' || ci.library END) AS fail_libraries
                    FROM check_items ci {where_sql}
                    GROUP BY ci.check_id
                    ORDER BY fail_count DESC, inconclusive_count DESC, ci.check_id ASC""",
                params,
            ).fetchall()
        ]
        total = sum(x['total'] for x in scoreboard)
        rows = conn.execute(
            f"""SELECT ci.*, l.ip_type
                FROM check_items ci
                LEFT JOIN libraries l ON ci.vendor = l.vendor AND ci.library = l.library
                {where_sql}
                ORDER BY CASE ci.result WHEN 'FAIL' THEN 0 WHEN 'INCONCLUSIVE' THEN 1 ELSE 2 END,
                         ci.run_at DESC, ci.vendor ASC, ci.library ASC, ci.item_idx ASC
                LIMIT ? OFFSET ?""",
            [*params, limit, offset],
        ).fetchall()
    finally:
        conn.close()

    return {
        'work': str(Path(work).resolve()),
        'backend': 'sqlite',
        'db_path': str(db),
        'latest_only': bool(latest_only),
        'total': total,
        'by_check_id': scoreboard,
        'limit': limit,
        'offset': offset,
        'items': [
            {
                'vendor': r['vendor'],
                'library': r['library'],
                'ip_type': r['ip_type'],
                'business_ip': r['business_ip'] or None,
                'revision': r['revision'],
                'check_name': r['check_name'],
                'run_at': r['run_at'],
                'check_id': r['check_id'],
                'result': r['result'],
                'coverage': r['coverage'],
                'severity': r['severity'],
                'scope_files_count': int(r['scope_files_count']),
                'findings_count': int(r['findings_count']),
                'detail': r['detail'],
                'is_latest_check': bool(r['is_latest_check']),
                'is_latest_revision': bool(r['is_latest_revision']),
            }
            for r in rows
        ],
    }


def query_catalog_object_changes(
    work,
    *,
    object_name: str | None = None,
    change_kind: str | None = None,
    view: str | None = None,
    vendor: str | None = None,
    library: str | None = None,
    business_ip: str | None = None,
    latest_only: bool = True,
    limit: int = 100,
    offset: int = 0,
    ensure_fresh: bool = True,
    fresh_ttl_s: float = 0.0,
) -> dict:
    """Layer-2 cross-workspace SQL query over cross-revision object change Deltas (SIZE, PIN, MODULE/SUBCKT)."""
    db = ensure_projection_fresh(work, fresh_ttl_s=fresh_ttl_s) if ensure_fresh else (catalog_db_path(work) if catalog_enabled(work) else None)
    if db is None or not db.is_file():
        return {'work': str(Path(work).resolve()), 'backend': 'disabled', 'total': 0, 'counts_by_kind': {}, 'items': []}

    where = []
    params: list = []
    if latest_only:
        where.append('e.is_latest_check = 1')
    if object_name:
        where.append('LOWER(e.object_name) LIKE ?')
        params.append(f'%{object_name.strip().lower()}%')
    if change_kind:
        where.append('UPPER(e.change_kind) = ?')
        params.append(change_kind.strip().upper())
    if view:
        where.append('UPPER(e.view) = ?')
        params.append(view.strip().upper())
    if vendor:
        where.append('e.vendor = ?')
        params.append(vendor)
    if library:
        where.append('e.library = ?')
        params.append(library)
    if business_ip is not None:
        where.append('e.business_ip = ?')
        params.append(business_ip)

    where_sql = 'WHERE ' + ' AND '.join(where) if where else ''
    limit = max(1, min(500, int(limit)))
    offset = max(0, int(offset))

    conn = _connect(db, readonly=True)
    try:
        counts_by_kind = dict(
            conn.execute(
                f'SELECT e.change_kind, COUNT(*) FROM object_change_events e {where_sql} GROUP BY e.change_kind',
                params,
            ).fetchall()
        )
        total = sum(counts_by_kind.values())
        rows = conn.execute(
            f"""SELECT e.*, l.ip_type
                FROM object_change_events e
                LEFT JOIN libraries l ON e.vendor = l.vendor AND e.library = l.library
                {where_sql}
                ORDER BY e.run_at DESC, e.vendor ASC, e.library ASC, e.revision DESC, e.event_idx ASC
                LIMIT ? OFFSET ?""",
            [*params, limit, offset],
        ).fetchall()
    finally:
        conn.close()

    return {
        'work': str(Path(work).resolve()),
        'backend': 'sqlite',
        'db_path': str(db),
        'latest_only': bool(latest_only),
        'total': total,
        'counts_by_kind': counts_by_kind,
        'limit': limit,
        'offset': offset,
        'items': [
            {
                'vendor': r['vendor'],
                'library': r['library'],
                'ip_type': r['ip_type'],
                'business_ip': r['business_ip'] or None,
                'revision': r['revision'],
                'baseline': r['baseline'],
                'check_name': r['check_name'],
                'run_at': r['run_at'],
                'view': r['view'],
                'file_path': r['file_path'],
                'baseline_version': r['baseline_version'],
                'version': r['version'],
                'object_type': r['object_type'],
                'object_name': r['object_name'],
                'change_kind': r['change_kind'],
                'old_value': r['old_value'],
                'new_value': r['new_value'],
                'unit': r['unit'],
                'is_latest_revision': bool(r['is_latest_revision']),
            }
            for r in rows
        ],
    }


def query_catalog_objects(
    work,
    *,
    q: str | None = None,
    object_type: str | None = None,
    view: str | None = None,
    vendor: str | None = None,
    library: str | None = None,
    business_ip: str | None = None,
    latest_only: bool = True,
    limit: int = 100,
    offset: int = 0,
    ensure_fresh: bool = True,
    fresh_ttl_s: float = 0.0,
) -> dict:
    """Layer-2 global Cell / Macro / Module / Subckt catalog search (deduplicated; no per-pin rows)."""
    db = ensure_projection_fresh(work, fresh_ttl_s=fresh_ttl_s) if ensure_fresh else (catalog_db_path(work) if catalog_enabled(work) else None)
    if db is None or not db.is_file():
        return {'work': str(Path(work).resolve()), 'backend': 'disabled', 'total': 0, 'counts_by_type': {}, 'items': []}

    where = []
    params: list = []
    if latest_only:
        where.append('o.is_latest = 1')
    if q:
        pat = f'%{q.strip().lower()}%'
        where.append('(LOWER(o.object_name) LIKE ? OR LOWER(o.library) LIKE ? OR LOWER(o.vendor) LIKE ?)')
        params.extend([pat] * 3)
    if object_type:
        where.append('UPPER(o.object_type) = ?')
        params.append(object_type.strip().upper())
    if view:
        where.append('UPPER(o.view) = ?')
        params.append(view.strip().upper())
    if vendor:
        where.append('o.vendor = ?')
        params.append(vendor)
    if library:
        where.append('o.library = ?')
        params.append(library)
    if business_ip is not None:
        where.append('o.business_ip = ?')
        params.append(business_ip)

    where_sql = 'WHERE ' + ' AND '.join(where) if where else ''
    limit = max(1, min(500, int(limit)))
    offset = max(0, int(offset))

    conn = _connect(db, readonly=True)
    try:
        counts_by_type = dict(
            conn.execute(
                f'SELECT o.object_type, COUNT(*) FROM effective_objects o {where_sql} GROUP BY o.object_type',
                params,
            ).fetchall()
        )
        total = sum(counts_by_type.values())
        rows = conn.execute(
            f"""SELECT o.*, l.ip_type
                FROM effective_objects o
                LEFT JOIN libraries l ON o.vendor = l.vendor AND o.library = l.library
                {where_sql}
                ORDER BY o.object_name ASC, o.vendor ASC, o.library ASC, o.view ASC
                LIMIT ? OFFSET ?""",
            [*params, limit, offset],
        ).fetchall()
    finally:
        conn.close()

    return {
        'work': str(Path(work).resolve()),
        'backend': 'sqlite',
        'db_path': str(db),
        'latest_only': bool(latest_only),
        'total': total,
        'counts_by_type': counts_by_type,
        'limit': limit,
        'offset': offset,
        'items': [
            {
                'vendor': r['vendor'],
                'library': r['library'],
                'ip_type': r['ip_type'],
                'business_ip': r['business_ip'] or None,
                'revision': r['revision'],
                'view': r['view'],
                'object_type': r['object_type'],
                'object_name': r['object_name'],
                'is_latest': bool(r['is_latest']),
                'is_accepted': bool(r['is_accepted']),
                'pin_count': int(r['pin_count']),
                'width_um': r['width_um'],
                'height_um': r['height_um'],
                'area_um2': r['area_um2'],
                'corner_file_count': int(r['corner_file_count']),
            }
            for r in rows
        ],
    }


def query_catalog_corners(
    work,
    *,
    q: str | None = None,
    view: str | None = None,
    vendor: str | None = None,
    library: str | None = None,
    business_ip: str | None = None,
    latest_only: bool = True,
    limit: int = 100,
    offset: int = 0,
    ensure_fresh: bool = True,
    fresh_ttl_s: float = 0.0,
) -> dict:
    """Layer-2 global View / Corner file index across latest & accepted effective revisions."""
    db = ensure_projection_fresh(work, fresh_ttl_s=fresh_ttl_s) if ensure_fresh else (catalog_db_path(work) if catalog_enabled(work) else None)
    if db is None or not db.is_file():
        return {'work': str(Path(work).resolve()), 'backend': 'disabled', 'total': 0, 'counts_by_view': {}, 'items': []}

    where = []
    params: list = []
    if latest_only:
        where.append('ev.is_latest = 1')
    if view:
        where.append('UPPER(ev.view) = ?')
        params.append(view.strip().upper())
    if vendor:
        where.append('ev.vendor = ?')
        params.append(vendor)
    if library:
        where.append('ev.library = ?')
        params.append(library)
    if business_ip is not None:
        where.append('ev.business_ip = ?')
        params.append(business_ip)
    if q:
        # Support `+` AND tokens like `ss+125c` as well as plain substring match
        tokens = [tok.strip().lower() for tok in q.split('+') if tok.strip()]
        for tok in tokens:
            pat = f'%{tok}%'
            where.append('(ev.corner_hint LIKE ? OR LOWER(ev.filename) LIKE ? OR LOWER(ev.file_path) LIKE ?)')
            params.extend([pat] * 3)

    where_sql = 'WHERE ' + ' AND '.join(where) if where else ''
    limit = max(1, min(500, int(limit)))
    offset = max(0, int(offset))

    conn = _connect(db, readonly=True)
    try:
        counts_by_view = dict(
            conn.execute(
                f'SELECT ev.view, COUNT(*) FROM effective_views ev {where_sql} GROUP BY ev.view',
                params,
            ).fetchall()
        )
        total = sum(counts_by_view.values())
        rows = conn.execute(
            f"""SELECT ev.*, l.ip_type
                FROM effective_views ev
                LEFT JOIN libraries l ON ev.vendor = l.vendor AND ev.library = l.library
                {where_sql}
                ORDER BY ev.vendor ASC, ev.library ASC, ev.view ASC, ev.filename ASC
                LIMIT ? OFFSET ?""",
            [*params, limit, offset],
        ).fetchall()
    finally:
        conn.close()

    return {
        'work': str(Path(work).resolve()),
        'backend': 'sqlite',
        'db_path': str(db),
        'latest_only': bool(latest_only),
        'total': total,
        'counts_by_view': counts_by_view,
        'limit': limit,
        'offset': offset,
        'items': [
            {
                'vendor': r['vendor'],
                'library': r['library'],
                'ip_type': r['ip_type'],
                'business_ip': r['business_ip'] or None,
                'revision': r['revision'],
                'view': r['view'],
                'file_path': r['file_path'],
                'filename': r['filename'],
                'corner_hint': r['corner_hint'] or None,
                'source_version': r['source_version'],
                'is_latest': bool(r['is_latest']),
                'is_accepted': bool(r['is_accepted']),
            }
            for r in rows
        ],
    }
