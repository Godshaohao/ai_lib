from __future__ import annotations

from pathlib import Path
from typing import Any
import re

from .base import BaseParser, make_parser_envelope, record_abs_path, get_field, read_text_file

LEF_PARSER_VERSION = '2.0'

_RE_VERSION = re.compile(r'^\s*VERSION\s+(?P<version>\S+)\s*;', re.I)
_RE_BUSBITCHARS = re.compile(r'^\s*BUSBITCHARS\s+"(?P<chars>[^"]+)"\s*;', re.I)
_RE_DIVIDERCHAR = re.compile(r'^\s*DIVIDERCHAR\s+"(?P<char>[^"]+)"\s*;', re.I)
_RE_UNITS = re.compile(r'^\s*DATABASE\s+MICRONS\s+(?P<dbu>\d+)\s*;', re.I)
_RE_MACRO_START = re.compile(r'^\s*MACRO\s+(?P<name>\S+)', re.I)
_RE_END = re.compile(r'^\s*END(?:\s+(?P<name>\S+))?', re.I)
_RE_CLASS = re.compile(r'^\s*CLASS\s+(?P<class>.+?)\s*;', re.I)
_RE_SIZE = re.compile(r'^\s*SIZE\s+(?P<x>[-\d\.]+)\s+BY\s+(?P<y>[-\d\.]+)\s*;', re.I)
_RE_ORIGIN = re.compile(r'^\s*ORIGIN\s+(?P<x>[-\d\.]+)\s+(?P<y>[-\d\.]+)\s*;', re.I)
_RE_SYMMETRY = re.compile(r'^\s*SYMMETRY\s+(?P<sym>.+?)\s*;', re.I)
_RE_SITE = re.compile(r'^\s*SITE\s+(?P<site>\S+)\s*;', re.I)
_RE_PIN_START = re.compile(r'^\s*PIN\s+(?P<name>\S+)', re.I)
_RE_DIRECTION = re.compile(r'^\s*DIRECTION\s+(?P<direction>\S+)\s*;', re.I)
_RE_USE = re.compile(r'^\s*USE\s+(?P<use>\S+)\s*;', re.I)
_RE_SHAPE = re.compile(r'^\s*SHAPE\s+(?P<shape>\S+)\s*;', re.I)
_RE_LAYER = re.compile(r'^\s*LAYER\s+(?P<layer>\S+)\s*;', re.I)
_RE_RECT = re.compile(r'^\s*RECT\s+(?P<x1>[-\d\.]+)\s+(?P<y1>[-\d\.]+)\s+(?P<x2>[-\d\.]+)\s+(?P<y2>[-\d\.]+)\s*;', re.I)
_RE_OBS = re.compile(r'^\s*OBS\b', re.I)


def parse_lef_text(text: str, source: str = '') -> dict[str, Any]:
    result: dict[str, Any] = {
        'source': source,
        'lef_version': None,
        'busbitchars': None,
        'dividerchar': None,
        'database_microns': None,
        'macros': {},
        'macro_order': [],
        'stats': {'macro_count': 0, 'pin_count': 0, 'obs_rect_count': 0},
    }
    current_macro: dict[str, Any] | None = None
    current_pin: dict[str, Any] | None = None
    current_layer: str | None = None
    in_obs = False

    for line_no, raw in enumerate(text.splitlines(), start=1):
        line = raw.split('#', 1)[0].strip()
        if not line:
            continue
        if current_macro is None:
            for regex, key, conv in [
                (_RE_VERSION, 'lef_version', str),
                (_RE_BUSBITCHARS, 'busbitchars', str),
                (_RE_DIVIDERCHAR, 'dividerchar', str),
            ]:
                m = regex.match(line)
                if m:
                    result[key] = conv(next(iter(m.groupdict().values())))
                    break
            else:
                m = _RE_UNITS.match(line)
                if m:
                    result['database_microns'] = int(m.group('dbu'))
                    continue
                m = _RE_MACRO_START.match(line)
                if m:
                    name = m.group('name')
                    current_macro = {
                        'name': name, 'line_start': line_no, 'line_end': None,
                        'class': None, 'origin': None, 'size': None, 'symmetry': [], 'site': None,
                        'pins': {}, 'pin_order': [], 'obs': [],
                    }
                    result['macros'][name] = current_macro
                    result['macro_order'].append(name)
                    continue
            continue

        if current_pin is not None:
            m_end = _RE_END.match(line)
            if m_end and (m_end.group('name') == current_pin['name'] or line.upper() == 'END'):
                current_pin = None
                current_layer = None
                continue
            for regex, key in [(_RE_DIRECTION, 'direction'), (_RE_USE, 'use'), (_RE_SHAPE, 'shape')]:
                m = regex.match(line)
                if m:
                    current_pin[key] = next(iter(m.groupdict().values())).upper()
                    break
            else:
                m = _RE_LAYER.match(line)
                if m:
                    current_layer = m.group('layer')
                    if current_layer not in current_pin['layers']:
                        current_pin['layers'].append(current_layer)
                    continue
                m = _RE_RECT.match(line)
                if m:
                    current_pin['rects'].append({'layer': current_layer, **{k: float(v) for k, v in m.groupdict().items()}})
                    continue
            continue

        if in_obs:
            m_end = _RE_END.match(line)
            if m_end and (m_end.group('name') is None or str(m_end.group('name')).upper() == 'OBS'):
                in_obs = False
                current_layer = None
                continue
            m = _RE_LAYER.match(line)
            if m:
                current_layer = m.group('layer')
                continue
            m = _RE_RECT.match(line)
            if m:
                current_macro['obs'].append({'layer': current_layer, **{k: float(v) for k, v in m.groupdict().items()}})
                continue

        m_end = _RE_END.match(line)
        if m_end and m_end.group('name') == current_macro['name']:
            current_macro['line_end'] = line_no
            current_macro = None
            continue
        m = _RE_CLASS.match(line)
        if m:
            current_macro['class'] = m.group('class')
            continue
        m = _RE_SIZE.match(line)
        if m:
            current_macro['size'] = {'x': float(m.group('x')), 'y': float(m.group('y'))}
            continue
        m = _RE_ORIGIN.match(line)
        if m:
            current_macro['origin'] = {'x': float(m.group('x')), 'y': float(m.group('y'))}
            continue
        m = _RE_SYMMETRY.match(line)
        if m:
            current_macro['symmetry'] = m.group('sym').split()
            continue
        m = _RE_SITE.match(line)
        if m:
            current_macro['site'] = m.group('site')
            continue
        m = _RE_PIN_START.match(line)
        if m:
            pname = m.group('name')
            current_pin = {'name': pname, 'line_start': line_no, 'direction': None, 'use': None, 'shape': None, 'layers': [], 'rects': []}
            current_macro['pins'][pname] = current_pin
            current_macro['pin_order'].append(pname)
            continue
        if _RE_OBS.match(line):
            in_obs = True
            current_layer = None
            continue

    result['stats']['macro_count'] = len(result['macros'])
    result['stats']['pin_count'] = sum(len(m['pins']) for m in result['macros'].values())
    result['stats']['obs_rect_count'] = sum(len(m['obs']) for m in result['macros'].values())
    return result


