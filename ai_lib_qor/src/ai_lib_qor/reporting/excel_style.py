"""Shared visual language, CJK layout sizing, semantic highlighting, formulas and safe writers for Excel reports."""
import math
import unicodedata

MAX_CELL_CHARS = 30000
TRUNCATE_SUFFIX = '\n… [已截断，完整内容见对应 CheckResult JSON]'
FONT_NAME = 'Microsoft YaHei'

# Semantic status -> tone key ('ok' | 'fail' | 'warn' | 'info' | 'muted')
_STATUS_EXACT = {
    # Green / Healthy / Pass / Match
    'PASS': 'ok',
    'SCOPE_PASS': 'ok',
    '已覆盖范围通过': 'ok',
    'PARSED': 'ok',
    '已解析': 'ok',
    '内容一致': 'ok',
    'CURRENT_CONTENT_MATCH': 'ok',
    '一致': 'ok',
    'MATCHED_RAW': 'ok',
    '已采纳': 'ok',
    '当前已采纳': 'ok',
    '当前版本已采纳': 'ok',
    '最新且已采纳': 'ok',
    '执行完成': 'ok',
    'FRESH': 'ok',
    '已同步': 'ok',
    '可解析视图同名齐全': 'ok',
    'P4 · 采纳': 'ok',
    # Red / Fail / Error / Drift / Removed
    'FAIL': 'fail',
    '质检失败': 'fail',
    'FAILED': 'fail',
    '执行失败': 'fail',
    '解析失败': 'fail',
    '移除': 'fail',
    'REMOVED': 'fail',
    '漂移': 'fail',
    '不一致': 'fail',
    'MISSING': 'fail',
    '缺失': 'fail',
    '方向冲突': 'fail',
    'Cell缺失': 'fail',
    'Pin缺失': 'fail',
    '移除 Macro': 'fail',
    '移除 Pin': 'fail',
    '移除 Module': 'fail',
    '移除 Subckt': 'fail',
    '移除端口': 'fail',
    '未命中同名对象': 'fail',
    'P1 · 高危': 'fail',
    # Amber / Partial / Warning / Changed / Diff / Pending
    'PARTIAL': 'warn',
    'INCONCLUSIVE': 'warn',
    '部分覆盖 / 无结论': 'warn',
    '未执行有效检查 / 无结论': 'warn',
    '部分完成': 'warn',
    '部分解析': 'warn',
    '内容变化': 'warn',
    'CURRENT_CONTENT_DIFF': 'warn',
    '部分差异': 'warn',
    'PARTIAL_DIFF': 'warn',
    '来源变化': 'warn',
    'UPDATED': 'warn',
    '新增': 'warn',
    'NEW': 'warn',
    '未采纳': 'warn',
    '尚未人工采纳': 'warn',
    '待检': 'warn',
    '待检查': 'warn',
    'STALE': 'warn',
    '待刷新': 'warn',
    '待核验': 'warn',
    'UNVERIFIED': 'warn',
    '多余': 'warn',
    'Pin多余': 'warn',
    '待人工确认': 'warn',
    '无法确认': 'warn',
    '尺寸变化': 'warn',
    'Pin 方向变更': 'warn',
    '端口变更': 'warn',
    '引脚列表变更': 'warn',
    '新增 Macro': 'warn',
    '新增 Pin': 'warn',
    '新增 Module': 'warn',
    '新增 Subckt': 'warn',
    '新增端口': 'warn',
    '仅基线移除': 'warn',
    '存在差异': 'warn',
    'P2 · 索引': 'warn',
    'P2 · 待检': 'warn',
    # Blue / Info / Current / Latest / Inherited
    '最新计算': 'info',
    '当前有效': 'info',
    '首版纳入': 'info',
    'PARTIAL_MATCH': 'info',
    '部分一致': 'info',
    '来源相同': 'info',
    'INHERITED': 'info',
    'CURRENT': 'info',
    '历史版本': 'info',
    'P3 · 复核': 'info',
    'P3 · 建版': 'info',
    # Muted Gray / N/A / Not Included
    'NOT_CHECKED': 'muted',
    '未检查': 'muted',
    '暂不支持(NOT_CHECKED)': 'muted',
    '未纳入当前有效集': 'muted',
    '未纳入有效集': 'muted',
    '未对比': 'muted',
    'NOT_COMPARED': 'muted',
    '无基线未对比': 'muted',
    '无': 'muted',
    '无基线': 'muted',
    '无此View': 'muted',
    '无匹配LEF': 'muted',
    '仅RAW存在': 'muted',
    '存在（未解析）': 'muted',
    '未挂载': 'muted',
    '已移除': 'muted',
    '无法对照': 'muted',
    '待建有效版': 'muted',
    '未建有效版': 'muted',
    '未识别': 'muted',
}


