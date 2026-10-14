from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path


class EffectiveReleaseSetTest(unittest.TestCase):
    def _write_current_effective(
        self,
        root: Path,
        *,
        library: str,
        effective_id: str,
        digest_suffix: str,
        base: str = "full",
        overlays: list[str] | None = None,
    ) -> None:
        from lib_guard.effective.manifest import build_effective_manifest
        from lib_guard.effective.pointer import write_current_pointer

        effective_dir = root / "libraries" / library.replace("/", "_") / "effective" / effective_id
        effective_dir.mkdir(parents=True)
        versions = [
            {
                "version_id": base,
                "scan": {"snapshot_identity": {"digest": f"sha256:{digest_suffix}-base", "strength": "full"}},
            },
            *[
                {
                    "version_id": version,
                    "scan": {"snapshot_identity": {"digest": f"sha256:{digest_suffix}-{version}", "strength": "full"}},
                    "update_scope": ["all"],
                }
                for version in (overlays or [])
            ],
        ]
        catalog = {"libraries": [{"library_id": library, "library_name": library.split("/")[-1], "versions": versions}]}
        manifest = build_effective_manifest(catalog, library, base, [(version, ["all"]) for version in (overlays or [])], effective_id=effective_id)
        manifest_path = effective_dir / "effective_manifest.json"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        write_current_pointer(manifest_path, html=effective_dir / "index.html", accepted_by="owner", note="test")

    def test_release_set_manifest_references_current_effective_pointers_without_copying_files(self) -> None:
        from lib_guard.effective.release_set import build_release_set_manifest

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._write_current_effective(root, library="ip/libA", effective_id="E1", digest_suffix="a", overlays=["fix1"])
            self._write_current_effective(root, library="ip/libB", effective_id="E2", digest_suffix="b")

            manifest = build_release_set_manifest(root, ["ip/libA", "ip/libB"], set_id="set1")

        self.assertEqual(manifest["schema_version"], "release_set_manifest.v1")
        self.assertEqual(manifest["set_id"], "set1")
        self.assertEqual(manifest["summary"]["library_count"], 2)
        self.assertEqual(manifest["summary"]["missing_current_effective"], 0)
        self.assertEqual(manifest["libraries"][0]["source"], "current_effective_pointer")
        self.assertEqual(manifest["libraries"][0]["base_full_version"], "full")
        self.assertEqual(manifest["libraries"][0]["accepted_updates"], ["fix1"])
        self.assertNotIn("effective_files", json.dumps(manifest))

    def test_release_set_compare_is_library_digest_level_and_points_changed_libs_to_drilldown(self) -> None:
        from lib_guard.effective.release_set import build_release_set_manifest, compare_release_sets

        with tempfile.TemporaryDirectory() as td:
            old_root = Path(td) / "old"
            new_root = Path(td) / "new"
            self._write_current_effective(old_root, library="ip/libA", effective_id="E1", digest_suffix="same")
            self._write_current_effective(new_root, library="ip/libA", effective_id="E1", digest_suffix="same")
            self._write_current_effective(old_root, library="ip/libB", effective_id="E2", digest_suffix="old")
            self._write_current_effective(new_root, library="ip/libB", effective_id="E3", digest_suffix="new")
            self._write_current_effective(new_root, library="ip/libC", effective_id="E1", digest_suffix="c")
            old = build_release_set_manifest(old_root, ["ip/libA", "ip/libB"], set_id="old")
            new = build_release_set_manifest(new_root, ["ip/libA", "ip/libB", "ip/libC"], set_id="new")

            compare = compare_release_sets(old, new)

        self.assertEqual(compare["summary"]["actions"], {"ADD_LIBRARY": 1, "CHANGE_EFFECTIVE": 1, "KEEP_LIBRARY": 1})
        changed = next(row for row in compare["libraries"] if row["library_id"] == "ip/libB")
        self.assertEqual(changed["action"], "CHANGE_EFFECTIVE")
        self.assertIn("effective:E2", changed["old_target"])
        self.assertIn("effective:E3", changed["new_target"])
        self.assertNotIn("changed_files", changed)

    def test_release_set_compare_keeps_same_missing_current_effective_state(self) -> None:
        from lib_guard.effective.release_set import build_release_set_manifest, compare_release_sets

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            old = build_release_set_manifest(root, ["ip/libA"], set_id="old")
            new = build_release_set_manifest(root, ["ip/libA"], set_id="new")

            compare = compare_release_sets(old, new)

        self.assertEqual(compare["summary"]["actions"], {"KEEP_LIBRARY": 1})
        self.assertEqual(compare["summary"]["changed_libraries"], 0)
        self.assertEqual(compare["libraries"][0]["action"], "KEEP_LIBRARY")
