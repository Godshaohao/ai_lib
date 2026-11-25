"""Two-stage business IP partitioning engine with incremental human-decision preservation."""
from contextlib import nullcontext
import json
from pathlib import Path

from ai_lib_qor.sources.layout import SAFE, library_folder
from ai_lib_qor.sources.timestamps import utc_text
from ai_lib_qor.versions.store import locked, validate, write_atomic
from .path_config import excluded_versions, library_ip_config

CORE_EDA_EXTENSIONS = frozenset({'.lef', '.lib', '.db', '.v', '.cdl'})


def track_id_for(vendor: str, library: str, business_ip: str) -> str:
    return f'{vendor}/{library}::{business_ip}'


def legacy_partition_path(work, library: str) -> Path:
    """Legacy workspace-root partition path `work/ip_partition_<lib>.json` (read-only fallback)."""
    if not isinstance(library, str) or not SAFE.fullmatch(library) or library in ('.', '..'):
        raise ValueError(f'库标识不安全: {library}')
    root = Path(work).resolve(strict=True)
    path = root / f'ip_partition_{library}.json'
    if path.is_symlink():
        raise ValueError(f'分轨配置文件不能为软链接: {path.name}')
    return path


def partition_path(work, vendor: str, library: str | None = None) -> Path:
    """Canonical per-(vendor, library) partition path `work/libraries/<vendor>/<library>/ip_partition.json`.

    Backward-compatibility: if called with 2 arguments `partition_path(work, library)`,
    returns the legacy path `work/ip_partition_<library>.json`.
    """
    if library is None:
        return legacy_partition_path(work, vendor)
    root = Path(work).resolve(strict=True)
    folder = library_folder(root, vendor, library)
    path = folder / 'ip_partition.json'
    if path.is_symlink():
        raise ValueError(f'分轨配置文件不能为软链接: {vendor}/{library}/ip_partition.json')
    return path


