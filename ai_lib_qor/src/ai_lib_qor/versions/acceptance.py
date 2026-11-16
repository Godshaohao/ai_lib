"""Acceptance event creation; authorization is the caller's responsibility."""
from uuid import uuid4


def create_event(set_id, revision, action, actor, reason, acted_at):
    if action not in {'ACCEPT', 'ROLLBACK', 'REVOKE'} or not actor.strip() or not reason.strip():
        raise ValueError('采纳动作、操作人或原因无效')
    return {'schema_version': 'acceptance_event.v1', 'event_id': 'accept_' + uuid4().hex,
            'effective_set_id': set_id, 'action': action, 'revision_id': revision,
            'acted_at': acted_at, 'actor': actor, 'reason': reason}
