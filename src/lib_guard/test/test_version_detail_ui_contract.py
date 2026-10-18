from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class VersionDetailUiContractTest(unittest.TestCase):
    def test_conflicting_same_content_change_is_rendered_as_pending_in_file_tree(self) -> None:
        from lib_guard.render.version_file_evidence import _evidence_records, render_version_file_evidence_section

        model = {
            'source_roots': {'current': '/raw/v2', 'base': '/raw/v1'},
            'file_changes': [{
                'path': 'lef/a.lef', 'change': 'unverified', 'display_change': 'UNVERIFIED',
                'file_type': 'lef', 'review_label': '对比结论待复核',
            }],
            'file_diff': {'logical_path_changes': []},
            'scan_evidence': {'inventory': {'files': [
                {'path': 'lef/a.lef', 'abs_path': '/raw/v2/lef/a.lef', 'file_type': 'lef'},
            ]}},
        }

        record = _evidence_records(model)[0]
        self.assertEqual(record['change'], 'unverified')
        html = render_version_file_evidence_section(model)
        self.assertIn("data-tree-status='unmatched_new'", html)
        self.assertIn('本版待核对', html)

    def test_file_tree_exposes_source_paths_without_guessing_missing_roots(self) -> None:
        from lib_guard.render.version_file_evidence import _evidence_records, render_version_file_evidence_section
        model = {
            'source_roots': {'current': '/raw/new', 'base': '/raw/old'},
            'scan_evidence': {'inventory': {'files': [
                {'path': 'wrapper/a.lef', 'abs_path': '/mounted/new/wrapper/a.lef', 'file_type': 'lef'},
            ]}},
            'file_changes': [
                {'path': 'wrapper/a.lef', 'change': 'added', 'file_type': 'lef'},
                {'path': 'old_wrapper/b.lef', 'change': 'removed', 'file_type': 'lef'},
                {'path': 'a.lef', 'change': 'changed', 'file_type': 'lef'},
            ],
            'file_diff': {'logical_path_changes': [{'logical_path': 'a.lef', 'old': 'old_wrapper/a.lef', 'new': 'wrapper/a.lef'}]},
        }
        rows = {row['path']: row for row in _evidence_records(model)}
        self.assertEqual(rows['wrapper/a.lef']['source_path'], '/mounted/new/wrapper/a.lef')
        self.assertEqual(rows['old_wrapper/b.lef']['source_path'], '/raw/old/old_wrapper/b.lef')
        self.assertEqual(rows['wrapper/a.lef']['source_path'], '/mounted/new/wrapper/a.lef')
        html = render_version_file_evidence_section(model)
        self.assertIn('本版源目录', html)
        self.assertIn('基准版源目录', html)
        self.assertIn('原始路径', html)
        self.assertIn('copyText(this.dataset.sourcePath, this)', html)
        self.assertNotIn('file://', html)
        unknown = _evidence_records({'file_changes': [{'path': 'x.lef', 'change': 'removed'}]})
        self.assertEqual(unknown[0]['source_path'], '')

    def test_first_version_matrix_shows_delivery_not_a_fictitious_zero_diff(self) -> None:
        from lib_guard.render.version_review_render import render_ip_user_view
        html = render_ip_user_view({'review_mode': 'first_version', 'view_rows': [{'view_type': 'lef', 'delivery_count': 1, 'evidence_level': '无变化'}]})
        self.assertIn('本次交付', html)
        self.assertIn('扫描证据', html)
        self.assertIn('data-view-type-filter', html)
        self.assertNotIn('data-change-filter', html)
        self.assertNotIn('data-only-changes', html)
        self.assertNotIn('<b>0</b>文件变化', html)
        self.assertNotIn('无变化', html)

    def test_matrix_file_entry_targets_the_corresponding_delivered_view(self) -> None:
        from lib_guard.render.version_review_render import _view_delta_file_evidence
        from lib_guard.render.version_file_evidence import render_version_file_evidence_section
        link = _view_delta_file_evidence({'view_type': 'lef', 'total_evidence_count': 27})
        self.assertIn("data-file-view='physical_abstract'", link)
        self.assertIn('selectFileTreeView(this.dataset.fileView)', link)
        tree = render_version_file_evidence_section({})
        self.assertIn('function selectFileTreeView(view)', tree)
        self.assertIn("filterFileTree('current')", tree)

    def test_library_report_internal_detail_links_are_portable(self) -> None:
        from lib_guard.render.catalog_workspace_report import _library_card, _library_focus_styles, render_library_workspace_page
        self.assertIn('min-height:132px', _library_focus_styles())
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / 'html'
            version = {'version_id': 'v1', 'links': {'version_review_html': str(out / 'libraries/ip_ucie/versions/v1/index.html')}}
            page = Path(render_library_workspace_page(out, {'library_id': 'ip/ucie', 'versions': [version]}, []))
            html = page.read_text()
            self.assertIn("href='versions/v1/index.html'", html)
            self.assertNotIn('file://', html)
            card = _library_card(out, {'library_id': 'ip/ucie', 'versions': [version], 'library_home_html': str(page)}, [])
            self.assertIn("href='libraries/ip_ucie/index.html'", card)
            self.assertNotIn('file://', card)

    def test_relative_output_directory_produces_correct_internal_report_links(self) -> None:
        import json
        import os
        from lib_guard.render.catalog_report import render_catalog_html
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            catalog = root / 'catalog.json'
            catalog.write_text(json.dumps({'libraries': [{'library_id': 'ip/ucie', 'library_name': 'ucie', 'versions': [{'version_id': 'v1'}]}]}))
            out = root / 'html'
            result = render_catalog_html(catalog, Path(os.path.relpath(out, Path.cwd())))
            self.assertEqual(result['status'], 'PASS')
            index = (out / 'index.html').read_text()
            library = (out / 'libraries/ip_ucie/index.html').read_text()
            self.assertIn("href='libraries/ip_ucie/index.html'", index)
            self.assertIn("href='versions/v1/index.html'", library)
            self.assertNotIn('file://', index + library)
            self.assertNotIn("href='#'>发布证据", index)
            self.assertNotIn('setTimeout(filterCatalogBrowser,0)', index)
            self.assertIn("addEventListener('DOMContentLoaded', filterCatalogBrowser)", index)
            self.assertNotIn("+' libraries / '", index)

    def test_static_report_navigation_and_secondary_maintenance_are_visible_but_compact(self) -> None:
        from lib_guard.render import product_theme as ui
        from lib_guard.render.version_detail_report import _render_freshness_panel, _version_update_note_panel, render_version_detail_page

        shell = ui.review_page_shell('库', '目录', '', '', nav="<a href='index.html'>总目录</a>")
        self.assertIn("<nav class='report-nav' aria-label='报告导航'>", shell)
        self.assertIn("<a href='index.html'>总目录</a>", shell)
        self.assertNotIn("class='report-nav'", ui.review_page_shell('库', '目录', '', ''))
        freshness = _render_freshness_panel({})
        self.assertIn("<details", freshness)
        self.assertNotIn(" open", freshness.split('>', 1)[0])
        note = _version_update_note_panel({'update_note': {'summary': '核对引脚', 'risks': ['注意极性'], 'must_check': ['确认端口'], 'updated_by': 'owner'}})
        self.assertIn('<summary>备注来源与更新时间</summary>', note)
        self.assertIn('注意极性', note)
        self.assertIn('确认端口', note)
        self.assertNotIn('机器结论只作为旁证', note)
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / 'html'
            page = Path(render_version_detail_page(out, {'library_id': 'ip/ucie', 'library_name': 'ucie'}, {'version_id': 'v1'}))
            html = page.read_text()
            self.assertIn("href='../../../../index.html'", html)
            self.assertIn("href='../../index.html'", html)
            self.assertEqual((page.parent / '../../../../index.html').resolve(), (out / 'index.html').resolve())
            self.assertIn('.hero h1{font-size:22px', html)

    def test_hot_path_version_detail_disables_catalog_links_until_catalog_render(self) -> None:
        from lib_guard.render.version_detail_report import render_version_detail_page

        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "html"
            page = Path(render_version_detail_page(
                out,
                {"library_id": "ip/ucie", "library_name": "ucie"},
                {"version_id": "v1"},
                catalog_navigation_available=False,
            ))
            html = page.read_text(encoding="utf-8")

        self.assertIn("总目录（刷新目录后可用）", html)
        self.assertIn("库概览（刷新目录后可用）", html)
        self.assertNotIn("href='../../../../index.html'", html)
        self.assertNotIn("href='../../index.html'", html)

    def test_web_console_exposes_parallel_version_actions_and_manual_write_controls(self) -> None:
        template = Path(__file__).resolve().parents[1] / "web" / "templates" / "index.html"
        html = template.read_text(encoding="utf-8")
        javascript = (template.parent.parent / "static" / "app.js").read_text(encoding="utf-8")

        self.assertIn('id="open-version-detail-button"', html)
        for workspace in ('version-workspace', 'action-workspace', 'release-workspace'):
            self.assertIn(f'data-stage-target="{workspace}"', html)
        for control in ('scan-action-button', 'compare-action-button', 'file-diff', 'release-action-button'):
            self.assertIn(control, html)
        self.assertIn('data-workflow-action="next-apply"', html)
        self.assertIn("审查记录", html)
        self.assertIn("openVersionDetail", javascript)
        self.assertNotIn("runReviewSequence", javascript)
        self.assertNotIn("data-sequence-action", html + javascript)
        self.assertNotIn("const scan = await runAction('scan')", javascript)
        self.assertNotIn("const compare = await runAction('compare', { scan_if_missing: true, rescan: false })", javascript)

    def test_review_report_has_fixed_sections_and_reconciled_counts(self) -> None:
        from lib_guard.render.version_review_model import build_ip_user_view_model, build_review_report

        source = {
            "status": "CHANGED",
            "base_ref": "previous_effective",
            "base_version": "v1_full",
            "target_version": "v2_full",
            "base_source": "previous_effective",
            "base_trust_status": "PASS",
            "base_trust_note": "基准已确认",
            "comparison_semantics": "full",
            "delete_semantics": "real_delete",
            "package_type": "FULL_PACKAGE",
            "file_changes": [
                {"change": "ADDED", "file_type": "lef", "path": "LEF/a.lef", "review_lane": "P0"},
                {"change": "CHANGED", "file_type": "liberty", "path": "LIB/a.lib", "review_lane": "SUMMARY_ONLY", "evidence_mode": "summary-only"},
                {"change": "REMOVED", "file_type": "verilog", "path": "RTL/old.v", "review_lane": "P1"},
            ],
            "added_files": 1,
            "removed_files": 1,
            "changed_files": 1,
            "lane_counts": {"recommended_file_diff": 2, "summary_only": 1, "metadata_only": 0},
            "scan_evidence": {
                "file_total": 2,
                "unknown_total": 1,
                "inventory": {"files": [{"path": "LEF/a.lef", "file_type": "lef"}, {"path": "LIB/a.lib", "file_type": "liberty"}, {"path": "misc.bin", "file_type": "unknown"}]},
                "context": {"scan_id": "scan-v2", "scan_status": "SCAN_PASS", "scan_dir": "/scan/v2"},
            },
            "comparison_context": {"diff_status": "CHANGED", "diff_dir": "/diff/v1-v2"},
            "diff_summary": {"status": "DIFF", "added_files": 1, "removed_files": 1, "changed_files": 1},
            "diff_issues": {"issues": []},
            "path_restructure": {"suspected": False},
            "release_notes": [],
            "recommended_actions": ["确认 LEF 变化"],
            "evidence_state": {"status": "PASS", "scan": {"status": "PASS"}, "diff": {"status": "PASS"}},
        }

        ip_view = build_ip_user_view_model(source)
        report = build_review_report(source, ip_view)
        self.assertEqual(
            set(report),
            {
                "schema_version", "base_analysis", "delivery_analysis", "view_delta_analysis",
                "focus_file_analysis", "unknown_analysis", "evidence_assessment",
                "open_questions", "recommended_actions",
            },
        )
        self.assertEqual(
            report["view_delta_analysis"]["totals"],
            {"added": 1, "removed": 1, "changed": 1, "unmatched_new": 0, "unmatched_base": 0},
        )
        self.assertEqual(report["view_delta_analysis"]["evidence_reconciliation"]["status"], "RECONCILED")
        self.assertTrue(report["view_delta_analysis"]["evidence_reconciliation"]["checks"]["file_diff_items_match_view_matrix"])
        self.assertTrue(report["view_delta_analysis"]["evidence_reconciliation"]["checks"]["focus_files_are_file_diff_subset"])
        self.assertEqual(report["focus_file_analysis"]["count"], 2)
        self.assertEqual(report["unknown_analysis"]["count"], 1)
        self.assertEqual(report["evidence_assessment"]["scan_id"], "scan-v2")
        self.assertTrue(report["open_questions"])

    def test_review_report_marks_declared_file_diff_mismatch(self) -> None:
        from lib_guard.render.version_review_model import build_ip_user_view_model, build_review_report

        source = {
            "status": "CHANGED",
            "base_ref": "previous_effective",
            "base_version": "v1_full",
            "base_trust_status": "PASS",
            "comparison_semantics": "full",
            "delete_semantics": "real_delete",
            "package_type": "FULL_PACKAGE",
            "file_changes": [{"change": "CHANGED", "file_type": "lef", "path": "LEF/a.lef", "review_lane": "P0"}],
            "file_diff": {"counts": {"added": 2, "removed": 0, "changed": 0}},
            "scan_evidence": {"counts": {"lef": 1}, "context": {"scan_status": "SCAN_PASS"}},
            "comparison_context": {"diff_status": "CHANGED"},
            "diff_summary": {"status": "DIFF"},
        }

        report = build_review_report(source, build_ip_user_view_model(source))
        reconciliation = report["view_delta_analysis"]["evidence_reconciliation"]
        self.assertEqual(reconciliation["status"], "MISMATCH")
        self.assertFalse(reconciliation["checks"]["declared_file_diff_matches_items"])

    def test_review_report_preserves_first_version_and_missing_evidence_states(self) -> None:
        from lib_guard.render.version_review_model import build_ip_user_view_model, build_review_report

        source = {
            "status": "DIFF_NOT_RUN",
            "review_mode": "first_version",
            "base_ref": "NEEDS_BASE_CONFIRM",
            "base_version": "",
            "base_trust_status": "INFO",
            "package_type": "UNKNOWN_PACKAGE",
            "file_changes": [],
            "lane_counts": {},
            "scan_evidence": {"file_total": 1, "unknown_total": 0, "inventory": {"files": [{"path": "README.md", "file_type": "doc"}]}, "context": {}},
            "comparison_context": {"diff_status": "DIFF_NOT_RUN"},
            "diff_summary": {},
            "diff_issues": {},
            "release_notes": [],
            "recommended_actions": [],
        }
        report = build_review_report(source, build_ip_user_view_model(source))
        self.assertEqual(report["base_analysis"]["status"], "INFO")
        self.assertEqual(report["view_delta_analysis"]["status"], "NOT_AVAILABLE")
        self.assertEqual(report["evidence_assessment"]["status"], "INCOMPLETE")
        self.assertTrue(report["open_questions"])

    def test_review_report_semantic_scenarios_a_to_h(self) -> None:
        from lib_guard.render.version_review_model import build_ip_user_view_model, build_review_report

        def source(**overrides):
            value = {
                "status": "CHANGED",
                "review_mode": "baseline",
                "base_ref": "previous_effective",
                "base_version": "full_v1",
                "base_trust_status": "PASS",
                "comparison_semantics": "full",
                "delete_semantics": "real_delete",
                "package_type": "FULL_PACKAGE",
                "file_changes": [{"change": "CHANGED", "file_type": "lef", "path": "LEF/a.lef", "review_lane": "P0"}],
                "added_files": 0,
                "removed_files": 0,
                "changed_files": 1,
                "lane_counts": {"recommended_file_diff": 1},
                "scan_evidence": {"file_total": 1, "unknown_total": 0, "inventory": {"files": [{"path": "LEF/a.lef", "file_type": "lef"}]}, "context": {"scan_id": "scan-1", "scan_status": "SCAN_PASS"}},
                "comparison_context": {"diff_status": "CHANGED"},
                "diff_summary": {"status": "DIFF", "changed_files": 1},
                "diff_issues": {"issues": []},
                "release_notes": [{"path": "RELEASE.md"}],
                "recommended_actions": [],
            }
            value.update(overrides)
            return value

        cases = [
            ("A 首版", source(review_mode="first_version", status="FIRST_VERSION_REVIEW", base_ref="", base_version=""), "NOT_AVAILABLE"),
            ("B 正常 FULL", source(), "RECONCILED"),
            ("C 缺少必需 View", source(delivery_completeness={"status": "MISSING", "missing": ["lef"]}), "RECONCILED"),
            ("D 缺少 diff", source(status="DIFF_NOT_RUN", comparison_context={"diff_status": "DIFF_NOT_RUN"}, diff_summary={}), "NOT_AVAILABLE"),
            ("E 相邻回退", source(base_ref="adjacent_fallback", base_trust_status="WARNING"), "RECONCILED"),
            ("F UNKNOWN 包", source(package_type="UNKNOWN_PACKAGE", scan_evidence={"file_total": 1, "unknown_total": 1, "inventory": {"files": [{"path": "x.bin", "file_type": "unknown"}]}, "context": {"scan_id": "scan-1", "scan_status": "SCAN_PASS"}}), "RECONCILED"),
            ("G FULL + FIX/DOC", source(package_type="FULL_PACKAGE", package_composition=["FULL_PACKAGE", "PARTIAL_UPDATE", "DOC_UPDATE"]), "RECONCILED"),
            ("H 证据过期", source(scan_evidence={"file_total": 1, "unknown_total": 0, "inventory": {"files": [{"path": "LEF/a.lef", "file_type": "lef"}]}, "context": {"scan_id": "scan-old", "scan_status": "STALE"}}), "RECONCILED"),
        ]
        for name, model, expected_delta in cases:
            with self.subTest(scenario=name):
                report = build_review_report(model, build_ip_user_view_model(model))
                self.assertIn("schema_version", report)
                self.assertIn(report["view_delta_analysis"]["status"], {expected_delta, "MISMATCH"})
                self.assertIn("evidence_assessment", report)

    def test_version_detail_has_stable_semantic_sections(self) -> None:
        from lib_guard.render.version_detail_report import render_version_detail_page

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            page = Path(render_version_detail_page(root / "html", {"library_id": "ip/ucie", "library_name": "ucie"}, {"version_id": "v1"}))
            html = page.read_text(encoding="utf-8")
            for section in (
                "decision-summary", "comparison-context", "impact-summary", "view-delta",
                "focus-files", "file-structure", "review-report", "evidence-status",
            ):
                self.assertIn(f'data-section="{section}"', html)
            self.assertIn("data-next-action='true'", html)
            self.assertIn("需要确认", html)
            self.assertNotIn("下一步", html)
            self.assertIn("review-report", html)
            self.assertIn("<details", html)

    def test_static_review_packet_is_compact_and_notes_stay_in_report(self) -> None:
        from lib_guard.render.version_detail_report import render_version_detail_page

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            page = Path(
                render_version_detail_page(
                    root / "html",
                    {"library_id": "ip/ucie", "library_name": "ucie"},
                    {
                        "version_id": "v2",
                        "review_gate": {
                            "packet_id": "rp_abc123",
                            "status": "BLOCKED",
                            "blocking_open": 1,
                            "attention_count": 0,
                            "items": [
                                {
                                    "department": "Physical",
                                    "decision": "BLOCK",
                                    "question": "请确认 lef 视图变化满足当前使用场景。",
                                    "note": "不要把这段长备注直接铺到版本详情主页面。",
                                }
                            ],
                            "review_report": str(root / "reviews" / "review_report.md"),
                        },
                        "review_packet": {
                            "packet_id": "rp_abc123",
                            "review_report": str(root / "reviews" / "review_report.md"),
                        },
                    },
                )
            )
            html = page.read_text(encoding="utf-8")

        self.assertIn('data-section="review-gate"', html)
        self.assertIn("部门审查", html)
        self.assertIn("已附备注；详见完整审查报告", html)
        self.assertNotIn("不要把这段长备注直接铺到版本详情主页面", html)

    def test_ip_decision_matrix_uses_evidence_state_instead_of_page_defaults(self) -> None:
        from lib_guard.render.version_review_model import build_ip_user_view_model

        scenarios = [
            {
                "name": "full_same",
                "model": {
                    "status": "SAME",
                    "base_ref": "previous_effective",
                    "base_version": "v1_full",
                    "base_trust_status": "PASS",
                    "comparison_semantics": "full",
                    "delete_semantics": "real_delete",
                    "file_changes": [],
                    "lane_counts": {},
                    "scan_evidence": {"counts": {"lef": 2}},
                },
                "decision": "READY",
                "label": "可接入",
            },
            {
                "name": "full_real_delete",
                "model": {
                    "status": "CHANGED",
                    "base_ref": "previous_effective",
                    "base_version": "v1_full",
                    "base_trust_status": "PASS",
                    "comparison_semantics": "full",
                    "delete_semantics": "real_delete",
                    "file_changes": [{"change": "REMOVED", "file_type": "lef", "path": "LEF/a.lef"}],
                    "lane_counts": {"recommended_file_diff": 1},
                    "scan_evidence": {"counts": {"lef": 1}},
                },
                "decision": "USAGE_REVIEW_REQUIRED",
                "label": "需审查后使用",
            },
            {
                "name": "missing_base",
                "model": {
                    "status": "NEEDS_BASE_CONFIRM",
                    "base_ref": "NEEDS_BASE_CONFIRM",
                    "base_version": None,
                    "base_trust_status": "BLOCKED",
                    "comparison_semantics": "full",
                    "delete_semantics": "real_delete",
                    "file_changes": [],
                    "lane_counts": {},
                    "scan_evidence": {"counts": {"lef": 1}},
                },
                "decision": "BLOCKED",
                "label": "暂不可判断",
            },
        ]

        for scenario in scenarios:
            with self.subTest(scenario=scenario["name"]):
                result = build_ip_user_view_model(scenario["model"])
                self.assertEqual(result["decision"]["status"], scenario["decision"])
                self.assertEqual(result["decision"]["label"], scenario["label"])

    def test_incremental_missing_files_are_not_real_deletes(self) -> None:
        from lib_guard.render.version_review_model import build_ip_change_projection

        changes = [
            {"change": "ADDED", "file_type": "doc", "path": "doc/release_note.txt"},
            {"change": "CHANGED", "file_type": "doc", "path": "SOURCE.md"},
            {"change": "REMOVED", "file_type": "lef", "path": "LEF/a.lef"},
        ]

        result = build_ip_change_projection(
            {"comparison_semantics": "incremental", "delete_semantics": "out_of_scope_missing"},
            changes,
        )

        self.assertEqual(
            result["visible_counts"],
            {"added": 1, "removed": 0, "changed": 1, "unmatched_new": 0, "unmatched_base": 0},
        )
        self.assertEqual(result["baseline_only_count"], 1)
        self.assertEqual(result["baseline_only_changes"][0]["path"], "LEF/a.lef")
        self.assertNotIn("LEF/a.lef", [item["path"] for item in result["visible_changes"]])

    def test_full_package_missing_files_remain_real_deletes(self) -> None:
        from lib_guard.render.version_review_model import build_ip_change_projection

        changes = [{"change": "REMOVED", "file_type": "lef", "path": "LEF/a.lef"}]

        result = build_ip_change_projection(
            {"comparison_semantics": "full", "delete_semantics": "real_delete"},
            changes,
        )

        self.assertEqual(
            result["visible_counts"],
            {"added": 0, "removed": 1, "changed": 0, "unmatched_new": 0, "unmatched_base": 0},
        )
        self.assertEqual(result["baseline_only_count"], 0)
        self.assertEqual(result["visible_changes"][0]["path"], "LEF/a.lef")

    def test_incremental_view_rows_keep_baseline_only_files_out_of_removed_count(self) -> None:
        from lib_guard.render.version_review_model import build_ip_user_view_model

        model = build_ip_user_view_model(
            {
                "status": "CHANGED",
                "base_ref": "previous_effective",
                "base_version": "v1_full",
                "comparison_semantics": "incremental",
                "delete_semantics": "out_of_scope_missing",
                "added_files": 1,
                "removed_files": 1,
                "changed_files": 1,
                "lane_counts": {},
                "file_changes": [
                    {"change": "ADDED", "file_type": "doc", "path": "doc/release_note.txt"},
                    {"change": "CHANGED", "file_type": "doc", "path": "SOURCE.md"},
                    {"change": "REMOVED", "file_type": "lef", "path": "LEF/a.lef"},
                ],
                "scan_evidence": {
                    "counts": {"doc": 2},
                    "inventory": {"files": [{"path": "SOURCE.md", "file_type": "doc"}]},
                },
            }
        )

        rows = {row["view_type"]: row for row in model["view_rows"]}
        self.assertEqual(model["comparison"]["visible_counts"]["removed"], 0)
        self.assertEqual(rows["physical_abstract"]["removed"], 0)
        self.assertEqual(rows["physical_abstract"]["baseline_only_count"], 1)
        self.assertEqual(rows["physical_abstract"]["status_label"], "本包未携带")

    def test_view_rows_separate_delivery_from_candidate_effective_inventory(self) -> None:
        from lib_guard.render.version_review_model import build_ip_user_view_model

        model = build_ip_user_view_model(
            {
                "status": "SAME",
                "base_ref": "previous_effective",
                "base_version": "v1_full",
                "comparison_semantics": "incremental",
                "delete_semantics": "out_of_scope_missing",
                "lane_counts": {},
                "file_changes": [],
                "scan_evidence": {"counts": {"doc": 1}, "inventory": {"files": []}},
                "candidate_effective_inventory": {
                    "file_count": 4,
                    "file_type_counts": {"lef": 2, "verilog": 1, "doc": 1},
                    "manifest": "/tmp/effective_manifest.json",
                },
            }
        )

        rows = {row["view_type"]: row for row in model["view_rows"]}
        self.assertEqual(rows["doc_evidence"]["delivery_count"], 1)
        self.assertEqual(rows["doc_evidence"]["candidate_effective_count"], 1)
        self.assertEqual(rows["physical_abstract"]["delivery_count"], 0)
        self.assertEqual(rows["physical_abstract"]["candidate_effective_count"], 2)
        self.assertEqual(rows["rtl_model"]["candidate_effective_count"], 1)

    def test_view_delta_is_a_structured_comparison_table(self) -> None:
        from lib_guard.render.version_review_model import build_version_review_model
        from lib_guard.render.version_review_render import render_ip_user_view

        review_model = build_version_review_model(
            {
                "status": "CHANGED",
                "base_ref": "previous_effective",
                "base_version": "v1_full",
                "base_trust_status": "PASS",
                "comparison_semantics": "full",
                "delete_semantics": "real_delete",
                "file_changes": [
                    {"path": "LEF/top.lef", "file_type": "lef", "change": "changed", "review_lane": "P0"},
                    {"path": "rtl/top.v", "file_type": "verilog", "change": "added", "review_lane": "Summary-only"},
                ],
                "scan_evidence": {
                    "counts": {"lef": 2, "verilog": 1},
                    "inventory": {"files": [{"path": "LEF/top.lef", "file_type": "lef"}]},
                },
            }
        )

        html = render_ip_user_view(review_model["ip_user_view"])

        self.assertIn("view-delta-scroll", html)
        self.assertIn("view-delta-table", html)
        self.assertIn("data-view-delta-filter", html)
        self.assertIn("data-view-search", html)
        self.assertIn("data-view-type-filter", html)
        self.assertIn("data-change-filter", html)
        self.assertIn("data-view-delta-count", html)
        self.assertIn("仅显示有变化", html)
        for label in ["新增", "删除", "修改"]:
            self.assertIn(label, html)
        for header in ["交付 / 变化", "证据 / 状态", "文件入口"]:
            self.assertIn(f"<th>{header}</th>", html)
        self.assertIn("delta-compact-count added", html)
        self.assertIn("delta-compact-count changed", html)
        self.assertIn("data-change-kinds='added'", html)
        self.assertIn("data-change-kinds='changed'", html)
        self.assertIn("data-view-label='物理抽象（LEF）'", html)
        self.assertNotIn("<th>当前文件</th>", html)
        self.assertIn("查看文件结构", html)
        self.assertNotIn("路径变化且内容相同", html)

    def test_view_delta_shows_content_preserving_path_change_as_its_own_category(self) -> None:
        from lib_guard.render.version_review_model import build_ip_user_view_model, build_review_report
        from lib_guard.render.version_review_render import render_ip_user_view

        source = {
            "status": "SAME",
            "base_ref": "previous_effective",
            "base_version": "v1_full",
            "base_trust_status": "PASS",
            "comparison_semantics": "full",
            "delete_semantics": "real_delete",
            "file_changes": [],
            "path_changes_same_content": [
                {
                    "file_type": "verilog",
                    "old": "RTL/top.v",
                    "new": "RTL/top_renamed.v",
                    "reason": "unique_hash_match",
                }
            ],
            "scan_evidence": {
                "counts": {"verilog": 1},
                "inventory": {"files": [{"path": "RTL/top_renamed.v", "file_type": "verilog"}]},
            },
            "file_diff": {"counts": {"added": 0, "removed": 0, "changed": 0, "renamed_or_moved": 1}},
        }
        model = build_ip_user_view_model(source)

        row = next(item for item in model["view_rows"] if item["view_type"] == "rtl_model")
        self.assertEqual(row["added"], 0)
        self.assertEqual(row["removed"], 0)
        self.assertEqual(row["changed"], 0)
        self.assertEqual(row["path_changed_same_content"], 1)
        self.assertEqual(row["status_label"], "路径变化，内容相同")

        report = build_review_report(source, model)
        self.assertEqual(
            report["view_delta_analysis"]["totals"],
            {
                "added": 0,
                "removed": 0,
                "changed": 0,
                "unmatched_new": 0,
                "unmatched_base": 0,
                "path_changed_same_content": 1,
            },
        )
        self.assertTrue(
            report["view_delta_analysis"]["evidence_reconciliation"]["checks"][
                "path_changes_match_view_matrix"
            ]
        )

        html = render_ip_user_view(model)
        self.assertIn("路径变化且内容相同", html)
        self.assertIn("delta-compact-count path-changed", html)
        self.assertIn("RTL/top.v", html)
        self.assertIn("RTL/top_renamed.v", html)

    def test_view_delta_evidence_links_are_relative_to_the_detail_page(self) -> None:
        from lib_guard.render.version_review_render import render_ip_user_view

        html = render_ip_user_view(
            {
                "view_rows": [
                    {
                        "view_type": "physical_abstract",
                        "view": "LEF / Physical abstract",
                        "usage_area": "Physical",
                        "current_count": 1,
                        "delivery_count": 1,
                        "added": 1,
                        "removed": 0,
                        "changed": 0,
                        "delta_total": 1,
                        "evidence_level": "人工审查",
                        "status": "INFO",
                        "status_label": "有更新",
                        "current_examples": ["LEF/top.lef"],
                        "full_evidence_href": "/workspace/diff/demo/v1/file_diff.json",
                    }
                ]
            },
            href_base=Path("/workspace/catalog/html/libraries/demo/versions/v1"),
        )

        self.assertNotIn("href='/workspace/diff/", html)
        self.assertIn("href='../../../../../../diff/demo/v1/file_diff.json'", html)

    def test_version_detail_uses_primary_table_and_collapsed_evidence_column(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            from lib_guard.render.version_detail_report import render_version_detail_page

            page = Path(
                render_version_detail_page(
                    root / "html",
                    {"library_id": "ip/demo", "display_name": "demo"},
                    {
                        "version_id": "v1",
                        "raw_path": str(root / "raw" / "v1"),
                        "review_gate": {"status": "REVIEW_REQUIRED", "attention_items": []},
                    },
                )
            )
            html = page.read_text(encoding="utf-8")

        self.assertIn("review-layout", html)
        self.assertIn("review-top-layout", html)
        self.assertIn("review-top-summary", html)
        self.assertIn("review-top-matrix", html)
        self.assertIn("review-primary-column", html)
        self.assertIn("review-secondary-column", html)
        self.assertIn("review-summary-strip", html)
        self.assertIn("--review-ink", html)
        self.assertIn("view-delta-toolbar", html)
        self.assertIn("delta-legend", html)
        self.assertIn("视图变化矩阵", html)
        self.assertLess(html.index("<section class='review-top-matrix'>"), html.index("<section class='review-top-summary'>"))
        self.assertIn("正式放行管理", html)
        self.assertIn("原始证据", html)
        self.assertIn("<table class='view-delta-table'>", html)
        self.assertNotIn("<details class='panel collapsible' open>", html)

    def test_review_report_focus_files_use_bounded_scroll_container(self) -> None:
        from lib_guard.render.version_review_render import render_review_report

        report = {
            "base_analysis": {},
            "delivery_analysis": {},
            "view_delta_analysis": {"rows": [], "totals": {}, "evidence_reconciliation": {}},
            "focus_file_analysis": {
                "count": 200,
                "shown_count": 120,
                "items": [{"review_lane": "P0", "change": "ADDED", "path": "LEF/macro.lef", "evidence_mode": "summary"}],
            },
            "unknown_analysis": {},
            "evidence_assessment": {},
            "open_questions": [],
            "recommended_actions": [],
        }

        html = render_review_report(report)
        self.assertIn("data-focus-scroll='true'", html)
        self.assertNotIn("数量较多时在列表内滚动", html)
        self.assertIn(".report-focus-scroll{max-height:360px;overflow:auto", html)
        self.assertIn(".report-focus-scroll th{position:sticky", html)

    def test_lightweight_evidence_does_not_force_usage_review(self) -> None:
        from lib_guard.render.version_review_model import build_ip_user_view_model

        model = build_ip_user_view_model(
            {
                "status": "SAME",
                "base_ref": "previous_effective",
                "base_version": "v1_full",
                "comparison_semantics": "full",
                "delete_semantics": "real_delete",
                "lane_counts": {"summary_only": 20, "metadata_only": 5},
                "file_changes": [],
                "scan_evidence": {"counts": {"liberty": 20, "gds": 5}},
            }
        )

        self.assertEqual(model["schema_version"], "ip_user_view.v2")
        self.assertEqual(model["decision"]["status"], "READY")
        self.assertIn("证据等级", model["non_blocker_note"])

    def test_ip_view_projects_delivery_completeness_without_inventing_missing_views(self) -> None:
        from lib_guard.render.version_review_model import build_ip_user_view_model

        model = build_ip_user_view_model(
            {
                "status": "CHANGED",
                "base_ref": "previous_effective",
                "base_version": "v1_full",
                "base_trust_status": "PASS",
                "file_changes": [],
                "scan_evidence": {
                    "release_readiness": {
                        "bundle_status": "PASS",
                        "release_level_candidate": "L1",
                        "components": [
                            {
                                "required_views": ["verilog", "lef"],
                                "required_view_results": {
                                    "verilog": {"found": True, "status": "PASS"},
                                    "lef": {"found": False, "status": "MISSING"},
                                },
                                "optional_views": ["sdc"],
                                "optional_view_results": {"sdc": {"found": True, "status": "PASS"}},
                            }
                        ],
                    }
                },
            }
        )

        completeness = model["delivery_completeness"]
        self.assertEqual(completeness["status"], "MISSING")
        self.assertEqual(completeness["required_total"], 2)
        self.assertEqual(completeness["required_present"], 1)
        self.assertEqual(completeness["optional_present"], 1)
        self.assertTrue(any("LEF" in item for item in completeness["missing"]))

    def test_missing_required_view_blocks_ip_user_decision(self) -> None:
        from lib_guard.render.version_review_model import build_ip_user_view_model

        model = build_ip_user_view_model(
            {
                "status": "CHANGED",
                "base_ref": "previous_effective",
                "base_version": "v1_full",
                "base_trust_status": "PASS",
                "file_changes": [],
                "scan_evidence": {
                    "release_readiness": {
                        "bundle_status": "BLOCK",
                        "components": [
                            {
                                "required_views": ["verilog"],
                                "required_view_results": {
                                    "verilog": {"found": False, "status": "MISSING"}
                                },
                            }
                        ],
                    }
                },
            }
        )

        self.assertEqual(model["delivery_completeness"]["status"], "MISSING")
        self.assertEqual(model["decision"]["status"], "BLOCKED")
        self.assertEqual(model["decision"]["label"], "不可接入")
        self.assertIn("RTL 模型", model["decision"]["reason"])
        self.assertEqual(model["decision"]["next_action"]["kind"], "complete_required_view")
        self.assertIn("确认必需视图", model["decision"]["next_action"]["label"])
        self.assertIn("补齐或确认缺失的必需视图", model["next_action"]["detail"])
        self.assertEqual(model["pending_fact_items"][0]["kind"], "REQUIRED_VIEW_MISSING")

    def test_ip_view_keeps_usage_in_matrix_without_duplicate_impact_cards(self) -> None:
        from lib_guard.render.version_review_render import render_ip_user_view

        html = render_ip_user_view(
            {
                "view_rows": [
                    {
                        "view": "Liberty / 时序",
                        "view_type": "timing_lib",
                        "usage_area": "时序分析 / STA",
                        "delta_total": 3,
                        "delivery_count": 3,
                        "added": 2,
                        "removed": 0,
                        "changed": 1,
                        "evidence_level": "摘要级证据（Summary-only）",
                        "evidence_counts": {"Summary-only": 3},
                    },
                    {
                        "view": "LEF / 物理抽象",
                        "view_type": "physical_abstract",
                        "usage_area": "物理实现 / PD",
                        "delta_total": 1,
                        "delivery_count": 1,
                        "added": 0,
                        "removed": 0,
                        "changed": 1,
                        "evidence_level": "重点审查",
                    },
                ],
                "usage_impact": {"summary": "影响场景：时序分析 / STA、物理实现 / PD。"},
            }
        )

        self.assertNotIn("impact-card", html)
        self.assertIn("时序库（Liberty）", html)
        self.assertIn("时序分析（STA）", html)
        self.assertIn("物理抽象（LEF）", html)
        self.assertIn("物理实现（PD）", html)
        self.assertIn("摘要检查", html)
        self.assertIn("· 3", html)
        self.assertNotIn("摘要检查 3", html)
        self.assertNotIn("摘要级证据（Summary-only）", html)
        self.assertNotIn("关联使用场景", html)

    def test_view_delta_shows_scroll_hint_when_many_views_are_present(self) -> None:
        from lib_guard.render.version_review_render import render_ip_user_view

        html = render_ip_user_view(
            {
                "view_rows": [
                    {"view": label, "view_type": str(index), "delivery_count": 1, "delta_total": 1, "added": 1}
                    for index, label in enumerate(("LEF", "Liberty", "RTL", "GDS"))
                ]
            }
        )

        self.assertIn("view-delta-scroll-note", html)
        self.assertIn("共 4 个视图", html)

    def test_page_prioritizes_decision_summary_and_lineage(self) -> None:
        html = self._render_doc_update_page()

        self.assertIn("版本摘要", html)
        self.assertIn("summary-window", html)
        self.assertIn(">主要变化<", html)
        self.assertIn("版本关系", html)
        self.assertNotIn("证据分层</b>", html)

    def test_change_status_is_separate_from_usage_decision(self) -> None:
        from lib_guard.render.version_review_model import build_ip_user_view_model

        model = build_ip_user_view_model(
            {
                "status": "CHANGED",
                "base_ref": "previous_effective",
                "base_version": "v1_full",
                "base_source": "previous_effective_version",
                "base_trust_status": "PASS",
                "comparison_semantics": "full",
                "delete_semantics": "real_delete",
                "lane_counts": {"summary_only": 1},
                "file_changes": [
                    {
                        "change": "CHANGED",
                        "file_type": "liberty",
                        "path": "LIB/slow.lib",
                        "review_lane": "Summary-only",
                    }
                ],
                "scan_evidence": {"counts": {"liberty": 1}},
            }
        )

        self.assertEqual(model["change_summary"]["status"], "CHANGED")
        self.assertEqual(model["change_summary"]["counts"]["changed"], 1)
        self.assertEqual(model["decision"]["status"], "READY")
        self.assertEqual(model["comparison"]["base_source_label"], "上一有效版")
        self.assertIn("时序", model["usage_impact"]["summary"])
        self.assertEqual(model["provenance"]["base"]["version"], "v1_full")

    def test_version_detail_includes_compact_file_structure_section(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            stale_evidence_page = root / "html" / "libraries" / "ip_demo" / "versions" / "v1" / "file-evidence.html"
            stale_evidence_page.parent.mkdir(parents=True)
            stale_evidence_page.write_text("old standalone page", encoding="utf-8")
            from lib_guard.render.version_detail_report import render_version_detail_page

            page = Path(
                render_version_detail_page(
                    root / "html",
                    {"library_id": "ip/demo", "display_name": "demo"},
                    {
                        "version_id": "v1",
                        "raw_path": str(root / "raw" / "v1"),
                        "review_gate": {},
                    },
                )
            )
            detail_html = page.read_text(encoding="utf-8")
            self.assertFalse(stale_evidence_page.exists())
            self.assertIn("文件结构", detail_html)
            self.assertNotIn("文件证据清单", detail_html)
            self.assertIn("file-tree-scroll", detail_html)
            self.assertIn("当前没有可展示的文件结构", detail_html)
            self.assertIn("默认显示变化文件", detail_html)
            self.assertIn("#file-structure", detail_html)

    def test_file_evidence_section_exposes_a_status_annotated_tree(self) -> None:
        from lib_guard.render.version_file_evidence import render_version_file_evidence_section

        html = render_version_file_evidence_section(
            {
                "base_version": "v1",
                "file_changes": [
                    {"change": "added", "file_type": "lef", "path": "LEF/macros/new.lef", "match_status": "true_added"},
                    {"change": "changed", "file_type": "liberty", "path": "LIB/slow.lib"},
                    {"change": "removed", "file_type": "gds", "path": "GDS/old.gds", "match_status": "true_removed"},
                ],
                "scan_evidence": {
                    "inventory": {
                        "files": [
                            {"path": "LEF/macros/new.lef", "file_type": "lef"},
                            {"path": "RTL/top.sv", "file_type": "systemverilog"},
                        ]
                    }
                },
            }
        )

        self.assertIn("文件结构", html)
        self.assertIn("class='file-tree'", html)
        self.assertIn("全部展开", html)
        self.assertIn("全部收起", html)
        self.assertIn("变化文件", html)
        self.assertIn("当前交付", html)
        self.assertIn("全部证据", html)
        self.assertIn("data-tree-view-filter", html)
        self.assertIn("data-tree-area-filter", html)
        self.assertIn("data-tree-change-filter", html)
        self.assertIn("视图类型", html)
        self.assertIn("使用场景", html)
        self.assertIn("变化类型", html)
        self.assertIn("新增", html)
        self.assertIn("删除", html)
        self.assertIn("修改", html)
        self.assertIn("data-tree-reset", html)
        self.assertIn("data-tree-filter='changes'", html)
        self.assertIn("data-tree-view-type='physical_abstract'", html)
        self.assertIn("data-tree-area='物理实现（PD）'", html)
        self.assertIn("data-tree-status='added'", html)
        self.assertIn("data-tree-status='removed'", html)
        self.assertIn("data-tree-status='changed'", html)
        self.assertIn("data-tree-status='current'", html)
        self.assertIn("LEF/macros/new.lef", html)
        self.assertIn("GDS/old.gds", html)
        self.assertIn("RTL/top.sv", html)

    def test_first_version_file_tree_defaults_to_current_delivery(self) -> None:
        from lib_guard.render.version_file_evidence import render_version_file_evidence_section

        html = render_version_file_evidence_section(
            {
                "review_mode": "first_version",
                "scan_evidence": {
                    "file_total": 1,
                    "inventory": {"files": [{"path": "LEF/top.lef", "file_type": "lef"}]},
                },
                "file_changes": [],
            }
        )

        self.assertIn("默认显示当前交付", html)
        self.assertIn("data-tree-filter='current'", html)
        self.assertIn("tree-filter-chip active' data-tree-filter='current'", html)

    def test_file_tree_keeps_deleted_paths_and_has_bounded_scroll(self) -> None:
        from lib_guard.render.version_file_evidence import render_version_file_evidence_section

        html = render_version_file_evidence_section(
            {
                "file_changes": [{"change": "removed", "file_type": "lef", "path": "old/only.lef"}],
                "scan_evidence": {"inventory": {"files": []}},
            }
        )

        self.assertIn("old/only.lef", html)
        self.assertIn("file-tree-scroll", html)
        self.assertIn("overflow:auto", html)

    def test_file_tree_explains_delivery_and_evidence_counts(self) -> None:
        from lib_guard.render.version_file_evidence import render_version_file_evidence_section

        html = render_version_file_evidence_section(
            {
                "file_changes": [{"change": "removed", "file_type": "lef", "path": "old/only.lef"}],
                "scan_evidence": {
                    "file_total": 2,
                    "inventory": {
                        "files": [
                            {"path": "LEF/a.lef", "file_type": "lef"},
                            {"path": "RTL/a.v", "file_type": "verilog"},
                        ]
                    },
                },
            }
        )

        self.assertIn("当前交付 <b>2</b>", html)
        self.assertIn("变化文件 <b>1</b>", html)
        self.assertIn("全部证据 <b>3</b>", html)

    def test_missing_diff_is_blocked_instead_of_presented_as_normal_review(self) -> None:
        from lib_guard.render.version_review_model import build_ip_user_view_model

        model = build_ip_user_view_model(
            {
                "status": "DIFF_NOT_RUN",
                "base_ref": "previous_effective",
                "base_version": "v1_full",
                "comparison_semantics": "full",
                "delete_semantics": "real_delete",
                "lane_counts": {},
                "file_changes": [],
                "scan_evidence": {"counts": {"lef": 1}},
            }
        )

        self.assertEqual(model["decision"]["status"], "BLOCKED")
        self.assertEqual(model["decision"]["label"], "暂不可判断")
        self.assertEqual(model["next_action"]["kind"], "generate_diff")
        self.assertIn("生成可信对比", model["next_action"]["label"])

    def test_unknown_files_require_review_even_without_diff_delta(self) -> None:
        from lib_guard.render.version_review_model import build_ip_user_view_model

        model = build_ip_user_view_model(
            {
                "status": "SAME",
                "base_ref": "previous_effective",
                "base_version": "v1_full",
                "comparison_semantics": "full",
                "delete_semantics": "real_delete",
                "lane_counts": {},
                "file_changes": [],
                "scan_evidence": {"counts": {"unknown": 2}},
            }
        )

        self.assertEqual(model["decision"]["status"], "USAGE_REVIEW_REQUIRED")
        self.assertIn("未知文件", model["decision"]["reason"])
        self.assertEqual(model["pending_fact_items"][0]["kind"], "UNKNOWN_FILES")
        self.assertNotIn("must_check_items", model)
        self.assertNotIn("usage_area_sections", model)

    def test_pending_facts_only_contain_unresolved_conditions_not_every_changed_view(self) -> None:
        from lib_guard.render.version_review_model import build_ip_user_view_model

        changed = build_ip_user_view_model(
            {
                "status": "CHANGED",
                "base_ref": "previous_effective",
                "base_version": "v1_full",
                "base_trust_status": "PASS",
                "comparison_semantics": "full",
                "delete_semantics": "real_delete",
                "file_changes": [{"change": "CHANGED", "file_type": "lef", "path": "LEF/a.lef"}],
                "lane_counts": {"recommended_file_diff": 1},
                "scan_evidence": {"counts": {"lef": 1}},
            }
        )
        removed = build_ip_user_view_model(
            {
                "status": "CHANGED",
                "base_ref": "previous_effective",
                "base_version": "v1_full",
                "base_trust_status": "PASS",
                "comparison_semantics": "full",
                "delete_semantics": "real_delete",
                "file_changes": [{"change": "REMOVED", "file_type": "lef", "path": "LEF/a.lef"}],
                "lane_counts": {"recommended_file_diff": 1},
                "scan_evidence": {"counts": {}},
            }
        )

        self.assertEqual(changed["pending_fact_items"], [])
        self.assertEqual([item["kind"] for item in removed["pending_fact_items"]], ["REAL_REMOVAL"])

    def test_ip_view_omits_duplicate_usage_and_policy_explanations(self) -> None:
        from lib_guard.render.version_review_render import render_ip_user_view

        html = render_ip_user_view(
            {
                "view_rows": [],
                "related_usage_sections": [
                    {
                        "area": "物理实现 / PD",
                        "summary": "关联 LEF / 物理抽象；本次可见变化 3 个。",
                        "evidence": "重点审查",
                    }
                ],
                "pending_fact_items": [],
                "non_blocker_note": "证据等级不自动构成阻塞。",
            }
        )

        self.assertNotIn("关联使用场景", html)
        self.assertNotIn("物理实现 / PD", html)
        self.assertNotIn("非阻塞说明", html)
        self.assertNotIn("review-group-card", html)
        self.assertNotIn("需确认", html)

    def test_ip_view_does_not_repeat_view_delta_as_pending_fact(self) -> None:
        from lib_guard.render.version_review_render import render_ip_user_view

        html = render_ip_user_view(
            {
                "view_rows": [],
                "pending_fact_items": [
                    {
                        "kind": "VIEW_DELTA",
                        "label": "文档与发布证据",
                        "summary": "新增 1 / 删除 0 / 修改 0",
                    },
                    {
                        "kind": "UNKNOWN_FILES",
                        "label": "待分类文件",
                        "summary": "当前交付包存在 1 个未知文件。",
                    },
                ],
            }
        )

        self.assertNotIn("文档与发布证据", html)
        self.assertIn("待分类文件", html)

    def test_ip_view_keeps_only_changed_or_unclassified_views_in_default_matrix(self) -> None:
        from lib_guard.render.version_review_render import render_ip_user_view

        html = render_ip_user_view(
            {
                "view_rows": [
                    {
                        "view_type": "doc_evidence",
                        "view": "文档与发布证据",
                        "delivery_count": 2,
                        "added": 1,
                        "removed": 0,
                        "changed": 1,
                        "delta_total": 2,
                        "baseline_only_count": 0,
                        "evidence_level": "人工审查",
                        "usage_area": "证据与豁免",
                    },
                    {
                        "view_type": "physical_abstract",
                        "view": "LEF / 物理抽象",
                        "delivery_count": 0,
                        "added": 0,
                        "removed": 0,
                        "changed": 0,
                        "delta_total": 0,
                        "baseline_only_count": 4,
                        "evidence_level": "无变化",
                        "usage_area": "物理实现 / PD",
                    },
                    {
                        "view_type": "unknown",
                        "view": "待分类文件",
                        "delivery_count": 2,
                        "added": 0,
                        "removed": 0,
                        "changed": 0,
                        "delta_total": 0,
                        "baseline_only_count": 0,
                        "status_label": "待分类",
                        "evidence_level": "人工审查",
                        "usage_area": "证据与豁免",
                    },
                ],
                "pending_fact_items": [{"label": "待分类文件", "summary": "当前交付包存在 2 个待分类文件。"}],
            }
        )

        self.assertIn("文档与发布证据", html)
        self.assertIn("待分类文件", html)
        self.assertNotIn("LEF / 物理抽象", html)
        self.assertIn("基准中另有 4 个文件未随本包交付，未计为删除。", html)
        self.assertNotIn("physical_abstract", html)

    def _render_doc_update_page(self) -> str:
        from lib_guard.render.version_detail_report import render_version_detail_page

        ip_model = {
            "schema_version": "ip_user_view.v2",
            "review_mode": "baseline",
            "decision": {
                "status": "USAGE_REVIEW_REQUIRED",
                "label": "需审查后使用",
                "reason": "文档视图存在 2 个真实变化。",
            },
            "comparison": {
                "scope": "incremental",
                "delete_semantics": "out_of_scope_missing",
                "visible_counts": {"added": 1, "removed": 0, "changed": 1},
                "baseline_only_count": 1,
                "baseline_only_label": "基准存在、本包未携带（不代表删除）",
                "base_label": "上一有效版 / full_v1",
            },
            "inventory_scope": {
                "delivery_file_count": 2,
                "delivery_view_counts": {"doc_evidence": 2},
                "candidate_effective_file_count": None,
                "candidate_effective_view_counts": {},
                "candidate_effective_available": False,
            },
            "view_rows": [
                {
                    "view_type": "doc_evidence",
                    "view": "文档与发布证据",
                    "delivery_count": 2,
                    "candidate_effective_count": None,
                    "added": 1,
                    "removed": 0,
                    "changed": 1,
                    "baseline_only_count": 0,
                    "delta_total": 2,
                    "evidence_level": "人工审查",
                    "usage_area": "证据与豁免",
                    "changed_examples": ["新增: doc/release_note.txt", "修改: SOURCE.md"],
                    "current_examples": ["doc/release_note.txt", "SOURCE.md"],
                    "full_evidence_href": "/tmp/file_diff.json",
                }
            ],
            "related_usage_sections": [],
            "pending_fact_items": [
                {
                    "kind": "VIEW_DELTA",
                    "label": "文档与发布证据",
                    "summary": "新增 1 / 删除 0 / 修改 1",
                    "file_count": 2,
                }
            ],
            "evidence_links": {"diff_file_changes": "/tmp/file_diff.json"},
            "non_blocker_note": "证据等级不自动构成阻塞。",
        }
        model = {
            "version_id": "doc_update",
            "target_version": "doc_update",
            "base_ref": "previous_effective",
            "base_version": "full_v1",
            "base_trust_status": "PASS",
            "review_mode": "baseline",
            "headline": "新增 1 / 删除 0 / 修改 1。",
            "confidence_note": "增量对比；本包未携带不代表删除。",
            "ip_user_view_model": ip_model,
            "version_review_model": {"ip_user_view": ip_model},
            "scan_context": {},
            "scan_evidence": {},
            "file_changes": [],
            "recommended_file_diff": [],
            "evidence_state": {
                "principle": "HTML 是事实投影。",
                "sources": [
                    {
                        "name": "diff",
                        "role": "变化事实",
                        "status": "PRESENT",
                        "artifacts": {},
                        "message": "已生成",
                    }
                ],
            },
        }
        lib = {"library_id": "ip/demo", "library_name": "demo", "display_name": "demo"}
        version = {"version_id": "doc_update", "review_gate": {}}
        from lib_guard.review.engineering import build_engineering_report
        model['engineering_report'] = build_engineering_report(model)
        with tempfile.TemporaryDirectory() as td:
            with patch("lib_guard.render.version_detail_report.build_version_update_detail_model", return_value=model):
                page = Path(render_version_detail_page(Path(td) / "html", lib, version))
            return page.read_text(encoding="utf-8")

    def test_view_matrix_precedes_fact_source_audit(self) -> None:
        html = self._render_doc_update_page()
        self.assertIn("视图变化矩阵", html)
        self.assertNotIn("事实源与审计证据", html)
        self.assertNotIn("scan_review_tables", html)

    def test_page_has_one_primary_decision_and_one_matrix_heading(self) -> None:
        html = self._render_doc_update_page()
        self.assertEqual(html.count("需审查后使用"), 1)
        self.assertEqual(html.count(">视图变化矩阵<"), 1)
        self.assertIn("已确认变化", html)
        self.assertNotIn("候选有效版 未生成", html)
        self.assertNotIn("由当前 scan / diff / effective 事实生成", html)
        self.assertNotIn("关联使用场景", html)
        self.assertNotIn("版本详情是唯一审查投影", html)
        self.assertNotIn("事实源与审计证据", html)
        self.assertNotIn("重点变化文件明细（按需展开）", html)
        self.assertNotIn("正式放行管理", html)

    def test_unknown_count_always_has_path_or_full_evidence_link(self) -> None:
        from lib_guard.render.version_review_model import build_ip_user_view_model

        result = build_ip_user_view_model(
            {
                "status": "SAME",
                "base_trust_status": "PASS",
                "comparison_semantics": "full",
                "delete_semantics": "real_delete",
                "scan_evidence": {
                    "file_count": 2,
                    "counts": {"unknown": 2},
                    "inventory": {
                        "files": [
                            {"path": "misc/a.foo", "file_type": "unknown"},
                            {"path": "misc/b.foo", "file_type": "unknown"},
                        ]
                    },
                    "review_links": {"unknown_files": "/tmp/unknown_files.tsv"},
                },
                "file_changes": [],
                "lane_counts": {},
                "trace_links": {},
            }
        )

        unknown = next(row for row in result["view_rows"] if row["view_type"] == "unknown")
        self.assertEqual(unknown["delivery_count"], 2)
        self.assertTrue(unknown["current_examples"] or unknown["full_evidence_href"])

    def test_scan_id_without_delivery_files_is_not_presented_as_scanned(self) -> None:
        from lib_guard.render.version_detail_report import _review_evidence_sidebar

        html = _review_evidence_sidebar(
            {
                "scan_context": {"scan_id": "legacy_scan"},
                "scan_evidence": {"inventory": {"files": []}, "counts": {}},
                "comparison_context": {"diff_status": "DIFF_NOT_RUN"},
                "lane_counts": {},
            },
            {},
        )

        self.assertIn("未获得可用的交付文件清单", html)
        self.assertNotIn("扫描结果已记录", html)
        self.assertNotIn("当前扫描交付文件", html)
        self.assertNotIn("scan_id", html)

    def test_sidebar_hides_complete_delivery_and_duplicate_lineage_panel(self) -> None:
        from lib_guard.render.version_detail_report import _review_evidence_sidebar

        html = _review_evidence_sidebar(
            {
                "scan_context": {"scan_id": "scan_ok", "scan_status": "SCAN_PASS"},
                "scan_evidence": {"file_count": 4, "inventory": {"files": [{"path": "lef/a.lef"}]}, "counts": {}},
                "comparison_context": {"diff_status": "CHANGED", "base_version": "base_v1"},
                "lane_counts": {"recommended_file_diff": 1},
                "ip_user_view_model": {
                    "delivery_completeness": {"status": "PASS", "required_total": 1, "required_present": 1, "missing": []},
                },
            },
            {},
        )

        self.assertIn("检查记录", html)
        self.assertNotIn("事实摘要", html)
        self.assertNotIn("交付完整度", html)
        self.assertNotIn("版本关系与来源", html)
        self.assertIn("原始证据", html)

    def test_large_diff_caps_inline_rows_and_keeps_full_evidence_link(self) -> None:
        from lib_guard.render.version_detail_report import render_version_update_detail_panel
        from lib_guard.render.version_review_model import build_ip_user_view_model

        changes = [
            {
                "change": "changed",
                "file_type": "lef",
                "path": f"LEF/macro_{index:04d}.lef",
                "review_lane": "P0",
            }
            for index in range(1000)
        ]
        model = {
            "status": "CHANGED",
            "base_trust_status": "PASS",
            "base_ref": "previous_effective",
            "base_version": "full_v1",
            "comparison_semantics": "full",
            "delete_semantics": "real_delete",
            "file_changes": changes,
            "lane_counts": {"recommended_file_diff": 1000},
            "trace_links": {"file_diff": "/tmp/file_diff.json", "diff_report": "/tmp/diff_html/index.html"},
            "headline": "修改 1000 个文件。",
            "confidence_note": "全量对比。",
        }
        model["ip_user_view_model"] = build_ip_user_view_model(model)
        model["version_review_model"] = {"ip_user_view": model["ip_user_view_model"]}

        html = render_version_update_detail_panel(model)

        self.assertLessEqual(html.count("<tr>"), 160)
        self.assertIn("对比数据（JSON）", html)
        self.assertIn("file_diff.json", html)


if __name__ == "__main__":
    unittest.main()
