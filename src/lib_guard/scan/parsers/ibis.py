from __future__ import annotations

from pathlib import Path
from typing import Any
import re

from .base import BaseParser, make_parser_envelope, record_abs_path, get_field, read_text_file

IBIS_PARSER_VERSION = "2.0"
_SECTION_RE = re.compile(r"^\s*\[([^\]]+)\]\s*(.*)$")


def parse_ibis_text(text: str, source: str = "") -> dict[str, Any]:
    components: dict[str, Any] = {}
    models: dict[str, Any] = {}
    pins: list[dict[str, Any]] = []
    sections: list[dict[str, Any]] = []
    current_section = ""
    current_component = ""
    current_model = ""
    version = None

    for line_no, raw in enumerate(text.splitlines(), start=1):
        line = raw.split("|", 1)[0].strip()
        if not line:
            continue
        match = _SECTION_RE.match(line)
        if match:
            current_section = match.group(1).strip()
            value = match.group(2).strip()
            sections.append({"name": current_section, "value": value, "line": line_no})
            low = current_section.lower()
            if low == "ibis ver":
                version = value
            elif low == "component":
                current_component = value
                components.setdefault(value, {"name": value, "line": line_no, "pins": []})
            elif low == "model":
                current_model = value
                models.setdefault(value, {"name": value, "line": line_no, "attrs": {}})
            continue

        if current_section.lower() == "pin":
            parts = line.split()
            if len(parts) >= 3:
                item = {"pin": parts[0], "signal": parts[1], "model": parts[2], "component": current_component, "line": line_no, "raw": line}
                pins.append(item)
                if current_component:
                    components.setdefault(current_component, {"name": current_component, "line": None, "pins": []})["pins"].append(item)
        elif current_section.lower() == "model" and current_model:
            parts = line.split(None, 1)
            if len(parts) == 2:
                models[current_model]["attrs"][parts[0]] = parts[1]

    return {
        "source": source,
        "ibis_version": version,
        "sections": sections,
        "components": components,
        "pins": pins,
        "models": models,
        "stats": {"component_count": len(components), "pin_count": len(pins), "model_count": len(models)},
    }


def parse_ibis_data_file(path: str | Path) -> dict[str, Any]:
    return parse_ibis_text(read_text_file(path), source=str(path))


def parse_ibis_file(path: str | Path) -> dict[str, Any]:
    data = parse_ibis_data_file(path)
    return make_parser_envelope(parser_name="IbisParser", parser_version=IBIS_PARSER_VERSION, file=str(path), abs_path=str(Path(path).resolve()), file_type="ibis", data=data)


class IbisParser(BaseParser):
    parser_name = "IbisParser"
    parser_version = IBIS_PARSER_VERSION
    parse_level = "L2"
    supported_file_types = ["ibis"]
    supported_extensions = [".ibs", ".ibis"]

    def parse(self, record: Any, context: Any) -> dict[str, Any]:
        path = record_abs_path(record, context)
        return make_parser_envelope(parser_name=self.parser_name, parser_version=self.parser_version, file=str(get_field(record, "path", path)), abs_path=str(path), file_type=str(get_field(record, "file_type", "ibis")), compression=get_field(record, "compression", None), data=parse_ibis_data_file(path), schema_version=str(get_field(context, "schema_version", "1.0")))
