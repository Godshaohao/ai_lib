"""Effective revisions over the path-based Delivery and Formal snapshots (single-track & multi-track business IP)."""
from contextlib import nullcontext
from copy import deepcopy
import csv
import json
import os
from pathlib import Path
import re
import uuid

from ai_lib_qor.sources.layout import SAFE, archive_files, library_folder, log_file, storage_dir
from ai_lib_qor.sources.root_inventory import update_pointer
from ai_lib_qor.sources.timestamps import utc_text
from ai_lib_qor.versions.store import locked, validate, write_atomic

_WATERMARK_RE = re.compile(r'watermark=(\[[^\]]*\])')
_UNSET = object()


def _norm_business_ip(business_ip):
    if business_ip is None:
        return None
    if not isinstance(business_ip, str):
        raise ValueError('业务 IP 标识必须为字符串')
    token = business_ip.strip()
    if not token:
        return None
    if not SAFE.fullmatch(token) or token in ('.', '..') or '__' in token:
        raise ValueError(f'业务 IP 标识不安全: {token}')
    return token


def _effective_stem(library: str, business_ip=None) -> str:
    ip = _norm_business_ip(business_ip)
    return f'effective_{library}__{ip}' if ip else f'effective_{library}'


def _latest_effective_pointer(business_ip=None) -> str:
    ip = _norm_business_ip(business_ip)
    return f'latest_effective__{ip}.json' if ip else 'latest_effective.json'


def _audit_filename(business_ip=None) -> str:
    ip = _norm_business_ip(business_ip)
    return f'effective_operations__{ip}.tsv' if ip else 'effective_operations.tsv'


def _auto_state_filename(business_ip=None) -> str:
    ip = _norm_business_ip(business_ip)
    return f'.auto_effective_state__{ip}.json' if ip else '.auto_effective_state.json'


def _validate_state_payload(raw, path_desc):
    if not isinstance(raw, dict):
        raise ValueError(f'自动更新状态无效 ({path_desc})')
    allowed = {'pending', 'processed'}
    if not set(raw) <= allowed or 'pending' not in raw:
        raise ValueError(f'自动更新状态无效 ({path_desc})')
    pending = raw.get('pending', [])
    processed = raw.get('processed', [])
    if not isinstance(pending, list) or any(not isinstance(x, str) for x in pending):
        raise ValueError(f'自动更新状态 pending 无效 ({path_desc})')
    if not isinstance(processed, list) or any(not isinstance(x, str) for x in processed):
        raise ValueError(f'自动更新状态 processed 无效 ({path_desc})')
    return pending, processed


def load_auto_effective_state(folder, *, business_ip=None):
    """Load L2 auto-evolution cache from canonical log/.auto_effective_state[__<ip>].json."""
    folder = Path(folder)
    ip = _norm_business_ip(business_ip)
    fname = _auto_state_filename(ip)
    root_path = folder / fname
    log_dir = folder / 'log'
    if root_path.is_symlink() or log_dir.is_symlink():
        raise ValueError('自动更新状态不能为软链接')
    log_path = log_dir / fname
    if log_path.is_symlink():
        raise ValueError('自动更新状态不能为软链接')

    pending = []
    processed = []
    seen_p = set()
    seen_done = set()
    exists = False
    candidates = (log_path, root_path) if ip is None else (log_path,)
    for candidate in candidates:
        if candidate.is_file():
            exists = True
            raw = json.loads(candidate.read_text(encoding='utf-8'))
            p_list, d_list = _validate_state_payload(raw, candidate.name)
            for v in p_list:
                if v not in seen_p:
                    pending.append(v)
                    seen_p.add(v)
            for v in d_list:
                if v not in seen_done:
                    processed.append(v)
                    seen_done.add(v)
    return {'pending': pending, 'processed': processed, '_exists': exists, '_legacy_root': (ip is None and root_path.is_file())}


def save_auto_effective_state(folder, pending, processed, *, business_ip=None):
    """Persist L2 auto-evolution state cache canonically under log/.auto_effective_state[__<ip>].json."""
    folder = Path(folder)
    ip = _norm_business_ip(business_ip)
    fname = _auto_state_filename(ip)
    root_path = folder / fname
    if root_path.is_symlink():
        raise ValueError('自动更新状态不能为软链接')
    log_path = storage_dir(folder, 'log') / fname
    if log_path.is_symlink():
        raise ValueError('自动更新状态不能为软链接')
    dedup_pending = list(dict.fromkeys(pending))
    dedup_processed = list(dict.fromkeys(processed))
    write_atomic(log_path, {'pending': dedup_pending, 'processed': dedup_processed})
    if ip is None and root_path.is_file() and not root_path.is_symlink():
        root_path.unlink(missing_ok=True)
    return log_path


