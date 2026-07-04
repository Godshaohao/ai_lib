from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


class PackageFlowTest(unittest.TestCase):
    def _write_catalog(self, path: Path, base: Path, update: Path) -> None:
        catalog = {
            "schema_version": "1.0",
            "libraries": [
                {
                    "library_id": "ip/ucie",
                    "library_type": "ip",
                    "library_name": "ucie",
                    "versions": [
                        {
                            "version_key": "ip/ucie/ucie_full_20260601",
                            "version_id": "ucie_full_20260601",
                            "library_type": "ip",
                            "library_name": "ucie",
                            "raw_path": str(base),
                            "package_type": "FULL_PACKAGE",
                            "update_scope": ["rtl", "lef", "lib", "gds", "sdc", "doc"],
                            "standalone": True,
                            "base_required": False,
                            "scan": {"scan_dir": None},
                        },
                        {
                            "version_key": "ip/ucie/ucie_rtl_patch_20260618",
                            "version_id": "ucie_rtl_patch_20260618",
                            "library_type": "ip",
                            "library_name": "ucie",
                            "raw_path": str(update),
                            "package_type": "PARTIAL_UPDATE",
                            "update_scope": ["rtl", "doc"],
                            "standalone": False,
                            "base_required": True,
                            "manual_review": True,
                            "scan": {"scan_dir": None},
                        },
                    ],
                }
            ],
            "manual_overrides": {},
            "runtime_state": {},
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(catalog, indent=2, ensure_ascii=False), encoding="utf-8")

    def test_classify_package_types_and_scopes(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            full = root / "full"
            partial = root / "partial"
            doc = root / "doc"
            reports = root / "reports"
            for p in [full / "rtl", full / "lef", full / "lib", full / "gds", full / "doc", partial / "rtl", partial / "doc", doc, reports / "logs"]:
                p.mkdir(parents=True, exist_ok=True)
            (full / "rtl" / "top.v").write_text("module top; endmodule\n", encoding="utf-8")
            (full / "lef" / "ucie.lef").write_text("MACRO U\nEND U\n", encoding="utf-8")
            (full / "lib" / "ucie.lib").write_text("library(u) {}\n", encoding="utf-8")
            (full / "gds" / "ucie.gds").write_bytes(b"gds")
            (full / "doc" / "README.md").write_text("full\n", encoding="utf-8")
            (partial / "rtl" / "top.v").write_text("module top; endmodule\n", encoding="utf-8")
            (partial / "doc" / "release_note.txt").write_text("patch\n", encoding="utf-8")
            (doc / "release_note.txt").write_text("doc only\n", encoding="utf-8")
            (reports / "logs" / "run.log").write_text("log\n", encoding="utf-8")

            from lib_guard.package.classifier import classify_package

            self.assertEqual(classify_package(full, library_type="ip")["package_type"], "FULL_PACKAGE")
            partial_result = classify_package(partial, library_type="ip")
            self.assertEqual(partial_result["package_type"], "PARTIAL_UPDATE")
            self.assertEqual(partial_result["update_scope"], ["rtl", "doc"])
            self.assertFalse(partial_result["standalone"])
            self.assertTrue(partial_result["base_required"])
            self.assertEqual(classify_package(doc, library_type="ip")["package_type"], "DOC_UPDATE")
            self.assertEqual(classify_package(reports, library_type="ip")["package_type"], "UNKNOWN_PACKAGE")

    def test_attach_updates_catalog_only_and_assemble_inherits_base_views(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            base = root / "raw" / "ucie_full_20260601"
            update = root / "raw" / "ucie_rtl_patch_20260618"
            catalog = root / "catalog" / "catalog.json"
            for p in [base / "rtl", base / "lef", base / "lib", base / "gds", base / "sdc", base / "doc", update / "rtl", update / "doc"]:
                p.mkdir(parents=True, exist_ok=True)
            (base / "rtl" / "top.v").write_text("module top; endmodule\n", encoding="utf-8")
            (base / "lef" / "ucie.lef").write_text("MACRO U\nEND U\n", encoding="utf-8")
            (base / "lib" / "ucie.lib").write_text("library(u) {}\n", encoding="utf-8")
            (base / "gds" / "ucie.gds").write_bytes(b"gds")
            (base / "sdc" / "ucie.sdc").write_text("create_clock clk\n", encoding="utf-8")
            (base / "doc" / "README.md").write_text("base doc\n", encoding="utf-8")
            (update / "rtl" / "top.v").write_text("module top(input a); endmodule\n", encoding="utf-8")
            (update / "doc" / "release_note.txt").write_text("rtl patch\n", encoding="utf-8")
            self._write_catalog(catalog, base, update)

            from lib_guard.package.attach import attach_base
            from lib_guard.package.assemble import assemble_snapshot

            attach = attach_base(catalog, package_key="ip/ucie/ucie_rtl_patch_20260618", base_version="ucie_full_20260601")
            self.assertEqual(attach["status"], "PASS")
            data = json.loads(catalog.read_text(encoding="utf-8"))
            patch = next(v for lib in data["libraries"] for v in lib["versions"] if v["version_id"] == "ucie_rtl_patch_20260618")
            self.assertEqual(patch["base_version"], "ucie_full_20260601")
            self.assertFalse(patch["manual_review"])
            self.assertFalse((update / "release_manifest.json").exists())

            snapshot = assemble_snapshot(
                catalog,
                library="ucie",
                base_version="ucie_full_20260601",
                updates=["ucie_rtl_patch_20260618"],
                out_path=root / "snapshots" / "ucie_snapshot_20260618.json",
            )
            self.assertEqual(snapshot["status"], "PASS")
            self.assertEqual(snapshot["resolved_views"]["rtl"], "ucie_rtl_patch_20260618")
            self.assertEqual(snapshot["resolved_views"]["doc"], "ucie_rtl_patch_20260618")
            self.assertEqual(snapshot["resolved_views"]["lef"], "ucie_full_20260601")
            self.assertTrue(any(item["target_relpath"] == "RTL/top.v" and item["source_kind"] == "update" for item in snapshot["resolved_files"]))
            self.assertTrue(any(item["target_relpath"] == "LEF/ucie.lef" and item["source_kind"] == "base" for item in snapshot["resolved_files"]))

    def test_release_manifest_from_snapshot_preserves_source_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            src = root / "raw"
            (src / "rtl").mkdir(parents=True)
            (src / "rtl" / "top.v").write_text("module top; endmodule\n", encoding="utf-8")
            snapshot = {
                "schema_version": "1.0",
                "snapshot_id": "ucie_snapshot_20260618",
                "library_type": "ip",
                "library_name": "ucie",
                "base_package": "ucie_full_20260601",
                "updates": ["ucie_rtl_patch_20260618"],
                "resolved_views": {"rtl": "ucie_rtl_patch_20260618"},
                "resolved_files": [
                    {
                        "target_relpath": "rtl/top.v",
                        "source_package": "ucie_rtl_patch_20260618",
                        "source_path": str(src / "rtl" / "top.v"),
                        "file_type": "verilog",
                        "view": "rtl",
                        "source_kind": "update",
                    }
                ],
                "issues": [],
            }
            snapshot_path = root / "snapshots" / "ucie_snapshot_20260618.json"
            snapshot_path.parent.mkdir(parents=True)
            snapshot_path.write_text(json.dumps(snapshot, ensure_ascii=False), encoding="utf-8")
            manifest_path = root / "release_runs" / "PD_LIB_CURRENT" / "release_manifest.json"

            from lib_guard.release.bundle import create_manifest_from_snapshot, iter_release_files

            manifest = create_manifest_from_snapshot(snapshot_path, manifest_path, release_root=root / "release_area")
            self.assertEqual(manifest["snapshot_id"], "ucie_snapshot_20260618")
            self.assertEqual(len(manifest["files"]), 1)
            self.assertEqual(manifest["files"][0]["source_package"], "ucie_rtl_patch_20260618")
            self.assertEqual(manifest["files"][0]["source_kind"], "update")
            planned = iter_release_files(manifest)
            self.assertEqual(planned[0]["relative_path"], "RTL/top.v")
            self.assertEqual(planned[0]["source_package"], "ucie_rtl_patch_20260618")
            self.assertEqual(planned[0]["source_kind"], "update")

    def test_cli_package_assemble_and_release_manifest_from_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            base = root / "raw" / "base"
            update = root / "raw" / "update"
            catalog = root / "catalog" / "catalog.json"
            (base / "lef").mkdir(parents=True)
            (update / "rtl").mkdir(parents=True)
            (base / "lef" / "ucie.lef").write_text("MACRO U\nEND U\n", encoding="utf-8")
            (update / "rtl" / "top.v").write_text("module top; endmodule\n", encoding="utf-8")
            self._write_catalog(catalog, base, update)

            from lib_guard.cli import main

            snapshot = root / "snapshots" / "ucie_snapshot.json"
            manifest = root / "release_runs" / "PD_LIB_CURRENT" / "release_manifest.json"
            self.assertEqual(
                main(
                    [
                        "package",
                        "attach",
                        "--catalog",
                        str(catalog),
                        "--package",
                        "ip/ucie/ucie_rtl_patch_20260618",
                        "--base",
                        "ucie_full_20260601",
                    ]
                ),
                0,
            )
            self.assertEqual(
                main(
                    [
                        "package",
                        "assemble",
                        "--catalog",
                        str(catalog),
                        "--library",
                        "ucie",
                        "--base",
                        "ucie_full_20260601",
                        "--update",
                        "ucie_rtl_patch_20260618",
                        "--out",
                        str(snapshot),
                        "--render",
                    ]
                ),
                0,
            )
            self.assertTrue(snapshot.exists())
            self.assertTrue((snapshot.parent / "ucie_snapshot_html" / "index.html").exists())
            self.assertEqual(
                main(
                    [
                        "release",
                        "manifest",
                        "--snapshot",
                        str(snapshot),
                        "--release-root",
                        str(root / "release_area"),
                        "--out",
                        str(manifest),
                    ]
                ),
                0,
            )
            data = json.loads(manifest.read_text(encoding="utf-8"))
            self.assertEqual(data["snapshot_id"], "ucie_snapshot")
            rtl = next(item for item in data["files"] if item["target_relpath"] == "RTL/top.v")
            self.assertEqual(rtl["source_package"], "ucie_rtl_patch_20260618")


if __name__ == "__main__":
    unittest.main()
