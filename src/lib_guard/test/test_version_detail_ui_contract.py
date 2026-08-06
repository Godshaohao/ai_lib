from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class VersionDetailUiContractTest(unittest.TestCase):
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

        self.assertEqual(result["visible_counts"], {"added": 1, "removed": 0, "changed": 1})
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

        self.assertEqual(result["visible_counts"], {"added": 0, "removed": 1, "changed": 0})
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
        for header in ["当前文件", "新增", "删除", "修改", "证据 / 状态", "代表文件"]:
            self.assertIn(f"<th>{header}</th>", html)
        self.assertIn("delta-number added", html)
        self.assertIn("delta-number changed", html)
        self.assertIn("展开文件", html)

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
        self.assertIn("review-primary-column", html)
        self.assertIn("review-secondary-column", html)
        self.assertIn("review-summary-strip", html)
        self.assertIn("--review-ink", html)
        self.assertIn("view-delta-toolbar", html)
        self.assertIn("delta-legend", html)
        self.assertIn("视图变化矩阵", html)
        self.assertIn("正式放行管理", html)
        self.assertIn("证据入口 / 调试", html)
        self.assertIn("<table class='view-delta-table'>", html)
        self.assertNotIn("<details class='panel collapsible' open>", html)

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

    def test_version_detail_generates_filterable_file_evidence_page(self) -> None:
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
                        "review_gate": {},
                    },
                )
            )
            evidence_page = page.parent / "file-evidence.html"
            detail_html = page.read_text(encoding="utf-8")
            evidence_html = evidence_page.read_text(encoding="utf-8")
            self.assertTrue(evidence_page.exists())
            self.assertIn("文件证据清单", evidence_html)
            self.assertIn("data-filterable-table", evidence_html)
            self.assertIn("文件路径", evidence_html)
            self.assertIn("file-evidence.html", detail_html)

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
        self.assertIn("Unknown", model["decision"]["reason"])
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
                        "summary": "当前交付包存在 1 个 Unknown 文件。",
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
        self.assertIn("交付变化", html)
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
        self.assertIn("完整变化证据", html)
        self.assertIn("file_diff.json", html)


if __name__ == "__main__":
    unittest.main()
