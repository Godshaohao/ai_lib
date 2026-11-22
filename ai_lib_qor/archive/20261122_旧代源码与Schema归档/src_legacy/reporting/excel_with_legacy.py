"""Render a filterable review workbook from one v3 report model."""
from pathlib import Path
import math
import unicodedata
import xlsxwriter
from .workbook_model import build_sheets


def render_excel(report, path):
    path=Path(path)
    if path.exists():raise FileExistsError(f'报告已存在: {path}')
    if report.get('schema_version')=='check_result.path.v1':
        from .path_workbook_model import build_path_sheets
        sheets=build_path_sheets(report)
    else:sheets=build_sheets(report)
    for name,headers,rows in sheets:
        for row in [headers,*rows]:
            if any(len(str(x))>32767 for x in row if x is not None):raise ValueError(f'{name}: 单元格内容超过 Excel 限制')
    path.parent.mkdir(parents=True,exist_ok=True)
    book=xlsxwriter.Workbook(str(path), {'strings_to_formulas':False,'strings_to_urls':False})
    book.set_properties({'title':'IP 库检查结果','subject':'v3 检查结果与明确提供的来源事实'})
    title=book.add_format({'bold':True,'font_size':16,'font_color':'#16324F','bg_color':'#EAF1F7','valign':'vcenter'})
    note=book.add_format({'font_color':'#526271','text_wrap':True,'valign':'top'})
    text=book.add_format({'text_wrap':True,'valign':'top'})
    header=book.add_format({'bold':True,'font_color':'#FFFFFF','bg_color':'#315A76','text_wrap':True,'valign':'vcenter'})
    try:
        for index,(name,headers,rows) in enumerate(sheets,1):
            sheet=book.add_worksheet(name);sheet.hide_gridlines(2);sheet.set_row(0,28);sheet.set_row(1,34);sheet.set_row(3,32,header);sheet.set_default_row(30)
            sheet.merge_range(0,0,0,len(headers)-1,name,title)
            scope='本表只使用本次 CheckResult 和明确提供的来源记录；未提供不表示不存在或通过。'
            sheet.merge_range(1,0,1,len(headers)-1,scope,note)
            visible=rows if rows else [['未提供']+['']*(len(headers)-1)]
            sheet.add_table(3,0,3+len(visible),len(headers)-1,{'name':f'QorReview{index}','style':'Table Style Medium 2','columns':[{'header':h} for h in headers],'data':visible})
            sheet.freeze_panes(4,0)
            widths=[]
            for col,label in enumerate(headers):
                values=[str(row[col]) for row in visible if col<len(row) and row[col] is not None]
                width=max(12,min(52,max([len(label)]+[min(len(x.split('\n')[0]),48) for x in values])+2))
                widths.append(width)
                sheet.set_column(col,col,width,text)
            for row_index,values in enumerate(visible,4):
                lines=1
                for col,value in enumerate(values):
                    if value is None:continue
                    segments=str(value).splitlines() or ['']
                    display=lambda segment:sum(2 if unicodedata.east_asian_width(c) in 'WF' else 1 for c in segment)
                    lines=max(lines,sum(max(1,math.ceil(display(segment)/max(widths[col]-2,1))) for segment in segments))
                sheet.set_row(row_index,min(18+14*lines,140))
    finally:book.close()
    return path
