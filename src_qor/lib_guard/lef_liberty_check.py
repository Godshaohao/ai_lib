"""Cross-check one LEF review target against a Liberty file."""

from __future__ import annotations

import argparse
import gzip
import json
from pathlib import Path
import re
import sys

SCHEMA_VERSION = 'lef_liberty_check.v1'
OUTPUT_JSON = 'lef_liberty_check.json'
OUTPUT_MD = 'lef_liberty_check.md'
LIBERTY_PARSER_VERSION = 'standalone-interface-2'
_POWER_TYPES = {'primary_power', 'backup_power', 'internal_power'}
_GROUND_TYPES = {'primary_ground', 'backup_ground', 'internal_ground'}
_PROCESS_CORNER_RE = re.compile(r'(?:^|[_.-])(FFPG|SSPG|TTNOMINAL|FAST|SLOW|TYP|TT|SS|FF|SF|FS)(?=$|[_.-])', re.IGNORECASE)
_RC_CORNER_RE = re.compile(r'(?:^|[_.-])(SIGRCMIN|SIGRCMAX)(?=$|[_.-])', re.IGNORECASE)
_RE_ATTR = re.compile(r'^\s*([A-Za-z_][\w]*)\s*:\s*([^;]+)\s*;')
_STREAM_MARKER = re.compile(r'[{};"/\\*\n]')
_RE_GROUP = re.compile(r'^([A-Za-z_]\w*)\s*\((.*?)\)\s*$', re.S)


def _clean_name(value: str) -> str:
    return value.strip().strip('"').strip("'")


def _clean_attr_value(value: str):
    cleaned = _clean_name(value)
    if cleaned.lower() in {'true', 'false'}:
        return cleaned.lower() == 'true'
    return cleaned


def parse_liberty_interface_data_file(path: str | Path, *, chunk_size: int = 1024 * 1024) -> dict:
    """Standalone streaming extraction of scalar cell, pin, PG pin and PVT facts."""
    source = Path(path)
    opener = gzip.open if source.name.lower().endswith('.gz') else open
    result = {'source': str(source), 'libraries': {}, 'library_order': [], 'stats': {}}
    stack: list[tuple[str, dict | None]] = []
    limitations: list[dict] = []
    complete = True
    line_no = 1
    statement_start = 1
    statement: list[str] = []
    quote = escape = line_comment = block_comment = False
    pending_slash = pending_star = escape_next = False

    def note(reason: str, text: str = '') -> None:
        if len(limitations) < 100:
            limitations.append({'line': statement_start, 'reason': reason, 'statement': text[:160]})

    def accept_statement(delimiter: str) -> None:
        nonlocal complete, statement, statement_start
        raw = ''.join(statement)
        leading = raw[:len(raw) - len(raw.lstrip())]
        event_line = statement_start + leading.count('\n')
        text = raw.strip()
        statement = []
        parent, record = stack[-1] if stack else ('', None)
        if delimiter == '{':
            match = _RE_GROUP.fullmatch(text)
            kind, name = (match.group(1).lower(), _clean_name(match.group(2))) if match else ('unknown', '')
            value = None
            if match is None and parent in {'', 'library', 'cell'}:
                complete = False
                note('malformed_group_header', text)
            if kind == 'library' and not stack:
                if not name or name in result['libraries']:
                    complete = False
                value = {'name': name, 'line_start': event_line, 'cells': {}, 'cell_order': [],
                         'operating_conditions': {}}
                result['libraries'][name] = value
                result['library_order'].append(name)
            elif kind == 'cell' and parent == 'library' and record is not None:
                if not name or name in record['cells']:
                    complete = False
                value = {'name': name, 'line_start': event_line, 'area': None, 'is_macro': None,
                         'is_pad': None, 'attrs': {}, 'attr_lines': {}, 'pins': {}, 'pin_order': [], 'pg_pins': {}}
                record['cells'][name] = value
                record['cell_order'].append(name)
            elif kind in {'pin', 'pg_pin'} and parent in {'cell', 'bus', 'bundle'} and record is not None:
                group = 'pins' if kind == 'pin' else 'pg_pins'
                cell = record if parent == 'cell' else record.get('cell')
                if cell is None:
                    complete = False
                    note('bus_pin_without_parent_cell', text)
                    cell = {'pins': {}, 'pg_pins': {}, 'pin_order': []}
                if not name or ',' in name or name in cell[group]:
                    complete = False
                value = {'name': name, 'line_start': event_line}
                value.update({'direction': None, 'capacitance': None, 'function': None} if kind == 'pin'
                             else {'pg_type': None, 'voltage_name': None})
                if parent in {'bus', 'bundle'} and kind == 'pin' and value['direction'] is None:
                    value['direction'] = record.get('direction')
                cell[group][name] = value
                if kind == 'pin':
                    cell['pin_order'].append(name)
                    if parent in {'bus', 'bundle'}:
                        record['explicit_pin_count'] += 1
            elif kind == 'operating_conditions' and parent == 'library' and record is not None:
                value = {'name': name}
                record['operating_conditions'][name] = value
            elif kind in {'bus', 'bundle'} and parent == 'cell' and record is not None:
                value = {'name': name, 'cell': record, 'direction': None, 'explicit_pin_count': 0}
            stack.append((kind, value))
        elif delimiter == '}':
            if text or not stack:
                complete = False
                note('unbalanced_group_close', text)
            else:
                closed_kind, closed_record = stack.pop()
                if closed_kind in {'bus', 'bundle'} and closed_record.get('explicit_pin_count', 0) == 0:
                    complete = False
                    note('bus_without_explicit_member_pins', closed_record.get('name', ''))
        elif delimiter == ';':
            if re.match(r'^(pin|pg_pin|bus|bundle|cell|library)\s*\(', text, re.I):
                complete = False
                note('incomplete_object_group', text)
            match = _RE_ATTR.match(text + ';')
            if match and record is not None:
                key, value = match.group(1), _clean_attr_value(match.group(2))
                if parent == 'cell':
                    if key == 'area':
                        try:
                            value = float(value)
                        except (TypeError, ValueError):
                            pass
                    if key in {'area', 'is_macro', 'is_pad', 'cell_footprint'}:
                        record[key] = value
                    record['attrs'][key] = value
                    record['attr_lines'][key] = event_line
                elif parent == 'pin' and key in {'direction', 'capacitance', 'function', 'related_power_pin', 'related_ground_pin'}:
                    record[key] = value
                elif parent in {'bus', 'bundle'} and key in {'direction', 'bus_type'}:
                    record[key] = value
                elif parent == 'pg_pin' and key in {'pg_type', 'voltage_name'}:
                    record[key] = value
                elif parent == 'operating_conditions':
                    record[key] = value
        statement_start = line_no

    def should_capture() -> bool:
        return not stack or stack[-1][0] in {'library', 'cell', 'pin', 'pg_pin', 'bus', 'bundle', 'operating_conditions'}

    try:
        with opener(source, 'rt', encoding='utf-8', errors='replace', newline='') as stream:
            while True:
                chunk = stream.read(chunk_size)
                if not chunk:
                    break
                position = 0
                for marker in _STREAM_MARKER.finditer(chunk):
                    segment = chunk[position:marker.start()]
                    char = marker.group()
                    if line_comment:
                        line_no += segment.count('\n')
                        if char == '\n':
                            line_comment = False
                            line_no += 1
                            if should_capture():
                                statement.append('\n')
                        position = marker.end()
                        continue
                    if block_comment:
                        line_no += segment.count('\n')
                        if should_capture() and segment.count('\n'):
                            statement.append('\n' * segment.count('\n'))
                        if segment:
                            pending_star = False
                        if pending_star and char == '/':
                            block_comment = pending_star = False
                            position = marker.end()
                            continue
                        pending_star = char == '*'
                        line_no += char.count('\n')
                        position = marker.end()
                        continue
                    if quote:
                        line_no += segment.count('\n') + char.count('\n')
                        if should_capture():
                            statement.extend((segment, char))
                        if segment:
                            escape_next = False
                        if char == '\\':
                            escape_next = not escape_next
                        elif char == '"':
                            if not escape_next:
                                quote = False
                            escape_next = False
                        position = marker.end()
                        continue
                    if pending_slash:
                        if segment:
                            if should_capture():
                                statement.extend(('/', segment))
                            pending_slash = False
                        elif char == '/':
                            line_comment = True
                            pending_slash = False
                            position = marker.end()
                            continue
                        elif char == '*':
                            block_comment = True
                            pending_slash = False
                            if should_capture():
                                statement.append(' ')
                            position = marker.end()
                            continue
                        else:
                            if should_capture():
                                statement.append('/')
                            pending_slash = False
                    elif segment and should_capture():
                        statement.append(segment)
                    line_no += segment.count('\n')
                    if char == '/':
                        pending_slash = True
                    elif char == '"':
                        quote = True
                        escape_next = False
                        if should_capture():
                            statement.append(char)
                    elif char in '{};':
                        accept_statement(char)
                    elif char == '*' and should_capture():
                        statement.append(char)
                    if char == '\n':
                        if should_capture():
                            statement.append(char)
                        line_no += 1
                    position = marker.end()
                tail = chunk[position:]
                if line_comment or block_comment:
                    line_no += tail.count('\n')
                elif quote:
                    line_no += tail.count('\n')
                    if should_capture():
                        statement.append(tail)
                elif pending_slash:
                    if should_capture():
                        statement.extend(('/', tail))
                    pending_slash = False
                elif should_capture():
                    statement.append(tail)
            if pending_slash:
                statement.append('/')
            if quote or block_comment or stack or ''.join(statement).strip():
                complete = False
                note('truncated_or_unbalanced_input', ''.join(statement))
    except (OSError, EOFError) as exc:
        raise ValueError(f'无法读取 Liberty 文件 {source}: {exc}') from exc

    result['stats'] = {
        'library_count': len(result['libraries']),
        'cell_count': sum(len(lib['cells']) for lib in result['libraries'].values()),
        'pin_count': sum(len(cell['pins']) for lib in result['libraries'].values() for cell in lib['cells'].values()),
        'pg_pin_count': sum(len(cell['pg_pins']) for lib in result['libraries'].values() for cell in lib['cells'].values()),
    }
    has_supported_interface_facts = (
        result['stats']['library_count'] > 0
        and result['stats']['cell_count'] > 0
        and result['stats']['pin_count'] + result['stats']['pg_pin_count'] > 0
    )
    interface_extraction_available = complete and has_supported_interface_facts
    result['semantic_coverage'] = {
        'schema_version': 'semantic_parser_coverage.v1',
        'validated': interface_extraction_available,
        'validation_scope': 'supported_interface_extraction_only',
        'basis': '抽取器支持范围内的接口事实已读取；不代表完整 Liberty 语法或全部语义验证',
        'validation_note': (
            '已识别 Library、Cell 与至少一个 Pin/PG Pin；时序表格等未纳入本核查。'
            if interface_extraction_available else
            '未能确认有效的 Library/Cell/Pin 接口事实，或输入结构不完整；不可据此认定 Pin 集合完整。'
        ),
        'port_set': 'PRESENT' if interface_extraction_available else 'NOT_EXTRACTED',
        'pg_port_set': 'PRESENT' if interface_extraction_available else 'NOT_EXTRACTED',
    }
    result['parse_limitations'] = limitations
    result['unparsed_features'] = limitations
    return result


