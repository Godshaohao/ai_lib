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

    def test_required_mode_and_corner_are_reported_and_missing_items_block(self):
        scan = self._scan([
            {"path": "LEF/demo_tt_0p8v_25c.lef", "file_type": "lef", "corner": {"process": "tt", "voltage": "0.8v", "temperature": "25c"}},
            {"path": "LIB/demo_tt_0p8v_25c.lib", "file_type": "liberty", "corner": {"process": "tt", "voltage": "0.8v", "temperature": "25c"}},
            {"path": "RTL/demo_functional.v", "file_type": "verilog", "delivery_mode": "functional"},
            {"path": "CDL/demo_tt_0p8v_25c.cdl", "file_type": "cdl", "corner": {"process": "tt", "voltage": "0.8v", "temperature": "25c"}},
        ])
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

    def test_version_detail_decision_blocks_on_required_corner_without_view_missing(self):
        model = {
            "status": "CHANGED",
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
        self.assertEqual(result["decision"]["status"], "BLOCKED")
        self.assertIn("工艺角：ss_0.7v_125c", result["decision"]["reason"])
        self.assertEqual(result["next_action"]["kind"], "complete_required_view")

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
