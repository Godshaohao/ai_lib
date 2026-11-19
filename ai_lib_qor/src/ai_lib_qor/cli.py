"""Minimal explicit-input entry points for delivery, facts, checks and reports."""
import argparse
import json
import sys
from pathlib import Path
from ai_lib_qor.sources.delivery_builder import build_delivery
from ai_lib_qor.sources.snapshot_builder import build_snapshot
from ai_lib_qor.facts.parsers import parse_delivery_file
from ai_lib_qor.versions.store import read_json, write_atomic
from ai_lib_qor.application.pipeline import check_plan, render_report


def parser():
    p=argparse.ArgumentParser(description='ai_lib_qor v3: 交付、事实、检查和报告');sub=p.add_subparsers(dest='command',required=True)
    d=sub.add_parser('delivery');d.add_argument('--root',required=True);d.add_argument('--config',required=True);d.add_argument('--out',required=True)
    sn=sub.add_parser('snapshot');sn.add_argument('--root',required=True);sn.add_argument('--config',required=True);sn.add_argument('--out',required=True)
    f=sub.add_parser('facts');f.add_argument('--delivery',required=True);f.add_argument('--file-id',required=True);f.add_argument('--out',required=True)
    e=sub.add_parser('facts-evidence');e.add_argument('--delivery',required=True);e.add_argument('--file-id',required=True);e.add_argument('--out',required=True)
    c=sub.add_parser('check');c.add_argument('--plan',required=True);c.add_argument('--out',required=True)
    r=sub.add_parser('report');r.add_argument('--check',required=True);r.add_argument('--html');r.add_argument('--excel');r.add_argument('--delivery',action='append',default=[]);r.add_argument('--facts',action='append',default=[]);r.add_argument('--formal-snapshot');r.add_argument('--source-snapshot',action='append',default=[]);r.add_argument('--target-revision');r.add_argument('--baseline-revision');r.add_argument('--accepted-revision');r.add_argument('--effective-index')
    r.add_argument('--work-root',help='v2 版本所在的 work 目录')
    scan=sub.add_parser('scan', help='扫描并自动登记已配置的 RAW 来源')
    scan.add_argument('--work',required=True);scan.add_argument('--runs',required=True)
    scan.add_argument('--vendor');scan.add_argument('--library')
    catalog=sub.add_parser('catalog-refresh',help='只读构建内存查询目录并输出统计；不扫描 RAW')
    catalog.add_argument('--work',required=True);catalog.add_argument('--runs',required=True)
    latest=sub.add_parser('latest-refresh',help='从已保存记录重建每库最新软链接')
    latest.add_argument('--work',required=True);latest.add_argument('--vendor');latest.add_argument('--library')
    query=sub.add_parser('data-query',help='只读查询 JSON 的 RAW / 历史 / 有效 / Formal 视图')
    query.add_argument('--work',required=True);query.add_argument('--runs',default='.')
    query.add_argument('--kind',required=True,choices=['raw','simple-raw','history','history-index','effective','effective-v2','simple-effective','formal','simple-formal','compare','deliveries','compare-revisions','changed-pairs','formal-effective','effective-timeline'])
    for name in ('vendor','library','version','view','path','owner','set-id','revision','snapshot','delivery-id','other-revision'):query.add_argument('--'+name)
    query.add_argument('--revisions',nargs='+')
    eff=sub.add_parser('effective-build',help='从简化 RAW JSON 和可选父版本计算独立有效版本')
    for name in ('raw','out','owner-type','owner-id','revision'):eff.add_argument('--'+name,required=True)
    eff.add_argument('--view',action='append',required=True);eff.add_argument('--parent');eff.add_argument('--work')
    eff.add_argument('--allow-cross-library',action='store_true')
    base=sub.add_parser('effective-formal-init',help='从 Formal 快照及 RAW 记录初始化 v2 版本')
    for name in ('formal','out','owner-type','owner-id'):base.add_argument('--'+name,required=True)
    base.add_argument('--raw',action='append',required=True);base.add_argument('--view',action='append',required=True);base.add_argument('--work')
    base.add_argument('--allow-cross-library',action='store_true')
    diff=sub.add_parser('effective-compare',help='只读比较两份 v2 有效版本的来源')
    diff.add_argument('--before',required=True);diff.add_argument('--after',required=True)
    timeline=sub.add_parser('effective-timeline',help='只读查看文件在父版本链中的来源')
    timeline.add_argument('--revision',action='append',required=True);timeline.add_argument('--view',required=True);timeline.add_argument('--path',required=True)
    migrate=sub.add_parser('effective-migrate',help='将旧版完整历史转换为独立的 v2 核验副本')
    for name in ('work','runs','vendor','library','owner','out'):migrate.add_argument('--'+name,required=True)
    formal=sub.add_parser('formal-sync', help='同步已配置的正式来源')
    formal.add_argument('--work',required=True);formal.add_argument('--runs',required=True);formal.add_argument('--formal-nl-id')
    batch=sub.add_parser('run-ip', help='执行已登记 IP 的所有版本检查')
    for name in ('work','runs','plans','vendor','library','ip'):batch.add_argument('--'+name,required=True)
    changed=sub.add_parser('run-changed-lef', help='只检查两个有效版本之间来源变化的 LEF，生成检查结果和报告')
    for name in ('work','runs','vendor','library','set-id','before','after'):changed.add_argument('--'+name,required=True)
    changed.add_argument('--pin-liberty-path',help='显式选择当前有效 Liberty 相对路径，同时检查其与变化 LEF 的信号 Pin')
    run_plan=sub.add_parser('run-plan', help='执行计划并保存状态、检查及报告')
    run_plan.add_argument('--plan',required=True,type=Path);run_plan.add_argument('--runs',required=True)
    for name in ('work','vendor','library','ip','revision'):run_plan.add_argument('--'+name)
    evidence=sub.add_parser('run-evidence', help='提取文件解析证据并生成可查看的运行记录')
    for name in ('delivery','file-id','runs'):evidence.add_argument('--'+name,required=True)
    reg=sub.add_parser('register', help='基于扫描结果登记显式文件映射')
    for name in ('work','source','scan','metadata','mapping','version-dir'):reg.add_argument('--'+name,required=True)
    return p


