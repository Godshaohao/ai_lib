"""Reader facts projected from existing extracts and completed check snapshots."""

import json
from pathlib import Path

from lib_guard.package.types import DOC_PACKAGE_TYPES, PARTIAL_PACKAGE_TYPES, normalize_package_type
from lib_guard.view_types import canonical_file_type


TYPES = {'lef', 'liberty', 'verilog', 'cdl'}
TYPE_LABELS = {'lef': 'LEF', 'liberty': 'Liberty', 'verilog': 'Verilog', 'cdl': 'CDL'}
TOPICS = {
    'size': ('尺寸', '核对布局尺寸、占位和相邻对象间距。'),
    'origin': ('原点', '核对布局坐标和放置脚本。'),
    'class': ('单元类别', '核对单元在实现流程中的使用方式。'),
    'site': ('放置 Site', '核对行高、Site 和放置规则。'),
    'object_set': ('单元集合', '核对设计引用的单元是否仍有交付。'),
    'pin_set': ('接口 Pin', '核对实例连接和对应视图的接口。'),
    'direction': ('Pin 方向', '核对端口方向和实例连接。'),
    'use': ('Pin 用途', '核对信号、电源和地端口连接。'),
    'width': ('端口位宽', '核对总线范围和实例连接位宽。'),
    'layers': ('Pin 金属层', '核对接入层和布线约束。'),
    'geometry': ('Pin 形状', '核对 Pin 接入位置和布线可达性。'),
    'obs': ('阻挡区域', '核对布线阻挡与通道。'),
    'conditions': ('工作条件', '核对模式、电压、温度和时序库选择。'),
    'area': ('面积字段', '核对综合或面积统计使用的库字段。'),
    'binding': ('跨视图对象对应', '确认对象名称、视图和上下文对应关系。'),
}
CHECK_TOPICS = {
    'MACRO_BINDING': 'binding', 'SIGNAL_PORT_SET': 'pin_set',
    'SIGNAL_PORT_DIRECTION': 'direction', 'PG_PORT_LEF_LIB': 'use',
    'LEF_SIZE_DELTA': 'size', 'LEF_PHYSICAL_DELTA': 'size',
    'LEF_PIN_DELTA': 'pin_set', 'LEF_INTERFACE_DELTA': 'pin_set',
    'LEF_GEOMETRY_DELTA': 'geometry', 'LEF_OBS_DELTA': 'obs',
    'LEF_MACRO_DELTA': 'object_set', 'PORT_DECLARATION_DELTA': 'width',
    'LIB_PORT_DELTA': 'pin_set', 'LIB_MACRO_FLAGS': 'class',
}


def _read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def _kind(value):
    kind = canonical_file_type(value)
    return 'verilog' if kind == 'systemverilog' else kind


def _covered(data, key):
    coverage = data.get('semantic_coverage') or {}
    return (coverage.get('validated') is True and coverage.get('basis')
            and coverage.get('schema_version') == 'semantic_parser_coverage.v1'
            and coverage.get(key) in {'PRESENT', 'ABSENT_VERIFIED'})


