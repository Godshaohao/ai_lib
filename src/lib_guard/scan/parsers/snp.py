from __future__ import annotations

from pathlib import Path
from typing import Any
import re

from .base import BaseParser, make_parser_envelope, record_abs_path, get_field, read_text_file

SNP_PARSER_VERSION = "2.0"
_PORT_RE = re.compile(r"\.s(\d+)p$", re.I)


def _ports_from_name(path: str | Path) -> int | None:
    match = _PORT_RE.search(Path(path).name)
    if match:
        return int(match.group(1))
    return None


def parse_snp_text(text: str, source: str = "") -> dict[str, Any]:
    option_line = None
    comments: list[str] = []
    data_lines: list[dict[str, Any]] = []
    for line_no, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue
        if line.startswith("!"):
            if len(comments) < 20:
                comments.append(line[1:].strip())
            continue
        if line.startswith("#"):
            option_line = line
            continue
        parts = line.split()
        if parts:
            data_lines.append({"line": line_no, "frequency": parts[0], "value_count": max(0, len(parts) - 1), "raw": line})
    ports = _ports_from_name(source)
    return {"source": source, "kind": "touchstone", "option_line": option_line, "ports": ports, "data_line_count": len(data_lines), "data_lines": data_lines[:200], "comments": comments, "stats": {"data_line_count": len(data_lines), "comment_count": len(comments)}}


def parse_snp_data_file(path: str | Path) -> dict[str, Any]:
    return parse_snp_text(read_text_file(path), source=str(path))


def parse_snp_file(path: str | Path) -> dict[str, Any]:
    data = parse_snp_data_file(path)
    return make_parser_envelope(parser_name="SnpParser", parser_version=SNP_PARSER_VERSION, file=str(path), abs_path=str(Path(path).resolve()), file_type="snp", data=data)


class SnpParser(BaseParser):
    parser_name = "SnpParser"
    parser_version = SNP_PARSER_VERSION
    parse_level = "L2"
    supported_file_types = ["snp", "touchstone"]
    supported_extensions = [".s1p", ".s2p", ".s4p", ".s6p", ".s8p", ".snp"]

    def parse(self, record: Any, context: Any) -> dict[str, Any]:
        path = record_abs_path(record, context)
        return make_parser_envelope(parser_name=self.parser_name, parser_version=self.parser_version, file=str(get_field(record, "path", path)), abs_path=str(path), file_type=str(get_field(record, "file_type", "snp")), compression=get_field(record, "compression", None), data=parse_snp_data_file(path), schema_version=str(get_field(context, "schema_version", "1.0")))
