"""Local three-level workbench over path-based application operations."""
import hmac
import json
import os
import re
from pathlib import Path

from flask import Flask,abort,jsonify,redirect,render_template,request,send_file,session,url_for
from ai_lib_qor.application.minimal_file_index import build_index
from ai_lib_qor.sources.layout import evidence_path,library_folder
from ai_lib_qor.versions.store import write_atomic
from .jobs import JobManager


def _fmt_bytes(n):
    val = float(n)
    for unit in ('B', 'KB', 'MB', 'GB'):
        if val < 1024 or unit == 'GB':
            return f'{val:.1f} {unit}' if unit != 'B' else f'{int(val)} B'
        val /= 1024.0
    return f'{n} B'


def is_path_work(work):
    if not work:return False
    root=Path(work)
    for path in [*root.glob('libraries/*/*/delivery_*.json'),*root.glob('libraries/*/*/delivery/delivery_*.json')]:
        if path.is_symlink():continue
        try:
            data=json.loads(path.read_text(encoding='utf-8'))
            if set(data)=={'vendor','library','version','version_date','directory_created_at','root','views'} and not evidence_path(path).exists():return True
        except (OSError,ValueError,TypeError):continue
    return False


def create_path_app(work_root):
    work=Path(work_root).resolve(strict=True)
    if not work.is_dir():raise ValueError('工作目录不存在')
    app=Flask(__name__);app.secret_key=os.urandom(32)
    app.config.update(SESSION_COOKIE_HTTPONLY=True,SESSION_COOKIE_SAMESITE='Strict')
    jobs=JobManager(max_workers=2)
    app.extensions['jobs']=jobs

    @app.before_request
    def security():
        if request.remote_addr not in ('127.0.0.1','::1') or request.host.split(':',1)[0] not in ('localhost','127.0.0.1','['):abort(403)
        if 'csrf' not in session:session['csrf']=os.urandom(32).hex()
        token=request.form.get('csrf') or request.headers.get('X-CSRF-Token','')
        if request.method=='POST' and not hmac.compare_digest(session['csrf'],token):abort(403)

    def scope():
        vendor=request.values.get('vendor','');library=request.values.get('library','')
        try:folder=library_folder(work,vendor,library)
        except ValueError:abort(400)
        if not folder.is_dir():abort(404)
        return vendor,library,folder

    def index_state(vendor,library,folder):
        try:
            from ai_lib_qor.application.path_query import PathDataQuery
            return PathDataQuery(work).index(vendor,library),None
        except (OSError,ValueError,KeyError,TypeError) as exc:return None,str(exc)

    def source_config():
        from ai_lib_qor.application.path_config import load_path_config,update_options
        value=load_path_config(work)
        return {**value,**update_options(value)}

    @app.context_processor
    def common():
        lib_list = []
        try:
            for f in sorted((work/'libraries').glob('*/*')):
                if f.is_dir() and not f.is_symlink() and not f.parent.is_symlink():
                    lib_list.append({'vendor':f.parent.name, 'library':f.name})
        except OSError:
            pass
        return {'csrf':session.get('csrf'),'work_root':str(work),'notice':session.pop('path_notice',None),'all_libraries':lib_list}

    @app.get('/')
    def overview():
        from ai_lib_qor.application.path_refresh import refresh_status
        from ai_lib_qor.application.path_storage import storage_stats
        status=refresh_status(work,limit=8)
        libraries=[]
        for item in status['libraries']:
            err=None
            if item['index_status']=='MISSING':err='索引未生成，请刷新 L3'
            elif item['index_status']=='STALE':err='归档已更新，索引待刷新 (L3)'
            libraries.append({**item,'error':err})
        summary={'vendors':status['totals']['vendors'],
                 'libraries':status['totals']['libraries'],
                 'with_effective':status['totals']['libraries_with_effective'],
                 'accepted':sum(1 for x in libraries if x.get('accepted_revision')),
                 'revisions':status['totals']['revisions'],
                 'issues':sum(1 for x in libraries if x.get('error'))}
        try:
            st=storage_stats(work)
            storage_display={'total':_fmt_bytes(st['total_bytes']),'auth':_fmt_bytes(st['authoritative_bytes']),'cache':_fmt_bytes(st['rebuildable_cache_bytes'])}
        except (OSError,ValueError):
            storage_display=None
        return render_template('path_overview.html',libraries=libraries,config=source_config(),summary=summary,refresh_info=status,storage_display=storage_display)

    @app.get('/path/library')
    def library_page():
        vendor,library,folder=scope();index,error=index_state(vendor,library,folder)
        revision=request.args.get('revision','');baseline=request.args.get('baseline','')
        members=[];removed=[];delivery_rows=[];member_views=[]
        prev_rev=None;next_rev=None;baseline_rev=None;rev_idx=-1
        if index:
            if revision and revision not in index['revisions']:abort(400)
            if not revision and index['revisions']:revision=index['revisions'][-1]
            if revision:
                rev_idx=index['revisions'].index(revision)
                prev_rev=index['revisions'][rev_idx-1] if rev_idx>0 else None
                next_rev=index['revisions'][rev_idx+1] if rev_idx<len(index['revisions'])-1 else None
            if baseline == '__none__':
                baseline_rev = None
            elif baseline:
                if baseline not in index['revisions'] or index['revisions'].index(baseline)>=rev_idx:abort(400)
                baseline_rev = baseline
            else:baseline_rev = prev_rev

            for view,group in index['views'].items():
                for path,row in group.items():
                    for entry in row['effective']:
                        if entry['revision']==revision:
                            diff_status='NEW' if baseline_rev else 'CURRENT'
                            if baseline_rev:
                                prev_entry=next((e for e in row['effective'] if e['revision']==baseline_rev),None)
                                if prev_entry:
                                    diff_status='INHERITED' if prev_entry['version']==entry['version'] else 'UPDATED'
                            members.append({'view':view,'relative_path':path,'diff_status':diff_status,**entry})
                    old=next((e for e in row['effective'] if e['revision']==baseline_rev),None) if baseline_rev else None
                    if old and not any(e['revision']==revision for e in row['effective']):
                        removed.append({'view':view,'relative_path':path,**old})
            member_views=sorted({m['view'] for m in members}|{r['view'] for r in removed})
            diff_counts={
                'NEW':sum(1 for m in members if m['diff_status']=='NEW'),
                'UPDATED':sum(1 for m in members if m['diff_status']=='UPDATED'),
                'INHERITED':sum(1 for m in members if m['diff_status']=='INHERITED'),
                'REMOVED':len(removed),
            }
            diff_counts['CHANGED']=diff_counts['NEW']+diff_counts['UPDATED']+diff_counts['REMOVED']
            for delivery in index['deliveries']:
                kinds={};count=0
                for kind,group in index['views'].items():
                    for row in group.values():
                        if any(entry['version']==delivery['version'] for entry in row['raw']):
                            count+=1;kinds[kind]=kinds.get(kind,0)+1
                delivery_rows.append({**delivery,'file_count':count,'view_counts':kinds})
        else:
            diff_counts={'NEW':0,'UPDATED':0,'INHERITED':0,'REMOVED':0,'CHANGED':0}
        artifacts=[]
        for path in sorted([*folder.glob('check_run_*.json'),*(folder/'log').glob('check_rev_*_run_*.json')],key=lambda p:p.stat().st_mtime_ns,reverse=True):
            if path.is_symlink():continue
            try:
                d=json.loads(path.read_text(encoding='utf-8'))
                if d.get('schema_version')=='check_result.path.v1':
                    report=path.with_suffix('.xlsx').name if path.parent.name=='log' else 'report_'+d['run_id']+'.xlsx'
                    summary=d.get('summary',{})
                    failed_checks=summary.get('failed_checks',0)
                    inconclusive_checks=summary.get('inconclusive_checks',0)
                    failed_files=summary.get('failed_files',0)
                    run_state=d.get('state','UNKNOWN')
                    if failed_checks>0 or failed_files>0:
                        q_code,q_cls,q_text='FAIL','tag-failed','质检失败'
                    elif run_state!='SUCCEEDED' or inconclusive_checks>0:
                        q_code,q_cls,q_text='PARTIAL','tag-partial','部分覆盖 / 无结论'
                    else:
                        q_code,q_cls,q_text='SCOPE_PASS','tag-new','已覆盖范围通过'
                    facts_files=sorted({Path(f['facts']).name for f in d.get('files',[]) if f.get('facts')})
                    artifacts.append({
                        'kind':'SINGLE','name':report,'check':path.name,'revision':d['revision'],'baseline':d.get('baseline'),
                        'run_at':d.get('run_at',''),
                        'run_state':run_state,'quality_code':q_code,'quality_cls':q_cls,'quality_text':q_text,
                        'failed_checks':failed_checks,'inconclusive_checks':inconclusive_checks,'failed_files':failed_files,
                        'facts_files':facts_files,
                        'label':d['revision']+' · 运行 '+run_state+' · 失败 '+str(failed_checks)+' · 无结论 '+str(inconclusive_checks)+' · 文件失败 '+str(failed_files),
                        'excel_cached':(path.parent/report).is_file(),
                        'available':(path.parent/report).is_file() or path.parent.name=='log'
                    })
            except (OSError,ValueError,KeyError):continue
        for path in sorted([*folder.glob('overall_run_*.xlsx'),*(folder/'log').glob('overall_run_*.xlsx')],key=lambda p:p.stat().st_mtime_ns,reverse=True):
            if not path.is_symlink():artifacts.append({'kind':'OVERALL','name':path.name,'label':'整体报告 · '+path.name,'overall_json':path.with_suffix('.json').name if path.with_suffix('.json').is_file() and not path.with_suffix('.json').is_symlink() else None,'available':True})
        audit_available=any(p.is_file() and not p.is_symlink() for p in (folder/'effective_operations.tsv',folder/'log/effective_operations.tsv'))
        latest_check=None
        latest_path=folder/'latest_check.json'
        if latest_path.is_symlink():
            try:
                target=latest_path.resolve(strict=True)
                if target.is_relative_to(folder.resolve()) and target.is_file():
                    row=json.loads(target.read_text(encoding='utf-8'))
                    if (row.get('vendor'),row.get('library'))==(vendor,library):latest_check={'revision':row['revision'],'run_at':row['run_at'],'name':target.name}
            except (OSError,ValueError,KeyError):pass
        from ai_lib_qor.reporting.qor_views import latest_check_for_scope
        from ai_lib_qor.application.path_acceptance import acceptance_status
        matched_check=latest_check_for_scope(work,vendor,library,revision,baseline_rev) if index and revision else None
        if matched_check:
            fmap=matched_check['files']
            for m in members:
                info=fmap.get((m['view'],m['relative_path']))
                if info:m.update(info)
        try:acceptance=acceptance_status(work,vendor,library,limit=10)
        except (OSError,ValueError):acceptance=None
        return render_template('path_library.html',vendor=vendor,library=library,index=index,error=error,revision=revision,members=members,removed=removed,diff_counts=diff_counts,delivery_rows=delivery_rows,artifacts=artifacts,audit_available=audit_available,member_views=member_views,prev_rev=prev_rev,next_rev=next_rev,baseline_rev=baseline_rev,rev_idx=rev_idx,latest_check=latest_check,matched_check=matched_check,acceptance=acceptance)

    @app.get('/path/index')
    def index_page():
        vendor,library,folder=scope();index,error=index_state(vendor,library,folder)
        query=request.args.get('q','').strip();view=request.args.get('view','');delivery=request.args.get('delivery','');nl_version=request.args.get('nl_version','')
        adoption=request.args.get('adoption','');nl_rel=request.args.get('nl_rel','')
        rows=[];views=[];nl_versions=[]
        revision=request.args.get('revision','')
        if index:
            views=sorted(index['views'])
            nl_versions=sorted({n['nl_version'] for n in index['nl_snapshots']})
            if nl_version and nl_version not in nl_versions:abort(400)
            if not nl_version and index['nl_snapshots']:nl_version=index['nl_snapshots'][-1]['nl_version']
            latest=next((n for n in reversed(index['nl_snapshots']) if n['nl_version']==nl_version),None)
            if delivery and delivery not in [d['version'] for d in index['deliveries']]:abort(400)
            if view and view not in views:abort(400)
            if revision and revision not in index['revisions']:abort(400)
            if adoption not in ('','adopted','unadopted'):abort(400)
            if nl_rel not in ('','来源相同','来源不同','无法确认','无法对照'):abort(400)
            if not revision and index['revisions']:
                revision = index['revisions'][-1]
            for kind,group in index['views'].items():
                if view and kind!=view:continue
                for path,history in group.items():
                    if delivery and not any(r['version']==delivery for r in history['raw']):continue
                    if query:
                        hay=(kind+' '+path+' '+' '.join(r['version'] for r in history['raw'])).casefold()
                        if query.casefold() not in hay:continue
                    effective_in_rev = None
                    if revision:
                        effective_in_rev = next((e for e in history['effective'] if e['revision']==revision), None)
                    if adoption=='adopted' and not effective_in_rev:continue
                    if adoption=='unadopted' and effective_in_rev:continue
                    nl_latest=next((n for n in reversed(history['nl']) if latest and n['observed_at']==latest['observed_at'] and n['version']==latest['nl_version']),None)
                    nl_relation=('无法确认' if nl_latest and nl_latest['source_match']!='MATCHED_RAW' else
                                 '来源相同' if nl_latest and effective_in_rev and nl_latest['resolved_path']==effective_in_rev['path'] else
                                 '来源不同' if nl_latest and effective_in_rev else '无法对照')
                    if nl_rel and nl_relation!=nl_rel:continue
                    rows.append({'view':kind,'path':path,'effective_in_rev':effective_in_rev,'nl_latest':nl_latest,'nl_relation':nl_relation,**history})
        try:page=max(1,int(request.args.get('page','1')))
        except ValueError:abort(400)
        total=len(rows);pages=max(1,(total+79)//80);page=min(page,pages);rows=rows[(page-1)*80:page*80]
        return render_template('path_index.html',vendor=vendor,library=library,index=index,error=error,rows=rows,views=views,view=view,q=query,delivery=delivery,nl_version=nl_version,nl_versions=nl_versions,adoption=adoption,nl_rel=nl_rel,page=page,pages=pages,total=total,revision=revision)

    @app.post('/path/update')
    def update():
        from ai_lib_qor.sources.root_inventory import build_from_roots
        config=source_config();raw=request.form['raw_root'].strip() if 'raw_root' in request.form else config.get('raw_root','');nl=request.form['nl_root'].strip() if 'nl_root' in request.form else config.get('nl_root','')
        vendor=request.form.get('vendor') or None;library=request.form.get('library') or None
        opts={'update_raw':request.form.get('raw')=='1','update_formal':request.form.get('formal')=='1','update_index':request.form.get('index')=='1','auto_effective':request.form.get('auto_effective')=='1'}
        try:
            result=build_from_roots(raw or None,nl or None,work,nl_version=request.form.get('nl_version','').strip() or config.get('nl_version') or None,vendor=vendor,library=library,**opts)
            if request.form.get('save_settings')=='1':
                from ai_lib_qor.application.path_config import load_path_config
                from ai_lib_qor.versions.store import locked
                cp=work/'path_sources.json'
                if cp.is_symlink():raise ValueError('来源配置不能为软链接')
                with locked(work):
                    current=load_path_config(work)
                    write_atomic(cp,{**current,'raw_root':raw,'nl_root':nl,'nl_version':request.form.get('nl_version','').strip() or current.get('nl_version',''),**opts})
            session['path_notice']={'title':'更新完成' if not result['warnings'] else '更新完成，有项目需要处理','details':f"新增交付 {result['delivery_created']} · 新增快照 {result['formal_created']} · 更新索引 {result['indexes_updated']} · 新发布有效版本 {result['effective_published']} · 待处理交付 {result['effective_pending']} · 索引未刷新 {result['indexes_failed']}",'warnings':result['warnings'][:8]}
        except (OSError,ValueError,KeyError,TypeError) as exc:session['path_notice']={'title':'更新未完成','details':str(exc),'warnings':[]}
        return redirect(url_for('library_page',vendor=vendor,library=library) if vendor and library else url_for('overview'))

    @app.post('/path/refresh')
    def refresh_layer():
        from ai_lib_qor.application.path_refresh import refresh_all,refresh_l1,refresh_l2,refresh_l3
        layer=(request.form.get('layer') or 'all').lower()
        vendor=request.form.get('vendor') or None;library=request.form.get('library') or None
        config=source_config()
        raw=request.form['raw_root'].strip() if 'raw_root' in request.form else config.get('raw_root','')
        nl=request.form['nl_root'].strip() if 'nl_root' in request.form else config.get('nl_root','')
        nl_ver=request.form.get('nl_version','').strip() or config.get('nl_version') or None
        try:
            if layer=='l1':
                res=refresh_l1(work,raw or None,nl or None,nl_version=nl_ver,
                               raw=request.form.get('raw','1')=='1',formal=request.form.get('formal','1')=='1',
                               vendor=vendor,library=library,actor='web')
                title='L1 来源刷新完成' if not res['warnings'] else 'L1 来源刷新完成（有提示）'
                details=f"新增交付 {res['delivery_created']} · 已有未变 {res['delivery_unchanged']} · 新增快照 {res['formal_created']} · 变动库 {len(res['libraries_changed'])}"
            elif layer=='l2':
                res=refresh_l2(work,auto_init_from_formal=request.form.get('auto_init','1')=='1',
                               vendor=vendor,library=library,actor='web-auto')
                title='L2 有效版本推进完成' if not res['warnings'] else 'L2 有效版本推进完成（有待处理）'
                details=f"自动初始化 {res['initialized']} · 自动发布新版本 {res['effective_published']} · 无需变更 {res['unchanged']} · 待处理 {res['effective_pending']}"
            elif layer=='l3':
                res=refresh_l3(work,force_verify=request.form.get('force_verify')=='1',
                               vendor=vendor,library=library,actor='web')
                title='L3 索引刷新完成' if not res['warnings'] else 'L3 索引刷新完成（有异常）'
                details=f"更新索引 {res['indexes_updated']} · 未变 {res['indexes_unchanged']}（跳过重建 {res['indexes_skipped_rebuild']}）· 失败 {res['indexes_failed']}"
            elif layer=='all':
                res=refresh_all(work,raw or None,nl or None,nl_version=nl_ver,
                                raw=request.form.get('raw','1')=='1',formal=request.form.get('formal','1')=='1',
                                auto_init_from_formal=request.form.get('auto_init','1')=='1',
                                force_verify=request.form.get('force_verify')=='1',
                                vendor=vendor,library=library,actor='web')
                l1,l2,l3=res['l1'],res['l2'],res['l3']
                title='三层自动同步完成' if not res['warnings'] else '三层自动同步完成（有提示）'
                details=(f"L1 新增交付 {l1['delivery_created']}/快照 {l1['formal_created']} · "
                         f"L2 初始化 {l2['initialized']}/新版本 {l2['effective_published']} · "
                         f"L3 更新索引 {l3['indexes_updated']}/跳过重建 {l3['indexes_skipped_rebuild']}")
            else:
                raise ValueError('无效的刷新层级')
            session['path_notice']={'title':title,'details':details,'warnings':res['warnings'][:8]}
        except (OSError,ValueError,KeyError,TypeError) as exc:
            session['path_notice']={'title':'刷新未完成','details':str(exc),'warnings':[]}
        return redirect(url_for('library_page',vendor=vendor,library=library) if vendor and library else url_for('overview'))

    @app.post('/path/check')
    def check():
        from ai_lib_qor.application.minimal_checks import run_revision,run_library
        vendor,library,folder=scope();revision=request.form.get('revision','')
        baseline=request.form.get('baseline') or None
        lazy_excel=request.form.get('lazy_excel')=='1'
        try:
            result=run_library(work,vendor,library,rerun=request.form.get('rerun')=='1',render_single_excel=not lazy_excel) if request.form.get('kind')=='all' else run_revision(work,vendor,library,revision,baseline=baseline,render=not lazy_excel)
            aggregate=request.form.get('kind')=='all' and request.form.get('rerun')!='1'
            session['path_notice']={'title':('汇总已生成' if aggregate else ('检查已完成' if result['state']=='SUCCEEDED' else '检查部分完成')),'details':'报告已保存到本库，可在下方在线查看或按需导出 Excel。'+('未检查版本在报告中标为 NOT_CHECKED。' if aggregate else ''),'warnings':[]}
        except (OSError,ValueError,KeyError,TypeError) as exc:session['path_notice']={'title':'检查未完成','details':str(exc),'warnings':[]}
        params={'vendor':vendor,'library':library,'revision':revision}
        if baseline:params['baseline']=baseline
        return redirect(url_for('library_page',**params))

    @app.post('/path/facts')
    def facts():
        from ai_lib_qor.application.minimal_facts import build_facts
        vendor,library,folder=scope();view=request.form.get('view','');path=request.form.get('path','');revision=request.form.get('revision') or None;version=request.form.get('version') or None
        try:
            result=build_facts(work,vendor,library,view,path,revision=revision,version=version)
            session['path_notice']={'title':'文件事实已生成','details':Path(result['path']).name,'artifact':Path(result['path']).name,'warnings':[]}
        except (OSError,ValueError,KeyError,TypeError) as exc:session['path_notice']={'title':'未能生成文件事实','details':str(exc),'warnings':[]}
        return redirect(url_for('index_page',vendor=vendor,library=library))

    @app.post('/path/effective/preview')
    def effective_preview():
        from ai_lib_qor.application.minimal_effective import preview_update,restore_issues,_history
        from ai_lib_qor.application.path_query import PathDataQuery
        vendor,library,folder=scope();action=request.form.get('action')
        try:
            if action in ('set','remove','batch'):
                view=request.form.get('view','');path=request.form.get('path','')
                operations={'set':[],'remove':[]}
                if action=='set':operations['set'].append({'view':view,'path':path,'version':request.form.get('version','')})
                elif action=='remove':operations['remove'].append({'view':view,'path':path})
                else:
                    selected=request.form.getlist('selection')
                    for key in request.form:
                        if re.fullmatch(r'selection_\d+',key):
                            values=request.form.getlist(key)
                            if len(values)!=1:raise ValueError('每个文件只能选择一个操作')
                            if values[0]:selected.append(values[0])
                    if not selected or len(selected)>50 or sum(len(x.encode('utf-8')) for x in selected)>2000:raise ValueError('请选择 1 至 50 项，单次选择内容不超过 2000 字节')
                    for value in selected:
                        item=json.loads(value)
                        if not isinstance(item,dict):raise ValueError('文件选择无效')
                        if item.get('action')=='set' and set(item)=={'action','view','path','version'}:
                            operations['set'].append({k:item[k] for k in ('view','path','version')})
                        elif item.get('action')=='remove' and set(item)=={'action','view','path'}:
                            operations['remove'].append({k:item[k] for k in ('view','path')})
                        else:raise ValueError('文件选择无效')
                preview=preview_update(work,vendor,library,operations)
                draft={'vendor':vendor,'library':library,'action':action,'operations':operations,'parent':preview['parent']}
                changes=preview['changes'];issues=[]
            elif action=='restore':
                revision=request.form.get('revision','');query=PathDataQuery(work);index=query.index(vendor,library)
                if not index['revisions'] or revision not in index['revisions']:raise ValueError('有效版本不存在')
                parent=index['revisions'][-1]
                before=query.get_check_context(vendor,library,parent)['members']
                after=query.get_check_context(vendor,library,revision)['members']
                a={(x['view'],x['path']):x for x in before};b={(x['view'],x['path']):x for x in after}
                changes=[{'view':v,'path':p,'before':a.get((v,p),{}).get('version'),'after':b.get((v,p),{}).get('version')}
                         for v,p in sorted(a.keys()|b.keys()) if a.get((v,p),{}).get('version')!=b.get((v,p),{}).get('version')]
                target=next(row for _,_,row in _history(folder,library) if row['revision']==revision)
                issues=restore_issues(work,vendor,library,target['views'])
                draft={'vendor':vendor,'library':library,'action':action,'revision':revision,'parent':parent,'issues':issues}
            else:raise ValueError('操作类型无效')
            session['effective_draft']=draft
            return render_template('path_effective_preview.html',vendor=vendor,library=library,draft=draft,changes=changes,issues=issues,csrf=session['csrf'])
        except (OSError,ValueError,KeyError,TypeError) as exc:
            session.pop('effective_draft',None)
            session['path_notice']={'title':'无法预览','details':str(exc),'warnings':[]}
            return redirect(url_for('library_page',vendor=vendor,library=library))

    @app.post('/path/effective/apply')
    def effective_apply():
        from ai_lib_qor.application.minimal_effective import apply_update,restore_revision
        vendor,library,folder=scope();draft=session.pop('effective_draft',None)
        try:
            if not isinstance(draft,dict) or (draft.get('vendor'),draft.get('library'))!=(vendor,library):raise ValueError('预览已失效，请重新选择')
            if draft['action']=='restore':result=restore_revision(work,vendor,library,draft['revision'],expected_parent=draft['parent'],actor='web',expected_issues=draft['issues'])
            else:result=apply_update(work,vendor,library,draft['operations'],expected_parent=draft['parent'],actor='web')
            session['path_notice']={'title':'有效版本已处理','details':result['state']+' · '+result['revision'],'warnings':[result['index_error']] if result.get('index_error') else []}
        except (OSError,ValueError,KeyError,TypeError) as exc:
            session['path_notice']={'title':'发布未完成','details':str(exc),'warnings':[]}
        return redirect(url_for('library_page',vendor=vendor,library=library))

    @app.post('/path/acceptance')
    def acceptance_action():
        from ai_lib_qor.application.path_acceptance import accept_revision,rollback_acceptance
        vendor,library,folder=scope()
        action=request.form.get('action','accept')
        revision=request.form.get('revision','')
        reason=request.form.get('reason','')
        try:
            if action=='rollback':
                res=rollback_acceptance(work,vendor,library,revision,actor='web',reason=reason)
                session['path_notice']={'title':'人工采纳已回退','details':f"accepted_effective → {res['revision']}（原：{res.get('previous_accepted') or '无'}）",'warnings':[]}
            else:
                res=accept_revision(work,vendor,library,revision,actor='web',reason=reason)
                session['path_notice']={'title':'已记录人工采纳','details':f"accepted_effective → {res['revision']}（与最新计算版本指针分离）",'warnings':[]}
        except (OSError,ValueError,KeyError,TypeError) as exc:
            session['path_notice']={'title':'采纳未完成','details':str(exc),'warnings':[]}
        return redirect(url_for('library_page',vendor=vendor,library=library,revision=revision)+'#ops')

    @app.get('/path/check/view')
    def check_view_page():
        from ai_lib_qor.reporting.qor_views import build_check_view
        vendor,library,folder=scope();name=request.args.get('name','')
        try:view_data=build_check_view(work,vendor,library,name)
        except ValueError:abort(404)
        return render_template('path_analysis.html',mode='check',vendor=vendor,library=library,data=view_data)

    @app.get('/path/facts/view')
    def facts_view_page():
        from ai_lib_qor.reporting.qor_views import build_facts_view,load_fact_object,paginate_facts_view
        vendor,library,folder=scope()
        name=request.args.get('name','') or None
        check_name=request.args.get('check','') or None
        ref=request.args.get('ref','') or None
        try:
            fact,label,_=load_fact_object(work,vendor,library,name=name,check=check_name,ref=ref)
            entity_page=int(request.args.get('entity_page','1'))
            pin_page=int(request.args.get('pin_page','1'))
            per_page=int(request.args.get('per_page','100'))
        except ValueError:abort(404)
        raw_view=build_facts_view(fact,label=label)
        view_data=paginate_facts_view(
            raw_view,
            q=request.args.get('q',''),
            direction=request.args.get('direction',''),
            use=request.args.get('use',''),
            entity_page=entity_page,
            pin_page=pin_page,
            per_page=per_page,
        )
        return render_template('path_analysis.html',mode='facts',vendor=vendor,library=library,data=view_data,check_name=check_name,fact_ref=ref,fact_name=name)

    @app.get('/path/facts/compare')
    def facts_compare_page():
        from ai_lib_qor.reporting.qor_views import build_facts_diff,load_fact_object,paginate_facts_diff
        vendor,library,folder=scope()
        check_name=request.args.get('check','') or None
        old_ref=request.args.get('old','') or None
        new_ref=request.args.get('new','') or None
        if not old_ref or not new_ref:abort(400)
        try:
            old_fact,old_label,_=load_fact_object(work,vendor,library,name=None if check_name else old_ref,check=check_name,ref=old_ref if check_name else None)
            new_fact,new_label,_=load_fact_object(work,vendor,library,name=None if check_name else new_ref,check=check_name,ref=new_ref if check_name else None)
            raw_diff=build_facts_diff(old_fact,new_fact,old_label=old_label,new_label=new_label)
            pin_page=int(request.args.get('pin_page','1'))
            per_page=int(request.args.get('per_page','100'))
        except ValueError:abort(404)
        diff=paginate_facts_diff(
            raw_diff,
            q=request.args.get('q',''),
            status=request.args.get('status','auto'),
            pin_page=pin_page,
            per_page=per_page,
        )
        return render_template('path_analysis.html',mode='compare',vendor=vendor,library=library,data=diff,check_name=check_name,old_ref=old_ref,new_ref=new_ref)

    @app.get('/path/facts/download')
    def facts_download():
        from io import BytesIO
        from ai_lib_qor.reporting.qor_views import load_fact_object
        vendor,library,folder=scope()
        name=request.args.get('name','') or None
        check_name=request.args.get('check','') or None
        ref=request.args.get('ref','') or None
        try:fact,label,_=load_fact_object(work,vendor,library,name=name,check=check_name,ref=ref)
        except ValueError:abort(404)
        filename=label if label.endswith('.json') else label+'.json'
        payload=json.dumps(fact,ensure_ascii=False,indent=2).encode('utf-8')
        return send_file(BytesIO(payload),mimetype='application/json',as_attachment=True,download_name=filename)

    # --- Read-Only JSON API (/api/v1/*) ---
    @app.get('/api/v1/overview')
    def api_overview():
        from ai_lib_qor.application.path_refresh import refresh_status
        from ai_lib_qor.application.path_storage import storage_stats
        return jsonify({'refresh':refresh_status(work,limit=10),'storage':storage_stats(work)})

    @app.get('/api/v1/storage')
    def api_storage():
        from ai_lib_qor.application.path_storage import storage_stats
        v=request.args.get('vendor') or None;lib=request.args.get('library') or None
        try:return jsonify(storage_stats(work,vendor=v,library=lib))
        except ValueError as exc:return jsonify({'error':str(exc)}),400

    @app.get('/api/v1/library')
    def api_library():
        from ai_lib_qor.application.path_acceptance import acceptance_status
        from ai_lib_qor.application.path_query import PathDataQuery
        vendor,library,folder=scope()
        revision=request.args.get('revision') or None
        baseline=request.args.get('baseline') or None
        try:
            index=PathDataQuery(work).index(vendor,library)
            rev=revision or (index['revisions'][-1] if index['revisions'] else None)
            ctx=PathDataQuery(work).get_check_context(vendor,library,rev,baseline=baseline) if rev else None
            acc=acceptance_status(work,vendor,library,limit=10)
            return jsonify({
                'vendor':vendor,'library':library,'revisions':index['revisions'],'deliveries':index['deliveries'],
                'acceptance':acc,
                'context':{k:v for k,v in ctx.items() if k!='index'} if ctx else None,
            })
        except ValueError as exc:
            return jsonify({'error':str(exc)}),400

    @app.get('/api/v1/check')
    def api_check():
        from ai_lib_qor.reporting.qor_views import build_check_view
        vendor,library,folder=scope();name=request.args.get('name','')
        try:return jsonify(build_check_view(work,vendor,library,name))
        except ValueError as exc:return jsonify({'error':str(exc)}),404

    @app.get('/api/v1/facts')
    def api_facts():
        from ai_lib_qor.reporting.qor_views import build_facts_view,load_fact_object,paginate_facts_view
        vendor,library,folder=scope()
        name=request.args.get('name','') or None
        check_name=request.args.get('check','') or None
        ref=request.args.get('ref','') or None
        try:
            fact,label,_=load_fact_object(work,vendor,library,name=name,check=check_name,ref=ref)
            raw_view=build_facts_view(fact,label=label)
            paged=paginate_facts_view(
                raw_view,
                q=request.args.get('q',''),
                direction=request.args.get('direction',''),
                use=request.args.get('use',''),
                entity_page=int(request.args.get('entity_page','1')),
                pin_page=int(request.args.get('pin_page','1')),
                per_page=int(request.args.get('per_page','100')),
            )
            return jsonify(paged)
        except ValueError as exc:return jsonify({'error':str(exc)}),404

    # --- Async Background Jobs API (/api/v1/jobs/*) ---
    @app.post('/api/v1/jobs/refresh')
    def api_job_refresh():
        from ai_lib_qor.application.path_refresh import refresh_all,refresh_l1,refresh_l2,refresh_l3
        layer=(request.form.get('layer') or 'all').lower()
        vendor=request.form.get('vendor') or None;library=request.form.get('library') or None
        if bool(vendor)!=bool(library):return jsonify({'error':'vendor 和 library 必须同时指定'}),400
        if vendor:
            try:library_folder(work,vendor,library)
            except ValueError as exc:return jsonify({'error':str(exc)}),400
        config=source_config()
        raw=request.form['raw_root'].strip() if 'raw_root' in request.form else config.get('raw_root','')
        nl=request.form['nl_root'].strip() if 'nl_root' in request.form else config.get('nl_root','')
        nl_ver=request.form.get('nl_version','').strip() or config.get('nl_version') or None
        raw_flag=request.form.get('raw','1')=='1'
        formal_flag=request.form.get('formal','1')=='1'
        auto_init=request.form.get('auto_init','1')=='1'
        force_verify=request.form.get('force_verify')=='1'
        verify_raw=request.form.get('verify_raw')=='1'
        if layer=='l1':
            fn=lambda cb,ev:refresh_l1(work,raw or None,nl or None,nl_version=nl_ver,raw=raw_flag,formal=formal_flag,verify_raw=verify_raw,vendor=vendor,library=library,actor='web-async',progress_cb=cb,cancel_event=ev)
        elif layer=='l2':
            fn=lambda cb,ev:refresh_l2(work,auto_init_from_formal=auto_init,vendor=vendor,library=library,actor='web-async',progress_cb=cb,cancel_event=ev)
        elif layer=='l3':
            fn=lambda cb,ev:refresh_l3(work,force_verify=force_verify,vendor=vendor,library=library,actor='web-async',progress_cb=cb,cancel_event=ev)
        elif layer=='all':
            fn=lambda cb,ev:refresh_all(work,raw or None,nl or None,nl_version=nl_ver,raw=raw_flag,formal=formal_flag,auto_init_from_formal=auto_init,force_verify=force_verify,verify_raw=verify_raw,vendor=vendor,library=library,actor='web-async',progress_cb=cb,cancel_event=ev)
        else:
            return jsonify({'error':'无效的刷新层级'}),400
        job=jobs.submit('refresh',f'刷新 {layer.upper()}'+(f' ({vendor}/{library})' if vendor else ''),fn)
        return jsonify(job),202

    @app.post('/api/v1/jobs/check')
    def api_job_check():
        from ai_lib_qor.application.minimal_checks import run_library,run_revision
        from ai_lib_qor.application.path_batch import check_pending
        kind=request.form.get('kind','single')
        lazy_excel=request.form.get('lazy_excel','1')=='1'
        if kind=='pending':
            v=request.form.get('vendor') or None;lib=request.form.get('library') or None
            if bool(v)!=bool(lib):return jsonify({'error':'vendor 和 library 必须同时指定'}),400
            rerun_flag=request.form.get('rerun')=='1'
            fn=lambda cb,ev:check_pending(work,vendor=v,library=lib,render_excel=not lazy_excel,rerun=rerun_flag,progress_cb=cb,cancel_event=ev)
            job=jobs.submit('check_pending','增量检查待检库',fn)
            return jsonify(job),202
        vendor,library,folder=scope()
        revision=request.form.get('revision','')
        baseline=request.form.get('baseline') or None
        if kind=='all':
            rerun=request.form.get('rerun')=='1'
            fn=lambda cb,ev:run_library(work,vendor,library,rerun=rerun,render_single_excel=not lazy_excel,progress_cb=cb,cancel_event=ev)
            job=jobs.submit('check_library',f'库级检查 {vendor}/{library}',fn)
            return jsonify(job),202
        fn=lambda cb,ev:run_revision(work,vendor,library,revision,baseline=baseline,render=not lazy_excel,progress_cb=cb,cancel_event=ev)
        job=jobs.submit('check_revision',f'单版本检查 {vendor}/{library} {revision}',fn)
        return jsonify(job),202

    @app.get('/api/v1/jobs')
    def api_jobs_list():
        return jsonify({'jobs':jobs.list_recent(limit=20)})

    @app.get('/api/v1/jobs/<job_id>')
    def api_job_status(job_id):
        job=jobs.get(job_id)
        if not job:abort(404)
        return jsonify(job)

    @app.post('/api/v1/jobs/<job_id>/cancel')
    def api_job_cancel(job_id):
        job=jobs.cancel(job_id)
        if not job:abort(404)
        return jsonify(job)

    @app.get('/path/artifact')
    def artifact():
        vendor,library,folder=scope();name=request.args.get('name','')
        if not re.fullmatch(r'(?:report_run_[a-f0-9]{32}\.xlsx|overall_run_[a-f0-9]{32}\.(?:xlsx|json)|check_run_[a-f0-9]{32}\.json|check_rev_[0-9]+_run_[a-f0-9]{32}\.(?:xlsx|json)|facts_[A-Z]+_[A-Za-z0-9_]+\.json|file_index\.json|effective_operations\.tsv|file_index_reconciliation\.tsv|formal_observations\.tsv)',name):abort(400)
        if (folder/'log').is_symlink():abort(400)
        path=folder/'log'/name if (folder/'log'/name).is_file() else folder/name
        if not path.is_file() and re.fullmatch(r'check_rev_[0-9]+_run_[a-f0-9]{32}\.xlsx',name):
            json_path=folder/'log'/(Path(name).stem+'.json')
            target_xlsx=folder/'log'/name
            if json_path.is_file() and not json_path.is_symlink() and not target_xlsx.is_symlink():
                from ai_lib_qor.application.minimal_checks import render_excel_from_check
                try:
                    if not target_xlsx.is_file():
                        render_excel_from_check(work,vendor,library,json_path.name,target_xlsx)
                except (OSError,ValueError,KeyError,TypeError):abort(404)
                path=target_xlsx
        if not path.is_file() and name=='formal_observations.tsv' and (work/name).is_file():
            path=work/name
        if path.is_symlink() or not path.is_file():abort(404)
        return send_file(path,as_attachment=True,download_name=name)

    return app
