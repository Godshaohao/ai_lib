"""Shared read-only QoR & FileFacts view models with pluggable View adapters."""
from collections import Counter
import json
from pathlib import Path

from ai_lib_qor.application.minimal_checks import load_check_bundle
from ai_lib_qor.sources.layout import library_folder
from ai_lib_qor.versions.store import validate


def _text(value):
    if value is None:
        return ''
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def _view_lef(fact):
    macros = fact.get('objects', {}).get('macros', [])
    macro_rows = []
    pin_rows = []
    dir_counts = Counter()
    for m in macros:
        size = m.get('size_um') or [0, 0]
        w, h = float(size[0]), float(size[1])
        pins = m.get('pins', [])
        m_dirs = Counter((p.get('direction') or 'UNKNOWN').upper() for p in pins)
        dir_counts.update(m_dirs)
        macro_rows.append({
            'name': m['name'],
            'width_um': round(w, 4),
            'height_um': round(h, 4),
            'area_um2': round(w * h, 4),
            'pin_count': len(pins),
            'dir_summary': ', '.join(f'{k} {v}' for k, v in sorted(m_dirs.items())),
        })
        for p in pins:
            pin_rows.append({
                'parent': m['name'],
                'name': p['name'],
                'direction': (p.get('direction') or '').upper(),
                'use': (p.get('use') or 'SIGNAL').upper(),
            })
    return {
        'summary_metrics': [
            {'label': 'Macro 数量', 'value': len(macros)},
            {'label': 'Pin 总数', 'value': len(pin_rows)},
            {'label': 'INPUT / OUTPUT', 'value': f"{dir_counts.get('INPUT', 0)} / {dir_counts.get('OUTPUT', 0)}"},
            {'label': 'INOUT / 其他', 'value': sum(v for k, v in dir_counts.items() if k not in ('INPUT', 'OUTPUT'))},
        ],
        'entities_title': 'Macro 物理概览',
        'entities_columns': ['Macro 名称', '宽度 (um)', '高度 (um)', '面积 (um²)', 'Pin 数', '方向分布'],
        'entities': [
            [r['name'], r['width_um'], r['height_um'], r['area_um2'], r['pin_count'], r['dir_summary']]
            for r in macro_rows
        ],
        'pins_title': 'LEF Pin 明细',
        'pins': pin_rows,
        'pin_directions': sorted({p['direction'] for p in pin_rows if p['direction']}),
        'pin_uses': sorted({p['use'] for p in pin_rows if p['use']}),
        'coverage_note': '已解析 Macro 尺寸与 Pin 名称/方向/用途；不含金属层绕线与 DRC 几何图形。',
    }


def _view_liberty(fact):
    cells = fact.get('objects', {}).get('cells', [])
    cell_rows = []
    pin_rows = []
    dir_counts = Counter()
    for c in cells:
        pins = c.get('pins', [])
        c_dirs = Counter((p.get('direction') or 'UNKNOWN').upper() for p in pins)
        dir_counts.update(c_dirs)
        cell_rows.append({
            'name': c['name'],
            'pin_count': len(pins),
            'dir_summary': ', '.join(f'{k} {v}' for k, v in sorted(c_dirs.items())),
        })
        for p in pins:
            pin_rows.append({
                'parent': c['name'],
                'name': p['name'],
                'direction': (p.get('direction') or '').upper(),
                'use': 'SIGNAL',
            })
    return {
        'summary_metrics': [
            {'label': 'Cell 数量', 'value': len(cells)},
            {'label': '信号 Pin 总数', 'value': len(pin_rows)},
            {'label': 'INPUT / OUTPUT', 'value': f"{dir_counts.get('INPUT', 0)} / {dir_counts.get('OUTPUT', 0)}"},
            {'label': 'INOUT / 其他', 'value': sum(v for k, v in dir_counts.items() if k not in ('INPUT', 'OUTPUT'))},
        ],
        'entities_title': 'Liberty Cell 接口概览',
        'entities_columns': ['Cell 名称', '信号 Pin 数', '方向分布'],
        'entities': [[r['name'], r['pin_count'], r['dir_summary']] for r in cell_rows],
        'pins_title': 'Liberty 信号 Pin 明细',
        'pins': pin_rows,
        'pin_directions': sorted({p['direction'] for p in pin_rows if p['direction']}),
        'pin_uses': [],
        'coverage_note': '当前仅覆盖 CELL_NAME / PIN_NAME / PIN_DIRECTION，未解析 PG Pin、PVT Corner、时序弧或功耗表。',
    }


