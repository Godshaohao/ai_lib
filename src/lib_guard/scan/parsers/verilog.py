from __future__ import annotations
from pathlib import Path
from typing import Any
import re
from .base import BaseParser, make_parser_envelope, record_abs_path, get_field, read_text_file

VERILOG_PARSER_VERSION = '2.0'
VERILOG_PARSE_STRATEGY = "lightweight_rtl_interface"
VERILOG_PARSED_FIELDS = ["module", "port", "direction", "width", "declared_range", "module_count", "port_count"]
VERILOG_UNPARSED_FEATURES = [
    "instance",
    "parameter_value",
    "generate_block",
    "always_block",
    "assign_expression",
    "gate_netlist_connectivity",
]
_RE_MODULE = re.compile(r'\bmodule\s+([A-Za-z_][\w$]*)\s*(?:#\s*\(.*?\)\s*)?\((.*?)\)\s*;', re.S)
_RE_DECL = re.compile(r'\b(input|output|inout)\b\s*(?:wire|reg|logic)?\s*(\[[^\]]+\])?\s*([^;]+);', re.I | re.S)
_RE_RANGE = re.compile(r'\[\s*([^:\]]+)\s*:\s*([^\]]+)\s*\]')

def _strip_comments(text: str) -> str:
    text = re.sub(r'/\*.*?\*/', '', text, flags=re.S)
    return re.sub(r'//.*', '', text)

def _width(range_text: str | None) -> int | str | None:
    if not range_text: return 1
    m = _RE_RANGE.search(range_text)
    if not m: return range_text
    try: return abs(int(m.group(1)) - int(m.group(2))) + 1
    except Exception: return range_text

def parse_verilog_text(text: str, source: str = '') -> dict[str, Any]:
    clean = _strip_comments(text)
    modules: dict[str, Any] = {}
    for mm in _RE_MODULE.finditer(clean):
        name, header = mm.group(1), mm.group(2)
        modules.setdefault(name, {'name': name, 'ports': {}, 'port_order': [], 'parameters': []})
        for raw_port in [p.strip() for p in header.replace('\n', ' ').split(',') if p.strip()]:
            toks = raw_port.split()
            pname = toks[-1].strip('.()')
            if pname and pname not in modules[name]['ports']:
                modules[name]['ports'][pname] = {'name': pname, 'direction': None, 'width': None, 'declared_range': None}
                modules[name]['port_order'].append(pname)
    for decl in _RE_DECL.finditer(clean):
        direction, rng, names = decl.group(1).lower(), decl.group(2), decl.group(3)
        width = _width(rng)
        for token in names.split(','):
            pname = token.strip().split('=')[0].strip()
            if not pname: continue
            # assign declaration to all modules that have the port, or only module if one module exists
            targets = [m for m in modules.values() if pname in m['ports']] or (list(modules.values()) if len(modules) == 1 else [])
            for mod in targets:
                mod['ports'].setdefault(pname, {'name': pname})
                if pname not in mod['port_order']: mod['port_order'].append(pname)
                mod['ports'][pname].update({'direction': direction, 'width': width, 'declared_range': rng})
    return {
        'source': source,
        'parse_strategy': VERILOG_PARSE_STRATEGY,
        'parsed_fields': list(VERILOG_PARSED_FIELDS),
        'unparsed_features': list(VERILOG_UNPARSED_FEATURES),
        'recommendation': 'Use File Diff or a dedicated netlist parser for large gate netlists and connectivity review.',
        'modules': modules,
        'module_order': list(modules.keys()),
        'stats': {'module_count': len(modules), 'port_count': sum(len(m['ports']) for m in modules.values())},
    }

def parse_verilog_data_file(path: str | Path) -> dict[str, Any]:
    return parse_verilog_text(read_text_file(path), source=str(path))

def parse_verilog_file(path: str | Path) -> dict[str, Any]:
    data = parse_verilog_data_file(path)
    return make_parser_envelope(
        parser_name='VerilogParser',
        parser_version=VERILOG_PARSER_VERSION,
        file=str(path),
        abs_path=str(Path(path).resolve()),
        file_type='verilog',
        data=data,
    )

def _view(s): return {m: {'ports': {p: {'direction': d.get('direction'), 'width': d.get('width')} for p,d in mod.get('ports',{}).items()}} for m, mod in s.get('modules', {}).items()}

def diff_verilog_summary(old: dict[str, Any], new: dict[str, Any]) -> dict[str, Any]:
    ov,nv=_view(old),_view(new); changed={}
    for m in sorted(set(ov)&set(nv)):
        op,np=ov[m]['ports'],nv[m]['ports']; pchg={}
        for p in sorted(set(op)&set(np)):
            diff={k:{'old':op[p].get(k),'new':np[p].get(k)} for k in ['direction','width'] if op[p].get(k)!=np[p].get(k)}
            if diff: pchg[p]=diff
        if set(op)!=set(np) or pchg: changed[m]={'ports':{'added':sorted(set(np)-set(op)),'removed':sorted(set(op)-set(np)),'changed':pchg}}
    return {'schema_version':'1.0','diff_type':'verilog_summary_diff','module_changes':{'added':sorted(set(nv)-set(ov)),'removed':sorted(set(ov)-set(nv)),'changed':changed}}

def diff_verilog_files(old_path: str | Path, new_path: str | Path) -> dict[str, Any]:
    return diff_verilog_summary(parse_verilog_file(old_path)["data"], parse_verilog_file(new_path)["data"])

class VerilogParser(BaseParser):
    parser_name='VerilogParser'; parser_version=VERILOG_PARSER_VERSION; parse_level='L2'
    supported_file_types=['verilog','systemverilog']; supported_extensions=['.v','.sv','.vp','.vg','.vh','.svh']
    def parse(self, record: Any, context: Any) -> dict[str, Any]:
        path=record_abs_path(record,context); data=parse_verilog_data_file(path)
        return make_parser_envelope(parser_name=self.parser_name, parser_version=self.parser_version, file=str(get_field(record,'path',path)), abs_path=str(path), file_type=str(get_field(record,'file_type','verilog')), compression=get_field(record,'compression',None), data=data, schema_version=str(get_field(context,'schema_version','1.0')))

