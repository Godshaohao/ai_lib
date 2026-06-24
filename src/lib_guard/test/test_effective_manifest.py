from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path


class EffectiveManifestTest(unittest.TestCase):
    def test_build_manifest_release_preview_and_html_for_partial_update(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            raw = root / "raw" / "ucie"
            base = raw / "stable_20250601_base_full_release_candidate_for_long_id_layout_check"
            patch = raw / "patch_20260612_incremental_rtl_doc_lef_lib_update_extra_long_id_case"
            (base / "rtl").mkdir(parents=True)
            (patch / "rtl").mkdir(parents=True)
            (base / "rtl" / "top.v").write_text("module top(input a); endmodule\n", encoding="utf-8")
            (patch / "rtl" / "top.v").write_text("module top(input a, output b); endmodule\n", encoding="utf-8")

            catalog = {
                "libraries": [
                    {
                        "library_id": "ip/ucie",
                        "library_name": "ucie",
                        "versions": [
                            {
                                "version_id": base.name,
                                "raw_path": str(base),
                                "stage": "stable",
                            },
                            {
                                "version_id": patch.name,
                                "raw_path": str(patch),
                                "stage": "ad-hoc",
                                "update_scope": ["verilog"],
                            },
                        ],
                    }
                ]
            }
            catalog_path = root / "catalog.json"
            catalog_path.write_text(json.dumps(catalog, ensure_ascii=False), encoding="utf-8")

            from lib_guard.effective.cli import main

            manifest_path = root / "effective" / "effective_manifest.json"
            html_path = root / "effective" / "index.html"
            preview_dir = root / "effective" / "release_preview"
            self.assertEqual(
                main(
                    [
                        "build",
                        "--catalog",
                        str(catalog_path),
                        "--library",
                        "ucie",
                        "--base-full",
                        base.name,
                        "--include",
                        patch.name,
                        "--scope",
                        f"{patch.name}:verilog",
                        "--effective-id",
                        "E_LONG_20260624",
                        "--out",
                        str(manifest_path),
                        "--html",
                        str(html_path),
                        "--release-preview",
                        str(preview_dir),
                        "--release-root",
                        str(root / "release_area"),
                        "--release-id",
                        "R_LONG_20260624",
                        "--link-mode",
                        "copy",
                    ]
                ),
                0,
            )

            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            preview = json.loads((preview_dir / "release_manifest.json").read_text(encoding="utf-8"))
            html = html_path.read_text(encoding="utf-8")

            self.assertEqual(manifest["schema_version"], "effective_manifest.v2")
            self.assertEqual(manifest["summary"]["file_count"], 1)
            self.assertEqual(manifest["summary"]["operation_summary"], {"replace": 1})
            self.assertEqual(manifest["effective_files"]["rtl/top.v"]["source_version"], patch.name)
            self.assertEqual(preview["schema_version"], "effective_release_preview.v1")
            self.assertEqual(preview["summary"]["actions"], {"add": 1})
            self.assertTrue((preview_dir / "release_delta.json").exists())
            self.assertTrue((preview_dir / "release_preview.csh").exists())
            self.assertIn("Effective Stack", html)
            self.assertIn("Release Delta Preview", html)
            self.assertIn("stable_20250601_base", html)
            self.assertNotIn("鍩", html)

    def test_catalog_indexes_effective_report_without_embedding_it(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            raw = root / "raw"
            base = raw / "ucie" / "stable_20250601_base_full_release_candidate"
            patch = raw / "ucie" / "patch_20260612_incremental_rtl_update"
            (base / "rtl").mkdir(parents=True)
            (patch / "rtl").mkdir(parents=True)
            (base / "rtl" / "top.v").write_text("module top(input a); endmodule\n", encoding="utf-8")
            (patch / "rtl" / "top.v").write_text("module top(input a, output b); endmodule\n", encoding="utf-8")

            from lib_guard.catalog.index import render_catalog_html, scan_catalog
            from lib_guard.effective.cli import main as effective_main

            catalog_dir = root / "catalog"
            scan_catalog(raw, out_dir=catalog_dir, library_type="ip")
            manifest_path = catalog_dir / "effective" / "ucie" / "E1_20260624" / "effective_manifest.json"
            effective_html = manifest_path.parent / "index.html"
            release_preview_dir = manifest_path.parent / "release_preview"
            self.assertEqual(
                effective_main(
                    [
                        "build",
                        "--catalog",
                        str(catalog_dir / "catalog.json"),
                        "--library",
                        "ucie",
                        "--base-full",
                        base.name,
                        "--include",
                        patch.name,
                        "--scope",
                        f"{patch.name}:verilog",
                        "--effective-id",
                        "E1_20260624",
                        "--out",
                        str(manifest_path),
                        "--html",
                        str(effective_html),
                        "--release-preview",
                        str(release_preview_dir),
                        "--release-id",
                        "R1_20260624",
                    ]
                ),
                0,
            )

            result = render_catalog_html(catalog_dir / "catalog.json", catalog_dir / "html")
            self.assertEqual(result["status"], "PASS")
            report_index = json.loads(Path(result["report_index"]).read_text(encoding="utf-8"))
            lib_entry = report_index["libraries"]["ip/ucie"]
            self.assertIn("E1_20260624", lib_entry["effective"])
            self.assertTrue(lib_entry["effective"]["E1_20260624"]["html"].endswith("index.html"))
            self.assertTrue(lib_entry["effective"]["E1_20260624"]["release_preview"].endswith("release_preview/index.html"))

            index_html = Path(result["index_html"]).read_text(encoding="utf-8")
            self.assertIn("report_index.json", index_html)
            self.assertIn("进入库工作台", index_html)
            self.assertNotIn("<iframe", index_html.lower())

            library_home = catalog_dir / "html" / "libraries" / "ip_ucie" / "index.html"
            self.assertTrue(library_home.exists())
            library_html = library_home.read_text(encoding="utf-8")
            self.assertIn("Effective Summary", library_html)
            self.assertIn("Compare Index", library_html)
            self.assertIn("Release Preview", library_html)
            self.assertNotIn("<iframe", library_html.lower())


if __name__ == "__main__":
    unittest.main()
