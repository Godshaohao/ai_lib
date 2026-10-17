"""Bind existing effective selections to the read-only diagnostic CLI."""

import json
from pathlib import Path
import sys

from lib_guard.effective.manifest import validate_effective_manifest
from lib_guard.semantic.profile import DEFAULT_CONFIG_PATH, load_review_profile, load_facts_settings
from lib_guard.semantic.binding import apply_file_contexts
from .read_model import _current_effective_pointer, _pending_window

RULE_LABELS = {
    'LEF_MACRO_DELTA': 'Macro 增删', 'LEF_PHYSICAL_DELTA': '尺寸与物理属性',
    'LEF_INTERFACE_DELTA': '引脚名称、方向与用途', 'LEF_GEOMETRY_DELTA': '引脚矩形与 PORT 分组',
    'LEF_OBS_DELTA': '布线阻挡矩形', 'MACRO_BINDING': '跨视图对象关联',
    'SIGNAL_PORT_SET': '信号引脚集合', 'SIGNAL_PORT_DIRECTION': '信号引脚方向',
    'PG_PORT_LEF_LIB': '电源地引脚一致性', 'LIB_MACRO_FLAGS': '时序库对象属性',
    'LEF_SIZE_DELTA': 'LEF 尺寸变化（原规则）', 'LEF_PIN_DELTA': 'LEF 引脚变化（原规则）',
    'PORT_DECLARATION_DELTA': '接口声明变化', 'LIB_PORT_DELTA': '时序库引脚变化',
}
PROFILE_LABELS = {'lef_basic': 'LEF 对象与变化', 'default': '跨视图基础核查', 'ip_basic': 'TT / SS 接口核查'}
BASE_REQUIRED_RULES = frozenset({
    'LEF_MACRO_DELTA', 'LEF_PHYSICAL_DELTA', 'LEF_INTERFACE_DELTA',
    'LEF_GEOMETRY_DELTA', 'LEF_OBS_DELTA', 'LEF_SIZE_DELTA',
    'LEF_PIN_DELTA', 'PORT_DECLARATION_DELTA', 'LIB_PORT_DELTA',
})


def _profile_mapping(profile):
    if not profile.get('mapping_path'):
        return None
    value = json.loads(Path(profile['mapping_path']).read_text(encoding='utf-8-sig'))
    if not isinstance(value, dict):
        raise ValueError('技术检查映射必须为 JSON 对象')
    return value


def _targets(state, library):
    window = _pending_window(state, library)
    directory = Path(window['path']).parent.parent / 'effective'
    rows = {item['effective_id']: {'id': item['effective_id'], 'kind': 'saved',
            'path': directory / item['effective_id'] / 'effective_manifest.json'}
            for item in window['saved_combinations']}
    current = _current_effective_pointer(state, library)
    for kind, identity, manifest in (
        ('current', current.get('current_effective_id'), current.get('manifest')),
        ('candidate', window.get('candidate_effective_id'), (window.get('candidate_effective_stack') or {}).get('manifest')),
    ):
        if identity and manifest and Path(manifest).is_file():
            rows[identity] = {'id': identity, 'kind': kind, 'path': Path(manifest)}
    identity = current.get('current_effective_id')
    if identity in rows and current.get('effective_integrity_status') == 'MISMATCH':
        rows[identity].update(kind='invalid_current', error='当前指针与有效组合清单不一致，请核对后再选择该组合。')
    return rows


def semantic_review_options(state, library):
    rows = _targets(state, library)
    config_path = Path(state['config'].get('semantic_review_config') or DEFAULT_CONFIG_PATH)
    document = json.loads(config_path.read_text(encoding='utf-8-sig'))
    profiles = []
    for name in document['profiles']:
        profile = load_review_profile(config_path, profile_name=name)
        mapping = _profile_mapping(profile)
        if mapping is not None and mapping.get('library_id') != library['library_id']:
            continue
        apply_file_contexts({'library_id': library['library_id'], 'facts': []}, mapping, allow_unused=True)
        profiles.append({'name': name, 'label': PROFILE_LABELS.get(name, name),
            'checks': [{'id': rule, 'label': RULE_LABELS.get(rule, rule),
                        'requires_base': rule in BASE_REQUIRED_RULES} for rule in profile['config']['checks']]})
    current = next((row['id'] for row in rows.values() if row['kind'] == 'current'), '')
    candidate = next((row['id'] for row in rows.values() if row['kind'] == 'candidate'), '')
    labels = {'current': '当前可用', 'candidate': '候选组合', 'saved': '已保存组合', 'invalid_current': '当前记录不一致'}
    targets = []
    for row in rows.values():
        versions = []
        try:
            manifest = json.loads(row['path'].read_text(encoding='utf-8-sig'))
            versions = [component['version_id'] for component in manifest['components']]
        except (OSError, ValueError, KeyError, TypeError):
            row['error'] = f"组合 {row['id']} 的组成清单无法读取，请刷新组合后重试。"
        targets.append({'id': row['id'], 'kind': row['kind'], 'versions': versions,
                        'available': not bool(row.get('error')),
                        'label': f"{labels[row['kind']]} · {' + '.join(versions) or row['id']}"})
    return {'targets': targets, 'profiles': profiles,
            'notice': '；'.join([row['error'] for row in rows.values() if row.get('error')]
                               + ([] if profiles else ['没有适用于本库的检查方案，请核对 semantic_review_config 和映射中的 library_id。'])),
            'default_profile': next((row['name'] for row in profiles if row['name'] == document.get('default_profile')),
                                    profiles[0]['name'] if profiles else ''),
            'default_target': candidate or current, 'default_base': current if candidate and candidate != current else ''}