def read(path):return json.loads(Path(path).read_text(encoding='utf-8'))


def avoid_source(output, root):
    if Path(output).resolve().is_relative_to(Path(root).resolve()):raise ValueError('输出不能位于 RAW 来源目录')


def run(a):
    if a.command == 'run-changed-lef':
        from ai_lib_qor.application.runs import execute_changed_lefs
        return execute_changed_lefs(a.work,a.runs,vendor=a.vendor,library=a.library,set_id=a.set_id,before=a.before,after=a.after,pin_liberty_path=a.pin_liberty_path)
    if a.command == 'latest-refresh':
        from ai_lib_qor.application.latest_pointers import refresh_all,refresh_library
        if bool(a.vendor)!=bool(a.library):raise ValueError('必须同时指定 vendor 和 library')
        rows=[refresh_library(a.work,a.vendor,a.library)] if a.vendor else refresh_all(a.work)
        return {'libraries':rows}
    if a.command == 'effective-migrate':
        from ai_lib_qor.application.history_migration import migrate_history
        return migrate_history(a.work,a.runs,vendor=a.vendor,library=a.library,owner=a.owner,output=a.out)
    if a.command == 'effective-build':
        from ai_lib_qor.application.effective_json import create_revision
        from ai_lib_qor.versions.store import now
        raw=read(a.raw); parent=read(a.parent) if a.parent else None
        avoid_source(a.out,raw.get('context',{}).get('root','/'))
        result=create_revision(raw,owner={'type':a.owner_type,'id':a.owner_id},revision=a.revision,
                               created_at=now(),include_views=a.view,parent=parent,allow_cross_library=a.allow_cross_library)
        if a.work:
            from ai_lib_qor.application.effective_publisher import publish_v2
            publish_v2(a.work,a.out,result,parent)
        else:write_atomic(a.out,result,immutable=True)
        return {'revision':result['revision'],'output':a.out,'state':'SUCCEEDED'}
    if a.command == 'effective-formal-init':
        from ai_lib_qor.application.effective_json import create_formal_revision
        from ai_lib_qor.versions.store import now
        formal=read(a.formal);raws=[read(p) for p in a.raw]
        for root in [formal.get('context',{}).get('root','/'),*[x.get('context',{}).get('root','/') for x in raws]]:avoid_source(a.out,root)
        result=create_formal_revision(formal,raws,owner={'type':a.owner_type,'id':a.owner_id},created_at=now(),
                                      include_views=a.view,allow_cross_library=a.allow_cross_library)
        if a.work:
            from ai_lib_qor.application.effective_publisher import publish_v2
            publish_v2(a.work,a.out,result)
        else:write_atomic(a.out,result,immutable=True)
        return {'revision':result['revision'],'output':a.out,'state':'SUCCEEDED'}
    if a.command == 'effective-compare':
        from ai_lib_qor.application.effective_json import compare_revisions
        return compare_revisions(read(a.before),read(a.after))
    if a.command == 'effective-timeline':
        from ai_lib_qor.application.effective_json import file_timeline
        return file_timeline([read(x) for x in a.revision],a.view,a.path)
    if a.command == 'data-query':
        from ai_lib_qor.application.data_query import query_data
        opts=vars(a).copy()
        for name in ('command','work','runs','kind'):opts.pop(name,None)
        return query_data(a.work,a.runs,a.kind,**opts)
    if a.command == 'catalog-refresh':
        from ai_lib_qor.application.library_catalog import LibraryCatalog
        if not Path(a.work).is_dir(): raise ValueError('工作目录不存在或不可访问')
        if Path(a.runs).exists() and not Path(a.runs).is_dir(): raise ValueError('运行目录不是目录')
        catalog=LibraryCatalog(a.work,a.runs).refresh(); overview=catalog.overview()
        return {'state':'PARTIAL' if catalog.warnings else 'COMPLETE','storage':'memory_only',
                'runs_exists':Path(a.runs).is_dir(),
                'vendors':len({k[0] for k in catalog.libraries}),'libraries':len(catalog.libraries),
                'ips':len(catalog.entries),'deliveries':sum(len(v['deliveries']) for v in catalog.libraries.values()),
                'formal_snapshots':len(catalog.snapshots),'raw_sources':len(overview['scan_rows']),
                'warnings':catalog.warnings}
    if a.command == 'scan':
        from ai_lib_qor.application.scans import sources, run_scan_and_ingest, ingest_result
        configured=[s for s in sources(a.work) if (not a.vendor or s['vendor_id']==a.vendor) and (not a.library or s['source_library_id']==a.library)]
        if not configured: raise ValueError('没有匹配的 RAW 来源配置')
        results=[]
        for source in configured:
            observation=run_scan_and_ingest(a.runs,a.work,source)
            results.append({'vendor_id':source['vendor_id'],'source_library_id':source['source_library_id'],
                            'scan_id':observation['scan_id'],'status':observation['status'],
                            'ingest':ingest_result(a.runs,observation)})
        return {'sources':results}
    if a.command == 'formal-sync':
        from ai_lib_qor.sources.formal_sync import formal_sources, sync_formal
        from ai_lib_qor.application.scans import sources
        from ai_lib_qor.sources.registration import registered_deliveries
        configured=[s for s in formal_sources(a.work) if not a.formal_nl_id or s['formal_nl_id']==a.formal_nl_id]
        if not configured: raise ValueError('没有匹配的正式来源配置')
        deliveries=[d for source in sources(a.work) for d in registered_deliveries(a.work,source)]
        return {'sources':[sync_formal(a.runs,source,deliveries,a.work) for source in configured]}
    if a.command == 'register':
        from ai_lib_qor.sources.registration import register_delivery
        path=register_delivery(a.work,read(a.source),read(a.scan),a.version_dir,read(a.metadata),read(a.mapping))
        return {'delivery':str(path)}
    if a.command == 'run-evidence':
        from ai_lib_qor.application.runs import execute_evidence
        return execute_evidence(read_json(a.delivery,'delivery_record'),a.file_id,a.runs)
    if a.command == 'run-plan':
        from ai_lib_qor.application.runs import execute, plans_for_revision
        scope=(a.work,a.vendor,a.library,a.ip,a.revision)
        if any(scope) and not all(scope): raise ValueError('绑定版本运行需要同时指定 --work、--vendor、--library、--ip 和 --revision')
        if all(scope):
            from ai_lib_qor.application.catalog import load_catalog
            entries,_,_=load_catalog(a.work)
            selected=[x for x in entries if (x['vendor'],x['library'],x['ip'])==(a.vendor,a.library,a.ip)]
            versions=[v for x in selected for v in x['versions'] if v['revision_id']==a.revision]
            if len(versions)!=1 or a.plan.name not in plans_for_revision(a.plan.parent,versions[0]):
                raise ValueError('检查计划与指定 IP 版本不匹配')
            return execute(a.plan,a.runs,owner={'vendor':a.vendor,'library':a.library,'ip':a.ip},expected_revision=a.revision)
        return execute(a.plan, a.runs)
    if a.command == 'run-ip':
        from ai_lib_qor.application.runs import execute_ip_batch
        from ai_lib_qor.application.catalog import load_catalog
        entries,_,warnings=load_catalog(a.work)
        selected=[x for x in entries if x['index']['owner']['owner_type']=='BUSINESS_IP' and (x['vendor'],x['library'],x['ip'])==(a.vendor,a.library,a.ip)]
        if len(selected)!=1: raise ValueError('没有唯一匹配的 IP；'+'; '.join(warnings))
        return execute_ip_batch(selected[0],a.plans,a.runs)
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
        return check_plan(a.plan,a.out)
    return render_report(a.check,html=a.html,excel=a.excel,delivery=a.delivery,facts=a.facts,source_snapshot=a.source_snapshot,formal_snapshot=a.formal_snapshot,target_revision=a.target_revision,baseline_revision=a.baseline_revision,accepted_revision=a.accepted_revision,effective_index=a.effective_index,work_root=a.work_root)


def main():
    try:
        args=parser().parse_args();result=run(args);print(json.dumps(result,ensure_ascii=False,indent=2))
        if result.get('state') in ('FAILED','PARTIAL') or (args.command in ('scan','formal-sync') and any(x.get('status') != 'COMPLETE' or x.get('ingest',{}).get('blocked',0) for x in result.get('sources',[]))): return 1
    except (OSError,ValueError,KeyError,ImportError) as e:print(f'错误: {e}',file=sys.stderr);return 1
    return 0

if __name__=='__main__':sys.exit(main())
