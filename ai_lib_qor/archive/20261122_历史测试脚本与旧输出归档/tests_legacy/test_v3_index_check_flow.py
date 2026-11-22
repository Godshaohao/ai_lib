import json
import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile

from ai_lib_qor.application.data_query import LibraryDataQuery
from ai_lib_qor.application.effective_json import create_revision
from ai_lib_qor.application.simple_sources import simple_raw
from ai_lib_qor.application.effective_publisher import publish_v2
from ai_lib_qor.sources.delivery_builder import build_delivery
from ai_lib_qor.sources.formal_sync import sync_formal


def make_fixture(root):
 root=Path(root);work=root/'work';folder=work/'libraries/v/lib';folder.mkdir(parents=True)
 raw=root/'raw';root.joinpath('runs').mkdir()
 paths={'lef/core.lef':'lib:lef:core','lib/core.lib':'lib:liberty:core'}
 cfg={'vendor_id':'v','source_library_id':'lib','root':str(raw),'delivery_orders':{'V01':1,'V02':2,'V03':3}}
 (work/'scan_sources.json').write_text(json.dumps({'sources':[cfg]}))
 records=[]
 for n in (1,2,3):
  folder_raw=raw/f'V0{n}';folder_raw.mkdir(parents=True)
  selected=list(paths) if n==1 else ['lef/core.lef'] if n==2 else ['lib/core.lib']
  for p in selected:
   file=folder_raw/p;file.parent.mkdir(parents=True,exist_ok=True)
   file.write_text(f'MACRO CORE\n SIZE {10 if n==1 else 12} BY 20 ;\n PIN A\n DIRECTION INPUT ;\n END A\nEND CORE\n' if p.endswith('.lef') else 'library(test) { cell(CORE) { pin(A) { direction : input; } } }')
  meta={'delivery_id':f'd{n}','vendor_id':'v','source_library_id':'lib','supplier_version':f'V0{n}','delivery_order':n,'received_at':f'2026-01-0{n}T00:00:00Z','package_mode':'UNKNOWN'}
  record=build_delivery(folder_raw,meta,{p:{'file_key':paths[p]} for p in selected});records.append(record)
  (folder/f'delivery_{n:03}.json').write_text(json.dumps(record))
  observed=[{'path':p,'size':(folder_raw/p).stat().st_size,'mtime_ns':(folder_raw/p).stat().st_mtime_ns} for p in selected]
  (folder/f'evidence_delivery_{n:03}.json').write_text(json.dumps({'order_basis':'configured_order','files':observed,'classification':{p:{'basis':'explicit'} for p in selected}}))
 formal=root/'formal';formal.mkdir();(formal/'core.lef').symlink_to(raw/'V01/lef/core.lef')
 result=sync_formal(root/'runs',{'formal_nl_id':'NL1','root':str(formal)},records,work)
 if result['snapshot_action']!='CREATED':raise RuntimeError(result)
 q=LibraryDataQuery(work,root/'runs');parent=None
 for n in (1,2,3):
  rev=create_revision(simple_raw(q,'v','lib',f'V0{n}'),owner={'type':'BUSINESS_IP','id':'core_ip'},revision=f'rev_{n:04}',created_at=f'2026-01-0{n}',include_views=['LEF','LIBERTY'],parent=parent)
  publish_v2(work,folder/f'effective_core_ip_{n:03}.json',rev,parent);parent=rev
 profile={'pin_pairs':[{'lef_path':'lef/core.lef','liberty_path':'lib/core.lib'}]}
 return work,profile


