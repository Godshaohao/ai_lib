"""Loopback-only web adapter; all business operations stay in the pipeline."""
import hmac
import json
import os
import re
import subprocess
from pathlib import Path
from flask import Flask, abort, g, jsonify, redirect, render_template, request, send_file, session, url_for
from ai_lib_qor.application.runs import ARTIFACTS, execute, execute_evidence, execute_ip_batch, history, plans_in, select_plan, plans_for_revision, plans_for_v2_revision
from .catalog import load_catalog, file_rows, compare_rows, member_rows, formal_comparison
from ai_lib_qor.application.scans import sources, observations, run_scan_and_ingest, ingest_result
from ai_lib_qor.sources.registration import registered_deliveries
from .read_models import build_file_matrix, result_matches
from ai_lib_qor.sources.formal_sync import formal_sources, formal_history
from ai_lib_qor.application.library_catalog import LibraryCatalog
from .progress import OperationProgress

RUN_ID = re.compile(r'run_[0-9a-f]{32}\Z')
FACT_ARTIFACT = re.compile(r'facts_[0-9a-f]{24}\.json\Z')


def v3_profile_names(plans):
    result=[]
    for name in plans_in(plans):
        if not re.fullmatch(r'v3_profile_[A-Za-z0-9_.-]+\.json',name):continue
        try:
            data=json.loads(select_plan(plans,name).read_text(encoding='utf-8'))
            if isinstance(data,dict) and set(data)=={'pin_pairs'} and isinstance(data['pin_pairs'],list) and data['pin_pairs']:
                result.append(name)
        except (OSError,ValueError,TypeError):continue
    return result


def sidebar_groups(entries, configured, work=None):
    grouped = {}
    for entry in entries:
        key = (entry['vendor'], entry['library'])
        grouped.setdefault(key, {'vendor':key[0], 'library':key[1], 'ips':[], 'configured':False})['ips'].append(entry)
    for source in configured:
        key = (source['vendor_id'], source['source_library_id'])
        grouped.setdefault(key, {'vendor':key[0], 'library':key[1], 'ips':[], 'configured':False})['configured'] = True
    if work:
        from ai_lib_qor.application.data_query import list_effective_v2
        for (vendor,library),group in grouped.items():
            newest={}
            for row in list_effective_v2(work,vendor,library):
                if row['owner']['type']!='BUSINESS_IP':continue
                key=(row['set_id'],row['owner']['id'])
                if key not in newest or int(row['revision'][4:])>int(newest[key]['revision'][4:]):newest[key]=row
            group['v2_ips']=[{'set_id':row['set_id'],'ip':row['owner']['id'],'revision':row['revision']}
                             for key,row in sorted(newest.items()) if not any(x['ip']==key[1] for x in group['ips'])]
            group['v2_ip_count']=len({x['ip'] for x in group['v2_ips']})
    return [grouped[key] for key in sorted(grouped)]


