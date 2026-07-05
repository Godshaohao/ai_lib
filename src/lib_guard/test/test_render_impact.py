from __future__ import annotations

import inspect
import unittest
from argparse import Namespace
from unittest import mock


class RenderImpactTest(unittest.TestCase):
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

    def test_render_impacted_catalog_html_renders_only_affected_versions_for_library(self) -> None:
        from lib_guard.cli_commands.common import render_impacted_catalog_html
        from lib_guard.render.impact import impacts_for_versions

        args = Namespace(
            catalog="/tmp/catalog.json",
            catalog_html_out="/tmp/html",
            no_catalog_render=False,
            workdir=None,
        )

        render_result = {"status": "PASS", "rendered_versions": 2, "index_html": "/tmp/html/index.html"}
        with mock.patch("lib_guard.catalog.index.render_catalog_html", return_value=render_result) as render:
            result = render_impacted_catalog_html(args, impacts_for_versions("ucie", ["v1", "v1", "v2"], "batch_scan_updated"))

        render.assert_called_once_with(
            "/tmp/catalog.json",
            "/tmp/html",
            library_filter="ucie",
            version_filter=["v1", "v2"],
        )
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

    def test_render_impacted_catalog_html_groups_by_library_to_avoid_cross_product(self) -> None:
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

        with mock.patch("lib_guard.catalog.index.render_catalog_html", return_value={"status": "PASS"}) as render:
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