def _format_watermark_detail(detail: str, watermark_versions) -> str:
    if not watermark_versions:
        return detail
    tag = 'watermark=' + json.dumps(sorted(set(watermark_versions)), ensure_ascii=False, separators=(',', ':'))
    return f'{detail}; {tag}' if detail else tag


def derive_processed_versions(folder, library, *, history=None, business_ip=None) -> set[str]:
    """Authoritatively derive L2-processed delivery versions from immutable effective/*.json + operations audit."""
    folder = Path(folder)
    ip = _norm_business_ip(business_ip)
    derived: set[str] = set()
    hist = history if history is not None else _history(folder, library, business_ip=ip)
    for _, _, row in hist:
        for ver in _flat(row.get('views') or {}).values():
            if isinstance(ver, str) and ver:
                derived.add(ver)

    audit_path = log_file(folder, _audit_filename(ip))
    if audit_path.is_symlink():
        raise ValueError('操作审计不能为软链接')
    if audit_path.is_file():
        with audit_path.open(encoding='utf-8', newline='') as stream:
            for rec in csv.DictReader(stream, delimiter='\t'):
                status = rec.get('status') or ''
                if status not in ('PUBLISHED', 'PUBLISHED_INDEX_STALE', 'RECOVERED', 'ACKNOWLEDGED'):
                    continue
                try:
                    changes = json.loads(rec.get('changes') or '[]')
                    if isinstance(changes, list):
                        for ch in changes:
                            after = ch.get('after') if isinstance(ch, dict) else None
                            if isinstance(after, str) and after:
                                derived.add(after)
                except (ValueError, TypeError):
                    pass
                detail = rec.get('detail') or ''
                for match in _WATERMARK_RE.finditer(detail):
                    try:
                        items = json.loads(match.group(1))
                        if isinstance(items, list):
                            for ver in items:
                                if isinstance(ver, str) and ver:
                                    derived.add(ver)
                    except (ValueError, TypeError):
                        pass
    return derived


def record_l2_acknowledged(folder, library, version: str, *, actor='automatic', revision='', business_ip=None):
    """Append an immutable audit acknowledgment for an L2 delivery that required no member updates."""
    _audit(
        folder,
        uuid.uuid4().hex,
        actor,
        'AUTO_ACK',
        revision,
        revision,
        'ACKNOWLEDGED',
        [],
        _format_watermark_detail('', [version]),
        business_ip=business_ip,
    )


def _compute_manual_watermark(folder, work, vendor, library, *, business_ip=None, allowed_versions=None) -> list[str]:
    from .path_config import excluded_versions
    deliveries = _deliveries(folder, vendor, library)
    excluded = excluded_versions(work, vendor, library) if work is not None else set()
    state = load_auto_effective_state(folder, business_ip=business_ip)
    pending_set = set(state['pending'])
    allowed = set(allowed_versions) if allowed_versions is not None else None
    return sorted(
        ver for ver in deliveries
        if ver not in pending_set and ver not in excluded and (allowed is None or ver in allowed)
    )


def _sync_watermark_cache(folder, watermark_versions, *, business_ip=None):
    state = load_auto_effective_state(folder, business_ip=business_ip)
    processed = list(state['processed'])
    processed_set = set(processed)
    changed = False
    for ver in watermark_versions:
        if ver not in processed_set:
            processed.append(ver)
            processed_set.add(ver)
            changed = True
    if changed or state['_legacy_root']:
        save_auto_effective_state(folder, state['pending'], processed, business_ip=business_ip)


def _deliveries(folder, vendor, library):
    from ai_lib_qor.sources.minimal_delivery import is_delivery_minimal
    from ai_lib_qor.versions.store import read_json_readonly
    result = {}
    for path in archive_files(folder, 'delivery', 'delivery_*.json'):
        if path.is_symlink():
            raise ValueError('交付文件不能是软链接')
        item = read_json_readonly(path, 'delivery_minimal')
        if not is_delivery_minimal(item) or (item['vendor'], item['library']) != (vendor, library):
            raise ValueError('交付格式或来源范围不正确')
        if item['version'] in result:
            raise ValueError('来源版本不唯一')
        result[item['version']] = item
    return result


