"""Publish one coherent advisory snapshot; upstream artifacts are read-only."""

from collections import Counter
from fnmatch import fnmatchcase
import hashlib
import json
from pathlib import Path

from lib_guard.atomic import atomic_write_json, file_lock
from lib_guard.catalog.runtime import load_catalog_view
from .binding import build_effective_model
from .checks import check_bindings, compare_bindings
from .effective import resolve_effective_facts
from .facts import FileFactsStore
from .model import POLICY_VERSION, canonical_json, check_result, implementation_identity, entity_id
from .profile import load_facts_settings, load_review_profile
from .results import deduplicate_report, freeze_bindings, freeze_index, result_identity, write_snapshot
from .lef_checks import LEF_RULES, LefCheckFacts, build_macro_index, compare_lef


def _delta_summary(counts):
    if not counts:
        return '没有可比较的变化项'
    labels = {'CHANGED': '确认变化', 'INCOMPLETE': '证据不足', 'UNKNOWN': '无法判定', 'UNCHANGED': '未变化'}
    return '；'.join(f'{labels.get(status, status)} {count}' for status, count in counts.items() if count)


def _lef_evidence(row):
    details = row.get('details') or {}
    pins = details.get('pins') or []
    if pins:
        samples = []
        for pin in pins[:3]:
            before, after = pin.get('old') or {}, pin.get('new') or {}
            change = []
            if before.get('direction') != after.get('direction'):
                change.append(f"{before.get('direction') or '无'} → {after.get('direction') or '无'}")
            if before.get('use') != after.get('use'):
                change.append(f"用途 {before.get('use') or '无'} → {after.get('use') or '无'}")
            samples.append(f"{pin['pin']}：{'、'.join(change) if change else '属性变化'}")
        return '；'.join(samples) + ('；更多见完整结果' if len(pins) > 3 else '')
    if details.get('change') in {'ADDED', 'REMOVED'}:
        return '新增对象' if details['change'] == 'ADDED' else '删除对象'
    if details.get('missing_attributes'):
        return '输入属性不完整；详见完整结果'
    if 'old_count' in details and 'new_count' in details:
        return f"数量 {details['old_count']} → {details['new_count']}；详见完整结果"
    return '详见 check_results.json'


def _lef_scope_index(index, model, config):
    files = [row for row in index['files']
        if row['file_type'] == 'lef' and any(fnmatchcase(row['effective_relpath'], pattern)
                                           for pattern in config['files'].get('lef', ['*']))]
    paths = {row['effective_relpath'] for row in files}
    # Object selection must not erase file-level evidence of incomplete discovery.
    return {**index, 'facts': model['facts'], 'files': files, 'bindings': model['bindings'],
            'discovery_facts': [fact for fact in index['facts'] if fact['view'] == 'lef'
                                and fact['file_identity']['effective_relpath'] in paths]}