def resolve_existing_partition_path(work, vendor: str, library: str) -> tuple[Path | None, bool]:
    """Resolve active partition file: canonical per-library file first, then vendor-matched legacy fallback.

    Returns `(path, is_legacy)`. If a legacy `work/ip_partition_<lib>.json` exists but declares a
    different `vendor`, it is NOT claimed by this library (preventing cross-vendor collisions).
    """
    canonical = partition_path(work, vendor, library)
    if canonical.is_file():
        return canonical, False

    legacy = legacy_partition_path(work, library)
    if not legacy.is_file():
        return None, False

    try:
        raw = json.loads(legacy.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        # Preserve malformed JSON error reporting on load_partition rather than silently hiding it
        return legacy, True

    if isinstance(raw, dict):
        stored_vendor = raw.get('vendor')
        if stored_vendor is not None and stored_vendor != vendor:
            # Legacy file belongs to another vendor with the same library name; do not collide or claim it.
            return None, False
    return legacy, True


def _validate_partition_payload(data, *, vendor: str, library: str, path_name: str) -> dict:
    if not isinstance(data, dict):
        raise ValueError(f'分轨配置格式无效 ({path_name})')
    stored_vendor = data.get('vendor')
    stored_library = data.get('library')
    if stored_vendor is not None and stored_vendor != vendor:
        raise ValueError(
            f'分轨配置文件 {path_name} 属于供应商 {stored_vendor}，与当前供应商 {vendor} 冲突（禁止跨供应商覆写）'
        )
    if stored_library is not None and stored_library != library:
        raise ValueError(f'分轨配置文件 {path_name} 属于库 {stored_library}，与当前库 {library} 不一致')

    raw_tracks = data.get('tracks')
    if raw_tracks is None:
        raw_tracks = {}
    if not isinstance(raw_tracks, dict):
        raise ValueError(f'分轨配置 tracks 必须为对象 ({path_name})')

    tracks: dict[str, list[str]] = {}
    seen_versions: dict[str, str] = {}
    for ip, versions in raw_tracks.items():
        if not isinstance(ip, str) or not SAFE.fullmatch(ip) or '__' in ip:
            raise ValueError(f'分轨配置包含无效业务 IP 名称: {ip}')
        if not isinstance(versions, list) or any(not isinstance(v, str) or not v.strip() for v in versions):
            raise ValueError(f'分轨配置轨道 {ip} 的版本列表无效')
        clean_list: list[str] = []
        for ver in versions:
            ver_s = ver.strip()
            if ver_s in seen_versions:
                prev_ip = seen_versions[ver_s]
                if prev_ip == ip:
                    raise ValueError(f'分轨配置轨道 {ip} 包含重复版本: {ver_s}')
                raise ValueError(f'版本 {ver_s} 同时出现在多个轨道中 ({prev_ip}, {ip})，请先人工修正')
            seen_versions[ver_s] = ip
            clean_list.append(ver_s)
        tracks[ip] = clean_list

    raw_trace = data.get('auto_trace')
    auto_trace = dict(raw_trace) if isinstance(raw_trace, dict) else {}

    raw_review = data.get('needs_review')
    if isinstance(raw_review, dict):
        conflicts = list(raw_review.get('conflicts') or [])
        unassigned = list(raw_review.get('unassigned') or [])
    else:
        conflicts = []
        unassigned = []

    return {
        'schema_version': data.get('schema_version') or 'ip_partition.v1',
        'vendor': vendor,
        'library': library,
        'ip_type': data.get('ip_type'),
        'ip_list': list(data.get('ip_list') or []),
        'tracks': tracks,
        'needs_review': {'conflicts': conflicts, 'unassigned': unassigned},
        'auto_trace': auto_trace,
        'updated_at': data.get('updated_at'),
    }


def load_partition(work, vendor: str, library: str) -> dict | None:
    """Read and validate per-library `ip_partition.json` (with vendor-matched legacy fallback)."""
    from ai_lib_qor.versions.store import read_json_readonly
    path, _ = resolve_existing_partition_path(work, vendor, library)
    if path is None:
        return None
    raw = read_json_readonly(path, 'ip_partition')
    return _validate_partition_payload(raw, vendor=vendor, library=library, path_name=path.name)


def save_partition_payload(work, vendor: str, library: str, payload: dict) -> Path:
    """Validate against ip_partition JSON Schema and write atomically to canonical per-library path."""
    path = partition_path(work, vendor, library)
    validate(payload, 'ip_partition')
    write_atomic(path, payload)
    return path


def match_ips_in_text(text: str, ip_list: list[str]) -> list[str]:
    """Longest-name-first case-insensitive substring matching with span subsumption.

    If a longer IP name matches span [s, e), a shorter IP whose match falls inside [s, e)
    is subsumed rather than treated as a conflict. Only independent non-subsumed matches
    produce multiple hits.
    """
    if not text or not ip_list:
        return []
    hay = text.casefold()
    ordered_ips = sorted(ip_list, key=lambda item: (-len(item), item))
    occupied: list[tuple[int, int]] = []
    matched: list[str] = []

    for ip in ordered_ips:
        needle = ip.casefold()
        if not needle:
            continue
        new_spans: list[tuple[int, int]] = []
        pos = 0
        while True:
            idx = hay.find(needle, pos)
            if idx < 0:
                break
            span = (idx, idx + len(needle))
            subsumed = any(os_ <= span[0] and span[1] <= oe_ for os_, oe_ in occupied)
            if not subsumed:
                new_spans.append(span)
            pos = idx + 1
        if new_spans:
            matched.append(ip)
            occupied.extend(new_spans)

    return matched


def _is_core_eda_file(rel_path: str) -> bool:
    name = rel_path.lower().removesuffix('.gz')
    return Path(name).suffix in CORE_EDA_EXTENSIONS


def _scan_files_stage(rel_paths: list[str], ip_list: list[str]) -> dict[str, list[str]]:
    hits: dict[str, list[str]] = {}
    for rel in sorted(rel_paths):
        basename = Path(rel).name
        for ip in match_ips_in_text(basename, ip_list):
            hits.setdefault(ip, []).append(rel)
    return hits


def classify_delivery_version(version: str, rel_paths: list[str], ip_list: list[str]) -> tuple[str, list[str], dict]:
    """Classify a single delivery version via Stage 1 (version name) -> Stage 2 (core EDA files -> all files)."""
    # Stage 1: match delivery version name
    s1_hits = match_ips_in_text(version, ip_list)
    if len(s1_hits) == 1:
        return 'MATCHED', s1_hits, {'stage': 'stage1_version_name', 'matched_by': [version]}
    if len(s1_hits) > 1:
        ordered_hits = sorted(s1_hits)
        return (
            'CONFLICT',
            ordered_hits,
            {
                'stage': 'stage1_version_name',
                'evidence': [version],
                'reason': f'版本名同时命中多个业务 IP: {", ".join(ordered_hits)}',
            },
        )

    # Stage 2a: core EDA view files (.lef/.lib/.db/.v/.cdl, including .gz)
    core_files = [p for p in rel_paths if _is_core_eda_file(p)]
    core_hits = _scan_files_stage(core_files, ip_list)
    if len(core_hits) == 1:
        only_ip = next(iter(core_hits))
        return 'MATCHED', [only_ip], {'stage': 'stage2_core_eda_files', 'matched_by': core_hits[only_ip][:10]}
    if len(core_hits) > 1:
        ordered_hits = sorted(core_hits)
        ev = {ip: core_hits[ip][:5] for ip in ordered_hits}
        return (
            'CONFLICT',
            ordered_hits,
            {
                'stage': 'stage2_core_eda_files',
                'evidence': ev,
                'reason': f'核心 EDA 文件同时命中多个业务 IP: {", ".join(ordered_hits)}',
            },
        )

    # Stage 2b: fallback to all filenames in this version
    all_hits = _scan_files_stage(rel_paths, ip_list)
    if len(all_hits) == 1:
        only_ip = next(iter(all_hits))
        return 'MATCHED', [only_ip], {'stage': 'stage2_all_files', 'matched_by': all_hits[only_ip][:10]}
    if len(all_hits) > 1:
        ordered_hits = sorted(all_hits)
        ev = {ip: all_hits[ip][:5] for ip in ordered_hits}
        return (
            'CONFLICT',
            ordered_hits,
            {
                'stage': 'stage2_all_files',
                'evidence': ev,
                'reason': f'交付文件清单同时命中多个业务 IP: {", ".join(ordered_hits)}',
            },
        )

    return 'UNASSIGNED', [], {'reason': '版本名及交付文件名均未命中任何配置的业务 IP'}


def _files_by_version_from_index(index: dict) -> dict[str, list[str]]:
    by_ver: dict[str, list[str]] = {d['version']: [] for d in index.get('deliveries') or []}
    for group in (index.get('views') or {}).values():
        for rel_path, row in group.items():
            for item in row.get('raw') or []:
                ver = item.get('version')
                if ver in by_ver:
                    by_ver[ver].append(rel_path)
    for ver in by_ver:
        by_ver[ver] = sorted(set(by_ver[ver]))
    return by_ver


def _semantic_snapshot(payload: dict) -> dict:
    return {
        'schema_version': payload.get('schema_version'),
        'vendor': payload.get('vendor'),
        'library': payload.get('library'),
        'ip_type': payload.get('ip_type'),
        'ip_list': payload.get('ip_list'),
        'tracks': payload.get('tracks'),
        'needs_review': payload.get('needs_review'),
        'auto_trace': payload.get('auto_trace'),
    }


def partition_library_ips(
    work,
    vendor: str,
    library: str,
    *,
    index: dict | None = None,
    dry_run: bool = False,
    _folder_locked: bool = False,
) -> dict:
    """Incrementally partition delivery versions into per-IP tracks, strictly preserving confirmed `tracks`."""
    root = Path(work).resolve(strict=True)
    folder = library_folder(root, vendor, library)
    if not folder.is_dir():
        raise ValueError(f'库目录不存在: {vendor}/{library}')

    ip_cfg = library_ip_config(root, vendor, library)
    if not ip_cfg['is_multi_track']:
        return {
            'state': 'SINGLE_TRACK',
            'vendor': vendor,
            'library': library,
            'ip_type': ip_cfg['ip_type'],
            'ip_list': [],
            'is_multi_track': False,
            'path': None,
            'tracks': {},
            'needs_review': {'conflicts': [], 'unassigned': []},
            'newly_assigned': [],
            'changed': False,
        }

    ip_list = ip_cfg['ip_list']
    ip_type = ip_cfg['ip_type']

    # Respect strict lock ordering: locked(folder) FIRST, then locked(root) SECOND.
    folder_ctx = nullcontext() if _folder_locked else locked(folder)
    with folder_ctx:
        if index is None:
            from .path_query import PathDataQuery
            index = PathDataQuery(root)._index_locked(vendor, library)

        excluded = excluded_versions(root, vendor, library)
        files_by_ver = _files_by_version_from_index(index)
        ordered_versions = [d['version'] for d in index.get('deliveries') or []]

        with locked(root):
            path = partition_path(root, vendor, library)
            existing_path, from_legacy = resolve_existing_partition_path(root, vendor, library)
            existing = load_partition(root, vendor, library) if existing_path is not None else None

            # Strictly preserve all existing confirmed tracks and their version order.
            tracks: dict[str, list[str]] = {}
            for ip in ip_list:
                tracks[ip] = list(existing['tracks'].get(ip, [])) if existing else []
            if existing:
                for extra_ip, vers in existing['tracks'].items():
                    if extra_ip not in tracks and vers:
                        tracks[extra_ip] = list(vers)

            confirmed = {ver for vers in tracks.values() for ver in vers}
            auto_trace = dict(existing['auto_trace']) if existing else {}
            conflicts: list[dict] = []
            unassigned: list[dict] = []
            newly_assigned: list[dict] = []
            now_ts = utc_text()

            for ver in ordered_versions:
                if ver in confirmed or ver in excluded:
                    continue
                outcome, hits, detail = classify_delivery_version(ver, files_by_ver.get(ver, []), ip_list)
                if outcome == 'MATCHED':
                    ip = hits[0]
                    tracks.setdefault(ip, []).append(ver)
                    confirmed.add(ver)
                    trace_entry = {
                        'ip': ip,
                        'stage': detail['stage'],
                        'matched_by': detail['matched_by'],
                        'matched_at': now_ts,
                    }
                    auto_trace[ver] = trace_entry
                    newly_assigned.append({'version': ver, 'business_ip': ip, 'stage': detail['stage']})
                elif outcome == 'CONFLICT':
                    conflicts.append({
                        'version': ver,
                        'stage': detail['stage'],
                        'candidates': hits,
                        'evidence': detail['evidence'],
                        'reason': detail['reason'],
                    })
                else:
                    unassigned.append({
                        'version': ver,
                        'reason': detail['reason'],
                    })

            payload = {
                'schema_version': 'ip_partition.v1',
                'vendor': vendor,
                'library': library,
                'ip_type': ip_type,
                'ip_list': ip_list,
                'tracks': tracks,
                'needs_review': {
                    'conflicts': conflicts,
                    'unassigned': unassigned,
                },
                'auto_trace': auto_trace,
                'updated_at': existing['updated_at'] if (existing and existing.get('updated_at')) else now_ts,
            }

            changed = existing is None or _semantic_snapshot(existing) != _semantic_snapshot(payload)
            migrated_from_legacy = bool(from_legacy and not path.is_file())
            if changed:
                payload['updated_at'] = now_ts
            if (changed or migrated_from_legacy) and not dry_run:
                validate(payload, 'ip_partition')
                write_atomic(path, payload)

    has_review = bool(conflicts or unassigned)
    state = 'NEEDS_REVIEW' if has_review else ('UPDATED' if changed else 'UNCHANGED')
    return {
        'state': state,
        'vendor': vendor,
        'library': library,
        'ip_type': ip_type,
        'ip_list': ip_list,
        'is_multi_track': True,
        'path': str(path),
        'tracks': tracks,
        'needs_review': {'conflicts': conflicts, 'unassigned': unassigned},
        'auto_trace': auto_trace,
        'newly_assigned': newly_assigned,
        'changed': changed,
        'migrated_from_legacy': migrated_from_legacy,
        'dry_run': dry_run,
    }


def active_tracks_for_library(work, vendor: str, library: str) -> dict:
    """Read-only summary of configured/discovered business IP tracks for a library."""
    ip_cfg = library_ip_config(work, vendor, library)
    if not ip_cfg['is_multi_track']:
        return {
            'is_multi_track': False,
            'ip_type': ip_cfg['ip_type'],
            'ip_list': [],
            'tracks': {},
            'needs_review': {'conflicts': [], 'unassigned': []},
            'partition_path': None,
        }
    resolved_path, _ = resolve_existing_partition_path(work, vendor, library)
    part = load_partition(work, vendor, library) if resolved_path is not None else None
    if part is not None:
        tracks = dict(part['tracks'])
        for ip in ip_cfg['ip_list']:
            tracks.setdefault(ip, [])
        return {
            'is_multi_track': True,
            'ip_type': ip_cfg['ip_type'] or part.get('ip_type'),
            'ip_list': ip_cfg['ip_list'],
            'tracks': tracks,
            'needs_review': part.get('needs_review') or {'conflicts': [], 'unassigned': []},
            'partition_path': str(resolved_path),
        }
    return {
        'is_multi_track': True,
        'ip_type': ip_cfg['ip_type'],
        'ip_list': ip_cfg['ip_list'],
        'tracks': {ip: [] for ip in ip_cfg['ip_list']},
        'needs_review': {'conflicts': [], 'unassigned': []},
        'partition_path': None,
    }