def _view_verilog(fact):
    modules = fact.get('objects', {}).get('modules', [])
    entity_rows = []
    pin_rows = []
    for m in modules:
        name = m.get('name', '')
        ports = m.get('ports') or m.get('port_names') or []
        entity_rows.append([name, len(ports), _text(m.get('port_directions') or '')])
        if isinstance(ports, list):
            for p in ports:
                if isinstance(p, dict):
                    pin_rows.append({'parent': name, 'name': p.get('name', _text(p)), 'direction': p.get('direction', ''), 'use': 'PORT'})
                else:
                    pin_rows.append({'parent': name, 'name': str(p), 'direction': '', 'use': 'PORT'})
    return {
        'summary_metrics': [
            {'label': 'Module 数量', 'value': len(modules)},
            {'label': '观察端口数', 'value': len(pin_rows)},
            {'label': '解析覆盖', 'value': fact.get('parse_status', 'PARTIAL')},
        ],
        'entities_title': 'Verilog Module 概览（部分解析）',
        'entities_columns': ['Module 名称', '端口数', '方向摘要'],
        'entities': entity_rows,
        'pins_title': 'Module 端口清单',
        'pins': pin_rows,
        'pin_directions': sorted({p['direction'] for p in pin_rows if p['direction']}),
        'pin_uses': [],
        'coverage_note': '仅轻量提取模块与端口声明（PARTIAL），不代表功能逻辑或完整网表已核验。',
    }


def _view_netlist(fact):
    subckts = fact.get('objects', {}).get('subcircuits', [])
    includes = fact.get('objects', {}).get('includes', [])
    entity_rows = []
    pin_rows = []
    for s in subckts:
        name = s.get('name', '')
        ports = s.get('pins') or s.get('ports') or []
        entity_rows.append([name, len(ports), len(s.get('instances', [])) if isinstance(s.get('instances'), list) else '—'])
        if isinstance(ports, list):
            for p in ports:
                pin_rows.append({'parent': name, 'name': str(p), 'direction': '', 'use': 'NET'})
    return {
        'summary_metrics': [
            {'label': 'Subcircuit 数量', 'value': len(subckts)},
            {'label': '观察引脚数', 'value': len(pin_rows)},
            {'label': 'Include 引用数', 'value': len(includes)},
        ],
        'entities_title': f"{fact.get('view', 'NETLIST')} Subcircuit 概览（部分解析）",
        'entities_columns': ['Subcircuit 名称', '引脚数', '子实例数'],
        'entities': entity_rows,
        'pins_title': 'Subcircuit 引脚清单',
        'pins': pin_rows,
        'pin_directions': [],
        'pin_uses': [],
        'includes': includes,
        'coverage_note': '仅轻量提取子电路接口与 .INCLUDE 声明（PARTIAL），不代表完整电路拓扑一致。',
    }


def _view_generic(fact):
    objs = fact.get('objects', {})
    return {
        'summary_metrics': [
            {'label': 'View 类型', 'value': fact.get('view', 'UNKNOWN')},
            {'label': '对象顶层键', 'value': len(objs)},
            {'label': '解析状态', 'value': fact.get('parse_status', 'UNKNOWN')},
        ],
        'entities_title': '对象摘要（通用视图）',
        'entities_columns': ['字段键', '项数 / 类型', '预览'],
        'entities': [
            [k, len(v) if isinstance(v, (list, dict)) else type(v).__name__, _text(v)[:200]]
            for k, v in sorted(objs.items())
        ],
        'pins_title': '',
        'pins': [],
        'pin_directions': [],
        'pin_uses': [],
        'coverage_note': '使用通用对象呈现器展示已解析结构。',
    }


FACTS_VIEW_REGISTRY = {
    'LEF': _view_lef,
    'LIBERTY': _view_liberty,
    'VERILOG': _view_verilog,
    'CDL': _view_netlist,
    'SPICE': _view_netlist,
}


def register_facts_view(view, handler, *, registry=FACTS_VIEW_REGISTRY):
    if not isinstance(view, str) or not view.strip() or not callable(handler):
        raise ValueError('Facts 视图注册参数无效')
    registry[view.upper()] = handler