def _expected_pg_type(use: str) -> str:
    return 'POWER' if use == 'POWER' else 'GROUND'


def _corner_axes(path: Path, library_names: list[str]) -> dict:
    process = set()
    rc = set()
    for source in (path.name, *library_names):
        process.update(match.group(1).upper() for match in _PROCESS_CORNER_RE.finditer(source))
        rc.update(match.group(1).upper() for match in _RC_CORNER_RE.finditer(source))
    return {
        'process_corner': next(iter(process)) if len(process) == 1 else None,
        'process_corner_candidates': sorted(process),
        'rc_corner': next(iter(rc)) if len(rc) == 1 else None,
        'rc_corner_candidates': sorted(rc),
        'conflict': len(process) > 1 or len(rc) > 1,
    }


def _corner_labels(axes: dict) -> list[str]:
    return [value for value in (axes.get('process_corner'), axes.get('rc_corner')) if value]


def _cell_definitions(data: dict) -> dict[str, list[dict]]:
    definitions: dict[str, list[dict]] = {}
    for library_name, library in (data.get('libraries') or {}).items():
        for name, cell in (library.get('cells') or {}).items():
            definitions.setdefault(name, []).append({'library': library_name, **cell})
    return definitions


def _lef_pins(macro: dict) -> tuple[dict[str, dict], dict[str, dict], dict[str, dict]]:
    signals, power, ground = {}, {}, {}
    for name, pin in (macro.get('pins') or {}).items():
        use = str(pin.get('use') or '').upper()
        if use == 'POWER':
            power[name] = pin
        elif use == 'GROUND':
            ground[name] = pin
        else:
            signals[name] = pin
    return signals, power, ground


_BUS_MEMBER_RANGE = re.compile(r"^(?P<base>.*)\[(?P<first>-?\d+):(?P<last>-?\d+)\]$")
_MAX_EXPANDED_BUS_WIDTH = 65536


