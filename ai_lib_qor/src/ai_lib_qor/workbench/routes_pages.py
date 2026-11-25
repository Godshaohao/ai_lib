"""Read-only HTML pages and file download routes for the path workbench (thin adapter over application/reporting)."""
from io import BytesIO
import json
from pathlib import Path
import re
import tempfile

from flask import abort, render_template, request, send_file

from ai_lib_qor.application.facts_pool import load_check_bundle
from ai_lib_qor.application.path_acceptance import acceptance_status, report_cache_is_current
from ai_lib_qor.application.path_config import liberty_parse_filter, select_liberty_files, skip_parse_views
from ai_lib_qor.application.path_query import (
    collect_json_inventory as _collect_json_inventory,
    format_bytes as _fmt_bytes,
    latest_check_for_scope,
    query_file_index,
    query_json_inventory,
    source_verification_note as _source_verification_note,
    unadopted_new_files,
)
from ai_lib_qor.application.path_refresh import refresh_status
from ai_lib_qor.application.path_storage import storage_stats
from ai_lib_qor.sources.layout import archive_files, library_folder


def _resolve_library_track(work, vendor, library, folder, index):
    """Read-only helper: resolve optional multi-track ?ip= param and project file_index onto the active track."""
    from ai_lib_qor.application.ip_partition import active_tracks_for_library
    from ai_lib_qor.application.minimal_effective import _norm_business_ip, list_track_effective_ips
    from ai_lib_qor.application.path_query import PathDataQuery, build_track_index_view

    track_info = active_tracks_for_library(work, vendor, library)
    requested_raw = (request.args.get('ip') or request.args.get('business_ip') or '').strip()
    if not track_info['is_multi_track']:
        if requested_raw:
            abort(400)
        return index, None, track_info, []

    try:
        requested_ip = _norm_business_ip(requested_raw) if requested_raw else None
    except ValueError:
        abort(400)
    available_ips = list(dict.fromkeys([
        *track_info['ip_list'],
        *track_info['tracks'].keys(),
        *list_track_effective_ips(folder, library),
    ]))
    if requested_ip is not None and requested_ip not in available_ips:
        abort(400)

    track_rows = PathDataQuery(work).list_tracks(vendor=vendor, library=library, include_checks=False)['tracks']
    track_map = {t['business_ip']: t for t in track_rows}
    if requested_ip is not None:
        active_ip = requested_ip
    else:
        first_with_rev = next((t['business_ip'] for t in track_rows if t.get('revisions')), None)
        active_ip = first_with_rev or (available_ips[0] if available_ips else None)

    available_tracks = []
    for ip_name in available_ips:
        t = track_map.get(ip_name) or {}
        available_tracks.append({
            'business_ip': ip_name,
            'version_count': len(track_info['tracks'].get(ip_name) or []),
            'revision_count': len(t.get('revisions') or []),
            'latest_revision': t.get('latest_revision'),
            'accepted_revision': t.get('accepted_revision'),
            'is_active': ip_name == active_ip,
        })

    projected = index
    if index and active_ip:
        projected, _, _ = build_track_index_view(folder, vendor, library, index, active_ip)
    return projected, active_ip, track_info, available_tracks


