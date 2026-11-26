"""Draft-first delivery sequence & business-IP track organizer with Policy A safe archive-and-rebuild."""
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
import shutil

from ai_lib_qor.sources.layout import SAFE, archive_files, library_folder
from ai_lib_qor.sources.minimal_delivery import order_deliveries, version_date
from ai_lib_qor.sources.timestamps import instant, utc_text
from ai_lib_qor.versions.store import locked, write_atomic
from .ip_partition import active_tracks_for_library, load_partition, partition_path
from .minimal_effective import (
    _audit_filename,
    _auto_state_filename,
    _deliveries,
    _effective_stem,
    _flat,
    _history,
    _latest_effective_pointer,
    _norm_business_ip,
    load_auto_effective_state,
)
from .path_acceptance import acceptance_status
from .path_config import excluded_versions, library_ip_config, load_path_config, registration_times


def _version_in_revisions_from_history(history: list) -> dict[str, list[str]]:
    """Map delivery version -> sorted list of effective revision ids from already-loaded history."""
    by_ver: dict[str, list[str]] = {}
    for _, _, row in history:
        rev = row['revision']
        used_vers = set(_flat(row.get('views') or {}).values())
        for v in used_vers:
            by_ver.setdefault(v, []).append(rev)
    return by_ver


def _version_in_revisions(folder: Path, library: str, business_ip=None) -> dict[str, list[str]]:
    """Map delivery version -> sorted list of effective revision ids that reference it."""
    return _version_in_revisions_from_history(_history(folder, library, business_ip=business_ip))


def _track_runtime_status(work: Path, folder: Path, vendor: str, library: str, business_ip=None) -> dict:
    ip = _norm_business_ip(business_ip)
    history = _history(folder, library, business_ip=ip)
    acc = acceptance_status(work, vendor, library, limit=1, business_ip=ip)
    state = load_auto_effective_state(folder, business_ip=ip)
    ver_revs = _version_in_revisions_from_history(history)
    evolved_vers = set(state.get('processed') or []) | set(ver_revs.keys())
    return {
        'business_ip': ip,
        'revision_count': len(history),
        'latest_revision': history[-1][2]['revision'] if history else None,
        'accepted_revision': acc.get('accepted_revision'),
        'is_accepted': bool(acc.get('accepted_revision')),
        'has_history': bool(history),
        'processed_versions': sorted(evolved_vers),
        'version_revisions': ver_revs,
    }


def _safe_ordered_deliveries(deliveries: dict, reg_times: dict) -> tuple[list[dict], str | None]:
    records = list(deliveries.values())
    try:
        return order_deliveries(records, reg_times), None
    except ValueError as exc:
        # Fallback deterministic display order when same-day tie is unresolved so user can fix it in UI!
        fallback = sorted(
            records,
            key=lambda d: (
                d.get('version_date') or '0000-00-00',
                reg_times.get(d['version']) or d.get('directory_mtime') or '',
                d['version'],
            ),
        )
        return fallback, str(exc)


