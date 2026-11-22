"""Layered three-stage data refresh orchestration: L1 (RAW/NL) -> L2 (Effective) -> L3 (FileIndex)."""
import json
import os
from pathlib import Path

from ai_lib_qor.sources.layout import SAFE, archive_files, library_folder
from ai_lib_qor.sources.root_inventory import build_from_roots, update_pointer
from ai_lib_qor.sources.timestamps import instant, utc_text
from ai_lib_qor.versions.store import locked, write_atomic
from .minimal_effective import (
    _audit_recover,
    _candidate,
    _deliveries,
    _flat,
    _history,
    _save,
    initialize_from_formal,
)
from .minimal_file_index import (
    _configured_times,
    _ordered,
    index_manifest_matches,
    refresh_index,
)
from .path_config import excluded_versions, load_path_config


def _target_libraries(work, vendor=None, library=None):
    if bool(vendor) != bool(library):
        raise ValueError('供应商和库必须同时指定')
    if vendor:
        folder = library_folder(work, vendor, library)
        return [(vendor, library, folder)] if folder.is_dir() else []
    root = Path(work) / 'libraries'
    if not root.is_dir():
        return []
    items = []
    for folder in sorted(root.glob('*/*')):
        if not folder.is_dir() or folder.is_symlink() or folder.parent.is_symlink():
            continue
        v, lib = folder.parent.name, folder.name
        if not (SAFE.fullmatch(v) and SAFE.fullmatch(lib)):
            continue
        items.append((v, lib, folder))
    return items


def _append_refresh_history(work, entry):
    root = Path(work)
    root.mkdir(parents=True, exist_ok=True)
    log = root / 'refresh_history.jsonl'
    if log.is_symlink():
        raise ValueError('刷新历史日志不能为软链接')
    with locked(root):
        with log.open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + '\n')
            stream.flush()
            os.fsync(stream.fileno())


def _snapshot_library_l1(work, vendor=None, library=None):
    state = {}
    for v, lib, folder in _target_libraries(work, vendor, library):
        deliveries = {}
        for p in archive_files(folder, 'delivery', 'delivery_*.json'):
            if p.is_symlink() or not p.is_file():
                continue
            try:
                data = json.loads(p.read_text(encoding='utf-8'))
                if isinstance(data, dict) and isinstance(data.get('version'), str):
                    deliveries[data['version']] = p.name
            except (OSError, ValueError, TypeError):
                continue
        formals = {p.name for p in archive_files(folder, 'formal', 'formal_*.json') if not p.is_symlink() and p.is_file()}
        state[(v, lib)] = {'deliveries': deliveries, 'formals': formals}
    return state


def refresh_l1(work, raw_root=None, nl_root=None, *, nl_version=None, raw=True, formal=True, verify_raw=False, vendor=None, library=None, actor='local', progress_cb=None, cancel_event=None):
    """Layer 1: Scan and archive RAW deliveries and Formal NL snapshots only (incremental skip by default)."""
    from ai_lib_qor.workbench.jobs import check_cancel, emit_progress
    if not (raw or formal):
        raise ValueError('L1 刷新至少需要启用 RAW 或 Formal 之一')
    check_cancel(cancel_event, 'L1 刷新已终止')
    emit_progress(progress_cb, 'L1', '准备 L1 来源盘点…')
    config = load_path_config(work)
    effective_raw = raw_root if raw_root is not None else config.get('raw_root')
    effective_nl = nl_root if nl_root is not None else config.get('nl_root')
    effective_nl_ver = nl_version if nl_version is not None else (config.get('nl_version') or None)

    before = _snapshot_library_l1(work, vendor, library)
    inv = build_from_roots(
        effective_raw,
        effective_nl,
        work,
        nl_version=effective_nl_ver,
        update_raw=raw,
        update_formal=formal,
        update_index=False,
        auto_effective=False,
        vendor=vendor,
        library=library,
        verify_raw=verify_raw,
        progress_cb=progress_cb,
        cancel_event=cancel_event,
    )
    after = _snapshot_library_l1(work, vendor, library)

    libraries_changed = []
    for key in sorted(after):
        prev = before.get(key, {'deliveries': {}, 'formals': set()})
        curr = after[key]
        new_deliveries = sorted(set(curr['deliveries']) - set(prev['deliveries']))
        new_formals = sorted(curr['formals'] - prev['formals'])
        if new_deliveries or new_formals:
            libraries_changed.append({
                'vendor': key[0],
                'library': key[1],
                'new_deliveries': new_deliveries,
                'new_formals': new_formals,
            })

    summary = {
        'layer': 'L1',
        'at': utc_text(),
        'actor': actor,
        'scope': {'vendor': vendor, 'library': library},
        'options': {'raw': raw, 'formal': formal, 'nl_version': effective_nl_ver, 'verify_raw': verify_raw},
        'delivery_created': inv['delivery_created'],
        'delivery_unchanged': inv['delivery_unchanged'],
        'formal_created': inv['formal_created'],
        'formal_unchanged': inv['formal_unchanged'],
        'raw_versions_walked': inv.get('raw_versions_walked', 0),
        'raw_versions_skipped': inv.get('raw_versions_skipped', 0),
        'formal_observation_status': inv.get('formal_observation_status'),
        'libraries_changed': libraries_changed,
        'warnings': inv['warnings'],
    }
    _append_refresh_history(work, summary)
    emit_progress(progress_cb, 'L1', f"L1 完成：新增交付 {inv['delivery_created']} · 跳过已归档版本 {inv.get('raw_versions_skipped', 0)}")
    return summary


