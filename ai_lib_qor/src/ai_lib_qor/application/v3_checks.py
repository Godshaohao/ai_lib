"""Explicit v3-index checks with per-version and shared overall results."""
import json
import uuid
import hashlib
from datetime import datetime, timezone
from pathlib import Path

from ai_lib_qor.application.data_query import LibraryDataQuery, _view
from ai_lib_qor.application.pipeline import render_report
from ai_lib_qor.application.library_runs import append_status, paths as library_paths
from ai_lib_qor.checks.assembler import build_check_result
from ai_lib_qor.facts.parsers import parse_delivery_file
from ai_lib_qor.reporting.overall_excel import render_overall_excel
from ai_lib_qor.sources.layout import library_folder
from ai_lib_qor.versions.store import write_atomic


def _now():return datetime.now(timezone.utc).isoformat()


from ai_lib_qor.application.source_repository import archive_fingerprint as _archive_fingerprint


def _setup(work,runs,vendor,library,set_id,profile,*,require_ip=False):
    if not isinstance(profile,dict) or set(profile)!={'pin_pairs'} or not isinstance(profile['pin_pairs'],list) or not profile['pin_pairs']:
        raise ValueError('检查配置必须包含至少一个明确的 LEF/Liberty 文件路径对')
    pairs=profile['pin_pairs']
    if any(not isinstance(p,dict) or set(p)!={'lef_path','liberty_path'} or not all(isinstance(x,str) and x for x in p.values()) for p in pairs):
        raise ValueError('检查配置中的路径对无效')
    if len({(p['lef_path'],p['liberty_path']) for p in pairs})!=len(pairs):raise ValueError('检查配置中存在重复路径对')
    before=_archive_fingerprint(work);q=LibraryDataQuery(work,runs);root=Path(runs).resolve()
    output_folder=library_folder(work,vendor,library)
    for p in [*[Path(x['record']['source_root']) for x in q.deliveries],*[Path(x['source_root']) for x in q.snapshots]]:
        if p.is_absolute() and (root.is_relative_to(p.resolve()) or output_folder.is_relative_to(p.resolve())):raise ValueError('运行目录不能位于 RAW 或 Formal 来源目录')
    status=q.file_index_status(vendor,library)
    if status['status']!='VALID':raise ValueError('v3 索引不可用：'+status['message'])
    index=q.published_v3_index(vendor,library)
    effective=index['effective_sets'].get(set_id)
    if not effective:raise ValueError('有效集不在索引中')
    if require_ip and effective['owner']['type']!='BUSINESS_IP':raise ValueError('整体 IP 报告需要 BUSINESS_IP 有效集')
    if before!=_archive_fingerprint(work):raise ValueError('检查准备期间归档发生变化')
    q._check_archive_fingerprint=before
    return q,index,effective,root


def _source(q,index,set_id,revision,view,path):
    node=index['views'].get(view,{}).get('files',{}).get(path)
    rows=[x for x in (node or {}).get('effective',{}).get(set_id,[]) if x['revision']==revision]
    if len(rows)!=1:raise ValueError(f'{revision}: {view}/{path} 不在有效集合或来源不唯一')
    row=rows[0];scope=row.get('source_scope',index['scope']);source_path=row.get('source_path',path)
    matches=[x for x in q.deliveries if (x['record']['vendor_id'],x['record']['source_library_id'],x['record']['delivery_id'])==
             (scope['vendor'],scope['library'],row['delivery_id'])]
    if len(matches)!=1:raise ValueError(f'{revision}: 交付记录不存在或不唯一')
    item=matches[0];files=[f for f in item['files'] if f['relative_path']==source_path and _view(f['view'],source_path)==view]
    if len(files)!=1 or files[0]['classification']!='RESOLVED' or files[0]['identity_status']!='CONFIRMED' or not files[0].get('file_key'):
        raise ValueError(f'{revision}: {view}/{source_path} 文件身份未明确确认')
    f=files[0];ref=(scope['library'],row['delivery_id'],f['file_id'])
    if len(q._refs[ref])!=1:raise ValueError('旧 FileFacts 引用跨供应商不唯一')
    return {'record':item['record'],'record_path':item['path'],'file':f,'path':source_path,'scope':scope}


