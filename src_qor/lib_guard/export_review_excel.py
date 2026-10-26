#!/usr/bin/env python3
"""Export normalized per-IP review evidence to one filterable Excel workbook."""

from __future__ import annotations

from pathlib import Path
import sys
from typing import Any

MAX_CELL_TEXT_LENGTH = 32767


def _cell_value(value: Any) -> Any:
    if isinstance(value, (dict, list, tuple, set)):
        value = "; ".join(str(item) for item in value) if isinstance(value, (list, tuple, set)) else str(value)
    if isinstance(value, str) and value.startswith(("=", "+", "-", "@")):
        return "'" + value
    if value is None:
        return ""
    if isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _validate_cell_text(value: Any, sheet: str, row: int, column: int) -> None:
    if isinstance(value, str) and len(value) > MAX_CELL_TEXT_LENGTH:
        raise ValueError(
            f"Excel 单元格文本超限：Sheet={sheet[:31]}，行={row}，列={column}，"
            f"实际长度={len(value)}，限制={MAX_CELL_TEXT_LENGTH}"
        )


def export_review_excel(
    sheets: dict[str, list[dict[str, Any]]],
    output_path: str | Path,
    *,
    scope_note: str = "各行保留独立 IP 与证据来源；观察数量不代表必需交付或发布结论。",
) -> Path:
    """Write named record tables, filters, frozen headers and readable widths."""
    try:
        import xlsxwriter
    except ImportError as exc:
        raise RuntimeError(
            f"当前 Python {sys.executable} 无法导入 XlsxWriter；"
            "请用已配置 XlsxWriter 的同一解释器启动工作台和导出命令。"
        ) from exc

    from .review_runner import SHEET_HEADERS

    prepared_sheets = []
    note_value = _cell_value(scope_note)
    for sheet_name, records in sheets.items():
        sheet_label = sheet_name[:31]
        if not isinstance(records, list):
            raise ValueError(f"{sheet_label}: 表数据必须是列表")
        raw_headers = SHEET_HEADERS.get(sheet_name) or (list(records[0]) if records else ["结果"])
        if len(raw_headers) != len(set(raw_headers)):
            raise ValueError(f"{sheet_label}: 列名重复")
        headers = [_cell_value(header) for header in raw_headers]
        rows = [[_cell_value(record.get(header)) for header in raw_headers] for record in records]

        _validate_cell_text(_cell_value(sheet_name), sheet_label, 1, 1)
        _validate_cell_text(note_value, sheet_label, 2, 1)
        for column, header in enumerate(headers, start=1):
            _validate_cell_text(header, sheet_label, 4, column)
        for row_index, values in enumerate(rows, start=5):
            for column, value in enumerate(values, start=1):
                _validate_cell_text(value, sheet_label, row_index, column)
        prepared_sheets.append((sheet_name, records, headers, rows))

    destination = Path(output_path).expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    workbook = xlsxwriter.Workbook(str(destination), {"strings_to_formulas": False, "strings_to_urls": False})
    workbook.set_properties({"title": "IP 库检查结果", "subject": "按 IP 汇总的工程检查与证据", "author": "src_qor/lib_guard"})
    title_fmt = workbook.add_format({"bold": True, "font_size": 16, "font_color": "#16324F", "bg_color": "#EAF1F7", "valign": "vcenter"})
    note_fmt = workbook.add_format({"font_color": "#526271", "text_wrap": True, "valign": "top"})
    text_fmt = workbook.add_format({"text_wrap": True, "valign": "top"})
    number_fmt = workbook.add_format({"num_format": "0", "valign": "top"})
    header_fmt = workbook.add_format({"bold": True, "font_color": "#FFFFFF", "bg_color": "#315A76", "text_wrap": True, "valign": "vcenter"})

    for sheet_name, records, headers, rows in prepared_sheets:
        sheet = workbook.add_worksheet(sheet_name[:31])
        sheet.hide_gridlines(2)
        sheet.merge_range(0, 0, 0, len(headers) - 1, _cell_value(sheet_name), title_fmt)
        sheet.set_row(0, 28)
        sheet.merge_range(1, 0, 1, len(headers) - 1, note_value, note_fmt)
        sheet.set_row(1, 34)
        first_data_row = 3
        column_widths = []
        for column, header in enumerate(headers):
            values = [str(row[column]) for row in rows if row[column] not in (None, "")]
            width = min(max([len(header), *(min(len(value.splitlines()[0]), 48) for value in values)] or [12]) + 2, 52)
            column_widths.append(max(width, 12))
        end_data_row = first_data_row + max(len(rows), 1)
        table_columns = [{"header": header} for header in headers]
        sheet.add_table(first_data_row, 0, end_data_row, len(headers) - 1, {
            "name": f"ReviewTable{len(workbook.worksheets())}",
            "style": "Table Style Medium 2",
            "columns": table_columns,
            "data": rows,
        })
        sheet.freeze_panes(first_data_row + 1, 0)
        sheet.set_row(first_data_row, 32, header_fmt)
        for column, width in enumerate(column_widths):
            nonempty = [row[column] for row in rows if row[column] not in (None, "")]
            cell_format = number_fmt if nonempty and all(isinstance(value, (int, float)) and not isinstance(value, bool) for value in nonempty) else text_fmt
            sheet.set_column(column, column, width, cell_format)
        for row_index, values in enumerate(rows, start=first_data_row + 1):
            estimated_lines = 1
            for column, value in enumerate(values):
                if value in (None, ""):
                    continue
                width = column_widths[column]
                segments = str(value).splitlines() or [""]
                estimated_lines = max(estimated_lines, sum(max(1, (len(segment) + width - 1) // width) for segment in segments))
            sheet.set_row(row_index, min(18 + 14 * estimated_lines, 88))
        sheet.set_default_row(30)
    workbook.close()
    return destination
