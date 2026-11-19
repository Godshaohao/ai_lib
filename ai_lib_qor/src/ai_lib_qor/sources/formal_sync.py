"""Formal NL link observations (metadata only) and immutable changed snapshots."""
from __future__ import annotations

import json
import os
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from ai_lib_qor.versions.store import write_atomic


def formal_sources(work):
    if not work:
        return []
    path = Path(work) / 'formal_sources.json'
    if not path.is_file() or path.is_symlink():
        return []
    data = json.loads(path.read_text(encoding='utf-8'))['sources']
    if not isinstance(data, list) or len({x['formal_nl_id'] for x in data}) != len(data):
        raise ValueError('正式来源配置无效或重复')
    return data


def formal_history(runs, config):
    rows = []
    for path in (Path(runs) / 'formal_observations').glob('formal_*.json'):
        if path.is_symlink():
            continue
        try:
            item = json.loads(path.read_text(encoding='utf-8'))
            if item['formal_nl_id'] == config['formal_nl_id'] and item['root'] == str(Path(config['root']).resolve()):
                rows.append(item)
        except (OSError, ValueError, KeyError):
            continue
    return sorted(rows, key=lambda x: x['observed_at'], reverse=True)


def formal_history_index(runs):
    """Read each saved formal observation once for multi-source overviews."""
    result=defaultdict(list)
    for path in (Path(runs)/'formal_observations').glob('formal_*.json'):
        if path.is_symlink(): continue
        try:
            item=json.loads(path.read_text(encoding='utf-8'))
            key=(item['formal_nl_id'],item['root'])
            if not item.get('observed_at'):continue
            result[key].append(item)
        except (OSError,ValueError,KeyError,AttributeError,TypeError):continue
    for rows in result.values(): rows.sort(key=lambda r:r['observed_at'],reverse=True)
    return result


def _same_snapshot(left, right):
    """Compare link identity only; no implication of file-content equivalence."""
    relevant = lambda s: (s['coverage'], s['scope'], [
        (f['file_key'], f['link_path'], f['resolved_path'], f['source_match'], f.get('source_ref'), f.get('link_target'))
        for f in sorted(s['linked_files'], key=lambda x: x['link_path'])
    ])
    return relevant(left) == relevant(right)


