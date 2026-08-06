from __future__ import annotations

import json
import sys
import tempfile
import unittest
from argparse import Namespace
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


class ReleaseManifestFlowTest(unittest.TestCase):
    def _write_effective_release_fixture(
        self,
        root: Path,
        *,
        accepted: bool,
        evidence_version_id: str | None = None,
        include_release_note: bool = True,
    ) -> tuple[Path, Path]:
        from types import SimpleNamespace

        from lib_guard.effective.manifest import build_effective_manifest
        from lib_guard.effective.pointer import sha256_file, write_current_pointer
        from lib_guard.scan.scanner import ScanRunner

        raw = root / "raw" / "demo" / "full"
        raw.mkdir(parents=True)
        (raw / "top.v").write_text("module top; endmodule\n", encoding="utf-8")
        (raw / "README.md").write_text("demo library\n", encoding="utf-8")
        if include_release_note:
            (raw / "release_note.txt").write_text("initial release\n", encoding="utf-8")
        scan_dir = root / "scan" / "demo" / "full"
        ScanRunner(
            SimpleNamespace(
                root_path=str(raw),
                out_dir=str(scan_dir),
                library_type="ip",
                library_name="demo",
                version="full",
                scan_mode="signature",
                scan_id="SIGNATURE_full",
                state_dir=str(root / "state"),
                cache_dir=str(root / "cache"),
                skip_cache=True,
                no_cache=True,
                no_progress=True,
                progress_interval=1,
                parse_jobs=1,
                parse_file_types=None,
                tool_version="test",
                schema_version="1.0",
            )
        ).run()
        scan_meta = json.loads((scan_dir / "scan_meta.json").read_text(encoding="utf-8"))
        catalog_data = {
            "libraries": [
                {
                    "library_id": "ip/demo",
                    "library_name": "demo",
                    "versions": [
                        {
                            "version_id": "full",
                            "raw_path": str(raw),
                            "scan": {
                                "status": scan_meta["status"],
                                "scan_dir": str(scan_dir),
                                "scan_mode": scan_meta["scan_mode"],
                                "snapshot_identity": scan_meta["snapshot_identity"],
                            },
                        }
                    ],
                }
            ]
        }
        catalog_path = root / "catalog" / "catalog.json"
        catalog_path.parent.mkdir(parents=True)
        catalog_path.write_text(json.dumps(catalog_data), encoding="utf-8")

        effective_dir = root / "catalog" / "html" / "libraries" / "ip_demo" / "effective" / "E1"
        effective_dir.mkdir(parents=True)
        manifest_path = effective_dir / "effective_manifest.json"
        manifest = build_effective_manifest(catalog_data, "demo", "full", [], effective_id="E1")
        manifest["library_type"] = "ip"
        if evidence_version_id is not None:
            manifest["version_evidence"]["components"][0]["version_id"] = evidence_version_id
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

        if accepted:
            compare_manifest = root / "compare" / "compare_manifest.json"
            compare_manifest.parent.mkdir(parents=True)
            compare_manifest.write_text(
                json.dumps({"old_target": {"spec": "none"}, "new_target": {"spec": "effective:E1"}}),
                encoding="utf-8",
            )
            approval_path = effective_dir / "review_approval.json"
            approval_path.write_text(
                json.dumps(
                    {
                        "candidate_effective_manifest": str(manifest_path.resolve()),
                        "candidate_effective_sha256": sha256_file(manifest_path),
                        "candidate_effective_digest": manifest["identity"]["digest"],
                        "compare_manifest": str(compare_manifest.resolve()),
                        "compare_manifest_sha256": sha256_file(compare_manifest),
                    }
                ),
                encoding="utf-8",
            )
            write_current_pointer(
                manifest_path,
                review_approval=approval_path,
                approval_sha256=sha256_file(approval_path),
                accepted_by="owner",
                note="review passed",
            )
        return catalog_path, manifest_path

    @staticmethod
    def _effective_release_args(root: Path, catalog: Path, manifest: Path) -> Namespace:
        return Namespace(
            catalog=str(catalog),
            library="demo",
            version=[],
            stage=None,
            policy=None,
            release_root=str(root / "release"),
            alias="current",
            release_id="R_EFFECTIVE",
            out=str(root / "release_run"),
            apply=False,
            overwrite=False,
            link_mode="symlink",
            force=False,
            force_reason=None,
            force_by=None,
            diff=None,
            diff_mode=None,
            only_checked=False,
            only_ready=False,
            limit=None,
            no_verify=True,
            no_render=True,
            catalog_html_out=None,
            no_catalog_render=True,
            effective_manifest=str(manifest),
        )

    def test_effective_release_batch_blocks_manifest_without_accepted_pointer(self) -> None:
        from lib_guard.cli_commands.catalog import run_catalog_release_batch

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            catalog, manifest = self._write_effective_release_fixture(root, accepted=False)
            args = self._effective_release_args(root, catalog, manifest)

            with patch(
                "lib_guard.release.linker.link_release_from_manifest",
                return_value={"status": "DRY_RUN", "failed_links": []},
            ) as link_release:
                with redirect_stdout(StringIO()):
                    code = run_catalog_release_batch(args)

            self.assertEqual(code, 2)
            link_release.assert_not_called()
            check = json.loads((root / "release_run" / "release_check.json").read_text(encoding="utf-8"))
            self.assertEqual(check["release_check_status"], "BLOCK")
            self.assertIn("effective_pointer", {item["category"] for item in check["issues"]})
            release_result = json.loads((root / "release_run" / "release_result.json").read_text(encoding="utf-8"))
            self.assertEqual(release_result["effective_digest"], check["effective_digest"])

    def test_effective_release_batch_rejects_scan_evidence_for_another_component(self) -> None:
        from lib_guard.cli_commands.catalog import run_catalog_release_batch

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            catalog, manifest = self._write_effective_release_fixture(
                root,
                accepted=True,
                evidence_version_id="../../unrelated",
            )
            args = self._effective_release_args(root, catalog, manifest)

            with patch(
                "lib_guard.release.linker.link_release_from_manifest",
                return_value={"status": "DRY_RUN", "failed_links": []},
            ) as link_release:
                with redirect_stdout(StringIO()):
                    code = run_catalog_release_batch(args)

            self.assertEqual(code, 2)
            link_release.assert_not_called()
            check = json.loads((root / "release_run" / "release_check.json").read_text(encoding="utf-8"))
            self.assertIn("component_identity", {item["category"] for item in check["issues"]})
            self.assertFalse((root / "unrelated" / "release_check.json").exists())

    def test_effective_release_batch_preserves_component_warning_status(self) -> None:
        from lib_guard.cli_commands.catalog import run_catalog_release_batch

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            catalog, manifest = self._write_effective_release_fixture(
                root,
                accepted=True,
                include_release_note=False,
            )
            args = self._effective_release_args(root, catalog, manifest)

            with patch(
                "lib_guard.release.linker.link_release_from_manifest",
                return_value={"status": "DRY_RUN", "failed_links": []},
            ):
                with redirect_stdout(StringIO()):
                    code = run_catalog_release_batch(args)

            self.assertEqual(code, 0)
            check = json.loads((root / "release_run" / "release_check.json").read_text(encoding="utf-8"))
            self.assertEqual(check["release_check_status"], "PASS_WITH_WARNING")

    def test_effective_release_force_passes_bypassed_check_to_linker_audit(self) -> None:
        from lib_guard.cli_commands.catalog import run_catalog_release_batch

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            catalog, manifest = self._write_effective_release_fixture(root, accepted=False)
            args = self._effective_release_args(root, catalog, manifest)
            args.force = True
            args.force_reason = "release owner accepted missing pointer"
            args.force_by = "owner"

            with patch(
                "lib_guard.release.linker.link_release_from_manifest",
                return_value={"status": "FORCE_DRY_RUN", "failed_links": []},
            ) as link_release:
                with redirect_stdout(StringIO()):
                    code = run_catalog_release_batch(args)

            self.assertEqual(code, 0)
            self.assertEqual(
                link_release.call_args.kwargs["release_check_path"],
                str(root / "release_run" / "release_check.json"),
            )

    def test_effective_release_batch_allows_accepted_manifest_with_valid_scan_evidence(self) -> None:
        from lib_guard.cli_commands.catalog import run_catalog_release_batch

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            catalog, manifest = self._write_effective_release_fixture(root, accepted=True)
            args = self._effective_release_args(root, catalog, manifest)

            with patch(
                "lib_guard.release.linker.link_release_from_manifest",
                return_value={"status": "DRY_RUN", "failed_links": []},
            ) as link_release:
                with redirect_stdout(StringIO()):
                    code = run_catalog_release_batch(args)

            self.assertEqual(code, 0)
            link_release.assert_called_once()
            check = json.loads((root / "release_run" / "release_check.json").read_text(encoding="utf-8"))
            self.assertIn(check["release_check_status"], {"PASS", "PASS_WITH_WARNING"})
            self.assertEqual(check["effective_integrity_status"], "MATCH")
            self.assertEqual(check["approval_integrity_status"], "MATCH")
            release_result = json.loads((root / "release_run" / "release_result.json").read_text(encoding="utf-8"))
            self.assertEqual(release_result["check_status"], check["release_check_status"])
            self.assertEqual(release_result["release_check"], str(root / "release_run" / "release_check.json"))

    def test_effective_manifest_release_manifest_is_file_level_and_hashed(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "raw" / "full" / "lef" / "macro.lef"
            source.parent.mkdir(parents=True)
            source.write_text("MACRO U\nEND U\n", encoding="utf-8")
            effective_manifest = root / "effective_manifest.json"
            effective_manifest.write_text(
                json.dumps(
                    {
                        "schema_version": "effective_manifest.v2",
                        "effective_id": "E_full_fix",
                        "library_type": "ip",
                        "library_name": "ucie",
                        "base_full_version": "full",
                        "accepted_updates": ["fix"],
                        "effective_files": {
                            "lef/macro.lef": {
                                "source_path": str(source),
                                "source_version": "fix",
                                "operation": "replace",
                                "file_type": "lef",
                                "hash": "abc123",
                                "size_bytes": source.stat().st_size,
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            out = root / "release_run" / "release_manifest.json"

            from lib_guard.release.bundle import create_manifest_from_effective_manifest, iter_release_files

            manifest = create_manifest_from_effective_manifest(effective_manifest, out, release_root=root / "release")
            planned = iter_release_files(manifest)

            self.assertEqual(manifest["source_kind"], "current_effective")
            self.assertEqual(manifest["effective_id"], "E_full_fix")
            self.assertEqual(manifest["files"][0]["sha256"], "abc123")
            self.assertEqual(manifest["files"][0]["operation"], "replace")
            self.assertEqual(planned[0]["sha256"], "abc123")
            self.assertEqual(planned[0]["source_effective_id"], "E_full_fix")

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
            self.assertTrue(any(item["relative_path"] == "RTL/top.v" for item in dry["planned_files"]))
            self.assertTrue((run_dir / "release_link_result.json").exists())
            self.assertTrue((run_dir / "release_result.json").exists())
            dry_result = json.loads((run_dir / "release_result.json").read_text(encoding="utf-8"))
            self.assertEqual(dry_result["schema_version"], "release_result.v1")
            self.assertEqual(dry_result["status"], "READY")

            applied = link_release_from_manifest(manifest_path, apply=True, mode="copy")
            self.assertEqual(applied["status"], "APPLIED")
            applied_result = json.loads((run_dir / "release_result.json").read_text(encoding="utf-8"))
            self.assertEqual(applied_result["status"], "APPLIED")
            immutable_release = release_root / "releases" / "PD_LIB_CURRENT_20260618"
            self.assertTrue((immutable_release / "RTL" / "top.v").exists())
            self.assertTrue((immutable_release / "DOC" / "README.md").exists())
            self.assertTrue((immutable_release / "LEF" / "block.lef").exists())
            self.assertTrue((release_root / "current").is_symlink())
            self.assertEqual((release_root / "current").resolve(), immutable_release.resolve())
            self.assertFalse((release_root / "rtl").exists())
            self.assertFalse((release_root / "lef").exists())
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
            self.assertIn("发布结论", html)
            self.assertIn("库校验", html)
            self.assertIn("证据区", html)
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
            (release_root / "RTL").mkdir(parents=True)
            (release_root / "RTL" / "top.v").write_text("stale file\n", encoding="utf-8")
            (release_root / "LEF").mkdir(parents=True)
            (release_root / "LEF" / "extra.lef").write_text("extra\n", encoding="utf-8")
            (run_dir / "release_link_result.json").write_text(
                json.dumps(
                    {
                        "created_links": [
                            {
                                "library_name": "ucie",
                                "relative_path": "RTL/top.v",
                                "link_path": str(release_root / "RTL" / "top.v"),
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
            self.assertEqual(verified["status"], "FAILED")
            self.assertEqual(verified["summary"]["missing_files"], 1)
            self.assertEqual(verified["summary"]["extra_files"], 1)
            self.assertEqual(verified["summary"]["target_mismatch"], 1)
            severities = {item["category"]: item["severity"] for item in verified["issues"]}
            self.assertEqual(severities["missing_file"], "error")
            self.assertEqual(severities["target_mismatch"], "error")
            self.assertEqual(severities["extra_file"], "warning")
            categories = {item["category"] for item in verified["issues"]}
            self.assertIn("missing_file", categories)
            self.assertIn("extra_file", categories)
            self.assertIn("target_mismatch", categories)

    def test_manifest_apply_overwrite_replaces_targets_without_deleting_unlisted_files(self) -> None:
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
            old_release = release_root / "releases" / "old_release"
            (old_release / "RTL").mkdir(parents=True)
            (old_release / "RTL" / "new_top.v").write_text("old target\n", encoding="utf-8")
            (old_release / "RTL" / "old_top.v").write_text("keep me\n", encoding="utf-8")
            release_root.mkdir(parents=True, exist_ok=True)
            (release_root / "current").symlink_to(old_release)
            self._write_manifest(manifest_path, release_root, ucie, ddr)

            from lib_guard.release.linker import link_release_from_manifest

            result = link_release_from_manifest(manifest_path, apply=True, mode="copy", overwrite=True)
            self.assertEqual(result["status"], "APPLIED")
            self.assertTrue(Path(result["release_lock"]).exists())
            immutable_release = release_root / "releases" / "PD_LIB_CURRENT_20260618"
            self.assertEqual((immutable_release / "RTL" / "new_top.v").read_text(encoding="utf-8"), "module new_top; endmodule\n")
            self.assertTrue((immutable_release / "RTL" / "ddr.v").exists())
            self.assertFalse((immutable_release / "RTL" / "old_top.v").exists())
            self.assertEqual((old_release / "RTL" / "new_top.v").read_text(encoding="utf-8"), "old target\n")
            self.assertTrue((old_release / "RTL" / "old_top.v").exists())
            self.assertEqual((release_root / "current").resolve(), immutable_release.resolve())
            self.assertEqual(result["summary"]["removed_files"], 0)

    def test_manifest_release_failure_keeps_current_alias_and_immutable_release(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            ucie = base / "raw" / "ucie" / "stable_20260620"
            ddr = base / "raw" / "ddr" / "final_20260601"
            release_root = base / "release_area"
            run_dir = base / "release_runs" / "PD_LIB_CURRENT_20260620"
            manifest_path = run_dir / "release_manifest.json"
            (ucie / "rtl").mkdir(parents=True)
            ddr.mkdir(parents=True)
            (ucie / "rtl" / "top.v").write_text("module top; endmodule\n", encoding="utf-8")
            (ddr / "ddr.v").write_text("module ddr; endmodule\n", encoding="utf-8")
            old_release = release_root / "releases" / "old_release"
            (old_release / "RTL").mkdir(parents=True)
            (old_release / "RTL" / "top.v").write_text("old release\n", encoding="utf-8")
            release_root.mkdir(parents=True, exist_ok=True)
            (release_root / "current").symlink_to(old_release)
            current_before = (release_root / "current").resolve()
            self._write_manifest(manifest_path, release_root, ucie, ddr)
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["release_id"] = "broken"
            manifest["files"] = [
                {
                    "library_type": "ip",
                    "library_name": "ucie",
                    "version_id": "broken",
                    "source_path": str(base / "missing.lef"),
                    "target_relpath": "LEF/missing.lef",
                    "file_type": "lef",
                }
            ]
            manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

            from lib_guard.release.linker import link_release_from_manifest

            result = link_release_from_manifest(manifest_path, apply=True, mode="copy", overwrite=True)

            self.assertEqual(result["status"], "FAILED")
            self.assertEqual(current_before, (release_root / "current").resolve())
            self.assertEqual((old_release / "RTL" / "top.v").read_text(encoding="utf-8"), "old release\n")
            self.assertFalse((release_root / "releases" / "broken").exists())
            self.assertFalse((release_root / ".staging" / "broken").exists())
            self.assertFalse((release_root / "RTL").exists())

    def test_manifest_legacy_view_failure_keeps_previous_alias_and_release(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            source = base / "raw" / "ucie" / "new.v"
            source.parent.mkdir(parents=True)
            source.write_text("module new; endmodule\n", encoding="utf-8")
            release_root = base / "release_area"
            old_release = release_root / "releases" / "old_release"
            (old_release / "RTL").mkdir(parents=True)
            (old_release / "RTL" / "old.v").write_text("old release\n", encoding="utf-8")
            release_root.mkdir(parents=True, exist_ok=True)
            alias = release_root / "current"
            alias.symlink_to(old_release)
            legacy_view = release_root / "RTL"
            legacy_view.symlink_to(alias / "RTL", target_is_directory=True)
            old_alias_target = alias.resolve()
            old_legacy_target = legacy_view.readlink()
            manifest_path = base / "release_runs" / "new_release" / "release_manifest.json"
            manifest_path.parent.mkdir(parents=True)
            manifest_path.write_text(
                json.dumps(
                    {
                        "release_id": "new_release",
                        "alias": "current",
                        "release_root": str(release_root),
                        "files": [
                            {
                                "library_name": "ucie",
                                "version_id": "v2",
                                "source_path": str(source),
                                "target_relpath": "RTL/new.v",
                                "file_type": "verilog",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            from lib_guard.release.linker import link_release_from_manifest

            with patch("lib_guard.release.linker._publish_legacy_view_links", side_effect=RuntimeError("legacy view failed")):
                result = link_release_from_manifest(manifest_path, apply=True, mode="copy", overwrite=True)

            self.assertEqual(result["status"], "FAILED")
            self.assertEqual(alias.resolve(), old_alias_target)
            self.assertEqual(legacy_view.readlink(), old_legacy_target)
            self.assertEqual((old_release / "RTL" / "old.v").read_text(encoding="utf-8"), "old release\n")
            self.assertFalse((release_root / "releases" / "new_release").exists())
            self.assertFalse((release_root / ".staging" / "new_release").exists())

    def test_manifest_post_promotion_verify_failure_keeps_previous_alias_and_release(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            source = base / "raw" / "ucie" / "new.v"
            source.parent.mkdir(parents=True)
            source.write_text("module new; endmodule\n", encoding="utf-8")
            release_root = base / "release_area"
            old_release = release_root / "releases" / "old_release"
            old_release.mkdir(parents=True)
            (old_release / "sentinel.txt").write_text("keep\n", encoding="utf-8")
            release_root.mkdir(parents=True, exist_ok=True)
            alias = release_root / "current"
            alias.symlink_to(old_release)
            manifest_path = base / "release_runs" / "post_verify_failure" / "release_manifest.json"
            manifest_path.parent.mkdir(parents=True)
            manifest_path.write_text(
                json.dumps(
                    {
                        "release_id": "post_verify_failure",
                        "alias": "current",
                        "release_root": str(release_root),
                        "files": [
                            {
                                "library_name": "ucie",
                                "version_id": "v2",
                                "source_path": str(source),
                                "target_relpath": "RTL/new.v",
                                "file_type": "verilog",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            from lib_guard.release.linker import link_release_from_manifest

            with patch(
                "lib_guard.release.postcheck.verify_release_manifest",
                side_effect=[{"status": "PASS"}, RuntimeError("post-promotion verify failed")],
            ) as verify:
                result = link_release_from_manifest(manifest_path, apply=True, mode="copy", overwrite=True)

            self.assertEqual(result["status"], "FAILED")
            self.assertEqual(verify.call_count, 2)
            self.assertEqual(alias.resolve(), old_release.resolve())
            self.assertTrue((old_release / "sentinel.txt").exists())
            self.assertFalse((release_root / "releases" / "post_verify_failure").exists())
            self.assertFalse((release_root / ".staging" / "post_verify_failure").exists())

    def test_manifest_hash_failure_removes_only_staging(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            source = base / "raw" / "ucie" / "top.lef"
            source.parent.mkdir(parents=True)
            source.write_text("MACRO U\nEND U\n", encoding="utf-8")
            release_root = base / "release_area"
            old_release = release_root / "releases" / "old_release"
            old_release.mkdir(parents=True)
            (old_release / "sentinel.txt").write_text("keep\n", encoding="utf-8")
            release_root.mkdir(parents=True, exist_ok=True)
            (release_root / "current").symlink_to(old_release)
            run_dir = base / "release_runs" / "hash_broken"
            manifest_path = run_dir / "release_manifest.json"
            manifest = {
                "schema_version": "1.0",
                "release_id": "hash_broken",
                "alias": "current",
                "release_root": str(release_root),
                "files": [
                    {
                        "library_type": "ip",
                        "library_name": "ucie",
                        "version_id": "v1",
                        "source_path": str(source),
                        "target_relpath": "LEF/top.lef",
                        "file_type": "lef",
                        "sha256": "0" * 64,
                    }
                ],
            }
            run_dir.mkdir(parents=True)
            manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

            from lib_guard.release.linker import link_release_from_manifest

            result = link_release_from_manifest(manifest_path, apply=True, mode="symlink", overwrite=True)

            self.assertEqual(result["status"], "FAILED")
            self.assertIn("hash_mismatch", {item["category"] for item in result["verify"]["issues"]})
            self.assertEqual((release_root / "current").resolve(), old_release.resolve())
            self.assertTrue((old_release / "sentinel.txt").exists())
            self.assertFalse((release_root / "releases" / "hash_broken").exists())
            self.assertFalse((release_root / ".staging" / "hash_broken").exists())

    def test_manifest_apply_cleans_stale_staging_before_build(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            source = base / "raw" / "ucie" / "top.v"
            source.parent.mkdir(parents=True)
            source.write_text("module top; endmodule\n", encoding="utf-8")
            release_root = base / "release_area"
            staging = release_root / ".staging" / "stale_release"
            staging.mkdir(parents=True)
            (staging / "stale.txt").write_text("must not publish\n", encoding="utf-8")
            manifest_path = base / "release_runs" / "stale_release" / "release_manifest.json"
            manifest_path.parent.mkdir(parents=True)
            manifest_path.write_text(
                json.dumps(
                    {
                        "release_id": "stale_release",
                        "alias": "current",
                        "release_root": str(release_root),
                        "files": [
                            {
                                "library_name": "ucie",
                                "version_id": "v1",
                                "source_path": str(source),
                                "target_relpath": "RTL/top.v",
                                "file_type": "verilog",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            from lib_guard.release.linker import link_release_from_manifest

            result = link_release_from_manifest(manifest_path, apply=True, mode="copy")

            self.assertEqual(result["status"], "APPLIED")
            immutable_release = release_root / "releases" / "stale_release"
            self.assertTrue((immutable_release / "RTL" / "top.v").exists())
            self.assertFalse((immutable_release / "stale.txt").exists())
            self.assertFalse(staging.exists())

    def test_manifest_apply_requires_migration_for_real_alias_directory(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            source = base / "raw" / "ucie" / "top.v"
            source.parent.mkdir(parents=True)
            source.write_text("module top; endmodule\n", encoding="utf-8")
            release_root = base / "release_area"
            alias = release_root / "current"
            alias.mkdir(parents=True)
            (alias / "legacy.txt").write_text("legacy\n", encoding="utf-8")
            manifest_path = base / "release_runs" / "migration" / "release_manifest.json"
            manifest_path.parent.mkdir(parents=True)
            manifest_path.write_text(
                json.dumps(
                    {
                        "release_id": "migration",
                        "alias": "current",
                        "release_root": str(release_root),
                        "files": [
                            {
                                "library_name": "ucie",
                                "version_id": "v1",
                                "source_path": str(source),
                                "target_relpath": "RTL/top.v",
                                "file_type": "verilog",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            from lib_guard.release.linker import link_release_from_manifest

            result = link_release_from_manifest(manifest_path, apply=True, mode="copy")

            self.assertEqual(result["status"], "MIGRATION_REQUIRED")
            self.assertTrue(alias.is_dir())
            self.assertTrue((alias / "legacy.txt").exists())
            self.assertFalse((release_root / "releases" / "migration").exists())

    def test_release_manifest_rejects_unknown_package_type(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            ucie = base / "raw" / "ucie" / "unknown_20260620"
            ddr = base / "raw" / "ddr" / "final_20260601"
            release_root = base / "release_area"
            manifest_path = base / "release_runs" / "PD_LIB_CURRENT_20260620" / "release_manifest.json"
            ucie.mkdir(parents=True)
            ddr.mkdir(parents=True)
            manifest = self._write_manifest(manifest_path, release_root, ucie, ddr)
            manifest["libraries"][0]["package_type"] = "UNKNOWN_PACKAGE"
            manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

            from lib_guard.release.bundle import load_release_manifest

            with self.assertRaisesRegex(ValueError, "unconfirmed package_type"):
                load_release_manifest(manifest_path)

    def test_manifest_mirror_release_root_removes_unlisted_files_only_when_explicit(self) -> None:
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
            old_release = release_root / "releases" / "old_release"
            (old_release / "RTL").mkdir(parents=True)
            (old_release / "RTL" / "old_top.v").write_text("remove me\n", encoding="utf-8")
            release_root.mkdir(parents=True, exist_ok=True)
            (release_root / "current").symlink_to(old_release)
            manifest = self._write_manifest(manifest_path, release_root, ucie, ddr)
            manifest["mirror_release_root"] = True
            manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

            from lib_guard.release.linker import link_release_from_manifest

            result = link_release_from_manifest(manifest_path, apply=True, mode="copy", overwrite=True)
            self.assertEqual(result["status"], "APPLIED")
            immutable_release = release_root / "releases" / "PD_LIB_CURRENT_20260618"
            self.assertTrue((immutable_release / "RTL" / "new_top.v").exists())
            self.assertTrue((immutable_release / "RTL" / "ddr.v").exists())
            self.assertFalse((immutable_release / "RTL" / "old_top.v").exists())
            self.assertTrue((old_release / "RTL" / "old_top.v").exists())
            self.assertEqual(result["summary"]["removed_files"], 0)

    def test_release_relative_path_strips_package_prefix_and_uses_uppercase_view_dir(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "raw" / "vendor_A" / "openroad_asap7" / "20260627_asap7"
            lef = root / "upstream_ae9a8ed9" / "lef" / "tech.lef"
            verilog = root / "upstream_ae9a8ed9" / "yoSys" / "cells.v"
            lef.parent.mkdir(parents=True)
            verilog.parent.mkdir(parents=True)
            lef.write_text("MACRO X\nEND X\n", encoding="utf-8")
            verilog.write_text("module cells; endmodule\n", encoding="utf-8")

            from lib_guard.release.bundle import release_relative_path

            self.assertEqual(release_relative_path(root, lef).as_posix(), "LEF/tech.lef")
            self.assertEqual(release_relative_path(root, verilog).as_posix(), "RTL/upstream_ae9a8ed9/yoSys/cells.v")

    def test_release_relpath_normalizes_common_view_aliases(self) -> None:
        from lib_guard.release.bundle import normalize_release_relpath

        cases = [
            ("source_package/lib/slow.lib", "liberty", "LIB/slow.lib"),
            ("source_package/spef/top.spef", "spef", "SPEF/top.spef"),
            ("source_package/db/top.db", "db", "DB/top.db"),
            ("source_package/gds/top.gds", "gds", "GDS/top.gds"),
            ("source_package/oas/top.oas", "oas", "OAS/top.oas"),
            ("source_package/tech/rules.lydrc", "tech_config", "TECH/rules.lydrc"),
            ("source_package/docs/release_note.md", "doc", "DOC/release_note.md"),
            ("misc/top.sv", "systemverilog", "RTL/misc/top.sv"),
        ]
        for relpath, file_type, expected in cases:
            with self.subTest(relpath=relpath, file_type=file_type):
                self.assertEqual(normalize_release_relpath(relpath, file_type=file_type).as_posix(), expected)

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
