"""Read-only JSON API (/api/v1/*) and async background job endpoints (/api/v1/jobs/*)."""
from flask import abort, jsonify, request

from ai_lib_qor.sources.layout import library_folder
from .jobs import JobConflictError
from .refresh_forms import refresh_form, run_refresh_form


def register_api_routes(app, ctx):
    work = ctx['work']
    jobs = ctx['jobs']
    scope = ctx['scope']
    source_config = ctx['source_config']

    @app.get('/api/v1/overview')
    def api_overview():
        from ai_lib_qor.application.path_refresh import refresh_status
        from ai_lib_qor.application.path_storage import storage_stats
        return jsonify({'refresh': refresh_status(work, limit=10), 'storage': storage_stats(work)})

    @app.get('/api/v1/storage')
    def api_storage():
        from ai_lib_qor.application.path_storage import storage_stats
        v = request.args.get('vendor') or None
        lib = request.args.get('library') or None
        try:
            return jsonify(storage_stats(work, vendor=v, library=lib))
        except ValueError as exc:
            return jsonify({'error': str(exc)}), 400

    @app.get('/api/v1/library')
    def api_library():
        from ai_lib_qor.application.path_acceptance import acceptance_status
        from ai_lib_qor.application.path_query import PathDataQuery, unadopted_new_files
        vendor, library, _ = scope()
        revision = request.args.get('revision') or None
        baseline = request.args.get('baseline') or None
        try:
            query = PathDataQuery(work)
            index = query.index(vendor, library)
            rev = revision or (index['revisions'][-1] if index['revisions'] else None)
            ctx_data = query.get_check_context(vendor, library, rev, baseline=baseline) if rev else None
            acc = acceptance_status(work, vendor, library, limit=10)
            unadopted = unadopted_new_files(work, vendor, library, sample_limit=20)
            return jsonify({
                'vendor': vendor,
                'library': library,
                'revisions': index['revisions'],
                'deliveries': index['deliveries'],
                'acceptance': acc,
                'unadopted_new_files': unadopted,
                'context': {k: v for k, v in ctx_data.items() if k != 'index'} if ctx_data else None,
            })
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
        from ai_lib_qor.reporting.check_renderer import render_excel_from_check, render_overall_excel_rows
        kind = request.form.get('kind', 'single')
        lazy_excel = request.form.get('lazy_excel', '1') == '1'
        if kind == 'pending':
            v = request.form.get('vendor') or None
            lib = request.form.get('library') or None
            if bool(v) != bool(lib):
                return jsonify({'error': 'vendor 和 library 必须同时指定'}), 400
            rerun_flag = request.form.get('rerun') == '1'
            include_outdated = request.form.get('include_outdated') == '1'
            fn = lambda cb, ev: check_pending(work, vendor=v, library=lib, render_excel=not lazy_excel, rerun=rerun_flag, include_outdated=include_outdated, progress_cb=cb, cancel_event=ev)
            scope_key = f'check:{v}/{lib}' if v else 'check:__pending__'
            try:
                job = jobs.submit('check_pending', '增量检查待检库', fn, scope_key=scope_key)
            except JobConflictError as exc:
                return jsonify({'error': str(exc), 'active_job': exc.active_job}), 409
            return jsonify(job), 202
        vendor, library, _ = scope()
        revision = request.form.get('revision', '')
        baseline = request.form.get('baseline') or None
        if kind == 'all':
            rerun = request.form.get('rerun') == '1'
            fn = lambda cb, ev: run_library(work, vendor, library, rerun=rerun, render_single_excel=not lazy_excel, single_renderer=render_excel_from_check, overall_renderer=render_overall_excel_rows, progress_cb=cb, cancel_event=ev)
            try:
                job = jobs.submit('check_library', f'库级检查 {vendor}/{library}', fn, scope_key=f'check:{vendor}/{library}')
            except JobConflictError as exc:
                return jsonify({'error': str(exc), 'active_job': exc.active_job}), 409
            return jsonify(job), 202
        fn = lambda cb, ev: run_revision(work, vendor, library, revision, baseline=baseline, render=not lazy_excel, single_renderer=render_excel_from_check, progress_cb=cb, cancel_event=ev)
        try:
            job = jobs.submit('check_revision', f'单版本检查 {vendor}/{library} {revision}', fn, scope_key=f'check:{vendor}/{library}:{revision}')
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
