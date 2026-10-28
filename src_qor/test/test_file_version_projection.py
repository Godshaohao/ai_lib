import tempfile
import unittest
import json
import importlib.util
import zipfile
from pathlib import Path


class FileVersionProjectionTests(unittest.TestCase):
    def test_previous_candidate_is_uncertain_when_intervening_inventory_is_partial(self):
        from lib_guard.file_version_projection import build_projection
        versions = [{"id": f"V{i}", "path": f"/raw/V{i}", "delivery_order": i} for i in (1, 2, 3)]
        inventories = [{"version_id": "V1", "status": "COMPLETE", "files": ["/raw/V1/LEF/core.lef"]},
                       {"version_id": "V2", "status": "PARTIAL", "files": []},
                       {"version_id": "V3", "status": "COMPLETE", "files": ["/raw/V3/LEF/core.lef"]}]
        row = build_projection("IP", versions, inventories, None)["files"][0]
        self.assertEqual((row["latest"]["version"], row["latest"]["status"]), ("V3", "CONFIRMED"))
        self.assertEqual((row["previous"]["version"], row["previous"]["status"]), ("V1", "UNKNOWN_COVERAGE"))
        self.assertEqual(row["previous"]["uncertain_versions"], ["V2"])

    def test_string_delivery_orders_are_sorted_numerically(self):
        from lib_guard.file_version_projection import resolve_version_order
        versions = [{"id": f"V{i}", "delivery_order": str(i)} for i in (1, 2, 10)]
        self.assertEqual(resolve_version_order(versions)["ordered_ids"], ["V1", "V2", "V10"])

    def test_scope_change_drops_old_comparison_and_evidence(self):
        from lib_guard.file_version_projection import build_projection, reproject_projection
        versions = [{"id": f"V{i}", "path": f"/raw/V{i}", "delivery_order": i} for i in (1, 2, 3)]
        inventories = [{"version_id": f"V{i}", "status": "COMPLETE", "files": [f"/raw/V{i}/LEF/core.lef"]} for i in (1, 2, 3)]
        original = build_projection("IP", versions, inventories, None, base_version="V1", target_version="V2")
        original["snapshot_id"] = "raw-snapshot"
        original["files"][0]["comparison"].update({"content_status": "BYTE_DIFFERENT", "semantic_status": "COMPLETE", "comparison_evidence": {"old": True}, "evidence_refs": ["old.json"]})
        updated = reproject_projection(original, base_version="V2", target_version="V3")
        comparison = updated["files"][0]["comparison"]
        self.assertEqual(comparison["content_status"], "NOT_COMPARED")
        self.assertEqual(comparison["semantic_status"], "NOT_CHECKED")
        self.assertFalse(comparison.get("comparison_evidence"))
        self.assertEqual(comparison["evidence_refs"], [])
        self.assertEqual(original["files"][0]["comparison"]["content_status"], "BYTE_DIFFERENT")

    def test_explicit_delivery_order_ranks_file_latest_and_previous_by_distinct_versions(self):
        from lib_guard.file_version_projection import build_projection
        versions = [
            {"id": "V01", "path": "/raw/V01", "delivery_order": 1},
            {"id": "V02", "path": "/raw/V02", "delivery_order": 2},
            {"id": "V03", "path": "/raw/V03", "delivery_order": 3},
            {"id": "V04", "path": "/raw/V04", "delivery_order": 4},
            {"id": "V05", "path": "/raw/V05", "delivery_order": 5},
        ]
        inventories = [{"version_id": version["id"], "status": "COMPLETE", "files": []} for version in versions]
        inventories[0]["files"] = ["/raw/V01/LEF/core.lef"]
        inventories[2]["files"] = ["/raw/V03/LEF/core.lef"]
        inventories[4]["files"] = ["/raw/V05/LEF/core.lef"]

        result = build_projection("IP_A", versions, inventories, [])

        row = result["files"][0]
        self.assertEqual(result["version_order"]["basis"], "EXPLICIT")
        self.assertEqual(row["latest"], {"status": "CONFIRMED", "version": "V05", "source_path": "/raw/V05/LEF/core.lef"})
        self.assertEqual(row["previous"], {"status": "CONFIRMED", "version": "V03", "source_path": "/raw/V03/LEF/core.lef"})

    def test_partial_later_delivery_does_not_claim_observed_file_is_confirmed_latest(self):
        from lib_guard.file_version_projection import build_projection
        versions = [
            {"id": "V04", "path": "/raw/V04", "delivery_order": 4},
            {"id": "V05", "path": "/raw/V05", "delivery_order": 5},
        ]
        result = build_projection("IP_A", versions, [
            {"version_id": "V04", "status": "COMPLETE", "files": ["/raw/V04/LEF/sram.lef"]},
            {"version_id": "V05", "status": "PARTIAL", "files": []},
        ], [])

        row = result["files"][0]
        self.assertEqual(row["latest"]["status"], "UNKNOWN_COVERAGE")
        self.assertEqual(row["latest"]["version"], "V04")

    def test_date_hint_requires_unique_dates_and_does_not_use_registry_order(self):
        from lib_guard.file_version_projection import build_projection
        versions = [
            {"id": "release_20261002", "path": "/raw/B"},
            {"id": "release_20261001", "path": "/raw/A"},
        ]
        result = build_projection("IP_A", versions, [
            {"version_id": "release_20261001", "status": "COMPLETE", "files": ["/raw/A/LEF/a.lef"]},
            {"version_id": "release_20261002", "status": "COMPLETE", "files": ["/raw/B/LEF/a.lef"]},
        ], [])
        self.assertEqual(result["version_order"]["basis"], "DATE_HINT")
        self.assertEqual(result["files"][0]["latest"]["version"], "release_20261002")

    def test_same_day_versions_have_unknown_order_and_keep_all_occurrences(self):
        from lib_guard.file_version_projection import build_projection
        versions = [
            {"id": "20261001_a", "path": "/raw/A"},
            {"id": "20261001_b", "path": "/raw/B"},
        ]
        result = build_projection("IP_A", versions, [
            {"version_id": "20261001_a", "status": "COMPLETE", "files": ["/raw/A/LEF/a.lef"]},
            {"version_id": "20261001_b", "status": "COMPLETE", "files": ["/raw/B/LEF/a.lef"]},
        ], [])
        row = result["files"][0]
        self.assertEqual(result["version_order"]["status"], "UNKNOWN")
        self.assertEqual(row["latest"]["status"], "UNKNOWN_ORDER")
        self.assertEqual([item["version"] for item in row["occurrences"]], ["20261001_a", "20261001_b"])

    def test_only_one_occurrence_has_no_previous(self):
        from lib_guard.file_version_projection import build_projection
        result = build_projection("IP_A", [{"id": "V05", "path": "/raw/V05", "delivery_order": 5}], [
            {"version_id": "V05", "status": "COMPLETE", "files": ["/raw/V05/LEF/new_io.lef"]},
        ], [])
        row = result["files"][0]
        self.assertEqual(row["latest"]["status"], "CONFIRMED")
        self.assertEqual(row["previous"]["status"], "NONE")

    def test_duplicate_raw_occurrence_does_not_choose_latest_representative(self):
        from lib_guard.file_version_projection import build_projection
        result = build_projection("IP_A", [
            {"id": "V1", "path": "/raw/V1", "delivery_order": 1},
        ], [{"version_id": "V1", "status": "COMPLETE", "files": [
            "/raw/V1/LEF/a.lef", "/raw/V1/LEF/a.lef"
        ]}], [])
        row = result["files"][0]
        self.assertEqual(row["identity_status"], "AMBIGUOUS")
        self.assertEqual(row["latest"]["status"], "AMBIGUOUS")

    def test_projection_display_labels_preserve_uncertainty(self):
        from lib_guard.display_labels import projection_label
        self.assertEqual(projection_label("PRESENT", "presence"), "已提供")
        self.assertEqual(projection_label("ABSENT_VERIFIED", "presence"), "未发现")
        self.assertEqual(projection_label("UNKNOWN", "presence"), "无法确认")
        self.assertEqual(projection_label("NOT_SELECTED", "presence"), "未选择版本")
        self.assertEqual(projection_label("NOT_CHECKED", "semantic"), "未做技术检查")
        self.assertEqual(projection_label("CONFIRMED", "previous"), "已确认")
        self.assertEqual(projection_label("CONTEXT_REQUIRED", "coverage"), "需要指定正式阶段")
        self.assertEqual(projection_label("FAILED", "semantic"), "检查失败")
        self.assertEqual(projection_label("FUTURE_STATE", "presence"), "未识别状态（FUTURE_STATE）")

    @unittest.skipUnless(importlib.util.find_spec("xlsxwriter"), "需要已安装的 XlsxWriter")
    def test_batch_missing_file_retains_successful_pair_without_promoting_latest(self):
        from lib_guard.file_version_projection import build_projection, publish_projection
        from lib_guard.review_runner import run
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            versions, inventories = [], []
            for version in ("V1", "V2"):
                folder = root / version
                paths = []
                for name in ("a.lef", "b.lef"):
                    path = folder / "LEF" / name
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text("VERSION 5.8 ;\nMACRO A\nEND A\nEND LIBRARY\n", encoding="utf-8")
                    paths.append(str(path))
                versions.append({"id": version, "path": str(folder)})
                inventories.append({"version_id": version, "files": paths, "status": "COMPLETE"})
            source = publish_projection(root / "snapshots", build_projection("IP_A", versions, inventories, [], base_version="V1", target_version="V2"))
            source_path = root / "snapshots" / "runs" / source["snapshot_id"] / "projection.json"
            (root / "V2" / "LEF" / "b.lef").unlink()
            config = {"ips": [{"id": "IP_A", "raw_version": "V2", "projection_json": str(source_path),
                "checks": {"lef_review": {"pairs": [{"file_key": "lef:a.lef"}, {"file_key": "lef:b.lef"}]}}}]}
            review = run(config, root / "output")[0][0]
            self.assertEqual(review["execution_status"], "INCOMPLETE")
            pairs = review["checks"]["lef_review"]["result"]["pairs"]
            self.assertEqual([pair["execution_status"] for pair in pairs], ["COMPLETE", "FAILED"])
            rows = review["file_version_projection"]["files"]
            self.assertEqual(rows[0]["comparison"]["content_status"], "BYTE_SAME")
            self.assertEqual(rows[1]["comparison"]["semantic_status"], "FAILED")
            self.assertFalse((Path(review["library_dir"]) / "latest.xlsx").exists())

    @unittest.skipUnless(importlib.util.find_spec("xlsxwriter"), "需要已安装的 XlsxWriter")
    def test_selected_matrix_pairs_produce_scoped_batch_and_excel(self):
        from lib_guard.file_version_projection import build_projection, publish_projection
        from lib_guard.review_runner import run
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            versions, inventories = [], []
            for version in ("V1", "V2"):
                version_root = root / version
                paths = []
                for name in ("a.lef", "b.lef"):
                    path = version_root / "LEF" / name
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text("VERSION 5.8 ;\nMACRO A\n  SIZE 1 BY " + ("2" if version == "V1" else "3") + " ;\nEND A\nEND LIBRARY\n", encoding="utf-8")
                    paths.append(str(path))
                versions.append({"id": version, "path": str(version_root)})
                inventories.append({"version_id": version, "root": str(version_root), "files": paths, "status": "COMPLETE"})
            source = publish_projection(root / "snapshots", build_projection("IP_A", versions, inventories, [], base_version="V1", target_version="V2"))
            source_path = root / "snapshots" / "runs" / source["snapshot_id"] / "projection.json"
            source["source_snapshot_id"] = "original_raw_inventory"
            source_path.write_text(json.dumps(source), encoding="utf-8")
            config = {"ips": [{"id": "IP_A", "raw_version": "V2", "projection_json": str(source_path),
                "checks": {"lef_review": {"pairs": [{"file_key": "lef:a.lef"}, {"file_key": "lef:b.lef"}]}}}]}
            reviews, _ = run(config, root / "output")
            review = reviews[0]
            self.assertEqual(review["checks"]["lef_review"]["status"], "COMPLETE")
            self.assertEqual(len(review["checks"]["lef_review"]["result"]["pairs"]), 2)
            self.assertEqual(len(review["checks"]["lef_review"]["input_identity"]["sources"]), 4)
            updated = review["file_version_projection"]
            self.assertEqual(updated["source_snapshot_id"], "original_raw_inventory")
            self.assertEqual(updated["input_snapshot_id"], source["snapshot_id"])
            self.assertNotEqual(updated["snapshot_id"], source["snapshot_id"])
            self.assertEqual([row["comparison"]["content_status"] for row in updated["files"]], ["BYTE_DIFFERENT", "BYTE_DIFFERENT"])
            self.assertTrue(all(row["comparison"]["evidence_refs"] for row in updated["files"]))
            self.assertGreaterEqual(review["summary"]["confirmed_changes"], 2)
            self.assertNotEqual(review["quality_status"], "NO_FINDINGS_WITHIN_SCOPE")
            self.assertEqual(json.loads(source_path.read_text())["files"][0]["comparison"]["content_status"], "NOT_COMPARED")
            from lib_guard.review_runner import _lef_rows
            rows = _lef_rows(review)
            self.assertEqual({row['LEF文件'] for row in rows}, {str(root / 'V2' / 'LEF' / 'a.lef'), str(root / 'V2' / 'LEF' / 'b.lef')})
            from lib_guard.review_runner import build_workbook_model
            macro_rows = build_workbook_model([review])["08-LEF宏"]
            self.assertTrue(macro_rows)
            self.assertEqual({row["文件键"] for row in macro_rows}, {"lef:a.lef", "lef:b.lef"})
            self.assertTrue(all(row["批次Pair"] for row in macro_rows))
            with zipfile.ZipFile(Path(review["run_dir"]) / "ip_review.xlsx") as workbook:
                strings = workbook.read("xl/sharedStrings.xml").decode()
                self.assertIn(updated["snapshot_id"], strings)
                self.assertIn(str(root / 'V2' / 'LEF' / 'a.lef'), strings)
                self.assertIn(str(root / 'V2' / 'LEF' / 'b.lef'), strings)

    @unittest.skipUnless(importlib.util.find_spec("xlsxwriter"), "需要已安装的 XlsxWriter")
    def test_explicit_projection_is_copied_into_review_and_excel(self):
        from lib_guard.review_runner import run
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            projection = root / "projection.json"
            projection.write_text(json.dumps({"schema_version": "file_version_projection.v1", "snapshot_id": "snapshot_test",
                "library_id": "IP_A", "scope": {"base_version": "V1", "target_version": "V2"},
                "coverage": {"raw_inventory": "PARTIAL"}, "files": [{"view": "lef", "file_key": "lef:a.lef",
                    "display_name": "a.lef", "identity_status": "EXACT_RELATIVE_PATH", "occurrences": [],
                    "formal_usage": {"approved_effective_status": "NOT_CONFIGURED"},
                    "comparison": {"target_presence": "UNKNOWN", "content_status": "NOT_COMPARED", "semantic_status": "NOT_CHECKED"}}]}), encoding="utf-8")
            macro = root / "macro.json"
            macro.write_text(json.dumps({"status": "COMPLETE", "macro_index": {"macros": {}}}), encoding="utf-8")
            reviews, _ = run({"ips": [{"id": "IP_A", "raw_version": "V2", "projection_json": str(projection),
                                      "checks": {"macro_index": {"report_json": str(macro)}}}]}, root / "output")
            run_dir = Path(reviews[0]["run_dir"])
            record = json.loads((run_dir / "review_result.json").read_text(encoding="utf-8"))
            self.assertEqual(record["file_version_projection"]["snapshot_id"], "snapshot_test")
            attempt = json.loads((run_dir.parents[1] / "latest_attempt.json").read_text(encoding="utf-8"))
            self.assertEqual(attempt["quality_status"], record["quality_status"])
            self.assertEqual(json.loads((run_dir / record["file_version_projection"]["result_ref"]).read_text())["snapshot_id"], "snapshot_test")
            with zipfile.ZipFile(run_dir / "ip_review.xlsx") as workbook:
                self.assertIn("snapshot_test", workbook.read("xl/sharedStrings.xml").decode())

    @unittest.skipUnless(importlib.util.find_spec("xlsxwriter"), "需要已安装的 XlsxWriter")
    def test_workbook_writes_matrix_snapshot_and_unknown(self):
        from lib_guard.review_runner import build_workbook_model
        from lib_guard.export_review_excel import export_review_excel
        projection = {"snapshot_id": "snapshot_test", "scope": {"base_version": "V1", "target_version": "V2"},
                      "coverage": {"raw_inventory": "PARTIAL"}, "files": [{"view": "lef", "file_key": "lef:a.lef",
                      "display_name": "a.lef", "occurrences": [], "identity_status": "EXACT_RELATIVE_PATH",
                      "formal_usage": {"approved_effective_status": "NOT_CONFIGURED"},
                      "comparison": {"target_presence": "UNKNOWN", "content_status": "NOT_COMPARED", "semantic_status": "NOT_CHECKED"}}]}
        model = build_workbook_model([{"ip": {"id": "IP_A"}, "checks": {}, "file_version_projection": projection}])
        with tempfile.TemporaryDirectory() as temp:
            path = export_review_excel(model, Path(temp) / "review.xlsx")
            with zipfile.ZipFile(path) as workbook:
                self.assertIn("文件版本矩阵", workbook.read("xl/workbook.xml").decode())
                strings = workbook.read("xl/sharedStrings.xml").decode()
                for value in ("snapshot_test", "无法确认", "未比较内容", "未核实批准状态"):
                    self.assertIn(value, strings)

    def test_explicit_review_projection_must_match_ip_and_target(self):
        from lib_guard.review_runner import run_review
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            projection = root / "projection.json"
            projection.write_text(json.dumps({"schema_version": "file_version_projection.v1", "snapshot_id": "s1",
                "library_id": "IP_A", "scope": {"target_version": "V2"}, "files": []}), encoding="utf-8")
            ip = {"id": "IP_A", "raw_version": "V2", "projection_json": str(projection), "checks": {}}
            result = run_review({"ips": [ip]}, root / "out")[0]
            self.assertEqual(result["file_version_projection"]["snapshot_id"], "s1")
            ip["raw_version"] = "V3"
            with self.assertRaisesRegex(ValueError, "目标版本"):
                run_review({"ips": [ip]}, root / "out")

    def test_explicit_projection_rejects_unrelated_lef_pair(self):
        from lib_guard.review_runner import run_review
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            projection = root / "projection.json"
            projection.write_text(json.dumps({"schema_version": "file_version_projection.v1", "snapshot_id": "s1",
                "library_id": "IP_A", "scope": {"base_version": "V1", "target_version": "V2"}, "files": [{
                    "view": "lef", "identity_status": "EXACT_RELATIVE_PATH", "occurrences": [
                        {"version": "V1", "source_path": str(root / "V1" / "a.lef")},
                        {"version": "V2", "source_path": str(root / "V2" / "a.lef")}]}]}), encoding="utf-8")
            ip = {"id": "IP_A", "raw_version": "V2", "projection_json": str(projection), "checks": {
                "lef_review": {"old_file": str(root / "other.lef"), "new_file": str(root / "other2.lef")}}}
            with self.assertRaisesRegex(ValueError, "LEF.*投影"):
                run_review({"ips": [ip]}, root / "out")

    def test_workbook_matrix_uses_projection_snapshot_and_status(self):
        from lib_guard.review_runner import build_workbook_model
        projection = {"snapshot_id": "snapshot_test", "library_id": "IP_A", "scope": {"base_version": "V1", "target_version": "V2"},
                      "coverage": {"raw_inventory": "PARTIAL"}, "files": [{
                          "file_key": "lef:a.lef", "view": "lef", "display_name": "a.lef",
                          "identity_status": "EXACT_RELATIVE_PATH", "occurrences": [],
                          "formal_usage": {"observation_status": "NOT_OBSERVED", "approved_effective_status": "NOT_CONFIGURED"},
                          "comparison": {"base_presence": "PRESENT", "target_presence": "UNKNOWN", "content_status": "NOT_COMPARED", "semantic_status": "NOT_CHECKED"},
                      }]}
        model = build_workbook_model([{"ip": {"id": "IP_A"}, "checks": {}, "file_version_projection": projection}])
        row = model["文件版本矩阵"][0]
        self.assertEqual(row["快照 ID"], "snapshot_test")
        self.assertEqual(row["目标存在性"], "无法确认")
        self.assertEqual(row["内容状态"], "未比较内容")

    def test_publish_keeps_history_and_independent_latest_pointer(self):
        from lib_guard.file_version_projection import publish_projection
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            first = publish_projection(root, {"schema_version": "file_version_projection.v1", "library_id": "IP_A"})
            second = publish_projection(root, {"schema_version": "file_version_projection.v1", "library_id": "IP_A"})
            self.assertNotEqual(first["snapshot_id"], second["snapshot_id"])
            self.assertTrue((root / "runs" / first["snapshot_id"] / "projection.json").is_file())
            self.assertEqual(json.loads((root / "latest.json").read_text())["snapshot_id"], second["snapshot_id"])

    def test_exact_paths_and_partial_inventory_preserve_unknown(self):
        from lib_guard.file_version_projection import build_projection

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            versions = [{"id": "V1", "path": str(root / "V1")},
                        {"id": "V2", "path": str(root / "V2")}]
            old = root / "V1" / "LEF" / "a.lef"
            new = root / "V2" / "LEF" / "a.lef"
            extra = root / "V1" / "LIB" / "tt.lib"
            inventories = [{"version_id": "V1", "root": str(root / "V1"), "files": [str(old), str(extra)], "status": "COMPLETE"},
                           {"version_id": "V2", "root": str(root / "V2"), "files": [str(new)], "status": "PARTIAL"}]
            formal = [{"view": "lef", "source_path": str(old), "published_path": "/nl/LEF/a.lef"}]
            result = build_projection("IP_A", versions, inventories, formal,
                                      base_version="V1", target_version="V2", formal_stage="NL")
            rows = {row["display_name"]: row for row in result["files"]}
            self.assertEqual(rows["a.lef"]["identity_status"], "EXACT_RELATIVE_PATH")
            self.assertEqual(rows["a.lef"]["comparison"]["content_status"], "NOT_COMPARED")
            self.assertEqual(rows["a.lef"]["formal_usage"]["source_version"], "V1")
            self.assertEqual(rows["tt.lib"]["comparison"]["target_presence"], "UNKNOWN")
            self.assertEqual(rows["tt.lib"]["identity_status"], "UNRESOLVED")
            self.assertEqual(rows["a.lef"]["formal_usage"]["approved_effective_status"], "NOT_CONFIGURED")
            self.assertEqual(result["coverage"]["raw_inventory"], "PARTIAL")

    def test_same_basename_different_directories_are_not_merged(self):
        from lib_guard.file_version_projection import build_projection

        versions = [{"id": "V1", "path": "/raw/V1"}, {"id": "V2", "path": "/raw/V2"}]
        inventories = [{"version_id": "V1", "root": "/raw/V1", "files": ["/raw/V1/LEF/a/x.lef"], "status": "COMPLETE"},
                       {"version_id": "V2", "root": "/raw/V2", "files": ["/raw/V2/LEF/b/x.lef"], "status": "COMPLETE"}]
        result = build_projection("IP_A", versions, inventories, [], base_version="V1", target_version="V2")
        self.assertEqual(len(result["files"]), 2)
        self.assertTrue(all(row["comparison"]["semantic_status"] == "NOT_CHECKED" for row in result["files"]))

    def test_case_distinct_paths_do_not_form_a_pair(self):
        from lib_guard.file_version_projection import build_projection
        versions = [{"id": "V1", "path": "/raw/V1"}, {"id": "V2", "path": "/raw/V2"}]
        inventories = [{"version_id": "V1", "files": ["/raw/V1/LEF/Top.lef"], "status": "COMPLETE"},
                       {"version_id": "V2", "files": ["/raw/V2/LEF/top.lef"], "status": "COMPLETE"}]
        projection = build_projection("IP_A", versions, inventories, [], base_version="V1", target_version="V2")
        self.assertEqual(len(projection["files"]), 2)
        self.assertTrue(all(row["identity_status"] != "EXACT_RELATIVE_PATH" for row in projection["files"]))

    def test_missing_formal_snapshot_is_not_reported_as_not_observed(self):
        from lib_guard.file_version_projection import build_projection
        versions = [{"id": "V1", "path": "/raw/V1"}]
        inventories = [{"version_id": "V1", "files": ["/raw/V1/LEF/top.lef"], "status": "COMPLETE"}]
        result = build_projection("IP_A", versions, inventories, None, target_version="V1")
        self.assertEqual(result["coverage"]["formal_inventory"], "NOT_AVAILABLE")
        self.assertEqual(result["files"][0]["formal_usage"]["observation_status"], "UNKNOWN")

    def test_unregistered_formal_source_remains_visible_without_raw_pairing(self):
        from lib_guard.file_version_projection import build_projection
        result = build_projection("IP_A", [], [], [{"view": "lef", "published_path": "/nl/a.lef",
                                                    "source_path": "/outside/a.lef"}], formal_stage="NL")
        self.assertEqual(len(result["files"]), 1)
        self.assertEqual(result["files"][0]["identity_status"], "UNRESOLVED")
        self.assertEqual(result["files"][0]["formal_usage"]["source_path"], "/outside/a.lef")

    def test_display_name_preserves_source_filename_case(self):
        from lib_guard.file_version_projection import build_projection
        versions = [{"id": "V1", "path": "/raw/V1"}]
        inventories = [{"version_id": "V1", "status": "COMPLETE", "files": ["/raw/V1/LIB/Cell_TT.lib"]}]
        result = build_projection("IP_A", versions, inventories, [], target_version="V1")
        self.assertEqual(result["files"][0]["display_name"], "Cell_TT.lib")

    def test_reproject_keeps_inventory_snapshot_and_changes_only_delivery_scope(self):
        from lib_guard.file_version_projection import build_projection, reproject_projection

        source = build_projection("IP_A", [
            {"id": "V1", "path": "/raw/V1", "delivery_order": 1},
            {"id": "V2", "path": "/raw/V2", "delivery_order": 2},
            {"id": "V3", "path": "/raw/V3", "delivery_order": 3},
        ], [
            {"version_id": "V1", "status": "COMPLETE", "files": ["/raw/V1/LEF/core.lef"]},
            {"version_id": "V2", "status": "COMPLETE", "files": []},
            {"version_id": "V3", "status": "COMPLETE", "files": ["/raw/V3/LEF/core.lef"]},
        ], [], base_version="V1", target_version="V2")
        source["snapshot_id"] = "snapshot_inventory"

        projected = reproject_projection(source, base_version="V1", target_version="V3")

        self.assertEqual(projected["source_snapshot_id"], "snapshot_inventory")
        self.assertEqual(projected["scope"]["base_version"], "V1")
        self.assertEqual(projected["scope"]["target_version"], "V3")
        self.assertEqual(projected["files"][0]["comparison"]["delivery_relation"], "READY_TO_COMPARE")
        self.assertEqual(projected["files"][0]["occurrences"], source["files"][0]["occurrences"])

    def test_file_capabilities_separate_locating_from_pair_comparison(self):
        from lib_guard.file_version_projection import build_projection

        versions = [
            {"id": "V1", "path": "/raw/V1", "delivery_order": 1},
            {"id": "V2", "path": "/raw/V2", "delivery_order": 2},
        ]
        inventories = [
            {"version_id": "V1", "status": "COMPLETE", "files": ["/raw/V1/LEF/a.lef"]},
            {"version_id": "V2", "status": "COMPLETE", "files": ["/raw/V2/LEF/a.lef"]},
        ]

        latest_only = build_projection("IP_A", versions, inventories, None)
        paired = build_projection("IP_A", versions, inventories, None, base_version="V1", target_version="V2")

        latest_caps = latest_only["files"][0]["capabilities"]
        paired_caps = paired["files"][0]["capabilities"]
        self.assertTrue(latest_caps["locatable"])
        self.assertTrue(latest_caps["lef_checkable"])
        self.assertFalse(latest_caps["content_comparable"])
        self.assertEqual(latest_caps["reason"], "BASE_TARGET_REQUIRED")
        self.assertTrue(paired_caps["locatable"])
        self.assertTrue(paired_caps["lef_checkable"])
        self.assertTrue(paired_caps["content_comparable"])


if __name__ == "__main__":
    unittest.main()
