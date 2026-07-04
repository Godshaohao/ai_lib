from __future__ import annotations

from typing import Any


FILE_TYPE_ALIASES = {
    "": "unknown",
    "-": "unknown",
    "lib": "liberty",
    "spi": "spice",
    "v": "verilog",
    "sv": "systemverilog",
    "md": "doc",
    "txt": "doc",
    "readme": "doc",
}

RAW_TYPE_TO_VIEW = {
    "liberty": "timing_lib",
    "verilog": "rtl_model",
    "systemverilog": "rtl_model",
    "vhdl": "rtl_model",
    "lef": "physical_abstract",
    "gds": "layout",
    "oas": "layout",
    "sdc": "constraint",
    "upf": "power_intent",
    "cpf": "power_intent",
    "spef": "parasitic_compiled",
    "db": "parasitic_compiled",
    "ndm": "parasitic_compiled",
    "milkyway": "parasitic_compiled",
    "sdf": "parasitic_compiled",
    "cdl": "netlist",
    "spice": "netlist",
    "sp": "netlist",
    "flow_config": "tech_flow_config",
    "tech_config": "tech_flow_config",
    "cfg": "tech_flow_config",
    "tcl": "tech_flow_config",
    "lydrc": "tech_flow_config",
    "doc": "doc_evidence",
    "package": "doc_evidence",
    "waiver": "waiver",
    "unknown": "unknown",
}

VIEW_LABELS = {
    "timing_lib": "Liberty / Timing",
    "rtl_model": "RTL model",
    "physical_abstract": "LEF / Physical abstract",
    "layout": "GDS/OAS / Layout",
    "constraint": "SDC / Constraint",
    "power_intent": "UPF/CPF / Power intent",
    "parasitic_compiled": "SPEF/DB/NDM / Parasitic & compiled",
    "netlist": "CDL/SPICE / Netlist",
    "tech_flow_config": "Tech/Flow config",
    "doc_evidence": "Doc / Release evidence",
    "waiver": "Waiver / Signoff evidence",
    "unknown": "Unknown / 待分类",
    "other": "Other / Evidence",
}

VIEW_ORDER = [
    "timing_lib",
    "rtl_model",
    "physical_abstract",
    "layout",
    "constraint",
    "power_intent",
    "parasitic_compiled",
    "netlist",
    "tech_flow_config",
    "doc_evidence",
    "waiver",
    "unknown",
    "other",
]

USAGE_AREAS = {
    "Timing / STA": {"timing_lib", "parasitic_compiled"},
    "Physical / PD": {"physical_abstract", "layout", "tech_flow_config"},
    "RTL / Integration": {"rtl_model"},
    "Constraint / Intent": {"constraint", "power_intent"},
    "Netlist / LVS": {"netlist"},
    "Evidence / Waiver": {"waiver", "doc_evidence", "unknown", "other"},
}

RELEASE_VIEW_DIR_ALIASES = {
    "rtl": "RTL",
    "verilog": "RTL",
    "systemverilog": "RTL",
    "lef": "LEF",
    "lib": "LIB",
    "liberty": "LIB",
    "db": "DB",
    "gds": "GDS",
    "oas": "OAS",
    "cdl": "CDL",
    "spice": "CDL",
    "sp": "CDL",
    "sdc": "SDC",
    "upf": "UPF",
    "cpf": "CPF",
    "spef": "SPEF",
    "sdf": "SDF",
    "doc": "DOC",
    "docs": "DOC",
    "md": "DOC",
    "txt": "DOC",
    "package": "DOC",
    "waiver": "WAIVER",
    "flow": "FLOW",
    "flow_config": "FLOW",
    "tech": "TECH",
    "tech_config": "TECH",
}

PACKAGE_VIEW_ALIASES = {
    "verilog": "rtl",
    "systemverilog": "rtl",
    "vhdl": "rtl",
    "lef": "lef",
    "liberty": "lib",
    "db": "db",
    "gds": "gds",
    "oas": "oas",
    "cdl": "cdl",
    "spice": "cdl",
    "sp": "cdl",
    "sdc": "sdc",
    "upf": "upf",
    "cpf": "cpf",
    "spef": "spef",
    "sdf": "sdf",
    "doc": "doc",
    "package": "doc",
    "waiver": "waiver",
    "flow_config": "flow",
    "tech_config": "tech",
    "cfg": "tech",
    "tcl": "tech",
    "lydrc": "tech",
}


def canonical_file_type(value: Any) -> str:
    text = str(value or "unknown").strip().lower()
    return FILE_TYPE_ALIASES.get(text, text or "unknown")


def canonical_view_type(file_type: Any) -> str:
    return RAW_TYPE_TO_VIEW.get(canonical_file_type(file_type), "other")


def view_label(view_type: Any) -> str:
    key = str(view_type or "unknown").strip().lower()
    return VIEW_LABELS.get(key, key or "unknown")


def view_sort_key(view_type: Any) -> tuple[int, str]:
    key = str(view_type or "unknown").strip().lower()
    return (VIEW_ORDER.index(key) if key in VIEW_ORDER else 999, key)


def usage_area_for_view(view_type: Any) -> str:
    key = str(view_type or "unknown").strip().lower()
    for area, view_types in USAGE_AREAS.items():
        if key in view_types:
            return area
    return "Other / Evidence"


def release_view_dir(value: Any) -> str:
    key = canonical_file_type(value)
    return RELEASE_VIEW_DIR_ALIASES.get(key, str(value or "UNKNOWN").strip().upper() or "UNKNOWN")


def package_view_type(value: Any) -> str:
    key = canonical_file_type(value)
    return PACKAGE_VIEW_ALIASES.get(key, key)
