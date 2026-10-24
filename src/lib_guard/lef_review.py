"""Compare two LEF files without a catalog or scan workspace.

Run ``python -m lib_guard.lef_review OLD.lef NEW.lef [--out-dir DIR]``.
"""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys

from lib_guard.scan.parsers.lef import LEF_PARSER_VERSION, parse_lef_data_file


SCHEMA_VERSION = 'lef_analysis.v1'
OUTPUT_JSON = 'lef_analysis.json'
OUTPUT_MD = 'lef_review.md'
FIELDS = ('class', 'size', 'site', 'origin', 'symmetry')
PIN_FIELDS = ('direction', 'use', 'shape', 'layers')
FIELD_LABELS = {
    'class': '类别', 'size': '尺寸', 'site': 'Site', 'origin': '原点',
    'symmetry': '对称属性', 'direction': '方向', 'use': '用途',
    'shape': '形状', 'layers': '层', 'rects': '几何', 'obs': 'OBS',
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def _stamp(path: Path) -> tuple[int, int]:
    stat = path.stat()
    return stat.st_size, stat.st_mtime_ns


def _source(path: Path) -> tuple[dict, dict]:
    before = _stamp(path)
    data = parse_lef_data_file(path)
    digest = _sha256(path)
    if _stamp(path) != before:
        raise ValueError(f'源文件在检查过程中发生变化: {path}')
    return {'path': str(path), 'size_bytes': before[0], 'sha256': digest}, data


def _covered(data: dict, field: str) -> bool:
    coverage = data.get('semantic_coverage') or {}
    return coverage.get('validated') is True and coverage.get(field) == 'PRESENT'


def _sorted_json(values: list) -> list:
    return sorted(values, key=lambda item: json.dumps(item, ensure_ascii=False, sort_keys=True))


def _changes(old: dict, new: dict) -> dict:
    old_macros, new_macros = old.get('macros') or {}, new.get('macros') or {}
    names_covered = _covered(old, 'macro_set') and _covered(new, 'macro_set')
    names = {
        'status': 'COMPARED' if names_covered else 'UNVERIFIED',
        'added': sorted(set(new_macros) - set(old_macros)) if names_covered else None,
        'removed': sorted(set(old_macros) - set(new_macros)) if names_covered else None,
        'common_count': len(set(old_macros) & set(new_macros)) if names_covered else None,
    }
    unverified = set()
    changes = []
    if not names_covered:
        unverified.add('macro_names')
        return {'macro_names': names, 'changes': changes, 'unverified': sorted(unverified)}

    def add(macro: str, field: str, left, right) -> None:
        if left != right:
            changes.append({'macro': macro, 'field': field, 'old': left, 'new': right})

    port_covered = _covered(old, 'port_set') and _covered(new, 'port_set')
    layer_covered = _covered(old, 'pin_layers') and _covered(new, 'pin_layers')
    geometry_covered = _covered(old, 'pin_geometry') and _covered(new, 'pin_geometry')
    obs_covered = _covered(old, 'obs_geometry') and _covered(new, 'obs_geometry')
    for field, covered in (('pins', port_covered), ('pin_layers', layer_covered),
                           ('pin_geometry', geometry_covered), ('obs_geometry', obs_covered)):
        if not covered:
            unverified.add(field)
    for name in sorted(set(old_macros) & set(new_macros)):
        left, right = old_macros[name], new_macros[name]
        for field in FIELDS:
            a, b = left.get(field), right.get(field)
            if field == 'symmetry':
                a, b = sorted(a or []), sorted(b or [])
            elif (a is None) != (b is None):
                unverified.add(field)
                continue
            add(name, field, a, b)
        if port_covered:
            old_pins, new_pins = left.get('pins') or {}, right.get('pins') or {}
            add(name, 'pin_names', sorted(old_pins), sorted(new_pins))
            for pin_name in sorted(set(old_pins) & set(new_pins)):
                old_pin, new_pin = old_pins[pin_name], new_pins[pin_name]
                for field in PIN_FIELDS:
                    if field == 'layers' and not layer_covered:
                        continue
                    a, b = old_pin.get(field), new_pin.get(field)
                    if field == 'layers':
                        a, b = sorted(a or []), sorted(b or [])
                    elif (a is None) != (b is None):
                        unverified.add(f'pins.{field}')
                        continue
                    add(name, f'pins.{pin_name}.{field}', a, b)
                if geometry_covered:
                    add(name, f'pins.{pin_name}.rects', _sorted_json(old_pin.get('rects') or []),
                        _sorted_json(new_pin.get('rects') or []))
        if obs_covered:
            add(name, 'obs', _sorted_json(left.get('obs') or []), _sorted_json(right.get('obs') or []))
    return {'macro_names': names, 'changes': changes, 'unverified': sorted(unverified)}


def _statistics(data: dict) -> dict:
    macros = data.get('macros') or {}
    pins = [pin for macro in macros.values() for pin in (macro.get('pins') or {}).values()]
    sizes = [macro['size'] for macro in macros.values()
             if isinstance(macro.get('size'), dict)
             and isinstance(macro['size'].get('x'), (int, float))
             and isinstance(macro['size'].get('y'), (int, float))]

    def counts(values) -> dict[str, int]:
        return dict(sorted(Counter(str(value) if value is not None else '未提供' for value in values).items()))

    stats = data.get('stats') or {}
    macros_with_power = sum(
        any(str(pin.get('use') or '').upper() == 'POWER'
            for pin in (macro.get('pins') or {}).values())
        for macro in macros.values()
    )
    macros_with_ground = sum(
        any(str(pin.get('use') or '').upper() == 'GROUND'
            for pin in (macro.get('pins') or {}).values())
        for macro in macros.values()
    )
    result = {key: int(stats.get(key) or 0) for key in (
        'macro_count', 'pin_count', 'layer_count', 'used_layer_count',
        'pin_rect_count', 'obs_rect_count')}
    result.update({
        'macro_set_complete': _covered(data, 'macro_set'),
        'port_set_complete': _covered(data, 'port_set'),
        'pin_layers_complete': _covered(data, 'pin_layers'),
        'pin_geometry_complete': _covered(data, 'pin_geometry'),
        'obs_geometry_complete': _covered(data, 'obs_geometry'),
        'macros_with_power_pin': macros_with_power,
        'macros_with_ground_pin': macros_with_ground,
        'class_counts': counts(macro.get('class') for macro in macros.values()),
        'site_counts': counts(macro.get('site') for macro in macros.values()),
        'pin_direction_counts': counts(pin.get('direction') for pin in pins),
        'pin_use_counts': counts(pin.get('use') for pin in pins),
        'used_layers': sorted(data.get('used_layers') or []),
        'size_range_um': ({'macro_count': len(sizes),
                           'width': [min(item['x'] for item in sizes), max(item['x'] for item in sizes)],
                           'height': [min(item['y'] for item in sizes), max(item['y'] for item in sizes)]}
                          if sizes else None),
        'parse_limitation_count': int(data.get('parse_limitation_count') or 0),
    })
    return result


def analyze(old_path: str | Path, new_path: str | Path) -> dict:
    old, new = Path(old_path).expanduser().resolve(), Path(new_path).expanduser().resolve()
    for path in (old, new):
        if not path.is_file():
            raise ValueError(f'找不到 LEF 文件: {path}')
        if not path.name.lower().endswith(('.lef', '.lef.gz')):
            raise ValueError(f'只接受 .lef 或 .lef.gz 文件: {path}')
    old_source, old_data = _source(old)
    new_source, new_data = _source(new)
    comparison = _changes(old_data, new_data)
    comparison['content'] = {'status': 'SAME' if old_source['sha256'] == new_source['sha256'] else 'DIFF'}
    return {
        'schema_version': SCHEMA_VERSION,
        'parser_version': LEF_PARSER_VERSION,
        'sources': {'old': old_source, 'new': new_source},
        'statistics': {'old': _statistics(old_data), 'new': _statistics(new_data)},
        'extraction': {
            side: {'macro_names': sorted(data.get('macros') or {}), 'data': data}
            for side, data in (('old', old_data), ('new', new_data))
        },
        'comparison': comparison,
    }


def _compact(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _list_lines(names: list[str] | None, label: str, limit: int = 30) -> list[str]:
    if not names:
        return [f'- {label}：无。']
    lines = [f'- {label}（{len(names)}）：' + '、'.join(f'`{name}`' for name in names[:limit])]
    if len(names) > limit:
        lines.append(f'- 其余 {len(names) - limit} 个名称见 `lef_analysis.json`。')
    return lines


def _histogram(counts: dict[str, int]) -> str:
    return '、'.join(f'{name}：{count}' for name, count in
                    sorted(counts.items(), key=lambda item: (-item[1], item[0]))) or '无'


def _size_range(stats: dict) -> str:
    size = stats.get('size_range_um')
    if not size:
        return '未提取'
    width, height = size['width'], size['height']
    return f'{width[0]:g}～{width[1]:g} × {height[0]:g}～{height[1]:g} μm（{size["macro_count"]} 个有尺寸）'


def _render_statistics(result: dict) -> list[str]:
    old, new = result['statistics']['old'], result['statistics']['new']
    lines = [
        '## 这两个文件分别包含什么？', '',
        '统计来自本次 LEF 解析；“仅已提取”不代表文件内容完整覆盖。', '',
        '| 指标 | 旧文件 | 新文件 |', '| --- | ---: | ---: |',
    ]
    for label, key, coverage in (
        ('Macro', 'macro_count', 'macro_set_complete'),
        ('Pin', 'pin_count', 'port_set_complete'),
        ('已识别层', 'layer_count', None),
        ('已用层', 'used_layer_count', 'pin_layers_complete'),
        ('Pin RECT', 'pin_rect_count', 'pin_geometry_complete'),
        ('OBS RECT', 'obs_rect_count', 'obs_geometry_complete'),
        ('解析限制', 'parse_limitation_count', None),
    ):
        def cell(stats: dict) -> str:
            if coverage in {'pin_geometry_complete', 'obs_geometry_complete'} and not stats[coverage]:
                return '未确认'
            if coverage and not stats[coverage]:
                return f'已提取 {stats[key]}（不完整）'
            return str(stats[key])
        lines.append(f'| {label} | {cell(old)} | {cell(new)} |')
    lines.extend(['', '| 内容 | 旧文件 | 新文件 |', '| --- | --- | --- |'])
    lines.append(f'| Macro 清单覆盖 | {"完整" if old["macro_set_complete"] else "仅已提取"} | {"完整" if new["macro_set_complete"] else "仅已提取"} |')
    lines.append(f'| Macro 类别 | {_histogram(old["class_counts"])} | {_histogram(new["class_counts"])} |')
    lines.append(f'| Site | {_histogram(old["site_counts"])} | {_histogram(new["site_counts"])} |')
    lines.append(f'| 尺寸范围 | {_size_range(old)} | {_size_range(new)} |')
    lines.append(f'| Pin 方向 | {_histogram(old["pin_direction_counts"])} | {_histogram(new["pin_direction_counts"])} |')
    lines.append(f'| Pin 用途 | {_histogram(old["pin_use_counts"])} | {_histogram(new["pin_use_counts"])} |')
    def power_ground_coverage(stats: dict) -> str:
        if not stats['port_set_complete']:
            return '未确认'
        total = stats['macro_count']
        return (f'POWER {stats["macros_with_power_pin"]}/{total}；'
                f'GROUND {stats["macros_with_ground_pin"]}/{total}')
    lines.append(f'| 含供电/接地 Pin 的 Macro | {power_ground_coverage(old)} | {power_ground_coverage(new)} |')
    lines.append(f'| 已用层名称 | {", ".join(old["used_layers"]) or "无"} | {", ".join(new["used_layers"]) or "无"} |')
    lines.append('')
    return lines


def _render_macro_index(result: dict) -> list[str]:
    new = result['extraction']['new']['data']
    macros = new.get('macros') or {}
    complete = result['statistics']['new']['macro_set_complete']
    title = ('完整 Macro 索引' if complete else '已提取 Macro 候选')
    lines = [f'## 附录：Macro 逐项索引（{title}，目标文件 {len(macros)} 个）', '',
             '供电脚覆盖结论已列在前面的统计摘要；此处用于按 Macro 查找 Pin/尺寸/几何细节。'
             '没有 POWER/GROUND 声明的 Macro 单独列出，是否属于预期黑盒需按库约定判断。', '',
             '| Macro | 类别 | Site | 尺寸 (μm) | Pin | 信号/时钟 | 电源脚 | 地脚 | 用途未标注 | Pin RECT | OBS RECT |',
             '| --- | --- | --- | ---: | ---: | --- | --- | --- | ---: | ---: | ---: |']
    port_set_complete = result['statistics']['new']['port_set_complete']
    missing_power = []
    missing_ground = []
    for name, macro in sorted(macros.items()):
        pins = list((macro.get('pins') or {}).values())
        uses = Counter(pin.get('use') for pin in pins)
        power_pins = sorted(pin['name'] for pin in pins if str(pin.get('use') or '').upper() == 'POWER')
        ground_pins = sorted(pin['name'] for pin in pins if str(pin.get('use') or '').upper() == 'GROUND')
        if port_set_complete:
            if not power_pins:
                missing_power.append(name)
            if not ground_pins:
                missing_ground.append(name)
        power_display = ', '.join(f'`{pin}`' for pin in power_pins) or ('未声明' if port_set_complete else '未确认')
        ground_display = ', '.join(f'`{pin}`' for pin in ground_pins) or ('未声明' if port_set_complete else '未确认')
        size = macro.get('size') or {}
        dimensions = f'{size["x"]:g} × {size["y"]:g}' if 'x' in size and 'y' in size else '未提供'
        pin_rect_count = sum(int(pin.get('rect_count') or 0) for pin in pins)
        pin_rect_display = str(pin_rect_count) if result['statistics']['new']['pin_geometry_complete'] else '未确认'
        obs_rect_display = str(int(macro.get('obs_rect_count') or 0)) if result['statistics']['new']['obs_geometry_complete'] else '未确认'
        lines.append(f'| `{name}` | {macro.get("class") or "未提供"} | {macro.get("site") or "未提供"} | '
                     f'{dimensions} | {len(pins)} | {uses["SIGNAL"] + uses["CLOCK"]} | '
                     f'{power_display} | {ground_display} | {uses[None]} | '
                     f'{pin_rect_display} | {obs_rect_display} |')
    if port_set_complete:
        lines.extend(['', f'本索引复核：POWER {len(macros) - len(missing_power)}/{len(macros)}；'
                      f'GROUND {len(macros) - len(missing_ground)}/{len(macros)}。'])
        if missing_power:
            lines.append('未声明 POWER：' + '、'.join(f'`{name}`' for name in missing_power) + '。')
        if missing_ground:
            lines.append('未声明 GROUND：' + '、'.join(f'`{name}`' for name in missing_ground) + '。')
        if not missing_power and not missing_ground:
            lines.append('目标文件中所有 Macro 均声明 POWER 和 GROUND Pin。')
    else:
        lines.extend(['', 'Pin 提取覆盖不完整；表中“未确认”不能解释为该 Macro 没有供电 Pin。'])
    if not complete:
        lines.extend(['', '上述名称只是已提取候选，不能作为完整 Macro 清单或增删判断。'])
    old_only = result['comparison']['macro_names']['removed']
    if old_only:
        lines.extend(['', '### 仅旧文件存在的 Macro', ''])
        lines.extend(f'- `{name}`' for name in old_only)
    lines.append('')
    return lines


def _render_guidance(result: dict) -> list[str]:
    comparison = result['comparison']
    fields = {row['field'] for row in comparison['changes']}
    names = comparison['macro_names']
    lines = ['## 对接入有什么提示？', '']
    if comparison['content']['status'] == 'SAME':
        lines.append('- 两个文件字节完全相同；就这对 LEF 而言，没有新的文件内容需要核对。')
    else:
        if names['status'] == 'COMPARED' and (names['added'] or names['removed']):
            lines.append('- Macro 清单变化：核对设计实例依赖的 Macro 是否仍在目标 LEF 中。')
        if fields & {'size', 'class', 'site', 'origin', 'symmetry'}:
            lines.append('- 物理规格变化：核对布局、站点兼容性以及相关放置约束；不能仅凭 LEF 推断设计失效。')
        if any(field == 'pin_names' or field.startswith('pins.') for field in fields):
            lines.append('- Pin 定义变化：核对实例连接、端口方向及所用层。')
        if any(field == 'obs' or field.endswith('.rects') for field in fields):
            lines.append('- 几何或 OBS 变化：核对布局布线和阻挡区域；必要时运行物理验证。')
        if not comparison['changes'] and names['status'] == 'COMPARED' and not names['added'] and not names['removed']:
            lines.append('- 原文件字节不同，但所选已提取字段未见变化；需按需核对文本或未支持的语法。')
    if comparison['unverified']:
        lines.append('- 部分字段证据不足；请先补充相应解析或人工核对，不能当作“未变化”。')
    lines.append('- 其他视图未比较；本报告不判断时序、逻辑、跨视图一致性或正式放行。')
    lines.append('')
    return lines


def render_markdown(result: dict) -> str:
    old, new = result['sources']['old'], result['sources']['new']
    comparison = result['comparison']
    names, changes = comparison['macro_names'], comparison['changes']
    same = comparison['content']['status'] == 'SAME'
    lines = [
        '# LEF 双文件核查', '',
        f'- 旧文件：`{old["path"]}`', f'- 新文件：`{new["path"]}`',
        '- 范围：仅比较上述两个 LEF，不代表整个库、所有视图或发布放行。', '',
        '## 两个 LEF 文件内容相同吗？', '',
        '相同；两侧完整 SHA-256 一致。' if same else '不同；两侧完整 SHA-256 不一致。', '',
    ]
    lines.extend(_render_statistics(result))
    lines.extend(['## Macro 名称有哪些变化？', ''])
    if names['status'] != 'COMPARED':
        lines.append('无法确认完整 Macro 名称列表；至少一侧解析覆盖不足，不判定新增或删除。')
    else:
        lines.append(f'两侧共有 {names["common_count"]} 个同名 Macro。')
        lines.extend(_list_lines(names['added'], '新增'))
        lines.extend(_list_lines(names['removed'], '移除'))
    lines.extend(['', '## 共同 Macro 的规格和接口有什么变化？', ''])
    ordinary = [item for item in changes if item['field'] != 'obs' and not item['field'].endswith('.rects')]
    if same:
        lines.append('文件字节相同；两侧规格和接口原文一致，已提取字段也一致。')
    elif names['status'] != 'COMPARED':
        lines.append('Macro 清单未完整提取，本次不判断共同 Macro 的整体规格和接口是否变化。')
    elif not ordinary:
        lines.append('已提取且可核查的规格和接口字段未发现变化；这不代表未解析字段相同。')
    else:
        lines.append(f'共 {len(ordinary)} 项已确认字段变化：')
        for item in ordinary[:30]:
            field = item['field']
            label = FIELD_LABELS.get(field.split('.')[-1], field)
            lines.append(f'- `{item["macro"]}` {label}（`{field}`）：{_compact(item["old"])} → {_compact(item["new"])}')
        if len(ordinary) > 30:
            lines.append(f'- 其余 {len(ordinary) - 30} 项见 `lef_analysis.json`。')
    lines.extend(['', '## 几何与 OBS 有什么变化？', ''])
    geometry = [item for item in changes if item['field'] == 'obs' or item['field'].endswith('.rects')]
    if same:
        lines.append('文件字节相同，RECT/OBS 原文未变化；解析覆盖不代表几何语义正确。')
    elif geometry:
        lines.append(f'共 {len(geometry)} 项已确认的 RECT 几何/OBS 变化：')
        for item in geometry[:20]:
            lines.append(f'- `{item["macro"]}` {FIELD_LABELS.get(item["field"].split(".")[-1], item["field"])}（`{item["field"]}`）发生变化；旧新坐标见 `lef_analysis.json`。')
        if len(geometry) > 20:
            lines.append(f'- 其余 {len(geometry) - 20} 项见 `lef_analysis.json`。')
    elif names['status'] != 'COMPARED' or 'pin_geometry' in comparison['unverified'] or 'obs_geometry' in comparison['unverified']:
        lines.append('几何/OBS 提取不完整，本次不判断是否变化；具体覆盖限制见下。')
    else:
        lines.append('两侧完整提取的 RECT 几何/OBS 未发现变化。')
    lines.append('')
    lines.extend(_render_guidance(result))
    lines.extend(['## 哪些内容不能确认？', ''])
    unverified = comparison['unverified']
    if unverified:
        prefix = ('以下字段缺少完整解析覆盖，不能评价语义正确性：' if same else
                  '以下字段至少一侧缺少完整解析覆盖，未作为“无变化”结论：')
        lines.append(prefix + '、'.join(f'`{field}`' for field in unverified) + '。')
    elif same:
        lines.append('两文件源文本一致，但本命令不验证 LEF 语义正确性或跨视图一致性。')
    else:
        lines.append('本命令选择的字段均具有两侧解析覆盖；其他 LEF 语法及跨视图一致性未检查。')
    for side in ('old', 'new'):
        data = result['extraction'][side]['data']
        count = data.get('parse_limitation_count') or 0
        if count:
            lines.append(f'- {"旧" if side == "old" else "新"}文件解析限制记录：{count} 项；最多前 100 条样例见 JSON 的 `extraction.{side}.data.parse_limitations`。')
    if not same and not changes and names['status'] == 'COMPARED' and not names['added'] and not names['removed']:
        lines.append('- 源文件不同，但所选已提取字段未发现变化；其他文本或未覆盖语法差异仍需检查。')
    lines.extend(['', '完整提取事实、Pin 明细、旧新值和证据覆盖保存在 `lef_analysis.json`。', ''])
    lines.extend(_render_macro_index(result))
    return '\n'.join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='独立比较两个 LEF，输出结构化事实和问答报告')
    parser.add_argument('old', help='基准 LEF 路径')
    parser.add_argument('new', help='目标 LEF 路径')
    parser.add_argument('--out-dir', default='lef_review', help='报告目录，默认 ./lef_review')
    args = parser.parse_args(argv)
    try:
        result = analyze(args.old, args.new)
        report = render_markdown(result)
        out = Path(args.out_dir).expanduser().resolve()
        out.mkdir(parents=True, exist_ok=True)
        (out / OUTPUT_JSON).write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        (out / OUTPUT_MD).write_text(report, encoding='utf-8')
    except (OSError, ValueError) as exc:
        print(f'LEF 核查失败：{exc}', file=sys.stderr)
        return 2
    print(json.dumps({'status': 'DONE', 'content_status': result['comparison']['content']['status'],
                      'macro_name_status': result['comparison']['macro_names']['status'],
                      'analysis': str(out / OUTPUT_JSON), 'review': str(out / OUTPUT_MD)}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
