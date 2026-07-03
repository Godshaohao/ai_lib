from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


class ShortCliRefreshTest(unittest.TestCase):
    def _workspace(self, root: Path) -> Path:
        workspace = root / "work"
        raw = workspace / "raw"
        catalog = workspace / "catalog" / "catalog.json"
        catalog.parent.mkdir(parents=True, exist_ok=True)
        catalog.write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "libraries": [
                        {
                            "library_id": "ucie",
                            "library_name": "ucie",
                            "summary": {"current_effective": "effective_20260620"},
                            "versions": [
                                {
                                    "version_id": "effective_20260620",
                                    "version_key": "ip/ucie/effective_20260620",
                                    "raw_path": str(raw / "ucie" / "effective_20260620"),
                                },
                                {
                                    "version_id": "patch_20260628",
                                    "version_key": "ip/ucie/patch_20260628",
                                    "raw_path": str(raw / "ucie" / "patch_20260628"),
                                    "current_effective_ref": "effective_20260620",
                                    "previous_effective_version": "previous_20260610",
                                    "diff": {"adjacent_old_version": "raw_adjacent_wrong"},
                                },
                            ],
                        }
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        from lib_guard.short_cli import write_default_config

        write_default_config(workspace, raw_root=raw)
        return workspace

    def test_refresh_defaults_to_effective_base_semantics(self) -> None:
        from lib_guard.short_cli import build_cli_commands

        with tempfile.TemporaryDirectory() as td:
            workspace = self._workspace(Path(td))
            commands = build_cli_commands(["refresh", "ucie"], cwd=workspace)

        self.assertEqual(len(commands), 1)
        command = commands[0]
        self.assertEqual(command[0], "compare")
        self.assertIn("--base", command)
        self.assertIn("effective_20260620", command)
        self.assertNotIn("--mode", command)
        self.assertNotIn("raw_adjacent_wrong", command)
        self.assertNotIn("previous_20260610", command)

    def test_refresh_adjacent_mode_is_explicit_manual_adjacent(self) -> None:
        from lib_guard.short_cli import build_cli_commands

        with tempfile.TemporaryDirectory() as td:
            workspace = self._workspace(Path(td))
            commands = build_cli_commands(["refresh", "ucie", "--mode", "adjacent"], cwd=workspace)

        self.assertEqual(len(commands), 1)
        command = commands[0]
        self.assertEqual(command[0], "compare")
        self.assertIn("--mode", command)
        self.assertIn("adjacent", command)
        self.assertNotIn("--base", command)
        self.assertNotIn("raw_adjacent_wrong", command)

    def test_refresh_reads_canonical_latest_effective_raw_ref(self) -> None:
        from lib_guard.short_cli import build_cli_commands

        with tempfile.TemporaryDirectory() as td:
            workspace = self._workspace(Path(td))
            catalog = workspace / "catalog" / "catalog.json"
            data = json.loads(catalog.read_text(encoding="utf-8"))
            lib = data["libraries"][0]
            lib["summary"] = {"latest_effective_ref": "raw:patch_20260628"}
            lib["versions"].append(
                {
                    "version_id": "future_20260701",
                    "version_key": "ip/ucie/future_20260701",
                    "raw_path": str(workspace / "raw" / "ucie" / "future_20260701"),
                }
            )
            catalog.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

            commands = build_cli_commands(["refresh", "ucie"], cwd=workspace)

        self.assertEqual(commands[0][commands[0].index("--new") + 1], "patch_20260628")
        self.assertEqual(commands[0][commands[0].index("--base") + 1], "effective_20260620")

    def test_cmp_keeps_manual_adjacent_default(self) -> None:
        from lib_guard.short_cli import build_cli_commands

        with tempfile.TemporaryDirectory() as td:
            workspace = self._workspace(Path(td))
            commands = build_cli_commands(["cmp", "ucie", "patch_20260628"], cwd=workspace)

        self.assertEqual(len(commands), 1)
        command = commands[0]
        self.assertEqual(command[0], "compare")
        self.assertIn("--mode", command)
        self.assertIn("adjacent", command)
        self.assertNotIn("--base", command)


if __name__ == "__main__":
    unittest.main()
