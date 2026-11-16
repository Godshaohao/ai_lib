from __future__ import annotations

import gzip
from pathlib import Path
from typing import Any, Iterable
import re

from .base import BaseParser, make_parser_envelope, record_abs_path, get_field

LEF_PARSER_VERSION = "2.5"
# A complete geometry payload is useful for small abstracts.  On a large
# technology LEF it expands every RECT/OBS into JSON and can exceed the source
# file by several times, without changing the review-level LEF summary.
LEF_FULL_GEOMETRY_MAX_BYTES = 8 * 1024 * 1024

_RE_VERSION = re.compile(r"^\s*VERSION\s+(?P<version>\S+)\s*;", re.I)
_RE_BUSBITCHARS = re.compile(r'^\s*BUSBITCHARS\s+"(?P<chars>[^"]+)"\s*;', re.I)
_RE_DIVIDERCHAR = re.compile(r'^\s*DIVIDERCHAR\s+"(?P<char>[^"]+)"\s*;', re.I)
_RE_UNITS = re.compile(r"^\s*DATABASE\s+MICRONS\s+(?P<dbu>\d+)\s*;", re.I)
_RE_MACRO_START = re.compile(r"^\s*MACRO\s+(?P<name>\S+)", re.I)
_RE_END = re.compile(r"^\s*END(?:\s+(?P<name>\S+))?", re.I)
_RE_CLASS = re.compile(r"^\s*CLASS\s+(?P<class>.+?)\s*;", re.I)
_RE_SIZE = re.compile(r"^\s*SIZE\s+(?P<x>[-\d.]+)\s+BY\s+(?P<y>[-\d.]+)\s*;", re.I)
_RE_ORIGIN = re.compile(r"^\s*ORIGIN\s+(?P<x>[-\d.]+)\s+(?P<y>[-\d.]+)\s*;", re.I)
_RE_SYMMETRY = re.compile(r"^\s*SYMMETRY\s+(?P<sym>.+?)\s*;", re.I)
_RE_SITE = re.compile(r"^\s*SITE\s+(?P<site>\S+)\s*;", re.I)
_RE_PIN_START = re.compile(r"^\s*PIN\s+(?P<name>\S+)", re.I)
_RE_PORT = re.compile(r"^\s*PORT\b", re.I)
_RE_DIRECTION = re.compile(r"^\s*DIRECTION\s+(?P<direction>\S+)\s*;", re.I)
_RE_USE = re.compile(r"^\s*USE\s+(?P<use>\S+)\s*;", re.I)
_RE_SHAPE = re.compile(r"^\s*SHAPE\s+(?P<shape>\S+)\s*;", re.I)
_RE_LAYER_START = re.compile(r"^\s*LAYER\s+(?P<layer>\S+)\s*;?\s*$", re.I)
_RE_LAYER_REF = re.compile(r"^\s*LAYER\s+(?P<layer>\S+)\s*;", re.I)
_RE_LAYER_TYPE = re.compile(r"^\s*TYPE\s+(?P<type>\S+)\s*;", re.I)
_RE_LAYER_DIRECTION = re.compile(r"^\s*DIRECTION\s+(?P<direction>\S+)\s*;", re.I)
_RE_LAYER_WIDTH = re.compile(r"^\s*WIDTH\s+(?P<width>[-\d.]+)\s*;", re.I)
_RE_LAYER_PITCH = re.compile(r"^\s*PITCH\s+(?P<pitch>.+?)\s*;", re.I)
_RE_LAYER_SPACING = re.compile(r"^\s*SPACING\s+(?P<spacing>[-\d.]+)\s*;", re.I)
_RE_RECT = re.compile(r"^\s*RECT\s+(?P<x1>[-\d.]+)\s+(?P<y1>[-\d.]+)\s+(?P<x2>[-\d.]+)\s+(?P<y2>[-\d.]+)\s*;", re.I)
_RE_OBS = re.compile(r"^\s*OBS\b", re.I)
_RE_ANTENNA = re.compile(r"^\s*(?P<key>ANTENNA\w+)\s+(?P<value>.+?)\s*;", re.I)


