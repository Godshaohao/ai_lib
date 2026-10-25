import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from lib_guard import ip_check_overview
from lib_guard.ip_check_overview import render_overview
from lib_guard.review_runner import _library_dir, refresh_ip_overview


def overview_row(*, attempt_status="COMPLETE", quality="MISMATCH"):
    return {
        "ip": {"id": "IP_A", "name": "IP A", "library_id": "Vendor.IP_A", "vendor": "Vendor"},
        "last_attempt": {
            "status": attempt_status,
            "id": "task_latest",
            "time": "2026-10-25T10:00:00Z",
            "checks": ["lef_review"],
        },
        "last_complete": {
            "id": "review_complete",
            "time": "2026-10-24T10:00:00Z",
            "requested_checks": ["formal_nl", "macro_index", "lef_review", "lef_liberty_check"],
            "checks": {
                "formal_nl": {"execution_status": "COMPLETE"},
                "macro_index": {"execution_status": "COMPLETE"},
                "lef_review": {"execution_status": "COMPLETE"},
                "lef_liberty_check": {"execution_status": "COMPLETE"},
            },
            "summary": {
                "counts": {
                    "CHANGED": {"affected_objects": 3},
                    "MISMATCH": {"affected_objects": 2},
                    "UNVERIFIED": {"affected_objects": 5},
                },
            },
            "context": {"target_raw_versions": ["V02"], "formal_stage": "lib_NL2.5_3"},
            "input_paths": ["/raw/V02/LEF/a.lef", "/formal/lib_NL2.5_3/LEF/a.lef"],
            "xlsx_href": "../libraries/ip_a/latest.xlsx",
        },
        "quality_status": quality,
        "simulation": False,
    }