def _latest_formal_file(folder):
    candidates = []
    for p in archive_files(folder, 'formal', 'formal_*.json'):
        if p.is_symlink() or not p.is_file():
            continue
        try:
            data = json.loads(p.read_text(encoding='utf-8'))
            if isinstance(data, dict) and data.get('observed_at') and data.get('views'):
                candidates.append((instant(data['observed_at']), p.name, p))
        except (OSError, ValueError, TypeError):
            continue
    if not candidates:
        return None
    candidates.sort(key=lambda x: (utc_text(x[0]), x[1]))
    return candidates[-1][2]


def refresh_l2(work, *, auto_init_from_formal=True, vendor=None, library=None, actor='automatic', progress_cb=None, cancel_event=None):
    """Layer 2: Auto-initialize (from Formal) and auto-evolve Effective revisions from archived L1 records."""
    from ai_lib_qor.workbench.jobs import check_cancel, emit_progress
    initialized = 0
    published = 0
    unchanged = 0
    pending_total = 0
    warnings = []
    libraries_changed = []

    targets = _target_libraries(work, vendor, library)
    total = len(targets)
    for idx, (v, lib, folder) in enumerate(targets, 1):
        check_cancel(cancel_event, 'L2 推进已由用户终止')
        emit_progress(progress_cb, 'L2', f'L2 推进有效版本 {v}/{lib} ({idx}/{total})', completed=idx - 1, total=total)
        lib_events = []
        try:
            with locked(folder):
                history = _history(folder, lib)
            if not history:
                if auto_init_from_formal:
                    formal_path = _latest_formal_file(folder)
                    if formal_path is not None:
                        try:
                            res = initialize_from_formal(work, v, lib, formal_path, actor=actor)
                            if res.get('state') in ('PUBLISHED', 'PUBLISHED_INDEX_STALE'):
                                initialized += 1
                                lib_events.append({'action': 'INITIALIZE', 'revision': res['revision'], 'source': formal_path.name})
                            else:
                                unchanged += 1
                                continue
                        except (OSError, ValueError, KeyError, TypeError) as exc:
                            warnings.append(f'{v}/{lib}: 自动从 Formal 初始化未完成: {exc}')
                            continue
                    else:
                        unchanged += 1
                        continue
                else:
                    unchanged += 1
                    continue

            with locked(folder):
                history = _history(folder, lib)
                update_pointer(folder, 'latest_effective.json', str(history[-1][1].relative_to(folder)))
                _audit_recover(folder, history[-1][2]['revision'])

                deliveries = _deliveries(folder, v, lib)
                if not deliveries:
                    unchanged += 1
                    continue
                try:
                    ordered = _ordered(list(deliveries.values()), _configured_times(work, v, lib))
                except ValueError as exc:
                    warnings.append(f'{v}/{lib}: 交付顺序未确认，跳过 L2 自动演化: {exc}')
                    state_path = folder / '.auto_effective_state.json'
                    if state_path.is_file() and not state_path.is_symlink():
                        try:
                            pending_total += len(json.loads(state_path.read_text(encoding='utf-8')).get('pending', []))
                        except (OSError, ValueError, TypeError):
                            pass
                    continue

                ranks = {d['version']: n for n, d in enumerate(ordered)}
                excluded = excluded_versions(work, v, lib)

                state_path = folder / '.auto_effective_state.json'
                if state_path.is_symlink():
                    raise ValueError('自动更新状态不能为软链接')
                state = json.loads(state_path.read_text(encoding='utf-8')) if state_path.exists() else {'pending': []}
                pending_list = list(state.get('pending', []))

                # Process explicitly queued pending deliveries first, plus any newer archived deliveries
                # whose (view, path) replaces an existing effective member with an older rank.
                candidate_versions = sorted(set(pending_list) | set(ranks), key=lambda ver: ranks[ver])
                lib_published = 0
                for ver in candidate_versions:
                    if ver in excluded:
                        if ver in pending_list:
                            pending_list.remove(ver)
                        continue
                    history = _history(folder, lib)
                    members = _flat(history[-1][2]['views'])
                    delivery = deliveries[ver]
                    ops = {
                        'set': [
                            {'view': view, 'version': ver, 'path': path}
                            for view, path in sorted(members)
                            if path in delivery['views'].get(view, [])
                            and members[(view, path)] in ranks
                            and ranks[ver] > ranks[members[(view, path)]]
                        ],
                        'remove': [],
                    }
                    if ops['set']:
                        hist, _, row = _candidate(folder, v, lib, ops, work=work)
                        res = _save(folder, lib, hist[-1][0] + 1, row, work, actor=actor, action='AUTO_UPDATE')
                        published += 1
                        lib_published += 1
                        lib_events.append({'action': 'AUTO_UPDATE', 'revision': res['revision'], 'source': ver, 'updated_files': len(ops['set'])})
                    if ver in pending_list:
                        pending_list.remove(ver)

                if state_path.exists() or pending_list != state.get('pending', []):
                    write_atomic(state_path, {'pending': pending_list})
                pending_total += len(pending_list)
                if not lib_published:
                    unchanged += 1
        except (OSError, ValueError, KeyError, TypeError) as exc:
            warnings.append(f'{v}/{lib}: L2 有效版本推进失败: {exc}')

        if lib_events:
            libraries_changed.append({'vendor': v, 'library': lib, 'events': lib_events})

    summary = {
        'layer': 'L2',
        'at': utc_text(),
        'actor': actor,
        'scope': {'vendor': vendor, 'library': library},
        'options': {'auto_init_from_formal': auto_init_from_formal},
        'initialized': initialized,
        'effective_published': published,
        'unchanged': unchanged,
        'effective_pending': pending_total,
        'libraries_changed': libraries_changed,
        'warnings': warnings,
    }
    _append_refresh_history(work, summary)
    return summary