def status_tone(value):
    """Map a status/verdict cell value to a semantic color tone, or None."""
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    if s in _STATUS_EXACT:
        return _STATUS_EXACT[s]
    if s.startswith('存在（未解析'):
        return 'muted'
    if s.startswith('缺少同名对象'):
        return 'warn'
    if s.startswith('差异 ('):
        return 'fail'
    if s.startswith('一致 ('):
        return 'ok'
    if '漂移' in s or '失败' in s or 'FAIL' in s:
        return 'fail'
    if '一致' in s and '不一致' not in s and '未验证' not in s:
        return 'ok'
    if '待刷新' in s or '待核验' in s or '未采纳' in s or '待检查' in s or '无法确认' in s or '已采纳 rev_' in s:
        return 'warn'
    return None


def safe_cell(value):
    """Ensure strings never exceed Excel's 32,767-char hard cell limit."""
    if value is None or isinstance(value, (int, float, bool)):
        return value
    text = str(value)
    if len(text) > MAX_CELL_CHARS:
        return text[:MAX_CELL_CHARS - len(TRUNCATE_SUFFIX)] + TRUNCATE_SUFFIX
    return text


def display_width(text: str) -> float:
    """Compute approximate visual character width accounting for East-Asian wide glyphs."""
    total = 0.0
    for ch in text:
        eaw = unicodedata.east_asian_width(ch)
        if eaw in ('W', 'F'):
            total += 2.05
        elif ch.isupper() or ch in 'MW@#%&':
            total += 1.12
        else:
            total += 1.0
    return total


def estimate_column_width(header: str, values, *, min_w: int = 10, max_w: int = 56) -> float:
    """Compute comfortable Excel column width using CJK-aware display widths."""
    best = display_width(str(header)) + 4.5
    for val in values:
        if val is None:
            continue
        if isinstance(val, tuple):
            # Support ('link', target, label) / ('formula', expr, cached) / (target, label)
            if len(val) == 3 and val[0] == 'link':
                val = val[2]
            elif len(val) == 3 and val[0] == 'formula':
                val = val[2]
            elif len(val) == 2:
                val = val[1]
        first_lines = str(val).splitlines()[:4]
        for seg in first_lines:
            w = display_width(seg) + 2.5
            if w > best:
                best = w
    return round(max(min_w, min(max_w, best)), 1)


def estimate_row_height(values, col_widths, *, min_h: float = 22.0, max_h: float = 175.0) -> float:
    """Compute wrapped row height accurately for CJK + ASCII mixed cells."""
    max_lines = 1
    for idx, val in enumerate(values):
        if val is None or idx >= len(col_widths):
            continue
        text = str(val)
        if not text:
            continue
        usable = max(col_widths[idx] - 2.5, 4.0)
        lines = 0
        for seg in text.splitlines() or ['']:
            seg_w = display_width(seg)
            lines += max(1, math.ceil(seg_w / usable)) if seg_w > 0 else 1
        if lines > max_lines:
            max_lines = lines
    return round(max(min_h, min(max_h, 10.0 + 16.5 * max_lines)), 1)


