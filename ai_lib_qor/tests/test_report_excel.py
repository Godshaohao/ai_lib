import json, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src'))
from ai_lib_qor.reporting.view import build_report
from ai_lib_qor.reporting.excel import render_excel
try:
 from openpyxl import load_workbook
except ImportError:
 load_workbook=None

ROOT=Path(__file__).resolve().parents[1]
def load(p): return json.loads((ROOT/p).read_text())

@unittest.skipIf(load_workbook is None, 'openpyxl required for Excel verification')
class ExcelReportTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  self.check=load('tests/fixtures/check_result.json')
  self.d07=load('examples/work/vendors/vendor_orion/libraries/lib_rtavfs/deliveries/dlv_20260907_001/delivery.json')
  self.d08=load('examples/work/vendors/vendor_orion/libraries/lib_rtavfs/deliveries/dlv_20261019_001/delivery.json')
  self.facts=[load('examples/file_facts/facts_core_v07.json'),load('examples/file_facts/facts_core_v08.json'),load('examples/file_facts/facts_tt_v08.json')]
  self.snapshot=load('examples/work/formal_nl/NL2.5.3/snapshots/snap_nl253_0002.json')
  self.rev1=load('examples/work/vendors/vendor_orion/libraries/lib_rtavfs/ips/rtavfs/effective/versions/rev_0001.json')
  self.rev2=load('examples/work/vendors/vendor_orion/libraries/lib_rtavfs/ips/rtavfs/effective/versions/rev_0002.json')
  self.index=load('examples/work/vendors/vendor_orion/libraries/lib_rtavfs/ips/rtavfs/effective/index.json')
 def workbook(self,**kwargs):
  dest=Path(self.tmp.name)/'out.xlsx';render_excel(build_report(self.check,**kwargs),dest);return load_workbook(dest,data_only=True)
 def test_legacy_navigation_with_actual_v3_facts(self):
  wb=self.workbook(deliveries=[self.d07,self.d08],facts=self.facts,formal_snapshot=self.snapshot,target_revision=self.rev2,baseline_revision=self.rev1,accepted_revision=self.rev1,effective_index=self.index)
  for title in ('00-概览','文件版本矩阵','01-工程检查','02-执行记录','03-问答','04-关注项','05-MacroView','06-MacroView文件','07-正式文件','08-LEF宏','09-Liberty角','10-Liberty单元'):
   self.assertIn(title,wb.sheetnames)
  text='\n'.join(str(c.value) for ws in wb for row in ws for c in row if c.value is not None)
  for value in ('MAC_A','SIZE','124.0','LEF_LIBERTY_PIN_MATCH','dlv_20261019_001','NL2.5.3'):
   self.assertIn(value,text)
  self.assertEqual(wb['文件版本矩阵'].freeze_panes,'A5')
  self.assertTrue(wb['文件版本矩阵'].tables)
  self.assertGreater(wb['02-执行记录'].row_dimensions[5].height,36)
  matrix=list(wb['文件版本矩阵'].values);headers=matrix[3];row=next(dict(zip(headers,r)) for r in matrix[4:] if r[1]=='lib_rtavfs:liberty:func_tt')
  self.assertIn('dlv_20261019_001',row['目标来源']);self.assertIn('snap_nl253_0001',row['基准来源']);self.assertIn('V08',row['最新路径（已提供范围）'])
 def test_cli_explicit_context_fills_old_style_matrix(self):
  import os,subprocess
  source=ROOT/'examples/work/vendors/vendor_orion/libraries/lib_rtavfs'
  cmd=[sys.executable,'-m','ai_lib_qor','report','--check',str(ROOT/'tests/fixtures/check_result.json'),'--delivery',str(source/'deliveries/dlv_20260907_001/delivery.json'),'--delivery',str(source/'deliveries/dlv_20261019_001/delivery.json'),'--facts',str(ROOT/'examples/file_facts/facts_core_v08.json'),'--facts',str(ROOT/'examples/file_facts/facts_tt_v08.json'),'--target-revision',str(source/'ips/rtavfs/effective/versions/rev_0002.json'),'--baseline-revision',str(source/'ips/rtavfs/effective/versions/rev_0001.json'),'--effective-index',str(source/'ips/rtavfs/effective/index.json'),'--accepted-revision',str(source/'ips/rtavfs/effective/versions/rev_0001.json'),'--formal-snapshot',str(ROOT/'examples/work/formal_nl/NL2.5.3/snapshots/snap_nl253_0002.json'),'--source-snapshot',str(ROOT/'examples/work/formal_nl/NL2.5.3/snapshots/snap_nl253_0001.json'),'--excel',str(Path(self.tmp.name)/'cli.xlsx')]
  env={**os.environ,'PYTHONPATH':str(ROOT/'src')+os.pathsep+os.environ.get('PYTHONPATH','')};r=subprocess.run(cmd,env=env,text=True,capture_output=True)
  self.assertEqual(r.returncode,0,r.stderr);wb=load_workbook(Path(self.tmp.name)/'cli.xlsx',data_only=True);self.assertIn('文件版本矩阵',wb.sheetnames);self.assertEqual(wb['文件版本矩阵'].max_row,7)
 def test_missing_context_explicit_and_no_fabricated_pass(self):
  wb=self.workbook();text='\n'.join(str(c.value) for ws in wb for row in ws for c in row if c.value is not None)
  self.assertIn('未提供',text);self.assertIn('未评估',text);self.assertNotIn('全部通过',text)
 def test_reject_wrong_snapshot_or_facts(self):
  duplicate=dict(self.facts[0]);duplicate['objects']={'macros':[]}
  with self.assertRaises(ValueError):build_report(self.check,facts=[self.facts[0],duplicate])

