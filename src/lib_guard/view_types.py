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
    "timing_lib": "Liberty / 时序",
    "rtl_model": "RTL 模型",
    "physical_abstract": "LEF / 物理抽象",
    "layout": "GDS/OAS / 版图",
    "constraint": "SDC / 约束",
    "power_intent": "UPF/CPF / 电源意图",
    "parasitic_compiled": "SPEF/DB/NDM / 寄生与编译库",
    "netlist": "CDL/SPICE / 网表",
    "tech_flow_config": "工艺与流程配置",
    "doc_evidence": "文档与发布证据",
    "waiver": "豁免与签核证据",
    "unknown": "Unknown / 待分类",
    "other": "其他 / 证据",
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
    "时序分析 / STA": {"timing_lib", "parasitic_compiled"},
    "物理实现 / PD": {"physical_abstract", "layout", "tech_flow_config"},
    "RTL 集成": {"rtl_model"},
    "约束与意图": {"constraint", "power_intent"},
    "网表与 LVS": {"netlist"},
    "证据与豁免": {"waiver", "doc_evidence", "unknown", "other"},
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
    return "其他 / 证据"


def release_view_dir(value: Any) -> str:
    key = canonical_file_type(value)
    return RELEASE_VIEW_DIR_ALIASES.get(key, str(value or "UNKNOWN").strip().upper() or "UNKNOWN")


def package_view_type(value: Any) -> str:
    key = canonical_file_type(value)
    return PACKAGE_VIEW_ALIASES.get(key, key)
