"""Isolated OS subprocess worker for heavy workbench jobs (avoids GIL contention and returns RSS on exit)."""
import json
import os
from pathlib import Path
import sys
from urllib.parse import urlencode

from ai_lib_qor.versions.runtime import JobCancelledError
from .jobs import _FileBackedCancelEvent


def _emit(payload: dict) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False, default=str) + '\n')
    sys.stdout.flush()


def _run_spec(spec: dict) -> dict:
    work = Path(spec['work']).resolve()
    cancel_path = Path(spec['cancel_path']) if spec.get('cancel_path') else None
    cancel_event = _FileBackedCancelEvent(cancel_path)

    from ai_lib_qor.application.plugin_loader import load_configured_plugins
    load_configured_plugins(work)

    def report_progress(stage: str, message: str, *, completed=None, total=None):
        _emit({
            'event': 'progress',
            'stage': str(stage),
            'message': str(message),
            'completed': completed,
            'total': total,
        })

    task = spec['task']
    if task == 'refresh':
        from .refresh_forms import run_refresh_form
        res = run_refresh_form(
            work,
            spec['layer'],
            spec['form'],
            spec['options'],
            vendor=spec.get('vendor'),
            library=spec.get('library'),
            actor=spec.get('actor', 'web-async'),
            progress_cb=report_progress,
            cancel_event=cancel_event,
        )
        if isinstance(res, dict):
            res['_worker_pid'] = os.getpid()
        return res

    from ai_lib_qor.application.minimal_checks import run_library, run_revision
    from ai_lib_qor.application.path_batch import check_pending
    from ai_lib_qor.reporting.check_renderer import (
        render_excel_from_check,
        render_overall_excel_rows,
        render_timeline_excel_for_scope,
    )

    if task == 'check_pending':
        res = check_pending(
            work,
            vendor=spec.get('vendor'),
            library=spec.get('library'),
            business_ip=spec.get('business_ip'),
            ip_type=spec.get('ip_type'),
            render_excel=bool(spec.get('render_excel', False)),
            single_renderer=render_excel_from_check,
            rerun=bool(spec.get('rerun', False)),
            include_outdated=bool(spec.get('include_outdated', False)),
            progress_cb=report_progress,
            cancel_event=cancel_event,
        )
        if isinstance(res, dict):
            res['_worker_pid'] = os.getpid()
        return res

    vendor = spec['vendor']
    library = spec['library']
    business_ip = spec.get('business_ip')
    lazy_excel = bool(spec.get('lazy_excel', True))
    update_timeline = bool(spec.get('update_timeline', True))
    report_page = spec.get('report_page', '')

    if task == 'check_library':
        res = run_library(
            work,
            vendor,
            library,
            business_ip=business_ip,
            rerun=bool(spec.get('rerun', False)),
            render_single_excel=not lazy_excel,
            single_renderer=render_excel_from_check,
            overall_renderer=render_overall_excel_rows,
            progress_cb=report_progress,
            cancel_event=cancel_event,
        )
        if update_timeline:
            try:
                res['timeline_excel'] = render_timeline_excel_for_scope(work, vendor, library, business_ip=business_ip)
            except (OSError, ValueError, KeyError, TypeError):
                pass
        if report_page and res.get('overall'):
            res['report_url'] = report_page + '&' + urlencode({'name': Path(res['overall']).name})
        res['_worker_pid'] = os.getpid()
        return res

    if task == 'check_revision':
        res = run_revision(
            work,
            vendor,
            library,
            spec['revision'],
            baseline=spec.get('baseline'),
            business_ip=business_ip,
            render=not lazy_excel,
            single_renderer=render_excel_from_check,
            progress_cb=report_progress,
            cancel_event=cancel_event,
        )
        if update_timeline:
            try:
                res['timeline_excel'] = render_timeline_excel_for_scope(work, vendor, library, business_ip=business_ip)
            except (OSError, ValueError, KeyError, TypeError):
                pass
        if report_page and res.get('check'):
            res['report_url'] = report_page + '&' + urlencode({'name': Path(res['check']).name})
        res['_worker_pid'] = os.getpid()
        return res

    raise ValueError(f'未知子进程作业类型: {task}')


def main() -> int:
    try:
        raw = sys.stdin.read()
        spec = json.loads(raw)
        result = _run_spec(spec)
        _emit({'event': 'result', 'data': result})
        return 0
    except JobCancelledError as exc:
        _emit({'event': 'cancelled', 'error': str(exc)})
        return 0
    except Exception as exc:
        _emit({'event': 'error', 'error': str(exc), 'exc_type': type(exc).__name__})
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
