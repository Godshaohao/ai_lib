from __future__ import annotations

from pathlib import Path
from typing import Any
import gzip
import re

from .base import BaseParser, make_parser_envelope, record_abs_path, get_field, read_text_file

LIBERTY_PARSER_VERSION = '2.4'
_RE_ATTR = re.compile(r'^\s*([A-Za-z_][\w]*)\s*:\s*([^;]+)\s*;')


def _clean_name(x: str) -> str:
    return x.strip().strip('"').strip("'")


def _clean_attr_value(value: str) -> Any:
    cleaned = _clean_name(value)
    lowered = cleaned.lower()
    if lowered in {"true", "false"}:
        return lowered == "true"
    return cleaned


_RE_BOUNDARY = re.compile(r'"(?:\\.|[^"\\])*"|//[^\n]*|/\*.*?\*/|[{};]', re.S)
_STREAM_MARKER = re.compile(r'[{};"/\\*\n]')
_RE_GROUP = re.compile(r'^([A-Za-z_]\w*)\s*\((.*?)\)\s*$', re.S)


def _liberty_statements(text):
    buffer, position, line_no, start = [], 0, 1, 1
    valid = True
    for match in _RE_BOUNDARY.finditer(text):
        gap = text[position:match.start()]
        valid &= '"' not in gap and '/*' not in gap
        buffer.append(gap)
        line_no += gap.count('\n')
        token = match.group()
        if token.startswith(('//', '/*')):
            buffer.append('\n' * token.count('\n') + ' ')
        elif token.startswith('"'):
            buffer.append(token)
        else:
            statement = ''.join(buffer)
            leading = statement[:len(statement) - len(statement.lstrip())]
            yield token, statement.strip(), start + leading.count('\n'), valid
            buffer = []
            start = line_no
            valid = True
        line_no += token.count('\n')
        position = match.end()
    tail = ''.join(buffer) + text[position:]
    if tail.strip():
        yield 'invalid', tail.strip(), start, False


def parse_liberty_text(text: str, source: str = '') -> dict[str, Any]:
    result: dict[str, Any] = {'source': source, 'libraries': {}, 'library_order': [], 'stats': {}}
    stack = []
    complete = True
    limitations = []
    for delimiter, statement, line_no, valid in _liberty_statements(text):
        complete &= valid
        parent, record = stack[-1] if stack else ('', None)
        if delimiter == '{':
            match = _RE_GROUP.fullmatch(statement)
            if match is None:
                complete = False
                if len(limitations) < 100:
                    limitations.append({'line': line_no, 'reason': 'malformed_group_header_or_missing_semicolon',
                                        'statement': statement[:160]})
            kind, name = (match.group(1).lower(), _clean_name(match.group(2))) if match else ('unknown', '')
            value = None
            if kind == 'library' and not stack:
                complete &= name not in result['libraries']
                value = {'name': name, 'line_start': line_no, 'cells': {}, 'cell_order': [], 'operating_conditions': {}}
                result['libraries'][name] = value
                result['library_order'].append(name)
            elif kind == 'cell' and parent == 'library':
                complete &= name not in record['cells']
                value = {'name': name, 'line_start': line_no, 'area': None, 'is_macro': None, 'is_pad': None,
                         'attrs': {}, 'attr_lines': {}, 'pins': {}, 'pin_order': [], 'pg_pins': {}}
                record['cells'][name] = value
                record['cell_order'].append(name)
            elif kind in {'pin', 'pg_pin'} and parent == 'cell':
                complete &= bool(name) and ',' not in name
                group = 'pins' if kind == 'pin' else 'pg_pins'
                complete &= name not in record[group]
                value = {'name': name, 'line_start': line_no}
                value.update({'direction': None, 'capacitance': None, 'function': None} if kind == 'pin'
                             else {'pg_type': None, 'voltage_name': None})
                record[group][name] = value
                if kind == 'pin':
                    record['pin_order'].append(name)
            elif kind == 'operating_conditions' and parent == 'library':
                value = {'name': name}
                record['operating_conditions'][name] = value
            elif kind in {'bus', 'bundle', 'pin', 'pg_pin', 'cell', 'library'}:
                complete = False
            stack.append((kind, value))
        elif delimiter == '}':
            if statement or not stack:
                complete = False
            if stack:
                stack.pop()
        elif delimiter == ';':
            if re.match(r'^(pin|pg_pin|bus|bundle|cell|library)\s*\(', statement, re.I):
                complete = False
                if len(limitations) < 100:
                    limitations.append({'line': line_no, 'reason': 'incomplete_object_group', 'statement': statement[:160]})
            match = _RE_ATTR.match(statement + ';')
            if not match or record is None:
                continue
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
                record['attr_lines'][key] = line_no
            elif parent == 'pin' and key in {'direction', 'capacitance', 'function', 'related_power_pin', 'related_ground_pin'}:
                record[key] = value
            elif parent == 'pg_pin' and key in {'pg_type', 'voltage_name'}:
                record[key] = value
            elif parent == 'operating_conditions':
                record[key] = value
    complete &= not stack
    result['stats'] = {'library_count': len(result['libraries']),
        'cell_count': sum(len(lib['cells']) for lib in result['libraries'].values()),
        'pin_count': sum(len(cell['pins']) for lib in result['libraries'].values() for cell in lib['cells'].values())}
    result['semantic_coverage'] = {'schema_version': 'semantic_parser_coverage.v1', 'validated': True,
        'basis': 'LibertyParser 2.4 balanced groups and nested malformed-object diagnostics; scalar pin/pg_pin declarations only',
        'port_set': 'PRESENT' if complete else 'NOT_EXTRACTED',
        'pg_port_set': 'PRESENT' if complete else 'NOT_EXTRACTED'}
    result['parse_limitations'] = limitations
    result['unparsed_features'] = limitations
    return result


