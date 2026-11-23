"""Pluggable QoR check plugin registry with metadata for path-based FileFacts."""
from .plugins import lef_liberty_pin_match, lef_macro_diff


def run_lef_liberty_pin_match(ctx):
    """Cross-check LEF Macro signal pins against uniquely matched Liberty Cell pins."""
    checks = []
    facts = ctx['facts']
    lef = [(key, p, f) for key, (p, f) in facts.items() if key[0] == 'LEF']
    libs = [(key, p, f) for key, (p, f) in facts.items() if key[0] == 'LIBERTY']
    for key, lefpath, leffact in lef:
        names = {x['name'] for x in leffact['objects']['macros']}
        matches = [(k, p, f) for k, p, f in libs if names and names <= {x['name'] for x in f['objects']['cells']}]
        for libkey, libpath, libfact in matches:
            cells = {x['name'] for x in libfact['objects']['cells']}
            owners = [k for k, _, candidate in lef if {x['name'] for x in candidate['objects']['macros']} & cells]
            if len(owners) != 1:
                checks.append({
                    'check_id': 'LEF_LIBERTY_PIN_MATCH',
                    'scope_file_keys': [key[1], libkey[1]],
                    'result': 'INCONCLUSIVE',
                    'coverage': 'UNKNOWN',
                    'facts_refs': [lefpath.name, libpath.name],
                    'detail': '同一 Liberty 对应多个 LEF，配对不唯一，未执行检查',
                })
                continue
            a = {**leffact, 'facts_id': lefpath.name}
            b = {**libfact, 'facts_id': libpath.name}
            checks.append(lef_liberty_pin_match.compare(a, b, key[1], libkey[1]))
        if not matches:
            checks.append({
                'check_id': 'LEF_LIBERTY_PIN_MATCH',
                'scope_file_keys': [key[1]],
                'result': 'INCONCLUSIVE',
                'coverage': 'UNKNOWN',
                'facts_refs': [lefpath.name],
                'detail': '未找到可配对的 Liberty Cell；无法检查信号 Pin',
            })
    if not lef:
        checks.append({
            'check_id': 'LEF_LIBERTY_PIN_MATCH',
            'scope_file_keys': [],
            'result': 'INCONCLUSIVE',
            'coverage': 'UNKNOWN',
            'facts_refs': [],
            'detail': '未解析到 LEF，接口检查未执行',
        })
    return {'checks': checks}


def run_lef_macro_diff(ctx):
    """Compare target LEF macros & pins against baseline revision LEF facts."""
    checks, comparisons, changes = [], [], []
    facts = ctx['facts']
    target = ctx['target']
    baseline = ctx['baseline']
    obtain = ctx['obtain']
    for key, (lefpath, leffact) in facts.items():
        if key[0] != 'LEF':
            continue
        previous = baseline.get(key)
        if not previous:
            continue
        try:
            oldpath, oldfact = obtain('LEF', key[1], previous)
            old = {**oldfact, 'facts_id': oldpath.name}
            new = {**leffact, 'facts_id': lefpath.name}
            diff = lef_macro_diff.compare(old, new)
            if diff is None:
                raise ValueError('LEF 对比覆盖不足')
            comparisons.append({
                'view': 'LEF',
                'path': key[1],
                'baseline_version': previous['version'],
                'version': target[key]['version'],
                'content_status': 'CURRENT_CONTENT_DIFF' if diff else 'CURRENT_CONTENT_MATCH',
                'facts_refs': [oldpath.name, lefpath.name],
            })
            for item in diff:
                changes.append({
                    'view': 'LEF',
                    'path': key[1],
                    'baseline_version': previous['version'],
                    'version': target[key]['version'],
                    **item,
                })
        except (OSError, ValueError, KeyError, TypeError) as exc:
            checks.append({
                'check_id': 'LEF_MACRO_DIFF',
                'scope_file_keys': [key[1]],
                'result': 'INCONCLUSIVE',
                'coverage': 'UNKNOWN',
                'facts_refs': [lefpath.name],
                'detail': f'基线解析或比较失败: {exc}',
            })
    return {'checks': checks, 'comparisons': comparisons, 'changes': changes}


