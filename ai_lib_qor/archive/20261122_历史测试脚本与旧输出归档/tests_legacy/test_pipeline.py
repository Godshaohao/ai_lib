import json, tempfile, unittest, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src'))
from ai_lib_qor.sources.delivery_builder import build_delivery
from ai_lib_qor.checks.assembler import build_check_result
from ai_lib_qor.reporting.view import build_report
from ai_lib_qor.reporting.html import render_html
from ai_lib_qor.versions.store import validate

ROOT=Path(__file__).resolve().parents[1]
FACTS=ROOT/'examples/file_facts'

def fact(name): return json.loads((FACTS/name).read_text())

class PipelineTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.raw=Path(self.tmp.name)/'raw';(self.raw/'lef').mkdir(parents=True);(self.raw/'lib').mkdir()
  (self.raw/'lef/core.lef').write_text('MACRO MAC_A\nEND MAC_A\n')
  (self.raw/'lib/func_tt.lib').write_text('library(tt){}\n')
  self.meta={'delivery_id':'dlv_20261019_001','vendor_id':'vendor_orion','source_library_id':'lib_rtavfs','supplier_version':'V08','delivery_order':8,'received_at':'2026-10-19T15:00:00+08:00','package_mode':'INCREMENTAL','scope_confirmed':True}
  self.mapping={'lef/core.lef':{'file_key':'lib_rtavfs:lef:core','view':'LEF','corner':None,'mode':None}, 'lib/func_tt.lib':{'file_key':'lib_rtavfs:liberty:func_tt','view':'LIBERTY','corner':'tt','mode':'func'}}
 def delivery(self):return build_delivery(self.raw,self.meta,self.mapping)
 def run_check(self,old=None,new=None,lib=None):
  old=old or fact('facts_core_v07.json');new=new or fact('facts_core_v08.json');lib=lib or fact('facts_tt_v08.json')
  return build_check_result(target={'kind':'RAW_DELIVERY','id':'dlv_20261019_001'},baseline={'kind':'RAW_DELIVERY','id':'dlv_20260907_001'},effective_set_id=None,run_id='run_001',ruleset_id='test',run_at='2026-10-20T00:00:00Z',comparisons=[{'file_key':'lib_rtavfs:lef:core','old':old,'new':new}],pin_pairs=[{'lef_key':'lib_rtavfs:lef:core','liberty_key':'lib_rtavfs:liberty:func_tt','lef':new,'liberty':lib}],target_delivery=json.loads((ROOT/'examples/work/vendors/vendor_orion/libraries/lib_rtavfs/deliveries/dlv_20261019_001/delivery.json').read_text()),baseline_delivery=json.loads((ROOT/'examples/work/vendors/vendor_orion/libraries/lib_rtavfs/deliveries/dlv_20260907_001/delivery.json').read_text()))
 def test_formal_snapshot_matches_explicit_delivery(self):
  from ai_lib_qor.sources.snapshot_builder import build_snapshot
  formal=Path(self.tmp.name)/'formal';(formal/'lef').mkdir(parents=True);(formal/'lef/core.lef').symlink_to(self.raw/'lef/core.lef');d=self.delivery()
  meta={'formal_nl_id':'NL2.5.3','formal_snapshot_id':'snap_0001','previous_snapshot_id':None,'observed_at':'2026-10-21T00:00:00Z','source_library_ids':['lib_rtavfs'],'views':['LEF'],'note':'仅检查指定 LEF','scope_confirmed':True}
  result=build_snapshot(formal,meta,{'lef/core.lef':'lib_rtavfs:lef:core'},[d]);validate(result,'formal_snapshot');self.assertEqual(result['linked_files'][0]['source_match'],'MATCHED_RAW');self.assertEqual(result['coverage'],'COMPLETE_IN_SCOPE')
 def test_snapshot_cli(self):
  import subprocess,os
  base=Path(self.tmp.name);formal=base/'formal';formal.mkdir();(formal/'core.lef').symlink_to(self.raw/'lef/core.lef')
  dpath=base/'delivery.json';dpath.write_text(json.dumps(self.delivery()));cfg=base/'formal.json';cfg.write_text(json.dumps({'metadata':{'formal_nl_id':'NL','formal_snapshot_id':'s1','previous_snapshot_id':None,'observed_at':'2026-10-21T00:00:00Z','source_library_ids':['lib_rtavfs'],'views':['LEF'],'note':'test','scope_confirmed':True},'link_mapping':{'core.lef':'lib_rtavfs:lef:core'},'deliveries':[str(dpath)]}))
  result=base/'snapshot.json';env={**os.environ,'PYTHONPATH':str(ROOT/'src')};p=subprocess.run([sys.executable,'-m','ai_lib_qor','snapshot','--root',str(formal),'--config',str(cfg),'--out',str(result)],env=env,text=True,capture_output=True)
  self.assertEqual(p.returncode,0,p.stderr);self.assertEqual(json.loads(result.read_text())['linked_files'][0]['source_match'],'MATCHED_RAW')
 def test_formal_snapshot_unknown_file_cannot_claim_complete(self):
  from ai_lib_qor.sources.snapshot_builder import build_snapshot
  formal=Path(self.tmp.name)/'formal';formal.mkdir();(formal/'a.lef').symlink_to(self.raw/'lef/core.lef');(formal/'extra.lef').write_text('x')
  meta={'formal_nl_id':'NL','formal_snapshot_id':'s1','previous_snapshot_id':None,'observed_at':'2026-10-21T00:00:00Z','source_library_ids':['lib_rtavfs'],'views':['LEF'],'note':'test','scope_confirmed':True}
  with self.assertRaises(ValueError):build_snapshot(formal,meta,{'a.lef':'lib_rtavfs:lef:core'},[])
 def test_selector_ranks_only_actual_file_appearances(self):
  from ai_lib_qor.checks.selectors import latest_previous
  a=self.delivery();a['delivery_id']='d7';a['delivery_order']=7
  b=self.delivery();b['delivery_id']='d8';b['delivery_order']=8;b['files']=[x for x in b['files'] if x['view']!='LIBERTY']
  result=latest_previous([a,b],'lib_rtavfs:liberty:func_tt',{'d7':'COMPLETE','d8':'COMPLETE'})
  self.assertEqual(result['latest']['delivery_id'],'d7');self.assertIsNone(result['previous']);self.assertEqual(result['status'],'CONFIRMED')
 def test_selector_incomplete_newer_scan_is_unknown(self):
  from ai_lib_qor.checks.selectors import latest_previous
  a=self.delivery();a['delivery_id']='d7';a['delivery_order']=7
  b=self.delivery();b['delivery_id']='d8';b['delivery_order']=8;b['files']=[x for x in b['files'] if x['view']!='LIBERTY']
  result=latest_previous([a,b],'lib_rtavfs:liberty:func_tt',{'d7':'COMPLETE','d8':'PARTIAL'})
  self.assertEqual(result['status'],'UNKNOWN_COVERAGE')
 def test_real_lef_and_liberty_are_adapted_to_v3_facts(self):
  from ai_lib_qor.facts.parsers import parse_delivery_file
  (self.raw/'lef/core.lef').write_text('MACRO MAC_A\n  SIZE 124 BY 80 ;\n  PIN A\n    DIRECTION INPUT ;\n  END A\nEND MAC_A\n')
  (self.raw/'lib/func_tt.lib').write_text('library(test) { cell(MAC_A) { pin(A) { direction : input; } } }')
  d=self.delivery();result={f['view']:parse_delivery_file(d,f['file_id']) for f in d['files']}
  self.assertEqual(result['LEF']['objects']['macros'][0]['size_um'],[124.0,80.0]);self.assertEqual(result['LIBERTY']['objects']['cells'][0]['pins'][0]['name'],'A')
  for x in result.values():validate(x,'file_facts')
 def test_incomplete_lef_does_not_become_complete_facts(self):
  from ai_lib_qor.facts.parsers import parse_delivery_file
  (self.raw/'lef/core.lef').write_text('MACRO MAC_A\n SIZE 124 BY 80 ;\n')
  d=self.delivery();item=next(x for x in d['files'] if x['view']=='LEF')
  with self.assertRaises(ValueError):parse_delivery_file(d,item['file_id'])
 def test_delivery_can_initialize_version(self):
  import subprocess,os
  d=self.delivery();validate(d,'delivery_record');p=Path(self.tmp.name)/'delivery.json';p.write_text(json.dumps(d))
  env={**os.environ,'PYTHONPATH':str(ROOT/'src')}
  cmd=[sys.executable,'-m','ai_lib_qor.versions','init','--effective-dir',str(Path(self.tmp.name)/'effective'),'--delivery',str(p),'--set-id','set','--owner-type','SOURCE_LIBRARY','--owner-id','lib_rtavfs','--home-library','lib_rtavfs']
  r=subprocess.run(cmd,env=env,text=True,capture_output=True);self.assertEqual(r.returncode,0,r.stderr)
  self.assertEqual(len(json.loads((Path(self.tmp.name)/'effective/versions/rev_0001.json').read_text())['members']),2)
 def test_unknown_file_remains_unresolved(self):
  (self.raw/'unknown.lef').write_text('x');d=self.delivery();u=[x for x in d['files'] if x['relative_path']=='unknown.lef'][0];self.assertIsNone(u['file_key']);self.assertEqual(u['classification'],'UNRESOLVED')
 def test_check_merges_macro_pin_and_quality(self):
  r=self.run_check();validate(r,'check_result');f=r['file_changes'][0];self.assertEqual(f['content_status'],'CHANGED');self.assertEqual({x['attribute'] for x in f['object_changes']},{'SIZE','PRESENCE'});self.assertEqual(r['quality_checks'][0]['result'],'PASS');self.assertEqual(r['summary']['files_with_confirmed_content_change'],1)
 def test_incomplete_pin_coverage_is_not_pass(self):
  lib=fact('facts_tt_v08.json');lib['parse_status']='PARTIAL';self.assertEqual(self.run_check(lib=lib)['quality_checks'][0]['result'],'INCONCLUSIVE')
 def test_check_effective_versions_resolves_formal_snapshot_evidence(self):
  base=ROOT/'examples/work';e=base/'vendors/vendor_orion/libraries/lib_rtavfs/ips/rtavfs/effective/versions';oldrev=json.loads((e/'rev_0001.json').read_text());newrev=json.loads((e/'rev_0002.json').read_text());snap=json.loads((base/'formal_nl/NL2.5.3/snapshots/snap_nl253_0001.json').read_text());old=fact('facts_core_v07.json');new=fact('facts_core_v08.json');lib=fact('facts_tt_v08.json')
  result=build_check_result(target={'kind':'EFFECTIVE_REVISION','id':'rev_0002'},baseline={'kind':'EFFECTIVE_REVISION','id':'rev_0001'},effective_set_id='rtavfs_primary',run_id='run_001',ruleset_id='test',run_at='2026-10-20T00:00:00Z',comparisons=[{'file_key':'lib_rtavfs:lef:core','old':old,'new':new}],pin_pairs=[{'lef_key':'lib_rtavfs:lef:core','liberty_key':'lib_rtavfs:liberty:func_tt','lef':new,'liberty':lib}],target_members={m['file_key']:m['source_ref'] for m in newrev['members']},baseline_members={m['file_key']:m['source_ref'] for m in oldrev['members']},formal_snapshots=[snap])
  self.assertEqual(result['file_changes'][0]['old_source_ref']['kind'],'formal_file');self.assertEqual(result['quality_checks'][0]['result'],'PASS')
 def test_effective_cli_check(self):
  import subprocess,os
  base=ROOT/'examples/work';e=base/'vendors/vendor_orion/libraries/lib_rtavfs/ips/rtavfs/effective/versions';plan={'target_revision':str(e/'rev_0002.json'),'baseline_revision':str(e/'rev_0001.json'),'formal_snapshots':[str(base/'formal_nl/NL2.5.3/snapshots/snap_nl253_0001.json')],'run_id':'r1','ruleset_id':'t','run_at':'2026-10-20T00:00:00Z','comparisons':[{'file_key':'lib_rtavfs:lef:core','old_facts':str(FACTS/'facts_core_v07.json'),'new_facts':str(FACTS/'facts_core_v08.json')}],'pin_pairs':[{'lef_key':'lib_rtavfs:lef:core','liberty_key':'lib_rtavfs:liberty:func_tt','lef_facts':str(FACTS/'facts_core_v08.json'),'liberty_facts':str(FACTS/'facts_tt_v08.json')}]}
  p=Path(self.tmp.name)/'plan.json';p.write_text(json.dumps(plan));out=Path(self.tmp.name)/'check.json';env={**os.environ,'PYTHONPATH':str(ROOT/'src')};r=subprocess.run([sys.executable,'-m','ai_lib_qor','check','--plan',str(p),'--out',str(out)],env=env,text=True,capture_output=True)
  self.assertEqual(r.returncode,0,r.stderr);self.assertEqual(json.loads(out.read_text())['target']['kind'],'EFFECTIVE_REVISION')
 def test_lef_diff_reports_pin_direction_and_macro_presence(self):
  old=fact('facts_core_v07.json');new=fact('facts_core_v08.json');new['objects']['macros'][0]['pins'][0]['direction']='OUTPUT';new['objects']['macros'].append({'name':'MAC_B','size_um':[2,3],'pins':[]})
  # Ignore Liberty quality here; this test only verifies LEF diff.
  lib=fact('facts_tt_v08.json');r=self.run_check(old=old,new=new,lib=lib);attrs={(x['object_name'],x['attribute']) for x in r['file_changes'][0]['object_changes']};self.assertIn(('MAC_A/A','DIRECTION'),attrs);self.assertIn(('MAC_B','PRESENCE'),attrs)
 def test_empty_pins_cannot_pass(self):
  lef=fact('facts_core_v08.json');lib=fact('facts_tt_v08.json');lef['objects']['macros'][0]['pins']=[];lib['objects']['cells'][0]['pins']=[]
  self.assertEqual(self.run_check(new=lef,lib=lib)['quality_checks'][0]['result'],'INCONCLUSIVE')
 def test_pg_pin_is_not_claimed_as_signal(self):
  from ai_lib_qor.facts.parsers import parse_delivery_file
  (self.raw/'lef/core.lef').write_text('MACRO MAC_A\n SIZE 2 BY 2 ;\n PIN VDD\n DIRECTION INOUT ;\n USE POWER ;\n END VDD\n END MAC_A\n')
  d=self.delivery();item=next(x for x in d['files'] if x['view']=='LEF')
  with self.assertRaises(ValueError):parse_delivery_file(d,item['file_id'])
 def test_missing_cell_coverage_does_not_yield_pass(self):
  lib=fact('facts_tt_v08.json');lib['covered_sections'].remove('CELL_NAME');self.assertEqual(self.run_check(lib=lib)['quality_checks'][0]['result'],'INCONCLUSIVE')
 def test_facts_source_mismatch_rejected(self):
  new=fact('facts_core_v08.json');new['source_ref']['delivery_id']='bad';
  with self.assertRaises(ValueError):self.run_check(new=new)
 def test_same_delivery_wrong_file_id_rejected(self):
  new=fact('facts_core_v08.json');new['source_ref']['file_id']='f002'
  with self.assertRaises(ValueError):self.run_check(new=new)
 def test_cli_delivery_facts_check_and_report(self):
  import os,subprocess
  base=Path(self.tmp.name);env={**os.environ,'PYTHONPATH':str(ROOT/'src')+os.pathsep+os.environ.get('PYTHONPATH','')}
  def cmd(*args):
   p=subprocess.run([sys.executable,'-m','ai_lib_qor',*map(str,args)],env=env,text=True,capture_output=True);self.assertEqual(p.returncode,0,p.stderr)
  oldroot=base/'V07';newroot=base/'V08'
  for root,size,extra in [(oldroot,120,''),(newroot,124,'  PIN C\n    DIRECTION INPUT ;\n  END C\n')]:
   (root/'lef').mkdir(parents=True);(root/'lib').mkdir()
   (root/'lef/core.lef').write_text(f'MACRO MAC_A\n SIZE {size} BY 80 ;\n PIN A\n DIRECTION INPUT ;\n END A\n{extra}END MAC_A\n')
   (root/'lib/func_tt.lib').write_text('library(test) { cell(MAC_A) { pin(A) { direction : input; } '+('pin(C) { direction : input; }' if extra else '')+' } }')
  records=[]
  for i,root in enumerate([oldroot,newroot],7):
   meta={**self.meta,'delivery_id':f'dlv_{i}','supplier_version':f'V{i:02}','delivery_order':i};config=base/f'config{i}.json';config.write_text(json.dumps({'metadata':meta,'file_mapping':self.mapping}));out=base/f'delivery{i}.json';cmd('delivery','--root',root,'--config',config,'--out',out);records.append(json.loads(out.read_text()))
  fact_paths={}
  for i,record in zip([7,8],records):
   for f in record['files']:
    if i==7 and f['view']=='LIBERTY':continue
    out=base/f'facts{i}_{f["view"]}.json';cmd('facts','--delivery',base/f'delivery{i}.json','--file-id',f['file_id'],'--out',out);fact_paths[(i,f['view'])]=str(out)
  plan={'target_delivery':str(base/'delivery8.json'),'baseline_delivery':str(base/'delivery7.json'),'run_id':'run_001','ruleset_id':'test','run_at':'2026-10-20T00:00:00Z','comparisons':[{'file_key':'lib_rtavfs:lef:core','old_facts':fact_paths[(7,'LEF')],'new_facts':fact_paths[(8,'LEF')]}],'pin_pairs':[{'lef_key':'lib_rtavfs:lef:core','liberty_key':'lib_rtavfs:liberty:func_tt','lef_facts':fact_paths[(8,'LEF')],'liberty_facts':fact_paths[(8,'LIBERTY')]}]}
  planpath=base/'plan.json';planpath.write_text(json.dumps(plan));result=base/'run_001.json';cmd('check','--plan',planpath,'--out',result)
  data=json.loads(result.read_text());self.assertEqual(data['quality_checks'][0]['result'],'PASS');self.assertEqual(data['file_changes'][0]['content_status'],'CHANGED')
  html=base/'report.html';cmd('report','--check',result,'--html',html);self.assertIn('LEF_LIBERTY_PIN_MATCH',html.read_text())
  effective=base/'effective'
  def ver(*args):
   p=subprocess.run([sys.executable,'-m','ai_lib_qor.versions',*map(str,args)],env=env,text=True,capture_output=True);self.assertEqual(p.returncode,0,p.stderr)
  ver('init','--effective-dir',effective,'--delivery',base/'delivery7.json','--set-id','set','--owner-type','SOURCE_LIBRARY','--owner-id','lib_rtavfs','--home-library','lib_rtavfs')
  ver('apply','--effective-dir',effective,'--delivery',base/'delivery8.json')
  plan.pop('target_delivery');plan.pop('baseline_delivery');plan['target_revision']=str(effective/'versions/rev_0002.json');plan['baseline_revision']=str(effective/'versions/rev_0001.json');planpath.write_text(json.dumps(plan));result2=base/'effective_run.json';cmd('check','--plan',planpath,'--out',result2)
  self.assertEqual(json.loads(result2.read_text())['target']['id'],'rev_0002')
 def test_excel_report_uses_same_model(self):
  import importlib.util,zipfile
  if not importlib.util.find_spec('xlsxwriter'):self.skipTest('xlsxwriter unavailable')
  from ai_lib_qor.reporting.excel import render_excel
  path=Path(self.tmp.name)/'report.xlsx';render_excel(build_report(self.run_check()),path)
  with zipfile.ZipFile(path) as z:
   strings=z.read('xl/sharedStrings.xml').decode();self.assertIn('LEF_LIBERTY_PIN_MATCH',strings);self.assertIn('PASS',strings);self.assertIn('MAC_A',strings);self.assertIn('SIZE',strings)
 def test_report_escapes_input_and_preserves_status(self):
  r=self.run_check();r['quality_checks'][0]['detail']='<script>alert(1)</script>';html=render_html(build_report(r));self.assertNotIn('<script>alert(1)</script>',html);self.assertIn('&lt;script&gt;',html);self.assertIn('PASS',html);self.assertIn('MAC_A',html);self.assertIn('SIZE',html)

