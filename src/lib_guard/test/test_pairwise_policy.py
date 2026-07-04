from __future__ import annotations

import contextlib
import io
import json
import shlex
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


class PairwisePolicyTest(unittest.TestCase):
    def _fd_workspace(self, root: Path, file_name: str = "top.v") -> Path:
        workspace = root / "work"
        raw = root / "raw"
        base_dir = raw / "ucie" / "base"
        patch_dir = raw / "ucie" / "patch"
        base_dir.mkdir(parents=True, exist_ok=True)
        patch_dir.mkdir(parents=True, exist_ok=True)
        (base_dir / file_name).write_text("module top; endmodule\n", encoding="utf-8")
        (patch_dir / file_name).write_text("module top; wire a; endmodule\n", encoding="utf-8")
        catalog = workspace / "catalog" / "catalog.json"
        catalog.parent.mkdir(parents=True, exist_ok=True)
        catalog.write_text(
            json.dumps(
                {
                    "libraries": [
                        {
                            "library_id": "ip/ucie",
                            "library_name": "ucie",
                            "versions": [
                                {"version_id": "base", "raw_path": str(base_dir)},
                                {
                                    "version_id": "patch",
                                    "raw_path": str(patch_dir),
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
        from lib_guard.short_cli import write_default_config

        write_default_config(workspace, raw_root=raw)
        return workspace

    def test_build_pairwise_diff_tasks_uses_default_file_diff_types_only(self) -> None:
        from lib_guard.diff.pairwise import build_pairwise_diff_tasks

        changed_types = [
            "lef",
            "cdl",
            "sdc",
            "verilog",
            "systemverilog",
            "liberty",
            "lib",
            "spef",
            "db",
            "gds",
            "oas",
            "layout",
            "milkyway",
            "ndm",
        ]
        expected_task_types = {"lef", "cdl", "sdc"}

        with tempfile.TemporaryDirectory() as td:
            old_scan = Path(td) / "old_scan"
            new_scan = Path(td) / "new_scan"
            old_scan.mkdir()
            new_scan.mkdir()
            (old_scan / "scan_meta.json").write_text(
                json.dumps({"library_name": "demo", "version": "base"}),
                encoding="utf-8",
            )
            (new_scan / "scan_meta.json").write_text(
                json.dumps({"library_name": "demo", "version": "new"}),
                encoding="utf-8",
            )
            file_diff = {
                "changed": [f"{file_type}/block.{file_type}" for file_type in changed_types],
                "_old_items": {},
                "_new_items": {},
            }
            for file_type in changed_types:
                relpath = f"{file_type}/block.{file_type}"
                file_diff["_old_items"][relpath] = {
                    "path": relpath,
                    "file_type": file_type,
                    "root_path": str(old_scan),
                }
                file_diff["_new_items"][relpath] = {
                    "path": relpath,
                    "file_type": file_type,
                    "root_path": str(new_scan),
                }

            tasks = build_pairwise_diff_tasks(
                old_scan,
                new_scan,
                file_diff,
                output_root=Path(td) / "pairwise",
            )

        task_types = [item["file_type"] for item in tasks["tasks"]]
        self.assertEqual(set(task_types), expected_task_types)
        self.assertEqual(len(task_types), len(expected_task_types))
        for item in tasks["tasks"]:
            self.assertNotIn("command", item)
            self.assertNotIn("low_level_command", item)
        for file_type in set(changed_types) - expected_task_types:
            self.assertNotIn(file_type, task_types)

    def test_default_pairwise_file_diff_types_match_project_defaults(self) -> None:
        from lib_guard.diff.pairwise import DEFAULT_PAIRWISE_FILE_DIFF_TYPES
        from lib_guard.project_config import DEFAULT_FILE_DIFF_TYPES

        self.assertEqual(DEFAULT_PAIRWISE_FILE_DIFF_TYPES, DEFAULT_FILE_DIFF_TYPES)

    def test_short_cli_file_diff_type_choices_include_expert_manual_types(self) -> None:
        from lib_guard.project_config import (
            BINARY_METADATA_ONLY_TYPES,
            DEFAULT_FILE_DIFF_TYPES,
            SUMMARY_ONLY_TYPES,
        )
        from lib_guard.short_cli import _build_parser

        parser = _build_parser()
        parser.parse_args(["fd", "ucie", "patch_20260628", "spice/top.sp", "--type", "spice"])
        parser.parse_args(["fd", "ucie", "patch_20260628", "touchstone/top.s2p", "--type", "touchstone"])
        parser.parse_args(["fd", "ucie", "patch_20260628", "rtl/top.v", "--type", "verilog"])

        file_diff_parser = next(
            action
            for action in parser._subparsers._group_actions[0].choices["fd"]._actions
            if action.dest == "type"
        )
        self.assertEqual(
            set(file_diff_parser.choices),
            DEFAULT_FILE_DIFF_TYPES | SUMMARY_ONLY_TYPES | BINARY_METADATA_ONLY_TYPES,
        )

    def test_summary_only_types_include_text_summary_lanes(self) -> None:
        from lib_guard.project_config import SUMMARY_ONLY_TYPES

        self.assertTrue(
            {"verilog", "systemverilog", "liberty", "lib", "spef"}.issubset(SUMMARY_ONLY_TYPES)
        )

    def test_binary_metadata_only_types_include_binary_metadata_lanes(self) -> None:
        from lib_guard.project_config import BINARY_METADATA_ONLY_TYPES

        self.assertTrue(
            {"db", "gds", "oas", "layout", "milkyway", "ndm"}.issubset(BINARY_METADATA_ONLY_TYPES)
        )

    def test_version_detail_report_reuses_project_config_policy_constants(self) -> None:
        from lib_guard.project_config import BINARY_METADATA_ONLY_TYPES, SUMMARY_ONLY_TYPES
        from lib_guard.render.version_detail_report import BINARY_METADATA_ONLY_TYPES as DETAIL_BINARY_TYPES
        from lib_guard.render.version_detail_report import SUMMARY_ONLY_TYPES as DETAIL_SUMMARY_TYPES

        self.assertEqual(DETAIL_SUMMARY_TYPES, SUMMARY_ONLY_TYPES)
        self.assertEqual(DETAIL_BINARY_TYPES, BINARY_METADATA_ONLY_TYPES)

    def test_comparison_review_reuses_default_file_diff_types(self) -> None:
        from lib_guard.project_config import DEFAULT_FILE_DIFF_TYPES
        from lib_guard.render.html_report import FILE_DIFF_TYPES

        self.assertEqual(FILE_DIFF_TYPES, DEFAULT_FILE_DIFF_TYPES)
        self.assertNotIn("verilog", FILE_DIFF_TYPES)
        self.assertNotIn("liberty", FILE_DIFF_TYPES)
        self.assertNotIn("spef", FILE_DIFF_TYPES)
        self.assertNotIn("db", FILE_DIFF_TYPES)

    def test_comparison_review_reuses_summary_and_binary_lanes(self) -> None:
        from lib_guard.project_config import BINARY_METADATA_ONLY_TYPES, SUMMARY_ONLY_TYPES
        from lib_guard.render.html_report import BINARY_METADATA_TYPES, COUNT_ONLY_TYPES

        self.assertEqual(BINARY_METADATA_TYPES, BINARY_METADATA_ONLY_TYPES)
        self.assertEqual(COUNT_ONLY_TYPES, SUMMARY_ONLY_TYPES | BINARY_METADATA_ONLY_TYPES)
        self.assertIn("systemverilog", COUNT_ONLY_TYPES)
        self.assertIn("ndm", BINARY_METADATA_TYPES)

    def test_fd_summary_only_without_force_large_fails_with_clear_message(self) -> None:
        from lib_guard.short_cli import build_cli_commands

        with tempfile.TemporaryDirectory() as td:
            workspace = self._fd_workspace(Path(td), "top.v")
            with self.assertRaises(ValueError) as cm:
                build_cli_commands(["fd", "ucie", "patch", "top.v", "--type", "verilog"], cwd=workspace)
        self.assertEqual(
            str(cm.exception),
            "verilog is summary-only; pass --force-large only for expert manual review.",
        )

    def test_fd_summary_only_with_force_large_generates_command(self) -> None:
        from lib_guard.short_cli import build_cli_commands

        with tempfile.TemporaryDirectory() as td:
            workspace = self._fd_workspace(Path(td), "top.v")
            commands = build_cli_commands(
                ["fd", "ucie", "patch", "top.v", "--type", "verilog", "--force-large"],
                cwd=workspace,
            )

        self.assertEqual(commands[0][0], "file-diff")
        self.assertEqual(commands[0][1], "verilog")
        self.assertIn("--manual-large-file-opt-in", commands[0])

    def test_fd_binary_metadata_only_without_force_large_fails_with_clear_message(self) -> None:
        from lib_guard.short_cli import build_cli_commands

        with tempfile.TemporaryDirectory() as td:
            workspace = self._fd_workspace(Path(td), "top.db")
            with self.assertRaises(ValueError) as cm:
                build_cli_commands(["fd", "ucie", "patch", "top.db", "--type", "db"], cwd=workspace)
        self.assertEqual(
            str(cm.exception),
            "db is metadata-only; pass --force-large only for expert manual review.",
        )

    def test_fd_binary_metadata_only_with_force_large_generates_command(self) -> None:
        from lib_guard.cli import build_parser
        from lib_guard.short_cli import build_cli_commands

        with tempfile.TemporaryDirectory() as td:
            workspace = self._fd_workspace(Path(td), "top.db")
            commands = build_cli_commands(
                ["fd", "ucie", "patch", "top.db", "--type", "db", "--force-large"],
                cwd=workspace,
            )

        self.assertEqual(commands[0][0], "file-diff")
        self.assertEqual(commands[0][1], "db")
        self.assertIn("--manual-large-file-opt-in", commands[0])
        build_parser().parse_args([item for item in commands[0] if item != "--manual-large-file-opt-in"])

    def test_pairwise_still_never_generates_force_large_tasks(self) -> None:
        from lib_guard.diff.pairwise import build_pairwise_diff_tasks

        changed_types = [
            "lef",
            "cdl",
            "sdc",
            "verilog",
            "systemverilog",
            "liberty",
            "lib",
            "spef",
            "db",
            "gds",
            "oas",
            "layout",
            "milkyway",
            "ndm",
        ]

        with tempfile.TemporaryDirectory() as td:
            old_scan = Path(td) / "old_scan"
            new_scan = Path(td) / "new_scan"
            old_scan.mkdir()
            new_scan.mkdir()
            (old_scan / "scan_meta.json").write_text(
                json.dumps({"library_name": "demo", "version": "base"}),
                encoding="utf-8",
            )
            (new_scan / "scan_meta.json").write_text(
                json.dumps({"library_name": "demo", "version": "new"}),
                encoding="utf-8",
            )
            file_diff = {
                "changed": [f"{file_type}/block.{file_type}" for file_type in changed_types],
                "_old_items": {},
                "_new_items": {},
            }
            for file_type in changed_types:
                relpath = f"{file_type}/block.{file_type}"
                file_diff["_old_items"][relpath] = {
                    "path": relpath,
                    "file_type": file_type,
                    "root_path": str(old_scan),
                }
                file_diff["_new_items"][relpath] = {
                    "path": relpath,
                    "file_type": file_type,
                    "root_path": str(new_scan),
                }

            tasks = build_pairwise_diff_tasks(
                old_scan,
                new_scan,
                file_diff,
                output_root=Path(td) / "pairwise",
            )

        task_text = json.dumps(tasks["tasks"], ensure_ascii=False)
        self.assertNotIn("--force-large", task_text)
        self.assertNotIn("--manual-large-file-opt-in", task_text)
        for item in tasks["tasks"]:
            self.assertNotIn("command", item)

    def test_short_cli_dry_run_force_large_prints_executable_lower_cli_command(self) -> None:
        from lib_guard.cli import build_parser
        from lib_guard.short_cli import main as short_main

        with tempfile.TemporaryDirectory() as td:
            workspace = self._fd_workspace(Path(td), "top.gds")
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = short_main(
                    [
                        "--config",
                        str(workspace / "lib_guard.yml"),
                        "--dry-run",
                        "fd",
                        "ucie",
                        "patch",
                        "top.gds",
                        "--type",
                        "gds",
                        "--force-large",
                    ]
                )

        self.assertEqual(code, 0)
        printed = output.getvalue().strip()
        self.assertNotIn("--manual-large-file-opt-in", printed)
        self.assertTrue(printed.startswith("python -m lib_guard.cli "))
        build_parser().parse_args(shlex.split(printed.removeprefix("python -m lib_guard.cli ")))

    def test_short_cli_dry_run_quotes_paths_with_spaces_for_lower_cli_command(self) -> None:
        from lib_guard.cli import build_parser
        from lib_guard.short_cli import main as short_main

        with tempfile.TemporaryDirectory(prefix="fd workspace ") as td:
            workspace = self._fd_workspace(Path(td), "top.gds")
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = short_main(
                    [
                        "--config",
                        str(workspace / "lib_guard.yml"),
                        "--dry-run",
                        "fd",
                        "ucie",
                        "patch",
                        "top.gds",
                        "--type",
                        "gds",
                        "--force-large",
                    ]
                )

        self.assertEqual(code, 0)
        printed = output.getvalue().strip()
        self.assertNotIn("--manual-large-file-opt-in", printed)
        argv = shlex.split(printed.removeprefix("python -m lib_guard.cli "))
        parsed = build_parser().parse_args(argv)
        self.assertIn(" ", parsed.old)
        self.assertIn(" ", parsed.new)
        self.assertTrue(parsed.old.endswith("top.gds"))
        self.assertTrue(parsed.new.endswith("top.gds"))

    def test_cli_file_diff_rejects_unsupported_type(self) -> None:
        from lib_guard.cli import build_parser

        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            build_parser().parse_args(["file-diff", "unknown", "--old", "old", "--new", "new", "--out", "out"])

    def test_unsupported_metadata_only_file_diff_uses_content_sensitive_metadata(self) -> None:
        from lib_guard.diff.file_diff import diff_pairwise_files

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            old = root / "old.gds"
            new = root / "new.gds"
            out = root / "out"
            old.write_bytes(b"GDS2\x00old-bytes\n")
            new.write_bytes(b"GDS2\x00new-different-bytes\n")

            result = diff_pairwise_files("gds", old, new, out)

            summary = json.loads((out / "file_diff_summary.json").read_text(encoding="utf-8"))
            old_extract = json.loads((out / "old_extract.json").read_text(encoding="utf-8"))
            new_extract = json.loads((out / "new_extract.json").read_text(encoding="utf-8"))

        self.assertEqual(result["status"], "DIFF")
        self.assertEqual(summary["status"], "DIFF")
        self.assertTrue(summary["changed"])
        self.assertNotEqual(summary["old_hash"], summary["new_hash"])
        self.assertEqual(old_extract["parser_status"], "UNSUPPORTED")
        self.assertEqual(new_extract["parser_status"], "UNSUPPORTED")
        self.assertEqual(old_extract["data"]["byte_size"], len(b"GDS2\x00old-bytes\n"))
        self.assertEqual(new_extract["data"]["byte_size"], len(b"GDS2\x00new-different-bytes\n"))
        self.assertNotEqual(old_extract["data"]["sha256_bytes"], new_extract["data"]["sha256_bytes"])
        self.assertEqual(old_extract["data"]["file_type"], "gds")
        self.assertEqual(new_extract["data"]["extension"], ".gds")


if __name__ == "__main__":
    unittest.main()
