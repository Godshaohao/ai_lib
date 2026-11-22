"""Minimal local filesystem store primitives (POSIX advisory lock, atomic write, JSON Schema validation)."""
import contextlib
import fcntl
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from jsonschema import Draft202012Validator

SCHEMAS = Path(__file__).resolve().parents[3] / 'schemas'


def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def validate(data, name):
    schema = json.loads((SCHEMAS / f'{name}.schema.json').read_text(encoding='utf-8'))
    errors = sorted(Draft202012Validator(schema).iter_errors(data), key=lambda e: str(list(e.absolute_path)))
    if errors:
        raise ValueError(f'{name} Schema 校验失败: {errors[0].message}')


def read_json(path, schema):
    data = json.loads(Path(path).read_text(encoding='utf-8'))
    validate(data, schema)
    return data


@contextlib.contextmanager
def locked(root):
    root = Path(root)
    if root.is_symlink():
        raise ValueError('锁目录不能为符号链接')
    root.mkdir(parents=True, exist_ok=True)
    lockfile = root / '.versions.lock'
    if lockfile.is_symlink():
        raise ValueError('锁文件不能为符号链接')
    with lockfile.open('a+') as f:
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
            f.write(_payload(obj))
            f.flush()
            os.fsync(f.fileno())
        if immutable:
            os.link(tmp, path)  # atomic create, never overwrites history
        else:
            os.replace(tmp, path)
        dirfd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(dirfd)
        finally:
            os.close(dirfd)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
