"""Regression coverage for the shared Formal view and incomplete Facts evidence."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from openpyxl import load_workbook

from ai_lib_qor.application.facts_pool import load_check_bundle
from ai_lib_qor.application.minimal_checks import run_revision
from ai_lib_qor.application.minimal_effective import initialize_from_formal
from ai_lib_qor.application.minimal_file_index import refresh_index
from ai_lib_qor.application.path_query import PathDataQuery
from ai_lib_qor.reporting.check_renderer import render_excel_from_check
from ai_lib_qor.sources.root_inventory import build_from_roots
from ai_lib_qor.workbench.path_app import create_path_app


class FormalReportConsistencyTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        self.work, self.raw, self.nl = root/'work', root/'raw', root/'NL1'
        self.nl.mkdir()
        self.scope = {'vendor': 'v', 'library': 'lib'}
        for name, content in (
            ('LEF/a.lef', 'MACRO A\n SIZE 1 BY 2 ;\n PIN IN\n DIRECTION INPUT ;\n END IN\nEND A\n'),
            ('LIB/a.lib', 'library(test) { cell(A) { pin(IN) { direction : input; } } }'),
        ):
            p = self.raw/'v/lib/20261001_v1'/name
            p.parent.mkdir(parents=True)
            p.write_text(content)
            (self.nl/p.name).symlink_to(p)
        build_from_roots(self.raw, self.nl, self.work)
        self.folder = self.work/'libraries/v/lib'
        self.formal = next((self.folder/'formal').glob('formal_*.json'))
        initialize_from_formal(self.work, 'v', 'lib', self.formal)
        self.client = create_path_app(self.work).test_client()

    def check(self):
        result = run_revision(self.work, 'v', 'lib', 'rev_0001', render=False)
        return Path(result['check'])

    def matrix_lef(self, check):
        path = render_excel_from_check(self.work, 'v', 'lib', check.name)
        book = load_workbook(path, read_only=True, data_only=True)
        try:
            return next(row for row in book['02-文件版本矩阵'].values if 'LEF/a.lef' in row)
        finally:
            book.close()

    def test_same_second_link_removal_matches_web_and_excel_and_keeps_old_run(self):
        original = self.check()
        (self.nl/'a.lef').unlink()
        timestamp = json.loads(self.formal.read_text())['observed_at']
        with patch('ai_lib_qor.sources.root_inventory.utc_text', return_value=timestamp):
            self.assertEqual(build_from_roots(self.raw, self.nl, self.work)['formal_created'], 1)
        index = PathDataQuery(self.work).index('v', 'lib')
        self.assertNotEqual(index['nl_snapshots'][0]['snapshot_id'], index['nl_snapshots'][1]['snapshot_id'])
        self.assertEqual(index['views']['LEF']['LEF/a.lef']['nl'][0]['snapshot_id'], self.formal.name)
        web = self.client.get('/path/index', query_string={**self.scope, 'view': 'LEF'})
        self.assertIn('最新快照未观察到', web.text)
        self.assertTrue(any('最新快照未观察到' in str(cell) for cell in self.matrix_lef(self.check())))
        self.assertTrue(any('来源相同' in str(cell) for cell in self.matrix_lef(original)))
        self.assertEqual(len(load_check_bundle(self.work, 'v', 'lib', original.name)['index']['nl_snapshots']), 1)

    def test_old_index_backfills_formal_identity_without_changing_archives(self):
        old = PathDataQuery(self.work).index('v', 'lib')
        for item in old['nl_snapshots']:
            item.pop('snapshot_id', None)
        for group in old['views'].values():
            for row in group.values():
                for item in row['nl']:
                    item.pop('snapshot_id', None)
        index_path = self.folder/'file_index.json'
        index_path.write_text(json.dumps(old))
        (self.folder/'.file_index_manifest.json').unlink()
        original = self.formal.read_bytes()
        self.assertEqual(PathDataQuery(self.work).index('v', 'lib')['nl_snapshots'][0]['snapshot_id'], self.formal.name)
        self.assertNotIn('snapshot_id', index_path.read_text())
        refresh_index(self.work, 'v', 'lib')
        self.assertIn('snapshot_id', index_path.read_text())
        self.assertEqual(self.formal.read_bytes(), original)

    def test_missing_or_broken_facts_keep_check_result_and_mark_unavailable(self):
        check = self.check()
        report = json.loads(check.read_text())
        evidence = list(report['facts_evidence'].items())
        self.assertGreaterEqual(len(evidence), 2)
        broken = self.folder/evidence[0][1]['pool_file']
        broken.write_bytes(broken.read_bytes()[:12])
        (self.folder/evidence[1][1]['pool_file']).unlink()
        response = self.client.get('/api/v1/check', query_string={**self.scope, 'name': check.name})
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data['report']['checks'], report['checks'])
        self.assertEqual(set(data['unavailable_facts']), {ref for ref, _ in evidence})
        page = self.client.get('/path/check/view', query_string={**self.scope, 'name': check.name})
        self.assertEqual(page.status_code, 200)
        self.assertIn('证据不可用', page.text)
        self.assertIn('证据不可用', self.matrix_lef(check))
        rerun = json.loads(self.check().read_text())
        self.assertEqual(rerun['state'], 'PARTIAL')
        self.assertTrue(any('共享池文件损坏' in row['note'] for row in rerun['files'] if row['status'] == 'FAILED'))
