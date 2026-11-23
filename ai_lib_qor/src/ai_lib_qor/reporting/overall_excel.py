"""Explicit multi-version library run overview workbook (v3); never infer an overall PASS."""
import json
from pathlib import Path
import xlsxwriter

from .excel_style import (
    build_palette,
    configure_sheet_print,
    write_banner,
    write_data_table,
    write_subtotal_row,
)
from .path_workbook_model import evidence_list_label, format_lef_change

_RUN_STATE_ZH = {
    'SUCCEEDED': '执行完成',
    'PARTIAL': '部分完成',
    'FAILED': '执行失败',
    'RUNNING': '运行中',
    'NOT_CHECKED': '未检查',
}


def _verdict_label(row):
    from ai_lib_qor.checks.path_plugins import evaluate_check_verdict
    if row.get('state', 'NOT_CHECKED') == 'NOT_CHECKED':
        return '未检查'
    return evaluate_check_verdict(row)['text']


def _role_label(revision, latest_rev, accepted_rev):
    is_latest = bool(latest_rev and revision == latest_rev)
    is_acc = bool(accepted_rev and revision == accepted_rev)
    if is_latest and is_acc:
        return '最新且已采纳'
    if is_latest:
        return '最新计算'
    if is_acc:
        return '当前已采纳'
    return '历史版本'