def _float(value: str) -> float:
    return float(value)


def _numeric_values(text: str) -> float | list[float] | str:
    parts = text.split()
    try:
        values = [float(part) for part in parts]
    except Exception:
        return text
    return values[0] if len(values) == 1 else values


def _lef_statements(lines: Iterable[str]):
    """Split scalar statements, keeping quoted LEF58 properties opaque."""
    buffer = []
    quoted = escaped = False
    start = 1
    for line_no, raw in enumerate(lines, start=1):
        if not buffer:
            start = line_no
        for char in raw.rstrip('\r\n'):
            if not quoted and char == '#':
                break
            buffer.append(char)
            if quoted and escaped:
                escaped = False
            elif quoted and char == '\\':
                escaped = True
            elif char == '"':
                quoted = not quoted
            elif not quoted and char == ';':
                yield start, ''.join(buffer).strip(), True
                buffer = []
                start = line_no
        if quoted:
            buffer.append('\n')
            escaped = False
        else:
            if ''.join(buffer).strip():
                yield start, ''.join(buffer).strip(), True
            buffer = []
    if buffer:
        yield start, ''.join(buffer).strip(), False


def _new_tech_layer(name: str, line_no: int) -> dict[str, Any]:
    return {
        "name": name,
        "line_start": line_no,
        "line_end": None,
        "type": None,
        "direction": None,
        "pitch": None,
        "width": None,
        "spacing": None,
    }


def _parse_tech_layer_attr(layer: dict[str, Any], line: str) -> bool:
    for regex, key, convert in [
        (_RE_LAYER_TYPE, "type", str.upper),
        (_RE_LAYER_DIRECTION, "direction", str.upper),
        (_RE_LAYER_WIDTH, "width", _float),
        (_RE_LAYER_SPACING, "spacing", _float),
        (_RE_LAYER_PITCH, "pitch", _numeric_values),
    ]:
        m = regex.match(line)
        if m:
            layer[key] = convert(next(iter(m.groupdict().values())))
            return True
    return False


def _finalize_stats(result: dict[str, Any]) -> None:
    used_layers: set[str] = set()
    pin_rect_count = 0
    pin_layer_count = 0
    obs_rect_count = 0
    total_area = 0.0

    counts_only = result.get("geometry_detail") == "counts_only"
    for macro in result["macros"].values():
        pins = macro.get("pins") or {}
        obs = macro.get("obs") or []
        macro["pin_count"] = len(pins)
        macro["obs_rect_count"] = int(macro.pop("_obs_rect_count", len(obs))) if counts_only else len(obs)
        size = macro.get("size")
        if isinstance(size, dict) and size.get("x") is not None and size.get("y") is not None:
            macro["area"] = float(size["x"]) * float(size["y"])
            total_area += macro["area"]
        for pin in pins.values():
            layers = [str(layer) for layer in (pin.get("layers") or []) if str(layer)]
            rects = pin.get("rects") or []
            pin["layer_count"] = len(layers)
            pin["rect_count"] = int(pin.pop("_rect_count", len(rects))) if counts_only else len(rects)
            used_layers.update(layers)
            pin_layer_count += len(layers)
            pin_rect_count += pin["rect_count"]
        for rect in obs:
            layer = rect.get("layer")
            if layer:
                used_layers.add(str(layer))
        used_layers.update(str(layer) for layer in macro.pop("_obs_layers", []) if str(layer))
        obs_rect_count += macro["obs_rect_count"]

    result["used_layers"] = sorted(used_layers)
    result["stats"] = {
        "macro_count": len(result["macros"]),
        "pin_count": sum(len(macro.get("pins") or {}) for macro in result["macros"].values()),
        "layer_count": len(result["layers"]) or len(used_layers),
        "used_layer_count": len(used_layers),
        "pin_layer_count": pin_layer_count,
        "pin_rect_count": pin_rect_count,
        "obs_rect_count": obs_rect_count,
        "macro_area_total": total_area,
    }


