"""Adapt trusted parsers to the path FileFacts contract via the pluggable registry."""
import hashlib
from pathlib import Path

from .registry import (
    ADAPTER_VERSION,
    CDL_PARSER_VERSION,
    LEF_PARSER_VERSION,
    LIBERTY_PARSER_VERSION,
    PARSER_REGISTRY,
    VERILOG_PARSER_VERSION,
    _strict_encoding,
    current_parser_info,
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
