from __future__ import annotations

from pathlib import Path
from typing import Any
import re

from .base import BaseParser, make_parser_envelope, record_abs_path, get_field, read_text_file

PWL_PARSER_VERSION = "2.0"
_NUMBER_RE = re.compile(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?([a-zA-Z]*)$")
_SCALE = {"": 1.0, "s": 1.0, "ms": 1e-3, "us": 1e-6, "ns": 1e-9, "ps": 1e-12, "fs": 1e-15, "v": 1.0, "mv": 1e-3}


def _num(value: str) -> float | str:
    match = _NUMBER_RE.match(value)
    if not match:
        return value
    suffix = match.group(1).lower()
    base = value[: len(value) - len(match.group(1))]
    try:
        return float(base) * _SCALE.get(suffix, 1.0)
    except ValueError:
        return value


def parse_pwl_text(text: str, source: str = "") -> dict[str, Any]:
    points: list[dict[str, Any]] = []
    directives: list[dict[str, Any]] = []
    for line_no, raw in enumerate(text.splitlines(), start=1):
        line = raw.split("#", 1)[0].split("//", 1)[0].strip()
        if not line:
            continue
        parts = line.replace(",", " ").replace("(", " ").replace(")", " ").split()
        if len(parts) >= 2:
            points.append({"index": len(points), "time": _num(parts[0]), "value": _num(parts[1]), "line": line_no, "raw": line})
        else:
            directives.append({"line": line_no, "raw": line})
    return {"source": source, "points": points, "directives": directives, "stats": {"point_count": len(points), "directive_count": len(directives)}}


def parse_pwl_data_file(path: str | Path) -> dict[str, Any]:
    return parse_pwl_text(read_text_file(path), source=str(path))


def parse_pwl_file(path: str | Path) -> dict[str, Any]:
    data = parse_pwl_data_file(path)
    return make_parser_envelope(parser_name="PwlParser", parser_version=PWL_PARSER_VERSION, file=str(path), abs_path=str(Path(path).resolve()), file_type="pwl", data=data)


class PwlParser(BaseParser):
    parser_name = "PwlParser"
    parser_version = PWL_PARSER_VERSION
    parse_level = "L2"
    supported_file_types = ["pwl"]
    supported_extensions = [".pwl"]

    def parse(self, record: Any, context: Any) -> dict[str, Any]:
        path = record_abs_path(record, context)
        return make_parser_envelope(parser_name=self.parser_name, parser_version=self.parser_version, file=str(get_field(record, "path", path)), abs_path=str(path), file_type=str(get_field(record, "file_type", "pwl")), compression=get_field(record, "compression", None), data=parse_pwl_data_file(path), schema_version=str(get_field(context, "schema_version", "1.0")))