def _expand_liberty_signal_pins(
    pins: dict[str, dict],
) -> tuple[dict[str, dict], list[dict], list[str], list[dict]]:
    ranges: list[dict] = []
    unexpanded: list[str] = []
    definitions_by_member: dict[str, list[dict]] = {}
    for raw_name, pin in pins.items():
        match = _BUS_MEMBER_RANGE.fullmatch(str(raw_name))
        if match is None:
            definitions_by_member.setdefault(str(raw_name), []).append(
                {"name": str(raw_name), "attributes": pin})
            continue
        first, last = int(match.group("first")), int(match.group("last"))
        width = abs(first - last) + 1
        if width > _MAX_EXPANDED_BUS_WIDTH:
            unexpanded.append(str(raw_name))
            continue
        members = [f"{match.group('base')}[{index}]" for index in range(min(first, last), max(first, last) + 1)]
        ranges.append({"source": str(raw_name), "members": members})
        for member in members:
            definitions_by_member.setdefault(member, []).append(
                {"name": str(raw_name), "attributes": pin})
    expanded: dict[str, dict] = {}
    conflicts = []
    for member, definitions in definitions_by_member.items():
        distinct = {json.dumps(item["attributes"], sort_keys=True, ensure_ascii=False) for item in definitions}
        if len(distinct) > 1:
            conflicts.append({"member": member, "definitions": sorted(
                definitions, key=lambda item: (item["name"], json.dumps(item["attributes"], sort_keys=True,
                                                                          ensure_ascii=False)))})
        else:
            expanded[member] = definitions[0]["attributes"]
    conflicts.sort(key=lambda item: item["member"])
    return expanded, ranges, unexpanded, conflicts


def _compare_cell(macro_name: str, macro: dict, library_name: str, cell: dict,
                  lef_ports_complete: bool, liberty_ports_complete: bool,
                  liberty_pg_complete: bool) -> dict:
    lef_signals, lef_power, lef_ground = _lef_pins(macro)
    raw_liberty_pins = cell.get('pins') or {}
    liberty_pins, expanded_bus_ranges, unexpanded_bus_ranges, bus_definition_conflicts = (
        _expand_liberty_signal_pins(raw_liberty_pins))
    liberty_pg_pins = cell.get('pg_pins') or {}
    signal_result = {'missing_in_liberty': [], 'extra_in_liberty': [], 'direction_mismatch': [],
                     'expanded_bus_ranges': expanded_bus_ranges,
                     'bus_definition_conflicts': bus_definition_conflicts}
    pg_result = {'missing_in_liberty': [], 'extra_in_liberty': [], 'wrong_type': [], 'unverified_type': [],
                 'name_alias_candidates': []}
    unverified = [f'Liberty 总线范围过大，未展开核对：{name}' for name in unexpanded_bus_ranges]
    unverified.extend(f'Liberty 总线/单 Pin 定义冲突，未核对成员：{item["member"]}'
                      for item in bus_definition_conflicts)
    conflicted_members = {item["member"] for item in bus_definition_conflicts}

    if lef_ports_complete and liberty_ports_complete and not unexpanded_bus_ranges:
        signal_names = set(lef_signals) - conflicted_members
        liberty_signal_names = set(liberty_pins) - conflicted_members
        signal_result['missing_in_liberty'] = sorted(signal_names - liberty_signal_names)
        signal_result['extra_in_liberty'] = sorted(liberty_signal_names - signal_names)
        for pin_name in sorted(signal_names & liberty_signal_names):
            lef_direction = str(lef_signals[pin_name].get('direction') or '').upper()
            liberty_direction = str((liberty_pins[pin_name] or {}).get('direction') or '').lower()
            if not lef_direction or not liberty_direction:
                unverified.append(f'信号脚方向未提取：{pin_name}')
            elif lef_direction.lower() != liberty_direction:
                signal_result['direction_mismatch'].append({
                    'pin': pin_name, 'lef': lef_direction, 'liberty': liberty_direction,
                })
    elif not (lef_ports_complete and liberty_ports_complete):
        unverified.append('信号 Pin 清单解析覆盖不完整')

    if lef_ports_complete and liberty_pg_complete:
        expected_pg = {**{name: ('POWER', pin) for name, pin in lef_power.items()},
                       **{name: ('GROUND', pin) for name, pin in lef_ground.items()}}
        lef_by_alias = {}
        liberty_by_alias = {}
        for name in expected_pg:
            if name.endswith('!') and name not in liberty_pg_pins:
                lef_by_alias.setdefault(name[:-1], []).append(name)
        for name in liberty_pg_pins:
            if not name.endswith('!'):
                liberty_by_alias.setdefault(name, []).append(name)
        alias_names = {}
        for alias, lef_names in lef_by_alias.items():
            liberty_names = liberty_by_alias.get(alias, [])
            if len(lef_names) == len(liberty_names) == 1:
                alias_names[lef_names[0]] = liberty_names[0]
        matched_liberty_pg_names = set(expected_pg)
        for pin_name, (lef_use, _) in expected_pg.items():
            liberty_name = pin_name if pin_name in liberty_pg_pins else alias_names.get(pin_name)
            liberty_pg = liberty_pg_pins.get(liberty_name) if liberty_name else None
            if liberty_pg is None:
                if pin_name in liberty_pins:
                    pg_result['wrong_type'].append({
                        'pin': pin_name, 'lef_use': lef_use, 'liberty_pg_type': 'ordinary_pin',
                    })
                else:
                    pg_result['missing_in_liberty'].append(pin_name)
                continue
            matched_liberty_pg_names.add(liberty_name)
            if liberty_name != pin_name:
                pg_result['name_alias_candidates'].append({
                    'lef': pin_name, 'liberty': liberty_name, 'lef_use': lef_use,
                    'liberty_pg_type': liberty_pg.get('pg_type'),
                })
                unverified.append(f'电源/地脚名称待确认：LEF {pin_name} 与 Liberty {liberty_name}')
            pg_type = str(liberty_pg.get('pg_type') or '').lower()
            expected = _POWER_TYPES if lef_use == 'POWER' else _GROUND_TYPES
            opposite = _GROUND_TYPES if lef_use == 'POWER' else _POWER_TYPES
            if not pg_type:
                pg_result['unverified_type'].append(pin_name)
            elif pg_type in opposite:
                pg_result['wrong_type'].append({
                    'pin': pin_name, 'lef_use': lef_use, 'liberty_pg_type': pg_type,
                })
            elif pg_type not in expected:
                pg_result['unverified_type'].append(pin_name)
        liberty_pg_names = set(liberty_pg_pins)
        pg_result['extra_in_liberty'] = sorted(liberty_pg_names - matched_liberty_pg_names)
    else:
        unverified.append('电源脚解析覆盖不完整')

    has_mismatch = any(signal_result[key] for key in ('missing_in_liberty', 'extra_in_liberty', 'direction_mismatch')) or any(
        pg_result[key] for key in ('missing_in_liberty', 'extra_in_liberty', 'wrong_type'))
    status = 'MISMATCH' if has_mismatch else ('UNVERIFIED' if unverified or pg_result['unverified_type'] else 'MATCH')
    return {
        'macro': macro_name,
        'library': library_name,
        'status': status,
        'signal_pins': signal_result,
        'signal_pin_checked_count': len((set(lef_signals) | set(liberty_pins)) - conflicted_members)
        if lef_ports_complete and liberty_ports_complete else None,
        'power_ground': {
            'lef_power_pins': sorted(lef_power),
            'liberty_power_pins': sorted(name for name, pin in liberty_pg_pins.items()
                                         if str(pin.get('pg_type') or '').lower() in _POWER_TYPES),
            'lef_ground_pins': sorted(lef_ground),
            'liberty_ground_pins': sorted(name for name, pin in liberty_pg_pins.items()
                                          if str(pin.get('pg_type') or '').lower() in _GROUND_TYPES),
            **pg_result,
        },
        'power_ground_checked_count': len(set(lef_power) | set(lef_ground) | set(liberty_pg_pins))
        if lef_ports_complete and liberty_pg_complete else None,
        'unverified': unverified,
    }


