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


def _fmt_bytes(n: int) -> str:
    val = float(n)
    for unit in ('B', 'KB', 'MB', 'GB'):
        if val < 1024 or unit == 'GB':
            return f'{val:.1f} {unit}' if unit != 'B' else f'{int(val)} B'
        val /= 1024.0
    return f'{n} B'


def format_table(command: str, result: dict) -> str:
    """Human-readable terminal table/summary renderer for primary CLI commands."""
    lines = []
    if command == 'refresh-status':
        t = result.get('totals', {})
        lines.append(
            f"工作目录: {result.get('work')} | 供应商 {t.get('vendors', 0)} · 库 {t.get('libraries', 0)} · "
            f"交付 {t.get('deliveries', 0)} · 有效版本 {t.get('revisions', 0)} · "
            f"索引最新 {t.get('index_fresh', 0)} / 待刷新 {t.get('index_stale_or_unverified', 0)} / 缺失 {t.get('index_missing', 0)}"
        )
        lines.append(f"{'VENDOR':<14} {'LIBRARY':<28} {'DELIV':>5} {'REV':>4} {'LATEST':<10} {'ACCEPTED':<10} {'INDEX':<10}")
        lines.append('-' * 88)
        for lib in result.get('libraries', []):
            lines.append(
                f"{lib['vendor']:<14} {lib['library']:<28} {lib['delivery_count']:>5} {lib['revision_count']:>4} "
                f"{(lib.get('latest_revision') or '—'):<10} {(lib.get('accepted_revision') or '未采纳'):<10} {lib['index_status']:<10}"
            )
        return '\n'.join(lines)
    if command == 'storage-stats':
        lines.append(
            f"工作目录: {result.get('work')} | 库数 {result.get('library_count', 0)} | "
            f"总计 {_fmt_bytes(result.get('total_bytes', 0))} "
            f"(权威历史 {_fmt_bytes(result.get('authoritative_bytes', 0))} · 可重建缓存 {_fmt_bytes(result.get('rebuildable_cache_bytes', 0))})"
        )
        lines.append(f"{'VENDOR':<14} {'LIBRARY':<28} {'TOTAL':>10} {'AUTH':>10} {'CACHE':>10} {'EXCEL':>10} {'FACTS':>10}")
        lines.append('-' * 98)
        for lib in result.get('libraries', []):
            bk = lib.get('bytes_by_kind', {})
            lines.append(
                f"{lib['vendor']:<14} {lib['library']:<28} {_fmt_bytes(lib['total_bytes']):>10} "
                f"{_fmt_bytes(lib['authoritative_bytes']):>10} {_fmt_bytes(lib['rebuildable_cache_bytes']):>10} "
                f"{_fmt_bytes(bk.get('excel_cache', 0)):>10} {_fmt_bytes(bk.get('facts_pool', 0)):>10}"
            )
        return '\n'.join(lines)
    if command == 'cache-clean':
        mode = '演练模式 (dry-run，加 --apply 执行)' if result.get('dry_run') else '已执行清理'
        lines.append(f"{mode} | 命中文件 {result.get('removed_count', 0)} 个 | 可释放/已释放 {_fmt_bytes(result.get('freed_bytes', 0))}")
        for item in result.get('removed', [])[:30]:
            lines.append(f"  - [{item['kind']}] {item['vendor']}/{item['library']}/{item['file']} ({_fmt_bytes(item['bytes'])})")
        if len(result.get('removed', [])) > 30:
            lines.append(f"  ... 共 {len(result['removed'])} 项")
        return '\n'.join(lines)
    if command == 'check-pending':
        lines.append(
            f"增量批量检查 [{result.get('state')}] | 新检查 {result.get('checked_count', 0)} · "
            f"已检查跳过 {result.get('skipped_already_checked_count', 0)} · 无版本跳过 {result.get('skipped_no_revision_count', 0)} · "
            f"质检失败项 {result.get('failed_checks_total', 0)} · 异常 {result.get('error_count', 0)}"
        )
        for row in result.get('checked', []):
            lines.append(
                f"  - {row['vendor']}/{row['library']} {row['revision']} (vs {row.get('baseline') or '无基线'}) "
                f"-> {row['state']} | fail={row['failed_checks']} inconclusive={row['inconclusive_checks']} file_fail={row['failed_files']}"
            )
        for err in result.get('errors', []):
            lines.append(f"  ! {err['vendor']}/{err['library']}: {err['error']}")
        return '\n'.join(lines)
    if command in ('accept-revision', 'rollback-acceptance', 'acceptance-status'):
        if command == 'acceptance-status':
            return (
                f"{result['vendor']}/{result['library']} | 最新计算: {result.get('latest_revision') or '—'} | "
                f"人工采纳: {result.get('accepted_revision') or '未采纳'} | 一致: {'是' if result.get('is_latest_accepted') else '否'}"
            )
        return (
            f"[{result['state']}] {result['vendor']}/{result['library']} -> {result['revision']} "
            f"(原采纳: {result.get('previous_accepted') or '无'})"
        )
    return json.dumps(result, ensure_ascii=False, indent=2)


