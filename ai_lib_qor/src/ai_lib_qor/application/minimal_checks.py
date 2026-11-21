"""Run the existing LEF checks with path-based facts and shared report data."""
from copy import deepcopy
from pathlib import Path
import json
import uuid

from ai_lib_qor.checks.plugins import lef_macro_diff,lef_liberty_pin_match
from ai_lib_qor.facts.parsers import _file_digest
from ai_lib_qor.sources.layout import library_folder
from ai_lib_qor.sources.timestamps import utc_text
from ai_lib_qor.versions.store import validate,write_atomic
from .minimal_effective import _history
from .minimal_facts import build_facts,_stat_key
from .minimal_file_index import build_index


def _fresh(work,vendor,library):
    folder=library_folder(work,vendor,library);path=folder/'file_index.json'
    if path.is_symlink() or not path.is_file():raise ValueError('文件索引不存在')
    saved=json.loads(path.read_text(encoding='utf-8'))
    if saved!=build_index(work,vendor,library):raise ValueError('文件索引过期')
    return folder,saved


def _members(index,revision):
    return {(view,path):entry for view,group in index['views'].items() for path,row in group.items()
            for entry in row['effective'] if entry['revision']==revision}


def _run(work,vendor,library,revision,cache):
    from .path_query import PathDataQuery
    context=PathDataQuery(work).get_check_context(vendor,library,revision)
    folder=library_folder(work,vendor,library);index=context['index'];parent=context['baseline']
    target={(row['view'],row['path']):{'version':row['version'],'path':row['absolute_path']} for row in context['members']}
    baseline={(row['view'],row['path']):row['baseline'] for row in context['members'] if row['baseline']}
    run='run_'+uuid.uuid4().hex;rows=[];facts={};checks=[];changes=[];comparisons=[];partial_comparisons=[]
    def obtain(view,path,source):
        key=(view,path,source['version'])
        if key not in cache:
            result=build_facts(work,vendor,library,view,path,version=source['version'],_capture=True)
            p=Path(result['path']);data=json.loads(p.read_text(encoding='utf-8'))
            actual=Path(data['source']['absolute_path']);before,digest=result['_source_stamp']
            if _stat_key(actual)!=before or _file_digest(actual)!=digest or _stat_key(actual)!=before:raise ValueError('事实复用核验期间文件变化')
            cache[key]=(p,data,before,digest)
            return p,data
        p,data,expected,digest=cache[key];actual=Path(data['source']['absolute_path'])
        if _stat_key(actual)!=expected or _file_digest(actual)!=digest or _stat_key(actual)!=expected:
            raise ValueError('本次运行中的来源文件发生变化，不能复用事实')
        return p,data
    for (view,path),source in sorted(target.items()):
        row={'view':view,'path':path,'version':source['version'],'absolute_path':source['path'],
             'status':'NOT_CHECKED','facts':None,'note':'暂不支持此 View 的解析'}
        if view in ('LEF','LIBERTY','VERILOG','CDL','SPICE'):
            try:
                fp,fact=obtain(view,path,source);facts[(view,path)]=(fp,fact)
                row.update(status='PARSED',facts=str(fp),note=('部分解析；' if fact['parse_status']=='PARTIAL' else '')+'仅覆盖 '+', '.join(fact['covered_sections']))
            except (OSError,ValueError,KeyError,TypeError) as exc:
                row.update(status='FAILED',note=f'{type(exc).__name__}: {exc}')
        rows.append(row)
    lef=[(key,p,f) for key,(p,f) in facts.items() if key[0]=='LEF']
    libs=[(key,p,f) for key,(p,f) in facts.items() if key[0]=='LIBERTY']
    for key,lefpath,leffact in lef:
        names={x['name'] for x in leffact['objects']['macros']}
        matches=[(k,p,f) for k,p,f in libs if names and names <= {x['name'] for x in f['objects']['cells']}]
        for libkey,libpath,libfact in matches:
            cells={x['name'] for x in libfact['objects']['cells']}
            owners=[k for k,_,candidate in lef if {x['name'] for x in candidate['objects']['macros']} & cells]
            if len(owners)!=1:
                checks.append({'check_id':'LEF_LIBERTY_PIN_MATCH','scope_file_keys':[key[1],libkey[1]],'result':'INCONCLUSIVE',
                               'coverage':'UNKNOWN','facts_refs':[lefpath.name,libpath.name],
                               'detail':'同一 Liberty 对应多个 LEF，配对不唯一，未执行检查'})
                continue
            # The check API uses a reference label; actual facts retain path-based sources.
            a={**leffact,'facts_id':lefpath.name};b={**libfact,'facts_id':libpath.name}
            check=lef_liberty_pin_match.compare(a,b,key[1],libkey[1]);checks.append(check)
        if not matches:
            checks.append({'check_id':'LEF_LIBERTY_PIN_MATCH','scope_file_keys':[key[1]],'result':'INCONCLUSIVE',
                           'coverage':'UNKNOWN','facts_refs':[lefpath.name],
                           'detail':'未找到可配对的 Liberty Cell；无法检查信号 Pin'})
        previous=baseline.get(key)
        if previous:
            try:
                oldpath,oldfact=obtain('LEF',key[1],previous)
                old={**oldfact,'facts_id':oldpath.name};new={**leffact,'facts_id':lefpath.name}
                diff=lef_macro_diff.compare(old,new)
                if diff is None:raise ValueError('LEF 对比覆盖不足')
                comparisons.append({'view':'LEF','path':key[1],'baseline_version':previous['version'],
                                    'version':target[key]['version'],'content_status':'CURRENT_CONTENT_DIFF' if diff else 'CURRENT_CONTENT_MATCH',
                                    'facts_refs':[oldpath.name,lefpath.name]})
                for item in diff:changes.append({'view':'LEF','path':key[1],'baseline_version':previous['version'],
                                                  'version':target[key]['version'],**item})
            except (OSError,ValueError,KeyError,TypeError) as exc:
                checks.append({'check_id':'LEF_MACRO_DIFF','scope_file_keys':[key[1]],'result':'INCONCLUSIVE',
                               'coverage':'UNKNOWN','facts_refs':[lefpath.name], 'detail':f'基线解析或比较失败: {exc}'})
    if not lef:
        checks.append({'check_id':'LEF_LIBERTY_PIN_MATCH','scope_file_keys':[],'result':'INCONCLUSIVE',
                       'coverage':'UNKNOWN','facts_refs':[],'detail':'未解析到 LEF，接口检查未执行'})
    for key,(newpath,newfact) in facts.items():
        view,path=key;previous=baseline.get(key)
        if view not in ('VERILOG','CDL','SPICE') or not previous:continue
        try:
            oldpath,oldfact=obtain(view,path,previous)
            if view=='VERILOG':
                from ai_lib_qor.facts._compat.verilog import diff_verilog_summary
                convert=lambda f:{'modules':{x['name']:x for x in f['objects']['modules']}}
                delta=diff_verilog_summary(convert(oldfact),convert(newfact))['module_changes']
            else:
                from ai_lib_qor.facts._compat.cdl import diff_cdl_summary
                convert=lambda f:{'subckts':{x['name']:x for x in f['objects']['subcircuits']}}
                delta=diff_cdl_summary(convert(oldfact),convert(newfact))['subckt_changes']
            differences={k:v for k,v in delta.items() if v}
            partial_comparisons.append({'view':view,'path':path,'baseline_version':previous['version'],
                'version':target[key]['version'],'coverage':'PARTIAL','differences':differences,
                'facts_refs':[oldpath.name,newpath.name],
                'note':'仅比较轻量解析到的模块端口或子电路引脚；不代表完整网表一致'})
        except (OSError,ValueError,KeyError,TypeError) as exc:
            checks.append({'check_id':view+'_PARTIAL_DIFF','scope_file_keys':[path],'result':'INCONCLUSIVE',
                           'coverage':'UNKNOWN','facts_refs':[newpath.name], 'detail':f'基线解析或比较失败: {exc}'})
    _,current=_fresh(work,vendor,library)
    if current!=index:raise ValueError('检查期间归档发生变化')
    state='PARTIAL' if any(r['status']!='PARSED' for r in rows) or any(f['parse_status']!='COMPLETE' for _,f in facts.values()) or any(c['result']=='INCONCLUSIVE' for c in checks) else 'SUCCEEDED'
    report={'schema_version':'check_result.path.v1','run_id':run,'vendor':vendor,'library':library,
            'revision':revision,'baseline':parent,'run_at':utc_text(),'state':state,'files':rows,
            'checks':checks,'comparisons':comparisons,'partial_comparisons':partial_comparisons,'changes':changes,
            'summary':{'failed_checks':sum(x['result']=='FAIL' for x in checks),
                       'inconclusive_checks':sum(x['result']=='INCONCLUSIVE' for x in checks),
                       'failed_files':sum(x['status']=='FAILED' for x in rows),
                       'files_with_new_source':sum(x['baseline_version']!=x['version'] for x in comparisons),
                       'files_with_confirmed_content_change':sum(x['content_status']=='CURRENT_CONTENT_DIFF' for x in comparisons)},
            'note':'仅比较 LEF Macro SIZE、Pin 存在及方向并检查 LEF/Liberty 信号 Pin；VERILOG/CDL/SPICE 的接口差异仅部分解析，GDS 等未检查；当前来源不证明历史字节一致。'}
    validate(report,'check_result_path')
    check=folder/f'check_{run}.json';excel=folder/f'report_{run}.xlsx'
    write_atomic(check,report,immutable=True)
    from ai_lib_qor.reporting.excel import render_excel
    render_excel({**report,'_path_context':{'index':index,'facts':{str(p):f for p,f in facts.values()}}},excel)
    return {'state':state,'revision':revision,'run_id':run,'check':str(check),'excel':str(excel)}


