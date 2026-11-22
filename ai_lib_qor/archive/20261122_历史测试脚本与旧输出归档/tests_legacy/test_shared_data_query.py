import json
import shutil
import tempfile
import unittest
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

from ai_lib_qor.application.data_query import LibraryDataQuery

ROOT=Path(__file__).resolve().parents[1]


class SharedDataQueryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.work=self.root/'work';shutil.copytree(ROOT/'examples/work',self.work)
        self.q=LibraryDataQuery(self.work,self.root/'runs')

    def test_raw_views_history_and_offline(self):
        with patch('os.walk',side_effect=AssertionError('来源目录不得扫描')):
            result=self.q.get_raw_files('vendor_orion','lib_rtavfs','V07')
            history=self.q.get_file_history('vendor_orion','lib_rtavfs','LEF','lef/core.lef')
        self.assertEqual(result['context']['version'],'V07')
        self.assertIn('lef/core.lef',result['views']['LEF'])
        self.assertEqual(history['ordering_status'],'ORDER_UNCONFIRMED')
        self.assertIsNone(history['latest'])
        self.assertEqual(len(history['occurrences']),2)

    def test_history_latest_requires_confirmed_comparable_order(self):
        folder=self.work/'vendors/vendor_orion/libraries/lib_rtavfs/deliveries'
        for path in folder.glob('*/delivery.json'):
            (path.parent/'source_evidence.json').write_text(json.dumps({'order_basis':'configured_order'}))
        q=LibraryDataQuery(self.work,self.root/'runs')
        history=q.get_file_history('vendor_orion','lib_rtavfs','LEF','lef/core.lef')
        self.assertEqual(history['ordering_status'],'CONFIRMED')
        self.assertEqual(history['latest']['version'],'V08')
        self.assertEqual(history['previous']['version'],'V07')

    def test_confirmed_date_rule_only_sorts_valid_unique_dates(self):
        folder=self.work/'vendors/vendor_orion/libraries/lib_rtavfs/deliveries'
        for i,path in enumerate(sorted(folder.glob('*/delivery.json'))):
            record=json.loads(path.read_text());record['supplier_version']=f'20260{i+1}01_abcdef0';path.write_text(json.dumps(record))
        config={'sources':[{'vendor_id':'vendor_orion','source_library_id':'lib_rtavfs','root':'/offline',
                           'order_rule':{'type':'VERSION_DATE_PREFIX','confirmed':True}}]}
        (self.work/'scan_sources.json').write_text(json.dumps(config))
        q=LibraryDataQuery(self.work,self.root/'runs')
        result=q.get_file_history('vendor_orion','lib_rtavfs','LEF','lef/core.lef')
        self.assertEqual(result['ordering_status'],'CONFIRMED')
        self.assertEqual(result['latest']['version'],'20260201_abcdef0')
        paths=sorted(folder.glob('*/delivery.json'));data=json.loads(paths[1].read_text());data['supplier_version']='20260101_different';paths[1].write_text(json.dumps(data))
        result=LibraryDataQuery(self.work,self.root/'runs').get_file_history('vendor_orion','lib_rtavfs','LEF','lef/core.lef')
        self.assertEqual(result['ordering_status'],'ORDER_UNCONFIRMED');self.assertIsNone(result['latest'])

    def test_effective_and_formal_resolve_saved_refs(self):
        result=self.q.get_effective_files('vendor_orion','lib_rtavfs','rtavfs','rev_0002','LEF')
        self.assertEqual(result['views']['LEF']['lef/core.lef']['version'],'V08')
        formal=self.q.get_formal_files('vendor_orion','lib_rtavfs','NL2.5.3','snap_nl253_0001')
        self.assertTrue(any(formal['views'].values()))
        diff=self.q.compare_effective('vendor_orion','lib_rtavfs','rtavfs','rev_0001','rev_0002')
        self.assertTrue(any(x['action']=='REPLACED' for x in diff['changes']))
        self.assertEqual(diff['meaning'],'SOURCE_RELATIONSHIP_ONLY')

    def test_cli_and_web_share_raw_projection(self):
        from ai_lib_qor.workbench.app import create_app
        args=['--kind','raw','--work',str(self.work),'--runs',str(self.root/'runs'),
              '--vendor','vendor_orion','--library','lib_rtavfs','--version','V07']
        env={**os.environ,'PYTHONPATH':str(ROOT/'src')+os.pathsep+str(ROOT.parent/'src')+os.pathsep+os.environ.get('PYTHONPATH','')}
        cli=subprocess.run([sys.executable,'-m','ai_lib_qor','data-query',*args],capture_output=True,text=True,env=env)
        self.assertEqual(cli.returncode,0,cli.stderr)
        client=create_app(ROOT/'examples/pipeline',self.root/'runs',self.work).test_client()
        response=client.get('/api/library-data',query_string={'kind':'raw','vendor':'vendor_orion','library':'lib_rtavfs','version':'V07'})
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.get_json(),json.loads(cli.stdout))
        self.assertEqual(client.get('/api/library-data?kind=raw').status_code,400)

    def test_cli_and_web_share_formal_v2(self):
        from ai_lib_qor.workbench.app import create_app
        args=['--kind','simple-formal','--work',str(self.work),'--runs',str(self.root/'runs'),
              '--vendor','vendor_orion','--library','lib_rtavfs','--version','NL2.5.3','--snapshot','snap_nl253_0001']
        env={**os.environ,'PYTHONPATH':str(ROOT/'src')+os.pathsep+str(ROOT.parent/'src')+os.pathsep+os.environ.get('PYTHONPATH','')}
        cli=subprocess.run([sys.executable,'-m','ai_lib_qor','data-query',*args],capture_output=True,text=True,env=env)
        self.assertEqual(cli.returncode,0,cli.stderr)
        client=create_app(ROOT/'examples/pipeline',self.root/'runs',self.work).test_client()
        response=client.get('/api/library-data',query_string={'kind':'simple-formal','vendor':'vendor_orion','library':'lib_rtavfs','version':'NL2.5.3','snapshot':'snap_nl253_0001'})
        self.assertEqual(response.status_code,200);self.assertEqual(response.get_json(),json.loads(cli.stdout))
        self.assertEqual(response.get_json()['schema'],'formal.simple.v3')

    def test_spice_suffix_is_presented_as_spice_not_cdl(self):
        from ai_lib_qor.application.data_query import _view
        self.assertEqual(_view('CDL','SPICE/core.spice'),'SPICE')

    def test_raw_projection_keeps_document_and_unknown_files(self):
        p=next(self.work.glob('vendors/vendor_orion/libraries/lib_rtavfs/deliveries/dlv_20260907_001/delivery.json'))
        data=json.loads(p.read_text())
        for i,path in enumerate(('DOC/spec.pdf','DOC/list.xlsx','notes.txt','README.md','misc/data.xyz')):
            data['files'].append({'file_id':f'doc{i}','file_key':None,'classification':'UNRESOLVED','relative_path':path,'view':'OTHER','corner':None,'mode':None})
        p.write_text(json.dumps(data))
        result=LibraryDataQuery(self.work,self.root/'runs').get_raw_files('vendor_orion','lib_rtavfs','V07')
        self.assertEqual(result['views']['DOC']['PDF'],['DOC/spec.pdf'])
        self.assertEqual(result['views']['DOC']['EXCEL'],['DOC/list.xlsx'])
        self.assertEqual(set(result['views']['DOC']['TEXT']),{'notes.txt','README.md'})
        self.assertEqual(result['views']['OTHER'],['misc/data.xyz'])

    def test_duplicate_version_requires_delivery_identity(self):
        original=next(self.work.glob('vendors/vendor_orion/libraries/lib_rtavfs/deliveries/*/delivery.json'))
        data=json.loads(original.read_text());data['delivery_id']='distinct_event'
        folder=original.parent.parent/'distinct_event';folder.mkdir();(folder/'delivery.json').write_text(json.dumps(data))
        q=LibraryDataQuery(self.work,self.root/'runs')
        with self.assertRaisesRegex(ValueError,'不唯一'):
            q.get_raw_files('vendor_orion','lib_rtavfs',data['supplier_version'])
        result=q.get_raw_files('vendor_orion','lib_rtavfs',data['supplier_version'],delivery_id='distinct_event')
        self.assertEqual(result['context']['delivery_id'],'distinct_event')

    def test_formal_unknown_slot_can_link_unique_archived_raw_path(self):
        p=self.work/'formal_nl/NL2.5.3/snapshots/snap_nl253_0001.json'
        data=json.loads(p.read_text());file=data['linked_files'][0]
        file['file_key']=None;file['source_ref']=None;file['source_match']='UNMATCHED';p.write_text(json.dumps(data))
        q=LibraryDataQuery(self.work,self.root/'runs')
        result=q.get_formal_files('vendor_orion','lib_rtavfs','NL2.5.3','snap_nl253_0001')
        row=result['views']['LEF'][file['link_path']]
        self.assertEqual(row['path_match_basis'],'ARCHIVED_PATH_TEXT')
        self.assertEqual(row['raw_source']['delivery_id'],'dlv_20260907_001')
        self.assertIsNone(row['file_key'])
        self.assertEqual(row['source_match'],'UNMATCHED')


if __name__=='__main__':unittest.main()
