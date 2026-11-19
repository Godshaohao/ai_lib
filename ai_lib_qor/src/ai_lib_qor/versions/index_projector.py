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


def project_simple(revisions, events, set_id, updated_at):
    """Project v2 history using the same acceptance transitions as v1."""
    from ai_lib_qor.application.effective_json import _flat_views
    if not revisions or not set_id:
        raise ValueError('没有可重建的版本或有效集身份')
    first = revisions[0]
    adapted = []
    for i, revision in enumerate(revisions):
        _flat_views(revision)
        expected = revisions[i-1]['revision'] if i else None
        if revision['parent'] != expected:
            raise ValueError('版本父版本链不连续')
        if revision['owner'] != first['owner'] or revision['scope'] != first['scope']:
            raise ValueError('版本归属不一致')
        if revision['revision'] in {r['revision_id'] for r in adapted}:
            raise ValueError('版本身份重复')
        adapted.append({'revision_id':revision['revision'], 'effective_set_id':set_id,
                        'owner':{'owner_type':first['owner']['type'], 'owner_id':first['owner']['id'],
                                 'home_source_library_id':first['scope']['library']}})
    return project(adapted,events,updated_at)
