"""Prepare a fixed check and explicitly supplied v3 context for reporting."""
from copy import deepcopy
from ai_lib_qor.checks.evidence import validate_check_result
from ai_lib_qor.versions.store import validate
from ai_lib_qor.versions.composer import members_map


def _unique(items, schema, identity):
    result={}
    for item in items:
        validate(item,schema);key=identity(item)
        if key in result and result[key]!=item:raise ValueError(f'{schema} 身份重复但内容不一致: {key}')
        result[key]=deepcopy(item)
    return list(result.values())


def build_report(check_result, *, deliveries=(), facts=(), formal_snapshot=None, target_revision=None, baseline_revision=None, effective_index=None, accepted_revision=None, source_snapshots=()):
    validate_check_result(check_result)
    deliveries=_unique(deliveries,'delivery_record',lambda x:(x['source_library_id'],x['delivery_id']))
    facts=_unique(facts,'file_facts',lambda x:x['facts_id'])
    source_snapshots=_unique([*source_snapshots,*([formal_snapshot] if formal_snapshot else [])],'formal_snapshot',lambda x:(x['formal_nl_id'],x['formal_snapshot_id']))
    for value,schema in ((formal_snapshot,'formal_snapshot'),(target_revision,'effective_version'),(baseline_revision,'effective_version'),(effective_index,'effective_index'),(accepted_revision,'effective_version')):
        if value is not None:validate(value,schema)
    if target_revision and (check_result['target']['kind']!='EFFECTIVE_REVISION' or check_result['target']['id']!=target_revision['revision_id'] or check_result['effective_set_id']!=target_revision['effective_set_id']):raise ValueError('报告目标版本与 CheckResult 不一致')
    if baseline_revision and (not check_result['baseline'] or check_result['baseline']['kind']!='EFFECTIVE_REVISION' or check_result['baseline']['id']!=baseline_revision['revision_id'] or check_result['effective_set_id']!=baseline_revision['effective_set_id']):raise ValueError('报告基准版本与 CheckResult 不一致')
    if effective_index and effective_index['effective_set_id']!=check_result['effective_set_id']:raise ValueError('报告有效集索引与 CheckResult 不一致')
    for revision,ref_field in ((target_revision,'new_source_ref'),(baseline_revision,'old_source_ref')):
        if revision:
            members=members_map(revision)
            for change in check_result['file_changes']:
                if members.get(change['file_key'])!=change[ref_field]:raise ValueError('报告版本成员与检查文件来源不一致')
    if accepted_revision and (not effective_index or effective_index['current_accepted_revision']!=accepted_revision['revision_id'] or effective_index['effective_set_id']!=accepted_revision['effective_set_id']):raise ValueError('已采纳版本与索引不一致')
    if target_revision:
        target_members=members_map(target_revision)
        facts_by_id={fact['facts_id']:fact for fact in facts}
        for check in check_result['quality_checks']:
            for fact_id in check['facts_refs']:
                fact=facts_by_id.get(fact_id)
                if not fact:continue
                matches=[]
                for key in check['scope_file_keys']:
                    selected=target_members.get(key)
                    if selected==fact['source_ref']:matches.append(key);continue
                    if selected and selected.get('kind')=='formal_file':
                        matching=[snapshot for snapshot in source_snapshots if snapshot['formal_nl_id']==selected['formal_nl_id'] and snapshot['formal_snapshot_id']==selected['formal_snapshot_id']]
                        if any(row['file_id']==selected['file_id'] and row['file_key']==key and row['source_match']=='MATCHED_RAW' and row['source_ref']==fact['source_ref'] for snapshot in matching for row in snapshot['linked_files']):matches.append(key)
                if len(matches)!=1:raise ValueError(f'质量检查事实与目标版本文件范围不匹配: {fact_id}')
    for revision in (target_revision,baseline_revision,accepted_revision):
        if revision and effective_index and revision['owner']!=effective_index['owner']:raise ValueError('版本与索引所属对象不一致')
    out=deepcopy(check_result)
    out['_report_context']={'deliveries':deliveries,'facts':facts,'formal_snapshot':deepcopy(formal_snapshot),'target_revision':deepcopy(target_revision),'baseline_revision':deepcopy(baseline_revision),'effective_index':deepcopy(effective_index),'accepted_revision':deepcopy(accepted_revision),'source_snapshots':source_snapshots}
    return out
