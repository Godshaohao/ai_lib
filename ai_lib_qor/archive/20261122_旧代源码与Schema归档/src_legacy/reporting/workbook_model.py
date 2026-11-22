"""Legacy-style workbook views derived exclusively from explicitly supplied v3 records."""
from collections import defaultdict
from pathlib import PurePosixPath
import json

UNKNOWN='未提供'


def _text(value):
    if value is None:return UNKNOWN
    if isinstance(value,(dict,list)):return json.dumps(value,ensure_ascii=False,sort_keys=True)
    return str(value)


def _ref(ref):
    if not ref:return UNKNOWN
    if ref['kind']=='delivery_file':return f"{ref['source_library_id']} / {ref['delivery_id']} / {ref['file_id']}"
    return f"{ref['formal_nl_id']} / {ref['formal_snapshot_id']} / {ref['file_id']}"


def build_sheets(report):
    ctx=report.get('_report_context',{});deliveries=ctx.get('deliveries',[]);facts=ctx.get('facts',[]);snapshot=ctx.get('formal_snapshot');index=ctx.get('effective_index')
    current=ctx.get('target_revision');base=ctx.get('baseline_revision');accepted=ctx.get('accepted_revision');library_index=ctx.get('library_index')
    owner=current['owner']['owner_id'] if current else (library_index['effective_sets'][report['effective_set_id']]['owner']['id'] if library_index else UNKNOWN)
    changes={x['file_key']:x for x in report['file_changes']};quality=report['quality_checks'];facts_by_id={f['facts_id']:f for f in facts}
    by_file={};occurrences=defaultdict(list);rows={}
    for d in deliveries:
        for f in d['files']:
            ref={'kind':'delivery_file','source_library_id':d['source_library_id'],'delivery_id':d['delivery_id'],'file_id':f['file_id']}
            desc={'delivery':d,'file':f,'ref':ref,'path':str(PurePosixPath(d['source_root'])/f['relative_path'])}
            by_file[(d['source_library_id'],d['delivery_id'],f['file_id'])]=desc
            if f['file_key'] and f['classification']=='RESOLVED':occurrences[f['file_key']].append(desc)
    def resolve(ref):
        if not ref:return None
        if ref['kind']=='formal_file':
            sources=ctx.get('source_snapshots',[])
            found=next((s for s in sources if s['formal_nl_id']==ref['formal_nl_id'] and s['formal_snapshot_id']==ref['formal_snapshot_id']),None)
            if not found:return None
            formal=next((x for x in found['linked_files'] if x['file_id']==ref['file_id']),None)
            return {'path':formal['resolved_path'],'file':{'relative_path':formal['link_path']}} if formal else None
        return by_file.get((ref['source_library_id'],ref['delivery_id'],ref['file_id']))
    def fact_location(f):
        ref=f['source_ref'];entry=resolve(ref)
        return entry or {'path':UNKNOWN,'file':{'file_key':UNKNOWN,'view':f['view'],'corner':None,'relative_path':UNKNOWN},'ref':ref}
    target_ids={id for q in quality for id in q['facts_refs']}
    for change in report['file_changes']:
        target_ids.update(f['facts_id'] for f in facts if f['source_ref']==change['new_source_ref'])
    target_facts=[f for f in facts if f['facts_id'] in target_ids]
    macro_entries=defaultdict(lambda:defaultdict(list));macro_files=[];lef_rows=[];lib_rows=[];corner_rows=[]
    for f in target_facts:
        location=fact_location(f);info=location.get('file',{});key=info.get('file_key') or UNKNOWN;path=location.get('path',UNKNOWN);source=_ref(f['source_ref']);view=f['view']
        objects=f['objects'].get('macros',[]) if view=='LEF' else f['objects'].get('cells',[])
        for obj in objects:
            name=obj['name'];macro_entries[name][view].append(f"{key} [{f['facts_id']}]")
            macro_files.append([owner,name,view,key,info.get('corner') or UNKNOWN,source,path,f['facts_id'],'按解析事实的同名对象'])
            if view=='LEF':lef_rows.append([owner,key,path,name,obj['size_um'][0],obj['size_um'][1],'um',len(obj['pins']),', '.join(f['covered_sections']),f['facts_id']])
            else:lib_rows.append([owner,key,path,info.get('corner') or UNKNOWN,name,len(obj['pins']),'未单独判断',f['facts_id']])
        if view=='LIBERTY':corner_rows.append([owner,key,path,info.get('corner') or UNKNOWN,len(objects),'未提供 PVT / RC / PG 信息',f['facts_id']])
    macro_rows=[[owner,name,'\n'.join(v['LEF']) or UNKNOWN,'\n'.join(v['LIBERTY']) or UNKNOWN,UNKNOWN,UNKNOWN,UNKNOWN,UNKNOWN,'仅按已提供目标事实的对象同名关联；不代表 View 齐套'] for name,v in sorted(macro_entries.items())]
    keys=set(changes)|set(occurrences)|{key for q in quality for key in q['scope_file_keys']}
    if current:keys.update(x['file_key'] for x in current['members'])
    if accepted:keys.update(x['file_key'] for x in accepted['members'])
    if snapshot:keys.update(x['file_key'] for x in snapshot['linked_files'] if x['file_key'])
    matrix=[]
    for key in sorted(keys):
        occ=occurrences.get(key,[])
        rank={(library_index['scope']['vendor'],library_index['scope']['library'],x['delivery_id']):i for i,x in enumerate(library_index['deliveries'])} if library_index else None
        ident=lambda x:(x['delivery']['vendor_id'],x['delivery']['source_library_id'],x['delivery']['delivery_id'])
        sorted_occ=sorted(occ,key=lambda x:rank.get(ident(x),len(rank)) if rank is not None else -x['delivery']['delivery_order'])
        ambiguous=(any(ident(x) not in rank for x in occ) or len({ident(x) for x in occ})!=len(occ)) if rank is not None else len({x['delivery']['delivery_order'] for x in occ})!=len(occ)
        if len({x['delivery']['source_library_id'] for x in occ})>1 or ambiguous:
            latest=previous='顺序不明确';latest_path=previous_path='顺序不明确'
        else:
            latest=sorted_occ[0]['delivery']['supplier_version'] if sorted_occ else UNKNOWN
            previous=sorted_occ[1]['delivery']['supplier_version'] if len(sorted_occ)>1 else UNKNOWN
            latest_path=sorted_occ[0]['path'] if sorted_occ else UNKNOWN
            previous_path=sorted_occ[1]['path'] if len(sorted_occ)>1 else UNKNOWN
        f=changes.get(key); formal=next((x for x in (snapshot or {}).get('linked_files',[]) if x['file_key']==key),None)
        selected=next((m['source_ref'] for m in (current or {}).get('members',[]) if m['file_key']==key),None)
        baseline_ref=next((m['source_ref'] for m in (base or {}).get('members',[]) if m['file_key']==key),None)
        accepted_ref=next((m['source_ref'] for m in (accepted or {}).get('members',[]) if m['file_key']==key),None)
        matrix.append([owner,key,latest,latest_path,previous,previous_path,_ref(f['old_source_ref'] if f else baseline_ref),_ref(f['new_source_ref'] if f else selected),
                       _ref(selected),_text(index['current_accepted_revision']) if index else UNKNOWN,_ref(accepted_ref),
                       formal['resolved_path'] if formal else UNKNOWN,f['content_status'] if f else '未检查','仅按提供的交付记录排序，不证明全部历史已覆盖'])
    details=[[owner,f['file_key'],x['object_type'],x['object_name'],x['attribute'],_text(x['old_value']),_text(x['new_value']),x['unit'] or '',', '.join(x['facts_refs'])] for f in report['file_changes'] for x in f['object_changes']]
    quality_rows=[[str(i+1),q['check_id'],q['result'],q['coverage'],', '.join(q['scope_file_keys']),', '.join(q['facts_refs']),q['detail']] for i,q in enumerate(quality)]
    formal_rows=[[owner,snapshot['formal_nl_id'],f['file_key'] or UNKNOWN,f['link_path'],f['resolved_path'],f['source_match'],_ref(f['source_ref']),snapshot['coverage']] for f in (snapshot or {}).get('linked_files',[])]
    qa=[['本次检查对象',report['target']['id'],report['target']['kind']],['比较基线',_text((report.get('baseline') or {}).get('id')),'基线由本次检查指定'],['当前已采纳版本',_text(index['current_accepted_revision']) if index else UNKNOWN,'采纳与检查结论独立'],['完整库整体是否通过','未评估','本报告仅覆盖已提供的检查与事实']]
    concerns=[[owner,x[2],x[3],x[4],x[5],x[6],x[8]] for x in details]
    concerns += [[owner,'质量检查',q['check_id'],q['result'],'','',q['detail']] for q in quality if q['result']!='PASS']
    sheets=[
      ('00-概览',['IP / Owner','检查目标','目标类型','基线','Run ID','规则集','执行时间','文件来源变化','确认内容变化','失败检查','不确定检查','采纳版本','整体质量判断','范围说明'],[[owner,report['target']['id'],report['target']['kind'],_text((report.get('baseline') or {}).get('id')),report['check_run_id'],report['ruleset_id'],report['run_at'],report['summary']['files_with_new_source'] if report['file_changes'] else '未对比',report['summary']['files_with_confirmed_content_change'] if report['file_changes'] else '未对比',report['summary']['failed_checks'],report['summary']['inconclusive_checks'],_text(index['current_accepted_revision']) if index else UNKNOWN,'未评估',report['evidence_note']]]),
      ('文件版本矩阵',['IP / Owner','文件键','最新版本（已提供范围）','最新路径（已提供范围）','次新版本（已提供范围）','次新路径（已提供范围）','基准来源','目标来源','目标 Rev 成员来源','当前已采纳 Rev','已采纳文件来源','正式快照来源','内容状态','范围说明'],matrix),
      ('01-工程检查',['序号','检查项ID','本次结果','覆盖','文件范围','事实引用','范围或缺口'],quality_rows),
      ('02-执行记录',['Run ID','目标类型','目标','基线','规则集','执行时间','证据范围'],[[report['check_run_id'],report['target']['kind'],report['target']['id'],_text((report.get('baseline') or {}).get('id')),report['ruleset_id'],report['run_at'],report['evidence_note']]]),
      ('03-问答',['问题','回答','证据范围'],qa),
      ('04-关注项',['IP / Owner','类型','对象 / 检查','属性 / 结果','旧值','新值','事实 / 说明'],concerns),
      ('05-MacroView',['IP / Owner','Macro','LEF','Liberty','GDS','CDL','DB','Verilog','证据说明'],macro_rows),
      ('06-MacroView文件',['IP / Owner','Macro / Cell','View','文件键','Corner','来源引用','来源路径','事实ID','关联证据'],macro_files),
      ('07-正式文件',['IP / Owner','正式阶段','文件键','相对路径','解析路径','来源匹配','来源引用','覆盖'],formal_rows),
      ('08-LEF宏',['IP / Owner','文件键','来源路径','Macro','宽度','高度','单位','Pin数','解析范围','事实ID'],lef_rows),
      ('09-Liberty角',['IP / Owner','文件键','来源路径','Corner','Cell数','范围或缺口','事实ID'],corner_rows),
      ('10-Liberty单元',['IP / Owner','文件键','来源路径','Corner','Cell','信号Pin数','接口状态','事实ID'],lib_rows),
      ('11-对象变化',['IP / Owner','文件键','对象类型','对象','属性','旧值','新值','单位','事实引用'],details)]
    if library_index:
        versions={x['delivery_id']:x for x in library_index['deliveries']}
        rows=[]
        for view,group in library_index['views'].items():
            for path,item in group['files'].items():
                for source in item.get('effective',{}).get(report['effective_set_id'],[]):
                    if source['revision']!=report['target']['id']:continue
                    info=versions.get(source['delivery_id'],{}) if not source.get('source_scope') else {}
                    ext=next((x for x in deliveries if x['delivery_id']==source['delivery_id'] and
                        (x['vendor_id'],x['source_library_id'])==(source.get('source_scope',{}).get('vendor'),source.get('source_scope',{}).get('library'))),None)
                    scope=source.get('source_scope',library_index['scope']);source_path=source.get('source_path',path)
                    rawroot=info.get('root') or (ext['source_root'] if ext else None)
                    formal='\n'.join(f"{f['nl']} / {f['snapshot_id']} / {f['link_path']} → {f.get('link_target') or '未记录'}" for f in item.get('formal',[])) or UNKNOWN
                    rows.append([owner,report['target']['id'],view,path,scope['vendor'],scope['library'],source['delivery_id'],info.get('version') or (ext['supplier_version'] if ext else UNKNOWN),str(PurePosixPath(rawroot)/source_path) if rawroot else UNKNOWN,formal,'来源记录；不代表内容已检查'])
        sheets.append(('12-有效文件来源',['IP / Owner','有效版本','View','文件路径','来源供应商','来源库','交付 ID','交付版本','RAW 路径','Formal 历史链接','证据范围'],rows))
        comparison=ctx.get('source_comparison');difference=[]
        if comparison:
            for item in comparison['files']:
                before=item['before'];after=item['after']
                label={'SOURCE_CHANGED':'来源变化','UNCHANGED':'来源相同','ADDED':'新增','REMOVED':'移除'}.get(item['change'],item['change'])
                difference.append([comparison['from'],comparison['to'],item['view'],item['path'],label,
                    _text(before['delivery_id']) if before else '无',_text(after['delivery_id']) if after else '无',
                    '按 View 和路径比较来源，不判断内容'])
        else:difference=[['未提供','当前版本','','','无基线','','','初始版本不进行来源对比']]
        sheets.append(('13-版本来源对照',['基线','目标','View','文件路径','来源关系','基线交付 ID','目标交付 ID','范围说明'],difference))
    return sheets
