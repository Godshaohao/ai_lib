"""Bounded background job manager with disk persistence, cross-process atomic scope leases, progress, and cancellation."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import socket
import threading
import time
import uuid

from ai_lib_qor.versions.runtime import JobCancelledError, check_cancel, emit_progress
from ai_lib_qor.versions.store import _pid_alive, _pid_start_ticks, write_atomic

_HOSTNAME = socket.gethostname()
_LOCAL_START_TICKS = _pid_start_ticks(os.getpid())
_ACTIVE_STATES = ('QUEUED', 'RUNNING', 'CANCELLING')
_TERMINAL_STATES = ('SUCCEEDED', 'PARTIAL', 'FAILED', 'CANCELLED')


class JobConflictError(RuntimeError):
    """Raised when a duplicate background job is submitted for an already-active scope."""

    def __init__(self, message: str, active_job: dict):
        super().__init__(message)
        self.active_job = active_job


class _FileBackedCancelEvent:
    """Cooperative cancel event backed by both an in-process Event and an optional cross-process flag file."""

    def __init__(self, cancel_path: Path | None = None):
        self._event = threading.Event()
        self._cancel_path = cancel_path

    def is_set(self) -> bool:
        if self._event.is_set():
            return True
        if self._cancel_path is not None:
            try:
                if self._cancel_path.is_file():
                    self._event.set()
                    return True
            except OSError:
                pass
        return False

    def set(self):
        self._event.set()
        if self._cancel_path is not None:
            try:
                self._cancel_path.parent.mkdir(parents=True, exist_ok=True)
                self._cancel_path.touch(exist_ok=True)
            except OSError:
                pass

    def wait(self, timeout=None) -> bool:
        if self._cancel_path is None:
            return self._event.wait(timeout=timeout)
        deadline = None if timeout is None else (time.monotonic() + float(timeout))
        while True:
            if self.is_set():
                return True
            if deadline is not None:
                rem = deadline - time.monotonic()
                if rem <= 0:
                    return False
                self._event.wait(timeout=min(0.1, rem))
            else:
                self._event.wait(timeout=0.1)


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def _scope_hash(scope_key: str) -> str:
    return hashlib.sha256(scope_key.encode('utf-8')).hexdigest()[:24]


def _json_safe(obj):
    try:
        json.dumps(obj, ensure_ascii=False)
        return obj
    except (TypeError, ValueError):
        return json.loads(json.dumps(obj, ensure_ascii=False, default=str))


class JobManager:
    """Thread-safe & local-multi-process-safe background executor with disk persistence, progress, and cancellation."""

    def __init__(self, *, max_workers: int = 2, max_history: int = 100, work_root=None):
        self._max_workers = max_workers
        self._executor = None
        self._lock = threading.Lock()
        self._jobs = {}
        self._order = []
        self._max_history = max_history
        self._work_root = Path(work_root).resolve() if work_root is not None else None
        self._jobs_root = None
        self._jobs_dir = None
        self._leases_dir = None
        self._cancel_dir = None
        if self._work_root is not None:
            self._init_disk_store()

    def _init_disk_store(self):
        jroot = self._work_root / '.jobs'
        if jroot.is_symlink():
            raise ValueError('作业状态目录不能为软链接')
        jroot.mkdir(parents=True, exist_ok=True)
        for sub_name in ('jobs', 'leases', 'cancel'):
            sub = jroot / sub_name
            if sub.is_symlink():
                raise ValueError(f'作业子目录不能为软链接: {sub}')
            sub.mkdir(parents=True, exist_ok=True)
        self._jobs_root = jroot
        self._jobs_dir = jroot / 'jobs'
        self._leases_dir = jroot / 'leases'
        self._cancel_dir = jroot / 'cancel'
        self._reconcile_disk_jobs()

    def _job_file(self, job_id: str) -> Path | None:
        if self._jobs_dir is None or '/' in job_id or '\\' in job_id or '..' in job_id:
            return None
        return self._jobs_dir / f'{job_id}.json'

    def _lease_file(self, scope_key: str) -> Path | None:
        if self._leases_dir is None or not scope_key:
            return None
        return self._leases_dir / f'{_scope_hash(scope_key)}.json'

    def _cancel_file(self, job_id: str) -> Path | None:
        if self._cancel_dir is None or '/' in job_id or '\\' in job_id or '..' in job_id:
            return None
        return self._cancel_dir / f'{job_id}.cancel'

    def _is_owner_stale(self, host: str | None, pid: int | None, start_ticks: int | None = None) -> bool:
        """Determine owner death strictly by local OS PID (+ start-ticks) liveness — never timeout-kill a live local process."""
        if host == _HOSTNAME and isinstance(pid, int):
            return not _pid_alive(pid, expected_start_ticks=start_ticks)
        # Foreign-host owners cannot be probed locally without a verified distributed coordinator;
        # never silently reclaim a potentially live foreign owner by wall-clock timeout.
        return False

    def _persist_record(self, rec: dict):
        if self._jobs_dir is None:
            return
        path = self._job_file(rec['job_id'])
        if path is None or path.is_symlink():
            return
        payload = self._serialize_disk(rec)
        try:
            write_atomic(path, payload)
        except OSError:
            pass

    def _serialize_disk(self, rec: dict) -> dict:
        return {
            'job_id': rec['job_id'],
            'kind': rec['kind'],
            'label': rec['label'],
            'scope_key': rec.get('scope_key'),
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
            'elapsed_seconds': rec['elapsed_seconds'],
            'result': _json_safe(rec['result']),
            'error': rec['error'],
            'owner_host': rec.get('owner_host', _HOSTNAME),
            'owner_pid': rec.get('owner_pid', os.getpid()),
            'owner_start_ticks': rec.get('owner_start_ticks', _LOCAL_START_TICKS),
            'created_ts': rec.get('created_ts', time.time()),
            'started_ts': rec.get('started_ts'),
        }

    def _read_disk_job(self, job_id: str) -> dict | None:
        path = self._job_file(job_id)
        if path is None or path.is_symlink() or not path.is_file():
            return None
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
            if isinstance(data, dict) and data.get('job_id') == job_id:
                return self._maybe_recover_orphan(data, path)
        except (OSError, ValueError, TypeError):
            return None
        return None

    def _maybe_recover_orphan(self, data: dict, path: Path) -> dict:
        if data.get('status') in _ACTIVE_STATES and self._is_owner_stale(
            data.get('owner_host'), data.get('owner_pid'), data.get('owner_start_ticks')
        ):
            now_txt = _utc_now()
            data = dict(data)
            data['status'] = 'FAILED'
            data['stage'] = 'INTERRUPTED'
            data['message'] = '服务重启或工作进程异常退出，任务已中断（可重新发起）'
            data['error'] = 'WorkerRestarted: owning process is no longer running'
            data['finished_at'] = now_txt
            data['events'] = [*(data.get('events') or []), f'[{now_txt[11:19]}] 检测到原工作进程已退出，任务标记为中断']
            try:
                write_atomic(path, data)
            except OSError:
                pass
            if data.get('scope_key'):
                self._release_scope_lease(data['scope_key'], data['job_id'])
        return data

    def _reconcile_disk_jobs(self):
        if self._jobs_dir is None:
            return
        for p in self._jobs_dir.glob('job_*.json'):
            if p.is_symlink() or not p.is_file():
                continue
            try:
                data = json.loads(p.read_text(encoding='utf-8'))
                if isinstance(data, dict) and isinstance(data.get('job_id'), str):
                    self._maybe_recover_orphan(data, p)
            except (OSError, ValueError, TypeError):
                continue
        self._prune_disk_history()

    def _prune_disk_history(self):
        if self._jobs_dir is None:
            return
        terminal = []
        for p in self._jobs_dir.glob('job_*.json'):
            if p.is_symlink() or not p.is_file():
                continue
            try:
                data = json.loads(p.read_text(encoding='utf-8'))
                if isinstance(data, dict) and data.get('status') in _TERMINAL_STATES:
                    terminal.append((float(data.get('created_ts') or p.stat().st_mtime), p))
            except (OSError, ValueError, TypeError):
                continue
        if len(terminal) > self._max_history:
            terminal.sort(key=lambda pair: pair[0])
            for _, old_path in terminal[:-self._max_history]:
                old_path.unlink(missing_ok=True)

    def _acquire_scope_lease(self, scope_key: str, job_id: str):
        """Atomically acquire a cross-process scope lease via POSIX/NFS O_CREAT|O_EXCL."""
        lease_path = self._lease_file(scope_key)
        if lease_path is None:
            return
        payload = json.dumps({
            'scope_key': scope_key,
            'job_id': job_id,
            'owner_host': _HOSTNAME,
            'owner_pid': os.getpid(),
            'owner_start_ticks': _LOCAL_START_TICKS,
            'created_at': _utc_now(),
        }, ensure_ascii=False, separators=(',', ':')).encode('utf-8')

        for _ in range(3):
            try:
                fd = os.open(str(lease_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
                try:
                    os.write(fd, payload)
                    os.fsync(fd)
                finally:
                    os.close(fd)
                return
            except FileExistsError:
                existing_lease = None
                try:
                    existing_lease = json.loads(lease_path.read_text(encoding='utf-8'))
                except (OSError, ValueError, TypeError):
                    existing_lease = None
                existing_jid = existing_lease.get('job_id') if isinstance(existing_lease, dict) else None
                existing_job = self._read_disk_job(existing_jid) if existing_jid else None

                is_stale = False
                if existing_lease is None:
                    try:
                        is_stale = (time.time() - lease_path.stat().st_mtime) > 5.0
                    except OSError:
                        is_stale = True
                elif existing_job is not None and existing_job.get('status') in _TERMINAL_STATES:
                    is_stale = True
                elif self._is_owner_stale(
                    existing_lease.get('owner_host'),
                    existing_lease.get('owner_pid'),
                    existing_lease.get('owner_start_ticks'),
                ):
                    is_stale = True

                if is_stale:
                    reclaim = lease_path.with_name(f'.reclaim_{uuid.uuid4().hex}')
                    try:
                        os.replace(lease_path, reclaim)
                        reclaim.unlink(missing_ok=True)
                    except OSError:
                        pass
                    continue

                active_public = self._public_from_disk(existing_job) if existing_job else {
                    'job_id': existing_jid or 'unknown',
                    'label': scope_key,
                    'scope_key': scope_key,
                    'status': 'RUNNING',
                }
                raise JobConflictError(
                    f'同范围任务「{active_public.get("label", scope_key)}」正在执行中，请等待完成或先终止后再试',
                    active_public,
                )
        raise JobConflictError(f'同范围任务「{scope_key}」正在竞争锁，请稍后重试', {'scope_key': scope_key, 'status': 'RUNNING'})

    def _release_scope_lease(self, scope_key: str | None, job_id: str):
        if not scope_key or self._leases_dir is None:
            return
        lease_path = self._lease_file(scope_key)
        if lease_path is None or not lease_path.is_file() or lease_path.is_symlink():
            return
        try:
            data = json.loads(lease_path.read_text(encoding='utf-8'))
            if isinstance(data, dict) and data.get('job_id') == job_id:
                lease_path.unlink(missing_ok=True)
        except (OSError, ValueError, TypeError):
            pass

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

    def submit(self, kind: str, label: str, fn, *, scope_key: str | None = None) -> dict:
        """Submit a callable `fn(report_progress, cancel_event)` to run in background."""
        job_id = 'job_' + uuid.uuid4().hex[:16]
        t_created = time.monotonic()
        now_ts = time.time()
        cancel_path = self._cancel_file(job_id)
        cancel_event = _FileBackedCancelEvent(cancel_path)
        record = {
            'job_id': job_id,
            'kind': kind,
            'label': label,
            'scope_key': scope_key,
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
            'owner_host': _HOSTNAME,
            'owner_pid': os.getpid(),
            'owner_start_ticks': _LOCAL_START_TICKS,
            'created_ts': now_ts,
            'started_ts': None,
            '_t_created': t_created,
            '_t_started': None,
            '_t_finished': None,
            '_cancel_event': cancel_event,
            '_last_persist': 0.0,
        }
        with self._lock:
            if scope_key:
                for active in self._jobs.values():
                    if active.get('scope_key') == scope_key and active.get('status') in _ACTIVE_STATES:
                        if not self._is_owner_stale(active.get('owner_host'), active.get('owner_pid'), active.get('owner_start_ticks')):
                            raise JobConflictError(
                                f'同范围任务「{active["label"]}」正在执行中，请等待完成或先终止后再试',
                                self._public(active),
                            )
                # Acquire cross-process atomic lease on disk (when persistent work_root is configured)
                self._acquire_scope_lease(scope_key, job_id)
            self._jobs[job_id] = record
            self._order.append(job_id)
            while len(self._order) > self._max_history:
                old = self._order.pop(0)
                if self._jobs.get(old, {}).get('status') in _TERMINAL_STATES:
                    self._jobs.pop(old, None)
            self._persist_record(record)

        def report_progress(stage: str, message: str, *, completed=None, total=None):
            stamp = _utc_now()[11:19]
            should_persist = False
            with self._lock:
                if record['status'] in _TERMINAL_STATES:
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
                now_mono = time.monotonic()
                if now_mono - record['_last_persist'] >= 0.25:
                    record['_last_persist'] = now_mono
                    should_persist = True
            if should_persist:
                self._persist_record(record)

        def _runner():
            t_start = time.monotonic()
            try:
                with self._lock:
                    if cancel_event.is_set() or record['status'] == 'CANCELLED':
                        record['status'] = 'CANCELLED'
                        record['stage'] = 'CANCELLED'
                        record['message'] = '任务已在开始前终止'
                        record['finished_at'] = _utc_now()
                        record['_t_finished'] = t_start
                        self._persist_record(record)
                        return
                    record['status'] = 'RUNNING'
                    record['stage'] = 'RUNNING'
                    record['message'] = f'正在执行：{label}'
                    record['started_at'] = _utc_now()
                    record['started_ts'] = time.time()
                    record['_t_started'] = t_start
                    record['events'].append(f"[{_utc_now()[11:19]}] 开始执行")
                    self._persist_record(record)
                try:
                    res = fn(report_progress, cancel_event)
                    t_end = time.monotonic()
                    with self._lock:
                        refresh_status = res.get('status') if kind == 'refresh' and isinstance(res, dict) else None
                        record['status'] = refresh_status if refresh_status in ('PARTIAL', 'FAILED') else 'SUCCEEDED'
                        record['stage'] = 'DONE'
                        if record['status'] in ('PARTIAL', 'FAILED'):
                            details = []
                            if res.get('effective_failed'):
                                details.append(f"有效版本推进失败 {res['effective_failed']} 个库")
                            if res.get('indexes_failed'):
                                details.append(f"索引刷新失败 {res['indexes_failed']} 个库")
                            record['message'] = f"{label} · {' · '.join(details)}"
                        elif refresh_status == 'SKIPPED':
                            record['message'] = '同步选项均已关闭'
                        else:
                            record['message'] = f'{label} 已完成'
                        if record['total']:
                            record['completed'] = record['total']
                        record['percent'] = 100
                        record['finished_at'] = _utc_now()
                        record['_t_finished'] = t_end
                        record['elapsed_seconds'] = round(t_end - t_start, 3)
                        record['result'] = res
                        record['events'].append(f"[{_utc_now()[11:19]}] {record['message']}（耗时 {record['elapsed_seconds']}s）")
                        self._persist_record(record)
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
                        self._persist_record(record)
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
                        self._persist_record(record)
            finally:
                self._release_scope_lease(scope_key, job_id)
                if cancel_path is not None:
                    cancel_path.unlink(missing_ok=True)
                self._prune_disk_history()

        self._get_executor().submit(_runner)
        return self._public(record)

    def cancel(self, job_id: str):
        with self._lock:
            rec = self._jobs.get(job_id)
            if rec is not None:
                rec['_cancel_event'].set()
                rec['cancel_requested'] = True
                if rec['status'] == 'QUEUED':
                    rec['status'] = 'CANCELLED'
                    rec['stage'] = 'CANCELLED'
                    rec['message'] = '任务已在排队阶段终止'
                    rec['finished_at'] = _utc_now()
                    rec['events'].append(f"[{_utc_now()[11:19]}] 用户在排队阶段终止了任务")
                    self._release_scope_lease(rec.get('scope_key'), job_id)
                elif rec['status'] == 'RUNNING':
                    rec['status'] = 'CANCELLING'
                    rec['message'] = '已发送终止指令，等待当前原子步骤安全退出…'
                    rec['events'].append(f"[{_utc_now()[11:19]}] 收到终止指令，正在安全停止…")
                self._persist_record(rec)
                return self._public(rec)

        # Cross-process cancel: job belongs to another worker process sharing work_root
        disk_rec = self._read_disk_job(job_id)
        if disk_rec is None:
            return None
        cpath = self._cancel_file(job_id)
        if cpath is not None:
            try:
                cpath.touch(exist_ok=True)
            except OSError:
                pass
        if disk_rec.get('status') in _ACTIVE_STATES:
            disk_rec = dict(disk_rec)
            disk_rec['cancel_requested'] = True
            if disk_rec['status'] == 'RUNNING':
                disk_rec['status'] = 'CANCELLING'
                disk_rec['message'] = '已跨进程发送终止指令，等待当前原子步骤安全退出…'
                disk_rec['events'] = [*(disk_rec.get('events') or []), f"[{_utc_now()[11:19]}] 收到跨进程终止指令，正在安全停止…"]
            jpath = self._job_file(job_id)
            if jpath is not None and not jpath.is_symlink():
                try:
                    write_atomic(jpath, disk_rec)
                except OSError:
                    pass
        return self._public_from_disk(disk_rec)

    def _public(self, rec: dict) -> dict:
        elapsed = rec['elapsed_seconds']
        if rec['status'] in ('RUNNING', 'CANCELLING'):
            if rec.get('_t_started') is not None:
                elapsed = round(time.monotonic() - rec['_t_started'], 3)
            elif rec.get('started_ts') is not None:
                elapsed = round(max(0.0, time.time() - float(rec['started_ts'])), 3)
        elif rec['status'] == 'QUEUED':
            if rec.get('_t_created') is not None:
                elapsed = round(time.monotonic() - rec['_t_created'], 3)
            elif rec.get('created_ts') is not None:
                elapsed = round(max(0.0, time.time() - float(rec['created_ts'])), 3)
        return {
            'job_id': rec['job_id'],
            'kind': rec['kind'],
            'label': rec['label'],
            'scope_key': rec.get('scope_key'),
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

    def _public_from_disk(self, data: dict) -> dict:
        elapsed = data.get('elapsed_seconds', 0.0)
        if data.get('status') in ('RUNNING', 'CANCELLING') and data.get('started_ts') is not None:
            elapsed = round(max(0.0, time.time() - float(data['started_ts'])), 3)
        elif data.get('status') == 'QUEUED' and data.get('created_ts') is not None:
            elapsed = round(max(0.0, time.time() - float(data['created_ts'])), 3)
        return {
            'job_id': data['job_id'],
            'kind': data.get('kind', ''),
            'label': data.get('label', ''),
            'scope_key': data.get('scope_key'),
            'status': data.get('status', 'UNKNOWN'),
            'stage': data.get('stage', ''),
            'message': data.get('message', ''),
            'completed': data.get('completed', 0),
            'total': data.get('total'),
            'percent': data.get('percent'),
            'events': list(data.get('events') or []),
            'cancel_requested': bool(data.get('cancel_requested', False)),
            'created_at': data.get('created_at'),
            'started_at': data.get('started_at'),
            'finished_at': data.get('finished_at'),
            'elapsed_seconds': elapsed,
            'result': data.get('result'),
            'error': data.get('error'),
        }

    def get(self, job_id: str):
        with self._lock:
            rec = self._jobs.get(job_id)
            if rec is not None:
                return self._public(rec)
        disk_rec = self._read_disk_job(job_id)
        return self._public_from_disk(disk_rec) if disk_rec else None

    def list_recent(self, *, limit: int = 20) -> list[dict]:
        if self._jobs_dir is None:
            with self._lock:
                ids = list(reversed(self._order[-limit:]))
                return [self._public(self._jobs[i]) for i in ids if i in self._jobs]
        merged = {}
        for p in self._jobs_dir.glob('job_*.json'):
            if p.is_symlink() or not p.is_file():
                continue
            try:
                data = json.loads(p.read_text(encoding='utf-8'))
                if isinstance(data, dict) and isinstance(data.get('job_id'), str):
                    data = self._maybe_recover_orphan(data, p)
                    merged[data['job_id']] = (float(data.get('created_ts') or 0.0), self._public_from_disk(data))
            except (OSError, ValueError, TypeError):
                continue
        with self._lock:
            for jid, rec in self._jobs.items():
                merged[jid] = (float(rec.get('created_ts') or 0.0), self._public(rec))
        ordered = sorted(merged.values(), key=lambda pair: (pair[0], pair[1]['job_id']), reverse=True)
        return [item for _, item in ordered[:limit]]
