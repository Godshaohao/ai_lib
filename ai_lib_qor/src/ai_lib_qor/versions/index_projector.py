"""Replay append-only events, independent of the latest calculated revision."""


def project(revisions, events, updated_at):
    if not revisions:
        raise ValueError('没有可重建的版本')
    by_id = {r['revision_id']: r for r in revisions}
    position = {r['revision_id']: i for i, r in enumerate(revisions)}
    current, seen = None, set()
    for event in events:
        eid, target = event['event_id'], event['revision_id']
        if eid in seen or event['effective_set_id'] != revisions[0]['effective_set_id'] or target not in by_id:
            raise ValueError('采纳事件重复、集合不符或版本不存在')
        seen.add(eid)
        if event['action'] == 'ACCEPT':
            current = target
        elif event['action'] == 'ROLLBACK':
            if current is None or position[target] >= position[current]:
                raise ValueError('回退目标必须早于当前已采纳版本')
            current = target
        elif event['action'] == 'REVOKE':
            if current != target:
                raise ValueError('只能撤销当前已采纳版本')
            current = None
        else:
            raise ValueError('未知采纳动作')
    return {'schema_version': 'effective_index.v1', 'effective_set_id': revisions[0]['effective_set_id'],
            'owner': revisions[0]['owner'], 'latest_calculated_revision': revisions[-1]['revision_id'],
            'current_accepted_revision': current, 'updated_at': updated_at}
