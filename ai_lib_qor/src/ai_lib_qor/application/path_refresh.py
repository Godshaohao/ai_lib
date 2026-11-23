"""Layered three-stage data refresh orchestration: L1 (RAW/NL) -> L2 (Effective) -> L3 (FileIndex)."""
import json
import os
from pathlib import Path

from ai_lib_qor.sources.layout import SAFE, archive_files, library_folder
from ai_lib_qor.sources.root_inventory import inventory_sources, update_pointer
from ai_lib_qor.sources.timestamps import instant, utc_text
from ai_lib_qor.versions.runtime import check_cancel, emit_progress
from ai_lib_qor.versions.store import locked, write_atomic
from .minimal_effective import (
    _audit_recover,
    _candidate,
    _deliveries,
    _flat,
    _history,
    _save,
    derive_processed_versions,
    initialize_from_formal,
    load_auto_effective_state,
    record_l2_acknowledged,
    save_auto_effective_state,
)
from .minimal_file_index import (
    _configured_times,
    _ignored_unadopted_digest,
    _ordered,
    index_manifest_matches,
    refresh_index,
    refresh_index_locked,
)
from .path_config import excluded_versions, load_path_config, registration_times, update_options
from .path_query import unadopted_new_files


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


def _enqueue_pending_locked(folder, library, new_versions):
    """Queue newly archived delivery versions into canonical log/.auto_effective_state.json when Effective already exists."""
    if not new_versions:
        return
    history = _history(folder, library)
    if not history:
        return
    state = load_auto_effective_state(folder)
    pending = list(state['pending'])
    processed = list(state['processed'])
    changed = False
    for ver in new_versions:
        if ver not in pending:
            pending.append(ver)
            changed = True
        if ver in processed:
            processed.remove(ver)
            changed = True
    if changed or state['_legacy_root']:
        save_auto_effective_state(folder, pending, processed)


def _evolve_library_l2_locked(
    work,
    folder,
    vendor,
    library,
    *,
    actor='automatic',
    only_pending=False,
    defer_index=True,
):
    """Single canonical L2 auto-evolution engine (caller holds locked(folder))."""
    history = _history(folder, library)
    if not history:
        return {'published': 0, 'events': [], 'pending_count': 0, 'index_refreshed': False, 'error': None}

    update_pointer(folder, 'latest_effective.json', str(history[-1][1].relative_to(folder)))
    _audit_recover(folder, history[-1][2]['revision'])

    deliveries = _deliveries(folder, vendor, library)
    state = load_auto_effective_state(folder)
    pending_list = list(state['pending'])
    processed_list = list(state['processed'])
    if not deliveries:
        return {'published': 0, 'events': [], 'pending_count': len(pending_list), 'index_refreshed': False, 'error': None}

    ordered = _ordered(list(deliveries.values()), _configured_times(work, vendor, library))
    ranks = {d['version']: n for n, d in enumerate(ordered)}
    if any(v not in ranks for v in pending_list):
        raise ValueError('待处理交付尚未完成登记')

    excluded = excluded_versions(work, vendor, library)
    derived_processed = derive_processed_versions(folder, library, history=history)
    processed_set = (set(processed_list) | derived_processed) - set(pending_list)
    processed_list = list(dict.fromkeys([*processed_list, *sorted(derived_processed - set(pending_list))]))
    if only_pending:
        candidates = sorted(set(pending_list), key=lambda ver: ranks[ver])
    else:
        # Authoritative high-watermark rule: derive processed versions from immutable effective/*.json +
        # effective_operations.tsv (with .auto_effective_state.json as cache), so manual restore_revision /
        # apply_update pins survive even if .auto_effective_state.json is missing or deleted.
        unprocessed = set(ranks) - processed_set
        candidates = sorted((set(pending_list) | unprocessed) & set(ranks), key=lambda ver: ranks[ver])

    published = 0
    events = []
    for ver in candidates:
        if ver in excluded:
            if ver in pending_list:
                pending_list.remove(ver)
                save_auto_effective_state(folder, pending_list, processed_list)
            continue
        history = _history(folder, library)
        update_pointer(folder, 'latest_effective.json', str(history[-1][1].relative_to(folder)))
        _audit_recover(folder, history[-1][2]['revision'])
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
            hist, _, row = _candidate(folder, vendor, library, ops, work=work)
            res = _save(
                folder,
                library,
                hist[-1][0] + 1,
                row,
                work,
                actor=actor,
                action='AUTO_UPDATE',
                refresh_idx=not defer_index,
                watermark_versions=[ver],
            )
            published += 1
            events.append({'action': 'AUTO_UPDATE', 'revision': res['revision'], 'source': ver, 'updated_files': len(ops['set'])})
            if not defer_index and res.get('state') == 'PUBLISHED_INDEX_STALE':
                raise ValueError('有效版本已发布，但索引刷新失败: ' + res['index_error'])
        elif ver not in derived_processed:
            record_l2_acknowledged(folder, library, ver, actor=actor, revision=history[-1][2]['revision'])
            derived_processed.add(ver)
        if ver in pending_list:
            pending_list.remove(ver)
        if ver not in processed_set:
            processed_list.append(ver)
            processed_set.add(ver)
        save_auto_effective_state(folder, pending_list, processed_list)

    if state['_legacy_root'] and not candidates:
        save_auto_effective_state(folder, pending_list, processed_list)

    return {
        'published': published,
        'events': events,
        'pending_count': len(pending_list),
        'index_refreshed': False,
        'error': None,
    }