def _load_lef_report(lef_analysis_path: str | Path) -> tuple[Path, dict]:
    lef_path = Path(lef_analysis_path).expanduser().resolve()
    if not lef_path.is_file():
        raise ValueError(f'找不到 LEF 核查报告: {lef_path}')
    try:
        lef_report = json.loads(lef_path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f'无法读取 LEF 核查 JSON: {exc}') from exc
    if lef_report.get('schema_version') != 'lef_analysis.v1':
        raise ValueError('输入必须是 lef_review.py 生成的 lef_analysis.v1 JSON')
    return lef_path, lef_report


def _analyze_loaded(lef_path: Path, lef_report: dict, liberty_path: str | Path,
                    *, keep_matching_cells: bool = True) -> dict:
    lib_path = Path(liberty_path).expanduser().resolve()
    if not lib_path.is_file() or not lib_path.name.lower().endswith(('.lib', '.lib.gz')):
        raise ValueError(f'找不到 Liberty 文件或扩展名不受支持: {lib_path}')

    target = lef_report.get('extraction', {}).get('new', {})
    lef_data = target.get('data') or {}
    lef_macros = lef_data.get('macros') or {}
    lef_stats = lef_report.get('statistics', {}).get('new', {})
    liberty_data = parse_liberty_interface_data_file(lib_path)
    liberty_parser_stats = liberty_data.get('stats') or {}
    liberty_cells = _cell_definitions(liberty_data)
    lef_macro_names = set(lef_macros)
    liberty_cell_names = set(liberty_cells)
    lef_names_complete = lef_stats.get('macro_set_complete') is True
    lef_ports_complete = lef_stats.get('port_set_complete') is True
    coverage = liberty_data.get('semantic_coverage') or {}
    liberty_ports_complete = coverage.get('validated') is True and coverage.get('port_set') == 'PRESENT'
    liberty_pg_complete = coverage.get('validated') is True and coverage.get('pg_port_set') == 'PRESENT'

    cells = []
    for name in sorted(lef_macro_names & liberty_cell_names):
        for definition in liberty_cells[name]:
            cells.append(_compare_cell(name, lef_macros[name], definition['library'], definition,
                                       lef_ports_complete, liberty_ports_complete, liberty_pg_complete))
    missing = sorted(lef_macro_names - liberty_cell_names) if lef_names_complete and liberty_ports_complete else None
    extra = sorted(liberty_cell_names - lef_macro_names) if lef_names_complete and liberty_ports_complete else None
    summary = {
        'lef_macro_count': len(lef_macro_names),
        'liberty_cell_count': len(liberty_cell_names),
        'matched_macro_count': len(lef_macro_names & liberty_cell_names),
        'lef_only_macro_count': len(missing) if missing is not None else None,
        'liberty_only_cell_count': len(extra) if extra is not None else None,
        'mismatch_cell_count': sum(row['status'] == 'MISMATCH' for row in cells),
        'unverified_cell_count': sum(row['status'] == 'UNVERIFIED' for row in cells),
        'signal_pin_checked_count': sum(row['signal_pin_checked_count'] or 0 for row in cells),
        'signal_pin_missing_count': sum(len(row['signal_pins']['missing_in_liberty']) for row in cells),
        'signal_pin_extra_count': sum(len(row['signal_pins']['extra_in_liberty']) for row in cells),
        'signal_pin_direction_mismatch_count': sum(len(row['signal_pins']['direction_mismatch']) for row in cells),
        'power_ground_checked_count': sum(row['power_ground_checked_count'] or 0 for row in cells),
        'lef_power_pin_count': sum(len(row['power_ground']['lef_power_pins']) for row in cells),
        'liberty_power_pin_count': sum(len(row['power_ground']['liberty_power_pins']) for row in cells),
        'lef_ground_pin_count': sum(len(row['power_ground']['lef_ground_pins']) for row in cells),
        'liberty_ground_pin_count': sum(len(row['power_ground']['liberty_ground_pins']) for row in cells),
        'power_ground_missing_count': sum(len(row['power_ground']['missing_in_liberty']) for row in cells),
        'power_ground_extra_count': sum(len(row['power_ground']['extra_in_liberty']) for row in cells),
        'power_ground_wrong_type_count': sum(len(row['power_ground']['wrong_type']) for row in cells),
        'power_ground_unverified_type_count': sum(len(row['power_ground']['unverified_type']) for row in cells),
        'signal_pin_coverage_complete': lef_ports_complete and liberty_ports_complete,
        'power_ground_coverage_complete': lef_ports_complete and liberty_pg_complete,
    }
    if not keep_matching_cells:
        cells = [row for row in cells if row['status'] != 'MATCH']
    corner_axes = _corner_axes(lib_path, sorted(liberty_data.get('libraries') or {}))
    return {
        'schema_version': SCHEMA_VERSION,
        'lef_analysis': str(lef_path),
        'lef_source': (lef_report.get('sources') or {}).get('new') or {},
        'liberty_source': str(lib_path),
        'library_names': sorted(liberty_data.get('libraries') or {}),
        'corner_axes': corner_axes,
        'corner_labels': _corner_labels(corner_axes),
        'operating_conditions': {
            library_name: library.get('operating_conditions') or {}
            for library_name, library in (liberty_data.get('libraries') or {}).items()
        },
        'liberty_inventory': {
            'cell_count': liberty_parser_stats.get('cell_count'),
            'signal_pin_count': liberty_parser_stats.get('pin_count'),
            'pg_pin_count': int(liberty_parser_stats.get('pg_pin_count') or 0),
            'cell_names': sorted(liberty_cell_names),
        },
        'liberty_parser_version': LIBERTY_PARSER_VERSION,
        'liberty_coverage': coverage,
        'summary': summary,
        'comparison': {'lef_only_macros': missing, 'liberty_only_cells': extra,
                       'lef_name_coverage_complete': lef_names_complete,
                       'liberty_cell_coverage_complete': liberty_ports_complete},
        'cells': cells,
        'matching_cell_details_omitted': not keep_matching_cells,
        'liberty_parse_limitations': liberty_data.get('parse_limitations') or [],
    }


