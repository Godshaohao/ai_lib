"""Explicit human acceptance state for path-based libraries (strictly separated from latest computed revision)."""
import json
import os
from pathlib import Path
import uuid

from ai_lib_qor.sources.layout import library_folder, storage_dir
from ai_lib_qor.sources.root_inventory import update_pointer
from ai_lib_qor.sources.timestamps import utc_text
from ai_lib_qor.versions.store import locked
from .minimal_effective import _history, _latest_effective_pointer, _norm_business_ip
from .path_config import library_ip_config


def _accepted_pointer_name(business_ip=None) -> str:
    ip = _norm_business_ip(business_ip)
    return f'accepted_effective__{ip}.json' if ip else 'accepted_effective.json'


def report_cache_is_current(folder, excel, business_ip=None, *, include_latest=False):
    """Check whether the Excel projection predates the pointers displayed in the workbook."""
    if excel.is_symlink() or not excel.is_file():
        return False
    try:
        rendered_at = excel.stat().st_mtime_ns
    except FileNotFoundError:
        return False
    names = [_accepted_pointer_name(business_ip)]
    if include_latest:
        names.append(_latest_effective_pointer(business_ip))
    for name in names:
        try:
            if (folder / name).lstat().st_ctime_ns > rendered_at:
                return False
        except FileNotFoundError:
            continue
    return True


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


def _read_events(folder: Path, *, limit: int = 20, business_ip=None):
    ip = _norm_business_ip(business_ip)
    path = folder / 'log' / 'acceptance_events.jsonl'
    if path.is_symlink() or not path.is_file():
        return []
    events = []
    try:
        for line in path.read_text(encoding='utf-8').splitlines():
            if line.strip():
                ev = json.loads(line)
                if ev.get('business_ip') == ip:
                    events.append(ev)
    except (OSError, ValueError, TypeError):
        return []
    return list(reversed(events[-limit:]))


def _resolve_accepted_pointer(folder: Path, library: str, *, business_ip=None):
    ip = _norm_business_ip(business_ip)
    ptr = folder / _accepted_pointer_name(ip)
    if not ptr.is_symlink():
        return None
    try:
        target = ptr.resolve(strict=True)
        if not target.is_relative_to(folder.resolve()) or not target.is_file():
            return None
        row = json.loads(target.read_text(encoding='utf-8'))
        if row.get('library') != library or row.get('business_ip') != ip:
            return None
        return row.get('revision')
    except (OSError, ValueError, TypeError):
        return None


def acceptance_status(work, vendor, library, *, limit: int = 20, business_ip=None):
    """Read-only view separating latest computed revision from explicitly accepted revision (single or per-IP track)."""
    ip = _norm_business_ip(business_ip)
    folder = library_folder(work, vendor, library)
    if not folder.is_dir():
        raise ValueError('库目录不存在')
    history = _history(folder, library, business_ip=ip)
    latest_rev = history[-1][2]['revision'] if history else None
    accepted_rev = _resolve_accepted_pointer(folder, library, business_ip=ip)
    events = _read_events(folder, limit=limit, business_ip=ip)
    latest_event = events[0] if events else None
    ip_cfg = library_ip_config(work, vendor, library)
    out = {
        'vendor': vendor,
        'library': library,
        'latest_revision': latest_rev,
        'accepted_revision': accepted_rev,
        'is_latest_accepted': bool(latest_rev and accepted_rev == latest_rev),
        'last_event': latest_event,
        'history': events,
    }
    if ip is not None:
        out['business_ip'] = ip
        out['ip_type'] = ip_cfg['ip_type']
        out['track_id'] = f'{vendor}/{library}::{ip}'
    elif ip_cfg['ip_type'] is not None:
        out['ip_type'] = ip_cfg['ip_type']
    return out


def _record_acceptance(work, vendor, library, revision, *, action: str, actor: str, reason: str, business_ip=None):
    ip = _norm_business_ip(business_ip)
    if not isinstance(actor, str) or not actor.strip():
        raise ValueError('必须提供操作者 actor')
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError('必须提供采纳或回退原因 reason')
    folder = library_folder(work, vendor, library)
    if not folder.is_dir():
        raise ValueError('库目录不存在')
    ip_cfg = library_ip_config(work, vendor, library)
    with locked(folder):
        history = _history(folder, library, business_ip=ip)
        match = next(((num, path, row) for num, path, row in history if row['revision'] == revision), None)
        if not match:
            raise ValueError(f'有效版本不存在: {revision}')
        _, target_path, _ = match
        previous = _resolve_accepted_pointer(folder, library, business_ip=ip)
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
        if ip is not None:
            event['business_ip'] = ip
            event['ip_type'] = ip_cfg['ip_type']
            event['track_id'] = f'{vendor}/{library}::{ip}'
        _append_event(folder, event)
        update_pointer(folder, _accepted_pointer_name(ip), str(target_path.relative_to(folder)))
    out = {
        'state': 'ACCEPTED' if action == 'ACCEPT' else 'ROLLED_BACK',
        'vendor': vendor,
        'library': library,
        'revision': revision,
        'previous_accepted': previous,
        'event': event,
    }
    if ip is not None:
        out['business_ip'] = ip
        out['ip_type'] = ip_cfg['ip_type']
        out['track_id'] = f'{vendor}/{library}::{ip}'
    return out


def accept_revision(work, vendor, library, revision, *, actor='local', reason='', business_ip=None):
    """Explicitly mark a revision as human-accepted without altering latest computed revision."""
    return _record_acceptance(work, vendor, library, revision, action='ACCEPT', actor=actor, reason=reason, business_ip=business_ip)


def rollback_acceptance(work, vendor, library, revision, *, actor='local', reason='', business_ip=None):
    """Explicitly move the accepted pointer back to an earlier revision without rewriting effective history."""
    return _record_acceptance(work, vendor, library, revision, action='ROLLBACK_ACCEPTANCE', actor=actor, reason=reason, business_ip=business_ip)


def acceptance_summary_by_ip_type(work, ip_type: str | None = None, *, vendor=None, library=None, business_ip=None):
    """Aggregate read-only acceptance status across libraries/tracks filtered by ip_type and/or business_ip."""
    from .path_query import PathDataQuery
    result = PathDataQuery(work).list_tracks(vendor=vendor, library=library, ip_type=ip_type, business_ip=business_ip)
    rows = result['tracks']
    return {
        'work': result['work'],
        'filters': result['filters'],
        'total_tracks': len(rows),
        'accepted_tracks': sum(1 for r in rows if r.get('accepted_revision')),
        'latest_accepted_tracks': sum(1 for r in rows if r.get('is_latest_accepted')),
        'tracks': rows,
    }