def _complete_legacy_build(
    work,
    result,
    *,
    new_deliveries_by_lib,
    touched_libraries,
    update_raw,
    update_index,
    auto_effective,
    vendor=None,
    library=None,
):
    """Unified L2/L3 completion hook for legacy build_from_roots callers (zero duplicated logic)."""
    out = Path(work)
    libs = set(touched_libraries)
    if update_index and (out / 'libraries').is_dir():
        for folder in (out / 'libraries').glob('*/*'):
            if folder.is_dir() and not folder.is_symlink() and not folder.parent.is_symlink():
                libs.add((folder.parent.name, folder.name))
    if vendor:
        libs = {key for key in libs if key == (vendor, library)}

    warnings = result['warnings']
    for v, lib in sorted(libs):
        folder = library_folder(out, v, lib)
        with locked(folder):
            _enqueue_pending_locked(folder, lib, new_deliveries_by_lib.get((v, lib), []))
            state_before = load_auto_effective_state(folder)

            index_ok = False
            if update_index:
                try:
                    index_result = refresh_index_locked(out, v, lib)
                    index_ok = True
                    result['indexes_unchanged' if index_result['state'] == 'UNCHANGED' else 'indexes_updated'] += 1
                except (OSError, ValueError, KeyError, TypeError) as exc:
                    result['indexes_failed'] += 1
                    warnings.append(f'{v}/{lib}: 文件索引未刷新: {exc}')

            if update_raw and auto_effective and update_index and index_ok and state_before['pending']:
                try:
                    evo = _evolve_library_l2_locked(
                        out,
                        folder,
                        v,
                        lib,
                        actor='automatic',
                        only_pending=True,
                        defer_index=True,
                    )
                    result['effective_published'] += evo['published']
                    if evo['published'] > 0:
                        try:
                            refresh_index_locked(out, v, lib)
                        except (OSError, ValueError, KeyError, TypeError) as exc:
                            raise ValueError('有效版本已发布，但索引刷新失败: ' + str(exc)) from exc
                except (OSError, ValueError, KeyError, TypeError) as exc:
                    warnings.append(f'{v}/{lib}: 自动发布未完成: {exc}')

            state_after = load_auto_effective_state(folder)
            if state_after['pending']:
                result['effective_pending'] += len(state_after['pending'])
                if update_raw and auto_effective and not update_index:
                    warnings.append(f'{v}/{lib}: 自动发布需要刷新索引，交付保持待处理')


