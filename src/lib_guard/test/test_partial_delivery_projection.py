"""P0 contract: package delivery facts are not an effective-IP verdict."""

import json
import tempfile
import unittest
from pathlib import Path

from lib_guard.render.version_review_model import build_ip_user_view_model
from lib_guard.render.version_review_model import build_review_report
from lib_guard.review.engineering import build_engineering_report
from lib_guard.render.version_detail_report import _reader_summary, _review_evidence_sidebar, render_version_detail_page


def review_model(package_type="PARTIAL_UPDATE", *, status="CHANGED", present=("lef",),
                 effective=None, semantic=None):
    results = {view: {"found": view in present,
                      "status": "PASS" if view in present else "MISSING"}
               for view in ("lef", "liberty", "verilog")}
    model = {
        "package_type": package_type,
        "comparison_semantics": "incremental" if package_type in {"PARTIAL_UPDATE", "HOTFIX", "DOC_UPDATE", "DOC_ONLY"} else "unknown" if package_type == "UNKNOWN_PACKAGE" else "full",
        "status": status,
        "base_ref": "previous_effective",
        "base_version": "F0",
        "base_trust_status": "PASS",
        "file_changes": [],
        "scan_evidence": {"release_readiness": {
            "bundle_status": "BLOCK",
            "components": [{"required_views": list(results), "required_view_results": results}],
        }},
        "review_gate": {"status": "BLOCKED", "blocking_items": [{"category": "release"}]},
    }
    if effective is not None:
        model["candidate_effective_inventory"] = effective
    if semantic is not None:
        model["semantic_check"] = semantic
    return model


