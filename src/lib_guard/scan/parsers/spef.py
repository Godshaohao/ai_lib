from __future__ import annotations
from pathlib import Path
from typing import Any
import re
from .base import BaseParser, make_parser_envelope, record_abs_path, get_field, read_text_file
SPEF_PARSER_VERSION='2.0'
_HDR=re.compile(r'^\*(SPEF|DESIGN|DATE|VENDOR|PROGRAM|VERSION|DESIGN_FLOW|DIVIDER|DELIMITER|BUS_DELIMITER|T_UNIT|C_UNIT|R_UNIT|L_UNIT)\s*(.*)$',re.I)
def parse_spef_text(text: str, source: str='')->dict[str,Any]:
    header={}; name_map_count=0; dnet_count=0
    for raw in text.splitlines():
        line=raw.strip()
        if not line: continue
        m=_HDR.match(line)
        if m: header[m.group(1).upper()]=m.group(2).strip().strip('"')
        if line.startswith('*NAME_MAP'): name_map_count += 1
        if line.startswith('*D_NET'): dnet_count += 1
    return {'source':source,'header':header,'stats':{'dnet_count':dnet_count,'name_map_section_count':name_map_count},'status':'light_parse'}
def parse_spef_data_file(path: str|Path)->dict[str,Any]: return parse_spef_text(read_text_file(path),source=str(path))
def parse_spef_file(path: str|Path)->dict[str,Any]:
    data=parse_spef_data_file(path)
    return make_parser_envelope(parser_name='SpefParser',parser_version=SPEF_PARSER_VERSION,file=str(path),abs_path=str(Path(path).resolve()),file_type='spef',data=data)
class SpefParser(BaseParser):
    parser_name='SpefParser'; parser_version=SPEF_PARSER_VERSION; parse_level='L2'; supported_file_types=['spef']; supported_extensions=['.spef','.spef.gz']
    def parse(self,record,context):
        path=record_abs_path(record,context); return make_parser_envelope(parser_name=self.parser_name,parser_version=self.parser_version,file=str(get_field(record,'path',path)),abs_path=str(path),file_type=str(get_field(record,'file_type','spef')),compression=get_field(record,'compression',None),data=parse_spef_data_file(path),schema_version=str(get_field(context,'schema_version','1.0')))

