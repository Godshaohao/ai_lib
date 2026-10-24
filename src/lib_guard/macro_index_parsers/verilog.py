from __future__ import annotations
from pathlib import Path
from typing import Any
import re
from .base import BaseParser, make_parser_envelope, record_abs_path, get_field, read_text_file

VERILOG_PARSER_VERSION = '2.3'
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
    headers = list(_RE_MODULE.finditer(clean))
    ends = list(re.finditer(r'\bendmodule\b', clean))
    complete = len(headers) == len(ends) == len(re.findall(r'\bmodule\b', clean))
    directives = list(re.finditer(r'`(ifdef|ifndef|elsif|else|endif|include|define)\b[^\n]*', clean))
    directive_index = conditional_depth = 0
    port_pattern = re.compile(r'(?:(input|output|inout)\s+)?(?:(?:wire|reg|logic|bit|signed|unsigned)\s+)*(\[[^\]]+\])?\s*([A-Za-z_][\w$]*)', re.I)
    end_index = 0
    for index, mm in enumerate(headers):
        name, header = mm.group(1), mm.group(2)
        while directive_index < len(directives) and directives[directive_index].start() < mm.start():
            directive = directives[directive_index]
            kind = directive.group(1)
            conditional_depth += 1 if kind in {'ifdef', 'ifndef'} else -1 if kind == 'endif' else 0
            complete &= conditional_depth >= 0 and kind != 'include' and directive.end() <= mm.start()
            directive_index += 1
        complete &= conditional_depth == 0
        complete &= name not in modules and '#' not in mm.group(0)
        module = {'name': name, 'ports': {}, 'port_order': [], 'parameters': []}
        modules[name] = module
        inherited_direction = inherited_range = None
        for raw_port in [p.strip() for p in header.replace('\n', ' ').split(',') if p.strip()]:
            port = port_pattern.fullmatch(raw_port)
            if not port:
                complete = False
                continue
            direction, rng, pname = port.groups()
            if direction:
                inherited_direction, inherited_range = direction.lower(), rng
            elif rng:
                complete = False
            complete &= pname not in module['ports']
            module['ports'][pname] = {'name': pname, 'direction': inherited_direction,
                'width': _width(inherited_range) if inherited_direction else None, 'declared_range': inherited_range}
            module['port_order'].append(pname)
        while end_index < len(ends) and ends[end_index].start() < mm.end():
            end_index += 1
        end = ends[end_index] if end_index < len(ends) else None
        next_header = headers[index + 1].start() if index + 1 < len(headers) else len(clean)
        if end is None or end.start() > next_header:
            complete = False
            continue
        declaration_scope = clean[mm.start():end.end()]
        complete &= not bool(re.search(r'`|\b(function|task|interface|modport)\b|"', declaration_scope))
        # Body declarations belong only to this module, never another module sharing a port name.
        declared = {name for name, port in module['ports'].items() if port['direction'] is not None}
        for decl in _RE_DECL.finditer(clean[mm.end():end.start()]):
            direction, rng, names = decl.group(1).lower(), decl.group(2), decl.group(3)
            for token in names.split(','):
                pname = token.strip()
                if pname not in module['ports'] or pname in declared:
                    complete = False
                    continue
                declared.add(pname)
                module['ports'][pname].update(direction=direction, width=_width(rng), declared_range=rng)
        complete &= all(port['direction'] is not None and isinstance(port['width'], int) for port in module['ports'].values())
    return {
        'source': source,
        'parse_strategy': VERILOG_PARSE_STRATEGY,
        'parsed_fields': list(VERILOG_PARSED_FIELDS),
        'unparsed_features': list(VERILOG_UNPARSED_FEATURES),
        'recommendation': 'Use File Diff or a dedicated netlist parser for large gate netlists and connectivity review.',
        'modules': modules,
        'module_order': list(modules.keys()),
        'stats': {'module_count': len(modules), 'port_count': sum(len(m['ports']) for m in modules.values())},
        'semantic_coverage': {'schema_version': 'semantic_parser_coverage.v1', 'validated': True,
            'basis': 'VerilogParser 2.3 conflict-checked module-scoped scalar/literal-range interfaces; guarded UDP is not interface evidence; no elaboration',
            'port_set': 'PRESENT' if complete else 'NOT_EXTRACTED', 'pg_port_set': 'NOT_APPLICABLE'},
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
