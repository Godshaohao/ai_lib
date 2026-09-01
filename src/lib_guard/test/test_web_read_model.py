from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SMOKE_CONFIG = ROOT / "work" / "single_library_smoke_20260805" / "lib_guard.yml"
LIBRARY = "vendor_A.openroad_platform.openroad_asap7"


class WebReadModelTest(unittest.TestCase):
    def test_load_web_state_reads_existing_catalog_without_discovering_raw(self) -> None:
        from lib_guard.web.read_model import load_web_state

        state = load_web_state(config_path=SMOKE_CONFIG, cwd=ROOT)

        self.assertEqual(state["catalog_path"].name, "catalog.json")
        self.assertEqual([item["library_name"] for item in state["catalog"]["libraries"]], [LIBRARY])
        self.assertEqual(state["config"]["raw_root"], str(ROOT / "tests" / "fixtures" / "raw"))

    def test_list_library_rows_keeps_formal_name_and_latest_summary(self) -> None:
        from lib_guard.web.read_model import list_library_rows, load_web_state

        rows = list_library_rows(load_web_state(config_path=SMOKE_CONFIG, cwd=ROOT))

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["library_name"], LIBRARY)
        self.assertEqual(rows[0]["version_count"], 2)
        self.assertEqual(rows[0]["latest_version"], "20260627_asap7")

    def test_library_pending_count_excludes_scanned_initial_baseline(self) -> None:
        from lib_guard.web.read_model import list_library_rows

        with tempfile.TemporaryDirectory() as td:
            scan_dir = Path(td) / "scan"
            scan_dir.mkdir()
            (scan_dir / "file_inventory.json").write_text(json.dumps({"files": []}), encoding="utf-8")
            state = {
                "catalog_html": Path(td),
                "catalog": {
                    "libraries": [
                        {
                            "library_name": "demo.lib",
                            "summary": {"version_count": 2, "latest_version": "v2"},
                            "versions": [
                                {
                                    "version_id": "v1",
                                    "scan": {"status": "SCANNED", "scan_dir": str(scan_dir)},
                                    "diff": {"adjacent_status": "NOT_APPLICABLE"},
                                    "release": {"check_status": "UNKNOWN"},
                                },
                                {
                                    "version_id": "v2",
                                    "scan": {"status": "NOT_SCANNED"},
                                    "diff": {"adjacent_old_version": "v1", "adjacent_status": "PENDING"},
                                },
                            ],
                        }
                    ]
                },
            }

            row = list_library_rows(state)[0]

        self.assertEqual(row["review_pending_count"], 1)

    def test_initial_baseline_has_own_review_label_without_comparison(self) -> None:
        from lib_guard.web.read_model import _review_decision

        with tempfile.TemporaryDirectory() as td:
            scan_dir = Path(td) / "scan"
            scan_dir.mkdir()
            (scan_dir / "file_inventory.json").write_text(json.dumps({"files": []}), encoding="utf-8")

            result = _review_decision(
                {
                    "scan": {"status": "SCANNED", "scan_dir": str(scan_dir)},
                    "diff": {"adjacent_status": "NOT_APPLICABLE"},
                    "release": {"check_status": "UNKNOWN"},
                },
                is_initial_baseline=True,
            )

        self.assertEqual(result["label"], "初始基线")
        self.assertEqual(result["next_action"], "查看详情")

    def test_list_version_rows_returns_statuses_and_existing_detail_link(self) -> None:
        from lib_guard.web.read_model import list_version_rows, load_web_state

        state = load_web_state(config_path=SMOKE_CONFIG, cwd=ROOT)
        rows = list_version_rows(state, LIBRARY)

        self.assertEqual([row["version_id"] for row in rows], ["20260627_asap7", "20260624_asap7"])
        self.assertIn(rows[0]["scan_status"], {"PASS", "SCANNED", "NOT_SCANNED", "STALE_SCAN"})
        self.assertIn("version_detail_path", rows[0])

    def test_list_version_rows_exposes_action_readiness_for_the_workbench(self) -> None:
        from lib_guard.web.read_model import list_version_rows, load_web_state

        state = load_web_state(config_path=SMOKE_CONFIG, cwd=ROOT)
        rows = list_version_rows(state, LIBRARY)

        newest = rows[0]
        self.assertEqual(newest["action_readiness"]["scan"]["enabled"], True)
        self.assertEqual(newest["action_readiness"]["compare"]["enabled"], True)
        self.assertEqual(newest["action_readiness"]["release-check"]["enabled"], True)

        from lib_guard.web.read_model import _action_readiness

        unscanned = _action_readiness({"scan": {"status": "NOT_SCANNED"}})
        self.assertEqual(unscanned["compare"]["enabled"], False)
        self.assertIn("先完成扫描", unscanned["compare"]["reason"])
        self.assertEqual(unscanned["release-check"]["enabled"], False)
        self.assertIn("先完成扫描", unscanned["release-check"]["reason"])

    def test_unscanned_version_prioritizes_scan_before_missing_base(self) -> None:
        from lib_guard.web.read_model import _action_readiness, _review_decision

        version = {"scan": {"status": "NOT_SCANNED"}}
        readiness = _action_readiness(version)

        self.assertIn("先完成扫描", readiness["compare"]["reason"])
        self.assertEqual(_review_decision(version)["label"], "待生成扫描")
        self.assertEqual(_review_decision(version)["next_action"], "生成扫描")

    def test_explicit_effective_pointer_overrides_catalog_review_flag(self) -> None:
        from lib_guard.web.read_model import _review_decision

        with tempfile.TemporaryDirectory() as td:
            scan_dir = Path(td) / "scan"
            scan_dir.mkdir()
            (scan_dir / "file_inventory.json").write_text(json.dumps({"files": []}), encoding="utf-8")
            version = {
                "current_effective": False,
                "scan": {"status": "SCANNED", "scan_dir": str(scan_dir)},
                "diff": {"adjacent_status": "NOT_APPLICABLE"},
                "release": {"check_status": "UNKNOWN"},
            }

            self.assertEqual(_review_decision(version, current_effective=True)["label"], "当前有效版")

    def test_completed_compare_and_release_results_get_repeat_labels(self) -> None:
        from lib_guard.web.read_model import _action_readiness, _diff_status

        readiness = _action_readiness(
            {
                "scan": {"status": "SCANNED"},
                "scan_dir": str(ROOT / "work" / "single_library_smoke_20260805" / "scan_out" / "ip" / "vendor_A.openroad_platform.openroad_asap7" / "20260627_asap7" / "runs" / "scan_20260825_154920"),
                "diff": {"base_version": "v1", "base_status": "DIFF_DONE"},
                "release": {"check_status": "CHECKED"},
            }
        )

        self.assertEqual(readiness["compare"]["label"], "重新对比")
        self.assertEqual(readiness["release-check"]["label"], "重新检查")

        version = {
            "diff": {
                "adjacent_old_version": "adjacent",
                "adjacent_status": "PENDING",
                "base_version": "explicit",
                "base_status": "DIFF_DONE",
            }
        }
        self.assertEqual(_diff_status(version), "PENDING")
        self.assertEqual(_diff_status(version, "cumulative"), "DIFF_DONE")

    def test_malformed_pending_window_is_visible_as_invalid(self) -> None:
        from lib_guard.web.read_model import _pending_window
        from lib_guard.window.resolver import default_window_path

        with tempfile.TemporaryDirectory() as td:
            library = {"library_id": "ip/vendor_A.ucie", "library_name": "vendor_A.ucie"}
            path = default_window_path(td, library, library["library_name"])
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps([]), encoding="utf-8")

            result = _pending_window({"catalog_html": td}, library)

        self.assertEqual(result["state"], "INVALID")
        self.assertEqual(result["candidate_effective_id"], "")

    def test_corrupt_catalog_is_not_reported_as_an_empty_pass(self) -> None:
        from lib_guard.web.read_model import load_web_state

        with tempfile.TemporaryDirectory() as td:
            catalog = Path(td) / "catalog.json"
            catalog.write_text("{bad json", encoding="utf-8")

            with self.assertRaises(OSError):
                load_web_state(
                    config={"catalog": str(catalog), "workspace": td, "raw_root": td},
                    cwd=td,
                )

    def test_scan_evidence_requires_this_version_inventory(self) -> None:
        from lib_guard.web.read_model import scan_evidence_ready

        with tempfile.TemporaryDirectory() as td:
            scan_dir = Path(td) / "scan"
            scan_dir.mkdir()
            self.assertFalse(scan_evidence_ready({"scan": {"status": "SCANNED", "scan_dir": str(scan_dir)}}))
            (scan_dir / "file_inventory.json").write_text(json.dumps({"files": []}), encoding="utf-8")
            self.assertTrue(scan_evidence_ready({"scan": {"status": "SCANNED", "scan_dir": str(scan_dir)}}))

    def test_scan_evidence_rejects_mismatched_scan_identity(self) -> None:
        from lib_guard.web.read_model import scan_evidence_ready

        with tempfile.TemporaryDirectory() as td:
            scan_dir = Path(td) / "scan"
            scan_dir.mkdir()
            (scan_dir / "file_inventory.json").write_text(
                json.dumps({"scan_id": "old", "root_path": str(Path(td) / "old-root"), "files": []}),
                encoding="utf-8",
            )
            version = {
                "raw_path": str(Path(td) / "new-root"),
                "scan": {"status": "SCANNED", "scan_dir": str(scan_dir), "scan_id": "new"},
            }

            self.assertFalse(scan_evidence_ready(version))

    def test_failed_compare_is_not_reported_as_completed(self) -> None:
        from lib_guard.web.read_model import _review_decision

        with tempfile.TemporaryDirectory() as td:
            scan_dir = Path(td) / "scan"
            scan_dir.mkdir()
            (scan_dir / "file_inventory.json").write_text(json.dumps({"files": []}), encoding="utf-8")
            result = _review_decision(
                {
                    "scan": {"status": "SCANNED", "scan_dir": str(scan_dir)},
                    "diff": {"base_version": "base", "base_status": "FAILED"},
                    "release": {"check_status": "UNKNOWN"},
                }
            )

        self.assertEqual(result["label"], "对比失败")
        self.assertEqual(result["next_action"], "查看对比结果")

    def test_unknown_library_returns_empty_version_rows(self) -> None:
        from lib_guard.web.read_model import list_version_rows, load_web_state

        state = load_web_state(config_path=SMOKE_CONFIG, cwd=ROOT)

        self.assertEqual(list_version_rows(state, "missing.library"), [])

    def test_file_tree_reads_inventory_without_walking_raw(self) -> None:
        from lib_guard.web.read_model import list_file_tree_rows

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            scan_dir = root / "scan"
            scan_dir.mkdir()
            (scan_dir / "file_inventory.json").write_text(
                json.dumps(
                    {
                        "root_path": str(root / "raw"),
                        "files": [
                            {"path": "LEF/macro.lef", "file_type": "lef", "size_bytes": 42, "role": "physical"},
                            {"path": "LIB/slow.lib", "file_type": "liberty", "size_bytes": 2048, "is_large_hash_skipped": True},
                        ],
                    }
                ),
                encoding="utf-8",
            )
            state = {
                "catalog": {
                    "libraries": [
                        {
                            "library_name": "demo",
                            "versions": [{"version_id": "v1", "raw_path": str(root / "raw"), "scan": {"scan_dir": str(scan_dir)}}],
                        }
                    ]
                }
            }
            result = list_file_tree_rows(state, "demo", "v1")

        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["file_count"], 2)
        self.assertEqual([item["path"] for item in result["files"]], ["LEF/macro.lef", "LIB/slow.lib"])
        self.assertEqual([item["display_path"] for item in result["files"]], ["LEF/macro.lef", "LIB/slow.lib"])
        self.assertEqual(result["files"][1]["evidence"], "大文件未读取完整内容")

    def test_file_tree_hides_single_packaging_root_only_in_display_path(self) -> None:
        from lib_guard.web.read_model import list_file_tree_rows

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            scan_dir = root / "scan"
            scan_dir.mkdir()
            (scan_dir / "file_inventory.json").write_text(
                json.dumps(
                    {
                        "root_path": str(root / "raw"),
                        "files": [
                            {"path": "upstream_ae9a8ed9/lef/macro.lef", "size_bytes": 3},
                            {"path": "upstream_ae9a8ed9/lib/cell.lib", "size_bytes": 4},
                        ],
                    }
                ),
                encoding="utf-8",
            )
            state = {
                "catalog": {
                    "libraries": [
                        {
                            "library_name": "demo",
                            "versions": [{"version_id": "v1", "raw_path": str(root / "raw"), "scan": {"scan_dir": str(scan_dir)}}],
                        }
                    ]
                }
            }
            result = list_file_tree_rows(state, "demo", "v1")

        self.assertEqual([item["path"] for item in result["files"]], ["upstream_ae9a8ed9/lef/macro.lef", "upstream_ae9a8ed9/lib/cell.lib"])
        self.assertEqual([item["display_path"] for item in result["files"]], ["lef/macro.lef", "lib/cell.lib"])

    def test_file_tree_missing_inventory_is_explicit(self) -> None:
        from lib_guard.web.read_model import list_file_tree_rows

        state = {
            "catalog": {
                "libraries": [
                    {"library_name": "demo", "versions": [{"version_id": "v1", "scan": {"scan_dir": "/missing/scan"}}]}
                ]
            }
        }

        result = list_file_tree_rows(state, "demo", "v1")

        self.assertEqual(result["status"], "NOT_READY")
        self.assertEqual(result["files"], [])


if __name__ == "__main__":
    unittest.main()
