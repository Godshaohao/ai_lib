"""Stateless JSON API (/api/v1/*) and async background job endpoints (/api/v1/jobs/*)."""
from io import BytesIO
from pathlib import Path
from urllib.parse import urlencode

from flask import abort, jsonify, request, send_file, url_for

from ai_lib_qor.sources.layout import library_folder
from .jobs import JobConflictError
from .refresh_forms import refresh_form, run_refresh_form


def register_api_routes(app, ctx):
    work = ctx['work']
    jobs = ctx['jobs']
    read_cache = ctx['read_cache']
    scope = ctx['scope']
    source_config = ctx['source_config']

    @app.get('/api/v1/overview')
    def api_overview():
        from ai_lib_qor.application.path_refresh import refresh_status
        from ai_lib_qor.application.path_storage import storage_stats
        return jsonify(read_cache.get_or_compute(
            'api_overview',
            lambda: {'refresh': refresh_status(work, limit=10), 'storage': storage_stats(work)},
        ))

    @app.get('/api/v1/activity')
    def api_activity():
        from ai_lib_qor.application.path_query import workspace_activity_and_readiness
        from ai_lib_qor.application.path_refresh import refresh_status
        raw_days = (request.args.get('days') or '7').strip().lower()
        if raw_days == 'all':
            days = None
        else:
            try:
                days = int(raw_days)
            except ValueError:
                return jsonify({'error': 'days 必须是正整数或 all'}), 400
        try:
            import time
            time_bucket = int(time.time() // 300)
            return jsonify(read_cache.get_or_compute(
                ('api_activity', days, time_bucket),
                lambda: workspace_activity_and_readiness(work, days=days, refresh_info=refresh_status(work, limit=5)),
            ))
        except ValueError as exc:
            return jsonify({'error': str(exc)}), 400

    @app.get('/api/v1/storage')
    def api_storage():
        from ai_lib_qor.application.path_storage import storage_stats
        v = request.args.get('vendor') or None
        lib = request.args.get('library') or None
        try:
            return jsonify(read_cache.get_or_compute(
                ('api_storage', v, lib),
                lambda: storage_stats(work, vendor=v, library=lib),
            ))
        except ValueError as exc:
            return jsonify({'error': str(exc)}), 400

    @app.get('/api/v1/tracks')
    def api_tracks():
        from ai_lib_qor.application.path_query import PathDataQuery
        v = request.args.get('vendor') or None
        lib = request.args.get('library') or None
        ip_type = request.args.get('ip_type') or None
        business_ip = (request.args.get('ip') or request.args.get('business_ip') or '').strip() or None
        try:
            return jsonify(PathDataQuery(work).list_tracks(vendor=v, library=lib, ip_type=ip_type, business_ip=business_ip))
        except ValueError as exc:
            return jsonify({'error': str(exc)}), 400

    @app.get('/api/v1/library')
    def api_library():
        from ai_lib_qor.application.ip_partition import active_tracks_for_library
        from ai_lib_qor.application.path_acceptance import acceptance_status
        from ai_lib_qor.application.path_query import PathDataQuery, build_track_index_view, unadopted_new_files
        vendor, library, folder = scope()
        revision = request.args.get('revision') or None
        baseline = request.args.get('baseline') or None
        business_ip = (request.args.get('ip') or request.args.get('business_ip') or '').strip() or None
        try:
            query = PathDataQuery(work)
            track_info = active_tracks_for_library(work, vendor, library)
            index = query.index(vendor, library)
            if business_ip:
                index, _, _ = build_track_index_view(folder, vendor, library, index, business_ip)
            rev = revision or (index['revisions'][-1] if index['revisions'] else None)
            ctx_data = query.get_check_context(vendor, library, rev, baseline=baseline, business_ip=business_ip) if rev else None
            acc = acceptance_status(work, vendor, library, limit=10, business_ip=business_ip) if (business_ip or not track_info['is_multi_track']) else None
            unadopted = unadopted_new_files(work, vendor, library, sample_limit=20, business_ip=business_ip) if (business_ip or not track_info['is_multi_track']) else None
            payload = {
                'vendor': vendor,
                'library': library,
                'ip_type': track_info['ip_type'],
                'is_multi_track': track_info['is_multi_track'],
                'revisions': index['revisions'],
                'deliveries': index['deliveries'],
                'acceptance': acc,
                'unadopted_new_files': unadopted,
                'context': {k: v for k, v in ctx_data.items() if k != 'index'} if ctx_data else None,
            }
            if business_ip:
                payload['business_ip'] = business_ip
            if track_info['is_multi_track']:
                payload['tracks'] = track_info['tracks']
                payload['needs_review'] = track_info['needs_review']
            return jsonify(payload)
        except ValueError as exc:
            return jsonify({'error': str(exc)}), 400

    @app.get('/api/v1/check')
    def api_check():
        from ai_lib_qor.reporting.qor_views import build_check_view
        vendor, library, _ = scope()
        name = request.args.get('name', '')
        try:
            return jsonify(build_check_view(work, vendor, library, name))
        except ValueError as exc:
            return jsonify({'error': str(exc)}), 404

    @app.get('/api/v1/facts')
    def api_facts():
        from ai_lib_qor.reporting.qor_views import build_facts_view, load_fact_object, paginate_facts_view
        vendor, library, _ = scope()
        name = request.args.get('name', '') or None
        check_name = request.args.get('check', '') or None
        ref = request.args.get('ref', '') or None
        try:
            fact, label, _ = load_fact_object(work, vendor, library, name=name, check=check_name, ref=ref)
            raw_view = build_facts_view(fact, label=label)
            paged = paginate_facts_view(
                raw_view,
                q=request.args.get('q', ''),
                direction=request.args.get('direction', ''),
                use=request.args.get('use', ''),
                entity_page=int(request.args.get('entity_page', '1')),
                pin_page=int(request.args.get('pin_page', '1')),
                per_page=int(request.args.get('per_page', '100')),
            )
            return jsonify(paged)
        except ValueError as exc:
            return jsonify({'error': str(exc)}), 404

    @app.get('/api/v1/inventory')
    def api_inventory():
        from ai_lib_qor.application.path_query import query_json_inventory
        v = (request.args.get('vendor') or '').strip() or None
        lib = (request.args.get('library') or '').strip() or None
        raw_ps = (request.args.get('page_size') or '').strip()
        try:
            page_size = int(raw_ps) if raw_ps else None
            return jsonify(query_json_inventory(work, vendor=v, library=lib, filters=request.args, page_size=page_size))
        except ValueError as exc:
            return jsonify({'error': str(exc)}), 400

    @app.get('/api/v1/index')
    def api_index():
        from ai_lib_qor.application.path_query import query_file_index
        vendor, library, _ = scope()
        business_ip = (request.args.get('ip') or request.args.get('business_ip') or '').strip() or None
        raw_page = (request.args.get('page') or '1').strip()
        raw_ps = (request.args.get('page_size') or '').strip()
        try:
            page = int(raw_page)
            page_size = int(raw_ps) if raw_ps else None
            return jsonify(query_file_index(
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
                page_size=page_size,
            ))
        except ValueError as exc:
            return jsonify({'error': str(exc)}), 400

    @app.get('/api/v1/overall')
    def api_overall():
        from ai_lib_qor.application.minimal_checks import _find_latest_overall_json
        from ai_lib_qor.application.minimal_effective import _norm_business_ip
        from ai_lib_qor.reporting.qor_views import build_overall_view
        vendor, library, folder = scope()
        name = (request.args.get('name') or '').strip()
        business_ip_raw = (request.args.get('ip') or request.args.get('business_ip') or '').strip() or None
        try:
            ip = _norm_business_ip(business_ip_raw)
            if not name:
                latest_ov = _find_latest_overall_json(folder / 'log', ip)
                if latest_ov is None:
                    return jsonify({'error': '未找到已保存的整体检查报告'}), 404
                name = latest_ov.name
            return jsonify(build_overall_view(work, vendor, library, name))
        except ValueError as exc:
            return jsonify({'error': str(exc)}), 404

    @app.get('/api/v1/config')
    def api_config_get():
        from ai_lib_qor.application.path_config import get_library_config_view, get_workspace_config_view
        v = (request.args.get('vendor') or '').strip() or None
        lib = (request.args.get('library') or '').strip() or None
        if bool(v) != bool(lib):
            return jsonify({'error': 'vendor 和 library 必须同时指定或同时省略'}), 400
        try:
            if v and lib:
                folder = library_folder(work, v, lib)
                if not folder.is_dir():
                    return jsonify({'error': f'库目录不存在: {v}/{lib}'}), 404
                return jsonify(get_library_config_view(work, v, lib))
            return jsonify(get_workspace_config_view(work))
        except (OSError, ValueError, TypeError) as exc:
            return jsonify({'error': str(exc)}), 400

    @app.post('/api/v1/config')
    def api_config_update():
        from ai_lib_qor.application.path_config import update_library_config, update_workspace_config
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify({'error': '请求体必须为 JSON 对象'}), 400
        v = str(payload.get('vendor') or '').strip() or None
        lib = str(payload.get('library') or '').strip() or None
        if bool(v) != bool(lib):
            return jsonify({'error': 'vendor 和 library 必须同时指定或同时省略'}), 400
        if 'updates' in payload and isinstance(payload['updates'], dict):
            updates = payload['updates']
        else:
            updates = {k: val for k, val in payload.items() if k not in ('vendor', 'library')}
        try:
            if v and lib:
                folder = library_folder(work, v, lib)
                if not folder.is_dir():
                    return jsonify({'error': f'库目录不存在: {v}/{lib}'}), 404
                return jsonify(update_library_config(work, v, lib, updates))
            return jsonify(update_workspace_config(work, updates))
        except (OSError, ValueError, TypeError) as exc:
            return jsonify({'error': str(exc)}), 400

    @app.get('/api/v1/acceptance')
    def api_acceptance_get():
        from ai_lib_qor.application.path_acceptance import acceptance_status
        vendor, library, _ = scope()
        business_ip = (request.args.get('ip') or request.args.get('business_ip') or '').strip() or None
        raw_limit = (request.args.get('limit') or '20').strip()
        try:
            limit = max(1, min(200, int(raw_limit)))
            return jsonify(acceptance_status(work, vendor, library, limit=limit, business_ip=business_ip))
        except ValueError as exc:
            return jsonify({'error': str(exc)}), 400

    @app.post('/api/v1/acceptance')
    def api_acceptance_post():
        from ai_lib_qor.application.path_acceptance import accept_revision, rollback_acceptance
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify({'error': '请求体必须为 JSON 对象'}), 400
        vendor = str(payload.get('vendor') or '').strip()
        library = str(payload.get('library') or '').strip()
        try:
            folder = library_folder(work, vendor, library)
        except ValueError as exc:
            return jsonify({'error': str(exc)}), 400
        if not folder.is_dir():
            return jsonify({'error': f'库目录不存在: {vendor}/{library}'}), 404
        action = str(payload.get('action') or 'accept').strip().lower()
        revision = str(payload.get('revision') or '').strip()
        reason = str(payload.get('reason') or '')
        actor = str(payload.get('actor') or 'api').strip() or 'api'
        business_ip = str(payload.get('business_ip') or payload.get('ip') or '').strip() or None
        try:
            if action == 'rollback':
                res = rollback_acceptance(work, vendor, library, revision, actor=actor, reason=reason, business_ip=business_ip)
            elif action == 'accept':
                res = accept_revision(work, vendor, library, revision, actor=actor, reason=reason, business_ip=business_ip)
            else:
                return jsonify({'error': 'action 必须为 accept 或 rollback'}), 400
            return jsonify(res)
        except (OSError, ValueError, TypeError) as exc:
            return jsonify({'error': str(exc)}), 400

    @app.post('/api/v1/effective/preview')
    def api_effective_preview():
        from ai_lib_qor.application.minimal_effective import _history, preview_update, restore_issues
        from ai_lib_qor.application.path_config import library_ip_config
        from ai_lib_qor.application.path_query import PathDataQuery, build_track_index_view
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify({'error': '请求体必须为 JSON 对象'}), 400
        vendor = str(payload.get('vendor') or '').strip()
        library = str(payload.get('library') or '').strip()
        try:
            folder = library_folder(work, vendor, library)
        except ValueError as exc:
            return jsonify({'error': str(exc)}), 400
        if not folder.is_dir():
            return jsonify({'error': f'库目录不存在: {vendor}/{library}'}), 404
        action = str(payload.get('action') or 'update').strip().lower()
        business_ip = str(payload.get('business_ip') or payload.get('ip') or '').strip() or None
        try:
            ip_cfg = library_ip_config(work, vendor, library)
            if action in ('update', 'set', 'remove', 'batch'):
                if 'operations' in payload and isinstance(payload['operations'], dict):
                    operations = payload['operations']
                elif action == 'set':
                    operations = {'set': [{'view': payload.get('view', ''), 'path': payload.get('path', ''), 'version': payload.get('version', '')}], 'remove': []}
                elif action == 'remove':
                    operations = {'set': [], 'remove': [{'view': payload.get('view', ''), 'path': payload.get('path', '')}]}
                else:
                    raise ValueError('请提供 operations 对象（含 set / remove 列表）')
                preview = preview_update(work, vendor, library, operations, business_ip=business_ip)
                return jsonify({
                    'vendor': vendor,
                    'library': library,
                    'business_ip': business_ip,
                    'ip_type': ip_cfg.get('ip_type'),
                    'action': action,
                    'parent': preview['parent'],
                    'operations': operations,
                    'changes': preview['changes'],
                    'issues': [],
                })
            if action == 'restore':
                revision = str(payload.get('revision') or '').strip()
                query = PathDataQuery(work)
                index = query.index(vendor, library)
                if business_ip:
                    index, _, _ = build_track_index_view(folder, vendor, library, index, business_ip)
                if not index['revisions'] or revision not in index['revisions']:
                    raise ValueError('有效版本不存在')
                parent = index['revisions'][-1]
                before = query.get_check_context(vendor, library, parent, business_ip=business_ip)['members']
                after = query.get_check_context(vendor, library, revision, business_ip=business_ip)['members']
                a = {(x['view'], x['path']): x for x in before}
                b = {(x['view'], x['path']): x for x in after}
                changes = [
                    {'view': v, 'path': p, 'before': a.get((v, p), {}).get('version'), 'after': b.get((v, p), {}).get('version')}
                    for v, p in sorted(a.keys() | b.keys())
                    if a.get((v, p), {}).get('version') != b.get((v, p), {}).get('version')
                ]
                target = next(row for _, _, row in _history(folder, library, business_ip=business_ip) if row['revision'] == revision)
                issues = restore_issues(work, vendor, library, target['views'])
                return jsonify({
                    'vendor': vendor,
                    'library': library,
                    'business_ip': business_ip,
                    'ip_type': ip_cfg.get('ip_type'),
                    'action': 'restore',
                    'revision': revision,
                    'parent': parent,
                    'changes': changes,
                    'issues': issues,
                })
            raise ValueError('action 必须为 update / set / remove / batch / restore')
        except (OSError, ValueError, KeyError, TypeError) as exc:
            return jsonify({'error': str(exc)}), 400

    @app.post('/api/v1/effective/apply')
    def api_effective_apply():
        from ai_lib_qor.application.minimal_effective import apply_update, restore_revision
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify({'error': '请求体必须为 JSON 对象'}), 400
        vendor = str(payload.get('vendor') or '').strip()
        library = str(payload.get('library') or '').strip()
        try:
            folder = library_folder(work, vendor, library)
        except ValueError as exc:
            return jsonify({'error': str(exc)}), 400
        if not folder.is_dir():
            return jsonify({'error': f'库目录不存在: {vendor}/{library}'}), 404
        action = str(payload.get('action') or 'update').strip().lower()
        business_ip = str(payload.get('business_ip') or payload.get('ip') or '').strip() or None
        expected_parent = payload.get('expected_parent')
        actor = str(payload.get('actor') or 'api').strip() or 'api'
        try:
            if action == 'restore':
                revision = str(payload.get('revision') or '').strip()
                res = restore_revision(
                    work,
                    vendor,
                    library,
                    revision,
                    expected_parent=expected_parent,
                    actor=actor,
                    expected_issues=payload.get('expected_issues'),
                    business_ip=business_ip,
                )
            elif action in ('update', 'set', 'remove', 'batch'):
                operations = payload.get('operations')
                if not isinstance(operations, dict):
                    raise ValueError('请提供 operations 对象')
                res = apply_update(
                    work,
                    vendor,
                    library,
                    operations,
                    expected_parent=expected_parent,
                    actor=actor,
                    business_ip=business_ip,
                )
            else:
                raise ValueError('action 必须为 update / set / remove / batch / restore')
            return jsonify(res)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            return jsonify({'error': str(exc)}), 400

    @app.post('/api/v1/unadopted/ignore')
    def api_unadopted_ignore():
        from ai_lib_qor.application.path_config import set_unadopted_ignored
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify({'error': '请求体必须为 JSON 对象'}), 400
        vendor = str(payload.get('vendor') or '').strip()
        library = str(payload.get('library') or '').strip()
        try:
            folder = library_folder(work, vendor, library)
        except ValueError as exc:
            return jsonify({'error': str(exc)}), 400
        if not folder.is_dir():
            return jsonify({'error': f'库目录不存在: {vendor}/{library}'}), 404
        try:
            res = set_unadopted_ignored(
                work,
                vendor,
                library,
                str(payload.get('view') or ''),
                str(payload.get('path') or ''),
                ignored=bool(payload.get('ignored', True)),
            )
            return jsonify(res)
        except (OSError, ValueError, TypeError) as exc:
            return jsonify({'error': str(exc)}), 400

    @app.post('/api/v1/partition')
    def api_partition():
        from ai_lib_qor.application.ip_partition import partition_library_ips
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify({'error': '请求体必须为 JSON 对象'}), 400
        vendor = str(payload.get('vendor') or '').strip()
        library = str(payload.get('library') or '').strip()
        try:
            folder = library_folder(work, vendor, library)
        except ValueError as exc:
            return jsonify({'error': str(exc)}), 400
        if not folder.is_dir():
            return jsonify({'error': f'库目录不存在: {vendor}/{library}'}), 404
        try:
            res = partition_library_ips(work, vendor, library, dry_run=bool(payload.get('dry_run', False)))
            return jsonify(res)
        except (OSError, ValueError, TypeError) as exc:
            return jsonify({'error': str(exc)}), 400

    @app.get('/api/v1/scripts/templates')
    def api_script_templates():
        from ai_lib_qor.reporting.eda_scripts import list_script_templates
        return jsonify({'templates': list_script_templates(work)})

    @app.get('/api/v1/scripts/export')
    def api_script_export():
        from ai_lib_qor.reporting.eda_scripts import render_eda_script
        vendor, library, _ = scope()
        revision = (request.args.get('revision') or '').strip() or None
        business_ip = (request.args.get('ip') or request.args.get('business_ip') or '').strip() or None
        template = (request.args.get('template') or 'pt_check').strip()
        output_dir = (request.args.get('output_dir') or '').strip() or None
        download = (request.args.get('download') or '').strip().lower() in ('1', 'true', 'yes')
        try:
            rendered = render_eda_script(
                work,
                vendor,
                library,
                revision,
                template=template,
                business_ip=business_ip,
                output_dir=output_dir,
            )
        except (OSError, ValueError, TypeError) as exc:
            return jsonify({'error': str(exc)}), 400
        if download:
            return send_file(
                BytesIO(rendered['content'].encode('utf-8')),
                mimetype='text/plain; charset=utf-8',
                as_attachment=True,
                download_name=rendered['filename'],
            )
        return jsonify(rendered)

    @app.post('/api/v1/jobs/refresh')
    def api_job_refresh():
        layer = (request.form.get('layer') or 'all').lower()
        vendor = request.form.get('vendor') or None
        library = request.form.get('library') or None
        if bool(vendor) != bool(library):
            return jsonify({'error': 'vendor 和 library 必须同时指定'}), 400
        if vendor:
            try:
                library_folder(work, vendor, library)
            except ValueError as exc:
                return jsonify({'error': str(exc)}), 400
        if layer not in ('l1', 'l2', 'l3', 'all'):
            return jsonify({'error': '无效的刷新层级'}), 400
        form = request.form.to_dict()
        try:
            options = refresh_form(form, source_config())
        except (OSError, ValueError, TypeError) as exc:
            return jsonify({'error': str(exc)}), 400

        def fn(cb, ev):
            return run_refresh_form(
                work, layer, form, options, vendor=vendor, library=library, actor='web-async',
                progress_cb=cb, cancel_event=ev,
            )

        scope_key = f'refresh:{vendor}/{library}' if vendor else 'refresh:__all__'
        try:
            job = jobs.submit('refresh', f'刷新 {layer.upper()}' + (f' ({vendor}/{library})' if vendor else ''), fn, scope_key=scope_key)
        except JobConflictError as exc:
            return jsonify({'error': str(exc), 'active_job': exc.active_job}), 409
        return jsonify(job), 202

    @app.post('/api/v1/jobs/check')
    def api_job_check():
        from ai_lib_qor.application.minimal_checks import run_library, run_revision
        from ai_lib_qor.application.path_batch import check_pending
        from ai_lib_qor.reporting.check_renderer import (
            render_excel_from_check,
            render_overall_excel_rows,
            render_timeline_excel_for_scope,
        )
        kind = request.form.get('kind', 'single')
        lazy_excel = request.form.get('lazy_excel', '1') == '1'
        update_timeline = request.form.get('update_timeline', '1') != '0'
        business_ip = (request.form.get('ip') or request.form.get('business_ip') or '').strip() or None
        ip_type = (request.form.get('ip_type') or '').strip() or None
        if kind == 'pending':
            v = request.form.get('vendor') or None
            lib = request.form.get('library') or None
            if bool(v) != bool(lib):
                return jsonify({'error': 'vendor 和 library 必须同时指定'}), 400
            rerun_flag = request.form.get('rerun') == '1'
            include_outdated = request.form.get('include_outdated') == '1'
            fn = lambda cb, ev: check_pending(
                work,
                vendor=v,
                library=lib,
                business_ip=business_ip,
                ip_type=ip_type,
                render_excel=not lazy_excel,
                single_renderer=render_excel_from_check,
                rerun=rerun_flag,
                include_outdated=include_outdated,
                progress_cb=cb,
                cancel_event=ev,
            )
            scope_key = f'check:{v}/{lib}' + (f'::{business_ip}' if business_ip else '') if v else 'check:__pending__'
            try:
                job = jobs.submit('check_pending', '增量检查待检库', fn, scope_key=scope_key)
            except JobConflictError as exc:
                return jsonify({'error': str(exc), 'active_job': exc.active_job}), 409
            return jsonify(job), 202
        vendor, library, _ = scope()
        revision = request.form.get('revision', '')
        baseline = request.form.get('baseline') or None
        track_tag = f'::{business_ip}' if business_ip else ''
        if kind == 'all':
            rerun = request.form.get('rerun') == '1'
            report_page = url_for('overall_view_page', vendor=vendor, library=library)
            def _run_lib_job(cb, ev):
                res = run_library(
                    work, vendor, library,
                    business_ip=business_ip,
                    rerun=rerun,
                    render_single_excel=not lazy_excel,
                    single_renderer=render_excel_from_check,
                    overall_renderer=render_overall_excel_rows,
                    progress_cb=cb,
                    cancel_event=ev,
                )
                if update_timeline:
                    try:
                        res['timeline_excel'] = render_timeline_excel_for_scope(work, vendor, library, business_ip=business_ip)
                    except (OSError, ValueError, KeyError, TypeError):
                        pass
                res['report_url'] = report_page + '&' + urlencode({'name': Path(res['overall']).name})
                return res
            try:
                job = jobs.submit('check_library', f'库级检查 {vendor}/{library}{track_tag}', _run_lib_job, scope_key=f'check:{vendor}/{library}{track_tag}')
            except JobConflictError as exc:
                return jsonify({'error': str(exc), 'active_job': exc.active_job}), 409
            return jsonify(job), 202

        report_page = url_for('check_view_page', vendor=vendor, library=library)

        def _run_rev_job(cb, ev):
            res = run_revision(
                work, vendor, library, revision,
                baseline=baseline,
                business_ip=business_ip,
                render=not lazy_excel,
                single_renderer=render_excel_from_check,
                progress_cb=cb,
                cancel_event=ev,
            )
            if update_timeline:
                try:
                    res['timeline_excel'] = render_timeline_excel_for_scope(work, vendor, library, business_ip=business_ip)
                except (OSError, ValueError, KeyError, TypeError):
                    pass
            res['report_url'] = report_page + '&' + urlencode({'name': Path(res['check']).name})
            return res

        try:
            job = jobs.submit('check_revision', f'单版本检查 {vendor}/{library}{track_tag} {revision}', _run_rev_job, scope_key=f'check:{vendor}/{library}{track_tag}:{revision}')
        except JobConflictError as exc:
            return jsonify({'error': str(exc), 'active_job': exc.active_job}), 409
        return jsonify(job), 202

    @app.get('/api/v1/jobs')
    def api_jobs_list():
        return jsonify({'jobs': jobs.list_recent(limit=20)})

    @app.get('/api/v1/jobs/<job_id>')
    def api_job_status(job_id):
        job = jobs.get(job_id)
        if not job:
            abort(404)
        return jsonify(job)

    @app.post('/api/v1/jobs/<job_id>/cancel')
    def api_job_cancel(job_id):
        job = jobs.cancel(job_id)
        if not job:
            abort(404)
        return jsonify(job)

    @app.get('/api/v1/organizer')
    def api_organizer_state():
        from ai_lib_qor.application.sequence_organizer import get_organizer_state
        vendor, library, _ = scope()
        inc_files = (request.args.get('include_files') or '1').strip().lower() not in ('0', 'false', 'no')
        try:
            return jsonify(get_organizer_state(work, vendor, library, include_files=inc_files))
        except (OSError, ValueError, TypeError) as exc:
            return jsonify({'error': str(exc)}), 400

    @app.post('/api/v1/organizer/apply')
    def api_organizer_apply():
        from ai_lib_qor.application.sequence_organizer import apply_sequence_plan
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify({'error': '请求体必须为 JSON 对象'}), 400
        vendor = str(payload.get('vendor') or '').strip()
        library = str(payload.get('library') or '').strip()
        try:
            folder = library_folder(work, vendor, library)
        except ValueError as exc:
            return jsonify({'error': str(exc)}), 400
        if not folder.is_dir():
            return jsonify({'error': f'库目录不存在: {vendor}/{library}'}), 404
        try:
            res = apply_sequence_plan(
                work,
                vendor,
                library,
                tracks=payload.get('tracks'),
                order=payload.get('order'),
                excluded=payload.get('excluded') or [],
                rebuild_tracks=payload.get('rebuild_tracks') or [],
                refresh=bool(payload.get('refresh', True)),
                actor='web-organizer',
            )
            return jsonify(res)
        except (OSError, ValueError, TypeError) as exc:
            return jsonify({'error': str(exc)}), 400
