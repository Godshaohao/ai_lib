import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from lib_guard.test.semantic_fixture import SemanticFixture, write_json


class SemanticProfileTest(unittest.TestCase):
    def test_same_macro_variants_do_not_complete_each_others_corners(self):
        from lib_guard.semantic.adapters import adapt_result
        from lib_guard.semantic.binding import build_effective_model
        from lib_guard.semantic.profile import load_review_profile
        from lib_guard.test.test_semantic_adapter import parser_result
        profile = load_review_profile(profile_name='ip_basic')
        profile['config']['checks'] = ['MACRO_BINDING', 'SIGNAL_PORT_SET']
        profile['config']['flag_policy'] = {}
        facts = []
        contexts = []
        for variant, corner in [('v1', 'TT'), ('v2', 'SS')]:
            for view in ('lef', 'liberty', 'verilog'):
                rel = variant + '/M.' + {'lef': 'lef', 'liberty': 'lib', 'verilog': 'v'}[view]
                facts.append(adapt_result(parser_result(view), {'file_type': view, 'library_id': 'ip/demo',
                    'effective_relpath': rel, 'source_relpath': rel, 'parser_result_ref': rel}))
                contexts.append({'view': view, 'files': [rel], 'variant': variant,
                                 **({'corner': corner, 'mode': 'functional'} if view == 'liberty' else {})})
        index = {'library_id': 'ip/demo', 'effective_digest': 'test', 'facts': facts,
                 'files': [{'effective_relpath': fact['file_identity']['effective_relpath']} for fact in facts]}
        mapping = {'confirmed': True, 'library_id': 'ip/demo', 'basis': 'fixture variants', 'file_contexts': contexts}
        model = build_effective_model(index, profile, mapping=mapping)
        self.assertEqual(len(model['scope']['missing_contexts']), 2)
        self.assertEqual({(row['variant'], row['selection']['corner']) for row in model['scope']['missing_contexts']}, {('v1', 'SS'), ('v2', 'TT')})
        self.assertTrue(all(row['status'] == 'UNRESOLVED' for row in model['bindings']))

    def test_macro_filter_preserves_failed_file_evidence(self):
        from lib_guard.semantic.runner import run_semantic_review
        from lib_guard.effective.manifest import build_effective_manifest
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            current, _, catalog = self.setup_inputs(root)
            raw = root / 'raw/full/verilog/unknown.v'
            raw.write_text('unparsed source')
            scan = root / 'scan/full'
            reference = scan / 'parser_results/verilog/unknown.json'
            write_json(reference, {'parser_name': 'VerilogParser', 'parser_version': '2.0', 'file_type': 'verilog',
                'file': 'verilog/unknown.v', 'abs_path': str(raw), 'status': 'FAILED', 'data': {}})
            inventory_path, tasks_path = scan / 'file_inventory.json', scan / 'parser_manifest.json'
            inventory, tasks = json.loads(inventory_path.read_text()), json.loads(tasks_path.read_text())
            inventory['files'].append({'path': 'verilog/unknown.v', 'abs_path': str(raw), 'file_type': 'verilog',
                'size_bytes': raw.stat().st_size, 'mtime': raw.stat().st_mtime})
            tasks['files'].append({'file': 'verilog/unknown.v', 'file_type': 'verilog', 'parser_tasks': [{
                'parser_name': 'VerilogParser', 'parser_version': '2.0', 'result_status': 'FAILED',
                'result_path': 'parser_results/verilog/unknown.json'}]})
            write_json(inventory_path, inventory)
            write_json(tasks_path, tasks)
            write_json(current, build_effective_manifest(json.loads(catalog.read_text()), 'demo', 'full', []))
            result = run_semantic_review(current, catalog, root / 'report', profile_config_path=self.profile(root))
            failures = [row for row in result['checks'] if row['check_id'] == 'FILE_EVIDENCE']
            self.assertTrue(any(row['file']['source_relpath'] == 'verilog/unknown.v' and row['status'] == 'NOT_CHECKED' for row in failures))

    def test_malformed_input_limitations_are_visible_in_markdown_not_only_json(self):
        from lib_guard.semantic.runner import run_semantic_review
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            current, _, catalog = self.setup_inputs(root)
            parser = root / 'scan/full/parser_results/liberty/result.json'
            payload = json.loads(parser.read_text())
            payload['data']['semantic_coverage']['port_set'] = 'NOT_EXTRACTED'
            payload['data']['parse_limitations'] = [{'line': 12, 'reason': 'malformed_group_header_or_missing_semicolon'}]
            write_json(parser, payload)
            result = run_semantic_review(current, catalog, root / 'report', profile_config_path=self.profile(root))
            markdown = (root / 'report' / result['summary']['artifacts']['markdown']).read_text()
            self.assertIn('输入证据限制', markdown)
            self.assertIn('liberty/M.lib', markdown)
            self.assertIn('12', markdown)
            self.assertIn('malformed_group_header_or_missing_semicolon', markdown)
            self.assertIn('| M | SIGNAL_PORT_SET |', markdown)
            self.assertNotIn('| M | LIB_MACRO_FLAGS |', markdown)
            self.assertTrue(any(row['check_id'] == 'LIB_MACRO_FLAGS' for row in result['checks']))

    def test_confirmed_file_contexts_bind_without_rewriting_scan_or_cached_facts(self):
        from lib_guard.semantic.runner import run_semantic_review
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            current, old, catalog = self.setup_inputs(root)
            parser = root / 'scan/full/parser_results/liberty/result.json'
            payload = json.loads(parser.read_text())
            payload.pop('semantic_context')
            write_json(parser, payload)
            before = parser.read_bytes()
            mapping = root / 'mapping.json'
            write_json(mapping, {'confirmed': True, 'library_id': 'ip/demo', 'basis': 'owner checked headers',
                'file_contexts': [{'view': 'liberty', 'files': ['liberty/*.lib'], 'corner': 'TT', 'mode': 'functional'}]})
            config = self.profile(root, mapping='mapping.json')
            result = run_semantic_review(current, catalog, root / 'report', base_manifest_path=old, profile_config_path=config)
            self.assertEqual(result['summary']['scope']['current']['missing_selections'], [])
            self.assertEqual(result['summary']['scope']['current']['selected_corners'], ['TT'])
            self.assertTrue(all(row['status'] == 'UNIQUE_EXACT' for row in result['bindings']))
            self.assertTrue(any(row['status'] == 'PASS' for row in result['checks']))
            self.assertEqual(parser.read_bytes(), before)
            self.assertTrue(all(fact.get('corner') is None for fact in result['index']['facts']))
            obs = next(obs for obs in result['bindings'][0]['observations'] if obs['view'] == 'liberty')
            self.assertEqual(obs['evidence']['semantic_context']['basis'], 'owner checked headers')
            self.assertEqual(obs['evidence']['semantic_context']['source'], 'manual_mapping')

    def test_context_mapping_rejects_unconfirmed_cross_library_conflicting_and_unused_rows(self):
        from lib_guard.semantic.runner import run_semantic_review
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            current, _, catalog = self.setup_inputs(root)
            config = self.profile(root)
            row = {'view': 'liberty', 'files': ['liberty/*.lib'], 'corner': 'TT', 'mode': 'functional'}
            valid = {'confirmed': True, 'library_id': 'ip/demo', 'basis': 'checked', 'file_contexts': [row]}
            invalid = [dict(valid, confirmed=False), dict(valid, library_id='ip/other'), dict(valid, basis=''),
                dict(valid, file_contexts={}),
                dict(valid, file_contexts=[row, row]), dict(valid, file_contexts=[dict(row, files=['missing.lib'])]),
                dict(valid, file_contexts=[dict(row, corner='SS')]),
                dict(valid, file_contexts=[dict(row, files='*.lib')])]
            mapping = root / 'mapping.json'
            for value in invalid:
                with self.subTest(value=value):
                    write_json(mapping, value)
                    with self.assertRaises(ValueError):
                        run_semantic_review(current, catalog, root / 'report', profile_config_path=config, mapping_path=mapping)
                    self.assertFalse((root / 'report/summary.json').exists())

    def setup_inputs(self, root):
        fixture = SemanticFixture(root)
        version = fixture.version('full')
        old = root / 'old.json'
        write_json(old, fixture.manifest())
        fixture.version('fix', views=('lef',), width=1000.1)
        current, catalog = root / 'current.json', root / 'catalog.json'
        write_json(current, fixture.manifest([('fix', ['lef'])]))
        write_json(catalog, fixture.catalog)
        parser = Path(version['scan']['scan_dir']) / 'parser_results/liberty/result.json'
        payload = json.loads(parser.read_text())
        payload['semantic_context'] = {
            'confirmed': True, 'basis': 'controlled fixture', 'corner': 'TT', 'mode': 'functional',
        }
        write_json(parser, payload)
        return current, old, catalog

    def profile(self, root, **overrides):
        config = {'schema_version': 'semantic_review_config.v1', 'default_profile': 'ip_basic',
                  'profiles': {'ip_basic': {
                      'macros': ['M'], 'required_views': ['lef', 'liberty', 'verilog'],
                      'liberty': {'selected': [{'corner': 'TT', 'mode': 'functional', 'files': ['liberty/*.lib']}]},
                      'checks': ['SIGNAL_PORT_SET', 'LIB_MACRO_FLAGS', 'LEF_SIZE_DELTA'],
                      'flag_policy': {'is_macro': True}, 'tolerance_um': 0.2,
                      **overrides}}}
        path = root / 'profile.json'
        write_json(path, config)
        return path

    def test_same_profile_controls_both_sides_and_is_stored_in_snapshot(self):
        from lib_guard.semantic.runner import run_semantic_review
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            current, old, catalog = self.setup_inputs(root)
            config = self.profile(root)
            protected = {path: path.read_bytes() for path in (current, old, catalog, config)}
            result = run_semantic_review(current, catalog, root / 'report',
                                         base_manifest_path=old, profile_config_path=config)
            self.assertEqual({r['check_id'] for r in result['checks']}, {'SIGNAL_PORT_SET', 'LIB_MACRO_FLAGS'})
            self.assertEqual({r['check_id'] for r in result['delta']}, {'LEF_SIZE_DELTA'})
            self.assertTrue(all(r['status'] == 'UNCHANGED' for r in result['delta']))
            flags = next(r for r in result['checks'] if r['check_id'] == 'LIB_MACRO_FLAGS')
            self.assertEqual(flags['status'], 'PASS')
            self.assertEqual(result['summary']['review_profile']['name'], 'ip_basic')
            self.assertEqual(result['summary']['review_profile']['config']['tolerance_um'], 0.2)
            self.assertEqual(result['summary']['scope']['current']['selected_files'], 3)
            self.assertEqual(result['summary']['scope']['base']['selected_files'], 3)
            self.assertEqual(protected, {path: path.read_bytes() for path in protected})
            markdown = root / 'report' / result['summary']['artifacts']['markdown']
            self.assertIn('TT', markdown.read_text())
            before = result['summary']['generation']
            self.profile(root, tolerance_um=0.01)
            changed = run_semantic_review(current, catalog, root / 'report',
                                          base_manifest_path=old, profile_config_path=config)
            self.assertNotEqual(changed['summary']['generation'], before)
            width = next(r for r in changed['delta'] if r['attribute'] == 'width_um')
            self.assertEqual(width['status'], 'CHANGED')
            self.assertTrue(markdown.is_file())

    def test_unselected_view_has_explicit_scope_and_missing_corner_cannot_pass(self):
        from lib_guard.semantic.runner import run_semantic_review
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            current, _, catalog = self.setup_inputs(root)
            config = self.profile(root, liberty={'selected': [{'corner': 'SS', 'files': '*.lib'}]})
            result = run_semantic_review(current, catalog, root / 'report', profile_config_path=config)
            self.assertEqual(result['summary']['scope']['current']['excluded_files'], 1)
            missing = [r for r in result['checks'] if r['check_id'] == 'PROFILE_SCOPE']
            self.assertTrue(missing)
            self.assertTrue(all(r['status'] == 'NOT_CHECKED' for r in missing))
            self.assertFalse(any(r['status'] == 'PASS' for r in result['checks']))

    def test_mode_and_corner_require_confirmed_evidence_not_just_filename(self):
        from lib_guard.semantic.runner import run_semantic_review
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            current, _, catalog = self.setup_inputs(root)
            parser = root / 'scan/full/parser_results/liberty/result.json'
            payload = json.loads(parser.read_text())
            payload.pop('semantic_context')
            write_json(parser, payload)
            config = self.profile(root)
            result = run_semantic_review(current, catalog, root / 'report', profile_config_path=config)
            self.assertTrue(result['summary']['scope']['current']['missing_selections'])
            self.assertFalse(any(r['status'] == 'PASS' for r in result['checks']))

    def test_invalid_profile_never_replaces_existing_report(self):
        from lib_guard.semantic.runner import run_semantic_review
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            current, _, catalog = self.setup_inputs(root)
            config = self.profile(root)
            run_semantic_review(current, catalog, root / 'report', profile_config_path=config)
            before = (root / 'report/summary.json').read_bytes()
            for settings in ({'checks': ['TYPO']}, {'tolerance_um': -1},
                             {'flag_policy': {'is_macro': 'true'}}, {'macros': 'M'}, {'cheks': []}):
                with self.subTest(settings=settings):
                    self.profile(root, **settings)
                    with self.assertRaises(ValueError):
                        run_semantic_review(current, catalog, root / 'report', profile_config_path=config)
                    self.assertEqual((root / 'report/summary.json').read_bytes(), before)

    def test_empty_or_unmatched_macro_selection_does_not_claim_success(self):
        from lib_guard.semantic.runner import run_semantic_review
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            current, _, catalog = self.setup_inputs(root)
            config = self.profile(root, macros=['DOES_NOT_EXIST'])
            result = run_semantic_review(current, catalog, root / 'report', profile_config_path=config)
            self.assertEqual(result['summary']['macro_count'], 0)
            self.assertEqual(result['summary']['counts'].get('PASS', 0), 0)
            self.assertTrue(result['summary']['scope']['current']['missing_macros'])

    def test_cli_config_and_profile_are_consumed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            current, _, catalog = self.setup_inputs(root)
            config = self.profile(root)
            proc = subprocess.run([sys.executable, '-m', 'lib_guard.semantic.cli',
                                   '--effective-manifest', str(current), '--catalog', str(catalog),
                                   '--out', str(root / 'report'), '--config', str(config), '--profile', 'ip_basic'],
                                  text=True, capture_output=True)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(json.loads(proc.stdout)['review_profile']['name'], 'ip_basic')

    def test_missing_selected_corner_is_checked_per_macro(self):
        from lib_guard.semantic.runner import run_semantic_review
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _, _, catalog = self.setup_inputs(root)
            for view, group in [('lef', ['macros']), ('liberty', ['libraries', 'L', 'cells']),
                                ('verilog', ['modules'])]:
                path = root / 'scan/full/parser_results' / view / 'result.json'
                payload = json.loads(path.read_text())
                objects = payload['data']
                for key in group:
                    objects = objects[key]
                objects['N'] = json.loads(json.dumps(objects['M']))
                write_json(path, payload)
            ss_raw = root / 'raw/full/liberty/M_ss.lib'
            ss_raw.write_text('ss fixture')
            ss = json.loads((root / 'scan/full/parser_results/liberty/result.json').read_text())
            ss['data']['libraries']['L']['cells'].pop('N')
            ss.update(file='liberty/M_ss.lib', abs_path=str(ss_raw),
                      semantic_context={'confirmed': True, 'basis': 'controlled fixture', 'corner': 'SS', 'mode': 'functional'})
            write_json(root / 'scan/full/parser_results/liberty/ss.json', ss)
            path = root / 'scan/full/parser_manifest.json'
            tasks = json.loads(path.read_text())
            tasks['files'].append({'file': ss['file'], 'file_type': 'liberty', 'parser_tasks': [{
                'parser_name': ss['parser_name'], 'parser_version': ss['parser_version'],
                'result_status': ss['status'], 'result_path': 'parser_results/liberty/ss.json'}]})
            write_json(path, tasks)
            path = root / 'scan/full/file_inventory.json'
            inventory = json.loads(path.read_text())
            inventory['files'].append({'path': ss['file'], 'abs_path': str(ss_raw), 'file_type': 'liberty',
                                       'size_bytes': ss_raw.stat().st_size, 'mtime': ss_raw.stat().st_mtime})
            write_json(path, inventory)
            from lib_guard.effective.manifest import build_effective_manifest
            catalog_data = json.loads(catalog.read_text())
            manifest = root / 'two_macros.json'
            write_json(manifest, build_effective_manifest(catalog_data, 'demo', 'full', []))
            config = self.profile(root, macros=['M', 'N'], liberty={'selected': [
                {'corner': 'TT', 'files': '*.lib'}, {'corner': 'SS', 'files': '*.lib'}]})
            result = run_semantic_review(manifest, catalog, root / 'report', profile_config_path=config)
            binding = next(row for row in result['bindings'] if row['name'] == 'N')
            self.assertEqual(binding['status'], 'UNRESOLVED')
            n_checks = [row for row in result['checks'] if row['macro_id'] == binding['macro_id']]
            self.assertFalse(any(row['status'] == 'PASS' for row in n_checks))

    def test_file_selection_does_not_hide_a_rule_mapping_typo(self):
        from lib_guard.semantic.runner import run_semantic_review
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            current, _, catalog = self.setup_inputs(root)
            config = self.profile(root)
            mapping = root / 'mapping.json'
            write_json(mapping, {'confirmed': True, 'macro_aliases': [
                {'view': 'lef', 'object': 'TYPO', 'macro': 'M'}]})
            with self.assertRaises(ValueError):
                run_semantic_review(current, catalog, root / 'report', profile_config_path=config, mapping_path=mapping)

    def test_unselected_files_do_not_add_checks_or_disappear_from_full_index(self):
        from lib_guard.semantic.runner import run_semantic_review
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            current, _, catalog = self.setup_inputs(root)
            parser = root / 'scan/full/parser_results/liberty/result.json'
            payload = json.loads(parser.read_text())
            payload['status'] = 'FAILED'
            write_json(parser, payload)
            task_path = root / 'scan/full/parser_manifest.json'
            tasks = json.loads(task_path.read_text())
            for item in tasks['files']:
                if item['file_type'] == 'liberty':
                    item['parser_tasks'][0]['result_status'] = 'FAILED'
            write_json(task_path, tasks)
            config = self.profile(root, required_views=['lef', 'verilog'], liberty={'selected': []},
                                  checks=['MACRO_BINDING', 'SIGNAL_PORT_SET'])
            result = run_semantic_review(current, catalog, root / 'report', profile_config_path=config)
            self.assertEqual(len(result['index']['files']), 3)
            self.assertEqual(result['summary']['scope']['current']['excluded_files'], 1)
            self.assertFalse(any(row['check_id'] == 'FILE_EVIDENCE' for row in result['checks']))

    def test_diagnostics_reuse_scan_without_reading_raw_contents(self):
        from unittest.mock import patch
        from lib_guard.semantic.runner import run_semantic_review
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            current, old, catalog = self.setup_inputs(root)
            config = self.profile(root)
            original = Path.open
            def open_without_raw(path, *args, **kwargs):
                if path.resolve().is_relative_to(root / 'raw'):
                    raise AssertionError('diagnostics unexpectedly read raw contents')
                return original(path, *args, **kwargs)
            with patch.object(Path, 'open', open_without_raw):
                result = run_semantic_review(current, catalog, root / 'report',
                                             base_manifest_path=old, profile_config_path=config)
            self.assertEqual(result['summary']['raw_content_reads'], 0)

    def test_checked_in_config_can_be_loaded_and_unknown_profile_is_explained(self):
        from lib_guard.semantic.profile import load_review_profile
        profile = load_review_profile()
        self.assertEqual(profile['name'], 'default')
        self.assertIn('LEF_SIZE_DELTA', profile['config']['checks'])
        with self.assertRaisesRegex(ValueError, '不存在'):
            load_review_profile(profile_name='missing')