def file_check_alignment(model, row, inventory_cache=None):
    """Align the selected source pair with the exact comparison inventories."""
    if row.get('freshness') != '文件状态未改变':
        return 'STALE'
    if not model.get('base_version') or row.get('base_version') != model['base_version']:
        return 'SOURCE_ONLY'
    scan = model.get('scan_evidence') or {}
    meta = model.get('diff_meta') or {}
    current_scan = (scan.get('context') or {}).get('scan_dir')
    if not current_scan or not meta.get('new_scan') or Path(current_scan).resolve() != Path(meta['new_scan']).resolve():
        return 'SOURCE_ONLY'
    old_scan = meta.get('old_scan')
    if not old_scan:
        return 'SOURCE_ONLY'
    cache = inventory_cache if inventory_cache is not None else {}
    try:
        if old_scan not in cache:
            cache[old_scan] = _read(Path(old_scan) / 'file_inventory.json')
        inventories = {'old': cache[old_scan], 'new': scan.get('inventory') or {}}
        roots = model.get('source_roots') or {}
        for side, inventory in inventories.items():
            source = Path(row[side + '_file']).resolve()
            expected_root = roots.get('base' if side == 'old' else 'current')
            if not expected_root or not source.is_relative_to(Path(expected_root).resolve()):
                return 'SOURCE_ONLY'
            records = [entry for entry in inventory.get('files', [])
                       if Path(entry.get('abs_path') or Path(inventory.get('root_path') or expected_root) / entry.get('path', '')).resolve() == source]
            if len(records) != 1:
                return 'SOURCE_ONLY'
            entry, stamp = records[0], (row.get('source_stamps') or {}).get(side, {})
            if entry.get('size_bytes') != stamp.get('size') or stamp.get('mtime_ns') is None:
                return 'SOURCE_ONLY'
            if entry.get('mtime_ns') is not None:
                matches_time = entry['mtime_ns'] == stamp['mtime_ns']
            else:
                matches_time = entry.get('mtime') is not None and abs(float(entry['mtime']) - stamp['mtime_ns'] / 1e9) < 1e-6
            digest = entry.get('sha256') or entry.get('hash')
            if not matches_time or (digest and str(digest).removeprefix('sha256:') != (row.get('content_sha256') or {}).get(side)):
                return 'SOURCE_ONLY'
        return 'ALIGNED'
    except (OSError, ValueError, TypeError, KeyError):
        return 'SOURCE_ONLY'


def _objects(kind, data):
    rows = []
    if kind == 'liberty':
        groups = [(f'libraries.{library}.cells', lib.get('cells') or {}, library)
                  for library, lib in (data.get('libraries') or {}).items()]
    else:
        group = {'lef': 'macros', 'verilog': 'modules', 'cdl': 'subckts'}[kind]
        groups = [(group, data.get(group) or {}, '')]
    for prefix, objects, library in groups:
        for name, obj in objects.items():
            if kind == 'cdl':
                ports = [{'name': pin, 'direction': None, 'width': None, 'use': None, 'layers': []}
                         for pin in obj.get('pins', [])]
            else:
                key = 'ports' if kind == 'verilog' else 'pins'
                ports = [{'name': pin, **record} for pin, record in (obj.get(key) or {}).items()]
                ports += [{'name': pin, **record, 'use': record.get('pg_type') or 'POWER/GROUND'}
                          for pin, record in (obj.get('pg_pins') or {}).items()]
            def is_power(port):
                return str(port.get('use') or '').upper() in {'POWER', 'GROUND'} or bool(port.get('pg_type'))
            signal_pins = sum((str(port.get('use') or '').upper() in {'SIGNAL', 'CLOCK'}
                               or kind in {'verilog', 'liberty'} and not is_power(port)) for port in ports)
            rows.append({'name': name, 'library': library, 'path': f'{prefix}.{name}',
                         'class': obj.get('class'), 'site': obj.get('site'), 'size': obj.get('size'),
                         'area': obj.get('area'), 'unit': 'µm' if data.get('coordinate_units') == 'um' else '单位未确认',
                         'ports': ports, 'signal_pins': signal_pins,
                         'power_pins': sum(is_power(port) for port in ports)})
    return rows


def _source(kind, payload, source, evidence, *, current=True, scope='所选文件', paired=False):
    data = payload.get('data') or {}
    status = payload.get('parser_status') or payload.get('status')
    available = status in {'PASS', 'PASS_WITH_WARNING'}
    objects = _objects(kind, data) if available else []
    limitations = []
    if not available:
        limitations.append('解析未完成，当前没有可引用的对象规格')
    if data.get('parse_limitations') or (data.get('semantic_coverage') or {}).get('port_set') == 'NOT_EXTRACTED':
        limitations.append('部分接口或语法未完整提取，相关项目不能判为通过')
    contexts, units = [], {}
    if kind == 'liberty':
        limitations.append('时序性能尚未比较')
        for library, lib in (data.get('libraries') or {}).items():
            contexts += [{'name': name, 'library': library, **attrs}
                         for name, attrs in (lib.get('operating_conditions') or {}).items()]
            units[library] = {key: value for key, value in lib.items() if key.endswith('_unit')}
    if kind == 'cdl':
        limitations.append('CDL 端口顺序已提取，方向与电源角色未确认')
    if not current:
        limitations.append('来源已变化；下面保留的是历史提取，未计入当前结论')
    description = ''
    if kind == 'lef' and objects:
        sites = sorted({obj['site'] for obj in objects if obj.get('site')})
        heights = sorted({obj['size']['y'] for obj in objects if obj.get('size') and obj['size'].get('y') is not None})
        classes = sorted({obj['class'] for obj in objects if obj.get('class')})
        height_text = ' / '.join(str(value) for value in heights[:3])
        unit = 'µm' if all(obj['unit'] == 'µm' for obj in objects) else '单位未确认'
        description = f"Site {' / '.join(sites[:3]) or '未提取'}；高度 {height_text or '未提取'} {unit}；类别 {' / '.join(classes[:3])}"
    elif kind == 'liberty':
        description = 'Library：' + ' / '.join((data.get('libraries') or {}).keys())
    elif objects:
        description = ('模块：' if kind == 'verilog' else '子电路：') + ' / '.join(obj['name'] for obj in objects[:3])
    return {'file_type': kind, 'label': TYPE_LABELS[kind], 'source': source, 'evidence': str(evidence),
            'scope': scope, 'paired': paired, 'current': current, 'objects': objects,
            'object_count': len(objects), 'pin_count': sum(len(obj['ports']) for obj in objects),
            'contexts': contexts, 'units': units, 'limitations': limitations, 'description': description}


