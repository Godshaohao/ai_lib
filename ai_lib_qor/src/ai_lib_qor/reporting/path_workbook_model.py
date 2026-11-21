"""Review sheets for path-based checks, with the familiar legacy sheet names."""
import json
from collections import defaultdict


def _text(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True) if isinstance(value,(dict,list)) else ('' if value is None else str(value))


def build_path_sheets(report):
    context=report['_path_context'];index=context['index'];facts=context['facts'];owner=report['library'];revision=report['revision'];baseline=report['baseline']
    files=report['files'];checks=report['checks'];changes=report['changes'];summary=report['summary']
    matrix=[];sources=[];comparison=[];formal=[]
    for view,group in index['views'].items():
        for path,row in group.items():
            raw=row['raw'];current=next((x for x in row['effective'] if x['revision']==revision),None)
            before=next((x for x in row['effective'] if x['revision']==baseline),None)
            item=next((x for x in files if (x['view'],x['path'])==(view,path)),None)
            status=item['status'] if item else 'NOT_CHECKED'
            matrix.append([owner,view,path,raw[-1]['version'] if raw else '',raw[-1]['path'] if raw else '',
                           raw[-2]['version'] if len(raw)>1 else '',raw[-2]['path'] if len(raw)>1 else '',
                           before['version'] if before else '',current['version'] if current else '',status])
            if current:
                sources.append([owner,revision,view,path,current['version'],current['path'],status,'来源记录；不证明历史内容一致'])
            if before or current:
                change='新增' if before is None else '移除' if current is None else '来源相同' if before['version']==current['version'] else '来源变化'
                comparison.append([baseline or '无',revision,view,path,change,before['version'] if before else '',current['version'] if current else '','仅来源关系'])
            for link in row['nl']:
                formal.append([owner,link['version'],view,path,link['link_path'],link['link_target'],link['resolved_path'],link['source_match']])
    macro_entries=defaultdict(lambda:defaultdict(list));macro_files=[];lef_rows=[];lib_rows=[];corner_rows=[]
    for row in files:
        if row['status']!='PARSED' or row['facts'] not in facts:continue
        fact=facts[row['facts']];view=row['view'];obj=fact['objects']
        for value in obj.get('macros',[]) if view=='LEF' else obj.get('cells',[]) if view=='LIBERTY' else []:
            name=value['name'];macro_entries[name][view].append(row['path'])
            macro_files.append([owner,name,view,row['path'],row['version'],row['absolute_path'],row['facts']])
            if view=='LEF':lef_rows.append([owner,row['path'],row['absolute_path'],name,*value['size_um'],'um',len(value['pins']),', '.join(fact['covered_sections']),row['facts']])
            else:lib_rows.append([owner,row['path'],row['absolute_path'],'未提供',name,len(value['pins']),'仅信号接口',row['facts']])
        if view in ('VERILOG','CDL','SPICE'):
            key='modules' if view=='VERILOG' else 'subcircuits'
            for value in obj.get(key,[]):
                name=value.get('name')
                if name:
                    macro_entries[name][view].append(row['path'])
                    macro_files.append([owner,name,view,row['path'],row['version'],row['absolute_path'],row['facts']])
        if view=='LIBERTY':corner_rows.append([owner,row['path'],row['absolute_path'],'未提供',len(obj.get('cells',[])),'未解析 PVT/PG',row['facts']])
    macro=[[owner,name,', '.join(v['LEF']),', '.join(v['LIBERTY']),'未检查',', '.join(v['CDL']+v['SPICE']),
            '未检查',', '.join(v['VERILOG']),'仅同名对象；Verilog/CDL/SPICE 为部分解析'] for name,v in sorted(macro_entries.items())]
    quality=[[i+1,q['check_id'],q['result'],q['coverage'],', '.join(q['scope_file_keys']),', '.join(q['facts_refs']),q['detail']] for i,q in enumerate(checks)]
    detail=[[owner,x['path'],x['object_type'],x['object_name'],x['attribute'],_text(x['old_value']),_text(x['new_value']),x['unit'] or '',', '.join(x['facts_refs'])] for x in changes]
    for item in report.get('partial_comparisons',[]):
        detail.append([owner,item['path'],item['view'],'部分接口观察','差异','',_text(item['differences']),'',', '.join(item['facts_refs'])])
    concerns=[[owner,'变化',x[3],x[4],x[5],x[6],x[8]] for x in detail]
    concerns += [[owner,'质量检查',q['check_id'],q['result'],'','',q['detail']] for q in checks if q['result']!='PASS']
    return [
      ('00-概览',['库','目标版本','基线','Run ID','执行状态','失败检查','不确定检查','失败文件','范围说明'],[[owner,revision,baseline or '无',report['run_id'],report['state'],summary['failed_checks'],summary['inconclusive_checks'],summary['failed_files'],report['note']]]),
      ('文件版本矩阵',['库','View','相对路径','最新版本','最新路径','次新版本','次新路径','基线来源','目标来源','解析状态'],matrix),
      ('01-工程检查',['序号','检查项ID','本次结果','覆盖','文件范围','事实引用','范围或缺口'],quality),
      ('02-执行记录',['Run ID','目标版本','基线','执行时间','执行状态','证据范围'],[[report['run_id'],revision,baseline or '无',report['run_at'],report['state'],report['note']]]),
      ('03-问答',['问题','回答','依据'],[['完整库整体是否通过','未评估','仅检查已列出规则'],['历史字节是否一致','未验证','当前解析不证明历史字节']]),
      ('04-关注项',['库','类型','对象 / 检查','属性 / 结果','旧值','新值','事实 / 说明'],concerns),
      ('05-MacroView',['库','Macro','LEF','Liberty','GDS','CDL','DB','Verilog','证据说明'],macro),
      ('06-MacroView文件',['库','Macro / Cell','View','相对路径','版本','来源路径','事实文件'],macro_files),
      ('07-正式文件',['库','正式阶段','View','RAW 相对路径','链接路径','链接目标','解析路径','来源关系'],formal),
      ('08-LEF宏',['库','相对路径','来源路径','Macro','宽度','高度','单位','Pin数','解析范围','事实文件'],lef_rows),
      ('09-Liberty角',['库','相对路径','来源路径','Corner','Cell数','范围或缺口','事实文件'],corner_rows),
      ('10-Liberty单元',['库','相对路径','来源路径','Corner','Cell','信号Pin数','接口状态','事实文件'],lib_rows),
      ('11-对象变化',['库','相对路径','对象类型','对象','属性','旧值','新值','单位','事实引用'],detail),
      ('12-有效文件来源',['库','有效版本','View','相对路径','来源版本','RAW 路径','解析状态','证据范围'],sources),
      ('13-版本来源对照',['基线','目标','View','相对路径','来源关系','基线版本','目标版本','范围说明'],comparison)]
