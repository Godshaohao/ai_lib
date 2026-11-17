import unittest
from copy import deepcopy
from ai_lib_qor.workbench.read_models import build_file_matrix


def ref(d,f):return {'kind':'delivery_file','source_library_id':'lib','delivery_id':d,'file_id':f}
def rev(r,parent,members):return {'revision_id':r,'parent_revision_id':parent,'effective_set_id':'set','owner':{'owner_id':'ip'},'members':[{'file_key':k,'source_ref':v} for k,v in members.items()]}
def delivery(d,v,items):return {'source_library_id':'lib','delivery_id':d,'supplier_version':v,'files':[{'file_key':k,'file_id':f,'relative_path':f,'view':view,'corner':corner,'mode':None} for k,f,view,corner in items]}

class MatrixTests(unittest.TestCase):
 def setUp(self):
  self.d7=delivery('d7','V07',[('lef','lef7','LEF',None),('ff','ff7','LIBERTY','ff'),('tt','tt7','LIBERTY','tt')]);self.d8=delivery('d8','V08',[('tt','tt8','LIBERTY','tt')]);self.d9=delivery('d9','V09',[('ss','ss9','LIBERTY','ss')]);self.old=rev('rev_2','rev_1',{'lef':ref('d7','lef7'),'ff':ref('d7','ff7'),'tt':ref('d8','tt8'),'gone':ref('d7','x')});self.new=rev('rev_3','rev_2',{'lef':ref('d7','lef7'),'ff':ref('d7','ff7'),'tt':ref('d8','tt8'),'ss':ref('d9','ss9')})
 def test_members_union_inheritance_and_no_unfounded_content(self):
  rows=build_file_matrix(self.new,self.old,[self.d7,self.d8,self.d9],[],None)['rows'];by={x['file_key']:x for x in rows}
  self.assertEqual(by['ff']['target']['version'],'V07');self.assertEqual(by['tt']['target']['version'],'V08');self.assertEqual(by['ss']['target']['version'],'V09')
  self.assertEqual(by['ss']['source_relation'],'ADDED');self.assertEqual(by['gone']['source_relation'],'REMOVED');self.assertEqual(by['ff']['source_relation'],'UNCHANGED');self.assertEqual(by['ff']['content_status'],'NOT_CHECKED')
 def test_duplicate_reference_never_picks_first(self):
  dup=deepcopy(self.d8);rows=build_file_matrix(self.new,self.old,[self.d7,self.d8,dup,self.d9],[],None)['rows'];self.assertEqual(next(x for x in rows if x['file_key']=='tt')['target']['state'],'AMBIGUOUS')
 def test_cross_library_not_loaded_is_out_of_scope(self):
  other=deepcopy(self.new);other['members'][0]['source_ref']['source_library_id']='elsewhere';rows=build_file_matrix(other,self.old,[self.d7,self.d8,self.d9],[],None,home_library='lib')['rows'];self.assertEqual(next(x for x in rows if x['file_key']=='lef')['target']['state'],'OUT_OF_SCOPE')

 def test_wrong_baseline_does_not_admit_comparison(self):
  from ai_lib_qor.workbench.read_models import result_matches
  result={'target':{'kind':'EFFECTIVE_REVISION','id':'rev_3'},'baseline':{'kind':'EFFECTIVE_REVISION','id':'rev_1'},'effective_set_id':'set','file_changes':[]}
  self.assertFalse(result_matches(result,self.new,self.old))
 def test_wrong_file_source_does_not_admit_result(self):
  from ai_lib_qor.workbench.read_models import result_matches
  result={'target':{'kind':'EFFECTIVE_REVISION','id':'rev_3'},'baseline':{'kind':'EFFECTIVE_REVISION','id':'rev_2'},'effective_set_id':'set','file_changes':[{'file_key':'ff','old_source_ref':ref('d7','ff7'),'new_source_ref':ref('d9','wrong')}]}
  self.assertFalse(result_matches(result,self.new,self.old))