def parse_lef_data_file(path: str | Path) -> dict[str, Any]:
    return parse_lef_text(read_text_file(path), source=str(path))


def parse_lef_file(path: str | Path) -> dict[str, Any]:
    data = parse_lef_data_file(path)
    return make_parser_envelope(
        parser_name="LefParser",
        parser_version=LEF_PARSER_VERSION,
        file=str(path),
        abs_path=str(Path(path).resolve()),
        file_type="lef",
        data=data,
    )


def _lef_public_view(summary: dict[str, Any]) -> dict[str, Any]:
    return {
        macro_name: {
            'size': macro.get('size'),
            'class': macro.get('class'),
            'site': macro.get('site'),
            'pins': {p: {'direction': v.get('direction'), 'use': v.get('use'), 'layers': sorted(v.get('layers') or [])}
                     for p, v in (macro.get('pins') or {}).items()},
        }
        for macro_name, macro in (summary.get('macros') or {}).items()
    }


def diff_lef_summary(old: dict[str, Any], new: dict[str, Any]) -> dict[str, Any]:
    oldv, newv = _lef_public_view(old), _lef_public_view(new)
    added = sorted(set(newv) - set(oldv)); removed = sorted(set(oldv) - set(newv)); changed = {}
    for name in sorted(set(oldv) & set(newv)):
        ch = {}
        for k in ['size', 'class', 'site']:
            if oldv[name].get(k) != newv[name].get(k):
                ch[k] = {'old': oldv[name].get(k), 'new': newv[name].get(k)}
        op, np = oldv[name]['pins'], newv[name]['pins']
        pin_ch = {}
        for p in sorted(set(op) & set(np)):
            diff = {k: {'old': op[p].get(k), 'new': np[p].get(k)} for k in ['direction', 'use', 'layers'] if op[p].get(k) != np[p].get(k)}
            if diff: pin_ch[p] = diff
        if set(np) - set(op) or set(op) - set(np) or pin_ch:
            ch['pins'] = {'added': sorted(set(np)-set(op)), 'removed': sorted(set(op)-set(np)), 'changed': pin_ch}
        if ch: changed[name] = ch
    return {'schema_version': '1.0', 'diff_type': 'lef_summary_diff', 'macro_changes': {'added': added, 'removed': removed, 'changed': changed}, 'stats': {'added_macro_count': len(added), 'removed_macro_count': len(removed), 'changed_macro_count': len(changed)}}


def diff_lef_files(old_path: str | Path, new_path: str | Path) -> dict[str, Any]:
    return diff_lef_summary(parse_lef_file(old_path)["data"], parse_lef_file(new_path)["data"])


class LefParser(BaseParser):
    parser_name = 'LefParser'; parser_version = LEF_PARSER_VERSION; parse_level = 'L2'
    supported_file_types = ['lef']; supported_extensions = ['.lef', '.lef.gz', '.tlef', '.tlef.gz']
    def parse(self, record: Any, context: Any) -> dict[str, Any]:
        path = record_abs_path(record, context)
        data = parse_lef_data_file(path)
        return make_parser_envelope(parser_name=self.parser_name, parser_version=self.parser_version, file=str(get_field(record, 'path', path)), abs_path=str(path), file_type=str(get_field(record, 'file_type', 'lef')), compression=get_field(record, 'compression', None), data=data, schema_version=str(get_field(context, 'schema_version', '1.0')))

