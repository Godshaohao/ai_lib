"""Minimal local filesystem store primitives (POSIX flock, runtime-enforced lock ordering, atomic write, cached Schema validation).

Lock Ordering Invariant (enforced at runtime via thread-local lock stack):
    1. Never acquire the same lock twice in the same thread (non-reentrant deadlock prevention).
    2. Whenever both a per-library lock (`locked(library_folder)`) and the workspace root lock
       (`locked(work_root)`) must be held simultaneously, ALWAYS acquire `locked(library_folder)`
       FIRST and `locked(work_root)` SECOND. Acquiring a nested/child lock while holding an
       ancestor lock raises RuntimeError immediately instead of deadlocking.
    3. Multi-library locks held simultaneously in one thread must be acquired in lexicographical path order.

Note on Multi-Host / NFS Deployments:
    This store intentionally uses kernel-managed POSIX `fcntl.flock` for local single-host operation
    (no timeout-based lock stealing that could violate mutual exclusion against live holders).
    Cross-host NFS/HPC deployments require dedicated environment-verified distributed locking.
"""
from collections import OrderedDict
import contextlib
import copy
import fcntl
import functools
from importlib import resources as importlib_resources
import json
import os
import sys
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path

from jsonschema import Draft202012Validator

SCHEMAS = Path(__file__).resolve().parents[3] / 'schemas'
_LOCK_STACK = threading.local()
_READ_CACHE_LOCK = threading.Lock()
_READ_CACHE: OrderedDict = OrderedDict()
_READ_CACHE_MAX = 2048


def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def _resolve_schema_path(name: str) -> Path:
    filename = f'{name}.schema.json'
    direct = SCHEMAS / filename
    if direct.is_file():
        return direct
    shared = Path(sys.prefix) / 'share' / 'ai_lib_qor' / 'schemas' / filename
    if shared.is_file():
        return shared
    try:
        res = importlib_resources.files('ai_lib_qor').joinpath('schemas', filename)
        with importlib_resources.as_file(res) as p:
            if p.is_file():
                return p
    except (FileNotFoundError, ModuleNotFoundError, TypeError, AttributeError):
        pass
    return direct


@functools.lru_cache(maxsize=64)
def _compiled_validator(schema_path_str: str, mtime_ns: int, size: int) -> Draft202012Validator:
    schema = json.loads(Path(schema_path_str).read_text(encoding='utf-8'))
    return Draft202012Validator(schema)


def validate(data, name):
    path = _resolve_schema_path(name)
    st = path.stat()
    validator = _compiled_validator(str(path), st.st_mtime_ns, st.st_size)
    errors = sorted(validator.iter_errors(data), key=lambda e: str(list(e.absolute_path)))
    if errors:
        path_txt = '.'.join(str(p) for p in errors[0].absolute_path)
        loc = f' ({path_txt})' if path_txt else ''
        raise ValueError(f'{name} Schema 校验失败{loc}: {errors[0].message}')


def _read_json_cached(path, schema=None):
    """Thread-safe stat-verified JSON+Schema read cache (validates mtime_ns, ctime_ns, size, ino)."""
    p = Path(path)
    st = p.stat()
    key = (str(p.resolve()), st.st_mtime_ns, st.st_ctime_ns, st.st_size, st.st_ino, schema)
    with _READ_CACHE_LOCK:
        hit = _READ_CACHE.get(key)
        if hit is not None:
            _READ_CACHE.move_to_end(key)
            return hit
    data = json.loads(p.read_text(encoding='utf-8'))
    if schema is not None:
        validate(data, schema)
    with _READ_CACHE_LOCK:
        _READ_CACHE[key] = data
        _READ_CACHE.move_to_end(key)
        while len(_READ_CACHE) > _READ_CACHE_MAX:
            _READ_CACHE.popitem(last=False)
    return data


def read_json_readonly(path, schema=None):
    """Return stat-verified cached JSON object for strictly read-only callers (callers must NOT mutate)."""
    return _read_json_cached(path, schema)


def read_json(path, schema):
    return copy.deepcopy(_read_json_cached(path, schema))


def _held_locks() -> list[Path]:
    stack = getattr(_LOCK_STACK, 'held', None)
    if stack is None:
        stack = []
        _LOCK_STACK.held = stack
    return stack


def _check_lock_order(resolved: Path):
    held = _held_locks()
    for prev in held:
        if prev == resolved:
            raise RuntimeError(f'检测到同线程重复获取同一锁（不可重入，防止自死锁）: {resolved}')
        if resolved.is_relative_to(prev):
            raise RuntimeError(
                f'违反锁序规范：禁止在持有外层目录锁 {prev} 期间获取内层库目录锁 {resolved}（必须先库锁、后工作区根锁）'
            )
        if not prev.is_relative_to(resolved) and str(resolved) < str(prev):
            raise RuntimeError(
                f'违反同级多库锁序规范：必须按路径字典序依次加锁（已持有 {prev}，尝试获取 {resolved}）'
            )


def _pid_start_ticks(pid: int) -> int | None:
    """Read Linux /proc/<pid>/stat process start ticks (field 22) to guard against PID reuse."""
    try:
        raw = Path(f'/proc/{pid}/stat').read_text(encoding='utf-8')
        rparen = raw.rfind(')')
        if rparen < 0:
            return None
        fields = raw[rparen + 2:].split()
        # Field 22 in /proc/<pid>/stat is index 19 after ') ' (fields start at field 3: state)
        return int(fields[19]) if len(fields) > 19 else None
    except (OSError, ValueError, IndexError):
        return None


def _pid_alive(pid: int, *, expected_start_ticks: int | None = None) -> bool:
    if not isinstance(pid, int) or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        pass
    except OSError:
        return False
    if expected_start_ticks is not None:
        actual = _pid_start_ticks(pid)
        if actual is not None and actual != expected_start_ticks:
            return False
    return True


@contextlib.contextmanager
def locked(root):
    root = Path(root)
    if root.is_symlink():
        raise ValueError('锁目录不能为符号链接')
    root.mkdir(parents=True, exist_ok=True)
    resolved = root.resolve()
    _check_lock_order(resolved)

    lockfile = root / '.versions.lock'
    if lockfile.is_symlink():
        raise ValueError('锁文件不能为软链接')
    held = _held_locks()
    with lockfile.open('a+') as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        held.append(resolved)
        try:
            yield
        finally:
            held.pop()
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