def _change_topic(suffix, kind):
    if not suffix:
        return 'object_set', '单元集合', 'macro_set' if kind == 'lef' else 'port_set'
    if suffix.startswith('size.'):
        return 'size', '宽度' if suffix.endswith('.x') else '高度', 'macro_set'
    if suffix.startswith('origin.'):
        return 'origin', '原点 ' + suffix.rsplit('.', 1)[-1], 'macro_set'
    if suffix in {'class', 'site', 'area'}:
        return suffix, TOPICS[suffix][0], 'macro_set' if kind == 'lef' else 'port_set'
    if suffix == 'obs':
        return 'obs', '阻挡区域', 'obs_geometry'
    if suffix.startswith(('pins.', 'ports.', 'pg_pins.')):
        field = suffix.rsplit('.', 1)[-1]
        topic = {'direction': 'direction', 'use': 'use', 'pg_type': 'use', 'width': 'width',
                 'declared_range': 'width', 'layers': 'layers', 'rects': 'geometry'}.get(field, 'pin_set')
        if field in {'line_start', 'line_end', 'rect_count', 'port_count', 'layer_count', 'capacitance'}:
            return None
        coverage = {'geometry': 'pin_geometry', 'layers': 'pin_layers'}.get(topic, 'port_set')
        pin_name = suffix.split('.', 1)[1]
        if field != pin_name and topic != 'pin_set':
            pin_name = pin_name.rsplit('.', 1)[0]
        label = '端口范围' if field == 'declared_range' else TOPICS[topic][0]
        return topic, label + ' · ' + pin_name, coverage
    if kind == 'cdl' and suffix == 'pins':
        return 'pin_set', '端口集合与顺序', None
    return None


def _interface_value(value):
    if not isinstance(value, dict) or not any(key in value for key in ('line_start', 'line_end', 'direction', 'use', 'pg_type')):
        return value
    fields = [('direction', '方向'), ('use', '用途'), ('pg_type', '电源角色'),
              ('width', '位宽'), ('declared_range', '端口范围'), ('layers', '层'),
              ('rect_count', '形状数')]
    return {label: value[key] for key, label in fields if value.get(key) not in (None, [], '')}


