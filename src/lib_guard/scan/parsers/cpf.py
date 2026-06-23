from __future__ import annotations
from pathlib import Path
from typing import Any
import shlex
from .base import BaseParser, make_parser_envelope, record_abs_path, get_field, read_text_file
CPF_PARSER_VERSION='2.0'
_CPF_COMMANDS=['create_power_domain','create_nominal_condition','create_power_mode','create_isolation_rule','create_level_shifter_rule','create_state_retention_rule','update_power_domain']

def parse_cpf_text(text: str, source: str='')->dict[str,Any]:
    commands=[]; counts={c:0 for c in _CPF_COMMANDS}; logical=''
    for raw in text.splitlines():
        line=raw.split('#',1)[0].rstrip()
        if not line: continue
        if line.endswith('\\'): logical += line[:-1]+' '; continue
        line=logical+line; logical=''; cmd=line.strip().split(None,1)[0] if line.strip() else ''
        if cmd in counts:
            counts[cmd]+=1
            try: toks=shlex.split(line)
            except Exception: toks=line.split()
            commands.append({'command':cmd,'tokens':toks,'raw':line.strip()})
    return {'source':source,'commands':commands,'counts':counts,'stats':{'command_count':len(commands)}}
def parse_cpf_data_file(path: str|Path)->dict[str,Any]: return parse_cpf_text(read_text_file(path),source=str(path))
def parse_cpf_file(path: str|Path)->dict[str,Any]:
    data=parse_cpf_data_file(path)
    return make_parser_envelope(parser_name='CpfParser',parser_version=CPF_PARSER_VERSION,file=str(path),abs_path=str(Path(path).resolve()),file_type='cpf',data=data)
class CpfParser(BaseParser):
    parser_name='CpfParser'; parser_version=CPF_PARSER_VERSION; parse_level='L2'; supported_file_types=['cpf']; supported_extensions=['.cpf']
    def parse(self,record,context):
        path=record_abs_path(record,context); return make_parser_envelope(parser_name=self.parser_name,parser_version=self.parser_version,file=str(get_field(record,'path',path)),abs_path=str(path),file_type=str(get_field(record,'file_type','cpf')),compression=get_field(record,'compression',None),data=parse_cpf_data_file(path),schema_version=str(get_field(context,'schema_version','1.0')))