def get_organizer_state(work, vendor: str, library: str, *, include_files: bool = False) -> dict:
    """Read-only organizer snapshot for both multi-IP and single-track libraries (zero external RAW scans)."""
    root = Path(work).resolve()
    folder = library_folder(root, vendor, library)
    if not folder.is_dir():
        raise ValueError(f'库目录不存在: {vendor}/{library}')

    ip_cfg = library_ip_config(root, vendor, library)
    is_multi = bool(ip_cfg['is_multi_track'])
    deliveries = _deliveries(folder, vendor, library)
    reg_times = registration_times(root, vendor, library)
    excluded = excluded_versions(root, vendor, library)

    ordered_records, order_error = _safe_ordered_deliveries(deliveries, reg_times)
    delivery_meta: dict[str, dict] = {}
    for rec in ordered_records:
        ver = rec['version']
        views = rec.get('views') or {}
        view_counts = {k: len(v) for k, v in sorted(views.items()) if v}
        item_meta = {
            'version': ver,
            'version_date': rec.get('version_date'),
            'directory_mtime': rec.get('directory_mtime'),
            'registration_time': reg_times.get(ver),
            'root': rec.get('root') or '',
            'file_count': sum(view_counts.values()),
            'view_counts': view_counts,
            'excluded': ver in excluded,
        }
        if include_files:
            files_by_view = {}
            files_truncated = 0
            for vk, vpaths in sorted(views.items()):
                if not vpaths:
                    continue
                files_by_view[vk] = list(vpaths[:60])
                if len(vpaths) > 60:
                    files_truncated += len(vpaths) - 60
            item_meta['files_by_view'] = files_by_view
            item_meta['files_truncated'] = files_truncated
        delivery_meta[ver] = item_meta

    if is_multi:
        part = load_partition(root, vendor, library)
        active = active_tracks_for_library(root, vendor, library)
        ip_list = list(active['ip_list'])
        tracks_raw = {ip: list(active['tracks'].get(ip, [])) for ip in ip_list}
        for extra_ip, vers in active['tracks'].items():
            if extra_ip not in tracks_raw and vers:
                tracks_raw[extra_ip] = list(vers)
                ip_list.append(extra_ip)

        auto_trace = (part.get('auto_trace') or {}) if isinstance(part, dict) else {}
        nr = active.get('needs_review') or {'conflicts': [], 'unassigned': []}
        conflict_map = {
            c['version']: c for c in (nr.get('conflicts') or []) if isinstance(c, dict) and c.get('version')
        }
        unassigned_map = {
            (u['version'] if isinstance(u, dict) else str(u)): (u if isinstance(u, dict) else {'version': str(u), 'reason': ''})
            for u in (nr.get('unassigned') or [])
            if (isinstance(u, dict) and u.get('version')) or isinstance(u, str)
        }

        track_statuses: dict[str, dict] = {}
        assigned_set: set[str] = set()
        tracks_out: dict[str, list[dict]] = {}
        for ip in ip_list:
            st = _track_runtime_status(root, folder, vendor, library, business_ip=ip)
            track_statuses[ip] = st
            items = []
            for ver in tracks_raw.get(ip, []):
                if ver not in delivery_meta or ver in excluded:
                    continue
                assigned_set.add(ver)
                meta = dict(delivery_meta[ver])
                meta['track_ip'] = ip
                meta['in_revisions'] = st['version_revisions'].get(ver, [])
                meta['is_evolved'] = ver in st['processed_versions']
                meta['trace'] = auto_trace.get(ver)
                items.append(meta)
            tracks_out[ip] = items

        review_items: list[dict] = []
        excluded_items: list[dict] = []
        for rec in ordered_records:
            ver = rec['version']
            if ver in excluded:
                meta = dict(delivery_meta[ver])
                meta['track_ip'] = None
                meta['in_revisions'] = []
                meta['is_evolved'] = False
                excluded_items.append(meta)
            elif ver not in assigned_set:
                meta = dict(delivery_meta[ver])
                meta['track_ip'] = None
                meta['in_revisions'] = []
                meta['is_evolved'] = False
                if ver in conflict_map:
                    meta['review_kind'] = 'CONFLICT'
                    meta['candidates'] = list(conflict_map[ver].get('candidates') or [])
                    meta['reason'] = conflict_map[ver].get('reason') or ''
                    meta['evidence'] = conflict_map[ver].get('evidence')
                else:
                    meta['review_kind'] = 'UNASSIGNED'
                    meta['candidates'] = []
                    meta['reason'] = (unassigned_map.get(ver) or {}).get('reason') or '尚未归类到任何业务 IP 轨道'
                    meta['evidence'] = None
                review_items.append(meta)

        return {
            'mode': 'multi_track',
            'vendor': vendor,
            'library': library,
            'ip_type': ip_cfg.get('ip_type'),
            'ip_list': ip_list,
            'tracks': tracks_out,
            'track_statuses': track_statuses,
            'needs_review': review_items,
            'excluded': excluded_items,
            'order_error': order_error,
            'partition_path': str(partition_path(root, vendor, library)),
        }

    # Single-track mode
    st = _track_runtime_status(root, folder, vendor, library, business_ip=None)
    active_items: list[dict] = []
    excluded_items: list[dict] = []
    for rec in ordered_records:
        ver = rec['version']
        meta = dict(delivery_meta[ver])
        meta['in_revisions'] = st['version_revisions'].get(ver, [])
        meta['is_evolved'] = ver in st['processed_versions']
        if ver in excluded:
            excluded_items.append(meta)
        else:
            active_items.append(meta)

    return {
        'mode': 'single_track',
        'vendor': vendor,
        'library': library,
        'ip_type': ip_cfg.get('ip_type'),
        'ip_list': [],
        'order': active_items,
        'track_statuses': {'__single__': st},
        'needs_review': [],
        'excluded': excluded_items,
        'order_error': order_error,
        'partition_path': None,
    }


