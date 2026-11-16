"""Explicit per-version run overview; never infer an overall PASS."""
from pathlib import Path
import xlsxwriter


def render_overall_excel(owner, rows, output):
    path=Path(output)
    if path.exists(): raise FileExistsError('整体报告已存在')
    book=xlsxwriter.Workbook(str(path), {'strings_to_formulas':False,'strings_to_urls':False})
    header=book.add_format({'bold':True,'bg_color':'#315A76','font_color':'white','text_wrap':True,'valign':'vcenter'})
    title=book.add_format({'bold':True,'font_size':15,'font_color':'#16324F','bg_color':'#EAF1F7','valign':'vcenter'})
    note=book.add_format({'text_wrap':True,'font_color':'#526271','valign':'vcenter'})
    text=book.add_format({'text_wrap':True,'valign':'top'})
    try:
        sheet=book.add_worksheet('版本运行汇总');sheet.hide_gridlines(2);sheet.freeze_panes(3,0)
        sheet.set_column(0,0,16,text);sheet.set_column(1,2,14,text);sheet.set_column(3,3,40,text);sheet.set_column(4,7,15,text);sheet.set_column(8,8,20,text);sheet.set_column(9,10,50,text)
        sheet.set_row(0,26);sheet.set_row(1,32);sheet.set_row(2,30)
        sheet.merge_range(0,0,0,10,f"IP: {owner['vendor']} / {owner['library']} / {owner['ip']}",title)
        sheet.merge_range(1,0,1,10,'仅汇总列出的各版本及其实际执行范围；不代表全部检查通过或版本采纳。',note)
        columns=['有效版本','基线','执行状态','Run ID','来源变化','确认内容变化','失败项','不确定项','计划','范围说明','错误']
        sheet.write_row(2,0,columns,header)
        for n,row in enumerate(rows,3):
            summary=row.get('summary') or {}
            sheet.set_row(n,62)
            sheet.write_row(n,0,[row['revision'],row.get('baseline') or '未提供',{'SUCCEEDED':'执行完成','FAILED':'执行失败','RUNNING':'运行中'}.get(row['state'],row['state']),row['run_id'],summary.get('files_with_new_source','未提供') if row.get('baseline') and row.get('comparison_count',1) else '未对比',summary.get('files_with_confirmed_content_change','未提供') if row.get('baseline') and row.get('comparison_count',1) else '未对比',summary.get('failed_checks','未提供'),summary.get('inconclusive_checks','未提供'),row['plan'],row.get('note') or '未生成',row.get('error') or ''],text)
        if rows:sheet.autofilter(2,0,2+len(rows),10)
        detail=book.add_worksheet('逐项检查');detail.hide_gridlines(2);detail.freeze_panes(1,0);detail.set_row(0,30)
        detail.set_column(0,0,16,text);detail.set_column(1,1,40,text);detail.set_column(2,2,26,text);detail.set_column(3,3,48,text);detail.set_column(4,5,12,text);detail.set_column(6,7,55,text)
        detail.write_row(0,0,['有效版本','Run ID','检查 ID','文件范围','结果','覆盖','事实引用','说明'],header)
        n=1
        for row in rows:
            for check in row.get('checks',[]):
                detail.set_row(n,46)
                detail.write_row(n,0,[row['revision'],row['run_id'],check['check_id'],', '.join(check['scope_file_keys']),check['result'],check['coverage'],', '.join(check['facts_refs']),check['detail']],text);n+=1
        if n>1:detail.autofilter(0,0,n-1,7)
    finally:book.close()
    return path
