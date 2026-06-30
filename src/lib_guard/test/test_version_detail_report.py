from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def _write_version_detail_lane_fixture(root: Path) -> tuple[dict[str, str], dict[str, object]]:
    diff_dir = root / "diff"
    diff_dir.mkdir()
    (diff_dir / "diff_summary.json").write_text(
        json.dumps({"status": "DIFF", "added_files": 1, "changed_files": 7}, ensure_ascii=False),
        encoding="utf-8",
    )
    (diff_dir / "file_diff.json").write_text(
        json.dumps(
            {
                "changed": [
                    {"path": "lef/top.lef", "file_type": "lef"},
                    {"path": "rtl/top.v", "file_type": "verilog"},
                    {"path": "timing/top.lib", "file_type": "liberty"},
                    {"path": "parasitics/top.spef", "file_type": "spef"},
                    {"path": "db/top.db", "file_type": "db"},
                    {"path": "layout/top.gds", "file_type": "gds"},
                    {"path": "layout/top.oas", "file_type": "oas"},
                ],
                "added": [{"path": "constraints/top.sdc", "file_type": "sdc"}],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    lib = {"library_id": "ip/lane_demo", "library_name": "lane_demo"}
    version = {
        "version_id": "patch_20260630",
        "diff": {
            "base_version": "base_20260629",
            "base_source": "explicit",
            "base_diff_dir": str(diff_dir),
        },
    }
    return lib, version


class VersionDetailReportTest(unittest.TestCase):
    def test_version_detail_groups_file_diff_evidence_by_review_lane(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            lib, version = _write_version_detail_lane_fixture(root)

            from lib_guard.render.version_detail_report import (
                build_version_update_detail_model,
                render_version_update_detail_panel,
            )

            model = build_version_update_detail_model(root / "html", lib, version)
            html = render_version_update_detail_panel(model)

            self.assertEqual(
                [item["path"] for item in model["recommended_file_diff"]],
                ["lef/top.lef", "constraints/top.sdc"],
            )
            self.assertEqual(
                [item["path"] for item in model["summary_only_reviewed"]],
                ["rtl/top.v", "timing/top.lib", "parasitics/top.spef"],
            )
            self.assertEqual(
                [item["path"] for item in model["metadata_only_reviewed"]],
                ["db/top.db", "layout/top.gds", "layout/top.oas"],
            )
            self.assertIn("Recommended File Diff", html)
            self.assertIn("Summary-only Reviewed", html)
            self.assertIn("Metadata-only Reviewed", html)
            self.assertIn("已完成摘要级审查；默认无需展开全文。", html)
            self.assertIn("已完成 metadata-only 审查；二进制/版图文件默认不做全文 diff。", html)
            summary_section = html.split("Summary-only Reviewed", 1)[1].split("Metadata-only Reviewed", 1)[0]
            metadata_section = html.split("Metadata-only Reviewed", 1)[1].split("Release note", 1)[0]
            self.assertNotIn("未生成 File Diff", summary_section)
            self.assertNotIn("未生成 File Diff", metadata_section)

    def test_markdown_export_uses_same_headline_and_evidence_counts_as_model(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            lib, version = _write_version_detail_lane_fixture(root)

            from lib_guard.render.version_detail_report import (
                build_version_update_detail_model,
                export_current_lib_diff_markdown,
            )

            model = build_version_update_detail_model(root / "html", lib, version)
            md_path = root / "current_lib_diff.md"
            export_current_lib_diff_markdown(model, md_path)
            text = md_path.read_text(encoding="utf-8")

            self.assertIn(model["headline"], text)
            self.assertIn(model["confidence_note"], text)
            self.assertIn(f"recommended_file_diff: {len(model['recommended_file_diff'])}", text)
            self.assertIn(f"summary_only_reviewed: {len(model['summary_only_reviewed'])}", text)
            self.assertIn(f"metadata_only_reviewed: {len(model['metadata_only_reviewed'])}", text)
            self.assertIn("## Summary-only Reviewed", text)
            self.assertIn("## Metadata-only Reviewed", text)
            self.assertIn("## Diff Issues", text)

    def test_view_type_release_issues_are_visible_in_update_detail_panel(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            lib, version = _write_version_detail_lane_fixture(root)
            diff_dir = root / "diff"
            (diff_dir / "view_diff.json").write_text(
                json.dumps(
                    {
                        "summary": {"changed": 1},
                        "changed": [{"view": "timing", "status": "changed"}],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (diff_dir / "type_diff.json").write_text(
                json.dumps(
                    {
                        "summary": {"changed_types": 1},
                        "changed": [{"file_type": "liberty", "status": "changed"}],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (diff_dir / "release_readiness_diff.json").write_text(
                json.dumps(
                    {
                        "status": "DIFF",
                        "regressions": [{"check": "required_view_status", "from": "PASS", "to": "WARNING"}],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (diff_dir / "release_evidence_diff.json").write_text(
                json.dumps(
                    {
                        "status": "DIFF",
                        "changed": [{"artifact": "release_readiness.json", "reason": "readiness changed"}],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (diff_dir / "diff_issues.json").write_text(
                json.dumps(
                    {
                        "issues": [
                            {
                                "severity": "warning",
                                "category": "view_diff",
                                "title": "Timing view changed",
                                "message": "Review timing collateral.",
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            from lib_guard.render.version_detail_report import (
                build_version_update_detail_model,
                render_version_update_detail_panel,
            )

            model = build_version_update_detail_model(root / "html", lib, version)
            html = render_version_update_detail_panel(model)

            self.assertIn("View Changes", html)
            self.assertIn("Type Changes", html)
            self.assertIn("Release Readiness Changes", html)
            self.assertIn("Release Evidence Changes", html)
            self.assertIn("Diff Issues", html)
            self.assertIn("Timing view changed", html)
            self.assertIn("required_view_status", html)
            self.assertIn("release_readiness.json", html)
            self.assertLess(html.index("Diff Issues"), html.index("建议动作"))

    def test_version_update_detail_model_exposes_headline_confidence_and_primary_action(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            lib, version = _write_version_detail_lane_fixture(root)
            diff_dir = root / "diff"
            (diff_dir / "diff_summary.json").write_text(
                json.dumps({"status": "DIFF", "added_files": 1, "changed_files": 6}, ensure_ascii=False),
                encoding="utf-8",
            )
            file_diff = json.loads((diff_dir / "file_diff.json").read_text(encoding="utf-8"))
            file_diff["changed"] = [item for item in file_diff["changed"] if item["path"] != "layout/top.oas"]
            (diff_dir / "file_diff.json").write_text(json.dumps(file_diff, ensure_ascii=False), encoding="utf-8")
            version["package_type"] = "FULL_PACKAGE"
            version["current_effective_ref"] = "base_20260629"
            version["diff"] = {
                "base_version": "stale_base",
                "base_source": "adjacent",
                "base_diff_dir": str(root / "stale_diff"),
                "current_effective_diff_dir": str(root / "diff"),
            }

            from lib_guard.render.version_detail_report import (
                build_version_update_detail_model,
                render_version_update_detail_panel,
            )

            model = build_version_update_detail_model(root / "html", lib, version)
            html = render_version_update_detail_panel(model)

            self.assertIn("headline", model)
            self.assertIn("confidence_note", model)
            self.assertIn("primary_next_action", model)
            self.assertEqual(model["base_ref"], "current_effective")
            self.assertEqual(model["primary_next_action"]["kind"], "file_diff_recommended")
            self.assertEqual(model["primary_next_action"]["command_count"], 2)
            self.assertIn("当前版本相对 current_effective", model["headline"])
            self.assertIn("2 个建议下钻", model["headline"])
            self.assertIn("5 个已按 Summary/Metadata-only 审查", model["headline"])
            self.assertIn("Base source=current_effective", model["confidence_note"])
            self.assertIn("comparison_semantics=full", model["confidence_note"])
            self.assertIn(model["headline"], html)
            self.assertIn(model["confidence_note"], html)
            self.assertIn("Run recommended File Diff", html)

    def test_version_detail_headline_mentions_base_and_lane_counts(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            lib, version = _write_version_detail_lane_fixture(root)

            from lib_guard.render.version_detail_report import build_version_update_detail_model

            model = build_version_update_detail_model(root / "html", lib, version)

            self.assertEqual(
                model["lane_counts"],
                {
                    "recommended_file_diff": 2,
                    "summary_only": 3,
                    "metadata_only": 3,
                    "blocking_issues": 0,
                },
            )
            self.assertEqual(model["reviewed_units_for_headline"], 5)
            self.assertEqual(model["summary_only_changes"], model["summary_only_reviewed"])
            self.assertEqual(model["metadata_only_reviewed_changes"], model["metadata_only_reviewed"])
            self.assertEqual(
                [item["path"] for item in model["metadata_only_changes"]],
                [
                    "rtl/top.v",
                    "timing/top.lib",
                    "parasitics/top.spef",
                    "db/top.db",
                    "layout/top.gds",
                    "layout/top.oas",
                ],
            )
            self.assertIn("当前版本相对 explicit", model["headline"])
            self.assertIn("2 个建议下钻", model["headline"])
            self.assertIn("5 个已按 Summary/Metadata-only 审查", model["headline"])

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

    def test_adjacent_fallback_warns_that_update_detail_is_manual_compare_debug_only(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            diff_dir = root / "adjacent_diff"
            diff_dir.mkdir()
            (diff_dir / "diff_summary.json").write_text(
                json.dumps({"status": "DIFF", "changed_files": 1}, ensure_ascii=False),
                encoding="utf-8",
            )

            from lib_guard.render.version_detail_report import (
                build_version_update_detail_model,
                render_version_update_detail_panel,
            )

            model = build_version_update_detail_model(
                root / "html",
                {"library_id": "ip/ucie", "library_name": "ucie"},
                {
                    "version_id": "patch_20260630",
                    "diff": {
                        "adjacent_old_version": "raw_previous",
                        "adjacent_diff_dir": str(diff_dir),
                    },
                },
            )
            html = render_version_update_detail_panel(model)

            self.assertEqual(model["base_ref"], "adjacent_fallback")
            self.assertEqual(model["base_trust_status"], "WARNING")
            self.assertIn("该结果不是标准 current-effective 更新详情，仅供手动 compare/debug；release 前请确认 base。", html)
            for label in [
                "Base source",
                "Base version",
                "Target version",
                "Comparison semantics",
                "Delete semantics",
                "Markdown export",
            ]:
                self.assertIn(label, html)

    def test_missing_base_blocks_update_detail_and_drives_primary_next_action(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)

            from lib_guard.render.version_detail_report import (
                build_version_update_detail_model,
                render_version_update_detail_panel,
            )

            model = build_version_update_detail_model(
                root / "html",
                {"library_id": "ip/ucie", "library_name": "ucie"},
                {"version_id": "orphan_20260630"},
            )
            html = render_version_update_detail_panel(model)

            self.assertEqual(model["status"], "NEEDS_BASE_CONFIRM")
            self.assertEqual(model["base_trust_status"], "BLOCKING")
            self.assertEqual(model["primary_next_action"]["kind"], "base_confirm_required")
            self.assertIn("无法确定 base；请先确认 current_effective 或 previous_effective。", html)
            self.assertIn("BLOCKING", html)

    def test_update_detail_status_copy_is_actionable(self) -> None:
        from lib_guard.render.version_detail_report import render_version_update_detail_panel

        cases = {
            "DIFF_NOT_RUN": "尚未生成更新详情；请运行 lg refresh <LIB>。",
            "NEEDS_BASE_CONFIRM": "无法确定 base；请先确认 current_effective 或 previous_effective。",
            "NO_DIFF_SUMMARY": "找到 diff 输出目录，但缺少 diff_summary.json；请检查 compare artifact。",
            "CHANGED": "已完成比较，有变化。",
            "SAME": "已完成比较，无变化。",
        }
        for status, expected in cases.items():
            with self.subTest(status=status):
                model = {
                    "status": status,
                    "base_ref": "current_effective",
                    "base_version": "base_20260629",
                    "target_version": "patch_20260630",
                    "comparison_semantics": "full",
                    "delete_semantics": "real_delete",
                    "headline": "当前版本相对 current_effective 有 0 个变化文件，0 个建议下钻，0 个已按 Summary/Metadata-only 审查。",
                    "confidence_note": "Base source=current_effective ref=base_20260629 source_detail=current_effective_ref; comparison_semantics=full; delete_semantics=real_delete",
                    "primary_next_action": {
                        "kind": "review_evidence",
                        "label": "Review evidence",
                        "command_count": 0,
                    },
                    "summary_metrics": [],
                    "file_changes": [],
                    "recommended_file_diff": [],
                    "summary_only_reviewed": [],
                    "metadata_only_reviewed": [],
                    "release_notes": [],
                    "recommended_actions": [],
                    "file_diff_recommendations": [],
                    "metadata_only_changes": [],
                }

                html = render_version_update_detail_panel(model)

                if status == "DIFF_NOT_RUN":
                    self.assertIn("尚未生成更新详情；请运行 lg refresh &lt;LIB&gt;。", html)
                    self.assertNotIn("lg refresh <LIB>", html)
                else:
                    self.assertIn(expected, html)

    def test_existing_diff_dir_without_summary_is_reported_as_missing_summary(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            diff_dir = root / "diff"
            diff_dir.mkdir()

            from lib_guard.render.version_detail_report import build_version_update_detail_model

            model = build_version_update_detail_model(
                root / "html",
                {"library_id": "ip/ucie", "library_name": "ucie"},
                {
                    "version_id": "patch_20260630",
                    "current_effective_ref": "base_20260629",
                    "diff": {
                        "current_effective_diff_dir": str(diff_dir),
                    },
                },
            )

            self.assertEqual(model["status"], "NO_DIFF_SUMMARY")
            self.assertEqual(
                model["status_message"],
                "找到 diff 输出目录，但缺少 diff_summary.json；请检查 compare artifact。",
            )

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
