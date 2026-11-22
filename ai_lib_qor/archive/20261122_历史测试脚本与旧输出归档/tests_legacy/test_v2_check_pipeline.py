import json
import shutil
import tempfile
import unittest
import zipfile
from pathlib import Path
from ai_lib_qor.application.data_query import LibraryDataQuery
from ai_lib_qor.application.simple_sources import simple_raw
from ai_lib_qor.application.effective_json import create_revision
from ai_lib_qor.application.pipeline import check_plan, render_report

ROOT=Path(__file__).resolve().parents[1]
FACTS=ROOT/'examples/file_facts'

class V2CheckPipelineTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name);self.work=self.root/'work'
  shutil.copytree(ROOT/'examples/work',self.work)
  for p in self.work.glob('vendors/vendor_orion/libraries/lib_rtavfs/deliveries/*/delivery.json'):
   d=json.loads(p.read_text());e={'classification':{f['relative_path']:{'basis':'explicit'} for f in d['files']}}
   (p.parent/'source_evidence.json').write_text(json.dumps(e))
  q=LibraryDataQuery(self.work,self.root/'runs');raws=[simple_raw(q,'vendor_orion','lib_rtavfs',v) for v in ('V07','V08')]
  owner={'type':'BUSINESS_IP','id':'rtavfs'}
  a=create_revision(raws[0],owner=owner,revision='rev_0001',created_at='t',include_views=['LEF','LIBERTY'])
  b=create_revision(raws[1],owner=owner,revision='rev_0002',created_at='t',include_views=['LEF','LIBERTY'],parent=a)
  folder=self.work/'libraries/vendor_orion/lib_rtavfs';folder.mkdir(parents=True)
  self.old=folder/'effective_rtavfs_primary_001.json';self.new=folder/'effective_rtavfs_primary_002.json'
  self.old.write_text(json.dumps(a));self.new.write_text(json.dumps(b))
 def test_v2_plan_runs_existing_check_and_excel(self):
  plan={'work_root':str(self.work),'target_revision':str(self.new),'baseline_revision':str(self.old),
        'run_id':'v2_run','ruleset_id':'test','run_at':'2026-10-20T00:00:00Z',
        'comparisons':[{'file_key':'lib_rtavfs:lef:core','old_facts':str(FACTS/'facts_core_v07.json'),'new_facts':str(FACTS/'facts_core_v08.json')}],
        'pin_pairs':[{'lef_key':'lib_rtavfs:lef:core','liberty_key':'lib_rtavfs:liberty:func_tt',
                      'lef_facts':str(FACTS/'facts_core_v08.json'),'liberty_facts':str(FACTS/'facts_tt_v08.json')}]}
  p=self.root/'plan.json';p.write_text(json.dumps(plan));result=self.root/'check.json'
  check_plan(p,result);out=json.loads(result.read_text());self.assertEqual(out['target']['id'],'rev_0002')
  self.assertEqual(out['quality_checks'][0]['result'],'PASS');self.assertEqual(out['file_changes'][0]['content_status'],'CHANGED')
  excel=self.root/'report.xlsx';render_report(result,excel=excel,facts=[str(FACTS/'facts_core_v07.json'),str(FACTS/'facts_core_v08.json'),str(FACTS/'facts_tt_v08.json')])
  with zipfile.ZipFile(excel) as z:self.assertIn('LEF_LIBERTY_PIN_MATCH',z.read('xl/sharedStrings.xml').decode())
 def test_v2_plan_requires_work_scope(self):
  plan={'target_revision':str(self.new),'baseline_revision':str(self.old),'run_id':'r','ruleset_id':'t','run_at':'t','comparisons':[],'pin_pairs':[]}
  path=self.root/'plan.json';path.write_text(json.dumps(plan))
  with self.assertRaisesRegex(ValueError,'work_root'):check_plan(path,self.root/'out.json')
 def test_v2_run_plan_produces_html_and_existing_excel(self):
  from ai_lib_qor.application.runs import execute
  plan={'work_root':str(self.work),'target_revision':str(self.new),'baseline_revision':str(self.old),
        'run_id':'ignored','ruleset_id':'test','run_at':'2026-10-20T00:00:00Z',
        'comparisons':[{'file_key':'lib_rtavfs:lef:core','old_facts':str(FACTS/'facts_core_v07.json'),'new_facts':str(FACTS/'facts_core_v08.json')}],
        'pin_pairs':[{'lef_key':'lib_rtavfs:lef:core','liberty_key':'lib_rtavfs:liberty:func_tt',
          'lef_facts':str(FACTS/'facts_core_v08.json'),'liberty_facts':str(FACTS/'facts_tt_v08.json')}]}
  path=self.root/'plan.json';path.write_text(json.dumps(plan));status=execute(path,self.root/'runs')
  self.assertEqual(status['state'],'SUCCEEDED',status.get('error'))
  folder=self.root/'runs'/status['id'];self.assertTrue((folder/'report.xlsx').is_file());self.assertTrue((folder/'report.html').is_file())
  with zipfile.ZipFile(folder/'report.xlsx') as z:self.assertIn('LEF_LIBERTY_PIN_MATCH',z.read('xl/sharedStrings.xml').decode())
 def test_ambiguous_cross_vendor_legacy_reference_is_rejected(self):
  from ai_lib_qor.application.v2_check_adapter import load_v2_for_check
  original=next(self.work.glob('vendors/vendor_orion/libraries/lib_rtavfs/deliveries/*/delivery.json'))
  other=self.work/'vendors/other/libraries/lib_rtavfs/deliveries'/original.parent.name
  other.mkdir(parents=True);record=json.loads(original.read_text());record['vendor_id']='other'
  (other/'delivery.json').write_text(json.dumps(record));shutil.copy2(original.parent/'source_evidence.json',other/'source_evidence.json')
  with self.assertRaisesRegex(ValueError,'不唯一'):load_v2_for_check(self.old,self.work)
 def test_existing_library_workbench_runs_matching_v2_plan(self):
  from ai_lib_qor.workbench.app import create_app
  plans=self.root/'plans';plans.mkdir()
  plan={'work_root':str(self.work),'target_revision':str(self.new),'baseline_revision':str(self.old),'ruleset_id':'test',
        'comparisons':[{'file_key':'lib_rtavfs:lef:core','old_facts':str(FACTS/'facts_core_v07.json'),'new_facts':str(FACTS/'facts_core_v08.json')}],
        'pin_pairs':[{'lef_key':'lib_rtavfs:lef:core','liberty_key':'lib_rtavfs:liberty:func_tt','lef_facts':str(FACTS/'facts_core_v08.json'),'liberty_facts':str(FACTS/'facts_tt_v08.json')}]}
  (plans/'v2.json').write_text(json.dumps(plan));app=create_app(plans,self.root/'runs',self.work);client=app.test_client()
  (plans/'invalid.json').write_text('[]')
  args={'vendor':'vendor_orion','library':'lib_rtavfs','set_id':'rtavfs_primary','revision':'rev_0002'}
  response=client.get('/library',query_string=args);self.assertEqual(response.status_code,200)
  self.assertIn('运行单版本检查',response.get_data(as_text=True))
  with client.session_transaction() as session:csrf=session['csrf']
  denied=client.post('/effective-v2/run',data={**args,'csrf':csrf,'plan':'invalid.json'})
  self.assertEqual(denied.status_code,400)
  response=client.post('/effective-v2/run',data={**args,'csrf':csrf,'plan':'v2.json'})
  self.assertEqual(response.status_code,303);self.assertIn('/runs/',response.headers['Location'])
  statuses=list((self.root/'runs').glob('run_*/status.json'));self.assertEqual(len(statuses),1)
  status=json.loads(statuses[0].read_text());self.assertEqual(status['state'],'SUCCEEDED',status.get('error'))
  self.assertTrue((statuses[0].parent/'report.xlsx').is_file())