def _fact(source,cache,stats,facts_root):
    record=source['record'];f=source['file'];root=Path(record['source_root']).resolve()
    path=(root/source['path']).resolve()
    if not path.is_relative_to(root) or not path.is_file():raise ValueError('选中的 RAW 文件不存在或路径越界')
    st=path.stat();fingerprint=(st.st_dev,st.st_ino,st.st_size,st.st_mtime_ns,st.st_ctime_ns)
    observed=f.get('observation') or {}
    has_observation='size' in observed and 'mtime_ns' in observed
    if has_observation:
        if (st.st_size,st.st_mtime_ns)!=(observed['size'],observed['mtime_ns']):
            raise ValueError('RAW 文件与交付时记录的大小或时间不一致，不能重现原交付')
    else:
        stats['unverified']+=1
    key=(record['vendor_id'],record['source_library_id'],record['delivery_id'],f['file_id'])
    if key in cache and cache[key][0]==fingerprint:
        stats.setdefault('paths',{})[cache[key][1]['facts_id']]=cache[key][2]
        stats['reused']+=1;return cache[key][1]
    from ai_lib_qor.facts.parsers import _file_digest,ADAPTER_VERSION,LEF_PARSER_VERSION,LIBERTY_PARSER_VERSION
    from ai_lib_qor.versions.store import validate
    parsers={'LEF':{'name':'src_qor_lef','version':f'{LEF_PARSER_VERSION}+adapter-{ADAPTER_VERSION}'},
             'LIBERTY':{'name':'src_qor_liberty_interface','version':f'{LIBERTY_PARSER_VERSION}+adapter-{ADAPTER_VERSION}'}}
    parser=parsers.get(f['view'])
    if not parser:raise ValueError('不支持的事实解析类型')
    digest=_file_digest(path);observed_stat=path.stat()
    if fingerprint!=(observed_stat.st_dev,observed_stat.st_ino,observed_stat.st_size,observed_stat.st_mtime_ns,observed_stat.st_ctime_ns):raise ValueError('文件读取期间发生变化')
    ref={'kind':'delivery_file','source_library_id':record['source_library_id'],'delivery_id':record['delivery_id'],'file_id':f['file_id']}
    canonical=lambda value:json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=True).encode()
    expected_id='facts_'+hashlib.sha256(canonical({'source_ref':ref,'digest':digest,'parser':parser})).hexdigest()[:24]
    cache_key=hashlib.sha256(canonical({'scope':[record['vendor_id'],record['source_library_id']],'ref':ref,'digest':digest,'parser':parser})).hexdigest()[:24]
    root=Path(facts_root)
    for candidate in sorted(root.glob('facts_'+cache_key+'_*.json')) if has_observation else ():
        if candidate.is_symlink():continue
        try:
            cached=json.loads(candidate.read_text(encoding='utf-8'));validate(cached,'file_facts')
            content_hash=hashlib.sha256(canonical(cached)).hexdigest()[:24]
            if candidate.name!='facts_'+cache_key+'_'+content_hash+'.json' or cached['facts_id']!=expected_id or cached['source_ref']!=ref or cached['parser']!=parser:continue
            current=path.stat()
            if fingerprint!=(current.st_dev,current.st_ino,current.st_size,current.st_mtime_ns,current.st_ctime_ns):raise ValueError('复用事实时来源文件发生变化')
            cache[key]=(fingerprint,cached,candidate);stats.setdefault('paths',{})[cached['facts_id']]=candidate;stats['reused']+=1;return cached
        except (OSError,KeyError,TypeError,json.JSONDecodeError):continue
    result=parse_delivery_file(record,f['file_id']);after=path.stat()
    if fingerprint!=(after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns,after.st_ctime_ns):
        raise ValueError('文件解析期间发生变化')
    if result['facts_id']!=expected_id or result['parser']!=parser:raise ValueError('解析事实与读取的来源不一致')
    content_hash=hashlib.sha256(canonical(result)).hexdigest()[:24]
    cache_path=root/('facts_'+cache_key+'_'+content_hash+'.json')
    try:write_atomic(cache_path,result,immutable=True)
    except FileExistsError:
        if cache_path.is_symlink() or json.loads(cache_path.read_text(encoding='utf-8'))!=result:raise ValueError('缓存事实发生冲突')
    cache[key]=(fingerprint,result,cache_path);stats.setdefault('paths',{})[result['facts_id']]=cache_path;stats['parsed']+=1;return result