def refresh_l1(work, raw_root=None, nl_root=None, *, nl_version=None, raw=None, formal=None, verify_raw=False, vendor=None, library=None, actor='local', progress_cb=None, cancel_event=None):
    """Layer 1: Scan and archive RAW deliveries and Formal NL snapshots only (incremental skip by default)."""
    config = load_path_config(work)
    options = update_options(config, update_raw=raw, update_formal=formal)
    raw, formal = options['update_raw'], options['update_formal']
    if not (raw or formal):
        raise ValueError('L1 刷新至少需要启用 RAW 或 Formal 之一')
    check_cancel(cancel_event, 'L1 刷新已终止')
    emit_progress(progress_cb, 'L1', '准备 L1 来源盘点…')
    effective_raw = raw_root if raw_root is not None else config.get('raw_root')
    effective_nl = nl_root if nl_root is not None else config.get('nl_root')
    effective_nl_ver = nl_version if nl_version is not None else (config.get('nl_version') or None)

    before = _snapshot_library_l1(work, vendor, library)
    inv = inventory_sources(
        effective_raw,
        effective_nl,
        work,
        nl_version=effective_nl_ver,
        update_raw=raw,
        update_formal=formal,
        vendor=vendor,
        library=library,
        verify_raw=verify_raw,
        registration_times_fn=registration_times,
        progress_cb=progress_cb,
        cancel_event=cancel_event,
    )
    # Queue newly discovered deliveries into canonical log/.auto_effective_state.json for libraries with Effective
    for (v, lib), new_vers in sorted(inv.get('new_deliveries_by_lib', {}).items()):
        folder = library_folder(work, v, lib)
        with locked(folder):
            _enqueue_pending_locked(folder, lib, new_vers)

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
        'source_verifications': inv['source_verifications'],
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


def refresh_l2(work, *, auto_init_from_formal=True, refresh_indexes=None, vendor=None, library=None, actor='automatic', progress_cb=None, cancel_event=None):
    """Layer 2: Auto-initialize (from Formal) and auto-evolve Effective revisions from archived L1 records."""
    initialized = 0
    published = 0
    unchanged = 0
    pending_total = 0
    unadopted_total = 0
    warnings = []
    libraries_changed = []
    libraries_with_unadopted = []
    libraries_failed = []
    indexes_refreshed = []
    if refresh_indexes is None:
        refresh_indexes = update_options(load_path_config(work))['update_index']

    targets = _target_libraries(work, vendor, library)
    total = len(targets)
    for idx, (v, lib, folder) in enumerate(targets, 1):
        check_cancel(cancel_event, 'L2 推进已由用户终止')
        emit_progress(progress_cb, 'L2', f'L2 推进有效版本 {v}/{lib} ({idx}/{total})', completed=idx - 1, total=total)
        lib_events = []
        lib_initialized = False
        try:
            with locked(folder):
                history = _history(folder, lib)
            if not history:
                if auto_init_from_formal:
                    formal_path = _latest_formal_file(folder)
                    if formal_path is not None:
                        try:
                            res = initialize_from_formal(work, v, lib, formal_path, actor=actor, refresh_idx=False)
                            if res.get('state') in ('PUBLISHED', 'PUBLISHED_INDEX_STALE'):
                                initialized += 1
                                lib_initialized = True
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
                try:
                    evo = _evolve_library_l2_locked(
                        work,
                        folder,
                        v,
                        lib,
                        actor=actor,
                        only_pending=False,
                        defer_index=True,
                    )
                except ValueError as exc:
                    warnings.append(f'{v}/{lib}: 交付顺序未确认，跳过 L2 自动演化: {exc}')
                    try:
                        pending_total += len(load_auto_effective_state(folder)['pending'])
                    except (OSError, ValueError, TypeError):
                        pass
                    evo = None
                if evo is not None:
                    published += evo['published']
                    lib_events.extend(evo['events'])
                    pending_total += evo['pending_count']
                    if not evo['published'] and not lib_initialized:
                        unchanged += 1

                if refresh_indexes and lib_events:
                    try:
                        result = refresh_index_locked(work, v, lib)
                        indexes_refreshed.append({'vendor': v, 'library': lib, 'status': result['state']})
                    except (OSError, ValueError, KeyError, TypeError) as exc:
                        libraries_failed.append({'vendor': v, 'library': lib, 'reason': str(exc)})
                        warnings.append(f'{v}/{lib}: 有效版本已发布，但索引刷新失败: {exc}')
        except (OSError, ValueError, KeyError, TypeError) as exc:
            warnings.append(f'{v}/{lib}: L2 有效版本推进失败: {exc}')

        unadopted = unadopted_new_files(work, v, lib, sample_limit=10)
        if unadopted and unadopted['count'] > 0:
            unadopted_total += unadopted['count']
            libraries_with_unadopted.append({'vendor': v, 'library': lib, **unadopted})

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
        'unadopted_new_files_total': unadopted_total,
        'libraries_with_unadopted': libraries_with_unadopted,
        'libraries_changed': libraries_changed,
        'libraries_failed': libraries_failed,
        'indexes_refreshed': indexes_refreshed,
        'indexes_failed': len(libraries_failed),
        'status': 'PARTIAL' if libraries_failed else 'SUCCEEDED',
        'warnings': warnings,
    }
    _append_refresh_history(work, summary)
    return summary


