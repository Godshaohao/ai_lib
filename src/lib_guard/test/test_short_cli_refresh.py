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

    def test_update_detail_targets_latest_delivery_not_current_effective(self) -> None:
        from lib_guard.short_cli import build_cli_commands

        with tempfile.TemporaryDirectory() as td:
            workspace = self._workspace(Path(td))
            catalog = workspace / "catalog" / "catalog.json"
            data = json.loads(catalog.read_text(encoding="utf-8"))
            lib = data["libraries"][0]
            lib["summary"] = {
                "current_effective": "effective_20260620",
                "latest_effective_ref": "raw:effective_20260620",
                "latest_version": "patch_20260628",
            }
            lib["versions"][0]["current_effective"] = True
            catalog.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

            commands = build_cli_commands(["cat", "ucie", "--update-detail"], cwd=workspace)

        self.assertEqual(len(commands), 1)
        command = commands[0]
        self.assertEqual(command[0], "compare")
        self.assertEqual(command[command.index("--new") + 1], "patch_20260628")
        self.assertEqual(command[command.index("--base") + 1], "effective_20260620")

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

    def test_update_detail_ignores_latest_effective_ref_when_picking_target_delivery(self) -> None:
        from lib_guard.short_cli import build_cli_commands

        with tempfile.TemporaryDirectory() as td:
            workspace = self._workspace(Path(td))
            catalog = workspace / "catalog" / "catalog.json"
            data = json.loads(catalog.read_text(encoding="utf-8"))
            lib = data["libraries"][0]
            lib["summary"] = {"latest_effective_ref": "raw:patch_20260628", "latest_version": "future_20260701"}
            lib["versions"].append(
                {
                    "version_id": "future_20260701",
                    "version_key": "ip/ucie/future_20260701",
                    "raw_path": str(workspace / "raw" / "ucie" / "future_20260701"),
                    "current_effective_ref": "effective_20260620",
                }
            )
            catalog.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

            commands = build_cli_commands(["refresh", "ucie"], cwd=workspace)

        self.assertEqual(commands[0][commands[0].index("--new") + 1], "future_20260701")
        self.assertEqual(commands[0][commands[0].index("--base") + 1], "effective_20260620")

    def test_previous_effective_mode_does_not_fall_back_to_adjacent(self) -> None:
        from lib_guard.short_cli import build_cli_commands

        with tempfile.TemporaryDirectory() as td:
            workspace = self._workspace(Path(td))
            catalog = workspace / "catalog" / "catalog.json"
            data = json.loads(catalog.read_text(encoding="utf-8"))
            version = data["libraries"][0]["versions"][1]
            version.pop("current_effective_ref", None)
            version.pop("previous_effective_version", None)
            catalog.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

            with self.assertRaises(ValueError) as caught:
                build_cli_commands(["cat", "ucie", "--update-detail", "--mode", "previous_effective"], cwd=workspace)

        self.assertIn("refresh cannot resolve previous_effective base", str(caught.exception))
        self.assertNotIn("raw_adjacent_wrong", str(caught.exception))

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

    def test_update_detail_uses_full_baseline_for_partial_update_without_effective_pointer(self) -> None:
        from lib_guard.short_cli import build_cli_commands

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            workspace = root / "work"
            raw = workspace / "raw"
            catalog = workspace / "catalog" / "catalog.json"
            catalog.parent.mkdir(parents=True, exist_ok=True)
            catalog.write_text(
                json.dumps(
                    {
                        "libraries": [
                            {
                                "library_id": "ip/Vendor_A.ucie",
                                "formal_library_id": "Vendor_A.ucie",
                                "library_type": "ip",
                                "library_name": "Vendor_A.ucie",
                                "summary": {"latest_version": "20260618_fix"},
                                "versions": [
                                    {
                                        "version_id": "20260601_full",
                                        "version_key": "ip/Vendor_A.ucie/20260601_full",
                                        "raw_path": str(raw / "Vendor_A" / "ucie" / "20260601_full"),
                                        "package_type": "FULL_PACKAGE",
                                        "standalone": True,
                                        "base_required": False,
                                    },
                                    {
                                        "version_id": "20260618_fix",
                                        "version_key": "ip/Vendor_A.ucie/20260618_fix",
                                        "raw_path": str(raw / "Vendor_A" / "ucie" / "20260618_fix"),
                                        "package_type": "PARTIAL_UPDATE",
                                        "standalone": False,
                                        "base_required": True,
                                        "base_full_version": "20260601_full",
                                        "compare_default": "full_baseline",
                                        "diff": {"adjacent_old_version": "20260601_full"},
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
            commands = build_cli_commands(["cat", "Vendor_A.ucie", "--update-detail"], cwd=workspace)

        command = commands[0]
        self.assertEqual(command[0], "compare")
        self.assertEqual(command[command.index("--new") + 1], "20260618_fix")
        self.assertEqual(command[command.index("--base") + 1], "20260601_full")
        self.assertEqual(command[command.index("--base-source") + 1], "full_baseline")
        self.assertNotIn("--mode", command)

    def test_update_detail_uses_previous_full_for_new_full_without_effective_pointer(self) -> None:
        from lib_guard.short_cli import build_cli_commands

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            workspace = root / "work"
            raw = workspace / "raw"
            catalog = workspace / "catalog" / "catalog.json"
            catalog.parent.mkdir(parents=True, exist_ok=True)
            catalog.write_text(
                json.dumps(
                    {
                        "libraries": [
                            {
                                "library_id": "ip/Vendor_A.ucie",
                                "formal_library_id": "Vendor_A.ucie",
                                "library_type": "ip",
                                "library_name": "Vendor_A.ucie",
                                "summary": {"latest_version": "20260701_full"},
                                "versions": [
                                    {
                                        "version_id": "20260601_full",
                                        "version_key": "ip/Vendor_A.ucie/20260601_full",
                                        "raw_path": str(raw / "Vendor_A" / "ucie" / "20260601_full"),
                                        "package_type": "FULL_PACKAGE",
                                        "standalone": True,
                                        "base_required": False,
                                    },
                                    {
                                        "version_id": "20260618_fix",
                                        "version_key": "ip/Vendor_A.ucie/20260618_fix",
                                        "raw_path": str(raw / "Vendor_A" / "ucie" / "20260618_fix"),
                                        "package_type": "PARTIAL_UPDATE",
                                        "standalone": False,
                                        "base_required": True,
                                        "base_full_version": "20260601_full",
                                        "diff": {"adjacent_old_version": "20260601_full"},
                                    },
                                    {
                                        "version_id": "20260701_full",
                                        "version_key": "ip/Vendor_A.ucie/20260701_full",
                                        "raw_path": str(raw / "Vendor_A" / "ucie" / "20260701_full"),
                                        "package_type": "FULL_PACKAGE",
                                        "standalone": True,
                                        "base_required": False,
                                        "diff": {"adjacent_old_version": "20260618_fix"},
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
            commands = build_cli_commands(["cat", "Vendor_A.ucie", "--update-detail"], cwd=workspace)

        command = commands[0]
        self.assertEqual(command[0], "compare")
        self.assertEqual(command[command.index("--new") + 1], "20260701_full")
        self.assertEqual(command[command.index("--base") + 1], "20260601_full")
        self.assertEqual(command[command.index("--base-source") + 1], "previous_full")
        self.assertNotIn("20260618_fix", command)


if __name__ == "__main__":
    unittest.main()
