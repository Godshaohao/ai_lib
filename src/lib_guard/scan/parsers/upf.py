from __future__ import annotations
from pathlib import Path
from typing import Any
import shlex
from .base import BaseParser, make_parser_envelope, record_abs_path, get_field, read_text_file
UPF_PARSER_VERSION='2.0'
_UPF_COMMANDS=['create_power_domain','create_supply_net','create_supply_port','connect_supply_net','set_domain_supply_net','set_isolation','set_level_shifter','set_retention','add_power_state']

def parse_upf_text(text: str, source: str='')->dict[str,Any]:
    commands=[]; counts={c:0 for c in _UPF_COMMANDS}; logical=''
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
def parse_upf_data_file(path: str|Path)->dict[str,Any]: return parse_upf_text(read_text_file(path),source=str(path))
def parse_upf_file(path: str|Path)->dict[str,Any]:
    data=parse_upf_data_file(path)
    return make_parser_envelope(parser_name='UpfParser',parser_version=UPF_PARSER_VERSION,file=str(path),abs_path=str(Path(path).resolve()),file_type='upf',data=data)
class UpfParser(BaseParser):
    parser_name='UpfParser'; parser_version=UPF_PARSER_VERSION; parse_level='L2'; supported_file_types=['upf']; supported_extensions=['.upf']
    def parse(self,record,context):
        path=record_abs_path(record,context); return make_parser_envelope(parser_name=self.parser_name,parser_version=self.parser_version,file=str(get_field(record,'path',path)),abs_path=str(path),file_type=str(get_field(record,'file_type','upf')),compression=get_field(record,'compression',None),data=parse_upf_data_file(path),schema_version=str(get_field(context,'schema_version','1.0')))