class PartialDeliveryProjectionTest(unittest.TestCase):
    def test_p0_01_lef_only_partial_preserves_readiness_without_unusable_verdict(self):
        source = review_model(effective={"manifest": "/candidate/manifest.json",
                                         "file_type_counts": {"lef": 1, "liberty": 1, "verilog": 1}})
        projected = build_ip_user_view_model(source)
        self.assertEqual(projected["delivery_completeness"]["status"], "MISSING")
        self.assertEqual(source["scan_evidence"]["release_readiness"]["bundle_status"], "BLOCK")
        self.assertEqual(projected["decision"]["status"], "USAGE_REVIEW_REQUIRED")
        self.assertNotIn("不可接入", str(projected))
        self.assertIn("组合", projected["decision"]["reason"])
        report = build_review_report(source, projected)
        self.assertIn("本包", " ".join(report["open_questions"]))
        self.assertEqual(report["delivery_analysis"]["status"], "MISSING")

    def test_p0_02_effective_interface_conflict_precedes_package_gap(self):
        source = review_model(semantic={"status": "CURRENT", "effective_id": "E1",
                                        "checks": [{"check_id": "SIGNAL_PORT_SET", "status": "FAIL",
                                                    "macro": "M", "actual": [
                                                        {"ports": {"CLK": {"direction": "INPUT"}}},
                                                        {"ports": {}}]}]})
        projected = build_ip_user_view_model(source)
        source["ip_user_view_model"] = projected
        report = build_engineering_report(source)
        source["engineering_report"] = report
        html = _reader_summary(source, {})
        self.assertEqual(projected["decision"]["status"], "USAGE_REVIEW_REQUIRED")
        self.assertIn("接口", projected["decision"]["reason"])
        self.assertLess(html.index("建议动作"), html.index("交付情况"))
        self.assertIn("Pin", html)
        self.assertIn("交付", html)

    def test_p0_03_doc_only_is_not_a_missing_technical_view(self):
        for package_type in ("DOC_ONLY", "DOC_UPDATE"):
            with self.subTest(package_type=package_type):
                source = review_model(package_type, present=())
                projected = build_ip_user_view_model(source)
                source["ip_user_view_model"] = projected
                engineering = build_engineering_report(source)
                self.assertEqual(projected["decision"]["status"], "USAGE_REVIEW_REQUIRED")
                self.assertNotIn("不可接入", projected["decision"]["reason"])
                self.assertIn("本包", engineering["delivery_summary"])

    def test_p0_04_unknown_package_requires_scope_confirmation(self):
        projected = build_ip_user_view_model(review_model("UNKNOWN_PACKAGE"))
        self.assertEqual(projected["decision"]["status"], "USAGE_REVIEW_REQUIRED")
        self.assertIn("包类型", projected["next_action"]["detail"])
        self.assertEqual(projected["comparison"]["scope"], "unknown")

    def test_p0_05_full_gap_remains_visible_without_mutating_release_gate(self):
        source = review_model("FULL_PACKAGE", present=("lef",))
        gate_before = source["review_gate"].copy()
        projected = build_ip_user_view_model(source)
        self.assertEqual(projected["delivery_completeness"]["status"], "MISSING")
        self.assertNotEqual(projected["decision"]["status"], "READY")
        self.assertIn("交付", projected["decision"]["reason"])
        self.assertEqual(source["review_gate"], gate_before)
        self.assertEqual(projected["release_summary"]["status"], "INFO")

    def test_p0_06_no_trustworthy_base_does_not_claim_unchanged(self):
        source = review_model(status="NEEDS_BASE_CONFIRM")
        source["base_trust_status"] = "BLOCK"
        projected = build_ip_user_view_model(source)
        self.assertEqual(projected["decision"]["label"], "暂不可判断")
        self.assertEqual(projected["change_summary"]["status"], "UNKNOWN")
        self.assertNotIn("不可接入", projected["decision"]["reason"])
        source = review_model(status="DIFF_NOT_RUN")
        projected = build_ip_user_view_model(source)
        self.assertEqual(projected["decision"]["label"], "暂不可判断")
        self.assertEqual(projected["change_summary"]["status"], "UNKNOWN")

    def test_stale_interface_failure_is_not_presented_as_current_conflict(self):
        source = review_model(semantic={"status": "STALE", "checks": [
            {"check_id": "SIGNAL_PORT_SET", "status": "FAIL"}]})
        projected = build_ip_user_view_model(source)
        self.assertNotEqual(projected["next_action"]["kind"], "review_interface_conflict")
        self.assertNotIn("发现单元", projected["decision"]["reason"])

    def test_missing_view_is_retained_when_mode_requirement_also_blocks_readiness(self):
        source = review_model()
        readiness = source["scan_evidence"]["release_readiness"]
        readiness["delivery_requirement_status"] = "BLOCK"
        readiness["delivery_requirements"] = {"modes": {"missing": ["scan"]}}
        projected = build_ip_user_view_model(source)
        self.assertEqual(projected["delivery_completeness"]["status"], "BLOCKED")
        self.assertEqual(projected["delivery_completeness"]["missing"], ["时序库（Liberty）", "RTL 模型"])
        self.assertEqual(projected["pending_fact_items"][0]["kind"], "REQUIRED_VIEW_MISSING")

    def test_p0_07_confirmed_conflict_and_missing_readiness_are_both_retained(self):
        source = review_model("HOTFIX", semantic={"status": "CURRENT", "effective_id": "E2",
                                                  "checks": [{"check_id": "SIGNAL_PORT_DIRECTION",
                                                              "status": "FAIL", "macro": "M"}]})
        projected = build_ip_user_view_model(source)
        self.assertEqual(projected["delivery_completeness"]["status"], "MISSING")
        self.assertEqual(projected["pending_fact_items"][0]["kind"], "REQUIRED_VIEW_MISSING")
        self.assertIn("接口", projected["decision"]["reason"])
        self.assertEqual(projected["next_action"]["kind"], "review_interface_conflict")

    def test_overlay_without_combination_is_not_ready_even_if_package_readiness_passes(self):
        source = review_model(present=("lef", "liberty", "verilog"))
        source["scan_evidence"]["release_readiness"]["bundle_status"] = "PASS"
        projected = build_ip_user_view_model(source)
        self.assertEqual(projected["delivery_completeness"]["status"], "PASS")
        self.assertEqual(projected["decision"]["status"], "USAGE_REVIEW_REQUIRED")
        self.assertIn("组合", projected["decision"]["reason"])

    def test_sidebar_names_package_scope_instead_of_effective_completeness(self):
        source = review_model()
        source["ip_user_view_model"] = build_ip_user_view_model(source)
        html = _review_evidence_sidebar(source, {})
        self.assertIn("本包交付范围", html)
        self.assertIn("本包未交付", html)
        self.assertNotIn("交付完整度", html)

    def test_actual_partial_version_page_keeps_gap_but_not_unusable_verdict(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            scan = root / "scan"
            diff = root / "diff"
            (scan / "summary").mkdir(parents=True)
            diff.mkdir()
            (scan / "scan_meta.json").write_text(json.dumps({"scan_id": "scan-p0"}))
            (scan / "file_inventory.json").write_text(json.dumps({
                "files": [{"path": "LEF/M.lef", "file_type": "lef", "size_bytes": 12}],
                "file_type_counts": {"lef": 1},
            }))
            (scan / "summary" / "release_readiness.json").write_text(json.dumps(
                review_model()["scan_evidence"]["release_readiness"]
            ))
            (diff / "diff_summary.json").write_text(json.dumps({"status": "DIFF", "changed_files": 1}))
            (diff / "file_diff.json").write_text(json.dumps({
                "changed": [{"path": "LEF/M.lef", "file_type": "lef"}],
            }))
            page = Path(render_version_detail_page(
                root / "html", {"library_id": "ip/demo", "library_name": "demo"},
                {"version_id": "fix_lef", "package_type": "PARTIAL_UPDATE",
                 "raw_path": str(root / "raw" / "fix_lef"),
                 "scan": {"scan_dir": str(scan), "status": "PASS"},
                 "diff": {"base_version": "full", "base_source": "explicit", "base_diff_dir": str(diff)}},
                catalog_navigation_available=False,
            ))
            html = page.read_text(encoding="utf-8")
            self.assertIn("本包未交付", html)
            self.assertIn("本包未交付视图", html)
            self.assertIn("组合待核对", html)
            self.assertNotIn("补齐前不可接入", html)
            self.assertNotIn("在补齐前不可接入", html)


if __name__ == "__main__":
    unittest.main()
