from __future__ import annotations

import json
import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


class PairwisePolicyTest(unittest.TestCase):
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
        for file_type in set(changed_types) - expected_task_types:
            self.assertNotIn(file_type, task_types)

    def test_default_pairwise_file_diff_types_match_project_defaults(self) -> None:
        from lib_guard.diff.pairwise import DEFAULT_PAIRWISE_FILE_DIFF_TYPES
        from lib_guard.project_config import DEFAULT_FILE_DIFF_TYPES

        self.assertEqual(DEFAULT_PAIRWISE_FILE_DIFF_TYPES, DEFAULT_FILE_DIFF_TYPES)

    def test_short_cli_file_diff_type_choices_match_project_defaults(self) -> None:
        from lib_guard.project_config import DEFAULT_FILE_DIFF_TYPES
        from lib_guard.short_cli import _build_parser

        parser = _build_parser()
        parser.parse_args(["fd", "ucie", "patch_20260628", "spice/top.sp", "--type", "spice"])
        parser.parse_args(["fd", "ucie", "patch_20260628", "touchstone/top.s2p", "--type", "touchstone"])
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            parser.parse_args(["fd", "ucie", "patch_20260628", "rtl/top.v", "--type", "verilog"])

        file_diff_parser = next(
            action
            for action in parser._subparsers._group_actions[0].choices["file-diff"]._actions
            if action.dest == "type"
        )
        self.assertEqual(set(file_diff_parser.choices), DEFAULT_FILE_DIFF_TYPES)

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


if __name__ == "__main__":
    unittest.main()