def refresh_l3(work, *, force_verify=False, vendor=None, library=None, actor='local', progress_cb=None, cancel_event=None):
    """Layer 3: Refresh file_index.json only for libraries whose archived L1/L2 fingerprint changed."""
    from ai_lib_qor.workbench.jobs import check_cancel, emit_progress
    updated = 0
    unchanged = 0
    skipped_rebuild = 0
    failed = 0
    warnings = []
    libraries_changed = []

    targets = _target_libraries(work, vendor, library)
    total = len(targets)
    for idx, (v, lib, _) in enumerate(targets, 1):
        check_cancel(cancel_event, 'L3 索引刷新已由用户终止')
        emit_progress(progress_cb, 'L3', f'L3 校验/刷新索引 {v}/{lib} ({idx}/{total})', completed=idx - 1, total=total)
        try:
            res = refresh_index(work, v, lib, force_verify=force_verify)
            if res['state'] == 'UPDATED':
                updated += 1
                libraries_changed.append({'vendor': v, 'library': lib, 'state': 'UPDATED', 'refreshed_at': res.get('refreshed_at')})
            else:
                unchanged += 1
                if res.get('skipped_rebuild'):
                    skipped_rebuild += 1
        except (OSError, ValueError, KeyError, TypeError) as exc:
            failed += 1
            warnings.append(f'{v}/{lib}: L3 索引刷新失败: {exc}')

    summary = {
        'layer': 'L3',
        'at': utc_text(),
        'actor': actor,
        'scope': {'vendor': vendor, 'library': library},
        'options': {'force_verify': force_verify},
        'indexes_updated': updated,
        'indexes_unchanged': unchanged,
        'indexes_skipped_rebuild': skipped_rebuild,
        'indexes_failed': failed,
        'libraries_changed': libraries_changed,
        'warnings': warnings,
    }
    _append_refresh_history(work, summary)
    emit_progress(progress_cb, 'L3', f'L3 完成：更新 {updated} · 跳过重建 {skipped_rebuild}', completed=total, total=total)
    return summary


