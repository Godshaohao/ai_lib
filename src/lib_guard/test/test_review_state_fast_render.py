from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from lib_guard.render.impact import impacts_for_versions
from lib_guard.render.version_detail_fast import render_impacted_version_details, render_version_detail_only
from lib_guard.review.state import build_review_version_state


class ReviewStateFastRenderTest(unittest.TestCase):
    def _catalog(self):
        return {
            "libraries": [
                {
                    "library_id": "Vendor_A/模拟IP/UVIP/ucie",
                    "typed_library_id": "Vendor_A_模拟IP_UVIP_ucie",
                    "formal_library_id": "Vendor_A_模拟IP_UVIP_ucie",
                    "library_name": "Vendor_A_模拟IP_UVIP_ucie",
                    "display_name": "ucie",
                    "report_slug": "Vendor_A_模拟IP_UVIP_ucie",
                    "versions": [
                        {
                            "version_id": "full1",
                            "version_key": "Vendor_A_模拟IP_UVIP_ucie:full1",
                            "stage": "stable",
                            "package_type": "FULL_PACKAGE",
                            "raw_path": "/raw/full1",
                            "scan": {"status": "SCANNED", "scan_dir": "/tmp/nonexistent_scan"},
                            "diff": {},
                        },
                        {
                            "version_id": "fix11",
                            "version_key": "Vendor_A_模拟IP_UVIP_ucie:fix11",
                            "stage": "adhoc",
                            "package_type": "PARTIAL_UPDATE",
                            "raw_path": "/raw/fix11",
                            "scan": {"status": "SCANNED", "scan_dir": "/tmp/nonexistent_scan"},
                            "diff": {},
                        },
                    ],
                }
            ]
        }

    def test_build_review_version_state_enriches_one_version(self):
        with tempfile.TemporaryDirectory() as td:
            lib, version = build_review_version_state(
                self._catalog(),
                out_dir=td,
                library="ucie",
                version="fix11",
            )
        self.assertEqual(version["version_id"], "fix11")
        self.assertEqual(version["library_name"], "Vendor_A_模拟IP_UVIP_ucie")
        self.assertIn("review_gate", version)
        self.assertIn("links", version)
        self.assertIn("pairwise_summary", version)
        self.assertEqual(lib["versions"][0]["version_id"], "fix11")
        self.assertEqual(lib["version_count"], 2)

    def test_render_version_detail_only_uses_enriched_state(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            catalog_path = root / "catalog.json"
            import json
            catalog_path.write_text(json.dumps(self._catalog(), ensure_ascii=False), encoding="utf-8")
            with patch("lib_guard.render.version_detail_report.render_version_detail_page") as render_page:
                render_page.return_value = str(root / "out.html")
                result = render_version_detail_only(
                    catalog_path=catalog_path,
                    out_dir=root / "html",
                    library="ucie",
                    version="fix11",
                )
        self.assertEqual(result["status"], "PASS")
        self.assertTrue(result["enriched_review_state"])
        args, _kwargs = render_page.call_args
        _out_dir, _lib, enriched_version = args
        self.assertIn("review_gate", enriched_version)
        self.assertEqual(enriched_version["version_id"], "fix11")

    def test_render_version_detail_only_reads_runtime_sidecar_without_embedded_runtime(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            catalog_path = root / "catalog.json"
            catalog = self._catalog()
            for version in catalog["libraries"][0]["versions"]:
                version.pop("scan", None)
                version.pop("diff", None)
            import json

            catalog_path.write_text(json.dumps(catalog, ensure_ascii=False), encoding="utf-8")
            (root / "catalog_runtime.json").write_text(
                json.dumps(
                    {
                        "schema_version": "catalog_runtime.v1",
                        "runtime_state": {
                            "Vendor_A_模拟IP_UVIP_ucie:fix11": {
                                "scan": {
                                    "status": "SCANNED",
                                    "scan_id": "sidecar-scan",
                                    "scan_dir": str(root / "scan" / "fix11"),
                                },
                                "diff": {"adjacent_status": "DIFF"},
                            }
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            with patch("lib_guard.render.version_detail_report.render_version_detail_page") as render_page:
                render_page.return_value = str(root / "out.html")
                result = render_version_detail_only(
                    catalog_path=catalog_path,
                    out_dir=root / "html",
                    library="ucie",
                    version="fix11",
                )

        self.assertEqual(result["status"], "PASS")
        args, _kwargs = render_page.call_args
        _out_dir, _lib, enriched_version = args
        self.assertEqual(enriched_version["scan_status"], "SCAN_PASS")
        self.assertEqual(enriched_version["scan"]["scan_id"], "sidecar-scan")
        self.assertEqual(enriched_version["diff"]["adjacent_status"], "DIFF")

    def test_render_impacted_version_details_defers_navigation_pages(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            catalog_path = root / "catalog.json"
            import json
            catalog_path.write_text(json.dumps(self._catalog(), ensure_ascii=False), encoding="utf-8")
            impacts = impacts_for_versions("ucie", ["fix11", "fix11"], "scan_updated")
            with patch("lib_guard.render.version_detail_report.render_version_detail_page") as render_page:
                render_page.return_value = str(root / "html/libraries/ucie/versions/fix11/index.html")
                result = render_impacted_version_details(
                    catalog_path=catalog_path,
                    out_dir=root / "html",
                    impacts=impacts,
                    all_impacts=impacts,
                )
            self.assertEqual(result["status"], "PASS")
            self.assertEqual(result["rendered_versions"], 1)
            self.assertTrue(result["deferred_file"])
            self.assertTrue((root / "html" / "render_deferred.json").exists())
            self.assertTrue(result["deferred_pages"])


if __name__ == "__main__":
    unittest.main()
