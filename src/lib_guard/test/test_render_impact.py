from __future__ import annotations

import inspect
import unittest
from argparse import Namespace
from unittest import mock


class RenderImpactTest(unittest.TestCase):
    def test_attach_render_output_adds_human_readable_render_summary(self) -> None:
        from lib_guard.cli_commands.catalog import _attach_render_output

        output: dict[str, object] = {}
        _attach_render_output(
            output,
            {
                "catalog_html_out": "/tmp/work/catalog/html",
                "affected_pages": [
                    {"kind": "version_detail", "library": "ucie", "version": "v1", "reason": "scan_updated"},
                    {"kind": "library_page", "library": "ucie", "version": None, "reason": "scan_updated"},
                    {"kind": "catalog_index", "library": None, "version": None, "reason": "scan_updated"},
                ],
                "render_result": {
                    "status": "PASS",
                    "index_html": "/tmp/work/catalog/html/index.html",
                    "version_detail_pages": [
                        {
                            "library": "ucie",
                            "version": "v1",
                            "version_detail_html": "/tmp/work/catalog/html/libraries/ip_ucie/versions/v1/index.html",
                        }
                    ],
                    "rendered_libraries": 1,
                    "rendered_versions": 1,
                },
            },
        )

        self.assertEqual(
            output["render_summary"],
            {
                "status": "PASS",
                "message": "版本详情已刷新 1 个版本；Catalog 首页已更新",
                "catalog_html_out": "/tmp/work/catalog/html",
                "index_html": "/tmp/work/catalog/html/index.html",
                "open_first": "/tmp/work/catalog/html/libraries/ip_ucie/versions/v1/index.html",
                "version_detail_htmls": ["/tmp/work/catalog/html/libraries/ip_ucie/versions/v1/index.html"],
                "rendered_libraries": 1,
                "rendered_versions": 1,
                "skipped_reason": None,
                "deferred_pages": [],
                "deferred_file": None,
                "failed_versions": [],
                "affected_versions": [{"library": "ucie", "version": "v1"}],
            },
        )

    def test_attach_render_output_reports_deferred_navigation_pages(self) -> None:
        from lib_guard.cli_commands.catalog import _attach_render_output

        output: dict[str, object] = {}
        _attach_render_output(
            output,
            {
                "catalog_html_out": "/tmp/work/catalog/html",
                "affected_pages": [
                    {"kind": "version_detail", "library": "ucie", "version": "v1", "reason": "scan_updated"},
                    {"kind": "library_page", "library": "ucie", "version": None, "reason": "scan_updated"},
                ],
                "render_result": {
                    "status": "PASS",
                    "mode": "version_detail_direct",
                    "rendered_versions": 1,
                    "deferred_pages": [
                        {"kind": "library_page", "library": "ucie", "version": None, "reason": "scan_updated"},
                    ],
                    "deferred_file": "/tmp/work/catalog/html/render_deferred.json",
                },
            },
        )

        self.assertEqual(output["render_summary"]["message"], "版本详情已刷新 1 个版本；Catalog 导航页延迟刷新")
        self.assertEqual(output["render_summary"]["deferred_file"], "/tmp/work/catalog/html/render_deferred.json")

    def test_attach_render_output_reports_failed_version_detail_render(self) -> None:
        from lib_guard.cli_commands.catalog import _attach_render_output

        output: dict[str, object] = {}
        _attach_render_output(
            output,
            {
                "catalog_html_out": "/tmp/work/catalog/html",
                "affected_pages": [
                    {"kind": "version_detail", "library": "ucie", "version": "v1", "reason": "scan_updated"},
                ],
                "render_result": {
                    "status": "FAILED",
                    "mode": "version_detail_direct",
                    "rendered_versions": 0,
                    "failed_versions": [{"library": "ucie", "version": "v1", "error": "boom"}],
                },
            },
        )

        self.assertEqual(output["render_summary"]["message"], "版本详情刷新失败：1 个版本失败")
        self.assertEqual(output["render_summary"]["failed_versions"][0]["error"], "boom")

    def test_attach_render_output_says_when_render_is_skipped(self) -> None:
        from lib_guard.cli_commands.catalog import _attach_render_output

        output: dict[str, object] = {}
        _attach_render_output(
            output,
            {
                "catalog_html_out": "/tmp/work/catalog/html",
                "affected_pages": [
                    {"kind": "version_detail", "library": "ucie", "version": "v1", "reason": "scan_updated"},
                ],
                "render_result": {"status": "SKIPPED", "reason": "no_catalog_render"},
            },
        )

        self.assertEqual(output["render_summary"]["message"], "版本详情未刷新：no_catalog_render")
        self.assertEqual(output["render_summary"]["skipped_reason"], "no_catalog_render")

    def test_impacts_for_versions_dedups_versions_and_adds_parent_pages(self) -> None:
        from lib_guard.render.impact import impacts_for_versions, serialize_impacts

        impacts = impacts_for_versions("ucie", ["v1", "", "v1", "v2"], "scan_updated")

        self.assertEqual(
            serialize_impacts(impacts),
            [
                {"kind": "version_detail", "library": "ucie", "version": "v1", "reason": "scan_updated"},
                {"kind": "version_detail", "library": "ucie", "version": "v2", "reason": "scan_updated"},
                {"kind": "library_page", "library": "ucie", "version": None, "reason": "scan_updated"},
                {"kind": "catalog_index", "library": None, "version": None, "reason": "scan_updated"},
            ],
        )

    def test_dedup_impacts_keeps_first_page_identity(self) -> None:
        from lib_guard.render.impact import (
            catalog_index_impact,
            dedup_impacts,
            library_page_impact,
            serialize_impacts,
            version_detail_impact,
        )

        impacts = dedup_impacts(
            [
                version_detail_impact("ucie", "v1", "scan_updated"),
                version_detail_impact("ucie", "v1", "compare_updated"),
                library_page_impact("ucie", "scan_updated"),
                library_page_impact("ucie", "compare_updated"),
                catalog_index_impact("scan_updated"),
                catalog_index_impact("compare_updated"),
            ]
        )

        self.assertEqual(
            serialize_impacts(impacts),
            [
                {"kind": "version_detail", "library": "ucie", "version": "v1", "reason": "scan_updated"},
                {"kind": "library_page", "library": "ucie", "version": None, "reason": "scan_updated"},
                {"kind": "catalog_index", "library": None, "version": None, "reason": "scan_updated"},
            ],
        )

    def test_render_impacted_catalog_html_respects_no_catalog_render_with_output_shape(self) -> None:
        from lib_guard.cli_commands.common import render_impacted_catalog_html
        from lib_guard.render.impact import impacts_for_versions

        args = Namespace(
            catalog="/tmp/catalog.json",
            catalog_html_out="/tmp/html",
            no_catalog_render=True,
            workdir=None,
        )

        with mock.patch("lib_guard.catalog.index.render_catalog_html") as render:
            result = render_impacted_catalog_html(args, impacts_for_versions("ucie", ["v1"], "scan_updated"))

        self.assertEqual(result["catalog_html_out"], "/tmp/html")
        self.assertEqual(
            result["affected_pages"],
            [
                {"kind": "version_detail", "library": "ucie", "version": "v1", "reason": "scan_updated"},
                {"kind": "library_page", "library": "ucie", "version": None, "reason": "scan_updated"},
                {"kind": "catalog_index", "library": None, "version": None, "reason": "scan_updated"},
            ],
        )
        self.assertEqual(result["render_result"], {"status": "SKIPPED", "reason": "no_catalog_render"})
        render.assert_not_called()

    def test_render_impacted_catalog_html_renders_version_details_directly_by_default(self) -> None:
        from lib_guard.cli_commands.common import render_impacted_catalog_html
        from lib_guard.render.impact import impacts_for_versions

        args = Namespace(
            catalog="/tmp/catalog.json",
            catalog_html_out="/tmp/html",
            no_catalog_render=False,
            workdir=None,
        )

        render_result = {"status": "PASS", "mode": "version_detail_direct", "rendered_versions": 2}
        with mock.patch("lib_guard.render.version_detail_fast.render_impacted_version_details", return_value=render_result) as render:
            result = render_impacted_catalog_html(args, impacts_for_versions("ucie", ["v1", "v1", "v2"], "batch_scan_updated"))

        render.assert_called_once()
        self.assertEqual(render.call_args.kwargs["catalog_path"], "/tmp/catalog.json")
        self.assertEqual(render.call_args.kwargs["out_dir"], "/tmp/html")
        self.assertEqual([item.version for item in render.call_args.kwargs["impacts"]], ["v1", "v2"])
        self.assertEqual(result["catalog_html_out"], "/tmp/html")
        self.assertEqual(
            result["affected_pages"],
            [
                {"kind": "version_detail", "library": "ucie", "version": "v1", "reason": "batch_scan_updated"},
                {"kind": "version_detail", "library": "ucie", "version": "v2", "reason": "batch_scan_updated"},
                {"kind": "library_page", "library": "ucie", "version": None, "reason": "batch_scan_updated"},
                {"kind": "catalog_index", "library": None, "version": None, "reason": "batch_scan_updated"},
            ],
        )
        self.assertEqual(result["render_result"], render_result)

    def test_render_impacted_catalog_html_groups_by_library_when_full_render_fallback_is_enabled(self) -> None:
        from lib_guard.cli_commands.common import render_impacted_catalog_html
        from lib_guard.render.impact import impacts_for_versions

        args = Namespace(
            catalog="/tmp/catalog.json",
            catalog_html_out="/tmp/html",
            no_catalog_render=False,
            workdir=None,
        )
        impacts = impacts_for_versions("ucie", ["u1", "u2"], "scan_updated")
        impacts.extend(impacts_for_versions("pcie", ["p1"], "scan_updated"))

        with mock.patch.dict("os.environ", {"LIB_GUARD_FULL_RENDER_ON_IMPACT": "1"}), mock.patch(
            "lib_guard.catalog.index.render_catalog_html", return_value={"status": "PASS"}
        ) as render:
            result = render_impacted_catalog_html(args, impacts)

        self.assertEqual(render.call_count, 2)
        self.assertEqual(
            [call.kwargs for call in render.call_args_list],
            [
                {"library_filter": "ucie", "version_filter": ["u1", "u2"]},
                {"library_filter": "pcie", "version_filter": ["p1"]},
            ],
        )
        version_pages = [item for item in result["affected_pages"] if item["kind"] == "version_detail"]
        self.assertEqual(len(version_pages), 3)
        self.assertEqual(result["render_result"]["render_calls"], [{"status": "PASS"}, {"status": "PASS"}])

    def test_catalog_scan_compare_batch_and_mark_use_render_impact_finalizer(self) -> None:
        from lib_guard.cli_commands.catalog import (
            run_catalog_batch,
            run_catalog_compare,
            run_catalog_compare_batch,
            run_catalog_override,
            run_catalog_workflow,
        )

        for fn in [run_catalog_workflow, run_catalog_compare, run_catalog_batch, run_catalog_compare_batch, run_catalog_override]:
            source = inspect.getsource(fn)
            self.assertIn("render_impacted_catalog_html", source, fn.__name__)
            self.assertNotIn("refresh_catalog_html(args)", source, fn.__name__)


if __name__ == "__main__":
    unittest.main()
