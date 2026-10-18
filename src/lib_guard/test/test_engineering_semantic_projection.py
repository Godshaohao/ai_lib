import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from lib_guard.render.version_semantic_checks import render_semantic_check, semantic_reader_totals
from lib_guard.review.publication import load_current_file_checks, load_semantic_projection, publish_semantic_review
from lib_guard.review.representative_files import load_representative_files
from lib_guard.semantic.runner import run_semantic_review
from lib_guard.test.semantic_fixture import SemanticFixture, write_json


class SemanticReaderTotalsTest(unittest.TestCase):
    def test_separates_current_checks_changes_and_unknown_delta(self):
        row = {'counts': {'PASS': 1, 'FAIL': 0, 'REVIEW_REQUIRED': 1, 'NOT_CHECKED': 2, 'UNKNOWN': 1},
               'delta_counts': {'CHANGED': 2, 'UNCHANGED': 4, 'INCOMPLETE': 1, 'UNKNOWN': 1},
               'delta_context': 'EXPLICIT_BASE_EFFECTIVE'}
        self.assertEqual(semantic_reader_totals(row), {
            'current_executed': 1, 'current_passed': 1, 'current_failed': 0, 'current_pending': 4,
            'delta_executed': 6, 'changed': 2, 'delta_pending': 2, 'unchanged': 4})

    def test_zero_checks_and_no_base_have_no_pass_conclusion(self):
        totals = semantic_reader_totals({'counts': {}, 'delta_counts': {'CHANGED': 2},
                                          'delta_context': 'NO_BASE_EFFECTIVE'})
        self.assertEqual(totals['current_executed'], 0)
        self.assertEqual(totals['current_passed'], 0)
        self.assertEqual(totals['delta_executed'], 0)
        self.assertEqual(totals['changed'], 0)
        legacy = semantic_reader_totals({'counts': {}, 'delta_counts': {'CHANGED': 2},
                                          'scope': {'base': None}})
        self.assertEqual(legacy['changed'], 0)