def run_semantic_review(manifest_path, catalog_path, out_dir, *, base_manifest_path=None, mapping_path=None,
                        flag_policy=None, profile_config_path=None, profile_name=None, artifact_store=None):
    profile = load_review_profile(profile_config_path, profile_name=profile_name)
    lef_session = LefCheckFacts(enabled_checks=profile['config']['checks']) if set(profile['config']['checks']) & set(LEF_RULES) else None
    cache_settings = load_facts_settings(profile_config_path)
    if flag_policy is not None:
        # Preserve the existing Python API while recording the effective policy.
        if profile_config_path is not None and flag_policy != profile['config']['flag_policy']:
            raise ValueError('flag_policy 与检查方案不一致，请在配置中统一设置')
        profile['config']['flag_policy'] = flag_policy
        profile['digest'] = 'sha256:' + hashlib.sha256(canonical_json(profile['config']).encode()).hexdigest()
    manifest = json.loads(Path(manifest_path).read_text(encoding='utf-8-sig'))
    catalog = load_catalog_view(catalog_path)
    if mapping_path and profile.get('mapping_path') and Path(mapping_path).resolve() != Path(profile['mapping_path']):
        raise ValueError('命令行 mapping 与检查方案 mapping 不一致，请统一配置')
    mapping_path = mapping_path or profile.get('mapping_path')
    mapping = json.loads(Path(mapping_path).read_text(encoding='utf-8-sig')) if mapping_path else None
    out = Path(out_dir).resolve()
    inputs = [Path(manifest_path).resolve(), Path(catalog_path).resolve()]
    if base_manifest_path:
        inputs.append(Path(base_manifest_path).resolve())
    if mapping_path:
        inputs.append(Path(mapping_path).resolve())
    if profile_config_path:
        inputs.append(Path(profile_config_path).resolve())
    roots = [path.parent for path in inputs]
    source_roots = []
    for lib in catalog.get('libraries', []):
        for version in lib.get('versions', []):
            for path in (version.get('raw_path') or version.get('version_path'), (version.get('scan') or {}).get('scan_dir')):
                if path:
                    source_roots.append(Path(path).resolve())
    if any(out == root or out.is_relative_to(root) for root in source_roots) or out in roots:
        raise ValueError('Semantic output must be isolated from RAW, scan and input artifact directories')
    facts_dir = Path(cache_settings['directory'] or out / 'facts').resolve()
    if any(facts_dir == root or facts_dir.is_relative_to(root) for root in source_roots) or facts_dir in roots:
        raise ValueError('Facts output must be isolated from RAW, scan and input artifact directories')
    if artifact_store is not None:
        artifact_store = Path(artifact_store).resolve()
        if (any(artifact_store == root or artifact_store.is_relative_to(root) for root in source_roots)
                or artifact_store in roots or artifact_store == out or artifact_store.is_relative_to(out)):
            raise ValueError('Artifact store must be isolated from RAW, scan, inputs and report output')
    store = FileFactsStore(facts_dir, reuse=cache_settings['reuse'])
    index = resolve_effective_facts(manifest, catalog, facts_store=store, check_facts=lef_session)
    model = build_effective_model(index, profile, mapping=mapping)
    facts, current_scope, bindings = model['facts'], model['scope'], model['bindings']
    config = profile['config']
    checks = check_bindings(bindings, flag_policy=config['flag_policy'], mapping=mapping, enabled_checks=config['checks'])
    for missing in current_scope['missing_selections']:
        checks.append(check_result('PROFILE_SCOPE', '', 'NOT_CHECKED', 'SELECTED_CONTEXT_UNAVAILABLE', [], selection=missing))
    for missing in current_scope['missing_macros']:
        checks.append(check_result('PROFILE_SCOPE', missing, 'NOT_CHECKED', 'SELECTED_MACRO_UNAVAILABLE', []))
    for missing in current_scope['missing_contexts']:
        checks.append(check_result('PROFILE_SCOPE', entity_id(index['library_id'], missing['macro'], missing['variant']),
                                  'NOT_CHECKED', 'MACRO_CONTEXT_UNAVAILABLE', [], selection=missing['selection'], variant=missing['variant']))
    selected_paths = {fact['file_identity']['effective_relpath'] for fact in facts}
    for row in index['files']:
        if (row['file_type'] not in config['required_views']
                or not any(fnmatchcase(row['effective_relpath'], pattern) for pattern in config['files'].get(row['file_type'], ['*']))
                or row['fact_status'] == 'AVAILABLE' and row.get('parse_status') == 'PASS' and row['effective_relpath'] not in selected_paths):
            continue
        if row['fact_status'] != 'AVAILABLE' or row.get('parse_status') != 'PASS':
            checks.append(check_result('FILE_EVIDENCE', '', 'NOT_CHECKED', row['reason_code'] if row['fact_status'] != 'AVAILABLE' else 'UNSUPPORTED_OR_INCOMPLETE_PARSE',
                                      [row['parser_result_ref']] if row.get('parser_result_ref') else [], file=row))
    if not checks and not bindings:
        checks.append(check_result('MACRO_BINDING', '', 'NOT_CHECKED', 'NO_SEMANTIC_OBJECTS', []))
    base_index = None
    base_scope = None
    base_bindings = []
    base_model = None
    if base_manifest_path:
        base = json.loads(Path(base_manifest_path).read_text(encoding='utf-8-sig'))
        base_index = resolve_effective_facts(base, catalog, facts_store=store, check_facts=lef_session)
        base_model = build_effective_model(base_index, profile, mapping=mapping, allow_unused_mapping=True)
        base_scope, base_bindings = base_model['scope'], base_model['bindings']
    delta = (compare_bindings(base_bindings, bindings, tolerance_um=config['tolerance_um'],
                             enabled_checks=config['checks'], mapping=mapping) if base_index is not None else [])
    if lef_session is not None:
        current_lef = _lef_scope_index(index, model, config)
        base_lef = _lef_scope_index(base_index, base_model, config) if base_model is not None else None
        index['macro_index'] = build_macro_index(current_lef, lef_session)
        if base_index is not None:
            base_index['macro_index'] = build_macro_index(base_lef, lef_session)
        if base_lef is not None:
            delta.extend(compare_lef(base_lef, current_lef, lef_session,
                                      enabled_checks=config['checks'], tolerance_um=config['tolerance_um']))
    checks = sorted(checks, key=lambda row: (row['macro_id'], row['check_id'], canonical_json(row)))
    counts = Counter(row['status'] for row in checks)
    summary = {'schema_version': 'semantic_summary.v1', 'advisory': True, 'library_id': index['library_id'],
        'effective_id': index['effective_id'], 'effective_digest': index['effective_digest'],
        'base_effective_digest': base_index['effective_digest'] if base_index else None,
        'effective_integrity': index['effective_integrity'], 'macro_count': len(bindings),
        'file_count': len(index['files']), 'counts': dict(sorted(counts.items())),
        'delta_counts': dict(sorted(Counter(row['status'] for row in delta).items())),
        'delta_context': 'EXPLICIT_BASE_EFFECTIVE' if base_index else 'NO_BASE_EFFECTIVE',
        'review_profile': profile, 'scope': {'current': current_scope, 'base': base_scope},
        'rules_identity': {'policy_version': POLICY_VERSION, 'code': implementation_identity(
            'lib_guard.semantic.checks', 'lib_guard.semantic.binding', 'lib_guard.semantic.normalize',
            'lib_guard.semantic.profile', 'lib_guard.semantic.effective', 'lib_guard.semantic.results', 'lib_guard.semantic.runner',
            'lib_guard.semantic.lef_checks')},
        'mapping': mapping, 'facts_schema': 'semantic_file_fact.v1',
        'content_hash_reads': 0, 'raw_content_reads': 0,
        'limitations': ['建议性检查，不改变使用判断或发布门禁。', '文件新鲜度仅核对大小与时间，不是内容验证。',
                        '旧解析器未声明完整端口覆盖，不授予端口集合通过。']}
    report = {'summary': summary, 'index': index, 'base_index': base_index, 'bindings': bindings, 'checks': checks, 'delta': delta}
    frozen_index, frozen_base, frozen_bindings = freeze_index(index, out), freeze_index(base_index, out), freeze_bindings(bindings, out)
    generation = result_identity(summary, frozen_index, frozen_base, frozen_bindings, checks, delta)
    relative = Path('snapshots') / generation
    artifacts = {'semantic_effective_index': str(relative / 'semantic_effective_index.json'),
                 'macro_bindings': str(relative / 'macro_bindings.json'),
                 'check_results': str(relative / 'check_results.json'), 'markdown': str(relative / 'summary.md'),
                 'snapshot_manifest': str(relative / 'snapshot.json')}
    summary = {**summary, 'generation': generation, 'artifacts': artifacts}
    current_attention = counts['FAIL'] + counts['REVIEW_REQUIRED'] + counts['NOT_CHECKED'] + counts['UNKNOWN']
    delta_attention = sum(count for status, count in summary['delta_counts'].items() if status in {'INCOMPLETE', 'UNKNOWN', 'CHANGED'})
    markdown = ['# 跨视图技术检查（实验性）', '',
                f"库：{index['library_id']}；有效组合：{index['effective_id']}", '',
                '## 结论', '',
                (f"当前版检查：{counts['PASS']} 项通过，{current_attention} 项需要处理。"
                 if checks else '当前版检查：尚未执行独立检查；本方案只选择了版本变化规则。'),
                (f"版本变化：{_delta_summary(summary['delta_counts'])}。" if base_index else '版本变化：未执行；未选择基准组合。'),
                '本报告是只读技术建议，不代表 IP 可用或正式放行。', '',
                '## 下一步', '']
    if counts['FAIL']:
        markdown.append('先核对失败项和对应证据，修正输入或确认真实问题。')
    elif current_attention:
        markdown.append('先核对需要处理的检查项，补齐缺失证据或完成必要的人工确认。')
    elif checks:
        markdown.append('当前版独立检查未发现需处理项；仍需按检查范围核对覆盖程度。')
    else:
        markdown.append('当前版没有通过或失败结论；可选择独立检查规则，完整对象索引另见同快照 JSON。')
    if base_index is None:
        markdown.append('如需判断版本变化，请选择基准组合后重新检查；无需逐对象处理“缺基准”。')
    elif delta_attention:
        markdown.append('版本变化项按下方分类核对；证据不足的项目不能当作已确认变化。')
    markdown += ['', '## 本次检查范围', '',
                 f"检查方案：{profile['name']}；配置指纹：{profile['digest']}",
                 f"工艺角：{current_scope['selected_corners']}；模式：{current_scope['selected_modes']}",
                 f"有效文件 {current_scope['effective_files']}；参与检查 {current_scope['selected_files']}；未纳入 {current_scope['excluded_files']}",
                 f"缺少所选上下文：{current_scope['missing_selections']}；缺少宏：{current_scope['missing_macros']}",
                 '未纳入的文件没有本次技术检查结论；完整路径和逐项证据见同快照 JSON。', '']
    limited = [fact for fact in facts if fact.get('parse_limitations')]
    if limited:
        markdown += ['## 输入证据限制', '', '以下是源文件或解析范围问题，不等同于引脚不一致；未完成的规则不能报通过。', '',
                     '| 文件 | 行号与原因（每文件最多 5 条） | 扫描证据 |', '| --- | --- | --- |']
        for fact in limited[:20]:
            limits = '; '.join(f"{item.get('line', '-')}：{item.get('reason', 'unknown')}" for item in fact['parse_limitations'][:5])
            cells = [fact['file_identity']['source_relpath'], limits, fact['file_identity']['parser_result_ref']]
            markdown.append('| ' + ' | '.join(str(cell).replace('|', '\\|').replace('\n', ' ') for cell in cells) + ' |')
        markdown += ['', f'共 {len(limited)} 个输入文件有记录限制；完整列表见同快照对象与来源索引。', '']
    object_names = {binding['macro_id']: binding['name'] + (f" [{binding['variant']}]" if binding['variant'] else '') for binding in bindings}
    attention_checks = [row for row in checks if row['status'] not in {'PASS', 'NOT_APPLICABLE'}]
    markdown += ['', '## 需要处理的检查', '']
    if attention_checks:
        markdown += ['| 对象 | 检查 | 结果 | 原因 | 证据 |', '| --- | --- | --- | --- | --- |']
        for row in attention_checks[:30]:
            cells = [object_names.get(row['macro_id'], row['macro_id'] or '文件范围'), row['check_id'], row['status'], row['reason_code'], '; '.join(row['evidence_refs'])]
            markdown.append('| ' + ' | '.join(str(cell).replace('|', '\\|').replace('\n', ' ') for cell in cells) + ' |')
        if len(attention_checks) > 30:
            markdown.append(f'\n仅列出前 30 项；完整 {len(attention_checks)} 项见 check_results.json。')
    elif checks:
        markdown.append('本次独立检查没有需处理项；通过项见 check_results.json。')
    else:
        markdown.append('尚未执行独立检查；没有通过或失败结论。')
    if lef_session is not None:
        macro_rows = index['macro_index']['macros']
        lef_delta = [row for row in delta if row.get('check_id') in LEF_RULES]
        attention = sorted([row for row in lef_delta if row['status'] != 'UNCHANGED'],
                           key=lambda row: (row['status'] != 'CHANGED', row['macro_id'], row['attribute']))
        if base_index is not None:
            markdown += ['', '## LEF 变化与未完成项', '',
                f"检查属性汇总：{_delta_summary(Counter(row['status'] for row in lef_delta))}；完整逐项结果见 check_results.json。", '']
            if attention:
                markdown += ['| Macro | 属性 | 结果 | 差异证据 |', '| --- | --- | --- | --- |']
                for row in attention[:30]:
                    cells = [row.get('macro') or row['macro_id'], row['attribute'], row['status'], _lef_evidence(row)]
                    markdown.append('| ' + ' | '.join(str(value).replace('|', '\\|').replace('\n', ' ') for value in cells) + ' |')
                if len(attention) > 30:
                    markdown.append(f'\n仅列出前 30 项；完整 {len(attention)} 项见 check_results.json。')
            else:
                markdown.append('本次没有已确认变化或未完成项；未变化明细保留在完整结果中。')
        markdown += ['', '## 物理对象索引', '',
            f'已识别 {len(macro_rows)} 个对象；完整尺寸、引脚数、关联状态与来源见 semantic_effective_index.json。',
            'READY 仅表示 LEF 对象关联及摘要可用，不代表 IP 质量通过。']
    markdown += ['', '## 能力边界', *('- ' + text for text in summary['limitations'])]
    with file_lock(out / '.semantic.lock'):
        snapshot = out / relative
        resolved_snapshot = snapshot.resolve()
        if (not resolved_snapshot.is_relative_to(out)
                or any(resolved_snapshot == root or resolved_snapshot.is_relative_to(root) for root in source_roots)
                or any((snapshot / name).resolve() in inputs for name in ('semantic_effective_index.json', 'macro_bindings.json', 'check_results.json', 'summary.md', 'snapshot.json'))):
            raise ValueError('Semantic snapshot directory escapes output root')
        write_snapshot(out, summary, frozen_index, frozen_base, frozen_bindings, checks, delta, '\n'.join(markdown) + '\n')
        if artifact_store is not None:
            deduplicate_report(out, artifact_store, generation, facts_dir)
        # Publish the pointer last; readers follow only this generation's artifacts.
        atomic_write_json(out / 'summary.json', summary)
    return {**report, 'summary': summary}
