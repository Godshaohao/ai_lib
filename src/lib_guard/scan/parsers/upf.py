from __future__ import annotations

from pathlib import Path
from typing import Any
import shlex

from .base import BaseParser, make_parser_envelope, record_abs_path, get_field, read_text_file

UPF_PARSER_VERSION = "2.0"
_UPF_COMMANDS = [
    "create_power_domain",
    "create_supply_net",
    "create_supply_port",
    "connect_supply_net",
    "set_domain_supply_net",
    "set_isolation",
    "set_level_shifter",
    "set_retention",
    "add_power_state",
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


def _first(positional: list[str], fallback: str) -> str:
    return str(positional[0] if positional else fallback)


def parse_upf_text(text: str, source: str = "") -> dict[str, Any]:
    commands: list[dict[str, Any]] = []
    counts = {command: 0 for command in _UPF_COMMANDS}
    semantic: dict[str, Any] = {
        "power_domains": {},
        "supply_nets": {},
        "supply_ports": {},
        "domain_supply": {},
        "isolation": {},
        "level_shifters": {},
        "retention": {},
        "power_states": [],
        "connections": [],
    }

    for line_no, line in _logical_lines(text):
        tokens = _tokens(line)
        cmd = tokens[0] if tokens else ""
        if cmd not in counts:
            continue
        counts[cmd] += 1
        opts, positional = _options(tokens)
        commands.append({"command": cmd, "tokens": tokens, "options": opts, "positional": positional, "raw": line, "line": line_no})

        if cmd == "create_power_domain":
            name = _first(positional, f"domain@{line_no}")
            semantic["power_domains"][name] = {"name": name, "elements": opts.get("elements"), "include_scope": opts.get("include_scope"), "line": line_no, "raw": line}
        elif cmd == "create_supply_net":
            name = _first(positional, f"supply_net@{line_no}")
            semantic["supply_nets"][name] = {"name": name, "domain": opts.get("domain"), "reuse": opts.get("reuse"), "line": line_no, "raw": line}
        elif cmd == "create_supply_port":
            name = _first(positional, f"supply_port@{line_no}")
            semantic["supply_ports"][name] = {"name": name, "domain": opts.get("domain"), "direction": opts.get("direction"), "line": line_no, "raw": line}
        elif cmd == "connect_supply_net":
            semantic["connections"].append({"net": _first(positional, ""), "ports": opts.get("ports") or opts.get("port"), "line": line_no, "raw": line})
        elif cmd == "set_domain_supply_net":
            domain = _first(positional, f"domain_supply@{line_no}")
            semantic["domain_supply"][domain] = {"primary_power_net": opts.get("primary_power_net"), "primary_ground_net": opts.get("primary_ground_net"), "line": line_no, "raw": line}
        elif cmd == "set_isolation":
            name = _first(positional, f"isolation@{line_no}")
            semantic["isolation"][name] = {"name": name, "domain": opts.get("domain"), "applies_to": opts.get("applies_to"), "clamp_value": opts.get("clamp_value"), "isolation_signal": opts.get("isolation_signal"), "line": line_no, "raw": line}
        elif cmd == "set_level_shifter":
            name = _first(positional, f"level_shifter@{line_no}")
            semantic["level_shifters"][name] = {"name": name, "domain": opts.get("domain"), "applies_to": opts.get("applies_to"), "rule": opts.get("rule"), "line": line_no, "raw": line}
        elif cmd == "set_retention":
            name = _first(positional, f"retention@{line_no}")
            semantic["retention"][name] = {"name": name, "domain": opts.get("domain"), "retention_supply": opts.get("retention_supply"), "save_signal": opts.get("save_signal"), "restore_signal": opts.get("restore_signal"), "line": line_no, "raw": line}
        elif cmd == "add_power_state":
            semantic["power_states"].append({"object": _first(positional, ""), "state": opts.get("state"), "supply_expr": opts.get("supply_expr"), "logic_expr": opts.get("logic_expr"), "line": line_no, "raw": line})

    return {"source": source, "commands": commands, "counts": counts, "semantic": semantic, "stats": {"command_count": len(commands), "power_domain_count": len(semantic["power_domains"]), "supply_net_count": len(semantic["supply_nets"])}}


def parse_upf_data_file(path: str | Path) -> dict[str, Any]:
    return parse_upf_text(read_text_file(path), source=str(path))


def parse_upf_file(path: str | Path) -> dict[str, Any]:
    data = parse_upf_data_file(path)
    return make_parser_envelope(parser_name="UpfParser", parser_version=UPF_PARSER_VERSION, file=str(path), abs_path=str(Path(path).resolve()), file_type="upf", data=data)


class UpfParser(BaseParser):
    parser_name = "UpfParser"
    parser_version = UPF_PARSER_VERSION
    parse_level = "L2"
    supported_file_types = ["upf"]
    supported_extensions = [".upf"]

    def parse(self, record: Any, context: Any) -> dict[str, Any]:
        path = record_abs_path(record, context)
        return make_parser_envelope(parser_name=self.parser_name, parser_version=self.parser_version, file=str(get_field(record, "path", path)), abs_path=str(path), file_type=str(get_field(record, "file_type", "upf")), compression=get_field(record, "compression", None), data=parse_upf_data_file(path), schema_version=str(get_field(context, "schema_version", "1.0")))
