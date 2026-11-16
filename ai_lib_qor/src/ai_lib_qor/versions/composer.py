"""Build complete immutable v3 revisions and verify the parent delta."""
from copy import deepcopy


def changes_between(old, new):
    changes = []
    for key in sorted(set(old) | set(new)):
        a, b = old.get(key), new.get(key)
        if a == b:
            continue
        changes.append({'file_key': key, 'action': 'ADDED' if a is None else 'REMOVED' if b is None else 'REPLACED',
                        'old_source_ref': deepcopy(a), 'new_source_ref': deepcopy(b)})
    return changes


def members_map(revision):
    items = revision['members']
    result = {m['file_key']: m['source_ref'] for m in items}
    if len(result) != len(items):
        raise ValueError('有效版本存在重复 file_key')
    return result


def compose(set_id, owner, revision_id, parent, members, reason, created_at):
    old = members_map(parent) if parent else {}
    changes = changes_between(old, members)
    if parent and not changes:
        return None
    return {'schema_version': 'effective_version.v1', 'effective_set_id': set_id, 'owner': deepcopy(owner),
            'revision_id': revision_id, 'parent_revision_id': parent['revision_id'] if parent else None,
            'created_at': created_at, 'reason': reason,
            'members': [{'file_key': k, 'source_ref': deepcopy(v)} for k, v in sorted(members.items())], 'changes': changes}


def verify_delta(parent, revision):
    old = members_map(parent) if parent else {}
    actual = revision['changes']
    if len({item['file_key'] for item in actual}) != len(actual):
        raise ValueError('版本变化中存在重复 file_key')
    if sorted(actual, key=lambda item: item['file_key']) != changes_between(old, members_map(revision)):
        raise ValueError(f"版本变化与成员不一致: {revision['revision_id']}")
