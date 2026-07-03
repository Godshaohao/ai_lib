from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


class ReleaseForceManifestTest(unittest.TestCase):
    def _write_manifest(self, path: Path, release_root: Path, source: Path) -> None:
        manifest = {
            "schema_version": "1.0",
            "release_id": "PD_FORCE_RELEASE",
            "alias": "current",
            "release_root": str(release_root),
            "libraries": [
                {
                    "library_type": "ip",
                    "library_name": "ucie",
                    "version_id": "stable_20260702",
                    "version_key": "ip/ucie/stable_20260702",
                    "source_path": str(source),
                }
            ],
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    def _read_json(self, path: Path) -> dict:
        return json.loads(path.read_text(encoding="utf-8"))

    def _assert_force_audit_fields(self, data: dict, override_path: Path) -> None:
        self.assertTrue(data["force"])
        self.assertEqual(data["force_reason"], "owner accepted")
        self.assertEqual(data["force_by"], "shenhao")
        self.assertEqual(data["override_path"], str(override_path))

    def test_force_requires_reason(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            source = base / "raw" / "ucie"
            source.mkdir(parents=True)
            manifest_path = base / "release_runs" / "PD_FORCE_RELEASE" / "release_manifest.json"
            self._write_manifest(manifest_path, base / "release_area", source)

            from lib_guard.release.linker import link_release_from_manifest

            with self.assertRaisesRegex(ValueError, "force release requires --force-reason"):
                link_release_from_manifest(manifest_path, force=True)

    def test_force_dry_run_writes_override_without_copying_files(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            source = base / "raw" / "ucie"
            release_root = base / "release_area"
            run_dir = base / "release_runs" / "PD_FORCE_RELEASE"
            manifest_path = run_dir / "release_manifest.json"
            (source / "rtl").mkdir(parents=True)
            (source / "rtl" / "top.v").write_text("module top; endmodule\n", encoding="utf-8")
            self._write_manifest(manifest_path, release_root, source)

            from lib_guard.release.linker import link_release_from_manifest

            result = link_release_from_manifest(
                manifest_path,
                force=True,
                force_reason="owner accepted",
                force_by="shenhao",
                verify_skipped=True,
                verify_skip_reason="no_verify requested",
            )

            override_path = run_dir / "release_override.json"
            self.assertEqual(result["status"], "FORCE_DRY_RUN")
            self.assertTrue(override_path.exists())
            self.assertFalse((release_root / "rtl" / "top.v").exists())
            self._assert_force_audit_fields(result, override_path)

            override = self._read_json(override_path)
            self.assertEqual(override["schema_version"], "release_override.v1")
            self.assertTrue(override["force"])
            summary = override["bypassed_gate_summary"]
            self.assertEqual(summary["review_gate_status"], "NOT_PROVIDED")
            self.assertEqual(summary["release_check_status"], "NOT_PROVIDED")
            self.assertEqual(summary["blocking_open"], 0)
            self.assertEqual(summary["block_reasons"], [])
            self.assertTrue(override["selected_versions"])

            link_result = self._read_json(run_dir / "release_link_result.json")
            release_result = self._read_json(run_dir / "release_result.json")
            self._assert_force_audit_fields(link_result, override_path)
            self._assert_force_audit_fields(release_result, override_path)
            self.assertTrue(release_result["verify_skipped"])
            self.assertEqual(release_result["verify_skip_reason"], "no_verify requested")

    def test_force_apply_success_is_forced_applied(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            source = base / "raw" / "ucie"
            release_root = base / "release_area"
            run_dir = base / "release_runs" / "PD_FORCE_RELEASE"
            manifest_path = run_dir / "release_manifest.json"
            (source / "rtl").mkdir(parents=True)
            (source / "rtl" / "top.v").write_text("module top; endmodule\n", encoding="utf-8")
            self._write_manifest(manifest_path, release_root, source)

            from lib_guard.release.linker import link_release_from_manifest

            result = link_release_from_manifest(
                manifest_path,
                apply=True,
                mode="copy",
                force=True,
                force_reason="owner accepted",
                force_by="shenhao",
            )

            override_path = run_dir / "release_override.json"
            self.assertEqual(result["status"], "FORCED_APPLIED")
            self.assertTrue((release_root / "rtl" / "top.v").exists())
            self._assert_force_audit_fields(result, override_path)
            release_result = self._read_json(run_dir / "release_result.json")
            self._assert_force_audit_fields(release_result, override_path)

    def test_force_apply_missing_source_records_force_failure(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            release_root = base / "release_area"
            run_dir = base / "release_runs" / "PD_FORCE_RELEASE"
            manifest_path = run_dir / "release_manifest.json"
            self._write_manifest(manifest_path, release_root, base / "raw" / "missing")

            from lib_guard.release.linker import link_release_from_manifest

            result = link_release_from_manifest(
                manifest_path,
                apply=True,
                mode="copy",
                force=True,
                force_reason="owner accepted",
                force_by="shenhao",
            )

            self.assertEqual(result["status"], "FORCE_FAILED")
            self.assertTrue(result["failed_links"])
            link_result = self._read_json(run_dir / "release_link_result.json")
            self.assertEqual(link_result["status"], "FORCE_FAILED")

    def test_force_bad_gate_json_keeps_override_summary_not_provided(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            source = base / "raw" / "ucie"
            release_root = base / "release_area"
            run_dir = base / "release_runs" / "PD_FORCE_RELEASE"
            manifest_path = run_dir / "release_manifest.json"
            review_gate_path = run_dir / "bad_review_gate.json"
            release_check_path = run_dir / "bad_release_check.json"
            run_dir.mkdir(parents=True)
            source.mkdir(parents=True)
            (source / "top.v").write_text("module top; endmodule\n", encoding="utf-8")
            review_gate_path.write_text("{bad json", encoding="utf-8")
            release_check_path.write_text("{bad json", encoding="utf-8")
            self._write_manifest(manifest_path, release_root, source)

            from lib_guard.release.linker import link_release_from_manifest

            result = link_release_from_manifest(
                manifest_path,
                force=True,
                force_reason="owner accepted",
                review_gate_path=review_gate_path,
                release_check_path=release_check_path,
            )

            self.assertEqual(result["status"], "FORCE_DRY_RUN")
            override = self._read_json(run_dir / "release_override.json")
            summary = override["bypassed_gate_summary"]
            self.assertEqual(summary["review_gate_status"], "NOT_PROVIDED")
            self.assertEqual(summary["release_check_status"], "NOT_PROVIDED")
            self.assertEqual(summary["blocking_open"], 0)
            self.assertEqual(summary["block_reasons"], [])


if __name__ == "__main__":
    unittest.main()