if __name__=='__main__':unittest.main()

class InitialRevisionPlanTest(unittest.TestCase):
 def test_initial_revision_checks_without_a_fabricated_baseline(self):
  import copy, subprocess, os
  f=copy.deepcopy(fact('facts_tt_v08.json'));f['facts_id']='test_tt_v07';f['source_ref']['delivery_id']='dlv_20260907_001';f['objects']['cells'][0]['pins']=[p for p in f['objects']['cells'][0]['pins'] if p['name']!='C']
  with tempfile.TemporaryDirectory() as t:
   base=Path(t);tt=base/'tt.json';tt.write_text(json.dumps(f));e=ROOT/'examples/work/vendors/vendor_orion/libraries/lib_rtavfs/ips/rtavfs/effective/versions'
   plan={'target_revision':str(e/'rev_0001.json'),'formal_snapshots':[str(ROOT/'examples/work/formal_nl/NL2.5.3/snapshots/snap_nl253_0001.json')],'run_id':'initial','ruleset_id':'test','run_at':'2026-10-20T00:00:00Z','comparisons':[],'pin_pairs':[{'lef_key':'lib_rtavfs:lef:core','liberty_key':'lib_rtavfs:liberty:func_tt','lef_facts':str(FACTS/'facts_core_v07.json'),'liberty_facts':str(tt)}]}
   p=base/'plan.json';p.write_text(json.dumps(plan));out=base/'out.json';env={**os.environ,'PYTHONPATH':str(ROOT/'src')+os.pathsep+os.environ.get('PYTHONPATH','')}
   proc=subprocess.run([sys.executable,'-m','ai_lib_qor','check','--plan',str(p),'--out',str(out)],env=env,text=True,capture_output=True)
   self.assertEqual(proc.returncode,0,proc.stderr)
   result=json.loads(out.read_text());self.assertIsNone(result['baseline']);self.assertEqual(result['file_changes'],[]);self.assertEqual(result['quality_checks'][0]['result'],'PASS')

 def test_liberty_failure_reports_specific_missing_pin(self):
  import copy
  from ai_lib_qor.checks.plugins.lef_liberty_pin_match import compare
  lef=copy.deepcopy(fact('facts_core_v08.json'));lib=copy.deepcopy(fact('facts_tt_v08.json'))
  lib['objects']['cells'][0]['pins']=[p for p in lib['objects']['cells'][0]['pins'] if p['name']!='C']
  result=compare(lef,lib,'lef','ff')
  self.assertEqual(result['result'],'FAIL');self.assertIn('C',result['detail']);self.assertIn('缺少',result['detail'])

 def test_noninitial_revision_cannot_omit_baseline(self):
  import subprocess, os
  with tempfile.TemporaryDirectory() as t:
   base=Path(t);e=ROOT/'examples/work/vendors/vendor_orion/libraries/lib_rtavfs/ips/rtavfs/effective/versions'
   plan={'target_revision':str(e/'rev_0002.json'),'run_id':'r','ruleset_id':'test','run_at':'2026-10-20T00:00:00Z','comparisons':[],'pin_pairs':[{'lef_key':'lib_rtavfs:lef:core','liberty_key':'lib_rtavfs:liberty:func_tt','lef_facts':str(FACTS/'facts_core_v08.json'),'liberty_facts':str(FACTS/'facts_tt_v08.json')}]}
   p=base/'plan.json';p.write_text(json.dumps(plan));out=base/'out.json';env={**os.environ,'PYTHONPATH':str(ROOT/'src')+os.pathsep+os.environ.get('PYTHONPATH','')}
   proc=subprocess.run([sys.executable,'-m','ai_lib_qor','check','--plan',str(p),'--out',str(out)],env=env,text=True,capture_output=True)
   self.assertNotEqual(proc.returncode,0);self.assertFalse(out.exists())
