import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest


class SemanticScanReuseTest(unittest.TestCase):
    def test_hashless_files_in_different_roots_cannot_share_parser_cache(self):
        from lib_guard.scan.scanner import ScanRunner
        runner = ScanRunner(SimpleNamespace(root_path='.', out_dir='unused'))
        task = SimpleNamespace(parser_name='LefParser', parser_version='2.0')
        context = SimpleNamespace(scan_mode='scan', schema_version='1.0', tool_version='0.5.0')
        record = {'path': 'lef/M.lef', 'hash': None, 'size_bytes': 42, 'mtime': 100}
        left = runner._parser_cache_key({**record, 'abs_path': '/library/E2/lef/M.lef'}, task, '1.0', context)
        right = runner._parser_cache_key({**record, 'abs_path': '/library/E3/lef/M.lef'}, task, '1.0', context)
        self.assertNotEqual(left, right)

    def test_real_parser_reuse_rebinds_source_and_keeps_shared_fact_identity(self):
        from lib_guard.effective.manifest import build_effective_manifest
        from lib_guard.scan.report import load_parser_results
        from lib_guard.scan.scanner import ScanRunner
        from lib_guard.semantic.effective import resolve_effective_facts
        from lib_guard.semantic.facts import FileFactsStore
        from lib_guard.test.semantic_rehearsal import LEF
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            catalog = {'libraries': [{'library_id': 'ip/demo', 'library_name': 'demo', 'versions': []}]}
            indices, stats = [], []
            store = FileFactsStore(root / 'facts')
            for version, filename in [('full', 'M.lef'), ('same', 'renamed.lef')]:
                raw, scan = root / 'raw' / version, root / 'scan' / version
                raw.mkdir(parents=True)
                (raw / filename).write_text(LEF)
                result = ScanRunner(SimpleNamespace(root_path=str(raw), out_dir=str(scan),
                    library_type='ip', library_name='demo', version=version, scan_mode='scan',
                    scan_id=version, state_dir=str(root / 'state'), cache_dir=str(root / 'parser_cache'),
                    no_progress=True, parse_jobs=1, hash_policy='full', parse_file_types=['lef'],
                    tool_version='0.5.0', schema_version='1.0')).run()
                meta = json.loads((scan / 'scan_meta.json').read_text())
                stats.append(meta['stats'])
                self.assertEqual(meta['status'], 'PASS')
                catalog['libraries'][0]['versions'].append({'version_id': version, 'raw_path': str(raw),
                    'scan': {'scan_dir': str(scan), 'snapshot_identity': meta['snapshot_identity']}})
                payload = next(iter(load_parser_results(scan).values()))
                self.assertEqual(payload['file'], filename)
                self.assertEqual(Path(payload['abs_path']).resolve(), raw / filename)
                index = resolve_effective_facts(build_effective_manifest(catalog, 'demo', version, []),
                                                catalog, facts_store=store)
                self.assertEqual(index['files'][0]['fact_status'], 'AVAILABLE')
                indices.append(index)
            self.assertEqual(stats[1]['parser_cache_hits'], 1)
            self.assertEqual(stats[1]['parsed_files'], 0)
            self.assertEqual(indices[0]['facts'][0]['fact_id'], indices[1]['facts'][0]['fact_id'])
            self.assertEqual(indices[1]['facts'][0]['file_identity']['source_version'], 'same')
