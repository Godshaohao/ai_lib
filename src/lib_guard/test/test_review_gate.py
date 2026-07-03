from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path


class ReviewGateTest(unittest.TestCase):
    def assertGateItemsExplainTheRule(self, items: list[dict]) -> None:
        for item in items:
            for key in ["rule_id", "rule_source", "why", "next_action"]:
                self.assertIn(key, item)
                self.assertTrue(item[key])

    def test_pairwise_pending_is_attention_not_current_blocker(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            diff = root / "diff" / "ucie" / "stable" / "adjacent"
            diff.mkdir(parents=True)
            (diff / "manual_pairwise_tasks.json").write_text(
                json.dumps(
                    {
                        "tasks": [
                            {
                                "task_id": "lef_001",
                                "command": "lg.csh fd ucie stable lef/ucie.lef --base initial",
                                "expected_output": str(diff / "file_diff" / "lef_001"),
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            catalog = {
                "libraries": [
                    {
                        "library_id": "ip/ucie",
                        "library_name": "ucie",
                        "versions": [
                            {
                                "version_id": "stable",
                                "version_key": "ip/ucie/stable",
                                "stage": "stable",
                                "scan": {"status": "PASS", "scan_dir": str(root / "scan")},
                                "diff": {"status": "DIFF", "diff_dir": str(diff)},
                            }
                        ],
                    }
                ]
            }

            from lib_guard.review.state import build_review_state
            from lib_guard.review.tasks import build_review_tasks

            state = build_review_state(catalog, out_dir=root / "catalog" / "html")
            version = state["libraries"][0]["versions"][0]
            gate = version["review_gate"]

            self.assertEqual(gate["status"], "ATTENTION")
            self.assertEqual(gate["blocking_open"], 0)
            self.assertEqual(gate["attention_items"][0]["id"], "pairwise.recommended:stable")
            self.assertGateItemsExplainTheRule(gate["attention_items"])
            tasks = build_review_tasks(state)["tasks"]
            pairwise = [task for task in tasks if task["task_type"] == "PAIRWISE_DIFF"]
            self.assertEqual(pairwise[0]["priority"], "P2")

    def test_metadata_only_blocks_until_accept(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            diff = root / "diff" / "ucie" / "stable" / "adjacent"
            diff.mkdir(parents=True)
            (diff / "metadata_review_tasks.json").write_text(
                json.dumps(
                    {
                        "tasks": [
                            {
                                "task_id": "metadata_review_0001",
                                "file_type": "db",
                                "path": "db/ucie.db",
                                "change_type": "changed",
                                "status": "PENDING",
                            }
                        ],
                        "summary": {"total": 1, "pending": 1},
                    }
                ),
                encoding="utf-8",
            )
            catalog = {
                "libraries": [
                    {
                        "library_id": "ip/ucie",
                        "library_name": "ucie",
                        "versions": [
                            {
                                "version_id": "stable",
                                "version_key": "ip/ucie/stable",
                                "stage": "stable",
                                "scan": {"status": "PASS", "scan_dir": str(root / "scan")},
                                "diff": {"status": "DIFF", "diff_dir": str(diff)},
                            }
                        ],
                    }
                ]
            }

            from lib_guard.review.overrides import write_review_override
            from lib_guard.review.state import build_review_state

            state = build_review_state(catalog, out_dir=root / "catalog" / "html")
            gate = state["libraries"][0]["versions"][0]["review_gate"]
            self.assertEqual(gate["status"], "REVIEW_REQUIRED")
            self.assertEqual(gate["blocking_open"], 1)
            self.assertGateItemsExplainTheRule(gate["blocking_items"])

            write_review_override(
                gate["override_file"],
                library="ucie",
                version="stable",
                item_id="metadata.db.changed:db/ucie.db",
                decision="accepted",
                by="lib_owner",
                reason="DB hash change acknowledged for current.",
            )
            refreshed = build_review_state(catalog, out_dir=root / "catalog" / "html")
            refreshed_gate = refreshed["libraries"][0]["versions"][0]["review_gate"]

            self.assertEqual(refreshed_gate["status"], "READY")
            self.assertEqual(refreshed_gate["blocking_open"], 0)
            self.assertEqual(refreshed_gate["accepted_items"][0]["id"], "metadata.db.changed:db/ucie.db")

    def test_release_checker_consumes_review_gate(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            scan = root / "scan"
            diff = root / "diff"
            (scan / "summary").mkdir(parents=True)
            diff.mkdir()
            (scan / "scan_meta.json").write_text(
                json.dumps({"status": "PASS", "scan_mode": "signature", "library_type": "ip", "library_name": "ucie", "release_version": "stable"}),
                encoding="utf-8",
            )
            (scan / "file_inventory.json").write_text(json.dumps({"files": [{"file_type": "verilog", "path": "rtl/top.v"}]}), encoding="utf-8")
            (scan / "parser_manifest.json").write_text(json.dumps({"files": []}), encoding="utf-8")
            (scan / "scan_issues.json").write_text(json.dumps({"issues": []}), encoding="utf-8")
            (scan / "summary" / "release_readiness.json").write_text(
                json.dumps({"bundle_status": "PASS", "release_level_candidate": "L1", "diff_level": "P0", "manual_review_items": []}),
                encoding="utf-8",
            )
            (diff / "diff_summary.json").write_text(json.dumps({"status": "SAME", "diff_level": "P0", "deep_diff_completed": False}), encoding="utf-8")
            (diff / "diff_issues.json").write_text(json.dumps({"issues": []}), encoding="utf-8")

            from lib_guard.release.checker import check_release_scan

            blocked = check_release_scan(
                scan,
                diff_dir=diff,
                alias="current",
                review_gate={"schema_version": "review_gate.v1", "status": "REVIEW_REQUIRED", "blocking_open": 1, "blocking_items": [{"id": "metadata.db.changed:db/ucie.db"}], "attention_items": []},
            )
            ready = check_release_scan(
                scan,
                diff_dir=diff,
                alias="current",
                review_gate={"schema_version": "review_gate.v1", "status": "READY", "blocking_open": 0, "blocking_items": [], "attention_items": [{"id": "pairwise.recommended:stable"}]},
            )

            self.assertFalse(blocked["allowed_to_apply"])
            self.assertIn("current requires review gate closed", blocked["block_reasons"])
            self.assertTrue(ready["allowed_to_apply"])
            self.assertNotIn("current requires pairwise file diff complete", ready["block_reasons"])

    def test_short_cli_release_symlink_default_and_review_aliases(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            workspace = Path(td)
            raw = workspace / "raw"
            catalog = workspace / "catalog" / "catalog.json"
            catalog.parent.mkdir(parents=True)
            catalog.write_text(
                json.dumps(
                    {
                        "libraries": [
                            {
                                "library_id": "ip/ucie",
                                "library_name": "ucie",
                                "versions": [{"version_id": "stable", "version_key": "ip/ucie/stable", "raw_path": str(raw / "ucie" / "stable")}],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            from lib_guard.short_cli import build_cli_command, write_default_config

            write_default_config(workspace, raw_root=raw)
            release = build_cli_command(["rel", "ucie", "stable", "--check-first"], cwd=workspace)
            rv_check = build_cli_command(["rv-check", "ucie", "stable"], cwd=workspace)
            rv_accept = build_cli_command(["rv-accept", "ucie", "stable", "--item", "metadata.db.changed:db/ucie.db", "--by", "lib_owner", "--reason", "accepted"], cwd=workspace)

            self.assertEqual(release[0], "release-batch")
            self.assertIn("--link-mode", release)
            self.assertEqual(release[release.index("--link-mode") + 1], "symlink")
            self.assertEqual(rv_check[:2], ["review", "check"])
            self.assertEqual(rv_accept[:2], ["review", "accept"])
            self.assertIn("--catalog-html-out", rv_accept)


if __name__ == "__main__":
    unittest.main()