def parser():
    epilog = (
        '常用主线命令分组（历史 v1/v2/v3 兼容命令仍可调用，已从主帮助页折叠）：\n'
        '  1. 三层刷新:     refresh | refresh-sources | refresh-effective | refresh-index | refresh-status\n'
        '  2. 检查与报告:   check-pending | minimal-check-revision | minimal-check-library | minimal-render-excel | minimal-facts\n'
        '  3. 版本与采纳:   accept-revision | rollback-acceptance | acceptance-status | path-effective-preview/apply/restore\n'
        '  4. 存储与运维:   storage-stats | cache-clean | path-migrate-layout | path-check-context'
    )
    p=argparse.ArgumentParser(
        description='ai_lib_qor: IP 库来源、有效版本、FileFacts 与 QoR 检查工具',
        epilog=epilog,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument('--format',dest='output_format',choices=['json','table'],default='json',help='输出格式（默认 json，可选 table 人类可读摘要）')
    fmt_parent=argparse.ArgumentParser(add_help=False)
    fmt_parent.add_argument('--format',dest='sub_format',choices=['json','table'],default=None,help='输出格式（json 或 table）')
    sub=p.add_subparsers(dest='command',required=True,metavar='COMMAND')

    # --- Primary Path-Mode Commands (shown in --help) ---
    ref_all=sub.add_parser('refresh',parents=[fmt_parent],help='一键三层自动刷新：L1(RAW/NL) → L2(有效版本) → L3(FileIndex)')
    ref_all.add_argument('--work',required=True);ref_all.add_argument('--raw-root');ref_all.add_argument('--nl-root');ref_all.add_argument('--nl-version')
    ref_all.add_argument('--no-raw',dest='raw',action='store_false',default=True)
    ref_all.add_argument('--no-formal',dest='formal',action='store_false',default=True)
    ref_all.add_argument('--no-auto-init',dest='auto_init_from_formal',action='store_false',default=True)
    ref_all.add_argument('--verify',dest='force_verify',action='store_true',default=False)
    ref_all.add_argument('--vendor');ref_all.add_argument('--library')
    ref_l1=sub.add_parser('refresh-sources',parents=[fmt_parent],help='仅执行 L1 刷新：盘点 RAW 交付与 Formal NL 快照')
    ref_l1.add_argument('--work',required=True);ref_l1.add_argument('--raw-root');ref_l1.add_argument('--nl-root');ref_l1.add_argument('--nl-version')
    ref_l1.add_argument('--no-raw',dest='raw',action='store_false',default=True)
    ref_l1.add_argument('--no-formal',dest='formal',action='store_false',default=True)
    ref_l1.add_argument('--vendor');ref_l1.add_argument('--library')
    ref_l2=sub.add_parser('refresh-effective',parents=[fmt_parent],help='仅执行 L2 推进：从已归档 L1 自动初始化与演化有效版本')
    ref_l2.add_argument('--work',required=True)
    ref_l2.add_argument('--no-auto-init',dest='auto_init_from_formal',action='store_false',default=True)
    ref_l2.add_argument('--vendor');ref_l2.add_argument('--library')
    ref_l3=sub.add_parser('refresh-index',parents=[fmt_parent],help='仅执行 L3 刷新：按归档指纹更新有变化的库 FileIndex')
    ref_l3.add_argument('--work',required=True)
    ref_l3.add_argument('--verify',dest='force_verify',action='store_true',default=False)
    ref_l3.add_argument('--vendor');ref_l3.add_argument('--library')
    ref_st=sub.add_parser('refresh-status',parents=[fmt_parent],help='只读查看 L1/L2/L3 状态、采纳状态与最近刷新明细')
    ref_st.add_argument('--work',required=True);ref_st.add_argument('--limit',type=int,default=10)

    cpend=sub.add_parser('check-pending',parents=[fmt_parent],help='增量批量检查：仅对最新有效版本尚未检查的库执行检查（默认懒 Excel）')
    cpend.add_argument('--work',required=True);cpend.add_argument('--vendor');cpend.add_argument('--library')
    cpend.add_argument('--excel',action='store_true',help='同时立即渲染 Excel（默认仅保存 JSON + 共享事实池）')
    cpend.add_argument('--rerun',action='store_true',help='忽略已有结果，强制重新检查全部库最新版本')
    cpend.add_argument('--limit',type=int,help='单次最多检查库数量')

    for command in ('minimal-check-revision','minimal-check-library'):
        check_new=sub.add_parser(command,parents=[fmt_parent],help='执行单版本或单库有效版本检查（支持内容寻址共享池与懒 Excel）')
        for name in ('work','vendor','library'):check_new.add_argument('--'+name,required=True)
        check_new.add_argument('--revision',action='append',required=command=='minimal-check-revision')
        if command=='minimal-check-revision':
            check_new.add_argument('--baseline',help='指定较早 Effective 版本；__none__ 表示无基线')
            check_new.add_argument('--no-excel',action='store_true',help='仅保存检查结果 JSON 与内容寻址事实，不立即渲染 Excel')
        else:
            check_new.add_argument('--rerun',action='store_true',help='显式重新检查各版本；默认汇总已保存结果')
            check_new.add_argument('--no-single-excel',action='store_true',help='重跑时不预渲染单版本 Excel，仅生成整体汇总 Excel')
    render_xlsx=sub.add_parser('minimal-render-excel',parents=[fmt_parent],help='从已保存的单版本检查 JSON 按需渲染 Excel 报告')
    for name in ('work','vendor','library','check'):render_xlsx.add_argument('--'+name,required=True)
    render_xlsx.add_argument('--out',help='可选：自定义 Excel 输出路径')
    path_facts=sub.add_parser('minimal-facts',parents=[fmt_parent],help='使用路径式 file_index 为指定文件构建 FileFacts')
    for name in ('work','vendor','library','view','path'):path_facts.add_argument('--'+name,required=True)
    select=path_facts.add_mutually_exclusive_group(required=True)
    select.add_argument('--version',help='精确交付版本')
    select.add_argument('--revision',help='有效版本')

    for acc_cmd, acc_help in (
        ('accept-revision', '显式人工采纳指定有效版本（更新 accepted_effective.json，与最新计算版本分离）'),
        ('rollback-acceptance', '显式将人工采纳指针回退到历史有效版本（不改写任何有效版本历史）'),
    ):
        acc=sub.add_parser(acc_cmd,parents=[fmt_parent],help=acc_help)
        for name in ('work','vendor','library','revision','reason'):acc.add_argument('--'+name,required=True)
        acc.add_argument('--actor',default='cli')
    acc_st=sub.add_parser('acceptance-status',parents=[fmt_parent],help='只读查看库的最新计算版本与人工采纳版本状态')
    for name in ('work','vendor','library'):acc_st.add_argument('--'+name,required=True)

    sstat=sub.add_parser('storage-stats',parents=[fmt_parent],help='只读统计 work 目录磁盘占用（区分权威历史与可重建缓存）')
    sstat.add_argument('--work',required=True);sstat.add_argument('--vendor');sstat.add_argument('--library')
    cclean=sub.add_parser('cache-clean',parents=[fmt_parent],help='安全清理可重建缓存（默认 dry-run 演练，加 --apply 生效；绝不删除权威历史）')
    cclean.add_argument('--work',required=True);cclean.add_argument('--vendor');cclean.add_argument('--library')
    cclean.add_argument('--no-excel',dest='clean_excel',action='store_false',default=True,help='保留已缓存单版本 Excel')
    cclean.add_argument('--orphan-facts',dest='clean_orphan_facts',action='store_true',default=False,help='同时清理不再被任何检查引用的孤儿共享事实池文件')
    cclean.add_argument('--apply',action='store_true',help='确认执行清理（省略时仅演练预览）')

    for command in ('path-effective-preview','path-effective-apply'):
        operation=sub.add_parser(command,parents=[fmt_parent],help='预览或发布路径式有效版本变更')
        for name in ('work','vendor','library','operations'):operation.add_argument('--'+name,required=True)
        if command.endswith('apply'):operation.add_argument('--expected-parent',required=True)
    restore=sub.add_parser('path-effective-restore',parents=[fmt_parent],help='将历史成员组合恢复为新版本')
    for name in ('work','vendor','library','revision','expected-parent'):restore.add_argument('--'+name,required=True)
    context=sub.add_parser('path-check-context',parents=[fmt_parent],help='查询检查的有效成员与基线')
    for name in ('work','vendor','library','revision'):context.add_argument('--'+name,required=True)
    context.add_argument('--baseline')
    layout_migration=sub.add_parser('path-migrate-layout',parents=[fmt_parent],help='安全迁移本库路径式归档至规范子目录')
    for name in ('work','vendor','library'):layout_migration.add_argument('--'+name,required=True)
    preview_delivery=sub.add_parser('path-delivery-preview',parents=[fmt_parent],help='预览交付对当前有效成员的更新')
    for name in ('work','vendor','library','version'):preview_delivery.add_argument('--'+name,required=True)
    for command in ('path-delivery-exclude','path-delivery-include'):
        policy=sub.add_parser(command,parents=[fmt_parent],help='设置路径式交付是否参与后续有效版本更新')
        for name in ('work','vendor','library','version'):policy.add_argument('--'+name,required=True)

    # --- Legacy / Low-level Compatibility Commands (hidden from main --help, 100% preserved) ---
    d=sub.add_parser('delivery');d.add_argument('--root',required=True);d.add_argument('--config',required=True);d.add_argument('--out',required=True)
    sn=sub.add_parser('snapshot');sn.add_argument('--root',required=True);sn.add_argument('--config',required=True);sn.add_argument('--out',required=True)
    f=sub.add_parser('facts');f.add_argument('--delivery',required=True);f.add_argument('--file-id',required=True);f.add_argument('--out',required=True)
    e=sub.add_parser('facts-evidence');e.add_argument('--delivery',required=True);e.add_argument('--file-id',required=True);e.add_argument('--out',required=True)
    fa=sub.add_parser('facts-at')
    for name in ('work','runs','vendor','library','delivery-id','view','path','out'):fa.add_argument('--'+name,required=True)
    c=sub.add_parser('check');c.add_argument('--plan',required=True);c.add_argument('--out',required=True)
    r=sub.add_parser('report');r.add_argument('--check',required=True);r.add_argument('--html');r.add_argument('--excel');r.add_argument('--delivery',action='append',default=[]);r.add_argument('--facts',action='append',default=[]);r.add_argument('--formal-snapshot');r.add_argument('--source-snapshot',action='append',default=[]);r.add_argument('--target-revision');r.add_argument('--baseline-revision');r.add_argument('--accepted-revision');r.add_argument('--effective-index')
    r.add_argument('--work-root',help='v2 版本所在的 work 目录')
    scan=sub.add_parser('scan')
    scan.add_argument('--work',required=True);scan.add_argument('--runs',required=True)
    scan.add_argument('--vendor');scan.add_argument('--library')
    catalog=sub.add_parser('catalog-refresh')
    catalog.add_argument('--work',required=True);catalog.add_argument('--runs',required=True)
    latest=sub.add_parser('latest-refresh')
    latest.add_argument('--work',required=True);latest.add_argument('--vendor');latest.add_argument('--library')
    fi=sub.add_parser('file-index-refresh')
    for name in ('work','vendor','library'):fi.add_argument('--'+name,required=True)
    fi.add_argument('--rebuild',action='store_true')
    migration=sub.add_parser('delivery-simplify')
    for name in ('work','vendor','library'):migration.add_argument('--'+name,required=True)
    inventory=sub.add_parser('inventory-roots')
    inventory.add_argument('--raw-root');inventory.add_argument('--nl-root');inventory.add_argument('--output',required=True)
    inventory.add_argument('--nl-version')
    for name in ('raw','formal','index'):
        group=inventory.add_mutually_exclusive_group()
        group.add_argument('--'+name,dest='update_'+name,action='store_true',default=None)
        group.add_argument('--no-'+name,'--skip-'+name,dest='update_'+name,action='store_false')
    auto=inventory.add_mutually_exclusive_group()
    auto.add_argument('--auto-effective',dest='auto_effective',action='store_true',default=None)
    auto.add_argument('--no-auto-effective',dest='auto_effective',action='store_false')
    inventory.add_argument('--vendor');inventory.add_argument('--library')
    init=sub.add_parser('minimal-effective-init')
    for name in ('work','vendor','library','formal'):init.add_argument('--'+name,required=True)
    init.add_argument('--include',action='append')
    update=sub.add_parser('minimal-effective-update')
    for name in ('work','vendor','library','operations'):update.add_argument('--'+name,required=True)
    migration_path=sub.add_parser('path-migrate-library')
    for name in ('source','destination','vendor','library'):migration_path.add_argument('--'+name,required=True)
    simple_index=sub.add_parser('minimal-index-refresh')
    for name in ('work','vendor','library'):simple_index.add_argument('--'+name,required=True)
    simple_query=sub.add_parser('minimal-index-query')
    for name in ('work','vendor','library','view','path'):simple_query.add_argument('--'+name,required=True)
    simple_query.add_argument('--revision');simple_query.add_argument('--version')
    query=sub.add_parser('data-query')
    query.add_argument('--work',required=True);query.add_argument('--runs',default='.')
    query.add_argument('--kind',required=True,choices=['raw','simple-raw','history','history-at','history-index','index-status','index-v3','logical-history','effective','effective-v2','simple-effective','formal','simple-formal','compare','deliveries','compare-revisions','compare-revisions-logical','changed-pairs','formal-effective','effective-timeline','check-context'])
    for name in ('vendor','library','version','view','path','file-key','owner','set-id','revision','snapshot','delivery-id','other-revision'):query.add_argument('--'+name)
    query.add_argument('--revisions',nargs='+')
    eff=sub.add_parser('effective-build')
    for name in ('raw','out','owner-type','owner-id','revision'):eff.add_argument('--'+name,required=True)
    eff.add_argument('--view',action='append',required=True);eff.add_argument('--parent');eff.add_argument('--work')
    eff.add_argument('--allow-cross-library',action='store_true')
    for name in ('effective-preview','effective-apply'):
        workflow=sub.add_parser(name)
        for option in ('work','vendor','library','set-id','delivery-id'):workflow.add_argument('--'+option,required=True)
        workflow.add_argument('--include-file-key',action='append')
        if name=='effective-apply':
            workflow.add_argument('--expected-parent',required=True)
            workflow.add_argument('--expected-preview-token')
    for name in ('delivery-exclude','delivery-include'):
        policy=sub.add_parser(name)
        for option in ('work','vendor','library','set-id','delivery-id','actor','reason'):policy.add_argument('--'+option,required=True)
    for name in ('acceptance-rollback','effective-restore'):
        operation=sub.add_parser(name)
        for option in ('work','vendor','library','set-id','revision','actor','reason'):operation.add_argument('--'+option,required=True)
        if name=='effective-restore':operation.add_argument('--expected-parent',required=True)
    base=sub.add_parser('effective-formal-init')
    for name in ('formal','out','owner-type','owner-id'):base.add_argument('--'+name,required=True)
    base.add_argument('--raw',action='append',required=True);base.add_argument('--view',action='append',required=True);base.add_argument('--work')
    base.add_argument('--allow-cross-library',action='store_true')
    diff=sub.add_parser('effective-compare')
    diff.add_argument('--before',required=True);diff.add_argument('--after',required=True)
    timeline=sub.add_parser('effective-timeline')
    timeline.add_argument('--revision',action='append',required=True);timeline.add_argument('--view',required=True);timeline.add_argument('--path',required=True)
    migrate=sub.add_parser('effective-migrate')
    for name in ('work','runs','vendor','library','owner','out'):migrate.add_argument('--'+name,required=True)
    formal=sub.add_parser('formal-sync')
    formal.add_argument('--work',required=True);formal.add_argument('--runs',required=True);formal.add_argument('--formal-nl-id')
    batch=sub.add_parser('run-ip')
    for name in ('work','runs','plans','vendor','library','ip'):batch.add_argument('--'+name,required=True)
    for command in ('run-v3-revision','run-v3-ip'):
        run3=sub.add_parser(command)
        for name in ('work','runs','vendor','library','set-id','profile'):run3.add_argument('--'+name,required=True)
        run3.add_argument('--revision',action='append',required=command=='run-v3-revision')
    changed=sub.add_parser('run-changed-lef')
    for name in ('work','runs','vendor','library','set-id','before','after'):changed.add_argument('--'+name,required=True)
    changed.add_argument('--pin-liberty-path')
    run_plan=sub.add_parser('run-plan')
    run_plan.add_argument('--plan',required=True,type=Path);run_plan.add_argument('--runs',required=True)
    for name in ('work','vendor','library','ip','revision'):run_plan.add_argument('--'+name)
    evidence=sub.add_parser('run-evidence')
    for name in ('delivery','file-id','runs'):evidence.add_argument('--'+name,required=True)
    reg=sub.add_parser('register')
    for name in ('work','source','scan','metadata','mapping','version-dir'):reg.add_argument('--'+name,required=True)
    return p


def read(path):return json.loads(Path(path).read_text(encoding='utf-8'))


def avoid_source(output, root):
    if Path(output).resolve().is_relative_to(Path(root).resolve()):raise ValueError('输出不能位于 RAW 来源目录')


def run(a):
    if a.command=='refresh':
        from ai_lib_qor.application.path_refresh import refresh_all
        return refresh_all(a.work,a.raw_root,a.nl_root,nl_version=a.nl_version,raw=a.raw,formal=a.formal,
                           auto_init_from_formal=a.auto_init_from_formal,force_verify=a.force_verify,
                           vendor=a.vendor,library=a.library,actor='cli')
    if a.command=='refresh-sources':
        from ai_lib_qor.application.path_refresh import refresh_l1
        return refresh_l1(a.work,a.raw_root,a.nl_root,nl_version=a.nl_version,raw=a.raw,formal=a.formal,
                          vendor=a.vendor,library=a.library,actor='cli')
    if a.command=='refresh-effective':
        from ai_lib_qor.application.path_refresh import refresh_l2
        return refresh_l2(a.work,auto_init_from_formal=a.auto_init_from_formal,
                          vendor=a.vendor,library=a.library,actor='cli')
    if a.command=='refresh-index':
        from ai_lib_qor.application.path_refresh import refresh_l3
        return refresh_l3(a.work,force_verify=a.force_verify,vendor=a.vendor,library=a.library,actor='cli')
    if a.command=='refresh-status':
        from ai_lib_qor.application.path_refresh import refresh_status
        return refresh_status(a.work,limit=a.limit)
    if a.command=='check-pending':
        from ai_lib_qor.application.path_batch import check_pending
        return check_pending(a.work,vendor=a.vendor,library=a.library,render_excel=a.excel,rerun=a.rerun,limit=a.limit)
    if a.command in ('accept-revision','rollback-acceptance','acceptance-status'):
        from ai_lib_qor.application.path_acceptance import accept_revision,acceptance_status,rollback_acceptance
        if a.command=='acceptance-status':
            return acceptance_status(a.work,a.vendor,a.library)
        if a.command=='accept-revision':
            return accept_revision(a.work,a.vendor,a.library,a.revision,actor=a.actor,reason=a.reason)
        return rollback_acceptance(a.work,a.vendor,a.library,a.revision,actor=a.actor,reason=a.reason)
    if a.command=='storage-stats':
        from ai_lib_qor.application.path_storage import storage_stats
        return storage_stats(a.work,vendor=a.vendor,library=a.library)
    if a.command=='cache-clean':
        from ai_lib_qor.application.path_storage import clean_cache
        return clean_cache(a.work,clean_excel=a.clean_excel,clean_orphan_facts=a.clean_orphan_facts,dry_run=not a.apply,vendor=a.vendor,library=a.library)
    if a.command=='path-migrate-library':
        from ai_lib_qor.application.path_migration import migrate_legacy_library
        return migrate_legacy_library(a.source,a.destination,a.vendor,a.library)
    if a.command=='path-delivery-preview':
        from ai_lib_qor.application.minimal_effective import preview_delivery
        return preview_delivery(a.work,a.vendor,a.library,a.version)
    if a.command in ('path-delivery-exclude','path-delivery-include'):
        from ai_lib_qor.application.path_config import set_version_excluded
        return set_version_excluded(a.work,a.vendor,a.library,a.version,a.command=='path-delivery-exclude')
    if a.command=='path-migrate-layout':
        from ai_lib_qor.application.library_layout_migration import migrate_library_layout
        return migrate_library_layout(a.work,a.vendor,a.library)
    if a.command=='path-check-context':
        from ai_lib_qor.application.path_query import PathDataQuery
        result=PathDataQuery(a.work).get_check_context(a.vendor,a.library,a.revision,baseline=a.baseline)
        return {key:value for key,value in result.items() if key!='index'}
    if a.command in ('path-effective-preview','path-effective-apply','path-effective-restore'):
        from ai_lib_qor.application.minimal_effective import preview_update,apply_update,restore_revision
        args=(a.work,a.vendor,a.library)
        if a.command=='path-effective-preview':return preview_update(*args,read(a.operations))
        if a.command=='path-effective-apply':return apply_update(*args,read(a.operations),expected_parent=a.expected_parent,actor='cli')
        return restore_revision(*args,a.revision,expected_parent=a.expected_parent,actor='cli')
    if a.command in ('minimal-check-revision','minimal-check-library'):
        from ai_lib_qor.application.minimal_checks import run_revision,run_library
        if a.command=='minimal-check-revision':
            if len(a.revision)!=1:raise ValueError('单版本检查必须恰好指定一个版本')
            return run_revision(a.work,a.vendor,a.library,a.revision[0],baseline=a.baseline,render=not a.no_excel)
        return run_library(a.work,a.vendor,a.library,revisions=a.revision,rerun=a.rerun,render_single_excel=not a.no_single_excel)
    if a.command=='minimal-render-excel':
        from ai_lib_qor.application.minimal_checks import render_excel_from_check
        return {'state':'SUCCEEDED','excel':render_excel_from_check(a.work,a.vendor,a.library,a.check,a.out)}
    if a.command=='minimal-facts':
        from ai_lib_qor.application.minimal_facts import build_facts
        return build_facts(a.work,a.vendor,a.library,a.view,a.path,version=a.version,revision=a.revision)
    if a.command in ('minimal-index-refresh','minimal-index-query'):
        from ai_lib_qor.application.minimal_file_index import refresh_index,query_path
        if a.command=='minimal-index-refresh':return refresh_index(a.work,a.vendor,a.library)
        return query_path(a.work,a.vendor,a.library,a.view,a.path,revision=a.revision,version=a.version)
    if a.command in ('minimal-effective-init','minimal-effective-update'):
        from ai_lib_qor.application.minimal_effective import initialize_from_formal,update_effective
        if a.command=='minimal-effective-init':
            include=None
            if a.include is not None:
                if any('=' not in x for x in a.include):raise ValueError('成员选择格式应为 VIEW=相对路径')
                include=[tuple(x.split('=',1)) for x in a.include]
            return initialize_from_formal(a.work,a.vendor,a.library,a.formal,include=include,actor='cli')
        return update_effective(a.work,a.vendor,a.library,read(a.operations),actor='cli')
    if a.command=='inventory-roots':
        from ai_lib_qor.sources.root_inventory import build_from_roots
        from ai_lib_qor.application.path_config import load_path_config,update_options
        config=load_path_config(a.output)
        options=update_options(config,**{key:getattr(a,key) for key in ('update_raw','update_formal','update_index','auto_effective')})
        return build_from_roots(a.raw_root or config.get('raw_root'),a.nl_root or config.get('nl_root'),a.output,nl_version=a.nl_version or config.get('nl_version'),vendor=a.vendor,library=a.library,**options)
    if a.command=='delivery-simplify':
        from ai_lib_qor.sources.minimal_delivery import migrate_library
        return migrate_library(a.work,a.vendor,a.library)
    if a.command in ('delivery-exclude','delivery-include'):
        from ai_lib_qor.application.effective_workflow import set_delivery_exclusion
        return set_delivery_exclusion(a.work,a.vendor,a.library,a.set_id,a.delivery_id,excluded=a.command=='delivery-exclude',actor=a.actor,reason=a.reason)
    if a.command in ('acceptance-rollback','effective-restore'):
        from ai_lib_qor.application.effective_workflow import rollback_acceptance,restore_effective_revision
        args=(a.work,a.vendor,a.library,a.set_id,a.revision)
        return rollback_acceptance(*args,actor=a.actor,reason=a.reason) if a.command=='acceptance-rollback' else restore_effective_revision(*args,expected_parent_revision=a.expected_parent,actor=a.actor,reason=a.reason)
    if a.command in ('effective-preview','effective-apply'):
        from ai_lib_qor.application.effective_workflow import preview_effective_update, apply_effective_update
        args=(a.work,a.vendor,a.library,a.set_id,a.delivery_id)
        return preview_effective_update(*args,include_file_keys=a.include_file_key) if a.command=='effective-preview' else apply_effective_update(*args,expected_parent_revision=a.expected_parent,include_file_keys=a.include_file_key,expected_preview_token=a.expected_preview_token)
    if a.command in ('run-v3-revision','run-v3-ip'):
        from ai_lib_qor.application.v3_checks import run_v3_ip,run_v3_revision
        profile_path=Path(a.profile)
        if profile_path.is_symlink() or not profile_path.is_file():raise ValueError('检查配置不存在或为软链接')
        profile=read(profile_path)
        options={'vendor':a.vendor,'library':a.library,'set_id':a.set_id,'profile':profile}
        if a.command=='run-v3-revision':
            if len(a.revision)!=1:raise ValueError('单版本检查必须恰好指定一个版本')
            return run_v3_revision(a.work,a.runs,revision=a.revision[0],**options)
        return run_v3_ip(a.work,a.runs,revisions=a.revision,**options)
    if a.command == 'file-index-refresh':
        from ai_lib_qor.application.file_index import refresh_library_index_locked
        from ai_lib_qor.application.latest_pointers import _config
        from ai_lib_qor.sources.layout import library_folder
        from ai_lib_qor.versions.store import locked
        folder=library_folder(a.work,a.vendor,a.library)
        with locked(folder):return refresh_library_index_locked(a.work,a.vendor,a.library,_config(a.work,a.vendor,a.library),force_rebuild=a.rebuild)
    if a.command == 'facts-at':
        from ai_lib_qor.application.data_query import LibraryDataQuery, parse_recorded_file
        q=LibraryDataQuery(a.work,a.runs)
        matches=[x['record'] for x in q.deliveries if (x['record']['vendor_id'],x['record']['source_library_id'],x['record']['delivery_id'])==(a.vendor,a.library,a.delivery_id)]
        if len(matches)!=1:raise ValueError('交付不存在或不唯一')
        for item in q.deliveries:avoid_source(a.out,item['record']['source_root'])
        for snapshot in q.snapshots:avoid_source(a.out,snapshot['source_root'])
        fact=parse_recorded_file(a.work,a.runs,a.vendor,a.library,a.delivery_id,a.view,a.path)
        write_atomic(a.out,fact,immutable=True)
        return {'facts_id':fact['facts_id'],'output':a.out}
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
        args=parser().parse_args();result=run(args)
        fmt=getattr(args,'sub_format',None) or getattr(args,'output_format','json')
        print(format_table(args.command,result) if fmt=='table' else json.dumps(result,ensure_ascii=False,indent=2))
        if args.command=='check-pending':
            if result.get('error_count',0):return 1
            if result.get('failed_checks_total',0):return 2
            return 0
        if args.command=='file-index-refresh' and result.get('action')=='ORDER_UNCONFIRMED':return 1
        if args.command=='inventory-roots' and result.get('indexes_failed',0):return 1
        if args.command=='inventory-roots' and result.get('effective_pending',0) and any('自动发布' in x for x in result.get('warnings',[])):return 1
        if result.get('state') in ('FAILED','PARTIAL') or (args.command in ('scan','formal-sync') and any(x.get('status') != 'COMPLETE' or x.get('ingest',{}).get('blocked',0) or x.get('ingest',{}).get('file_index',{}).get('action') == 'ERROR' for x in result.get('sources',[]))): return 1
    except (OSError,ValueError,KeyError,ImportError) as e:print(f'错误: {e}',file=sys.stderr);return 1
    return 0

if __name__=='__main__':sys.exit(main())
