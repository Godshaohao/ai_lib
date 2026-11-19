import tempfile
import unittest
from pathlib import Path
from test_v3_index_check_flow import make_fixture
from ai_lib_qor.workbench.app import create_app


class WebIndexRefreshTests(unittest.TestCase):
    def test_refresh_stale_index_from_archives(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            work, _ = make_fixture(root)
            plans = root / 'plans'
            plans.mkdir()
            index = work / 'libraries/v/lib/file_index.json'
            index.unlink()
            client = create_app(plans, root / 'runs', work).test_client()
            page = client.get('/library?vendor=v&library=lib')
            self.assertIn('刷新文件索引', page.get_data(as_text=True))
            with client.session_transaction() as session:
                csrf = session['csrf']
            response = client.post('/file-index/refresh', data={'vendor': 'v', 'library': 'lib', 'csrf': csrf})
            self.assertEqual(response.status_code, 302)
            self.assertTrue(index.is_file())
            page = client.get(response.location)
            self.assertIn('索引已更新', page.get_data(as_text=True))
