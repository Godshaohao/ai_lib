"""Read-only workspace-level cross-library overview Excel exporter (v3; never scans RAW or parses)."""
import json
import os
from pathlib import Path
import uuid
import xlsxwriter

from ai_lib_qor.application.path_query import latest_check_for_revision as _latest_check_for_revision
from ai_lib_qor.application.path_refresh import refresh_status
from ai_lib_qor.application.path_storage import storage_stats
from ai_lib_qor.sources.timestamps import utc_text
from .excel_style import (
    build_palette,
    configure_sheet_print,
    safe_cell,
    write_banner,
    write_data_table,
    write_subtotal_row,
)


def _fmt_bytes(n: int) -> str:
    val = float(n)
    for unit in ('B', 'KB', 'MB', 'GB'):
        if val < 1024 or unit == 'GB':
            return f'{val:.1f} {unit}' if unit != 'B' else f'{int(val)} B'
        val /= 1024.0
    return f'{n} B'


def _index_label(status):
    return {'FRESH': '已同步', 'STALE': '待刷新', 'MISSING': '缺失', 'UNVERIFIED': '待核验'}.get(status, status)


def render_work_overview_excel(work, output, *, overwrite=False):
    """Render a read-only cross-library overview Excel workbook from saved work/ data."""
    work_path = Path(work).resolve(strict=True)
    out_path = Path(output)
    if out_path.is_symlink():
        raise ValueError('输出路径不能为软链接')
    if out_path.exists() and not overwrite:
        raise FileExistsError(f'全库总览报告已存在: {out_path}')
    out_path.parent.mkdir(parents=True, exist_ok=True)

    status = refresh_status(work_path, limit=5)
    st = storage_stats(work_path)
    bytes_by_lib = {(x['vendor'], x['library']): x['total_bytes'] for x in st.get('libraries', [])}

    overview_rows = []
    todo_items = []
    verdict_counts = {'pass': 0, 'fail': 0, 'partial': 0, 'pending': 0}
    sum_deliv = sum_revs = sum_fc = sum_ic = sum_ff = 0

    for lib in status.get('libraries', []):
        v = lib['vendor']
        name = lib['library']
        d_cnt = int(lib.get('delivery_count', 0))
        r_cnt = int(lib.get('revision_count', 0))
        sum_deliv += d_cnt
        sum_revs += r_cnt
        latest_rev = lib.get('latest_revision')
        acc_rev = lib.get('accepted_revision')
        idx_st = lib.get('index_status', 'MISSING')
        idx_lbl = _index_label(idx_st)

        if not latest_rev:
            acc_lbl = '待建有效版'
        elif acc_rev == latest_rev:
            acc_lbl = '最新且已采纳'
        elif acc_rev:
            acc_lbl = f'已采纳 {acc_rev}（落后最新）'
        else:
            acc_lbl = '尚未人工采纳'

        chk = _latest_check_for_revision(work_path, v, name, latest_rev)
        if not latest_rev:
            verdict = '未建有效版'
            base_lbl = '—'
            fc = ic = ff = '—'
            run_at = '—'
            rep_name = '—'
        elif chk is None:
            verdict = '待检查'
            verdict_counts['pending'] += 1
            base_lbl = '—'
            fc = ic = ff = '—'
            run_at = '—'
            rep_name = '—'
        else:
            verdict = chk['verdict']
            if verdict == '质检失败':
                verdict_counts['fail'] += 1
            elif verdict == '已覆盖范围通过':
                verdict_counts['pass'] += 1
            else:
                verdict_counts['partial'] += 1
            base_lbl = chk['baseline'] or '无基线'
            fc = chk['failed_checks']
            ic = chk['inconclusive_checks']
            ff = chk['failed_files']
            sum_fc += int(fc)
            sum_ic += int(ic)
            sum_ff += int(ff)
            run_at = chk['run_at'] or '—'
            rep_name = chk['report_name']

        size_txt = _fmt_bytes(bytes_by_lib.get((v, name), 0))
        overview_rows.append([
            v, name, d_cnt, r_cnt,
            latest_rev or '无', acc_rev or '未采纳', acc_lbl, idx_lbl,
            verdict, base_lbl, fc, ic, ff, run_at, rep_name, size_txt,
        ])

        if verdict == '质检失败':
            todo_items.append((1, 'P1 · 高危', '质检失败', v, name, verdict, latest_rev, acc_rev or '未采纳', f'失败检查 {fc} / 失败文件 {ff}；请打开单版本报告核查差异并修复后再采纳'))
        if idx_st in ('MISSING', 'STALE', 'UNVERIFIED'):
            idx_todo_kind = {'MISSING': '索引缺失', 'STALE': '索引待刷新', 'UNVERIFIED': '索引待核验'}[idx_st]
            todo_items.append((2, 'P2 · 索引', idx_todo_kind, v, name, idx_lbl, latest_rev or '无', acc_rev or '未采纳', '执行 refresh-index 同步或补建归档指纹索引'))
        if latest_rev and chk is None:
            todo_items.append((3, 'P2 · 待检', '最新版未检查', v, name, '待检查', latest_rev, acc_rev or '未采纳', '执行 check-pending 或单版本检查'))
        elif chk is not None and chk.get('quality_code') == 'PARTIAL':
            todo_items.append((4, 'P3 · 复核', '部分覆盖/无结论', v, name, verdict, latest_rev, acc_rev or '未采纳', f'不确定检查 {ic} 或含未解析视图（如 GDS/DB）；需人工确认覆盖边界'))
        if chk is not None and (chk.get('tooling_status') or {}).get('is_stale'):
            reasons = '; '.join((chk.get('tooling_status') or {}).get('reasons') or [])
            todo_items.append((4, 'P3 · 升级', '解析器已升级', v, name, 'STALE_TOOLING', latest_rev, acc_rev or '未采纳', f'现有检查基于旧版解析器（{reasons}）；可执行 check-pending --include-outdated 重检'))
        if not latest_rev:
            todo_items.append((5, 'P3 · 建版', '待建有效版本', v, name, '未建有效版', '无', '未采纳', '检查 Formal NL 快照或手工初始化首版有效版本'))
        elif chk is not None and verdict != '质检失败' and acc_rev != latest_rev:
            todo_items.append((6, 'P4 · 采纳', '新版待人工采纳', v, name, acc_lbl, latest_rev, acc_rev or '未采纳', '确认质检报告无阻塞问题后执行 accept-revision 显式采纳'))

    todo_items.sort(key=lambda x: (x[0], x[3], x[4]))
    todo_rows = [list(x[1:]) for x in todo_items]

    totals = status.get('totals', {})
    gen_at = utc_text()
    subtitle = (
        f"工作目录: {work_path}  |  导出时间 (UTC): {gen_at}  |  "
        f"只读汇总已保存状态（不触发 RAW 扫描或重解析）；已覆盖通过不代表全库通过或人工采纳。"
    )

    tmp = out_path.parent / f'.{out_path.stem}.{uuid.uuid4().hex}.tmp.xlsx'
    book = xlsxwriter.Workbook(str(tmp), {'strings_to_formulas': False, 'strings_to_urls': False})
    book.set_properties({'title': 'ai_lib_qor 全库状态总览', 'subject': '跨供应商与来源库的版本、质检与人工采纳总表'})
    pal = build_palette(book)
    try:
        # Sheet 00: Workspace Overview
        sh0 = book.add_worksheet('00-全库总览')
        headers = [
            'Vendor', 'Library', '交付版本数', '有效版本数', '最新计算版本',
            '人工采纳版本', '采纳状态', '索引状态', '最新版质检结论',
            '对比基线', '失败检查', '不确定检查', '失败文件',
            '最近检查时间', '最近检查报告', '占用空间',
        ]
        specs = [
            {'kind': 'text', 'min_w': 14, 'max_w': 20},
            {'kind': 'text', 'min_w': 24, 'max_w': 36},
            {'kind': 'int', 'min_w': 11, 'max_w': 13},
            {'kind': 'int', 'min_w': 11, 'max_w': 13},
            {'kind': 'center', 'min_w': 13, 'max_w': 15},
            {'kind': 'center', 'min_w': 13, 'max_w': 15},
            {'kind': 'status', 'min_w': 18, 'max_w': 26},
            {'kind': 'status', 'min_w': 11, 'max_w': 14},
            {'kind': 'status', 'min_w': 16, 'max_w': 20},
            {'kind': 'center', 'min_w': 11, 'max_w': 14},
            {'kind': 'int', 'min_w': 10, 'max_w': 12},
            {'kind': 'int', 'min_w': 11, 'max_w': 13},
            {'kind': 'int', 'min_w': 10, 'max_w': 12},
            {'kind': 'center', 'min_w': 20, 'max_w': 22},
            {'kind': 'text', 'min_w': 30, 'max_w': 46},
            {'kind': 'center', 'min_w': 12, 'max_w': 14},
        ]
        ncols = len(headers)
        has_sub = bool(overview_rows)
        hdr_row = 5 if has_sub else 4
        configure_sheet_print(sh0, header_row=hdr_row, freeze_row=hdr_row + 1, tab_color='#1B365D')
        write_banner(sh0, pal, 'ai_lib_qor · 全工作区来源库状态总览', subtitle, ncols)

        # Row 3: KPI summary strip + jump link to Todo sheet
        accepted_libs = sum(1 for x in status.get('libraries', []) if x.get('accepted_revision'))
        kpi_text = (
            f"供应商 {totals.get('vendors', 0)}  ·  来源库 {totals.get('libraries', 0)}  ·  "
            f"已建有效版 {totals.get('libraries_with_effective', 0)}  ·  已人工采纳 {accepted_libs}  ·  "
            f"最新版质检: 通过 {verdict_counts['pass']} / 失败 {verdict_counts['fail']} / 部分 {verdict_counts['partial']} / 待检 {verdict_counts['pending']}  ·  "
            f"总存储 {_fmt_bytes(st.get('total_bytes', 0))} (权威 {_fmt_bytes(st.get('authoritative_bytes', 0))} · 缓存 {_fmt_bytes(st.get('rebuildable_cache_bytes', 0))})"
        )
        sh0.set_row(3, 25)
        sh0.merge_range(3, 0, 3, ncols - 3, safe_cell(kpi_text), pal['section'])
        sh0.merge_range(3, ncols - 2, 3, ncols - 1, '', pal['link_center'])
        sh0.write_url(3, ncols - 2, "internal:'01-待处理与风险清单'!A1", pal['link_center'], string=f'待处理与风险 ({len(todo_rows)}) →')

        # Row 4: Dynamic SUBTOTAL row directly above table header
        if has_sub:
            end_r = 6 + len(overview_rows)
            write_subtotal_row(
                sh0, pal, 4, ncols,
                '动态筛选汇总（筛选 Vendor / 状态后自动重算）：',
                {
                    2: (f'=SUBTOTAL(109,C7:C{end_r})', sum_deliv, 'int'),
                    3: (f'=SUBTOTAL(109,D7:D{end_r})', sum_revs, 'int'),
                    10: (f'=SUBTOTAL(109,K7:K{end_r})', sum_fc, 'int'),
                    11: (f'=SUBTOTAL(109,L7:L{end_r})', sum_ic, 'int'),
                    12: (f'=SUBTOTAL(109,M7:M{end_r})', sum_ff, 'int'),
                },
            )

        write_data_table(
            sh0, pal, hdr_row, headers, overview_rows,
            col_specs=specs,
            empty_message='当前工作区尚无已归档的来源库记录。',
            autofilter=True, set_widths=True,
        )

        # Sheet 01: Prioritized Todo & Risk List
        todo_headers = ['优先级', '待办类型', 'Vendor', 'Library', '当前状态', '最新有效版本', '人工采纳版本', '建议动作']
        todo_specs = [
            {'kind': 'status', 'min_w': 13, 'max_w': 15},
            {'kind': 'center', 'min_w': 15, 'max_w': 18},
            {'kind': 'text', 'min_w': 14, 'max_w': 20},
            {'kind': 'text', 'min_w': 24, 'max_w': 38},
            {'kind': 'status', 'min_w': 16, 'max_w': 24},
            {'kind': 'center', 'min_w': 13, 'max_w': 15},
            {'kind': 'center', 'min_w': 13, 'max_w': 15},
            {'kind': 'text', 'min_w': 36, 'max_w': 60},
        ]
        tab1 = '#DC2626' if verdict_counts['fail'] > 0 else ('#D97706' if todo_rows else '#16A34A')
        sh1 = book.add_worksheet('01-待处理与风险清单')
        configure_sheet_print(sh1, header_row=3, freeze_row=4, tab_color=tab1)
        write_banner(
            sh1, pal, '01 · 待处理与风险清单（按优先级排序）',
            subtitle, len(todo_headers), back_sheet='00-全库总览',
        )
        write_data_table(
            sh1, pal, 3, todo_headers, todo_rows,
            col_specs=todo_specs,
            empty_message='所有已归档库索引同步、最新版均已检查通过且已完成人工采纳。',
            autofilter=True, set_widths=True,
        )
    finally:
        book.close()

    try:
        os.replace(tmp, out_path)
    finally:
        tmp.unlink(missing_ok=True)
    return {
        'state': 'SUCCEEDED',
        'work': str(work_path),
        'excel': str(out_path),
        'library_count': len(overview_rows),
        'todo_count': len(todo_rows),
        'verdict_counts': verdict_counts,
    }
