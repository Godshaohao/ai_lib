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
                                "scan": {
                                    "status": "PASS",
                                    "scan_dir": str(root / "scan" / base.name),
                                    "parser_summary": {"parser_tasks": 1, "parsed_views": 1},
                                },
                            },
                            {
                                "version_id": patch.name,
                                "raw_path": str(patch),
                                "stage": "ad-hoc",
                                "update_scope": ["verilog"],
                                "scan": {
                                    "status": "PASS",
                                    "scan_dir": str(root / "scan" / patch.name),
                                    "parser_summary": {"parser_tasks": 2, "parsed_views": 1, "ignored_views": 1},
                                },
                                "diff": {
                                    "adjacent_status": "DIFF",
                                    "adjacent_old_version": base.name,
                                    "adjacent_diff_html": str(root / "diff_html" / patch.name / "index.html"),
                                    "summary": {"changed_files": 1, "removed_files": 0},
                                },
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
            self.assertEqual(manifest["version_evidence"]["summary"]["diff_ready_components"], 1)
            self.assertEqual(preview["schema_version"], "effective_release_preview.v1")
            self.assertEqual(preview["summary"]["actions"], {"add": 1})
            self.assertTrue((preview_dir / "release_delta.json").exists())
            self.assertTrue((preview_dir / "release_preview.csh").exists())
            self.assertIn("Effective Stack", html)
            self.assertIn("Version Evidence", html)
            self.assertIn("parser_tasks", html)
            self.assertIn("adjacent_old_version", html)
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
            self.assertIn("版本时间线", library_html)
            self.assertIn("latest_effective_ref", library_html)
            self.assertNotIn("Current Effective Detail", library_html)
            self.assertNotIn("Version Evidence", library_html)
            self.assertIn("Compare 索引", library_html)
            self.assertIn("Release Preview", library_html)
            self.assertNotIn("<iframe", library_html.lower())

    def test_catalog_indexes_current_effective_and_compare_report(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            raw = root / "raw"
            base = raw / "ucie" / "stable_20250601_base_full_release"
            patch = raw / "ucie" / "patch_20260624_rtl_lef_update"
            (base / "rtl").mkdir(parents=True)
            (base / "lef").mkdir(parents=True)
            (patch / "rtl").mkdir(parents=True)
            (patch / "lef").mkdir(parents=True)
            (base / "rtl" / "top.v").write_text("module top(input a); endmodule\n", encoding="utf-8")
            (base / "lef" / "ucie.lef").write_text("MACRO ucie\n  SIZE 1 BY 1 ;\nEND ucie\n", encoding="utf-8")
            (patch / "rtl" / "top.v").write_text("module top(input a, output b); endmodule\n", encoding="utf-8")
            (patch / "lef" / "ucie.lef").write_text("MACRO ucie\n  SIZE 2 BY 1 ;\nEND ucie\n", encoding="utf-8")

            from lib_guard.catalog.index import render_catalog_html, scan_catalog
            from lib_guard.effective.cli import main as effective_main

            catalog_dir = root / "catalog"
            html_dir = catalog_dir / "html"
            scan_catalog(raw, out_dir=catalog_dir, library_type="ip")
            e2_manifest = html_dir / "libraries" / "ip_ucie" / "effective" / "E2_20260624" / "effective_manifest.json"
            e3_manifest = html_dir / "libraries" / "ip_ucie" / "effective" / "E3_20260624" / "effective_manifest.json"
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
                        "--effective-id",
                        "E2_20260624",
                        "--out",
                        str(e2_manifest),
                        "--html",
                        str(e2_manifest.parent / "index.html"),
                    ]
                ),
                0,
            )
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
                        f"{patch.name}:verilog,lef",
                        "--effective-id",
                        "E3_20260624",
                        "--out",
                        str(e3_manifest),
                        "--html",
                        str(e3_manifest.parent / "index.html"),
                        "--release-preview",
                        str(e3_manifest.parent / "release_preview"),
                        "--release-id",
                        "R3_20260624",
                    ]
                ),
                0,
            )
            self.assertEqual(
                effective_main(
                    [
                        "accept",
                        "--effective",
                        str(e3_manifest),
                        "--html",
                        str(e3_manifest.parent / "index.html"),
                        "--release-preview",
                        str(e3_manifest.parent / "release_preview" / "index.html"),
                        "--status",
                        "accepted",
                    ]
                ),
                0,
            )
            compare_dir = html_dir / "libraries" / "ip_ucie" / "compares" / "E2_vs_E3"
            self.assertEqual(
                effective_main(
                    [
                        "compare",
                        "--catalog",
                        str(catalog_dir / "catalog.json"),
                        "--library",
                        "ucie",
                        "--old",
                        "effective:E2_20260624",
                        "--new",
                        "effective:E3_20260624",
                        "--mode",
                        "patch_delta",
                        "--compare-id",
                        "E2_vs_E3",
                        "--out-dir",
                        str(compare_dir),
                        "--search-root",
                        str(html_dir),
                    ]
                ),
                0,
            )

            compare_html = (compare_dir / "index.html").read_text(encoding="utf-8")
            self.assertIn("Compare Report", compare_html)
            self.assertIn("变化文件", compare_html)
            self.assertIn("风险复核", compare_html)
            self.assertIn("$PROJ/scripts/lg.csh fd", compare_html)
            self.assertNotIn("$PROJ/scripts/lg.csh file-diff", compare_html)

            result = render_catalog_html(catalog_dir / "catalog.json", html_dir)
            report_index = json.loads(Path(result["report_index"]).read_text(encoding="utf-8"))
            lib_entry = report_index["libraries"]["ip/ucie"]
            self.assertEqual(lib_entry["current_effective"], "E3_20260624")
            self.assertEqual(lib_entry["latest_effective_ref"], "E3_20260624")
            self.assertTrue(any(node["node_kind"] == "raw" for node in lib_entry["timeline"]))
            self.assertTrue(any(node["node_kind"] == "effective" for node in lib_entry["timeline"]))
            self.assertIn("E2_vs_E3", lib_entry["compare_reports"])
            self.assertEqual(lib_entry["compare_reports"]["E2_vs_E3"]["summary"]["changed_files"], 2)

            library_html = (html_dir / "libraries" / "ip_ucie" / "index.html").read_text(encoding="utf-8")
            self.assertIn("E3_20260624", library_html)
            self.assertIn("版本时间线", library_html)
            self.assertIn("E2_vs_E3", library_html)
            self.assertIn("打开报告", library_html)
            self.assertNotIn("<iframe", library_html.lower())

    def test_timeline_can_point_latest_effective_to_raw_full(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            raw = root / "raw"
            base = raw / "ucie" / "stable_20250601_base_full_release"
            patch = raw / "ucie" / "patch_20260624_rtl_update"
            full = raw / "ucie" / "stable_20260701_full_refresh"
            for folder in [base / "rtl", patch / "rtl", full / "rtl"]:
                folder.mkdir(parents=True)
            (base / "rtl" / "top.v").write_text("module top(input a); endmodule\n", encoding="utf-8")
            (patch / "rtl" / "top.v").write_text("module top(input a, output b); endmodule\n", encoding="utf-8")
            (full / "rtl" / "top.v").write_text("module top(input a, output b, output c); endmodule\n", encoding="utf-8")

            from lib_guard.catalog.index import render_catalog_html, scan_catalog
            from lib_guard.effective.cli import main as effective_main

            catalog_dir = root / "catalog"
            html_dir = catalog_dir / "html"
            scan_catalog(raw, out_dir=catalog_dir, library_type="ip")
            manifest = html_dir / "libraries" / "ip_ucie" / "effective" / "effective_20260624" / "effective_manifest.json"
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
                        "effective_20260624",
                        "--out",
                        str(manifest),
                        "--html",
                        str(manifest.parent / "index.html"),
                    ]
                ),
                0,
            )

            result = render_catalog_html(catalog_dir / "catalog.json", html_dir)
            report_index = json.loads(Path(result["report_index"]).read_text(encoding="utf-8"))
            lib_entry = report_index["libraries"]["ip/ucie"]
            self.assertEqual(lib_entry["latest_effective_ref"], full.name)

            nodes = {node["version_id"]: node for node in lib_entry["timeline"]}
            self.assertEqual(nodes[full.name]["node_kind"], "raw")
            self.assertEqual(nodes[full.name]["package_type"], "full")
            self.assertEqual(nodes[full.name]["usage_status"], "current")
            self.assertEqual(nodes[patch.name]["package_type"], "partial")
            self.assertEqual(nodes[patch.name]["usage_status"], "accepted")
            self.assertEqual(nodes["effective_20260624"]["node_kind"], "effective")
            self.assertEqual(nodes["effective_20260624"]["package_type"], "composed")

            library_html = (html_dir / "libraries" / "ip_ucie" / "index.html").read_text(encoding="utf-8")
            self.assertIn("Current Effective", library_html)
            self.assertIn(full.name, library_html)
            self.assertIn("版本时间线", library_html)
            self.assertNotIn("Current Effective Detail", library_html)
            self.assertNotIn("Current raw", library_html)
            self.assertNotIn("Version Evidence", library_html)
            self.assertNotIn("Scan HTML", library_html)
            self.assertNotIn("Diff HTML", library_html)


if __name__ == "__main__":
    unittest.main()
