from __future__ import annotations
from pathlib import Path
from typing import Any
from .base import BaseParser, make_parser_envelope, record_abs_path, get_field, read_text_file
FILELIST_PARSER_VERSION='2.0'
def parse_filelist_text(text: str, source: str='')->dict[str,Any]:
    files=[]; incdirs=[]; defines=[]; options=[]
    for ln, raw in enumerate(text.splitlines(),1):
        line=raw.split('//',1)[0].strip()
        if not line: continue
        if line.startswith('+incdir+'): incdirs.extend([x for x in line.split('+')[2:] if x])
        elif line.startswith('+define+'): defines.append(line[len('+define+'):])
        elif line.startswith('-'): options.append(line)
        else: files.append({'path':line,'line':ln})
    return {'source':source,'files':files,'incdirs':incdirs,'defines':defines,'options':options,'stats':{'file_count':len(files),'incdir_count':len(incdirs),'define_count':len(defines)}}
def parse_filelist_data_file(path: str|Path)->dict[str,Any]: return parse_filelist_text(read_text_file(path),source=str(path))
def parse_filelist_file(path: str|Path)->dict[str,Any]:
    data=parse_filelist_data_file(path)
    return make_parser_envelope(parser_name='FilelistParser',parser_version=FILELIST_PARSER_VERSION,file=str(path),abs_path=str(Path(path).resolve()),file_type='filelist',data=data)
class FilelistParser(BaseParser):
    parser_name='FilelistParser'; parser_version=FILELIST_PARSER_VERSION; parse_level='L2'; supported_file_types=['filelist']; supported_extensions=['.f','.flist']
    def parse(self,record,context):
        path=record_abs_path(record,context); return make_parser_envelope(parser_name=self.parser_name,parser_version=self.parser_version,file=str(get_field(record,'path',path)),abs_path=str(path),file_type=str(get_field(record,'file_type','filelist')),compression=get_field(record,'compression',None),data=parse_filelist_data_file(path),schema_version=str(get_field(context,'schema_version','1.0')))

