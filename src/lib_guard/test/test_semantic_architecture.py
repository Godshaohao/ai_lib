import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from lib_guard.test.semantic_fixture import SemanticFixture, write_json


class SemanticArchitectureTest(unittest.TestCase):
    def add_corner(self, version, *, corner, relpath, rename_pin=False):
        scan = Path(version['scan']['scan_dir'])
        raw = Path(version['raw_path']) / relpath
        raw.parent.mkdir(parents=True, exist_ok=True)
        raw.write_text(corner + ('-changed' if rename_pin else ''))
        payload = json.loads((scan / 'parser_results/liberty/result.json').read_text())
        if rename_pin:
            pins = payload['data']['libraries']['L']['cells']['M']['pins']
            pins['NEW_CLK'] = pins.pop('CLK')
        payload.update(file=relpath, abs_path=str(raw), semantic_context={
            'confirmed': True, 'basis': 'controlled complete fixture', 'corner': corner, 'mode': 'functional'})
        ref = f'parser_results/liberty/{corner}.json'
        write_json(scan / ref, payload)
        tasks = json.loads((scan / 'parser_manifest.json').read_text())
        tasks['files'] = [row for row in tasks['files'] if row['file'] != relpath]
        tasks['files'].append({'file': relpath, 'file_type': 'liberty', 'parser_tasks': [{
            'parser_name': payload['parser_name'], 'parser_version': payload['parser_version'],
            'result_status': payload['status'], 'result_path': ref}]})
        write_json(scan / 'parser_manifest.json', tasks)
        inventory = json.loads((scan / 'file_inventory.json').read_text())
        inventory['files'] = [row for row in inventory['files'] if row['path'] != relpath]
        inventory['files'].append({'path': relpath, 'abs_path': str(raw), 'file_type': 'liberty',
                                  'size_bytes': raw.stat().st_size, 'mtime': raw.stat().st_mtime})
        write_json(scan / 'file_inventory.json', inventory)

    def inputs(self, root):
        fixture = SemanticFixture(root)
        fixture.version('full')
        old = root / 'old.json'
        write_json(old, fixture.manifest())
        fixture.version('fix', views=('lef',), width=1100)
        new, catalog = root / 'new.json', root / 'catalog.json'
        write_json(new, fixture.manifest([('fix', ['lef'])]))
        write_json(catalog, fixture.catalog)
        return old, new, catalog

    def test_models_assemble_without_mutating_facts_and_share_unchanged_files(self):
        from lib_guard.semantic.binding import build_effective_model
        from lib_guard.semantic.effective import resolve_effective_facts
        from lib_guard.semantic.facts import FileFactsStore
        from lib_guard.semantic.profile import load_review_profile
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            old, new, catalog = self.inputs(root)
            store = FileFactsStore(root / 'facts')
            context = json.loads(catalog.read_text())
            old_index = resolve_effective_facts(json.loads(old.read_text()), context, facts_store=store)
            new_index = resolve_effective_facts(json.loads(new.read_text()), context, facts_store=store)
            before = json.dumps(new_index, sort_keys=True)
            old_model = build_effective_model(old_index, load_review_profile())
            new_model = build_effective_model(new_index, load_review_profile())
            self.assertEqual(json.dumps(new_index, sort_keys=True), before)
            self.assertEqual(old_model['schema_version'], 'semantic_effective_model.v1')
            old_ids = {f['view']: f['fact_id'] for f in old_index['facts']}
            new_ids = {f['view']: f['fact_id'] for f in new_index['facts']}
            self.assertEqual(old_ids['liberty'], new_ids['liberty'])
            self.assertNotEqual(old_ids['lef'], new_ids['lef'])
            self.assertEqual(store.stats, {'hits': 2, 'adapted': 4})
            self.assertNotEqual(old_model['effective_digest'], new_model['effective_digest'])

    def test_results_bind_rules_mapping_and_facts_and_old_snapshots_are_read_only(self):
        from lib_guard.semantic.runner import run_semantic_review
        from lib_guard.semantic.results import load_review_snapshot
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            old, new, catalog = self.inputs(root)
            out = root / 'report'
            first = run_semantic_review(new, catalog, out, base_manifest_path=old)
            snapshot = out / 'snapshots' / first['summary']['generation']
            stamps = {p: p.stat().st_mtime_ns for p in snapshot.iterdir()}
            second = run_semantic_review(new, catalog, out, base_manifest_path=old)
            self.assertEqual(first, second)
            self.assertEqual(stamps, {p: p.stat().st_mtime_ns for p in snapshot.iterdir()})
            self.assertIn('rules_identity', second['summary'])
            self.assertIn('snapshot_manifest', second['summary']['artifacts'])
            index = json.loads((out / second['summary']['artifacts']['semantic_effective_index']).read_text())
            self.assertNotIn('facts', index['current'])
            self.assertEqual(len(index['current']['fact_refs']), 3)
            for p in root.rglob('*.json'):
                if p.is_relative_to(out):
                    continue
                p.unlink()
            restored = load_review_snapshot(out)
            self.assertEqual(restored['checks'], first['checks'])
            self.assertEqual(restored['delta'], first['delta'])
            self.assertEqual(restored['index'], first['index'])
            self.assertEqual(restored['bindings'], first['bindings'])

    def test_recompute_matches_reuse_and_tampered_snapshot_does_not_replace_pointer(self):
        from lib_guard.semantic.runner import run_semantic_review
        from lib_guard.semantic.results import load_review_snapshot
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            old, new, catalog = self.inputs(root)
            config = root / 'config.json'
            document = {'schema_version': 'semantic_review_config.v1', 'profiles': {'default': {}},
                        'facts_cache': {'reuse': True, 'directory': 'shared_facts'}}
            write_json(config, document)
            out = root / 'report'
            first = run_semantic_review(new, catalog, out, base_manifest_path=old, profile_config_path=config)
            document['facts_cache']['reuse'] = False
            write_json(config, document)
            rebuilt = run_semantic_review(new, catalog, out, base_manifest_path=old, profile_config_path=config)
            self.assertEqual(first, rebuilt)
            target = out / first['summary']['artifacts']['check_results']
            original = target.read_bytes()
            write_json(target, {'checks': [], 'delta': []})
            pointer = (out / 'summary.json').read_bytes()
            with self.assertRaisesRegex(ValueError, '快照'):
                load_review_snapshot(out)
            with self.assertRaisesRegex(ValueError, '快照'):
                run_semantic_review(new, catalog, out, base_manifest_path=old, profile_config_path=config)
            self.assertEqual((out / 'summary.json').read_bytes(), pointer)
            self.assertNotEqual(target.read_bytes(), original)

    def test_rule_code_change_publishes_new_generation_without_modifying_old(self):
        from lib_guard.semantic.runner import run_semantic_review
        from lib_guard.semantic.model import implementation_identity
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            old, new, catalog = self.inputs(root)
            out = root / 'report'
            first = run_semantic_review(new, catalog, out, base_manifest_path=old)
            saved = (out / first['summary']['artifacts']['check_results']).read_bytes()
            actual = implementation_identity('lib_guard.semantic.checks')
            actual['lib_guard.semantic.checks'] = 'sha256:changed-rule'
            with patch('lib_guard.semantic.runner.implementation_identity', return_value=actual):
                changed = run_semantic_review(new, catalog, out, base_manifest_path=old)
            self.assertNotEqual(changed['summary']['generation'], first['summary']['generation'])
            self.assertEqual((out / first['summary']['artifacts']['check_results']).read_bytes(), saved)

    def test_selected_and_unselected_corner_updates_use_same_scope(self):
        from lib_guard.semantic.runner import run_semantic_review
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            fixture = SemanticFixture(root)
            full = fixture.version('full')
            self.add_corner(full, corner='TT', relpath='liberty/M.lib')
            self.add_corner(full, corner='FF', relpath='liberty/M_ff.lib')
            old = root / 'old.json'
            write_json(old, fixture.manifest())
            config = root / 'config.json'
            write_json(config, {'schema_version': 'semantic_review_config.v1', 'profiles': {'default': {
                'liberty': {'selected': [{'corner': 'TT', 'mode': 'functional', 'files': '*.lib'}]},
                'checks': ['SIGNAL_PORT_SET', 'LIB_PORT_DELTA']}}})
            for corner, relpath in [('TT', 'liberty/M.lib'), ('FF', 'liberty/M_ff.lib')]:
                with self.subTest(corner=corner):
                    fix = fixture.version('fix_' + corner, views=('liberty',))
                    self.add_corner(fix, corner=corner, relpath=relpath, rename_pin=True)
                    if corner == 'FF':
                        path = Path(fix['scan']['scan_dir']) / 'file_inventory.json'
                        inv = json.loads(path.read_text())
                        inv['files'] = [row for row in inv['files'] if row['path'] != 'liberty/M.lib']
                        write_json(path, inv)
                    new, catalog = root / f'{corner}.json', root / 'catalog.json'
                    write_json(new, fixture.manifest([('fix_' + corner, ['liberty'])]))
                    write_json(catalog, fixture.catalog)
                    result = run_semantic_review(new, catalog, root / ('report_' + corner),
                        base_manifest_path=old, profile_config_path=config)
                    signal = next(row for row in result['checks'] if row['check_id'] == 'SIGNAL_PORT_SET')
                    self.assertEqual(signal['status'], 'FAIL' if corner == 'TT' else 'PASS')
                    delta = next(row for row in result['delta'] if row['attribute'] == 'signal_ports')
                    self.assertEqual(delta['corner'], 'TT')
                    self.assertEqual(delta['status'], 'CHANGED' if corner == 'TT' else 'UNCHANGED')
                    self.assertEqual(result['summary']['scope']['current']['excluded_files'], 1)
                    self.assertTrue(any(row['source_version'] == 'fix_' + corner for row in result['index']['files']))

    def test_interrupted_snapshot_write_can_resume_without_switching_old_pointer(self):
        from lib_guard.atomic import atomic_write_json
        from lib_guard.semantic.runner import run_semantic_review
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            old, new, catalog = self.inputs(root)
            out = root / 'report'
            first = run_semantic_review(new, catalog, out, base_manifest_path=old)
            before = (out / 'summary.json').read_bytes()
            config = root / 'config.json'
            write_json(config, {'schema_version': 'semantic_review_config.v1',
                                'profiles': {'default': {'tolerance_um': 0.2}}})
            def fail_midway(path, value):
                if Path(path).name == 'macro_bindings.json':
                    raise OSError('simulated interrupted write')
                return atomic_write_json(path, value)
            with patch('lib_guard.semantic.results.atomic_write_json', side_effect=fail_midway):
                with self.assertRaises(OSError):
                    run_semantic_review(new, catalog, out, base_manifest_path=old, profile_config_path=config)
            self.assertEqual((out / 'summary.json').read_bytes(), before)
            self.assertEqual(len(list((out / 'snapshots').glob('*/snapshot.json'))), 1)
            resumed = run_semantic_review(new, catalog, out, base_manifest_path=old, profile_config_path=config)
            self.assertNotEqual(resumed['summary']['generation'], first['summary']['generation'])
            self.assertEqual(len(list((out / 'snapshots').glob('*/snapshot.json'))), 2)

    def test_facts_storage_failure_does_not_publish_an_incomplete_replacement(self):
        from lib_guard.semantic.runner import run_semantic_review
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            old, new, catalog = self.inputs(root)
            out = root / 'report'
            first = run_semantic_review(new, catalog, out, base_manifest_path=old)
            before = (out / 'summary.json').read_bytes()
            parser = root / 'scan/fix/parser_results/lef/result.json'
            payload = json.loads(parser.read_text())
            payload['data']['macros']['M']['size']['x'] = 1200
            write_json(parser, payload)
            with patch('lib_guard.semantic.facts.atomic_write_json', side_effect=PermissionError('read-only facts store')):
                with self.assertRaises(RuntimeError):
                    run_semantic_review(new, catalog, out, base_manifest_path=old)
            self.assertEqual((out / 'summary.json').read_bytes(), before)
            self.assertTrue((out / first['summary']['artifacts']['snapshot_manifest']).is_file())
