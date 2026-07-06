from __future__ import annotations

import contextlib
import io
import json
import os
import tempfile
import unittest
from argparse import Namespace
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
        self.assertIn("{init,scan,cat,library,cmp,fd,rel,action,intake,window,accept-window,mark,rv}", help_text)
        for name in ["init", "library", "cat", "scan", "cmp", "fd", "rv", "rel", "action", "intake", "window", "accept-window", "mark"]:
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
            self.assertIn("--base-source", commands[-1])
            self.assertEqual(commands[-1][commands[-1].index("--base-source") + 1], "previous_effective")

    def test_cat_default_only_renders_existing_catalog(self) -> None:
        td, workspace = self._workspace()
        with td:
            from lib_guard.short_cli import build_cli_commands

            commands = build_cli_commands(["cat", "ucie"], cwd=workspace)

            self.assertEqual(len(commands), 1)
            command = commands[0]
            self.assertEqual(command[:2], ["catalog", "render"])
            self.assertIn("--library", command)
            self.assertEqual(command[command.index("--library") + 1], "ucie")
            self.assertNotIn("refresh", command)

    def test_cat_refresh_catalog_is_explicit_catalog_rebuild(self) -> None:
        td, workspace = self._workspace()
        with td:
            from lib_guard.short_cli import build_cli_commands

            commands = build_cli_commands(["cat", "ucie", "--refresh-catalog"], cwd=workspace)

            self.assertEqual(len(commands), 1)
            command = commands[0]
            self.assertEqual(command[:2], ["catalog", "refresh"])
            self.assertIn("--library", command)
            self.assertEqual(command[command.index("--library") + 1], "ucie")
            self.assertIn("--fast", command)

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

    def test_library_list_before_catalog_exists_points_to_cat_bootstrap(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            workspace = Path(td)
            raw = workspace / "raw"
            raw.mkdir()
            from lib_guard.short_cli import main, write_default_config

            write_default_config(workspace, raw_root=raw)

            old_cwd = Path.cwd()
            stderr = io.StringIO()
            try:
                os.chdir(workspace)
                with contextlib.redirect_stderr(stderr):
                    code = main(["library", "list"])
            finally:
                os.chdir(old_cwd)
            self.assertEqual(code, 2)
            error = stderr.getvalue()
            self.assertIn("catalog 尚未生成", error)
            self.assertIn("lg.csh library add <LIBRARY> --root <ROOT> --apply --refresh-catalog", error)
            self.assertIn("lg.csh cat --refresh-catalog", error)
            self.assertNotIn("lg.ps1 scan", error)
            self.assertNotIn("Traceback", error)

    def test_library_add_apply_prints_next_catalog_refresh_step(self) -> None:
        td, workspace = self._workspace()
        with td:
            from lib_guard.short_cli import main

            new_root = workspace / "raw" / "newlib"
            (new_root / "20260701_full").mkdir(parents=True)
            (new_root / "20260701_full" / "top.v").write_text("module top; endmodule\n", encoding="utf-8")

            old_cwd = Path.cwd()
            stderr = io.StringIO()
            try:
                os.chdir(workspace)
                with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(stderr):
                    code = main(["library", "add", "newlib", "--root", str(new_root), "--apply"])
            finally:
                os.chdir(old_cwd)
            self.assertEqual(code, 0)
            message = stderr.getvalue()
            self.assertIn("[NEXT]", message)
            self.assertIn("lg cat newlib --refresh-catalog", message)
            self.assertNotIn("--with-evidence", message)

    def test_library_add_apply_refresh_catalog_chains_registry_apply_and_local_catalog_refresh(self) -> None:
        td, workspace = self._workspace()
        with td:
            from lib_guard.short_cli import build_cli_commands

            new_root = workspace / "raw" / "newlib"
            new_root.mkdir(parents=True)

            commands = build_cli_commands(
                [
                    "library",
                    "add",
                    "newlib",
                    "--root",
                    str(new_root),
                    "--apply",
                    "--refresh-catalog",
                ],
                cwd=workspace,
            )

            self.assertEqual([cmd[:2] for cmd in commands], [["library", "add"], ["library", "apply"], ["catalog", "refresh"]])
            refresh = commands[-1]
            self.assertIn("--library", refresh)
            self.assertEqual(refresh[refresh.index("--library") + 1], "newlib")
            self.assertIn("--fast", refresh)
            self.assertNotIn("--with-evidence", refresh)

    def test_library_list_plain_is_copyable_and_short_cli_expands_it(self) -> None:
        td, workspace = self._workspace()
        with td:
            from lib_guard.cli_commands.catalog import run_catalog_list
            from lib_guard.short_cli import build_cli_commands, main

            command = build_cli_commands(["library", "list", "--plain"], cwd=workspace)[0]
            self.assertEqual(command[:2], ["catalog", "list"])
            self.assertIn("--plain", command)

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                code = run_catalog_list(
                    Namespace(
                        catalog=str(workspace / "catalog" / "catalog.json"),
                        library=None,
                        versions=False,
                        plain=True,
                        effective=False,
                        html_out=None,
                    )
                )
            self.assertEqual(code, 0)
            self.assertEqual(stdout.getvalue().strip(), "ucie")

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                code = run_catalog_list(
                    Namespace(
                        catalog=str(workspace / "catalog" / "catalog.json"),
                        library="ucie",
                        versions=True,
                        plain=True,
                        effective=False,
                        html_out=None,
                    )
            )
            self.assertEqual(code, 0)
            self.assertEqual(stdout.getvalue().splitlines(), ["base", "patch"])

            old_cwd = Path.cwd()
            stdout = io.StringIO()
            try:
                os.chdir(workspace)
                with contextlib.redirect_stdout(stdout):
                    code = main(["library", "list", "--plain"])
            finally:
                os.chdir(old_cwd)
            self.assertEqual(code, 0)
            self.assertEqual(stdout.getvalue().strip(), "ucie")
            self.assertNotIn("python -m lib_guard.cli", stdout.getvalue())

    def test_csh_completion_script_is_documented_static_helper(self) -> None:
        root = Path(__file__).resolve().parents[3]
        script = root / "scripts" / "lg_complete.csh"

        self.assertTrue(script.exists())
        text = script.read_text(encoding="utf-8")
        self.assertIn("alias lg", text)
        self.assertIn("complete $_lg_complete_name", text)
        self.assertIn("init scan cat library cmp fd rel action intake window accept-window mark rv", text)
        self.assertIn("lg library list --plain", text)
        self.assertIn("lg library list <LIBRARY> --versions --plain", text)

    def test_explicit_config_load_keeps_workspace_relative_paths_single_rooted(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            workspace = root / "work" / "demo"
            raw = root / "raw"
            raw.mkdir(parents=True)

            from lib_guard.short_cli import _load_config, write_default_config

            old_cwd = Path.cwd()
            try:
                os.chdir(root)
                config = write_default_config(workspace.relative_to(root), raw_root=raw.relative_to(root))
            finally:
                os.chdir(old_cwd)
            cfg = _load_config(root, str(config))

            self.assertEqual(cfg["workspace"], str(workspace.resolve()))
            self.assertEqual(cfg["library_registry"], str((workspace / "config" / "library_registry.tsv").resolve()))
            self.assertEqual(cfg["catalog"], str((workspace / "catalog" / "catalog.json").resolve()))
            self.assertEqual(cfg["raw_root"], str(raw.resolve()))
            for key in ["library_registry", "catalog", "catalog_html"]:
                self.assertNotIn("work/demo/work/demo", cfg[key])


if __name__ == "__main__":
    unittest.main()
