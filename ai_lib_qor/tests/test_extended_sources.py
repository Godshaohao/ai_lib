import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ai_lib_qor.application.minimal_checks import run_revision
from ai_lib_qor.application.path_query import PathDataQuery
from ai_lib_qor.application.path_refresh import refresh_all
from ai_lib_qor.cli import parser, run
from ai_lib_qor.sources.minimal_delivery import order_deliveries
from ai_lib_qor.workbench.path_app import create_path_app


class ExtendedSourcesTests(unittest.TestCase):
    def setUp(self):
        holder = tempfile.TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        self.root = Path(holder.name)
        self.work, self.raw1, self.raw2, self.nl = (
            self.root / name for name in ('work', 'RAW1', 'RAW2', 'NL1')
        )
        for path in (self.work, self.raw1, self.raw2, self.nl):
            path.mkdir()

    def config(self, **options):
        (self.work / 'path_sources.json').write_text(json.dumps({
            'raw_roots': [str(self.raw1), str(self.raw2)],
            'nl_root': str(self.nl), 'nl_version': 'NL1', **options,
        }))

    def leaf(self, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('VERSION 5.8 ;\nMACRO A\n SIZE 1 BY 2 ;\nEND A\nEND LIBRARY\n')
        return path

    def test_multiple_roots_links_and_independent_formal_reach_check(self):
        real = self.leaf(self.raw2 / 'V2/B/release_blue/LEF/core.lef')
        tree = self.raw1 / 'V1/A/release_green'
        tree.mkdir(parents=True)
        alias = tree / 'LEF'
        alias.symlink_to(real.parent, target_is_directory=True)
        (self.nl / 'linked.lef').symlink_to(alias / real.name)
        self.leaf(self.nl / 'independent.lef')
        self.config()
        result = refresh_all(self.work)
        self.assertEqual(result['l1']['delivery_created'], 2)
        self.assertEqual(result['l1']['formal_created'], 1)
        self.assertEqual(result['l1']['formal_independent_count'], 1)
        self.assertEqual(result['l1']['formal_observation_status'], 'COMPLETE')
        self.assertIn('NL_ONLY', (self.work / 'formal_observations.tsv').read_text())
        context = PathDataQuery(self.work).get_check_context('V1', 'A', 'rev_0001')
        self.assertEqual(len(context['members']), 1)
        check = run_revision(self.work, 'V1', 'A', 'rev_0001', render=False)
        report = json.loads(Path(check['check']).read_text())
        self.assertEqual([f['status'] for f in report['files']], ['PARSED'])
        self.assertEqual(refresh_all(self.work)['l1']['formal_created'], 0)

    def test_undated_without_metadata_has_natural_order(self):
        rows = [{'version': v, 'version_date': None} for v in ('release10', 'release2', 'release1')]
        self.assertEqual([row['version'] for row in order_deliveries(rows, {})],
                         ['release1', 'release2', 'release10'])

    def test_link_boundary_and_retarget_leave_old_records_intact(self):
        external = self.root / 'external'
        good = self.leaf(external / 'old.lef')
        new = self.leaf(external / 'new.lef')
        raw = self.raw1 / 'V/A/release_blue'
        raw.mkdir(parents=True)
        alias = raw / 'core.lef'
        alias.symlink_to(good)
        nl_link = self.nl / 'linked.lef'
        nl_link.symlink_to(alias)
        self.config()
        rejected = refresh_all(self.work)
        self.assertEqual(rejected['l1']['delivery_created'], 0)
        self.assertTrue(any('超出允许目录' in warning for warning in rejected['warnings']))
        self.config(raw_link_roots=[str(external)])
        first = refresh_all(self.work)
        self.assertEqual(first['l1']['formal_created'], 1)
        folder = self.work / 'libraries/V/A'
        previous = (folder / 'latest_formal_NL1.json').readlink()
        alias.unlink()
        alias.symlink_to(new)
        again = refresh_all(self.work)
        self.assertEqual(again['l1']['formal_observation_status'], 'PARTIAL')
        self.assertEqual((folder / 'latest_formal_NL1.json').readlink(), previous)
        check = run_revision(self.work, 'V', 'A', 'rev_0001', render=False)
        report = json.loads(Path(check['check']).read_text())
        self.assertIn('链接目标与归档不一致', str(report['files']))

    def test_duplicate_version_and_directory_cycle_are_reported(self):
        roots = [self.raw1, self.raw2]
        for root in roots:
            self.leaf(root / 'V/A/V01/LEF/a.lef')
        version = self.raw1 / 'V/B/V01'
        self.leaf(version / 'core.lef')
        (version / 'back').symlink_to(version, target_is_directory=True)
        self.config(update_formal=False)
        args = ['refresh-sources', '--work', str(self.work)]
        for root in roots:
            args.extend(['--raw-root', str(root)])
        outcome = run(parser().parse_args(args))
        self.assertEqual(outcome['delivery_created'], 0)
        self.assertTrue(any('同名版本' in warning for warning in outcome['warnings']))
        self.assertTrue(any('链接循环' in warning for warning in outcome['warnings']))

    def test_formal_inventory_can_run_without_a_raw_source(self):
        self.leaf(self.nl / 'independent.lef')
        external = self.root / 'other'
        external.mkdir()
        (self.nl / 'external').symlink_to(external, target_is_directory=True)
        self.config(raw_roots=[], update_raw=False)
        result = refresh_all(self.work)
        self.assertEqual(result['l1']['formal_independent_count'], 2)
        self.assertEqual(result['l1']['formal_observation_status'], 'COMPLETE')

    def test_web_persists_multiline_raw_roots(self):
        self.leaf(self.raw1 / 'V/A/release_a/LEF/a.lef')
        self.leaf(self.raw2 / 'V/B/release_b/LEF/b.lef')
        self.config(raw_roots=[])
        app = create_path_app(self.work)
        self.addCleanup(app.extensions['jobs'].shutdown)
        client = app.test_client()
        client.get('/')
        with client.session_transaction() as session:
            csrf = session['csrf']
        result = client.post('/path/update', data={
            'csrf': csrf, 'raw': '1', 'index': '1', 'save_settings': '1',
            'raw_roots': f'{self.raw1}\n{self.raw2}\n',
        }, follow_redirects=True)
        self.assertIn('新增交付 2', result.get_data(as_text=True))
        self.assertEqual(json.loads((self.work / 'path_sources.json').read_text())['raw_roots'],
                         [str(self.raw1), str(self.raw2)])

    def test_workbench_accepts_explicit_network_and_host(self):
        self.config(workbench={'host': '0.0.0.0', 'port': 8060,
                               'allowed_clients': ['192.168.10.0/24'], 'allowed_hosts': ['qor.lab']})
        app = create_path_app(self.work)
        self.addCleanup(app.extensions['jobs'].shutdown)
        client = app.test_client()
        self.assertEqual(client.get('/', base_url='http://qor.lab:8060',
                                    environ_overrides={'REMOTE_ADDR': '192.168.10.5'}).status_code, 200)
        self.assertEqual(client.get('/', base_url='http://qor.lab:8060',
                                    environ_overrides={'REMOTE_ADDR': '192.168.11.5'}).status_code, 403)
        self.assertEqual(client.get('/', base_url='http://wrong.lab:8060',
                                    environ_overrides={'REMOTE_ADDR': '192.168.10.5'}).status_code, 403)
        self.assertEqual(client.post('/path/refresh', base_url='http://qor.lab:8060',
                                     environ_overrides={'REMOTE_ADDR': '192.168.10.5'}).status_code, 403)
        from ai_lib_qor.workbench.__main__ import main
        with patch('sys.argv', ['workbench', '--work', str(self.work)]), \
                patch('ai_lib_qor.workbench.__main__.create_path_app', return_value=app), patch.object(app, 'run') as serve:
            main()
            serve.assert_called_once_with(host='0.0.0.0', port=8060, debug=False)
