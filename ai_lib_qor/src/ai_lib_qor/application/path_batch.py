"""Incremental batch QoR checks over path-based libraries that have unchecked (or outdated-tooling) latest revisions."""
import json
from pathlib import Path

from ai_lib_qor.checks.path_plugins import resolve_path_plugins
from ai_lib_qor.sources.layout import SAFE, library_folder
from ai_lib_qor.versions.runtime import check_cancel, emit_progress
from .ip_partition import active_tracks_for_library
from .minimal_checks import run_revision
from .minimal_effective import _history, _norm_business_ip, list_track_effective_ips
from .path_config import effective_check_plugins, library_ip_config
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
    business_ip=None,
    ip_type=None,
    render_excel=False,
    single_renderer=None,
    rerun=False,
    include_outdated=False,
    plugins=None,
    limit=None,
    progress_cb=None,
    cancel_event=None,
):
    """Run single-revision checks for libraries/tracks whose latest effective revision lacks a saved check."""
    root = Path(work).resolve(strict=True)
    query = PathDataQuery(root)
    wanted_ip = _norm_business_ip(business_ip)
    wanted_type = ip_type.strip().casefold() if isinstance(ip_type, str) and ip_type.strip() else None
    lib_targets = _iter_targets(root, vendor=vendor, library=library)

    # Expand multi-track libraries into per-(vendor, library, business_ip) units while preserving single-track libraries.
    work_units = []
    for v, lib in lib_targets:
        ip_cfg = library_ip_config(root, v, lib)
        if wanted_type is not None and (ip_cfg['ip_type'] or '').casefold() != wanted_type:
            continue
        if ip_cfg['is_multi_track']:
            folder = library_folder(root, v, lib)
            tinfo = active_tracks_for_library(root, v, lib)
            ips = list(dict.fromkeys([*tinfo['tracks'].keys(), *list_track_effective_ips(folder, lib)]))
            for ip in ips:
                if wanted_ip is not None and ip != wanted_ip:
                    continue
                work_units.append((v, lib, ip, ip_cfg['ip_type']))
        else:
            if wanted_ip is not None:
                continue
            work_units.append((v, lib, None, ip_cfg['ip_type']))

    total = len(work_units)
    checked = []
    skipped_already_checked = []
    skipped_no_revision = []
    errors = []
    failed_checks_total = 0
    outdated_tooling_count = 0

    for idx, (v, lib, ip, lib_ip_type) in enumerate(work_units, 1):
        scope_tag = f'{v}/{lib}::{ip}' if ip else f'{v}/{lib}'
        check_cancel(cancel_event, '增量批量检查已由用户终止')
        emit_progress(progress_cb, 'CHECK', f'检查进度 {scope_tag} ({idx}/{total})', completed=idx - 1, total=total)
        if limit is not None and len(checked) >= limit:
            break
        try:
            index = query.index(v, lib)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            err_row = {'vendor': v, 'library': lib, 'error': str(exc)}
            if ip is not None:
                err_row['business_ip'] = ip
            errors.append(err_row)
            continue

        if ip is not None:
            folder = library_folder(root, v, lib)
            try:
                hist = _history(folder, lib, business_ip=ip)
            except (OSError, ValueError, KeyError, TypeError) as exc:
                errors.append({'vendor': v, 'library': lib, 'business_ip': ip, 'error': str(exc)})
                continue
            revs = [r[2]['revision'] for r in hist]
        else:
            revs = index.get('revisions') or []

        if not revs:
            row = {'vendor': v, 'library': lib}
            if ip is not None:
                row['business_ip'] = ip
                row['ip_type'] = lib_ip_type
            skipped_no_revision.append(row)
            continue

        latest = revs[-1]
        baseline = revs[-2] if len(revs) >= 2 else None
        rerun_reason = 'FORCED_RERUN' if rerun else None
        eff_plugins = effective_check_plugins(root, v, lib, ip_type=lib_ip_type, explicit_plugins=plugins)
        expected_plugins = [name for name, _ in resolve_path_plugins(eff_plugins)]
        if not rerun:
            existing = latest_check_for_scope(root, v, lib, latest, baseline, plugins=expected_plugins, business_ip=ip)
            if existing:
                tooling = existing.get('tooling_status') or {'status': 'CURRENT', 'is_stale': False, 'reasons': []}
                if tooling['is_stale']:
                    outdated_tooling_count += 1
                    if include_outdated:
                        rerun_reason = 'STALE_TOOLING'
                    else:
                        skip_row = {
                            'vendor': v,
                            'library': lib,
                            'revision': latest,
                            'baseline': baseline,
                            'check_name': existing['check_name'],
                            'state': existing['state'],
                            'tooling_status': tooling['status'],
                            'tooling_reasons': tooling['reasons'],
                        }
                        if ip is not None:
                            skip_row['business_ip'] = ip
                            skip_row['ip_type'] = lib_ip_type
                        skipped_already_checked.append(skip_row)
                        continue
                else:
                    skip_row = {
                        'vendor': v,
                        'library': lib,
                        'revision': latest,
                        'baseline': baseline,
                        'check_name': existing['check_name'],
                        'state': existing['state'],
                        'tooling_status': tooling['status'],
                    }
                    if ip is not None:
                        skip_row['business_ip'] = ip
                        skip_row['ip_type'] = lib_ip_type
                    skipped_already_checked.append(skip_row)
                    continue
        try:
            res = run_revision(
                root,
                v,
                lib,
                latest,
                baseline=baseline,
                business_ip=ip,
                plugins=plugins,
                render=render_excel,
                single_renderer=single_renderer,
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
            if ip is not None:
                entry['business_ip'] = ip
                entry['ip_type'] = lib_ip_type
            if rerun_reason:
                entry['rerun_reason'] = rerun_reason
            checked.append(entry)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            err_row = {'vendor': v, 'library': lib, 'revision': latest, 'error': str(exc)}
            if ip is not None:
                err_row['business_ip'] = ip
            errors.append(err_row)

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