class CurrentFileHistoryTest(unittest.TestCase):
    def test_one_current_per_type_with_nonrecursive_metadata_history(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            rows = {}
            for evidence_id, kind, started in [('old', 'lef', 1), ('middle', 'lef', 2),
                                               ('current', 'lef', 3), ('rtl', 'verilog', 1)]:
                rows[evidence_id] = {
                    'evidence_id': evidence_id, 'file_type': kind, 'started_epoch': started,
                    'evidence_dir': f'/evidence/{evidence_id}', 'generated_at': f'g{started}',
                    'saved_at': f's{started}', 'old_file': f'/old/{evidence_id}',
                    'new_file': f'/new/{evidence_id}', 'base_version': 'v1',
                    'source_stamps': {}, 'changes': [{'path': 'not history metadata'}],
                }
            write_json(root / 'ip_demo/v2/representative_files.json', {'files': rows})
            with patch('lib_guard.review.publication.load_representative_files', wraps=load_representative_files) as load:
                selected = load_current_file_checks(root, 'ip/demo', 'v2')
            load.assert_called_once_with(root, 'ip/demo', 'v2')
            self.assertEqual([item['evidence_id'] for item in selected], ['current', 'rtl'])
            self.assertEqual([item['evidence_id'] for item in selected[0]['history']], ['middle', 'old'])
            self.assertEqual(set(selected[0]['history'][0]), {
                'evidence_id', 'evidence_dir', 'generated_at', 'saved_at',
                'old_file', 'new_file', 'base_version'})
            self.assertNotIn('history', selected[1])


class SemanticReaderRenderTest(unittest.TestCase):
    def test_no_base_reader_summary_does_not_claim_zero_version_changes(self):
        from lib_guard.render.version_detail_report import _reader_summary
        html = _reader_summary({'engineering_report': {'delivery_summary': '必需视图 1 / 1',
                                                          'key_facts': [], 'limitations': []},
                                'semantic_check': {'status': 'CURRENT', 'delta_context': 'NO_BASE_EFFECTIVE',
                                                   'counts': {'PASS': 2}, 'delta_counts': {}}}, {})
        self.assertIn('未选择基准组合', html)
        self.assertNotIn('版本变化 0 项', html)

    def test_current_pass_with_delta_change_and_unknown_are_separate(self):
        row = {'status': 'CURRENT', 'counts': {'PASS': 1},
               'delta_counts': {'CHANGED': 2, 'INCOMPLETE': 1},
               'delta_context': 'EXPLICIT_BASE_EFFECTIVE', 'effective_id': 'demo',
               'checks': [{'check_id': 'MACRO_BINDING', 'status': 'PASS', 'macro_id': 'id'}],
               'delta': [{'check_id': 'LEF_SIZE_DELTA', 'status': 'CHANGED', 'macro_id': 'id',
                          'reason_code': 'ATTRIBUTES_COMPARED'},
                         {'check_id': 'LEF_PIN_DELTA', 'status': 'INCOMPLETE', 'macro_id': 'id',
                          'reason_code': 'INCOMPLETE_ATTRIBUTE_EVIDENCE'}],
               'object_names': {'id': 'M'}}
        with tempfile.TemporaryDirectory() as td:
            html = render_semantic_check(row, Path(td) / 'index.html')
        self.assertIn('1 项通过', html)
        self.assertIn('2 项变化', html)
        self.assertIn('1 项待核对', html)
        self.assertIn('M', html)
        self.assertIn('尺寸', html)
        self.assertNotIn('LEF_SIZE_DELTA', html)
        self.assertNotIn('未发现需处理项', html)

    def test_only_delta_does_not_render_zero_checks_as_pass(self):
        row = {'status': 'CURRENT', 'counts': {}, 'delta_counts': {'CHANGED': 1},
               'delta_context': 'EXPLICIT_BASE_EFFECTIVE', 'effective_id': 'demo'}
        with tempfile.TemporaryDirectory() as td:
            html = render_semantic_check(row, Path(td) / 'index.html')
        self.assertIn('尚未执行独立检查', html)
        self.assertIn('1 项变化', html)
        self.assertNotIn('未发现需处理项', html)


class SemanticReaderPublicationTest(unittest.TestCase):
    def test_full_with_two_overlays_is_attributed_to_last_target_version_in_order(self):
        from lib_guard.review.engineering import build_engineering_report
        from lib_guard.render.version_engineering import render_engineering_report
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            fixture = SemanticFixture(root)
            fixture.version('full')
            fixture.version('fix_lef', views=('lef',), width=1100)
            fixture.version('fix_rtl', views=('verilog',))
            catalog, base, current = root / 'catalog/catalog.json', root / 'base.json', root / 'current.json'
            write_json(catalog, fixture.catalog)
            write_json(base, fixture.manifest())
            write_json(current, fixture.manifest([('fix_lef', ['lef']), ('fix_rtl', ['verilog'])]))
            out = root / 'job/semantic'
            run_semantic_review(current, catalog, out, base_manifest_path=base)
            published = publish_semantic_review(catalog, root / 'catalog/html', current, out, refresh=False)
            self.assertEqual(published['version'], 'fix_rtl')
            projection = load_semantic_projection(root / 'review_notes', 'ip/demo', 'fix_rtl')
            self.assertEqual(projection['status'], 'CURRENT')
            self.assertEqual(projection['components'], ['full', 'fix_lef', 'fix_rtl'])
            self.assertEqual(load_semantic_projection(root / 'review_notes', 'ip/demo', 'fix_lef'), {})
            report = build_engineering_report({'semantic_check': projection})
            html = render_engineering_report(report, root / 'reader.html')
            self.assertIn('FULL', html)
            self.assertIn('fix_lef', html)
            self.assertIn('fix_rtl', html)
            self.assertTrue(any(item['topic'] == 'size' and item['status'] == 'CHANGED'
                                for item in report['findings']))

    def test_unreadable_source_marks_projection_stale_instead_of_breaking_reader(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            fixture = SemanticFixture(root)
            fixture.version('full')
            catalog, manifest = root / 'catalog/catalog.json', root / 'effective.json'
            write_json(catalog, fixture.catalog)
            write_json(manifest, fixture.manifest())
            out = root / 'job/semantic'
            run_semantic_review(manifest, catalog, out)
            publish_semantic_review(catalog, root / 'catalog/html', manifest, out, refresh=False)
            stat = Path.stat

            def unreadable(path, *args, **kwargs):
                if str(path).endswith('/raw/full/lef/M.lef'):
                    raise PermissionError('source permission changed')
                return stat(path, *args, **kwargs)

            with patch.object(Path, 'stat', unreadable):
                result = load_semantic_projection(root / 'review_notes', 'ip/demo', 'full')
            self.assertEqual(result['status'], 'STALE')

    def test_copied_rows_and_names_survive_job_removal_but_stale_is_not_current(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            fixture = SemanticFixture(root)
            fixture.version('full')
            catalog, manifest = root / 'catalog/catalog.json', root / 'effective.json'
            write_json(catalog, fixture.catalog)
            write_json(manifest, fixture.manifest())
            out = root / 'job/semantic'
            result = run_semantic_review(manifest, catalog, out)
            publish_semantic_review(catalog, root / 'catalog/html', manifest, out, refresh=False)
            shutil.rmtree(out.parent)
            manifest.unlink()
            projection = load_semantic_projection(root / 'review_notes', 'ip/demo', 'full')
            self.assertEqual(projection['status'], 'CURRENT')
            self.assertEqual(projection['checks'], result['checks'])
            self.assertEqual(projection['delta'], result['delta'])
            self.assertEqual(projection['object_names'][result['bindings'][0]['macro_id']], 'M')
            (root / 'raw/full/lef/M.lef').write_text('changed')
            stale = load_semantic_projection(root / 'review_notes', 'ip/demo', 'full')
            self.assertEqual(stale['status'], 'STALE')
            html = render_semantic_check(stale, root / 'page.html')
            self.assertIn('旧结果仅供追溯', html)
            self.assertNotIn('当前版：', html)

    def test_legacy_projection_without_optional_metadata_loads_copied_rows(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            fixture = SemanticFixture(root)
            fixture.version('full')
            catalog, manifest = root / 'catalog/catalog.json', root / 'effective.json'
            write_json(catalog, fixture.catalog)
            write_json(manifest, fixture.manifest())
            out = root / 'job/semantic'
            run_semantic_review(manifest, catalog, out)
            publish_semantic_review(catalog, root / 'catalog/html', manifest, out, refresh=False)
            index = root / 'review_notes/ip_demo/full/semantic_review.json'
            data = json.loads(index.read_text())
            row = next(iter(data['results'].values()))
            row.pop('object_names', None)
            row.pop('delta_context', None)
            row.pop('delta_counts', None)
            index.write_text(json.dumps(data))
            projection = load_semantic_projection(root / 'review_notes', 'ip/demo', 'full')
            self.assertEqual(projection['status'], 'CURRENT')
            self.assertIsInstance(projection['checks'], list)
            self.assertEqual(projection['delta'], [])
            self.assertEqual(projection['object_names'], {})

    def test_legacy_publish_time_stamps_cannot_claim_current(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            fixture = SemanticFixture(root)
            fixture.version('full')
            catalog, manifest = root / 'catalog/catalog.json', root / 'effective.json'
            write_json(catalog, fixture.catalog)
            write_json(manifest, fixture.manifest())
            out = root / 'job/semantic'
            run_semantic_review(manifest, catalog, out)
            publish_semantic_review(catalog, root / 'catalog/html', manifest, out, refresh=False)
            index = root / 'review_notes/ip_demo/full/semantic_review.json'
            data = json.loads(index.read_text())
            row = next(iter(data['results'].values()))
            row.pop('source_stamps_complete')
            index.write_text(json.dumps(data))
            self.assertEqual(load_semantic_projection(root / 'review_notes', 'ip/demo', 'full')['status'], 'STALE')

    def test_damaged_copied_details_are_invalid_and_not_exposed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            fixture = SemanticFixture(root)
            fixture.version('full')
            catalog, manifest = root / 'catalog/catalog.json', root / 'effective.json'
            write_json(catalog, fixture.catalog)
            write_json(manifest, fixture.manifest())
            out = root / 'job/semantic'
            run_semantic_review(manifest, catalog, out)
            published = publish_semantic_review(catalog, root / 'catalog/html', manifest, out, refresh=False)
            Path(published['details_path']).write_text('{"checks": []}')
            projection = load_semantic_projection(root / 'review_notes', 'ip/demo', 'full')
            self.assertEqual(projection['status'], 'INVALID')
            self.assertEqual(projection['checks'], [])
            self.assertEqual(projection['delta'], [])

    def test_missing_copied_details_is_invalid(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            fixture = SemanticFixture(root)
            fixture.version('full')
            catalog, manifest = root / 'catalog/catalog.json', root / 'effective.json'
            write_json(catalog, fixture.catalog)
            write_json(manifest, fixture.manifest())
            out = root / 'job/semantic'
            run_semantic_review(manifest, catalog, out)
            published = publish_semantic_review(catalog, root / 'catalog/html', manifest, out, refresh=False)
            Path(published['details_path']).unlink()
            projection = load_semantic_projection(root / 'review_notes', 'ip/demo', 'full')
            self.assertEqual(projection['status'], 'INVALID')
            self.assertEqual(projection['checks'], [])

    def test_republish_same_generation_never_refreshes_evidence_fingerprints(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            fixture = SemanticFixture(root)
            fixture.version('full')
            catalog, manifest = root / 'catalog/catalog.json', root / 'effective.json'
            write_json(catalog, fixture.catalog)
            write_json(manifest, fixture.manifest())
            out = root / 'job/semantic'
            run_semantic_review(manifest, catalog, out)
            first = publish_semantic_review(catalog, root / 'catalog/html', manifest, out,
                                            started_epoch=10, refresh=False)
            (root / 'raw/full/lef/M.lef').write_text('changed after check')
            self.assertEqual(load_semantic_projection(root / 'review_notes', 'ip/demo', 'full')['status'], 'STALE')
            again = publish_semantic_review(catalog, root / 'catalog/html', manifest, out,
                                            started_epoch=10, refresh=False)
            self.assertEqual(again['source_stamps'], first['source_stamps'])
            self.assertEqual(again['published_at'], first['published_at'])
            self.assertEqual(load_semantic_projection(root / 'review_notes', 'ip/demo', 'full')['status'], 'STALE')

    def test_first_publish_after_raw_change_uses_snapshot_stamp(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            fixture = SemanticFixture(root)
            fixture.version('full')
            catalog, manifest = root / 'catalog/catalog.json', root / 'effective.json'
            write_json(catalog, fixture.catalog)
            write_json(manifest, fixture.manifest())
            out = root / 'job/semantic'
            run_semantic_review(manifest, catalog, out)
            (root / 'raw/full/lef/M.lef').write_text('changed after check')
            publish_semantic_review(catalog, root / 'catalog/html', manifest, out, refresh=False)
            self.assertEqual(load_semantic_projection(root / 'review_notes', 'ip/demo', 'full')['status'], 'STALE')

    def test_base_only_source_change_invalidates_delta(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            fixture = SemanticFixture(root)
            fixture.version('full')
            fixture.version('fix', views=('lef',), width=1100)
            catalog, base, current = root / 'catalog/catalog.json', root / 'base.json', root / 'current.json'
            write_json(catalog, fixture.catalog)
            write_json(base, fixture.manifest())
            write_json(current, fixture.manifest([('fix', ['lef'])]))
            out = root / 'job/semantic'
            result = run_semantic_review(current, catalog, out, base_manifest_path=base)
            published = publish_semantic_review(catalog, root / 'catalog/html', current, out, refresh=False)
            projection = load_semantic_projection(root / 'review_notes', 'ip/demo', 'fix')
            self.assertEqual(projection['status'], 'CURRENT')
            self.assertEqual(published['base_effective_id'], result['base_index']['effective_id'])
            self.assertEqual(projection['base_effective_id'], result['base_index']['effective_id'])
            self.assertEqual(projection['base_effective_digest'], result['summary']['base_effective_digest'])
            (root / 'raw/full/lef/M.lef').write_text('base only changed')
            self.assertEqual(load_semantic_projection(root / 'review_notes', 'ip/demo', 'fix')['status'], 'STALE')

    def test_no_base_projection_has_explicit_null_base_identity(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            fixture = SemanticFixture(root)
            fixture.version('full')
            catalog, manifest = root / 'catalog/catalog.json', root / 'effective.json'
            write_json(catalog, fixture.catalog)
            write_json(manifest, fixture.manifest())
            out = root / 'job/semantic'
            run_semantic_review(manifest, catalog, out)
            publish_semantic_review(catalog, root / 'catalog/html', manifest, out, refresh=False)
            projection = load_semantic_projection(root / 'review_notes', 'ip/demo', 'full')
            self.assertIsNone(projection['base_effective_id'])
            self.assertIsNone(projection['base_effective_digest'])

    def test_new_generation_config_mismatch_is_stale(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            fixture = SemanticFixture(root)
            fixture.version('full')
            catalog, manifest, config = root / 'catalog/catalog.json', root / 'effective.json', root / 'profile.json'
            write_json(catalog, fixture.catalog)
            write_json(manifest, fixture.manifest())
            write_json(config, {'schema_version': 'semantic_review_config.v1',
                                'profiles': {'default': {'checks': ['MACRO_BINDING']}}})
            out = root / 'job/semantic'
            run_semantic_review(manifest, catalog, out, profile_config_path=config)
            write_json(config, {'schema_version': 'semantic_review_config.v1',
                                'profiles': {'default': {'checks': ['SIGNAL_PORT_SET']}}})
            publish_semantic_review(catalog, root / 'catalog/html', manifest, out,
                                    profile_config_path=config, refresh=False)
            self.assertEqual(load_semantic_projection(root / 'review_notes', 'ip/demo', 'full')['status'], 'STALE')

    def test_missing_markdown_does_not_hide_modified_details(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            fixture = SemanticFixture(root)
            fixture.version('full')
            catalog, manifest = root / 'catalog/catalog.json', root / 'effective.json'
            write_json(catalog, fixture.catalog)
            write_json(manifest, fixture.manifest())
            out = root / 'job/semantic'
            run_semantic_review(manifest, catalog, out)
            published = publish_semantic_review(catalog, root / 'catalog/html', manifest, out, refresh=False)
            Path(published['markdown_path']).unlink()
            missing = load_semantic_projection(root / 'review_notes', 'ip/demo', 'full')
            self.assertEqual(missing['status'], 'INVALID')
            self.assertEqual(missing['checks'], [])
            Path(published['details_path']).write_text('{"checks": [], "delta": []}')
            projection = load_semantic_projection(root / 'review_notes', 'ip/demo', 'full')
            self.assertEqual(projection['status'], 'INVALID')
            self.assertEqual(projection['checks'], [])


if __name__ == '__main__':
    unittest.main()