def _history(folder, library, *, business_ip=None):
    from ai_lib_qor.versions.store import read_json_readonly
    ip = _norm_business_ip(business_ip)
    stem = _effective_stem(library, ip)
    regex = re.compile(r'^' + re.escape(stem) + r'_(\d+)\.json$')
    rows = []
    for path in archive_files(folder, 'effective', stem + '_*.json'):
        match = regex.fullmatch(path.name)
        if not match:
            continue
        if path.is_symlink():
            raise ValueError('有效版本不能是软链接')
        row = read_json_readonly(path, 'effective_path')
        if row.get('revision') != f'rev_{int(match.group(1)):04d}':
            raise ValueError('有效版本与文件名不一致')
        if row.get('business_ip') != ip:
            raise ValueError('有效版本与业务 IP 轨道不一致')
        rows.append((int(match.group(1)), path, row))
    rows.sort()
    if [r[0] for r in rows] != list(range(1, len(rows) + 1)):
        raise ValueError('有效版本序列不连续')
    return rows


def fast_library_track_revisions(folder, library: str) -> tuple[dict[str | None, list[str]], dict[str | None, str | None]]:
    """Single-pass os.scandir extraction of revisions & accepted_revision per track (zero JSON reads).

    Returns `(revisions_by_ip, accepted_by_ip)` where key is `business_ip` (str) or `None` (single-track).
    """
    folder = Path(folder)
    revs_num: dict[str | None, list[int]] = {}
    multi_re = re.compile(rf'^effective_{re.escape(library)}__([A-Za-z0-9][A-Za-z0-9_.-]{{0,127}})_(\d+)\.json\Z')
    single_re = re.compile(rf'^effective_{re.escape(library)}_(\d+)\.json\Z')

    eff_dirs = [folder / 'effective', folder]
    seen_names: set[str] = set()
    for d in eff_dirs:
        if d.is_symlink() or not d.is_dir():
            continue
        try:
            with os.scandir(d) as it:
                for entry in it:
                    name = entry.name
                    if name in seen_names or not name.startswith(f'effective_{library}_') or not name.endswith('.json'):
                        continue
                    if entry.is_symlink() or not entry.is_file(follow_symlinks=False):
                        continue
                    seen_names.add(name)
                    m_tr = multi_re.fullmatch(name)
                    if m_tr and '__' not in m_tr.group(1):
                        revs_num.setdefault(m_tr.group(1), []).append(int(m_tr.group(2)))
                        continue
                    m_sg = single_re.fullmatch(name)
                    if m_sg:
                        revs_num.setdefault(None, []).append(int(m_sg.group(1)))
        except OSError:
            continue

    revisions_by_ip: dict[str | None, list[str]] = {
        ip: [f'rev_{n:04d}' for n in sorted(nums)]
        for ip, nums in revs_num.items()
    }

    accepted_by_ip: dict[str | None, str | None] = {}
    acc_multi_re = re.compile(r'^accepted_effective__([A-Za-z0-9][A-Za-z0-9_.-]{0,127})\.json\Z')
    folder_resolved = folder.resolve()
    try:
        with os.scandir(folder) as it:
            for entry in it:
                name = entry.name
                if not name.startswith('accepted_effective') or not name.endswith('.json'):
                    continue
                if not entry.is_symlink():
                    continue
                if name == 'accepted_effective.json':
                    acc_ip = None
                else:
                    m_acc = acc_multi_re.fullmatch(name)
                    if not m_acc or '__' in m_acc.group(1):
                        continue
                    acc_ip = m_acc.group(1)
                try:
                    ptr_path = Path(entry.path)
                    target = ptr_path.resolve(strict=True)
                    if not target.is_relative_to(folder_resolved) or not target.is_file():
                        continue
                    tname = target.name
                    m_tr = multi_re.fullmatch(tname)
                    m_sg = single_re.fullmatch(tname) if not m_tr else None
                    if acc_ip is not None and m_tr and m_tr.group(1) == acc_ip:
                        accepted_by_ip[acc_ip] = f'rev_{int(m_tr.group(2)):04d}'
                    elif acc_ip is None and m_sg:
                        accepted_by_ip[None] = f'rev_{int(m_sg.group(1)):04d}'
                    else:
                        from ai_lib_qor.versions.store import read_json_readonly
                        row = read_json_readonly(target)
                        if isinstance(row, dict) and row.get('library') == library and row.get('business_ip') == acc_ip:
                            accepted_by_ip[acc_ip] = row.get('revision')
                except (OSError, ValueError, TypeError):
                    continue
    except OSError:
        pass
    return revisions_by_ip, accepted_by_ip