def build_facts_view(fact_data, *, label=None, registry=FACTS_VIEW_REGISTRY):
    view = fact_data.get('view', 'UNKNOWN')
    adapter = registry.get(view, _view_generic)
    body = adapter(fact_data)
    return {
        'label': label or '',
        'schema_version': fact_data.get('schema_version'),
        'view': view,
        'source': fact_data.get('source', {}),
        'selection': fact_data.get('selection', {}),
        'parsed_at': fact_data.get('parsed_at', ''),
        'parser': fact_data.get('parser', {}),
        'parse_status': fact_data.get('parse_status', 'UNKNOWN'),
        'covered_sections': fact_data.get('covered_sections', []),
        'units': fact_data.get('units', {}),
        **body,
    }


def _extract_pin_map(fact):
    view = fact.get('view')
    objs = fact.get('objects', {})
    pins = {}
    sizes = {}
    if view == 'LEF':
        for m in objs.get('macros', []):
            sizes[m['name']] = m.get('size_um')
            for p in m.get('pins', []):
                pins[(m['name'], p['name'])] = {'direction': (p.get('direction') or '').upper(), 'use': (p.get('use') or 'SIGNAL').upper()}
    elif view == 'LIBERTY':
        for c in objs.get('cells', []):
            for p in c.get('pins', []):
                pins[(c['name'], p['name'])] = {'direction': (p.get('direction') or '').upper(), 'use': 'SIGNAL'}
    elif view == 'VERILOG':
        for m in objs.get('modules', []):
            for p in (m.get('ports') or m.get('port_names') or []):
                pname = p.get('name', str(p)) if isinstance(p, dict) else str(p)
                pdir = p.get('direction', '') if isinstance(p, dict) else ''
                pins[(m.get('name', ''), pname)] = {'direction': pdir, 'use': 'PORT'}
    elif view in ('CDL', 'SPICE'):
        for s in objs.get('subcircuits', []):
            for p in (s.get('pins') or s.get('ports') or []):
                pins[(s.get('name', ''), str(p))] = {'direction': '', 'use': 'NET'}
    return sizes, pins


def build_facts_diff(old_fact, new_fact, *, old_label=None, new_label=None):
    if old_fact.get('view') != new_fact.get('view'):
        raise ValueError('只能对比相同 View 的 FileFacts')
    old_sizes, old_pins = _extract_pin_map(old_fact)
    new_sizes, new_pins = _extract_pin_map(new_fact)

    size_diffs = []
    for name in sorted(old_sizes.keys() | new_sizes.keys()):
        o, n = old_sizes.get(name), new_sizes.get(name)
        status = 'ADDED' if o is None else ('REMOVED' if n is None else ('CHANGED' if o != n else 'UNCHANGED'))
        size_diffs.append({'name': name, 'old': o, 'new': n, 'status': status})

    pin_diffs = []
    counts = Counter()
    for parent, pname in sorted(old_pins.keys() | new_pins.keys()):
        o, n = old_pins.get((parent, pname)), new_pins.get((parent, pname))
        if o is None:
            status = 'ADDED'
        elif n is None:
            status = 'REMOVED'
        elif o['direction'] != n['direction']:
            status = 'DIRECTION_CHANGED'
        elif o['use'] != n['use']:
            status = 'USE_CHANGED'
        else:
            status = 'UNCHANGED'
        counts[status] += 1
        pin_diffs.append({
            'parent': parent,
            'name': pname,
            'status': status,
            'old_direction': o['direction'] if o else '',
            'new_direction': n['direction'] if n else '',
            'old_use': o['use'] if o else '',
            'new_use': n['use'] if n else '',
        })

    old_src = old_fact.get('source', {})
    new_src = new_fact.get('source', {})
    same_source = bool(
        old_src.get('absolute_path')
        and old_src.get('absolute_path') == new_src.get('absolute_path')
        and old_src.get('version') == new_src.get('version')
    )
    return {
        'view': new_fact.get('view'),
        'old_label': old_label or '',
        'new_label': new_label or '',
        'old_source': old_src,
        'new_source': new_src,
        'same_source': same_source,
        'size_diffs': size_diffs,
        'pin_diffs': pin_diffs,
        'counts': {
            'total': len(pin_diffs),
            'changed': len(pin_diffs) - counts['UNCHANGED'],
            'ADDED': counts['ADDED'],
            'REMOVED': counts['REMOVED'],
            'DIRECTION_CHANGED': counts['DIRECTION_CHANGED'],
            'USE_CHANGED': counts['USE_CHANGED'],
            'UNCHANGED': counts['UNCHANGED'],
        },
    }


