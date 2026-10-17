import hashlib
import json
from pathlib import Path
import subprocess
import shutil
import tempfile
import unittest

from lib_guard.effective.manifest import build_effective_manifest
from lib_guard.effective.pointer import pointer_search_paths
from lib_guard.test.semantic_fixture import write_json
from lib_guard.test.test_lef_check_facts import LEF
from lib_guard.test.test_release_levels import _scan
from lib_guard.window.resolver import default_window_path

ROOT = Path(__file__).resolve().parents[3]


def make_workspace(root):
    root = Path(root)
    library = {'library_id': 'ip/demo', 'library_name': 'demo', 'versions': []}
    catalog = {'libraries': [library]}
    for version, text in [('full', LEF), ('fix', LEF.replace('DIRECTION INPUT', 'DIRECTION OUTPUT'))]:
        raw, scan = root / 'raw' / version, root / 'scan' / version
        raw.mkdir(parents=True)
        (raw / 'M.lef').write_text(text)
        _scan(raw, scan, mode='scan', version=version, parse_file_types=['lef'])
        meta = json.loads((scan / 'scan_meta.json').read_text())
        library['versions'].append({'version_id': version, 'raw_path': str(raw),
            'package_type': 'FULL_PACKAGE' if version == 'full' else 'PARTIAL_UPDATE',
            'scan': {'scan_dir': str(scan), 'snapshot_identity': meta['snapshot_identity']}})
    catalog_path = root / 'catalog/catalog.json'
    html = root / 'catalog/html'
    write_json(catalog_path, catalog)
    window = default_window_path(html, library, 'demo')
    manifests = {}
    for name, includes in [('E1', []), ('E2', [('fix', ['lef'])])]:
        manifest = build_effective_manifest(catalog, 'demo', 'full', includes)
        manifest['effective_id'] = name
        path = window.parent.parent / 'effective' / name / 'effective_manifest.json'
        write_json(path, manifest)
        manifests[name] = path
    write_json(pointer_search_paths(html, 'ip/demo')[0], {
        'current_effective_id': 'E1', 'manifest': str(manifests['E1']), 'base_full_version': 'full'})
    write_json(window, {'state': 'PENDING', 'candidate_effective': {'effective_id': 'E2',
        'manifest': str(manifests['E2']), 'base_full': 'full', 'overlays': ['fix']}})
    config = root / 'lib_guard.yml'
    config.write_text(f'workspace: {root}\nraw_root: {root}/raw\ncatalog: {catalog_path}\ncatalog_html: {html}\n')
    return config, manifests