def sync_formal(runs, config, deliveries, work=None):
    from lib_guard.release.inventory import inventory_directory
    allowed = config.get('libraries')
    if allowed is not None:
        from ai_lib_qor.sources.registration import SAFE
        if (not isinstance(allowed, list) or any(
                not isinstance(item, dict) or set(item) != {'vendor_id', 'source_library_id'}
                or any(not isinstance(item[k], str) or not SAFE.fullmatch(item[k])
                       for k in ('vendor_id', 'source_library_id')) for item in allowed)):
            raise ValueError('正式来源 libraries 必须为 vendor_id / source_library_id 列表')
        allowed = {(item['vendor_id'], item['source_library_id']) for item in allowed}
    root = Path(config['root']).resolve()
    now = datetime.now(timezone.utc).isoformat()
    result = {'observation_id': 'formal_' + uuid.uuid4().hex,
              'formal_nl_id': config['formal_nl_id'], 'root': str(root),
              'observed_at': now, 'status': 'COMPLETE', 'files': [], 'errors': []}
    try:
        legacy = inventory_directory(root, {'libraries': []})
        by_path = {}
        for delivery in deliveries:
            base = Path(delivery['source_root']).resolve()
            for file in delivery['files']:
                path = (base / file['relative_path']).resolve()
                if path.is_relative_to(base):
                    by_path.setdefault(str(path), []).append((delivery, file))
        for file in legacy['files']:
            status = {'链接正常': 'OK', '链接失效': 'BROKEN', '普通文件': 'REGULAR'}.get(file['link_status'], 'UNKNOWN')
            candidates = by_path.get(file['source_path'], []) if status == 'OK' else []
            source = None
            if len(candidates) == 1:
                delivery, matched = candidates[0]
                source = {'vendor': delivery['vendor_id'], 'library': delivery['source_library_id'],
                          'version': delivery['supplier_version'], 'delivery_id': delivery['delivery_id'],
                          'file_id': matched['file_id'], 'file_key': matched['file_key']}
            in_scope = source is None or allowed is None or (source['vendor'], source['library']) in allowed
            result['files'].append({
                'path': file['relative_path'], 'target': file['source_path'], 'link_status': status,
                'link_target': os.readlink(root / file['relative_path']) if status in ('OK','BROKEN') else None,
                'source_status': 'OUT_OF_SCOPE' if not in_scope else 'MATCHED_RAW' if source else 'AMBIGUOUS' if len(candidates) > 1 else 'UNKNOWN',
                'source': source,
            })
        if legacy.get('ignored_directory_links'):
            result['errors'].append('存在未扫描的目录链接')
            result['status'] = 'PARTIAL'
        if any(x['link_status'] != 'OK' for x in result['files']):
            result['status'] = 'PARTIAL'
    except (OSError, ValueError) as exc:
        result['status'] = 'FAILED'
        result['errors'].append(str(exc))

    prior = next((r for r in formal_history(runs, config) if r['status'] == 'COMPLETE'), None)
    result['previous_success_id'] = prior['observation_id'] if prior else None
    result['changes'] = None
    if prior and result['status'] == 'COMPLETE':
        old = {x['path']: x for x in prior['files']}
        new = {x['path']: x for x in result['files']}
        result['changes'] = {'added': sorted(new.keys() - old.keys()),
                             'changed': sorted(k for k in old.keys() & new.keys() if old[k]['target'] != new[k]['target'] or ('link_target' in old[k] and old[k]['link_target'] != new[k]['link_target'])),
                             'removed': sorted(old.keys() - new.keys())}

    result['snapshot_id'] = None
    result['snapshot_action'] = 'NONE'
    result['snapshot_note'] = '没有满足发布条件；扫描观察已保存'
    result['snapshots'] = []
    if work and result['status'] != 'FAILED':
        from .snapshot_builder import build_snapshot
        from .layout import library_folder, next_filename
        from ai_lib_qor.sources.registration import SAFE
        from ai_lib_qor.versions.store import locked, read_json
        groups = defaultdict(list)
        ref_owners = defaultdict(list)
        deliveries_by_library = defaultdict(list)
        for delivery in deliveries:
            deliveries_by_library[(delivery['vendor_id'], delivery['source_library_id'])].append(delivery)
            for file in delivery['files']:
                ref_owners[(delivery['source_library_id'], delivery['delivery_id'], file['file_id'])].append(delivery['vendor_id'])
        for observed in result['files']:
            if observed['source'] and observed['source_status'] == 'MATCHED_RAW':
                source = observed['source']
                groups[(source['vendor'], source['library'])].append(observed)
        previous_groups = set()
        for observed in prior.get('files', []) if prior else []:
            source = observed.get('source')
            if source and observed.get('source_status') == 'MATCHED_RAW':
                owner = (source['vendor'], source['library'])
                if allowed is None or owner in allowed:
                    previous_groups.add(owner)
        for vendor, library in sorted(previous_groups - set(groups)):
            result['snapshots'].append({'vendor':vendor, 'library':library, 'snapshot_id':None,
                                        'action':'NONE', 'note':'本次无唯一归属链接；保留历史，未推断删除'})
        inventory_paths = {f['path'] for f in result['files']}
        for (vendor, library), observed_files in sorted(groups.items()):
            row = {'vendor': vendor, 'library': library, 'snapshot_id': None, 'action': 'NONE', 'note': ''}
            result['snapshots'].append(row)
            try:
                nl = config['formal_nl_id']
                if any(not isinstance(x, str) or not SAFE.fullmatch(x) or x in ('.', '..') for x in (nl, vendor, library)):
                    raise ValueError('正式库或来源库标识不安全')
                base = Path(work).resolve(strict=True)
                if base.is_relative_to(root):
                    raise ValueError('工作目录不能位于正式来源内')
                folder = library_folder(base,vendor,library)
                legacy_folder = base/'vendors'/vendor/'libraries'/library/'formal_nl'/nl/'snapshots'
                keys = [f['source']['file_key'] for f in observed_files if f['source']['file_key']]
                if len(keys) != len(set(keys)):
                    raise ValueError('同一来源库的正式文件位存在冲突')
                if any(len(ref_owners[(library, f['source']['delivery_id'], f['source']['file_id'])]) != 1
                       for f in observed_files if f['source']['file_key']):
                    raise ValueError('跨供应商交付引用不唯一')
                if legacy.get('ignored_directory_links'):
                    raise ValueError('不支持目录符号链接，请明确展开扫描范围')
                with locked(folder):
                    snapshots = []
                    paths=list(folder.glob(f'formal_{nl}_*.json'))
                    paths.extend(legacy_folder.glob('*/snapshot.json'))
                    for path in paths:
                        if any(p.is_symlink() for p in [path,*path.parents] if p != base and p.is_relative_to(base)):
                            continue
                        item = read_json(path, 'formal_snapshot')
                        if item['formal_nl_id'] == nl and item['scope']['source_library_ids'] == [library]:
                            snapshots.append(item)
                    previous = max(snapshots, key=lambda x: x['observed_at']) if snapshots else None
                    sid = 'snap_' + uuid.uuid4().hex
                    metadata = {'formal_nl_id': nl, 'formal_snapshot_id': sid,
                                'previous_snapshot_id': previous['formal_snapshot_id'] if previous else None,
                                'observed_at': now, 'scope_confirmed': False,
                                'source_library_ids': [library], 'views': [], 'capture_link_target':True,
                                'note': '按唯一来源路径分库；范围未确认，链接匹配不证明文件内容一致'}
                    own_deliveries = deliveries_by_library[(vendor, library)]
                    candidate = build_snapshot(root, metadata,
                        {f['path']: f['source']['file_key'] for f in observed_files}, own_deliveries,
                        _inventory=inventory_paths, _by_path=by_path)
                    for observed, linked in zip(sorted(observed_files, key=lambda f: f['path']), candidate['linked_files']):
                        if observed['target'] != linked['resolved_path']:
                            raise ValueError('正式链接在观察与快照之间变化')
                        if observed['link_target'] != linked['link_target'] or os.readlink(root / observed['path']) != linked['link_target']:
                            raise ValueError('正式链接文字在观察与快照之间变化')
                        if str((root / observed['path']).resolve(strict=True)) != linked['resolved_path']:
                            raise ValueError('正式链接解析目标在观察与快照之间变化')
                        if observed['source']['file_key'] and (linked['source_match'] != 'MATCHED_RAW' or linked['source_ref']['delivery_id'] != observed['source']['delivery_id']):
                            raise ValueError('正式来源文件位未能唯一确认')
                    if previous and _same_snapshot(previous, candidate):
                        row.update(snapshot_id=previous['formal_snapshot_id'], action='REUSED', note='链接未变化；复用快照')
                    else:
                        write_atomic(folder / next_filename(folder,'formal_'+nl), candidate, immutable=True)
                        row.update(snapshot_id=sid, action='CREATED', note='已保存部分覆盖快照')
                    from ai_lib_qor.application.latest_pointers import refresh_formal_locked
                    try:
                        link_status=refresh_formal_locked(base,vendor,library).get(nl,{'status':'UNAVAILABLE'})
                        if link_status['status']!='READY':raise ValueError(link_status.get('reason','无法确定最新快照'))
                    except (OSError,ValueError,KeyError,TypeError) as exc:
                        row['note']+=f'；最新链接更新失败：{exc}'
                        row['link_status']='FAILED';result['status']='PARTIAL'
            except (OSError, ValueError, KeyError, TypeError) as exc:
                row['note'] = f'快照未发布：{exc}'
        if len(result['snapshots']) == 1:
            row = result['snapshots'][0]
            result['snapshot_id'], result['snapshot_action'], result['snapshot_note'] = row['snapshot_id'], row['action'], row['note']
        elif result['snapshots']:
            result['snapshot_note'] = f"已处理 {len(result['snapshots'])} 个来源库；详情见 snapshots"
    write_atomic(Path(runs) / 'formal_observations' / f"{result['observation_id']}.json", result, immutable=True)
    return result
