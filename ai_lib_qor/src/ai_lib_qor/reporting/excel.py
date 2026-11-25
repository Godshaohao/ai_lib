"""Render high-signal v3 Excel review workbooks from path-mode CheckResult."""
from pathlib import Path
import xlsxwriter

from .excel_style import (
    build_palette,
    configure_sheet_print,
    estimate_row_height,
    safe_cell,
    status_tone,
    write_banner,
    write_data_table,
    write_subtotal_row,
)
from .path_workbook_model import build_path_workbook_spec


def _write_kv_block(sheet, pal, start_row, pairs, col_widths):
    r = start_row
    for k1, v1, k2, v2 in pairs:
        s1, s2 = safe_cell(v1), safe_cell(v2)
        sheet.write(r, 0, safe_cell(k1), pal['kv_label'])
        t1 = status_tone(s1) if isinstance(s1, str) else None
        if t1:
            sheet.write(r, 1, s1, pal['tone_left_' + t1])
        elif isinstance(s1, int) and not isinstance(s1, bool):
            sheet.write_number(r, 1, s1, pal['kv_num'])
        else:
            sheet.write(r, 1, '' if s1 is None else s1, pal['kv_value'])

        sheet.write(r, 2, safe_cell(k2), pal['kv_label'])
        t2 = status_tone(s2) if isinstance(s2, str) else None
        if t2:
            sheet.write(r, 3, s2, pal['tone_left_' + t2])
        elif isinstance(s2, int) and not isinstance(s2, bool):
            sheet.write_number(r, 3, s2, pal['kv_num'])
        else:
            sheet.write(r, 3, '' if s2 is None else s2, pal['kv_value'])

        sheet.set_row(r, estimate_row_height([k1, s1, k2, s2], col_widths, min_h=23.0))
        r += 1
    return r


def _render_overview(sheet, pal, spec):
    widths = [24.0, 38.0, 34.0, 56.0]
    for idx, w in enumerate(widths):
        sheet.set_column(idx, idx, w)
    configure_sheet_print(sheet, freeze_row=3, tab_color=spec.get('tab_color'))
    sheet.fit_to_pages(1, 1)
    write_banner(sheet, pal, spec['title'], spec['subtitle'], 4)

    r = 3
    # Prominent decision action callout banner
    callout = spec.get('action_callout')
    if callout:
        tone, text = callout
        safe_txt = safe_cell(text)
        sheet.merge_range(r, 0, r, 3, safe_txt, pal.get('callout_' + tone, pal['callout_info']))
        sheet.set_row(r, estimate_row_height([safe_txt], [sum(widths) - 4.0], min_h=30.0))
        r += 1
        sheet.set_row(r, 8)
        r += 1

    sheet.set_row(r, 23)
    sheet.merge_range(r, 0, r, 3, '一、版本、质检与人工采纳摘要', pal['section'])
    r = _write_kv_block(sheet, pal, r + 1, spec['identity_cards'], widths)

    sheet.set_row(r, 8)
    r += 1
    sheet.set_row(r, 23)
    sheet.merge_range(r, 0, r, 3, '二、覆盖范围与关键指标', pal['section'])
    r = _write_kv_block(sheet, pal, r + 1, spec['kpi_cards'], widths)

    sheet.set_row(r, 8)
    r += 1
    sheet.set_row(r, 23)
    sheet.merge_range(r, 0, r, 3, '三、工作表目录导航（点击表名直达；记录数为动态公式）', pal['section'])
    r, _ = write_data_table(
        sheet, pal, r + 1,
        spec['directory_headers'], spec['directory_rows'],
        col_specs=spec['directory_col_specs'],
        autofilter=False, set_widths=False, existing_widths=widths,
    )

    sheet.set_row(r, 8)
    r += 1
    sheet.set_row(r, 23)
    sheet.merge_range(r, 0, r, 3, '四、证据边界与工程红线', pal['section'])
    r += 1
    merged_span_w = widths[1] + widths[2] + widths[3]
    for label, text in spec['boundaries']:
        safe_txt = safe_cell(text)
        sheet.write(r, 0, safe_cell(label), pal['kv_label'])
        sheet.merge_range(r, 1, r, 3, safe_txt, pal['note_row'])
        sheet.set_row(r, estimate_row_height([label, safe_txt], [widths[0], merged_span_w], min_h=23.0))
        r += 1


def _render_provenance(sheet, pal, spec):
    ncols = max(len(spec['formal_headers']), len(spec['prov_headers']))
    configure_sheet_print(sheet, header_row=4, freeze_row=5, tab_color=spec.get('tab_color'))
    write_banner(sheet, pal, spec['title'], spec['subtitle'], ncols, back_sheet=spec.get('back_sheet'))

    r = 3
    sheet.set_row(r, 24)
    sheet.merge_range(r, 0, r, ncols - 1, '一、Formal NL 正式库软链对照', pal['section'])
    r, widths = write_data_table(
        sheet, pal, r + 1,
        spec['formal_headers'], spec['formal_rows'],
        col_specs=spec['formal_col_specs'],
        empty_message=spec['formal_empty'],
        autofilter=True, set_widths=False,
    )

    sheet.set_row(r, 14)
    r += 1
    sheet.set_row(r, 24)
    sheet.merge_range(r, 0, r, ncols - 1, '二、解析证据溯源清单（内容寻址 FileFacts 共享池）', pal['section'])
    r, widths = write_data_table(
        sheet, pal, r + 1,
        spec['prov_headers'], spec['prov_rows'],
        col_specs=spec['prov_col_specs'],
        empty_message=spec['prov_empty'],
        autofilter=False, set_widths=True, existing_widths=widths,
    )


def render_excel(report, path):
    path = Path(path)
    if path.exists():
        raise FileExistsError(f'报告已存在: {path}')
    if report.get('schema_version') != 'check_result.path.v1':
        raise ValueError('仅支持 check_result.path.v1 报告渲染')
    wb_spec = build_path_workbook_spec(report)
    path.parent.mkdir(parents=True, exist_ok=True)
    book = xlsxwriter.Workbook(str(path), {'strings_to_formulas': False, 'strings_to_urls': False})
    book.set_properties(wb_spec['properties'])
    pal = build_palette(book)
    try:
        for sh_spec in wb_spec['sheets']:
            sheet = book.add_worksheet(sh_spec['name'])
            kind = sh_spec['kind']
            if kind == 'overview':
                _render_overview(sheet, pal, sh_spec)
            elif kind == 'provenance':
                _render_provenance(sheet, pal, sh_spec)
            else:
                headers = sh_spec['headers']
                subtotal = sh_spec.get('subtotal')
                header_row = 4 if subtotal else 3
                configure_sheet_print(
                    sheet,
                    header_row=header_row,
                    freeze_row=header_row + 1,
                    tab_color=sh_spec.get('tab_color'),
                )
                write_banner(
                    sheet, pal, sh_spec['title'], sh_spec['subtitle'],
                    len(headers), back_sheet=sh_spec.get('back_sheet'),
                )
                if subtotal:
                    write_subtotal_row(sheet, pal, 3, len(headers), subtotal['label'], subtotal['formulas'])
                write_data_table(
                    sheet, pal, header_row,
                    headers, sh_spec['rows'],
                    col_specs=sh_spec.get('col_specs'),
                    empty_message=sh_spec.get('empty_message', '当前范围内无记录。'),
                    autofilter=True, set_widths=True,
                )
    finally:
        book.close()
    return path
