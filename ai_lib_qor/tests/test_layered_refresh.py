import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ai_lib_qor.application.path_query import PathDataQuery
from ai_lib_qor.application.path_refresh import (
    refresh_all,
    refresh_l1,
    refresh_l2,
    refresh_l3,
    refresh_status,
)
from ai_lib_qor.cli import parser, run


class LayeredRefreshTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.root = root
        self.work = root / 'work'
        self.raw = root / 'raw'
        self.nl = root / 'NL1'
        self.nl.mkdir()
        (root / 'plans').mkdir()
        p1 = self.raw / 'v/lib/20261001_a/LEF/a.lef'
        p1.parent.mkdir(parents=True)
        p1.write_text('MACRO A\n SIZE 2 BY 3 ;\n PIN IN\n  DIRECTION INPUT ;\n END IN\nEND A\n')
        (self.nl / 'a.lef').symlink_to(p1)
        self.work.mkdir()
        (self.work / 'path_sources.json').write_text(json.dumps({
            'raw_root': str(self.raw),
            'nl_root': str(self.nl),
            'nl_version': 'NL1',
        }))

    def test_three_layers_automate_and_skip_rebuild_when_unchanged(self):
        # L1: scan RAW + Formal only
        l1 = refresh_l1(self.work)
        self.assertEqual(l1['delivery_created'], 1)
        self.assertEqual(l1['formal_created'], 1)
        self.assertEqual(len(l1['libraries_changed']), 1)
        self.assertEqual(l1['libraries_changed'][0]['new_deliveries'], ['20261001_a'])
        folder = self.work / 'libraries/v/lib'
        self.assertFalse((folder / 'file_index.json').exists())

        # L2: auto-initialize Effective from Formal without touching RAW filesystem
        with patch('os.walk', side_effect=AssertionError('L2 不得扫描磁盘')):
            l2 = refresh_l2(self.work)
        self.assertEqual(l2['initialized'], 1)
        self.assertEqual(l2['effective_published'], 0)

        # L3: since L2 already refreshed index on publish, L3 skips rebuild; force_verify still works
        with patch('os.walk', side_effect=AssertionError('L3 不得扫描磁盘')):
            l3_first = refresh_l3(self.work)
            l3_forced = refresh_l3(self.work, force_verify=True)
        self.assertEqual(l3_first['indexes_unchanged'], 1)
        self.assertEqual(l3_first['indexes_skipped_rebuild'], 1)
        self.assertEqual(l3_forced['indexes_unchanged'], 1)
        self.assertEqual(l3_forced['indexes_skipped_rebuild'], 0)

        # Add a second RAW delivery -> one-click refresh_all auto-evolves rev_0002
        p2 = self.raw / 'v/lib/20261002_b/LEF/a.lef'
        p2.parent.mkdir(parents=True)
        p2.write_text('MACRO A\n SIZE 2 BY 4 ;\n PIN IN\n  DIRECTION INPUT ;\n END IN\nEND A\n')
        full = refresh_all(self.work, formal=False)
        self.assertEqual(full['l1']['delivery_created'], 1)
        self.assertEqual(full['l2']['effective_published'], 1)
        self.assertEqual(full['l3']['indexes_unchanged'], 1)
        self.assertEqual(full['l3']['indexes_skipped_rebuild'], 1)

        status = refresh_status(self.work)
        self.assertEqual(status['totals']['libraries'], 1)
        self.assertEqual(status['totals']['revisions'], 2)
        self.assertEqual(status['totals']['index_fresh'], 1)
        self.assertIsNotNone(status['last_by_layer']['L1'])
        self.assertIsNotNone(status['last_by_layer']['L2'])
        self.assertIsNotNone(status['last_by_layer']['L3'])

    def test_manifest_read_avoids_rebuild_and_detects_preserved_mtime_tampering(self):
        refresh_all(self.work)
        query = PathDataQuery(self.work)

        # Normal read hits manifest without calling build_index
        with patch('ai_lib_qor.application.path_query.build_index', side_effect=AssertionError('不应触发重建')):
            data = query.index('v', 'lib')
        self.assertEqual(data['revisions'], ['rev_0001'])

        # Tamper delivery JSON while preserving original mtime -> MUST detect staleness
        from ai_lib_qor.sources.layout import archive_files
        folder = self.work / 'libraries/v/lib'
        delivery = archive_files(folder, 'delivery', 'delivery_*.json')[0]
        orig_stat = delivery.stat()
        payload = json.loads(delivery.read_text(encoding='utf-8'))
        payload['views']['LEF'] = []
        delivery.write_text(json.dumps(payload), encoding='utf-8')
        os.utime(delivery, ns=(orig_stat.st_atime_ns, orig_stat.st_mtime_ns))

        with self.assertRaisesRegex(ValueError, '过期|无效|不兼容'):
            query.index('v', 'lib')

    def test_cli_and_web_three_layer_endpoints(self):
        cli_parser = parser()
        res = run(cli_parser.parse_args(['refresh', '--work', str(self.work)]))
        self.assertEqual(res['l1']['delivery_created'], 1)
        self.assertEqual(res['l2']['initialized'], 1)
        st = run(cli_parser.parse_args(['refresh-status', '--work', str(self.work)]))
        self.assertEqual(st['totals']['index_fresh'], 1)

        from ai_lib_qor.workbench.app import create_app
        app = create_app(self.root / 'plans', self.root / 'runs', self.work)
        client = app.test_client()

        # Overview page must NOT scan RAW or call build_index
        with patch('os.walk', side_effect=AssertionError('首页不扫描')), \
             patch('ai_lib_qor.application.minimal_file_index.build_index', side_effect=AssertionError('首页不重建')):
            page = client.get('/')
        self.assertEqual(page.status_code, 200)
        html = page.get_data(as_text=True)
        self.assertIn('三层数据刷新中心', html)
        self.assertIn('一键三层自动同步', html)

        with client.session_transaction() as sess:
            csrf = sess['csrf']
        r_l3 = client.post('/path/refresh', data={'csrf': csrf, 'layer': 'l3'}, follow_redirects=True)
        self.assertEqual(r_l3.status_code, 200)
        self.assertIn('跳过重建 1', r_l3.get_data(as_text=True))
        self.assertEqual(client.post('/path/refresh', data={'csrf': 'bad', 'layer': 'l3'}).status_code, 403)

        # Verify failed_checks > 0 renders tag-failed (质检失败) instead of green SUCCEEDED
        folder = self.work / 'libraries/v/lib'
        fake_check = {
            'schema_version': 'check_result.path.v1',
            'run_id': 'run_' + 'a' * 32,
            'vendor': 'v',
            'library': 'lib',
            'revision': 'rev_0001',
            'baseline': None,
            'run_at': '2026-11-22T00:00:00Z',
            'state': 'SUCCEEDED',
            'files': [],
            'checks': [],
            'comparisons': [],
            'partial_comparisons': [],
            'changes': [],
            'summary': {
                'failed_checks': 1,
                'inconclusive_checks': 0,
                'failed_files': 0,
                'files_with_new_source': 0,
                'files_with_confirmed_content_change': 0,
            },
            'note': 'test',
        }
        (folder / f"check_{fake_check['run_id']}.json").write_text(json.dumps(fake_check), encoding='utf-8')
        lib_html = client.get('/path/library', query_string={'vendor': 'v', 'library': 'lib'}).get_data(as_text=True)
        self.assertIn('tag-failed', lib_html)
        self.assertIn('质检失败', lib_html)