def register_page_routes(app, ctx):
    work = ctx['work']
    read_cache = ctx['read_cache']
    scope = ctx['scope']
    index_state = ctx['index_state']
    source_config = ctx['source_config']

    @app.get('/')
    def overview():
        from ai_lib_qor.application.path_query import PathDataQuery, workspace_activity_and_readiness

        sig = read_cache.signature()

        def _compute_core():
            status = refresh_status(work, limit=8)
            query = PathDataQuery(work)
            libraries = []
            for item in status['libraries']:
                err = None
                attempt = item['index_attempt'] or {}
                if attempt.get('status') == 'FAILED':
                    err = attempt['reason']
                elif item['index_status'] == 'MISSING':
                    err = '索引未生成，请刷新 L3'
                elif item['index_status'] == 'STALE':
                    err = '归档已更新，索引待刷新 (L3)'
                sources = item['source_verifications']
                track_items = []
                accepted_track_count = 0
                if item.get('is_multi_track'):
                    try:
                        track_items = query.list_tracks(
                            vendor=item['vendor'],
                            library=item['library'],
                            include_checks=False,
                        )['tracks']
                        accepted_track_count = sum(1 for t in track_items if t.get('accepted_revision'))
                    except (OSError, ValueError):
                        track_items = []
                libraries.append({
                    **item,
                    'error': err,
                    'track_items': track_items,
                    'accepted_track_count': accepted_track_count,
                    'raw_verification_note': _source_verification_note('RAW', sources.get('RAW')),
                    'formal_verification_notes': {
                        version: _source_verification_note('Formal', evidence)
                        for version, evidence in sorted(sources.get('FORMAL', {}).items())
                    },
                })
            ip_types = sorted({x['ip_type'] for x in libraries if x.get('ip_type')})
            needs_review_libraries = [x for x in libraries if int(x.get('needs_review_count', 0)) > 0]
            summary = {
                'vendors': status['totals']['vendors'],
                'libraries': status['totals']['libraries'],
                'with_effective': status['totals']['libraries_with_effective'],
                'accepted': sum(1 for x in libraries if x.get('accepted_revision') or x.get('accepted_track_count', 0) > 0),
                'revisions': status['totals']['revisions'],
                'issues': sum(1 for x in libraries if x.get('error') or int(x.get('needs_review_count', 0)) > 0),
                'multi_track_libraries': sum(1 for x in libraries if x.get('is_multi_track')),
                'needs_review_total': sum(int(x.get('needs_review_count', 0)) for x in libraries),
            }
            try:
                st = storage_stats(work)
                storage_display = {
                    'total': _fmt_bytes(st['total_bytes']),
                    'auth': _fmt_bytes(st['authoritative_bytes']),
                    'cache': _fmt_bytes(st['rebuildable_cache_bytes']),
                }
            except (OSError, ValueError):
                storage_display = None
            return status, libraries, ip_types, needs_review_libraries, summary, storage_display

        status, libraries, ip_types, needs_review_libraries, summary, storage_display = read_cache.get_or_compute(
            'overview_core', _compute_core, sig=sig,
        )

        json_filter_key = tuple(
            (k, request.args.get(k, ''))
            for k in ('json_layer', 'json_status', 'json_scope', 'json_lib', 'json_q', 'json_sort', 'json_page')
        )
        json_inventory = read_cache.get_or_compute(
            ('overview_json_inventory', json_filter_key),
            lambda: _collect_json_inventory(work, status, libraries, filters=request.args),
            sig=sig,
        )

        raw_days = (request.args.get('days') or '7').strip().lower()
        if raw_days == 'all':
            activity_days = None
        else:
            try:
                activity_days = max(1, int(raw_days))
            except ValueError:
                activity_days = 7
        import time
        time_bucket = int(time.time() // 300)
        activity = read_cache.get_or_compute(
            ('overview_activity', activity_days, time_bucket),
            lambda: workspace_activity_and_readiness(work, days=activity_days, refresh_info=status),
            sig=sig,
        )
        req_view = (request.args.get('view') or '').strip().lower()
        req_pipe = (request.args.get('pipe_tab') or '').strip().lower()
        has_json_q = any(request.args.get(k) for k in ('json_layer', 'json_status', 'json_scope', 'json_lib', 'json_q', 'json_page', 'json_sort'))
        if req_view in ('layers', 'json', 'history'):
            active_domain = 'pipeline'
            active_pipeline_tab = req_view
        elif req_view == 'pipeline':
            active_domain = 'pipeline'
            active_pipeline_tab = req_pipe if req_pipe in ('layers', 'json', 'history') else ('json' if has_json_q else 'layers')
        elif req_view in ('activity', 'libraries', 'config'):
            active_domain = req_view
            active_pipeline_tab = 'json' if has_json_q else 'layers'
        elif has_json_q:
            active_domain = 'pipeline'
            active_pipeline_tab = 'json'
        else:
            active_domain = 'activity'
            active_pipeline_tab = 'layers'
        active_view = active_pipeline_tab if active_domain == 'pipeline' else active_domain
        from ai_lib_qor.application.path_config import workbench_runtime_settings
        try:
            runtime_settings = workbench_runtime_settings(work)
        except (OSError, ValueError, TypeError):
            runtime_settings = None
        try:
            effective_liberty_filter = liberty_parse_filter(work)
        except (OSError, ValueError, TypeError):
            effective_liberty_filter = None
        return render_template(
            'path_overview.html',
            libraries=libraries,
            config=source_config(),
            runtime_settings=runtime_settings,
            effective_liberty_filter=effective_liberty_filter,
            summary=summary,
            refresh_info=status,
            storage_display=storage_display,
            json_inventory=json_inventory,
            activity=activity,
            active_view=active_view,
            active_domain=active_domain,
            active_pipeline_tab=active_pipeline_tab,
            ip_types=ip_types,
            needs_review_libraries=needs_review_libraries,
        )

    @app.get('/path/overview/export.xlsx')
    def overview_export_excel():
        from ai_lib_qor.reporting.work_overview_excel import render_work_overview_excel
        with tempfile.TemporaryDirectory() as tmpdir:
            out = Path(tmpdir) / 'workspace_overview.xlsx'
            render_work_overview_excel(work, out, overwrite=True)
            data = out.read_bytes()
        return send_file(
            BytesIO(data),
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            as_attachment=True,
            download_name='ai_lib_qor_workspace_overview.xlsx',
        )

    @app.get('/path/library')
    def library_page():
        vendor, library, folder = scope()
        raw_index, error = index_state(vendor, library, folder)
        index, business_ip, track_info, available_tracks = _resolve_library_track(work, vendor, library, folder, raw_index)
        revision = request.args.get('revision', '')
        baseline = request.args.get('baseline', '')
        members = []
        removed = []
        delivery_rows = []
        member_views = []
        liberty_preview = None
        rev_meta = {}
        prev_rev = None
        next_rev = None
        baseline_rev = None
        check_baseline_param = '__prev_file__'
        rev_idx = -1
        ver_to_track = {}
        conflict_vers = set()
        unassigned_vers = set()
        if track_info['is_multi_track']:
            for ip_name, vers in (track_info.get('tracks') or {}).items():
                for ver in vers:
                    ver_to_track[ver] = ip_name
            nr = track_info.get('needs_review') or {}
            conflict_vers = {c['version'] for c in (nr.get('conflicts') or []) if isinstance(c, dict) and c.get('version')}
            unassigned_vers = {
                (u['version'] if isinstance(u, dict) else str(u))
                for u in (nr.get('unassigned') or [])
                if (isinstance(u, dict) and u.get('version')) or isinstance(u, str)
            }
        if index:
            if revision and revision not in index['revisions']:
                abort(400)
            if not revision and index['revisions']:
                revision = index['revisions'][-1]
            if revision:
                rev_idx = index['revisions'].index(revision)
                prev_rev = index['revisions'][rev_idx - 1] if rev_idx > 0 else None
                next_rev = index['revisions'][rev_idx + 1] if rev_idx < len(index['revisions']) - 1 else None
            if baseline == '__none__':
                baseline_rev = None
                check_baseline_param = '__none__'
            elif baseline == '__prev_file__':
                baseline_rev = prev_rev
                check_baseline_param = '__prev_file__'
            elif baseline:
                if baseline not in index['revisions'] or index['revisions'].index(baseline) >= rev_idx:
                    abort(400)
                baseline_rev = baseline
                check_baseline_param = baseline
            else:
                baseline_rev = prev_rev
                check_baseline_param = '__prev_file__'

            # Single-pass member, delivery & per-revision source mapping: O(F) instead of O(D * F * R)
            deliv_order = {d['version']: i for i, d in enumerate(index.get('deliveries') or [])}
            rev_latest_deliv: dict[str, tuple[int, str]] = {}
            deliv_total_counts: dict[str, int] = {}
            deliv_view_counts: dict[str, dict[str, int]] = {}
            for view, group in index['views'].items():
                for path, row in group.items():
                    curr_entry = None
                    base_entry = None
                    for entry in row['effective']:
                        er = entry['revision']
                        ev_ver = entry.get('version') or ''
                        if ev_ver:
                            ord_idx = deliv_order.get(ev_ver, -1)
                            prev_best = rev_latest_deliv.get(er)
                            if prev_best is None or ord_idx > prev_best[0]:
                                rev_latest_deliv[er] = (ord_idx, ev_ver)
                        if er == revision:
                            curr_entry = entry
                        if baseline_rev and er == baseline_rev:
                            base_entry = entry
                    if curr_entry is not None:
                        if baseline_rev:
                            if base_entry is not None:
                                diff_status = 'INHERITED' if base_entry['version'] == curr_entry['version'] else 'UPDATED'
                            else:
                                diff_status = 'NEW'
                        else:
                            diff_status = 'CURRENT'
                        members.append({'view': view, 'relative_path': path, 'diff_status': diff_status, **curr_entry})
                    elif base_entry is not None:
                        removed.append({'view': view, 'relative_path': path, **base_entry})

                    seen_vers = {entry['version'] for entry in row['raw']}
                    for dv in seen_vers:
                        deliv_total_counts[dv] = deliv_total_counts.get(dv, 0) + 1
                        vmap = deliv_view_counts.setdefault(dv, {})
                        vmap[view] = vmap.get(view, 0) + 1

            rev_meta = {}
            for idx_r, rev_id in enumerate(index['revisions'], 1):
                src_ver = rev_latest_deliv.get(rev_id, (-1, ''))[1]
                rev_meta[rev_id] = {
                    'seq': idx_r,
                    'source_version': src_ver,
                    'short': f'有效版 #{idx_r} ({rev_id})',
                    'label': f'有效版 #{idx_r} ({rev_id}) · {src_ver}' if src_ver else f'有效版 #{idx_r} ({rev_id})',
                }

            member_views = sorted({m['view'] for m in members} | {r['view'] for r in removed})
            if revision and not error:
                liberty_paths = [m['relative_path'] for m in members if m['view'] == 'LIBERTY']
                skipped_views = skip_parse_views(work, vendor, library)
                lf_policy = liberty_parse_filter(work, vendor, library)
                liberty_preview = select_liberty_files(
                    [] if 'LIBERTY' in skipped_views else liberty_paths,
                    lf_policy,
                )
                liberty_preview['member_count'] = len(liberty_paths)
                liberty_preview['skipped_by_view_policy'] = 'LIBERTY' in skipped_views
                liberty_preview['lef_skipped_by_view_policy'] = 'LEF' in skipped_views
                liberty_preview['skipped_views'] = skipped_views
            diff_counts = {
                'NEW': sum(1 for m in members if m['diff_status'] == 'NEW'),
                'UPDATED': sum(1 for m in members if m['diff_status'] == 'UPDATED'),
                'INHERITED': sum(1 for m in members if m['diff_status'] == 'INHERITED'),
                'REMOVED': len(removed),
            }
            diff_counts['CHANGED'] = diff_counts['NEW'] + diff_counts['UPDATED'] + diff_counts['REMOVED']
            for delivery in index['deliveries']:
                dv = delivery['version']
                delivery_rows.append({
                    **delivery,
                    'file_count': deliv_total_counts.get(dv, 0),
                    'view_counts': deliv_view_counts.get(dv, {}),
                    'track_ip': ver_to_track.get(dv),
                    'review_status': 'CONFLICT' if dv in conflict_vers else ('UNASSIGNED' if dv in unassigned_vers else None),
                })
        else:
            diff_counts = {'NEW': 0, 'UPDATED': 0, 'INHERITED': 0, 'REMOVED': 0, 'CHANGED': 0}

        from ai_lib_qor.checks.path_plugins import evaluate_check_verdict
        from ai_lib_qor.versions.store import read_json_readonly
        artifacts = []
        log_dir = folder / 'log'
        if business_ip:
            check_candidates = [
                *folder.glob('check_run_*.json'),
                *(log_dir.glob(f'check__{business_ip}__*.json') if log_dir.is_dir() else ()),
            ]
        else:
            check_candidates = [
                *folder.glob('check_run_*.json'),
                *(p for p in (log_dir.glob('check_*.json') if log_dir.is_dir() else ()) if not p.name.startswith('check__')),
            ]
        for path in sorted(check_candidates, key=lambda p: p.stat().st_mtime_ns, reverse=True):
            if path.is_symlink():
                continue
            try:
                d = read_json_readonly(path)
                if d.get('schema_version') == 'check_result.path.v1' and d.get('business_ip') == business_ip:
                    report = path.with_suffix('.xlsx').name if path.parent.name == 'log' else 'report_' + d['run_id'] + '.xlsx'
                    verdict = evaluate_check_verdict(d)
                    failed_checks = verdict['failed_checks']
                    inconclusive_checks = verdict['inconclusive_checks']
                    failed_files = verdict['failed_files']
                    run_state = d.get('state', 'UNKNOWN')
                    q_code, q_cls, q_text = verdict['code'], verdict['cls'], verdict['text']
                    facts_files = sorted({Path(f['facts']).name for f in d.get('files', []) if f.get('facts')})
                    artifacts.append({
                        'kind': 'SINGLE',
                        'name': report,
                        'check': path.name,
                        'revision': d['revision'],
                        'baseline': d.get('baseline'),
                        'business_ip': d.get('business_ip'),
                        'run_at': d.get('run_at', ''),
                        'run_state': run_state,
                        'quality_code': q_code,
                        'quality_cls': q_cls,
                        'quality_text': q_text,
                        'failed_checks': failed_checks,
                        'inconclusive_checks': inconclusive_checks,
                        'failed_files': failed_files,
                        'facts_files': facts_files,
                        'label': d['revision'] + ' · 运行 ' + run_state + ' · 失败 ' + str(failed_checks) + ' · 无结论 ' + str(inconclusive_checks) + ' · 文件失败 ' + str(failed_files),
                        'excel_cached': (path.parent / report).is_file(),
                        'available': (path.parent / report).is_file() or path.parent.name == 'log',
                    })
            except (OSError, ValueError, KeyError):
                continue
        overall_candidates = (
            list((folder / 'log').glob(f'overall__{business_ip}__*.xlsx'))
            if business_ip
            else [
                *folder.glob('overall_*.xlsx'),
                *(p for p in (folder / 'log').glob('overall_*.xlsx') if not p.name.startswith('overall__')),
            ]
        )
        for path in sorted(overall_candidates, key=lambda p: p.stat().st_mtime_ns, reverse=True):
            if not path.is_symlink():
                artifacts.append({
                    'kind': 'OVERALL',
                    'name': path.name,
                    'business_ip': business_ip,
                    'label': '整体报告 · ' + path.name,
                    'overall_json': path.with_suffix('.json').name if path.with_suffix('.json').is_file() and not path.with_suffix('.json').is_symlink() else None,
                    'available': True,
                })
        audit_filename = f'effective_operations__{business_ip}.tsv' if business_ip else 'effective_operations.tsv'
        audit_available = any(p.is_file() and not p.is_symlink() for p in (folder / audit_filename, folder / 'log' / audit_filename))
        latest_check = None
        latest_path = folder / (f'latest_check__{business_ip}.json' if business_ip else 'latest_check.json')
        if latest_path.is_symlink():
            try:
                target = latest_path.resolve(strict=True)
                if target.is_relative_to(folder.resolve()) and target.is_file():
                    row = read_json_readonly(target)
                    if (row.get('vendor'), row.get('library')) == (vendor, library) and row.get('business_ip') == business_ip:
                        latest_check = {'revision': row['revision'], 'run_at': row['run_at'], 'name': target.name}
            except (OSError, ValueError, KeyError):
                pass
        matched_check = None
        if index and revision:
            if baseline == '__prev_file__':
                matched_check = latest_check_for_scope(work, vendor, library, revision, '__prev_file__', business_ip=business_ip)
            elif baseline == '__none__':
                matched_check = latest_check_for_scope(work, vendor, library, revision, None, business_ip=business_ip)
            elif baseline:
                matched_check = latest_check_for_scope(work, vendor, library, revision, baseline_rev, business_ip=business_ip)
            else:
                matched_check = (
                    latest_check_for_scope(work, vendor, library, revision, '__prev_file__', business_ip=business_ip)
                    or latest_check_for_scope(work, vendor, library, revision, baseline_rev, business_ip=business_ip)
                )
        if matched_check:
            fmap = matched_check['files']
            for m in members:
                info = fmap.get((m['view'], m['relative_path']))
                if info:
                    m.update(info)
        try:
            acceptance = acceptance_status(work, vendor, library, limit=10, business_ip=business_ip) if (business_ip or not track_info['is_multi_track']) else None
        except (OSError, ValueError):
            acceptance = None
        unadopted = unadopted_new_files(work, vendor, library, sample_limit=10, business_ip=business_ip) if (business_ip or not track_info['is_multi_track']) else None
        lib_sig = read_cache.signature()
        try:
            lib_json_key = tuple(
                (k, request.args.get(k, ''))
                for k in ('json_layer', 'json_status', 'json_scope', 'json_q', 'json_sort', 'json_page')
            )
            library_json_inventory = read_cache.get_or_compute(
                ('lib_json_inventory', vendor, library, lib_json_key),
                lambda: query_json_inventory(work, vendor=vendor, library=library, filters=request.args),
                sig=lib_sig,
            )
        except (OSError, ValueError, TypeError):
            library_json_inventory = None
        organizer_state = None
        try:
            from ai_lib_qor.application.sequence_organizer import get_organizer_state
            organizer_state = read_cache.get_or_compute(
                ('organizer_state', vendor, library),
                lambda: get_organizer_state(work, vendor, library),
                sig=lib_sig,
            )
        except (OSError, ValueError, TypeError):
            organizer_state = None
        active_check_view = None
        active_check_candidate = matched_check['check_name'] if matched_check else None
        if active_check_candidate:
            try:
                from ai_lib_qor.reporting.qor_views import build_check_view
                active_check_view = build_check_view(work, vendor, library, active_check_candidate)
            except (OSError, ValueError, TypeError):
                active_check_view = None
        active_overall_view = None
        latest_overall_json = next((a['overall_json'] for a in artifacts if a.get('kind') == 'OVERALL' and a.get('overall_json')), None)
        if latest_overall_json:
            try:
                from ai_lib_qor.reporting.qor_views import build_overall_view
                active_overall_view = read_cache.get_or_compute(
                    ('overall_view', vendor, library, latest_overall_json),
                    lambda: build_overall_view(work, vendor, library, latest_overall_json),
                    sig=lib_sig,
                )
            except (OSError, ValueError, TypeError):
                active_overall_view = None
        library_ip_overview = None
        if track_info and track_info.get('is_multi_track') and available_tracks:
            def _compute_ip_overview():
                from ai_lib_qor.application.path_query import PathDataQuery
                rows_out = []
                counts = {'total': 0, 'pass': 0, 'fail': 0, 'partial': 0, 'unchecked': 0, 'no_rev': 0}
                t_res = PathDataQuery(work).list_tracks(vendor=vendor, library=library, include_checks=True)
                by_ip = {t['business_ip']: t for t in (t_res.get('tracks') or []) if t.get('business_ip')}
                for t in available_tracks:
                    ip_name = t['business_ip']
                    info = by_ip.get(ip_name, {})
                    lc = info.get('latest_check')
                    latest_r = t.get('latest_revision') or info.get('latest_revision')
                    rev_cnt = t.get('revision_count') or 0
                    if not latest_r:
                        status_code = 'NO_REV'
                        counts['no_rev'] += 1
                    elif not lc:
                        status_code = 'UNCHECKED'
                        counts['unchecked'] += 1
                    else:
                        qcode = lc.get('quality_code') or 'PARTIAL'
                        status_code = qcode
                        if qcode == 'FAIL':
                            counts['fail'] += 1
                        elif qcode == 'SCOPE_PASS':
                            counts['pass'] += 1
                        else:
                            counts['partial'] += 1
                    counts['total'] += 1
                    rows_out.append({
                        'business_ip': ip_name,
                        'version_count': t.get('version_count') or 0,
                        'revision_count': rev_cnt,
                        'latest_revision': latest_r,
                        'accepted_revision': t.get('accepted_revision') or info.get('accepted_revision'),
                        'latest_check': lc,
                        'status_code': status_code,
                    })
                return {'rows': rows_out, 'counts': counts}
            try:
                library_ip_overview = read_cache.get_or_compute(
                    ('lib_ip_overview', vendor, library),
                    _compute_ip_overview,
                    sig=lib_sig,
                )
            except (OSError, ValueError, TypeError):
                library_ip_overview = None
        from ai_lib_qor.reporting.timeline_excel import build_timeline_model, timeline_excel_filename
        timeline_excel_name = timeline_excel_filename(business_ip) if (index and index.get('revisions')) else None
        timeline_excel_exists = bool(
            timeline_excel_name
            and (folder / 'log' / timeline_excel_name).is_file()
            and not (folder / 'log' / timeline_excel_name).is_symlink()
        )
        timeline_model = None
        if index and index.get('revisions') and (business_ip or not track_info['is_multi_track']):
            try:
                timeline_model = read_cache.get_or_compute(
                    ('timeline_model', vendor, library, business_ip),
                    lambda: build_timeline_model(work, vendor, library, business_ip=business_ip),
                    sig=lib_sig,
                )
            except (OSError, ValueError, TypeError):
                timeline_model = None
        return render_template(
            'path_library.html',
            vendor=vendor,
            library=library,
            business_ip=business_ip,
            track_info=track_info,
            available_tracks=available_tracks,
            index=index,
            error=error,
            revision=revision,
            rev_meta=rev_meta,
            members=members,
            organizer_state=organizer_state,
            active_check_view=active_check_view,
            active_overall_view=active_overall_view,
            timeline_model=timeline_model,
            timeline_excel_name=timeline_excel_name,
            timeline_excel_exists=timeline_excel_exists,
            check_baseline_param=check_baseline_param,
            library_ip_overview=library_ip_overview,
            removed=removed,
            diff_counts=diff_counts,
            delivery_rows=delivery_rows,
            artifacts=artifacts,
            audit_available=audit_available,
            audit_filename=audit_filename,
            member_views=member_views,
            liberty_preview=liberty_preview,
            prev_rev=prev_rev,
            next_rev=next_rev,
            baseline_rev=baseline_rev,
            rev_idx=rev_idx,
            latest_check=latest_check,
            matched_check=matched_check,
            acceptance=acceptance,
            unadopted_new_files=unadopted,
            library_json_inventory=library_json_inventory,
        )

    @app.get('/path/index')
    def index_page():
        vendor, library, folder = scope()
        raw_index, error = index_state(vendor, library, folder)
        index, business_ip, track_info, available_tracks = _resolve_library_track(work, vendor, library, folder, raw_index)
        try:
            page = max(1, int(request.args.get('page', '1')))
        except ValueError:
            abort(400)
        try:
            idx_view = query_file_index(
                work,
                vendor,
                library,
                business_ip=business_ip,
                q=request.args.get('q', ''),
                view=request.args.get('view', ''),
                delivery=request.args.get('delivery', ''),
                nl_version=request.args.get('nl_version', ''),
                adoption=request.args.get('adoption', ''),
                nl_rel=request.args.get('nl_rel', ''),
                revision=request.args.get('revision', ''),
                page=page,
                index=index if index is not None else {'views': {}, 'nl_snapshots': [], 'deliveries': [], 'revisions': []},
            )
        except ValueError:
            abort(400)
        return render_template(
            'path_index.html',
            vendor=vendor,
            library=library,
            business_ip=business_ip,
            track_info=track_info,
            available_tracks=available_tracks,
            index=index,
            error=error,
            rows=idx_view['rows'],
            views=idx_view['views'],
            view=idx_view['view'],
            q=idx_view['q'],
            delivery=idx_view['delivery'],
            nl_version=idx_view['nl_version'],
            nl_versions=idx_view['nl_versions'],
            adoption=idx_view['adoption'],
            nl_rel=idx_view['nl_rel'],
            page=idx_view['page'],
            pages=idx_view['pages'],
            total=idx_view['total'],
            revision=idx_view['revision'],
        )

    @app.get('/path/check/view')
    def check_view_page():
        from ai_lib_qor.reporting.qor_views import build_check_view
        vendor, library, _ = scope()
        name = request.args.get('name', '')
        try:
            view_data = build_check_view(work, vendor, library, name)
        except ValueError:
            abort(404)
        return render_template(
            'path_analysis.html',
            mode='check',
            vendor=vendor,
            library=library,
            business_ip=view_data.get('business_ip'),
            revision=view_data['report'].get('revision'),
            data=view_data,
        )

    @app.get('/path/check/export.html')
    def check_export_html():
        from ai_lib_qor.reporting.html_report import render_check_html_report
        from ai_lib_qor.reporting.qor_views import build_check_view
        vendor, library, _ = scope()
        name = request.args.get('name', '')
        try:
            view_data = build_check_view(work, vendor, library, name)
            html_str = render_check_html_report(view_data)
        except ValueError:
            abort(404)
        dl_name = Path(view_data['check_name']).with_suffix('.html').name
        return send_file(
            BytesIO(html_str.encode('utf-8')),
            mimetype='text/html; charset=utf-8',
            as_attachment=True,
            download_name=dl_name,
        )

    @app.get('/path/overall/view')
    def overall_view_page():
        from ai_lib_qor.reporting.qor_views import build_overall_view
        vendor, library, _ = scope()
        name = request.args.get('name', '')
        try:
            ov_data = build_overall_view(work, vendor, library, name)
        except ValueError:
            abort(404)
        return render_template(
            'path_analysis.html',
            mode='overall',
            vendor=vendor,
            library=library,
            business_ip=ov_data.get('business_ip'),
            data=ov_data,
        )

    @app.get('/path/overall/export.html')
    def overall_export_html():
        from ai_lib_qor.reporting.html_report import render_overall_html_report
        from ai_lib_qor.reporting.qor_views import build_overall_view
        vendor, library, _ = scope()
        name = request.args.get('name', '')
        try:
            ov_data = build_overall_view(work, vendor, library, name)
            html_str = render_overall_html_report(ov_data)
        except ValueError:
            abort(404)
        dl_name = Path(ov_data['overall_name']).with_suffix('.html').name
        return send_file(
            BytesIO(html_str.encode('utf-8')),
            mimetype='text/html; charset=utf-8',
            as_attachment=True,
            download_name=dl_name,
        )

    @app.get('/path/facts/view')
    def facts_view_page():
        from ai_lib_qor.reporting.qor_views import build_facts_view, load_fact_object, paginate_facts_view
        vendor, library, _ = scope()
        name = request.args.get('name', '') or None
        check_name = request.args.get('check', '') or None
        ref = request.args.get('ref', '') or None
        try:
            bundle = load_check_bundle(work, vendor, library, check_name) if check_name and ref else None
            fact, label, _ = load_fact_object(work, vendor, library, name=name, check=check_name, ref=ref, bundle=bundle)
            entity_page = int(request.args.get('entity_page', '1'))
            pin_page = int(request.args.get('pin_page', '1'))
            per_page = int(request.args.get('per_page', '100'))
        except ValueError:
            abort(404)
        raw_view = build_facts_view(fact, label=label)
        view_data = paginate_facts_view(
            raw_view,
            q=request.args.get('q', ''),
            direction=request.args.get('direction', ''),
            use=request.args.get('use', ''),
            entity_page=entity_page,
            pin_page=pin_page,
            per_page=per_page,
        )
        report = bundle['report'] if bundle else {}
        return render_template(
            'path_analysis.html', mode='facts', vendor=vendor, library=library, data=view_data,
            check_name=check_name, fact_ref=ref, fact_name=name, origin_report=report,
            business_ip=report.get('business_ip'), revision=report.get('revision'),
        )

    @app.get('/path/facts/compare')
    def facts_compare_page():
        from ai_lib_qor.reporting.qor_views import build_facts_diff, load_fact_object, paginate_facts_diff
        vendor, library, _ = scope()
        check_name = request.args.get('check', '') or None
        old_ref = request.args.get('old', '') or None
        new_ref = request.args.get('new', '') or None
        if not old_ref or not new_ref:
            abort(400)
        try:
            bundle = load_check_bundle(work, vendor, library, check_name) if check_name else None
            old_fact, old_label, _ = load_fact_object(work, vendor, library, name=old_ref, check=check_name, ref=old_ref, bundle=bundle)
            new_fact, new_label, _ = load_fact_object(work, vendor, library, name=new_ref, check=check_name, ref=new_ref, bundle=bundle)
            raw_diff = build_facts_diff(old_fact, new_fact, old_label=old_label, new_label=new_label)
            pin_page = int(request.args.get('pin_page', '1'))
            per_page = int(request.args.get('per_page', '100'))
        except ValueError:
            abort(404)
        diff = paginate_facts_diff(
            raw_diff,
            q=request.args.get('q', ''),
            status=request.args.get('status', 'auto'),
            pin_page=pin_page,
            per_page=per_page,
        )
        report = bundle['report'] if bundle else {}
        return render_template(
            'path_analysis.html', mode='compare', vendor=vendor, library=library, data=diff,
            check_name=check_name, old_ref=old_ref, new_ref=new_ref, origin_report=report,
            business_ip=report.get('business_ip'), revision=report.get('revision'),
        )

    @app.get('/path/facts/download')
    def facts_download():
        from ai_lib_qor.reporting.qor_views import load_fact_object
        vendor, library, _ = scope()
        name = request.args.get('name', '') or None
        check_name = request.args.get('check', '') or None
        ref = request.args.get('ref', '') or None
        try:
            fact, label, _ = load_fact_object(work, vendor, library, name=name, check=check_name, ref=ref)
        except ValueError:
            abort(404)
        filename = label if label.endswith('.json') else label + '.json'
        payload = json.dumps(fact, ensure_ascii=False, indent=2).encode('utf-8')
        return send_file(BytesIO(payload), mimetype='application/json', as_attachment=True, download_name=filename)

    @app.get('/path/artifact')
    def artifact():
        vendor, library, folder = scope()
        name = request.args.get('name', '')
        _ip_seg = r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}'
        _run_tag = r'(?:run_[a-f0-9]{32}|[0-9]{8}(?:_[0-9]+)?)'
        if not re.fullmatch(
            rf'(?:report_run_[a-f0-9]{{32}}\.xlsx|timeline(?:__{_ip_seg})?\.xlsx|overall(?:__{_ip_seg}__|_{_ip_seg}_|_){_run_tag}\.(?:xlsx|json)|check_run_[a-f0-9]{{32}}\.json|check(?:__{_ip_seg}__|_{_ip_seg}_|_)rev_[0-9]+_{_run_tag}\.(?:xlsx|json)|facts_[A-Z]+_[A-Za-z0-9_]+\.json|file_index\.json|effective_operations(?:__{_ip_seg})?\.tsv|file_index_reconciliation\.tsv|formal_observations\.tsv)',
            name,
        ):
            abort(400)
        if (folder / 'log').is_symlink():
            abort(400)
        path = folder / 'log' / name if (folder / 'log' / name).is_file() else folder / name
        if name.startswith('timeline') and name.endswith('.xlsx') and not path.is_symlink():
            from ai_lib_qor.reporting.check_renderer import render_timeline_excel_for_scope
            m_tl = re.fullmatch(rf'timeline(?:__({_ip_seg}))?\.xlsx', name)
            tl_ip = m_tl.group(1) if m_tl else None
            target_xlsx = folder / 'log' / name
            try:
                if not report_cache_is_current(folder, target_xlsx, tl_ip, include_latest=True):
                    render_timeline_excel_for_scope(work, vendor, library, business_ip=tl_ip, excel_path=target_xlsx)
            except (OSError, ValueError, KeyError, TypeError):
                abort(404)
            path = target_xlsx
        elif name.endswith('.xlsx') and not path.is_symlink():
            from ai_lib_qor.reporting.check_renderer import render_excel_from_check, render_overall_excel_from_saved
            legacy = name.startswith('report_run_')
            stem = Path(name).stem
            json_name = ('check_' + stem.removeprefix('report_') if legacy else stem) + '.json'
            json_path = next((p for p in (folder / 'log' / json_name, folder / json_name)
                              if p.is_file() and not p.is_symlink()), None)
            if json_path is not None:
                overall = name.startswith('overall_')
                target_xlsx = path if path.is_file() or legacy else json_path.with_suffix('.xlsx')
                try:
                    report = json.loads(json_path.read_text(encoding='utf-8'))
                    if (report.get('vendor'), report.get('library')) != (vendor, library):
                        abort(404)
                    if not report_cache_is_current(folder, target_xlsx, report.get('business_ip'), include_latest=overall):
                        renderer = render_overall_excel_from_saved if overall else render_excel_from_check
                        renderer(work, vendor, library, json_path.name, target_xlsx)
                except (OSError, ValueError, KeyError, TypeError):
                    abort(404)
                path = target_xlsx
        if not path.is_file() and name == 'formal_observations.tsv' and (work / name).is_file():
            path = work / name
        if path.is_symlink() or not path.is_file():
            abort(404)
        return send_file(path, as_attachment=True, download_name=name)
