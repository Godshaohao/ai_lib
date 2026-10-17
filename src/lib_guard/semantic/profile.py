"""Explicit review scope and existing Python rule selection."""

from copy import deepcopy
from fnmatch import fnmatchcase
import hashlib
import json
import math
from pathlib import Path

from .model import canonical_json
from .lef_checks import LEF_RULES

CHECK_IDS = (
    'MACRO_BINDING', 'SIGNAL_PORT_SET', 'SIGNAL_PORT_DIRECTION', 'PG_PORT_LEF_LIB',
    'LIB_MACRO_FLAGS', 'LEF_SIZE_DELTA', 'LEF_PIN_DELTA', 'PORT_DECLARATION_DELTA', 'LIB_PORT_DELTA',
    *LEF_RULES,
)
DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[3] / 'configs/semantic_review.json'
DEFAULT_PROFILE = {
    'macros': [], 'required_views': ['lef', 'liberty', 'verilog'], 'files': {},
    'liberty': {'selected': []}, 'checks': [name for name in CHECK_IDS if name not in LEF_RULES], 'flag_policy': {}, 'tolerance_um': 1e-6,
    'mapping': None,
}


def _strings(value, field):
    if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
        raise ValueError(f'{field} 必须是非空字符串组成的列表')
    return list(dict.fromkeys(value))


def _patterns(value, field):
    return _strings([value] if isinstance(value, str) else value, field)


def _load_config(config_path):
    path = Path(config_path) if config_path else DEFAULT_CONFIG_PATH
    if config_path or path.exists():
        document = json.loads(path.read_text(encoding='utf-8-sig'))
    else:
        document = {'schema_version': 'semantic_review_config.v1', 'profiles': {'default': DEFAULT_PROFILE}}
    if not isinstance(document, dict) or document.get('schema_version') != 'semantic_review_config.v1':
        raise ValueError('检查配置 schema_version 必须为 semantic_review_config.v1')
    return document, path


def load_facts_settings(config_path=None):
    document, path = _load_config(config_path)
    settings = document.get('facts_cache', {})
    if not isinstance(settings, dict) or set(settings) - {'reuse', 'directory'} or not isinstance(settings.get('reuse', True), bool):
        raise ValueError('facts_cache 仅支持 reuse 布尔值与 directory 路径')
    directory = settings.get('directory')
    if directory is not None:
        if not isinstance(directory, str) or not directory.strip():
            raise ValueError('facts_cache.directory 必须为路径或 null')
        directory = Path(directory)
        directory = directory if directory.is_absolute() else path.resolve().parent / directory
    return {'reuse': settings.get('reuse', True), 'directory': directory}


def load_review_profile(config_path=None, *, profile_name=None):
    document, path = _load_config(config_path)
    name = profile_name or document.get('default_profile', 'default')
    profiles = document.get('profiles')
    if not isinstance(profiles, dict) or name not in profiles:
        raise ValueError(f'检查方案不存在：{name}')
    raw = profiles[name]
    if not isinstance(raw, dict) or set(raw) - set(DEFAULT_PROFILE):
        raise ValueError(f'检查方案 {name} 含未知字段或不是对象')
    config = {**deepcopy(DEFAULT_PROFILE), **deepcopy(raw)}
    for key in ('macros', 'required_views', 'checks'):
        config[key] = _strings(config[key], key)
    if not config['required_views'] or set(config['required_views']) - {'lef', 'liberty', 'verilog'}:
        raise ValueError('required_views 仅支持 lef/liberty/verilog，且不可为空')
    if not config['checks'] or set(config['checks']) - set(CHECK_IDS):
        raise ValueError('checks 必须选择已实现的规则：' + ', '.join(CHECK_IDS))
    if not isinstance(config['files'], dict) or set(config['files']) - {'lef', 'liberty', 'verilog'}:
        raise ValueError('files 必须按 lef/liberty/verilog 配置路径匹配列表')
    config['files'] = {view: _patterns(patterns, f'files.{view}') for view, patterns in config['files'].items()}
    liberty = config['liberty']
    if not isinstance(liberty, dict) or set(liberty) - {'selected'} or not isinstance(liberty.get('selected', []), list):
        raise ValueError('liberty.selected 必须为 Corner/Mode 选择列表')
    selected = []
    for item in liberty.get('selected', []):
        if not isinstance(item, dict) or not item or set(item) - {'corner', 'mode', 'files'}:
            raise ValueError('liberty.selected 每项仅支持 corner/mode/files')
        for key in ('corner', 'mode'):
            if key in item and (not isinstance(item[key], str) or not item[key].strip()):
                raise ValueError(f'liberty.selected.{key} 必须为非空字符串')
        selected.append({**item, 'files': _patterns(item.get('files', ['*']), 'liberty.selected.files')})
    config['liberty'] = {'selected': selected}
    flags = config['flag_policy']
    if (not isinstance(flags, dict) or set(flags) - {'is_macro', 'is_pad'}
            or any(not isinstance(value, bool) for value in flags.values())):
        raise ValueError('flag_policy 仅支持 is_macro/is_pad 布尔期望值')
    tolerance = config['tolerance_um']
    if isinstance(tolerance, bool) or not isinstance(tolerance, (int, float)) or not math.isfinite(tolerance) or tolerance < 0:
        raise ValueError('tolerance_um 必须为有限的非负数')
    mapping = config['mapping']
    if mapping is not None and (not isinstance(mapping, str) or not mapping.strip()):
        raise ValueError('mapping 必须为映射文件路径或 null')
    mapping_path = (path.resolve().parent / mapping).resolve() if mapping else None
    return {'name': name, 'config': config, 'mapping_path': str(mapping_path) if mapping_path else None,
            'digest': 'sha256:' + hashlib.sha256(canonical_json(config).encode()).hexdigest()}