def _pair_findings(row, old_payload, new_payload, semantic):
    old, new = old_payload.get('data') or {}, new_payload.get('data') or {}
    kind = row['file_type']
    objects = {obj['path']: obj for obj in _objects(kind, old) + _objects(kind, new)}
    paths = sorted(objects, key=len, reverse=True)
    findings = []
    for item in semantic.get('changes', []):
        path = str(item.get('path') or '')
        object_path = next((key for key in paths if path == key or path.startswith(key + '.')), None)
        if object_path:
            obj = objects[object_path]
            spec = _change_topic(path[len(object_path):].lstrip('.'), kind)
            name = (obj['library'] + ' / ' if obj['library'] else '') + obj['name']
        elif '.operating_conditions.' in path:
            spec, name = ('conditions', '工作条件', None), path.removeprefix('libraries.')
        else:
            continue
        if spec is None:
            continue
        topic, label, coverage = spec
        complete = row.get('parsed_fields_status') == 'DIFF'
        if coverage:
            complete &= bool(_covered(old, coverage) and _covered(new, coverage))
        if topic in {'size', 'origin'}:
            known_units = all(data.get('coordinate_units') == 'um' for data in (old, new))
            complete &= known_units
            label += '（µm）' if known_units else '（单位未确认）'
        before = item.get('old', {'数量': item.get('old_count'), '样例': item.get('removed_samples')})
        after = item.get('new', {'数量': item.get('new_count'), '样例': item.get('added_samples')})
        if topic == 'pin_set':
            before, after = _interface_value(before), _interface_value(after)
        findings.append({'object': name, 'topic': topic, 'label': label, 'old': before, 'new': after,
                         'status': 'CHANGED' if complete else 'NOT_CHECKED', 'scope': '所选文件对',
                         'advice': TOPICS[topic][1] if complete else '补齐该字段的解析覆盖后再确认变化。',
                         'source': row['new_file'], 'base_source': row['old_file'],
                         'evidence': str(Path(row['evidence_dir']) / 'index.html')})
    return findings


def _semantic_findings(semantic):
    if semantic.get('status') != 'CURRENT':
        return []
    rows, pending_groups = [], {}
    names = semantic.get('object_names') or {}
    for is_delta, items in ((False, semantic.get('checks', [])), (True, semantic.get('delta', []))):
        for item in items:
            if item.get('status') in {'PASS', 'NOT_APPLICABLE', 'UNCHANGED'}:
                continue
            topic = CHECK_TOPICS.get(item.get('check_id'), 'binding')
            attribute = item.get('attribute')
            topic = {'size_um': 'size', 'origin': 'origin', 'class': 'class', 'interface': 'pin_set',
                     'pin_geometry': 'geometry', 'obstructions': 'obs', 'presence': 'object_set'}.get(attribute, topic)
            actual = item.get('actual') or []
            details = item.get('details') or {}
            before, after = item.get('old', details.get('old')), item.get('new', details.get('new'))
            if details.get('pins'):
                before = {pin['pin']: pin.get('old') for pin in details['pins']}
                after = {pin['pin']: pin.get('new') for pin in details['pins']}
            elif 'old_count' in details:
                before = {'数量': details['old_count']}
                after = {'数量': details.get('new_count'), '涉及 Pin': details.get('changed_pins') or []}
            if actual:
                before, after = actual[0], actual[1:]
            if not is_delta and item.get('check_id') in {'SIGNAL_PORT_SET', 'SIGNAL_PORT_DIRECTION', 'PG_PORT_LEF_LIB'}:
                # Expose only ports with different presence or attributes.
                ports = [record.get('ports') or {} for record in actual]
                different = {pin for record in ports for pin in record
                             if len({json.dumps(record.get(pin), sort_keys=True) for record in ports}) > 1}
                before = [{**record, 'ports': {pin: value for pin, value in (record.get('ports') or {}).items() if pin in different}}
                          for record in actual]
                after = None
            refs = item.get('evidence_refs') or [item.get(key) for key in ('old_evidence', 'new_evidence')]
            refs = [ref.get('parser_result_ref') or ref.get('source_ref') or '' if isinstance(ref, dict) else str(ref or '')
                    for ref in refs]
            finding = {'object': names.get(item.get('macro_id')) or item.get('macro') or '检查范围',
                         'topic': topic, 'label': TOPICS[topic][0] + ('（µm）' if attribute == 'size_um' else ''), 'old': before, 'new': after,
                         'status': item.get('status', 'NOT_CHECKED'),
                         'scope': '完整有效组合 ' + str(semantic.get('effective_id') or ''),
                         'advice': TOPICS[topic][1], 'source': '; '.join(ref for ref in refs if ref),
                         'href': f"semantic/{semantic['generation']}/summary.md" if semantic.get('generation') else '',
                         'evidence': semantic.get('details_path') or semantic.get('markdown_path') or ''}
            if finding['status'] in {'NOT_CHECKED', 'INCOMPLETE', 'UNKNOWN', 'REVIEW_REQUIRED', 'AMBIGUOUS'}:
                key = (topic, item.get('reason_code'), finding['status'])
                group = pending_groups.setdefault(key, {**finding, 'item_count': 0, 'object_examples': []})
                group['item_count'] += 1
                if len(group['object_examples']) < 3:
                    group['object_examples'].append(finding['object'])
                if item.get('reason_code') == 'UNCONFIRMED_BINDING':
                    group['advice'] = '确认这些对象的视图与上下文对应关系后，再执行接口检查。'
                else:
                    group['advice'] = '补齐所选对象的输入证据或解析范围，再执行该项检查。'
            else:
                rows.append(finding)
    for group in pending_groups.values():
        group['object'] = f"{group['item_count']} 项未覆盖（示例：{'、'.join(group.pop('object_examples'))}）"
    return rows + list(pending_groups.values())


