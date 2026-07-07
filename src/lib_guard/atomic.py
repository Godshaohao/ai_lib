from __future__ import annotations

import json
import os
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

try:  # pragma: no cover - fcntl is always available on the target Linux env.
    import fcntl
except Exception:  # pragma: no cover
    fcntl = None  # type: ignore[assignment]


def _fsync_dir(path: Path) -> None:
    try:
        fd = os.open(str(path), os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


@contextmanager
def file_lock(lock_path: str | Path) -> Iterator[Path]:
    """Best-effort advisory file lock for shared Linux work/release trees."""

    path = Path(lock_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a+", encoding="utf-8")
    try:
        if fcntl is not None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        yield path
    finally:
        try:
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()


def atomic_write_text(path: str | Path, text: str, *, lock: bool = False, fsync: bool = True) -> Path:
    """Write text by unique temp file + replace, safe for concurrent readers."""

    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    lock_path = out.with_name(f".{out.name}.lock")

    def _write() -> None:
        tmp = out.with_name(f".{out.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
        try:
            with tmp.open("w", encoding="utf-8") as fh:
                fh.write(text)
                fh.flush()
                if fsync:
                    os.fsync(fh.fileno())
            os.replace(tmp, out)
            if fsync:
                _fsync_dir(out.parent)
        finally:
            try:
                if tmp.exists():
                    tmp.unlink()
            except OSError:
                pass

    if lock:
        with file_lock(lock_path):
            _write()
    else:
        _write()
    return out


def atomic_write_json(path: str | Path, data: Any, *, lock: bool = False, fsync: bool = True) -> Path:
    text = json.dumps(data, ensure_ascii=False, indent=2, default=str) + "\n"
    return atomic_write_text(path, text, lock=lock, fsync=fsync)
