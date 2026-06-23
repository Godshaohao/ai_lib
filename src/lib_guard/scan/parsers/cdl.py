from __future__ import annotations
from pathlib import Path
from typing import Any
import re
from .base import BaseParser, make_parser_envelope, record_abs_path, get_field, read_text_file
CDL_PARSER_VERSION='2.0'
_RE_SUBCKT=re.compile(r'^\s*\.SUBCKT\s+(\S+)\s+(.*)$', re.I)
_RE_ENDS=re.compile(r'^\s*\.ENDS\s*(\S+)?', re.I)
_RE_INCLUDE=re.compile(r'^\s*\.(?:INCLUDE|INC)\s+["\']?([^"\'\s]+)', re.I)

def parse_cdl_text(text: str, source: str='') -> dict[str, Any]:
    subckts={}; includes=[]; current=None; dev_count=0
    for ln, raw in enumerate(text.splitlines(),1):
        line=raw.strip()
        if not line or line.startswith('*'): continue
        m=_RE_INCLUDE.match(line)
        if m: includes.append({'file':m.group(1),'line':ln}); continue
        m=_RE_SUBCKT.match(line)
        if m:
            current=m.group(1); pins=m.group(2).split()
            subckts[current]={'name':current,'line_start':ln,'pins':pins,'pin_count':len(pins),'device_count':0}
            dev_count=0; continue
        m=_RE_ENDS.match(line)
        if m and current:
            subckts[current]['line_end']=ln; subckts[current]['device_count']=dev_count; current=None; continue
        if current and not line.startswith('.'):
            dev_count += 1
    return {'source':source,'subckts':subckts,'subckt_order':list(subckts.keys()),'includes':includes,'stats':{'subckt_count':len(subckts),'include_count':len(includes)}}

def parse_cdl_data_file(path: str|Path)->dict[str,Any]: return parse_cdl_text(read_text_file(path), source=str(path))
def parse_cdl_file(path: str|Path)->dict[str,Any]:
    data=parse_cdl_data_file(path)
    return make_parser_envelope(parser_name='CdlParser',parser_version=CDL_PARSER_VERSION,file=str(path),abs_path=str(Path(path).resolve()),file_type='cdl',data=data)
def diff_cdl_summary(old,new):
    os,ns=old.get('subckts',{}),new.get('subckts',{}); changed={}
    for s in sorted(set(os)&set(ns)):
        if os[s].get('pins')!=ns[s].get('pins'): changed[s]={'pins':{'old':os[s].get('pins'),'new':ns[s].get('pins')}}
    return {'schema_version':'1.0','diff_type':'cdl_summary_diff','subckt_changes':{'added':sorted(set(ns)-set(os)),'removed':sorted(set(os)-set(ns)),'changed':changed}}
def diff_cdl_files(old_path,new_path): return diff_cdl_summary(parse_cdl_file(old_path)["data"],parse_cdl_file(new_path)["data"])
class CdlParser(BaseParser):
    parser_name='CdlParser'; parser_version=CDL_PARSER_VERSION; parse_level='L2'; supported_file_types=['cdl']; supported_extensions=['.cdl','.cdl.gz','.sp','.spi','.spice']
    def parse(self, record, context):
        path=record_abs_path(record,context); return make_parser_envelope(parser_name=self.parser_name,parser_version=self.parser_version,file=str(get_field(record,'path',path)),abs_path=str(path),file_type=str(get_field(record,'file_type','cdl')),compression=get_field(record,'compression',None),data=parse_cdl_data_file(path),schema_version=str(get_field(context,'schema_version','1.0')))

