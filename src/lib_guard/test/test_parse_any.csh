#!/bin/csh -f

# Usage:
#   ./test_parse_any.csh /path/to/file
#   ./test_parse_any.csh /path/to/file work/parser_debug/result.json

if ( $#argv < 1 ) then
    echo "Usage: $0 /path/to/file [out_json]"
    exit 1
endif

set TARGET_FILE = "$argv[1]"

if ( $#argv >= 2 ) then
    set OUT_JSON = "$argv[2]"
else
    set OUT_JSON = ""
endif

if ( ! -f "$TARGET_FILE" ) then
    echo "ERROR: file not found: $TARGET_FILE"
    exit 1
endif

# Make sure current source tree is used.
if ( $?PYTHONPATH ) then
    setenv PYTHONPATH `pwd`/src:$PYTHONPATH
else
    setenv PYTHONPATH `pwd`/src
endif

echo "PYTHONPATH  = $PYTHONPATH"
echo "TARGET_FILE = $TARGET_FILE"
echo "OUT_JSON    = $OUT_JSON"
echo ""

python - "$TARGET_FILE" "$OUT_JSON" << PY
from __future__ import annotations

from pathlib import Path
import importlib
import json
import sys
import time
import traceback
from typing import Any


target = Path(sys.argv[1])
out_json = Path(sys.argv[2]) if len(sys.argv) >= 3 and sys.argv[2] else None


def detect_file_type(path: Path) -> str:
    name = path.name.lower()

    # Composite gzip extensions first.
    if name.endswith(".lib.gz"):
        return "liberty"
    if name.endswith(".lef.gz") or name.endswith(".tlef.gz"):
        return "lef"
    if name.endswith((".v.gz", ".sv.gz", ".vg.gz", ".vp.gz")):
        return "verilog"
    if name.endswith(".cdl.gz"):
        return "cdl"
    if name.endswith(".sdc.gz"):
        return "sdc"
    if name.endswith(".upf.gz"):
        return "upf"
    if name.endswith(".cpf.gz"):
        return "cpf"
    if name.endswith((".spef.gz", ".sdf.gz")):
        return "spef"

    suffix = path.suffix.lower()

    if suffix in {".lef", ".tlef"}:
        return "lef"
    if suffix == ".lib":
        return "liberty"
    if suffix == ".db":
        return "db"

    if suffix in {".v", ".sv", ".vg", ".vp", ".vh", ".svh"}:
        return "verilog"

    if suffix in {".cdl", ".sp", ".spi", ".spice"}:
        return "cdl"

    if suffix == ".sdc":
        return "sdc"
    if suffix == ".upf":
        return "upf"
    if suffix == ".cpf":
        return "cpf"
    if suffix == ".spef":
        return "spef"

    if suffix in {".f", ".flist"}:
        return "filelist"

    if suffix in {".s1p", ".s2p", ".s4p", ".s6p", ".s8p", ".snp", ".pwl", ".ibs"}:
        return "package"

    if suffix in {".waiver", ".wvr"}:
        return "waiver"

    if suffix in {".md", ".txt", ".pdf", ".doc", ".docx", ".xls", ".xlsx"}:
        return "doc"

    return "unknown"


PARSER_CANDIDATES = {
    "lef": [
        ("lib_guard.scan.parsers.lef", ["parse_lef_file", "parse_lef"]),
    ],
    "liberty": [
        ("lib_guard.scan.parsers.liberty", ["parse_liberty_file", "parse_liberty", "parse_lib"]),
    ],
    "db": [
        ("lib_guard.scan.parsers.db", ["parse_db_file", "parse_db"]),
    ],
    "verilog": [
        ("lib_guard.scan.parsers.verilog", ["parse_verilog_file", "parse_verilog", "parse_sv"]),
    ],
    "cdl": [
        ("lib_guard.scan.parsers.cdl", ["parse_cdl_file", "parse_cdl", "parse_spice_file", "parse_spice"]),
    ],
    "sdc": [
        ("lib_guard.scan.parsers.sdc", ["parse_sdc_file", "parse_sdc"]),
    ],
    "upf": [
        ("lib_guard.scan.parsers.upf", ["parse_upf_file", "parse_upf"]),
    ],
    "cpf": [
        ("lib_guard.scan.parsers.cpf", ["parse_cpf_file", "parse_cpf"]),
    ],
    "spef": [
        ("lib_guard.scan.parsers.spef", ["parse_spef_file", "parse_spef"]),
    ],
    "filelist": [
        ("lib_guard.scan.parsers.filelist", ["parse_filelist_file", "parse_filelist", "parse_flist"]),
    ],
    "package": [
        ("lib_guard.scan.parsers.package", ["parse_package_file", "parse_package", "parse_touchstone", "parse_ibis_file", "parse_ibis"]),
    ],
    "waiver": [
        ("lib_guard.scan.parsers.waiver", ["parse_waiver_file", "parse_waiver"]),
    ],
}


def load_parser(file_type: str):
    errors = []

    for module_name, func_names in PARSER_CANDIDATES.get(file_type, []):
        try:
            module = importlib.import_module(module_name)
        except Exception as exc:
            errors.append(f"{module_name}: import failed: {exc}")
            continue

        for func_name in func_names:
            func = getattr(module, func_name, None)
            if callable(func):
                return module_name, func_name, func

        errors.append(f"{module_name}: no parser function found among {func_names}")

    raise RuntimeError(
        "No parser found for file_type=%s\\n%s"
        % (file_type, "\\n".join(errors))
    )


def unwrap_data(result: Any) -> Any:
    if isinstance(result, dict) and result.get("result_type") == "parser_result":
        return result["data"]
    return result


def as_list_or_dict_len(value: Any) -> int:
    if value is None:
        return 0
    if isinstance(value, dict):
        return len(value)
    if isinstance(value, list):
        return len(value)
    return 1


def first_items(value: Any, n: int = 10):
    if isinstance(value, dict):
        return list(value.items())[:n]
    if isinstance(value, list):
        return list(enumerate(value[:n]))
    return []


def get_name(obj: Any) -> str:
    if isinstance(obj, dict):
        return str(obj.get("name") or obj.get("macro_name") or obj.get("module") or obj.get("subckt") or "")
    return str(getattr(obj, "name", ""))


def get_collection(data: Any, names: list[str]):
    if not isinstance(data, dict):
        return None
    for name in names:
        if name in data:
            return data[name]
    return None


def print_preview(file_type: str, result: Any) -> None:
    data = unwrap_data(result)

    print("\\n== result envelope ==")
    if isinstance(result, dict):
        for k in ["schema_version", "result_type", "parser_name", "parser_version", "parser_schema_version", "file", "abs_path", "file_type", "compression", "status"]:
            if k in result:
                print(f"{k}: {result.get(k)}")

    print("\\n== stats ==")
    if isinstance(data, dict):
        print(json.dumps(data.get("stats", {}), indent=2, ensure_ascii=False))
    else:
        print("data is not dict:", type(data).__name__)
        return

    print("\\n== object preview ==")

    if file_type == "lef":
        macros = get_collection(data, ["macros"])
        print("macro_count:", as_list_or_dict_len(macros))
        for name, macro in first_items(macros, 10):
            macro_name = name if isinstance(macros, dict) else get_name(macro)
            pins = macro.get("pins", {}) if isinstance(macro, dict) else {}
            size = macro.get("size") if isinstance(macro, dict) else None
            klass = macro.get("class") if isinstance(macro, dict) else None
            print(f"  MACRO {macro_name} class={klass} size={size} pin_count={as_list_or_dict_len(pins)}")

    elif file_type == "liberty":
        libraries = get_collection(data, ["libraries", "libs"])
        cells = get_collection(data, ["cells"])
        print("library_count:", as_list_or_dict_len(libraries))
        print("top_cell_count:", as_list_or_dict_len(cells))

        if libraries:
            for _, lib in first_items(libraries, 5):
                lib_name = get_name(lib)
                lib_cells = lib.get("cells", {}) if isinstance(lib, dict) else {}
                print(f"  LIB {lib_name} cell_count={as_list_or_dict_len(lib_cells)}")

    elif file_type == "verilog":
        modules = get_collection(data, ["modules"])
        print("module_count:", as_list_or_dict_len(modules))
        for _, mod in first_items(modules, 20):
            mod_name = get_name(mod)
            ports = mod.get("ports", []) if isinstance(mod, dict) else []
            print(f"  MODULE {mod_name} port_count={as_list_or_dict_len(ports)}")

    elif file_type == "cdl":
        subckts = get_collection(data, ["subckts", "subcircuits"])
        print("subckt_count:", as_list_or_dict_len(subckts))
        for _, subckt in first_items(subckts, 20):
            subckt_name = get_name(subckt)
            pins = subckt.get("pins", []) if isinstance(subckt, dict) else []
            print(f"  SUBCKT {subckt_name} pin_count={as_list_or_dict_len(pins)}")

    elif file_type == "sdc":
        clocks = get_collection(data, ["clocks", "create_clocks"])
        generated = get_collection(data, ["generated_clocks"])
        constraints = get_collection(data, ["constraints", "commands"])
        print("clock_count:", as_list_or_dict_len(clocks))
        print("generated_clock_count:", as_list_or_dict_len(generated))
        print("constraint_count:", as_list_or_dict_len(constraints))

    elif file_type in {"upf", "cpf"}:
        domains = get_collection(data, ["power_domains", "domains"])
        supply_ports = get_collection(data, ["supply_ports"])
        supply_nets = get_collection(data, ["supply_nets"])
        isolation = get_collection(data, ["isolation", "isolations"])
        print("power_domain_count:", as_list_or_dict_len(domains))
        print("supply_port_count:", as_list_or_dict_len(supply_ports))
        print("supply_net_count:", as_list_or_dict_len(supply_nets))
        print("isolation_count:", as_list_or_dict_len(isolation))

    elif file_type == "spef":
        nets = get_collection(data, ["nets"])
        ports = get_collection(data, ["ports"])
        print("net_count:", as_list_or_dict_len(nets))
        print("port_count:", as_list_or_dict_len(ports))

    elif file_type == "filelist":
        files = get_collection(data, ["files", "entries"])
        includes = get_collection(data, ["includes", "include_dirs"])
        defines = get_collection(data, ["defines"])
        print("file_entry_count:", as_list_or_dict_len(files))
        print("include_count:", as_list_or_dict_len(includes))
        print("define_count:", as_list_or_dict_len(defines))

    elif file_type == "package":
        records = get_collection(data, ["records", "files", "signals", "ports"])
        print("package_record_count:", as_list_or_dict_len(records))

    elif file_type == "waiver":
        waivers = get_collection(data, ["waivers", "rules", "items"])
        print("waiver_count:", as_list_or_dict_len(waivers))

    elif file_type == "db":
        print(json.dumps(data, indent=2, ensure_ascii=False)[:2000])

    elif file_type == "doc":
        print("doc file: no deep parser. Use doc_extractor through scan summary.")

    else:
        print("unknown preview. top-level keys:", list(data.keys())[:50])


def main() -> int:
    print("== parser smoke test ==")
    print("file:", str(target))

    file_type = detect_file_type(target)
    print("detected_type:", file_type)

    if file_type == "unknown":
        print("ERROR: unknown file type. Please check extension.")
        return 2

    if file_type == "doc":
        print_preview(file_type, {})
        return 0

    module_name, func_name, func = load_parser(file_type)
    print("parser_module:", module_name)
    print("parser_func:", func_name)

    t0 = time.time()
    result = func(str(target))
    elapsed = time.time() - t0

    print("elapsed_seconds:", round(elapsed, 3))

    print_preview(file_type, result)

    if out_json is not None:
        out_json.parent.mkdir(parents=True, exist_ok=True)
        out_json.write_text(
            json.dumps(result, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        print("\\nwrote:", str(out_json))

    return 0


try:
    raise SystemExit(main())
except Exception as exc:
    print("\\nERROR:", type(exc).__name__, exc)
    traceback.print_exc()
    raise SystemExit(1)
PY