def run_verilog_partial_diff(ctx):
    """Compare lightweight Verilog module/port observations against baseline."""
    from ai_lib_qor.facts._compat.verilog import diff_verilog_summary
    checks, partial = [], []
    for key, (newpath, newfact) in ctx['facts'].items():
        view, path = key
        previous = ctx['baseline'].get(key)
        if view != 'VERILOG' or not previous:
            continue
        try:
            oldpath, oldfact = ctx['obtain'](view, path, previous)
            convert = lambda f: {'modules': {x['name']: x for x in f['objects']['modules']}}
            delta = diff_verilog_summary(convert(oldfact), convert(newfact))['module_changes']
            differences = {k: v for k, v in delta.items() if v}
            partial.append({
                'view': view,
                'path': path,
                'baseline_version': previous['version'],
                'version': ctx['target'][key]['version'],
                'coverage': 'PARTIAL',
                'differences': differences,
                'facts_refs': [oldpath.name, newpath.name],
                'note': '仅比较轻量解析到的模块端口或子电路引脚；不代表完整网表一致',
            })
        except (OSError, ValueError, KeyError, TypeError) as exc:
            checks.append({
                'check_id': 'VERILOG_PARTIAL_DIFF',
                'scope_file_keys': [path],
                'result': 'INCONCLUSIVE',
                'coverage': 'UNKNOWN',
                'facts_refs': [newpath.name],
                'detail': f'基线解析或比较失败: {exc}',
            })
    return {'checks': checks, 'partial_comparisons': partial}


def run_netlist_partial_diff(ctx):
    """Compare lightweight CDL/SPICE subcircuit observations against baseline."""
    from ai_lib_qor.facts._compat.cdl import diff_cdl_summary
    checks, partial = [], []
    for key, (newpath, newfact) in ctx['facts'].items():
        view, path = key
        previous = ctx['baseline'].get(key)
        if view not in ('CDL', 'SPICE') or not previous:
            continue
        try:
            oldpath, oldfact = ctx['obtain'](view, path, previous)
            convert = lambda f: {'subckts': {x['name']: x for x in f['objects']['subcircuits']}}
            delta = diff_cdl_summary(convert(oldfact), convert(newfact))['subckt_changes']
            differences = {k: v for k, v in delta.items() if v}
            partial.append({
                'view': view,
                'path': path,
                'baseline_version': previous['version'],
                'version': ctx['target'][key]['version'],
                'coverage': 'PARTIAL',
                'differences': differences,
                'facts_refs': [oldpath.name, newpath.name],
                'note': '仅比较轻量解析到的模块端口或子电路引脚；不代表完整网表一致',
            })
        except (OSError, ValueError, KeyError, TypeError) as exc:
            checks.append({
                'check_id': view + '_PARTIAL_DIFF',
                'scope_file_keys': [path],
                'result': 'INCONCLUSIVE',
                'coverage': 'UNKNOWN',
                'facts_refs': [newpath.name],
                'detail': f'基线解析或比较失败: {exc}',
            })
    return {'checks': checks, 'partial_comparisons': partial}


PATH_CHECK_PLUGINS = {
    'LEF_LIBERTY_PIN_MATCH': run_lef_liberty_pin_match,
    'LEF_MACRO_DIFF': run_lef_macro_diff,
    'VERILOG_PARTIAL_DIFF': run_verilog_partial_diff,
    'NETLIST_PARTIAL_DIFF': run_netlist_partial_diff,
}