def create_app(plan_root, runs_root, work_root=None, *, path_mode=None):
    from .path_app import is_path_work,create_path_app
    if path_mode is True or (path_mode is None and is_path_work(work_root)):
        return create_path_app(work_root)
    app = Flask(__name__)
    operations=OperationProgress()
    app.secret_key = os.urandom(32)
    app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Strict')
    plans, runs = Path(plan_root).resolve(), Path(runs_root).resolve()
    if not plans.is_dir(): raise ValueError('计划目录不存在')
    runs.mkdir(parents=True, exist_ok=True)
    if runs.is_relative_to(plans): raise ValueError('运行输出不能位于计划目录中')

    def all_history():
        from ai_lib_qor.application.library_runs import history as library_history
        rows=history(runs)+library_history(work_root)
        counts={}
        for row in rows:counts[row['id']]=counts.get(row['id'],0)+1
        return sorted((row for row in rows if counts[row['id']]==1),key=lambda x:x.get('started_at',''),reverse=True)

    @app.before_request
    def local_only():
        if request.remote_addr not in ('127.0.0.1', '::1'):
            abort(403)
        host = request.host.split(':', 1)[0]
        if host not in ('localhost', '127.0.0.1', '['): abort(403)
        if 'csrf' not in session: session['csrf'] = os.urandom(32).hex()
        if request.method == 'POST' and not hmac.compare_digest(session['csrf'], request.form.get('csrf', '')):
            abort(403)
        labels={'scan_all':'扫描全部 RAW','scan_source':'扫描 RAW','formal_sync':'同步正式来源',
                'start_run':'执行检查','start_version_run':'单版本检查','start_v2_run':'单版本检查','start_ip_run':'整体 IP 检查',
                'start_v3_index_run':'v3 索引单版本检查','start_v3_index_ip':'v3 索引整体 IP 检查',
                'apply_effective':'更新有效版本','extract_evidence':'提取解析证据','registration':'登记交付'}
        ident=request.form.get('_operation_id','') if request.method=='POST' else ''
        if ident and request.endpoint in labels:
            if not re.fullmatch(r'[0-9a-f]{32}',ident):abort(400)
            if not operations.start(ident,session['csrf'],labels[request.endpoint]):abort(409)
            g.operation_id=ident

    def progress(message,completed=None,total=None):
        ident=getattr(g,'operation_id',None)
        if ident:operations.update(ident,message,completed,total)

    def finish_progress(state,message):
        ident=getattr(g,'operation_id',None)
        if ident:operations.finish(ident,state,message)

    @app.after_request
    def finish_request(response):
        if getattr(g,'operation_id',None):
            finish_progress('FAILED' if response.status_code>=400 else 'SUCCEEDED',
                            '操作失败，请查看错误信息' if response.status_code>=400 else '操作已完成')
        return response

    @app.get('/operations/<ident>')
    def operation_status(ident):
        if not re.fullmatch(r'[0-9a-f]{32}',ident):abort(404)
        status=operations.get(ident,session['csrf'],wait=request.args.get('wait')=='1')
        if status is None:abort(404)
        response=jsonify(status);response.headers['Cache-Control']='no-store'
        return response

    @app.get('/')
    def index():
        # L1 is a read-only source projection. Do not build plans, check history,
        # macros or per-IP matrices when the user opens the global page.
        if request.args.get('view') == 'discover' or (not request.args.get('view') and not any(
                request.args.get(k) for k in ('vendor', 'library', 'ip'))):
            return render_template('global_overview.html', csrf=session['csrf'],
                                   **LibraryCatalog(work_root,runs).refresh().overview())
        catalog=LibraryCatalog(work_root,runs).refresh()
        entries, snapshots, warnings = catalog.entries, catalog.snapshots, catalog.warnings
        overview=catalog.overview()
        scan_rows=overview['scan_rows']
        formal_rows=overview['formal_observation_rows']
        sidebar_libraries = sidebar_groups(entries, [dict(vendor_id=k[0],source_library_id=k[1]) for k in catalog.libraries],work_root)
        chosen = tuple(request.args.get(x, '') for x in ('vendor', 'library', 'ip'))
        selected = next((e for e in entries if (e['vendor'], e['library'], e['ip']) == chosen), None)
        if any(chosen) and selected is None: abort(400)
        if selected is None and entries and request.args.get('view') in ('files','compare','deliveries','versions','formal','history','checks','catalog','manual'): selected = entries[0]
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
        requested_view = request.args.get('view', 'overview' if selected else 'discover')
        view = {'catalog':'checks', 'manual':'checks'}.get(requested_view, requested_view)
        if view not in ('files', 'compare', 'deliveries', 'formal', 'history', 'checks', 'discover', 'versions', 'overview', 'analysis'): abort(400)
        ip_model=catalog.ip_detail(selected['vendor'],selected['library'],selected['ip'],revision_id=revision_id) if selected else None
        all_members = ip_model['members'] if ip_model else []
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
        runs_list = all_history()
        selected_runs = [r for r in runs_list if selected and r.get('owner') == {k:selected[k] for k in ('vendor','library','ip')}]
        overall_runs = [r for r in selected_runs if r.get('target_kind') == 'IP_VERSION_BATCH']
        revision_runs = {v['revision_id']: [r for r in selected_runs if r.get('target_kind') != 'IP_VERSION_BATCH' and (r.get('expected_revision') or r.get('target')) == v['revision_id']] for v in versions}
        baseline_arg = request.args.get('baseline', '')
        baseline_id = baseline_arg or (revision.get('parent_revision_id') if revision else None)
        baseline = next((r for r in versions if r['revision_id'] == baseline_id), None)
        if baseline_arg and (not baseline or not revision or versions.index(baseline) >= versions.index(revision)): abort(400)
        baseline_missing = bool(baseline_id and baseline is None)
        baseline_options = versions[:versions.index(revision)] if revision else []
        ip_model=(catalog.ip_detail(selected['vendor'],selected['library'],selected['ip'],revision_id=revision_id,
                  baseline_id=baseline_id,formal_snapshot=snapshot if view=='analysis' else None) if selected else None)
        matching_result=ip_model['matching_result'] if ip_model else None
        matrix=ip_model['matrix'] if ip_model else build_file_matrix(None,None,[],[])
        matrix_filters={key:request.args.get('matrix_'+key,'').strip() for key in ('q','view','corner','source','content','check')}
        matrix_all=matrix['rows']
        matrix_views=sorted({r['view'] for r in matrix_all})
        matrix_corners=sorted({r['corner'] for r in matrix_all if r['corner']})
        if view=='analysis':
            matrix['rows']=[r for r in matrix_all if (not matrix_filters['q'] or matrix_filters['q'].casefold() in r['file_key'].casefold())
                and (not matrix_filters['view'] or r['view']==matrix_filters['view'])
                and (not matrix_filters['corner'] or r['corner']==matrix_filters['corner'])
                and (not matrix_filters['source'] or r['source_relation']==matrix_filters['source'])
                and (not matrix_filters['content'] or r['content_status']==matrix_filters['content'])
                and (not matrix_filters['check'] or (matrix_filters['check']=='NOT_RUN' and not r['checks']) or any(q['result']==matrix_filters['check'] for q in r['checks']))]
            keys={r['file_key'] for r in matrix['rows']};matrix['objects']=[x for x in matrix['objects'] if x['file_key'] in keys]
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
                               view=view, baseline=baseline, baseline_missing=baseline_missing, baseline_options=baseline_options, matrix=matrix, matrix_filters=matrix_filters, matrix_views=matrix_views, matrix_corners=matrix_corners, scan_rows=scan_rows, formal_rows=formal_rows, sidebar_libraries=sidebar_libraries, version_views=version_views, plan_baselines=plan_baselines, nl_rows=nl_rows, plans=plans_in(plans), runs=runs_list, selected_runs=selected_runs, overall_runs=overall_runs, revision_runs=revision_runs, plan_readiness=plan_readiness, plan_root=str(plans), matching_plans=matching_plans, output_root=str(runs), csrf=session['csrf'], work_root=work_root)

    @app.get('/api/library-data')
    def library_data_api():
        from ai_lib_qor.application.data_query import query_data
        if not work_root:return jsonify({'error':'未配置 work 目录'}),400
        names=('vendor','library','version','view','path','file_key','owner','set_id','revision','snapshot','delivery_id','other_revision')
        try:
            options={name:request.args.get(name) for name in names};options['revisions']=request.args.getlist('revisions')
            result=query_data(work_root,runs,request.args.get('kind',''),**options)
            return jsonify(result)
        except (OSError,ValueError,KeyError) as exc:
            return jsonify({'error':str(exc)}),400

    @app.get('/library')
    def library_workspace():
        vendor = request.args.get('vendor', '')
        library = request.args.get('library', '')
        catalog=LibraryCatalog(work_root,runs).refresh()
        context = catalog.library_detail(vendor,library)
        if context is None: abort(404)
        entries=catalog.entries
        from ai_lib_qor.application.data_query import list_effective_v2, query_data
        try:index_status=query_data(work_root,runs,'index-status',vendor=vendor,library=library)
        except (OSError,ValueError,KeyError) as exc:index_status={'status':'INVALID','message':'索引状态无法核验：'+str(exc)}
        v2_versions=list_effective_v2(work_root,vendor,library)
        v2_ip_sets={}
        for item in v2_versions:
            if item['owner']['type']!='BUSINESS_IP' or any(x['ip']==item['owner']['id'] for x in context.get('ips',[])):continue
            key=(item['set_id'],item['owner']['id'])
            if key not in v2_ip_sets or int(item['revision'][4:])>int(v2_ip_sets[key]['revision'][4:]):v2_ip_sets[key]=item
        set_id=request.args.get('set_id','');revision=request.args.get('revision','');v2_selected=None;v2_plans=[];v2_blocked=None
        v2_comparison=None;v2_comparison_error=None;v2_baselines=[];v2_baseline=''
        if set_id or revision:
            if not any(v['set_id']==set_id and v['revision']==revision for v in v2_versions):abort(400)
            try:v2_selected=query_data(work_root,runs,'effective-v2',vendor=vendor,library=library,set_id=set_id,revision=revision)
            except (OSError,ValueError,KeyError):abort(400)
            v2_baselines=[v for v in v2_versions if v['set_id']==set_id and v['revision']!=revision]
            v2_baseline=request.args.get('baseline',v2_selected['parent'] or '')
            if v2_baseline:
                if not any(v['revision']==v2_baseline for v in v2_baselines):v2_comparison_error='基准版本未找到，无法比较。'
                else:
                    try:v2_comparison=query_data(work_root,runs,'compare-revisions',vendor=vendor,library=library,set_id=set_id,revision=v2_baseline,other_revision=revision)
                    except (OSError,ValueError,KeyError) as exc:v2_comparison_error=str(exc)
            v2_plans=plans_for_v2_revision(plans,work_root,vendor,library,set_id,revision)
            from ai_lib_qor.application.v2_check_adapter import load_v2_for_check
            from ai_lib_qor.sources.layout import library_folder
            try:load_v2_for_check(library_folder(work_root,vendor,library)/f'effective_{set_id}_{int(revision[4:]):03d}.json',work_root)
            except (OSError,ValueError,KeyError) as exc:v2_blocked=str(exc)
        index_refresh_message=session.pop('index_refresh_message',None)
        policy_message=session.pop('policy_message',None);version_message=session.pop('version_message',None);excluded_ids=set();policy_error=None;latest_revision=None
        if v2_selected:
            latest_revision=max((x['revision'] for x in v2_versions if x['set_id']==set_id),key=lambda x:int(x[4:]))
            try:
                from ai_lib_qor.application.effective_workflow import excluded_deliveries
                excluded_ids=excluded_deliveries(work_root,vendor,library,set_id)
            except (OSError,ValueError,KeyError,TypeError) as exc:policy_error=str(exc)
        return render_template('library_workspace.html', vendor=vendor, library=library, index_refresh_message=index_refresh_message,policy_message=policy_message,version_message=version_message,latest_revision=latest_revision,excluded_ids=excluded_ids,policy_error=policy_error,
                               sidebar_libraries=sidebar_groups(entries, [dict(vendor_id=k[0],source_library_id=k[1]) for k in catalog.libraries],work_root),
                               entries=entries, selected=None, view='library', v2_versions=v2_versions,v2_selected=v2_selected,v2_plans=v2_plans,v2_blocked=v2_blocked,
                               v2_comparison=v2_comparison,v2_comparison_error=v2_comparison_error,v2_baselines=v2_baselines,v2_baseline=v2_baseline,index_status=index_status,v3_profiles=v3_profile_names(plans),v2_ip_sets=list(v2_ip_sets.values()),csrf=session['csrf'], **context)

    @app.post('/delivery/policy')
    def delivery_policy():
        from ai_lib_qor.application.effective_workflow import set_delivery_exclusion
        vendor=request.form.get('vendor','');library=request.form.get('library','');set_id=request.form.get('set_id','');revision=request.form.get('revision','')
        action=request.form.get('action','')
        if action not in ('exclude','include'):abort(400)
        try:
            result=set_delivery_exclusion(work_root,vendor,library,set_id,request.form.get('delivery_id',''),excluded=action=='exclude',actor=request.form.get('actor',''),reason=request.form.get('reason',''))
            message={'EXCLUDED':'已排除后续参与','INCLUDED':'已恢复参与','UNCHANGED':'状态无变化'}[result['state']]
            if result['current_revision_uses_delivery']:message+='；当前版本仍引用该交付，历史未修改'
            session['policy_message']=message
        except (OSError,ValueError,KeyError,TypeError) as exc:session['policy_message']='操作失败：'+str(exc)
        return redirect(url_for('library_workspace',vendor=vendor,library=library,set_id=set_id,revision=revision)+'#deliveries',code=302)

    @app.post('/effective/restore')
    def restore_effective():
        from ai_lib_qor.application.effective_workflow import restore_effective_revision
        vendor=request.form.get('vendor','');library=request.form.get('library','');set_id=request.form.get('set_id','');revision=request.form.get('revision','')
        try:
            result=restore_effective_revision(work_root,vendor,library,set_id,revision,expected_parent_revision=request.form.get('expected_parent',''),actor=request.form.get('actor',''),reason=request.form.get('reason',''))
            if result['state']=='PUBLISHED':session['version_message']='已创建恢复版本 '+result['revision'];revision=result['revision']
            elif result['state']=='PUBLISHED_INDEX_STALE':session['version_message']='版本已发布，但索引需核查：'+result.get('error','');revision=result['revision']
            else:session['version_message']='文件组合无变化'
        except (OSError,ValueError,KeyError,TypeError) as exc:session['version_message']='恢复失败：'+str(exc)
        return redirect(url_for('library_workspace',vendor=vendor,library=library,set_id=set_id,revision=revision)+'#effective-files',code=302)

    @app.post('/effective/acceptance-rollback')
    def rollback_effective_acceptance():
        from ai_lib_qor.application.effective_workflow import rollback_acceptance
        vendor=request.form.get('vendor','');library=request.form.get('library','');set_id=request.form.get('set_id','');revision=request.form.get('revision','')
        try:
            result=rollback_acceptance(work_root,vendor,library,set_id,revision,actor=request.form.get('actor',''),reason=request.form.get('reason',''))
            session['version_message']='采纳已回退到 '+revision if result['state']=='ROLLED_BACK' else '回退事件已记录，索引需核查：'+result.get('error','')
        except (OSError,ValueError,KeyError,TypeError) as exc:session['version_message']='采纳回退失败：'+str(exc)
        return redirect(url_for('library_workspace',vendor=vendor,library=library,set_id=set_id,revision=revision)+'#effective-files',code=302)

    @app.post('/file-index/refresh')
    def refresh_file_index():
        from ai_lib_qor.application.file_index import refresh_library_index_locked
        from ai_lib_qor.application.latest_pointers import _config
        from ai_lib_qor.sources.layout import SAFE, library_folder
        from ai_lib_qor.versions.store import locked
        vendor=request.form.get('vendor','');library=request.form.get('library','')
        if not all(SAFE.fullmatch(x) and x not in ('.','..') for x in (vendor,library)):abort(400)
        if LibraryCatalog(work_root,runs).refresh().library_detail(vendor,library) is None:abort(404)
        try:
            folder=library_folder(work_root,vendor,library)
            with locked(folder):
                result=refresh_library_index_locked(work_root,vendor,library,_config(work_root,vendor,library))
            action=result.get('action')
            session['index_refresh_message']='交付顺序未确认，索引未更新' if action=='ORDER_UNCONFIRMED' else '索引已更新：'+str(action)
        except (OSError,ValueError,KeyError,TypeError) as exc:
            session['index_refresh_message']='索引更新失败：'+str(exc)
        return redirect(url_for('library_workspace',vendor=vendor,library=library)+'#file-history',code=302)

    @app.get('/effective-v2')
    def effective_v2_page():
        options={name:request.args.get(name,'') for name in ('vendor','library','set_id','revision')}
        return redirect(url_for('library_workspace',**options)+'#effective-files',code=302)

    @app.get('/formal/<nl_id>')
    def formal_detail(nl_id):
        catalog=LibraryCatalog(work_root,runs).refresh()
        detail=catalog.formal_detail(nl_id)
        if not detail['snapshots'] and not any(c['formal_nl_id']==nl_id for c in catalog.formal_configured): abort(404)
        return render_template('formal_catalog.html',detail=detail,warnings=catalog.warnings)

    @app.route('/registration', methods=['GET','POST'])
    def registration():
        from ai_lib_qor.sources.registration import register_delivery, SAFE
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
                progress(f'正在核验 {vendor} / {library} / {version} 的扫描记录和文件位')
                mapping = {name:{'file_key':request.form.get(f'file_key_{i}','').strip()} for i,name in enumerate(files)}
                meta = {key:request.form.get(key,'').strip() for key in ('delivery_id','supplier_version','delivery_order','package_mode')}
                if not meta['supplier_version']: raise ValueError('供应商版本不能为空')
                path=register_delivery(work_root,source,scan,version,meta,mapping)
                progress(f"交付记录已保存：{meta['delivery_id']}")
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
            failures=[];total=len(configured)
            for n,source in enumerate(configured):
                name=f"{source['vendor_id']} / {source['source_library_id']}"
                progress(f'正在扫描 {name}',n,total)
                row=run_scan_and_ingest(runs,work_root,source,progress=lambda message:progress(f'{name}：{message}'))
                ingest=ingest_result(runs,row) or {}
                if row['status']!='COMPLETE' or ingest.get('blocked',0) or ingest.get('modified',0):
                    failures.append(f"{name}：{'；'.join(ingest.get('reasons',[]) or row.get('errors',[])) or row['status']}")
                progress(f"{name}：新增 {ingest.get('created',0)}、重复 {ingest.get('duplicates',0)}、原地变化 {ingest.get('modified',0)}、未确认 {ingest.get('unresolved',0)}",n+1,total)
            if failures:finish_progress('PARTIAL','部分来源未完成：'+'；'.join(failures))
        except (OSError, ValueError, KeyError) as exc:
            return render_template('operation_error.html',message=str(exc),params={}),409
        return redirect(url_for('index',view='discover'),code=303)

    @app.post('/scan')
    def scan_source():
        try:
            matches = [x for x in sources(work_root) if x['vendor_id']==request.form.get('vendor') and x['source_library_id']==request.form.get('library')]
            if len(matches)!=1: abort(400)
            source=matches[0];name=f"{source['vendor_id']} / {source['source_library_id']}"
            progress(f'正在扫描 {name}',0,1)
            row=run_scan_and_ingest(runs,work_root,source,progress=lambda message:progress(f'{name}：{message}'))
            ingest=ingest_result(runs,row) or {}
            progress(f"{name}：新增 {ingest.get('created',0)}、重复 {ingest.get('duplicates',0)}、原地变化 {ingest.get('modified',0)}、未确认 {ingest.get('unresolved',0)}",1,1)
            if row['status']!='COMPLETE' or ingest.get('blocked',0) or ingest.get('modified',0):
                state='FAILED' if row['status']=='FAILED' else 'PARTIAL'
                finish_progress(state,'扫描需要处理：'+'；'.join(ingest.get('reasons',[]) or row.get('errors',[]) or [row['status']]))
        except (OSError, ValueError, KeyError) as exc:
            return render_template('operation_error.html',message=str(exc),params={}), 409
        return redirect(url_for('index',view='discover'),code=303)

    @app.post('/formal-sync')
    def formal_sync():
        from ai_lib_qor.sources.formal_sync import sync_formal
        try:
            configured=formal_sources(work_root)
            requested=request.form.get('formal_nl_id','')
            if requested: configured=[x for x in configured if x['formal_nl_id']==requested]
            if not configured: raise ValueError('没有匹配的正式来源配置')
            deliveries=[d for source in sources(work_root) for d in registered_deliveries(work_root,source)]
            failures=[];total=len(configured)
            for n,source in enumerate(configured):
                progress(f"正在同步 {source['formal_nl_id']}",n,total)
                result=sync_formal(runs,source,deliveries,work_root)
                if result.get('status')!='COMPLETE':failures.append(f"{source['formal_nl_id']}：{'；'.join(result.get('errors',[])) or result.get('status','未知')}")
                progress(f"已处理 {source['formal_nl_id']}",n+1,total)
            if failures:finish_progress('PARTIAL','部分正式来源未完成：'+'；'.join(failures))
        except (OSError,ValueError,KeyError,ImportError) as exc:
            return render_template('operation_error.html',message=str(exc),params={}),409
        return redirect(url_for('index',view='discover'),code=303)

    @app.post('/runs')
    def start_run():
        try: plan = select_plan(plans, request.form.get('plan', ''))
        except ValueError: abort(400)
        result = execute(plan, runs, progress=progress)
        if result['state']!='SUCCEEDED':finish_progress('FAILED',result.get('error','检查执行失败'))
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
        result = execute(select_plan(plans, name), runs, owner=owner, expected_revision=matches[0]['revision_id'],progress=progress)
        if result['state']!='SUCCEEDED':finish_progress('FAILED',result.get('error','检查执行失败'))
        return redirect(url_for('detail',run_id=result['id']),code=303)

    @app.post('/effective-v2/run')
    def start_v2_run():
        from ai_lib_qor.application.data_query import query_data
        args={key:request.form.get(key,'') for key in ('vendor','library','set_id','revision')}
        try:
            selected=query_data(work_root,runs,'effective-v2',**args)
            name=request.form.get('plan','')
            if name not in plans_for_v2_revision(plans,work_root,**args):abort(400)
            owner=({'vendor':args['vendor'],'library':args['library'],'ip':selected['owner']['id']}
                   if selected['owner']['type']=='BUSINESS_IP' else None)
            result=execute(select_plan(plans,name),runs,owner=owner,expected_revision=args['revision'],progress=progress)
        except (OSError,ValueError,KeyError) as exc:
            return render_template('operation_error.html',message=str(exc),params={}),409
        if result['state']!='SUCCEEDED':finish_progress('FAILED',result.get('error','检查执行失败'))
        return redirect(url_for('detail',run_id=result['id']),code=303)

    def execute_v3_index(batch):
        from ai_lib_qor.application.v3_checks import run_v3_ip,run_v3_revision
        args={key:request.form.get(key,'') for key in ('vendor','library','set_id','revision')}
        name=request.form.get('profile','')
        if name not in v3_profile_names(plans):abort(400)
        try:
            profile=json.loads(select_plan(plans,name).read_text(encoding='utf-8'))
            options={'vendor':args['vendor'],'library':args['library'],'set_id':args['set_id'],'profile':profile,'progress':progress}
            result=run_v3_ip(work_root,runs,**options) if batch else run_v3_revision(work_root,runs,revision=args['revision'],**options)
        except (OSError,ValueError,KeyError,TypeError) as exc:
            return render_template('operation_error.html',message=str(exc),params={}),409
        if result['state']!='SUCCEEDED':finish_progress(result['state'],result.get('error','部分版本执行失败，请查看各版本运行记录'))
        return redirect(url_for('detail',run_id=result['id']),code=303)

    @app.post('/index-v3/run')
    def start_v3_index_run():return execute_v3_index(False)

    @app.post('/index-v3/ip')
    def start_v3_index_ip():return execute_v3_index(True)

    @app.post('/effective/apply')
    def apply_effective():
        from ai_lib_qor.versions.store import read_json
        from ai_lib_qor.versions.service import apply_version, candidate_file_keys
        entries, _, _ = load_catalog(work_root)
        owner = {key: request.form.get(key, '') for key in ('vendor', 'library', 'ip')}
        selected = next((e for e in entries if all(e[k] == owner[k] for k in owner)), None)
        if not selected or not work_root: abort(400)
        delivery_id = request.form.get('delivery', '')
        if sum(d['delivery_id'] == delivery_id for d in selected['deliveries']) != 1: abort(400)
        root = Path(work_root).resolve()
        library_dir = root / 'vendors' / owner['vendor'] / 'libraries' / owner['library']
        effective_dir = library_dir / 'ips' / owner['ip'] / 'effective'
        from ai_lib_qor.application.source_repository import SourceRepository
        from ai_lib_qor.versions.store import index_path
        from ai_lib_qor.sources.layout import SAFE
        if not SAFE.fullmatch(selected['index']['effective_set_id']):abort(400)
        flat_dir=root/'libraries'/owner['vendor']/owner['library']/('effective_'+selected['index']['effective_set_id'])
        if index_path(flat_dir).is_file():effective_dir=flat_dir
        try:
            matches=[Path(x['path']) for x in SourceRepository(root).deliveries() if
                     (x['record']['vendor_id'],x['record']['source_library_id'],x['record']['delivery_id'])==
                     (owner['vendor'],owner['library'],delivery_id)]
        except (OSError,ValueError,KeyError):abort(409)
        if len(matches) != 1 or not effective_dir.resolve().is_relative_to(root): abort(400)
        try:
            progress('正在校验交付文件和候选有效版本')
            delivery = read_json(matches[0], 'delivery_record')
            selected_keys = None
            candidates = candidate_file_keys(matches[0],delivery)
            # Select only explicitly identified slots. An unclassified README
            # remains RAW history and cannot block a known LEF/Liberty update.
            if candidates or any(f['classification'] != 'RESOLVED' for f in delivery['files']):
                selected_keys = {f['file_key'] for f in delivery['files']
                                 if f['classification'] == 'RESOLVED' and f['file_key'] and f['file_key'] not in candidates}
                selected_keys.update(delivery['explicit_removed_file_keys'])
                if not selected_keys:
                    raise ValueError('当前交付没有可采用的已确认文件位')
            result = apply_version(effective_dir, matches[0],
                                   file_keys=sorted(selected_keys) if selected_keys is not None else None)
            progress(f"有效版本处理完成：{result['revision_id']}")
        except (OSError, ValueError, KeyError) as exc:
            return render_template('operation_error.html', message=str(exc), params=owner), 409
        return redirect(url_for('index', view='versions', revision=result['revision_id'], generated='1' if result.get('changed') else '0', **owner), code=303)

    @app.post('/ip-run')
    def start_ip_run():
        entries, _, _ = load_catalog(work_root)
        owner={key:request.form.get(key, '') for key in ('vendor','library','ip')}
        selected=next((e for e in entries if all(e[k]==owner[k] for k in owner)),None)
        if not selected: abort(400)
        try: result=execute_ip_batch(selected,plans,runs,progress=progress)
        except ValueError: abort(400)
        if result['state']!='SUCCEEDED':finish_progress(result['state'],result.get('error','部分版本执行失败，请查看各版本运行记录'))
        return redirect(url_for('detail',run_id=result['id']),code=303)

    @app.get('/outputs')
    def outputs():
        return render_template('outputs.html', runs=all_history(), output_root=str(runs), csrf=session['csrf'])

    @app.get('/directories')
    def directories():
        which=request.args.get('root','work')
        if which not in ('work','runs') or (which=='work' and not work_root): abort(400)
        root=Path(work_root if which=='work' else runs).resolve()
        rel=request.args.get('path','')
        path=Path(rel)
        if path.is_absolute() or '..' in path.parts: abort(400)
        target=root
        for part in path.parts:
            target=target/part
            if target.is_symlink(): abort(400)
        if not target.resolve().is_relative_to(root) or not target.is_dir(): abort(400)
        rows=[]
        for item in sorted(target.iterdir(),key=lambda p:(not p.is_dir(),p.name.lower())):
            if item.is_symlink(): continue
            try: stat=item.stat()
            except OSError: continue
            from datetime import datetime
            rows.append({'name':item.name,'path':str(item.relative_to(root)),
                         'directory':item.is_dir(), 'size':stat.st_size,
                         'mtime':stat.st_mtime, 'mtime_date':datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d')})
        return render_template('directories.html',which=which,root=str(root),relative=rel,rows=rows)

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
        try: result = execute_evidence(deliveries[0], files[0]['file_id'], runs,progress=progress)
        except ValueError: abort(400)
        if result['state']!='SUCCEEDED':finish_progress('FAILED',result.get('error','解析证据提取失败'))
        return redirect(url_for('detail',run_id=result['id']),code=303)

    def lookup(run_id):
        if not RUN_ID.fullmatch(run_id): abort(404)
        item = next((item for item in all_history() if item['id'] == run_id), None)
        if item is None: abort(404)
        if item.get('storage')!='LIBRARY':
            folder=runs/run_id
            if folder.is_symlink() or not folder.is_dir() or not folder.resolve().is_relative_to(runs):abort(404)
        return item

    def run_artifact(item,name):
        if item.get('storage')=='LIBRARY':
            from ai_lib_qor.application.library_runs import artifact as library_artifact
            try:return library_artifact(work_root,item,name)
            except (OSError,ValueError,KeyError,TypeError):return None
        path=runs/item['id']/name
        if (name not in ARTIFACTS and not FACT_ARTIFACT.fullmatch(name)) or path.is_symlink() or not path.is_file():return None
        return path

    @app.get('/runs/<run_id>')
    def detail(run_id):
        item = lookup(run_id)
        artifacts = [name for name in ARTIFACTS if run_artifact(item,name)]
        if item.get('storage')=='LIBRARY':artifacts.extend(name for name in item.get('facts_files',[]) if run_artifact(item,name))
        else:artifacts.extend(sorted(p.name for p in (runs/run_id).glob('facts_*.json') if FACT_ARTIFACT.fullmatch(p.name) and p.is_file() and not p.is_symlink()))
        inputs = []
        quality = None
        check_record = None
        try:
            check_path = run_artifact(item,'check.json')
            if check_path:
                check_record=json.loads(check_path.read_text(encoding='utf-8'));quality=check_record.get('summary')
        except (OSError, ValueError, AttributeError): pass
        try:
            plan_path = run_artifact(item,'input_plan.json')
            if plan_path:
                plan = json.loads(plan_path.read_text(encoding='utf-8'))
                for key,label in [('target_revision','目标有效版本'),('baseline_revision','检查基线'),('report_formal_snapshot','正式快照')]:
                    if plan.get(key): inputs.append((label, plan[key]))
                for group,keys in [('comparisons',('old_facts','new_facts')),('pin_pairs',('lef_facts','liberty_facts')),('auto_pair_facts',('facts',))]:
                    for row in plan.get(group, []):
                        for key in keys:
                            if row.get(key) and ('解析事实', row[key]) not in inputs: inputs.append(('解析事实',row[key]))
        except (OSError, ValueError, TypeError, AttributeError): pass
        back_url=None;v2_history=False
        if item.get('owner') and work_root:
            from ai_lib_qor.application.data_query import list_effective_v2
            owner=item['owner'];candidate=check_record
            if candidate is None and item.get('children'):
                for child in reversed(item['children']):
                    child_id=child.get('id','')
                    if not RUN_ID.fullmatch(child_id):continue
                    child_item=next((x for x in all_history() if x['id']==child_id),None)
                    child_path=run_artifact(child_item,'check.json') if child_item else None
                    try:
                        if child_path:candidate=json.loads(child_path.read_text(encoding='utf-8'));break
                    except (OSError,ValueError,TypeError):continue
            if isinstance(candidate,dict):
                set_id=candidate.get('effective_set_id');revision=(candidate.get('target') or {}).get('id')
                versions=list_effective_v2(work_root,owner['vendor'],owner['library'])
                match=next((v for v in versions if v['set_id']==set_id and v['revision']==revision and v['owner']['id']==owner['ip']),None)
                if match:
                    back_url=url_for('library_workspace',vendor=owner['vendor'],library=owner['library'],set_id=set_id,revision=revision)+'#effective-files';v2_history=True
        if item.get('storage')=='LIBRARY':
            from ai_lib_qor.sources.layout import library_folder
            output_path=library_folder(work_root,item['owner']['vendor'],item['owner']['library'])
        else:output_path=runs/run_id
        artifact_labels={name:run_artifact(item,name).name for name in artifacts if run_artifact(item,name)}
        return render_template('detail.html', run=item, artifacts=artifacts, artifact_labels=artifact_labels,inputs=inputs, quality=quality, back_url=back_url,v2_history=v2_history,output_path=str(output_path), csrf=session['csrf'], folder_error=request.args.get('folder_error') == '1')

    @app.post('/runs/<run_id>/open-folder')
    def open_run_folder(run_id):
        item=lookup(run_id)
        if item.get('storage')=='LIBRARY':
            from ai_lib_qor.sources.layout import library_folder
            path=library_folder(work_root,item['owner']['vendor'],item['owner']['library'])
        else:path = runs / run_id
        if path.is_symlink() or not path.is_dir(): abort(404)
        return redirect(url_for('detail',run_id=run_id,folder_error=0 if open_directory(path) else 1),code=303)

    @app.get('/runs/<run_id>/preview/<name>')
    def preview(run_id,name):
        item=lookup(run_id)
        path=run_artifact(item,name)
        if name not in ('report.html','parser_evidence.html') or not path: abort(404)
        response=send_file(path, as_attachment=False)
        response.headers['Content-Security-Policy']="default-src 'none'; style-src 'unsafe-inline'"
        return response

    @app.get('/runs/<run_id>/artifacts/<name>')
    def artifact(run_id, name):
        item=lookup(run_id)
        path=run_artifact(item,name)
        if not path: abort(404)
        return send_file(path, as_attachment=True, download_name=path.name)

    return app
