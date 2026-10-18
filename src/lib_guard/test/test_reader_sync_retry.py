import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from lib_guard.diff.file_diff import diff_pairwise_files
from lib_guard.web.app import create_app


class ReaderSyncRetryTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.workspace = self.root / 'workspace'
        self.old = self.root / 'raw/v1/a.v'
        self.new = self.root / 'raw/v2/a.v'
        for path, content in ((self.old, 'module a(input x); endmodule\n'),
                              (self.new, 'module a(input y); endmodule\n')):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
        self.app = create_app(cwd=self.root, test_config={'TESTING': True})
        self.client = self.app.test_client()
        response = self.client.post('/api/workspace/init', json={
            'workspace': str(self.workspace), 'raw_root': str(self.root / 'raw'),
        })
        self.assertEqual(response.status_code, 200, response.get_json())
        self.catalog = self.workspace / 'catalog/catalog.json'
        self.catalog.parent.mkdir(parents=True, exist_ok=True)
        self.catalog.write_text(json.dumps({'libraries': [{'library_id': 'demo', 'library_name': 'demo',
            'versions': [{'version_id': 'v1', 'raw_path': str(self.old.parent)},
                         {'version_id': 'v2', 'raw_path': str(self.new.parent)}]}]}))
        self.html = self.workspace / 'catalog/html'
        self.job = self.workspace / 'web_jobs/file-diff_retry'
        self.job.mkdir(parents=True)
        result = diff_pairwise_files('verilog', self.old, self.new, self.job / 'pair',
                                     library_id='demo', version_id='v2', base_version='v1')
        self.write('request.json', {'job_id': self.job.name, 'action': 'file-diff',
            'library': 'demo', 'version': 'v2', 'payload': {},
            'reader_target': {'workspace': str(self.workspace), 'catalog_path': str(self.catalog),
                              'catalog_html': str(self.html), 'config_path': str(self.workspace / 'lib_guard.yml'),
                              'profile_config_path': ''}})
        self.write('result.json', {'result': 'ok', 'exit_code': 0, 'cli_result': result})
        self.write('status.json', {'job_id': self.job.name, 'action': 'file-diff',
            'status': 'COMPLETED', 'return_code': 0, 'started_epoch': 123.0,
            'reader_sync': {'status': 'FAILED', 'error': 'registration failed'}})

    def write(self, name, value):
        (self.job / name).write_text(json.dumps(value))

    def retry(self):
        return self.client.post(f'/api/runs/{self.job.name}/retry-reader-sync')

    def test_failed_sync_retry_publishes_without_subprocess(self):
        with patch('lib_guard.web.app.subprocess.Popen') as process:
            response = self.retry()
            process.assert_not_called()
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(response.get_json()['reader_sync']['status'], 'PASS')
        self.assertEqual(json.loads((self.job / 'status.json').read_text())['reader_sync']['status'], 'PASS')
        self.assertTrue(list(self.html.glob('libraries/*/versions/v2/index.html')))
        self.assertEqual(len(json.loads((self.workspace / 'review_notes/demo/v2/representative_files.json').read_text())['files']), 1)

    def test_retry_after_success_keeps_one_evidence_row(self):
        self.assertEqual(self.retry().status_code, 200)
        first = json.loads((self.workspace / 'review_notes/demo/v2/representative_files.json').read_text())
        response = self.retry()
        self.assertEqual(response.status_code, 200, response.get_json())
        second = json.loads((self.workspace / 'review_notes/demo/v2/representative_files.json').read_text())
        self.assertEqual(first, second)
        self.assertEqual(response.get_json()['reader_sync']['status'], 'PASS')

    def test_failed_job_and_wrong_action_are_rejected(self):
        status = json.loads((self.job / 'status.json').read_text())
        status['status'] = 'FAILED'
        status['return_code'] = 1
        self.write('status.json', status)
        self.assertEqual(self.retry().status_code, 400)
        status['status'] = 'COMPLETED'
        status['return_code'] = 0
        self.write('status.json', status)
        request = json.loads((self.job / 'request.json').read_text())
        request['action'] = 'scan'
        self.write('request.json', request)
        self.assertEqual(self.retry().status_code, 400)

    def test_retry_rejects_changed_report_target(self):
        request = json.loads((self.job / 'request.json').read_text())
        request['reader_target']['catalog_html'] = str(self.root / 'other/html')
        self.write('request.json', request)
        self.assertEqual(self.retry().status_code, 400)
        self.assertFalse((self.workspace / 'review_notes/demo/v2/representative_files.json').exists())

    def test_semantic_retry_uses_persisted_profile_and_start_time(self):
        request = json.loads((self.job / 'request.json').read_text())
        request['action'] = 'semantic-review'
        request['reader_target']['profile_config_path'] = str(self.root / 'profile.yml')
        self.write('request.json', request)
        status = json.loads((self.job / 'status.json').read_text())
        status['action'] = 'semantic-review'
        self.write('status.json', status)
        with patch('lib_guard.review.publication.sync_operator_result', return_value={'status': 'SKIPPED', 'reason': 'no artifacts'}) as sync:
            response = self.retry()
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(response.get_json()['reader_sync']['status'], 'SKIPPED')
        self.assertEqual(sync.call_args.kwargs['started_epoch'], 123.0)
        self.assertEqual(sync.call_args.kwargs['profile_config_path'], str(self.root / 'profile.yml'))


if __name__ == '__main__':
    unittest.main()