def list_track_effective_ips(folder, library) -> list[str]:
    """Discover all business IP tracks that have at least one saved multi-track Effective JSON."""
    prefix = f'effective_{library}__'
    regex = re.compile(r'^' + re.escape(prefix) + r'([A-Za-z0-9][A-Za-z0-9_.-]{0,127})_(\d+)\.json$')
    ips = set()
    for path in archive_files(folder, 'effective', prefix + '*.json'):
        if path.is_symlink() or not path.is_file():
            continue
        m = regex.fullmatch(path.name)
        if m and '__' not in m.group(1):
            ips.add(m.group(1))
    return sorted(ips)


def _make(vendor, library, number, views, *, business_ip=None, ip_type=None):
    ip = _norm_business_ip(business_ip)
    row = {
        'vendor': vendor,
        'library': library,
        'revision': f'rev_{number:04d}',
        'created_at': utc_text(),
        'views': {
            view: {ver: sorted(paths) for ver, paths in sorted(versions.items()) if paths}
            for view, versions in sorted(views.items())
            if any(versions.values())
        },
    }
    if ip is not None:
        row['business_ip'] = ip
        row['ip_type'] = ip_type
        row['track_id'] = f'{vendor}/{library}::{ip}'
    return row


def _audit(folder, operation, actor, action, parent, revision, status, changes, detail='', *, business_ip=None):
    if not isinstance(actor, str) or not actor.strip() or len(actor) > 128:
        raise ValueError('操作来源无效')
    path = log_file(folder, _audit_filename(business_ip))
    if path.is_symlink():
        raise ValueError('操作审计不能为软链接')
    new = not path.exists()
    with path.open('a', encoding='utf-8', newline='') as stream:
        writer = csv.writer(stream, delimiter='\t', lineterminator='\n')
        if new:
            writer.writerow(['operation', 'time', 'actor', 'action', 'parent', 'revision', 'status', 'changes', 'detail'])
        writer.writerow([operation, utc_text(), actor, action, parent or '', revision, status, json.dumps(changes, ensure_ascii=False, sort_keys=True), detail])
        stream.flush()
        os.fsync(stream.fileno())


def _audit_recover(folder, revision, *, business_ip=None):
    path = log_file(folder, _audit_filename(business_ip))
    if path.is_symlink():
        raise ValueError('操作审计不能为软链接')
    if not path.is_file():
        return
    with path.open(encoding='utf-8', newline='') as stream:
        rows = [x for x in csv.DictReader(stream, delimiter='\t') if x.get('revision') == revision]
    if rows and rows[-1].get('status') in ('INTENT', 'INTERRUPTED'):
        item = rows[-1]
        _audit(
            folder,
            item['operation'],
            item['actor'],
            item['action'],
            item['parent'],
            revision,
            'RECOVERED',
            json.loads(item['changes']),
            '已修复指针并刷新索引',
            business_ip=business_ip,
        )


def _save(folder, library, number, row, work, *, actor='local', action='update', refresh_idx=True, watermark_versions=None, business_ip=None, parent_row=_UNSET):
    ip = _norm_business_ip(business_ip if business_ip is not None else row.get('business_ip'))
    validate(row, 'effective_path')
    stem = _effective_stem(library, ip)
    target = storage_dir(folder, 'effective') / f'{stem}_{number:03d}.json'
    if parent_row is _UNSET:
        history = _history(folder, library, business_ip=ip)
        parent = history[-1][2] if history else None
    else:
        parent = parent_row
    before = _flat(parent['views']) if parent else {}
    after = _flat(row['views'])
    changes = [
        {'view': v, 'path': p, 'before': before.get((v, p)), 'after': after.get((v, p))}
        for v, p in sorted(before.keys() | after.keys())
        if before.get((v, p)) != after.get((v, p))
    ]
    operation = uuid.uuid4().hex
    parent_rev = parent['revision'] if parent else None
    _audit(folder, operation, actor, action, parent_rev, row['revision'], 'INTENT', changes, business_ip=ip)
    try:
        write_atomic(target, row, immutable=True)
        update_pointer(folder, _latest_effective_pointer(ip), str(target.relative_to(folder)))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        _audit(folder, operation, actor, action, parent_rev, row['revision'], 'INTERRUPTED', changes, str(exc), business_ip=ip)
        raise
    result = {'state': 'PUBLISHED', 'revision': row['revision'], 'path': str(target)}
    if ip is not None:
        result['business_ip'] = ip
        result['track_id'] = row.get('track_id')
    if refresh_idx and ip is None:
        try:
            from .minimal_file_index import refresh_index_locked
            result['index'] = refresh_index_locked(work, row['vendor'], library)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            result.update(state='PUBLISHED_INDEX_STALE', index_error=str(exc))
    detail = _format_watermark_detail(result.get('index_error', ''), watermark_versions)
    _audit(folder, operation, actor, action, parent_rev, row['revision'], result['state'], changes, detail, business_ip=ip)
    return result


