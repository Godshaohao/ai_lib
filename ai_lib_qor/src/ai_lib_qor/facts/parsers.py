"""Adapt trusted parsers to the v3/path FileFacts contracts via the pluggable registry."""
import hashlib
import json
from pathlib import Path

from ai_lib_qor.versions.store import validate
from .registry import (
    ADAPTER_VERSION,
    CDL_PARSER_VERSION,
    LEF_PARSER_VERSION,
    LIBERTY_PARSER_VERSION,
    PARSER_REGISTRY,
    VERILOG_PARSER_VERSION,
    _strict_encoding,
    get_parser,
    parser_signature,
    register_parser,
    supported_views,
)


def _file_digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        while chunk := f.read(1024 * 1024):
            h.update(chunk)
    return h.hexdigest()


def parse_file_payload(path, view, *, allow_pg=False, registry=PARSER_REGISTRY):
    """Parse supported objects via the pluggable view parser registry."""
    handler = get_parser(view, registry=registry)
    return handler(Path(path), allow_pg=allow_pg)


def parse_delivery_file(delivery, file_id):
    validate(delivery, 'delivery_record')
    items = [x for x in delivery['files'] if x['file_id'] == file_id]
    if len(items) != 1 or items[0]['classification'] != 'RESOLVED':
        raise ValueError('文件行身份不明确')
    item = items[0]
    root = Path(delivery['source_root']).resolve()
    path = (root / item['relative_path']).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError('来源路径无效')
    ref = {
        'kind': 'delivery_file',
        'source_library_id': delivery['source_library_id'],
        'delivery_id': delivery['delivery_id'],
        'file_id': file_id,
    }
    digest = _file_digest(path)
    payload = parse_file_payload(path, item['view'])
    if _file_digest(path) != digest:
        raise ValueError('解析期间文件发生变化')
    parser = payload['parser']
    identity = json.dumps({'source_ref': ref, 'digest': digest, 'parser': parser}, sort_keys=True, separators=(',', ':')).encode()
    facts = {
        'schema_version': 'file_facts.v1',
        'facts_id': 'facts_' + hashlib.sha256(identity).hexdigest()[:24],
        'source_ref': ref,
        **payload,
    }
    validate(facts, 'file_facts')
    return facts
