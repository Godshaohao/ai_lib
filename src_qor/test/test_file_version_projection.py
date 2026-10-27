import tempfile
import unittest
import json
import importlib.util
import zipfile
from pathlib import Path


class FileVersionProjectionTests(unittest.TestCase):
    def test_projection_display_labels_preserve_uncertainty(self):
        from lib_guard.display_labels import projection_label
        self.assertEqual(projection_label("PRESENT", "presence"), "已提供")
        self.assertEqual(projection_label("ABSENT_VERIFIED", "presence"), "未发现")
        self.assertEqual(projection_label("UNKNOWN", "presence"), "无法确认")
        self.assertEqual(projection_label("NOT_SELECTED", "presence"), "未选择版本")
        self.assertEqual(projection_label("NOT_CHECKED", "semantic"), "未做技术检查")
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
            self.assertEqual(rows[0]["comparison"]["content_status"], "SAME")
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
            config = {"ips": [{"id": "IP_A", "raw_version": "V2", "projection_json": str(source_path),
                "checks": {"lef_review": {"pairs": [{"file_key": "lef:a.lef"}, {"file_key": "lef:b.lef"}]}}}]}
            reviews, _ = run(config, root / "output")
            review = reviews[0]
            self.assertEqual(review["checks"]["lef_review"]["status"], "COMPLETE")
            self.assertEqual(len(review["checks"]["lef_review"]["result"]["pairs"]), 2)
            self.assertEqual(len(review["checks"]["lef_review"]["input_identity"]["sources"]), 4)
            updated = review["file_version_projection"]
            self.assertEqual(updated["source_snapshot_id"], source["snapshot_id"])
            self.assertNotEqual(updated["snapshot_id"], source["snapshot_id"])
            self.assertEqual([row["comparison"]["content_status"] for row in updated["files"]], ["DIFF", "DIFF"])
            self.assertTrue(all(row["comparison"]["evidence_refs"] for row in updated["files"]))
            self.assertGreaterEqual(review["summary"]["confirmed_changes"], 2)
            self.assertNotEqual(review["quality_status"], "NO_FINDINGS_WITHIN_SCOPE")
            self.assertEqual(json.loads(source_path.read_text())["files"][0]["comparison"]["content_status"], "NOT_COMPARED")
            with zipfile.ZipFile(Path(review["run_dir"]) / "ip_review.xlsx") as workbook:
                self.assertIn(updated["snapshot_id"], workbook.read("xl/sharedStrings.xml").decode())

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


if __name__ == "__main__":
    unittest.main()
