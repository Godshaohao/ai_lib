"""Incremental batch QoR checks over path-based libraries that have unchecked (or outdated-tooling) latest revisions."""
import json
from pathlib import Path

from ai_lib_qor.checks.path_plugins import resolve_path_plugins
from ai_lib_qor.sources.layout import SAFE, library_folder
from ai_lib_qor.versions.runtime import check_cancel, emit_progress
from .minimal_checks import run_revision
from .path_query import PathDataQuery, latest_check_for_scope


def _iter_targets(work: Path, vendor=None, library=None):
    if bool(vendor) != bool(library):
        raise ValueError('vendor 和 library 必须同时指定或同时省略')
    if vendor:
        folder = library_folder(work, vendor, library)
        if not folder.is_dir():
            raise ValueError('指定库目录不存在')
        return [(vendor, library)]
    libs_root = work / 'libraries'
    if not libs_root.is_dir():
        return []
    out = []
    for v_dir in sorted(libs_root.iterdir()):
        if v_dir.is_symlink() or not v_dir.is_dir() or not SAFE.fullmatch(v_dir.name):
            continue
        for l_dir in sorted(v_dir.iterdir()):
            if l_dir.is_symlink() or not l_dir.is_dir() or not SAFE.fullmatch(l_dir.name):
                continue
            out.append((v_dir.name, l_dir.name))
    return out


def check_pending(
    work,
    *,
    vendor=None,
    library=None,
    render_excel=False,
    rerun=False,
    include_outdated=False,
    plugins=None,
    limit=None,
    progress_cb=None,
    cancel_event=None,
):
    """Run single-revision checks for libraries whose latest effective revision lacks a saved check (or has stale tooling when include_outdated=True)."""
    root = Path(work).resolve(strict=True)
    query = PathDataQuery(root)
    expected_plugins = [name for name, _ in resolve_path_plugins(plugins)]
    targets = _iter_targets(root, vendor=vendor, library=library)
    total = len(targets)

    checked = []
    skipped_already_checked = []
    skipped_no_revision = []
    errors = []
    failed_checks_total = 0
    outdated_tooling_count = 0

    for idx, (v, lib) in enumerate(targets, 1):
        check_cancel(cancel_event, '增量批量检查已由用户终止')
        emit_progress(progress_cb, 'CHECK', f'检查进度 {v}/{lib} ({idx}/{total})', completed=idx - 1, total=total)
        if limit is not None and len(checked) >= limit:
            break
        try:
            index = query.index(v, lib)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            errors.append({'vendor': v, 'library': lib, 'error': str(exc)})
            continue
        revs = index.get('revisions') or []
        if not revs:
            skipped_no_revision.append({'vendor': v, 'library': lib})
            continue
        latest = revs[-1]
        baseline = revs[-2] if len(revs) >= 2 else None
        rerun_reason = 'FORCED_RERUN' if rerun else None
        if not rerun:
            existing = latest_check_for_scope(root, v, lib, latest, baseline, plugins=expected_plugins)
            if existing:
                tooling = existing.get('tooling_status') or {'status': 'CURRENT', 'is_stale': False, 'reasons': []}
                if tooling['is_stale']:
                    outdated_tooling_count += 1
                    if include_outdated:
                        rerun_reason = 'STALE_TOOLING'
                    else:
                        skipped_already_checked.append({
                            'vendor': v,
                            'library': lib,
                            'revision': latest,
                            'baseline': baseline,
                            'check_name': existing['check_name'],
                            'state': existing['state'],
                            'tooling_status': tooling['status'],
                            'tooling_reasons': tooling['reasons'],
                        })
                        continue
                else:
                    skipped_already_checked.append({
                        'vendor': v,
                        'library': lib,
                        'revision': latest,
                        'baseline': baseline,
                        'check_name': existing['check_name'],
                        'state': existing['state'],
                        'tooling_status': tooling['status'],
                    })
                    continue
        try:
            res = run_revision(
                root,
                v,
                lib,
                latest,
                baseline=baseline,
                plugins=plugins,
                render=render_excel,
                cancel_event=cancel_event,
            )
            report = json.loads(Path(res['check']).read_text(encoding='utf-8'))
            f_checks = report.get('summary', {}).get('failed_checks', 0)
            failed_checks_total += f_checks
            entry = {
                'vendor': v,
                'library': lib,
                'revision': latest,
                'baseline': baseline,
                'state': res['state'],
                'run_id': res['run_id'],
                'check': Path(res['check']).name,
                'excel': Path(res['excel']).name if res.get('excel') else None,
                'failed_checks': f_checks,
                'failed_files': report.get('summary', {}).get('failed_files', 0),
                'inconclusive_checks': report.get('summary', {}).get('inconclusive_checks', 0),
            }
            if rerun_reason:
                entry['rerun_reason'] = rerun_reason
            checked.append(entry)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            errors.append({'vendor': v, 'library': lib, 'revision': latest, 'error': str(exc)})

    emit_progress(progress_cb, 'CHECK', f'批量检查完成：新检查 {len(checked)} 库 · 跳过 {len(skipped_already_checked)} 库', completed=total, total=total)

    overall_state = (
        'FAILED' if errors else (
            'PARTIAL' if any(x['state'] != 'SUCCEEDED' for x in checked) else 'SUCCEEDED'
        )
    )
    return {
        'work': str(root),
        'state': overall_state,
        'render_excel': render_excel,
        'include_outdated': include_outdated,
        'checked_count': len(checked),
        'skipped_already_checked_count': len(skipped_already_checked),
        'skipped_no_revision_count': len(skipped_no_revision),
        'outdated_tooling_count': outdated_tooling_count,
        'error_count': len(errors),
        'failed_checks_total': failed_checks_total,
        'checked': checked,
        'skipped_already_checked': skipped_already_checked,
        'skipped_no_revision': skipped_no_revision,
        'errors': errors,
    }
