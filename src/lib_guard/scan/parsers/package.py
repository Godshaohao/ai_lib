from __future__ import annotations
from pathlib import Path
from typing import Any
from .base import BaseParser, make_parser_envelope, record_abs_path, get_field, read_text_file
PACKAGE_PARSER_VERSION='2.0'
def parse_touchstone_text(text: str, source: str='')->dict[str,Any]:
    option_line=None; data_lines=0; comments=[]
    for raw in text.splitlines():
        line=raw.strip()
        if not line: continue
        if line.startswith('!'):
            if len(comments)<20: comments.append(line[1:].strip())
            continue
        if line.startswith('#'): option_line=line
        else: data_lines += 1
    return {'source':source,'kind':'touchstone','option_line':option_line,'data_line_count':data_lines,'comments':comments}
def parse_touchstone_data_file(path: str|Path)->dict[str,Any]: return parse_touchstone_text(read_text_file(path),source=str(path))
def parse_touchstone_file(path: str|Path)->dict[str,Any]:
    data=parse_touchstone_data_file(path)
    return make_parser_envelope(parser_name='PackageParser',parser_version=PACKAGE_PARSER_VERSION,file=str(path),abs_path=str(Path(path).resolve()),file_type='touchstone',data=data)
def parse_package_text(text: str, source: str='')->dict[str,Any]:
    return {'source':source,'kind':'generic_package_text','line_count':len(text.splitlines()),'status':'light_parse'}
def parse_package_data_file(path: str|Path)->dict[str,Any]:
    p=Path(path); ext=p.suffix.lower()
    if ext in {'.s1p','.s2p','.s4p','.s6p','.s8p','.snp'} or ext.endswith('p'):
        return parse_touchstone_data_file(p)
    return parse_package_text(read_text_file(p),source=str(p))
def parse_package_file(path: str|Path)->dict[str,Any]:
    data=parse_package_data_file(path)
    return make_parser_envelope(parser_name='PackageParser',parser_version=PACKAGE_PARSER_VERSION,file=str(path),abs_path=str(Path(path).resolve()),file_type='package',data=data)
class PackageParser(BaseParser):
    parser_name='PackageParser'; parser_version=PACKAGE_PARSER_VERSION; parse_level='L2'; supported_file_types=['touchstone','pwl','ibis']; supported_extensions=['.s1p','.s2p','.s4p','.s6p','.s8p','.snp','.pwl','.ibs']
    def parse(self,record,context):
        path=record_abs_path(record,context); return make_parser_envelope(parser_name=self.parser_name,parser_version=self.parser_version,file=str(get_field(record,'path',path)),abs_path=str(path),file_type=str(get_field(record,'file_type','package')),compression=get_field(record,'compression',None),data=parse_package_data_file(path),schema_version=str(get_field(context,'schema_version','1.0')))

