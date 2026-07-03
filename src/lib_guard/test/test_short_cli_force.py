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


if __name__ == "__main__":
    unittest.main()
