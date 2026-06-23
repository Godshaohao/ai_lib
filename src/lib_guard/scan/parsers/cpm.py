from __future__ import annotations

from pathlib import Path
from typing import Any

from .base import BaseParser, make_parser_envelope, record_abs_path, get_field, read_text_file

CPM_PARSER_VERSION = "2.0"


def parse_cpm_text(text: str, source: str = "") -> dict[str, Any]:
    components: dict[str, Any] = {}
    pins: list[dict[str, Any]] = []
    records: list[dict[str, Any]] = []
    current_component = ""
    for line_no, raw in enumerate(text.splitlines(), start=1):
        line = raw.split("#", 1)[0].split("//", 1)[0].strip()
        if not line:
            continue
        parts = line.replace(",", " ").split()
        keyword = parts[0].lower() if parts else ""
        records.append({"keyword": keyword, "line": line_no, "raw": line})
        if keyword in {"component", ".component"} and len(parts) >= 2:
            current_component = parts[1]
            components.setdefault(current_component, {"name": current_component, "line": line_no, "pins": []})
        elif keyword in {"pin", ".pin"} and len(parts) >= 2:
            item = {"name": parts[1], "direction": parts[2] if len(parts) >= 3 else "", "component": current_component, "line": line_no, "raw": line}
            pins.append(item)
            if current_component:
                components.setdefault(current_component, {"name": current_component, "line": None, "pins": []})["pins"].append(item)
    return {"source": source, "records": records, "components": components, "pins": pins, "stats": {"component_count": len(components), "pin_count": len(pins), "record_count": len(records)}}


def parse_cpm_data_file(path: str | Path) -> dict[str, Any]:
    return parse_cpm_text(read_text_file(path), source=str(path))


def parse_cpm_file(path: str | Path) -> dict[str, Any]:
    data = parse_cpm_data_file(path)
    return make_parser_envelope(parser_name="CpmParser", parser_version=CPM_PARSER_VERSION, file=str(path), abs_path=str(Path(path).resolve()), file_type="cpm", data=data)


class CpmParser(BaseParser):
    parser_name = "CpmParser"
    parser_version = CPM_PARSER_VERSION
    parse_level = "L2"
    supported_file_types = ["cpm"]
    supported_extensions = [".cpm"]

    def parse(self, record: Any, context: Any) -> dict[str, Any]:
        path = record_abs_path(record, context)
        return make_parser_envelope(parser_name=self.parser_name, parser_version=self.parser_version, file=str(get_field(record, "path", path)), abs_path=str(path), file_type=str(get_field(record, "file_type", "cpm")), compression=get_field(record, "compression", None), data=parse_cpm_data_file(path), schema_version=str(get_field(context, "schema_version", "1.0")))
