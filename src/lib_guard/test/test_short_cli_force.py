from __future__ import annotations

import json
import tempfile
import unittest
import sys
from argparse import Namespace
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


class ShortCliForceTest(unittest.TestCase):
    def _write_catalog(self, root: Path) -> Path:
        raw = root / "raw" / "ucie" / "stable"
        scan = root / "work" / "scan_out" / "ucie" / "stable"
        raw.mkdir(parents=True)
        scan.mkdir(parents=True)
        (scan / "scan_meta.json").write_text(json.dumps({"root_path": str(raw)}), encoding="utf-8")
        catalog = root / "catalog" / "catalog.json"
        catalog.parent.mkdir(parents=True)
        catalog.write_text(
            json.dumps(
                {
                    "libraries": [
                        {
                            "library_id": "ip/ucie",
                            "library_name": "ucie",
                            "library_type": "ip",
                            "versions": [
                                {
                                    "version_id": "stable",
                                    "version_key": "ip/ucie/stable",
                                    "library_type": "ip",
                                    "library_name": "ucie",
                                    "raw_path": str(raw),
                                    "scan": {"status": "PASS", "scan_dir": str(scan)},
                                    "release": {"check_status": "PASS"},
                                }
                            ],
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        return catalog

    def test_short_cli_rel_expands_force_by(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            workspace = Path(td)
            catalog = self._write_catalog(workspace)

            from lib_guard.short_cli import build_cli_command, write_default_config

            write_default_config(workspace, raw_root=workspace / "raw")
            command = build_cli_command(
                [
                    "rel",
                    "ucie",
                    "stable",
                    "--force",
                    "--force-reason",
                    "owner accepted",
                    "--force-by",
                    "shenhao",
                ],
                cwd=workspace,
            )

            self.assertEqual(command[0], "release-batch")
            self.assertIn("--catalog", command)
            self.assertEqual(command[command.index("--catalog") + 1], str(catalog))
            self.assertIn("--force", command)
            self.assertEqual(command[command.index("--force-reason") + 1], "owner accepted")
            self.assertEqual(command[command.index("--force-by") + 1], "shenhao")
            self.assertIn("--policy", command)
            self.assertTrue(command[command.index("--policy") + 1].endswith("configs/release_policy.json"))

    def test_short_cli_rel_force_without_reason_fails_before_release_batch(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            workspace = Path(td)
            self._write_catalog(workspace)

            from lib_guard.short_cli import build_cli_command, write_default_config

            write_default_config(workspace, raw_root=workspace / "raw")
            with self.assertRaisesRegex(ValueError, "lg rel --force requires --force-reason"):
                build_cli_command(["rel", "ucie", "stable", "--apply", "--force"], cwd=workspace)

    def test_short_cli_rel_without_version_uses_current_effective_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            workspace = Path(td)
            self._write_catalog(workspace)
            effective_dir = workspace / "catalog" / "html" / "libraries" / "ip_ucie" / "effective" / "E1"
            effective_dir.mkdir(parents=True)
            manifest = effective_dir / "effective_manifest.json"
            manifest.write_text(json.dumps({"effective_id": "E1", "effective_files": {}}), encoding="utf-8")
            (effective_dir.parent / "current_effective.json").write_text(
                json.dumps({"current_effective_id": "E1", "manifest": str(manifest)}),
                encoding="utf-8",
            )

            from lib_guard.short_cli import build_cli_commands, write_default_config

            write_default_config(workspace, raw_root=workspace / "raw")
            commands = build_cli_commands(["rel", "ucie"], cwd=workspace)

            self.assertEqual(len(commands), 1)
            self.assertEqual(commands[0][0], "release-batch")
            self.assertIn("--effective-manifest", commands[0])
            self.assertEqual(commands[0][commands[0].index("--effective-manifest") + 1], str(manifest))
            self.assertNotIn("--version", commands[0])

    def test_short_cli_rel_force_is_reachable_without_precheck_command(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            workspace = Path(td)
            self._write_catalog(workspace)

            from lib_guard.short_cli import build_cli_commands, write_default_config

            write_default_config(workspace, raw_root=workspace / "raw")
            commands = build_cli_commands(
                [
                    "rel",
                    "ucie",
                    "stable",
                    "--apply",
                    "--force",
                    "--force-reason",
                    "owner accepted",
                    "--force-by",
                    "shenhao",
                ],
                cwd=workspace,
            )

            self.assertEqual(len(commands), 1)
            self.assertEqual(commands[0][0], "release-batch")
            self.assertIn("--force", commands[0])

    def test_release_batch_passes_force_audit_fields_to_manifest_linker(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            catalog = self._write_catalog(root)
            run_dir = root / "work" / "release_runs" / "FORCE_TEST"
            release_root = root / "release_area"
            args = Namespace(
                catalog=str(catalog),
                library="ucie",
                version=["stable"],
                stage=None,
                only_checked=False,
                only_ready=False,
                limit=None,
                release_id="FORCE_TEST",
                out=str(run_dir),
                release_root=str(release_root),
                alias="current",
                apply=True,
                overwrite=False,
                link_mode="copy",
                force=True,
                force_reason="owner accepted",
                force_by="shenhao",
                no_verify=True,
                no_render=True,
                catalog_html_out=None,
                no_catalog_render=True,
            )
            link_result = {
                "status": "FORCED_APPLIED",
                "release_dir": str(release_root),
                "release_root": str(release_root),
                "manifest_path": str(run_dir / "release_manifest.json"),
                "failed_links": [],
                "summary": {"planned_files": 1, "created_files": 1, "removed_files": 0, "failed_files": 0},
                "force": True,
                "force_reason": "owner accepted",
                "force_by": "shenhao",
                "override_path": str(run_dir / "release_override.json"),
                "verify_skipped": True,
                "verify_skip_reason": "no_verify requested",
            }

            from lib_guard.cli_commands.catalog import run_catalog_release_batch

            with patch("lib_guard.release.linker.link_release_from_manifest", return_value=link_result) as link_mock:
                with redirect_stdout(StringIO()):
                    code = run_catalog_release_batch(args)

            self.assertEqual(code, 0)
            kwargs = link_mock.call_args.kwargs
            self.assertTrue(kwargs["force"])
            self.assertEqual(kwargs["force_reason"], "owner accepted")
            self.assertEqual(kwargs["force_by"], "shenhao")
            self.assertTrue(kwargs["verify_skipped"])
            self.assertEqual(kwargs["verify_skip_reason"], "no_verify requested")

    def test_release_batch_postcheck_failure_controls_exit_code(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            catalog = self._write_catalog(root)
            run_dir = root / "work" / "release_runs" / "VERIFY_FAIL"
            release_root = root / "release_area"
            args = Namespace(
                catalog=str(catalog),
                library="ucie",
                version=["stable"],
                stage=None,
                only_checked=False,
                only_ready=False,
                limit=None,
                release_id="VERIFY_FAIL",
                out=str(run_dir),
                release_root=str(release_root),
                alias="current",
                apply=True,
                overwrite=False,
                link_mode="copy",
                force=False,
                force_reason=None,
                force_by=None,
                no_verify=False,
                no_render=True,
                catalog_html_out=None,
                no_catalog_render=True,
            )
            link_result = {
                "status": "APPLIED",
                "release_dir": str(release_root),
                "release_root": str(release_root),
                "manifest_path": str(run_dir / "release_manifest.json"),
                "failed_links": [],
                "summary": {"planned_files": 1, "created_files": 1, "removed_files": 0, "failed_files": 0},
            }
            verify_result = {
                "status": "FAILED",
                "postcheck_path": str(run_dir / "release_postcheck.json"),
                "summary": {"failed_files": 1},
                "issues": [{"level": "ERROR", "category": "hash_mismatch"}],
            }
            link_result["verify"] = verify_result

            from lib_guard.cli_commands.catalog import run_catalog_release_batch

            with patch("lib_guard.release.linker.link_release_from_manifest", return_value=link_result):
                with patch("lib_guard.release.postcheck.verify_release_manifest", side_effect=AssertionError("catalog must use linker transaction verification")):
                    stdout = StringIO()
                    with redirect_stdout(stdout):
                        code = run_catalog_release_batch(args)

            self.assertEqual(code, 2)
            output = json.loads(stdout.getvalue())
            self.assertEqual(output["status"], "FAILED")
            self.assertEqual(output["phase"], "postcheck")
            self.assertEqual(output["link_status"], "APPLIED")
            self.assertEqual(output["verify_status"], "FAILED")


if __name__ == "__main__":
    unittest.main()
