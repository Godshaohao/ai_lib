from __future__ import annotations
from pathlib import Path
from typing import Any
from .base import BaseParser, make_parser_envelope, record_abs_path, get_field

DB_PARSER_VERSION = '2.0'

def probe_db_file(path: str | Path) -> dict[str, Any]:
    p = Path(path); st = p.stat()
    return {'source': str(p), 'file_type': 'db', 'size_bytes': st.st_size, 'status': 'metadata_only', 'note': 'Synopsys .db is binary. MVP does not deep-parse .db without EDA tool adapter.'}

def parse_db_data_file(path: str | Path) -> dict[str, Any]:
    return probe_db_file(path)

def parse_db_file(path: str | Path) -> dict[str, Any]:
    data = parse_db_data_file(path)
    return make_parser_envelope(parser_name='DbParser', parser_version=DB_PARSER_VERSION, file=str(path), abs_path=str(Path(path).resolve()), file_type='db', data=data, status='METADATA_ONLY')

class DbParser(BaseParser):
    parser_name = 'DbParser'; parser_version = DB_PARSER_VERSION; parse_level = 'L2'
    supported_file_types = ['db']; supported_extensions = ['.db']
    def parse(self, record: Any, context: Any) -> dict[str, Any]:
        path = record_abs_path(record, context)
        return make_parser_envelope(parser_name=self.parser_name, parser_version=self.parser_version, file=str(get_field(record, 'path', path)), abs_path=str(path), file_type=str(get_field(record, 'file_type', 'db')), compression=get_field(record, 'compression', None), data=parse_db_data_file(path), status='METADATA_ONLY', schema_version=str(get_field(context, 'schema_version', '1.0')))