def render_overall_excel(owner, rows, output, *, acceptance=None):
    path = Path(output)
    if path.exists():
        raise FileExistsError('整体报告已存在')
    path.parent.mkdir(parents=True, exist_ok=True)

    latest_rev = (acceptance or {}).get('latest_revision') or (rows[-1]['revision'] if rows else None)
    accepted_rev = (acceptance or {}).get('accepted_revision')
    label = (
        f"IP 多版本检查汇总 · {owner['vendor']} / {owner['library']} / {owner['ip']}"
        if owner.get('ip')
        else f"库多版本检查汇总 · {owner['vendor']} / {owner['library']}"
    )
    acc_note = f"当前已采纳: {accepted_rev or '尚未人工采纳'}  |  最新计算: {latest_rev or '无'}"
    subtitle = (
        f"{acc_note}  |  仅汇总列出的版本与已检查范围；来源变化不等于内容变化；质检通过不代表全库通过或自动采纳。"
    )

    summary_headers = [
        '有效版本', '版本角色', '基线', '执行状态', '质检结论',
        '有效文件数', '已解析 / 失败', '来源新增', '来源变更', '来源移除',
        '内容变化文件', '对象变化条数', '失败检查', '不确定检查',
        'Run ID', '执行时间', '备注与错误',
    ]
    summary_specs = [
        {'kind': 'center', 'min_w': 12, 'max_w': 14},
        {'kind': 'status', 'min_w': 14, 'max_w': 16},
        {'kind': 'center', 'min_w': 11, 'max_w': 14},
        {'kind': 'status', 'min_w': 12, 'max_w': 14},
        {'kind': 'status', 'min_w': 16, 'max_w': 20},
        {'kind': 'int', 'min_w': 11, 'max_w': 13},
        {'kind': 'center', 'min_w': 13, 'max_w': 15},
        {'kind': 'int', 'min_w': 10, 'max_w': 12},
        {'kind': 'int', 'min_w': 10, 'max_w': 12},
        {'kind': 'int', 'min_w': 10, 'max_w': 12},
        {'kind': 'int', 'min_w': 13, 'max_w': 15},
        {'kind': 'int', 'min_w': 13, 'max_w': 15},
        {'kind': 'int', 'min_w': 10, 'max_w': 12},
        {'kind': 'int', 'min_w': 11, 'max_w': 13},
        {'kind': 'text', 'min_w': 28, 'max_w': 38},
        {'kind': 'center', 'min_w': 20, 'max_w': 22},
        {'kind': 'text', 'min_w': 34, 'max_w': 56},
    ]

    summary_rows = []
    check_rows = []
    change_rows = []
    any_fail = False
    any_inc = False
    totals = {'add': 0, 'chg': 0, 'rem': 0, 'obj': 0, 'fc': 0, 'ic': 0}

    for row in rows:
        rev = row['revision']
        state = row.get('state', 'NOT_CHECKED')
        summary = row.get('summary') or {}
        verdict = _verdict_label(row)
        has_base = bool(row.get('baseline'))
        has_check = state != 'NOT_CHECKED'
        parsed_cnt = row.get('parsed_files')
        failed_files = summary.get('failed_files', 0) if has_check else 0
        pf_text = f'{parsed_cnt} / {failed_files}' if parsed_cnt is not None else ('未检查' if not has_check else f'— / {failed_files}')
        member_cnt = row.get('member_count')
        src_added = row.get('index_source_added')
        src_chg = row.get('index_source_changes')
        src_rem = row.get('index_source_removed')
        if isinstance(src_added, int):
            totals['add'] += src_added
        if isinstance(src_chg, int):
            totals['chg'] += src_chg
        if isinstance(src_rem, int):
            totals['rem'] += src_rem
        content_diff = (
            summary.get('files_with_confirmed_content_change', 0)
            if (has_check and has_base and row.get('comparison_count', 1))
            else ('未检查' if not has_check else '未对比')
        )
        changes = row.get('changes') or []
        if has_check:
            totals['obj'] += len(changes)
            totals['fc'] += int(summary.get('failed_checks', 0))
            totals['ic'] += int(summary.get('inconclusive_checks', 0))
        note_parts = []
        if row.get('error'):
            note_parts.append(f"【错误】{row['error']}")
        if row.get('note'):
            note_parts.append(row['note'])

        summary_rows.append([
            rev,
            _role_label(rev, latest_rev, accepted_rev),
            row.get('baseline') or '无基线',
            _RUN_STATE_ZH.get(state, state),
            verdict,
            member_cnt if member_cnt is not None else '—',
            pf_text,
            src_added if src_added is not None else ('无基线' if not has_base else '—'),
            src_chg if src_chg is not None else ('无基线' if not has_base else '—'),
            src_rem if src_rem is not None else ('无基线' if not has_base else '—'),
            content_diff,
            len(changes) if has_check else '未检查',
            summary.get('failed_checks', 0) if has_check else '未检查',
            summary.get('inconclusive_checks', 0) if has_check else '未检查',
            row.get('run_id') or '未运行',
            row.get('run_at') or '—',
            '；'.join(note_parts),
        ])

        ev_map = row.get('facts_evidence') or {}
        for check in row.get('checks') or []:
            res = check.get('result', 'INCONCLUSIVE')
            if res == 'FAIL':
                any_fail = True
            elif res == 'INCONCLUSIVE':
                any_inc = True
            check_rows.append([
                rev,
                row.get('run_id') or '',
                check.get('check_id', ''),
                res,
                check.get('coverage', 'UNKNOWN'),
                '\n'.join(check.get('scope_file_keys') or []),
                check.get('detail', ''),
                evidence_list_label(check.get('facts_refs') or [], ev_map),
            ])
        for ch in changes:
            fmt = format_lef_change(ch, ev_map)
            change_rows.append([
                rev,
                row.get('baseline') or '无基线',
                ch.get('view', 'LEF'),
                ch.get('path', ''),
                fmt['object_type'],
                fmt['object_name'],
                fmt['diff_type'],
                fmt['old_text'],
                fmt['new_text'],
                fmt['note'],
                fmt['evidence'],
            ])

    book = xlsxwriter.Workbook(str(path), {'strings_to_formulas': False, 'strings_to_urls': False})
    book.set_properties({'title': label, 'subject': '多版本有效集演进与检查结果汇总'})
    pal = build_palette(book)
    try:
        # Sheet 00: Version Run Overview with dynamic SUBTOTAL strip
        sh0 = book.add_worksheet('00-版本运行汇总')
        has_sub = bool(summary_rows)
        hdr_row = 4 if has_sub else 3
        configure_sheet_print(sh0, header_row=hdr_row, freeze_row=hdr_row + 1, tab_color='#1B365D')
        write_banner(sh0, pal, label, subtitle, len(summary_headers))
        if has_sub:
            end_r = 5 + len(summary_rows)
            write_subtotal_row(
                sh0, pal, 3, len(summary_headers),
                f'动态筛选汇总（共 {len(summary_rows)} 个有效版本；右侧为来源增删改、对象变化及失败/不确定检查累计）：',
                {
                    7: (f'=SUBTOTAL(109,H6:H{end_r})', totals['add'], 'int'),
                    8: (f'=SUBTOTAL(109,I6:I{end_r})', totals['chg'], 'int'),
                    9: (f'=SUBTOTAL(109,J6:J{end_r})', totals['rem'], 'int'),
                    11: (f'=SUBTOTAL(109,L6:L{end_r})', totals['obj'], 'int'),
                    12: (f'=SUBTOTAL(109,M6:M{end_r})', totals['fc'], 'int'),
                    13: (f'=SUBTOTAL(109,N6:N{end_r})', totals['ic'], 'int'),
                },
            )
        write_data_table(
            sh0, pal, hdr_row, summary_headers, summary_rows,
            col_specs=summary_specs,
            empty_message='当前库暂无有效版本运行记录。',
            autofilter=True, set_widths=True,
        )

        # Sheet 01: Per-Check Breakdown
        check_headers = ['有效版本', 'Run ID', '检查项ID', '结果', '覆盖度', '涉及文件', '结果说明', '事实证据文件']
        check_specs = [
            {'kind': 'center', 'min_w': 12, 'max_w': 14},
            {'kind': 'text', 'min_w': 26, 'max_w': 36},
            {'kind': 'text', 'min_w': 24, 'max_w': 30},
            {'kind': 'status', 'min_w': 14, 'max_w': 16},
            {'kind': 'center', 'min_w': 12, 'max_w': 14},
            {'kind': 'text', 'min_w': 32, 'max_w': 48},
            {'kind': 'text', 'min_w': 38, 'max_w': 58},
            {'kind': 'text', 'min_w': 26, 'max_w': 44},
        ]
        sh1 = book.add_worksheet('01-逐项检查汇总')
        tab1 = '#DC2626' if any_fail else ('#D97706' if any_inc else '#16A34A')
        configure_sheet_print(sh1, header_row=3, freeze_row=4, tab_color=tab1)
        write_banner(
            sh1, pal, f'01 · 逐项工程检查汇总 — {owner["vendor"]} / {owner["library"]}',
            subtitle, len(check_headers), back_sheet='00-版本运行汇总',
        )
        write_data_table(
            sh1, pal, 3, check_headers, check_rows,
            col_specs=check_specs,
            empty_message='所选版本中暂无已保存的工程检查记录。',
            autofilter=True, set_widths=True,
        )

        # Sheet 02: Cross-Version Object Changes
        chg_headers = ['有效版本', '基线', 'View', '相对路径', '对象类型', '对象名称', '差异类型', '旧值', '新值', '说明与变化量', '证据文件']
        chg_specs = [
            {'kind': 'center', 'min_w': 12, 'max_w': 14},
            {'kind': 'center', 'min_w': 11, 'max_w': 14},
            {'kind': 'center', 'min_w': 10, 'max_w': 12},
            {'kind': 'text', 'min_w': 28, 'max_w': 46},
            {'kind': 'center', 'min_w': 10, 'max_w': 14},
            {'kind': 'text', 'min_w': 22, 'max_w': 36},
            {'kind': 'status', 'min_w': 14, 'max_w': 18},
            {'kind': 'text', 'min_w': 16, 'max_w': 28},
            {'kind': 'text', 'min_w': 16, 'max_w': 28},
            {'kind': 'text', 'min_w': 28, 'max_w': 52},
            {'kind': 'text', 'min_w': 26, 'max_w': 44},
        ]
        sh2 = book.add_worksheet('02-跨版本对象变化')
        configure_sheet_print(sh2, header_row=3, freeze_row=4, tab_color='#D97706' if change_rows else '#64748B')
        write_banner(
            sh2, pal, f'02 · 跨版本对象变化演进 — {owner["vendor"]} / {owner["library"]}',
            subtitle, len(chg_headers), back_sheet='00-版本运行汇总',
        )
        write_data_table(
            sh2, pal, 3, chg_headers, change_rows,
            col_specs=chg_specs,
            empty_message='所选历次有效版本对比均未发现 LEF 对象或引脚变化。',
            autofilter=True, set_widths=True,
        )
    finally:
        book.close()
    return path
