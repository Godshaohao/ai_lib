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


class ReleaseExplainTest(unittest.TestCase):
    def test_explain_release_check_reports_review_gate_blocker_and_force_action(self) -> None:
        from lib_guard.release.explain import explain_release_check

        explain = explain_release_check(
            {
                "release_check_status": "BLOCK",
                "library_name": "ucie",
                "version": "stable_20250608",
                "review_gate": {
                    "status": "REVIEW_REQUIRED",
                    "blocking_items": [
                        {
                            "id": "metadata.db.changed:db/ucie.db",
                            "category": "metadata_only",
                            "title": "Metadata-only view changed",
                            "message": "DB changed",
                            "next_action": "rv-accept or force release with audit reason",
                        }
                    ],
                },
            }
        )

        self.assertEqual(explain["status"], "BLOCKED")
        self.assertEqual(explain["failed_phase"], "REVIEW_GATE_BLOCKED")
        self.assertEqual(explain["blockers"][0]["id"], "metadata.db.changed:db/ucie.db")
        self.assertEqual(explain["blockers"][0]["next_action"], "rv accept or force release with audit reason")
        self.assertTrue(explain["safe_actions"])
        self.assertTrue(any("--explain" in action for action in explain["safe_actions"]))
        self.assertFalse(any("--apply" in action for action in explain["safe_actions"]))
        self.assertIn("--force", explain["force_actions"][0])
        self.assertIn("--force-by", explain["force_actions"][0])

    def test_explain_release_check_classifies_common_failure_phases(self) -> None:
        from lib_guard.release.explain import explain_release_check

        cases = [
            ({"catalog_status": "NEED_CONFIRM"}, "CATALOG_NOT_READY"),
            ({"scan_status": "NOT_SCANNED"}, "SCAN_MISSING"),
            ({"release_check_status": "BLOCK", "block_reasons": ["manual review open"]}, "RELEASE_CHECK_BLOCKED"),
            ({"status": "VERIFY_FAILED"}, "VERIFY_FAILED"),
            ({"status": "FAILED", "failed_links": [{"error": "release source does not exist: raw/missing"}]}, "MANIFEST_SOURCE_MISSING"),
            ({"status": "FAILED", "failed_links": [{"status": "TARGET_EXISTS", "error": "target exists"}]}, "TARGET_EXISTS"),
            ({"status": "FAILED", "failed_links": [{"error": "Permission denied"}]}, "PERMISSION_DENIED"),
            ({"status": "FAILED", "failed_links": [{"error": "copy failed"}]}, "LINK_FAILED"),
        ]
        for payload, phase in cases:
            with self.subTest(phase=phase):
                self.assertEqual(explain_release_check(payload)["failed_phase"], phase)

    def test_short_cli_rel_explain_expands_only_release_check(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            workspace = Path(td)
            raw = workspace / "raw"
            catalog = workspace / "catalog" / "catalog.json"
            catalog.parent.mkdir(parents=True)
            catalog.write_text(json.dumps({"libraries": []}), encoding="utf-8")

            from lib_guard.short_cli import build_cli_commands, write_default_config

            write_default_config(workspace, raw_root=raw)
            commands = build_cli_commands(["rel", "ucie", "stable_20250608", "--check-first", "--explain"], cwd=workspace)

            self.assertEqual(len(commands), 1)
            self.assertEqual(commands[0][:2], ["catalog", "release-check"])
            self.assertIn("--explain", commands[0])
            self.assertIn("--policy", commands[0])
            self.assertTrue(commands[0][commands[0].index("--policy") + 1].endswith("configs/release_policy.json"))

    def test_catalog_release_check_parser_accepts_explain(self) -> None:
        from lib_guard.cli import build_parser

        args = build_parser().parse_args(
            [
                "catalog",
                "release-check",
                "--catalog",
                "catalog.json",
                "--library",
                "ucie",
                "--version",
                "stable_20250608",
                "--explain",
            ]
        )

        self.assertTrue(args.explain)

    def test_catalog_release_check_explain_does_not_update_release_state(self) -> None:
        from lib_guard.cli_commands.catalog import run_catalog_release_check

        args = Namespace(
            catalog="catalog.json",
            library="ucie",
            version="stable_20250608",
            policy=None,
            alias="current",
            diff=None,
            diff_mode=None,
            review_gate=None,
            explain=True,
        )
        check_result = {
            "release_check_status": "BLOCK",
            "library_name": "ucie",
            "version": "stable_20250608",
            "review_gate": {"status": "REVIEW_REQUIRED", "blocking_items": [{"id": "metadata.db.changed:db/ucie.db"}]},
        }

        with (
            patch("lib_guard.catalog.index.find_catalog_version", return_value={"version_key": "ip/ucie/stable_20250608", "scan": {"scan_dir": "scan"}}),
            patch("lib_guard.cli_commands.catalog._review_gate_for_catalog_version", return_value=(None, {})),
            patch("lib_guard.release.checker.check_release_scan", return_value=check_result),
            patch("lib_guard.release.result.write_release_result") as write_result,
            patch("lib_guard.catalog.index.update_catalog_release_status") as update_status,
        ):
            with redirect_stdout(StringIO()):
                code = run_catalog_release_check(args)

        self.assertEqual(code, 0)
        write_result.assert_not_called()
        update_status.assert_not_called()


if __name__ == "__main__":
    unittest.main()
