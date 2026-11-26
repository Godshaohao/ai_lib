"""Adapt trusted parsers to the path FileFacts contract via the pluggable registry."""
import hashlib
import inspect
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


def parse_file_payload(path, view, *, allow_pg=False, registry=PARSER_REGISTRY, digest_out=None):
    """Parse supported objects via the pluggable view parser registry (single-pass hashing when supported)."""
    handler = get_parser(view, registry=registry)
    if digest_out is not None and 'digest_out' in inspect.signature(handler).parameters:
        return handler(Path(path), allow_pg=allow_pg, digest_out=digest_out)
    return handler(Path(path), allow_pg=allow_pg)