def _track_allowed_versions(work, vendor, library, business_ip):
    """If multi-track partition defines tracks for business_ip, return set of allowed delivery versions (or None)."""
    ip = _norm_business_ip(business_ip)
    if ip is None or work is None:
        return None
    from .ip_partition import load_partition
    part = load_partition(work, vendor, library)
    if part is None or ip not in part['tracks']:
        return None
    return set(part['tracks'][ip])


def initialize_from_formal(
    work,
    vendor,
    library,
    formal_path,
    *,
    include=None,
    actor='local',
    refresh_idx=True,
    business_ip=None,
    ip_type=None,
    allowed_versions=None,
    _folder_locked=False,
):
    ip = _norm_business_ip(business_ip)
    folder = library_folder(work, vendor, library)
    lock_ctx = nullcontext() if _folder_locked else locked(folder)
    with lock_ctx:
        path = Path(formal_path)
        if (folder / 'formal').is_symlink() or path.is_symlink() or not path.is_file() or path.parent.resolve() not in (folder.resolve(), (folder / 'formal').resolve()):
            raise ValueError('正式快照必须为当前库的普通文件')
        formal = json.loads(path.read_text(encoding='utf-8'))
        validate(formal, 'formal_path')
        if set(formal) != {'version', 'vendor', 'library', 'root', 'observed_at', 'views'} or (formal['vendor'], formal['library']) != (vendor, library):
            raise ValueError('正式快照格式或归属不匹配')
        deliveries = _deliveries(folder, vendor, library)
        allowed = set(allowed_versions) if allowed_versions is not None else _track_allowed_versions(work, vendor, library, ip)
        views = {}
        matched = set()
        selected = set(include) if include is not None else None
        if selected is not None and (not selected or len(selected) != len(include)):
            raise ValueError('初始成员选择为空或重复')
        for view, versions in formal['views'].items():
            for version, links in versions.items():
                if allowed is not None and version not in allowed:
                    continue
                if version not in deliveries:
                    raise ValueError('正式来源版本不存在')
                delivery = deliveries[version]
                root = Path(delivery['root'])
                for link in links:
                    resolved = Path(link.get('raw_path', link['resolved']))
                    if not root.is_absolute() or not resolved.is_absolute() or not resolved.is_relative_to(root):
                        raise ValueError('正式目标不在来源版本内')
                    raw = resolved.relative_to(root).as_posix()
                    if raw not in delivery['views'].get(view, []):
                        raise ValueError('正式目标不在对应的交付 View 中')
                    if selected is not None and (view, raw) not in selected:
                        continue
                    if (view, raw) in matched:
                        raise ValueError('正式来源中同一文件位有多个版本，请先处理来源冲突')
                    matched.add((view, raw))
                    bucket = views.setdefault(view, {}).setdefault(version, [])
                    if raw in bucket:
                        raise ValueError('多个正式链接指向同一个 RAW 成员')
                    bucket.append(raw)
        if not views or (selected is not None and selected != matched):
            raise ValueError('初始成员不在正式来源中或不唯一')
        row = _make(vendor, library, 1, views, business_ip=ip, ip_type=ip_type)
        history = _history(folder, library, business_ip=ip)
        if history:
            if history[0][2]['views'] == row['views']:
                res = {'state': 'UNCHANGED', 'revision': history[-1][2]['revision']}
                if ip is not None:
                    res['business_ip'] = ip
                return res
            raise ValueError('有效版本已初始化，不覆盖历史')
        return _save(folder, library, 1, row, work, actor=actor, action='INITIALIZE', refresh_idx=refresh_idx, business_ip=ip)