def compute_single_track_registration_times(
    deliveries: dict[str, dict],
    desired_order: list[str],
    existing_times: dict[str, str] | None = None,
) -> dict[str, str]:
    """Compute canonical `version_registration_times` achieving `desired_order` while respecting `version_date`-first rule."""
    if len(desired_order) != len(set(desired_order)):
        raise ValueError('版本顺序列表中存在重复版本')
    for ver in desired_order:
        if ver not in deliveries:
            raise ValueError(f'版本不存在: {ver}')

    # 1. Verify directory-date monotonicity: dated items cannot be inverted across different dates.
    last_dated_day: date | None = None
    last_dated_ver: str | None = None
    for ver in desired_order:
        vd = deliveries[ver].get('version_date')
        if vd:
            d = date.fromisoformat(vd)
            if last_dated_day is not None and d < last_dated_day:
                raise ValueError(
                    f'目录日期优先规则不允许跨日期倒排：{ver} ({vd}) 不能排在 '
                    f'{last_dated_ver} ({last_dated_day.isoformat()}) 之后；如需停用请标记排除'
                )
            last_dated_day = d
            last_dated_ver = ver

    # 2. Check whether existing times + mtimes already produce exact desired_order without changes.
    base_times = dict(existing_times or {})
    active_records = [deliveries[v] for v in desired_order]
    try:
        cur_order = [r['version'] for r in order_deliveries(active_records, base_times)]
        if cur_order == desired_order:
            return base_times
    except ValueError:
        pass

    # 3. Assign clean strictly-monotonic UTC timestamps on exact anchor dates.
    # Dated anchors share their exact `version_date`; same-day dated items get wide 3600s/1800s slots,
    # and undated runs between anchors are evenly spaced strictly between neighboring (day, when).
    dated_positions: list[tuple[int, date]] = []
    for idx, ver in enumerate(desired_order):
        vd = deliveries[ver].get('version_date')
        if vd:
            dated_positions.append((idx, date.fromisoformat(vd)))

    assigned_dt: dict[str, datetime] = {}

    if not dated_positions:
        # All versions are undated: anchor cleanly at 2026-01-01T00:01:00Z + 1 min increments.
        anchor = datetime(2026, 1, 1, 0, 1, 0, tzinfo=timezone.utc)
        for i, ver in enumerate(desired_order):
            assigned_dt[ver] = anchor + timedelta(minutes=i)
    else:
        # Group dated items by day to space same-day dated items cleanly across the day (01:00 .. 22:00)
        by_day: dict[date, list[int]] = {}
        for pos, d in dated_positions:
            by_day.setdefault(d, []).append(pos)
        for d, positions in by_day.items():
            count = len(positions)
            # Reserve 00:00..01:00 for undated before first item, and 22:00..23:59 for undated after last item
            span_secs = 20 * 3600  # 01:00 to 21:00
            step = max(60, span_secs // max(1, count))
            for k, pos in enumerate(positions):
                secs = 3600 + k * step
                assigned_dt[desired_order[pos]] = datetime(d.year, d.month, d.day, tzinfo=timezone.utc) + timedelta(seconds=secs)

        # Fill every contiguous run of undated versions between dated anchors
        n = len(desired_order)
        i = 0
        while i < n:
            if deliveries[desired_order[i]].get('version_date'):
                i += 1
                continue
            j = i
            while j < n and not deliveries[desired_order[j]].get('version_date'):
                j += 1
            run = desired_order[i:j]
            k = len(run)
            left_dt = assigned_dt[desired_order[i - 1]] if i > 0 else None
            right_dt = assigned_dt[desired_order[j]] if j < n else None

            if left_dt is None and right_dt is not None:
                # Strictly earlier day than first dated item
                prev_day = right_dt.date() - timedelta(days=1)
                start = datetime(prev_day.year, prev_day.month, prev_day.day, 12, 0, 0, tzinfo=timezone.utc)
                for idx_r, ver in enumerate(run):
                    assigned_dt[ver] = start + timedelta(seconds=idx_r + 1)
            elif left_dt is not None and right_dt is None:
                # Strictly after last dated item (same day +1s.. or next day)
                start = left_dt + timedelta(seconds=1)
                for idx_r, ver in enumerate(run):
                    assigned_dt[ver] = start + timedelta(seconds=idx_r)
            else:
                assert left_dt is not None and right_dt is not None
                gap_secs = int((right_dt - left_dt).total_seconds())
                if gap_secs > k:
                    step = max(1, gap_secs // (k + 1))
                    for idx_r, ver in enumerate(run):
                        assigned_dt[ver] = left_dt + timedelta(seconds=(idx_r + 1) * step)
                else:
                    raise ValueError('同日版本数量过多，无法自动分配唯一秒级顺序时间戳')
            i = j

    # Write registration times for all active versions whose ordering depends on timestamp
    # (preserve unrelated historical keys for excluded versions).
    new_times = dict(base_times)
    for ver in desired_order:
        new_times[ver] = utc_text(assigned_dt[ver])

    # Mathematical invariant check: MUST reproduce desired_order identically!
    verified = [r['version'] for r in order_deliveries(active_records, new_times)]
    if verified != desired_order:
        raise ValueError(f'顺序时间戳计算自检失败（预期 {desired_order}，实际 {verified}）')
    return new_times


def _collect_track_artifact_files(folder: Path, library: str, business_ip=None) -> tuple[list[Path], list[Path]]:
    """Return (regular_files_to_archive, root_symlinks_to_unlink) strictly scoped to one track."""
    ip = _norm_business_ip(business_ip)
    files: list[Path] = []
    symlinks: list[Path] = []

    eff_stem = _effective_stem(library, ip)
    eff_prefix = eff_stem + '_'
    # 1. Effective revisions (subdir + legacy flat root if any)
    for base in (folder / 'effective', folder):
        if not base.is_dir() or base.is_symlink():
            continue
        for p in sorted(base.glob(f'{eff_prefix}*.json')):
            if p.is_symlink() or not p.is_file():
                continue
            if ip is None and p.name.startswith(f'effective_{library}__'):
                continue
            files.append(p)

    # 2. Log artifacts (auto state, audit tsv, checks, overall reports for THIS track only)
    log_dir = folder / 'log'
    if log_dir.is_dir() and not log_dir.is_symlink():
        for exact_name in (_auto_state_filename(ip), _audit_filename(ip)):
            p = log_dir / exact_name
            if p.is_file() and not p.is_symlink():
                files.append(p)
        if ip is not None:
            for pat in (f'check__{ip}__*', f'overall__{ip}__*'):
                for p in sorted(log_dir.glob(pat)):
                    if p.is_file() and not p.is_symlink():
                        files.append(p)
        else:
            for pat in (f'check_{library}_*', f'overall_{library}_*'):
                for p in sorted(log_dir.glob(pat)):
                    if p.is_file() and not p.is_symlink() and not p.name.startswith(('check__', 'overall__')):
                        files.append(p)

    # Legacy root state/audit files for single-track
    if ip is None:
        for exact_name in (_auto_state_filename(None), _audit_filename(None)):
            p = folder / exact_name
            if p.is_file() and not p.is_symlink():
                files.append(p)

    # 3. Track-scoped root pointer symlinks (NEVER touch accepted_effective*, latest_delivery*, latest_formal*)
    ptr_names = (
        _latest_effective_pointer(ip),
        f'latest_check__{ip}.json' if ip else 'latest_check.json',
        f'latest_check__{ip}.xlsx' if ip else 'latest_check.xlsx',
        f'latest_overall__{ip}.xlsx' if ip else 'latest_overall.xlsx',
    )
    for name in ptr_names:
        p = folder / name
        if p.is_symlink():
            symlinks.append(p)

    # Deduplicate preserving order
    seen_f = set()
    uniq_files = []
    for f in files:
        rf = str(f)
        if rf not in seen_f:
            seen_f.add(rf)
            uniq_files.append(f)
    return uniq_files, symlinks


def _archive_track_for_rebuild_locked(
    work: Path,
    folder: Path,
    vendor: str,
    library: str,
    business_ip=None,
    *,
    actor: str = 'web',
    reason: str = '顺序/分轨调整后无损归档重建',
) -> dict:
    """Policy A lossless archive of ONE unaccepted track's L2/check artifacts (caller holds locked(folder))."""
    ip = _norm_business_ip(business_ip)
    acc = acceptance_status(work, vendor, library, limit=1, business_ip=ip)
    if acc.get('accepted_revision'):
        label = ip or library
        raise ValueError(
            f'轨道 {label} 已有人工采纳版本 {acc["accepted_revision"]}，受保护禁止归档重建；'
            '请先在「采纳与维护」回退人工采纳后再操作'
        )

    files, symlinks = _collect_track_artifact_files(folder, library, business_ip=ip)
    if not files and not symlinks:
        return {'business_ip': ip, 'archived_count': 0, 'archive_dir': None}

    ts_tag = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')
    track_dir_name = ip if ip else '_single_track'
    archive_base = work / 'archive' / f'{ts_tag}_轨道重建' / vendor / library / track_dir_name
    suffix = 2
    while archive_base.exists():
        archive_base = work / 'archive' / f'{ts_tag}_轨道重建_{suffix}' / vendor / library / track_dir_name
        suffix += 1
    archive_base.mkdir(parents=True, exist_ok=True)

    moved_records = []
    for src in files:
        rel = src.relative_to(folder)
        dst = archive_base / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))
        moved_records.append(str(rel))

    unlinked_ptrs = []
    for sym in symlinks:
        try:
            target = str(sym.readlink())
        except OSError:
            target = ''
        unlinked_ptrs.append({'name': sym.name, 'target': target})
        sym.unlink(missing_ok=True)

    manifest = {
        'schema_version': 'track_rebuild_archive.v1',
        'archived_at': utc_text(),
        'actor': actor,
        'reason': reason,
        'vendor': vendor,
        'library': library,
        'business_ip': ip,
        'moved_files': moved_records,
        'cleared_pointers': unlinked_ptrs,
    }
    write_atomic(archive_base / 'manifest.json', manifest)
    return {
        'business_ip': ip,
        'archived_count': len(moved_records),
        'archive_dir': str(archive_base.relative_to(work)),
    }


