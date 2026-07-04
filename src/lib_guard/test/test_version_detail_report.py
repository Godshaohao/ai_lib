from __future__ import annotations

import json
import sys
import tempfile
import unittest
from unittest.mock import patch
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
    def test_review_model_rules_are_available_outside_renderer(self) -> None:
        from lib_guard.review.model_rules import (
            classify_review_lane,
            comparison_semantics_for_package,
            resolve_review_base,
        )

        base = resolve_review_base({"version_id": "patch", "current_effective_ref": "effective_current"})
        lane = classify_review_lane("db")
        semantics = comparison_semantics_for_package("PARTIAL_UPDATE")

        self.assertEqual(base["base_ref"], "current_effective")
        self.assertEqual(base["base_version"], "effective_current")
        self.assertEqual(lane["lane"], "Metadata-only")
        self.assertEqual(semantics["comparison_scope"], "incremental")

    def test_version_detail_groups_file_diff_evidence_by_review_lane(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            lib, version = _write_version_detail_lane_fixture(root)

            from lib_guard.render.version_detail_report import (
                _audit_evidence_panel,
                build_version_update_detail_model,
                render_version_update_detail_panel,
            )

            model = build_version_update_detail_model(root / "html", lib, version)
            main_html = render_version_update_detail_panel(model)
            audit_html = _audit_evidence_panel(model)
            html = main_html + audit_html

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
            self.assertIn("重点变化文件", main_html)
            self.assertNotIn("Summary-only / Metadata-only 明细", main_html)
            self.assertIn("审计证据", audit_html)
            self.assertIn("Summary-only / Metadata-only 明细", audit_html)
            self.assertIn("Summary-only Reviewed", html)
            self.assertIn("Metadata-only Reviewed", html)
            self.assertIn("证据分层", html)
            self.assertIn("混合证据", html)
            self.assertIn("摘要级 3", html)
            self.assertIn("metadata-only 3", html)
            summary_section = html.split("Summary-only Reviewed", 1)[1].split("Metadata-only Reviewed", 1)[0]
            metadata_section = html.split("Metadata-only Reviewed", 1)[1].split("Release note", 1)[0]
            self.assertNotIn("未生成 File Diff", summary_section)
            self.assertNotIn("未生成 File Diff", metadata_section)

    def test_compressed_collateral_uses_real_file_type_not_gzip_suffix(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            lib, version = _write_version_detail_lane_fixture(root)
            diff_dir = root / "diff"
            (diff_dir / "file_diff.json").write_text(
                json.dumps(
                    {
                        "added": [
                            {"path": "timing/lib_fast.lib.gz", "file_type": "gz"},
                            {"path": "parasitics/top.spef.gz", "file_type": "gz"},
                            {"path": "rtl/top.v.gz", "file_type": "gz"},
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            from lib_guard.render.version_detail_report import build_version_update_detail_model

            model = build_version_update_detail_model(root / "html", lib, version)
            by_path = {item["path"]: item["file_type"] for item in model["file_changes"]}

            self.assertEqual(by_path["timing/lib_fast.lib.gz"], "liberty")
            self.assertEqual(by_path["parasitics/top.spef.gz"], "spef")
            self.assertEqual(by_path["rtl/top.v.gz"], "verilog")
            self.assertNotIn("gz", set(by_path.values()))

    def test_update_detail_lane_sections_use_reviewer_columns(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            lib, version = _write_version_detail_lane_fixture(root)

            from lib_guard.render.version_detail_report import (
                _audit_evidence_panel,
                build_version_update_detail_model,
                render_version_update_detail_panel,
            )

            model = build_version_update_detail_model(root / "html", lib, version)
            model["recommended_file_diff"][0]["reason"] = "sentinel recommended reason"
            model["summary_only_reviewed"][0]["summary_evidence"] = "sentinel summary evidence"
            model["summary_only_reviewed"][0]["reason"] = "sentinel summary reason"
            model["metadata_only_reviewed"][0]["metadata_evidence"] = "sentinel metadata evidence"
            model["metadata_only_reviewed"][0]["reason"] = "sentinel metadata reason"
            main_html = render_version_update_detail_panel(model)
            audit_html = _audit_evidence_panel(model)
            html = main_html + audit_html

            recommended_section = main_html.split("重点变化文件", 1)[1]
            summary_section = audit_html.split("Summary-only Reviewed", 1)[1].split("Metadata-only Reviewed", 1)[0]
            metadata_section = audit_html.split("Metadata-only Reviewed", 1)[1].split("Release note", 1)[0]

            for header in ["变化", "类型", "路径", "审查级别", "建议"]:
                self.assertIn(header, recommended_section)
            for header in ["file_type", "path", "summary evidence", "reason"]:
                self.assertIn(header, summary_section)
            for header in ["file_type", "path", "metadata evidence", "reason"]:
                self.assertIn(header, metadata_section)
            self.assertIn("lef/top.lef", recommended_section)
            self.assertIn("constraints/top.sdc", recommended_section)
            self.assertIn("重点确认内容变化或等价性", recommended_section)
            self.assertIn("先按 basename/hash/parser signature 匹配 old/new", recommended_section)
            self.assertNotIn("lg.csh fd lane_demo patch_20260630 lef/top.lef", recommended_section)
            self.assertNotIn("lg.csh fd lane_demo patch_20260630 lef/top.lef", html)
            self.assertNotIn("lg.csh fd lane_demo patch_20260630 constraints/top.sdc", html)
            for path in ["rtl/top.v", "timing/top.lib", "parasitics/top.spef"]:
                self.assertIn(path, summary_section)
            self.assertIn("sentinel summary evidence", summary_section)
            self.assertIn("sentinel summary reason", summary_section)
            self.assertIn(
                "<td><code>timing/top.lib</code></td>"
                "<td>摘要级审查；默认不做文件级深度比较</td>"
                "<td>已完成摘要级审查</td>",
                summary_section,
            )
            for path in ["db/top.db", "layout/top.gds", "layout/top.oas"]:
                self.assertIn(path, metadata_section)
            self.assertIn("sentinel metadata evidence", metadata_section)
            self.assertIn("sentinel metadata reason", metadata_section)
            self.assertIn(
                "<td><code>layout/top.gds</code></td>"
                "<td>metadata-only 审查；默认只看元数据/哈希/规模</td>"
                "<td>metadata-only 审查</td>",
                metadata_section,
            )

    def test_path_restructure_is_called_out_before_full_file_list(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            diff_dir = root / "diff"
            diff_dir.mkdir()
            (diff_dir / "diff_summary.json").write_text(
                json.dumps(
                    {
                        "status": "DIFF",
                        "added_files": 181,
                        "removed_files": 10,
                        "changed_files": 0,
                        "renamed_or_moved": 23,
                        "package_root_migrations": 1,
                        "package_root_migration_matched_files": 31,
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (diff_dir / "file_diff.json").write_text(
                json.dumps(
                    {
                        "added": ["upstream_ae9a8ed9/lef/top.lef"],
                        "removed": ["asap7_source_package/lef/top.lef"],
                        "changed": [],
                        "renamed_or_moved": [
                            {"old": "asap7_source_package/README.md", "new": "upstream_ae9a8ed9/README.md"},
                        ],
                        "package_root_migrations": [
                            {
                                "old_root": "asap7_source_package",
                                "new_root": "upstream_ae9a8ed9",
                                "matched_logical_paths": 31,
                                "old_root_file_count": 31,
                                "new_root_file_count": 206,
                                "raw_added_under_new_root": 181,
                                "raw_removed_under_old_root": 9,
                            }
                        ],
                        "counts": {
                            "added": 181,
                            "removed": 10,
                            "changed": 0,
                            "renamed_or_moved": 23,
                            "package_root_migrations": 1,
                            "package_root_migration_matched_files": 31,
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            from lib_guard.render.version_detail_report import (
                build_version_update_detail_model,
                render_version_update_detail_panel,
            )

            model = build_version_update_detail_model(
                root / "html",
                {"library_id": "ip/asap7", "library_name": "asap7"},
                {
                    "version_id": "20260627_asap7",
                    "current_effective_ref": "20260624_asap7",
                    "diff": {"current_effective_diff_dir": str(diff_dir)},
                },
            )
            html = render_version_update_detail_panel(model)

            self.assertTrue(model["path_restructure"]["suspected"])
            self.assertIn("修改文件 0 个，新增 181 个，删除 10 个", model["headline"])
            self.assertIn("疑似重打包 / 目录迁移", html)
            self.assertIn("old root: <code>asap7_source_package</code>", html)
            self.assertIn("new root: <code>upstream_ae9a8ed9</code>", html)
            self.assertIn("逻辑路径匹配 31", html)
            self.assertIn("old 包内 31 个文件，new 包内 206 个文件", html)
            self.assertIn("文件级 moved/renamed 23", html)
            self.assertLess(html.index("疑似重打包 / 目录迁移"), html.index("重点变化文件"))

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
            self.assertIn(f"usage_decision: {model['usage_decision']}", text)
            self.assertIn("usage_decision_reasons:", text)
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
                _audit_evidence_panel,
                build_version_update_detail_model,
            )

            model = build_version_update_detail_model(root / "html", lib, version)
            html = _audit_evidence_panel(model)

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
            self.assertEqual(model["file_diff_recommendations"], [])
            self.assertEqual(model["base_ref"], "current_effective")
            self.assertEqual(model["primary_next_action"]["kind"], "file_diff_recommended")
            self.assertEqual(model["primary_next_action"]["command_count"], 0)
            self.assertIn("当前版本相对 current_effective", model["headline"])
            self.assertIn("修改文件 6 个，新增 1 个，删除 0 个", model["headline"])
            self.assertIn("2 个需要优先下钻", model["headline"])
            self.assertIn("5 个按 Summary/Metadata-only 处理", model["headline"])
            self.assertIn("Base source=current_effective", model["confidence_note"])
            self.assertIn("comparison_semantics=full", model["confidence_note"])
            self.assertIn(model["headline"], html)
            self.assertIn(model["confidence_note"], html)
            self.assertIn("重点变化文件", html)
            self.assertIn("变化风险", html)
            self.assertIn("P0/P1=2", html)
            self.assertNotIn("Run recommended File Diff", html)
            self.assertNotIn("文件级 Diff 命令", html)
            self.assertNotIn("$PROJ/scripts/lg.csh fd", html)

    def test_version_update_detail_model_exposes_single_usage_decision(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            lib, version = _write_version_detail_lane_fixture(root)

            from lib_guard.render.version_detail_report import build_version_update_detail_model

            model = build_version_update_detail_model(root / "html", lib, version)

            self.assertEqual(model["usage_decision"], "USAGE_REVIEW_REQUIRED")
            self.assertIn("usage_decision_reasons", model)
            self.assertIn("diff_changed", model["usage_decision_reasons"])
            self.assertIn("recommended_file_diff", model["usage_decision_reasons"])
            self.assertIn("release_note_missing", model["usage_decision_reasons"])

            missing = build_version_update_detail_model(
                root / "html",
                {"library_id": "ip/ucie", "library_name": "ucie"},
                {"version_id": "orphan_20260630"},
            )
            self.assertEqual(missing["usage_decision"], "BLOCKED")
            self.assertIn("base_not_confirmed", missing["usage_decision_reasons"])

    def test_version_detail_top_copy_uses_ip_user_status_contract(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            lib, version = _write_version_detail_lane_fixture(root)
            version["review_gate"] = {
                "status": "REVIEW_REQUIRED",
                "blocking_items": [{"id": "gate.release_note", "title": "Release note missing"}],
                "attention_items": [],
            }

            from lib_guard.render.version_detail_report import render_version_detail_page

            page = Path(render_version_detail_page(root / "html", lib, version))
            html = page.read_text(encoding="utf-8")

            from lib_guard.render.version_detail_report import build_version_update_detail_model

            model = build_version_update_detail_model(root / "html", lib, version)
            self.assertEqual(model["usage_decision"], "BLOCKED")
            self.assertIn("review_gate_blocking", model["usage_decision_reasons"])
            self.assertIn("必需 View 覆盖", html)
            self.assertNotIn("View 完整性", html)
            self.assertIn("Release note", html)
            self.assertIn("缺失", html)
            self.assertIn("管理门禁", html)
            self.assertIn("影响使用", html)
            self.assertNotIn("门禁状态</div><div class='metric-value'>需审阅", html)
            self.assertNotIn("阻塞项</div><div class='metric-value'>1", html)

    def test_version_update_detail_model_carries_scan_and_comparison_context(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            scan_dir = root / "scan"
            diff_dir = root / "diff"
            scan_dir.mkdir()
            diff_dir.mkdir()
            (scan_dir / "summary").mkdir()
            (scan_dir / "scan_meta.json").write_text(
                json.dumps(
                    {
                        "scan_id": "SCAN_TARGET",
                        "library_id": "ip/ucie",
                        "version": "patch_20260701",
                        "root_path": str(root / "raw"),
                        "input_fingerprint": "fingerprint-target",
                        "tool_version": "0.5.0",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (scan_dir / "file_inventory.json").write_text(
                json.dumps({"file_type_counts": {"lef": 1, "unknown": 1}}, ensure_ascii=False),
                encoding="utf-8",
            )
            (scan_dir / "parser_manifest.json").write_text(
                json.dumps({"files": [{"parser_tasks": [{"parser_name": "LefParser"}]}]}, ensure_ascii=False),
                encoding="utf-8",
            )
            (scan_dir / "parser_results.json").write_text(json.dumps({"results": []}), encoding="utf-8")
            (scan_dir / "summary" / "release_readiness.json").write_text(
                json.dumps({"required_view_status": "PASS"}, ensure_ascii=False),
                encoding="utf-8",
            )
            (diff_dir / "diff_meta.json").write_text(
                json.dumps(
                    {
                        "diff_type": "scan_output_diff",
                        "old_scan": str(root / "base_scan"),
                        "new_scan": str(scan_dir),
                        "old_scan_id": "SCAN_BASE",
                        "new_scan_id": "SCAN_TARGET",
                        "version_relation": {"diff_mode": "current_effective"},
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (diff_dir / "diff_summary.json").write_text(
                json.dumps({"status": "DIFF", "changed_files": 1}, ensure_ascii=False),
                encoding="utf-8",
            )

            from lib_guard.render.version_detail_report import build_version_update_detail_model

            model = build_version_update_detail_model(
                root / "html",
                {"library_id": "ip/ucie", "library_name": "ucie"},
                {
                    "version_id": "patch_20260701",
                    "scan": {"scan_dir": str(scan_dir)},
                    "current_effective_ref": "base_20260630",
                    "diff": {"current_effective_diff_dir": str(diff_dir)},
                },
            )

            self.assertEqual(model["scan_context"]["scan_id"], "SCAN_TARGET")
            self.assertEqual(model["scan_context"]["input_fingerprint"], "fingerprint-target")
            self.assertEqual(model["scan_evidence"]["parser_task_count"], 1)
            self.assertEqual(model["scan_evidence"]["unknown_count"], 1)
            self.assertEqual(model["scan_evidence"]["required_view_status"], "PASS")
            self.assertEqual(model["comparison_context"]["old_scan_id"], "SCAN_BASE")
            self.assertEqual(model["comparison_context"]["new_scan_id"], "SCAN_TARGET")
            self.assertEqual(model["comparison_context"]["relation_kind"], "current_effective")
            self.assertEqual(model["scan_compatibility"]["status"], "PASS")
            self.assertTrue(model["scan_compatibility"]["new_scan_matches_current"])

    def test_file_changes_expose_identity_without_claiming_equivalence(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            lib, version = _write_version_detail_lane_fixture(root)
            diff_dir = root / "diff"
            (diff_dir / "file_diff.json").write_text(
                json.dumps(
                    {
                        "added": [
                            {
                                "path": "upstream_ae9a8ed9/lef/top.lef",
                                "file_type": "lef",
                                "sha256": "new_hash",
                                "size": 120,
                                "parser_signature": "macro:top,pins:4",
                            }
                        ],
                        "removed": [
                            {
                                "path": "asap7_source_package/lef/top.lef",
                                "file_type": "lef",
                                "sha256": "old_hash",
                                "size": 120,
                                "parser_signature": "macro:top,pins:4",
                            }
                        ],
                        "counts": {"added": 1, "removed": 1, "changed": 0},
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            from lib_guard.render.version_detail_report import build_version_update_detail_model

            model = build_version_update_detail_model(root / "html", lib, version)
            by_path = {item["path"]: item for item in model["file_changes"]}
            added = by_path["upstream_ae9a8ed9/lef/top.lef"]
            removed = by_path["asap7_source_package/lef/top.lef"]

            self.assertEqual(added["identity"]["basename"], "top.lef")
            self.assertEqual(added["identity"]["suffix"], ".lef")
            self.assertEqual(added["identity"]["sha256"], "new_hash")
            self.assertEqual(added["identity"]["size"], 120)
            self.assertEqual(added["identity"]["parser_signature"], "macro:top,pins:4")
            self.assertEqual(added["identity"]["match_key"], "lef:top.lef:120:macro:top,pins:4")
            self.assertEqual(removed["identity"]["match_key"], "lef:top.lef:120:macro:top,pins:4")
            self.assertNotIn("equivalent", added)

    def test_path_migration_evidence_is_attached_to_focus_rows(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            diff_dir = root / "diff"
            diff_dir.mkdir()
            (diff_dir / "diff_summary.json").write_text(
                json.dumps(
                    {
                        "status": "DIFF",
                        "added_files": 1,
                        "removed_files": 1,
                        "changed_files": 0,
                        "renamed_or_moved": 1,
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (diff_dir / "file_diff.json").write_text(
                json.dumps(
                    {
                        "added": [{"path": "upstream_ae9a8ed9/lef/top.lef", "file_type": "lef"}],
                        "removed": [{"path": "asap7_source_package/lef/top.lef", "file_type": "lef"}],
                        "changed": [],
                        "renamed_or_moved": [
                            {
                                "old": "asap7_source_package/lef/top.lef",
                                "new": "upstream_ae9a8ed9/lef/top.lef",
                                "reason": "same basename and content signature",
                            }
                        ],
                        "counts": {"added": 1, "removed": 1, "changed": 0, "renamed_or_moved": 1},
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            from lib_guard.render.version_detail_report import (
                build_version_update_detail_model,
                render_version_update_detail_panel,
            )

            model = build_version_update_detail_model(
                root / "html",
                {"library_id": "ip/asap7", "library_name": "asap7"},
                {
                    "version_id": "20260627_asap7",
                    "current_effective_ref": "20260624_asap7",
                    "diff": {"current_effective_diff_dir": str(diff_dir)},
                },
            )
            html = render_version_update_detail_panel(model)
            rows = {item["path"]: item for item in model["file_changes"]}

            self.assertEqual(rows["upstream_ae9a8ed9/lef/top.lef"]["match_status"], "matched_move")
            self.assertEqual(
                rows["upstream_ae9a8ed9/lef/top.lef"]["base_candidate"],
                "asap7_source_package/lef/top.lef",
            )
            self.assertEqual(
                rows["upstream_ae9a8ed9/lef/top.lef"]["target_candidate"],
                "upstream_ae9a8ed9/lef/top.lef",
            )
            self.assertEqual(rows["asap7_source_package/lef/top.lef"]["match_status"], "matched_move")
            self.assertEqual(
                rows["asap7_source_package/lef/top.lef"]["base_candidate"],
                "asap7_source_package/lef/top.lef",
            )
            self.assertEqual(
                rows["asap7_source_package/lef/top.lef"]["target_candidate"],
                "upstream_ae9a8ed9/lef/top.lef",
            )
            self.assertIn("匹配状态", html)
            self.assertIn("Base 候选", html)
            self.assertIn("Target 文件", html)
            self.assertIn("matched_move", html)
            self.assertIn("asap7_source_package/lef/top.lef", html)
            self.assertIn("upstream_ae9a8ed9/lef/top.lef", html)

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
            self.assertIn("修改文件 7 个，新增 1 个，删除 0 个", model["headline"])
            self.assertIn("2 个需要优先下钻", model["headline"])
            self.assertIn("5 个按 Summary/Metadata-only 处理", model["headline"])

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
                "Base 来源",
                "Base 版本",
                "Target 版本",
                "对比语义",
                "删除语义",
            ]:
                self.assertIn(label, html)
            self.assertNotIn("Markdown export", html)

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
                    "headline": "当前版本相对 current_effective：修改文件 0 个，新增 0 个，删除 0 个；其中 0 个需要优先下钻，0 个按 Summary/Metadata-only 处理。",
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

    def test_version_detail_uses_scan_evidence_for_release_notes_without_raw_rglob(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            raw = root / "raw" / "ucie" / "stable_20250608"
            scan_dir = root / "scan"
            out = root / "html"
            raw.mkdir(parents=True)
            scan_dir.mkdir()
            (scan_dir / "file_inventory.json").write_text(
                json.dumps(
                    {
                        "files": [
                            {
                                "path": "doc/release_note.txt",
                                "file_type": "doc",
                                "role": "release_note",
                                "doc_type": "release_note",
                                "is_key_doc": True,
                            }
                        ],
                        "file_type_counts": {"doc": 1},
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (scan_dir / "parser_manifest.json").write_text(json.dumps({"files": []}), encoding="utf-8")
            (scan_dir / "parser_results.json").write_text("{}", encoding="utf-8")
            summary_dir = scan_dir / "summary"
            summary_dir.mkdir()
            (summary_dir / "release_readiness.json").write_text(
                json.dumps(
                    {
                        "doc_summary": {
                            "release_note_found": True,
                            "files": [
                                {
                                    "path": "doc/release_note.txt",
                                    "role": "release_note",
                                    "doc_type": "release_note",
                                }
                            ],
                        }
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            lib = {"library_id": "ip/ucie", "library_name": "ucie"}
            version = {
                "version_id": "stable_20250608",
                "raw_path": str(raw),
                "previous_effective_version": "stable_20250601",
                "scan": {"scan_dir": str(scan_dir)},
            }

            from lib_guard.render.version_detail_report import render_version_detail_page

            with patch.object(Path, "rglob", side_effect=AssertionError("render must not recursively scan raw")):
                page = Path(render_version_detail_page(out, lib, version))

            html = page.read_text(encoding="utf-8")
            self.assertIn("doc/release_note.txt", html)
            self.assertNotIn(str(raw / "doc" / "release_note.txt"), html)


if __name__ == "__main__":
    unittest.main()
