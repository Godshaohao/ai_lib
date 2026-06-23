from __future__ import annotations
from pathlib import Path
from typing import Any
from .base import BaseParser, make_parser_envelope, record_abs_path, get_field, read_text_file
WAIVER_PARSER_VERSION='2.0'
def parse_waiver_text(text: str, source: str='')->dict[str,Any]:
    entries=[]
    for ln, raw in enumerate(text.splitlines(),1):
        line=raw.strip()
        if not line or line.startswith('#') or line.startswith('//'): continue
        entries.append({'line':ln,'raw':line})
    return {'source':source,'entries':entries,'stats':{'entry_count':len(entries)}}
def parse_waiver_data_file(path: str|Path)->dict[str,Any]: return parse_waiver_text(read_text_file(path),source=str(path))
def parse_waiver_file(path: str|Path)->dict[str,Any]:
    data=parse_waiver_data_file(path)
    return make_parser_envelope(parser_name='WaiverParser',parser_version=WAIVER_PARSER_VERSION,file=str(path),abs_path=str(Path(path).resolve()),file_type='waiver',data=data)
class WaiverParser(BaseParser):
    parser_name='WaiverParser'; parser_version=WAIVER_PARSER_VERSION; parse_level='L2'; supported_file_types=['waiver']; supported_extensions=['.waiver','.wvr']
    def parse(self,record,context):
        path=record_abs_path(record,context); return make_parser_envelope(parser_name=self.parser_name,parser_version=self.parser_version,file=str(get_field(record,'path',path)),abs_path=str(path),file_type=str(get_field(record,'file_type','waiver')),compression=get_field(record,'compression',None),data=parse_waiver_data_file(path),schema_version=str(get_field(context,'schema_version','1.0')))

