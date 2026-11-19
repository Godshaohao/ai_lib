import tempfile
import unittest
from pathlib import Path
from ai_lib_qor.sources.update_scan import scan_library, compare_scans

class UpdateScanTest(unittest.TestCase):
    def test_new_changed_removed_and_raw_untouched(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); (root/'v1').mkdir(); p=root/'v1/a.lef'; p.write_text('before')
            first=scan_library(root,'vendor','library')
            p.write_text('after'); (root/'v1/b.lib').write_text('new')
            second=scan_library(root,'vendor','library')
            self.assertEqual(compare_scans(first,second),{'added':['v1/b.lib'],'changed':['v1/a.lef'],'removed':[]})
            self.assertEqual(p.read_text(),'after')
            p.unlink(); third=scan_library(root,'vendor','library')
            self.assertEqual(compare_scans(second,third)['removed'],['v1/a.lef'])

    def test_symlink_or_partial_does_not_establish_removal(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); (root/'a').write_text('x'); first=scan_library(root,'v','l')
            (root/'a').unlink(); (root/'link').symlink_to('/nonexistent')
            second=scan_library(root,'v','l')
            self.assertEqual(second['status'],'PARTIAL')
            with self.assertRaises(ValueError): compare_scans(first,second)

class WorkbenchScanTest(unittest.TestCase):
    def test_scan_configured_source_and_persist_observations(self):
        import json
        from ai_lib_qor.workbench.app import create_app
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); raw=root/'raw';raw.mkdir();(raw/'a.lef').write_text('one')
            work=root/'work';work.mkdir();plans=root/'plans';plans.mkdir()
            (work/'scan_sources.json').write_text(json.dumps({'sources':[{'vendor_id':'v','source_library_id':'lib','root':str(raw)}]}))
            client=create_app(plans,root/'runs',work).test_client()
            with client.session_transaction() as session: session['csrf']='test'
            before=client.get('/?view=discover').get_data(as_text=True)
            self.assertIn('尚未扫描',before)
            self.assertEqual(client.post('/scan',data={'csrf':'test','vendor':'v','library':'lib'}).status_code,303)
            (raw/'a.lef').write_text('two')
            self.assertEqual(client.post('/scan',data={'csrf':'test','vendor':'v','library':'lib'}).status_code,303)
            body=client.get('/?view=discover').get_data(as_text=True)
            self.assertIn('进入库工作台',body);self.assertIn('元数据变化',body)
            self.assertEqual(len(list((root/'runs'/'scans').glob('*.json'))),2)
            self.assertEqual(client.post('/scan',data={'csrf':'test','vendor':'x','library':'lib'}).status_code,400)

    def test_unavailable_source_is_recorded_as_failed(self):
        import json
        from ai_lib_qor.workbench.scans import run_scan
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);source={'vendor_id':'v','source_library_id':'lib','root':str(root/'missing')}
            result=run_scan(root/'runs',source)
            self.assertEqual(result['status'],'FAILED')
            self.assertTrue(result['errors'])
            self.assertEqual(len(list((root/'runs'/'scans').glob('*.json'))),1)

    def test_first_scan_displays_observed_files(self):
        import json
        from ai_lib_qor.workbench.app import create_app
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);raw=root/'raw';raw.mkdir();(raw/'core.lef').write_text('data')
            work=root/'work';work.mkdir();plans=root/'plans';plans.mkdir()
            (work/'scan_sources.json').write_text(json.dumps({'sources':[{'vendor_id':'v','source_library_id':'lib','root':str(raw)}]}))
            client=create_app(plans,root/'runs',work).test_client()
            with client.session_transaction() as session:session['csrf']='test'
            client.post('/scan',data={'csrf':'test','vendor':'v','library':'lib'})
            body=client.get('/?view=discover').get_data(as_text=True)
            self.assertIn('进入库工作台',body)
            detail=client.get('/library?vendor=v&library=lib').get_data(as_text=True)
            self.assertIn('core.lef',detail)

    def test_scan_overview_distinguishes_global_scope_and_states(self):
        import json
        from ai_lib_qor.workbench.app import create_app
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);raw=root/'raw';raw.mkdir();(raw/'a.lef').write_text('one')
            work=root/'work';work.mkdir();plans=root/'plans';plans.mkdir()
            (work/'scan_sources.json').write_text(json.dumps({'sources':[{'vendor_id':'v','source_library_id':'lib','root':str(raw)}]}))
            client=create_app(plans,root/'runs',work).test_client()
            with client.session_transaction() as session:session['csrf']='test'
            body=client.get('/?view=discover').get_data(as_text=True)
            self.assertIn('全部已配置库',body);self.assertIn('尚未扫描',body)
            client.post('/scan',data={'csrf':'test','vendor':'v','library':'lib'})
            body=client.get('/?view=discover').get_data(as_text=True)
            self.assertIn('已建立首次观察基线',body);self.assertIn('进入库工作台',body)
            self.assertIn('按库名筛选',body)

    def test_fast_scanning_uses_metadata_without_reading_file_contents(self):
        from unittest.mock import patch
        from ai_lib_qor.workbench.scans import run_scan
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);raw=root/'raw';raw.mkdir();(raw/'a.lef').write_text('hello')
            source={'vendor_id':'v','source_library_id':'l','root':str(raw)}
            with patch('pathlib.Path.open',side_effect=AssertionError('content read')):
                scan=run_scan(root/'runs',source)
            self.assertEqual(scan['comparison_method'],'size_mtime_ns')
            self.assertNotIn('sha256',scan['files'][0]);self.assertIn('mtime_ns',scan['files'][0])

    def test_scan_all_processes_each_configured_library(self):
        import json
        from ai_lib_qor.workbench.app import create_app
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);work=root/'work';work.mkdir();plans=root/'plans';plans.mkdir()
            data=[]
            for i in range(2):
                raw=root/f'raw{i}';raw.mkdir();(raw/'a').write_text('x');data.append({'vendor_id':'v','source_library_id':f'l{i}','root':str(raw)})
            (work/'scan_sources.json').write_text(json.dumps({'sources':data}))
            client=create_app(plans,root/'runs',work).test_client()
            with client.session_transaction() as session:session['csrf']='t'
            response=client.post('/scan-all',data={'csrf':'t'})
            self.assertEqual(response.status_code,303)
            self.assertEqual(len(list((root/'runs/scans').glob('*.json'))),2)
