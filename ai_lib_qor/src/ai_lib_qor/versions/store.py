"""Minimal local filesystem store for one effective set (POSIX advisory lock)."""
import contextlib
import fcntl
import hashlib
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from jsonschema import Draft202012Validator
from .composer import verify_delta
from .index_projector import project

SCHEMAS = Path(__file__).resolve().parents[3] / 'schemas'
REV = re.compile(r'rev_(\d{4,})\Z')


def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def validate(data, name):
    schema = json.loads((SCHEMAS / f'{name}.schema.json').read_text(encoding='utf-8'))
    errors = sorted(Draft202012Validator(schema).iter_errors(data), key=lambda e: str(list(e.absolute_path)))
    if errors:
        raise ValueError(f"{name} Schema 校验失败: {errors[0].message}")


def read_json(path, schema):
    data = json.loads(Path(path).read_text(encoding='utf-8'))
    validate(data, schema)
    return data


@contextlib.contextmanager
def locked(root):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    with (root / '.versions.lock').open('a+') as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def _payload(obj):
    return (json.dumps(obj, ensure_ascii=False, indent=2) + '\n').encode('utf-8')


def write_atomic(path, obj, immutable=False):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix='.tmp-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(_payload(obj)); f.flush(); os.fsync(f.fileno())
        if immutable:
            os.link(tmp, path)  # atomic create, never overwrites history
        else:
            os.replace(tmp, path)
        dirfd = os.open(path.parent, os.O_RDONLY)
        try: os.fsync(dirfd)
        finally: os.close(dirfd)
    finally:
        if os.path.exists(tmp): os.unlink(tmp)


def revisions(root):
    directory = Path(root) / 'versions'
    files = list(directory.glob('*.json')) if directory.exists() else []
    if any(not REV.fullmatch(p.stem) for p in files):
        raise ValueError('版本目录存在无效文件名')
    files.sort(key=lambda p: int(REV.fullmatch(p.stem).group(1)))
    result = []
    for i, file in enumerate(files):
        item = read_json(file, 'effective_version')
        if item['revision_id'] != file.stem:
            raise ValueError('版本文件名与 ID 不匹配')
        parent = result[-1] if result else None
        if item['parent_revision_id'] != (parent['revision_id'] if parent else None):
            raise ValueError('版本历史不是单一连续父版本链')
        if parent and (item['owner'] != parent['owner'] or item['effective_set_id'] != parent['effective_set_id']):
            raise ValueError('版本所有者或有效集发生变化')
        verify_delta(parent, item)
        result.append(item)
    return result


def events(root):
    path = Path(root) / 'acceptance.jsonl'
    if not path.exists(): return []
    result = []
    with path.open(encoding='utf-8') as f:
        for number, line in enumerate(f, 1):
            try:
                event = json.loads(line); validate(event, 'acceptance_event'); result.append(event)
            except (json.JSONDecodeError, ValueError) as exc:
                raise ValueError(f'采纳事件第 {number} 行损坏: {exc}') from exc
    return result


def append_event(root, event):
    path = Path(root) / 'acceptance.jsonl'
    text = json.dumps(event, ensure_ascii=False, separators=(',', ':')) + '\n'
    with path.open('a', encoding='utf-8') as f:
        f.write(text); f.flush(); os.fsync(f.fileno())


def rebuild_index(root, revs=None, evts=None):
    revs = revisions(root) if revs is None else revs
    evts = events(root) if evts is None else evts
    index = project(revs, evts, now())
    validate(index, 'effective_index')
    write_atomic(Path(root) / 'index.json', index)
    return index


def archive_delivery(root, delivery):
    """Freeze consumed source records and prevent unintentional out-of-order application."""
    directory = Path(root) / '_inputs' / 'deliveries'
    directory.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha256(delivery['delivery_id'].encode('utf-8')).hexdigest()
    target = directory / (key + '.json')
    existing = [read_json(p, 'delivery_record') for p in directory.glob('*.json')]
    for old in existing:
        if old['delivery_id'] == delivery['delivery_id'] and old != delivery:
            raise ValueError('同一 delivery_id 的内容发生变化，不能覆盖历史')
        if old['source_library_id'] == delivery['source_library_id'] and old['delivery_id'] != delivery['delivery_id']:
            if old['delivery_order'] >= delivery['delivery_order']:
                raise ValueError('交付顺序不递增或出现相同 order；回退请使用采纳回退')
    if not target.exists():
        write_atomic(target, delivery, immutable=True)