def col_letter(col_idx: int) -> str:
    """Convert 0-based column index to Excel column letters (0 -> 'A', 26 -> 'AA')."""
    n = col_idx + 1
    out = []
    while n > 0:
        n, rem = divmod(n - 1, 26)
        out.append(chr(65 + rem))
    return ''.join(reversed(out))


def build_palette(book):
    """Register the unified enterprise format palette on an xlsxwriter.Workbook."""
    base = {'font_name': FONT_NAME, 'font_size': 10}
    border = {'border': 1, 'border_color': '#CBD5E1'}
    thin_cell = {'border': 1, 'border_color': '#E2E8F0'}

    palette = {
        'title': book.add_format({
            **base, 'bold': True, 'font_size': 14,
            'font_color': '#FFFFFF', 'bg_color': '#1B365D',
            'valign': 'vcenter', 'indent': 1,
        }),
        'title_back': book.add_format({
            **base, 'bold': True, 'font_size': 9.5, 'underline': 1,
            'font_color': '#1E40AF', 'bg_color': '#DBEAFE',
            'valign': 'vcenter', 'align': 'center',
            'border': 1, 'border_color': '#93C5FD',
        }),
        'subtitle': book.add_format({
            **base, 'font_size': 9.5,
            'font_color': '#475569', 'bg_color': '#F1F5F9',
            'text_wrap': True, 'valign': 'vcenter', 'indent': 1,
            'bottom': 1, 'bottom_color': '#CBD5E1',
        }),
        'section': book.add_format({
            **base, 'bold': True, 'font_size': 10.5,
            'font_color': '#1E293B', 'bg_color': '#E2E8F0',
            'valign': 'vcenter', 'indent': 1,
            'top': 1, 'bottom': 1, 'border_color': '#94A3B8',
        }),
        'subtotal_bar': book.add_format({
            **base, 'bold': True, 'font_size': 9.5,
            'font_color': '#1E3A5F', 'bg_color': '#EFF6FF',
            'valign': 'vcenter', 'align': 'left', 'indent': 1,
            'border': 1, 'border_color': '#BFDBFE',
        }),
        'subtotal_num': book.add_format({
            **base, 'bold': True, 'font_size': 10,
            'font_color': '#1E3A5F', 'bg_color': '#EFF6FF',
            'valign': 'vcenter', 'align': 'center', 'num_format': '#,##0',
            'border': 1, 'border_color': '#BFDBFE',
        }),
        'subtotal_float': book.add_format({
            **base, 'bold': True, 'font_size': 10,
            'font_color': '#1E3A5F', 'bg_color': '#EFF6FF',
            'valign': 'vcenter', 'align': 'right', 'num_format': '#,##0.00_ ',
            'border': 1, 'border_color': '#BFDBFE',
        }),
        'header': book.add_format({
            **base, 'bold': True, 'font_size': 10,
            'font_color': '#FFFFFF', 'bg_color': '#2C4C6E',
            'text_wrap': True, 'valign': 'vcenter', 'align': 'center',
            'border': 1, 'border_color': '#1E3A5F',
        }),
        'kv_label': book.add_format({
            **base, 'bold': True, 'font_size': 10,
            'font_color': '#334155', 'bg_color': '#F8FAFC',
            'valign': 'vcenter', 'text_wrap': True, **border,
        }),
        'kv_value': book.add_format({
            **base, 'font_size': 10,
            'font_color': '#0F172A', 'bg_color': '#FFFFFF',
            'valign': 'vcenter', 'text_wrap': True, **border,
        }),
        'kv_num': book.add_format({
            **base, 'bold': True, 'font_size': 10.5,
            'font_color': '#0F172A', 'bg_color': '#FFFFFF',
            'valign': 'vcenter', 'align': 'left', 'num_format': '#,##0', **border,
        }),
        'note_row': book.add_format({
            **base, 'font_size': 9.5,
            'font_color': '#475569', 'bg_color': '#F8FAFC',
            'text_wrap': True, 'valign': 'vcenter', **thin_cell,
        }),
        'empty': book.add_format({
            **base, 'italic': True, 'font_size': 10,
            'font_color': '#64748B', 'bg_color': '#F8FAFC',
            'text_wrap': True, 'valign': 'vcenter', 'align': 'left', 'indent': 1, **thin_cell,
        }),
        'link': book.add_format({
            **base, 'bold': True, 'font_size': 10,
            'font_color': '#1D4ED8', 'underline': 1,
            'bg_color': '#FFFFFF', 'valign': 'vcenter', **thin_cell,
        }),
        'link_alt': book.add_format({
            **base, 'bold': True, 'font_size': 10,
            'font_color': '#1D4ED8', 'underline': 1,
            'bg_color': '#F8FAFC', 'valign': 'vcenter', **thin_cell,
        }),
        'link_center': book.add_format({
            **base, 'bold': True, 'font_size': 9.5,
            'font_color': '#1D4ED8', 'underline': 1, 'align': 'center',
            'bg_color': '#FFFFFF', 'valign': 'vcenter', **thin_cell,
        }),
        'link_center_alt': book.add_format({
            **base, 'bold': True, 'font_size': 9.5,
            'font_color': '#1D4ED8', 'underline': 1, 'align': 'center',
            'bg_color': '#F8FAFC', 'valign': 'vcenter', **thin_cell,
        }),
    }

    # Action callout banners with left accent stripe
    callout_tones = {
        'fail': ('#FEF2F2', '#991B1B', '#DC2626'),
        'warn': ('#FFFBEB', '#92400E', '#D97706'),
        'ok': ('#F0FDF4', '#166534', '#16A34A'),
        'info': ('#EFF6FF', '#1E40AF', '#2563EB'),
    }
    for tone, (bg, fg, accent) in callout_tones.items():
        palette['callout_' + tone] = book.add_format({
            **base, 'bold': True, 'font_size': 10,
            'font_color': fg, 'bg_color': bg,
            'text_wrap': True, 'valign': 'vcenter', 'indent': 1,
            'top': 1, 'bottom': 1, 'right': 1, 'border_color': '#CBD5E1',
            'left': 5, 'left_color': accent,
        })

    # Zebra row formats for regular text / center / integer / float
    for suffix, bg in (('', '#FFFFFF'), ('_alt', '#F8FAFC')):
        palette['text' + suffix] = book.add_format({
            **base, 'font_color': '#0F172A', 'bg_color': bg,
            'text_wrap': True, 'valign': 'vcenter', 'align': 'left', **thin_cell,
        })
        palette['center' + suffix] = book.add_format({
            **base, 'font_color': '#0F172A', 'bg_color': bg,
            'text_wrap': True, 'valign': 'vcenter', 'align': 'center', **thin_cell,
        })
        palette['int' + suffix] = book.add_format({
            **base, 'font_color': '#0F172A', 'bg_color': bg,
            'valign': 'vcenter', 'align': 'center', 'num_format': '#,##0', **thin_cell,
        })
        palette['float' + suffix] = book.add_format({
            **base, 'font_color': '#0F172A', 'bg_color': bg,
            'valign': 'vcenter', 'align': 'right', 'num_format': '#,##0.000_ ', **thin_cell,
        })

    # Semantic status badge formats
    tone_colors = {
        'ok': ('#DCFCE7', '#166534', True),
        'fail': ('#FEE2E2', '#991B1B', True),
        'warn': ('#FEF3C7', '#92400E', True),
        'info': ('#DBEAFE', '#1E40AF', True),
        'muted': ('#F1F5F9', '#64748B', False),
    }
    for tone, (bg, fg, bold) in tone_colors.items():
        palette['tone_' + tone] = book.add_format({
            **base, 'bold': bold, 'font_color': fg, 'bg_color': bg,
            'text_wrap': True, 'valign': 'vcenter', 'align': 'center', **thin_cell,
        })
        palette['tone_left_' + tone] = book.add_format({
            **base, 'bold': bold, 'font_color': fg, 'bg_color': bg,
            'text_wrap': True, 'valign': 'vcenter', 'align': 'left', **thin_cell,
        })

    return palette


