from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from lib_guard.release.linker import link_release_from_manifest


class NamedReleaseTest(unittest.TestCase):
    def test_snapshot_and_effective_builders_preserve_original_names(self):
        from lib_guard.release.bundle import create_manifest_from_effective_manifest, create_manifest_from_snapshot

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for name in ('SRAM_Main.LEF', 'memory_2kb.lef'):
                with self.subTest(name=name):
                    source = root / 'raw/2kb' / name
                    source.parent.mkdir(parents=True, exist_ok=True)
                    source.write_text('VERSION 5.8 ;\n')
                    snapshot = root / 'snapshot.json'
                    snapshot.write_text(json.dumps({'resolved_files': [{
                        'source_path': str(source), 'target_relpath': 'lef/2kb/rewritten.lef', 'file_type': 'lef',
                    }]}))
                    effective = root / 'effective.json'
                    effective.write_text(json.dumps({'effective_files': {'lef/2kb/rewritten.lef': {
                        'source_path': str(source), 'file_type': 'lef',
                    }}}))
                    for builder, path in ((create_manifest_from_snapshot, snapshot), (create_manifest_from_effective_manifest, effective)):
                        manifest = builder(path, root / 'manifest.json', release_root=root / 'published')
                        self.assertEqual(manifest['files'][0]['target_relpath'], f'LEF/{name}')

    def test_release_preserves_source_filename_even_if_target_name_is_stale(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / 'raw/2kb/SRAM_Main.LEF'
            source.parent.mkdir(parents=True)
            source.write_text('VERSION 5.8 ;\n')
            manifest = self.manifest(root, source, 'R1')
            data = json.loads(manifest.read_text())
            data['files'][0]['target_relpath'] = 'lef/2kb/SRAM_Main_2kb.lef'
            manifest.write_text(json.dumps(data))
            result = link_release_from_manifest(manifest, apply=True)
            self.assertEqual(result['status'], 'APPLIED')
            self.assertTrue((root / 'published/lib_NL7/LEF/SRAM_Main.LEF').is_symlink())
            installed = json.loads((root / 'published/lib_NL7/release_manifest.json').read_text())
            self.assertEqual(installed['files'][0]['target_relpath'], 'LEF/SRAM_Main.LEF')

    def test_updating_nested_old_delivery_preserves_backup_and_flattens_new_links(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            old_source, new_source = root / 'old/top.lef', root / 'new/top.lef'
            old_source.parent.mkdir()
            new_source.parent.mkdir()
            old_source.write_text('old\n')
            new_source.write_text('new\n')
            old_link = root / 'published/lib_NL7/LEF/2kb/top.lef'
            old_link.parent.mkdir(parents=True)
            old_link.symlink_to(old_source)
            (root / 'published/latest_NL7').symlink_to('lib_NL7', target_is_directory=True)
            manifest = self.manifest(root, new_source, 'R2')
            data = json.loads(manifest.read_text())
            data['files'][0]['target_relpath'] = 'lef/4kb/top.lef'
            manifest.write_text(json.dumps(data))
            result = link_release_from_manifest(manifest, apply=True)
            self.assertEqual(result['status'], 'APPLIED')
            self.assertEqual((root / 'published/lib_NL7/LEF/top.lef').resolve(), new_source)
            self.assertFalse((root / 'published/lib_NL7/LEF/2kb').exists())
            backup = root / 'published/history' / f'lib_NL7_{datetime.now():%Y%m%d}'
            self.assertEqual((backup / 'LEF/2kb/top.lef').resolve(), old_source)
            self.assertEqual((root / 'published/latest_NL7').resolve(), root / 'published/lib_NL7')

    def test_capacity_folders_are_flattened_in_preview_links_and_manifest(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            files = []
            for size in (2, 4, 6, 8):
                source = root / 'raw' / 'lef' / f'{size}kb' / f'memory_{size}kb.lef'
                source.parent.mkdir(parents=True)
                source.write_text('VERSION 5.8 ;\n')
                files.append({'source_path': str(source), 'target_relpath': f'lef/{size}kb/{source.name}', 'relative_path': f'lef/{size}kb/{source.name}', 'file_type': 'lef'})
            manifest = root / 'manifest.json'
            manifest.write_text(json.dumps({'release_id': 'R1', 'release_root': str(root / 'published'), 'publish_name': 'lib_NL7', 'files': files}))
            preview = link_release_from_manifest(manifest)
            self.assertEqual({item['relative_path'] for item in preview['planned_files']}, {f'LEF/memory_{size}kb.lef' for size in (2, 4, 6, 8)})
            result = link_release_from_manifest(manifest, apply=True)
            self.assertEqual(result['status'], 'APPLIED')
            self.assertEqual(result['verify']['status'], 'PASS')
            for source in files:
                link = root / 'published' / 'lib_NL7' / 'LEF' / Path(source['source_path']).name
                self.assertTrue(link.is_symlink())
                self.assertEqual(link.resolve(), Path(source['source_path']))
            self.assertFalse((root / 'published/lib_NL7/LEF/2kb').exists())
            installed = json.loads((root / 'published/lib_NL7/release_manifest.json').read_text())
            self.assertEqual({item['target_relpath'] for item in installed['files']}, {f'LEF/memory_{size}kb.lef' for size in (2, 4, 6, 8)})
            self.assertTrue(all(item['relative_path'] == item['target_relpath'] for item in installed['files']))

    def test_flatten_collision_never_silently_overwrites_a_file(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            files = []
            for size in (2, 4):
                source = root / 'raw' / f'{size}kb' / 'top.lef'
                source.parent.mkdir(parents=True)
                source.write_text(f'capacity {size}\n')
                files.append({'source_path': str(source), 'target_relpath': f'LEF/{size}kb/top.lef', 'file_type': 'lef'})
            manifest = root / 'manifest.json'
            manifest.write_text(json.dumps({'release_id': 'R1', 'release_root': str(root / 'published'), 'publish_name': 'lib_NL7', 'files': files}))
            result = link_release_from_manifest(manifest, apply=True)
            self.assertNotIn(result['status'], {'APPLIED', 'FORCE_APPLIED'})
            self.assertFalse((root / 'published/lib_NL7').exists())

    def manifest(self, root: Path, source: Path, release_id: str) -> Path:
        run = root / "runs" / release_id
        run.mkdir(parents=True)
        path = run / "release_manifest.json"
        path.write_text(json.dumps({
            "release_id": release_id, "release_root": str(root / "published"),
            "publish_name": "lib_NL7", "latest_name": "latest_NL7", "alias": "current",
            "files": [{"source_path": str(source), "target_relpath": "LEF/top.lef", "file_type": "lef"}],
        }))
        return path

    def test_same_day_backup_replaced_and_links_not_dereferenced(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            sources = []
            for i in range(3):
                source = root / f"source{i}/top.lef"
                source.parent.mkdir()
                source.write_text(f"VERSION 5.{i} ;\n")
                sources.append(source)
            first = self.manifest(root, sources[0], "R1")
            preview = link_release_from_manifest(first)
            self.assertEqual(preview["status"], "DRY_RUN")
            self.assertFalse((root / "published").exists())
            for i, source in enumerate(sources):
                manifest = first if i == 0 else self.manifest(root, source, f"R{i+1}")
                result = link_release_from_manifest(manifest, apply=True)
                self.assertEqual(result["status"], "APPLIED")
                self.assertEqual(result["verify"]["status"], "PASS")
            published = root / "published"
            backup = published / "history" / f"lib_NL7_{datetime.now():%Y%m%d}"
            self.assertTrue((backup / "LEF/top.lef").is_symlink())
            self.assertEqual((backup / "LEF/top.lef").resolve(), sources[1])
            self.assertEqual((published / "lib_NL7/LEF/top.lef").resolve(), sources[2])
            self.assertEqual(result["created_links"][0]["previous_target"], str(sources[1]))
            self.assertEqual(result["created_links"][0]["link_action"], "REPLACE")
            self.assertEqual((published / "latest_NL7").resolve(), published / "lib_NL7")
            self.assertEqual(len(list((published / "history").iterdir())), 1)

    def test_failed_postcheck_restores_previous_release_and_daily_backup(self):
        from lib_guard.release.postcheck import verify_release_manifest
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            old = root / "old/top.lef"
            new = root / "new/top.lef"
            old.parent.mkdir()
            new.parent.mkdir()
            old.write_text("old")
            new.write_text("new")
            link_release_from_manifest(self.manifest(root, old, "R1"), apply=True)
            manifest = self.manifest(root, new, "R2")
            count = 0
            def check(*args, **kwargs):
                nonlocal count
                count += 1
                return {"status": "FAILED", "issues": []} if count == 2 else verify_release_manifest(*args, **kwargs)
            with patch("lib_guard.release.postcheck.verify_release_manifest", side_effect=check):
                result = link_release_from_manifest(manifest, apply=True)
            self.assertEqual(result["status"], "FAILED")
            self.assertEqual((root / "published/lib_NL7/LEF/top.lef").resolve(), old)
            self.assertEqual((root / "published/latest_NL7").resolve(), root / "published/lib_NL7")
            self.assertFalse(any((root / "published/history").iterdir()))

    def test_invalid_names_are_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "top.lef"
            source.write_text("old")
            path = self.manifest(root, source, "R1")
            original = json.loads(path.read_text())
            for field, value in [("publish_name", "../escape"), ("latest_name", "/tmp/escape"), ("latest_name", "lib_NL7")]:
                path.write_text(json.dumps(original | {field: value}))
                with self.assertRaises(ValueError):
                    link_release_from_manifest(path, apply=True)

    def test_backup_copy_failure_never_deletes_original(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "top.lef"
            source.write_text("old")
            link_release_from_manifest(self.manifest(root, source, "R1"), apply=True)
            with patch("lib_guard.release.linker.shutil.copytree", side_effect=OSError("backup failed")):
                result = link_release_from_manifest(self.manifest(root, source, "R2"), apply=True)
            self.assertEqual(result["status"], "FAILED")
            self.assertEqual((root / "published/lib_NL7/LEF/top.lef").resolve(), source)
            self.assertEqual((root / "published/latest_NL7").resolve(), root / "published/lib_NL7")

    def test_missing_source_does_not_replace_published_links(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "top.lef"
            source.write_text("old")
            link_release_from_manifest(self.manifest(root, source, "R1"), apply=True)
            result = link_release_from_manifest(self.manifest(root, root / "missing.lef", "R2"), apply=True)
            self.assertEqual(result["status"], "FAILED")
            self.assertEqual((root / "published/lib_NL7/LEF/top.lef").resolve(), source)

    def test_existing_daily_backup_is_restored_on_failed_publish(self):
        from lib_guard.release.postcheck import verify_release_manifest
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            sources = []
            for i in range(3):
                source = root / f"old{i}/top.lef"
                source.parent.mkdir()
                source.write_text(str(i))
                sources.append(source)
            for i in range(2):
                link_release_from_manifest(self.manifest(root, sources[i], f"R{i}"), apply=True)
            count = 0
            def check(*args, **kwargs):
                nonlocal count
                count += 1
                return {"status": "FAILED", "issues": []} if count == 2 else verify_release_manifest(*args, **kwargs)
            with patch("lib_guard.release.postcheck.verify_release_manifest", side_effect=check):
                result = link_release_from_manifest(self.manifest(root, sources[2], "R2"), apply=True)
            self.assertEqual(result["status"], "FAILED")
            self.assertEqual((root / "published/lib_NL7/LEF/top.lef").resolve(), sources[1])
            self.assertEqual((root / "published/history" / f"lib_NL7_{datetime.now():%Y%m%d}" / "LEF/top.lef").resolve(), sources[0])
