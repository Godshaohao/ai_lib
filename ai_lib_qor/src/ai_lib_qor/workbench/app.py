"""Loopback-only web adapter; all business operations stay in the pipeline."""
import hmac
import json
import os
import re
import subprocess
from pathlib import Path
from flask import Flask, abort, redirect, render_template, request, send_file, session, url_for
from .service import ARTIFACTS, execute, execute_evidence, execute_ip_batch, history, plans_in, select_plan, plans_for_revision
from .catalog import load_catalog, file_rows, compare_rows, member_rows, formal_comparison
from .scans import sources, observations, run_scan
from .registration import registered_deliveries

RUN_ID = re.compile(r'run_[0-9a-f]{32}\Z')


def create_app(plan_root, runs_root, work_root=None):
    app = Flask(__name__)
    app.secret_key = os.urandom(32)
    app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Strict')
    plans, runs = Path(plan_root).resolve(), Path(runs_root).resolve()
    if not plans.is_dir(): raise ValueError('计划目录不存在')
    runs.mkdir(parents=True, exist_ok=True)
    if runs.is_relative_to(plans): raise ValueError('运行输出不能位于计划目录中')

    @app.before_request
    def local_only():
        if request.remote_addr not in ('127.0.0.1', '::1'):
            abort(403)
        host = request.host.split(':', 1)[0]
        if host not in ('localhost', '127.0.0.1', '['): abort(403)
        if 'csrf' not in session: session['csrf'] = os.urandom(32).hex()
        if request.method == 'POST' and not hmac.compare_digest(session['csrf'], request.form.get('csrf', '')):
            abort(403)

    @app.get('/')
    def index():
        entries, snapshots, warnings = load_catalog(work_root)
        try:
            scan_sources = sources(work_root)
            scan_rows = []
            for x in scan_sources:
                history_rows = observations(runs,x)
                latest = history_rows[0] if history_rows else None
                versions = sorted({f['path'].split('/',1)[0] for f in latest['files'] if '/' in f['path']}) if latest and latest['status']=='COMPLETE' else []
                scan_rows.append({'source':x, 'observations':history_rows, 'candidate_dirs':versions, 'deliveries':registered_deliveries(work_root,x)})
        except (ValueError, KeyError, OSError, TypeError) as exc:
            scan_rows = []; warnings.append(f'扫描配置错误: {exc}')
        sidebar = {}
        for entry in entries:
            key = (entry['vendor'], entry['library'])
            sidebar.setdefault(key, {'vendor': key[0], 'library': key[1], 'ips': [], 'configured': False})['ips'].append(entry)
        for row in scan_rows:
            source = row['source']; key = (source['vendor_id'], source['source_library_id'])
            sidebar.setdefault(key, {'vendor': key[0], 'library': key[1], 'ips': [], 'configured': False})['configured'] = True
        sidebar_libraries = [sidebar[key] for key in sorted(sidebar)]
        chosen = tuple(request.args.get(x, '') for x in ('vendor', 'library', 'ip'))
        selected = next((e for e in entries if (e['vendor'], e['library'], e['ip']) == chosen), None)
        if any(chosen) and selected is None: abort(400)
        if selected is None and entries: selected = entries[0]
        deliveries = selected['deliveries'] if selected else []
        snapshot_id = request.args.get('snapshot', '')
        snapshot_counts = {}
        for item in snapshots:
            sid = f"{item['formal_nl_id']}/{item['formal_snapshot_id']}"
            snapshot_counts[sid] = snapshot_counts.get(sid, 0) + 1
        matching_snapshots = [s for s in snapshots if f"{s['formal_nl_id']}/{s['formal_snapshot_id']}" == snapshot_id]
        if snapshot_id and len(matching_snapshots) != 1: abort(400)
        snapshot = matching_snapshots[0] if matching_snapshots else None
        formal_query = request.args.get('formal_q', '').strip()
        formal_match = request.args.get('formal_match', '').strip()
        if formal_match not in ('', 'MATCHED_RAW', 'UNMATCHED', 'NOT_ATTEMPTED'): abort(400)
        formal_files = [f for f in snapshot['linked_files'] if (not formal_query or formal_query.casefold() in ' '.join(str(f.get(k) or '') for k in ('file_key','file_id','link_path','resolved_path')).casefold()) and (not formal_match or f['source_match'] == formal_match)] if snapshot else []
        revision_id = request.args.get('revision', '')
        versions = selected['versions'] if selected else []
        if not revision_id and selected: revision_id = selected['index']['latest_calculated_revision'] or ''
        revision = next((r for r in versions if r['revision_id'] == revision_id), None)
        if request.args.get('revision') and revision is None: abort(400)
        requested_view = request.args.get('view', 'files')
        view = {'catalog':'checks', 'manual':'checks'}.get(requested_view, requested_view)
        if view not in ('files', 'compare', 'deliveries', 'formal', 'history', 'checks', 'discover', 'versions'): abort(400)
        all_members = member_rows(revision, deliveries, snapshots)
        filters = {k: request.args.get(k, '').strip() for k in ('q', 'source', 'file_view', 'change', 'corner')}
        if filters['source'] not in ('', 'RAW', 'FORMAL') or filters['change'] not in ('', 'ADDED', 'REPLACED', 'UNCHANGED'):
            abort(400)
        file_views = sorted({r['file_view'] for r in all_members})
        if filters['file_view'] and filters['file_view'] not in file_views: abort(400)
        corners = sorted({r['detail']['corner'] for r in all_members if r['detail'] and r['detail']['corner']})
        if filters['corner'] and filters['corner'] not in corners: abort(400)
        query = filters['q'].casefold()
        members = [r for r in all_members if (not query or query in ' '.join([r['key'],r['label'],r['detail']['path'] if r['detail'] else '']).casefold())
                   and (not filters['source'] or r['source_kind']==filters['source'])
                   and (not filters['file_view'] or r['file_view']==filters['file_view'])
                   and (not filters['change'] or r['action']==filters['change'])
                   and (not filters['corner'] or (r['detail'] and r['detail']['corner']==filters['corner']))]
        matching_plans = {r['revision_id']: plans_for_revision(plans, r) for r in versions}
        plan_baselines = {}
        for names in matching_plans.values():
            for name in names:
                try:
                    plan = json.loads((plans / name).read_text(encoding='utf-8'))
                    baseline_path = plan.get('baseline_revision')
                    from ai_lib_qor.versions.store import read_json
                    plan_baselines[name] = read_json(baseline_path, 'effective_version')['revision_id'] if baseline_path else '无（初始版本）'
                except (OSError, ValueError, KeyError):
                    plan_baselines[name] = '无法读取'
        version_views = {}
        for item in versions:
            counts = {}
            for row in member_rows(item, deliveries, snapshots): counts[row['file_view']] = counts.get(row['file_view'], 0) + 1
            version_views[item['revision_id']] = counts
        nl_rows = formal_comparison(revision, snapshot, snapshots)
        plan_readiness = [{'revision':r['revision_id'], 'plans':matching_plans[r['revision_id']]} for r in versions]
        runs_list = history(runs)
        selected_runs = [r for r in runs_list if selected and r.get('owner') == {k:selected[k] for k in ('vendor','library','ip')}]
        overall_runs = [r for r in selected_runs if r.get('target_kind') == 'IP_VERSION_BATCH']
        revision_runs = {v['revision_id']: [r for r in selected_runs if r.get('target_kind') != 'IP_VERSION_BATCH' and (r.get('expected_revision') or r.get('target')) == v['revision_id']] for v in versions}
        file_filter = request.args.get('file_q', '').strip().casefold()
        file_view = request.args.get('file_kind', '').strip()
        location_rows = file_rows(deliveries)
        file_kinds = sorted({r['view'] for r in location_rows})
        if file_view and file_view not in file_kinds: abort(400)
        shown_rows = [r for r in location_rows if (not file_filter or file_filter in (r['key']+' '+r['path']).casefold()) and (not file_view or r['view']==file_view)]
        unresolved_count = sum(1 for d in deliveries for f in d['files'] if f['classification'] == 'UNRESOLVED')
        history_scope = request.args.get('history_scope', 'ip' if selected else 'all')
        if history_scope not in ('ip','all'): abort(400)
        shown_runs = selected_runs if history_scope == 'ip' else runs_list
        return render_template('index.html', entries=entries, selected=selected, snapshots=snapshots, snapshot=snapshot,
                               warnings=warnings, snapshot_counts=snapshot_counts, formal_files=formal_files, formal_query=formal_query, formal_match=formal_match, revision=revision, members=members, member_total=len(all_members), file_views=file_views, corners=corners, filters=filters, rows=shown_rows, file_total=len(location_rows), file_filter=file_filter, file_kind=file_view, file_kinds=file_kinds, unresolved_count=unresolved_count, history_scope=history_scope, shown_runs=shown_runs, compare=compare_rows(deliveries, request.args.get('base'), request.args.get('target')),
                               view=view, scan_rows=scan_rows, sidebar_libraries=sidebar_libraries, version_views=version_views, plan_baselines=plan_baselines, nl_rows=nl_rows, plans=plans_in(plans), runs=runs_list, selected_runs=selected_runs, overall_runs=overall_runs, revision_runs=revision_runs, plan_readiness=plan_readiness, plan_root=str(plans), matching_plans=matching_plans, output_root=str(runs), csrf=session['csrf'], work_root=work_root)

    @app.route('/registration', methods=['GET','POST'])
    def registration():
        from .registration import register_delivery, SAFE
        vendor = request.values.get('vendor',''); library = request.values.get('library','')
        version = request.values.get('version','')
        try:
            matches = [x for x in sources(work_root) if (x['vendor_id'],x['source_library_id']) == (vendor,library)]
            if len(matches)!=1 or not SAFE.fullmatch(version): abort(400)
            source = matches[0]
            scans = observations(runs,source)
            scan = next((x for x in scans if x['status']=='COMPLETE'),None)
            if not scan: raise ValueError('请先完成库扫描')
            if request.method == 'POST' and request.form.get('scan_id') != scan['scan_id']:
                raise ValueError('扫描记录已更新，请重新确认文件')
            prefix = version+'/'
            files = sorted(f['path'][len(prefix):] for f in scan['files'] if f['path'].startswith(prefix))
            if not files: raise ValueError('扫描中没有该交付目录的文件')
            if request.method == 'POST':
                mapping = {name:{'file_key':request.form.get(f'file_key_{i}','').strip()} for i,name in enumerate(files)}
                meta = {key:request.form.get(key,'').strip() for key in ('delivery_id','supplier_version','delivery_order','package_mode')}
                if not meta['supplier_version']: raise ValueError('供应商版本不能为空')
                path=register_delivery(work_root,source,scan,version,meta,mapping)
                return redirect(url_for('registration_done',vendor=vendor,library=library,delivery=meta['delivery_id']),code=303)
            return render_template('registration.html',source=source,version=version,files=files,scan=scan,csrf=session['csrf'])
        except (OSError,ValueError,KeyError,TypeError) as exc:
            return render_template('operation_error.html',message=str(exc),params={}),409

    @app.get('/registration/done')
    def registration_done():
        return render_template('registration_done.html',vendor=request.args.get('vendor',''),library=request.args.get('library',''),delivery=request.args.get('delivery',''))

    @app.post('/scan-all')
    def scan_all():
        try:
            configured = sources(work_root)
            if not configured: raise ValueError('没有已配置的扫描库')
            for source in configured: run_scan(runs, source)
        except (OSError, ValueError, KeyError) as exc:
            return render_template('operation_error.html',message=str(exc),params={}),409
        return redirect(url_for('index',view='discover'),code=303)

    @app.post('/scan')
    def scan_source():
        try:
            matches = [x for x in sources(work_root) if x['vendor_id']==request.form.get('vendor') and x['source_library_id']==request.form.get('library')]
            if len(matches)!=1: abort(400)
            run_scan(runs,matches[0])
        except (OSError, ValueError, KeyError) as exc:
            return render_template('operation_error.html',message=str(exc),params={}), 409
        return redirect(url_for('index',view='discover'),code=303)

    @app.post('/runs')
    def start_run():
        try: plan = select_plan(plans, request.form.get('plan', ''))
        except ValueError: abort(400)
        result = execute(plan, runs)
        return redirect(url_for('detail', run_id=result['id']), code=303)

    @app.post('/version-run')
    def start_version_run():
        entries, _, _ = load_catalog(work_root)
        owner = {key:request.form.get(key, '') for key in ('vendor','library','ip')}
        selected = next((e for e in entries if all(e[k] == owner[k] for k in owner)), None)
        if not selected: abort(400)
        matches = [r for r in selected['versions'] if r['revision_id'] == request.form.get('revision')]
        if len(matches) != 1: abort(400)
        name = request.form.get('plan', '')
        if name not in plans_for_revision(plans, matches[0]): abort(400)
        result = execute(select_plan(plans, name), runs, owner=owner, expected_revision=matches[0]['revision_id'])
        return redirect(url_for('detail',run_id=result['id']),code=303)

    @app.post('/effective/apply')
    def apply_effective():
        from ai_lib_qor.versions.store import read_json
        from ai_lib_qor.versions.__main__ import parser as version_parser, run as version_run
        entries, _, _ = load_catalog(work_root)
        owner = {key: request.form.get(key, '') for key in ('vendor', 'library', 'ip')}
        selected = next((e for e in entries if all(e[k] == owner[k] for k in owner)), None)
        if not selected or not work_root: abort(400)
        delivery_id = request.form.get('delivery', '')
        if sum(d['delivery_id'] == delivery_id for d in selected['deliveries']) != 1: abort(400)
        root = Path(work_root).resolve()
        library_dir = root / 'vendors' / owner['vendor'] / 'libraries' / owner['library']
        effective_dir = library_dir / 'ips' / owner['ip'] / 'effective'
        delivery_dir = library_dir / 'deliveries'
        paths = list(delivery_dir.glob('*.json')) + list(delivery_dir.glob('*/delivery.json'))
        matches = []
        for path in paths:
            if path.is_symlink() or path.parent.is_symlink() or not path.resolve().is_relative_to(delivery_dir.resolve()): continue
            try:
                item = read_json(path, 'delivery_record')
                if item['delivery_id'] == delivery_id and item['source_library_id'] == owner['library'] and item['vendor_id'] == owner['vendor']: matches.append(path)
            except (OSError, ValueError, KeyError): continue
        if len(matches) != 1 or not effective_dir.resolve().is_relative_to(root): abort(400)
        try:
            args = version_parser().parse_args(['apply', '--effective-dir', str(effective_dir), '--delivery', str(matches[0])])
            result = version_run(args)
        except (OSError, ValueError, KeyError) as exc:
            return render_template('operation_error.html', message=str(exc), params=owner), 409
        return redirect(url_for('index', view='versions', revision=result['revision_id'], generated='1' if result.get('changed') else '0', **owner), code=303)

    @app.post('/ip-run')
    def start_ip_run():
        entries, _, _ = load_catalog(work_root)
        owner={key:request.form.get(key, '') for key in ('vendor','library','ip')}
        selected=next((e for e in entries if all(e[k]==owner[k] for k in owner)),None)
        if not selected: abort(400)
        try: result=execute_ip_batch(selected,plans,runs)
        except ValueError: abort(400)
        return redirect(url_for('detail',run_id=result['id']),code=303)

    @app.get('/outputs')
    def outputs():
        return render_template('outputs.html', runs=history(runs), output_root=str(runs), csrf=session['csrf'])

    def open_directory(path):
        try:
            result = subprocess.run(['xdg-open',str(path)],capture_output=True,text=True,timeout=10,check=False)
            return result.returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            return False

    @app.post('/outputs/open-folder')
    def open_output_root():
        return redirect(url_for('outputs', folder_error=0 if open_directory(runs) else 1),code=303)

    @app.post('/evidence')
    def extract_evidence():
        entries, _, _ = load_catalog(work_root)
        selected = next((e for e in entries if (e['vendor'], e['library'], e['ip']) ==
                         tuple(request.form.get(k, '') for k in ('vendor', 'library', 'ip'))), None)
        if not selected: abort(400)
        deliveries = [d for d in selected['deliveries'] if d['delivery_id'] == request.form.get('delivery')]
        if len(deliveries) != 1: abort(400)
        files = [f for f in deliveries[0]['files'] if f['file_id'] == request.form.get('file_id')]
        if len(files) != 1 or files[0]['classification'] != 'RESOLVED' or files[0]['view'] not in ('LEF','LIBERTY','VERILOG','CDL'): abort(400)
        try: result = execute_evidence(deliveries[0], files[0]['file_id'], runs)
        except ValueError: abort(400)
        return redirect(url_for('detail',run_id=result['id']),code=303)

    def lookup(run_id):
        if not RUN_ID.fullmatch(run_id): abort(404)
        item = next((item for item in history(runs) if item['id'] == run_id), None)
        if item is None: abort(404)
        return item

    @app.get('/runs/<run_id>')
    def detail(run_id):
        item = lookup(run_id)
        artifacts = [name for name in ARTIFACTS if (runs / run_id / name).is_file()]
        inputs = []
        quality = None
        try:
            check_path = runs / run_id / 'check.json'
            if not check_path.is_symlink() and check_path.is_file():
                quality = json.loads(check_path.read_text(encoding='utf-8')).get('summary')
        except (OSError, ValueError, AttributeError): pass
        try:
            plan_path = runs / run_id / 'input_plan.json'
            if not plan_path.is_symlink() and plan_path.is_file():
                plan = json.loads(plan_path.read_text(encoding='utf-8'))
                for key,label in [('target_revision','目标有效版本'),('baseline_revision','检查基线'),('report_formal_snapshot','正式快照')]:
                    if plan.get(key): inputs.append((label, plan[key]))
                for group,keys in [('comparisons',('old_facts','new_facts')),('pin_pairs',('lef_facts','liberty_facts')),('auto_pair_facts',('facts',))]:
                    for row in plan.get(group, []):
                        for key in keys:
                            if row.get(key) and ('解析事实', row[key]) not in inputs: inputs.append(('解析事实',row[key]))
        except (OSError, ValueError, TypeError, AttributeError): pass
        return render_template('detail.html', run=item, artifacts=artifacts, inputs=inputs, quality=quality, output_path=str(runs / run_id), csrf=session['csrf'], folder_error=request.args.get('folder_error') == '1')

    @app.post('/runs/<run_id>/open-folder')
    def open_run_folder(run_id):
        lookup(run_id)
        path = runs / run_id
        if path.is_symlink() or not path.is_dir(): abort(404)
        return redirect(url_for('detail',run_id=run_id,folder_error=0 if open_directory(path) else 1),code=303)

    @app.get('/runs/<run_id>/preview/<name>')
    def preview(run_id,name):
        lookup(run_id)
        path=runs / run_id / name
        if name not in ('report.html','parser_evidence.html') or path.is_symlink() or not path.is_file(): abort(404)
        response=send_file(path, as_attachment=False)
        response.headers['Content-Security-Policy']="default-src 'none'; style-src 'unsafe-inline'"
        return response

    @app.get('/runs/<run_id>/artifacts/<name>')
    def artifact(run_id, name):
        lookup(run_id)
        path = runs / run_id / name
        if name not in ARTIFACTS or path.is_symlink() or not path.is_file(): abort(404)
        return send_file(path, as_attachment=True, download_name=name)

    return app
