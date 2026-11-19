import json
import shutil
import tempfile
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

class LibraryCatalogTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name); self.work=self.root/'work'; self.runs=self.root/'runs'
        shutil.copytree(ROOT/'examples/work',self.work)

    def catalog(self):
        from ai_lib_qor.application.library_catalog import LibraryCatalog
        return LibraryCatalog(self.work,self.runs).refresh()

    def test_library_and_file_history_do_not_require_ip_or_scan_config(self):
        source=self.work/'vendors/vendor_orion/libraries/lib_rtavfs/deliveries/dlv_20260907_001/delivery.json'
        data=json.loads(source.read_text());data['vendor_id']='vendor_new';data['source_library_id']='lib_new'
        path=self.work/'vendors/vendor_new/libraries/lib_new/deliveries'/data['delivery_id']/'delivery.json'
        path.parent.mkdir(parents=True);path.write_text(json.dumps(data))
        cat=self.catalog(); detail=cat.library_detail('vendor_new','lib_new')
        self.assertEqual(len(detail['deliveries']),1)
        self.assertEqual(detail['ips'],[])
        self.assertTrue(detail['file_rows'])
        self.assertIn(('vendor_new','lib_new'),[(r['vendor'],r['library']) for r in cat.overview()['raw_rows']])

    def test_refresh_sees_new_saved_records_without_changing_them(self):
        cat=self.catalog(); self.assertIsNone(cat.library_detail('vendor_new','lib_new'))
        source=self.work/'vendors/vendor_orion/libraries/lib_rtavfs/deliveries/dlv_20260907_001/delivery.json'
        data=json.loads(source.read_text());data['vendor_id']='vendor_new';data['source_library_id']='lib_new'
        path=self.work/'vendors/vendor_new/libraries/lib_new/deliveries'/data['delivery_id']/'delivery.json'
        path.parent.mkdir(parents=True);path.write_text(json.dumps(data)); before=path.read_bytes()
        cat.refresh()
        self.assertEqual(len(cat.library_detail('vendor_new','lib_new')['deliveries']),1)
        self.assertEqual(path.read_bytes(),before)

    def test_formal_source_and_effective_member_trace(self):
        cat=self.catalog(); detail=cat.library_detail('vendor_orion','lib_rtavfs')
        lef=next(r for r in detail['file_rows'] if r['key']=='lib_rtavfs:lef:core')
        self.assertEqual([r['version'] for r in lef['history'][:2]],['V08','V07'])
        formal=cat.formal_detail('NL2.5.3')
        row=next(x for x in formal['links'] if x['snapshot_id']=='snap_nl253_0001' and x['file_key']=='lib_rtavfs:lef:core')
        self.assertEqual((row['vendor'],row['library'],row['raw_version']),('vendor_orion','lib_rtavfs','V07'))
        self.assertIn('rtavfs',row['ips'])
        ip=cat.ip_detail('vendor_orion','lib_rtavfs','rtavfs',revision_id='rev_0002')
        self.assertEqual(len(ip['matrix']['rows']),3)
        ff=next(r for r in ip['matrix']['rows'] if r['file_key']=='lib_rtavfs:liberty:func_ff')
        self.assertEqual(ff['target']['state'],'RESOLVED')
        self.assertEqual(ff['target']['version'],'NL2.5.3')

    def test_refresh_reads_saved_records_without_raw_scanning(self):
        from unittest.mock import patch
        with patch('ai_lib_qor.sources.update_scan.scan_library',side_effect=AssertionError('RAW scanned')):
            cat=self.catalog();cat.overview();cat.library_detail('vendor_orion','lib_rtavfs');cat.formal_detail('NL2.5.3')

    def test_equal_delivery_orders_do_not_claim_latest_file(self):
        source=self.work/'vendors/vendor_orion/libraries/lib_rtavfs/deliveries/dlv_20260907_001/delivery.json'
        data=json.loads(source.read_text());data['delivery_order']=8
        source.write_text(json.dumps(data))
        row=next(r for r in self.catalog().library_detail('vendor_orion','lib_rtavfs')['file_rows'] if r['key']=='lib_rtavfs:lef:core')
        self.assertTrue(row['order_ambiguous'])
        self.assertIsNone(row['latest']);self.assertIsNone(row['previous'])

    def test_ambiguous_cross_vendor_reference_is_not_attributed(self):
        source=self.work/'vendors/vendor_orion/libraries/lib_rtavfs/deliveries/dlv_20260907_001/delivery.json'
        data=json.loads(source.read_text());data['vendor_id']='other_vendor'
        path=self.work/'vendors/other_vendor/libraries/lib_rtavfs/deliveries'/data['delivery_id']/'delivery.json'
        path.parent.mkdir(parents=True);path.write_text(json.dumps(data))
        cat=self.catalog(); formal=cat.formal_detail('NL2.5.3')
        row=next(x for x in formal['links'] if x['snapshot_id']=='snap_nl253_0001' and x['file_key']=='lib_rtavfs:lef:core')
        self.assertEqual(row['resolution'],'AMBIGUOUS');self.assertIsNone(row['vendor']);self.assertIsNone(row['raw_version'])

    def test_identical_snapshot_identity_is_deduplicated(self):
        source=self.work/'formal_nl/NL2.5.3/snapshots/snap_nl253_0001.json'
        folder=self.work/'formal_nl/NL2.5.3/snapshots/duplicate';folder.mkdir()
        shutil.copy(source,folder/'snapshot.json')
        detail=self.catalog().formal_detail('NL2.5.3')
        row=next(x for x in detail['links'] if x['snapshot_id']=='snap_nl253_0001')
        self.assertNotEqual(row['resolution'],'AMBIGUOUS_SNAPSHOT')
        self.assertEqual(sum(s['formal_snapshot_id']=='snap_nl253_0001' for s in detail['snapshots']),1)

    def test_web_formal_detail_uses_saved_snapshots_without_sync(self):
        from ai_lib_qor.workbench.app import create_app
        app=create_app(ROOT/'examples/pipeline',self.runs,self.work)
        result=app.test_client().get('/formal/NL2.5.3')
        self.assertEqual(result.status_code,200)
        body=result.get_data(as_text=True)
        for text in ('vendor_orion','lib_rtavfs','V07','core.lef'):self.assertIn(text,body)

if __name__=='__main__':unittest.main()
