"""Bounded in-process background job manager with real-time progress and cooperative cancellation."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import threading
import time
import uuid


class JobCancelledError(RuntimeError):
    """Raised cooperatively when a running background job is cancelled by the user."""


def check_cancel(cancel_event, message: str = '任务已被用户终止'):
    if cancel_event is not None and cancel_event.is_set():
        raise JobCancelledError(message)


def emit_progress(progress_cb, stage: str, message: str, *, completed=None, total=None):
    if progress_cb is not None:
        progress_cb(stage, message, completed=completed, total=total)


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


class JobManager:
    """Thread-safe bounded executor tracking progress, step logs, and cancellation."""

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

    def submit(self, kind: str, label: str, fn) -> dict:
        """Submit a callable `fn(report_progress, cancel_event)` to run in background."""
        job_id = 'job_' + uuid.uuid4().hex[:16]
        t_created = time.monotonic()
        cancel_event = threading.Event()
        record = {
            'job_id': job_id,
            'kind': kind,
            'label': label,
            'status': 'QUEUED',
            'stage': 'QUEUED',
            'message': '任务已进入队列，准备开始…',
            'completed': 0,
            'total': None,
            'percent': None,
            'events': [f"[{_utc_now()[11:19]}] 已提交任务：{label}"],
            'cancel_requested': False,
            'created_at': _utc_now(),
            'started_at': None,
            'finished_at': None,
            'elapsed_seconds': 0.0,
            'result': None,
            'error': None,
            '_t_created': t_created,
            '_t_started': None,
            '_t_finished': None,
            '_cancel_event': cancel_event,
        }
        with self._lock:
            self._jobs[job_id] = record
            self._order.append(job_id)
            while len(self._order) > self._max_history:
                old = self._order.pop(0)
                if self._jobs.get(old, {}).get('status') in ('SUCCEEDED', 'FAILED', 'CANCELLED'):
                    self._jobs.pop(old, None)

        def report_progress(stage: str, message: str, *, completed=None, total=None):
            stamp = _utc_now()[11:19]
            with self._lock:
                if record['status'] in ('SUCCEEDED', 'FAILED', 'CANCELLED'):
                    return
                record['stage'] = str(stage)
                record['message'] = str(message)
                if completed is not None:
                    record['completed'] = int(completed)
                if total is not None:
                    record['total'] = int(total)
                if record['total'] and record['total'] > 0 and record['completed'] is not None:
                    record['percent'] = max(0, min(100, int(round(record['completed'] * 100.0 / record['total']))))
                line = f'[{stamp}] [{stage}] {message}'
                if not record['events'] or record['events'][-1] != line:
                    record['events'].append(line)
                    record['events'] = record['events'][-60:]

        def _runner():
            t_start = time.monotonic()
            with self._lock:
                if cancel_event.is_set() or record['status'] == 'CANCELLED':
                    record['status'] = 'CANCELLED'
                    record['stage'] = 'CANCELLED'
                    record['message'] = '任务已在开始前终止'
                    record['finished_at'] = _utc_now()
                    record['_t_finished'] = t_start
                    return
                record['status'] = 'RUNNING'
                record['stage'] = 'RUNNING'
                record['message'] = f'正在执行：{label}'
                record['started_at'] = _utc_now()
                record['_t_started'] = t_start
                record['events'].append(f"[{_utc_now()[11:19]}] 开始执行")
            try:
                res = fn(report_progress, cancel_event)
                t_end = time.monotonic()
                with self._lock:
                    record['status'] = 'SUCCEEDED'
                    record['stage'] = 'DONE'
                    record['message'] = f'{label} 已完成'
                    if record['total']:
                        record['completed'] = record['total']
                    record['percent'] = 100
                    record['finished_at'] = _utc_now()
                    record['_t_finished'] = t_end
                    record['elapsed_seconds'] = round(t_end - t_start, 3)
                    record['result'] = res
                    record['events'].append(f"[{_utc_now()[11:19]}] 执行完成（耗时 {record['elapsed_seconds']}s）")
            except JobCancelledError as exc:
                t_end = time.monotonic()
                with self._lock:
                    record['status'] = 'CANCELLED'
                    record['stage'] = 'CANCELLED'
                    record['message'] = str(exc) or '任务已由用户安全终止'
                    record['finished_at'] = _utc_now()
                    record['_t_finished'] = t_end
                    record['elapsed_seconds'] = round(t_end - t_start, 3)
                    record['events'].append(f"[{_utc_now()[11:19]}] 已安全终止：{record['message']}")
            except Exception as exc:  # noqa: BLE001
                t_end = time.monotonic()
                with self._lock:
                    record['status'] = 'FAILED'
                    record['stage'] = 'FAILED'
                    record['message'] = f'执行失败：{exc}'
                    record['finished_at'] = _utc_now()
                    record['_t_finished'] = t_end
                    record['elapsed_seconds'] = round(t_end - t_start, 3)
                    record['error'] = f'{type(exc).__name__}: {exc}'
                    record['events'].append(f"[{_utc_now()[11:19]}] 执行失败：{record['error']}")

        self._get_executor().submit(_runner)
        return self._public(record)

    def cancel(self, job_id: str):
        with self._lock:
            rec = self._jobs.get(job_id)
            if not rec:
                return None
            rec['_cancel_event'].set()
            rec['cancel_requested'] = True
            if rec['status'] == 'QUEUED':
                rec['status'] = 'CANCELLED'
                rec['stage'] = 'CANCELLED'
                rec['message'] = '任务已在排队阶段终止'
                rec['finished_at'] = _utc_now()
                rec['events'].append(f"[{_utc_now()[11:19]}] 用户在排队阶段终止了任务")
            elif rec['status'] == 'RUNNING':
                rec['status'] = 'CANCELLING'
                rec['message'] = '已发送终止指令，等待当前原子步骤安全退出…'
                rec['events'].append(f"[{_utc_now()[11:19]}] 收到终止指令，正在安全停止…")
            return self._public(rec)

    def _public(self, rec: dict) -> dict:
        elapsed = rec['elapsed_seconds']
        if rec['status'] in ('RUNNING', 'CANCELLING') and rec['_t_started'] is not None:
            elapsed = round(time.monotonic() - rec['_t_started'], 3)
        elif rec['status'] == 'QUEUED':
            elapsed = round(time.monotonic() - rec['_t_created'], 3)
        return {
            'job_id': rec['job_id'],
            'kind': rec['kind'],
            'label': rec['label'],
            'status': rec['status'],
            'stage': rec['stage'],
            'message': rec['message'],
            'completed': rec['completed'],
            'total': rec['total'],
            'percent': rec['percent'],
            'events': list(rec['events']),
            'cancel_requested': rec['cancel_requested'],
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