def build_engineering_report(model):
    """Use saved extracts only: no source hashing, parser calls or directory walks."""
    sources, findings, limitations, key_facts = [], [], [], []
    selected_types = set()
    same_files = 0
    for row in model.get('representative_files', []):
        kind = _kind(row.get('file_type'))
        if kind not in TYPES:
            continue
        selected_types.add(kind)
        current = row.get('freshness') == '文件状态未改变'
        try:
            old, new = (_read(Path(row['evidence_dir']) / f'{side}_extract.json') for side in ('old', 'new'))
            semantic = _read(Path(row['evidence_dir']) / 'semantic_diff.json')
        except (OSError, ValueError, TypeError) as error:
            limitations.append(f'{TYPE_LABELS[kind]} 已保存提取不可读取：{error}')
            continue
        source = _source(kind, new, row.get('new_file') or '', Path(row['evidence_dir']) / 'index.html',
                         current=current, scope='所选 ' + TYPE_LABELS[kind] + ' 文件；不代表全部同类文件', paired=True)
        source['href'] = f"representative/{kind}/{row['evidence_id']}/index.html" if row.get('evidence_id') else ''
        sources.append(source)
        hashes = row.get('content_sha256') or {}
        same = (current and row.get('source_content_status') == 'SAME' and len(str(hashes.get('old') or '')) == 64
                and hashes.get('old') == hashes.get('new'))
        aligned = row.get('report_alignment') not in {'SOURCE_ONLY', 'STALE'}
        if same and aligned:
            same_files += 1
            key_facts.append(f"所选 {TYPE_LABELS[kind]} 文件内容未变化；已提取 {source['object_count']} 个对象、{source['pin_count']} 个声明 Pin。")
            if source['description']:
                key_facts.append('所选文件规格：' + source['description'])
        parser_conflict = same and (row.get('parsed_fields_status') == 'DIFF' or bool(semantic.get('changes')))
        if parser_conflict:
            limitations.append(f'{TYPE_LABELS[kind]} 解析结果与文件内容相同的证据冲突；需检查解析器版本和结果来源')
        pair_findings = _pair_findings({**row, 'file_type': kind}, old, new, semantic) if current and aligned and not same else []
        findings += pair_findings
        if not aligned:
            source['limitations'].append('此文件对基准或来源快照与版本报告不一致；只保留单文件结果')
        if current and row.get('source_content_status') == 'DIFF' and not pair_findings:
            limitations.append(f'{TYPE_LABELS[kind]} 字节变化未在已提取字段中解释；请查看双栏文本对比')
        if semantic.get('truncated'):
            limitations.append(f'{TYPE_LABELS[kind]} 字段变化明细已截断，完整变化数量见详细对比')

    scan = model.get('scan_evidence') or {}
    for key, payload in sorted((scan.get('parser_results') or {}).items()):
        if not isinstance(payload, dict):
            continue
        kind = _kind(payload.get('file_type'))
        if kind not in TYPES or kind in selected_types or payload.get('status') not in {'PASS', 'PASS_WITH_WARNING'}:
            continue
        selected_types.add(kind)
        data = payload.get('data') or {}
        source_path = payload.get('abs_path') or data.get('source') or payload.get('file') or ''
        sources.append(_source(kind, payload, source_path, Path((scan.get('context') or {}).get('scan_dir') or '') / key,
                               scope='当前扫描中的一个已解析文件；不代表全部同类文件'))
    if sources and not any(source['paired'] for source in sources):
        limitations.append('未执行版本深度对比')
    semantic = model.get('semantic_check') or {}
    findings += _semantic_findings(semantic)
    if semantic and semantic.get('status') != 'CURRENT':
        limitations.append('组合技术检查已过期或不可引用，未计入当前结论')
    if not semantic:
        limitations.append('跨视图单元、Pin 与上下文对应尚未执行组合检查')
    if any(source['file_type'] == 'liberty' for source in sources):
        limitations.append('时序性能尚未比较')
    corner_hints = scan.get('corner_summary') or {}
    if corner_hints.get('process_counts'):
        limitations.append('文件名中的工艺角线索：' + ' / '.join(sorted(corner_hints['process_counts'])) + '；未确认文件级 Mode/Corner 覆盖')
    delivery = (model.get('ip_user_view_model') or {}).get('delivery_completeness') or {}
    required = int(delivery.get('required_total') or 0)
    missing_requirements = list(delivery.get('missing') or []) + list(delivery.get('contract_missing') or [])
    package_type = normalize_package_type(model.get('package_type'))
    if missing_requirements:
        if package_type in PARTIAL_PACKAGE_TYPES | DOC_PACKAGE_TYPES:
            delivery_summary = '本包未交付：' + '、'.join(str(value) for value in missing_requirements) + '；有效组合继承范围待核对'
            limitations.append('单包交付检查不代表最终有效组合的视图覆盖')
        elif package_type == 'UNKNOWN_PACKAGE':
            delivery_summary = '包类型待确认；本包未交付：' + '、'.join(str(value) for value in missing_requirements)
        else:
            delivery_summary = '交付缺口：' + '、'.join(str(value) for value in missing_requirements)
    elif required:
        names = '、'.join(delivery.get('required_views') or [])
        delivery_summary = f"{names or '必需视图'} {delivery.get('required_present', 0)} / {required}"
        evidence = delivery.get('required_view_evidence') or []
        if evidence and all(item.get('validation_level') == 'metadata_required' for item in evidence):
            delivery_summary += '（仅元数据级）'
        requirements = delivery.get('delivery_requirements') or {}
        unconfigured = [label for key, label in (('modes', '模式'), ('corners', '工艺角'))
                        if (requirements.get(key) or {}).get('status') == 'NOT_CONFIGURED']
        if unconfigured:
            delivery_summary += '；' + '/'.join(unconfigured) + '未配置'
            limitations.append('仅满足已配置的视图要求，不代表整库交付齐全；模式和工艺角须按目标 IP 要求确认')
        elif delivery.get('delivery_requirement_status') == 'NOT_CONFIGURED':
            delivery_summary += '；模式/工艺角要求未配置'
            limitations.append('仅满足已配置的视图要求，不代表整库交付齐全；模式和工艺角须按目标 IP 要求确认')
        else:
            delivery_summary += '；已满足现有配置' if delivery.get('status') == 'PASS' else '；仍有检查待确认'
    else:
        delivery_summary = '尚未配置完整交付要求，不能据文件存在判断交付齐全'
    changed = sum(item['status'] == 'CHANGED' for item in findings)
    pending = sum(item.get('item_count', 1) for item in findings
                  if item['status'] in {'NOT_CHECKED', 'INCOMPLETE', 'UNKNOWN', 'REVIEW_REQUIRED', 'AMBIGUOUS'})
    failures = sum(item['status'] == 'FAIL' for item in findings)
    changed_facts = [f"{item['object']}：{item['label']}" + ('发生变化' if item['status'] == 'CHANGED' else '检查未通过')
                     for item in findings if item['status'] in {'CHANGED', 'FAIL'}]
    key_facts = list(dict.fromkeys(changed_facts))[:3] + key_facts
    if not key_facts:
        key_facts.append('当前只有交付文件范围信息，尚无已确认的工程变化结论')
    return {'sources': sources, 'findings': findings, 'same_files': same_files, 'changed': changed,
            'pending': pending, 'failures': failures, 'key_facts': key_facts,
            'limitations': list(dict.fromkeys(limitations)), 'delivery': delivery,
            'delivery_summary': delivery_summary, 'contact': model.get('review_contact') or '未登记',
            'combination': {key: semantic.get(key) for key in ('effective_id', 'base_effective_id', 'components', 'profile', 'published_at', 'status')} if semantic else {}}
