"""Explicit human acceptance state for path-based libraries (strictly separated from latest computed revision)."""
import json
import os
from pathlib import Path
import uuid

from ai_lib_qor.sources.layout import library_folder, storage_dir
from ai_lib_qor.sources.root_inventory import update_pointer
from ai_lib_qor.sources.timestamps import utc_text
from ai_lib_qor.versions.store import locked
from .minimal_effective import _history


def _events_path(folder: Path) -> Path:
    return storage_dir(folder, 'log') / 'acceptance_events.jsonl'


def _append_event(folder: Path, event: dict):
    path = _events_path(folder)
    if path.is_symlink():
        raise ValueError('采纳事件日志不能为软链接')
    with path.open('a', encoding='utf-8') as stream:
        stream.write(json.dumps(event, ensure_ascii=False) + '\n')
        stream.flush()
        os.fsync(stream.fileno())


def _read_events(folder: Path, *, limit: int = 20):
    path = folder / 'log' / 'acceptance_events.jsonl'
    if path.is_symlink() or not path.is_file():
        return []
    events = []
    try:
        for line in path.read_text(encoding='utf-8').splitlines():
            if line.strip():
                events.append(json.loads(line))
    except (OSError, ValueError, TypeError):
        return []
    return list(reversed(events[-limit:]))


def _resolve_accepted_pointer(folder: Path, library: str):
    ptr = folder / 'accepted_effective.json'
    if not ptr.is_symlink():
        return None
    try:
        target = ptr.resolve(strict=True)
        if not target.is_relative_to(folder.resolve()) or not target.is_file():
            return None
        row = json.loads(target.read_text(encoding='utf-8'))
        if row.get('library') != library:
            return None
        return row.get('revision')
    except (OSError, ValueError, TypeError):
        return None


def acceptance_status(work, vendor, library, *, limit: int = 20):
    """Read-only view separating latest computed revision from explicitly accepted revision."""
    folder = library_folder(work, vendor, library)
    if not folder.is_dir():
        raise ValueError('库目录不存在')
    history = _history(folder, library)
    latest_rev = history[-1][2]['revision'] if history else None
    accepted_rev = _resolve_accepted_pointer(folder, library)
    events = _read_events(folder, limit=limit)
    latest_event = events[0] if events else None
    return {
        'vendor': vendor,
        'library': library,
        'latest_revision': latest_rev,
        'accepted_revision': accepted_rev,
        'is_latest_accepted': bool(latest_rev and accepted_rev == latest_rev),
        'last_event': latest_event,
        'history': events,
    }


def _record_acceptance(work, vendor, library, revision, *, action: str, actor: str, reason: str):
    if not isinstance(actor, str) or not actor.strip():
        raise ValueError('必须提供操作者 actor')
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError('必须提供采纳或回退原因 reason')
    folder = library_folder(work, vendor, library)
    if not folder.is_dir():
        raise ValueError('库目录不存在')
    with locked(folder):
        history = _history(folder, library)
        match = next(((num, path, row) for num, path, row in history if row['revision'] == revision), None)
        if not match:
            raise ValueError(f'有效版本不存在: {revision}')
        _, target_path, _ = match
        previous = _resolve_accepted_pointer(folder, library)
        event = {
            'schema_version': 'path_acceptance_event.v1',
            'event_id': 'acc_' + uuid.uuid4().hex[:16],
            'action': action,
            'vendor': vendor,
            'library': library,
            'revision': revision,
            'previous_accepted': previous,
            'acted_at': utc_text(),
            'actor': actor.strip(),
            'reason': reason.strip(),
        }
        _append_event(folder, event)
        update_pointer(folder, 'accepted_effective.json', str(target_path.relative_to(folder)))
    return {
        'state': 'ACCEPTED' if action == 'ACCEPT' else 'ROLLED_BACK',
        'vendor': vendor,
        'library': library,
        'revision': revision,
        'previous_accepted': previous,
        'event': event,
    }


def accept_revision(work, vendor, library, revision, *, actor='local', reason=''):
    """Explicitly mark a revision as human-accepted without altering latest computed revision."""
    return _record_acceptance(work, vendor, library, revision, action='ACCEPT', actor=actor, reason=reason)


def rollback_acceptance(work, vendor, library, revision, *, actor='local', reason=''):
    """Explicitly move the accepted pointer back to an earlier revision without rewriting effective history."""
    return _record_acceptance(work, vendor, library, revision, action='ROLLBACK_ACCEPTANCE', actor=actor, reason=reason)
