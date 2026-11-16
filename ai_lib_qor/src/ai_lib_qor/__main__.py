"""Minimal explicit-input entry points for delivery, facts, checks and reports."""
import argparse
import json
import sys
from pathlib import Path
from ai_lib_qor.sources.delivery_builder import build_delivery
from ai_lib_qor.sources.snapshot_builder import build_snapshot
from ai_lib_qor.facts.parsers import parse_delivery_file
from ai_lib_qor.checks.assembler import build_check_result
from ai_lib_qor.reporting.view import build_report
from ai_lib_qor.reporting.html import render_html
from ai_lib_qor.versions.store import read_json, write_atomic
from ai_lib_qor.versions.composer import members_map


def parser():
    p=argparse.ArgumentParser(description='ai_lib_qor v3: 交付、事实、检查和报告');sub=p.add_subparsers(dest='command',required=True)
    d=sub.add_parser('delivery');d.add_argument('--root',required=True);d.add_argument('--config',required=True);d.add_argument('--out',required=True)
    sn=sub.add_parser('snapshot');sn.add_argument('--root',required=True);sn.add_argument('--config',required=True);sn.add_argument('--out',required=True)
    f=sub.add_parser('facts');f.add_argument('--delivery',required=True);f.add_argument('--file-id',required=True);f.add_argument('--out',required=True)
    e=sub.add_parser('facts-evidence');e.add_argument('--delivery',required=True);e.add_argument('--file-id',required=True);e.add_argument('--out',required=True)
    c=sub.add_parser('check');c.add_argument('--plan',required=True);c.add_argument('--out',required=True)
    r=sub.add_parser('report');r.add_argument('--check',required=True);r.add_argument('--html');r.add_argument('--excel');r.add_argument('--delivery',action='append',default=[]);r.add_argument('--facts',action='append',default=[]);r.add_argument('--formal-snapshot');r.add_argument('--source-snapshot',action='append',default=[]);r.add_argument('--target-revision');r.add_argument('--baseline-revision');r.add_argument('--accepted-revision');r.add_argument('--effective-index')
    return p


def read(path):return json.loads(Path(path).read_text(encoding='utf-8'))


def avoid_source(output, root):
    if Path(output).resolve().is_relative_to(Path(root).resolve()):raise ValueError('输出不能位于 RAW 来源目录')


