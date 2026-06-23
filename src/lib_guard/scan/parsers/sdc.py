from __future__ import annotations
from pathlib import Path
from typing import Any
import re, shlex
from .base import BaseParser, make_parser_envelope, record_abs_path, get_field, read_text_file
SDC_PARSER_VERSION='2.0'
_COMMANDS=['create_clock','create_generated_clock','set_clock_groups','set_input_delay','set_output_delay','set_false_path','set_multicycle_path','set_clock_uncertainty','set_load','set_driving_cell']

def parse_sdc_text(text: str, source: str='')->dict[str,Any]:
    commands=[]; counts={c:0 for c in _COMMANDS}
    logical=''
    for raw in text.splitlines():
        line=raw.split('#',1)[0].rstrip()
        if not line: continue
        if line.endswith('\\'):
            logical += line[:-1]+' '; continue
        line = logical + line; logical=''
        cmd=line.strip().split(None,1)[0] if line.strip() else ''
        if cmd in counts:
            counts[cmd]+=1
            try: tokens=shlex.split(line)
            except Exception: tokens=line.split()
            commands.append({'command':cmd,'tokens':tokens,'raw':line.strip()})
    return {'source':source,'commands':commands,'counts':counts,'stats':{'command_count':len(commands)}}
def parse_sdc_data_file(path: str|Path)->dict[str,Any]: return parse_sdc_text(read_text_file(path),source=str(path))
def parse_sdc_file(path: str|Path)->dict[str,Any]:
    data=parse_sdc_data_file(path)
    return make_parser_envelope(parser_name='SdcParser',parser_version=SDC_PARSER_VERSION,file=str(path),abs_path=str(Path(path).resolve()),file_type='sdc',data=data)
class SdcParser(BaseParser):
    parser_name='SdcParser'; parser_version=SDC_PARSER_VERSION; parse_level='L2'; supported_file_types=['sdc']; supported_extensions=['.sdc']
    def parse(self,record,context):
        path=record_abs_path(record,context); return make_parser_envelope(parser_name=self.parser_name,parser_version=self.parser_version,file=str(get_field(record,'path',path)),abs_path=str(path),file_type=str(get_field(record,'file_type','sdc')),compression=get_field(record,'compression',None),data=parse_sdc_data_file(path),schema_version=str(get_field(context,'schema_version','1.0')))

