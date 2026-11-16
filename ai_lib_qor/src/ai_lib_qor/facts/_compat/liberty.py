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
_PROCESS_CORNER_RE = re.compile(r'(?:^|[_.-])(SSG|FFG|TTG|FFPG|SSPG|TTNOMINAL|FAST|SLOW|TYP|TT|SS|FF|SF|FS)(?=$|[_.-])', re.IGNORECASE)
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
