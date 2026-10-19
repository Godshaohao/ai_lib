from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from lib_guard.summary.readiness import build_release_readiness
from lib_guard.render.version_review_model import build_ip_user_view_model
from lib_guard.render.version_review_render import render_review_report


class DeliveryRequirementsTest(unittest.TestCase):
    def _scan(self, files, *, library_type="ip"):
        root = Path(tempfile.mkdtemp())
        (root / "summary").mkdir()
        (root / "scan_meta.json").write_text(
            json.dumps({"library_type": library_type, "library_name": "demo", "release_version": "v1", "scan_mode": "release"}),
            encoding="utf-8",
        )
        (root / "file_inventory.json").write_text(json.dumps({"files": files}), encoding="utf-8")
        (root / "parser_manifest.json").write_text(json.dumps({"files": []}), encoding="utf-8")
        (root / "scan_issues.json").write_text(json.dumps({"issues": []}), encoding="utf-8")
        (root / "summary" / "parser_quality.json").write_text(json.dumps({}), encoding="utf-8")
        return root

    def _set_parser_manifest(self, scan, entries):
        (scan / "parser_manifest.json").write_text(
            json.dumps({"files": entries}), encoding="utf-8"
        )

    def _write_parser_result(self, scan, path):
        result = scan / path
        result.parent.mkdir(parents=True, exist_ok=True)
        result.write_text("{}\n", encoding="utf-8")

    def _update_scan_meta(self, scan, **values):
        path = scan / "scan_meta.json"
        meta = json.loads(path.read_text(encoding="utf-8"))
        meta.update(values)
        path.write_text(json.dumps(meta), encoding="utf-8")

    def _lef_readiness(self, scan):
        return build_release_readiness(
            scan,
            {
                "required_views": {"ip": ["lef"]},
                "validation_levels": {"lef": "parsed_required"},
            },
        )

    def test_required_view_without_parser_tasks_is_blocked_with_missing_file(self):
        scan = self._scan([{"path": "lef/cell.lef", "file_type": "lef"}])

        result = self._lef_readiness(scan)

        view = result["components"][0]["required_view_results"]["lef"]
        self.assertEqual(view["status"], "BLOCK")
        self.assertIn("lef/cell.lef", view["message"])
        self.assertEqual(result["required_view_status"], "BLOCK")
        self.assertEqual(result["bundle_status"], "BLOCK")

    def test_missing_required_view_is_blocked(self):
        scan = self._scan([{"path": "rtl/top.v", "file_type": "verilog"}])

        result = self._lef_readiness(scan)
        view = result["components"][0]["required_view_results"]["lef"]

        self.assertFalse(view["found"])
        self.assertEqual(view["status"], "BLOCK")
        self.assertEqual(result["required_view_status"], "BLOCK")
        self.assertEqual(result["bundle_status"], "BLOCK")

    def test_required_view_requires_parser_evidence_for_each_file(self):
        scan = self._scan([
            {"path": "lef/cell_a.lef", "file_type": "lef"},
            {"path": "lef/cell_b.lef", "file_type": "lef"},
        ])
        self._set_parser_manifest(scan, [{
            "file": "lef/cell_a.lef",
            "file_type": "lef",
            "parser_tasks": [{"parser_name": "LefParser", "result_status": "PASS", "result_path": "parser_results/lef/cell_a.json"}],
        }])
        self._write_parser_result(scan, "parser_results/lef/cell_a.json")

        result = self._lef_readiness(scan)

        view = result["components"][0]["required_view_results"]["lef"]
        self.assertEqual(view["status"], "BLOCK")
        self.assertIn("lef/cell_b.lef", view["message"])
        self.assertEqual(view["evidence_counts"], {"total": 2, "satisfied": 1, "incomplete": 1})

    def test_required_view_rejects_non_success_parser_statuses(self):
        for status in ("SKIPPED", "UNSUPPORTED", "METADATA_ONLY", "FAILED", "PASS_EMPTY", "UNKNOWN"):
            with self.subTest(status=status):
                scan = self._scan([{"path": "lef/cell.lef", "file_type": "lef"}])
                self._set_parser_manifest(scan, [{
                    "file": "lef/cell.lef",
                    "file_type": "lef",
                    "parser_tasks": [{"parser_name": "LefParser", "result_status": status}],
                }])

                result = self._lef_readiness(scan)

                view = result["components"][0]["required_view_results"]["lef"]
                self.assertEqual(view["status"], "BLOCK", status)
                self.assertIn(status, view["message"])

    def test_pass_status_without_result_artifact_is_incomplete(self):
        scan = self._scan([{"path": "lef/cell.lef", "file_type": "lef"}])
        self._set_parser_manifest(scan, [{
            "file": "lef/cell.lef",
            "file_type": "lef",
            "parser_tasks": [{"parser_name": "LefParser", "result_status": "PASS", "result_path": "parser_results/lef/missing.json"}],
        }])

        result = self._lef_readiness(scan)
        view = result["components"][0]["required_view_results"]["lef"]

        self.assertEqual(view["status"], "BLOCK")
        self.assertIn("缺少解析结果文件", view["message"])

    def test_parser_result_path_outside_scan_directory_is_not_accepted(self):
        scan = self._scan([{"path": "lef/cell.lef", "file_type": "lef"}])
        outside = scan.parent / "outside_parser_result.json"
        outside.write_text("{}\n", encoding="utf-8")
        self._set_parser_manifest(scan, [{
            "file": "lef/cell.lef",
            "file_type": "lef",
            "parser_tasks": [{"parser_name": "LefParser", "result_status": "PASS", "result_path": "../outside_parser_result.json"}],
        }])

        result = self._lef_readiness(scan)
        view = result["components"][0]["required_view_results"]["lef"]

        self.assertEqual(view["status"], "BLOCK")
        self.assertIn("缺少解析结果文件", view["message"])

    def test_duplicate_inventory_paths_do_not_inflate_view_coverage(self):
        scan = self._scan([
            {"path": "lef/cell.lef", "file_type": "lef"},
            {"path": "lef/./cell.lef", "file_type": "lef"},
        ])
        self._set_parser_manifest(scan, [{
            "file": "lef/cell.lef",
            "file_type": "lef",
            "parser_tasks": [{"parser_name": "LefParser", "result_status": "PASS", "result_path": "parser_results/lef/cell.json"}],
        }])
        self._write_parser_result(scan, "parser_results/lef/cell.json")

        result = self._lef_readiness(scan)
        view = result["components"][0]["required_view_results"]["lef"]

        self.assertEqual(view["status"], "PASS")
        self.assertEqual(view["evidence_counts"]["total"], 1)

    def test_required_view_passes_when_every_file_has_successful_parser_evidence(self):
        scan = self._scan([
            {"path": "lef/cell_a.lef", "file_type": "lef"},
            {"path": "lef/cell_b.lef", "file_type": "lef"},
        ])
        self._set_parser_manifest(scan, [
            {
                "file": path,
                "file_type": "lef",
                "parser_tasks": [{"parser_name": "LefParser", "result_status": "PASS", "result_path": f"parser_results/lef/{path.split('/')[-1]}.json"}],
            }
            for path in ("lef/cell_a.lef", "lef/cell_b.lef")
        ])
        for path in ("lef/cell_a.lef", "lef/cell_b.lef"):
            self._write_parser_result(scan, f"parser_results/lef/{path.split('/')[-1]}.json")

        result = self._lef_readiness(scan)

        view = result["components"][0]["required_view_results"]["lef"]
        self.assertEqual(view["status"], "PASS")
        self.assertEqual(view["evidence_counts"], {"total": 2, "satisfied": 2, "incomplete": 0})

    def test_liberty_alias_in_manifest_matches_canonical_inventory_type(self):
        scan = self._scan([{"path": "lib/cell.lib", "file_type": "liberty"}])
        result_path = "parser_results/liberty/cell.json"
        self._set_parser_manifest(scan, [{
            "file": "./lib\\cell.lib",
            "file_type": "lib",
            "parser_tasks": [{"parser_name": "LibertyParser", "result_status": "PASS", "result_path": result_path}],
        }])
        self._write_parser_result(scan, result_path)
        result = build_release_readiness(
            scan,
            {"required_views": {"ip": ["liberty"]}, "validation_levels": {"liberty": "parsed_required"}},
        )

        view = result["components"][0]["required_view_results"]["liberty"]
        self.assertEqual(view["status"], "PASS")

    def test_one_failed_parser_task_is_not_hidden_by_another_success(self):
        scan = self._scan([{"path": "lef/cell.lef", "file_type": "lef"}])
        result_path = "parser_results/lef/cell.json"
        self._set_parser_manifest(scan, [{
            "file": "lef/cell.lef",
            "file_type": "lef",
            "parser_tasks": [
                {"parser_name": "LefParser", "result_status": "PASS", "result_path": result_path},
                {"parser_name": "SecondaryLefParser", "result_status": "FAILED"},
            ],
        }])
        self._write_parser_result(scan, result_path)

        result = self._lef_readiness(scan)
        view = result["components"][0]["required_view_results"]["lef"]

        self.assertEqual(view["status"], "BLOCK")
        self.assertIn("FAILED", view["message"])

    def test_optional_view_with_incomplete_parser_evidence_warns_without_blocking(self):
        scan = self._scan([
            {"path": "lef/optional.lef", "file_type": "lef"},
            {"path": "rtl/top.v", "file_type": "verilog"},
        ])
        result = build_release_readiness(
            scan,
            {
                "required_views": {"ip": ["verilog"]},
                "optional_views": {"ip": ["lef"]},
                "validation_levels": {"verilog": "metadata_required", "lef": "parsed_required"},
            },
        )

        view = result["components"][0]["optional_view_results"]["lef"]
        self.assertEqual(view["status"], "WARNING")
        self.assertEqual(result["required_view_status"], "PASS")
        self.assertNotEqual(result["bundle_status"], "BLOCK")

    def test_metadata_required_view_does_not_claim_parser_validation(self):
        scan = self._scan([{"path": "rtl/top.v", "file_type": "verilog"}])
        result = build_release_readiness(
            scan,
            {
                "required_views": {"ip": ["verilog"]},
                "validation_levels": {"verilog": "metadata_required"},
            },
        )

        view = result["components"][0]["required_view_results"]["verilog"]
        self.assertEqual(view["status"], "PASS")
        self.assertEqual(view["parser_status"], "METADATA_ONLY")
        self.assertEqual(view["evidence_counts"], {"total": 1, "satisfied": 1, "incomplete": 0})
        self.assertIn("元数据", view["message"])

    def test_required_mode_and_corner_are_reported_and_missing_items_block(self):
        scan = self._scan([
            {"path": "LEF/demo_tt_0p8v_25c.lef", "file_type": "lef", "corner": {"process": "tt", "voltage": "0.8v", "temperature": "25c"}},
            {"path": "LIB/demo_tt_0p8v_25c.lib", "file_type": "liberty", "corner": {"process": "tt", "voltage": "0.8v", "temperature": "25c"}},
            {"path": "RTL/demo_functional.v", "file_type": "verilog", "delivery_mode": "functional"},
            {"path": "CDL/demo_tt_0p8v_25c.cdl", "file_type": "cdl", "corner": {"process": "tt", "voltage": "0.8v", "temperature": "25c"}},
        ])
        parser_entries = []
        for file_type, parser_name in (("lef", "LefParser"), ("liberty", "LibertyParser"), ("cdl", "CdlParser")):
            path = next(item["path"] for item in json.loads((scan / "file_inventory.json").read_text(encoding="utf-8"))["files"] if item["file_type"] == file_type)
            result_path = f"parser_results/{file_type}/result.json"
            parser_entries.append({
                "file": path,
                "file_type": file_type,
                "parser_tasks": [{"parser_name": parser_name, "result_status": "PASS", "result_path": result_path}],
            })
            self._write_parser_result(scan, result_path)
        self._set_parser_manifest(scan, parser_entries)
        self._update_scan_meta(scan, delivery_modes=["functional"], delivery_corners=["tt_0.8v_25c"])
        policy = {
            "required_views": {"ip": ["lef", "liberty", "verilog", "cdl"]},
            "required_modes": {"ip": ["functional", "scan"]},
            "required_corners": {"ip": ["tt_0p8v_25c", "ss_0.7v_125c"]},
        }

        result = build_release_readiness(scan, policy)
        contract = result["delivery_requirements"]
        self.assertEqual(contract["modes"]["status"], "BLOCK")
        self.assertEqual(contract["modes"]["missing"], ["scan"])
        self.assertEqual(contract["corners"]["status"], "BLOCK")
        self.assertEqual(contract["corners"]["missing"], ["ss_0.7v_125c"])
        self.assertEqual(result["bundle_status"], "BLOCK")
        self.assertEqual(result["required_view_status"], "PASS")

    def test_empty_mode_and_corner_policy_is_explicitly_unconfigured(self):
        scan = self._scan([{ "path": "RTL/demo.v", "file_type": "verilog" }])
        result = build_release_readiness(scan, {"required_views": {"ip": ["verilog"]}})
        contract = result["delivery_requirements"]
        self.assertEqual(contract["modes"]["status"], "NOT_CONFIGURED")
        self.assertEqual(contract["corners"]["status"], "NOT_CONFIGURED")
        self.assertEqual(result["bundle_status"], "PASS")

    def test_filename_corner_hint_is_not_reported_as_confirmed_coverage(self):
        scan = self._scan([{
            "path": "LIB/demo_tt_0p8v_25c.lib",
            "file_type": "liberty",
            "corner": {"process": "tt", "voltage": "0.8v", "temperature": "25c"},
        }])

        result = build_release_readiness(
            scan,
            {
                "required_views": {"ip": ["liberty"]},
                "required_corners": {"ip": ["tt_0.8v_25c"]},
                "validation_levels": {"liberty": "metadata_required"},
            },
        )

        corners = result["delivery_requirements"]["corners"]
        self.assertEqual(corners["status"], "BLOCK")
        self.assertEqual(corners["missing"], ["tt_0.8v_25c"])
        self.assertEqual(corners["hinted_required"], ["tt_0.8v_25c"])
        self.assertEqual(corners["evidence_source"], "filename_or_path_hint")
        self.assertIn("尚未确认", corners["message"])

    def test_version_detail_report_preserves_corner_hint_provenance(self):
        from lib_guard.render.version_review_model import build_ip_user_view_model, build_review_report
        from lib_guard.render.version_review_render import render_review_report

        source = {
            "status": "CHANGED",
            "version_id": "v2",
            "target_version": "v2",
            "base_version": "v1",
            "base_ref": "previous_effective",
            "file_changes": [],
            "scan_evidence": {
                "release_readiness": {
                    "required_view_status": "PASS",
                    "delivery_requirement_status": "BLOCK",
                    "delivery_requirements": {
                        "status": "BLOCK",
                        "modes": {"required": [], "observed": [], "candidate_hints": [], "missing": [], "evidence_source": "none"},
                        "corners": {
                            "required": ["tt_0.8v_25c"],
                            "observed": [],
                            "candidate_hints": ["tt_0.8v_25c"],
                            "hinted_required": ["tt_0.8v_25c"],
                            "missing": ["tt_0.8v_25c"],
                            "evidence_source": "filename_or_path_hint",
                        },
                    },
                    "components": [{
                        "required_views": ["verilog", "lef"],
                        "required_view_results": {
                            "verilog": {"found": True, "status": "PASS", "validation_level": "metadata_required", "evidence_counts": {"total": 1, "satisfied": 1, "incomplete": 0}},
                            "lef": {"found": True, "status": "BLOCK", "validation_level": "parsed_required", "evidence_counts": {"total": 2, "satisfied": 1, "incomplete": 1}, "incomplete_files": ["LEF/cell_b.lef"], "message": "解析证据不完整"},
                        },
                        "optional_views": [],
                        "optional_view_results": {},
                    }],
                }
            },
        }

        report = build_review_report(source, build_ip_user_view_model(source))

        self.assertEqual(report["delivery_analysis"]["hinted_required_corners"], ["tt_0.8v_25c"])
        self.assertEqual(report["delivery_analysis"]["corner_evidence_source"], "filename_or_path_hint")
        self.assertEqual(report["delivery_analysis"]["view_evidence"][0]["incomplete_files"], ["LEF/cell_b.lef"])
        html = render_review_report(report)
        self.assertIn("路径提示待确认", html)
        self.assertIn("文件名/目录提示（尚未确认）", html)
        self.assertIn("LEF/cell_b.lef", html)

    def test_version_detail_decision_blocks_on_required_corner_without_view_missing(self):
        model = {
            "status": "CHANGED",
            "package_type": "FULL_PACKAGE",
            "review_mode": "baseline",
            "base_ref": "current_effective",
            "base_version": "base",
            "file_changes": [],
            "lane_counts": {},
            "scan_evidence": {
                "release_readiness": {
                    "required_view_status": "PASS",
                    "delivery_requirement_status": "BLOCK",
                    "delivery_requirements": {
                        "modes": {"missing": []},
                        "corners": {"missing": ["ss_0.7v_125c"]},
                    },
                    "components": [{
                        "required_views": ["verilog"],
                        "required_view_results": {"verilog": {"found": True, "status": "PASS"}},
                        "optional_views": [],
                        "optional_view_results": {},
                    }],
                }
            },
        }
        result = build_ip_user_view_model(model)
        self.assertEqual(result["decision"]["status"], "USAGE_REVIEW_REQUIRED")
        self.assertIn("工艺角：ss_0.7v_125c", result["decision"]["reason"])
        self.assertEqual(result["next_action"]["kind"], "complete_required_view")
        self.assertEqual(result["delivery_completeness"]["delivery_requirement_status"], "BLOCK")

    def test_detail_report_exposes_mode_and_corner_requirements(self):
        html = render_review_report({
            "delivery_analysis": {
                "status": "MISSING",
                "package_type": "FULL_PACKAGE",
                "file_count": 4,
                "required_total": 4,
                "required_present": 4,
                "required_modes": ["functional", "scan"],
                "missing_modes": ["scan"],
                "required_corners": ["tt_0.8v_25c", "ss_0.7v_125c"],
                "missing_corners": ["ss_0.7v_125c"],
                "requirement_status": "BLOCK",
            },
            "base_analysis": {},
            "view_delta_analysis": {},
            "focus_file_analysis": {},
            "unknown_analysis": {},
            "evidence_assessment": {},
        })
        self.assertIn("必需模式", html)
        self.assertIn("必需工艺角", html)
        self.assertIn("ss_0.7v_125c", html)


if __name__ == "__main__":
    unittest.main()
