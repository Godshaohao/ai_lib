import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from ai_lib_qor.workbench.app import create_app

ROOT=Path(__file__).resolve().parents[1]


class WebProgressTests(unittest.TestCase):
    def test_check_reports_stage_during_execution_and_keeps_output(self):
        from ai_lib_qor.application.pipeline import check_plan
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);plans=ROOT/'examples/overall_demo/dataset/plans'
            app=create_app(plans,root/'runs');app.testing=True
            starter=app.test_client();watcher=app.test_client()
            with starter.session_transaction() as session:session['csrf']='t'
            watcher.set_cookie('session',starter.get_cookie('session').value)
            entered=threading.Event();release=threading.Event();responses=[];op='c'*32
            def slow_check(*args):
                entered.set();release.wait(5);return check_plan(*args)
            def do_post():responses.append(starter.post('/runs',data={'csrf':'t','plan':'rev_0002.json','_operation_id':op}))
            with patch('ai_lib_qor.application.runs.check_plan',side_effect=slow_check):
                thread=threading.Thread(target=do_post);thread.start()
                try:
                    self.assertTrue(entered.wait(3))
                    status=watcher.get('/operations/'+op).get_json()
                    self.assertEqual(status['state'],'RUNNING');self.assertIn('质量检查',status['message'])
                    self.assertIsNone(status['total'])
                finally:release.set();thread.join(10)
            self.assertFalse(thread.is_alive());self.assertEqual(responses[0].status_code,303)
            status=watcher.get('/operations/'+op).get_json()
            self.assertEqual(status['state'],'SUCCEEDED')
            self.assertTrue(any('report.xlsx' in event for event in status['events']))
            self.assertTrue(list((root/'runs').glob('run_*/report.xlsx')))

    def test_scan_progress_is_observable_while_request_is_running(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);work=root/'work';work.mkdir()
            (work/'scan_sources.json').write_text(json.dumps({'sources':[{'vendor_id':'v','source_library_id':'lib','root':str(root/'raw')}]}))
            app=create_app(ROOT/'examples/pipeline',root/'runs',work);app.testing=True
            starter=app.test_client(); watcher=app.test_client(); outsider=app.test_client()
            with starter.session_transaction() as session:session['csrf']='test-token'
            watcher.set_cookie('session',starter.get_cookie('session').value)
            entered=threading.Event();release=threading.Event();responses=[]
            def slow_scan(*args,**kwargs):
                entered.set();release.wait(5)
                return {'scan_id':'x','status':'COMPLETE'}
            op='a'*32
            def do_post():responses.append(starter.post('/scan',data={'csrf':'test-token','vendor':'v','library':'lib','_operation_id':op}))
            with patch('ai_lib_qor.workbench.app.run_scan_and_ingest',side_effect=slow_scan):
                thread=threading.Thread(target=do_post);thread.start()
                try:
                    self.assertTrue(entered.wait(3))
                    status=watcher.get('/operations/'+op).get_json()
                    self.assertEqual(status['state'],'RUNNING')
                    self.assertIn('lib',status['message'])
                    self.assertEqual((status['completed'],status['total']),(0,1))
                    self.assertEqual(outsider.get('/operations/'+op).status_code,404)
                finally:release.set();thread.join(5)
            self.assertFalse(thread.is_alive())
            self.assertEqual(responses[0].status_code,303)
            self.assertEqual(watcher.get('/operations/'+op).get_json()['state'],'SUCCEEDED')

    def test_failed_scan_is_not_reported_as_success(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);work=root/'work';work.mkdir()
            (work/'scan_sources.json').write_text(json.dumps({'sources':[{'vendor_id':'v','source_library_id':'lib','root':str(root/'missing')}]}))
            app=create_app(ROOT/'examples/pipeline',root/'runs',work);client=app.test_client()
            with client.session_transaction() as session:session['csrf']='t'
            op='b'*32
            self.assertEqual(client.post('/scan',data={'csrf':'t','vendor':'v','library':'lib','_operation_id':op}).status_code,303)
            result=client.get('/operations/'+op).get_json()
            self.assertEqual(result['state'],'FAILED');self.assertIn('扫描',result['message'])

    def test_in_place_modification_is_reported_as_partial(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);work=root/'work';work.mkdir()
            (work/'scan_sources.json').write_text(json.dumps({'sources':[{'vendor_id':'v','source_library_id':'lib','root':str(root/'raw')}]}))
            app=create_app(ROOT/'examples/pipeline',root/'runs',work);client=app.test_client()
            with client.session_transaction() as session:session['csrf']='t'
            op='d'*32
            row={'scan_id':'scan_test','status':'COMPLETE'}
            ingest={'created':0,'duplicates':0,'modified':1,'blocked':0,'unresolved':0,'reasons':['RAW 原地变化']}
            with patch('ai_lib_qor.workbench.app.run_scan_and_ingest',return_value=row), patch('ai_lib_qor.workbench.app.ingest_result',return_value=ingest):
                response=client.post('/scan',data={'csrf':'t','vendor':'v','library':'lib','_operation_id':op})
            self.assertEqual(response.status_code,303)
            result=client.get('/operations/'+op).get_json()
            self.assertEqual(result['state'],'PARTIAL');self.assertIn('RAW 原地变化',result['message'])


if __name__=='__main__':unittest.main()
