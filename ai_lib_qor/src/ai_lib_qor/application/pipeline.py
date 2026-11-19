"""Application use cases for checking and rendering saved business records."""
import json
from pathlib import Path
from ai_lib_qor.checks.assembler import build_check_result
from ai_lib_qor.reporting.view import build_report
from ai_lib_qor.reporting.html import render_html
from ai_lib_qor.versions.store import read_json, write_atomic
from ai_lib_qor.versions.composer import members_map


def read(path):return json.loads(Path(path).read_text(encoding='utf-8'))


def avoid_source(output, root):
    if Path(output).resolve().is_relative_to(Path(root).resolve()):raise ValueError('输出不能位于 RAW 来源目录')


def _check_revision(path,work_root,out):
    value=read(path)
    if value.get('schema')=='effective.simple.v2':
        if not work_root:raise ValueError('v2 检查计划必须指定 work_root')
        from .v2_check_adapter import load_v2_for_check
        result=load_v2_for_check(path,work_root)
        for root in result['source_roots']:avoid_source(out,root)
        return result,result['members']
    result=read_json(path,'effective_version')
    return result,members_map(result)


def check_plan(plan_path, out):
    plan=read(plan_path)
    comparisons=[{'file_key':x['file_key'],'old':read_json(x['old_facts'],'file_facts'),'new':read_json(x['new_facts'],'file_facts')} for x in plan.get('comparisons',[])]
    pairs=[{'lef_key':x['lef_key'],'liberty_key':x['liberty_key'],'lef':read_json(x['lef_facts'],'file_facts'),'liberty':read_json(x['liberty_facts'],'file_facts')} for x in plan.get('pin_pairs',[])]
    if 'auto_pair_facts' in plan:
        from ai_lib_qor.checks.plan import pair_interfaces
        auto_inputs=[{'file_key':x['file_key'],'facts':read_json(x['facts'],'file_facts')} for x in plan['auto_pair_facts']]
        pairs.extend(pair_interfaces(auto_inputs))
    if 'target_delivery' in plan and 'target_revision' not in plan:
        target=read_json(plan['target_delivery'],'delivery_record');baseline=read_json(plan['baseline_delivery'],'delivery_record');avoid_source(out,target['source_root']);avoid_source(out,baseline['source_root'])
        target_ref={'kind':'RAW_DELIVERY','id':target['delivery_id']};base_ref={'kind':'RAW_DELIVERY','id':baseline['delivery_id']};extra={'target_delivery':target,'baseline_delivery':baseline,'effective_set_id':None}
    elif 'target_revision' in plan and 'target_delivery' not in plan:
        target,target_members=_check_revision(plan['target_revision'],plan.get('work_root'),out)
        baseline,baseline_members=_check_revision(plan['baseline_revision'],plan.get('work_root'),out) if plan.get('baseline_revision') else (None,None)
        if baseline and (target['effective_set_id']!=baseline['effective_set_id'] or target['owner']!=baseline['owner']):raise ValueError('目标与基线不属于同一有效集')
        if baseline is None and (target['parent_revision_id'] is not None or comparisons):raise ValueError('仅初始版本的非对比检查可省略基线')
        snapshots=[read_json(x,'formal_snapshot') for x in plan.get('formal_snapshots',[])]
        for snapshot in snapshots:avoid_source(out,snapshot['source_root'])
        target_ref={'kind':'EFFECTIVE_REVISION','id':target['revision_id']};base_ref={'kind':'EFFECTIVE_REVISION','id':baseline['revision_id']} if baseline else None;extra={'target_members':target_members,'baseline_members':baseline_members,'effective_set_id':target['effective_set_id'],'formal_snapshots':snapshots}
    else:raise ValueError('必须指定唯一一种目标：交付或有效版本')
    result=build_check_result(target=target_ref,baseline=base_ref,run_id=plan['run_id'],ruleset_id=plan['ruleset_id'],run_at=plan['run_at'],comparisons=comparisons,pin_pairs=pairs,plugin_ids=plan.get('plugins'),**extra)
    write_atomic(out,result,immutable=True);return {'check_run_id':result['check_run_id'],'output':str(out)}

def render_report(check_path, *, html=None, excel=None, delivery=(), facts=(), source_snapshot=(), formal_snapshot=None, target_revision=None, baseline_revision=None, accepted_revision=None, effective_index=None, work_root=None):
    context_options={'formal_snapshot':formal_snapshot,'target_revision':target_revision,'baseline_revision':baseline_revision,'accepted_revision':accepted_revision,'effective_index':effective_index}
    if not html and not excel:raise ValueError('至少指定 --html 或 --excel')
    context={'deliveries':[read_json(x,'delivery_record') for x in delivery], 'facts':[read_json(x,'file_facts') for x in facts], 'source_snapshots':[read_json(x,'formal_snapshot') for x in source_snapshot]}
    result=read_json(check_path,'check_result');v2_context={}
    for name,schema in [('formal_snapshot','formal_snapshot'),('target_revision','effective_version'),('baseline_revision','effective_version'),('accepted_revision','effective_version'),('effective_index','effective_index')]:
        value=context_options.get(name)
        if not value:continue
        if schema=='effective_version' and read(value).get('schema')=='effective.simple.v2':
            revision,member_refs=_check_revision(value,work_root,html or excel)
            for output in (html,excel):
                if output:
                    for root in revision['source_roots']:avoid_source(output,root)
            v2_context[name]=(revision,member_refs)
            continue
        context[name]=read_json(value,schema)
    for name,ref_field,target_key in [('target_revision','new_source_ref','target'),('baseline_revision','old_source_ref','baseline')]:
        if name not in v2_context:continue
        rev,member_refs=v2_context[name];ref=result.get(target_key)
        if not ref or ref.get('kind')!='EFFECTIVE_REVISION' or ref.get('id')!=rev['revision_id'] or result['effective_set_id']!=rev['effective_set_id']:
            raise ValueError('报告版本与检查结果不一致')
        for change in result['file_changes']:
            if member_refs.get(change['file_key'])!=change[ref_field]:raise ValueError('报告版本成员与检查来源不一致')
    if 'accepted_revision' in v2_context:
        rev,_=v2_context['accepted_revision'];index=context.get('effective_index')
        if not index or index['current_accepted_revision']!=rev['revision_id'] or index['effective_set_id']!=rev['effective_set_id']:
            raise ValueError('已采纳版本与索引不一致')
    if 'target_revision' in v2_context:
        _,member_refs=v2_context['target_revision'];facts_by_id={fact['facts_id']:fact for fact in context['facts']}
        for check in result['quality_checks']:
            for fact_id in check['facts_refs']:
                fact=facts_by_id.get(fact_id)
                if fact is None:continue
                matches=[key for key in check['scope_file_keys'] if member_refs.get(key)==fact['source_ref']]
                if len(matches)!=1:raise ValueError(f'质量检查事实与目标版本文件范围不匹配: {fact_id}')
    if v2_context:
        result=dict(result);result['evidence_note']+=' v2 版本来源已核对；工作簿的旧版有效成员上下文未填充。'
    report=build_report(result,**context);outputs=[]
    if html:
        path=Path(html);path.parent.mkdir(parents=True,exist_ok=True)
        with path.open('x',encoding='utf-8') as out:out.write(render_html(report))
        outputs.append(str(path))
    if excel:
        from ai_lib_qor.reporting.excel import render_excel
        outputs.append(str(render_excel(report,excel)))
    return {'outputs':outputs}
