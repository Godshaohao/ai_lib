from __future__ import annotations

import unittest
import gzip
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from lib_guard.macro_index import build_macro_index, build_macro_index_from_filemap, build_parser_facts


def selected_file(view, path, version, *, corner=None):
    return {
        "view": view,
        "relative_path": path,
        "identity_path": f"{view}/{path}",
        "source_path": f"/raw/{version}/{path}",
        "source_version": version,
        **({"corner": corner} if corner else {}),
    }


def parser_fact(view, path, version, data, *, corner=None):
    return {
        "file_type": view,
        "file": path,
        "abs_path": f"/raw/{version}/{path}",
        "status": "PASS",
        "data": data,
        "semantic_context": ({"confirmed": True, "basis": "test", "corner": corner}
                             if corner else {}),
    }


class MacroIndexTests(unittest.TestCase):
    def test_independent_entry_parses_selected_files_and_builds_index(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            lef = root / "physical" / "sram.lef"
            liberty = root / "timing" / "sram_tt.lib.gz"
            verilog = root / "rtl" / "sram.v"
            cdl = root / "lvs" / "sram.cdl"
            for path in (lef, liberty, verilog, cdl):
                path.parent.mkdir(parents=True, exist_ok=True)
            lef.write_text("UNITS\n DATABASE MICRONS 1000 ;\nEND UNITS\nMACRO SRAM_A\n SIZE 1 BY 2 ;\nEND SRAM_A\n", encoding="utf-8")
            with gzip.open(liberty, "wt", encoding="utf-8") as stream:
                stream.write("library (tt) { cell (SRAM_A) { pin (A) { direction : input; } } }")
            verilog.write_text("module SRAM_A(input A); endmodule\n", encoding="utf-8")
            cdl.write_text(".SUBCKT SRAM_A A\n.ENDS SRAM_A\n", encoding="utf-8")
            filemap = {"library_id": "ip/sram", "context": {"type": "CANDIDATE"}, "files": [
                selected_file("lef", "physical/sram.lef", "V01") | {"source_path": str(lef)},
                selected_file("liberty", "timing/sram_tt.lib.gz", "V01") | {"source_path": str(liberty)},
                selected_file("verilog", "rtl/sram.v", "V01") | {"source_path": str(verilog)},
                selected_file("cdl", "lvs/sram.cdl", "V01") | {"source_path": str(cdl)},
            ]}

            facts = build_parser_facts(filemap)
            result = build_macro_index_from_filemap(filemap, facts)

        self.assertEqual(len(facts), 4)
        self.assertTrue(all(item["status"] == "PASS" for item in facts))
        self.assertNotIn("parser_facts", result)
        self.assertEqual(result["macros"]["SRAM_A"]["lef"][0]["evidence"], "PARSED_OBJECT")
        self.assertEqual(result["macros"]["SRAM_A"]["liberty"][0]["evidence"], "PARSED_OBJECT")
        self.assertEqual(result["macros"]["SRAM_A"]["verilog"][0]["evidence"], "PARSED_OBJECT")
        self.assertEqual(result["macros"]["SRAM_A"]["cdl"][0]["evidence"], "PARSED_OBJECT")

    def test_independent_fact_generation_records_file_parse_failure(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            missing = Path(temp_dir) / "missing.lef"
            filemap = {"library_id": "ip/demo", "files": [
                selected_file("lef", "missing.lef", "V01") | {"source_path": str(missing)},
            ]}

            facts = build_parser_facts(filemap)

        self.assertEqual(len(facts), 1)
        self.assertEqual(facts[0]["status"], "FAILED")
        self.assertIn("No such file", facts[0]["error"])

    def test_independent_parser_entry_does_not_import_scan_pipeline(self):
        project_root = Path(__file__).resolve().parents[3]
        env = dict(os.environ, PYTHONPATH=str(project_root / "src"))
        code = (
            "import sys; "
            "from lib_guard.macro_index import build_parser_facts; "
            "build_parser_facts({'files': []}); "
            "assert not any(name == 'lib_guard.scan' or name.startswith('lib_guard.scan.') "
            "for name in sys.modules)"
        )

        result = subprocess.run([sys.executable, "-c", code], env=env, text=True,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        self.assertEqual(result.returncode, 0, result.stderr)

    def test_builds_macro_index_from_selected_filemap_and_existing_facts(self):
        filemap = {
            "library_id": "ip/sram",
            "effective_id": "formal:Nl77",
            "context": {"type": "FORMAL", "formal_stage": "NL77"},
            "files": [
                selected_file("lef", "LEF/sram.lef", "V12"),
                selected_file("liberty", "LIB/sram_tt.lib", "V18", corner="TT"),
                selected_file("liberty", "LIB/sram_ff.lib", "V15", corner="FF"),
                selected_file("verilog", "VERILOG/sram.v", "V12"),
                selected_file("cdl", "CDL/sram.cdl", "V12"),
                selected_file("gds", "GDS/SRAM_A.gds", "V20"),
                selected_file("db", "DB/SRAM_B.db", "V18"),
            ],
        }
        facts = [
            parser_fact("lef", "LEF/sram.lef", "V12", {"macros": {"SRAM_A": {}, "SRAM_B": {}}}),
            parser_fact("liberty", "LIB/sram_tt.lib", "V18", {
                "libraries": {"tt": {"cells": {"SRAM_A": {}}}},
            }, corner="TT"),
            parser_fact("liberty", "LIB/sram_ff.lib", "V15", {
                "libraries": {"ff": {"cells": {"SRAM_A": {}, "LIB_ONLY": {}}}},
            }, corner="FF"),
            parser_fact("verilog", "VERILOG/sram.v", "V12", {
                "modules": {"SRAM_A": {}, "SRAM_B": {}}
            }),
            parser_fact("cdl", "CDL/sram.cdl", "V12", {
                "subckts": {"SRAM_A_LVS": {}, "SRAM_B": {}}
            }),
        ]

        result = build_macro_index(filemap, facts, explicit_aliases={"cdl": {"SRAM_A_LVS": "SRAM_A"}})

        self.assertEqual(result["schema_version"], "macro_index.v1")
        self.assertEqual(result["context"]["type"], "FORMAL")
        self.assertEqual(set(result["macros"]), {"SRAM_A", "SRAM_B"})
        views = result["macros"]["SRAM_A"]
        self.assertEqual([(item["source_version"], item["corner"]) for item in views["liberty"]],
                         [("V15", "FF"), ("V18", "TT")])
        self.assertEqual(views["cdl"][0]["matched_name"], "SRAM_A_LVS")
        self.assertEqual(views["cdl"][0]["match_basis"], "EXPLICIT_ALIAS")
        self.assertEqual(views["gds"][0]["evidence"], "NAME_CANDIDATE")
        self.assertEqual(result["macros"]["SRAM_B"]["db"][0]["evidence"], "NAME_CANDIDATE")
        self.assertEqual(result["unmatched_objects"]["liberty"][0]["name"], "LIB_ONLY")
        self.assertNotIn("LIB_ONLY", result["macros"])

    def test_filemap_entry_uses_supplied_facts_without_loading_parser_package(self):
        project_root = Path(__file__).resolve().parents[3]
        env = dict(os.environ, PYTHONPATH=str(project_root / "src"))
        code = """
import sys
from lib_guard.macro_index import build_macro_index_from_filemap
filemap = {
    'library_id': 'ip/demo',
    'files': [{'view': 'lef', 'relative_path': 'LEF/a.lef',
               'source_path': '/raw/V01/LEF/a.lef', 'source_version': 'V01'}],
}
facts = [{'file_type': 'lef', 'file': 'LEF/a.lef',
          'abs_path': '/raw/V01/LEF/a.lef', 'status': 'PASS',
          'data': {'macros': {'A': {}}}}]
result = build_macro_index_from_filemap(filemap, facts)
assert result['macros']['A']['lef'][0]['evidence'] == 'PARSED_OBJECT'
assert 'parser_facts' not in result
assert not any(name == 'lib_guard.macro_index_parsers' or
               name.startswith('lib_guard.macro_index_parsers.')
               for name in sys.modules)
"""

        result = subprocess.run([sys.executable, "-c", code], env=env, text=True,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        self.assertEqual(result.returncode, 0, result.stderr)

    def test_only_facts_for_selected_filemap_sources_are_associated(self):
        filemap = {"library_id": "ip/demo", "context": {"type": "CANDIDATE"}, "files": [
            selected_file("lef", "LEF/a.lef", "V02"),
            selected_file("liberty", "LIB/a.lib", "V02"),
        ]}
        facts = [
            parser_fact("lef", "LEF/a.lef", "V02", {"macros": {"A": {}}}),
            parser_fact("liberty", "LIB/a.lib", "V01", {"libraries": {"l": {"cells": {"A": {}}}}}),
        ]

        result = build_macro_index(filemap, facts)

        self.assertEqual(result["macros"]["A"]["liberty"], [])
        self.assertEqual(result["unmatched_files"][0]["reason"], "PARSER_FACT_SOURCE_MISMATCH")

    def test_without_lef_uses_parsed_objects_but_marks_missing_baseline(self):
        filemap = {"library_id": "ip/demo", "context": {"type": "CANDIDATE"}, "files": [
            selected_file("liberty", "LIB/a.lib", "V01"),
        ]}
        facts = [parser_fact("liberty", "LIB/a.lib", "V01", {
            "libraries": {"l": {"cells": {"A": {}}}},
        })]

        result = build_macro_index(filemap, facts)

        self.assertEqual(result["baseline"]["status"], "LEF_MISSING")
        self.assertEqual(result["macros"]["A"]["liberty"][0]["evidence"], "PARSED_OBJECT")

    def test_failed_or_incomplete_parser_result_does_not_claim_object_evidence(self):
        filemap = {"library_id": "ip/demo", "context": {"type": "FORMAL"}, "files": [
            selected_file("lef", "LEF/a.lef", "V01"),
            selected_file("liberty", "LIB/a.lib", "V01"),
        ]}
        facts = [
            parser_fact("lef", "LEF/a.lef", "V01", {"macros": {"A": {}}}),
            {**parser_fact("liberty", "LIB/a.lib", "V01", {
                "libraries": {"l": {"cells": {"A": {}}}},
            }), "status": "FAILED"},
        ]

        result = build_macro_index(filemap, facts)

        self.assertEqual(result["macros"]["A"]["liberty"], [])
        self.assertEqual(result["unmatched_files"][0]["reason"], "PARSER_NOT_PASS")

    def test_real_sky130_sram_facts_map_to_one_macro_without_promoting_gds_name(self):
        root = Path(__file__).resolve().parents[3] / "tests/fixtures/raw/vendor_C/openroad_sky130ram/20260619_sky130ram/sky130ram_source_package/sky130_sram_1rw1r_80x64_8"
        paths = {
            "lef": root / "sky130_sram_1rw1r_80x64_8.lef",
            "liberty": root / "sky130_sram_1rw1r_80x64_8_TT_1p8V_25C.lib",
            "verilog": root / "sky130_sram_1rw1r_80x64_8.v",
            "cdl": root / "sky130_sram_1rw1r_80x64_8.lvs.sp",
            "gds": root / "sky130_sram_1rw1r_80x64_8.gds",
        }
        filemap = {
            "library_id": "sky130ram/80x64",
            "context": {"type": "CANDIDATE", "candidate_version": "20260619_sky130ram"},
            "files": [selected_file(view, path.name, "20260619_sky130ram") | {"source_path": str(path)}
                      for view, path in paths.items()],
        }

        facts = build_parser_facts(filemap)
        result = build_macro_index(filemap, facts)

        macro = result["macros"]["sky130_sram_1rw1r_80x64_8"]
        for view in ("lef", "liberty", "cdl", "verilog"):
            self.assertEqual(macro[view][0]["evidence"], "PARSED_OBJECT")
        self.assertEqual(macro["gds"][0]["evidence"], "NAME_CANDIDATE")
        self.assertEqual(result["baseline"]["macro_count"], 1)


if __name__ == "__main__":
    unittest.main()