PATH_CHECK_PLUGIN_META = {
    'LEF_LIBERTY_PIN_MATCH': {
        'version': '1.0',
        'description': 'LEF/Liberty 信号 Pin 一致性核验',
        'required_views': ('LEF', 'LIBERTY'),
        'requires_baseline': False,
    },
    'LEF_MACRO_DIFF': {
        'version': '1.0',
        'description': 'LEF Macro SIZE 与 Pin 跨版本对比',
        'required_views': ('LEF',),
        'requires_baseline': True,
    },
    'VERILOG_PARTIAL_DIFF': {
        'version': '1.0',
        'description': 'Verilog 轻量模块端口对比（PARTIAL）',
        'required_views': ('VERILOG',),
        'requires_baseline': True,
    },
    'NETLIST_PARTIAL_DIFF': {
        'version': '1.0',
        'description': 'CDL/SPICE 轻量字电路引脚对比（PARTIAL）',
        'required_views': ('CDL', 'SPICE'),
        'requires_baseline': True,
    },
}


def register_path_plugin(
    name,
    handler,
    *,
    version='1.0',
    description='',
    required_views=(),
    requires_baseline=False,
    registry=PATH_CHECK_PLUGINS,
):
    if not isinstance(name, str) or not name.strip():
        raise ValueError('检查插件名称无效')
    if not callable(handler):
        raise ValueError('检查插件必须可调用')
    if not isinstance(version, str) or not version.strip():
        raise ValueError('检查插件版本号无效')
    registry[name] = handler
    if registry is PATH_CHECK_PLUGINS:
        PATH_CHECK_PLUGIN_META[name] = {
            'version': version.strip(),
            'description': description or name,
            'required_views': tuple(str(v).upper() for v in required_views),
            'requires_baseline': bool(requires_baseline),
        }


def evaluate_check_verdict(report: dict) -> dict:
    """Single canonical quality verdict for CheckResult across check list, detail page/API, and Excel."""
    if not isinstance(report, dict):
        return {
            'code': 'PARTIAL',
            'cls': 'tag-partial',
            'text': '未执行有效检查 / 无结论',
            'failed_checks': 0,
            'inconclusive_checks': 0,
            'failed_files': 0,
        }
    summary = report.get('summary') or {}
    checks = report.get('checks') or []
    comparisons = report.get('comparisons') or []
    partial_comparisons = report.get('partial_comparisons') or []
    comparison_count = int(report.get('comparison_count', 0) or 0)

    fc = max(
        int(summary.get('failed_checks', 0) or 0),
        sum(1 for c in checks if isinstance(c, dict) and c.get('result') == 'FAIL'),
    )
    ic = max(
        int(summary.get('inconclusive_checks', 0) or 0),
        sum(1 for c in checks if isinstance(c, dict) and c.get('result') == 'INCONCLUSIVE'),
    )
    ff = int(summary.get('failed_files', 0) or 0)
    run_state = report.get('state', 'UNKNOWN')

    has_executed_rules = bool(checks or comparisons or partial_comparisons or comparison_count > 0)
    tooling = report.get('tooling') or {}
    plugin_cov = tooling.get('plugin_coverage') if isinstance(tooling, dict) else None
    has_not_executed_plugin = isinstance(plugin_cov, dict) and any(v == 'NOT_EXECUTED' for v in plugin_cov.values())

    if fc > 0 or ff > 0 or run_state == 'FAILED':
        code, cls, text = 'FAIL', 'tag-failed', '质检失败'
    elif not has_executed_rules:
        code, cls, text = 'PARTIAL', 'tag-partial', '未执行有效检查 / 无结论'
    elif run_state != 'SUCCEEDED' or ic > 0 or has_not_executed_plugin:
        code, cls, text = 'PARTIAL', 'tag-partial', '部分覆盖 / 无结论'
    else:
        code, cls, text = 'SCOPE_PASS', 'tag-new', '已覆盖范围通过'

    return {
        'code': code,
        'cls': cls,
        'text': text,
        'failed_checks': fc,
        'inconclusive_checks': ic,
        'failed_files': ff,
    }


