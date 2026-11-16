"""Check cross-field invariants before publishing or rendering a check result."""
from ai_lib_qor.versions.store import validate


def validate_check_result(result):
    validate(result, 'check_result')
    changes = result['file_changes']
    checks = result['quality_checks']
    keys = [item['file_key'] for item in changes]
    if len(keys) != len(set(keys)):
        raise ValueError('CheckResult 文件位重复')
    for change in changes:
        if change['source_changed'] != (change['old_source_ref'] != change['new_source_ref']):
            raise ValueError('文件来源变化与来源引用不一致')
    for check in checks:
        if check['result'] == 'PASS' and check['coverage'] != 'COMPLETE':
            raise ValueError('检查 PASS 必须具备 COMPLETE 覆盖')
    expected = {
        'files_with_new_source': sum(x['source_changed'] for x in changes),
        'files_with_confirmed_content_change': sum(x['content_status'] == 'CHANGED' for x in changes),
        'failed_checks': sum(x['result'] == 'FAIL' for x in checks),
        'inconclusive_checks': sum(x['result'] == 'INCONCLUSIVE' for x in checks),
    }
    if result['summary'] != expected:
        raise ValueError('CheckResult 汇总与检查明细不一致')
