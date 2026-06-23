from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


class ReleaseManifestFlowTest(unittest.TestCase):
    def _write_manifest(self, path: Path, release_root: Path, ucie: Path, ddr: Path) -> dict:
        manifest = {
            "schema_version": "1.0",
            "release_id": "PD_LIB_CURRENT_20260618",
            "alias": "current",
            "release_root": str(release_root),
            "created_by": "unit-test",
            "libraries": [
                {
                    "library_type": "ip",
                    "library_name": "ucie",
                    "version_id": "stable_20260612",
                    "version_key": "ip/ucie/stable_20260612",
                    "source_path": str(ucie),
                    "scan_dir": str(Path("work") / "scan" / "ucie"),
                    "scan_html": "scan/ucie/index.html",
                    "diff_html": "diff/ucie/index.html",
                    "manual_accept": True,
                    "note": "manual accepted",
                },
                {
                    "library_type": "ip",
                    "library_name": "ddr",
                    "version_id": "final_20260601",
                    "version_key": "ip/ddr/final_20260601",
                    "source_path": str(ddr),
                    "scan_html": "scan/ddr/index.html",
                    "manual_accept": True,
                },
            ],
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
        return manifest

    def test_manifest_link_apply_verify_and_render_release_html_uses_file_level_view_layout(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            ucie = base / "raw" / "ucie" / "stable_20260612"
            ddr = base / "raw" / "ddr" / "final_20260601"
            release_root = base / "release_area"
            run_dir = base / "release_runs" / "PD_LIB_CURRENT_20260618"
            manifest_path = run_dir / "release_manifest.json"
            (ucie / "rtl").mkdir(parents=True)
            (ucie / "doc").mkdir()
            (ddr / "lef").mkdir(parents=True)
            (ucie / "rtl" / "top.v").write_text("module top(input a); endmodule\n", encoding="utf-8")
            (ucie / "doc" / "README.md").write_text("ucie release note\n", encoding="utf-8")
            (ddr / "lef" / "block.lef").write_text("VERSION 5.8 ;\nMACRO D\nEND D\n", encoding="utf-8")
            self._write_manifest(manifest_path, release_root, ucie, ddr)

            from lib_guard.release.linker import link_release_from_manifest
            from lib_guard.release.postcheck import verify_release_manifest

            dry = link_release_from_manifest(manifest_path, apply=False, mode="copy")
            self.assertEqual(dry["status"], "DRY_RUN")
            self.assertFalse((release_root / "current").exists())
            self.assertFalse((release_root / "ucie").exists())
            self.assertTrue(any(item["relative_path"] == "rtl/top.v" for item in dry["planned_files"]))
            self.assertTrue((run_dir / "release_link_result.json").exists())
            self.assertTrue((run_dir / "release_result.json").exists())
            dry_result = json.loads((run_dir / "release_result.json").read_text(encoding="utf-8"))
            self.assertEqual(dry_result["schema_version"], "release_result.v1")
            self.assertEqual(dry_result["status"], "READY")

            applied = link_release_from_manifest(manifest_path, apply=True, mode="copy")
            self.assertEqual(applied["status"], "APPLIED")
            applied_result = json.loads((run_dir / "release_result.json").read_text(encoding="utf-8"))
            self.assertEqual(applied_result["status"], "APPLIED")
            self.assertTrue((release_root / "rtl" / "top.v").exists())
            self.assertTrue((release_root / "doc" / "README.md").exists())
            self.assertTrue((release_root / "lef" / "block.lef").exists())
            self.assertFalse((release_root / "current").exists())
            self.assertFalse((release_root / "ucie").exists())

            verified = verify_release_manifest(manifest_path, render=True)
            self.assertEqual(verified["status"], "PASS")
            self.assertEqual(verified["summary"]["expected_libraries"], 2)
            self.assertEqual(verified["summary"]["expected_files"], 3)
            self.assertEqual(verified["summary"]["linked_files"], 3)
            self.assertEqual(verified["summary"]["missing_files"], 0)
            self.assertEqual(verified["summary"]["extra_files"], 0)
            self.assertEqual(verified["summary"]["target_mismatch"], 0)
            ucie_row = next(item for item in verified["libraries"] if item["library_name"] == "ucie")
            self.assertEqual(ucie_row["file_type_counts"]["verilog"], 1)
            self.assertEqual(ucie_row["file_type_counts"]["doc"], 1)
            self.assertTrue((run_dir / "release_postcheck.json").exists())
            self.assertTrue((run_dir / "index.html").exists())
            html = (run_dir / "index.html").read_text(encoding="utf-8")
            self.assertIn("Release 文件级审阅台", html)
            self.assertIn("ucie", html)
            self.assertIn("stable_20260612", html)

    def test_release_verify_reports_missing_extra_and_target_mismatch_files(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            ucie = base / "raw" / "ucie" / "stable_20260612"
            ddr = base / "raw" / "ddr" / "final_20260601"
            release_root = base / "release_area"
            run_dir = base / "release_runs" / "PD_LIB_CURRENT_20260618"
            manifest_path = run_dir / "release_manifest.json"
            ucie.mkdir(parents=True)
            ddr.mkdir(parents=True)
            (ucie / "top.v").write_text("module top; endmodule\n", encoding="utf-8")
            (ddr / "block.lef").write_text("VERSION 5.8 ;\nMACRO D\nEND D\n", encoding="utf-8")
            self._write_manifest(manifest_path, release_root, ucie, ddr)
            (release_root / "rtl").mkdir(parents=True)
            (release_root / "rtl" / "top.v").write_text("stale file\n", encoding="utf-8")
            (release_root / "lef").mkdir(parents=True)
            (release_root / "lef" / "extra.lef").write_text("extra\n", encoding="utf-8")
            (run_dir / "release_link_result.json").write_text(
                json.dumps(
                    {
                        "created_links": [
                            {
                                "library_name": "ucie",
                                "relative_path": "rtl/top.v",
                                "link_path": str(release_root / "rtl" / "top.v"),
                                "target_path": str(base / "wrong_source"),
                                "status": "COPIED",
                            }
                        ],
                        "failed_links": [],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            from lib_guard.release.postcheck import verify_release_manifest

            verified = verify_release_manifest(manifest_path)
            self.assertEqual(verified["status"], "PASS_WITH_WARNING")
            self.assertEqual(verified["summary"]["missing_files"], 1)
            self.assertEqual(verified["summary"]["extra_files"], 1)
            self.assertEqual(verified["summary"]["target_mismatch"], 1)
            categories = {item["category"] for item in verified["issues"]}
            self.assertIn("missing_file", categories)
            self.assertIn("extra_file", categories)
            self.assertIn("target_mismatch", categories)

    def test_manifest_apply_overwrite_mirrors_release_root_files(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            ucie = base / "raw" / "ucie" / "stable_20260620"
            ddr = base / "raw" / "ddr" / "final_20260601"
            release_root = base / "release_area"
            run_dir = base / "release_runs" / "PD_LIB_CURRENT_20260620"
            manifest_path = run_dir / "release_manifest.json"
            (ucie / "rtl").mkdir(parents=True)
            ddr.mkdir(parents=True)
            (ucie / "rtl" / "new_top.v").write_text("module new_top; endmodule\n", encoding="utf-8")
            (ddr / "ddr.v").write_text("module ddr; endmodule\n", encoding="utf-8")
            (release_root / "rtl").mkdir(parents=True)
            (release_root / "rtl" / "old_top.v").write_text("old\n", encoding="utf-8")
            self._write_manifest(manifest_path, release_root, ucie, ddr)

            from lib_guard.release.linker import link_release_from_manifest

            result = link_release_from_manifest(manifest_path, apply=True, mode="copy", overwrite=True)
            self.assertEqual(result["status"], "APPLIED")
            self.assertTrue((release_root / "rtl" / "new_top.v").exists())
            self.assertTrue((release_root / "rtl" / "ddr.v").exists())
            self.assertFalse((release_root / "rtl" / "old_top.v").exists())
            self.assertEqual(result["summary"]["removed_files"], 1)

    def test_manifest_template_selects_one_latest_scanned_version_per_library(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            catalog_path = base / "catalog" / "catalog.json"
            manifest_path = base / "release_runs" / "current" / "release_manifest.json"
            catalog = {
                "libraries": [
                    {
                        "library_id": "ip/ucie",
                        "library_type": "ip",
                        "library_name": "ucie",
                        "versions": [
                            {
                                "version_key": "ip/ucie/stable_20250601",
                                "version_id": "stable_20250601",
                                "library_type": "ip",
                                "library_name": "ucie",
                                "raw_path": str(base / "raw" / "ucie" / "stable_20250601"),
                                "scan": {"scan_dir": str(base / "scan" / "ucie_old")},
                            },
                            {
                                "version_key": "ip/ucie/stable_20250608",
                                "version_id": "stable_20250608",
                                "library_type": "ip",
                                "library_name": "ucie",
                                "raw_path": str(base / "raw" / "ucie" / "stable_20250608"),
                                "scan": {"scan_dir": str(base / "scan" / "ucie_new")},
                            },
                        ],
                    }
                ]
            }
            catalog_path.parent.mkdir(parents=True)
            catalog_path.write_text(json.dumps(catalog, ensure_ascii=False), encoding="utf-8")

            from lib_guard.release.bundle import create_manifest_template_from_catalog

            manifest = create_manifest_template_from_catalog(
                catalog_path,
                manifest_path,
                release_root=base / "release_area",
                alias="current",
            )
            self.assertEqual(len(manifest["libraries"]), 1)
            self.assertEqual(manifest["libraries"][0]["version_id"], "stable_20250608")

            with self.assertRaisesRegex(ValueError, "multiple versions for one library"):
                create_manifest_template_from_catalog(
                    catalog_path,
                    manifest_path,
                    release_root=base / "release_area",
                    alias="current",
                    versions=["ip/ucie/stable_20250601", "ip/ucie/stable_20250608"],
                )

    def test_release_manifest_accepts_utf8_bom_from_windows_editors(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            source = base / "raw" / "ucie"
            source.mkdir(parents=True)
            manifest_path = base / "release_manifest.json"
            payload = {
                "release_id": "BOM_TEST",
                "alias": "current",
                "release_root": str(base / "release_area"),
                "libraries": [{"library_name": "ucie", "version_id": "v1", "source_path": str(source)}],
            }
            manifest_path.write_text("\ufeff" + json.dumps(payload, ensure_ascii=False), encoding="utf-8")

            from lib_guard.release.bundle import load_release_manifest

            manifest = load_release_manifest(manifest_path)
            self.assertEqual(manifest["release_root"], str(base / "release_area"))
            self.assertEqual(manifest["libraries"][0]["library_name"], "ucie")


if __name__ == "__main__":
    unittest.main()
