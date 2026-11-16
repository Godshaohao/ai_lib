"""CLI for a single effective directory and explicit v3 intermediate JSON."""
import argparse
import json
import sys
from pathlib import Path

from .acceptance import create_event
from .composer import compose, members_map
from .delivery_policy import apply_delivery
from .index_projector import project
from .slot_resolver import delivery_members, snapshot_members
from .store import archive_delivery, append_event, events, locked, now, read_json, rebuild_index, revisions, validate, write_atomic


def parser():
    p = argparse.ArgumentParser(description='根据 v3 交付或正式快照维护有效版本和采纳事件')
    subs = p.add_subparsers(dest='command', required=True)
    def base(name):
        sub = subs.add_parser(name); sub.add_argument('--effective-dir', required=True, type=Path); return sub
    init = base('init'); source = init.add_mutually_exclusive_group(required=True)
    source.add_argument('--delivery', type=Path); source.add_argument('--snapshot', type=Path)
    for x in ('set-id', 'owner-id', 'home-library'): init.add_argument('--'+x, required=True)
    init.add_argument('--owner-type', required=True, choices=['BUSINESS_IP','SOURCE_LIBRARY'])
    apply = base('apply'); apply.add_argument('--delivery', required=True, type=Path)
    apply.add_argument('--allow-source-library', action='append', default=[], help='显式确认与此有效集关联的其他来源库，可重复')
    apply.add_argument('--file-key', action='append', help='只采用指定文件位，可重复；省略时采用记录中的全部明确文件和显式删除')
    for action in ('accept', 'rollback', 'revoke'):
        sub = base(action)
        for x in ('revision','actor','reason'): sub.add_argument('--'+x, required=True)
    base('rebuild-index')
    return p


def run(args):
    root = args.effective_dir
    with locked(root):
        revs = revisions(root); evts = events(root)
        if args.command == 'init':
            if revs or evts: raise ValueError('有效集已经存在，不能重新初始化')
            owner = {'owner_type': args.owner_type, 'owner_id': args.owner_id, 'home_source_library_id': args.home_library}
            if args.delivery:
                source = read_json(args.delivery, 'delivery_record'); members = delivery_members(source)
                if source['source_library_id'] != args.home_library:
                    raise ValueError('来源库不等于 home_library；跨库归属需先确认')
                reason = {'kind': 'RAW_DELIVERY', 'ref_id': source['delivery_id']}
            else:
                source = read_json(args.snapshot, 'formal_snapshot'); members = snapshot_members(source)
                reason = {'kind': 'FORMAL_BASELINE', 'ref_id': source['formal_snapshot_id']}
            if not members: raise ValueError('初始成员为空')
            candidate = compose(args.set_id, owner, 'rev_0001', None, members, reason, now())
            validate(candidate, 'effective_version')
            if args.delivery: archive_delivery(root, source)
            write_atomic(root/'versions/rev_0001.json', candidate, immutable=True)
            index = rebuild_index(root, [candidate], [])
            return {'revision_id': candidate['revision_id'], 'index': index}
        if not revs: raise ValueError('有效集尚未初始化')
        # Validate full history before any modification; index may be missing/stale and is rebuilt.
        project(revs, evts, now())
        if args.command == 'apply':
            delivery = read_json(args.delivery, 'delivery_record')
            parent = revs[-1]
            if delivery['source_library_id'] not in {parent['owner']['home_source_library_id'], *args.allow_source_library}:
                raise ValueError('来源库不等于 home_library；跨库归属需先确认')
            members = apply_delivery(members_map(parent), delivery, args.file_key)
            n = int(parent['revision_id'][4:]) + 1; rev_id = f'rev_{n:04d}'
            candidate = compose(parent['effective_set_id'], parent['owner'], rev_id, parent, members,
                                {'kind': 'RAW_DELIVERY', 'ref_id': delivery['delivery_id']}, now())
            if candidate is None:
                archive_delivery(root, delivery)
                index = rebuild_index(root, revs, evts)
                return {'revision_id': parent['revision_id'], 'changed': False, 'index': index}
            validate(candidate, 'effective_version')
            archive_delivery(root, delivery)
            write_atomic(root/'versions'/f'{rev_id}.json', candidate, immutable=True)
            index = rebuild_index(root, revs + [candidate], evts)
            return {'revision_id': rev_id, 'changed': True, 'index': index}
        if args.command == 'rebuild-index':
            return {'index': rebuild_index(root, revs, evts)}
        event = create_event(revs[-1]['effective_set_id'], args.revision, args.command.upper(), args.actor, args.reason, now())
        validate(event, 'acceptance_event')
        project(revs, evts + [event], now())  # validate transitions before append
        append_event(root, event)
        index = rebuild_index(root, revs, evts + [event])
        return {'event_id': event['event_id'], 'index': index}


def main():
    try:
        print(json.dumps(run(parser().parse_args()), ensure_ascii=False, indent=2))
    except (OSError, ValueError, KeyError) as exc:
        print(f'错误: {exc}', file=sys.stderr); return 1
    return 0

if __name__ == '__main__':
    sys.exit(main())
