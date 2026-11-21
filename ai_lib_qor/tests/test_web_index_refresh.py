import tempfile
import unittest
from pathlib import Path
from test_v3_index_check_flow import make_fixture
from ai_lib_qor.workbench.app import create_app


class WebIndexRefreshTests(unittest.TestCase):
    def test_v2_ip_is_visible_in_library_scope_and_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            work, _ = make_fixture(root)
            plans = root / 'plans'
            plans.mkdir()
            client = create_app(plans, root / 'runs', work).test_client()
            html = client.get('/library?vendor=v&library=lib').get_data(as_text=True)
            self.assertIn('IP · core_ip', html)
            self.assertIn('1</strong><small>关联有效版本 IP', html)
            self.assertNotIn('尚无已登记 IP', html)
            self.assertLess(html.index('id="effective-files"'), html.index('id="file-history"'))

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

class WebDeliveryPolicyTests(unittest.TestCase):
    def test_exclude_delivery_with_csrf_and_show_impact(self):
        import json
        from ai_lib_qor.workbench.app import create_app
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);work,_=make_fixture(root);plans=root/'plans';plans.mkdir()
            client=create_app(plans,root/'runs',work).test_client()
            query='vendor=v&library=lib&set_id=core_ip&revision=rev_0003'
            page=client.get('/library?'+query)
            self.assertIn('排除此交付',page.get_data(as_text=True))
            args={'vendor':'v','library':'lib','set_id':'core_ip','revision':'rev_0003','delivery_id':'d2','action':'exclude','actor':'operator','reason':'test'}
            self.assertEqual(client.post('/delivery/policy',data=args).status_code,403)
            with client.session_transaction() as session:args['csrf']=session['csrf']
            response=client.post('/delivery/policy',data=args)
            self.assertEqual(response.status_code,302)
            page=client.get(response.location).get_data(as_text=True)
            self.assertIn('当前版本仍引用',page)
            self.assertIn('恢复参与',page)
            config=json.loads((work/'scan_sources.json').read_text())
            self.assertEqual(config['sources'][0]['excluded_delivery_ids']['core_ip'],['d2'])

    def test_restore_historical_version_through_web(self):
        from ai_lib_qor.workbench.app import create_app
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);work,_=make_fixture(root);plans=root/'plans';plans.mkdir()
            client=create_app(plans,root/'runs',work).test_client()
            page=client.get('/library?vendor=v&library=lib&set_id=core_ip&revision=rev_0001')
            self.assertIn('恢复历史文件组合',page.get_data(as_text=True))
            with client.session_transaction() as session:csrf=session['csrf']
            result=client.post('/effective/restore',data={'csrf':csrf,'vendor':'v','library':'lib','set_id':'core_ip','revision':'rev_0001','expected_parent':'rev_0003','actor':'operator','reason':'test'})
            self.assertEqual(result.status_code,302)
            self.assertIn('已创建恢复版本',client.get(result.location).get_data(as_text=True))
            self.assertTrue((work/'libraries/v/lib/effective_core_ip_004.json').is_file())