def refresh_all(work, raw_root=None, nl_root=None, *, nl_version=None, raw=True, formal=True, auto_init_from_formal=True, force_verify=False, verify_raw=False, vendor=None, library=None, actor='local', progress_cb=None, cancel_event=None):
    """Run full automated pipeline L1 -> L2 -> L3."""
    from ai_lib_qor.workbench.jobs import check_cancel
    l1 = refresh_l1(work, raw_root, nl_root, nl_version=nl_version, raw=raw, formal=formal, verify_raw=verify_raw, vendor=vendor, library=library, actor=actor, progress_cb=progress_cb, cancel_event=cancel_event)
    check_cancel(cancel_event, '三层刷新在 L2 前已由用户终止')
    l2 = refresh_l2(work, auto_init_from_formal=auto_init_from_formal, vendor=vendor, library=library, actor='automatic' if actor == 'local' else actor, progress_cb=progress_cb, cancel_event=cancel_event)
    check_cancel(cancel_event, '三层刷新在 L3 前已由用户终止')
    l3 = refresh_l3(work, force_verify=force_verify, vendor=vendor, library=library, actor=actor, progress_cb=progress_cb, cancel_event=cancel_event)
    summary = {
        'layer': 'ALL',
        'at': utc_text(),
        'actor': actor,
        'scope': {'vendor': vendor, 'library': library},
        'l1': l1,
        'l2': l2,
        'l3': l3,
        'warnings': [*l1['warnings'], *l2['warnings'], *l3['warnings']],
    }
    return summary


def refresh_status(work, *, limit=10):
    """Read-only status across L1/L2/L3 without scanning RAW or rebuilding indexes."""
    root = Path(work)
    log = root / 'refresh_history.jsonl'
    recent = []
    last_by_layer = {'L1': None, 'L2': None, 'L3': None}
    if log.is_file() and not log.is_symlink():
        try:
            lines = [line for line in log.read_text(encoding='utf-8').splitlines() if line.strip()]
            for raw_line in reversed(lines):
                item = json.loads(raw_line)
                layer = item.get('layer')
                if layer in last_by_layer and last_by_layer[layer] is None:
                    last_by_layer[layer] = item
                if len(recent) < limit:
                    recent.append(item)
                if len(recent) >= limit and all(last_by_layer.values()):
                    break
        except (OSError, ValueError, TypeError):
            pass

    libraries = []
    fresh_count = 0
    stale_count = 0
    missing_count = 0
    with_effective = 0
    total_revisions = 0
    total_deliveries = 0

    for v, lib, folder in _target_libraries(work):
        d_count = len([p for p in archive_files(folder, 'delivery', 'delivery_*.json') if not p.is_symlink()])
        f_count = len([p for p in archive_files(folder, 'formal', 'formal_*.json') if not p.is_symlink()])
        e_count = len([p for p in archive_files(folder, 'effective', f'effective_{lib}_*.json') if not p.is_symlink()])
        total_deliveries += d_count
        total_revisions += e_count
        if e_count > 0:
            with_effective += 1
        index_path = folder / 'file_index.json'
        if index_path.is_symlink() or not index_path.is_file():
            idx_state, refreshed_at = 'MISSING', None
            missing_count += 1
        else:
            matched, manifest = index_manifest_matches(work, v, lib, fast=True)
            if matched:
                idx_state, refreshed_at = 'FRESH', manifest.get('refreshed_at')
                fresh_count += 1
            else:
                idx_state = 'UNVERIFIED' if manifest is None else 'STALE'
                refreshed_at = manifest.get('refreshed_at') if manifest else None
                stale_count += 1
        latest_rev = None
        latest_eff_ptr = folder / 'latest_effective.json'
        if latest_eff_ptr.is_symlink():
            try:
                tgt = latest_eff_ptr.resolve(strict=True)
                if tgt.is_relative_to(folder.resolve()) and tgt.is_file():
                    latest_rev = json.loads(tgt.read_text(encoding='utf-8')).get('revision')
            except (OSError, ValueError, TypeError):
                latest_rev = None
        accepted_rev = None
        acc_ptr = folder / 'accepted_effective.json'
        if acc_ptr.is_symlink():
            try:
                tgt = acc_ptr.resolve(strict=True)
                if tgt.is_relative_to(folder.resolve()) and tgt.is_file():
                    accepted_rev = json.loads(tgt.read_text(encoding='utf-8')).get('revision')
            except (OSError, ValueError, TypeError):
                accepted_rev = None
        libraries.append({
            'vendor': v,
            'library': lib,
            'delivery_count': d_count,
            'formal_count': f_count,
            'revision_count': e_count,
            'latest_revision': latest_rev,
            'accepted_revision': accepted_rev,
            'index_status': idx_state,
            'index_refreshed_at': refreshed_at,
        })

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
        },
        'last_by_layer': last_by_layer,
        'recent_runs': recent,
        'libraries': libraries,
    }