def load_fact_object(work, vendor, library, *, name=None, check=None, ref=None):
    """Safely load a FileFacts JSON either from standalone disk file or embedded CheckResult evidence."""
    folder = library_folder(work, vendor, library)
    if check and ref:
        bundle = load_check_bundle(work, vendor, library, check)
        fact = bundle['facts'].get(ref) or bundle['facts'].get(Path(ref).name)
        if not fact:
            raise ValueError('检查结果中不存在指定的 FileFacts 引用')
        return fact, Path(ref).name, None
    if name:
        if '/' in name or '\\' in name or name in ('', '.', '..'):
            raise ValueError('事实文件名不安全')
        for base in (folder / 'log', folder):
            if base.is_symlink():
                continue
            path = base / name
            if path.is_file() and not path.is_symlink() and path.resolve().is_relative_to(folder.resolve()):
                data = json.loads(path.read_text(encoding='utf-8'))
                validate(data, 'file_facts_path')
                return data, path.name, path
        raise ValueError('FileFacts 文件不存在')
    raise ValueError('必须指定事实文件名或检查结果引用')


def build_check_view(work, vendor, library, check_filename):
    """Unified read-only single-revision comparison & QoR view combining FileIndex + CheckResult."""
    bundle = load_check_bundle(work, vendor, library, check_filename)
    report = bundle['report']
    index = bundle['index']
    facts_map = bundle['facts']
    revision = report['revision']
    baseline = report.get('baseline')

    parsed_by_key = {(f['view'], f['path']): f for f in report.get('files', [])}
    comp_by_key = {(c['view'], c['path']): c for c in report.get('comparisons', [])}
    partial_by_key = {(c['view'], c['path']): c for c in report.get('partial_comparisons', [])}

    file_rows = []
    source_counts = Counter()
    parse_counts = Counter()

    for view, group in index['views'].items():
        for path, hist in group.items():
            curr = next((x for x in hist['effective'] if x['revision'] == revision), None)
            prev = next((x for x in hist['effective'] if x['revision'] == baseline), None) if baseline else None
            if not curr and not prev:
                continue
            if curr and not prev:
                src_status = 'NEW' if baseline else 'CURRENT'
            elif prev and not curr:
                src_status = 'REMOVED'
            elif curr['version'] == prev['version']:
                src_status = 'INHERITED'
            else:
                src_status = 'UPDATED'
            source_counts[src_status] += 1

            finfo = parsed_by_key.get((view, path))
            p_status = finfo['status'] if finfo else ('REMOVED' if src_status == 'REMOVED' else 'NOT_CHECKED')
            parse_counts[p_status] += 1

            comp = comp_by_key.get((view, path))
            pcomp = partial_by_key.get((view, path))
            if comp:
                content_status = comp['content_status']
                compare_refs = comp.get('facts_refs') or []
            elif pcomp:
                content_status = 'PARTIAL_DIFF' if pcomp.get('differences') else 'PARTIAL_MATCH'
                compare_refs = pcomp.get('facts_refs') or []
            else:
                content_status = 'NOT_COMPARED'
                compare_refs = []

            fact_ref = Path(finfo['facts']).name if (finfo and finfo.get('facts')) else None
            has_fact = bool(fact_ref and (fact_ref in facts_map or (finfo and finfo.get('facts') in facts_map)))
            can_compare = len(compare_refs) == 2 and all(
                (r in facts_map or Path(r).name in facts_map) for r in compare_refs
            )

            file_rows.append({
                'view': view,
                'path': path,
                'source_status': src_status,
                'baseline_version': prev['version'] if prev else '',
                'target_version': curr['version'] if curr else '',
                'parse_status': p_status,
                'parse_note': finfo['note'] if finfo else '',
                'content_status': content_status,
                'fact_ref': fact_ref if has_fact else None,
                'compare_old': Path(compare_refs[0]).name if can_compare else None,
                'compare_new': Path(compare_refs[1]).name if can_compare else None,
            })

    summary = report.get('summary', {})
    failed_checks = summary.get('failed_checks', 0)
    inconclusive = summary.get('inconclusive_checks', 0)
    failed_files = summary.get('failed_files', 0)
    if failed_checks > 0 or failed_files > 0:
        q_code, q_cls, q_text = 'FAIL', 'tag-failed', '质检失败'
    elif report.get('state') != 'SUCCEEDED' or inconclusive > 0:
        q_code, q_cls, q_text = 'PARTIAL', 'tag-partial', '部分覆盖 / 无结论'
    else:
        q_code, q_cls, q_text = 'SCOPE_PASS', 'tag-new', '已覆盖范围通过'

    checks_out = []
    for c in report.get('checks', []):
        refs = [
            {'name': Path(r).name, 'available': (r in facts_map or Path(r).name in facts_map)}
            for r in (c.get('facts_refs') or [])
        ]
        checks_out.append({**c, 'resolved_refs': refs})

    excel_path = bundle['check_path'].with_suffix('.xlsx') if bundle['check_path'].parent.name == 'log' else bundle['folder'] / ('report_' + report['run_id'] + '.xlsx')
    excel_cached = excel_path.is_file()

    return {
        'vendor': vendor,
        'library': library,
        'check_name': bundle['check_path'].name,
        'excel_name': excel_path.name if (excel_cached or bundle['check_path'].parent.name == 'log') else None,
        'excel_cached': excel_cached,
        'report': report,
        'quality': {'code': q_code, 'cls': q_cls, 'text': q_text},
        'source_counts': dict(source_counts),
        'parse_counts': dict(parse_counts),
        'file_rows': file_rows,
        'checks': checks_out,
        'changes': report.get('changes', []),
        'partial_comparisons': report.get('partial_comparisons', []),
        'views_present': sorted({r['view'] for r in file_rows}),
    }