def plugin_versions(names=None, *, registry=PATH_CHECK_PLUGINS):
    """Return {plugin_name: version} for tooling freshness tracking."""
    target = list(registry.keys()) if names is None else list(names)
    out = {}
    for name in target:
        if name not in registry:
            continue
        meta = PATH_CHECK_PLUGIN_META.get(name, {}) if registry is PATH_CHECK_PLUGINS else {}
        ver = meta.get('version') or getattr(registry[name], 'plugin_version', None) or '1.0'
        out[name] = str(ver)
    return out


def list_path_plugins(*, registry=PATH_CHECK_PLUGINS):
    out = []
    for name in registry:
        meta = PATH_CHECK_PLUGIN_META.get(name, {}) if registry is PATH_CHECK_PLUGINS else {}
        out.append({
            'name': name,
            'version': meta.get('version') or '1.0',
            'description': meta.get('description') or name,
            'required_views': list(meta.get('required_views') or ()),
            'requires_baseline': bool(meta.get('requires_baseline', False)),
        })
    return out


def resolve_path_plugins(names=None, *, registry=PATH_CHECK_PLUGINS):
    if names is None:
        return list(registry.items())
    if not isinstance(names, (list, tuple)) or not names:
        raise ValueError('插件列表不能为空')
    if len(names) != len(set(names)):
        raise ValueError('检查插件名称重复')
    unknown = [n for n in names if n not in registry]
    if unknown:
        raise ValueError('未注册的路径式检查插件: ' + ', '.join(unknown))
    return [(n, registry[n]) for n in names]


def describe_check_note(
    plugin_names,
    *,
    parsed_views=(),
    partial_views=(),
    not_checked_views=(),
    plugin_coverage=None,
    registry=PATH_CHECK_PLUGINS,
):
    """Build a truthful coverage boundary note dynamically from active plugins, actual coverage, and parsed views."""
    def _desc(name):
        meta = PATH_CHECK_PLUGIN_META.get(name, {}) if registry is PATH_CHECK_PLUGINS else {}
        return meta.get('description') or name

    if isinstance(plugin_coverage, dict):
        executed = [_desc(n) for n in plugin_names if plugin_coverage.get(n) == 'EXECUTED']
        not_executed = [_desc(n) for n in plugin_names if plugin_coverage.get(n) == 'NOT_EXECUTED']
    else:
        executed = [_desc(n) for n in plugin_names]
        not_executed = []

    parts = [f"已执行检查插件：{'、'.join(executed) if executed else '无'}"]
    if not_executed:
        parts.append(f"未执行检查插件：{'、'.join(not_executed)}")
    if partial_views:
        parts.append(f"{'/'.join(sorted(partial_views))} 仅轻量部分解析（PARTIAL）")
    if not_checked_views:
        parts.append(f"{'/'.join(sorted(not_checked_views))} 等视图暂未检查（NOT_CHECKED）")
    elif not parsed_views:
        parts.append('本次未解析到受支持视图')
    parts.append('当前来源对比不证明历史交付字节一致，检查通过不代表整库全量通过或人工采纳。')
    return '；'.join(parts)


def run_path_plugins(ctx, plugins=None, *, registry=PATH_CHECK_PLUGINS):
    resolved = resolve_path_plugins(plugins, registry=registry)
    executed_names = [name for name, _ in resolved]
    merged = {
        'checks': [],
        'comparisons': [],
        'partial_comparisons': [],
        'changes': [],
        'plugins_executed': executed_names,
        'plugin_versions': plugin_versions(executed_names, registry=registry),
        'plugin_produced': {},
    }
    for name, fn in resolved:
        out = fn(ctx) or {}
        produced = False
        for key in ('checks', 'comparisons', 'partial_comparisons', 'changes'):
            items = out.get(key)
            if items:
                merged[key].extend(items)
                if key in ('checks', 'comparisons', 'partial_comparisons'):
                    produced = True
        merged['plugin_produced'][name] = produced
    return merged