def prepare_semantic_job(state, library, payload, job_dir):
    if set(payload) - {'target', 'base', 'profile', 'checks'}:
        raise ValueError('技术检查仅接受目标组合、基准组合、检查方案和规则；不自动扫描，也不接受路径或命令参数。')
    targets = _targets(state, library)
    target, base = payload.get('target'), payload.get('base') or ''
    if not isinstance(target, str) or target not in targets:
        raise ValueError('请选择本库已生成的有效组合；没有组合时请先生成候选。')
    if not isinstance(base, str) or base and base not in targets:
        raise ValueError('基准必须是本库已保存的有效组合，或选择不对比。')
    if target == base:
        raise ValueError('目标组合与基准不能相同。')
    for identity in (target, base):
        if identity and targets[identity].get('error'):
            raise ValueError(targets[identity]['error'])
    name = payload.get('profile')
    if name is not None and not isinstance(name, str):
        raise ValueError('检查方案名称必须是字符串。')
    config_path = state['config'].get('semantic_review_config') or DEFAULT_CONFIG_PATH
    profile = load_review_profile(config_path, profile_name=name)
    name = profile['name']
    mapping = _profile_mapping(profile)
    if mapping is not None and mapping.get('library_id') != library['library_id']:
        raise ValueError('检查方案映射的 library_id 与当前库不一致')
    apply_file_contexts({'library_id': library['library_id'], 'facts': []}, mapping, allow_unused=True)
    checks = payload.get('checks', profile['config']['checks'])
    if not isinstance(checks, list) or not checks or any(not isinstance(rule, str) or rule not in profile['config']['checks'] for rule in checks):
        raise ValueError('至少勾选一项当前检查方案中的规则。')
    profile['config']['checks'] = list(dict.fromkeys(checks))
    settings = load_facts_settings(config_path)
    profile['config']['mapping'] = None
    config = {'schema_version': 'semantic_review_config.v1', 'profiles': {name: profile['config']},
              'facts_cache': {'reuse': settings['reuse'], 'directory': str(settings['directory']) if settings['directory'] else None}}
    catalog_snapshot = json.dumps(state['catalog'], ensure_ascii=False, indent=2)
    documents = {
        'review_config.json': json.dumps(config, ensure_ascii=False, indent=2),
        'catalog_snapshot.json': catalog_snapshot,
    }
    args = [sys.executable, '-m', 'lib_guard.semantic.cli', '--catalog', str(Path(job_dir) / 'catalog_snapshot.json'),
            '--config', str(job_dir / 'review_config.json'), '--profile', name, '--out', str(job_dir / 'semantic_review'),
            '--artifact-store', str(Path(state['workspace']) / 'semantic_artifacts')]
    if mapping is not None:
        documents['review_mapping.json'] = json.dumps(mapping, ensure_ascii=False, indent=2)
        args.extend(['--mapping', str(job_dir / 'review_mapping.json')])
    for identity, filename, flag in ((target, 'target_effective.json', '--effective-manifest'),
                                     (base, 'base_effective.json', '--base-effective-manifest')):
        if not identity:
            continue
        content = targets[identity]['path'].read_text(encoding='utf-8-sig')
        manifest = json.loads(content)
        if manifest.get('library_id') != library['library_id'] or manifest.get('effective_id') != identity:
            raise ValueError('有效组合清单与所选库或组合标识不一致，请核对有效组合。')
        if not validate_effective_manifest(manifest)['valid']:
            raise ValueError('有效组合清单完整性校验未通过，请重新生成组合后再检查。')
        documents[filename] = content
        args.extend([flag, str(job_dir / filename)])
    return args, documents
