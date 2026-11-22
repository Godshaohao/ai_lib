"""Pluggable QoR check plugin registry for path-based FileFacts."""
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


def register_path_plugin(name, handler, *, registry=PATH_CHECK_PLUGINS):
    if not isinstance(name, str) or not name.strip():
        raise ValueError('检查插件名称无效')
    if not callable(handler):
        raise ValueError('检查插件必须可调用')
    registry[name] = handler


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


def run_path_plugins(ctx, plugins=None, *, registry=PATH_CHECK_PLUGINS):
    merged = {'checks': [], 'comparisons': [], 'partial_comparisons': [], 'changes': []}
    for _, fn in resolve_path_plugins(plugins, registry=registry):
        out = fn(ctx) or {}
        for key in merged:
            if out.get(key):
                merged[key].extend(out[key])
    return merged