def _parse_lef_lines(
    lines: Iterable[str],
    *,
    source: str = "",
    geometry_detail: str = "full",
    source_size_bytes: int | None = None,
) -> dict[str, Any]:
    retain_geometry = geometry_detail == "full"
    result: dict[str, Any] = {
        "source": source,
        "source_size_bytes": source_size_bytes,
        "geometry_detail": geometry_detail,
        "geometry_omitted": not retain_geometry,
        "lef_version": None,
        "busbitchars": None,
        "dividerchar": None,
        "database_microns": None,
        "coordinate_units": "um",
        "layers": {},
        "layer_order": [],
        "macros": {},
        "macro_order": [],
        "used_layers": [],
        "stats": {
            "macro_count": 0,
            "pin_count": 0,
            "layer_count": 0,
            "used_layer_count": 0,
            "pin_layer_count": 0,
            "pin_rect_count": 0,
            "obs_rect_count": 0,
        },
    }
    current_macro: dict[str, Any] | None = None
    current_pin: dict[str, Any] | None = None
    current_tech_layer: dict[str, Any] | None = None
    current_layer_name: str | None = None
    in_pin_port = False
    in_obs = False
    in_properties = False
    auxiliary_block = None
    limitations: list[dict[str, Any]] = []
    duplicate_pin = False
    malformed = False
    unsupported_pin_geometry = False
    unsupported_obs_geometry = False
    limitation_count = 0

    def note_limitation(record):
        nonlocal limitation_count
        limitation_count += 1
        if len(limitations) < 100:
            limitations.append(record)

    for line_no, line, valid in _lef_statements(lines):
        if not line:
            continue
        if not valid:
            malformed = True
            note_limitation({'line': line_no, 'reason': 'unterminated_quoted_string'})
            continue
        if _RE_MACRO_START.match(line) and (current_macro is not None or auxiliary_block is not None or current_tech_layer is not None):
            malformed = True
            note_limitation({'line': line_no, 'reason': 'nested_macro_before_block_end'})
            continue
        if auxiliary_block is not None:
            end = _RE_END.match(line)
            if end and end.group('name') == auxiliary_block:
                auxiliary_block = None
            continue
        if in_properties:
            if re.match(r'^END\s+PROPERTYDEFINITIONS\b', line, re.I):
                in_properties = False
            continue
        if current_macro is None and re.match(r'^PROPERTYDEFINITIONS\b', line, re.I):
            in_properties = True
            continue
        if (in_pin_port or in_obs) and re.match(r'^(POLYGON|PATH|VIA|RECT\s+(MASK|ITERATE)|LAYER\s+\S+\s+(EXCEPTPGNET|SPACING|DESIGNRULEWIDTH))\b', line, re.I):
            unsupported_pin_geometry |= in_pin_port
            unsupported_obs_geometry |= in_obs
            note_limitation({'line': line_no, 'reason': 'unsupported_geometry', 'statement': line.split()[0]})

        if current_tech_layer is not None:
            m_end = _RE_END.match(line)
            if m_end and (m_end.group("name") == current_tech_layer["name"]):
                current_tech_layer["line_end"] = line_no
                current_tech_layer = None
                continue
            if _parse_tech_layer_attr(current_tech_layer, line):
                continue
            continue

        if current_macro is None:
            auxiliary = re.match(r'^(VIA|VIARULE|SITE|NONDEFAULTRULE)\s+(\S+)', line, re.I)
            if auxiliary:
                auxiliary_block = auxiliary.group(2)
                continue
            matched_header = False
            for regex, key, conv in [
                (_RE_VERSION, "lef_version", str),
                (_RE_BUSBITCHARS, "busbitchars", str),
                (_RE_DIVIDERCHAR, "dividerchar", str),
            ]:
                m = regex.match(line)
                if m:
                    result[key] = conv(next(iter(m.groupdict().values())))
                    matched_header = True
                    break
            if matched_header:
                continue
            m = _RE_UNITS.match(line)
            if m:
                result["database_microns"] = int(m.group("dbu"))
                continue
            m = _RE_LAYER_START.match(line)
            if m:
                name = m.group("layer")
                current_tech_layer = _new_tech_layer(name, line_no)
                result["layers"][name] = current_tech_layer
                result["layer_order"].append(name)
                continue
            m = _RE_MACRO_START.match(line)
            if m:
                name = m.group("name")
                current_macro = {
                    "name": name,
                    "line_start": line_no,
                    "line_end": None,
                    "class": None,
                    "origin": None,
                    "size": None,
                    "area": None,
                    "symmetry": [],
                    "site": None,
                    "pins": {},
                    "pin_order": [],
                    "obs": [],
                }
                result["macros"][name] = current_macro
                result["macro_order"].append(name)
                continue
            continue

        if current_pin is not None:
            if _RE_PIN_START.match(line) or _RE_MACRO_START.match(line):
                malformed = True
                note_limitation({'line': line_no, 'reason': 'nested_object_before_pin_end'})
                continue
            if _RE_PORT.match(line):
                if in_pin_port:
                    malformed = True
                in_pin_port = True
                current_pin['port_count'] += 1
                current_layer_name = None
                continue
            m_end = _RE_END.match(line)
            if m_end:
                end_name = m_end.group("name")
                if end_name == current_pin["name"] or (end_name is None and not in_pin_port):
                    if in_pin_port or end_name is None:
                        malformed = True
                        note_limitation({'line': line_no, 'reason': 'unclosed_port_or_unnamed_pin_end'})
                    current_pin["line_end"] = line_no
                    current_pin = None
                    current_layer_name = None
                    in_pin_port = False
                    continue
                if end_name is None and in_pin_port:
                    in_pin_port = False
                    current_layer_name = None
                    continue
                malformed = True
                note_limitation({'line': line_no, 'reason': 'mismatched_pin_end'})
                continue
            for regex, key in [(_RE_DIRECTION, "direction"), (_RE_USE, "use"), (_RE_SHAPE, "shape")]:
                m = regex.match(line)
                if m:
                    current_pin[key] = next(iter(m.groupdict().values())).upper()
                    break
            else:
                m = _RE_LAYER_REF.match(line)
                if m:
                    current_layer_name = m.group("layer")
                    if current_layer_name not in current_pin["layers"]:
                        current_pin["layers"].append(current_layer_name)
                    continue
                m = _RE_RECT.match(line)
                if m:
                    if retain_geometry:
                        current_pin["rects"].append(
                            {"port_index": current_pin['port_count'] - 1, "layer": current_layer_name, **{k: float(v) for k, v in m.groupdict().items()}}
                        )
                    else:
                        current_pin["_rect_count"] = int(current_pin.get("_rect_count", 0)) + 1
                    continue
                m = _RE_ANTENNA.match(line)
                if m:
                    current_pin.setdefault("antenna", {})[m.group("key").upper()] = _numeric_values(m.group("value"))
                    continue
                unsupported_pin_geometry = True
                note_limitation({'line': line_no, 'reason': 'unsupported_pin_statement', 'statement': line.split()[0]})
            continue

        if in_obs:
            m_end = _RE_END.match(line)
            if m_end and (m_end.group("name") is None or str(m_end.group("name")).upper() == "OBS"):
                in_obs = False
                current_layer_name = None
                continue
            m = _RE_LAYER_REF.match(line)
            if m:
                current_layer_name = m.group("layer")
                continue
            m = _RE_RECT.match(line)
            if m:
                if retain_geometry:
                    current_macro["obs"].append(
                        {"layer": current_layer_name, **{k: float(v) for k, v in m.groupdict().items()}}
                    )
                else:
                    current_macro["_obs_rect_count"] = int(current_macro.get("_obs_rect_count", 0)) + 1
                    if current_layer_name:
                        current_macro.setdefault("_obs_layers", []).append(current_layer_name)
                continue
            unsupported_obs_geometry = True
            note_limitation({'line': line_no, 'reason': 'unsupported_obs_statement', 'statement': line.split()[0]})
            continue

        m_end = _RE_END.match(line)
        if m_end and m_end.group("name") == current_macro["name"]:
            current_macro["line_end"] = line_no
            current_macro = None
            continue
        m = _RE_CLASS.match(line)
        if m:
            current_macro["class"] = m.group("class").upper()
            continue
        m = _RE_SIZE.match(line)
        if m:
            current_macro["size"] = {"x": float(m.group("x")), "y": float(m.group("y"))}
            continue
        m = _RE_ORIGIN.match(line)
        if m:
            current_macro["origin"] = {"x": float(m.group("x")), "y": float(m.group("y"))}
            continue
        m = _RE_SYMMETRY.match(line)
        if m:
            current_macro["symmetry"] = m.group("sym").upper().split()
            continue
        m = _RE_SITE.match(line)
        if m:
            current_macro["site"] = m.group("site")
            continue
        m = _RE_PIN_START.match(line)
        if m:
            pname = m.group("name")
            duplicate_pin |= pname in current_macro['pins']
            current_pin = {
                "name": pname,
                "line_start": line_no,
                "line_end": None,
                "direction": None,
                "use": None,
                "shape": None,
                "layers": [],
                "layer_count": 0,
                "rects": [],
                "rect_count": 0,
                "port_count": 0,
            }
            current_macro["pins"][pname] = current_pin
            current_macro["pin_order"].append(pname)
            current_layer_name = None
            in_pin_port = False
            continue
        if _RE_OBS.match(line):
            in_obs = True
            current_layer_name = None
            continue

    complete = not (malformed or current_macro is not None or current_pin is not None or in_obs or in_properties
                    or current_tech_layer is not None or auxiliary_block is not None)
    unique = len(result['macro_order']) == len(set(result['macro_order']))
    interface_complete = complete and unique and not duplicate_pin
    result['parse_limitations'] = limitations
    if not complete:
        note_limitation({'reason': 'incomplete_or_unsupported_structure'})
    if not unique or duplicate_pin:
        note_limitation({'reason': 'duplicate_object_name'})
    result['parse_limitation_count'] = limitation_count
    result['semantic_coverage'] = {
        'schema_version': 'semantic_parser_coverage.v1', 'validated': True,
        'basis': 'LefParser 2.5 quoted statement boundaries and nested-block validation; RECT-only geometry with explicit PORT groups',
        'macro_set': 'PRESENT' if complete and unique else 'NOT_EXTRACTED',
        'port_set': 'PRESENT' if interface_complete else 'NOT_EXTRACTED',
        'pg_port_set': 'PRESENT' if interface_complete else 'NOT_EXTRACTED',
        'pin_layers': 'PRESENT' if interface_complete and not unsupported_pin_geometry else 'NOT_EXTRACTED',
        'pin_geometry': 'PRESENT' if interface_complete and retain_geometry and not unsupported_pin_geometry else 'NOT_EXTRACTED',
        'obs_geometry': 'PRESENT' if complete and unique and retain_geometry and not unsupported_obs_geometry else 'NOT_EXTRACTED',
    }
    _finalize_stats(result)
    return result