def parse_liberty_data_file(path: str | Path) -> dict[str, Any]:
    return parse_liberty_text(read_text_file(path), source=str(path))


def parse_liberty_interface_data_file(path: str | Path, *, chunk_size: int = 1024 * 1024) -> dict[str, Any]:
    """Stream only Liberty cell/pin interface facts, discarding timing payloads."""
    source = Path(path)
    opener = gzip.open if source.name.lower().endswith('.gz') else open
    result: dict[str, Any] = {'source': str(source), 'libraries': {}, 'library_order': [], 'stats': {}}
    stack: list[tuple[str, dict | None]] = []
    limitations: list[dict[str, Any]] = []
    complete = True
    line_no = 1
    statement_start = 1
    statement: list[str] = []
    quote = False
    escape = False
    line_comment = False
    block_comment = False
    pending_slash = False
    pending_star = False
    escape_next = False
    max_limitations = 100

    def note(reason: str, text: str = '') -> None:
        if len(limitations) < max_limitations:
            limitations.append({'line': statement_start, 'reason': reason, 'statement': text[:160]})

    def accept_statement(delimiter: str) -> None:
        nonlocal complete, statement, statement_start
        raw_statement = ''.join(statement)
        leading = raw_statement[:len(raw_statement) - len(raw_statement.lstrip())]
        event_line = statement_start + leading.count('\n')
        text = raw_statement.strip()
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
            elif kind in {'pin', 'pg_pin'} and parent == 'cell' and record is not None:
                group = 'pins' if kind == 'pin' else 'pg_pins'
                if not name or ',' in name or name in record[group]:
                    complete = False
                value = {'name': name, 'line_start': event_line}
                value.update({'direction': None, 'capacitance': None, 'function': None} if kind == 'pin'
                             else {'pg_type': None, 'voltage_name': None})
                record[group][name] = value
                if kind == 'pin':
                    record['pin_order'].append(name)
            elif kind == 'operating_conditions' and parent == 'library' and record is not None:
                value = {'name': name}
                record['operating_conditions'][name] = value
            elif kind in {'bus', 'bundle'}:
                complete = False
                note('unsupported_bus_or_bundle_group', text)
            # Keep structural balance, but do not retain payload or records below irrelevant groups.
            stack.append((kind, value))
        elif delimiter == '}':
            if text:
                complete = False
            if not stack:
                complete = False
                note('unbalanced_group_close', text)
            else:
                stack.pop()
        elif delimiter == ';':
            if re.match(r'^(pin|pg_pin|bus|bundle|cell|library)\s*\(', text, re.I):
                complete = False
                note('incomplete_object_group', text)
            match = _RE_ATTR.match(text + ';')
            if not match or record is None:
                return
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
            elif parent == 'pg_pin' and key in {'pg_type', 'voltage_name'}:
                record[key] = value
            elif parent == 'operating_conditions':
                record[key] = value
        statement_start = line_no

    def should_capture() -> bool:
        return not stack or stack[-1][0] in {'library', 'cell', 'pin', 'pg_pin', 'operating_conditions'}

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
                            block_comment = False
                            pending_star = False
                            position = marker.end()
                            continue
                        pending_star = char == '*'
                        line_no += char.count('\n')
                        position = marker.end()
                        continue
                    if quote:
                        line_no += segment.count('\n') + char.count('\n')
                        if should_capture():
                            statement.append(segment)
                            statement.append(char)
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
                            line_no += char.count('\n')
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
                    elif char == '\\' and quote:
                        escape_next = not escape_next
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
                    if tail:
                        escape_next = False
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
                # Existing parser marks incomplete coverage; retain complete objects parsed before EOF.
    except (OSError, EOFError) as exc:
        raise ValueError(f'无法读取 Liberty 文件 {source}: {exc}') from exc

    result['stats'] = {
        'library_count': len(result['libraries']),
        'cell_count': sum(len(lib['cells']) for lib in result['libraries'].values()),
        'pin_count': sum(len(cell['pins']) for lib in result['libraries'].values()
                         for cell in lib['cells'].values()),
        'pg_pin_count': sum(len(cell['pg_pins']) for lib in result['libraries'].values()
                            for cell in lib['cells'].values()),
    }
    result['semantic_coverage'] = {
        'schema_version': 'semantic_parser_coverage.v1', 'validated': True,
        'basis': 'LibertyInterfaceParser streaming balanced groups; timing/table payloads discarded',
        'port_set': 'PRESENT' if complete else 'NOT_EXTRACTED',
        'pg_port_set': 'PRESENT' if complete else 'NOT_EXTRACTED',
    }
    result['parse_limitations'] = limitations
    result['unparsed_features'] = limitations
    return result


