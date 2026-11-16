"""Create one v3 result from LEF differences and LEF/Liberty quality checks."""
from ai_lib_qor.versions.store import validate
from .evidence import validate_check_result
from .runner import run_contributions


def _fact(f, expected_kind, expected_id, members, file_key, delivery, snapshots):
    validate(f,'file_facts')
    ref=f['source_ref']
    if expected_kind=='RAW_DELIVERY':
        if delivery is None:raise ValueError('必须提供交付记录以验证 file_key 与文件行')
        validate(delivery,'delivery_record')
        ids=[x['file_id'] for x in delivery['files']]
        if len(ids)!=len(set(ids)):raise ValueError('交付内文件行 ID 重复')
        matches=[x for x in delivery['files'] if x['file_key']==file_key and x['classification']=='RESOLVED']
        if delivery['delivery_id']!=expected_id or len(matches)!=1:raise ValueError('交付记录与目标或文件位不一致')
        expected={'kind':'delivery_file','source_library_id':delivery['source_library_id'],'delivery_id':delivery['delivery_id'],'file_id':matches[0]['file_id']}
        if ref!=expected:raise ValueError('事实来源与交付文件行不一致')
    elif expected_kind=='EFFECTIVE_REVISION':
        selected=members.get(file_key) if members is not None else None
        if selected is None:raise ValueError('版本成员缺失')
        if selected!=ref:
            if selected.get('kind')!='formal_file':raise ValueError('事实来源与版本成员不一致')
            found=[x for snap in snapshots if snap['formal_nl_id']==selected['formal_nl_id'] and snap['formal_snapshot_id']==selected['formal_snapshot_id'] for x in snap['linked_files'] if x['file_id']==selected['file_id'] and x['file_key']==file_key and x['source_match']=='MATCHED_RAW' and x['source_ref']==ref]
            if len(found)!=1:raise ValueError('正式快照无法唯一证明事实来源')
    else:raise ValueError('不支持的检查目标')
    return selected if expected_kind=='EFFECTIVE_REVISION' else ref


def build_check_result(*,target,baseline,effective_set_id,run_id,ruleset_id,run_at,comparisons,pin_pairs,target_members=None,baseline_members=None,target_delivery=None,baseline_delivery=None,formal_snapshots=(),plugin_ids=None):
    if not comparisons and not pin_pairs:raise ValueError('没有指定任何检查')
    if baseline and baseline['kind']!=target['kind']:raise ValueError('目标与基线类型不一致')
    if target['kind']=='EFFECTIVE_REVISION' and not effective_set_id:raise ValueError('版本检查必须指定 effective_set_id')
    if target['kind']=='RAW_DELIVERY' and effective_set_id is not None:raise ValueError('交付检查不能指定有效集')
    for snapshot in formal_snapshots:validate(snapshot,'formal_snapshot')
    facts={}; checked_comparisons=[]; checked_pairs=[]; seen=set()
    def remember(f):
        if f['facts_id'] in facts and facts[f['facts_id']]!=f:raise ValueError('facts_id 重复但内容不同')
        facts[f['facts_id']]=f
    for comp in comparisons:
        key=comp['file_key']
        if key in seen:raise ValueError('同一 file_key 重复比较')
        seen.add(key);old,new=comp['old'],comp['new']
        if not baseline:raise ValueError('文件差异需要明确基线')
        old_ref=_fact(old,baseline['kind'],baseline['id'],baseline_members,key,baseline_delivery,formal_snapshots);new_ref=_fact(new,target['kind'],target['id'],target_members,key,target_delivery,formal_snapshots);remember(old);remember(new)
        checked_comparisons.append({'file_key':key,'old':old,'new':new,'old_ref':old_ref,'new_ref':new_ref})
    scopes=set()
    for pair in pin_pairs:
        a,b=pair['lef'],pair['liberty'];lk,bk=pair['lef_key'],pair['liberty_key'];scope=(lk,bk)
        if scope in scopes:raise ValueError('重复质量检查范围')
        scopes.add(scope);_fact(a,target['kind'],target['id'],target_members,lk,target_delivery,formal_snapshots);_fact(b,target['kind'],target['id'],target_members,bk,target_delivery,formal_snapshots);remember(a);remember(b)
        checked_pairs.append(pair)
    selected = plugin_ids if plugin_ids is not None else ['LEF_MACRO_DIFF','LEF_LIBERTY_PIN_MATCH']
    contributions = run_contributions(selected, {'comparisons':checked_comparisons,'pin_pairs':checked_pairs})
    changes, quality = contributions['file_changes'], contributions['quality_checks']
    if not changes and not quality: raise ValueError('所选插件未对输入产生检查结果')
    result={'schema_version':'check_result.v1','check_run_id':run_id,'target':target,'baseline':baseline,'effective_set_id':effective_set_id,'run_at':run_at,'ruleset_id':ruleset_id,'file_changes':changes,'quality_checks':quality,'summary':{'files_with_new_source':sum(x['source_changed'] for x in changes),'files_with_confirmed_content_change':sum(x['content_status']=='CHANGED' for x in changes),'failed_checks':sum(x['result']=='FAIL' for x in quality),'inconclusive_checks':sum(x['result']=='INCONCLUSIVE' for x in quality)},'evidence_note':'仅依据调用方提供的 v3 解析事实；范围为 LEF Macro SIZE、Pin 存在性及 LEF/Liberty 信号 Pin 名称和方向；不验证原始文件或解析器可信度。'}
    validate_check_result(result);return result