def parse_lef_text(text: str, source: str = "") -> dict[str, Any]:
    return _parse_lef_lines(text.splitlines(), source=source)


def parse_lef_data_file(
    path: str | Path,
    *,
    full_geometry_max_bytes: int = LEF_FULL_GEOMETRY_MAX_BYTES,
) -> dict[str, Any]:
    source = Path(path)
    source_size_bytes = source.stat().st_size
    geometry_detail = "full" if source_size_bytes <= full_geometry_max_bytes else "counts_only"
    opener = gzip.open if source.name.lower().endswith(".gz") else open
    with opener(source, "rt", encoding="utf-8", errors="ignore") as handle:
        return _parse_lef_lines(
            handle,
            source=str(source),
            geometry_detail=geometry_detail,
            source_size_bytes=source_size_bytes,
        )


def parse_lef_file(path: str | Path) -> dict[str, Any]:
    data = parse_lef_data_file(path)
    return make_parser_envelope(
        parser_name="LefParser",
        parser_version=LEF_PARSER_VERSION,
        file=str(path),
        abs_path=str(Path(path).resolve()),
        file_type="lef",
        data=data,
    )


def _lef_public_view(summary: dict[str, Any]) -> dict[str, Any]:
    return {
        macro_name: {
            "size": macro.get("size"),
            "class": macro.get("class"),
            "site": macro.get("site"),
            "pins": {
                p: {"direction": v.get("direction"), "use": v.get("use"), "layers": sorted(v.get("layers") or [])}
                for p, v in (macro.get("pins") or {}).items()
            },
        }
        for macro_name, macro in (summary.get("macros") or {}).items()
    }