def parse_liberty_file(path: str | Path) -> dict[str, Any]:
    data = parse_liberty_data_file(path)
    return make_parser_envelope(parser_name='LibertyParser', parser_version=LIBERTY_PARSER_VERSION, file=str(path), abs_path=str(Path(path).resolve()), file_type='liberty', data=data)


def _lib_view(summary: dict[str, Any]) -> dict[str, Any]:
    out = {}
    for lname, lib in (summary.get('libraries') or {}).items():
        out[lname] = {'cells': {cname: {'area': cell.get('area'), 'pins': {p: {'direction': pin.get('direction')} for p, pin in (cell.get('pins') or {}).items()}} for cname, cell in (lib.get('cells') or {}).items()}, 'operating_conditions': sorted((lib.get('operating_conditions') or {}).keys())}
    return out


def diff_liberty_summary(old: dict[str, Any], new: dict[str, Any]) -> dict[str, Any]:
    ov, nv = _lib_view(old), _lib_view(new)
    added_libs = sorted(set(nv)-set(ov)); removed_libs = sorted(set(ov)-set(nv)); changed = {}
    for lib in sorted(set(ov)&set(nv)):
        och, nch = ov[lib]['cells'], nv[lib]['cells']
        cchg = {'added': sorted(set(nch)-set(och)), 'removed': sorted(set(och)-set(nch)), 'changed': {}}
        for c in sorted(set(och)&set(nch)):
            ch = {}
            if och[c].get('area') != nch[c].get('area'): ch['area'] = {'old': och[c].get('area'), 'new': nch[c].get('area')}
            op, np = och[c]['pins'], nch[c]['pins']
            if set(op) != set(np): ch['pins'] = {'added': sorted(set(np)-set(op)), 'removed': sorted(set(op)-set(np))}
            if ch: cchg['changed'][c] = ch
        if cchg['added'] or cchg['removed'] or cchg['changed'] or ov[lib]['operating_conditions'] != nv[lib]['operating_conditions']:
            changed[lib] = {'cells': cchg, 'operating_conditions': {'old': ov[lib]['operating_conditions'], 'new': nv[lib]['operating_conditions']} if ov[lib]['operating_conditions'] != nv[lib]['operating_conditions'] else None}
    return {'schema_version': '1.0', 'diff_type': 'liberty_summary_diff', 'library_changes': {'added': added_libs, 'removed': removed_libs, 'changed': changed}}


def diff_liberty_files(old_path: str | Path, new_path: str | Path) -> dict[str, Any]:
    return diff_liberty_summary(parse_liberty_file(old_path)["data"], parse_liberty_file(new_path)["data"])


class LibertyParser(BaseParser):
    parser_name = 'LibertyParser'; parser_version = LIBERTY_PARSER_VERSION; parse_level = 'L2'
    supported_file_types = ['liberty']; supported_extensions = ['.lib', '.lib.gz']
    def parse(self, record: Any, context: Any) -> dict[str, Any]:
        path = record_abs_path(record, context)
        data = parse_liberty_data_file(path)
        return make_parser_envelope(parser_name=self.parser_name, parser_version=self.parser_version, file=str(get_field(record, 'path', path)), abs_path=str(path), file_type=str(get_field(record, 'file_type', 'liberty')), compression=get_field(record, 'compression', None), data=data, schema_version=str(get_field(context, 'schema_version', '1.0')))
