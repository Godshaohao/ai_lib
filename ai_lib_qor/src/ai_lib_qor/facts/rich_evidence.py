"""Supplemental parser evidence; never masquerades as the v3 FileFacts contract."""
import hashlib
import json
from pathlib import Path
from ai_lib_qor.versions.store import validate
from .parsers import _file_digest, _strict_encoding
from ._compat.lef import LEF_PARSER_VERSION, parse_lef_data_file
from ._compat.liberty import LIBERTY_PARSER_VERSION, parse_liberty_interface_data_file
from ._compat.verilog import VERILOG_PARSER_VERSION, parse_verilog_data_file
from ._compat.cdl import CDL_PARSER_VERSION, parse_cdl_data_file

PARSERS = {
    'LEF': ('src_qor_lef', LEF_PARSER_VERSION, parse_lef_data_file),
    'LIBERTY': ('src_qor_liberty_interface', LIBERTY_PARSER_VERSION, parse_liberty_interface_data_file),
    'VERILOG': ('src_qor_verilog', VERILOG_PARSER_VERSION, parse_verilog_data_file),
    'CDL': ('src_qor_cdl', CDL_PARSER_VERSION, parse_cdl_data_file),
}


def _digest(data):
    payload = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')
    return hashlib.sha256(payload).hexdigest()


def validate_evidence(evidence):
    if evidence.get('schema_version') != 'parser_evidence.v1': raise ValueError('证据类型不正确')
    data = {k:v for k,v in evidence.items() if k != 'content_sha256'}
    if evidence.get('content_sha256') != _digest(data): raise ValueError('解析证据内容与摘要不一致')


def parse_delivery_evidence(delivery, file_id):
    validate(delivery, 'delivery_record')
    items = [item for item in delivery['files'] if item['file_id'] == file_id]
    if len(items) != 1 or items[0]['classification'] != 'RESOLVED': raise ValueError('文件行身份不明确')
    item = items[0]
    if item['view'] not in PARSERS: raise ValueError('暂不支持该视图的详细证据')
    root = Path(delivery['source_root']).resolve()
    path = (root / item['relative_path']).resolve()
    if not path.is_relative_to(root) or not path.is_file(): raise ValueError('来源路径无效')
    name, version, parser = PARSERS[item['view']]
    before = _file_digest(path)
    _strict_encoding(path)
    data = parser(path)
    if _file_digest(path) != before: raise ValueError('解析期间文件发生变化')
    # The old CDL parser and Verilog preprocessing do not prove complete semantic coverage.
    evidence = {'schema_version':'parser_evidence.v1', 'view':item['view'],
                'source_ref':{'kind':'delivery_file', 'source_library_id':delivery['source_library_id'],
                              'delivery_id':delivery['delivery_id'], 'file_id':file_id},
                'source_sha256':before, 'parser':{'name':name,'version':version},
                'coverage':'PARTIAL', 'coverage_note':'旧版轻量解析输出；不证明完整语义、原始文件当前状态或质量通过。',
                'data':data}
    evidence['content_sha256'] = _digest(evidence)
    return evidence
