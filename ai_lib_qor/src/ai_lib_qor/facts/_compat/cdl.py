from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable
import re

from .base import BaseParser, make_parser_envelope, record_abs_path, get_field, read_text_file

CDL_PARSER_VERSION = "2.0"

_RE_SUBCKT = re.compile(r"^\s*\.SUBCKT\s+(\S+)\s*(.*)$", re.I)
_RE_ENDS = re.compile(r"^\s*\.ENDS\s*(\S+)?", re.I)
_RE_INCLUDE = re.compile(r"^\s*\.(?:INCLUDE|INC)\s+[\"']?([^\"'\s]+)", re.I)

_KIND_BY_PREFIX = {
    "X": "subckt",
    "M": "mos",
    "R": "resistor",
    "C": "capacitor",
    "L": "inductor",
    "D": "diode",
    "Q": "bjt",
    "J": "jfet",
    "V": "voltage_source",
    "I": "current_source",
}


def _logical_lines(text: str) -> Iterable[tuple[int, str]]:
    start_line: int | None = None
    parts: list[str] = []
    for line_no, raw in enumerate(text.splitlines(), start=1):
        stripped = raw.strip()
        if not stripped or stripped.startswith("*"):
            continue
        if stripped.startswith("+"):
            if start_line is None:
                start_line = line_no
            parts.append(stripped[1:].strip())
            continue
        if parts and start_line is not None:
            yield start_line, " ".join(part for part in parts if part)
        start_line = line_no
        parts = [stripped]
    if parts and start_line is not None:
        yield start_line, " ".join(part for part in parts if part)


def _non_parameter_tokens(tokens: list[str]) -> list[str]:
    return [token for token in tokens if "=" not in token]


def _instance_pins_and_target(kind: str, tokens: list[str]) -> tuple[list[str], str | None]:
    non_params = _non_parameter_tokens(tokens)
    if not non_params:
        return [], None
    if kind == "subckt":
        return non_params[:-1], non_params[-1]
    if kind == "mos":
        return non_params[:4], non_params[4] if len(non_params) > 4 else None
    if kind in {"resistor", "capacitor", "inductor", "voltage_source", "current_source"}:
        return non_params[:2], non_params[2] if len(non_params) > 2 else None
    if kind == "diode":
        return non_params[:2], non_params[2] if len(non_params) > 2 else None
    if kind in {"bjt", "jfet"}:
        return non_params[:3], non_params[3] if len(non_params) > 3 else None
    return non_params[:-1], non_params[-1] if len(non_params) > 1 else None


def _parse_instance(line: str, line_no: int) -> dict[str, Any] | None:
    tokens = line.split()
    if not tokens:
        return None
    name = tokens[0]
    if name.startswith("."):
        return None
    kind = _KIND_BY_PREFIX.get(name[:1].upper(), "device")
    pins, target = _instance_pins_and_target(kind, tokens[1:])
    return {
        "name": name,
        "kind": kind,
        "target": target,
        "pins": pins,
        "pin_count": len(pins),
        "line": line_no,
    }


def parse_cdl_text(text: str, source: str = "") -> dict[str, Any]:
    subckts: dict[str, dict[str, Any]] = {}
    includes: list[dict[str, Any]] = []
    flat_instances: list[dict[str, Any]] = []
    current_name: str | None = None
    current: dict[str, Any] | None = None

    for line_no, line in _logical_lines(text):
        m = _RE_INCLUDE.match(line)
        if m:
            includes.append({"file": m.group(1), "line": line_no})
            continue
        m = _RE_SUBCKT.match(line)
        if m:
            current_name = m.group(1)
            pins = [token for token in m.group(2).split() if token]
            current = {
                "name": current_name,
                "line_start": line_no,
                "line_end": None,
                "pins": pins,
                "pin_count": len(pins),
                "instances": [],
                "instance_count": 0,
                "device_count": 0,
            }
            subckts[current_name] = current
            continue
        m = _RE_ENDS.match(line)
        if m and current is not None:
            current["line_end"] = line_no
            current["instance_count"] = len(current["instances"])
            current["device_count"] = len(current["instances"])
            current = None
            current_name = None
            continue
        if current is not None and current_name is not None:
            instance = _parse_instance(line, line_no)
            if instance is None:
                continue
            instance["subckt"] = current_name
            current["instances"].append(instance)
            flat_instances.append(instance)

    for subckt in subckts.values():
        subckt["instance_count"] = len(subckt.get("instances") or [])
        subckt["device_count"] = subckt["instance_count"]

    pin_count = sum(int(subckt.get("pin_count") or 0) for subckt in subckts.values())
    instance_count = len(flat_instances)
    return {
        "source": source,
        "subckts": subckts,
        "subckt_order": list(subckts.keys()),
        "instances": flat_instances,
        "includes": includes,
        "stats": {
            "subckt_count": len(subckts),
            "include_count": len(includes),
            "pin_count": pin_count,
            "instance_count": instance_count,
            "device_count": instance_count,
        },
    }


def parse_cdl_data_file(path: str | Path) -> dict[str, Any]:
    return parse_cdl_text(read_text_file(path), source=str(path))


def parse_cdl_file(path: str | Path) -> dict[str, Any]:
    data = parse_cdl_data_file(path)
    return make_parser_envelope(
        parser_name="CdlParser",
        parser_version=CDL_PARSER_VERSION,
        file=str(path),
        abs_path=str(Path(path).resolve()),
        file_type="cdl",
        data=data,
    )


def diff_cdl_summary(old, new):
    os, ns = old.get("subckts", {}), new.get("subckts", {})
    changed = {}
    for s in sorted(set(os) & set(ns)):
        if os[s].get("pins") != ns[s].get("pins"):
            changed[s] = {"pins": {"old": os[s].get("pins"), "new": ns[s].get("pins")}}
    return {
        "schema_version": "1.0",
        "diff_type": "cdl_summary_diff",
        "subckt_changes": {
            "added": sorted(set(ns) - set(os)),
            "removed": sorted(set(os) - set(ns)),
            "changed": changed,
        },
    }


def diff_cdl_files(old_path, new_path):
    return diff_cdl_summary(parse_cdl_file(old_path)["data"], parse_cdl_file(new_path)["data"])


class CdlParser(BaseParser):
    parser_name = "CdlParser"
    parser_version = CDL_PARSER_VERSION
    parse_level = "L2"
    supported_file_types = ["cdl"]
    supported_extensions = [".cdl", ".cdl.gz", ".sp", ".spi", ".spice"]

    def parse(self, record, context):
        path = record_abs_path(record, context)
        return make_parser_envelope(
            parser_name=self.parser_name,
            parser_version=self.parser_version,
            file=str(get_field(record, "path", path)),
            abs_path=str(path),
            file_type=str(get_field(record, "file_type", "cdl")),
            compression=get_field(record, "compression", None),
            data=parse_cdl_data_file(path),
            schema_version=str(get_field(context, "schema_version", "1.0")),
        )