def run_revision(work,vendor,library,revision):return _run(work,vendor,library,revision,{})


def run_library(work,vendor,library,*,revisions=None):
    folder,index=_fresh(work,vendor,library);available=index['revisions']
    if revisions is not None and (not revisions or len(set(revisions))!=len(revisions) or not set(revisions)<=set(available)):
        raise ValueError('版本选择无效')
    selected=[x for x in available if revisions is None or x in revisions]
    if not selected:raise ValueError('没有可检查的有效版本')
    cache={};runs=[];snapshot=index
    for revision in selected:
        _,current=_fresh(work,vendor,library)
        if current!=snapshot:raise ValueError('整体运行期间归档发生变化')
        runs.append(_run(work,vendor,library,revision,cache))
    data={'vendor':vendor,'library':library,'versions':runs}
    ident='run_'+uuid.uuid4().hex;out=folder/f'overall_{ident}.json';excel=folder/f'overall_{ident}.xlsx'
    write_atomic(out,data,immutable=True)
    from ai_lib_qor.reporting.overall_excel import render_overall_excel
    rows=[]
    for run in runs:
        check=json.loads(Path(run['check']).read_text(encoding='utf-8'))
        rows.append({'revision':run['revision'],'baseline':check['baseline'],'run_id':run['run_id'],'state':run['state'],
                     'plan':'路径式有效版本检查','summary':check['summary'],'checks':check['checks'],'note':check['note'],
                     'error':f"解析失败 {check['summary']['failed_files']} 个文件" if check['summary']['failed_files'] else None,
                     'comparison_count':len(check['comparisons'])})
    render_overall_excel({'vendor':vendor,'library':library},rows,excel)
    return {'state':'SUCCEEDED' if all(x['state']=='SUCCEEDED' for x in runs) else 'PARTIAL',
            'overall':str(out),'excel':str(excel),'versions':runs}