def initialize_from_deliveries(
    work,
    vendor,
    library,
    versions,
    *,
    business_ip=None,
    ip_type=None,
    actor='local',
    refresh_idx=True,
    _folder_locked=False,
):
    """Initialize rev_0001 by chronologically folding one or more ordered delivery versions (A+ non-Formal init).

    Later versions in `versions` override earlier versions for the same (view, path), add new paths,
    and inherit untouched paths from earlier versions. All folded versions are recorded in the immutable
    audit watermark so L2 never replays them, while newer tail deliveries evolve naturally into rev_0002+.
    """
    from .path_config import excluded_versions, ignored_unadopted_files
    if not isinstance(versions, (list, tuple)) or not versions or any(not isinstance(v, str) or not v for v in versions):
        raise ValueError('初始化交付版本列表不能为空')
    if len(set(versions)) != len(versions):
        raise ValueError('初始化交付版本列表存在重复版本')
    ip = _norm_business_ip(business_ip)
    folder = library_folder(work, vendor, library)
    lock_ctx = nullcontext() if _folder_locked else locked(folder)
    with lock_ctx:
        deliveries = _deliveries(folder, vendor, library)
        excluded = excluded_versions(work, vendor, library)
        ignored = ignored_unadopted_files(work, vendor, library)
        members: dict[tuple[str, str], str] = {}
        for version in versions:
            if version not in deliveries:
                raise ValueError(f'来源版本不存在: {version}')
            if version in excluded:
                raise ValueError(f'来源版本已被排除: {version}')
            delivery = deliveries[version]
            for view, paths in sorted((delivery.get('views') or {}).items()):
                for rel in sorted(paths):
                    if (view, rel) not in ignored:
                        members[(view, rel)] = version
        views: dict[str, dict[str, list[str]]] = {}
        for (view, rel), ver in sorted(members.items()):
            views.setdefault(view, {}).setdefault(ver, []).append(rel)
        if not views:
            raise ValueError(f'来源版本不含可初始化成员: {", ".join(versions)}')
        row = _make(vendor, library, 1, views, business_ip=ip, ip_type=ip_type)
        history = _history(folder, library, business_ip=ip)
        if history:
            if history[0][2]['views'] == row['views']:
                res = {'state': 'UNCHANGED', 'revision': history[-1][2]['revision']}
                if ip is not None:
                    res['business_ip'] = ip
                return res
            raise ValueError('有效版本已初始化，不覆盖历史')
        return _save(
            folder,
            library,
            1,
            row,
            work,
            actor=actor,
            action='INITIALIZE_DELIVERY',
            refresh_idx=refresh_idx,
            watermark_versions=list(versions),
            business_ip=ip,
        )


def initialize_from_delivery(
    work,
    vendor,
    library,
    version,
    *,
    business_ip=None,
    ip_type=None,
    actor='local',
    refresh_idx=True,
    _folder_locked=False,
):
    """Initialize rev_0001 from a single delivery version."""
    return initialize_from_deliveries(
        work,
        vendor,
        library,
        [version],
        business_ip=business_ip,
        ip_type=ip_type,
        actor=actor,
        refresh_idx=refresh_idx,
        _folder_locked=_folder_locked,
    )


def _candidate(
    folder,
    vendor,
    library,
    operations,
    expected_parent=None,
    work=None,
    *,
    business_ip=None,
    ip_type=None,
    allowed_versions=None,
    history=None,
    deliveries=None,
    excluded=None,
):
    ip = _norm_business_ip(business_ip)
    if not isinstance(operations, dict) or set(operations) != {'set', 'remove'} or not isinstance(operations['set'], list) or not isinstance(operations['remove'], list):
        raise ValueError('操作必须包含 set 与 remove 数组')
    if history is None:
        history = _history(folder, library, business_ip=ip)
    if not history:
        raise ValueError('需要先初始化有效版本')
    last = history[-1][2]
    if expected_parent is not None and last['revision'] != expected_parent:
        raise ValueError('父版本已变化，请重新预览')
    if deliveries is None:
        deliveries = _deliveries(folder, vendor, library)
    views = deepcopy(last['views'])
    touched = set()
    if excluded is None:
        from .path_config import excluded_versions
        excluded = excluded_versions(work, vendor, library) if work is not None else set()
    allowed = set(allowed_versions) if allowed_versions is not None else _track_allowed_versions(work, vendor, library, ip)
    eff_ip_type = ip_type if ip_type is not None else last.get('ip_type')
    for item in operations['set']:
        if not isinstance(item, dict) or set(item) != {'view', 'version', 'path'}:
            raise ValueError('set 需要 view、version、path')
        view, version, path = item['view'], item['version'], item['path']
        key = (view, path)
        if key in touched:
            raise ValueError('操作包含重复成员')
        touched.add(key)
        if version in excluded:
            raise ValueError('来源版本已被排除')
        if allowed is not None and version not in allowed:
            raise ValueError(f'来源版本 {version} 不属于业务 IP 轨道 {ip}')
        if version not in deliveries or path not in deliveries[version]['views'].get(view, []):
            raise ValueError('所选路径不在对应交付中')
        bucket = views.setdefault(view, {})
        for paths in bucket.values():
            if path in paths:
                paths.remove(path)
        bucket.setdefault(version, []).append(path)
    for item in operations['remove']:
        if not isinstance(item, dict) or set(item) != {'view', 'path'}:
            raise ValueError('remove 需要 view、path')
        key = (item['view'], item['path'])
        if key in touched:
            raise ValueError('操作包含重复成员')
        touched.add(key)
        for paths in views.get(item['view'], {}).values():
            if item['path'] in paths:
                paths.remove(item['path'])
    row = _make(vendor, library, history[-1][0] + 1, views, business_ip=ip, ip_type=eff_ip_type)
    return history, last, row