def configure_sheet_print(sheet, *, header_row=None, freeze_row=None, tab_color=None):
    """Apply clean gridlines, landscape 1-page-wide printing, freeze panes, and tab color."""
    sheet.hide_gridlines(2)
    sheet.set_landscape()
    sheet.fit_to_pages(1, 0)
    sheet.set_margins(0.35, 0.35, 0.45, 0.45)
    if tab_color:
        sheet.set_tab_color(tab_color)
    if header_row is not None:
        sheet.repeat_rows(header_row)
    if freeze_row is not None:
        sheet.freeze_panes(freeze_row, 0)


def write_banner(sheet, pal, title_text: str, subtitle_text: str, ncols: int, *, back_sheet: str | None = None):
    """Write consistent row-0 title (+ optional top-right back hyperlink) + row-1 subtitle banner."""
    last = max(0, ncols - 1)
    sheet.set_row(0, 30)
    if back_sheet and last >= 2:
        sheet.merge_range(0, 0, 0, last - 1, safe_cell(title_text), pal['title'])
        escaped = str(back_sheet).replace("'", "''")
        sheet.write_url(0, last, f"internal:'{escaped}'!A1", pal['title_back'], string=f'← 返回 {back_sheet}')
    else:
        sheet.merge_range(0, 0, 0, last, safe_cell(title_text), pal['title'])
    sub_lines = max(1, len(subtitle_text.splitlines()))
    sheet.set_row(1, max(24, 14 + 14 * sub_lines))
    sheet.merge_range(1, 0, 1, last, safe_cell(subtitle_text), pal['subtitle'])
    sheet.set_row(2, 8)


