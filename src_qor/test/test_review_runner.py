import tempfile
import unittest
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET
from unittest.mock import patch

from lib_guard.review_runner import _qa_rows, _review_summary, _write_latest_if_newer, build_workbook_model, run, run_review
from lib_guard.lef_liberty_check import analyze_many
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

    def test_failed_formal_check_does_not_answer_inventory_is_empty(self):
        item = {"ip": {"id": "IP_A"}, "checks": {"formal_nl": {
            "selected": True, "status": "FAILED", "error": "Permission denied", "result": {}
        }}}

        rows = _qa_rows(item)

        self.assertEqual(len(rows), 1)
        self.assertIn("未生成", rows[0]["回答"])
        self.assertNotIn("清单为空", rows[0]["回答"])

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

            with patch("lib_guard.review_runner.export_review_excel", side_effect=OSError("disk full")):
                with self.assertRaisesRegex(OSError, "disk full"):
                    run(config, root / "output")

            self.assertEqual(__import__("json").loads(latest_path.read_text(encoding="utf-8")), old_latest)
            records = list(latest_path.parent.glob("runs/*/review_result.json"))
            self.assertEqual(len(records), 1)

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
                record = __import__("json").loads(result_file.read_text(encoding="utf-8"))
                self.assertEqual(record["execution_status"], "COMPLETE")
                self.assertEqual(record["requested_checks"], ["macro_index"])
                self.assertEqual(record["checks"]["formal_nl"]["execution_status"], "NOT_RUN")
                with zipfile.ZipFile(result_file.parent / "ip_review.xlsx") as archive:
                    workbook = ET.fromstring(archive.read("xl/workbook.xml"))
                    self.assertEqual([item.attrib["name"] for item in workbook.findall(".//{*}sheet")],
                                     ["00-概览", "01-工程检查", "02-执行记录", "03-问答", "04-关注项",
                                      "05-MacroView", "06-MacroView文件"])
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
            self.assertIn("最近成功", page)

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
        self.assertEqual(len(checklist), 10)
        self.assertEqual(checklist[0]["工程检查主题"], "RAW 版本与文件盘点")
        self.assertEqual(checklist[-1]["工程检查主题"], "文档更新 Delta")
        self.assertIn("工程覆盖", checklist[0])
        self.assertIn("本次执行", checklist[0])

    def test_only_selected_checks_add_details_and_questions(self):
        item = review("IP_A", "MACRO_A", "/raw/a/LEF/a.lef")
        item["checks"].pop("formal_nl")
        model = build_workbook_model([item])

        self.assertEqual(list(model), ["00-概览", "01-工程检查", "02-执行记录", "03-问答", "04-关注项",
                                       "05-MacroView", "06-MacroView文件"])
        self.assertEqual(len(model["03-问答"]), 1)
        self.assertIn("Macro", model["03-问答"][0]["问题"])

    def test_failed_check_is_isolated_to_its_ip(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            good = root / "macro.json"
            good.write_text('{"status":"COMPLETE","macro_index":{"macros":{}}}', encoding="utf-8")
            config = {
                "_config_path": str(root / "config.json"),
                "ips": [
                    {"id": "IP_BAD", "checks": {"formal_nl": {"report_json": "missing.json"}}},
                    {"id": "IP_GOOD", "checks": {"macro_index": {"report_json": str(good)}}},
                ],
            }
            results = run_review(config, root / "output")
            self.assertEqual(results[0]["checks"]["formal_nl"]["status"], "FAILED")
            self.assertEqual(results[1]["checks"]["macro_index"]["status"], "COMPLETE")

    def test_unknown_check_name_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "不支持的检查名"):
            run_review({"ips": [{"id": "IP_A", "checks": {"release_gate": {}}}]}, tempfile.mkdtemp())

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
