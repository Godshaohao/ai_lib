import json
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET
from unittest.mock import patch

from lib_guard.review_runner import (_finding_rows, _publish_latest_workbook, _qa_rows, _review_summary,
                                    _input_identity, _input_scope, _input_scope_label,
                                    _finalize_engineering_checklist, _run_formal, _source_revision,
                                    _write_latest_if_newer, build_workbook_model, run, run_review)


class FormalDefaultConfigTests(unittest.TestCase):
    def test_formal_inventory_uses_registered_paths_without_yaml(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            raw = root / "raw" / "Vendor_A" / "phy_ip"
            raw.mkdir(parents=True)
            formal = root / "formal" / "lib_NL2.5_3" / "IP"
            formal.mkdir(parents=True)

            result = _run_formal({"root": str(raw), "formal_nl_root": str(formal),
                                  "ip_directory_name": "phy_ip", "library_id": "Vendor_A.phy_ip"},
                                 root, root / "evidence")

            self.assertEqual(result["formal_nl_root"], str(formal))
            self.assertEqual(result["library_root"], str(raw))
            self.assertTrue((root / "evidence" / "formal_nl" / "formal_nl.json").is_file())


class InputScopeTests(unittest.TestCase):
    def test_cross_ip_lef_scope_and_formal_snapshot_are_recorded_for_excel(self):
        comparison_scope = {
            "kind": "INDEPENDENT_CROSS_IP",
            "old_library_id": "Vendor_B.RM_IP",
            "new_library_id": "Vendor_A.stdcell",
            "notice": "独立跨 IP 文件对比；不代表所选库的版本变化。",
        }
        identity = _input_identity("lef_review", {"comparison_scope": comparison_scope}, {})
        review = {
            "context": {"target_raw_versions": []},
            "checks": {"lef_review": {"selected": True, "input_identity": identity}},
            "inventory_snapshot": {
                "status": "COMPLETE", "generated_at": "2026-10-26T10:00:00Z",
                "report_ref": "formal_nl/vendor_a/runs/formal_01/formal_nl.json",
                "report": {"inventories": {"lib_NL2.5_3": {}}},
            },
        }

        scope = _input_scope(review)
        label = _input_scope_label(scope)

        self.assertEqual(scope["checks"][0]["comparison_scope"], comparison_scope)
        self.assertEqual(scope["formal_inventory_snapshot"]["generated_at"], "2026-10-26T10:00:00Z")
        self.assertEqual(scope["formal_inventory_snapshot"]["stages"], ["lib_NL2.5_3"])
        self.assertIn("独立跨 IP 文件对比", label)
        self.assertIn("不代表所选库的版本变化", label)
        self.assertIn("2026-10-26T10:00:00Z", label)

    def test_formal_inventory_explicit_yaml_overrides_registered_paths(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            formal = root / "formal" / "lib_NL2.5_3" / "IP"
            formal.mkdir(parents=True)
            config = root / "formal.yml"
            config.write_text("library:\n  ip_directory_name: phy_ip\nformal_nl:\n  root: " +
                              str(formal) + "\n", encoding="utf-8")

            result = _run_formal({"config": str(config), "formal_nl_root": "/wrong/path"},
                                 root, root / "evidence")

            self.assertEqual(result["formal_nl_root"], str(formal))
from lib_guard.ip_check_overview import render_overview
from lib_guard.lef_liberty_check import _compare_cell, _corner_axes, analyze_many
from lib_guard.export_review_excel import export_review_excel


def review(ip_id, macro_name, source_path):
    return {
        "ip": {"id": ip_id, "name": ip_id, "raw_version": "raw-v1", "formal_stage": "lib_NL2.5_3"},
        "checks": {
            "formal_nl": {
                "selected": True,
                "status": "COMPLETE",
                "result": {
                    "report_status": "COMPLETE",
                    "inventories": {
                        "lib_NL2.5_3": {
                            "status": "COMPLETE",
                            "files": [{"relative_path": "LEF/a.lef", "view": "lef", "source_path": source_path}],
                            "view_counts": {"lef": 1},
                        }
                    },
                    "filename_coverage": {},
                },
            },
            "macro_index": {
                "selected": True,
                "status": "COMPLETE",
                "result": {
                    "macro_index": {
                        "baseline": {"status": "LEF_PARSED", "macro_count": 1},
                        "macros": {macro_name: {"lef": [{"file": "LEF/a.lef", "source_path": source_path}], "liberty": []}},
                        "unmatched_files": [],
                        "unmatched_objects": {},
                    }
                },
            },
        },
    }


class ReviewRunnerTests(unittest.TestCase):
    def test_workbook_includes_saved_formal_and_all_raw_file_inventories(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            output = root / "output"
            library_id = "Vendor.IP_A"
            # The production directory includes a hash suffix; use the runner helper.
            from lib_guard.review_runner import _library_dir
            formal_dir = output / "formal_nl" / _library_dir(library_id)
            report_path = formal_dir / "runs" / "formal_001" / "formal_nl.json"
            report_path.parent.mkdir(parents=True)
            report = {
                "library_id": library_id,
                "report_status": "COMPLETE",
                "generated_at": "2026-10-25T10:00:00+00:00",
                "inventories": {
                    "lib_NL2.5_3": {"status": "COMPLETE", "view_counts": {"lef": 1},
                                    "files": [{"relative_path": "LEF/a.lef", "view": "lef",
                                               "raw_version": "20261001_v1",
                                               "source_path": "/raw/v1/LEF/a.lef",
                                               "published_path": "/formal/lib_NL2.5_3/IP/LEF/a.lef"}]}
                },
                "raw_library": {"status": "COMPLETE", "versions": [
                    {"version_id": "20261001_v1", "path": "/raw/v1", "inventory_status": "COMPLETE",
                     "file_count": 1, "view_counts": {"lef": 1}},
                    {"version_id": "20261002_v2", "path": "/raw/v2", "inventory_status": "COMPLETE",
                     "file_count": 2, "view_counts": {"lef": 1, "liberty": 1}},
                ], "inventories": {
                    "20261001_v1": {"status": "COMPLETE", "file_count": 1,
                                     "view_counts": {"lef": 1}, "files": [
                                         {"relative_path": "LEF/a.lef", "view": "lef", "source_path": "/raw/v1/LEF/a.lef"}]},
                    "20261002_v2": {"status": "COMPLETE", "file_count": 2,
                                     "view_counts": {"lef": 1, "liberty": 1}, "files": [
                                         {"relative_path": "LEF/a.lef", "view": "lef", "source_path": "/raw/v2/LEF/a.lef"},
                                         {"relative_path": "LIB/a.lib", "view": "liberty", "source_path": "/raw/v2/LIB/a.lib"}]},
                }},
            }
            report_path.write_text(json.dumps(report), encoding="utf-8")
            (formal_dir / "latest_check.json").write_text(json.dumps({
                "generated_at": "2026-10-25T10:00:00+00:00",
                "report_status": "COMPLETE",
                "report_json": str(report_path),
            }), encoding="utf-8")
            macro_report = root / "macro.json"
            macro_report.write_text(json.dumps({"status": "COMPLETE", "macro_index": {
                "baseline": {"status": "NO_LEF", "macro_count": 0}, "macros": {},
                "unmatched_files": [], "unmatched_objects": {},
            }}), encoding="utf-8")
            captured = {}

            def export(model, path, *, scope_note):
                captured["model"] = model
                Path(path).write_bytes(b"workbook")

            with patch("lib_guard.review_runner._source_revision", return_value={
                    "commit": "abc123", "working_tree_dirty": False,
            }), patch("lib_guard.review_runner.export_review_excel", side_effect=export):
                run({"ips": [{"id": "IP_A", "library_id": library_id, "raw_version": "20261002_v2",
                               "checks": {"macro_index": {"report_json": str(macro_report)}}}]}, output)

            model = captured["model"]
            self.assertEqual(len(model["07-正式文件"]), 1)
            self.assertEqual(model["07-正式文件"][0]["正式阶段"], "lib_NL2.5_3")
            self.assertEqual(len(model["RAW文件清单"]), 3)
            self.assertEqual({row["RAW版本"] for row in model["RAW文件清单"]},
                             {"20261001_v1", "20261002_v2"})
            self.assertEqual(model["00-概览"][0]["质量判断"], "本次范围未发现问题")
            workbook_path = root / "inventory.xlsx"
            export_review_excel(model, workbook_path)
            with zipfile.ZipFile(workbook_path) as archive:
                workbook_xml = ET.fromstring(archive.read("xl/workbook.xml"))
                sheet_names = [sheet.attrib["name"] for sheet in workbook_xml.findall(".//{*}sheet")]
                text_evidence = b"".join(archive.read(name) for name in archive.namelist()
                                           if name.startswith("xl/worksheets/sheet"))
                if "xl/sharedStrings.xml" in archive.namelist():
                    text_evidence += archive.read("xl/sharedStrings.xml")
            self.assertIn("07-正式文件", sheet_names)
            self.assertIn("RAW文件清单", sheet_names)
            self.assertIn(b"lib_NL2.5_3", text_evidence)
            self.assertIn(b"20261002_v2", text_evidence)
            self.assertIn(b"/raw/v2/LIB/a.lib", text_evidence)

    def test_missing_saved_inventory_is_explicit_not_zero_files(self):
        model = build_workbook_model([{
            "ip": {"id": "IP_A", "library_id": "Vendor.IP_A"},
            "checks": {"macro_index": {"selected": True, "status": "COMPLETE", "result": {}}},
        }])

        self.assertIn("07-正式文件", model)
        self.assertIn("RAW文件清单", model)
        self.assertEqual(model["07-正式文件"][0]["盘点状态"], "未附盘点")
        self.assertEqual(model["RAW文件清单"][0]["版本盘点状态"], "未附盘点")
        self.assertIn("未找到", model["RAW文件清单"][0]["盘点报告"])

    def test_new_review_scope_does_not_treat_formal_inventory_as_manual_check(self):
        item = {"ip": {"id": "IP_A"}, "checks": {
            "macro_index": {"selected": True, "status": "COMPLETE", "result": {}}
        }}

        summary = _review_summary(item)
        qa = _qa_rows(item)
        not_run = next(row for row in qa if row["问题"] == "本次有哪些检查没有运行？")
        model = build_workbook_model([item])

        self.assertEqual(summary["quality_assessment"]["not_run_checks"],
                         ["lef_liberty_check", "lef_review"])
        self.assertNotIn("正式可见文件", model["00-概览"][0])
        self.assertNotIn("正式目录盘点", not_run["回答"])
        self.assertIn("07-正式文件", model)
        self.assertEqual(model["07-正式文件"][0]["盘点状态"], "未附盘点")
        self.assertEqual(model["RAW文件清单"][0]["版本盘点状态"], "未附盘点")
        self.assertFalse(any("正式目录观察到哪些文件类型和数量？" == row["问题"]
                             for row in model["03-问答"]))

    def test_legacy_formal_review_evidence_remains_exportable(self):
        item = review("IP_A", "MACRO_A", "/raw/a/LEF/a.lef")

        model = build_workbook_model([item])

        self.assertIn("07-正式文件", model)
        self.assertEqual(model["07-正式文件"][0]["来源路径"], "/raw/a/LEF/a.lef")

    def test_source_revision_marks_untracked_workspace_files_dirty(self):
        with patch("lib_guard.review_runner.subprocess.run", side_effect=[
                subprocess.CompletedProcess([], 0, "0123456789abcdef\n", ""),
                subprocess.CompletedProcess([], 0, "?? new_runtime_module.py\n", "")]) as run_command:
            revision = _source_revision()

        self.assertEqual(revision["commit"], "0123456789abcdef")
        self.assertTrue(revision["working_tree_dirty"])
        self.assertNotIn("--untracked-files=no", run_command.call_args_list[1].args[0])

    def test_fast_slow_typ_are_reported_as_filename_corner_clues(self):
        expected = {
            "fast": "FAST",
            "slow": "SLOW",
            "typ": "TYP",
        }
        for token, label in expected.items():
            with self.subTest(token=token):
                axes = _corner_axes(Path(f"ip_{token}_1p20V_25C.lib"), [f"ip_{token}_1p20V_25C"])
                self.assertEqual(axes["process_corner"], label)
                self.assertEqual(axes["process_corner_candidates"], [label])
                self.assertFalse(axes["conflict"])

    def test_ssg_process_corner_is_extracted_from_operating_condition_name(self):
        axes = _corner_axes(Path("generic_slow.lib"), ["generic_slow"], ["ssg_0p72v_125c"])
        self.assertEqual(axes["process_corner"], "SSG")
        self.assertEqual(axes["process_corner_candidates"], ["SSG"])

    def test_pvt_coverage_does_not_require_numeric_liberty_process_attribute(self):
        from lib_guard.review_runner import _file_has_pvt_observation

        item = {"source_path": "/raw/LIB/model.lib", "operating_conditions": {
            "model": {"ssg_0p72v_125c": {"process": None, "voltage": "0.72", "temperature": "125"}}}}
        self.assertTrue(_file_has_pvt_observation(item))

    def test_interface_mismatch_rollup_counts_instances_by_combined_reason(self):
        cells = []
        for index in range(504):
            signal = {"missing_in_liberty": [], "extra_in_liberty": [], "direction_mismatch": []}
            pg = {"missing_in_liberty": ["VDD"], "extra_in_liberty": [], "wrong_type": [],
                  "unverified_type": []}
            if index >= 492:
                signal["extra_in_liberty"] = ["EXTRA"]
            cells.append({"macro": f"CELL_{index:03}", "status": "MISMATCH",
                          "signal_pins": signal, "power_ground": pg})
        item = {"ip": {"id": "IHP.sg13g2_stdcell"}, "checks": {"lef_liberty_check": {
            "selected": True, "status": "COMPLETE", "result": {"files": [{
                "liberty_source": "/fixture/sg13g2.lib", "summary": {"mismatch_cell_count": 504},
                "cells": cells}], "summary": {"liberty_file_count": 1}}}}}

        model = build_workbook_model([item])

        groups = [row for row in model["04-关注项"] if row["类别"] == "LEF-Liberty接口"]
        self.assertEqual(len(model["10-Liberty单元"]), 504)
        self.assertEqual({row["对象"]: row["数量"] for row in groups},
                         {"PG脚缺失": 492, "信号Pin多出 + PG脚缺失": 12})
        self.assertIn("VDD", groups[0]["发现"])
        self.assertEqual({item["count"] for item in _review_summary(item)["primary_findings"]}, {492, 12})

    def test_review_json_excel_and_html_record_shared_provenance_and_scope(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "macro.json"
            source.write_text(json.dumps({"status": "COMPLETE", "macro_index": {
                "baseline": {"status": "LEF_PARSED", "macro_count": 1}, "macros": {},
                "unmatched_files": [], "unmatched_objects": {},
            }}), encoding="utf-8")
            captured = {}

            def export(model, path, *, scope_note):
                captured["overview"] = model["00-概览"][0]
                captured["scope_note"] = scope_note
                Path(path).write_bytes(b"test workbook")

            with patch("lib_guard.review_runner._source_revision", return_value={
                "commit": "0123456789abcdef", "working_tree_dirty": True,
            }), patch("lib_guard.review_runner.export_review_excel", side_effect=export):
                run({"ips": [{"id": "IP_A", "library_id": "Vendor.IP_A", "raw_version": "V20",
                               "formal_stage": "lib_NL2.5_3", "checks": {
                                   "macro_index": {"report_json": str(source)},
                               }}]}, root / "output")

            record_path = next((root / "output" / "libraries").rglob("review_result.json"))
            record = json.loads(record_path.read_text(encoding="utf-8"))
            self.assertEqual(record["source_revision"]["commit"], "0123456789abcdef")
            self.assertTrue(record["source_revision"]["working_tree_dirty"])
            self.assertEqual(record["input_scope"]["target_raw_versions"], ["V20"])
            self.assertEqual(record["input_scope"]["formal_stage"], "lib_NL2.5_3")
            self.assertEqual(captured["overview"]["源提交"], "0123456789abcdef")
            self.assertEqual(captured["overview"]["工作区有改动"], "是")
            self.assertIn("RAW：V20", captured["overview"]["输入范围"])
            self.assertIn("源提交：0123456789abcdef（工作区有改动）", captured["scope_note"])
            page = (root / "output" / "ip_checks" / "index.html").read_text(encoding="utf-8")
            self.assertIn("0123456789abcdef", page)
            self.assertIn("RAW V20", page)

    def test_mismatch_takes_precedence_over_unverified_in_quality_label(self):
        item = review("IP_A", "MACRO_A", "/raw/a/LEF/a.lef")
        item["checks"]["formal_nl"]["result"]["broken_links"] = ["/formal/LEF/broken.lef"]
        item["checks"]["macro_index"]["result"]["macro_index"]["unmatched_objects"] = {
            "liberty": [{"name": "CELL_UNCERTAIN", "file": "/raw/a.lib"}]
        }

        summary = _review_summary(item)

        self.assertEqual(summary["quality_assessment"]["status"], "ISSUES_FOUND")
        self.assertEqual(summary["counts"]["MISMATCH"]["affected_objects"], 1)
        self.assertEqual(summary["counts"]["UNVERIFIED"]["affected_objects"], 1)

    def test_cross_view_alone_exports_matching_lef_cell_and_pin_reason(self):
        item = {"ip": {"id": "IP_A"}, "checks": {"lef_liberty_check": {
            "selected": True, "status": "COMPLETE", "result_ref": "evidence/lef_liberty_check.json",
            "result": {"files": [{"liberty_source": "/raw/a.lib", "corner_axes": {},
                "library_names": ["lib_a"], "summary": {"mismatch_cell_count": 1},
                "cells": [{"macro": "CELL_A", "status": "MISMATCH",
                    "signal_pins": {"missing_in_liberty": [], "extra_in_liberty": ["X"],
                                    "direction_mismatch": []},
                    "power_ground": {"missing_in_liberty": ["VDD", "VSS"],
                                     "extra_in_liberty": [], "wrong_type": [], "unverified_type": []}}]}],
                "summary": {"liberty_file_count": 1}}
        }}}

        model = build_workbook_model([item])

        cell = model["10-Liberty单元"][0]
        self.assertTrue(cell["LEF同名"])
        self.assertIn("PG脚缺失", cell["差异类型"])
        self.assertIn("VDD", cell["具体差异"])
        self.assertIn("X", cell["具体差异"])
        self.assertEqual(cell["证据路径"], "evidence/lef_liberty_check.json")
        findings = [row for row in model["04-关注项"] if row["类别"] == "LEF-Liberty接口"]
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["数量"], 1)
        self.assertIn("PG脚缺失", findings[0]["对象"])
        self.assertIn("信号Pin多出", findings[0]["对象"])
        self.assertTrue(all("CELL_A" in row["发现"] for row in findings))

    def test_liberty_bus_member_range_matches_flat_lef_pin_names(self):
        macro = {"pins": {
            "DATA[0]": {"direction": "INPUT", "use": "SIGNAL"},
            "DATA[1]": {"direction": "INPUT", "use": "SIGNAL"},
            "DATA[2]": {"direction": "INPUT", "use": "SIGNAL"},
        }}
        liberty_cell = {"pins": {"DATA[2:0]": {"direction": "input"}}, "pg_pins": {}}

        result = _compare_cell("MACRO_A", macro, "lib_a", liberty_cell, True, True, True)

        self.assertEqual(result["status"], "MATCH")
        self.assertEqual(result["signal_pins"]["missing_in_liberty"], [])
        self.assertEqual(result["signal_pins"]["extra_in_liberty"], [])
        self.assertEqual(result["signal_pin_checked_count"], 3)
        self.assertEqual(result["signal_pins"]["expanded_bus_ranges"], [
            {"source": "DATA[2:0]", "members": ["DATA[0]", "DATA[1]", "DATA[2]"]}
        ])

    def test_overlapping_bus_and_scalar_pin_definitions_are_unverified_not_order_dependent(self):
        macro = {"pins": {
            "DATA[0]": {"direction": "INPUT", "use": "SIGNAL"},
            "DATA[1]": {"direction": "INPUT", "use": "SIGNAL"},
        }}
        definitions = [
            ("DATA[1:0]", {"direction": "input"}),
            ("DATA[1]", {"direction": "output"}),
        ]

        results = []
        for ordered in (definitions, list(reversed(definitions))):
            result = _compare_cell("MACRO_A", macro, "lib_a",
                                   {"pins": dict(ordered), "pg_pins": {}}, True, True, True)
            results.append(result)

        for result in results:
            self.assertEqual(result["status"], "UNVERIFIED")
            self.assertEqual(result["signal_pins"]["missing_in_liberty"], [])
            self.assertEqual(result["signal_pins"]["extra_in_liberty"], [])
            self.assertEqual(len(result["signal_pins"]["bus_definition_conflicts"]), 1)
            conflict = result["signal_pins"]["bus_definition_conflicts"][0]
            self.assertEqual(conflict["member"], "DATA[1]")
            self.assertEqual({source["name"] for source in conflict["definitions"]},
                             {"DATA[1:0]", "DATA[1]"})
            self.assertTrue(any("DATA[1]" in reason for reason in result["unverified"]))
        self.assertEqual(results[0]["signal_pins"]["bus_definition_conflicts"],
                         results[1]["signal_pins"]["bus_definition_conflicts"])

    def test_oversized_liberty_bus_range_is_unverified_not_false_pin_mismatch(self):
        macro = {"pins": {"DATA[0]": {"direction": "INPUT", "use": "SIGNAL"}}}
        liberty_cell = {"pins": {"DATA[70000:0]": {"direction": "input"}}, "pg_pins": {}}

        result = _compare_cell("MACRO_A", macro, "lib_a", liberty_cell, True, True, True)

        self.assertEqual(result["status"], "UNVERIFIED")
        self.assertEqual(result["signal_pins"]["missing_in_liberty"], [])
        self.assertEqual(result["signal_pins"]["extra_in_liberty"], [])
        self.assertIn("Liberty 总线范围过大，未展开核对：DATA[70000:0]", result["unverified"])

    def test_pg_terminal_bang_name_difference_is_unverified_alias_not_confirmed_pin_loss(self):
        macro = {"pins": {
            "VDD!": {"direction": "INOUT", "use": "POWER"},
            "VSS!": {"direction": "INOUT", "use": "GROUND"},
        }}
        liberty_cell = {"pins": {}, "pg_pins": {
            "VDD": {"pg_type": "primary_power"},
            "VSS": {"pg_type": "primary_ground"},
        }}

        result = _compare_cell("MACRO_A", macro, "lib_a", liberty_cell, True, True, True)

        self.assertEqual(result["status"], "UNVERIFIED")
        self.assertEqual(result["power_ground"]["missing_in_liberty"], [])
        self.assertEqual(result["power_ground"]["extra_in_liberty"], [])
        self.assertEqual(result["power_ground"]["name_alias_candidates"], [
            {"lef": "VDD!", "liberty": "VDD", "lef_use": "POWER", "liberty_pg_type": "primary_power"},
            {"lef": "VSS!", "liberty": "VSS", "lef_use": "GROUND", "liberty_pg_type": "primary_ground"},
        ])

    def test_liberty_operating_conditions_are_separate_filterable_rows(self):
        item = {"ip": {"id": "IP_A"}, "checks": {"lef_liberty_check": {
            "selected": True, "status": "COMPLETE", "result": {"files": [{
                "liberty_source": "/raw/a.lib", "library_names": ["lib_a"],
                "operating_conditions": {"lib_a": {
                    "FAST": {"process": "1", "voltage": "1.95", "temperature": "-40"},
                    "SLOW": {"process": "2", "voltage": "1.6", "temperature": "100"}}},
                "liberty_inventory": {"cell_count": 1}, "summary": {}, "cells": []}],
                "summary": {"liberty_file_count": 1}}}}}

        rows = build_workbook_model([item])["09-Liberty角"]

        self.assertEqual(len(rows), 2)
        self.assertEqual({row["条件"] for row in rows}, {"FAST", "SLOW"})
        self.assertEqual({row["Voltage (V)"] for row in rows}, {1.95, 1.6})
        self.assertEqual({row["Temp (°C)"] for row in rows}, {-40, 100})
        self.assertNotIn("PVT", rows[0])

    def test_execution_records_use_short_summary_and_relative_evidence(self):
        item = review("IP_A", "MACRO_A", "/raw/a/LEF/a.lef")
        check = item["checks"]["macro_index"]
        check["result_ref"] = "evidence/macro_index.json"
        check["report_path"] = "/tmp/volatile/macro_index.json"
        check["input_identity"] = {"sources": [{"role": "filemap", "path": "/raw/a/LEF/a.lef"}]}
        check["input_spec"] = {"root": "/raw/a", "enabled": True}

        model = build_workbook_model([item])
        record = next(row for row in model["02-执行记录"] if row["检查"] == "Macro / View 文件索引")
        self.assertNotIn("{", record["输入身份"])
        self.assertNotIn("{", record["输入范围"])
        self.assertEqual(record["报告路径"], "evidence/macro_index.json")
        qa = next(row for row in model["03-问答"] if "LEF Macro" in row["问题"])
        self.assertEqual(qa["来源报告"], "evidence/macro_index.json")

    def test_questions_explain_selected_formal_sources_and_lef_changes(self):
        item = review("IP_A", "MACRO_A", "/raw/V2/LEF/a.lef")
        formal = item["checks"]["formal_nl"]
        formal["result_ref"] = "evidence/formal_nl.json"
        formal["result"]["inventories"]["lib_NL2.5_3"]["files"] = [
            {"relative_path": "LEF/a.lef", "raw_version": "V1"},
            {"relative_path": "LIB/a.lib", "raw_version": "V2"},
        ]
        item["checks"]["lef_review"] = {"selected": True, "status": "COMPLETE",
            "result_ref": "evidence/lef_review.json", "result": {"comparison": {
                "macro_names": {"added": ["CELL_B"], "removed": []},
                "changes": [{"macro": "MACRO_A", "field": "size"}]}}}

        qa = build_workbook_model([item])["03-问答"]

        source = next(row for row in qa if "RAW 版本" in row["问题"])
        self.assertIn("V1", source["回答"])
        self.assertIn("V2", source["回答"])
        self.assertEqual(source["来源报告"], "evidence/formal_nl.json")
        changed = next(row for row in qa if "哪些 Macro" in row["问题"])
        self.assertIn("CELL_B", changed["回答"])
        self.assertIn("MACRO_A", changed["回答"])

    def test_lef_rect_findings_use_compact_counts_and_archive_evidence(self):
        rects_old = [{"port_index": 0, "layer": "met2", "x1": i, "y1": 0,
                      "x2": i + 1, "y2": 1} for i in range(600)]
        rects_new = rects_old + [{"port_index": 0, "layer": "met2", "x1": 700,
                                  "y1": 0, "x2": 701, "y2": 1}]
        obs_old = [{"layer": "met3", "x1": i, "y1": 2, "x2": i + 1,
                    "y2": 3} for i in range(24)]
        obs_new = obs_old + [{"layer": "met3", "x1": 40, "y1": 2,
                              "x2": 41, "y2": 3}]
        item = {"ip": {"id": "IP_A"}, "checks": {"lef_review": {
            "selected": True, "status": "COMPLETE", "result_ref": "evidence/lef_review.json",
            "result": {"comparison": {"changes": [
                {"macro": "MACRO_A", "field": "pins.VDD.rects",
                 "old": rects_old, "new": rects_new},
                {"macro": "MACRO_A", "field": "obs", "old": obs_old, "new": obs_new},
            ]}},
        }}}

        rows = _finding_rows(item)

        self.assertEqual(len(rows), 2)
        self.assertEqual([row["kind"] for row in rows], ["CHANGED", "CHANGED"])
        self.assertEqual([row["evidence"] for row in rows], [
            "evidence/lef_review.json", "evidence/lef_review.json"])
        pin = rows[0]
        self.assertIn("MACRO_A", pin["object"])
        self.assertIn("VDD", pin["object"])
        self.assertIn("Pin RECT", pin["message"])
        self.assertIn("600", pin["message"])
        self.assertIn("601", pin["message"])
        self.assertIn("物理区域等价性未验证", pin["message"])
        self.assertLess(len(pin["message"]), 300)
        self.assertNotIn("x1", pin["message"])
        self.assertIn("OBS", rows[1]["message"])
        self.assertIn("24", rows[1]["message"])
        self.assertIn("25", rows[1]["message"])
        self.assertLess(len(rows[1]["message"]), 300)

    def test_lef_regular_field_change_keeps_specific_old_and_new_values(self):
        item = {"ip": {"id": "IP_A"}, "checks": {"lef_review": {
            "selected": True, "status": "COMPLETE", "result_ref": "evidence/lef_review.json",
            "result": {"comparison": {"changes": [{"macro": "MACRO_A", "field": "size",
                "old": {"x": 1.0, "y": 2.0}, "new": {"x": 3.0, "y": 2.0}}]}},
        }}}

        finding = _finding_rows(item)[0]

        self.assertIn("size:", finding["message"])
        self.assertIn("'x': 1.0", finding["message"])
        self.assertIn("'x': 3.0", finding["message"])
        self.assertEqual(finding["evidence"], "evidence/lef_review.json")

    def test_lef_unrecognized_geometry_does_not_infer_record_counts(self):
        item = {"ip": {"id": "IP_A"}, "checks": {"lef_review": {
            "selected": True, "status": "COMPLETE", "result_ref": "evidence/lef_review.json",
            "result": {"comparison": {"changes": [
                {"macro": "MACRO_A", "field": "pins.VDD.rects",
                 "old": {"rects": 4}, "new": "unknown"},
                {"macro": "MACRO_A", "field": "obs",
                 "old": [{"layer": "M2", "x1": 0}], "new": [{"layer": "M2"}]},
            ]}},
        }}}

        rows = _finding_rows(item)

        self.assertEqual(len(rows), 2)
        for row in rows:
            self.assertIn("结构化详情见证据", row["message"])
            self.assertIn("未验证", row["message"])
            self.assertNotIn("旧 1 条", row["message"])
            self.assertNotIn("旧 4 条", row["message"])
            self.assertEqual(row["evidence"], "evidence/lef_review.json")

    def test_not_run_qa_uses_review_result_request_and_execution_records(self):
        item = {"ip": {"id": "IP_A"}, "requested_checks": ["lef_review"],
                "review_result_ref": "review_result.json",
                "checks": {"lef_review": {"selected": False, "status": "NOT_RUN"}},
                "review_result": {"requested_checks": ["lef_review"], "checks": {
                    "lef_review": {"execution_status": "FAILED"},
                    "formal_nl": {"execution_status": "NOT_RUN"},
                    "macro_index": {"execution_status": "NOT_RUN"},
                    "lef_liberty_check": {"execution_status": "NOT_RUN"},
                }}}

        row = next(row for row in _qa_rows(item)
                   if row["问题"] == "本次有哪些检查没有运行？")

        self.assertIn("正式目录盘点", row["回答"])
        self.assertIn("Macro / View 文件索引", row["回答"])
        self.assertIn("LEF–Liberty 接口核查", row["回答"])
        self.assertNotIn("LEF 双文件核查", row["回答"])
        self.assertEqual(row["来源报告"], "review_result.json")

    def test_run_workbook_qa_points_to_its_review_result(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            item = review("IP_A", "MACRO_A", "/raw/a/LEF/a.lef")
            output = root / "output"
            library_dir = output / "libraries" / "ip_a"
            run_dir = library_dir / "runs" / "review_qa"
            run_dir.mkdir(parents=True)
            item.update({"review_id": "review_qa", "generated_at": "2026-10-25T00:00:00+00:00",
                         "run_dir": str(run_dir), "library_dir": str(library_dir),
                         "requested_checks": ["formal_nl", "macro_index"]})
            captured = {}

            def fake_export(model, path, **_kwargs):
                captured["qa"] = model["03-问答"]
                Path(path).write_bytes(b"xlsx")

            with patch("lib_guard.review_runner.run_review", return_value=[item]), \
                    patch("lib_guard.review_runner.export_review_excel", side_effect=fake_export):
                run({"ips": []}, output)

            row = next(row for row in captured["qa"]
                       if row["问题"] == "本次有哪些检查没有运行？")
            self.assertEqual(row["来源报告"], "review_result.json")

    def test_no_lef_changes_produces_no_change_findings(self):
        item = {"ip": {"id": "IP_A"}, "checks": {"lef_review": {
            "selected": True, "status": "COMPLETE", "result_ref": "evidence/lef_review.json",
            "result": {"comparison": {"macro_names": {"added": [], "removed": []},
                                        "changes": [], "unverified": []}},
        }}}

        self.assertEqual(_finding_rows(item), [])

        all_match = {"ip": {"id": "IP_A"}, "checks": {"lef_liberty_check": {
            "selected": True, "status": "COMPLETE", "result_ref": "evidence/lef_liberty_check.json",
            "result": {"files": [{"liberty_source": "/raw/a.lib",
                "summary": {"mismatch_cell_count": 0, "unverified_cell_count": 0},
                "cells": [{"macro": "MACRO_A", "status": "MATCH",
                    "signal_pins": {"missing_in_liberty": [], "extra_in_liberty": [],
                                    "direction_mismatch": []},
                    "power_ground": {"missing_in_liberty": [], "extra_in_liberty": [],
                                     "wrong_type": [], "unverified_type": []}}]}],
                "summary": {"liberty_file_count": 1}},
        }}}

        self.assertEqual(_finding_rows(all_match), [])

    def test_overview_distinguishes_failed_attempt_from_last_complete_result(self):
        page = render_overview([{
            "ip": {"name": "IP A", "library_id": "vendor.ip_a"},
            "last_attempt": {"status": "FAILED", "id": "task_failed", "time": "2026-10-24T12:00Z"},
            "last_complete": {"id": "review_good", "time": "2026-10-23T12:00Z",
                               "requested_checks": ["lef_review"],
                               "checks": {"lef_review": {"execution_status": "COMPLETE"}},
                               "summary": {"counts": {"MISMATCH": {"affected_objects": 4},
                                                          "CHANGED": {"affected_objects": 0},
                                                          "UNVERIFIED": {"affected_objects": 0}}},
                               "xlsx_href": "../libraries/ip_a/latest.xlsx"},
        }])

        self.assertEqual(page.count("<tbody id=\"ip-rows\">"), 1)
        self.assertIn("task_failed", page)
        self.assertIn("review_good", page)
        self.assertIn("最近完整报告范围", page)
        self.assertIn("不一致 4", page)

    def test_persistent_overview_reads_failed_web_attempt_separately(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            ip = {"id": "IP_A", "library_id": "vendor.ip_a", "raw_versions": []}
            from lib_guard.review_runner import _library_dir
            library_dir = root / "output" / "libraries" / _library_dir("vendor.ip_a")
            run_id = "review_20261024T010000Z_abcd1234"
            run_dir = library_dir / "runs" / run_id
            run_dir.mkdir(parents=True)
            (run_dir / "review_result.json").write_text(json.dumps({
                "review_id": run_id, "execution_status": "COMPLETE",
                "generated_at": "2026-10-24T01:00:00Z",
                "summary": {"counts": {"MISMATCH": {"affected_objects": 4, "finding_records": 1}}},
            }), encoding="utf-8")
            (run_dir / "ip_review.xlsx").write_bytes(b"test workbook")
            (library_dir / "latest_attempt.json").write_text(json.dumps({
                "task_id": "task_failed", "status": "FAILED", "finished_at": "2026-10-24T02:00:00Z",
            }), encoding="utf-8")

            run({"ips": [], "registry_ips": [ip]}, root / "output")

            page = (root / "output" / "ip_checks" / "index.html").read_text(encoding="utf-8")
            self.assertIn("task_failed", page)
            self.assertIn(run_id, page)
            self.assertIn("不一致 4", page)
            self.assertIn("发现已确认不一致", page)
            self.assertIn("最近完整报告范围", page)

    def test_overview_shows_one_excel_link_when_latest_and_last_run_are_same(self):
        page = render_overview([{
            "ip": {"name": "IP A", "library_id": "vendor.ip_a"},
            "last_attempt": {"status": "COMPLETE", "id": "review_x"},
            "last_complete": {"id": "review_x", "requested_checks": ["macro_index"],
                               "checks": {"macro_index": {"execution_status": "COMPLETE"}},
                               "summary": {"counts": {"MISMATCH": {"affected_objects": 0},
                                                          "CHANGED": {"affected_objects": 0},
                                                          "UNVERIFIED": {"affected_objects": 0}}},
                               "xlsx_href": "../libraries/ip_a/latest.xlsx"},
        }])

        self.assertEqual(page.count("latest.xlsx"), 1)
        self.assertIn("打开 Excel", page)
        self.assertNotIn("本次 Excel", page)

    def test_overview_keeps_excel_entry_only_in_catalog_table(self):
        page = render_overview([{
            "ip": {"name": "IP A", "library_id": "vendor.ip_a"},
            "last_attempt": {"status": "COMPLETE"},
            "last_complete": {"id": "review_x", "requested_checks": ["macro_index"],
                               "checks": {"macro_index": {"execution_status": "COMPLETE"}},
                               "summary": {"counts": {"MISMATCH": {"affected_objects": 0},
                                                          "CHANGED": {"affected_objects": 0},
                                                          "UNVERIFIED": {"affected_objects": 0}}},
                               "xlsx_href": "../libraries/ip_a/latest.xlsx"},
        }])

        self.assertEqual(page.count("latest.xlsx"), 1)

    def test_latest_pointer_never_moves_back_to_an_older_result(self):
        with tempfile.TemporaryDirectory() as temp:
            latest = Path(temp) / "latest.json"
            newer = {"review_id": "review_new", "generated_at": "2026-10-24T12:00:00+00:00"}
            older = {"review_id": "review_old", "generated_at": "2026-10-24T11:00:00+00:00"}

            self.assertTrue(_write_latest_if_newer(latest, newer))
            self.assertFalse(_write_latest_if_newer(latest, older))
            self.assertEqual(__import__("json").loads(latest.read_text())["review_id"], "review_new")

    def test_latest_pointer_rejects_result_without_valid_generated_time(self):
        with tempfile.TemporaryDirectory() as temp:
            latest = Path(temp) / "latest.json"
            current = {"review_id": "review_new", "generated_at": "2026-10-24T12:00:00+00:00"}
            unordered = {"review_id": "review_unordered"}

            self.assertTrue(_write_latest_if_newer(latest, current))
            self.assertFalse(_write_latest_if_newer(latest, unordered))
            self.assertEqual(__import__("json").loads(latest.read_text())["review_id"], "review_new")

    def test_stable_workbook_does_not_regress_when_an_older_task_finishes_late(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            library_dir = root / "library"
            old_book = root / "old.xlsx"
            new_book = root / "new.xlsx"
            old_book.write_bytes(b"old")
            new_book.write_bytes(b"new")

            self.assertTrue(_publish_latest_workbook(new_book, library_dir, "review_new",
                                                     "2026-10-24T12:00:00+00:00"))
            self.assertFalse(_publish_latest_workbook(old_book, library_dir, "review_old",
                                                      "2026-10-24T11:00:00+00:00"))

            self.assertEqual((library_dir / "latest.xlsx").read_bytes(), b"new")
            pointer = __import__("json").loads((library_dir / "latest_workbook.json").read_text())
            self.assertEqual(pointer["review_id"], "review_new")

    def test_summary_counts_unmatched_macro_objects_and_broken_links_by_kind(self):
        item = review("IP_A", "MACRO_A", "/raw/a/LEF/a.lef")
        item["checks"]["formal_nl"]["result"]["broken_links"] = ["/formal/LEF/broken.lef"]
        item["checks"]["macro_index"]["result"]["macro_index"]["unmatched_objects"] = {
            "liberty": [{"name": f"CELL_{index}", "file": "/raw/a/lib/a.lib"} for index in range(3)]
        }

        summary = _review_summary(item)

        self.assertEqual(summary["counts"]["MISMATCH"]["affected_objects"], 1)
        self.assertEqual(summary["counts"]["UNVERIFIED"]["affected_objects"], 3)
        self.assertEqual(summary["counts"]["UNVERIFIED"]["finding_records"], 1)

    def test_quality_assessment_is_separate_from_successful_execution(self):
        item = review("IP_A", "MACRO_A", "/raw/a/LEF/a.lef")
        item["checks"]["macro_index"]["status"] = "COMPLETE"
        item["checks"]["lef_liberty_check"] = {
            "selected": True, "status": "COMPLETE", "result": {"files": [{
                "liberty_source": "/raw/a.lib", "summary": {"mismatch_cell_count": 1},
                "cells": [{"macro": "MACRO_A", "status": "MISMATCH",
                           "signal_pins": {"missing_in_liberty": ["A"], "extra_in_liberty": [],
                                           "direction_mismatch": []},
                           "power_ground": {"missing_in_liberty": [], "extra_in_liberty": [],
                                            "wrong_type": [], "unverified_type": []}}]}]}}

        summary = _review_summary(item)

        self.assertEqual(summary["quality_assessment"]["status"], "ISSUES_FOUND")
        self.assertIn("发布放行", summary["quality_assessment"]["boundary"])

    def test_quality_assessment_marks_unverified_evidence_without_calling_it_pass(self):
        item = review("IP_A", "MACRO_A", "/raw/a/LEF/a.lef")
        item["checks"]["macro_index"]["result"]["macro_index"]["unmatched_objects"] = {
            "liberty": [{"name": "OTHER", "file": "/raw/a.lib"}]
        }

        assessment = _review_summary(item)["quality_assessment"]

        self.assertEqual(assessment["status"], "REVIEW_REQUIRED")
        self.assertNotIn("通过", assessment["label"])

    def test_unrecognized_liberty_process_corner_is_quality_scope_gap(self):
        item = review("IP_A", "MACRO_A", "/raw/a/LEF/a.lef")
        item["checks"]["lef_liberty_check"] = {
            "selected": True, "status": "COMPLETE", "result": {"files": [{
                "liberty_source": "/raw/LIB/a_fast.lib", "corner_axes": {
                    "process_corner": None, "process_corner_candidates": [], "conflict": False},
                "operating_conditions": {"lib_a": {"nominal": {"process": "1", "voltage": "1.2",
                                                                      "temperature": "25"}}},
                "summary": {"unverified_cell_count": 0}, "cells": []}]}}

        summary = _review_summary(item)
        findings = [row for row in _finding_rows(item) if row["category"] == "Liberty工艺角"]

        self.assertEqual(summary["quality_assessment"]["status"], "REVIEW_REQUIRED")
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["kind"], "UNVERIFIED")
        self.assertIn("a_fast.lib", findings[0]["message"])
        self.assertIn("核对项目 Corner 命名映射", findings[0]["action"])

    def test_quality_summary_and_qa_list_checks_not_selected_this_run(self):
        item = review("IP_A", "MACRO_A", "/raw/a/LEF/a.lef")
        item["checks"]["formal_nl"]["selected"] = False
        item["checks"]["lef_review"] = {"selected": False, "status": "NOT_RUN"}
        item["checks"]["lef_liberty_check"] = {
            "selected": True, "status": "COMPLETE", "result": {"files": []}}

        summary = _review_summary(item)
        qa = _qa_rows(item)
        not_run = next(row for row in qa if row["问题"] == "本次有哪些检查没有运行？")

        self.assertEqual(summary["quality_assessment"]["not_run_checks"], ["formal_nl", "lef_review"])
        self.assertIn("LEF 双文件核查", summary["quality_assessment"]["boundary"])
        self.assertIn("正式目录盘点", not_run["回答"])
        self.assertIn("LEF 双文件核查", not_run["回答"])
        self.assertIn("未选择", not_run["证据范围"])

    def test_cdl_subcircuits_outside_lef_macro_names_are_scope_notes_not_missing_coverage(self):
        item = review("IP_A", "MACRO_A", "/raw/a/LEF/a.lef")
        item["checks"]["macro_index"]["result"]["macro_index"]["unmatched_objects"] = {
            "cdl": [{"name": f"BITCELL_{index}", "file": "/raw/a.cdl"} for index in range(4)]
        }

        summary = _review_summary(item)
        findings = _finding_rows(item)

        self.assertEqual(summary["unverified"], 0)
        self.assertEqual(summary["scope_notes"], 4)
        cdl = next(row for row in findings if row["category"] == "CDL对象范围")
        self.assertEqual(cdl["kind"], "SCOPE_INFO")
        self.assertEqual(cdl["count"], 4)
        self.assertEqual(cdl["evidence"], "/raw/a.cdl")

    def test_runner_persists_execution_and_quality_status_as_separate_fields(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            run_id = "review_20261024T010000Z_quality"
            output = root / "output"
            library_dir = output / "libraries" / "ip_a"
            run_dir = library_dir / "runs" / run_id
            run_dir.mkdir(parents=True)
            item = review("IP_A", "MACRO_A", "/raw/a/LEF/a.lef")
            item.update({"review_id": run_id, "generated_at": "2026-10-24T01:00:00+00:00",
                         "run_dir": str(run_dir), "library_dir": str(library_dir),
                         "requested_checks": ["formal_nl", "macro_index"]})
            def fake_export(_model, path, **_kwargs):
                Path(path).write_bytes(b"xlsx")

            with patch("lib_guard.review_runner.run_review", return_value=[item]), \
                    patch("lib_guard.review_runner.export_review_excel", side_effect=fake_export):
                reviews, _ = run({"ips": []}, output)

            record = json.loads((run_dir / "review_result.json").read_text(encoding="utf-8"))
            self.assertEqual(reviews[0]["execution_status"], "COMPLETE")
            self.assertEqual(reviews[0]["quality_status"], "NO_FINDINGS_WITHIN_SCOPE")
            self.assertEqual(record["execution_status"], "COMPLETE")
            self.assertEqual(record["quality_status"], "NO_FINDINGS_WITHIN_SCOPE")
            self.assertIn("不等同于 IP 全面质量通过", record["summary"]["quality_assessment"]["boundary"])

    def test_failed_formal_check_does_not_answer_inventory_is_empty(self):
        item = {"ip": {"id": "IP_A"}, "checks": {"formal_nl": {
            "selected": True, "status": "FAILED", "error": "Permission denied", "result": {}
        }}}

        rows = _qa_rows(item)

        failed_answer = next(row for row in rows if row["问题"] == "正式目录观察到哪些文件类型和数量？")
        self.assertEqual(len(rows), 2)
        self.assertIn("未生成", failed_answer["回答"])
        self.assertNotIn("清单为空", failed_answer["回答"])
        unselected_answer = next(row for row in rows if row["问题"] == "本次有哪些检查没有运行？")["回答"]
        self.assertNotIn("正式目录盘点", unselected_answer)
        self.assertIn("LEF 双文件核查", unselected_answer)

    def test_run_records_mixed_explicit_raw_versions_without_merging_them(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            report = root / "macro.json"
            report.write_text(__import__("json").dumps({
                "filemap": {"context": {"source": "/raw/V1"}, "files": [
                    {"view": "lef", "source_path": "/raw/V1/LEF/a.lef", "source_version": "V1"}
                ]},
                "macro_index": {"baseline": {"macro_count": 1}, "macros": {"A": {}}},
            }), encoding="utf-8")
            config = {"_config_path": str(root / "config.yml"), "ips": [{
                "id": "IP_A", "library_id": "vendor/ip_a", "raw_version": "V2",
                "checks": {"macro_index": {"report_json": str(report)}}
            }]}

            result = run_review(config, root / "output")[0]

            self.assertEqual(result["context_alignment"], "MIXED_EXPLICIT")
            identity = result["checks"]["macro_index"]["input_identity"]
            self.assertEqual(identity["source_versions"], ["V1"])
            self.assertEqual(result["context"]["target_raw_versions"], ["V2"])

            run(config, root / "published")
            record = __import__("json").loads(next((root / "published").rglob("review_result.json")).read_text())
            self.assertEqual(record["context_alignment"], "MIXED_EXPLICIT")
            self.assertEqual(record["checks"]["macro_index"]["input_identity"]["source_versions"], ["V1"])

    def test_failed_workbook_export_does_not_publish_result_or_replace_latest(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            report = root / "macro.json"
            report.write_text('{"status":"COMPLETE","macro_index":{"macros":{}}}', encoding="utf-8")
            config = {"ips": [{"id": "IP_A", "library_id": "vendor/ip_a", "publish_latest": True,
                               "checks": {"macro_index": {"report_json": str(report)}}}]}
            run(config, root / "output")
            latest_path = next((root / "output" / "libraries").glob("*/latest.json"))
            old_latest = __import__("json").loads(latest_path.read_text(encoding="utf-8"))
            library_dir = latest_path.parent
            latest_workbook_path = library_dir / "latest.xlsx"
            workbook_pointer_path = library_dir / "latest_workbook.json"
            old_workbook = latest_workbook_path.read_bytes()
            old_workbook_pointer = __import__("json").loads(workbook_pointer_path.read_text(encoding="utf-8"))

            with patch("lib_guard.review_runner.export_review_excel", side_effect=OSError("disk full")):
                with self.assertRaisesRegex(OSError, "disk full"):
                    run(config, root / "output")

            self.assertEqual(__import__("json").loads(latest_path.read_text(encoding="utf-8")), old_latest)
            self.assertEqual(latest_workbook_path.read_bytes(), old_workbook)
            self.assertEqual(__import__("json").loads(workbook_pointer_path.read_text(encoding="utf-8")),
                             old_workbook_pointer)
            records = list(latest_path.parent.glob("runs/*/review_result.json"))
            self.assertEqual(len(records), 1)

    def test_lef_review_only_workbook_has_only_relevant_sheets_and_relative_evidence(self):
        item = {"ip": {"id": "IP_A"}, "checks": {"lef_review": {
            "selected": True, "status": "COMPLETE", "result_ref": "evidence/lef_review.json",
            "result": {"sources": {"old": {"path": "/old/a.lef"},
                                    "new": {"path": "/new/a.lef"}},
                       "comparison": {"macro_names": {"added": [], "removed": []},
                                      "changes": [{"macro": "MACRO_A", "field": "size",
                                                   "old": {"x": 1, "y": 2},
                                                   "new": {"x": 2, "y": 2}}]},
                       "extraction": {"new": {"data": {"macros": {}}}}},
        }}}

        model = build_workbook_model([item])

        self.assertEqual(list(model), ["00-概览", "01-工程检查", "02-执行记录",
                                       "03-问答", "04-关注项", "07-正式文件", "08-LEF宏", "RAW文件清单"])
        self.assertEqual(model["04-关注项"][0]["证据路径"], "evidence/lef_review.json")
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "lef_only.xlsx"
            export_review_excel(model, output)
            with zipfile.ZipFile(output) as archive:
                workbook = ET.fromstring(archive.read("xl/workbook.xml"))
            names = [sheet.attrib["name"] for sheet in workbook.findall(".//{*}sheet")]
        self.assertEqual(names, list(model))

    def test_run_writes_one_workbook_per_library_id_and_preserves_ip_identity(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            reports = []
            ips = []
            for library_id in ("vendor/ip_a", "vendor/ip_b"):
                report = root / f"{library_id.rsplit('/', 1)[-1]}.json"
                report.write_text(__import__("json").dumps({
                    "status": "COMPLETE",
                    "macro_index": {"baseline": {"status": "LEF_PARSED", "macro_count": 1},
                                    "macros": {}, "unmatched_files": [], "unmatched_objects": {}},
                }), encoding="utf-8")
                reports.append(report)
                ips.append({"id": "same_display_name", "library_id": library_id,
                            "name": "same display name", "checks": {
                                "macro_index": {"report_json": str(report)}}})

            run({"ips": ips}, root / "output")

            result_files = sorted((root / "output" / "libraries").rglob("review_result.json"))
            self.assertEqual(len(result_files), 2)
            result_data = [__import__("json").loads(path.read_text(encoding="utf-8")) for path in result_files]
            self.assertEqual({item["library_id"] for item in result_data}, {"vendor/ip_a", "vendor/ip_b"})
            for result_file in result_files:
                self.assertTrue((result_file.parent / "ip_review.xlsx").is_file())
                self.assertTrue((result_file.parent.parent.parent / "latest.xlsx").is_file())
                record = __import__("json").loads(result_file.read_text(encoding="utf-8"))
                self.assertEqual(record["execution_status"], "COMPLETE")
                self.assertEqual(record["requested_checks"], ["macro_index"])
                self.assertNotIn("formal_nl", record["checks"])
                with zipfile.ZipFile(result_file.parent / "ip_review.xlsx") as archive:
                    workbook = ET.fromstring(archive.read("xl/workbook.xml"))
                    self.assertEqual([item.attrib["name"] for item in workbook.findall(".//{*}sheet")],
                                     ["00-概览", "01-工程检查", "02-执行记录", "03-问答", "04-关注项",
                              "05-MacroView", "06-MacroView文件", "07-正式文件", "RAW文件清单"])
            self.assertFalse((root / "output" / "ai_lib_IP检查结果.xlsx").exists())
            self.assertFalse(any((root / "output" / "libraries").glob("*/latest.json")))
            self.assertTrue((root / "output" / "ip_checks" / "index.html").is_file())

            run({"ips": ips}, root / "output")
            self.assertEqual(len(list((root / "output" / "libraries").rglob("review_result.json"))), 4)

    def test_latest_pointer_is_written_only_when_explicitly_requested(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            report = root / "macro.json"
            report.write_text('{"status":"COMPLETE","macro_index":{"macros":{}}}', encoding="utf-8")
            config = {"ips": [{"id": "IP_A", "library_id": "vendor/ip_a", "publish_latest": True,
                               "checks": {"macro_index": {"report_json": str(report)}}}]}

            run(config, root / "output")

            pointer = next((root / "output" / "libraries").glob("*/latest.json"))
            data = __import__("json").loads(pointer.read_text(encoding="utf-8"))
            self.assertEqual(data["library_id"], "vendor/ip_a")
            self.assertTrue((pointer.parent / data["review_result_ref"]).is_file())

            previous_review_id = data["review_id"]
            report.write_text("not json", encoding="utf-8")
            run(config, root / "output")
            latest_after_failure = __import__("json").loads(pointer.read_text(encoding="utf-8"))
            self.assertEqual(latest_after_failure["review_id"], previous_review_id)

    def test_persistent_overview_keeps_registered_ips_when_running_a_subset(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            report = root / "macro.json"
            report.write_text('{"status":"COMPLETE","macro_index":{"macros":{}}}', encoding="utf-8")
            ip_a = {"id": "IP_A", "library_id": "vendor/ip_a", "publish_latest": True,
                    "checks": {"macro_index": {"report_json": str(report)}}}
            ip_b = {"id": "IP_B", "library_id": "vendor/ip_b", "publish_latest": True,
                    "checks": {"macro_index": {"report_json": str(report)}}}
            output = root / "output"
            run({"ips": [ip_a, ip_b]}, output)

            run({"ips": [ip_a], "registry_ips": [ip_a, ip_b]}, output)

            page = (output / "ip_checks" / "index.html").read_text(encoding="utf-8")
            self.assertIn("IP_A", page)
            self.assertIn("IP_B", page)
            self.assertIn("最近完整报告范围", page)

    def test_overview_includes_catalog_context_and_stable_latest_workbook_link(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            report = root / "macro.json"
            report.write_text('{"status":"COMPLETE","macro_index":{"macros":{}}}', encoding="utf-8")
            ip = {
                "id": "IP_A", "library_id": "vendor/ip_a", "name": "IP A", "vendor": "Vendor X",
                "middle_path": "memory/sram", "raw_root": "/raw/Vendor_X/IP_A",
                "raw_versions": [{"id": "V1", "path": "/raw/Vendor_X/IP_A/V1", "views": ["LEF", "LIB"]},
                                 {"id": "V2", "path": "/raw/Vendor_X/IP_A/V2", "views": ["LEF", "GDS"]}],
                "checks": {"macro_index": {"report_json": str(report)}},
            }

            with patch("lib_guard.review_runner.export_review_excel",
                       side_effect=lambda model, path, scope_note="": Path(path).write_bytes(b"test workbook")):
                run({"ips": [ip], "registry_ips": [ip]}, root / "output")

            page = (root / "output" / "ip_checks" / "index.html").read_text(encoding="utf-8")
            self.assertIn("Vendor X", page)
            self.assertIn("memory/sram", page)
            self.assertNotIn("/raw/Vendor_X/IP_A/V1", page)
            self.assertNotIn("/raw/Vendor_X/IP_A/V2", page)
            self.assertIn("../libraries/", page)
            self.assertIn("latest.xlsx", page)

    def test_overview_recovers_latest_complete_legacy_run_without_latest_pointers(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            ip = {"id": "IP_A", "library_id": "vendor.ip_a", "name": "IP A",
                  "vendor": "Vendor X", "raw_root": "/raw/IP_A", "raw_versions": []}
            from lib_guard.review_runner import _library_dir
            library_dir = root / "output" / "libraries" / _library_dir("vendor.ip_a")
            run_id = "review_20261024T010000Z_abcd1234"
            run_dir = library_dir / "runs" / run_id
            run_dir.mkdir(parents=True)
            (run_dir / "review_result.json").write_text(json.dumps({
                "review_id": run_id, "library_id": "vendor.ip_a", "execution_status": "COMPLETE",
                "generated_at": "2026-10-24T01:00:00Z", "summary": {"counts": {}},
            }), encoding="utf-8")
            (run_dir / "ip_review.xlsx").write_bytes(b"legacy workbook")

            run({"ips": [], "registry_ips": [ip]}, root / "output")

            page = (root / "output" / "ip_checks" / "index.html").read_text(encoding="utf-8")
            self.assertIn("Vendor X", page)
            self.assertIn("IP A", page)
            self.assertIn("任务已结束", page)
            self.assertIn(f"runs/{run_id}/ip_review.xlsx", page)

    def test_incomplete_run_preserves_previous_stable_workbook(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            complete_report = root / "complete.json"
            complete_report.write_text('{"status":"COMPLETE","macro_index":{"macros":{}}}', encoding="utf-8")
            ip = {"id": "IP_A", "library_id": "vendor/ip_a",
                  "checks": {"macro_index": {"report_json": str(complete_report)}}}
            output = root / "output"
            with patch("lib_guard.review_runner.export_review_excel",
                       side_effect=lambda model, path, scope_note="": Path(path).write_bytes(b"first workbook")):
                run({"ips": [ip]}, output)
            stable_path = next((output / "libraries").glob("*/latest.xlsx"))
            previous = stable_path.read_bytes()

            incomplete_report = root / "incomplete.json"
            incomplete_report.write_text('{"status":"FAILED","macro_index":{"macros":{}}}', encoding="utf-8")
            ip["checks"]["macro_index"]["report_json"] = str(incomplete_report)
            with patch("lib_guard.review_runner.export_review_excel",
                       side_effect=lambda model, path, scope_note="": Path(path).write_bytes(b"second workbook")):
                run({"ips": [ip]}, output)

            self.assertEqual(previous, b"first workbook")
            self.assertEqual(stable_path.read_bytes(), previous)

    def test_duplicate_library_id_in_one_run_is_rejected_to_prevent_mixing_contexts(self):
        with tempfile.TemporaryDirectory() as temp:
            report = Path(temp) / "macro.json"
            report.write_text('{"status":"COMPLETE","macro_index":{"macros":{}}}', encoding="utf-8")
            config = {"ips": [
                {"id": "A", "library_id": "vendor/same", "raw_version": "V1",
                 "checks": {"macro_index": {"report_json": str(report)}}},
                {"id": "B", "library_id": "vendor/same", "raw_version": "V2",
                 "checks": {"macro_index": {"report_json": str(report)}}},
            ]}
            with self.assertRaisesRegex(ValueError, "library_id 重复"):
                run(config, Path(temp) / "output")

    def test_build_workbook_model_keeps_ip_evidence_separate_and_describes_observations(self):
        model = build_workbook_model([
            review("IP_A", "MACRO_A", "/raw/a/LEF/a.lef"),
            review("IP_B", "MACRO_B", "/raw/b/LEF/a.lef"),
        ])

        ip_ids = {row["IP"] for row in model["05-MacroView"]}
        self.assertEqual(ip_ids, {"IP_A", "IP_B"})
        self.assertEqual({row["Macro"] for row in model["05-MacroView"]}, {"MACRO_A", "MACRO_B"})
        self.assertEqual({row["来源路径"] for row in model["07-正式文件"]}, {"/raw/a/LEF/a.lef", "/raw/b/LEF/a.lef"})
        self.assertTrue(any("观察到" in row["回答"] for row in model["03-问答"]))
        self.assertFalse(any("必需" in row["回答"] for row in model["03-问答"]))
        self.assertNotIn("09-Liberty角", model)
        self.assertNotIn("10-Liberty单元", model)

    def test_macro_file_mapping_and_ten_engineering_topics_are_filterable_rows(self):
        item = review("IP_A", "MACRO_A", "/raw/a/LEF/a.lef")
        item["checks"]["macro_index"]["result"]["macro_index"]["macros"]["MACRO_A"]["liberty"] = [
            {"view": "liberty", "file": "lib/tt.lib.gz", "source_path": "/raw/V2/lib/tt.lib.gz",
             "source_version": "V2", "corner": "TT", "evidence": "PARSED_OBJECT", "match_basis": "EXACT_OBJECT_NAME"}
        ]

        model = build_workbook_model([item])

        self.assertEqual(len(model["06-MacroView文件"]), 2)
        liberty_row = next(row for row in model["06-MacroView文件"] if row["View"] == "Liberty")
        self.assertEqual((liberty_row["来源版本"], liberty_row["Corner/线索"], liberty_row["状态"]),
                         ("V2", "TT", "PARSED_OBJECT"))
        checklist = model["01-工程检查"]
        self.assertEqual(len(checklist), 9)
        self.assertEqual(checklist[0]["工程检查主题"], "RAW 文件盘点")
        self.assertIn("正式 NL 来源", [row["工程检查主题"] for row in checklist])
        self.assertNotIn("doc_delta", {row["检查项ID"] for row in checklist})
        self.assertIn("工程覆盖", checklist[0])
        self.assertIn("本次执行", checklist[0])

    def test_raw_document_files_remain_visible_without_a_document_delta_check(self):
        item = {"ip": {"id": "IP_A"}}
        item["inventory_snapshot"] = {"report": {"raw_library": {
            "versions": [{"version_id": "V1", "path": "/raw/V1", "inventory_status": "COMPLETE"}],
            "inventories": {"V1": {"status": "COMPLETE", "files": [
                {"view": "doc", "relative_path": "DOC/README.md", "source_path": "/raw/V1/DOC/README.md"}],
                "view_counts": {"doc": 1}}}}}}
        model = build_workbook_model([item])
        self.assertEqual(len(model["RAW文件清单"]), 1)
        self.assertEqual(model["RAW文件清单"][0]["View"], "文档")
        self.assertEqual(model["RAW文件清单"][0]["相对路径"], "DOC/README.md")

    def test_engineering_checklist_uses_nine_source_topics_and_never_marks_unrun_as_pass(self):
        item = review("IP_A", "MACRO_A", "/raw/a/LEF/a.lef")
        item["checks"].pop("formal_nl")
        item["engineering_checklist"] = [
            {"id": "raw_inventory", "topic": "RAW 文件盘点", "execution": "已执行",
             "result": "2 个交付已盘点", "reason": "", "evidence": "evidence/file_version_projection.json"},
            {"id": "corner_coverage", "topic": "Signoff Corner 覆盖", "execution": "未执行",
             "result": "无结论", "reason": "未配置期望 Corner 集合", "evidence": ""},
        ]

        model = build_workbook_model([item])

        rows = model["01-工程检查"]
        self.assertEqual(len(rows), 9)
        raw = next(row for row in rows if row["检查项ID"] == "raw_inventory")
        corner = next(row for row in rows if row["检查项ID"] == "corner_coverage")
        self.assertEqual((raw["本次执行"], raw["本次结果"]), ("已执行", "2 个交付已盘点"))
        self.assertEqual((corner["本次执行"], corner["未完成原因"]), ("未执行", "未配置期望 Corner 集合"))
        self.assertNotIn("通过", corner["本次结果"])

    def test_view_inventory_is_executed_and_reports_observed_views_without_claiming_completeness(self):
        item = review("IP_A", "MACRO_A", "/raw/a/LEF/a.lef")
        item["checks"].pop("formal_nl")
        item["checks"]["macro_index"]["result"]["filemap"] = {"files": [
            {"view": "lef", "relative_path": "LEF/a.lef"},
            {"view": "liberty", "relative_path": "LIB/tt.lib"},
            {"view": "gds", "relative_path": "GDS/a.gds"},
        ]}
        item["engineering_checklist"] = [{
            "id": "view_completeness", "topic": "Macro 六类文件齐套", "execution": "计划执行",
            "result": "盘点当前 View", "reason": "无项目必需 View 规则",
            "evidence": "evidence/macro_index.json", "check_names": ["macro_index"]}]

        _finalize_engineering_checklist(item)
        row = item["engineering_checklist"][0]
        self.assertEqual(row["execution"], "已执行")
        self.assertIn("LEF×1", row["result"])
        self.assertIn("Liberty×1", row["result"])
        self.assertIn("GDS×1", row["result"])
        self.assertIn("尚无项目必需 View 规则", row["reason"])
        self.assertNotIn("齐套通过", row["result"])

    def test_corner_checklist_lists_observed_corner_counts_and_links_per_liberty_pvt(self):
        item = {"ip": {"id": "IP_A"}, "engineering_checklist": [{
            "id": "corner_coverage", "topic": "Signoff Corner 覆盖", "execution": "部分覆盖",
            "result": "将观察 3 个 Liberty 的 Corner/PVT",
            "reason": "未配置期望 Corner 集合；报告观察结果，不判断齐套",
            "evidence": "evidence/lef_liberty_check.json"}],
            "checks": {"lef_liberty_check": {
            "selected": True, "status": "COMPLETE", "result_ref": "evidence/lef_liberty_check.json",
            "result": {"summary": {"liberty_file_count": 3,
                "process_corner_file_counts": {"FF": 1, "SS": 1, "TT": 1},
                "files_with_unknown_process_corner": 0, "files_with_unknown_rc_corner": 3}, "files": [
                {"liberty_source": f"/raw/V2/{corner}.lib", "library_names": [f"lib_{corner.lower()}"],
                 "corner_axes": {"process_corner": corner, "rc_corner": "未识别"},
                 "operating_conditions": {f"lib_{corner.lower()}": {"nominal": {
                     "process": process, "voltage": voltage, "temperature": temperature}}},
                 "liberty_inventory": {"cell_count": 1}, "summary": {"matched_macro_count": 1}, "cells": []}
                for corner, process, voltage, temperature in (
                    ("FF", "1", "1.32", "-55"), ("SS", "2", "1.08", "125"),
                    ("TT", "1", "1.20", "25"))]}}}}

        _finalize_engineering_checklist(item)
        self.assertIn("FF×1", item["engineering_checklist"][0]["result"])
        self.assertIn("RC角未识别 3 个文件", item["engineering_checklist"][0]["result"])
        model = build_workbook_model([item])

        corner = next(row for row in model["01-工程检查"] if row["检查项ID"] == "corner_coverage")
        self.assertIn("3 个 Liberty", corner["本次结果"])
        for label in ("FF×1", "SS×1", "TT×1"):
            self.assertIn(label, corner["本次结果"])
        self.assertIn("未配置期望 Corner", corner["未完成原因"])
        self.assertNotIn("输入组合待确认", corner["未完成原因"])
        detail = model["09-Liberty角"]
        self.assertEqual({row["PVT Process"] for row in detail}, {"FF", "SS", "TT"})
        self.assertNotIn("工艺角线索", detail[0])
        self.assertNotIn("Liberty process attr", detail[0])
        self.assertEqual({row["Voltage (V)"] for row in detail}, {1.32, 1.08, 1.2})
        self.assertEqual({row["Temp (°C)"] for row in detail}, {-55, 125, 25})
        self.assertEqual({Path(row["Liberty文件"]).name for row in detail},
                         {"FF.lib", "SS.lib", "TT.lib"})

    def test_only_selected_checks_add_details_and_questions(self):
        item = review("IP_A", "MACRO_A", "/raw/a/LEF/a.lef")
        item["checks"].pop("formal_nl")
        model = build_workbook_model([item])

        self.assertEqual(list(model), ["00-概览", "01-工程检查", "02-执行记录", "03-问答", "04-关注项",
                                       "05-MacroView", "06-MacroView文件", "07-正式文件", "RAW文件清单"])
        self.assertEqual(len(model["03-问答"]), 3)
        self.assertEqual(sum("Macro" in row["问题"] for row in model["03-问答"]), 2)
        self.assertTrue(any(row["问题"] == "本次有哪些检查没有运行？" for row in model["03-问答"]))

    def test_failed_check_is_isolated_to_its_ip(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            good = root / "macro.json"
            good.write_text('{"status":"COMPLETE","macro_index":{"macros":{}}}', encoding="utf-8")
            config = {
                "_config_path": str(root / "config.json"),
                "ips": [
                    {"id": "IP_BAD", "checks": {"lef_review": {"report_json": "missing.json"}}},
                    {"id": "IP_GOOD", "checks": {"macro_index": {"report_json": str(good)}}},
                ],
            }
            results = run_review(config, root / "output")
            self.assertEqual(results[0]["checks"]["lef_review"]["status"], "FAILED")
            self.assertEqual(results[1]["checks"]["macro_index"]["status"], "COMPLETE")

    def test_unknown_check_name_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "不支持的检查名"):
            run_review({"ips": [{"id": "IP_A", "checks": {"release_gate": {}}}]}, tempfile.mkdtemp())

    def test_formal_inventory_is_not_runnable_from_manual_review_runner(self):
        with self.assertRaisesRegex(ValueError, "不支持的检查名.*formal_nl"):
            run_review({"ips": [{"id": "IP_A", "checks": {"formal_nl": {"report_json": "formal.json"}}}]},
                       tempfile.mkdtemp())

    def test_liberty_batch_can_retain_matching_cells_for_excel_detail(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            lef = {
                "schema_version": "lef_analysis.v1",
                "sources": {"new": {"path": str(root / "new.lef"), "sha256": "a" * 64}},
                "extraction": {"new": {"data": {"macros": {"LOGIC": {"pins": {
                    "A": {"direction": "INPUT", "use": "SIGNAL"}
                }}}}}},
                "statistics": {"new": {"macro_set_complete": True, "port_set_complete": True}},
            }
            lef_path = root / "lef_analysis.json"
            lef_path.write_text(__import__("json").dumps(lef), encoding="utf-8")
            liberty_path = root / "logic_TT.lib"
            liberty_path.write_text("library (TT) { cell (LOGIC) { pin (A) { direction : input; } } }", encoding="utf-8")
            compact = analyze_many(lef_path, [liberty_path])
            detailed = analyze_many(lef_path, [liberty_path], keep_matching_cells=True)
        self.assertEqual(compact["files"][0]["cells"], [])
        self.assertEqual(detailed["files"][0]["cells"][0]["macro"], "LOGIC")
        self.assertEqual(detailed["files"][0]["cells"][0]["status"], "MATCH")

    def test_runner_links_lef_review_snapshot_into_liberty_check(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            lef = {
                "schema_version": "lef_analysis.v1",
                "sources": {"new": {"path": str(root / "new.lef"), "sha256": "a" * 64}},
                "extraction": {"new": {"data": {"macros": {"LOGIC": {"pins": {
                    "A": {"direction": "INPUT", "use": "SIGNAL"}
                }}}}}},
                "statistics": {"new": {"macro_set_complete": True, "port_set_complete": True}},
            }
            lef_path = root / "lef_report.json"
            lef_path.write_text(__import__("json").dumps(lef), encoding="utf-8")
            liberty = root / "logic_TT.lib"
            liberty.write_text("library (TT) { cell (LOGIC) { pin (A) { direction : input; } } }", encoding="utf-8")
            config = {"_config_path": str(root / "config.yml"), "ips": [{"id": "IP_A", "checks": {
                "lef_liberty_check": {"liberty_files": [str(liberty)]},
                "lef_review": {"report_json": str(lef_path)},
            }}]}

            result = run_review(config, root / "output")[0]

            self.assertEqual(result["checks"]["lef_liberty_check"]["status"], "COMPLETE",
                             result["checks"]["lef_liberty_check"])
            self.assertTrue((Path(result["run_dir"]) / "evidence" / "lef_review" / "lef_analysis.json").is_file())

    def test_runner_rejects_explicit_lef_different_from_review_target(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            target = root / "target.lef"
            other = root / "other.lef"
            target.write_text("MACRO TARGET\nEND TARGET\n", encoding="utf-8")
            other.write_text("MACRO OTHER\nEND OTHER\n", encoding="utf-8")
            liberty = root / "target.lib"
            liberty.write_text("library (TT) {}", encoding="utf-8")
            config = {"ips": [{"id": "IP_A", "checks": {
                "lef_review": {"old_file": str(target), "new_file": str(target)},
                "lef_liberty_check": {"lef_file": str(other), "liberty_files": [str(liberty)]},
            }}]}

            result = run_review(config, root / "output")[0]

            self.assertEqual(result["checks"]["lef_liberty_check"]["status"], "FAILED")
            self.assertIn("LEF", result["checks"]["lef_liberty_check"]["error"])
            self.assertIn("不一致", result["checks"]["lef_liberty_check"]["error"])

    def test_runner_rejects_explicit_lef_report_from_different_target(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            def report(path, source, digest):
                path.write_text(__import__("json").dumps({
                    "schema_version": "lef_analysis.v1",
                    "sources": {"new": {"path": str(source), "sha256": digest * 64}},
                    "extraction": {"new": {"data": {"macros": {}}}},
                }), encoding="utf-8")
            target_report = root / "target.json"
            other_report = root / "other.json"
            report(target_report, root / "target.lef", "a")
            report(other_report, root / "other.lef", "b")
            liberty = root / "target.lib"
            liberty.write_text("library (TT) {}", encoding="utf-8")
            config = {"ips": [{"id": "IP_A", "checks": {
                "lef_review": {"report_json": str(target_report)},
                "lef_liberty_check": {"lef_analysis_json": str(other_report), "lef_library_id": "IP_A",
                                      "liberty_files": [str(liberty)]},
            }}]}
            result = run_review(config, root / "output")[0]
            self.assertEqual(result["checks"]["lef_liberty_check"]["status"], "FAILED")
            self.assertIn("LEF 来源不一致", result["checks"]["lef_liberty_check"]["error"])

    def test_runner_builds_target_lef_snapshot_for_single_version_linked_check(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            lef_path = root / "raw" / "V1" / "LEF" / "top.lef"
            liberty_path = root / "raw" / "V1" / "LIB" / "TT" / "top.lib"
            lef_path.parent.mkdir(parents=True)
            liberty_path.parent.mkdir(parents=True)
            lef_path.write_text("MACRO TOP\nEND TOP\n", encoding="utf-8")
            liberty_path.write_text("library (TT) {}", encoding="utf-8")
            snapshot = {
                "schema_version": "lef_analysis.v1",
                "sources": {"new": {"path": str(lef_path), "sha256": "a" * 64}},
                "extraction": {"new": {"data": {"macros": {}}}},
                "statistics": {"new": {"macro_count": 0}},
            }
            config = {"_config_path": str(root / "config.yml"), "ips": [{
                "id": "IP_A", "library_id": "vendor.ip_a", "raw_version": "V1",
                "checks": {"lef_liberty_check": {"lef_file": str(lef_path),
                                                    "liberty_files": [str(liberty_path)]}},
            }]}
            cross_view = {"schema_version": "lef_liberty_batch.v1", "lef_source": snapshot["sources"]["new"],
                          "files": [], "summary": {"liberty_file_count": 1}}

            with patch("lib_guard.review_runner.lef_review.analyze", return_value=snapshot) as lef_analyze, \
                    patch("lib_guard.review_runner.lef_liberty_check.analyze_many", return_value=cross_view) as check, \
                    patch("lib_guard.review_runner.lef_liberty_check.render_markdown", return_value="test report"):
                result = run_review(config, root / "output")[0]

            self.assertEqual(result["checks"]["lef_liberty_check"]["status"], "COMPLETE",
                             result["checks"]["lef_liberty_check"])
            lef_analyze.assert_called_once_with(lef_path.resolve(), lef_path.resolve())
            self.assertTrue((Path(result["run_dir"]) / "evidence" / "lef_liberty_check" / "lef_snapshot.json").is_file())
            self.assertEqual(check.call_args.args[1], [liberty_path.resolve()])

    def test_runner_rejects_cross_view_report_from_another_lef_source(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            lef = {
                "schema_version": "lef_analysis.v1",
                "sources": {"new": {"path": str(root / "ip_a.lef"), "sha256": "a" * 64}},
                "extraction": {"new": {"data": {"macros": {}}}},
            }
            lef_path = root / "lef.json"
            lef_path.write_text(__import__("json").dumps(lef), encoding="utf-8")
            unrelated_report = root / "other_ip_cross_view.json"
            unrelated_report.write_text(__import__("json").dumps({
                "lef_source": {"path": str(root / "ip_b.lef"), "sha256": "b" * 64},
                "files": [], "summary": {"liberty_file_count": 0},
            }), encoding="utf-8")
            config = {"_config_path": str(root / "config.yml"), "ips": [{"id": "IP_A", "checks": {
                "lef_review": {"report_json": str(lef_path)},
                "lef_liberty_check": {"report_json": str(unrelated_report)},
            }}]}

            result = run_review(config, root / "output")[0]

            self.assertEqual(result["checks"]["lef_liberty_check"]["status"], "FAILED")
            self.assertIn("LEF 来源不一致", result["checks"]["lef_liberty_check"]["error"])

    def test_runner_requires_ip_binding_for_standalone_lef_report(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            lef = {"sources": {"new": {"path": str(root / "ip_a.lef"), "sha256": "a" * 64}},
                   "extraction": {"new": {"data": {"macros": {}}}}}
            lef_path = root / "lef.json"
            lef_path.write_text(__import__("json").dumps(lef), encoding="utf-8")
            liberty = root / "logic_TT.lib"
            liberty.write_text("library (TT) { cell (LOGIC) { } }", encoding="utf-8")
            config = {"_config_path": str(root / "config.yml"), "ips": [{"id": "IP_A", "checks": {
                "lef_liberty_check": {"lef_analysis_json": str(lef_path),
                                      "lef_library_id": "vendor/ip_b",
                                      "liberty_files": [str(liberty)]},
            }}]}

            result = run_review(config, root / "output")[0]

            self.assertEqual(result["checks"]["lef_liberty_check"]["status"], "FAILED")
            self.assertIn("lef_library_id", result["checks"]["lef_liberty_check"]["error"])

    def test_export_creates_filtered_evidence_workbook_with_expected_sheets(self):
        model = build_workbook_model([review("IP_A", "MACRO_A", "/raw/a/LEF/a.lef")])
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "review.xlsx"
            export_review_excel(model, output)
            self.assertTrue(output.is_file())
            with zipfile.ZipFile(output) as archive:
                workbook = ET.fromstring(archive.read("xl/workbook.xml"))
                names = [item.attrib["name"] for item in workbook.findall(".//{*}sheet")]
                self.assertEqual(names, list(model))
                self.assertIn("xl/tables/table1.xml", archive.namelist())
                self.assertGreater(len(archive.read("xl/worksheets/sheet1.xml")), 100)

    def test_export_expands_long_text_rows_instead_of_clipping_answers(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "long.xlsx"
            export_review_excel({"问答": [{"问题": "为什么", "回答": "工程范围说明。" * 50}]}, output)
            with zipfile.ZipFile(output) as archive:
                sheet = ET.fromstring(archive.read("xl/worksheets/sheet1.xml"))
            data_row = next(row for row in sheet.findall(".//{*}row") if row.attrib.get("r") == "5")
            self.assertGreater(float(data_row.attrib["ht"]), 30)


if __name__ == "__main__":
    unittest.main()
