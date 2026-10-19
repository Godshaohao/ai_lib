from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from lib_guard.project_config import (
    BINARY_METADATA_ONLY_TYPES,
    DEFAULT_FILE_DIFF_TYPES,
    HASH_POLICIES,
    MAX_PARSE_JOBS,
    MIN_PARSE_JOBS,
    SUMMARY_ONLY_TYPES,
    VIEW_TYPE_SPECS,
    WEB_ACTION_SPECS,
    WEB_COMPARE_DEFAULTS,
    WEB_COMPARE_MODES,
    WEB_MARK_TYPES,
    WEB_MUTATING_ACTIONS,
    WEB_PACKAGE_TYPES,
    WEB_STAGES,
    WORKSPACE_CONFIG_SCHEMA_VERSION,
    canonical_view_type,
    default_discovery_strategy,
    default_scan_strategy,
    file_diff_allowed,
    file_diff_requires_force_large,
)
from lib_guard.short_cli_config import (
    WorkspaceConfig,
    load_config,
    load_workspace_config,
    merge_config_overrides,
    parse_config,
    update_config_file,
    write_default_config,
)


class ConfigModelTest(unittest.TestCase):
    def test_execution_limits_are_shared_configuration_constants(self) -> None:
        self.assertEqual(HASH_POLICIES, frozenset({"none", "smart", "full"}))
        self.assertEqual((MIN_PARSE_JOBS, MAX_PARSE_JOBS), (1, 32))

    def test_web_command_surface_is_defined_in_shared_project_config(self) -> None:
        from lib_guard import project_config
        from lib_guard.web import app as web_app

        self.assertIs(web_app.WEB_ACTION_SPECS, project_config.WEB_ACTION_SPECS)
        self.assertIs(web_app.WEB_MUTATING_ACTIONS, project_config.WEB_MUTATING_ACTIONS)
        self.assertEqual(WEB_MUTATING_ACTIONS, frozenset(WEB_ACTION_SPECS))
        self.assertEqual(WEB_ACTION_SPECS["scan"].scope, "version")
        self.assertEqual(WEB_ACTION_SPECS["cmp"].cli_action, "cmp")
        self.assertEqual(WEB_ACTION_SPECS["file-diff"].cli_action, "fd")
        self.assertEqual(WEB_ACTION_SPECS["release-force"].cli_action, "rel")
        self.assertEqual(WEB_COMPARE_MODES, frozenset({"adjacent", "cumulative"}))
        self.assertIn("FULL", WEB_MARK_TYPES)
        self.assertIn("FULL_PACKAGE", WEB_PACKAGE_TYPES)
        self.assertIn("previous_effective", WEB_COMPARE_DEFAULTS)
        self.assertIn("final", WEB_STAGES)

    def test_default_config_exposes_effective_scan_strategy(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            config = write_default_config(root, raw_root=root / "raw")

            text = config.read_text(encoding="utf-8")
            self.assertIn(f"config_version: {WORKSPACE_CONFIG_SCHEMA_VERSION}", text)
            self.assertIn("hash_policy: smart", text)
            self.assertIn("force_hash_file_types:", text)
            self.assertIn("skip_hash_file_types:", text)
            self.assertIn("parse_file_types:", text)
            self.assertIn("parse_exclude_file_types:", text)
            self.assertIn("render_detail: true", text)
            self.assertIn("discover_min_versions: 1", text)
            self.assertIn("discover_max_depth: 8", text)

            loaded = load_config(root, config)
            self.assertEqual(loaded["config_version"], WORKSPACE_CONFIG_SCHEMA_VERSION)
            self.assertEqual(loaded["hash_policy"], "smart")
            self.assertEqual(loaded["render_detail"], "true")
            self.assertEqual(loaded["discover_min_versions"], "1")

    def test_default_config_creates_empty_formal_release_root(self) -> None:
        """A freshly initialized workspace must not block read-only release indexing."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            config = write_default_config(root, raw_root=root / "raw")

            loaded = load_config(root, config)

            self.assertEqual(Path(loaded["release_root"]), root / "release_area")
            self.assertTrue((root / "release_area").is_dir())

    def test_web_default_strategy_payloads_come_from_shared_config(self) -> None:
        scan = default_scan_strategy()
        discovery = default_discovery_strategy()

        self.assertEqual(scan["hash_policy"], "smart")
        self.assertEqual(scan["parse_jobs"], "8")
        self.assertEqual(scan["render_detail"], "true")
        self.assertEqual(discovery["max_depth"], "8")
        self.assertEqual(discovery["min_versions"], "1")
        self.assertEqual(discovery["max_dirs"], "5000")
        self.assertEqual(discovery["max_candidates"], "200")

    def test_config_update_is_allowlisted_validated_and_backed_up(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "raw").mkdir()
            config = write_default_config(root, raw_root=root / "raw")

            result = update_config_file(
                config,
                {
                    "raw_root": str(root / "raw"),
                    "hash_policy": "none",
                    "parse_jobs": 2,
                    "force_hash_file_types": ["lef", "liberty"],
                    "discover_min_versions": 1,
                    "discover_max_candidates": 50,
                },
            )

            self.assertEqual(result["status"], "PASS")
            self.assertTrue(Path(result["backup"]).is_file())
            loaded = load_config(root, config)
            self.assertEqual(loaded["hash_policy"], "none")
            self.assertEqual(loaded["parse_jobs"], "2")
            self.assertEqual(loaded["force_hash_file_types"], "lef,liberty")
            self.assertEqual(loaded["discover_min_versions"], "1")
            self.assertEqual(loaded["discover_max_candidates"], "50")

    def test_workspace_config_exposes_typed_values_without_breaking_dict_callers(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            config = write_default_config(root, raw_root=root / "raw")

            typed = load_workspace_config(root, config)
            legacy = load_config(root, config)

            self.assertIsInstance(typed, WorkspaceConfig)
            self.assertEqual(typed.config_version, WORKSPACE_CONFIG_SCHEMA_VERSION)
            self.assertEqual(typed.parse_jobs, 8)
            self.assertTrue(typed.render_detail)
            self.assertEqual(typed.workspace, root.resolve())
            self.assertEqual(legacy, typed.as_dict())

    def test_cli_overrides_have_precedence_and_none_does_not_erase_config(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            typed = load_workspace_config(root, write_default_config(root, raw_root=root / "raw"))

            merged = merge_config_overrides(
                typed,
                {"parse_jobs": 4, "hash_policy": "none", "render_detail": False, "mode": None},
            )

            self.assertEqual(merged.parse_jobs, 4)
            self.assertEqual(merged.hash_policy, "none")
            self.assertFalse(merged.render_detail)
            self.assertEqual(merged.mode, "scan")

    def test_unknown_config_schema_version_fails_but_legacy_missing_version_loads(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            config = write_default_config(root, raw_root=root / "raw")
            legacy_text = config.read_text(encoding="utf-8").replace(
                f"config_version: {WORKSPACE_CONFIG_SCHEMA_VERSION}\n", ""
            )
            config.write_text(legacy_text, encoding="utf-8")
            self.assertEqual(load_config(root, config)["config_version"], WORKSPACE_CONFIG_SCHEMA_VERSION)

            config.write_text(
                f"config_version: lib_guard_config.v99\nworkspace: {root}\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "config_version"):
                load_config(root, config)

    def test_invalid_typed_config_fails_at_load_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            config = write_default_config(root, raw_root=root / "raw")
            text = config.read_text(encoding="utf-8").replace("parse_jobs: 8", "parse_jobs: many")
            config.write_text(text, encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "parse_jobs"):
                load_config(root, config)

    def test_valid_config_values_are_normalized_once(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            config = write_default_config(root, raw_root=root / "raw")
            text = config.read_text(encoding="utf-8")
            text = text.replace("parse_jobs: 8", "parse_jobs: 08")
            text = text.replace("hash_policy: smart", "hash_policy: SMART")
            text = text.replace("render_detail: true", "render_detail: YES")
            config.write_text(text, encoding="utf-8")

            loaded = load_config(root, config)

            self.assertEqual(loaded["parse_jobs"], "8")
            self.assertEqual(loaded["hash_policy"], "smart")
            self.assertEqual(loaded["render_detail"], "true")

    def test_legacy_candidate_scan_mode_is_migrated_to_single_scan_mode(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            config = write_default_config(root, raw_root=root / "raw")
            config.write_text(
                config.read_text(encoding="utf-8").replace("mode: scan", "mode: candidate"),
                encoding="utf-8",
            )

            loaded = load_config(root, config)

            self.assertEqual(loaded["mode"], "scan")

    def test_duplicate_and_unknown_config_keys_are_not_silently_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            duplicate = root / "duplicate.yml"
            duplicate.write_text("workspace: work\nworkspace: other\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "重复配置项"):
                parse_config(duplicate)

            unknown = root / "unknown.yml"
            unknown.write_text("workspace: work\nparse_job: 8\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "未知配置项.*parse_job"):
                load_config(root, unknown)

    def test_view_capabilities_are_derived_from_one_registry(self) -> None:
        self.assertEqual(canonical_view_type("lib"), "liberty")
        self.assertEqual(canonical_view_type("SP"), "spice")
        self.assertEqual(canonical_view_type("systemverilog"), "systemverilog")

        summary_names = {
            name
            for spec in VIEW_TYPE_SPECS.values()
            if spec.evidence_mode == "summary"
            for name in (spec.canonical_type, *spec.aliases)
        }
        metadata_names = {
            name
            for spec in VIEW_TYPE_SPECS.values()
            if spec.evidence_mode == "metadata"
            for name in (spec.canonical_type, *spec.aliases)
        }
        pairwise_names = {
            name
            for spec in VIEW_TYPE_SPECS.values()
            if spec.default_file_diff
            for name in (spec.canonical_type, *spec.aliases)
        }

        self.assertEqual(SUMMARY_ONLY_TYPES, summary_names)
        self.assertEqual(BINARY_METADATA_ONLY_TYPES, metadata_names)
        self.assertEqual(DEFAULT_FILE_DIFF_TYPES, pairwise_names)
        self.assertTrue(file_diff_allowed("lib"))
        self.assertTrue(file_diff_requires_force_large("lib"))
        self.assertTrue(file_diff_allowed("lef"))
        self.assertFalse(file_diff_requires_force_large("lef"))
        self.assertFalse(file_diff_allowed("unknown"))
        self.assertTrue(file_diff_allowed("generic"))
        self.assertTrue(file_diff_requires_force_large("generic"))


if __name__ == "__main__":
    unittest.main()