def _source_comparison(index,set_id,parent,revision):
    if not parent:return None
    rows=[]
    for view,group in index['views'].items():
        for path,node in group['files'].items():
            entries=node.get('effective',{}).get(set_id,[])
            def pick(rev):
                found=[x for x in entries if x['revision']==rev]
                if len(found)>1:raise ValueError('版本来源记录重复')
                if not found:return None
                item=found[0];return {'delivery_id':item['delivery_id'],'scope':item.get('source_scope',index['scope']),'path':item.get('source_path',path)}
            old,new=pick(parent),pick(revision)
            if old is None and new is None:continue
            change='ADDED' if old is None else 'REMOVED' if new is None else 'UNCHANGED' if old==new else 'SOURCE_CHANGED'
            rows.append({'view':view,'path':path,'change':change,'before':old,'after':new,'content_status':'NOT_CHECKED'})
    return {'from':parent,'to':revision,'meaning':'SOURCE_ONLY','files':rows,
            'summary':{key:sum(x['change']==key for x in rows) for key in ('SOURCE_CHANGED','ADDED','REMOVED','UNCHANGED')}}


def _run_revision(q,index,effective,root,vendor,library,set_id,revision,profile,cache,stats,progress=None):
    revs={x['revision']:x for x in effective['revisions']}
    if revision not in revs:raise ValueError('所选版本不在有效集')
    parent=revs[revision]['parent'];folder=library_folder(q.work,vendor,library);ident='run_'+uuid.uuid4().hex;artifacts=library_paths(folder,ident)
    status={'id':ident,'state':'RUNNING','plan':'v3 索引范围检查','target':revision,'target_kind':'EFFECTIVE_REVISION',
            'set_id':set_id,'baseline':parent,'profile':profile,'output_directory':str(folder),'owner':{'vendor':vendor,'library':library,'ip':effective['owner']['id']},'started_at':_now()}
    append_status(folder,status)
    try:
        if q._check_archive_fingerprint!=_archive_fingerprint(q.work):raise ValueError('检查开始前归档发生变化')
        unverified_before=stats['unverified']
        if progress:progress(f'{revision}：读取索引并解析所选文件')
        pairs=[];comparisons=[];target_members={};baseline_members={};facts=[];sources=[];seen_lef=set()
        context=q.get_check_context(vendor,library,set_id,revision,baseline=parent)
        logical=context['logical_matches']
        if context['unresolved']:raise ValueError('检查上下文包含无法定位的来源：'+str(context['unresolved']))
        snapshot={'baseline_revision':parent,'selection_rule':'V3_INDEX_EXPLICIT_PAIRS',
                  'pairs':profile['pin_pairs'],'target_files':[],'baseline_files':[],'facts_ids':[]}
        status['execution_snapshot']=snapshot
        def record_selection(source,view,selected_revision,role):
            row={'vendor':source['scope']['vendor'],'library':source['scope']['library'],
                 'delivery_id':source['record']['delivery_id'],'file_id':source['file']['file_id'],
                 'view':view,'source_relative_path':source['path'],'revision':selected_revision}
            if row not in snapshot[role]:snapshot[role].append(row)
        def record_fact(source):
            value=_fact(source,cache,stats,library_folder(q.work,vendor,library));facts.append(value);sources.append(source['record_path'])
            if value['facts_id'] not in snapshot['facts_ids']:snapshot['facts_ids'].append(value['facts_id'])
            return value
        for spec in profile['pin_pairs']:
            for view,path in (('LEF',spec['lef_path']),('LIBERTY',spec['liberty_path'])):
                if sum(1 for row in context['selected_files'] if (row['view'],row['effective_path'])==(view,path))!=1:
                    raise ValueError('所选检查文件不在完整有效版本中或不唯一')
            lef=_source(q,index,set_id,revision,'LEF',spec['lef_path'])
            lib=_source(q,index,set_id,revision,'LIBERTY',spec['liberty_path'])
            record_selection(lef,'LEF',revision,'target_files');record_selection(lib,'LIBERTY',revision,'target_files')
            lk=lef['file']['file_key'];bk=lib['file']['file_key']
            if lk==bk:raise ValueError('LEF 和 Liberty 的文件身份冲突')
            lf=record_fact(lef);bf=record_fact(lib)
            for key,ref in ((lk,lf['source_ref']),(bk,bf['source_ref'])):
                if key in target_members and target_members[key]!=ref:raise ValueError('目标文件身份不唯一')
                target_members[key]=ref
            pairs.append({'lef_key':lk,'liberty_key':bk,'lef':lf,'liberty':bf})
            if parent and lk not in seen_lef:
                matches=[x for x in logical if x.get('after') and x['after']['view']=='LEF' and x['after']['path']==spec['lef_path']]
                if len(matches)!=1:raise ValueError('无法唯一确定目标 LEF 与基线的关系')
                prior=matches[0].get('before')
                if prior:
                    old=_source(q,index,set_id,parent,'LEF',prior['path'])
                    if old['file']['file_key']!=lk:raise ValueError('新旧 LEF 身份不同，不能作为同一对象比较')
                    record_selection(old,'LEF',parent,'baseline_files')
                    old_fact=record_fact(old);baseline_members[lk]=old_fact['source_ref']
                    comparisons.append({'file_key':lk,'old':old_fact,'new':lf})
                seen_lef.add(lk)
        if q._check_archive_fingerprint!=_archive_fingerprint(q.work):raise ValueError('检查期间归档发生变化')
        plan={'kind':'V3_INDEX_EXPLICIT_PAIRS','vendor':vendor,'library':library,'set_id':set_id,
              'revision':revision,'parent':parent,'profile':profile,'index_schema':index['schema'],
              'source_comparison':_source_comparison(index,set_id,parent,revision)}
        result=build_check_result(target={'kind':'EFFECTIVE_REVISION','id':revision},
            baseline={'kind':'EFFECTIVE_REVISION','id':parent} if parent else None,effective_set_id=set_id,
            run_id=status['id'],ruleset_id='v3_index_explicit_pairs',run_at=status['started_at'],
            comparisons=comparisons,pin_pairs=pairs,target_members=target_members,baseline_members=baseline_members,
            plugin_ids=['LEF_MACRO_DIFF','LEF_LIBERTY_PIN_MATCH'])
        result['evidence_note']='仅比较所选 LEF 的 Macro SIZE、Pin，并检查目标版本 LEF/Liberty 信号 Pin 对齐；不比较新旧 Liberty 内容。未覆盖的文件和检查不代表通过，检查不等于采纳。'
        if stats['unverified']>unverified_before:result['evidence_note']+=' 部分来源缺少交付时文件元信息，无法确认当前内容与历史交付一致。'
        else:result['evidence_note']+=' 已核对交付时文件元信息；大小和时间一致不证明历史内容一致。'
        fact_paths=[]
        for fact in facts:
            path=stats['paths'][fact['facts_id']]
            if path not in fact_paths:fact_paths.append(path)
        status['facts_files']=[p.name for p in fact_paths]
        write_atomic(artifacts['check.json'],result,immutable=True)
        render_report(str(artifacts['check.json']),html=str(artifacts['report.html']),excel=str(artifacts['report.xlsx']),
                      facts=[str(p) for p in fact_paths],delivery=list(dict.fromkeys(sources)),library_index=index,
                      source_comparison=plan['source_comparison'])
        status.update(state='SUCCEEDED',summary=result['summary'],source_summary=(plan['source_comparison'] or {}).get('summary'))
        if progress:progress(f'{revision}：检查和单版本报告已生成')
    except Exception as exc:
        status.update(state='FAILED',error=f'{type(exc).__name__}: {exc}')
        if progress:progress(f"{revision}：{status['error']}")
    status['artifact_files']=[p.name for p in artifacts.values() if p.is_file() and not p.is_symlink()]
    status['finished_at']=_now();append_status(folder,status)
    return status


