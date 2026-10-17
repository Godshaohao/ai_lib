import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from lib_guard.test.semantic_fixture import SemanticFixture, write_json


class SemanticRunnerTest(unittest.TestCase):
    def test_report_summarizes_confirmed_changes_without_raw_status_dictionary(self):
        from lib_guard.semantic.runner import run_semantic_review
        from lib_guard.test.test_web_semantic_review import make_workspace
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _, manifests = make_workspace(root)
            catalog, config = root / 'catalog/catalog.json', root / 'profile.json'
            write_json(config, {'schema_version': 'semantic_review_config.v1',
                'profiles': {'lef_only': {'required_views': ['lef'], 'checks': ['LEF_INTERFACE_DELTA']}}})
            result = run_semantic_review(manifests['E2'], catalog, root / 'report', base_manifest_path=manifests['E1'],
                                         profile_config_path=config, profile_name='lef_only')
            self.assertGreater(result['summary']['delta_counts'].get('CHANGED', 0), 0)
            markdown = (root / 'report' / result['summary']['artifacts']['markdown']).read_text()
            self.assertIn('确认变化', markdown)
            self.assertNotIn('版本变化：{', markdown)
            self.assertNotIn('检查属性汇总：{', markdown)
            self.assertIn('A：INPUT → OUTPUT', markdown)
            self.assertNotIn("'pins':", markdown)

    def test_no_base_reports_one_limitation_without_per_macro_delta(self):
        from lib_guard.semantic.runner import run_semantic_review
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            fixture = SemanticFixture(td)
            fixture.version('full')
            manifest, catalog, config = (root / name for name in ('effective.json', 'catalog.json', 'profile.json'))
            write_json(manifest, fixture.manifest())
            write_json(catalog, fixture.catalog)
            write_json(config, {'schema_version': 'semantic_review_config.v1',
                'profiles': {'lef_only': {'required_views': ['lef'],
                    'checks': ['LEF_PHYSICAL_DELTA', 'LEF_INTERFACE_DELTA']}}})
            result = run_semantic_review(manifest, catalog, root / 'report', profile_config_path=config,
                                         profile_name='lef_only')
            self.assertEqual(result['delta'], [])
            self.assertEqual(result['summary']['delta_counts'], {})
            markdown = (root / 'report' / result['summary']['artifacts']['markdown']).read_text()
            self.assertIn('## 结论', markdown)
            self.assertIn('未选择基准组合', markdown)
            self.assertIn('## 下一步', markdown)
            self.assertNotIn('检查结果：{}', markdown)
            self.assertIn('尚未执行独立检查', markdown)
            self.assertNotIn('本次独立检查没有需处理项', markdown)

    def test_repeated_web_reports_share_bytes_without_sharing_lifecycle(self):
        from lib_guard.semantic.results import load_review_snapshot
        from lib_guard.semantic.runner import run_semantic_review
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            fixture = SemanticFixture(td)
            fixture.version('full')
            manifest, catalog = root / 'effective.json', root / 'catalog.json'
            write_json(manifest, fixture.manifest())
            write_json(catalog, fixture.catalog)
            store = root / 'artifact_store'
            first = root / 'job_a/semantic_review'
            second = root / 'job_b/semantic_review'
            one = run_semantic_review(manifest, catalog, first, artifact_store=store)
            two = run_semantic_review(manifest, catalog, second, artifact_store=store)
            self.assertEqual(one['summary']['generation'], two['summary']['generation'])
            first_fact = next((first / 'facts').rglob('*.json'))
            second_fact = second / first_fact.relative_to(first)
            self.assertEqual(first_fact.stat().st_ino, second_fact.stat().st_ino)
            left = first / one['summary']['artifacts']['check_results']
            right = second / two['summary']['artifacts']['check_results']
            self.assertEqual(left.stat().st_ino, right.stat().st_ino)
            self.assertEqual(right.stat().st_mode & 0o222, 0)
            left = first / one['summary']['artifacts']['macro_bindings']
            right = second / two['summary']['artifacts']['macro_bindings']
            self.assertEqual(left.stat().st_ino, right.stat().st_ino)
            frozen = json.loads((second / two['summary']['artifacts']['semantic_effective_index']).read_text())
            self.assertFalse(Path(frozen['current']['fact_refs'][0]['fact_ref']).is_absolute())
            relocated = root / 'relocated'
            shutil.copytree(second, relocated)
            shutil.rmtree(first.parent)
            self.assertEqual(load_review_snapshot(second)['summary']['generation'], two['summary']['generation'])
            shutil.rmtree(second.parent)
            self.assertEqual(load_review_snapshot(relocated)['summary']['generation'], two['summary']['generation'])

    def test_internal_protected_snapshot_target_is_rejected(self):
        from lib_guard.semantic.runner import run_semantic_review
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            fixture = SemanticFixture(td)
            version = fixture.version('full')
            manifest, catalog = root / 'inputs/effective.json', root / 'inputs/catalog.json'
            write_json(manifest, fixture.manifest())
            write_json(catalog, fixture.catalog)
            probe = run_semantic_review(manifest, catalog, root / 'probe')
            snapshots = root / 'snapshots'
            snapshots.mkdir()
            (snapshots / probe['summary']['generation']).symlink_to(Path(version['raw_path']))
            with self.assertRaises(ValueError):
                run_semantic_review(manifest, catalog, root)
            self.assertFalse((Path(version['raw_path']) / 'check_results.json').exists())

    def test_output_snapshot_symlink_cannot_redirect_writes(self):
        from lib_guard.semantic.runner import run_semantic_review
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            fixture = SemanticFixture(td)
            fixture.version('full')
            manifest, catalog = root / 'effective.json', root / 'catalog.json'
            write_json(manifest, fixture.manifest())
            write_json(catalog, fixture.catalog)
            out, target = root / 'out', root / 'protected'
            out.mkdir()
            target.mkdir()
            (out / 'snapshots').symlink_to(target)
            with self.assertRaises(ValueError):
                run_semantic_review(manifest, catalog, out)
            self.assertEqual(list(target.iterdir()), [])

    def test_output_cannot_overwrite_mapping_or_version_path_raw(self):
        from lib_guard.semantic.runner import run_semantic_review
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            fixture = SemanticFixture(td)
            version = fixture.version('full')
            manifest, catalog = root / 'effective.json', root / 'catalog.json'
            write_json(manifest, fixture.manifest())
            version['version_path'] = version.pop('raw_path')
            write_json(catalog, fixture.catalog)
            out = root / 'out'
            mapping = out / 'summary.json'
            write_json(mapping, {'confirmed': True})
            before = mapping.read_bytes()
            with self.assertRaises(ValueError):
                run_semantic_review(manifest, catalog, out, mapping_path=mapping)
            self.assertEqual(mapping.read_bytes(), before)
            with self.assertRaises(ValueError):
                run_semantic_review(manifest, catalog, version['version_path'])

    def test_new_side_alias_does_not_require_a_matching_old_object(self):
        from lib_guard.semantic.runner import run_semantic_review
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            fixture = SemanticFixture(td)
            fixture.version('full')
            version = fixture.version('fix', views=('liberty',))
            parser = Path(version['scan']['scan_dir']) / 'parser_results/liberty/result.json'
            payload = json.loads(parser.read_text())
            cells = payload['data']['libraries']['L']['cells']
            cells['OTHER'] = cells.pop('M')
            write_json(parser, payload)
            old, new, catalog, mapping = [root / name for name in ('old.json', 'new.json', 'catalog.json', 'mapping.json')]
            write_json(old, fixture.manifest())
            write_json(new, fixture.manifest([('fix', ['liberty'])]))
            write_json(catalog, fixture.catalog)
            write_json(mapping, {'confirmed': True, 'macro_aliases': [{'view': 'liberty', 'object': 'OTHER', 'macro': 'M'}]})
            result = run_semantic_review(new, catalog, root / 'review', base_manifest_path=old, mapping_path=mapping)
            self.assertEqual(result['bindings'][0]['status'], 'CONFIRMED')

    def test_real_scan_pipeline_missing_pin_is_not_fake_pass(self):
        from lib_guard.test.semantic_rehearsal import rehearse
        with tempfile.TemporaryDirectory() as td:
            result, audit = rehearse(td)
            self.assertEqual(audit['mutations'], [])
            ports = next(row for row in result['checks'] if row['check_id'] == 'SIGNAL_PORT_SET')
            self.assertEqual(ports['status'], 'FAIL')
            self.assertEqual(ports['reason_code'], 'PORT_SET_MISMATCH')
            delta = next(row for row in result['delta'] if row['attribute'] == 'width_um')
            self.assertEqual(delta['status'], 'CHANGED')
            self.assertEqual(delta['new_evidence']['source_version'], 'fix')

    def test_read_only_repeatability_and_multicorner_T05_T28_T29(self):
        from lib_guard.semantic.runner import run_semantic_review
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            fixture = SemanticFixture(td)
            version = fixture.version('full')
            scan = Path(version['scan']['scan_dir'])
            parser_path = scan / 'parser_results/liberty/result.json'
            tt = json.loads(parser_path.read_text())
            tt['semantic_context'] = {'confirmed': True, 'basis': 'controlled fixture', 'corner': 'TT'}
            write_json(parser_path, tt)
            raw_ff = Path(version['raw_path']) / 'liberty/M_ff.lib'
            raw_ff.write_text('ff fixture')
            ff = json.loads(json.dumps(tt))
            ff.update(file='liberty/M_ff.lib', abs_path=str(raw_ff), semantic_context={'confirmed': True, 'basis': 'controlled fixture', 'corner': 'FF'})
            write_json(scan / 'parser_results/liberty/ff.json', ff)
            task_path = scan / 'parser_manifest.json'
            task_manifest = json.loads(task_path.read_text())
            task_manifest['files'].append({'file': ff['file'], 'file_type': 'liberty', 'parser_tasks': [{
                'parser_name': ff['parser_name'], 'parser_version': ff['parser_version'],
                'result_status': ff['status'], 'result_path': 'parser_results/liberty/ff.json'}]})
            write_json(task_path, task_manifest)
            inventory_path = scan / 'file_inventory.json'
            inventory = json.loads(inventory_path.read_text())
            inventory['files'].append({'path': ff['file'], 'abs_path': str(raw_ff), 'file_type': 'liberty',
                'size_bytes': raw_ff.stat().st_size, 'mtime': raw_ff.stat().st_mtime})
            write_json(inventory_path, inventory)
            manifest = fixture.manifest()
            catalog_path, manifest_path = root / 'catalog.json', root / 'effective_manifest.json'
            write_json(catalog_path, fixture.catalog)
            write_json(manifest_path, manifest)
            for name in ('catalog_runtime.json', 'current_effective.json', 'release_manifest.json'):
                write_json(root / name, {'keep': name})
            protected = [catalog_path, manifest_path] + [root / name for name in ('catalog_runtime.json', 'current_effective.json', 'release_manifest.json')]
            before = {str(path): path.read_bytes() for path in protected}
            out = root / 'diagnostics'
            unrelated = out / 'other_library.txt'
            out.mkdir()
            unrelated.write_text('keep')
            first = run_semantic_review(manifest_path, catalog_path, out)
            second = run_semantic_review(manifest_path, catalog_path, out)
            self.assertEqual(first, second)
            self.assertEqual(first['summary']['counts']['PASS'], 4)
            self.assertEqual(len(first['bindings'][0]['observations']), 4)
            self.assertEqual(before, {str(path): path.read_bytes() for path in protected})
            self.assertEqual(unrelated.read_text(), 'keep')
            published = json.loads((out / 'summary.json').read_text())
            self.assertTrue((out / published['artifacts']['check_results']).is_file())

    def test_cli_advisory_failure_case_and_missing_base_T08_T27(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            fixture = SemanticFixture(td)
            version = fixture.version('full')
            parser_path = Path(version['scan']['scan_dir']) / 'parser_results/lef/result.json'
            payload = json.loads(parser_path.read_text())
            del payload['data']['macros']['M']['pins']['CLK']
            write_json(parser_path, payload)
            manifest, catalog = root / 'effective.json', root / 'catalog.json'
            write_json(manifest, fixture.manifest())
            write_json(catalog, fixture.catalog)
            command = [sys.executable, '-m', 'lib_guard.semantic.cli', '--effective-manifest', str(manifest),
                       '--catalog', str(catalog), '--out', str(root / 'report')]
            proc = subprocess.run(command, text=True, capture_output=True)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            summary = json.loads(proc.stdout)
            self.assertGreater(summary['counts']['FAIL'], 0)
            self.assertEqual(summary['delta_context'], 'NO_BASE_EFFECTIVE')
            checks = json.loads((root / 'report' / summary['artifacts']['check_results']).read_text())['checks']
            self.assertTrue(any(row['check_id'] == 'SIGNAL_PORT_SET' and row['status'] == 'FAIL' for row in checks))

    def test_failed_snapshot_publication_retains_old_generation(self):
        from lib_guard.semantic.runner import run_semantic_review
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            fixture = SemanticFixture(td)
            fixture.version('full')
            manifest, catalog = root / 'effective.json', root / 'catalog.json'
            write_json(manifest, fixture.manifest())
            write_json(catalog, fixture.catalog)
            out = root / 'out'
            run_semantic_review(manifest, catalog, out)
            before = (out / 'summary.json').read_bytes()
            with patch('lib_guard.semantic.runner.atomic_write_json', side_effect=OSError('simulated disk full')):
                with self.assertRaises(OSError):
                    run_semantic_review(manifest, catalog, out)
            self.assertEqual((out / 'summary.json').read_bytes(), before)
