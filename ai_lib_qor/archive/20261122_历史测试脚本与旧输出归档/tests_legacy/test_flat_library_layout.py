import json
import tempfile
import unittest
from pathlib import Path

from ai_lib_qor.application.scans import run_scan_and_ingest, ingest_result
from ai_lib_qor.sources.registration import registered_deliveries
from ai_lib_qor.sources.formal_sync import sync_formal
from ai_lib_qor.application.library_catalog import LibraryCatalog
from ai_lib_qor.versions.service import run_version


class FlatLibraryLayoutTests(unittest.TestCase):
    def test_scan_and_formal_are_flat_and_reused(self):
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp);work=base/'work';work.mkdir();raw=base/'raw';v=raw/'V01';v.mkdir(parents=True)
            target=v/'core.lef';target.write_text('LEF');formal=base/'formal';formal.mkdir();(formal/'core.lef').symlink_to(target)
            source={'vendor_id':'vendor','source_library_id':'lib','root':str(raw),'version_paths':{'V01':'V01'},
                    'file_mapping':{'V01/core.lef':{'file_key':'lib:lef:core'}}}
            scan=run_scan_and_ingest(base/'runs',work,source)
            self.assertEqual(ingest_result(base/'runs',scan)['created'],1)
            folder=work/'libraries/vendor/lib'
            self.assertEqual(len(list(folder.glob('delivery_*.json'))),1)
            deliveries=registered_deliveries(work,source);self.assertEqual(len(deliveries),1)
            cfg={'formal_nl_id':'NL2.5.3','root':str(formal)}
            first=sync_formal(base/'runs',cfg,deliveries,work);second=sync_formal(base/'runs',cfg,deliveries,work)
            self.assertEqual(first['snapshot_action'],'CREATED');self.assertEqual(second['snapshot_action'],'REUSED')
            self.assertEqual(len(list(folder.glob('formal_NL2.5.3_*.json'))),1)
            catalog=LibraryCatalog(work,base/'runs').refresh()
            self.assertEqual(len(catalog.snapshots),1)
            self.assertEqual(len(catalog.libraries[('vendor','lib')]['deliveries']),1)

    def test_flat_effective_revisions_index_acceptance_and_catalog(self):
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp);work=base/'work';folder=work/'libraries/vendor_orion/lib_rtavfs';folder.mkdir(parents=True)
            fixture=Path(__file__).resolve().parents[1]/'examples/work/vendors/vendor_orion/libraries/lib_rtavfs/deliveries'
            sources=[]
            for ident in ('dlv_20260907_001','dlv_20261019_001'):
                data=json.loads((fixture/ident/'delivery.json').read_text());path=folder/f'delivery_{ident}.json'
                path.write_text(json.dumps(data));sources.append(path)
            effective=folder/'effective_rtavfs'
            run_version('init',effective_dir=effective,delivery=sources[0],set_id='rtavfs',owner_type='BUSINESS_IP',owner_id='rtavfs',home_library='lib_rtavfs')
            run_version('accept',effective_dir=effective,revision='rev_0001',actor='tester',reason='review')
            from ai_lib_qor.workbench.app import create_app
            client=create_app(Path(__file__).resolve().parents[1]/'examples/pipeline',base/'runs',work).test_client()
            with client.session_transaction() as session:session['csrf']='token'
            result=client.post('/effective/apply',data={'csrf':'token','vendor':'vendor_orion','library':'lib_rtavfs','ip':'rtavfs','delivery':'dlv_20261019_001'})
            self.assertEqual(result.status_code,303)
            for filename in ('effective_rtavfs_001.json','effective_rtavfs_002.json','effective_rtavfs_index.json','effective_rtavfs_acceptance.jsonl'):
                self.assertTrue((folder/filename).is_file(),filename)
            self.assertFalse(effective.exists())
            catalog=LibraryCatalog(work,base/'runs').refresh()
            self.assertEqual(len(catalog.entries),1)
            self.assertEqual(len(catalog.entries[0]['versions']),2)
            self.assertEqual(catalog.entries[0]['index']['current_accepted_revision'],'rev_0001')

    def test_library_owned_set_is_not_reported_as_business_ip(self):
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp);work=base/'work';folder=work/'libraries/vendor_orion/lib_rtavfs';folder.mkdir(parents=True)
            fixture=Path(__file__).resolve().parents[1]/'examples/work/vendors/vendor_orion/libraries/lib_rtavfs/deliveries/dlv_20260907_001/delivery.json'
            data=json.loads(fixture.read_text());delivery=folder/'delivery_001.json';delivery.write_text(json.dumps(data))
            run_version('init',effective_dir=folder/'effective_lib_rtavfs',delivery=delivery,set_id='lib_rtavfs',owner_type='SOURCE_LIBRARY',owner_id='lib_rtavfs',home_library='lib_rtavfs')
            catalog=LibraryCatalog(work,base/'runs').refresh()
            self.assertEqual(catalog.overview()['ip_total'],0)
            self.assertEqual(len(catalog.library_detail('vendor_orion','lib_rtavfs')['effective_sets']),1)

    def test_ambiguous_cross_vendor_delivery_reference_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            work=Path(temp)/'work';a=work/'libraries/vendor_orion/lib_rtavfs';b=work/'libraries/other_vendor/lib_rtavfs'
            a.mkdir(parents=True);b.mkdir(parents=True)
            fixture=Path(__file__).resolve().parents[1]/'examples/work/vendors/vendor_orion/libraries/lib_rtavfs/deliveries/dlv_20260907_001/delivery.json'
            data=json.loads(fixture.read_text());delivery=a/'delivery_001.json';delivery.write_text(json.dumps(data))
            data['vendor_id']='other_vendor';(b/'delivery_001.json').write_text(json.dumps(data))
            with self.assertRaisesRegex(ValueError,'引用不唯一'):
                run_version('init',effective_dir=a/'effective_lib_rtavfs',delivery=delivery,set_id='lib_rtavfs',owner_type='SOURCE_LIBRARY',owner_id='lib_rtavfs',home_library='lib_rtavfs')


if __name__=='__main__':unittest.main()