def refresh_l3(work, *, force_verify=False, vendor=None, library=None, actor='local', progress_cb=None, cancel_event=None):
    """Layer 3: Refresh file_index.json only for libraries whose archived L1/L2 fingerprint changed."""
    updated = 0
    unchanged = 0
    skipped_rebuild = 0
    warnings = []
    libraries_changed = []
    libraries_unchanged = []
    libraries_failed = []

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
                libraries_unchanged.append({'vendor': v, 'library': lib})
                if res.get('skipped_rebuild'):
                    skipped_rebuild += 1
        except (OSError, ValueError, KeyError, TypeError) as exc:
            libraries_failed.append({'vendor': v, 'library': lib, 'reason': str(exc)})
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
        'indexes_failed': len(libraries_failed),
        'status': ('FAILED' if len(libraries_failed) == total else 'PARTIAL') if libraries_failed else 'SUCCEEDED',
        'libraries_changed': libraries_changed,
        'libraries_unchanged': libraries_unchanged,
        'libraries_failed': libraries_failed,
        'warnings': warnings,
    }
    _append_refresh_history(work, summary)
    emit_progress(progress_cb, 'L3', f'L3 结束：更新 {updated} · 跳过重建 {skipped_rebuild} · 失败 {len(libraries_failed)}', completed=total, total=total)
    return summary


def refresh_all(work, raw_root=None, nl_root=None, *, nl_version=None, raw=None, formal=None, auto_effective=None, update_index=None, auto_init_from_formal=True, force_verify=False, verify_raw=False, vendor=None, library=None, actor='local', progress_cb=None, cancel_event=None):
    """Run the enabled stages of the automated pipeline L1 -> L2 -> L3."""
    config = load_path_config(work)
    options = update_options(config, update_raw=raw, update_formal=formal, auto_effective=auto_effective, update_index=update_index)
    if bool(vendor) != bool(library):
        raise ValueError('供应商和库必须同时指定')
    if vendor:
        library_folder(work, vendor, library)
    common = {'vendor': vendor, 'library': library, 'actor': actor, 'progress_cb': progress_cb, 'cancel_event': cancel_event}
    skipped = {'status': 'SKIPPED', 'warnings': []}
    l1 = {'layer': 'L1', **skipped}
    l2 = {'layer': 'L2', **skipped}
    l3 = {'layer': 'L3', **skipped}
    if options['update_raw'] or options['update_formal']:
        l1 = refresh_l1(work, raw_root, nl_root, nl_version=nl_version, raw=options['update_raw'], formal=options['update_formal'], verify_raw=verify_raw, **common)
    check_cancel(cancel_event, '三层刷新在 L2 前已由用户终止')
    if options['auto_effective']:
        l2 = refresh_l2(work, auto_init_from_formal=auto_init_from_formal, refresh_indexes=False, **{**common, 'actor': 'automatic' if actor == 'local' else actor})
    check_cancel(cancel_event, '三层刷新在 L3 前已由用户终止')
    if options['update_index']:
        l3 = refresh_l3(work, force_verify=force_verify, **common)
    return {
        'layer': 'ALL',
        'at': utc_text(),
        'actor': actor,
        'scope': {'vendor': vendor, 'library': library},
        'options': options,
        'status': l3['status'] if l3['status'] in ('FAILED', 'PARTIAL') else ('SUCCEEDED' if any(options.values()) else 'SKIPPED'),
        'indexes_failed': l3.get('indexes_failed', 0),
        'libraries_failed': l3.get('libraries_failed', []),
        'l1': l1,
        'l2': l2,
        'l3': l3,
        'warnings': [*l1['warnings'], *l2['warnings'], *l3['warnings']],
    }


