from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path


class EffectiveManifestTest(unittest.TestCase):
    @staticmethod
    def _lock_catalog(*, snapshots: dict[str, str] | None = None, fingerprints: dict[str, str] | None = None) -> dict[str, object]:
        snapshots = snapshots or {}
        fingerprints = fingerprints or {}
        versions = []
        for version_id in ("full", "fix1", "fix2"):
            scan: dict[str, object] = {}
            if version_id in snapshots:
                scan["snapshot_identity"] = {
                    "digest": snapshots[version_id],
                    "strength": "full",
                }
            if version_id in fingerprints:
                scan["input_fingerprint"] = {"hash": fingerprints[version_id]}
            versions.append({"version_id": version_id, "scan": scan})
        return {"libraries": [{"library_id": "ip/demo", "library_name": "demo", "versions": versions}]}

    def test_effective_digest_binds_component_order_and_snapshots(self) -> None:
        from lib_guard.effective.manifest import build_effective_manifest

        catalog = self._lock_catalog(
            snapshots={"full": "sha256:full", "fix1": "sha256:fix1", "fix2": "sha256:fix2"},
        )
        first = build_effective_manifest(catalog, "demo", "full", [("fix1", ["lef"]), ("fix2", ["lef"])])
        repeated = build_effective_manifest(catalog, "demo", "full", [("fix1", ["lef"]), ("fix2", ["lef"])])
        reordered = build_effective_manifest(catalog, "demo", "full", [("fix2", ["lef"]), ("fix1", ["lef"])])
        changed_catalog = self._lock_catalog(
            snapshots={"full": "sha256:full", "fix1": "sha256:changed", "fix2": "sha256:fix2"},
        )
        changed_snapshot = build_effective_manifest(
            changed_catalog,
            "demo",
            "full",
            [("fix1", ["lef"]), ("fix2", ["lef"])],
        )

        self.assertEqual(first["identity"]["digest"], repeated["identity"]["digest"])
        self.assertNotEqual(first["identity"]["digest"], reordered["identity"]["digest"])
        self.assertNotEqual(first["identity"]["digest"], changed_snapshot["identity"]["digest"])
        self.assertEqual(first["components"][1]["snapshot_digest"], "sha256:fix1")
        self.assertEqual(first["components"][1]["evidence_strength"], "full")

    def test_effective_digest_excludes_created_at_and_paths(self) -> None:
        from lib_guard.effective.manifest import build_effective_manifest
        from lib_guard.identity import build_effective_identity

        catalog = self._lock_catalog(snapshots={"full": "sha256:full", "fix1": "sha256:fix1"})
        manifest = build_effective_manifest(catalog, "demo", "full", [("fix1", ["lef"])])
        audit_only = {
            **manifest,
            "created_at": "2099-01-01T00:00:00Z",
            "manifest_path": "/other-host/effective_manifest.json",
            "effective_files": {"lef/demo.lef": {"source_path": "/other-host/demo.lef"}},
        }

        self.assertEqual(manifest["identity"]["digest"], build_effective_identity(audit_only)["digest"])

    def test_effective_components_mark_legacy_and_missing_evidence(self) -> None:
        from lib_guard.effective.manifest import build_effective_manifest

        legacy = build_effective_manifest(
            self._lock_catalog(fingerprints={"full": "legacy-full", "fix1": "legacy-fix"}),
            "demo",
            "full",
            [("fix1", ["lef"])],
        )
        missing = build_effective_manifest(self._lock_catalog(), "demo", "full", [("fix1", ["lef"])])

        self.assertEqual(legacy["components"][0]["snapshot_digest"], "legacy-full")
        self.assertEqual(legacy["components"][0]["identity_source"], "legacy_input_fingerprint")
        self.assertEqual(legacy["identity_status"], "LEGACY_FALLBACK")
        self.assertEqual(missing["components"][1]["identity_source"], "missing_evidence")
        self.assertEqual(missing["components"][1]["evidence_strength"], "unavailable")
        self.assertEqual(missing["identity_status"], "UNAVAILABLE")

    def test_effective_manifest_validation_recomputes_full_identity_and_provenance(self) -> None:
        from lib_guard.effective.manifest import build_effective_manifest, validate_effective_manifest

        manifest = build_effective_manifest(
            self._lock_catalog(snapshots={"full": "sha256:full", "fix1": "sha256:fix1"}),
            "demo",
            "full",
            [("fix1", ["lef"])],
        )
        self.assertEqual(validate_effective_manifest(manifest)["integrity_status"], "MATCH")

        tampered_payload = json.loads(json.dumps(manifest))
        tampered_payload["identity"]["payload"]["resolver_version"] = "effective.tampered"
        self.assertEqual(validate_effective_manifest(tampered_payload)["integrity_status"], "MISMATCH")

        tampered_schema = json.loads(json.dumps(manifest))
        tampered_schema["identity"]["schema_version"] = "effective_identity.tampered"
        self.assertEqual(validate_effective_manifest(tampered_schema)["integrity_status"], "MISMATCH")

        tampered_provenance = json.loads(json.dumps(manifest))
        tampered_provenance["identity_status"] = "UNAVAILABLE"
        self.assertEqual(validate_effective_manifest(tampered_provenance)["integrity_status"], "MISMATCH")

        tampered_component_provenance = json.loads(json.dumps(manifest))
        tampered_component_provenance["components"][1]["identity_source"] = "missing_evidence"
        self.assertEqual(validate_effective_manifest(tampered_component_provenance)["integrity_status"], "MISMATCH")

    def test_effective_manifest_validator_rejects_malformed_component_sequences(self) -> None:
        from lib_guard.effective.manifest import build_effective_manifest, validate_effective_manifest

        manifest = build_effective_manifest(
            self._lock_catalog(snapshots={"full": "sha256:full", "fix1": "sha256:fix1"}),
            "demo",
            "full",
            [("fix1", ["lef"])],
            effective_id="E1",
        )
        for components in ({"not": "a sequence"}, ["not a mapping"]):
            with self.subTest(components=components):
                malformed = json.loads(json.dumps(manifest))
                malformed["components"] = components
                validation = validate_effective_manifest(malformed)
                self.assertFalse(validation["valid"])
                self.assertEqual(validation["integrity_status"], "MISMATCH")

    def test_pointer_and_approval_bind_effective_digest_and_detect_mismatch(self) -> None:
        from lib_guard.effective.manifest import build_effective_manifest
        from lib_guard.effective.pointer import load_current_pointer, write_current_pointer
        from lib_guard.window.cli import _validate_accept_compare, _validate_review_approval, _write_review_approval

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            effective_dir = root / "libraries" / "ip_demo" / "effective" / "E1"
            effective_dir.mkdir(parents=True)
            manifest_path = effective_dir / "effective_manifest.json"
            manifest = build_effective_manifest(
                self._lock_catalog(snapshots={"full": "sha256:full", "fix1": "sha256:fix1"}),
                "demo",
                "full",
                [("fix1", ["lef"])],
                effective_id="E1",
            )
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            pointer_path = write_current_pointer(manifest_path)
            pointer = load_current_pointer(root, "ip/demo")
            self.assertEqual(pointer["effective_digest"], manifest["identity"]["digest"])
            self.assertEqual(pointer["effective_identity_status"], "MATCH")

            compare_dir = root / "compare"
            compare_dir.mkdir()
            compare_manifest = compare_dir / "compare_manifest.json"
            compare_manifest.write_text(
                json.dumps(
                    {
                        "old_target": {"spec": "effective:E0"},
                        "new_target": {
                            "spec": "effective:E1",
                            "effective_digest": manifest["identity"]["digest"],
                        },
                    }
                ),
                encoding="utf-8",
            )
            window = {
                "library": "demo",
                "base_effective": {"target": "effective:E0"},
                "candidate_effective": {"effective_id": "E1", "manifest": str(manifest_path)},
                "compare": {"old": "effective:E0", "new": "effective:E1"},
            }
            approval_path, _ = _write_review_approval(
                window=window,
                manifest_path=manifest_path,
                compare_manifest_path=compare_manifest,
                accepted_by="owner",
                note="reviewed",
            )
            approval = json.loads(approval_path.read_text(encoding="utf-8"))
            self.assertEqual(approval["candidate_effective_digest"], manifest["identity"]["digest"])
            approval["candidate_effective_digest"] = "sha256:wrong"
            approval_path.write_text(json.dumps(approval), encoding="utf-8")
            window["review_approval"] = str(approval_path)
            with self.assertRaisesRegex(ValueError, "approval effective digest"):
                _validate_review_approval(window, manifest["identity"]["digest"])

            pointer_data = json.loads(pointer_path.read_text(encoding="utf-8"))
            pointer_data["effective_digest"] = "sha256:wrong"
            pointer_path.write_text(json.dumps(pointer_data), encoding="utf-8")
            self.assertEqual(load_current_pointer(root, "ip/demo")["effective_identity_status"], "MISMATCH")

            compare_manifest.write_text(
                json.dumps(
                    {
                        "old_target": {"spec": "effective:E0"},
                        "new_target": {"spec": "effective:E1", "effective_digest": "sha256:wrong"},
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "effective digest changed after compare"):
                _validate_accept_compare(window, compare_manifest)

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
            self.assertIn("RTL/top.v", preview["release_files"])
            self.assertTrue(preview["release_files"]["RTL/top.v"]["release_path"].endswith("/release_area/RTL/top.v"))
            self.assertNotIn("/ucie/R_LONG_20260624/", preview["release_files"]["RTL/top.v"]["release_path"])
            self.assertTrue((preview_dir / "release_delta.json").exists())
            self.assertTrue((preview_dir / "release_preview.csh").exists())
            self.assertIn("有效版组成", html)
            self.assertIn("来源版本证据", html)
            self.assertIn("parser_tasks", html)
            self.assertIn("相邻上一版", html)
            self.assertIn("发布变化预览", html)
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
            self.assertNotIn("report_index.json", index_html)
            self.assertIn("进入库工作台", index_html)
            self.assertNotIn("<iframe", index_html.lower())

            library_home = catalog_dir / "html" / "libraries" / "ip_ucie" / "index.html"
            self.assertTrue(library_home.exists())
            library_html = library_home.read_text(encoding="utf-8")
            self.assertIn("库入口", library_html)
            self.assertIn("当前有效版", library_html)
            self.assertIn("最新待审版", library_html)
            self.assertNotIn("Current Effective Detail", library_html)
            self.assertNotIn("Version Evidence", library_html)
            self.assertNotIn("历史对比记录", library_html)
            self.assertNotIn("Compare 索引", library_html)
            self.assertIn("正式发布", library_html)
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
            self.assertIn("对比审查报告", compare_html)
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
            self.assertIn("库入口", library_html)
            self.assertIn("历史版本", library_html)
            self.assertNotIn("E2_vs_E3", library_html)
            self.assertNotIn("打开报告", library_html)
            self.assertNotIn("<iframe", library_html.lower())

    def test_timeline_keeps_generated_effective_as_candidate_until_current_pointer_exists(self) -> None:
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
            self.assertEqual(lib_entry["latest_effective_ref"], "")
            self.assertEqual(lib_entry["current_effective"], "")

            nodes = {node["version_id"]: node for node in lib_entry["timeline"]}
            self.assertEqual(nodes[full.name]["node_kind"], "raw")
            self.assertEqual(nodes[full.name]["package_type"], "full")
            self.assertEqual(nodes[full.name]["usage_status"], "usable")
            self.assertEqual(nodes[patch.name]["package_type"], "partial")
            self.assertEqual(nodes[patch.name]["usage_status"], "accepted")
            self.assertEqual(nodes["effective_20260624"]["node_kind"], "effective")
            self.assertEqual(nodes["effective_20260624"]["package_type"], "composed")
            self.assertNotEqual(nodes["effective_20260624"]["usage_status"], "current")

            library_html = (html_dir / "libraries" / "ip_ucie" / "index.html").read_text(encoding="utf-8")
            self.assertIn("当前有效版", library_html)
            self.assertIn("库入口", library_html)
            self.assertNotIn("Current Effective Detail", library_html)
            self.assertNotIn("Current raw", library_html)
            self.assertNotIn("Version Evidence", library_html)
            self.assertNotIn("Scan HTML", library_html)
            self.assertNotIn("Diff HTML", library_html)


if __name__ == "__main__":
    unittest.main()
