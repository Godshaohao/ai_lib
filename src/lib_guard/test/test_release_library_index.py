from __future__ import annotations

import json
import contextlib
import io
import tempfile
import unittest
from pathlib import Path


class ReleaseLibraryIndexTest(unittest.TestCase):
    def test_unregistered_delivery_is_not_reported_as_no_publication(self):
        from lib_guard.release.library_index import build_release_library_index, write_release_library_index, load_release_library_index
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            legacy = root / 'lib_NL2.0/LEF'
            legacy.mkdir(parents=True)
            (legacy / 'a.lef').symlink_to(root / 'missing.lef')
            (root / 'current').symlink_to(legacy.parent)
            (root / 'history/lib_NLold/LEF').mkdir(parents=True)
            index = build_release_library_index(root)
            self.assertEqual(index['libraries'], [])
            self.assertEqual(index['stages'], [])
            self.assertEqual(len(index['unregistered_deliveries']), 1)
            self.assertEqual(index['unregistered_deliveries'][0]['path'], str(legacy.parent))
            self.assertEqual(index['unregistered_deliveries'][0]['pointers'], ['current'])
            self.assertFalse((legacy.parent / 'release_manifest.json').exists())
            write_release_library_index(root / 'index.json', index)
            self.assertEqual(load_release_library_index(root / 'index.json')['unregistered_deliveries'], index['unregistered_deliveries'])

    def _write_manifest(
        self,
        root: Path,
        *,
        library_type: str,
        library_name: str,
        version_id: str,
        release_id: str,
        created_at: str,
    ) -> Path:
        release_dir = root / library_name / "releases" / release_id
        release_dir.mkdir(parents=True)
        manifest = {
            "schema_version": "release_manifest.v1",
            "release_id": release_id,
            "alias": "current",
            "release_root": str(root / library_name),
            "link_mode": "symlink",
            "created_at": created_at,
            "libraries": [
                {
                    "library_type": library_type,
                    "library_name": library_name,
                    "version_id": version_id,
                    "version_key": f"{library_type}/{library_name}/{version_id}",
                }
            ],
        }
        path = release_dir / "release_manifest.json"
        path.write_text(json.dumps(manifest), encoding="utf-8")
        return path

    def test_index_groups_multiple_libraries_keeps_history_and_prefers_alias_link(self) -> None:
        from lib_guard.release.library_index import build_release_library_index

        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "formal_release"
            first = self._write_manifest(
                root,
                library_type="ip",
                library_name="ucie",
                version_id="v1",
                release_id="R_UCIE_1",
                created_at="2026-09-01T00:00:00Z",
            )
            second = self._write_manifest(
                root,
                library_type="ip",
                library_name="ucie",
                version_id="v2",
                release_id="R_UCIE_2",
                created_at="2026-09-02T00:00:00Z",
            )
            self._write_manifest(
                root,
                library_type="ip",
                library_name="ddr",
                version_id="v7",
                release_id="R_DDR_7",
                created_at="2026-09-03T00:00:00Z",
            )
            (root / "ucie" / "current").symlink_to(second.parent)
            broken = root / "broken" / "release_manifest.json"
            broken.parent.mkdir(parents=True)
            broken.write_text("{not json", encoding="utf-8")

            index = build_release_library_index(root)

            self.assertEqual(index["schema_version"], "release_library_index.v1")
            self.assertEqual(index["summary"]["library_count"], 2)
            self.assertEqual(index["summary"]["invalid_manifest_count"], 1)
            self.assertEqual(index["summary"]["raw_candidate_count"], 0)
            ucie = next(row for row in index["libraries"] if row["library_id"] == "ip/ucie")
            self.assertEqual(len(ucie["releases"]), 2)
            self.assertEqual(ucie["current"]["release_id"], "R_UCIE_2")
            self.assertEqual(ucie["current"]["source"], "alias_link")
            self.assertEqual(ucie["releases"][0]["manifest"], str(second.resolve()))
            self.assertNotEqual(ucie["releases"][0]["manifest_sha256"], "")
            self.assertTrue(first.exists())

    def test_index_current_ignores_an_active_stage_alias(self) -> None:
        """A newer stage link must not replace the library's current publication."""
        from lib_guard.release.library_index import build_release_library_index

        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "formal_release"
            current = self._write_manifest(
                root,
                library_type="ip",
                library_name="ucie",
                version_id="v1",
                release_id="R_CURRENT",
                created_at="2026-09-01T00:00:00Z",
            )
            stage_dir = root / "ucie" / "releases" / "R_STAGE"
            stage_dir.mkdir(parents=True)
            stage_manifest = json.loads(current.read_text(encoding="utf-8"))
            stage_manifest.update({"release_id": "R_STAGE", "alias": "stage", "created_at": "2026-09-02T00:00:00Z"})
            stage_path = stage_dir / "release_manifest.json"
            stage_path.write_text(json.dumps(stage_manifest), encoding="utf-8")
            (root / "ucie" / "current").symlink_to(current.parent)
            (root / "ucie" / "stage").symlink_to(stage_dir)

            index = build_release_library_index(root)

        ucie = next(row for row in index["libraries"] if row["library_id"] == "ip/ucie")
        self.assertEqual(ucie["current"]["release_id"], "R_CURRENT")
        self.assertEqual(ucie["current"]["alias"], "current")

    def test_index_rejects_manifest_outside_requested_release_root(self) -> None:
        from lib_guard.release.library_index import build_release_library_index

        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "formal_release"
            root.mkdir()
            outside = Path(td) / "outside"
            manifest = self._write_manifest(
                outside,
                library_type="ip",
                library_name="ucie",
                version_id="v1",
                release_id="R1",
                created_at="2026-09-01T00:00:00Z",
            )
            linked = root / "escaped" / "release_manifest.json"
            linked.parent.mkdir(parents=True)
            linked.symlink_to(manifest)

            index = build_release_library_index(root)

            self.assertEqual(index["summary"]["library_count"], 0)
            self.assertEqual(index["summary"]["invalid_manifest_count"], 1)
            self.assertIn("路径越界", index["invalid_manifests"][0]["error"])

    def test_core_cli_refresh_and_list_only_read_release_manifests(self) -> None:
        from lib_guard.cli import main

        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "formal_release"
            self._write_manifest(
                root,
                library_type="ip",
                library_name="ucie",
                version_id="v1",
                release_id="R_UCIE_1",
                created_at="2026-09-01T00:00:00Z",
            )
            index = Path(td) / "config" / "release_libraries" / "latest.json"
            stdout = io.StringIO()

            with contextlib.redirect_stdout(stdout):
                self.assertEqual(main(["release-library", "refresh", "--root", str(root), "--out", str(index)]), 0)
            self.assertTrue(index.is_file())
            self.assertIn("正式发布库", stdout.getvalue())

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                self.assertEqual(main(["release-library", "list", "--input", str(index), "--library", "ip/ucie"]), 0)
            self.assertIn("ip/ucie", stdout.getvalue())

    def test_short_cli_expands_release_library_refresh_without_catalog_or_scan(self) -> None:
        from lib_guard.short_cli import build_cli_commands
        from lib_guard.short_cli_config import write_default_config

        with tempfile.TemporaryDirectory() as td:
            workspace = Path(td) / "work"
            raw_root = Path(td) / "raw"
            release_root = Path(td) / "formal_release"
            raw_root.mkdir()
            release_root.mkdir()
            config = write_default_config(workspace, raw_root=raw_root)
            config.write_text(
                config.read_text(encoding="utf-8").replace("release_root: " + str(workspace / "release_area"), "release_root: " + str(release_root)),
                encoding="utf-8",
            )

            commands = build_cli_commands(["--config", str(config), "release-library", "refresh"], cwd=workspace)

        self.assertEqual(commands[0][:2], ["release-library", "refresh"])
        self.assertIn(str(release_root), commands[0])
        self.assertNotIn("catalog", commands[0])
        self.assertNotIn("scan", commands[0])


if __name__ == "__main__":
    unittest.main()