def run_v3_revision(work,runs,*,vendor,library,set_id,revision,profile,progress=None):
    q,index,effective,root=_setup(work,runs,vendor,library,set_id,profile)
    return _run_revision(q,index,effective,root,vendor,library,set_id,revision,profile,{}, {'parsed':0,'reused':0,'unverified':0},progress)


def run_v3_ip(work,runs,*,vendor,library,set_id,profile,revisions=None,progress=None):
    q,index,effective,root=_setup(work,runs,vendor,library,set_id,profile,require_ip=True)
    all_revs=[x['revision'] for x in reversed(effective['revisions'])]
    if revisions is None:chosen=all_revs
    else:
        if not isinstance(revisions,list) or not revisions or len(set(revisions))!=len(revisions) or not set(revisions)<=set(all_revs):raise ValueError('所选版本无效或重复')
        chosen=[r for r in all_revs if r in revisions]
    if not chosen:raise ValueError('有效集没有版本')
    folder=library_folder(q.work,vendor,library);ident='run_'+uuid.uuid4().hex;artifacts=library_paths(folder,ident)
    owner={'vendor':vendor,'library':library,'ip':effective['owner']['id']}
    status={'id':ident,'owner':owner,'set_id':set_id,'profile':profile,'output_directory':str(folder),'plan':'v3 索引整体 IP 检查','target':owner['ip'],
            'target_kind':'IP_VERSION_BATCH','state':'RUNNING','started_at':_now()}
    append_status(folder,status);rows=[];cache={};stats={'parsed':0,'reused':0,'unverified':0}
    try:
        for number,revision in enumerate(chosen):
            if progress:progress(f'正在处理 {revision}',number,len(chosen))
            child_progress=(lambda message:progress(message,number,len(chosen))) if progress else None
            child=_run_revision(q,index,effective,root,vendor,library,set_id,revision,profile,cache,stats,child_progress)
            parent=next(x['parent'] for x in effective['revisions'] if x['revision']==revision)
            row={'revision':revision,'baseline':parent,'plan':'v3 索引范围检查','run_id':child['id'],'state':child['state'],'error':child.get('error')}
            source_diff=_source_comparison(index,set_id,parent,revision)
            counts=source_diff['summary'] if source_diff else None
            row.update(index_source_changes=counts['SOURCE_CHANGED'] if counts else None,
                       index_source_added=counts['ADDED'] if counts else None,index_source_removed=counts['REMOVED'] if counts else None)
            check_path=library_paths(folder,child['id'])['check.json']
            if child['state']=='SUCCEEDED' and check_path.is_file():
                check=json.loads(check_path.read_text(encoding='utf-8'))
                row.update(summary=check['summary'],comparison_count=len(check['file_changes']),baseline=(check.get('baseline') or {}).get('id'),checks=check['quality_checks'],note=check['evidence_note'])
            rows.append(row)
            if progress:progress(f"{revision}：{'完成' if child['state']=='SUCCEEDED' else '失败'}",number+1,len(chosen))
        if progress:progress('正在汇总各版本 CheckResult 并生成整体 Excel',len(chosen),len(chosen))
        write_atomic(artifacts['overall.json'],{'owner':owner,'versions':rows},immutable=True)
        render_overall_excel(owner,rows,artifacts['overall.xlsx'])
        status['state']='SUCCEEDED' if all(r['state']=='SUCCEEDED' for r in rows) else 'PARTIAL'
    except Exception as exc:status.update(state='FAILED',error=f'{type(exc).__name__}: {exc}')
    status['children']=[{'id':r['run_id'],'revision':r['revision'],'state':r['state'],'summary':r.get('summary'),'error':r.get('error')} for r in rows]
    status['artifact_files']=[p.name for p in artifacts.values() if p.is_file() and not p.is_symlink()]
    status['facts_parsed']=stats['parsed'];status['facts_reused']=stats['reused'];status['finished_at']=_now()
    append_status(folder,status)
    return status
