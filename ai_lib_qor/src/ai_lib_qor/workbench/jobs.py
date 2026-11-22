"""Lightweight bounded in-process background job manager for long-running Web operations."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import threading
import time
import uuid


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


class JobManager:
    """Thread-safe bounded executor tracking recent background jobs without touching disk."""

    def __init__(self, *, max_workers: int = 2, max_history: int = 100):
        self._max_workers = max_workers
        self._executor = None
        self._lock = threading.Lock()
        self._jobs = {}
        self._order = []
        self._max_history = max_history

    def _get_executor(self):
        if self._executor is None:
            self._executor = ThreadPoolExecutor(max_workers=self._max_workers, thread_name_prefix='ai-lib-job')
        return self._executor

    def shutdown(self, *, wait: bool = True):
        with self._lock:
            ex = self._executor
            self._executor = None
        if ex is not None:
            ex.shutdown(wait=wait)

    def submit(self, kind: str, label: str, fn, *args, **kwargs) -> dict:
        job_id = 'job_' + uuid.uuid4().hex[:16]
        t_created = time.monotonic()
        record = {
            'job_id': job_id,
            'kind': kind,
            'label': label,
            'status': 'QUEUED',
            'created_at': _utc_now(),
            'started_at': None,
            'finished_at': None,
            'elapsed_seconds': 0.0,
            'result': None,
            'error': None,
            '_t_created': t_created,
            '_t_started': None,
            '_t_finished': None,
        }
        with self._lock:
            self._jobs[job_id] = record
            self._order.append(job_id)
            while len(self._order) > self._max_history:
                old = self._order.pop(0)
                if self._jobs.get(old, {}).get('status') in ('SUCCEEDED', 'FAILED'):
                    self._jobs.pop(old, None)

        def _runner():
            t_start = time.monotonic()
            with self._lock:
                record['status'] = 'RUNNING'
                record['started_at'] = _utc_now()
                record['_t_started'] = t_start
            try:
                res = fn(*args, **kwargs)
                t_end = time.monotonic()
                with self._lock:
                    record['status'] = 'SUCCEEDED'
                    record['finished_at'] = _utc_now()
                    record['_t_finished'] = t_end
                    record['elapsed_seconds'] = round(t_end - t_start, 3)
                    record['result'] = res
            except Exception as exc:  # noqa: BLE001
                t_end = time.monotonic()
                with self._lock:
                    record['status'] = 'FAILED'
                    record['finished_at'] = _utc_now()
                    record['_t_finished'] = t_end
                    record['elapsed_seconds'] = round(t_end - t_start, 3)
                    record['error'] = f'{type(exc).__name__}: {exc}'

        self._get_executor().submit(_runner)
        return self._public(record)

    def _public(self, rec: dict) -> dict:
        elapsed = rec['elapsed_seconds']
        if rec['status'] == 'RUNNING' and rec['_t_started'] is not None:
            elapsed = round(time.monotonic() - rec['_t_started'], 3)
        elif rec['status'] == 'QUEUED':
            elapsed = round(time.monotonic() - rec['_t_created'], 3)
        return {
            'job_id': rec['job_id'],
            'kind': rec['kind'],
            'label': rec['label'],
            'status': rec['status'],
            'created_at': rec['created_at'],
            'started_at': rec['started_at'],
            'finished_at': rec['finished_at'],
            'elapsed_seconds': elapsed,
            'result': rec['result'],
            'error': rec['error'],
        }

    def get(self, job_id: str):
        with self._lock:
            rec = self._jobs.get(job_id)
            return self._public(rec) if rec else None

    def list_recent(self, *, limit: int = 20) -> list[dict]:
        with self._lock:
            ids = list(reversed(self._order[-limit:]))
            return [self._public(self._jobs[i]) for i in ids if i in self._jobs]