def _flat(views):
    return {(view, path): version for view, versions in views.items() for version, paths in versions.items() for path in paths}


def preview_update(work, vendor, library, operations, *, business_ip=None):
    ip = _norm_business_ip(business_ip)
    folder = library_folder(work, vendor, library)
    with locked(folder):
        _, last, row = _candidate(folder, vendor, library, operations, work=work, business_ip=ip)
        before = _flat(last['views'])
        after = _flat(row['views'])
        changes = [
            {'view': key[0], 'path': key[1], 'before': before.get(key), 'after': after.get(key)}
            for key in sorted(before.keys() | after.keys())
            if before.get(key) != after.get(key)
        ]
        out = {'parent': last['revision'], 'changes': changes, 'views': row['views']}
        if ip is not None:
            out['business_ip'] = ip
        return out


def apply_update(work, vendor, library, operations, *, expected_parent, actor='local', business_ip=None):
    ip = _norm_business_ip(business_ip)
    folder = library_folder(work, vendor, library)
    with locked(folder):
        try:
            history, last, row = _candidate(folder, vendor, library, operations, expected_parent, work, business_ip=ip)
        except (ValueError, KeyError, TypeError) as exc:
            _audit(folder, uuid.uuid4().hex, actor, 'UPDATE', expected_parent, '', 'REJECTED', [], str(exc), business_ip=ip)
            raise
        if row['views'] == last['views']:
            _audit(folder, uuid.uuid4().hex, actor, 'UPDATE', last['revision'], last['revision'], 'UNCHANGED', [], business_ip=ip)
            return {'state': 'UNCHANGED', 'revision': last['revision']}
        allowed = _track_allowed_versions(work, vendor, library, ip)
        watermark = _compute_manual_watermark(folder, work, vendor, library, business_ip=ip, allowed_versions=allowed)
        res = _save(folder, library, history[-1][0] + 1, row, work, actor=actor, action='UPDATE', watermark_versions=watermark, business_ip=ip)
        _sync_watermark_cache(folder, watermark, business_ip=ip)
    from .catalog_projection import sync_library_projection
    sync_library_projection(work, vendor, library)
    return res


def update_effective(work, vendor, library, operations, *, actor='local', business_ip=None):
    ip = _norm_business_ip(business_ip)
    folder = library_folder(work, vendor, library)
    with locked(folder):
        try:
            history, last, row = _candidate(folder, vendor, library, operations, work=work, business_ip=ip)
        except (ValueError, KeyError, TypeError) as exc:
            _audit(folder, uuid.uuid4().hex, actor, 'UPDATE', None, '', 'REJECTED', [], str(exc), business_ip=ip)
            raise
        if row['views'] == last['views']:
            _audit(folder, uuid.uuid4().hex, actor, 'UPDATE', last['revision'], last['revision'], 'UNCHANGED', [], business_ip=ip)
            return {'state': 'UNCHANGED', 'revision': last['revision']}
        allowed = _track_allowed_versions(work, vendor, library, ip)
        watermark = _compute_manual_watermark(folder, work, vendor, library, business_ip=ip, allowed_versions=allowed)
        res = _save(folder, library, history[-1][0] + 1, row, work, actor=actor, action='UPDATE', watermark_versions=watermark, business_ip=ip)
        _sync_watermark_cache(folder, watermark, business_ip=ip)
    from .catalog_projection import sync_library_projection
    sync_library_projection(work, vendor, library)
    return res


