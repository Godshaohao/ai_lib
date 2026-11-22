"""Effective version operations, independent of CLI argument parsing."""
from pathlib import Path
import json
from .acceptance import create_event
from .composer import compose, members_map
from .delivery_policy import apply_delivery
from .index_projector import project
from .slot_resolver import delivery_members, snapshot_members
from .store import archive_delivery, append_event, events, locked, now, read_json, rebuild_index, revisions, validate, write_atomic, flat_effective, revision_path


def candidate_file_keys(delivery_path, delivery):
    """Known filename-derived candidates from v1 source evidence."""
    from ai_lib_qor.sources.layout import evidence_path as get_evidence_path
    evidence_path=get_evidence_path(delivery_path)
    if evidence_path.is_symlink():
        raise ValueError('来源证据不能是符号链接')
    if not evidence_path.is_file():
        return set()  # old explicit/manual v1 records may have no sidecar
    evidence=json.loads(evidence_path.read_text(encoding='utf-8'))
    bases=evidence.get('classification',{})
    return {f['file_key'] for f in delivery['files']
            if f.get('file_key') and bases.get(f['relative_path'],{}).get('basis')=='filename_unique_candidate'}


def _reject_implicit_candidates(delivery_path, delivery, file_keys):
    """A filename hint is not an implicit user decision to adopt that slot."""
    if file_keys is None and candidate_file_keys(delivery_path,delivery):
        raise ValueError('存在仅由文件名推断的候选文件位；请显式选择确认的文件位')


def run_version(command, *, effective_dir, delivery=None, snapshot=None, owner_type=None, owner_id=None, home_library=None, set_id=None, file_key=None, allow_source_library=(), revision=None, actor=None, reason=None, verify_files=False):
    root = Path(effective_dir)
    if command not in ('init','apply','rebuild-index','accept','rollback','revoke'):
        raise ValueError('不支持的版本命令')
    if command == 'init':
        if bool(delivery) == bool(snapshot): raise ValueError('初始化必须指定唯一一种来源')
        if owner_type not in ('BUSINESS_IP','SOURCE_LIBRARY') or not all((owner_id,home_library,set_id)):
            raise ValueError('初始化必须指定有效的所有者、来源库和有效集')
    if command == 'apply' and not delivery: raise ValueError('更新版本必须指定交付')
    if command in ('accept','rollback','revoke') and not all((revision,actor,reason)):
        raise ValueError('采纳操作必须指定版本、操作人和原因')
    if flat_effective(root):
        from ai_lib_qor.sources.layout import library_folder, SAFE
        if not SAFE.fullmatch(root.name) or root.is_symlink():raise ValueError('有效集标识不安全')
        work=root.parent.parent.parent.parent
        if library_folder(work,root.parent.parent.name,root.parent.name)!=root.parent.resolve():
            raise ValueError('有效集目录不安全')
    if flat_effective(root) and command == 'init' and root.name != 'effective_'+set_id:
        raise ValueError('有效集名称与 set_id 不一致')
    with locked(root.parent if flat_effective(root) else root):
        revs = revisions(root); evts = events(root)
        if command == 'init':
            if revs or evts: raise ValueError('有效集已经存在，不能重新初始化')
            owner = {'owner_type': owner_type, 'owner_id': owner_id, 'home_source_library_id': home_library}
            if delivery:
                source = read_json(delivery, 'delivery_record')
                _reject_implicit_candidates(delivery, source, file_key)
                members = delivery_members(source, selected_keys=file_key, verify_files=verify_files)
                if source['source_library_id'] != home_library:
                    raise ValueError('来源库不等于 home_library；跨库归属需先确认')
                reason = {'kind': 'RAW_DELIVERY', 'ref_id': source['delivery_id']}
            else:
                source = read_json(snapshot, 'formal_snapshot'); members = snapshot_members(source)
                reason = {'kind': 'FORMAL_BASELINE', 'ref_id': source['formal_snapshot_id']}
            if not members: raise ValueError('初始成员为空')
            candidate = compose(set_id, owner, 'rev_0001', None, members, reason, now())
            validate(candidate, 'effective_version')
            if delivery: archive_delivery(root, source)
            write_atomic(revision_path(root,'rev_0001'), candidate, immutable=True)
            index = rebuild_index(root, [candidate], [])
            return {'revision_id': candidate['revision_id'], 'index': index}
        if not revs: raise ValueError('有效集尚未初始化')
        # Validate full history before any modification; index may be missing/stale and is rebuilt.
        project(revs, evts, now())
        if command == 'apply':
            delivery_path = delivery
            delivery = read_json(delivery_path, 'delivery_record')
            _reject_implicit_candidates(delivery_path, delivery, file_key)
            parent = revs[-1]
            if delivery['source_library_id'] not in {parent['owner']['home_source_library_id'], *allow_source_library}:
                raise ValueError('来源库不等于 home_library；跨库归属需先确认')
            members = apply_delivery(members_map(parent), delivery, file_key, verify_files=verify_files)
            n = int(parent['revision_id'][4:]) + 1; rev_id = f'rev_{n:04d}'
            candidate = compose(parent['effective_set_id'], parent['owner'], rev_id, parent, members,
                                {'kind': 'RAW_DELIVERY', 'ref_id': delivery['delivery_id']}, now())
            if candidate is None:
                archive_delivery(root, delivery)
                index = rebuild_index(root, revs, evts)
                return {'revision_id': parent['revision_id'], 'changed': False, 'index': index}
            validate(candidate, 'effective_version')
            archive_delivery(root, delivery)
            write_atomic(revision_path(root,rev_id), candidate, immutable=True)
            index = rebuild_index(root, revs + [candidate], evts)
            return {'revision_id': rev_id, 'changed': True, 'index': index}
        if command == 'rebuild-index':
            return {'index': rebuild_index(root, revs, evts)}
        event = create_event(revs[-1]['effective_set_id'], revision, command.upper(), actor, reason, now())
        validate(event, 'acceptance_event')
        project(revs, evts + [event], now())  # validate transitions before append
        append_event(root, event)
        index = rebuild_index(root, revs, evts + [event])
        return {'event_id': event['event_id'], 'index': index}


def apply_version(effective_dir, delivery, *, file_keys=None, allow_source_libraries=()):
    return run_version('apply', effective_dir=effective_dir, delivery=delivery,
                       file_key=file_keys, allow_source_library=allow_source_libraries)
