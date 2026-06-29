from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


class VersionDetailReportTest(unittest.TestCase):
    def test_current_effective_wins_over_stale_diff_base(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            current_diff = root / "current_diff"
            stale_diff = root / "stale_diff"
            current_diff.mkdir()
            stale_diff.mkdir()
            (current_diff / "diff_summary.json").write_text(
                json.dumps({"status": "DIFF", "changed_files": 1, "view_changes": 1}, ensure_ascii=False),
                encoding="utf-8",
            )
            (current_diff / "view_diff.json").write_text(
                json.dumps({"summary": {"changed": 1}, "changed": [{"view": "lef"}]}, ensure_ascii=False),
                encoding="utf-8",
            )
            (current_diff / "type_diff.json").write_text(
                json.dumps({"summary": {"changed_types": 1}, "changed": [{"file_type": "lef"}]}, ensure_ascii=False),
                encoding="utf-8",
            )
            (current_diff / "release_readiness_diff.json").write_text(
                json.dumps({"status": "DIFF", "regressions": [{"check": "required_view_status"}]}, ensure_ascii=False),
                encoding="utf-8",
            )
            (current_diff / "release_evidence_diff.json").write_text(
                json.dumps({"status": "DIFF", "changed": [{"artifact": "release_readiness.json"}]}, ensure_ascii=False),
                encoding="utf-8",
            )
            (current_diff / "diff_issues.json").write_text(
                json.dumps({"issues": [{"category": "view_diff", "severity": "warning"}]}, ensure_ascii=False),
                encoding="utf-8",
            )
            (current_diff / "file_diff.json").write_text(
                json.dumps({"changed": [{"path": "lef/macro.lef", "file_type": "lef"}]}, ensure_ascii=False),
                encoding="utf-8",
            )
            (stale_diff / "diff_summary.json").write_text(
                json.dumps({"status": "SAME", "changed_files": 0}, ensure_ascii=False),
                encoding="utf-8",
            )

            from lib_guard.render.version_detail_report import build_version_update_detail_model

            model = build_version_update_detail_model(
                root / "html",
                {"library_id": "ip/ucie", "library_name": "ucie"},
                {
                    "version_id": "patch_20260628",
                    "current_effective_ref": "effective_current",
                    "diff": {
                        "base_version": "stale_adjacent_base",
                        "base_source": "adjacent",
                        "base_diff_dir": str(stale_diff),
                        "current_effective_diff_dir": str(current_diff),
                        "adjacent_old_version": "adjacent_only_fallback",
                    },
                },
            )

            self.assertEqual(model["base_ref"], "current_effective")
            self.assertEqual(model["base_version"], "effective_current")
            self.assertEqual(model["base_source"], "current_effective_ref")
            self.assertEqual(model["status"], "CHANGED")
            self.assertEqual(model["diff_summary"]["view_changes"], 1)
            self.assertEqual(model["view_diff"]["summary"]["changed"], 1)
            self.assertEqual(model["type_diff"]["summary"]["changed_types"], 1)
            self.assertEqual(model["release_readiness_diff"]["regressions"][0]["check"], "required_view_status")
            self.assertEqual(model["release_evidence_diff"]["changed"][0]["artifact"], "release_readiness.json")
            self.assertEqual(model["diff_issues"]["issues"][0]["category"], "view_diff")
            self.assertEqual(model["file_diff"]["changed"][0]["path"], "lef/macro.lef")
            for key in [
                "diff_summary",
                "file_diff",
                "view_diff",
                "type_diff",
                "release_readiness_diff",
                "release_evidence_diff",
                "diff_issues",
            ]:
                self.assertIn(key, model["trace_links"])

    def test_diff_base_only_high_priority_when_source_is_explicit_or_current_effective(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            diff_dir = root / "explicit_diff"
            diff_dir.mkdir()
            (diff_dir / "diff_summary.json").write_text(
                json.dumps({"status": "DIFF", "changed_files": 1}),
                encoding="utf-8",
            )

            from lib_guard.render.version_detail_report import build_version_update_detail_model

            explicit_model = build_version_update_detail_model(
                root / "html",
                {"library_id": "ip/ucie", "library_name": "ucie"},
                {
                    "version_id": "patch_20260628",
                    "diff": {
                        "base_version": "manual_base",
                        "base_source": "explicit",
                        "base_diff_dir": str(diff_dir),
                    },
                },
            )
            current_model = build_version_update_detail_model(
                root / "html",
                {"library_id": "ip/ucie", "library_name": "ucie"},
                {
                    "version_id": "patch_20260629",
                    "diff": {
                        "base_version": "effective_base",
                        "base_source": "current_effective",
                        "current_effective_diff_dir": str(diff_dir),
                    },
                },
            )

            self.assertEqual(explicit_model["base_ref"], "explicit")
            self.assertEqual(explicit_model["base_version"], "manual_base")
            self.assertEqual(current_model["base_ref"], "current_effective")
            self.assertEqual(current_model["base_version"], "effective_base")

    def test_current_library_diff_uses_current_effective_lane(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            current_diff = root / "current_diff"
            stale_base_diff = root / "base_diff"
            current_diff.mkdir()
            stale_base_diff.mkdir()
            (current_diff / "diff_summary.json").write_text(
                json.dumps({"status": "DIFF", "changed_files": 2, "view_changes": 1}),
                encoding="utf-8",
            )
            (stale_base_diff / "diff_summary.json").write_text(
                json.dumps({"status": "SAME", "changed_files": 0}),
                encoding="utf-8",
            )

            from lib_guard.render.version_detail_report import build_version_update_detail_model

            model = build_version_update_detail_model(
                root / "html",
                {"library_id": "ip/ucie", "library_name": "ucie"},
                {
                    "version_id": "patch_20260629",
                    "diff": {
                        "kind": "current_library_diff",
                        "base_version": "effective_current",
                        "base_diff_dir": str(stale_base_diff),
                        "current_effective_diff_dir": str(current_diff),
                    },
                },
            )

            self.assertEqual(model["base_ref"], "current_effective")
            self.assertEqual(model["base_version"], "effective_current")
            self.assertEqual(model["base_source"], "diff.base_version:current_library_diff")
            self.assertEqual(model["status"], "CHANGED")
            self.assertEqual(model["diff_summary"]["changed_files"], 2)

    def test_adjacent_is_fallback_and_missing_base_needs_confirmation(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)

            from lib_guard.render.version_detail_report import build_version_update_detail_model

            adjacent_model = build_version_update_detail_model(
                root / "html",
                {"library_id": "ip/ucie", "library_name": "ucie"},
                {
                    "version_id": "patch_20260628",
                    "diff": {"adjacent_old_version": "raw_previous"},
                },
            )
            missing_model = build_version_update_detail_model(
                root / "html",
                {"library_id": "ip/ucie", "library_name": "ucie"},
                {"version_id": "orphan_20260628"},
            )

            self.assertEqual(adjacent_model["base_ref"], "adjacent_fallback")
            self.assertEqual(adjacent_model["base_version"], "raw_previous")
            self.assertEqual(missing_model["status"], "NEEDS_BASE_CONFIRM")
            self.assertEqual(missing_model["base_ref"], "NEEDS_BASE_CONFIRM")

    def test_html_does_not_require_or_auto_export_current_lib_diff_markdown(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)

            from lib_guard.render.version_detail_report import (
                build_version_update_detail_model,
                export_current_lib_diff_markdown,
                render_version_detail_page,
                render_version_update_detail_panel,
            )

            lib = {"library_id": "ip/ucie", "library_name": "ucie"}
            version = {"version_id": "orphan_20260628"}
            model = build_version_update_detail_model(root / "html", lib, version)
            page = Path(render_version_detail_page(root / "html", lib, version))
            panel_before_md = render_version_update_detail_panel(model)
            md_path = page.parent / "current_lib_diff.md"
            self.assertFalse(md_path.exists())
            export_current_lib_diff_markdown(model, md_path)
            md_text = md_path.read_text(encoding="utf-8")
            md_path.unlink()
            panel_after_delete = render_version_update_detail_panel(model)
            html = page.read_text(encoding="utf-8")

            self.assertFalse(md_path.exists())
            self.assertEqual(panel_before_md, panel_after_delete)
            self.assertIn("NEEDS_BASE_CONFIRM", html)
            self.assertIn("NEEDS_BASE_CONFIRM", md_text)
            self.assertNotIn("NO_DIFF_SUMMARY", html)
            self.assertNotIn("Comparison Review 是唯一 diff 入口", html)


if __name__ == "__main__":
    unittest.main()