class V3IndexCheckFlowTests(unittest.TestCase):
 def setUp(self):
  self.t=tempfile.TemporaryDirectory();self.addCleanup(self.t.cleanup);self.root=Path(self.t.name)
  self.work,self.profile=make_fixture(self.root)
 def test_batch_outputs_same_checks_as_version_reports(self):
  from ai_lib_qor.application.v3_checks import run_v3_ip
  result=run_v3_ip(self.work,self.root/'runs',vendor='v',library='lib',set_id='core_ip',profile=self.profile)
  self.assertEqual(result['state'],'SUCCEEDED',result.get('error'))
  folder=self.work/'libraries/v/lib';overall=json.loads((folder/f"overall_{result['id']}.json").read_text())
  self.assertEqual([r['revision'] for r in overall['versions']],['rev_0001','rev_0002','rev_0003'])
  rev3=overall['versions'][2]
  self.assertEqual(rev3['index_source_changes'],1)
  self.assertEqual(rev3['summary']['files_with_new_source'],0)
  for row in overall['versions']:
   child=folder;check=json.loads((child/f"check_{row['run_id']}.json").read_text())
   self.assertEqual(row['summary'],check['summary']);self.assertEqual(row['checks'],check['quality_checks'])
   report=child/f"report_{row['run_id']}.xlsx";self.assertTrue(report.is_file())
   with ZipFile(report) as z:self.assertIn('LEF_LIBERTY_PIN_MATCH',z.read('xl/sharedStrings.xml').decode())
   from openpyxl import load_workbook
   book=load_workbook(report,data_only=True)
   self.assertIn('12-有效文件来源',book.sheetnames)
   self.assertIn('13-版本来源对照',book.sheetnames)
   values=[tuple(x.value for x in r) for r in book['12-有效文件来源']]
   self.assertTrue(any('lef/core.lef' in r for r in values));self.assertTrue(any('lib/core.lib' in r for r in values))
  output=folder/f"overall_{result['id']}.xlsx";self.assertTrue(output.is_file())
  with ZipFile(output) as z:
   text=z.read('xl/sharedStrings.xml').decode();self.assertIn('rev_0003',text);self.assertIn('LEF_LIBERTY_PIN_MATCH',text)
  self.assertGreaterEqual(result['facts_reused'],1)
 def test_missing_and_unconfirmed_are_not_fabricated(self):
  from ai_lib_qor.application.v3_checks import run_v3_ip
  (self.root/'raw/V02/lef/core.lef').unlink()
  result=run_v3_ip(self.work,self.root/'runs',vendor='v',library='lib',set_id='core_ip',profile=self.profile)
  self.assertEqual(result['state'],'PARTIAL');self.assertTrue(any(x['state']=='FAILED' for x in result['children']))
  self.assertTrue((self.work/'libraries/v/lib'/f"overall_{result['id']}.xlsx").is_file())
 def test_wrong_index_and_unsafe_output_are_rejected(self):
  from ai_lib_qor.application.v3_checks import run_v3_ip
  (self.work/'libraries/v/lib/file_index.json').unlink()
  with self.assertRaisesRegex(ValueError,'索引'):run_v3_ip(self.work,self.root/'runs',vendor='v',library='lib',set_id='core_ip',profile=self.profile)
  with self.assertRaises(ValueError):run_v3_ip(self.work,self.root/'raw/V01/output',vendor='v',library='lib',set_id='core_ip',profile=self.profile)

 def test_unconfirmed_identity_does_not_produce_fake_pass(self):
  from ai_lib_qor.application.v3_checks import run_v3_ip
  from ai_lib_qor.application.file_index import refresh_library_index_locked
  from ai_lib_qor.versions.store import locked
  folder=self.work/'libraries/v/lib';path=folder/'evidence_delivery_002.json';data=json.loads(path.read_text())
  data['classification']['lef/core.lef']['basis']='filename_unique_candidate';path.write_text(json.dumps(data))
  source=json.loads((self.work/'scan_sources.json').read_text())['sources'][0]
  with locked(folder):refresh_library_index_locked(self.work,'v','lib',source,force_rebuild=True)
  result=run_v3_ip(self.work,self.root/'runs',vendor='v',library='lib',set_id='core_ip',profile=self.profile)
  self.assertEqual(result['state'],'PARTIAL');failed=[x for x in result['children'] if x['state']=='FAILED']
  self.assertTrue(failed);self.assertTrue(any('未明确确认' in x['error'] for x in failed))

 def test_in_place_raw_modification_is_reported(self):
  from ai_lib_qor.application.v3_checks import run_v3_ip
  (self.root/'raw/V02/lef/core.lef').write_text('modified')
  result=run_v3_ip(self.work,self.root/'runs',vendor='v',library='lib',set_id='core_ip',profile=self.profile)
  self.assertEqual(result['state'],'PARTIAL')
  self.assertTrue(any('不能重现原交付' in (x.get('error') or '') for x in result['children']))

 def test_cli_runs_single_revision_and_selected_batch(self):
  import subprocess,sys
  profile=self.root/'profile.json';profile.write_text(json.dumps(self.profile))
  common=['--work',str(self.work),'--runs',str(self.root/'runs'),'--vendor','v','--library','lib','--set-id','core_ip','--profile',str(profile)]
  single=subprocess.run([sys.executable,'-m','ai_lib_qor','run-v3-revision',*common,'--revision','rev_0002'],capture_output=True,text=True)
  self.assertEqual(single.returncode,0,single.stderr);self.assertEqual(json.loads(single.stdout)['state'],'SUCCEEDED')
  batch=subprocess.run([sys.executable,'-m','ai_lib_qor','run-v3-ip',*common,'--revision','rev_0001','--revision','rev_0003'],capture_output=True,text=True)
  self.assertEqual(batch.returncode,0,batch.stderr);status=json.loads(batch.stdout)
  self.assertEqual([x['revision'] for x in status['children']],['rev_0001','rev_0003'])

 def test_web_uses_same_v3_flow_and_exposes_facts(self):
  from ai_lib_qor.workbench.app import create_app
  plans=self.root/'plans';plans.mkdir();(plans/'v3_profile_core.json').write_text(json.dumps(self.profile))
  client=create_app(plans,self.root/'runs',self.work).test_client()
  page=client.get('/library',query_string={'vendor':'v','library':'lib','set_id':'core_ip','revision':'rev_0002'})
  self.assertEqual(page.status_code,200);self.assertIn('v3_profile_core.json',page.get_data(as_text=True))
  self.assertIn('data-v2-ip="core_ip"',page.get_data(as_text=True))
  with client.session_transaction() as session:csrf=session['csrf']
  data={'csrf':csrf,'vendor':'v','library':'lib','set_id':'core_ip','revision':'rev_0002','profile':'v3_profile_core.json'}
  response=client.post('/index-v3/run',data=data)
  self.assertEqual(response.status_code,303);detail=client.get(response.location)
  self.assertIn('facts_',detail.get_data(as_text=True))
  import html,re
  markup=detail.get_data(as_text=True)
  href=html.unescape(re.search(r'<a href="([^"]+)">← 返回当前 IP 的检查与报告</a>',markup).group(1))
  self.assertIn('/library?',href);self.assertIn('set_id=core_ip',href);self.assertIn('revision=rev_0002',href)
  self.assertEqual(client.get(href).status_code,200)
  from ai_lib_qor.application.library_runs import history as library_history
  run_id=response.location.rsplit('/',1)[-1];row=next(x for x in library_history(self.work) if x['id']==run_id);fact=self.work/'libraries/v/lib'/row['facts_files'][0]
  downloaded=client.get(response.location+'/artifacts/'+fact.name);self.assertEqual(downloaded.status_code,200);downloaded.close()
  batch=client.post('/index-v3/ip',data=data);self.assertEqual(batch.status_code,303)
  status=next(x for x in library_history(self.work) if x['id']==batch.location.rsplit('/',1)[-1])
  self.assertEqual(status['state'],'SUCCEEDED');self.assertEqual(len(status['children']),3)
  import html,re
  batch_html=client.get(batch.location).get_data(as_text=True)
  batch_back=html.unescape(re.search(r'<a href="([^"]+)">← 返回当前 IP 的检查与报告</a>',batch_html).group(1))
  self.assertIn('revision=rev_0003',batch_back);self.assertEqual(client.get(batch_back).status_code,200)
  denied=client.post('/index-v3/run',data={**data,'profile':'../profile.json'});self.assertEqual(denied.status_code,400)
  denied=client.post('/index-v3/run',data={**data,'csrf':'bad'});self.assertEqual(denied.status_code,403)
  (self.work/'libraries/v/lib/file_index.json').unlink()
  blocked=client.post('/index-v3/run',data=data);self.assertEqual(blocked.status_code,409)
