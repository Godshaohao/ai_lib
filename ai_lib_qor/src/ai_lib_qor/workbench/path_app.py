"""Local three-level workbench over path-based application operations."""
import hmac
import json
import os
import re
from pathlib import Path

from flask import Flask,abort,redirect,render_template,request,send_file,session,url_for
from ai_lib_qor.application.minimal_file_index import build_index
from ai_lib_qor.sources.layout import evidence_path,library_folder
from ai_lib_qor.versions.store import write_atomic


def is_path_work(work):
    if not work:return False
    root=Path(work)
    for path in root.glob('libraries/*/*/delivery_*.json'):
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

    @app.before_request
    def security():
        if request.remote_addr not in ('127.0.0.1','::1') or request.host.split(':',1)[0] not in ('localhost','127.0.0.1','['):abort(403)
        if 'csrf' not in session:session['csrf']=os.urandom(32).hex()
        if request.method=='POST' and not hmac.compare_digest(session['csrf'],request.form.get('csrf','')):abort(403)

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
        return {'csrf':session.get('csrf'),'work_root':str(work),'notice':session.pop('path_notice',None)}

    @app.get('/')
    def overview():
        libraries=[]
        for folder in sorted((work/'libraries').glob('*/*')):
            if not folder.is_dir() or folder.is_symlink() or folder.parent.is_symlink():continue
            vendor,library=folder.parent.name,folder.name
            index,error=index_state(vendor,library,folder)
            libraries.append({'vendor':vendor,'library':library,'delivery_count':len(index['deliveries']) if index else None,
                              'revision_count':len(index['revisions']) if index else None,'error':error})
        return render_template('path_workbench.html',level=1,libraries=libraries,config=source_config())

    @app.get('/path/library')
    def library_page():
        vendor,library,folder=scope();index,error=index_state(vendor,library,folder)
        revision=request.args.get('revision','');members=[];delivery_rows=[]
        if index:
            if revision and revision not in index['revisions']:abort(400)
            if not revision and index['revisions']:revision=index['revisions'][-1]
            for view,group in index['views'].items():
                for path,row in group.items():
                    for entry in row['effective']:
                        if entry['revision']==revision:members.append({'view':view,'relative_path':path,**entry})
            for delivery in index['deliveries']:
                kinds={};count=0
                for kind,group in index['views'].items():
                    for row in group.values():
                        if any(entry['version']==delivery['version'] for entry in row['raw']):
                            count+=1;kinds[kind]=kinds.get(kind,0)+1
                delivery_rows.append({**delivery,'file_count':count,'view_counts':kinds})
        artifacts=[]
        for path in sorted(folder.glob('check_run_*.json'),key=lambda p:p.stat().st_mtime_ns,reverse=True)[:20]:
            if path.is_symlink():continue
            try:
                d=json.loads(path.read_text(encoding='utf-8'))
                if d.get('schema_version')=='check_result.path.v1':
                    report='report_'+d['run_id']+'.xlsx'
                    artifacts.append({'name':report,'check':path.name,'label':d['revision']+' · '+d['state'],'available':(folder/report).is_file()})
            except (OSError,ValueError,KeyError):continue
        for path in sorted(folder.glob('overall_run_*.xlsx'),key=lambda p:p.stat().st_mtime_ns,reverse=True)[:10]:
            if not path.is_symlink():artifacts.append({'name':path.name,'label':'整体报告 · '+path.name,'available':True})
        audit_available=(folder/'effective_operations.tsv').is_file() and not (folder/'effective_operations.tsv').is_symlink()
        return render_template('path_workbench.html',level=2,vendor=vendor,library=library,index=index,error=error,revision=revision,members=members,delivery_rows=delivery_rows,artifacts=artifacts,audit_available=audit_available)

    @app.get('/path/index')
    def index_page():
        vendor,library,folder=scope();index,error=index_state(vendor,library,folder)
        query=request.args.get('q','').strip();view=request.args.get('view','');rows=[];views=[]
        if index:
            views=sorted(index['views'])
            if view and view not in views:abort(400)
            for kind,group in index['views'].items():
                if view and kind!=view:continue
                for path,history in group.items():
                    if query and query.casefold() not in (kind+' '+path).casefold():continue
                    rows.append({'view':kind,'path':path,**history})
        try:page=max(1,int(request.args.get('page','1')))
        except ValueError:abort(400)
        total=len(rows);pages=max(1,(total+79)//80);page=min(page,pages);rows=rows[(page-1)*80:page*80]
        return render_template('path_workbench.html',level=3,vendor=vendor,library=library,index=index,error=error,rows=rows,views=views,view=view,q=query,page=page,pages=pages,total=total)

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

    @app.post('/path/check')
    def check():
        from ai_lib_qor.application.minimal_checks import run_revision,run_library
        vendor,library,folder=scope();revision=request.form.get('revision','')
        try:
            result=run_library(work,vendor,library) if request.form.get('kind')=='all' else run_revision(work,vendor,library,revision)
            session['path_notice']={'title':'检查已完成' if result['state']=='SUCCEEDED' else '检查部分完成','details':'报告已保存到本库，可在下方下载。','warnings':[]}
        except (OSError,ValueError,KeyError,TypeError) as exc:session['path_notice']={'title':'检查未完成','details':str(exc),'warnings':[]}
        return redirect(url_for('library_page',vendor=vendor,library=library,revision=revision))

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

    @app.get('/path/artifact')
    def artifact():
        vendor,library,folder=scope();name=request.args.get('name','')
        if not re.fullmatch(r'(?:report_run_[a-f0-9]{32}\.xlsx|overall_run_[a-f0-9]{32}\.(?:xlsx|json)|check_run_[a-f0-9]{32}\.json|facts_[A-Z]+_[A-Za-z0-9_]+\.json|file_index\.json|effective_operations\.tsv|file_index_reconciliation\.tsv|formal_observations\.tsv)',name):abort(400)
        path=folder/name
        if path.is_symlink() or not path.is_file():abort(404)
        return send_file(path,as_attachment=True,download_name=name)

    return app
