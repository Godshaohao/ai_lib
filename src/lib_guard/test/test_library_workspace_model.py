from __future__ import annotations

import tempfile
import unittest
from pathlib import Path


class LibraryWorkspaceModelTest(unittest.TestCase):
    def test_separates_current_effective_candidate_and_effective_evidence(self) -> None:
        from lib_guard.render.library_workspace_model import build_library_workspace_model

        lib = {
            "library_id": "ip/ucie",
            "library_name": "ucie",
            "latest_version": "adhoc_20260624",
            "versions": [
                {
                    "version_id": "stable_20260601",
                    "current_effective": True,
                    "scan": {"status": "SCANNED"},
                    "diff_status": "PASS",
                },
                {
                    "version_id": "adhoc_20260624",
                    "previous_effective_version": "stable_20260601",
                    "scan": {"status": "NOT_SCANNED"},
                    "diff_status": "COMPARE_PENDING",
                },
            ],
        }
        effective_items = [
            {
                "effective_id": "E1_20260624",
                "manifest": "/tmp/E1/effective_manifest.json",
                "html": "/tmp/E1/index.html",
                "release_preview": "/tmp/E1/release_preview/index.html",
            }
        ]

        model = build_library_workspace_model(lib, effective_items)

        self.assertEqual(model["current_effective_ref"], "stable_20260601")
        self.assertEqual(model["current_effective_source"], "version_flag")
        self.assertEqual(model["latest_candidate_ref"], "adhoc_20260624")
        self.assertEqual(model["base_ref"], "stable_20260601")
        self.assertEqual(model["effective_evidence_ref"], "E1_20260624")
        self.assertEqual(model["effective_evidence_manifest"], "/tmp/E1/effective_manifest.json")
        self.assertTrue(model["needs_review"])

    def test_current_effective_manifest_pointer_wins_when_marked_current(self) -> None:
        from lib_guard.render.library_workspace_model import build_library_workspace_model

        lib = {
            "library_id": "ip/ucie",
            "library_name": "ucie",
            "latest_version": "patch_20260624",
            "versions": [
                {"version_id": "base_20260601"},
                {"version_id": "patch_20260624", "current_effective_ref": "E_CURRENT"},
            ],
        }
        effective_items = [
            {
                "effective_id": "E_CURRENT",
                "is_current_effective": True,
                "manifest": "/tmp/E_CURRENT/effective_manifest.json",
            }
        ]

        model = build_library_workspace_model(lib, effective_items)

        self.assertEqual(model["current_effective_ref"], "E_CURRENT")
        self.assertEqual(model["current_effective_source"], "effective_manifest")
        self.assertEqual(model["latest_candidate_ref"], "patch_20260624")
        self.assertEqual(model["effective_evidence_ref"], "E_CURRENT")

    def test_missing_current_effective_is_unconfirmed_and_blocks_use_decision(self) -> None:
        from lib_guard.render.library_workspace_model import build_library_workspace_model

        lib = {
            "library_id": "ip/ucie",
            "library_name": "ucie",
            "latest_version": "patch_20260624",
            "versions": [
                {"version_id": "base_20260601", "scan": {"status": "SCANNED"}, "diff_status": "PASS"},
                {
                    "version_id": "patch_20260624",
                    "previous_effective_version": "base_20260601",
                    "scan": {"status": "NOT_SCANNED"},
                    "diff_status": "COMPARE_PENDING",
                },
            ],
        }

        model = build_library_workspace_model(lib, [])

        self.assertEqual(model["current_effective_ref"], "未确认")
        self.assertEqual(model["current_effective_source"], "unconfirmed")
        self.assertFalse(model["current_effective_confirmed"])
        self.assertEqual(model["latest_candidate_ref"], "patch_20260624")
        self.assertEqual(model["base_ref"], "base_20260601")
        self.assertTrue(model["needs_review"])
        self.assertEqual(model["decision"], "需确认当前有效版")
        self.assertIn("确认当前有效版", model["candidate_action_text"])

    def test_library_workspace_html_does_not_expose_internal_status_codes(self) -> None:
        from lib_guard.render.catalog_workspace_report import render_library_workspace_page

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            lib = {
                "library_id": "ip/ucie",
                "library_name": "ucie",
                "display_name": "ucie",
                "latest_version": "patch_20260624",
                "versions": [
                    {
                        "version_id": "patch_20260624",
                        "scan": {"status": "NOT_SCANNED"},
                        "diff_status": "DIFF_REVIEW",
                    }
                ],
            }

            page = Path(render_library_workspace_page(root / "html", lib, []))
            html = page.read_text(encoding="utf-8")

            self.assertNotIn("NOT_SCANNED", html)
            self.assertNotIn("DIFF_REVIEW", html)
            self.assertIn("未扫描", html)
            self.assertIn("对比需审查", html)
            self.assertNotIn(">待对比<", html)

    def test_library_workspace_keeps_full_version_list_below_focus_summary(self) -> None:
        from lib_guard.render.catalog_workspace_report import render_library_workspace_page

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            lib = {
                "library_id": "ip/ucie",
                "library_name": "ucie",
                "display_name": "ucie",
                "latest_version": "patch_20260624",
                "versions": [
                    {
                        "version_id": "base_20250501",
                        "scan": {"status": "SCANNED"},
                        "diff_status": "PASS",
                    },
                    {
                        "version_id": "base_20260601",
                        "current_effective": True,
                        "scan": {"status": "SCANNED"},
                        "diff_status": "PASS",
                    },
                    {
                        "version_id": "patch_20260624",
                        "previous_effective_version": "base_20260601",
                        "scan": {"status": "NOT_SCANNED"},
                        "diff_status": "COMPARE_PENDING",
                    },
                ],
            }

            page = Path(render_library_workspace_page(root / "html", lib, []))
            html = page.read_text(encoding="utf-8")

            self.assertIn("库版本清单", html)
            self.assertIn("base_20250501", html)
            self.assertIn("base_20260601", html)
            self.assertIn("patch_20260624", html)
            self.assertIn("3 个版本", html)

    def test_library_workspace_scan_label_accepts_enriched_scan_status(self) -> None:
        from lib_guard.render.catalog_workspace_report import render_library_workspace_page

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            lib = {
                "library_id": "ip/ucie",
                "library_name": "ucie",
                "display_name": "ucie",
                "latest_version": "patch_20260624",
                "versions": [
                    {
                        "version_id": "patch_20260624",
                        "scan_status": "SCAN_PASS",
                        "scan": {"status": "SCANNED", "scan_dir": str(root / "scan")},
                    }
                ],
            }

            page = Path(render_library_workspace_page(root / "html", lib, []))
            html = page.read_text(encoding="utf-8")

            self.assertIn("已扫", html)
            self.assertNotIn(">未扫<", html)


if __name__ == "__main__":
    unittest.main()
