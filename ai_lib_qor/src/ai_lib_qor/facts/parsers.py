"""Adapt copied src_qor LEF and Liberty interface parsers to the v3 facts contract."""
import gzip
import hashlib
import json
from pathlib import Path
from ai_lib_qor.versions.store import validate
from ._compat.lef import LEF_PARSER_VERSION, parse_lef_data_file
from ._compat.liberty import LIBERTY_PARSER_VERSION, parse_liberty_interface_data_file

ADAPTER_VERSION = "1.0"


def _unique(items,label):
    names=[x['name'] for x in items]
    if len(names)!=len(set(names)):raise ValueError(f'{label} 名称重复')
    return items


def _file_digest(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        while chunk:=f.read(1024*1024):h.update(chunk)
    return h.hexdigest()


def _strict_encoding(path):
    opener=gzip.open if path.name.lower().endswith('.gz') else open
    with opener(path,'rt',encoding='utf-8',errors='strict') as f:
        while f.read(1024*1024):pass


def parse_delivery_file(delivery,file_id):
    validate(delivery,'delivery_record')
    items=[x for x in delivery['files'] if x['file_id']==file_id]
    if len(items)!=1 or items[0]['classification']!='RESOLVED':raise ValueError('文件行身份不明确')
    item=items[0];root=Path(delivery['source_root']).resolve();path=(root/item['relative_path']).resolve()
    if not path.is_relative_to(root) or not path.is_file():raise ValueError('来源路径无效')
    ref={'kind':'delivery_file','source_library_id':delivery['source_library_id'],'delivery_id':delivery['delivery_id'],'file_id':file_id}
    digest=_file_digest(path)
    if item['view']=='LEF':
        _strict_encoding(path)
        parsed=parse_lef_data_file(path)
        coverage=parsed['semantic_coverage']
        if coverage['macro_set']!='PRESENT' or coverage['port_set']!='PRESENT':raise ValueError('LEF 结构不完整或解析覆盖不足')
        result=[]
        for name,m in parsed['macros'].items():
            size=m.get('size'); pins=[]
            if isinstance(size,dict) and set(size)>={'x','y'}:size=[size['x'],size['y']]
            if not isinstance(size,(list,tuple)) or len(size)!=2:raise ValueError(f'{name} 缺少可确认 SIZE')
            for pin,p in m['pins'].items():
                if str(p.get('use') or '').upper() in {'POWER','GROUND'}:raise ValueError(f'{name}/{pin} 是电源引脚，v3 事实无法保留 Pin 类型')
                if not p.get('direction'):raise ValueError(f'{name}/{pin} 缺少方向')
                pins.append({'name':pin,'direction':p['direction']})
            result.append({'name':name,'size_um':list(size),'pins':_unique(pins,'Pin')})
        if not result:raise ValueError('LEF 不含可确认 Macro')
        obj={'macros':_unique(result,'Macro')};units={'distance':'um'};sections=['MACRO_NAME','MACRO_SIZE','PIN_NAME','PIN_DIRECTION'];parser={'name':'src_qor_lef','version':f'{LEF_PARSER_VERSION}+adapter-{ADAPTER_VERSION}'}
    elif item['view']=='LIBERTY':
        _strict_encoding(path)
        parsed=parse_liberty_interface_data_file(path)
        if parsed['semantic_coverage']['port_set']!='PRESENT':raise ValueError('Liberty 结构不完整或接口覆盖不足')
        cells=[]
        for lib in parsed['libraries'].values():
            for name,cell in lib['cells'].items():
                pins=[]
                for pin,p in cell['pins'].items():
                    if not p.get('direction'):raise ValueError(f'{name}/{pin} 缺少方向')
                    pins.append({'name':pin,'direction':p['direction']})
                cells.append({'name':name,'pins':_unique(pins,'Pin')})
        if not cells:raise ValueError('Liberty 不含可确认 Cell')
        obj={'cells':_unique(cells,'Cell')};units={};sections=['CELL_NAME','PIN_NAME','PIN_DIRECTION'];parser={'name':'src_qor_liberty_interface','version':f'{LIBERTY_PARSER_VERSION}+adapter-{ADAPTER_VERSION}'}
    else:raise ValueError(f"不支持解析的 View: {item['view']}")
    if _file_digest(path)!=digest:raise ValueError('解析期间文件发生变化')
    identity=json.dumps({'source_ref':ref,'digest':digest,'parser':parser},sort_keys=True,separators=(',',':')).encode()
    facts={'schema_version':'file_facts.v1','facts_id':'facts_'+hashlib.sha256(identity).hexdigest()[:24],'source_ref':ref,'view':item['view'],'parser':parser,'parse_status':'COMPLETE','covered_sections':sections,'units':units,'objects':obj}
    validate(facts,'file_facts');return facts