def diff_lef_summary(old: dict[str, Any], new: dict[str, Any]) -> dict[str, Any]:
    oldv, newv = _lef_public_view(old), _lef_public_view(new)
    added = sorted(set(newv) - set(oldv))
    removed = sorted(set(oldv) - set(newv))
    changed = {}
    for name in sorted(set(oldv) & set(newv)):
        ch = {}
        for k in ["size", "class", "site"]:
            if oldv[name].get(k) != newv[name].get(k):
                ch[k] = {"old": oldv[name].get(k), "new": newv[name].get(k)}
        op, np = oldv[name]["pins"], newv[name]["pins"]
        pin_ch = {}
        for p in sorted(set(op) & set(np)):
            diff = {
                k: {"old": op[p].get(k), "new": np[p].get(k)}
                for k in ["direction", "use", "layers"]
                if op[p].get(k) != np[p].get(k)
            }
            if diff:
                pin_ch[p] = diff
        if set(np) - set(op) or set(op) - set(np) or pin_ch:
            ch["pins"] = {"added": sorted(set(np) - set(op)), "removed": sorted(set(op) - set(np)), "changed": pin_ch}
        if ch:
            changed[name] = ch
    return {
        "schema_version": "1.0",
        "diff_type": "lef_summary_diff",
        "macro_changes": {"added": added, "removed": removed, "changed": changed},
        "stats": {
            "added_macro_count": len(added),
            "removed_macro_count": len(removed),
            "changed_macro_count": len(changed),
        },
    }


def diff_lef_files(old_path: str | Path, new_path: str | Path) -> dict[str, Any]:
    return diff_lef_summary(parse_lef_file(old_path)["data"], parse_lef_file(new_path)["data"])


class LefParser(BaseParser):
    parser_name = "LefParser"
    parser_version = LEF_PARSER_VERSION
    parse_level = "L2"
    supported_file_types = ["lef"]
    supported_extensions = [".lef", ".lef.gz", ".tlef", ".tlef.gz"]

    def parse(self, record: Any, context: Any) -> dict[str, Any]:
        path = record_abs_path(record, context)
        data = parse_lef_data_file(path)
        return make_parser_envelope(
            parser_name=self.parser_name,
            parser_version=self.parser_version,
            file=str(get_field(record, "path", path)),
            abs_path=str(path),
            file_type=str(get_field(record, "file_type", "lef")),
            compression=get_field(record, "compression", None),
            data=data,
            schema_version=str(get_field(context, "schema_version", "1.0")),
        )
