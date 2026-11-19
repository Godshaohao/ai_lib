import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ai_lib_qor.sources.delivery_builder import build_delivery
from ai_lib_qor.sources.formal_sync import sync_formal
from ai_lib_qor.application.data_query import LibraryDataQuery
from ai_lib_qor.application.simple_sources import simple_raw
from ai_lib_qor.application.effective_json import create_revision


class FileIndexV3Tests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
  self.work=self.root/'work';self.folder=self.work/'libraries/v/lib';self.folder.mkdir(parents=True)
  self.formal=self.root/'formal';self.formal.mkdir();self.records=[]
  for n in (1,2):
   raw=self.root/f'raw{n}';raw.mkdir();(raw/'a.lef').write_text('LEF')
   if n==1:(raw/'keep.lib').write_text('LIB')
   mapping={'a.lef':{'file_key':'lib:lef:a'}}
   if n==1:mapping['keep.lib']={'file_key':'lib:lib:keep'}
   meta={'delivery_id':f'd{n}','vendor_id':'v','source_library_id':'lib','supplier_version':f'V0{n}',
         'delivery_order':n,'received_at':'2026-01-01T00:00:00Z','package_mode':'UNKNOWN'}
   d=build_delivery(raw,meta,mapping);self.records.append(d)
   (self.folder/f'delivery_{n:03}.json').write_text(json.dumps(d))
  cfg={'sources':[{'vendor_id':'v','source_library_id':'lib','root':str(self.root),'delivery_orders':{'V01':1,'V02':2}}]}
  (self.work/'scan_sources.json').write_text(json.dumps(cfg))
  (self.formal/'a.lef').symlink_to(self.root/'raw1/a.lef')
  self.snap=sync_formal(self.root/'runs',{'formal_nl_id':'NL1','root':str(self.formal)},self.records,self.work)
  (self.folder/'file_index.json').unlink(missing_ok=True)
  q=LibraryDataQuery(self.work,self.root/'runs');owner={'type':'SOURCE_LIBRARY','id':'lib'}
  old=create_revision(simple_raw(q,'v','lib','V01'),owner=owner,revision='rev_0001',created_at='t',include_views=['LEF','LIBERTY'])
  new=create_revision(simple_raw(q,'v','lib','V02'),owner=owner,revision='rev_0002',created_at='t',include_views=['LEF'],parent=old)
  for n,r in ((1,old),(2,new)):(self.folder/f'effective_lib_{n:03}.json').write_text(json.dumps(r))

 def test_complete_raw_formal_and_effective_projection(self):
  from ai_lib_qor.application.file_index_v3 import build_library_index
  with patch('os.walk',side_effect=AssertionError('不得扫描 RAW 或 Formal')),patch('os.readlink',side_effect=AssertionError('不得重新读取链接')):
   data=build_library_index(self.work,'v','lib')
  self.assertEqual(data['schema'],'file_index.v3')
  self.assertEqual([x['delivery_id'] for x in data['deliveries']],['d2','d1'])
  a=data['views']['LEF']['files']['a.lef']
  self.assertEqual([x['delivery_id'] for x in a['raw']],['d2','d1'])
  self.assertTrue(all(x['file_key'] is None for x in a['raw']))
  self.assertEqual(a['formal'][0]['raw_source']['delivery_id'],'d1')
  self.assertEqual([x['delivery_id'] for x in a['effective']['lib']],['d2','d1'])
  keep=data['views']['LIBERTY']['files']['keep.lib']
  self.assertEqual([x['delivery_id'] for x in keep['effective']['lib']],['d1','d1'])

 def test_formal_reference_with_wrong_root_is_not_claimed_matched(self):
  from ai_lib_qor.application.file_index_v3 import build_library_index
  p=self.folder/'delivery_001.json';d=json.loads(p.read_text());d['source_root']=str(self.root/'moved');p.write_text(json.dumps(d))
  data=build_library_index(self.work,'v','lib')
  self.assertNotIn('formal',data['views']['LEF']['files']['a.lef'])
  self.assertEqual(data['views']['LEF']['unmatched_formal'][0]['source_match'],'MATCHED_RAW')

 def test_cli_and_web_share_v3_projection(self):
  import subprocess,sys
  from ai_lib_qor.workbench.app import create_app
  plans=self.root/'plans';plans.mkdir()
  args={'kind':'index-v3','vendor':'v','library':'lib'}
  response=create_app(plans,self.root/'runs',self.work).test_client().get('/api/library-data',query_string=args)
  self.assertEqual(response.status_code,200)
  proc=subprocess.run([sys.executable,'-m','ai_lib_qor','data-query','--work',str(self.work),'--runs',str(self.root/'runs'),
                       '--kind','index-v3','--vendor','v','--library','lib'],capture_output=True,text=True)
  self.assertEqual(proc.returncode,0,proc.stderr);self.assertEqual(response.get_json(),json.loads(proc.stdout))

 def test_absent_referenced_delivery_refuses_incomplete_index(self):
  from ai_lib_qor.application.file_index_v3 import build_library_index
  (self.folder/'delivery_002.json').unlink()
  with self.assertRaises(ValueError):build_library_index(self.work,'v','lib')

 def test_saved_index_refresh_and_stale_detection(self):
  from ai_lib_qor.application.file_index import refresh_library_index_locked
  from ai_lib_qor.versions.store import locked
  source=json.loads((self.work/'scan_sources.json').read_text())['sources'][0]
  with locked(self.folder):first=refresh_library_index_locked(self.work,'v','lib',source)
  self.assertEqual(first['action'],'REBUILD')
  path=self.folder/'file_index.json';saved=json.loads(path.read_text());self.assertEqual(saved['schema'],'file_index.v3')
  q=LibraryDataQuery(self.work,self.root/'runs');self.assertEqual(q.file_index_status('v','lib')['status'],'VALID')
  with locked(self.folder):again=refresh_library_index_locked(self.work,'v','lib',source)
  self.assertEqual(again['action'],'UNCHANGED')
  # The historical record exists but the saved projection omits it (interrupted publication).
  saved['effective_sets'].clear();path.write_text(json.dumps(saved))
  q=LibraryDataQuery(self.work,self.root/'runs');self.assertEqual(q.file_index_status('v','lib')['status'],'STALE')
  with locked(self.folder):recovered=refresh_library_index_locked(self.work,'v','lib',source)
  self.assertEqual(recovered['action'],'APPEND')

 def test_cross_library_effective_reference_has_explicit_scope(self):
  from ai_lib_qor.application.file_index_v3 import build_library_index
  external=self.work/'libraries/other/otherlib';external.mkdir(parents=True)
  root=self.root/'otherraw';root.mkdir();(root/'a.lef').write_text('LEF')
  meta={'delivery_id':'dx','vendor_id':'other','source_library_id':'otherlib','supplier_version':'VX',
        'delivery_order':1,'received_at':'2026-01-01T00:00:00Z','package_mode':'UNKNOWN'}
  record=build_delivery(root,meta,{'a.lef':{'file_key':'otherlib:lef:a'}})
  (external/'delivery_001.json').write_text(json.dumps(record))
  q=LibraryDataQuery(self.work,self.root/'runs')
  old=json.loads((self.folder/'effective_lib_001.json').read_text())
  cross=create_revision(simple_raw(q,'other','otherlib','VX'),owner=old['owner'],revision='rev_0002',
     created_at='t',include_views=['LEF'],parent=old,allow_cross_library=True)
  (self.folder/'effective_lib_002.json').write_text(json.dumps(cross))
  result=build_library_index(self.work,'v','lib')
  row=result['views']['LEF']['files']['a.lef']['effective']['lib'][0]
  self.assertEqual(row['source_scope'],{'vendor':'other','library':'otherlib'})
  self.assertEqual(row['delivery_id'],'dx');self.assertEqual(row['source_path'],'a.lef')

 def test_missing_parent_is_rejected(self):
  from ai_lib_qor.application.file_index_v3 import build_library_index
  path=self.folder/'effective_lib_002.json';record=json.loads(path.read_text());record['parent']='rev_0009';path.write_text(json.dumps(record))
  with self.assertRaisesRegex(ValueError,'父记录缺失'):build_library_index(self.work,'v','lib')

 def test_formal_sync_refreshes_saved_projection(self):
  from ai_lib_qor.application.file_index import refresh_library_index_locked
  from ai_lib_qor.versions.store import locked
  source=json.loads((self.work/'scan_sources.json').read_text())['sources'][0]
  with locked(self.folder):refresh_library_index_locked(self.work,'v','lib',source)
  link=self.formal/'a.lef';link.unlink();link.symlink_to(self.root/'raw2/a.lef')
  result=sync_formal(self.root/'runs',{'formal_nl_id':'NL1','root':str(self.formal)},self.records,self.work)
  self.assertEqual(result['snapshot_action'],'CREATED')
  self.assertEqual(result['snapshots'][0]['file_index_action'],'APPEND')
  data=json.loads((self.folder/'file_index.json').read_text())
  self.assertEqual(len(data['formal_nl']['NL1']['snapshots']),2)
  self.assertEqual(len(data['views']['LEF']['files']['a.lef']['formal']),2)

 def test_effective_publish_refreshes_saved_projection(self):
  from ai_lib_qor.application.file_index import refresh_library_index_locked
  from ai_lib_qor.application.effective_publisher import publish_v2
  from ai_lib_qor.versions.store import locked
  p1=self.folder/'effective_lib_001.json';p2=self.folder/'effective_lib_002.json'
  old=json.loads(p1.read_text());new=json.loads(p2.read_text());p1.unlink();p2.unlink()
  source=json.loads((self.work/'scan_sources.json').read_text())['sources'][0]
  with locked(self.folder):refresh_library_index_locked(self.work,'v','lib',source)
  publish_v2(self.work,p1,old)
  self.assertEqual(len(json.loads((self.folder/'file_index.json').read_text())['effective_sets']['lib']['revisions']),1)
  publish_v2(self.work,p2,new,old)
  data=json.loads((self.folder/'file_index.json').read_text())
  self.assertEqual([x['revision'] for x in data['effective_sets']['lib']['revisions']],['rev_0002','rev_0001'])

 def test_flat_v1_revision_is_projected(self):
  from ai_lib_qor.application.file_index_v3 import build_library_index
  from ai_lib_qor.versions.service import run_version
  (self.folder/'effective_lib_001.json').unlink();(self.folder/'effective_lib_002.json').unlink()
  run_version('init',effective_dir=self.folder/'effective_lib',delivery=self.folder/'delivery_001.json',
              set_id='lib',owner_type='SOURCE_LIBRARY',owner_id='lib',home_library='lib')
  data=build_library_index(self.work,'v','lib')
  self.assertEqual(data['effective_sets']['lib']['revisions'][0]['revision'],'rev_0001')
  self.assertTrue(data['views']['LEF']['files']['a.lef']['effective']['lib'])

 def test_logical_compare_matches_confirmed_rename_only(self):
  old=self.records[0];new=self.records[1];raw=self.root/'raw2';(raw/'b.lef').write_text('LEF')
  meta={k:new[k] for k in ('delivery_id','vendor_id','source_library_id','supplier_version','delivery_order','received_at','package_mode')}
  renamed=build_delivery(raw,meta,{'b.lef':{'file_key':'lib:lef:a'}})
  (self.folder/'delivery_002.json').write_text(json.dumps(renamed))
  revision_path=self.folder/'effective_lib_002.json';revision=json.loads(revision_path.read_text());revision['views']['LEF']={'b.lef':'V02'};revision_path.write_text(json.dumps(revision))
  for n,path in ((1,'a.lef'),(2,'b.lef')):
   (self.folder/f'evidence_delivery_{n:03}.json').write_text(json.dumps({'classification':{path:{'basis':'explicit'}}}))
  q=LibraryDataQuery(self.work,self.root/'runs')
  result=q.compare_revisions_logical('v','lib','lib','rev_0001','rev_0002')
  changed=[x for x in result['files'] if x['change']=='SOURCE_CHANGED']
  self.assertEqual(len(changed),1);self.assertEqual(changed[0]['match_basis'],'CONFIRMED_KEY')
  self.assertEqual((changed[0]['before']['path'],changed[0]['after']['path']),('a.lef','b.lef'))
  (self.folder/'evidence_delivery_002.json').write_text(json.dumps({'classification':{'b.lef':{'basis':'filename_unique_candidate'}}}))
  q=LibraryDataQuery(self.work,self.root/'runs');result=q.compare_revisions_logical('v','lib','lib','rev_0001','rev_0002')
  self.assertEqual(sorted(x['change'] for x in result['files']),['ADDED','REMOVED','UNCHANGED'])
