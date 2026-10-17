"""Small bounded scheduler primitives for Web-launched CLI jobs."""

from __future__ import annotations

from contextlib import contextmanager
import os
from pathlib import Path
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor

try:
    import fcntl
except ImportError:  # pragma: no cover - the supported Web host is Linux.
    fcntl = None


def actions_conflict(existing: str, requested: str) -> bool:
    """Semantic review reads frozen inputs and may overlap a library mutation."""

    return "semantic-review" not in {existing, requested}


class JobAdmission:
    """Bound active plus queued work submitted to one Web process."""

    def __init__(self, *, max_workers: int, max_pending: int):
        if max_workers < 1 or max_pending < 0:
            raise ValueError("job limits must be non-negative and max_workers must be positive")
        self._capacity = threading.BoundedSemaphore(max_workers + max_pending)

    def submit(self, executor: ThreadPoolExecutor, callback) -> Future:
        if not self._capacity.acquire(blocking=False):
            raise RuntimeError("工作任务队列已满；请等待已有任务完成后再提交。")
        try:
            future = executor.submit(callback)
        except BaseException:
            self._capacity.release()
            raise
        future.add_done_callback(lambda _: self._capacity.release())
        return future


@contextmanager
def acquire_global_slot(lock_root: str | Path, max_workers: int, *, poll_interval: float = 0.1):
    """Acquire one cross-process worker slot; child processes may inherit its fd."""

    if fcntl is None:
        raise RuntimeError("Web job coordination requires fcntl file locks")
    root = Path(lock_root)
    root.mkdir(parents=True, exist_ok=True)
    while True:
        for slot in range(max_workers):
            path = root / f"worker-{slot}.lock"
            descriptor = os.open(path, os.O_CREAT | os.O_RDWR, 0o664)
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                os.close(descriptor)
                continue
            try:
                yield descriptor
            finally:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
                os.close(descriptor)
            return
        time.sleep(poll_interval)


@contextmanager
def acquire_catalog_writer_lock(lock_root: str | Path):
    """Serialize catalog-mutating CLI workflows across libraries and Web processes."""

    if fcntl is None:
        raise RuntimeError("Web job coordination requires fcntl file locks")
    root = Path(lock_root)
    root.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(root / "catalog-writer.lock", os.O_CREAT | os.O_RDWR, 0o664)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield descriptor
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)