def write_subtotal_row(sheet, pal, row_idx: int, ncols: int, label_text: str, formula_cells: dict):
    """Write a dynamic SUBTOTAL summary strip directly above an autofilter table.

    formula_cells maps col_index -> (formula_str, cached_value, 'int' | 'float').
    Columns not in formula_cells are filled cleanly with the subtle bar background.
    """
    sheet.set_row(row_idx, 24)
    first_formula_col = min(formula_cells.keys()) if formula_cells else ncols
    if first_formula_col > 1:
        sheet.merge_range(row_idx, 0, row_idx, first_formula_col - 1, safe_cell(label_text), pal['subtotal_bar'])
    else:
        sheet.write(row_idx, 0, safe_cell(label_text), pal['subtotal_bar'])
    for c in range(max(1, first_formula_col), ncols):
        if c in formula_cells:
            expr, cached, kind = formula_cells[c]
            fmt = pal['subtotal_float'] if kind == 'float' else pal['subtotal_num']
            sheet.write_formula(row_idx, c, expr, fmt, value=cached)
        else:
            sheet.write(row_idx, c, '', pal['subtotal_bar'])


def write_data_table(
    sheet,
    pal,
    start_row: int,
    headers: list[str],
    rows: list[list],
    *,
    col_specs: list[dict] | None = None,
    empty_message: str = '当前范围内无记录。',
    autofilter: bool = True,
    set_widths: bool = True,
    existing_widths: list[float] | None = None,
):
    """Write a styled, autofilterable table with semantic status coloring, formulas, links & CJK sizing."""
    ncols = len(headers)
    specs = col_specs or [{} for _ in range(ncols)]
    sheet.set_row(start_row, 28)
    for col, h in enumerate(headers):
        sheet.write(start_row, col, safe_cell(h), pal['header'])

    col_widths = list(existing_widths) if existing_widths else [0.0] * ncols
    if len(col_widths) < ncols:
        col_widths.extend([0.0] * (ncols - len(col_widths)))
    for col, h in enumerate(headers):
        spec = specs[col] if col < len(specs) else {}
        vals = [row[col] for row in rows if col < len(row)]
        w = estimate_column_width(
            h,
            vals,
            min_w=spec.get('min_w', 10),
            max_w=spec.get('max_w', 54),
        )
        if w > col_widths[col]:
            col_widths[col] = w
    if set_widths:
        for col, w in enumerate(col_widths):
            sheet.set_column(col, col, w)

    if not rows:
        r = start_row + 1
        sheet.set_row(r, 26)
        if ncols > 1:
            sheet.merge_range(r, 0, r, ncols - 1, safe_cell(empty_message), pal['empty'])
        else:
            sheet.write(r, 0, safe_cell(empty_message), pal['empty'])
        return r + 1, col_widths

    for idx, row in enumerate(rows):
        r = start_row + 1 + idx
        alt = '_alt' if idx % 2 == 1 else ''
        display_vals = []
        for col in range(ncols):
            val = row[col] if col < len(row) else ''
            spec = specs[col] if col < len(specs) else {}
            kind = spec.get('kind', 'text')

            # Explicit internal link cell: ('link', sheet_name, label) or (sheet_name, label) when kind=='link'
            if isinstance(val, tuple) and len(val) == 3 and val[0] == 'link':
                _, target_sheet, label = val
                safe_label = safe_cell(label)
                display_vals.append(safe_label)
                escaped = str(target_sheet).replace("'", "''")
                lfmt = pal['link_center' + alt] if kind == 'link_center' else pal['link' + alt]
                sheet.write_url(r, col, f"internal:'{escaped}'!A1", lfmt, string=str(safe_label))
                continue
            if kind in ('link', 'link_center') and isinstance(val, tuple) and len(val) == 2:
                target_sheet, label = val
                safe_label = safe_cell(label)
                display_vals.append(safe_label)
                escaped = str(target_sheet).replace("'", "''")
                lfmt = pal['link_center' + alt] if kind == 'link_center' else pal['link' + alt]
                sheet.write_url(r, col, f"internal:'{escaped}'!A1", lfmt, string=str(safe_label))
                continue

            # Explicit formula cell: ('formula', '=EXPR', cached_value)
            if isinstance(val, tuple) and len(val) == 3 and val[0] == 'formula':
                _, expr, cached = val
                display_vals.append(str(cached))
                if kind == 'float':
                    sheet.write_formula(r, col, expr, pal['float' + alt], value=float(cached))
                elif kind == 'int':
                    sheet.write_formula(r, col, expr, pal['int' + alt], value=int(cached))
                else:
                    sheet.write_formula(r, col, expr, pal['center' + alt], value=cached)
                continue

            val = safe_cell(val)
            display_vals.append(val)
            if isinstance(val, bool):
                val = '是' if val else '否'
            if kind == 'status':
                tone = status_tone(val)
                fmt = pal['tone_' + tone] if tone else pal['center' + alt]
                sheet.write(r, col, val, fmt)
            elif kind == 'int' and isinstance(val, (int, float)) and not isinstance(val, bool):
                sheet.write_number(r, col, int(val), pal['int' + alt])
            elif kind == 'float' and isinstance(val, (int, float)) and not isinstance(val, bool):
                sheet.write_number(r, col, float(val), pal['float' + alt])
            elif kind in ('center', 'link_center'):
                sheet.write(r, col, '' if val is None else val, pal['center' + alt])
            elif isinstance(val, int) and not isinstance(val, bool):
                sheet.write_number(r, col, val, pal['int' + alt])
            elif isinstance(val, float):
                sheet.write_number(r, col, val, pal['float' + alt])
            else:
                sheet.write(r, col, '' if val is None else val, pal['text' + alt])
        sheet.set_row(r, estimate_row_height(display_vals, col_widths))

    last_row = start_row + len(rows)
    if autofilter and ncols > 0:
        sheet.autofilter(start_row, 0, last_row, ncols - 1)
    return last_row + 1, col_widths