class WebSemanticReviewTest(unittest.TestCase):
    def test_quality_projection_separates_job_completion_from_review_conclusion(self):
        from lib_guard.web.app import _semantic_quality_projection

        current_only = _semantic_quality_projection({
            'schema_version': 'semantic_summary.v1', 'counts': {'PASS': 4},
            'delta_counts': {}, 'delta_context': 'NO_BASE_EFFECTIVE',
            'scope': {'current': {'effective_files': 3, 'selected_files': 2}, 'base': None},
        })
        self.assertEqual(current_only['verdict'], 'INCOMPLETE')
        self.assertIn('未形成版本变化结论', current_only['next_action'])

        incomplete = _semantic_quality_projection({
            'schema_version': 'semantic_summary.v1',
            'delta_counts': {'INCOMPLETE': 7240},
            'scope': {'current': {'effective_files': 205, 'selected_files': 27}, 'base': None},
        })
        self.assertEqual(incomplete['verdict'], 'INCOMPLETE')
        self.assertEqual(incomplete['verdict_label'], '需要补齐检查')
        self.assertFalse(incomplete['base_selected'])
        self.assertEqual(incomplete['coverage'], {'selected_files': 27, 'effective_files': 205})
        self.assertIn('未形成版本变化结论', incomplete['next_action'])

        review = _semantic_quality_projection({
            'schema_version': 'semantic_summary.v1',
            'counts': {'PASS': 697, 'REVIEW_REQUIRED': 10},
            'scope': {'current': {'effective_files': 205, 'selected_files': 16}, 'base': {'selected_files': 16}},
        })
        self.assertEqual(review['verdict'], 'REVIEW_REQUIRED')
        self.assertEqual(review['counts']['PASS'], 697)
        self.assertTrue(review['base_selected'])
        self.assertIn('人工确认', review['next_action'])

        delta = _semantic_quality_projection({
            'schema_version': 'semantic_summary.v1',
            'delta_counts': {'CHANGED': 269, 'UNCHANGED': 5088},
            'scope': {'current': {'effective_files': 205, 'selected_files': 16}, 'base': {}},
        })
        self.assertEqual(delta['verdict'], 'PASS')
        self.assertEqual(delta['counts']['CHANGED'], 269)
        self.assertEqual(delta['delta_counts'], {'CHANGED': 269, 'UNCHANGED': 5088})

    def test_workspace_profiles_and_mapping_are_frozen_for_actual_execution(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            config, _ = make_workspace(root)
            config.write_text(config.read_text() + 'semantic_review_config: config/semantic.json\n')
            profile = root / 'config/semantic.json'
            mapping = root / 'config/binding.json'
            write_json(profile, {'schema_version': 'semantic_review_config.v1', 'default_profile': 'demo_cells',
                'profiles': {'demo_cells': {'required_views': ['lef'], 'mapping': 'binding.json',
                    'checks': ['LEF_INTERFACE_DELTA']}}})
            write_json(mapping, {'confirmed': True, 'library_id': 'ip/demo', 'basis': 'owner confirmed',
                'file_contexts': [{'view': 'lef', 'files': ['*.lef'], 'mode': 'functional'}]})
            client = self.app(root, config).test_client()
            options = client.get('/api/libraries/demo/semantic-review')
            self.assertEqual(options.status_code, 200, options.get_json())
            self.assertEqual([row['name'] for row in options.get_json()['profiles']], ['demo_cells'])
            self.assertEqual(options.get_json()['default_profile'], 'demo_cells')
            response = client.post('/api/libraries/demo/semantic-review', json={
                'target': 'E2', 'base': 'E1'})
            self.assertEqual(response.status_code, 202, response.get_json())
            args = json.loads(Path(response.get_json()['request']).read_text())['args']
            self.assertEqual(Path(args[args.index('--artifact-store') + 1]), root / 'semantic_artifacts')
            frozen_mapping = Path(args[args.index('--mapping') + 1])
            self.assertNotEqual(frozen_mapping, mapping)
            self.assertEqual(json.loads(frozen_mapping.read_text()), json.loads(mapping.read_text()))
            profile.unlink()
            mapping.unlink()
            result = subprocess.run(args, cwd=ROOT, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            summary = json.loads(result.stdout)
            self.assertEqual(summary['mapping']['basis'], 'owner confirmed')
            self.assertEqual(summary['scope']['current']['selected_modes'], ['functional'])
            self.assertEqual(summary['delta_counts'], {'CHANGED': 1})

    def test_wrong_library_mapping_is_not_offered_and_cannot_start_job(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            config, _ = make_workspace(root)
            config.write_text(config.read_text() + 'semantic_review_config: config/semantic.json\n')
            write_json(root / 'config/semantic.json', {'schema_version': 'semantic_review_config.v1',
                'profiles': {'other': {'mapping': 'binding.json'}}})
            write_json(root / 'config/binding.json', {'confirmed': True, 'library_id': 'ip/other'})
            client = self.app(root, config).test_client()
            options = client.get('/api/libraries/demo/semantic-review')
            self.assertEqual(options.status_code, 200, options.get_json())
            self.assertEqual(options.get_json()['profiles'], [])
            response = client.post('/api/libraries/demo/semantic-review', json={'target': 'E2', 'profile': 'other'})
            self.assertEqual(response.status_code, 400)
            self.assertFalse((root / 'jobs').exists())

    def app(self, root, config, *, testing=True):
        from lib_guard.web.app import create_app
        return create_app(config_path=config, cwd=ROOT,
                          test_config={'TESTING': testing, 'job_root': str(root / 'jobs')})

    def test_options_are_existing_effectives_and_configured_rules(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            config, manifests = make_workspace(root)
            client = self.app(root, config).test_client()
            response = client.get('/api/libraries/demo/semantic-review')
            self.assertEqual(response.status_code, 200)
            options = response.get_json()
            self.assertEqual({row['id'] for row in options['targets']}, {'E1', 'E2'})
            self.assertEqual(options['default_target'], 'E2')
            self.assertEqual(options['default_base'], 'E1')
            self.assertTrue(any(row['name'] == 'lef_basic' for row in options['profiles']))
            self.assertFalse(any('manifest' in row for row in options['targets']))

    def test_submission_freezes_selection_and_generates_files_not_ui_projection(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            config, manifests = make_workspace(root)
            client = self.app(root, config).test_client()
            before = {path: path.read_bytes() for path in manifests.values()}
            response = client.post('/api/libraries/demo/semantic-review', json={
                'target': 'E2', 'base': 'E1', 'profile': 'lef_basic', 'checks': ['LEF_INTERFACE_DELTA']})
            self.assertEqual(response.status_code, 202, response.get_json())
            request = json.loads(Path(response.get_json()['request']).read_text())
            args = request['args']
            self.assertEqual(args[args.index('-m') + 1], 'lib_guard.semantic.cli')
            target = Path(args[args.index('--effective-manifest') + 1])
            self.assertNotEqual(target, manifests['E2'])
            self.assertEqual(target.read_bytes(), before[manifests['E2']])
            config_path = Path(args[args.index('--config') + 1])
            frozen = json.loads(config_path.read_text())
            self.assertEqual(frozen['profiles']['lef_basic']['checks'], ['LEF_INTERFACE_DELTA'])
            result = subprocess.run(args, cwd=ROOT, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            job_dir = Path(response.get_json()['request']).parent
            (job_dir / 'stdout.log').write_text(result.stdout)
            from lib_guard.web.app import _record_machine_result, _job_artifact_map
            _record_machine_result(job_dir, result.returncode)
            artifacts = _job_artifact_map(job_dir)
            self.assertIn('markdown', artifacts)
            self.assertIn('semantic_checks', artifacts)
            self.assertTrue(all(item.get('download') is True for item in artifacts.values()))
            self.assertFalse(any(item['kind'] == 'html' for item in artifacts.values()))
            for item in artifacts.values():
                with client.get(item['url']) as download:
                    self.assertEqual(download.status_code, 200)
                    self.assertIn('attachment;', download.headers.get('Content-Disposition', ''))
            checks = json.loads(Path(artifacts['semantic_checks']['path']).read_text())
            self.assertEqual(checks['delta'][0]['status'], 'CHANGED')
            self.assertEqual({row['check_id'] for row in checks['delta']}, {'LEF_INTERFACE_DELTA'})
            self.assertEqual(before, {path: path.read_bytes() for path in manifests.values()})
            self.assertFalse((root / 'release').exists())

    def test_bad_requests_create_no_jobs(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            config, _ = make_workspace(root)
            client = self.app(root, config).test_client()
            for payload in ({'target': '/etc/passwd'}, {'target': 'E2', 'base': 'E2'},
                            {'target': 'E2', 'profile': 'not-a-profile'},
                            {'target': 'E2', 'checks': []},
                            {'target': 'E2', 'checks': ['NOT_A_RULE']},
                            {'target': 'E2', 'out': '/tmp/uncontrolled'},
                            {'target': 'E2', 'scan_if_missing': True}):
                with self.subTest(payload=payload):
                    response = client.post('/api/libraries/demo/semantic-review', json=payload)
                    self.assertEqual(response.status_code, 400, response.get_json())
            self.assertFalse((root / 'jobs').exists())

    def test_actual_background_task_without_base_preserves_inputs_and_reports_incomplete(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            config, _ = make_workspace(root)
            protected = list(root.rglob('*'))
            before = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in protected if path.is_file()}
            app = self.app(root, config, testing=False)
            client = app.test_client()
            response = client.post('/api/libraries/demo/semantic-review', json={'target': 'E2', 'base': '', 'profile': 'lef_basic'})
            self.assertEqual(response.status_code, 202, response.get_json())
            job_id = response.get_json()['job_id']
            process = app.extensions['lib_guard_jobs'][job_id]
            try:
                process.wait(timeout=30)
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait()
            status = client.get(f'/api/runs/{job_id}').get_json()
            self.assertEqual(status['return_code'], 0, status)
            self.assertNotIn('usage_decision', status)
            self.assertNotIn('delta', status)
            self.assertNotIn('checks', status)
            self.assertIn('报告', status['result_summary'])
            self.assertEqual(status['quality_summary']['verdict'], 'INCOMPLETE')
            self.assertFalse(status['quality_summary']['base_selected'])
            self.assertIn('未形成版本变化结论', status['quality_summary']['next_action'])
            artifacts = {row['id']: row for row in status['artifacts']}
            with client.get(artifacts['semantic_checks']['url']) as download:
                detail = download.get_json()
            self.assertTrue(all(row['status'] == 'INCOMPLETE' for row in detail['delta']))
            self.assertEqual(before, {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in before})

    def test_ui_has_execution_controls_but_no_report_content_panel(self):
        template = (ROOT / 'src/lib_guard/web/templates/index.html').read_text()
        script = (ROOT / 'src/lib_guard/web/static/app.js').read_text()
        for identity in ('semantic-review-target', 'semantic-review-base', 'semantic-review-profile',
                         'semantic-review-checks', 'semantic-review-run', 'semantic-review-feedback'):
            self.assertIn(f'id="{identity}"', template)
        self.assertIn('/semantic-review', script)
        self.assertIn('async function runSemanticReview(', script)
        self.assertIn('只生成报告文件', template)
        self.assertNotIn('id="semantic-review-results"', template)
        self.assertNotIn('id="semantic-review-iframe"', template)

    def test_missing_scan_evidence_is_reported_without_automatic_scan(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            config, _ = make_workspace(root)
            missing = next((root / 'scan/fix/parser_results').rglob('*.json'))
            missing.unlink()
            # Scanner also writes a supported aggregate; remove both to model absent evidence.
            (root / 'scan/fix/parser_results.json').unlink()
            client = self.app(root, config).test_client()
            response = client.post('/api/libraries/demo/semantic-review', json={'target': 'E2', 'base': 'E1', 'profile': 'lef_basic'})
            self.assertEqual(response.status_code, 202)
            request_path = Path(response.get_json()['request'])
            args = json.loads(request_path.read_text())['args']
            result = subprocess.run(args, cwd=ROOT, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            summary = json.loads(result.stdout)
            report_root = request_path.parent / 'semantic_review'
            checks = json.loads((report_root / summary['artifacts']['check_results']).read_text())
            self.assertTrue(any(row['status'] == 'NOT_CHECKED' for row in checks['checks']))
            self.assertTrue(all(row['status'] == 'INCOMPLETE' for row in checks['delta']))
            self.assertFalse(missing.exists())
            self.assertEqual(summary['raw_content_reads'], 0)

    def test_empty_library_has_no_executable_target_and_cross_library_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            config, manifests = make_workspace(root)
            client = self.app(root, config).test_client()
            document = json.loads(manifests['E2'].read_text())
            document['library_id'] = 'ip/other'
            write_json(manifests['E2'], document)
            response = client.post('/api/libraries/demo/semantic-review', json={'target': 'E2'})
            self.assertEqual(response.status_code, 400)
            self.assertIn('不一致', response.get_json()['error'])
            for path in (root / 'catalog/html').rglob('*.json'):
                path.unlink()
            response = client.get('/api/libraries/demo/semantic-review')
            self.assertEqual(response.get_json()['targets'], [])
            self.assertEqual(client.post('/api/libraries/demo/semantic-review', json={'target': 'E2'}).status_code, 400)
            self.assertFalse((root / 'jobs').exists())

    def test_changed_current_pointer_cannot_silently_supply_an_approved_baseline(self):
        from lib_guard.effective.manifest import validate_effective_manifest
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            config, manifests = make_workspace(root)
            html = root / 'catalog/html'
            pointer = pointer_search_paths(html, 'ip/demo')[0]
            current = json.loads(pointer.read_text())
            current['effective_digest'] = validate_effective_manifest(json.loads(manifests['E1'].read_text()))['digest']
            write_json(pointer, current)
            client = self.app(root, config).test_client()
            self.assertEqual(client.get('/api/libraries/demo/semantic-review').get_json()['default_base'], 'E1')
            # Independently valid replacement is not the combination recorded by the pointer.
            replacement = json.loads(manifests['E2'].read_text())
            replacement['effective_id'] = 'E1'
            write_json(manifests['E1'], replacement)
            options = client.get('/api/libraries/demo/semantic-review').get_json()
            self.assertEqual(options['default_base'], '')
            row = next(row for row in options['targets'] if row['id'] == 'E1')
            self.assertFalse(row['available'])
            response = client.post('/api/libraries/demo/semantic-review', json={'target': 'E2', 'base': 'E1'})
            self.assertEqual(response.status_code, 400)
            self.assertIn('不一致', response.get_json()['error'])
            self.assertFalse((root / 'jobs').exists())

    @unittest.skipUnless(shutil.which('node'), 'Node required')
    def test_late_options_from_previous_library_cannot_replace_current_selection(self):
        script = (ROOT / 'src/lib_guard/web/static/app.js').read_text()
        helpers = script[script.index('  function renderSemanticReviewReadiness('):script.index('  function releaseSetLibraryAvailable(')]
        harness = '''
const assert = require('node:assert/strict');
const state = {selectedLibrary:'A', semanticOptionsRequestId:0};
const nodes=new Map(); const $=id=>{if(!nodes.has(id))nodes.set(id,{value:'',querySelectorAll(){return [];}});return nodes.get(id);};
const escapeHtml=String; const pending={};
const getJson=url=>new Promise(resolve=>{pending[url]=resolve;});
''' + helpers + '''
(async()=>{
const a=loadSemanticReviewOptions(); state.selectedLibrary='B'; const b=loadSemanticReviewOptions();
const option = id=>({targets:[{id,label:id}],profiles:[{name:'lef_basic',label:'LEF',checks:[]}],default_target:id,default_base:''});
pending['/api/libraries/B/semantic-review'](option('B1')); await b;
pending['/api/libraries/A/semantic-review'](option('A1')); await a;
assert.equal(state.semanticOptionsLibrary,'B'); assert.equal($('semantic-review-target').value,'B1');
assert.equal(state.semanticOptionsLoading,false);
})();
'''
        result = subprocess.run(['node', '-e', harness], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
