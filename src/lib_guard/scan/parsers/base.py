"""
Base parser utilities.

This is the only shared helper module under parsers/. There is no text.py.
It contains generic read helpers, parser envelope helpers, and BaseParser.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Mapping, Iterable
import gzip
import json
import hashlib


def get_field(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, Mapping):
        return obj.get(key, default)
    return getattr(obj, key, default)


def record_abs_path(record: Any, context: Any = None) -> Path:
    abs_path = get_field(record, 'abs_path', None)
    if abs_path:
        return Path(abs_path)
    path = Path(str(get_field(record, 'path', '')))
    if path.is_absolute():
        return path
    root = Path(str(get_field(context, 'root_path', '.'))) if context is not None else Path('.')
    return root / path


def detect_combined_extension(path: str | Path) -> str:
    name = Path(path).name.lower()
    if name.endswith(".gz"):
        stem = name[:-3]
        return Path(stem).suffix.lower() + ".gz"
    return Path(name).suffix.lower()


def detect_compression(path: str | Path) -> str | None:
    return "gzip" if Path(path).name.lower().endswith(".gz") else None


def read_text_file(path: str | Path, *, encoding: str = 'utf-8', errors: str = 'ignore', max_bytes: int | None = None) -> str:
    p = Path(path)
    if max_bytes is not None and p.exists() and p.stat().st_size > max_bytes and not p.name.endswith('.gz'):
        with p.open('rb') as f:
            data = f.read(max_bytes)
        return data.decode(encoding, errors=errors)
    if p.name.endswith('.gz'):
        with gzip.open(p, 'rt', encoding=encoding, errors=errors) as f:
            return f.read()
    return p.read_text(encoding=encoding, errors=errors)


def stable_hash(data: Any) -> str:
    payload = json.dumps(data, sort_keys=True, ensure_ascii=False, default=str, separators=(',', ':'))
    return 'sha256:' + hashlib.sha256(payload.encode('utf-8')).hexdigest()


def unique_sorted(items: Iterable[Any]) -> list[Any]:
    return sorted(set(items), key=lambda x: str(x))


@dataclass
class ParserIssue:
    severity: str
    message: str
    rule_id: str = 'PARSER.GENERIC'
    line: int | None = None
    object_name: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def make_parser_envelope(
    *,
    parser_name: str | None = None,
    parser_version: str,
    file: str,
    data: dict[str, Any],
    status: str = 'PASS',
    issues: list[ParserIssue | dict[str, Any]] | None = None,
    schema_version: str = '1.0',
    abs_path: str | None = None,
    file_type: str | None = None,
    compression: str | None = None,
    parser_schema_version: str = '1.0',
) -> dict[str, Any]:
    norm_issues: list[dict[str, Any]] = []
    for issue in issues or []:
        norm_issues.append(issue.to_dict() if isinstance(issue, ParserIssue) else dict(issue))
    resolved_parser_name = parser_name or 'UnknownParser'
    resolved_file_type = file_type if file_type is not None else _infer_file_type(resolved_parser_name, file)
    object_count = _object_count(data)
    warning_count = len([i for i in norm_issues if str(i.get("severity", "")).lower() == "warning"])
    error_count = len([i for i in norm_issues if str(i.get("severity", "")).lower() in {"error", "blocker"}])
    final_status = status
    if final_status == "PASS" and object_count == 0:
        final_status = "PASS_EMPTY"
    return {
        'schema_version': schema_version,
        'result_type': 'parser_result',
        'parser_name': resolved_parser_name,
        'parser_version': '2.0',
        'parser_schema_version': parser_schema_version,
        'file': file,
        'abs_path': abs_path,
        'file_type': resolved_file_type,
        'compression': compression if compression is not None else detect_compression(file),
        'status': final_status,
        'stats': {
            'object_count': object_count,
            'warning_count': warning_count,
            'error_count': error_count,
        },
        'data': data,
        'issues': norm_issues,
    }


def _object_count(data: Mapping[str, Any]) -> int:
    stats = data.get("stats")
    if isinstance(stats, Mapping):
        counts = [value for key, value in stats.items() if str(key).endswith("_count") and isinstance(value, int)]
        if counts:
            return sum(counts)
    for key in ("modules", "macros", "cells", "libraries", "subckts", "constraints", "clocks", "nets", "waivers", "files", "entries"):
        value = data.get(key)
        if isinstance(value, Mapping):
            return len(value)
        if isinstance(value, list):
            return len(value)
    return 0


def _infer_file_type(parser_name: str, file: str) -> str:
    name = parser_name.lower().replace("parser", "")
    if name:
        return "verilog" if name == "systemverilog" else name
    ext = detect_combined_extension(file)
    return ext.lstrip(".").replace(".gz", "") or "unknown"


class BaseParser:
    parser_name = 'BaseParser'
    parser_version = '2.0'
    parse_level = 'L2'
    supported_file_types: list[str] = []
    supported_extensions: list[str] = []

    def __init__(self, config: Any = None) -> None:
        self.config = config

    def can_parse(self, record: Any, context: Any) -> bool:
        file_type = str(get_field(record, 'file_type', ''))
        ext = str(get_field(record, 'combined_extension', get_field(record, 'extension', ''))).lower()
        return file_type in self.supported_file_types or ext in self.supported_extensions

    def parse(self, record: Any, context: Any) -> dict[str, Any]:
        raise NotImplementedError