class NavigationTests(unittest.TestCase):
 def test_global_default_and_selected_overview(self):
  from pathlib import Path
  import tempfile
  from ai_lib_qor.workbench.app import create_app
  root=Path(__file__).resolve().parents[1]
  with tempfile.TemporaryDirectory() as d:
   client=create_app(root/'examples/pipeline',Path(d)/'runs',root/'examples/work').test_client()
   body=client.get('/').get_data(as_text=True);self.assertIn('哪些库有更新',body);self.assertNotIn('IP REVIEW / vendor_orion',body)
   body=client.get('/?vendor=vendor_orion&library=lib_rtavfs&ip=rtavfs').get_data(as_text=True)
   for text in ('IP 总览','当前有效来源','基线有效来源','rev_0002','rev_0001'):self.assertIn(text,body)

 def test_analysis_filters_and_explicit_baseline(self):
  from pathlib import Path
  import tempfile
  from ai_lib_qor.workbench.app import create_app
  root=Path(__file__).resolve().parents[1]
  with tempfile.TemporaryDirectory() as d:
   client=create_app(root/'examples/pipeline',Path(d)/'runs',root/'examples/work').test_client()
   url='/?view=analysis&vendor=vendor_orion&library=lib_rtavfs&ip=rtavfs&revision=rev_0002&baseline=rev_0001&matrix_q=func_ff'
   body=client.get(url).get_data(as_text=True)
   self.assertIn('lib_rtavfs:liberty:func_ff',body);self.assertNotIn('lib_rtavfs:lef:core',body)
   self.assertIn('基线：rev_0001',body)

 def test_analysis_projects_recorded_run_evidence(self):
  from pathlib import Path
  import tempfile
  from ai_lib_qor.workbench.app import create_app
  from ai_lib_qor.workbench.service import execute
  root=Path(__file__).resolve().parents[1];demo=root/'examples/overall_demo/dataset'
  with tempfile.TemporaryDirectory() as d:
   runs=Path(d)/'runs'; result=execute(demo/'plans/rev_0002.json',runs,owner={'vendor':'vendor_orion','library':'lib_rtavfs','ip':'rtavfs'},expected_revision='rev_0002')
   self.assertEqual(result['state'],'SUCCEEDED')
   client=create_app(demo/'plans',runs,demo/'work').test_client()
   url='/?view=analysis&vendor=vendor_orion&library=lib_rtavfs&ip=rtavfs&revision=rev_0002'
   body=client.get(url).get_data(as_text=True)
   self.assertIn('MAC_A',body);self.assertIn('facts_',body);self.assertIn('输入新鲜度未验证',body);self.assertIn(result['id'],body)

 def test_failed_scan_retains_last_success_time(self):
  import tempfile, json
  from pathlib import Path
  from ai_lib_qor.workbench.app import create_app
  from ai_lib_qor.workbench.scans import run_scan
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);raw=root/'raw';raw.mkdir();(raw/'one').write_text('1');work=root/'work';work.mkdir();plans=root/'plans';plans.mkdir();runs=root/'runs';source={'vendor_id':'v','source_library_id':'l','root':str(raw)};(work/'scan_sources.json').write_text(json.dumps({'sources':[source]}))
   first=run_scan(runs,source);(raw/'one').unlink();raw.rmdir();second=run_scan(runs,source);self.assertEqual(second['status'],'FAILED')
   body=create_app(plans,runs,work).test_client().get('/').get_data(as_text=True)
   self.assertIn('上次成功扫描',body);self.assertIn(first['finished_at'],body)

 def test_checks_page_exposes_scope_and_not_run_for_missing_run(self):
  from pathlib import Path
  import tempfile
  from ai_lib_qor.workbench.app import create_app
  root=Path(__file__).resolve().parents[1]
  with tempfile.TemporaryDirectory() as d:
   client=create_app(root/'examples/pipeline',Path(d)/'runs',root/'examples/work').test_client()
   body=client.get('/?view=checks&vendor=vendor_orion&library=lib_rtavfs&ip=rtavfs&revision=rev_0002').get_data(as_text=True)
   self.assertIn('检查覆盖与结果',body);self.assertIn('尚无对应检查记录',body)

 def test_missing_parent_is_not_initial_revision(self):
  import tempfile,json,shutil
  from pathlib import Path
  from ai_lib_qor.workbench.app import create_app
  root=Path(__file__).resolve().parents[1]
  with tempfile.TemporaryDirectory() as d:
   work=Path(d)/'work';shutil.copytree(root/'examples/work',work)
   p=work/'vendors/vendor_orion/libraries/lib_rtavfs/ips/rtavfs/effective/versions/rev_0001.json';p.unlink()
   client=create_app(root/'examples/pipeline',Path(d)/'runs',work).test_client()
   body=client.get('/?view=overview&vendor=vendor_orion&library=lib_rtavfs&ip=rtavfs').get_data(as_text=True)
   self.assertIn('父版本记录不可读取',body)

 def test_formal_unknown_source_stays_unknown(self):
  from ai_lib_qor.workbench.read_models import build_file_matrix
  fref={'kind':'formal_file','formal_nl_id':'NL','formal_snapshot_id':'s1','file_id':'x'}
  snap={'formal_nl_id':'NL','formal_snapshot_id':'s2','linked_files':[{'file_key':'lef','file_id':'y','link_path':'x','source_ref':ref('d7','lef7')}]}
  target={'revision_id':'r','members':[{'file_key':'lef','source_ref':fref}]}
  rows=build_file_matrix(target,None,[],[snap],formal_snapshot=snap)['rows']
  self.assertEqual(rows[0]['formal_relation'],'来源未知')

 def test_analysis_escapes_file_keys(self):
  import tempfile,json,shutil
  from pathlib import Path
  from ai_lib_qor.workbench.app import create_app
  root=Path(__file__).resolve().parents[1]
  with tempfile.TemporaryDirectory() as d:
   work=Path(d)/'work';shutil.copytree(root/'examples/work',work)
   path=work/'vendors/vendor_orion/libraries/lib_rtavfs/ips/rtavfs/effective/versions/rev_0002.json'
   data=json.loads(path.read_text());data['members'][0]['file_key']='<script>alert(1)</script>';path.write_text(json.dumps(data))
   body=create_app(root/'examples/pipeline',Path(d)/'runs',work).test_client().get('/?view=analysis&vendor=vendor_orion&library=lib_rtavfs&ip=rtavfs').get_data(as_text=True)
   self.assertIn('&lt;script&gt;alert(1)&lt;/script&gt;',body);self.assertNotIn('<script>alert(1)</script>',body)
