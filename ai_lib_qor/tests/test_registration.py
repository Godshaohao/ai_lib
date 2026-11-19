import tempfile
import unittest
from pathlib import Path
from ai_lib_qor.workbench.registration import register_delivery
from ai_lib_qor.workbench.scans import run_scan

class RegistrationTests(unittest.TestCase):
    def test_register_confirmed_mapping_and_detect_changed_raw(self):
        with tempfile.TemporaryDirectory() as d:
            base=Path(d); (base/'work').mkdir(); raw=base/'raw'; (raw/'V1').mkdir(parents=True)
            f=raw/'V1'/'core.lef'; f.write_text('first')
            source={'vendor_id':'v','source_library_id':'lib','root':str(raw)}
            scan=run_scan(base/'runs',source)
            metadata={'delivery_id':'d1','supplier_version':'V1','delivery_order':1,'package_mode':'FULL'}
            f.write_text('changed')
            with self.assertRaisesRegex(ValueError,'变化'):
                register_delivery(base/'work',source,scan,'V1',metadata,{'core.lef':{'file_key':'lib:lef:core'}})
            self.assertFalse((base/'work/libraries/v/lib/delivery_001.json').exists())
            scan=run_scan(base/'runs',source)
            path=register_delivery(base/'work',source,scan,'V1',metadata,{'core.lef':{'file_key':'lib:lef:core'}})
            self.assertTrue(path.is_file());self.assertTrue(path.with_name('evidence_'+path.stem+'.json').is_file())
            with self.assertRaises((FileExistsError,ValueError)):
                register_delivery(base/'work',source,scan,'V1',metadata,{'core.lef':{'file_key':'lib:lef:core'}})

    def test_web_registers_scanned_files(self):
        import json
        from ai_lib_qor.workbench.app import create_app
        with tempfile.TemporaryDirectory() as d:
            base=Path(d);raw=base/'raw';(raw/'V1').mkdir(parents=True);(raw/'V1/core.lef').write_text('data')
            work=base/'work';work.mkdir();plans=base/'plans';plans.mkdir();runs=base/'runs'
            (work/'scan_sources.json').write_text(json.dumps({'sources':[{'vendor_id':'v','source_library_id':'lib','root':str(raw)}]}))
            client=create_app(plans,runs,work).test_client()
            with client.session_transaction() as session:session['csrf']='t'
            client.post('/scan',data={'csrf':'t','vendor':'v','library':'lib'})
            page=client.get('/registration?vendor=v&library=lib&version=V1')
            self.assertEqual(page.status_code,200);self.assertIn('core.lef',page.get_data(as_text=True))
            scan_id=next((runs/'scans').glob('scan_*.json')).stem
            response=client.post('/registration',data={'scan_id':scan_id,'csrf':'t','vendor':'v','library':'lib','version':'V1','delivery_id':'d1','supplier_version':'V1','delivery_order':'1','package_mode':'FULL','file_key_0':'lib:lef:core'})
            self.assertEqual(response.status_code,303)
            self.assertTrue((work/'libraries/v/lib/delivery_001.json').is_file())

    def test_registered_delivery_visible_before_ip_exists(self):
        import json
        from ai_lib_qor.workbench.app import create_app
        with tempfile.TemporaryDirectory() as d:
            base=Path(d);raw=base/'raw';(raw/'V1').mkdir(parents=True);(raw/'V1/core.lef').write_text('x')
            work=base/'work';work.mkdir();plans=base/'plans';plans.mkdir();runs=base/'runs'
            source={'vendor_id':'v','source_library_id':'lib','root':str(raw)}
            (work/'scan_sources.json').write_text(json.dumps({'sources':[source]}))
            scan=run_scan(runs,source)
            register_delivery(work,source,scan,'V1',{'delivery_id':'d1','supplier_version':'V1','delivery_order':1,'package_mode':'FULL'},{'core.lef':{'file_key':'lib:lef:core'}})
            client=create_app(plans,runs,work).test_client()
            body=client.get('/?view=discover').get_data(as_text=True)
            self.assertIn('进入库工作台',body)
            detail=client.get('/library?vendor=v&library=lib').get_data(as_text=True)
            self.assertIn('d1',detail);self.assertIn('交付版本时间线',detail)