class ReportContextIntegrityTests(unittest.TestCase):
 def test_revision_member_must_match_check_result(self):
  from copy import deepcopy
  check=load('tests/fixtures/check_result.json');rev=load('examples/work/vendors/vendor_orion/libraries/lib_rtavfs/ips/rtavfs/effective/versions/rev_0002.json')
  rev=deepcopy(rev);rev['members'][0]['source_ref']['file_id']='different'
  with self.assertRaises(ValueError):build_report(check,target_revision=rev)
 def test_quality_fact_must_belong_to_selected_revision(self):
  from copy import deepcopy
  check=load('tests/fixtures/check_result.json');rev=load('examples/work/vendors/vendor_orion/libraries/lib_rtavfs/ips/rtavfs/effective/versions/rev_0002.json');f=deepcopy(load('examples/file_facts/facts_core_v08.json'));f['source_ref']['delivery_id']='another_delivery'
  with self.assertRaises(ValueError):build_report(check,target_revision=rev,facts=[f])

 def test_formal_target_evidence_can_use_separate_snapshot(self):
  from copy import deepcopy
  check=deepcopy(load('tests/fixtures/check_result.json'));rev=load('examples/work/vendors/vendor_orion/libraries/lib_rtavfs/ips/rtavfs/effective/versions/rev_0001.json');s1=load('examples/work/formal_nl/NL2.5.3/snapshots/snap_nl253_0001.json');s2=load('examples/work/formal_nl/NL2.5.3/snapshots/snap_nl253_0002.json');f=load('examples/file_facts/facts_core_v07.json')
  check['target']['id']='rev_0001';check['file_changes']=[];check['quality_checks'][0].update(scope_file_keys=['lib_rtavfs:lef:core'],facts_refs=['facts_core_v07'],result='NOT_RUN',coverage='UNKNOWN')
  check['summary']={key:0 for key in check['summary']}
  model=build_report(check,target_revision=rev,facts=[f],formal_snapshot=s2,source_snapshots=[s1]);self.assertEqual(model['_report_context']['formal_snapshot']['formal_snapshot_id'],'snap_nl253_0002')