def paginate_facts_view(view_data, *, q='', direction='', use='', entity_page=1, pin_page=1, per_page=100):
    """Server-side search & pagination over build_facts_view() so large PDK files never overwhelm browser DOM."""
    q_norm = (q or '').strip().casefold()
    dir_norm = (direction or '').strip()
    use_norm = (use or '').strip()
    per_page = max(10, min(500, int(per_page or 100)))

    all_entities = view_data.get('entities', [])
    if q_norm:
        filtered_entities = [row for row in all_entities if any(q_norm in str(cell).casefold() for cell in row)]
    else:
        filtered_entities = all_entities
    e_total = len(filtered_entities)
    e_pages = max(1, (e_total + per_page - 1) // per_page)
    e_page = max(1, min(int(entity_page or 1), e_pages))
    paged_entities = filtered_entities[(e_page - 1) * per_page : e_page * per_page]

    all_pins = view_data.get('pins', [])
    filtered_pins = []
    for p in all_pins:
        if dir_norm and p.get('direction', '') != dir_norm:
            continue
        if use_norm and p.get('use', '') != use_norm:
            continue
        if q_norm and q_norm not in (f"{p.get('parent', '')} {p.get('name', '')}").casefold():
            continue
        filtered_pins.append(p)
    p_total = len(filtered_pins)
    p_pages = max(1, (p_total + per_page - 1) // per_page)
    p_page = max(1, min(int(pin_page or 1), p_pages))
    paged_pins = filtered_pins[(p_page - 1) * per_page : p_page * per_page]

    return {
        **view_data,
        'entities': paged_entities,
        'pins': paged_pins,
        'pagination': {
            'q': q or '',
            'direction': dir_norm,
            'use': use_norm,
            'per_page': per_page,
            'entity_total': e_total,
            'entity_unfiltered': len(all_entities),
            'entity_page': e_page,
            'entity_pages': e_pages,
            'pin_total': p_total,
            'pin_unfiltered': len(all_pins),
            'pin_page': p_page,
            'pin_pages': p_pages,
        },
    }


def paginate_facts_diff(diff_data, *, q='', status='auto', pin_page=1, per_page=100):
    """Server-side filter & pagination over build_facts_diff(); defaults to showing changed rows first."""
    q_norm = (q or '').strip().casefold()
    per_page = max(10, min(500, int(per_page or 100)))
    effective_status = (status or 'auto').strip()
    if effective_status == 'auto':
        effective_status = 'changed' if diff_data.get('counts', {}).get('changed', 0) > 0 else 'all'

    all_sizes = diff_data.get('size_diffs', [])
    filtered_sizes = [
        s for s in all_sizes
        if (effective_status == 'all' or (effective_status == 'changed' and s['status'] != 'UNCHANGED') or s['status'] == effective_status)
        and (not q_norm or q_norm in s['name'].casefold())
    ]

    all_pins = diff_data.get('pin_diffs', [])
    filtered_pins = []
    for p in all_pins:
        if effective_status == 'changed':
            if p['status'] == 'UNCHANGED':
                continue
        elif effective_status != 'all' and p['status'] != effective_status:
            continue
        if q_norm and q_norm not in (f"{p['parent']} {p['name']}").casefold():
            continue
        filtered_pins.append(p)

    p_total = len(filtered_pins)
    p_pages = max(1, (p_total + per_page - 1) // per_page)
    p_page = max(1, min(int(pin_page or 1), p_pages))
    paged_pins = filtered_pins[(p_page - 1) * per_page : p_page * per_page]

    return {
        **diff_data,
        'size_diffs': filtered_sizes[:200],
        'size_diffs_total': len(filtered_sizes),
        'pin_diffs': paged_pins,
        'pagination': {
            'q': q or '',
            'status': effective_status,
            'per_page': per_page,
            'pin_total': p_total,
            'pin_unfiltered': len(all_pins),
            'pin_page': p_page,
            'pin_pages': p_pages,
        },
    }


def latest_check_for_scope(work, vendor, library, revision, baseline):
    """Find the most recent saved CheckResult matching (revision, baseline) without triggering parsing."""
    if not revision:
        return None
    folder = library_folder(work, vendor, library)
    candidates = sorted(
        [*folder.glob('check_run_*.json'), *(folder / 'log').glob('check_rev_*_run_*.json')],
        key=lambda p: p.stat().st_mtime_ns,
        reverse=True,
    )
    for path in candidates:
        if path.is_symlink():
            continue
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
            if (
                data.get('schema_version') == 'check_result.path.v1'
                and data.get('revision') == revision
                and data.get('baseline') == baseline
            ):
                comp_map = {(c['view'], c['path']): c for c in data.get('comparisons', [])}
                pcomp_map = {(c['view'], c['path']): c for c in data.get('partial_comparisons', [])}
                file_map = {}
                for f in data.get('files', []):
                    key = (f['view'], f['path'])
                    comp = comp_map.get(key)
                    pcomp = pcomp_map.get(key)
                    if comp:
                        c_status = comp['content_status']
                        refs = comp.get('facts_refs') or []
                    elif pcomp:
                        c_status = 'PARTIAL_DIFF' if pcomp.get('differences') else 'PARTIAL_MATCH'
                        refs = pcomp.get('facts_refs') or []
                    else:
                        c_status = 'NOT_COMPARED'
                        refs = []
                    file_map[key] = {
                        'parse_status': f.get('status'),
                        'fact_ref': Path(f['facts']).name if f.get('facts') else None,
                        'content_status': c_status,
                        'compare_old': Path(refs[0]).name if len(refs) == 2 else None,
                        'compare_new': Path(refs[1]).name if len(refs) == 2 else None,
                    }
                summary = data.get('summary', {})
                fc = summary.get('failed_checks', 0)
                ic = summary.get('inconclusive_checks', 0)
                ff = summary.get('failed_files', 0)
                run_state = data.get('state', 'UNKNOWN')
                if fc > 0 or ff > 0:
                    q_code, q_cls, q_text = 'FAIL', 'tag-failed', '质检失败'
                elif run_state != 'SUCCEEDED' or ic > 0:
                    q_code, q_cls, q_text = 'PARTIAL', 'tag-partial', '部分覆盖 / 无结论'
                else:
                    q_code, q_cls, q_text = 'SCOPE_PASS', 'tag-new', '已覆盖范围通过'
                return {
                    'check_name': path.name,
                    'run_at': data.get('run_at', ''),
                    'state': run_state,
                    'quality_code': q_code,
                    'quality_cls': q_cls,
                    'quality_text': q_text,
                    'failed_checks': fc,
                    'inconclusive_checks': ic,
                    'failed_files': ff,
                    'files': file_map,
                }
        except (OSError, ValueError, TypeError, KeyError):
            continue
    return None