def read_refresh_history(work, *, limit=10):
    """Project recorded refreshes by layer, library and observed source."""
    log = Path(work) / 'refresh_history.jsonl'
    recent = []
    last_by_layer = {'L1': None, 'L2': None, 'L3': None}
    source_verifications = {}
    index_attempts = {}
    if log.is_file() and not log.is_symlink():
        try:
            with log.open(encoding='utf-8') as stream:
                for line in stream:
                    try:
                        item = json.loads(line)
                    except ValueError:
                        continue
                    if not isinstance(item, dict) or item.get('layer') not in last_by_layer:
                        continue
                    at = item.get('at')
                    layer = item['layer']
                    last_by_layer[layer] = item
                    if limit > 0:
                        recent.append(item)
                        if len(recent) > limit:
                            recent.pop(0)
                    if layer == 'L1':
                        for evidence in item.get('source_verifications', []):
                            key = (evidence['vendor'], evidence['library'])
                            record = {**evidence, 'at': evidence.get('at') or at}
                            sources = source_verifications.setdefault(key, {})
                            raw = evidence['source'] == 'RAW'
                            source = sources if raw else sources.setdefault('FORMAL', {})
                            name = 'RAW' if raw else evidence['nl_version']
                            complete = (
                                not (evidence['versions_incomplete'] or evidence['versions_reused'])
                                if raw else evidence['status'] == 'COMPLETE'
                            )
                            previous = source.get(name, {})
                            verified_at = previous.get('verified_at')
                            if complete and record['at'] and (not verified_at or record['at'] > verified_at):
                                verified_at = record['at']
                            latest = record if (record['at'] or '') >= (previous.get('at') or '') else previous
                            source[name] = {**latest, 'verified_at': verified_at}
                    if layer in ('L2', 'L3'):
                        for field, state in (
                            ('libraries_changed' if layer == 'L3' else 'indexes_refreshed', 'UPDATED'),
                            ('libraries_unchanged', 'UNCHANGED'),
                            ('libraries_failed', 'FAILED'),
                        ):
                            for row in item.get(field, []):
                                index_attempts[(row['vendor'], row['library'])] = {'status': state, **row, 'at': at}
        except OSError:
            pass
    return list(reversed(recent)), last_by_layer, source_verifications, index_attempts


def refresh_status(work, *, limit=10):
    """Read-only status across L1/L2/L3 without scanning RAW or rebuilding indexes."""
    root = Path(work)
    recent, last_by_layer, source_verifications, index_attempts = read_refresh_history(work, limit=limit)
    libraries = []
    fresh_count = 0
    stale_count = 0
    missing_count = 0
    with_effective = 0
    total_revisions = 0
    total_deliveries = 0
    total_unadopted = 0

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
        unadopted_count = None
        if idx_state == 'FRESH' and isinstance(manifest, dict) and 'unadopted_new_files_count' in manifest:
            _, cur_ign_sha = _ignored_unadopted_digest(work, v, lib)
            if manifest.get('ignored_unadopted_sha256') == cur_ign_sha:
                unadopted_count = int(manifest['unadopted_new_files_count'])
        if unadopted_count is None:
            unadopted = unadopted_new_files(work, v, lib, sample_limit=5)
            unadopted_count = unadopted['count'] if unadopted else 0
        total_unadopted += unadopted_count
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
            'source_verifications': source_verifications.get((v, lib), {}),
            'index_attempt': index_attempts.get((v, lib)),
            'unadopted_new_files_count': unadopted_count,
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
            'unadopted_new_files': total_unadopted,
        },
        'last_by_layer': last_by_layer,
        'recent_runs': recent,
        'libraries': libraries,
    }
