from __future__ import annotations

import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path


class ShortCliCommandSurfaceTest(unittest.TestCase):
    def _workspace(self) -> tuple[tempfile.TemporaryDirectory[str], Path]:
        td = tempfile.TemporaryDirectory()
        root = Path(td.name)
        catalog = root / "catalog" / "catalog.json"
        catalog.parent.mkdir(parents=True, exist_ok=True)
        catalog.write_text(
            json.dumps(
                {
                    "libraries": [
                        {
                            "library_id": "ip/ucie",
                            "library_type": "ip",
                            "library_name": "ucie",
                            "versions": [
                                {
                                    "version_key": "ip/ucie/base",
                                    "version_id": "base",
                                    "raw_path": str(root / "raw" / "ucie" / "base"),
                                },
                                {
                                    "version_key": "ip/ucie/patch",
                                    "version_id": "patch",
                                    "raw_path": str(root / "raw" / "ucie" / "patch"),
                                    "previous_effective_version": "base",
                                },
                            ],
                        }
                    ]
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        (root / "raw" / "ucie" / "base" / "lef").mkdir(parents=True)
        (root / "raw" / "ucie" / "patch" / "lef").mkdir(parents=True)
        (root / "raw" / "ucie" / "base" / "lef" / "ucie.lef").write_text("MACRO U\nEND U\n", encoding="utf-8")
        (root / "raw" / "ucie" / "patch" / "lef" / "ucie.lef").write_text("MACRO U\nEND U\n", encoding="utf-8")
        from lib_guard.short_cli import write_default_config

        write_default_config(root, raw_root=root / "raw")
        return td, root

    def test_help_only_promotes_recommended_daily_short_commands(self) -> None:
        from lib_guard.short_cli import main

        stdout = io.StringIO()
        with self.assertRaises(SystemExit) as cm, contextlib.redirect_stdout(stdout):
            main(["--help"])
        self.assertEqual(cm.exception.code, 0)
        help_text = stdout.getvalue()
        self.assertIn("{init,scan,cat,library,cmp,fd,rel,action,rv}", help_text)
        for name in ["init", "library", "cat", "scan", "cmp", "fd", "rv", "rel", "action"]:
            self.assertIn(name, help_text)
        for old_name in ["catalog,", "diff,", "file-diff", "release,", "override,", "refresh,", "rv-check", "rv-accept"]:
            self.assertNotIn(old_name, help_text)

    def test_cat_update_detail_replaces_refresh_as_visible_entry(self) -> None:
        td, workspace = self._workspace()
        with td:
            from lib_guard.short_cli import build_cli_commands

            commands = build_cli_commands(["cat", "ucie", "--update-detail"], cwd=workspace)
            self.assertEqual(commands[-1][0], "compare")
            self.assertIn("--base", commands[-1])
            self.assertEqual(commands[-1][commands[-1].index("--base") + 1], "base")

    def test_legacy_refresh_is_rewritten_to_cat_update_detail_for_compatibility(self) -> None:
        td, workspace = self._workspace()
        with td:
            from lib_guard.short_cli import build_cli_commands

            old_commands = build_cli_commands(["refresh", "ucie"], cwd=workspace)
            new_commands = build_cli_commands(["cat", "ucie", "--update-detail"], cwd=workspace)
            self.assertEqual(old_commands, new_commands)

    def test_rv_group_replaces_legacy_rv_dash_commands(self) -> None:
        td, workspace = self._workspace()
        with td:
            from lib_guard.short_cli import build_cli_commands

            new_command = build_cli_commands(["rv", "check", "ucie", "patch"], cwd=workspace)[0]
            old_command = build_cli_commands(["rv-check", "ucie", "patch"], cwd=workspace)[0]
            self.assertEqual(old_command, new_command)
            self.assertEqual(new_command[:2], ["review", "check"])

    def test_library_override_replaces_top_level_override(self) -> None:
        td, workspace = self._workspace()
        with td:
            from lib_guard.short_cli import build_cli_commands

            new_command = build_cli_commands(["library", "override", "ucie", "patch", "--base", "base"], cwd=workspace)[0]
            old_command = build_cli_commands(["override", "ucie", "patch", "--base", "base"], cwd=workspace)[0]
            self.assertEqual(old_command, new_command)
            self.assertEqual(new_command[:2], ["catalog", "override"])

    def test_scan_without_target_is_clean_user_error(self) -> None:
        td, workspace = self._workspace()
        with td:
            from lib_guard.short_cli import main

            old_cwd = Path.cwd()
            stderr = io.StringIO()
            try:
                os.chdir(workspace)
                with contextlib.redirect_stderr(stderr):
                    code = main(["scan"])
            finally:
                os.chdir(old_cwd)
            self.assertEqual(code, 2)
            self.assertIn("ERROR: lg scan requires <library> <version>", stderr.getvalue())
            self.assertNotIn("Traceback", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