class IpCheckOverviewTests(unittest.TestCase):
    def test_summary_filters_and_findings_keep_mismatch_visible(self):
        html = render_overview([overview_row()])

        self.assertIn('id="metric-ip-count">1<', html)
        self.assertIn('id="metric-complete-count">1<', html)
        self.assertIn('id="metric-mismatch-count">1<', html)
        self.assertIn('id="metric-unverified-count">1<', html)
        self.assertIn('data-quality="MISMATCH"', html)
        self.assertIn("不一致 2", html)
        self.assertIn("待核实 5", html)
        self.assertIn("变化 3", html)
        self.assertIn('id="ip-search"', html)
        self.assertIn('id="attempt-filter"', html)
        self.assertIn('id="quality-filter"', html)
        self.assertIn('id="check-filter"', html)
        self.assertIn("<script>", html)
        self.assertNotIn("https://", html)

    def test_partial_check_coverage_is_not_rendered_as_four_checks_complete(self):
        row = overview_row()
        row["last_complete"]["requested_checks"] = ["lef_review"]
        row["last_complete"]["checks"] = {
            "formal_nl": {"execution_status": "NOT_RUN"},
            "macro_index": {"execution_status": "NOT_RUN"},
            "lef_review": {"execution_status": "COMPLETE"},
            "lef_liberty_check": {"execution_status": "NOT_RUN"},
        }

        html = render_overview([row])

        self.assertIn("1 / 4", html)
        self.assertIn("正式目录盘点：未选", html)
        self.assertIn("LEF 双文件核查：完成", html)
        self.assertIn("LEF–Liberty 接口核查：未选", html)

    def test_missing_finding_counts_are_not_fabricated_as_zero(self):
        row = overview_row()
        row["last_complete"]["summary"] = {"counts": {}}

        html = render_overview([row])

        self.assertIn('data-quality="SUMMARY_INCOMPLETE"', html)
        self.assertIn("变化 未确认", html)
        self.assertIn("不一致 未确认", html)
        self.assertIn("待核实 未确认", html)
        self.assertNotIn("本次范围未发现问题", html)

    def test_qualitative_mismatch_without_numeric_count_still_appears_in_metrics_and_filter(self):
        row = overview_row()
        row["last_complete"]["summary"] = {
            "quality_assessment": {"status": "ISSUES_FOUND"},
            "counts": {
                "CHANGED": {"affected_objects": 1},
                "MISMATCH": {"affected_objects": None},
                "UNVERIFIED": {"affected_objects": 3},
            },
        }

        html = render_overview([row])

        self.assertIn('id="metric-mismatch-count">1<', html)
        self.assertIn('data-quality="MISMATCH"', html)
        self.assertIn('data-has-mismatch="true"', html)
        self.assertIn('data-has-unverified="true"', html)
        self.assertIn("不一致 未确认", html)

    def test_default_priority_places_mismatch_failure_unverified_then_changes(self):
        mismatch = overview_row()
        mismatch["ip"]["name"] = "Mismatch IP"
        failed = overview_row(attempt_status="FAILED", quality="NO_FINDINGS")
        failed["ip"]["name"] = "Failed IP"
        failed["last_complete"]["summary"]["counts"] = {
            "CHANGED": {"affected_objects": 0}, "MISMATCH": {"affected_objects": 0},
            "UNVERIFIED": {"affected_objects": 0},
        }
        unverified = overview_row(quality="UNVERIFIED")
        unverified["ip"]["name"] = "Unverified IP"
        unverified["last_complete"]["summary"]["counts"].update({
            "CHANGED": {"affected_objects": 0}, "MISMATCH": {"affected_objects": 0},
            "UNVERIFIED": {"affected_objects": 1},
        })
        changed = overview_row(quality="CHANGED")
        changed["ip"]["name"] = "Changed IP"
        changed["last_complete"]["summary"]["counts"].update({
            "MISMATCH": {"affected_objects": 0}, "UNVERIFIED": {"affected_objects": 0},
        })
        no_report = {"ip": {"name": "No Report IP", "library_id": "Vendor.NoReport"}}

        html = render_overview([changed, no_report, unverified, failed, mismatch])
        positions = [html.index(f"<strong>{name}</strong>") for name in
                     ("Mismatch IP", "Failed IP", "Unverified IP", "Changed IP", "No Report IP")]

        self.assertEqual(positions, sorted(positions))

    def test_attempt_failure_does_not_replace_complete_report_findings_or_scope(self):
        row = overview_row(attempt_status="FAILED")
        row["last_attempt"]["quality_status"] = "NOT_ASSESSED"
        html = render_overview([row])

        self.assertIn("task_latest", html)
        self.assertIn("review_complete", html)
        self.assertIn("V02", html)
        self.assertIn("lib_NL2.5_3", html)
        self.assertIn("不一致 2", html)
        self.assertIn("待核实 5", html)
        self.assertNotIn("NOT_ASSESSED", html)

    def test_long_paths_are_collapsed_and_simulation_is_explicit(self):
        row = overview_row()
        row["simulation"] = True
        html = render_overview([row], simulation=True)

        self.assertIn("模拟数据", html)
        self.assertIn("<details", html)
        self.assertIn("/raw/V02/LEF/a.lef", html)
        self.assertIn("打开 Excel", html)

    def test_overview_exposes_primary_finding_and_review_provenance_in_details(self):
        row = overview_row()
        row["last_complete"]["source_revision"] = {
            "commit": "0123456789abcdef", "working_tree_dirty": True,
        }
        row["last_complete"]["input_scope"] = {
            "checks": [{"name": "lef_liberty_check"}], "target_raw_versions": ["V02"],
            "formal_stage": "lib_NL2.5_3", "source_count": 4,
        }
        row["last_complete"]["summary"]["primary_findings"] = [
            {"kind": "MISMATCH", "category": "LEF-Liberty接口", "label": "PG脚缺失", "count": 12},
        ]

        html = render_overview([row])

        self.assertIn("主要发现：LEF-Liberty接口：PG脚缺失 (12)", html)
        self.assertIn("源提交：0123456789abcdef（生成时工作区有未提交修改）", html)
        self.assertIn("输入范围：</strong>检查 lef_liberty_check；RAW V02", html)

    def test_many_raw_versions_are_counted_in_row_and_listed_only_in_collapsed_details(self):
        row = overview_row()
        versions = [f"RAW_V{index:02d}" for index in range(1, 51)]
        row["last_complete"]["context"]["target_raw_versions"] = versions

        html = render_overview([row])
        summary_cell = html.split("<details", 1)[0]

        self.assertIn("RAW 输入：50 个版本", summary_cell)
        self.assertNotIn("RAW_V01", summary_cell)
        self.assertIn("RAW_V01", html)
        self.assertIn("RAW_V50", html)

    def test_refresh_reads_last_attempt_and_immutable_complete_result_separately(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            output = root / "output"
            library_id = "Vendor.IP_A"
            library_dir = output / "libraries" / _library_dir(library_id)
            review_id = "review_20261024T100000Z_aaaaaaaa"
            run_dir = library_dir / "runs" / review_id
            run_dir.mkdir(parents=True)
            (run_dir / "ip_review.xlsx").write_bytes(b"xlsx")
            (run_dir / "review_result.json").write_text(json.dumps({
                "library_id": library_id,
                "review_id": review_id,
                "generated_at": "2026-10-24T10:00:00Z",
                "execution_status": "COMPLETE",
                "requested_checks": ["lef_review"],
                "checks": {
                    "formal_nl": {"execution_status": "NOT_RUN"},
                    "macro_index": {"execution_status": "NOT_RUN"},
                    "lef_review": {"execution_status": "COMPLETE"},
                    "lef_liberty_check": {"execution_status": "NOT_RUN"},
                },
                "summary": {"counts": {
                    "CHANGED": {"affected_objects": 3},
                    "MISMATCH": {"affected_objects": 2},
                    "UNVERIFIED": {"affected_objects": 5},
                }},
                "context": {"target_raw_versions": ["V02"], "formal_stage": "lib_NL2.5_3"},
            }), encoding="utf-8")
            (library_dir / "latest_attempt.json").write_text(json.dumps({
                "task_id": "task_failed", "status": "FAILED", "execution_status": "FAILED",
                "finished_at": "2026-10-25T10:00:00Z", "requested_checks": ["lef_review"],
                "summary": {"counts": {"MISMATCH": {"affected_objects": 999}}},
            }), encoding="utf-8")
            (library_dir / "latest.xlsx").write_bytes(b"stable")

            target = refresh_ip_overview({"environment": "SIMULATION", "ips": [{
                "id": "IP_A", "library_id": library_id, "name": "IP A", "vendor": "Vendor",
                "raw_versions": [{"id": "V02", "path": "/raw/V02"}],
            }]}, output)

            html = target.read_text(encoding="utf-8")
            self.assertIn("task_failed", html)
            self.assertIn(review_id, html)
            self.assertIn("不一致 2", html)
            self.assertNotIn("不一致 999", html)
            self.assertIn("1 / 4", html)
            self.assertIn("模拟数据", html)

    def test_refresh_uses_atomic_replace_and_preserves_previous_page_on_render_error(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "output"
            target = output / "ip_checks" / "index.html"
            target.parent.mkdir(parents=True)
            target.write_text("previous complete page", encoding="utf-8")

            with patch("lib_guard.review_runner.render_overview", side_effect=RuntimeError("render failed")):
                with self.assertRaisesRegex(RuntimeError, "render failed"):
                    refresh_ip_overview({"ips": []}, output)

            self.assertEqual(target.read_text(encoding="utf-8"), "previous complete page")
            self.assertEqual(list(target.parent.glob("*.tmp")), [])

    def test_refresh_is_read_only_and_does_not_invoke_review_checkers(self):
        with tempfile.TemporaryDirectory() as temp:
            with patch("lib_guard.review_runner.run_review") as run_review:
                refresh_ip_overview({"ips": []}, Path(temp) / "output")

            run_review.assert_not_called()

    def test_parallel_refreshes_never_leave_truncated_html_or_temp_files(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "output"
            config = {"ips": [{"id": "IP_A", "library_id": "Vendor.IP_A", "name": "IP A"}]}
            with ThreadPoolExecutor(max_workers=2) as executor:
                targets = list(executor.map(lambda _: refresh_ip_overview(config, output), range(2)))

            self.assertEqual(targets[0], targets[1])
            self.assertIn("</html>", targets[0].read_text(encoding="utf-8"))
            self.assertEqual(list(targets[0].parent.glob("*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
