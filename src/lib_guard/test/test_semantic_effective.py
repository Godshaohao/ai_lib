import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from lib_guard.test.semantic_fixture import SemanticFixture, write_json


class SemanticEffectiveTest(unittest.TestCase):
    def test_task_status_contradiction_and_missing_version_rejected(self):
        from lib_guard.semantic.effective import resolve_effective_facts
        with tempfile.TemporaryDirectory() as td:
            fixture = SemanticFixture(td)
            version = fixture.version('full')
            path = Path(version['scan']['scan_dir']) / 'parser_manifest.json'
            original = json.loads(path.read_text())
            for change in ({'status': 'FAILED'}, {'parser_version': None}):
                tasks = copy.deepcopy(original)
                for file in tasks['files']:
                    file['parser_tasks'][0].update(change)
                write_json(path, tasks)
                result = resolve_effective_facts(fixture.manifest(), fixture.catalog)
                self.assertFalse(result['facts'])

    def test_task_index_linear_not_payload_times_manifest(self):
        from lib_guard.semantic.effective import resolve_effective_facts, _read
        class CountedList(list):
            count = 0
            def __iter__(self):
                self.count += 1
                return super().__iter__()
        with tempfile.TemporaryDirectory() as td:
            fixture = SemanticFixture(td)
            version = fixture.version('full')
            tasks = _read(Path(version['scan']['scan_dir']) / 'parser_manifest.json')
            counted = CountedList(tasks['files'])
            tasks['files'] = counted
            def read(path):
                return tasks if Path(path).name == 'parser_manifest.json' else _read(path)
            with patch('lib_guard.semantic.effective._read', side_effect=read):
                resolve_effective_facts(fixture.manifest(), fixture.catalog)
            self.assertEqual(counted.count, 1)

    def test_mixed_scan_generation_and_unplanned_parser_rejected(self):
        from lib_guard.semantic.effective import resolve_effective_facts
        with tempfile.TemporaryDirectory() as td:
            fixture = SemanticFixture(td)
            version = fixture.version('full')
            manifest = fixture.manifest()
            scan = Path(version['scan']['scan_dir'])
            path = scan / 'file_inventory.json'
            inventory = json.loads(path.read_text())
            inventory['scan_id'] = 'OLD'
            write_json(path, inventory)
            result = resolve_effective_facts(manifest, fixture.catalog)
            self.assertFalse(result['facts'])
            self.assertTrue(all(row['reason_code'] == 'SCAN_GENERATION_MISMATCH' for row in result['files']))
            inventory['scan_id'] = 'full'
            write_json(path, inventory)
            write_json(scan / 'parser_manifest.json', {'scan_id': 'full', 'files': []})
            result = resolve_effective_facts(manifest, fixture.catalog)
            self.assertFalse(result['facts'])

    def test_source_cannot_escape_declared_version(self):
        from lib_guard.semantic.effective import resolve_effective_facts
        with tempfile.TemporaryDirectory() as td:
            fixture = SemanticFixture(td)
            version = fixture.version('full')
            fixture.version('fix', views=('lef',))
            manifest = fixture.manifest()
            raw, scan = Path(version['raw_path']), Path(version['scan']['scan_dir'])
            (raw / 'lef/M.lef').unlink()
            (raw / 'lef/M.lef').symlink_to(fixture.root / 'raw/fix/lef/M.lef')
            inventory_path = scan / 'file_inventory.json'
            inventory = json.loads(inventory_path.read_text())
            inventory['files'][0]['abs_path'] = str((raw / 'lef/M.lef').resolve())
            write_json(inventory_path, inventory)
            parser_path = scan / 'parser_results/lef/result.json'
            payload = json.loads(parser_path.read_text())
            payload['abs_path'] = str((raw / 'lef/M.lef').resolve())
            write_json(parser_path, payload)
            result = resolve_effective_facts(manifest, fixture.catalog)
            self.assertEqual(next(row for row in result['files'] if row['file_type'] == 'lef')['reason_code'], 'SOURCE_OUTSIDE_VERSION')

    def test_symlink_aliases_require_logical_source_not_only_realpath(self):
        from lib_guard.semantic.effective import resolve_effective_facts
        with tempfile.TemporaryDirectory() as td:
            fixture = SemanticFixture(td)
            version = fixture.version('full')
            raw, scan = Path(version['raw_path']), Path(version['scan']['scan_dir'])
            (raw / 'lef/alias.lef').symlink_to('M.lef')
            inventory_path = scan / 'file_inventory.json'
            inventory = json.loads(inventory_path.read_text())
            old = next(row for row in inventory['files'] if row['file_type'] == 'lef')
            inventory['files'].append({**old, 'path': 'lef/alias.lef'})
            write_json(inventory_path, inventory)
            result = resolve_effective_facts(fixture.manifest(), fixture.catalog)
            selected = next(row for row in result['files'] if row['effective_relpath'] == 'lef/M.lef')
            alias = next(row for row in result['files'] if row['effective_relpath'] == 'lef/alias.lef')
            self.assertEqual(selected['fact_status'], 'AVAILABLE')
            self.assertEqual(alias['reason_code'], 'PARSER_RESULT_MISSING')

    def test_parser_index_built_once_not_per_selected_file_T30(self):
        from lib_guard.semantic.effective import resolve_effective_facts, _result_source
        with tempfile.TemporaryDirectory() as td:
            fixture = SemanticFixture(td)
            fixture.version('full')
            with patch('lib_guard.semantic.effective._result_source', wraps=_result_source) as lookup:
                resolve_effective_facts(fixture.manifest(), fixture.catalog)
            self.assertEqual(lookup.call_count, 3)

    def test_invalid_scan_index_is_not_reloaded_for_each_file(self):
        from lib_guard.semantic.effective import resolve_effective_facts, _index_scan
        with tempfile.TemporaryDirectory() as td:
            fixture = SemanticFixture(td)
            version = fixture.version('full')
            write_json(Path(version['scan']['scan_dir']) / 'parser_manifest.json', {'scan_id': 'OLD'})
            with patch('lib_guard.semantic.effective._index_scan', wraps=_index_scan) as lookup:
                result = resolve_effective_facts(fixture.manifest(), fixture.catalog)
            self.assertFalse(result['facts'])
            self.assertEqual(lookup.call_count, 1)

    def test_final_full_fix_selection_and_delta_T18(self):
        from lib_guard.semantic.effective import resolve_effective_facts
        from lib_guard.semantic.binding import bind_macros
        from lib_guard.semantic.checks import compare_bindings
        with tempfile.TemporaryDirectory() as td:
            fixture = SemanticFixture(td)
            fixture.version('full')
            fixture.version('fix', views=('lef',), width=1100)
            old = resolve_effective_facts(fixture.manifest(), fixture.catalog)
            new = resolve_effective_facts(fixture.manifest([('fix', ['lef'])]), fixture.catalog)
            sources = {item['file_identity']['file_type']: item['file_identity']['source_version'] for item in new['facts']}
            self.assertEqual(sources, {'lef': 'fix', 'liberty': 'full', 'verilog': 'full'})
            delta = next(row for row in compare_bindings(bind_macros(old['facts']), bind_macros(new['facts'])) if row['attribute'] == 'width_um')
            self.assertEqual(delta['status'], 'CHANGED')
            self.assertEqual(delta['new_evidence']['source_version'], 'fix')

    def test_order_and_tombstones_T19_T20(self):
        from lib_guard.semantic.effective import resolve_effective_facts
        with tempfile.TemporaryDirectory() as td:
            fixture = SemanticFixture(td)
            fixture.version('full')
            for name in ('fix1', 'fix2'):
                fixture.version(name, views=('lef',))
            for first, second in [('fix1', 'fix2'), ('fix2', 'fix1')]:
                result = resolve_effective_facts(fixture.manifest([(first, ['lef']), (second, ['lef'])]), fixture.catalog)
                lef = next(row for row in result['files'] if row['file_type'] == 'lef')
                self.assertEqual(lef['source_version'], second)
            result = resolve_effective_facts(fixture.manifest(delete_files=['lef/M.lef']), fixture.catalog)
            self.assertNotIn('lef', [row['file_type'] for row in result['files']])

    def test_legacy_and_no_cross_version_fallback_T21_T22(self):
        from lib_guard.semantic.effective import resolve_effective_facts
        with tempfile.TemporaryDirectory() as td:
            fixture = SemanticFixture(td)
            fixture.version('full', legacy=True)
            fix = fixture.version('fix', views=('lef',))
            result = resolve_effective_facts(fixture.manifest(), fixture.catalog)
            self.assertEqual(len(result['facts']), 3)
            (Path(fix['scan']['scan_dir']) / 'parser_results/lef/result.json').unlink()
            result = resolve_effective_facts(fixture.manifest([('fix', ['lef'])]), fixture.catalog)
            lef = next(row for row in result['files'] if row['file_type'] == 'lef')
            self.assertEqual(lef['fact_status'], 'NOT_CHECKED')
            self.assertEqual(lef['reason_code'], 'PARSER_RESULT_MISSING')

    def test_stale_source_and_snapshot_T23(self):
        from lib_guard.semantic.effective import resolve_effective_facts
        with tempfile.TemporaryDirectory() as td:
            fixture = SemanticFixture(td)
            version = fixture.version('full')
            manifest = fixture.manifest()
            (Path(version['raw_path']) / 'lef/M.lef').write_text('changed content size')
            result = resolve_effective_facts(manifest, fixture.catalog)
            self.assertEqual(next(row for row in result['files'] if row['file_type'] == 'lef')['reason_code'], 'STALE_SOURCE_METADATA')
            meta_path = Path(version['scan']['scan_dir']) / 'scan_meta.json'
            meta = json.loads(meta_path.read_text())
            meta['snapshot_identity']['digest'] = 'sha256:other'
            write_json(meta_path, meta)
            result = resolve_effective_facts(manifest, fixture.catalog)
            self.assertTrue(all(row['fact_status'] == 'NOT_CHECKED' for row in result['files']))

    def test_corrupt_manifest_and_wrong_parser_path_T24(self):
        from lib_guard.semantic.effective import resolve_effective_facts
        with tempfile.TemporaryDirectory() as td:
            fixture = SemanticFixture(td)
            version = fixture.version('full')
            manifest = fixture.manifest()
            broken = copy.deepcopy(manifest)
            broken['identity']['digest'] = 'sha256:bad'
            result = resolve_effective_facts(broken, fixture.catalog)
            self.assertEqual(result['effective_integrity'], 'MISMATCH')
            self.assertFalse(result['facts'])
            parser = Path(version['scan']['scan_dir']) / 'parser_results/lef/result.json'
            payload = json.loads(parser.read_text())
            payload['abs_path'] = str(Path(td) / 'somewhere_else/M.lef')
            write_json(parser, payload)
            result = resolve_effective_facts(manifest, fixture.catalog)
            self.assertEqual(next(row for row in result['files'] if row['file_type'] == 'lef')['reason_code'], 'PARSER_RESULT_MISSING')

    def test_no_raw_reads_or_walk_or_hash_T30(self):
        from lib_guard.semantic.effective import resolve_effective_facts
        with tempfile.TemporaryDirectory() as td:
            fixture = SemanticFixture(td)
            fixture.version('full')
            manifest = fixture.manifest()
            read_text = Path.read_text
            def guarded(path, *args, **kwargs):
                if '/raw/' in str(path):
                    self.fail('semantic resolver reread RAW')
                return read_text(path, *args, **kwargs)
            with patch.object(Path, 'read_text', guarded), patch('os.walk', side_effect=AssertionError('RAW walk')):
                result = resolve_effective_facts(manifest, fixture.catalog)
            self.assertEqual(len(result['facts']), 3)