def apply_sequence_plan(
    work,
    vendor: str,
    library: str,
    *,
    tracks: dict[str, list[str]] | None = None,
    order: list[str] | None = None,
    excluded: list[str] | None = None,
    rebuild_tracks: list[str] | None = None,
    refresh: bool = True,
    actor: str = 'web',
) -> dict:
    """Atomically apply draft sequence / IP-track plan, optionally Policy-A archiving unaccepted tracks, and run L2+L3."""
    root = Path(work).resolve(strict=True)
    folder = library_folder(root, vendor, library)
    if not folder.is_dir():
        raise ValueError(f'库目录不存在: {vendor}/{library}')

    ip_cfg = library_ip_config(root, vendor, library)
    is_multi = bool(ip_cfg['is_multi_track'])
    rebuild_req = set(rebuild_tracks or [])

    archived_results: list[dict] = []
    touched_evolved_tracks: list[str] = []

    # Respect strict lock order: locked(folder) FIRST, locked(root) SECOND.
    with locked(folder):
        deliveries = _deliveries(folder, vendor, library)
        all_versions = set(deliveries.keys())
        new_excluded = sorted({str(v).strip() for v in (excluded or []) if str(v).strip()})
        for v in new_excluded:
            if v not in all_versions:
                raise ValueError(f'待排除版本不存在: {v}')
        excluded_set = set(new_excluded)

        if is_multi:
            if not isinstance(tracks, dict):
                raise ValueError('多业务 IP 模式需要提供 tracks 映射')
            ip_list = list(ip_cfg['ip_list'])
            existing_part = load_partition(root, vendor, library)
            old_tracks = (existing_part.get('tracks') or {}) if existing_part else {}

            clean_tracks: dict[str, list[str]] = {ip: [] for ip in ip_list}
            seen_assigned: set[str] = set()
            for ip, vers in tracks.items():
                if not isinstance(ip, str) or not SAFE.fullmatch(ip) or '__' in ip:
                    raise ValueError(f'业务 IP 名称无效: {ip}')
                if ip not in clean_tracks and ip not in old_tracks:
                    raise ValueError(f'未知业务 IP 轨道: {ip}')
                if not isinstance(vers, list):
                    raise ValueError(f'轨道 {ip} 版本列表格式无效')
                bucket: list[str] = []
                for raw_v in vers:
                    v = str(raw_v).strip()
                    if not v:
                        continue
                    if v not in all_versions:
                        raise ValueError(f'轨道 {ip} 包含不存在的版本: {v}')
                    if v in excluded_set:
                        raise ValueError(f'版本 {v} 不能同时位于轨道 {ip} 和排除列表中')
                    if v in seen_assigned:
                        raise ValueError(f'版本 {v} 不能重复出现在多个轨道中')
                    seen_assigned.add(v)
                    bucket.append(v)
                clean_tracks[ip] = bucket

            # Determine which tracks had their previously-evolved versions altered (removed or reordered).
            for ip, new_vers in clean_tracks.items():
                old_vers = [v for v in (old_tracks.get(ip) or []) if v in all_versions]
                st = _track_runtime_status(root, folder, vendor, library, business_ip=ip)
                evolved = set(st['processed_versions'])
                if not st['has_history'] or not evolved:
                    continue
                old_evolved_seq = [v for v in old_vers if v in evolved]
                new_evolved_seq = [v for v in new_vers if v in evolved]
                # Check if any evolved version was removed, moved out, reordered, OR an earlier version inserted before it
                changed_history = (old_evolved_seq != new_evolved_seq)
                if not changed_history and old_evolved_seq:
                    # Also check if a new version was inserted BEFORE the last evolved version
                    last_ev_idx = max(new_vers.index(v) for v in old_evolved_seq)
                    for prefix_v in new_vers[:last_ev_idx]:
                        if prefix_v not in evolved:
                            changed_history = True
                            break
                if changed_history:
                    touched_evolved_tracks.append(ip)

            # Policy A validation BEFORE mutating config/partition!
            for ip in sorted(rebuild_req):
                if ip not in clean_tracks:
                    raise ValueError(f'请求重建的轨道不存在: {ip}')
                st = _track_runtime_status(root, folder, vendor, library, business_ip=ip)
                if st['is_accepted']:
                    raise ValueError(
                        f'轨道 {ip} 已有人工采纳版本 {st["accepted_revision"]}，受保护禁止归档重建；'
                        '请先在「采纳与维护」回退采纳'
                    )

            # Rebuild remaining needs_review cleanly (keep conflict detail if still unassigned)
            old_nr = (existing_part.get('needs_review') or {}) if existing_part else {}
            old_conflicts = {
                c['version']: c for c in (old_nr.get('conflicts') or []) if isinstance(c, dict) and c.get('version')
            }
            new_conflicts = []
            new_unassigned = []
            for ver in sorted(all_versions - seen_assigned - excluded_set):
                if ver in old_conflicts:
                    new_conflicts.append(old_conflicts[ver])
                else:
                    new_unassigned.append({'version': ver, 'reason': '手工移出轨道或待归类'})

            auto_trace = dict((existing_part.get('auto_trace') or {}) if existing_part else {})
            now_ts = utc_text()
            for ip, vers in clean_tracks.items():
                old_set = set(old_tracks.get(ip) or [])
                for v in vers:
                    if v not in old_set:
                        auto_trace[v] = {
                            'ip': ip,
                            'stage': 'manual_organizer',
                            'matched_by': [actor],
                            'matched_at': now_ts,
                        }

            with locked(root):
                # 1. Update excluded_versions in path_sources.json
                from .path_config import save_path_config
                from .ip_partition import save_partition_payload
                cfg = deepcopy(load_path_config(root))
                lib_item = cfg.setdefault('libraries', {}).setdefault(vendor, {}).setdefault(library, {})
                lib_item['excluded_versions'] = new_excluded
                save_path_config(root, cfg, already_locked=True)

                # 2. Write updated libraries/<vendor>/<library>/ip_partition.json
                part_payload = {
                    'schema_version': 'ip_partition.v1',
                    'vendor': vendor,
                    'library': library,
                    'ip_type': ip_cfg.get('ip_type'),
                    'ip_list': ip_list,
                    'tracks': clean_tracks,
                    'needs_review': {
                        'conflicts': new_conflicts,
                        'unassigned': new_unassigned,
                    },
                    'auto_trace': auto_trace,
                    'updated_at': now_ts,
                }
                save_partition_payload(root, vendor, library, part_payload)

            # 3. Losslessly archive any requested unaccepted tracks BEFORE running L2+L3
            for ip in sorted(rebuild_req):
                res = _archive_track_for_rebuild_locked(root, folder, vendor, library, business_ip=ip, actor=actor)
                if res['archived_count'] > 0 or res['archive_dir']:
                    archived_results.append(res)

        else:
            # Single-track mode: validate desired order and write version_registration_times + excluded_versions
            if not isinstance(order, list):
                raise ValueError('单轨模式需要提供 order 版本顺序列表')
            clean_order = [str(v).strip() for v in order if str(v).strip()]
            expected_active = all_versions - excluded_set
            if set(clean_order) != expected_active or len(clean_order) != len(expected_active):
                raise ValueError('版本顺序列表必须精确包含全部未排除交付版本')

            old_reg_times = registration_times(root, vendor, library)
            old_excluded = excluded_versions(root, vendor, library)
            old_ordered, _ = _safe_ordered_deliveries(
                {k: v for k, v in deliveries.items() if k not in old_excluded},
                old_reg_times,
            )
            old_seq = [r['version'] for r in old_ordered]

            new_reg_times = compute_single_track_registration_times(deliveries, clean_order, old_reg_times)

            st = _track_runtime_status(root, folder, vendor, library, business_ip=None)
            evolved = set(st['processed_versions'])
            if st['has_history'] and evolved:
                old_ev = [v for v in old_seq if v in evolved]
                new_ev = [v for v in clean_order if v in evolved]
                changed_history = (old_ev != new_ev)
                if not changed_history and old_ev:
                    last_ev_idx = max(clean_order.index(v) for v in old_ev)
                    for prefix_v in clean_order[:last_ev_idx]:
                        if prefix_v not in evolved:
                            changed_history = True
                            break
                if changed_history:
                    touched_evolved_tracks.append('__single__')

            want_single_rebuild = '__single__' in rebuild_req or library in rebuild_req
            if want_single_rebuild and st['is_accepted']:
                raise ValueError(
                    f'库 {library} 已有人工采纳版本 {st["accepted_revision"]}，受保护禁止归档重建；'
                    '请先在「采纳与维护」回退采纳'
                )

            with locked(root):
                from .path_config import save_path_config
                cfg = deepcopy(load_path_config(root))
                lib_item = cfg.setdefault('libraries', {}).setdefault(vendor, {}).setdefault(library, {})
                lib_item['excluded_versions'] = new_excluded
                lib_item['version_registration_times'] = new_reg_times
                save_path_config(root, cfg, already_locked=True)

            if want_single_rebuild:
                res = _archive_track_for_rebuild_locked(root, folder, vendor, library, business_ip=None, actor=actor)
                if res['archived_count'] > 0 or res['archive_dir']:
                    archived_results.append(res)

    l2_res = None
    l3_res = None
    if refresh:
        from .path_refresh import refresh_l2, refresh_l3
        l2_res = refresh_l2(root, vendor=vendor, library=library, actor=actor)
        l3_res = refresh_l3(root, vendor=vendor, library=library, actor=actor)

    return {
        'status': 'OK',
        'mode': 'multi_track' if is_multi else 'single_track',
        'vendor': vendor,
        'library': library,
        'touched_evolved_tracks': touched_evolved_tracks,
        'archived_tracks': archived_results,
        'l2': l2_res,
        'l3': l3_res,
    }
