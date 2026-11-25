import json
from io import BytesIO
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import time
import unittest
from xml.etree import ElementTree
from zipfile import ZipFile

from ai_lib_qor.application.minimal_checks import run_library, run_revision
from ai_lib_qor.application.path_acceptance import accept_revision, rollback_acceptance
from ai_lib_qor.application.path_batch import check_pending
from ai_lib_qor.application.path_refresh import refresh_all, refresh_l2
from ai_lib_qor.workbench.path_app import create_path_app
from test_delivery_init_fold import _lef, _LIB


def workbook_text(file):
    with ZipFile(file) as archive:
        root = ElementTree.fromstring(archive.read('xl/sharedStrings.xml'))
        return '\n'.join(row.text or '' for row in root.findall('.//{*}t'))


class ReviewRegressionsTests(unittest.TestCase):
    def setUp(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.work = self.root / 'work'
        self.work.mkdir()
        self.config_file = self.work / 'path_sources.json'
        self.config = {'raw_root': str(self.root / 'RAW'), 'update_formal': False}

    def save_config(self):
        self.config_file.write_text(json.dumps(self.config))

    def delivery(self, library, version, files):
        for rel, content in files.items():
            path = self.root / 'RAW' / 'V' / library / version / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)

    def client(self):
        app = create_path_app(self.work)
        self.addCleanup(app.extensions['jobs'].shutdown)
        return app.test_client()

    def test_l2_failure_changes_pipeline_exit_and_background_state(self):
        self.delivery('L', '20261001_v1', {'a.lef': _lef(10)})
        self.config['initial_delivery_tail'] = -1
        self.save_config()
        cli = subprocess.run([sys.executable, '-m', 'ai_lib_qor', 'refresh', '--work', str(self.work)],
                             capture_output=True, text=True)
        self.assertEqual(cli.returncode, 1, cli.stdout + cli.stderr)
        result = json.loads(cli.stdout)
        self.assertEqual((result['status'], result['l2']['status'], result['l3']['status']),
                         ('FAILED', 'FAILED', 'SUCCEEDED'))
        self.assertEqual(result['effective_failed'], 1)
        self.assertIn('initial_delivery_tail', result['libraries_failed'][0]['reason'])

        client = self.client()
        client.get('/')
        with client.session_transaction() as session:
            csrf = session['csrf']
        posted = client.post('/api/v1/jobs/refresh', data={'csrf': csrf, 'layer': 'all'})
        self.assertEqual(posted.status_code, 202)
        for _ in range(250):
            job = client.get('/api/v1/jobs/' + posted.json['job_id']).json
            if job['status'] not in ('QUEUED', 'RUNNING'):
                break
            time.sleep(0.01)
        self.assertEqual(job['status'], 'FAILED')
        self.assertIn('有效版本推进失败', job['message'])
        self.assertIn('initial_delivery_tail', client.get('/').get_data(as_text=True))

    def test_no_auto_init_applies_to_single_and_multiple_tracks(self):
        for lib in ('SINGLE', 'MULTI'):
            self.delivery(lib, '20261001_DDR5', {'a.lef': _lef(10)})
        self.config['libraries'] = {'V': {'MULTI': {'ip_list': ['DDR5']}}}
        self.save_config()
        refresh_all(self.work, auto_effective=False)
        result = refresh_l2(self.work, auto_init_from_formal=False)
        self.assertEqual(result['initialized'], 0)
        for lib in ('SINGLE', 'MULTI'):
            self.assertFalse(list((self.work / 'libraries' / 'V' / lib).glob('effective/*.json')))

    def test_successful_library_remains_available_when_another_l2_fails(self):
        for lib in ('BAD', 'GOOD'):
            self.delivery(lib, '20261001_v1', {'a.lef': _lef(10)})
        self.config['libraries'] = {'V': {'BAD': {'initial_delivery_tail': -1}}}
        self.save_config()
        result = refresh_all(self.work)
        self.assertEqual(result['status'], 'PARTIAL')
        self.assertEqual(result['l2']['initialized'], 1)
        self.assertEqual(result['l3']['indexes_updated'], 2)
        self.assertEqual([(row['layer'], row['library']) for row in result['libraries_failed']], [('L2', 'BAD')])

    def test_excel_updates_after_accept_and_rollback_while_json_is_reused(self):
        for day in (1, 2):
            self.delivery('L', f'2026100{day}_v{day}', {'a.lef': _lef(10 + day), 'a.lib': _LIB})
        self.save_config()
        refresh_all(self.work)
        single = run_revision(self.work, 'V', 'L', 'rev_0002')
        overall = run_library(self.work, 'V', 'L')
        saved = {key: Path(out[key]).read_bytes() for key, out in [('check', single), ('overall', overall)]}
        self.assertIn('尚未人工采纳', workbook_text(single['excel']))
        self.assertIn('当前已采纳: 尚未人工采纳', workbook_text(overall['excel']))

        accept_revision(self.work, 'V', 'L', 'rev_0002', reason='确认新版')
        client = self.client()
        for out, label in ((single, '当前版本已采纳'), (overall, '当前已采纳: rev_0002')):
            reply = client.get('/path/artifact', query_string={
                'vendor': 'V', 'library': 'L', 'name': Path(out['excel']).name,
            })
            self.assertEqual(reply.status_code, 200)
            self.assertIn(label, workbook_text(BytesIO(reply.data)))
            reply.close()

        rollback_acceptance(self.work, 'V', 'L', 'rev_0001', reason='恢复旧版')
        single2 = run_revision(self.work, 'V', 'L', 'rev_0002')
        overall2 = run_library(self.work, 'V', 'L')
        self.assertIn('已采纳 rev_0001', workbook_text(single2['excel']))
        self.assertIn('当前已采纳: rev_0001', workbook_text(overall2['excel']))
        for key, before, after in [('check', single, single2), ('overall', overall, overall2)]:
            self.assertTrue(after['reused'])
            self.assertEqual(before[key], after[key])
            self.assertEqual(Path(after[key]).read_bytes(), saved[key])

    def test_incremental_checks_detect_current_liberty_sampling_policy(self):
        self.delivery('L', '20261001_v1', {'a.lef': _lef(10), 'a_tt.lib': _LIB, 'a_ss.lib': _LIB})
        self.config['liberty_parse_filter'] = {'threshold': 1, 'keywords': ['tt'], 'max_selected': 1}
        self.save_config()
        refresh_all(self.work)
        check_pending(self.work)
        self.config['liberty_parse_filter']['keywords'] = ['ss']
        self.save_config()
        skipped = check_pending(self.work)
        self.assertEqual(skipped['outdated_tooling_count'], 1)
        self.assertEqual(skipped['checked_count'], 0)
        run = check_pending(self.work, include_outdated=True)
        self.assertEqual(run['checked_count'], 1)
        result = json.loads((self.work / 'libraries/V/L/log' / run['checked'][0]['check']).read_text())
        self.assertEqual([row['path'] for row in result['files'] if row['view'] == 'LIBERTY' and row['status'] == 'PARSED'],
                         ['a_ss.lib'])
        self.assertEqual(check_pending(self.work, include_outdated=True)['checked_count'], 0)