def select_review_facts(index, profile, *, mapping=None, allow_unused_mapping=False):
    """Select cached facts without changing their coverage or the Effective index."""
    config = profile['config']
    selectors = config['liberty']['selected']
    matches = [0 for _ in selectors]
    context_macros = [set() for _ in selectors]
    facts, selected_paths = [], set()
    macros = set()
    macro_variants = set()
    for alias in ([] if allow_unused_mapping else (mapping or {}).get('macro_aliases', [])):
        if not any(fact['view'] == alias['view'] and obj['name'] == alias['object']
                   and (not alias.get('source_relpath') or alias['source_relpath'] == fact['file_identity']['source_relpath'])
                   for fact in index['facts'] for obj in fact['objects']):
            raise ValueError('Explicit macro mapping has no selected evidence')
    for source in index['facts']:
        view = source['view']
        path = source['file_identity']['effective_relpath']
        if view not in config['required_views'] or not any(fnmatchcase(path, pattern) for pattern in config['files'].get(view, ['*'])):
            continue
        matching = [i for i, item in enumerate(selectors)
                    if any(fnmatchcase(path, pattern) for pattern in item['files'])
                    and ('corner' not in item or source.get('corner_status') == 'CONFIRMED' and source.get('corner') == item['corner'])
                    and ('mode' not in item or source['file_identity'].get('mode') == item['mode'])]
        if view == 'liberty' and selectors and not matching:
            continue
        fact = deepcopy(source)
        objects = []
        object_names = set()
        for obj in fact['objects']:
            aliases = [row['macro'] for row in (mapping or {}).get('macro_aliases', [])
                       if row['view'] == view and row['object'] == obj['name']
                       and (not row.get('source_relpath') or row['source_relpath'] == fact['file_identity']['source_relpath'])]
            name = aliases[0] if len(aliases) == 1 else obj['name']
            if not config['macros'] or name in config['macros']:
                objects.append(obj)
                macros.add(name)
                identity = (name, fact.get('variant'))
                macro_variants.add(identity)
                object_names.add(identity)
        fact['objects'] = objects
        if config['macros'] and not objects:
            continue
        facts.append(fact)
        selected_paths.add(path)
        if view == 'liberty':
            for i in matching:
                matches[i] += 1
                context_macros[i].update(object_names)
    scope = {
        'effective_files': len(index['files']), 'selected_files': len(selected_paths),
        'excluded_files': len(index['files']) - len(selected_paths),
        'excluded_paths': [row['effective_relpath'] for row in index['files'] if row['effective_relpath'] not in selected_paths],
        'selected_corners': sorted({fact['corner'] for fact in facts if fact.get('corner')}),
        'selected_modes': sorted({fact['file_identity']['mode'] for fact in facts if fact['file_identity'].get('mode')}),
        'missing_selections': [item for i, item in enumerate(selectors) if not matches[i]],
        'missing_macros': sorted(set(config['macros']) - macros),
        'missing_contexts': [{'macro': name, 'variant': variant, 'selection': item}
                             for name, variant in sorted(macro_variants, key=lambda value: (value[0], value[1] or ''))
                             for i, item in enumerate(selectors) if (name, variant) not in context_macros[i]],
    }
    return facts, scope
