from __future__ import annotations

from pathlib import Path
from typing import Any
import shlex

from .base import BaseParser, make_parser_envelope, record_abs_path, get_field, read_text_file

SDC_PARSER_VERSION = "2.0"
_COMMANDS = [
    "create_clock",
    "create_generated_clock",
    "set_clock_groups",
    "set_input_delay",
    "set_output_delay",
    "set_false_path",
    "set_multicycle_path",
    "set_clock_uncertainty",
    "set_load",
    "set_driving_cell",
]


def _logical_lines(text: str) -> list[tuple[int, str]]:
    lines: list[tuple[int, str]] = []
    pending = ""
    start_line = 0
    for line_no, raw in enumerate(text.splitlines(), start=1):
        line = raw.split("#", 1)[0].rstrip()
        if not line:
            continue
        if not pending:
            start_line = line_no
        if line.endswith("\\"):
            pending += line[:-1] + " "
            continue
        lines.append((start_line or line_no, (pending + line).strip()))
        pending = ""
        start_line = 0
    if pending:
        lines.append((start_line, pending.strip()))
    return lines


def _tokens(line: str) -> list[str]:
    try:
        return shlex.split(line)
    except Exception:
        return line.split()


def _options(tokens: list[str]) -> tuple[dict[str, str | bool], list[str]]:
    opts: dict[str, str | bool] = {}
    positional: list[str] = []
    index = 1
    while index < len(tokens):
        token = tokens[index]
        if token.startswith("-"):
            key = token.lstrip("-").replace("-", "_")
            if index + 1 < len(tokens) and not tokens[index + 1].startswith("-"):
                opts[key] = tokens[index + 1]
                index += 2
            else:
                opts[key] = True
                index += 1
        else:
            positional.append(token)
            index += 1
    return opts, positional


def _float_or_text(value: Any) -> Any:
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return value


def _name(opts: dict[str, Any], positional: list[str], fallback: str) -> str:
    return str(opts.get("name") or (positional[0] if positional else fallback))


def parse_sdc_text(text: str, source: str = "") -> dict[str, Any]:
    commands: list[dict[str, Any]] = []
    counts = {command: 0 for command in _COMMANDS}
    semantic: dict[str, Any] = {
        "clocks": {},
        "generated_clocks": {},
        "clock_groups": [],
        "input_delays": [],
        "output_delays": [],
        "false_paths": [],
        "multicycle_paths": [],
        "uncertainty": {},
        "loads": {},
        "driving_cells": {},
    }

    for line_no, line in _logical_lines(text):
        tokens = _tokens(line)
        cmd = tokens[0] if tokens else ""
        if cmd not in counts:
            continue
        counts[cmd] += 1
        opts, positional = _options(tokens)
        commands.append({"command": cmd, "tokens": tokens, "options": opts, "positional": positional, "raw": line, "line": line_no})

        if cmd == "create_clock":
            name = _name(opts, positional, f"clock@{line_no}")
            target = opts.get("targets") or (positional[-1] if positional else "")
            semantic["clocks"][name] = {"name": name, "period": _float_or_text(opts.get("period")), "waveform": opts.get("waveform"), "target": target, "line": line_no, "raw": line}
        elif cmd == "create_generated_clock":
            name = _name(opts, positional, f"generated_clock@{line_no}")
            semantic["generated_clocks"][name] = {"name": name, "source": opts.get("source"), "master_clock": opts.get("master_clock"), "divide_by": _float_or_text(opts.get("divide_by")), "multiply_by": _float_or_text(opts.get("multiply_by")), "target": positional[-1] if positional else "", "line": line_no, "raw": line}
        elif cmd == "set_clock_uncertainty":
            value = positional[0] if positional else opts.get("setup") or opts.get("hold")
            target = " ".join(positional[1:]) if len(positional) > 1 else str(opts.get("to") or opts.get("from") or "global")
            semantic["uncertainty"][target] = {"value": _float_or_text(value), "setup": _float_or_text(opts.get("setup")), "hold": _float_or_text(opts.get("hold")), "line": line_no, "raw": line}
        elif cmd == "set_load":
            value = positional[0] if positional else opts.get("pin_load") or opts.get("wire_load")
            target = " ".join(positional[1:]) if len(positional) > 1 else "global"
            semantic["loads"][target] = {"value": _float_or_text(value), "line": line_no, "raw": line}
        elif cmd == "set_driving_cell":
            target = str(opts.get("pin") or (positional[-1] if positional else f"driving@{line_no}"))
            semantic["driving_cells"][target] = {"lib_cell": opts.get("lib_cell"), "library": opts.get("library"), "from_pin": opts.get("from_pin"), "line": line_no, "raw": line}
        elif cmd in {"set_input_delay", "set_output_delay"}:
            bucket = "input_delays" if cmd == "set_input_delay" else "output_delays"
            semantic[bucket].append({"value": _float_or_text(positional[0] if positional else None), "clock": opts.get("clock"), "target": " ".join(positional[1:]) if len(positional) > 1 else "", "line": line_no, "raw": line})
        elif cmd in {"set_false_path", "set_multicycle_path", "set_clock_groups"}:
            bucket = {"set_false_path": "false_paths", "set_multicycle_path": "multicycle_paths", "set_clock_groups": "clock_groups"}[cmd]
            semantic[bucket].append({"options": opts, "positional": positional, "line": line_no, "raw": line})

    return {"source": source, "commands": commands, "counts": counts, "semantic": semantic, "stats": {"command_count": len(commands), "clock_count": len(semantic["clocks"]), "load_count": len(semantic["loads"])}}


def parse_sdc_data_file(path: str | Path) -> dict[str, Any]:
    return parse_sdc_text(read_text_file(path), source=str(path))


def parse_sdc_file(path: str | Path) -> dict[str, Any]:
    data = parse_sdc_data_file(path)
    return make_parser_envelope(parser_name="SdcParser", parser_version=SDC_PARSER_VERSION, file=str(path), abs_path=str(Path(path).resolve()), file_type="sdc", data=data)


class SdcParser(BaseParser):
    parser_name = "SdcParser"
    parser_version = SDC_PARSER_VERSION
    parse_level = "L2"
    supported_file_types = ["sdc"]
    supported_extensions = [".sdc"]

    def parse(self, record: Any, context: Any) -> dict[str, Any]:
        path = record_abs_path(record, context)
        return make_parser_envelope(parser_name=self.parser_name, parser_version=self.parser_version, file=str(get_field(record, "path", path)), abs_path=str(path), file_type=str(get_field(record, "file_type", "sdc")), compression=get_field(record, "compression", None), data=parse_sdc_data_file(path), schema_version=str(get_field(context, "schema_version", "1.0")))