def run(a):
    if a.command=='delivery':
        avoid_source(a.out,a.root);config=read(a.config);result=build_delivery(a.root,config['metadata'],config['file_mapping']);write_atomic(a.out,result,immutable=True);return {'delivery_id':result['delivery_id'],'output':a.out}
    if a.command=='snapshot':
        avoid_source(a.out,a.root);config=read(a.config);deliveries=[read_json(p,'delivery_record') for p in config.get('deliveries',[])]
        result=build_snapshot(a.root,config['metadata'],config['link_mapping'],deliveries);write_atomic(a.out,result,immutable=True);return {'formal_snapshot_id':result['formal_snapshot_id'],'output':a.out}
    if a.command=='facts':
        delivery=read_json(a.delivery,'delivery_record');avoid_source(a.out,delivery['source_root']);result=parse_delivery_file(delivery,a.file_id);write_atomic(a.out,result,immutable=True);return {'facts_id':result['facts_id'],'output':a.out}
    if a.command=='facts-evidence':
        from ai_lib_qor.facts.rich_evidence import parse_delivery_evidence
        delivery=read_json(a.delivery,'delivery_record');avoid_source(a.out,delivery['source_root']);result=parse_delivery_evidence(delivery,a.file_id);write_atomic(a.out,result,immutable=True);return {'source_sha256':result['source_sha256'],'output':a.out}
    if a.command=='check':
        plan=read(a.plan)
        comparisons=[{'file_key':x['file_key'],'old':read_json(x['old_facts'],'file_facts'),'new':read_json(x['new_facts'],'file_facts')} for x in plan.get('comparisons',[])]
        pairs=[{'lef_key':x['lef_key'],'liberty_key':x['liberty_key'],'lef':read_json(x['lef_facts'],'file_facts'),'liberty':read_json(x['liberty_facts'],'file_facts')} for x in plan.get('pin_pairs',[])]
        if 'auto_pair_facts' in plan:
            from ai_lib_qor.checks.plan import pair_interfaces
            auto_inputs=[{'file_key':x['file_key'],'facts':read_json(x['facts'],'file_facts')} for x in plan['auto_pair_facts']]
            pairs.extend(pair_interfaces(auto_inputs))
        if 'target_delivery' in plan and 'target_revision' not in plan:
            target=read_json(plan['target_delivery'],'delivery_record');baseline=read_json(plan['baseline_delivery'],'delivery_record');avoid_source(a.out,target['source_root']);avoid_source(a.out,baseline['source_root'])
            target_ref={'kind':'RAW_DELIVERY','id':target['delivery_id']};base_ref={'kind':'RAW_DELIVERY','id':baseline['delivery_id']};extra={'target_delivery':target,'baseline_delivery':baseline,'effective_set_id':None}
        elif 'target_revision' in plan and 'target_delivery' not in plan:
            target=read_json(plan['target_revision'],'effective_version')
            baseline=read_json(plan['baseline_revision'],'effective_version') if plan.get('baseline_revision') else None
            if baseline and (target['effective_set_id']!=baseline['effective_set_id'] or target['owner']!=baseline['owner']):raise ValueError('目标与基线不属于同一有效集')
            if baseline is None and (target['parent_revision_id'] is not None or comparisons):raise ValueError('仅初始版本的非对比检查可省略基线')
            snapshots=[read_json(x,'formal_snapshot') for x in plan.get('formal_snapshots',[])]
            for snapshot in snapshots:avoid_source(a.out,snapshot['source_root'])
            target_ref={'kind':'EFFECTIVE_REVISION','id':target['revision_id']};base_ref={'kind':'EFFECTIVE_REVISION','id':baseline['revision_id']} if baseline else None;extra={'target_members':members_map(target),'baseline_members':members_map(baseline) if baseline else None,'effective_set_id':target['effective_set_id'],'formal_snapshots':snapshots}
        else:raise ValueError('必须指定唯一一种目标：交付或有效版本')
        result=build_check_result(target=target_ref,baseline=base_ref,run_id=plan['run_id'],ruleset_id=plan['ruleset_id'],run_at=plan['run_at'],comparisons=comparisons,pin_pairs=pairs,plugin_ids=plan.get('plugins'),**extra)
        write_atomic(a.out,result,immutable=True);return {'check_run_id':result['check_run_id'],'output':a.out}
    if not a.html and not a.excel:raise ValueError('至少指定 --html 或 --excel')
    context={'deliveries':[read_json(x,'delivery_record') for x in a.delivery], 'facts':[read_json(x,'file_facts') for x in a.facts], 'source_snapshots':[read_json(x,'formal_snapshot') for x in a.source_snapshot]}
    for name,schema in [('formal_snapshot','formal_snapshot'),('target_revision','effective_version'),('baseline_revision','effective_version'),('accepted_revision','effective_version'),('effective_index','effective_index')]:
        value=getattr(a,name)
        if value:context[name]=read_json(value,schema)
    report=build_report(read_json(a.check,'check_result'),**context);outputs=[]
    if a.html:
        path=Path(a.html);path.parent.mkdir(parents=True,exist_ok=True)
        with path.open('x',encoding='utf-8') as out:out.write(render_html(report))
        outputs.append(str(path))
    if a.excel:
        from ai_lib_qor.reporting.excel import render_excel
        outputs.append(str(render_excel(report,a.excel)))
    return {'outputs':outputs}


def main():
    try:print(json.dumps(run(parser().parse_args()),ensure_ascii=False,indent=2))
    except (OSError,ValueError,KeyError,ImportError) as e:print(f'错误: {e}',file=sys.stderr);return 1
    return 0

if __name__=='__main__':sys.exit(main())