def analyze(lef_analysis_path: str | Path, liberty_path: str | Path) -> dict:
    lef_path, lef_report = _load_lef_report(lef_analysis_path)
    return _analyze_loaded(lef_path, lef_report, liberty_path)


def analyze_many(
    lef_analysis_path: str | Path, liberty_paths: list[str | Path], *, keep_matching_cells: bool = False,
) -> dict:
    if not liberty_paths:
        raise ValueError('至少指定一个 .lib 或 .lib.gz 文件')
    lef_path, lef_report = _load_lef_report(lef_analysis_path)
    lef_stats = lef_report.get('statistics', {}).get('new', {})
    files = [_analyze_loaded(lef_path, lef_report, path, keep_matching_cells=keep_matching_cells)
             for path in liberty_paths]
    corner_labels = sorted({label for item in files for label in item['corner_labels']})
    corner_file_counts = {
        label: sum(label in item['corner_labels'] for item in files) for label in corner_labels
    }
    process_corner_labels = sorted({
        item['corner_axes']['process_corner'] for item in files
        if item['corner_axes'].get('process_corner')
    })
    rc_corner_labels = sorted({
        item['corner_axes']['rc_corner'] for item in files
        if item['corner_axes'].get('rc_corner')
    })
    process_corner_file_counts = {
        label: sum(item['corner_axes'].get('process_corner') == label for item in files)
        for label in process_corner_labels
    }
    rc_corner_file_counts = {
        label: sum(item['corner_axes'].get('rc_corner') == label for item in files)
        for label in rc_corner_labels
    }
    scope_groups: dict[tuple[tuple[str, ...] | None, tuple[str, ...] | None], list[dict]] = {}
    for item in files:
        lef_only = item['comparison'].get('lef_only_macros')
        lib_only = item['comparison'].get('liberty_only_cells')
        if lef_only or lib_only:
            scope_groups.setdefault((tuple(lef_only) if lef_only is not None else None,
                                     tuple(lib_only) if lib_only is not None else None), []).append(item)
    summarized_groups = [
        {'liberty_files': [item['liberty_source'] for item in grouped],
         'lef_only_macros': list(key[0] or ()), 'liberty_only_cells': list(key[1] or ())}
        for key, grouped in scope_groups.items()
    ]
    lef_macros = (lef_report.get('extraction', {}).get('new', {}).get('data') or {}).get('macros') or {}
    lef_macro_names = set(lef_macros)
    coverage_groups: dict[tuple[str, str, str], list[dict]] = {}
    for item in files:
        axes = item.get('corner_axes') or {}
        process = axes.get('process_corner') or '未识别'
        rc = axes.get('rc_corner') or '未识别'
        # Conflicting labels cannot establish a shared analysis context; isolate
        # those files instead of accidentally combining their Cell inventories.
        conflict_key = item['liberty_source'] if axes.get('conflict') else ''
        coverage_groups.setdefault((process, rc, conflict_key), []).append(item)
    set_coverages = []
    lef_set_complete = lef_stats.get('macro_set_complete') is True
    for (process, rc, _conflict_key), grouped_files in sorted(coverage_groups.items()):
        group_cells = set().union(*(
            set((item.get('liberty_inventory') or {}).get('cell_names') or [])
            for item in grouped_files
        ))
        group_complete = lef_set_complete and all(
            (item.get('liberty_coverage') or {}).get('validated') is True
            for item in grouped_files
        )
        set_coverages.append({
            'process_corner': process, 'rc_corner': rc,
            'context_status': 'LABEL_CONFLICT' if _conflict_key else (
                'UNIDENTIFIED' if process == '未识别' and rc == '未识别' else 'LABEL_BASED'
            ),
            'scope': '仅本次传入且归入此标签组的 Liberty 文件；标签是文件名/Library 名线索，不是人工确认',
            'liberty_files': [item['liberty_source'] for item in grouped_files],
            'liberty_file_count': len(grouped_files),
            'lef_macro_count': len(lef_macro_names) if lef_set_complete else None,
            'liberty_union_cell_count': len(group_cells) if group_complete else None,
            'matched_macro_count': len(lef_macro_names & group_cells) if group_complete else None,
            'lef_only_macro_count': len(lef_macro_names - group_cells) if group_complete else None,
            'liberty_only_cell_count': len(group_cells - lef_macro_names) if group_complete else None,
            'lef_only_macros': sorted(lef_macro_names - group_cells) if group_complete else None,
            'liberty_only_cells': sorted(group_cells - lef_macro_names) if group_complete else None,
            'coverage_complete': group_complete,
        })
    set_coverage = set_coverages[0] if len(set_coverages) == 1 else {
        'scope': '按已识别的工艺角/RC 角分组，禁止跨组补齐；未识别角标单列为一组',
        'coverage_complete': all(item['coverage_complete'] for item in set_coverages),
        'groups': set_coverages,
    }
    return {
        'schema_version': 'lef_liberty_batch.v1',
        'lef_analysis': str(lef_path),
        'lef_source': (lef_report.get('sources') or {}).get('new') or {},
        'lef_inventory': {
            key: lef_stats.get(key) for key in (
                'macro_count', 'pin_count', 'layer_count', 'used_layer_count',
                'pin_rect_count', 'obs_rect_count', 'pin_use_counts', 'pin_direction_counts',
                'class_counts', 'site_counts', 'used_layers', 'size_range_um',
            )
        },
        'summary': {
            'liberty_file_count': len(files),
            'files_with_mismatches': sum(item['summary']['mismatch_cell_count'] > 0 for item in files),
            'files_with_unverified': sum(item['summary']['unverified_cell_count'] > 0 for item in files),
            'files_with_scope_gaps': sum(
                (item['summary']['lef_only_macro_count'] or 0) > 0
                or (item['summary']['liberty_only_cell_count'] or 0) > 0 for item in files),
            'recognized_corners': corner_labels,
            'recognized_corner_count': len(corner_labels),
            'corner_file_counts': corner_file_counts,
            'process_corner_file_counts': process_corner_file_counts,
            'rc_corner_file_counts': rc_corner_file_counts,
            'files_with_unknown_process_corner': sum(
                not item['corner_axes'].get('process_corner') for item in files),
            'files_with_unknown_rc_corner': sum(
                not item['corner_axes'].get('rc_corner') for item in files),
            'files_with_corner_label_conflict': sum(
                item['corner_axes'].get('conflict', False) for item in files),
            'files_with_unknown_corner': sum(not item['corner_labels'] for item in files),
            'files_with_incomplete_signal_pin_coverage': sum(
                not item['summary']['signal_pin_coverage_complete'] for item in files),
            'files_with_incomplete_power_ground_coverage': sum(
                not item['summary']['power_ground_coverage_complete'] for item in files),
            'identical_scope_gap_groups': len(summarized_groups),
            'files_in_identical_scope_gap_groups': sum(len(group['liberty_files']) for group in summarized_groups),
            'signal_pin_checked_count': sum(item['summary']['signal_pin_checked_count'] for item in files),
            'signal_pin_mismatch_count': sum(
                item['summary']['signal_pin_missing_count'] + item['summary']['signal_pin_extra_count']
                + item['summary']['signal_pin_direction_mismatch_count'] for item in files),
            'power_ground_checked_count': sum(item['summary']['power_ground_checked_count'] for item in files),
            'power_ground_issue_count': sum(
                item['summary']['power_ground_missing_count'] + item['summary']['power_ground_extra_count']
                + item['summary']['power_ground_wrong_type_count'] for item in files),
        },
        'scope_gap_groups': summarized_groups,
        'set_coverage': set_coverage,
        'set_coverages': set_coverages,
        'files': files,
    }


