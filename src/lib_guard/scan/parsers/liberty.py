from __future__ import annotations

from pathlib import Path
from typing import Any
import re

from .base import BaseParser, make_parser_envelope, record_abs_path, get_field, read_text_file

LIBERTY_PARSER_VERSION = '2.0'
_RE_LIBRARY = re.compile(r'\blibrary\s*\(\s*([^\)]+)\s*\)\s*\{', re.I)
_RE_CELL = re.compile(r'\bcell\s*\(\s*([^\)]+)\s*\)\s*\{', re.I)
_RE_PIN = re.compile(r'\bpin\s*\(\s*([^\)]+)\s*\)\s*\{', re.I)
_RE_PG_PIN = re.compile(r'\bpg_pin\s*\(\s*([^\)]+)\s*\)\s*\{', re.I)
_RE_ATTR = re.compile(r'^\s*([A-Za-z_][\w]*)\s*:\s*([^;]+)\s*;')
_RE_OC = re.compile(r'\boperating_conditions\s*\(\s*([^\)]+)\s*\)\s*\{', re.I)


def _clean_name(x: str) -> str:
    return x.strip().strip('"').strip("'")


def parse_liberty_text(text: str, source: str = '') -> dict[str, Any]:
    result: dict[str, Any] = {'source': source, 'libraries': {}, 'library_order': [], 'stats': {}}
    stack: list[tuple[str, str]] = []
    current_lib = None; current_cell = None; current_pin = None; current_pg_pin = None; current_oc = None
    for line_no, raw in enumerate(text.splitlines(), start=1):
        line = raw.split('//', 1)[0].strip()
        if not line:
            continue
        m = _RE_LIBRARY.search(line)
        if m:
            name = _clean_name(m.group(1)); current_lib = name
            result['libraries'].setdefault(name, {'name': name, 'line_start': line_no, 'cells': {}, 'cell_order': [], 'operating_conditions': {}})
            result['library_order'].append(name); stack.append(('library', name)); continue
        m = _RE_CELL.search(line)
        if m and current_lib:
            name = _clean_name(m.group(1)); current_cell = name
            lib = result['libraries'][current_lib]
            lib['cells'].setdefault(name, {'name': name, 'line_start': line_no, 'area': None, 'pins': {}, 'pin_order': [], 'pg_pins': {}})
            lib['cell_order'].append(name); stack.append(('cell', name)); continue
        m = _RE_PIN.search(line)
        if m and current_lib and current_cell:
            name = _clean_name(m.group(1)); current_pin = name
            cell = result['libraries'][current_lib]['cells'][current_cell]
            cell['pins'].setdefault(name, {'name': name, 'line_start': line_no, 'direction': None, 'capacitance': None, 'function': None})
            cell['pin_order'].append(name); stack.append(('pin', name)); continue
        m = _RE_PG_PIN.search(line)
        if m and current_lib and current_cell:
            name = _clean_name(m.group(1)); current_pg_pin = name
            cell = result['libraries'][current_lib]['cells'][current_cell]
            cell['pg_pins'].setdefault(name, {'name': name, 'line_start': line_no, 'pg_type': None, 'voltage_name': None})
            stack.append(('pg_pin', name)); continue
        m = _RE_OC.search(line)
        if m and current_lib:
            name = _clean_name(m.group(1)); current_oc = name
            result['libraries'][current_lib]['operating_conditions'].setdefault(name, {'name': name})
            stack.append(('operating_conditions', name)); continue

        m = _RE_ATTR.match(line)
        if m:
            key, value = m.group(1), _clean_name(m.group(2))
            if current_lib and current_cell and current_pin:
                if key in {'direction', 'capacitance', 'function', 'related_power_pin', 'related_ground_pin'}:
                    result['libraries'][current_lib]['cells'][current_cell]['pins'][current_pin][key] = value
            elif current_lib and current_cell and current_pg_pin:
                if key in {'pg_type', 'voltage_name'}:
                    result['libraries'][current_lib]['cells'][current_cell]['pg_pins'][current_pg_pin][key] = value
            elif current_lib and current_cell:
                if key == 'area':
                    try: value = float(value)
                    except ValueError: pass
                    result['libraries'][current_lib]['cells'][current_cell]['area'] = value
            elif current_lib and current_oc:
                result['libraries'][current_lib]['operating_conditions'][current_oc][key] = value

        if '}' in line and stack:
            kind, _ = stack.pop()
            if kind == 'pin': current_pin = None
            elif kind == 'pg_pin': current_pg_pin = None
            elif kind == 'cell': current_cell = None
            elif kind == 'operating_conditions': current_oc = None
            elif kind == 'library': current_lib = None

    lib_count = len(result['libraries'])
    cell_count = sum(len(lib['cells']) for lib in result['libraries'].values())
    pin_count = sum(len(cell['pins']) for lib in result['libraries'].values() for cell in lib['cells'].values())
    result['stats'] = {'library_count': lib_count, 'cell_count': cell_count, 'pin_count': pin_count}
    return result


def parse_liberty_data_file(path: str | Path) -> dict[str, Any]:
    return parse_liberty_text(read_text_file(path), source=str(path))


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

