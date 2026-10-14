import tempfile
import unittest
from pathlib import Path

from lib_guard.release.bundle import iter_release_files, write_json
from lib_guard.release.linker import link_release_from_manifest


class ReleasePayloadSelectionTest(unittest.TestCase):
    def test_view_layout_and_excluded_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw = root / 'raw'
            names = ['rtl/top.sv', 'spice/top.sp', 'DFT/test.v', 'PGV/top.pgv',
                     'NDM/top.ndm', 'doc/README.md', 'lef/README.txt',
                     'bak/old.lef', 'misc/random.bin', 'lef/top.lef']
            for name in names:
                path = raw / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('fixture')
            manifest = {'release_root': str(root / 'release'), 'release_id': 'R1',
                        'libraries': [{'library_name': 'ip', 'version_id': 'v1',
                                       'source_path': str(raw)}]}
            excluded = []
            rows = iter_release_files(manifest, excluded_files=excluded)
            self.assertEqual({row['relative_path'] for row in rows},
                             {'VERILOG/top.sv', 'SPICE/top.sp', 'DFT/test.v',
                              'PGV/top.pgv', 'NDM/top.ndm', 'LEF/top.lef'})
            self.assertEqual(len(excluded), 4)
            path = root / 'manifest.json'
            write_json(path, manifest)
            result = link_release_from_manifest(path, apply=True)
            self.assertEqual(result['status'], 'APPLIED')
            self.assertEqual(result['summary']['excluded_files'], 4)
            for row in rows:
                target = root / 'release/releases/R1' / row['relative_path']
                self.assertTrue(target.is_symlink())
                self.assertEqual(target.resolve(), Path(row['source_path']))
            self.assertFalse((root / 'release/releases/R1/DOC').exists())

    def test_explicit_manifest_cannot_reintroduce_readme(self):
        manifest = {'release_root': '/tmp/release', 'files': [
            {'source_path': '/tmp/README.md', 'target_relpath': 'LEF/README.md',
             'file_type': 'lef'}]}
        excluded = []
        self.assertEqual(iter_release_files(manifest, excluded_files=excluded), [])
        self.assertEqual(len(excluded), 1)

    def test_multilibrary_collision_skips_both_but_links_other_views(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            libraries = []
            for name in ['one', 'two']:
                raw = root / name
                raw.mkdir()
                (raw / 'top.v').write_text(name)
                (raw / (name + '.lef')).write_text(name)
                (raw / 'README.md').write_text(name)
                libraries.append({'library_name': name, 'version_id': 'v1',
                                  'source_path': str(raw)})
            path = root / 'manifest.json'
            write_json(path, {'release_root': str(root / 'release'),
                              'release_id': 'R1', 'libraries': libraries})
            preview = link_release_from_manifest(path)
            result = link_release_from_manifest(path, apply=True)
            self.assertEqual(preview['status'], 'PARTIAL_DRY_RUN')
            self.assertEqual(result['status'], 'PARTIAL_APPLIED')
            self.assertEqual(result['summary']['skipped_files'], 2)
            self.assertEqual(result['summary']['excluded_files'], 2)
            self.assertFalse((root / 'release/releases/R1/VERILOG/top.v').exists())
            for name in ['one', 'two']:
                self.assertTrue((root / 'release/releases/R1/LEF' / (name + '.lef')).is_symlink())

    def test_docs_only_does_not_publish_empty_delivery(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw = root / 'raw'
            raw.mkdir()
            (raw / 'README.md').write_text('doc')
            path = root / 'manifest.json'
            write_json(path, {'release_root': str(root / 'release'), 'release_id': 'R1',
                              'libraries': [{'library_name': 'ip', 'source_path': str(raw)}]})
            result = link_release_from_manifest(path, apply=True)
            self.assertEqual(result['status'], 'FAILED')
            self.assertEqual(result['summary']['excluded_files'], 1)
            self.assertFalse((root / 'release/current').exists())