def preview_delivery(work, vendor, library, version, *, business_ip=None, include_new=True):
    """Preview advancing the latest effective revision with this delivery (upgrades existing members and optionally merges new paths)."""
    ip = _norm_business_ip(business_ip)
    folder = library_folder(work, vendor, library)
    with locked(folder):
        history = _history(folder, library, business_ip=ip)
        deliveries = _deliveries(folder, vendor, library)
        if not history:
            raise ValueError('需要先初始化有效版本')
        if version not in deliveries:
            raise ValueError('来源版本不存在')
        from .path_config import excluded_versions, ignored_unadopted_files
        if version in excluded_versions(work, vendor, library):
            raise ValueError('来源版本已被排除')
        old = _flat(history[-1][2]['views'])
        delivery = deliveries[version]
        ignored = ignored_unadopted_files(work, vendor, library)
        ops_set = [
            {'view': v, 'version': version, 'path': p}
            for v, p in sorted(old)
            if p in delivery['views'].get(v, []) and old[(v, p)] != version
        ]
        if include_new:
            for v, paths in sorted((delivery.get('views') or {}).items()):
                for p in sorted(paths):
                    if (v, p) not in old and (v, p) not in ignored:
                        ops_set.append({'view': v, 'version': version, 'path': p})
        operations = {'set': ops_set, 'remove': []}
        _, last, row = _candidate(folder, vendor, library, operations, work=work, business_ip=ip)
        after = _flat(row['views'])
        changes = [
            {'view': v, 'path': p, 'before': old.get((v, p)), 'after': after.get((v, p))}
            for v, p in sorted(old.keys() | after.keys())
            if old.get((v, p)) != after.get((v, p))
        ]
        return {'parent': last['revision'], 'changes': changes, 'views': row['views'], 'operations': operations}


def restore_issues(work, vendor, library, views):
    from .path_config import excluded_versions
    folder = library_folder(work, vendor, library)
    deliveries = _deliveries(folder, vendor, library)
    excluded = excluded_versions(work, vendor, library)
    issues = []
    for (view, path), version in sorted(_flat(views).items()):
        if version in excluded:
            issues.append(f'已排除来源：{version} · {path}')
        delivery = deliveries.get(version)
        if not delivery or path not in delivery['views'].get(view, []):
            issues.append(f'来源交付不可用：{version} · {path}')
            continue
        absolute = Path(delivery['root']) / path
        if not absolute.is_file():
            issues.append(f'来源文件不可用：{absolute}')
    return sorted(issues)


def restore_revision(work, vendor, library, revision, *, expected_parent, actor='local', expected_issues=None, business_ip=None):
    ip = _norm_business_ip(business_ip)
    folder = library_folder(work, vendor, library)
    with locked(folder):
        history = _history(folder, library, business_ip=ip)
        if not history or history[-1][2]['revision'] != expected_parent:
            _audit(folder, uuid.uuid4().hex, actor, 'RESTORE:' + str(revision), expected_parent, '', 'REJECTED', [], '父版本已变化', business_ip=ip)
            raise ValueError('父版本已变化，请重新选择')
        matches = [item[2] for item in history if item[2]['revision'] == revision]
        if len(matches) != 1:
            _audit(folder, uuid.uuid4().hex, actor, 'RESTORE:' + str(revision), expected_parent, '', 'REJECTED', [], '有效版本不存在', business_ip=ip)
            raise ValueError('有效版本不存在')
        if expected_issues is not None and restore_issues(work, vendor, library, matches[0]['views']) != expected_issues:
            _audit(folder, uuid.uuid4().hex, actor, 'RESTORE:' + str(revision), expected_parent, '', 'REJECTED', [], '来源状态已变化', business_ip=ip)
            raise ValueError('来源状态已变化，请重新预览')
        row = _make(vendor, library, history[-1][0] + 1, matches[0]['views'], business_ip=ip, ip_type=history[-1][2].get('ip_type'))
        if row['views'] == history[-1][2]['views']:
            _audit(folder, uuid.uuid4().hex, actor, 'RESTORE:' + str(revision), expected_parent, expected_parent, 'UNCHANGED', [], business_ip=ip)
            return {'state': 'UNCHANGED', 'revision': expected_parent}
        allowed = _track_allowed_versions(work, vendor, library, ip)
        watermark = _compute_manual_watermark(folder, work, vendor, library, business_ip=ip, allowed_versions=allowed)
        res = _save(folder, library, history[-1][0] + 1, row, work, actor=actor, action='RESTORE:' + revision, watermark_versions=watermark, business_ip=ip)
        _sync_watermark_cache(folder, watermark, business_ip=ip)
    from .catalog_projection import sync_library_projection
    sync_library_projection(work, vendor, library)
    return res