def render_markdown(result: dict) -> str:
    if result.get('schema_version') == 'lef_liberty_batch.v1':
        summary = result['summary']
        lef_inventory = result.get('lef_inventory') or {}
        pin_uses = lef_inventory.get('pin_use_counts') or {}
        used_layers = lef_inventory.get('used_layers') or []
        process_counts = summary.get('process_corner_file_counts') or {}
        rc_counts = summary.get('rc_corner_file_counts') or {}
        process_text = '、'.join(f'{corner} {count}' for corner, count in process_counts.items()) or '未识别'
        rc_text = '、'.join(f'{corner} {count}' for corner, count in rc_counts.items()) or '未识别'
        class_counts = lef_inventory.get('class_counts') or {}
        size_range = lef_inventory.get('size_range_um') or {}
        width = size_range.get('width') or []
        height = size_range.get('height') or []
        size_text = (f'{width[0]}–{width[-1]} × {height[0]}–{height[-1]} μm'
                     if len(width) == 2 and len(height) == 2 else '未提供')
        lines = [
            '# LEF–Liberty 多文件联动核查', '',
            f'- LEF 核查报告：`{result["lef_analysis"]}`',
            f'- LEF 目标文件：`{result["lef_source"].get("path", "未知")}`',
            f'- Liberty 文件：{summary["liberty_file_count"]} 个；逐文件独立核查，不跨角合并。',
            f'- 角标统计：工艺角 {process_text}；RC 角 {rc_text}。'
            f'工艺角未识别 {summary.get("files_with_unknown_process_corner", 0)} 个，'
            f'未标 RC 角 {summary.get("files_with_unknown_rc_corner", 0)} 个；'
            f'标签冲突 {summary.get("files_with_corner_label_conflict", 0)} 个文件。',
            '- 工艺角和 RC 角仅按文件名/Library 名标注；不代表角条件完整，也不代替人工确认。',
            f'- 同名 Cell 接口存在已确认不一致：{summary["files_with_mismatches"]} 个文件。',
            f'- 同名 Cell 接口核查有证据不足：{summary["files_with_unverified"]} 个文件。', '',
            f'- 单个 Liberty 文件未覆盖全部 LEF 名称：{summary["files_with_scope_gaps"]} 个；'
            f'这些单文件名称差异归并为 {summary["identical_scope_gap_groups"]} 组。',
            f'- 信号 Pin 对照：{summary["signal_pin_checked_count"]} 项，'
            f'差异 {summary["signal_pin_mismatch_count"]} 项；电源/地脚对照：'
            f'{summary["power_ground_checked_count"]} 项，差异 {summary["power_ground_issue_count"]} 项。', '',
            '## 各 Liberty 文件的名称覆盖', '',
            '本节先给出本次输入文件集合的并集，再列单文件覆盖。单文件未包含的 Macro 不直接等于交付缺失。',
            '信号 Pin 与电源/地脚差异只对该 Liberty 文件中的同名 Cell 统计；未匹配对象不在该项对照范围内。',
        ]
        set_coverages = result.get('set_coverages') or [result.get('set_coverage') or {}]
        lines.extend(['', '### 本次输入 Liberty 集合覆盖', '',
                      '按识别到的工艺角/RC 角分组统计，不跨组补齐；角标来自文件名或 Library 名，未人工确认。'])
        for group in set_coverages:
            lef_set_count = group.get('lef_macro_count')
            union_match_count = group.get('matched_macro_count')
            union_coverage_text = (
                f'{union_match_count}/{lef_set_count}（{union_match_count / lef_set_count * 100:.1f}%）'
                if isinstance(union_match_count, int) and isinstance(lef_set_count, int) and lef_set_count
                else '无法确认（LEF 或 Liberty 解析覆盖不足）'
            )
            lines.extend([
                f'- **{group.get("process_corner", "角未识别")} / {group.get("rc_corner", "RC 角未识别")}**：'
                f'{group.get("liberty_file_count", 0)} 个输入文件；集合覆盖 {union_coverage_text}；'
                f'Cell 并集 {group.get("liberty_union_cell_count", "未确认")} 个。',
                f'  - LEF 有、该组文件未包含：{group.get("lef_only_macro_count", "未确认")} 个；'
                f'Liberty 有、LEF 未列出：{group.get("liberty_only_cell_count", "未确认")} 个。',
                f'  - 文件：{", ".join(Path(path).name for path in group.get("liberty_files", [])) or "未列出"}。',
            ])
        lines.extend([
            '- “未包含”描述的是本次传入的对应角标组，不自动判定交付缺失；未识别角标文件单独作为未识别组。',
        ])
        for item in result['files']:
            stats = item['summary']
            lef_count = stats.get('lef_macro_count') or 0
            matched = stats.get('matched_macro_count') or 0
            coverage = f'{matched}/{lef_count}（{matched / lef_count * 100:.1f}%）' if lef_count else '无法计算'
            lef_only = stats.get('lef_only_macro_count')
            lef_only_text = str(lef_only) if lef_only is not None else '未确认'
            source_name = Path(item['liberty_source']).name
            lines.append(f'- `{source_name}`：同名 Cell 覆盖 {coverage}；LEF 有、当前 Liberty 文件未包含 {lef_only_text} 个 Macro；Pin 差异只适用于这 {matched} 个同名对象。')
        lines.extend([
            '',
            '| Liberty 文件 | 同名 Cell 覆盖 | LEF 有、当前 Liberty 文件未包含 | 同名对象 Pin 差异 |',
            '| --- | ---: | ---: | ---: |',
        ])
        for item in result['files']:
            stats = item['summary']
            lef_count = stats.get('lef_macro_count') or 0
            matched = stats.get('matched_macro_count') or 0
            coverage = f'{matched}/{lef_count}（{matched / lef_count * 100:.1f}%）' if lef_count else '无法计算'
            lef_only = stats.get('lef_only_macro_count')
            lef_only_text = str(lef_only) if lef_only is not None else '未确认'
            signal_delta = (stats.get('signal_pin_missing_count', 0) + stats.get('signal_pin_extra_count', 0)
                            + stats.get('signal_pin_direction_mismatch_count', 0))
            pg_delta = (stats.get('power_ground_missing_count', 0) + stats.get('power_ground_extra_count', 0)
                        + stats.get('power_ground_wrong_type_count', 0))
            pin_delta = f'信号 {signal_delta}；电源/地 {pg_delta}'
            source_name = Path(item['liberty_source']).name
            lines.append(f'| `{source_name}` | {coverage} | {lef_only_text} | {pin_delta} |')
        lines.extend([
            '', '名称覆盖统计只回答“此文件包含哪些 LEF 同名对象”，不能单独作为交付完整性结论。', '',
            '## LEF 基准规模', '',
            '| Macro | Pin | Signal / Power / Ground | 使用层数 | 尺寸范围（宽 × 高） | Pin 几何 | OBS 几何 |',
            '| ---: | ---: | ---: | ---: | --- | ---: | ---: |',
            f'| {lef_inventory.get("macro_count", "未提供")} | {lef_inventory.get("pin_count", "未提供")} | '
            f'{pin_uses.get("SIGNAL", 0)} / {pin_uses.get("POWER", 0)} / {pin_uses.get("GROUND", 0)} | '
            f'{lef_inventory.get("used_layer_count", "未提供")}（{", ".join(used_layers) or "未列出"}） | '
            f'{size_text} | {lef_inventory.get("pin_rect_count", "未提供")} | '
            f'{lef_inventory.get("obs_rect_count", "未提供")} |',
            f'- Macro 类别：{", ".join(f"{name}: {count}" for name, count in sorted(class_counts.items())) or "未提供"}.', '',
            '以下 Liberty 数量只覆盖该文件实际包含且与 LEF 同名的 Cell；LEF 基准规模不代表本文件交付覆盖。', '',
            '| Liberty 文件 | Library | 工艺角 / RC 角 | Cell 数（LEF/LIB/同名） | LEF-only / LIB-only | 信号 Pin 对照 / 差异 | 电源地脚对照 / 差异 | 未验证 |',
            '| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |',
        ])
        for item in result['files']:
            stats = item['summary']
            libs = ', '.join(f'`{name}`' for name in item.get('library_names', [])) or '未识别'
            lef_only = stats['lef_only_macro_count'] if stats['lef_only_macro_count'] is not None else '未确认'
            lib_only = stats['liberty_only_cell_count'] if stats['liberty_only_cell_count'] is not None else '未确认'
            scope = f'{lef_only} / {lib_only}'
            signal_delta = stats['signal_pin_missing_count'] + stats['signal_pin_extra_count'] + stats['signal_pin_direction_mismatch_count']
            pg_delta = stats['power_ground_missing_count'] + stats['power_ground_extra_count'] + stats['power_ground_wrong_type_count']
            oc = item.get('operating_conditions') or {}
            oc_values = []
            for conditions in oc.values():
                for condition in conditions.values():
                    values = [f'{key}={condition[key]}' for key in ('process', 'voltage', 'temperature') if condition.get(key) is not None]
                    if values:
                        oc_values.append(', '.join(values))
            axes = item.get('corner_axes') or {}
            process_corner = axes.get('process_corner') or '工艺角未识别'
            if axes.get('rc_corner'):
                rc_corner = axes['rc_corner']
            elif len(axes.get('rc_corner_candidates') or []) > 1:
                rc_corner = 'RC 角冲突'
            else:
                rc_corner = '无 RC 角标'
            corner = f'{process_corner} / {rc_corner}'
            if oc_values:
                corner += '; ' + '; '.join(oc_values)
            source_name = Path(item['liberty_source']).name
            lines.append(f'| `{source_name}` | {libs} | {corner} | {stats["lef_macro_count"]} / '
                         f'{stats["liberty_cell_count"]} / {stats["matched_macro_count"]} | {scope} | '
                         f'{stats["signal_pin_checked_count"]} / {signal_delta} | '
                         f'{stats["power_ground_checked_count"]} / {pg_delta} | {stats["unverified_cell_count"]} |')
            inventory = item.get('liberty_inventory') or {}
            lines.append(f'| ↳ Liberty 解析总量 | — | — | {inventory.get("cell_count", "未提供")} Cell / '
                         f'{inventory.get("signal_pin_count", "未提供")} 信号 Pin / '
                         f'{inventory.get("pg_pin_count", 0) if inventory.get("pg_pin_count") is not None else 0} 电源地 Pin | — | — | — | — |')
        lines.extend(['', '## 核查范围与未检查项', '',
                      f'- 信号 Pin 解析覆盖不完整：{summary["files_with_incomplete_signal_pin_coverage"]} 个文件；'
                      f'电源/地脚解析覆盖不完整：{summary["files_with_incomplete_power_ground_coverage"]} 个文件。',
                      '- “解析覆盖已提取”只表示当前抽取器支持范围内读到了接口事实，不等于完整 Liberty 语法验证或全部 Pin 集合的独立证明。',
                      '- 每个 Liberty 文件独立核对；不会用其他工艺角或 RC 角的 Cell、Pin 补齐本文件。',
                      '- 本报告未检查时序弧与时序数值、功耗数值、跨 Corner 等价性或正式发布放行。'])
        if result.get('scope_gap_groups'):
            lines.extend(['', '## 名称覆盖范围', '',
                          '仅表示指定 LEF 与单个 Liberty 文件的 Cell 名称集合差异；不直接等于交付缺失。相同差异集合只列一次。', ''])
            for group in result['scope_gap_groups']:
                sources = ', '.join(Path(path).name for path in group['liberty_files'])
                lines.append(f'- 涉及 {len(group["liberty_files"])} 个文件（{sources}）')
                if group['lef_only_macros']:
                    names = ', '.join(f'`{name}`' for name in group['lef_only_macros'][:20])
                    suffix = f'；另有 {len(group["lef_only_macros"]) - 20} 个名称见 JSON' if len(group['lef_only_macros']) > 20 else ''
                    lines.append(f'  - LEF 有、当前 Liberty 文件未包含：{len(group["lef_only_macros"])} 个；示例：{names}{suffix}')
                if group['liberty_only_cells']:
                    names = ', '.join(f'`{name}`' for name in group['liberty_only_cells'][:20])
                    suffix = f'；另有 {len(group["liberty_only_cells"]) - 20} 个名称见 JSON' if len(group['liberty_only_cells']) > 20 else ''
                    lines.append(f'  - Liberty 有、LEF 未找到：{len(group["liberty_only_cells"])} 个；示例：{names}{suffix}')
        lines.extend(['', '每个文件的结论仅适用于该文件与指定 LEF 的同名对象；不同工艺角或 RC 角不互相补齐或合并。',
                      '角标只按文件名和 Library 名识别，未识别时不作推断；PVT 数值另列于逐文件行。',
                      '完整差异、解析覆盖和绝对来源路径保存在 JSON。', ''])
        return '\n'.join(lines)
    summary = result['summary']
    lines = [
        '# LEF–Liberty 联动核查', '',
        f'- LEF 核查报告：`{result["lef_analysis"]}`',
        f'- LEF 目标文件：`{result["lef_source"].get("path", "未知")}`',
        f'- Liberty 文件：`{result["liberty_source"]}`',
        '- 核查范围：Macro/Cell 名称、信号 Pin 名称与方向、LEF POWER/GROUND 与 Liberty `pg_pin` 声明。', '',
        '## 核查摘要', '',
        '| 项目 | 结果 |', '| --- | ---: |',
        f'| LEF Macro | {summary["lef_macro_count"]} |',
        f'| Liberty Cell | {summary["liberty_cell_count"]} |',
        f'| 同名对象 | {summary["matched_macro_count"]} |',
        f'| LEF 有、Liberty 无 | {summary["lef_only_macro_count"] if summary["lef_only_macro_count"] is not None else "未确认"} |',
        f'| Liberty 有、LEF 无 | {summary["liberty_only_cell_count"] if summary["liberty_only_cell_count"] is not None else "未确认"} |',
        f'| 确认不一致 | {summary["mismatch_cell_count"]} 个定义 |',
        f'| 证据不足 | {summary["unverified_cell_count"]} 个定义 |', '',
    ]
    for title, key in (('当前 Liberty 文件未包含的 LEF Macro', 'lef_only_macros'),
                       ('LEF 中未找到的 Liberty Cell', 'liberty_only_cells')):
        names = result['comparison'][key]
        if names:
            shown = ', '.join(f'`{name}`' for name in names[:30])
            suffix = f'；其余 {len(names) - 30} 个名称见 JSON' if len(names) > 30 else ''
            lines.extend([f'## {title}（{len(names)}）', '', shown + suffix, ''])
    lines.extend(['## 同名对象的接口核查', '',
                  '| Macro / Cell | Liberty 库 | 状态 | 信号 Pin 差异 | 电源脚差异 |',
                  '| --- | --- | --- | --- | --- |'])
    issue_rows = [row for row in result['cells'] if row['status'] != 'MATCH']
    for row in issue_rows:
        signal = row['signal_pins']
        pg = row['power_ground']
        details = []
        if signal['missing_in_liberty']:
            details.append('LIB 缺少 ' + ', '.join(signal['missing_in_liberty']))
        if signal['extra_in_liberty']:
            details.append('LIB 多出 ' + ', '.join(signal['extra_in_liberty']))
        if signal['direction_mismatch']:
            details.append('方向不一致 ' + ', '.join(f"{item['pin']}({item['lef']}→{item['liberty']})" for item in signal['direction_mismatch']))
        pg_details = []
        if pg['missing_in_liberty']:
            pg_details.append('LIB 缺少 ' + ', '.join(pg['missing_in_liberty']))
        if pg['wrong_type']:
            pg_details.append('用途不一致 ' + ', '.join(f"{item['pin']}({item['lef_use']}→{item['liberty_pg_type']})" for item in pg['wrong_type']))
        if pg['extra_in_liberty']:
            pg_details.append('LIB 多出 ' + ', '.join(pg['extra_in_liberty']))
        details.extend(row['unverified'])
        lines.append(f'| `{row["macro"]}` | `{row["library"]}` | {row["status"]} | '
                     f'{"；".join(details) or "无"} | {"；".join(pg_details) or "无"} |')
    if not issue_rows:
        if summary['matched_macro_count']:
            lines.append('| — | — | 匹配 | 同名对象的 Pin 和电源脚均匹配 | — |')
        else:
            lines.append('| — | — | 无同名对象 | 无法进行 Pin 和电源脚核对 | — |')
    lines.extend(['', 'MATCH 表示当前解析字段一致；UNVERIFIED 表示解析覆盖不足。Cell 名称按精确字符串匹配。',
                  '本报告不检查时序弧、功耗数值、跨 Corner 一致性或正式发布放行。',
                  '完整逐 Cell 结果和解析限制见 `lef_liberty_check.json`。', ''])
    return '\n'.join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='读取 LEF 双文件核查报告，与 .lib/.lib.gz 做接口联动核查')
    parser.add_argument('lef_analysis_json', help='lef_review.py 生成的 lef_analysis.json')
    parser.add_argument('liberty', nargs='+', help='一个或多个待核查的 .lib 或 .lib.gz 文件；逐文件独立核查')
    parser.add_argument('--out-dir', default='lef_liberty_check', help='输出目录，默认 ./lef_liberty_check')
    args = parser.parse_args(argv)
    try:
        result = analyze_many(args.lef_analysis_json, args.liberty)
        out = Path(args.out_dir).expanduser().resolve()
        out.mkdir(parents=True, exist_ok=True)
        (out / OUTPUT_JSON).write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        (out / OUTPUT_MD).write_text(render_markdown(result), encoding='utf-8')
    except (OSError, ValueError) as exc:
        print(f'LEF–Liberty 核查失败：{exc}', file=sys.stderr)
        return 2
    print(json.dumps({'status': 'DONE', 'summary': result['summary'],
                      'analysis': str(out / OUTPUT_JSON), 'report': str(out / OUTPUT_MD)}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
