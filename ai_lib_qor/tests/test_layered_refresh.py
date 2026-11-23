import json
import os
import tempfile
import time
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

    def _client(self):
        from ai_lib_qor.workbench.app import create_app
        app = create_app(self.root / 'plans', self.root / 'runs', self.work)
        self.addCleanup(app.extensions['jobs'].shutdown)
        client = app.test_client()
        client.get('/')
        with client.session_transaction() as session:
            self.csrf = session['csrf']
        return client

    def _web_refresh(self, client, **form):
        reply = client.post('/api/v1/jobs/refresh', data={'csrf': self.csrf, **form})
        self.assertEqual(reply.status_code, 202, reply.get_data(as_text=True))
        job_id = reply.json['job_id']
        for _ in range(200):
            job = client.get(f'/api/v1/jobs/{job_id}').json
            if job['status'] not in ('QUEUED', 'RUNNING'):
                return job
            time.sleep(0.01)
        self.fail('刷新任务未结束')

    def test_saved_options_apply_to_cli_and_web_background_sync(self):
        refresh_all(self.work)
        client = self._client()
        reply = client.post('/path/update', data={
            'csrf': self.csrf, 'raw': '1', 'index': '1', 'save_settings': '1',
        })
        self.assertEqual(reply.status_code, 302)
        p = self.raw / 'v/lib/20261002_b/LEF/a.lef'
        p.parent.mkdir(parents=True)
        p.write_text('MACRO A\n SIZE 3 BY 4 ;\nEND A\n')
        result = run(parser().parse_args(['refresh', '--work', str(self.work)]))
        self.assertEqual(result['l1']['delivery_created'], 1)
        self.assertFalse(result['l1']['options']['formal'])
        self.assertEqual(result['l2']['status'], 'SKIPPED')
        self.assertEqual(self._web_refresh(client, layer='all')['result']['l2']['status'], 'SKIPPED')
        self.assertEqual(refresh_status(self.work)['totals']['revisions'], 1)
        enabled = run(parser().parse_args(['refresh', '--work', str(self.work), '--auto-effective', '--no-index']))
        self.assertEqual(enabled['l2']['effective_published'], 1)
        self.assertEqual(enabled['l3']['status'], 'SKIPPED')
        self.assertNotEqual(refresh_status(self.work)['libraries'][0]['index_status'], 'FRESH')

    def test_single_library_raw_only_does_not_change_other_verification_times(self):
        p = self.raw / 'v/other/20261001_a/LEF/b.lef'
        p.parent.mkdir(parents=True)
        p.write_text('MACRO B\nEND B\n')
        (self.nl / 'b.lef').symlink_to(p)
        with patch('ai_lib_qor.sources.root_inventory.utc_text', return_value='2026-11-20T00:00:00Z'):
            refresh_l1(self.work)
        with patch('ai_lib_qor.sources.root_inventory.utc_text', return_value='2026-11-21T00:00:00Z'):
            refresh_l1(self.work, vendor='v', library='other', formal=False, verify_raw=True)
        libraries = {row['library']: row for row in refresh_status(self.work)['libraries']}
        for name, raw_time in [('lib', '2026-11-20'), ('other', '2026-11-21')]:
            sources = libraries[name]['source_verifications']
            self.assertTrue(sources['RAW']['at'].startswith(raw_time))
            self.assertTrue(sources['FORMAL']['NL1']['at'].startswith('2026-11-20'))
        page = self._client().get('/?json_layer=L1&json_scope=v%2Fother').get_data(as_text=True)
        self.assertIn('最近 RAW 核验 2026-11-21', page)
        self.assertIn('最近 Formal 核验 2026-11-20', page)
        with patch('ai_lib_qor.sources.root_inventory.utc_text', return_value='2026-11-22T00:00:00Z'):
            refresh_l1(self.work, vendor='v', library='other', formal=False)
        other = next(row for row in refresh_status(self.work)['libraries'] if row['library'] == 'other')
        raw = other['source_verifications']['RAW']
        self.assertEqual(raw['at'], '2026-11-22T00:00:00Z')
        self.assertEqual(raw['verified_at'], '2026-11-21T00:00:00Z')
        self.assertEqual(raw['versions_reused'], 1)

    def test_failed_l3_job_surfaces_library_and_reason(self):
        p = self.raw / 'v/lib/20261001_b/LEF/a.lef'
        p.parent.mkdir(parents=True)
        p.write_text('MACRO A\nEND A\n')
        refresh_l1(self.work, formal=False)
        client = self._client()
        job = self._web_refresh(client, layer='l3', vendor='v', library='lib')
        self.assertEqual(job['status'], 'FAILED')
        failure, = job['result']['libraries_failed']
        self.assertEqual((failure['vendor'], failure['library']), ('v', 'lib'))
        self.assertTrue(failure['reason'])
        page = client.get('/?json_layer=L3&json_status=issue').get_data(as_text=True)
        self.assertIn(failure['reason'], page)
        self.assertNotIn('各库索引一致，无需重建', page)

    def test_json_filters_reach_entries_beyond_the_first_300(self):
        many = self.work / 'libraries/v/many/delivery'
        many.mkdir(parents=True)
        for number in range(305):
            (many / f'delivery_demo_{number:03}.json').write_text('{}')
        target = many / 'delivery_extra_old.json'
        target.write_text('{}')
        os.utime(target, (1, 1))
        client = self._client()
        page = client.get('/?json_layer=L1&json_sort=newest&json_page=2').get_data(as_text=True)
        self.assertIn('第 2 / 4 页', page)
        self.assertNotIn('delivery_extra_old.json', page)
        last = client.get('/?json_layer=L1&json_sort=newest&json_page=4').get_data(as_text=True)
        self.assertIn('第 4 / 4 页', last)
        self.assertIn('delivery_extra_old.json', last)
        page = client.get('/?json_layer=L1&json_scope=v%2Fmany&json_q=extra_old').get_data(as_text=True)
        self.assertIn('delivery_extra_old.json', page)
        self.assertNotIn('delivery_demo_000.json', page)

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
        self.assertEqual(full['l3']['indexes_updated'], 1)
        self.assertEqual(full['l3']['indexes_skipped_rebuild'], 0)

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
        self.assertIn('JSON 数据产物与更新时间明细', html)
        self.assertIn('sync-json-table', html)
        self.assertIn('file_index.json', html)
        self.assertIn('effective_lib_001.json', html)
        self.assertNotIn('隐藏模拟库', html)
        self.assertNotIn('hide-sim-cb', html)

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
        self.assertIn('lib-json-table', lib_html)
        self.assertIn('file_index.json', lib_html)
