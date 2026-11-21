import json
import tempfile
import unittest
from pathlib import Path

from ai_lib_qor.sources.root_inventory import build_from_roots
from ai_lib_qor.application.minimal_effective import initialize_from_formal,update_effective


class MinimalCheckFlowTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  root=Path(self.tmp.name);self.root=root;self.raw=root/'raw';nl=root/'NL1';nl.mkdir();self.work=root/'work'
  self.v1='20261001_abcdef12';self.v2='20261002_abcdef12'
  for version,width in ((self.v1,2),(self.v2,4)):
   files={'LEF/a.lef':f'MACRO A\n SIZE {width} BY 3 ;\n PIN IN\n DIRECTION INPUT ;\n END IN\n PIN VDD\n DIRECTION INOUT ;\n USE POWER ;\n END VDD\nEND A\n',
          'LIB/a.lib':'library(test) { cell(A) { pin(IN) { direction : input; } } }',
          'VERILOG/a.v':'module A(input IN); endmodule\n','CDL/a.cdl':'.SUBCKT A IN VDD\nR1 IN VDD 10\n.ENDS A\n',
          'SPICE/a.spice':'.SUBCKT A IN VDD\nR1 IN VDD 10\n.ENDS A\n','GDS/a.gds':'opaque'}
   for name,content in files.items():
    p=self.raw/'v/lib'/version/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(content)
    if version==self.v1:(nl/p.name).symlink_to(p)
  build_from_roots(self.raw,nl,self.work);self.folder=self.work/'libraries/v/lib'
  initialize_from_formal(self.work,'v','lib',next(self.folder.glob('formal_NL1_*.json')))
  ops={'set':[{'view':'LEF','version':self.v2,'path':'LEF/a.lef'},{'view':'LIBERTY','version':self.v2,'path':'LIB/a.lib'}],'remove':[]}
  update_effective(self.work,'v','lib',ops)

 def test_single_and_overall_excel_share_check_results(self):
  from ai_lib_qor.application.minimal_checks import run_revision,run_library
  from openpyxl import load_workbook
  single=run_revision(self.work,'v','lib','rev_0002')
  self.assertEqual(single['state'],'PARTIAL',single)
  check=json.loads(Path(single['check']).read_text());self.assertEqual(check['revision'],'rev_0002')
  self.assertTrue(any(c['check_id']=='LEF_LIBERTY_PIN_MATCH' and c['result']=='PASS' for c in check['checks']))
  self.assertTrue(any(c['attribute']=='SIZE' and c['new_value']==[4.0,3.0] for c in check['changes']))
  self.assertTrue(any(f['view']=='GDS' and f['status']=='NOT_CHECKED' for f in check['files']))
  book=load_workbook(single['excel'],read_only=True,data_only=True)
  self.assertIn('文件版本矩阵',book.sheetnames);self.assertIn('12-有效文件来源',book.sheetnames)
  batch=run_library(self.work,'v','lib')
  self.assertEqual(batch['state'],'PARTIAL',batch)
  data=json.loads(Path(batch['overall']).read_text())
  self.assertEqual([r['revision'] for r in data['versions']],['rev_0001','rev_0002'])
  check2=json.loads(Path(data['versions'][1]['check']).read_text())
  self.assertEqual([(c['check_id'],c['result']) for c in check2['checks']],[(c['check_id'],c['result']) for c in check['checks']])
  self.assertTrue(Path(batch['excel']).is_file())

 def test_missing_file_is_reported_not_passed(self):
  from ai_lib_qor.application.minimal_checks import run_revision
  (self.raw/'v/lib'/self.v2/'LIB/a.lib').unlink()
  result=run_revision(self.work,'v','lib','rev_0002');self.assertEqual(result['state'],'PARTIAL')
  check=json.loads(Path(result['check']).read_text())
  self.assertTrue(any(f['view']=='LIBERTY' and f['status']=='FAILED' for f in check['files']))
  self.assertFalse(any(c['check_id']=='LEF_LIBERTY_PIN_MATCH' and c['result']=='PASS' for c in check['checks']))
  from ai_lib_qor.application.minimal_checks import run_library
  from openpyxl import load_workbook
  batch=run_library(self.work,'v','lib')
  rows=list(load_workbook(batch['excel'],read_only=True,data_only=True)['版本运行汇总'].values)
  self.assertTrue(any(any('解析失败' in str(v) for v in row if v is not None) for row in rows))

 def test_changed_source_cannot_reuse_fact_within_batch(self):
  from unittest.mock import patch
  import ai_lib_qor.application.minimal_checks as checks
  original=checks._run
  def run(*args,**kwargs):
   result=original(*args,**kwargs)
   if result['revision']=='rev_0001':
    (self.raw/'v/lib'/self.v1/'LEF/a.lef').write_text('changed after first revision')
   return result
  with patch.object(checks,'_run',side_effect=run):result=checks.run_library(self.work,'v','lib')
  self.assertEqual(result['state'],'PARTIAL')
  check=json.loads(Path(result['versions'][1]['check']).read_text())
  self.assertTrue(any(x['check_id']=='LEF_MACRO_DIFF' and x['result']=='INCONCLUSIVE' for x in check['checks']))
  self.assertEqual(check['comparisons'],[])

 def test_ambiguous_lef_pair_never_reports_pass(self):
  from ai_lib_qor.application.minimal_checks import run_revision
  version='20261003_abcdef12';path=self.raw/'v/lib'/version/'LEF/other.lef';path.parent.mkdir(parents=True)
  path.write_text('MACRO A\n SIZE 4 BY 3 ;\n PIN IN\n DIRECTION INPUT ;\n END IN\nEND A\n')
  build_from_roots(self.raw,self.root/'NL1',self.work)
  update_effective(self.work,'v','lib',{'set':[{'view':'LEF','version':version,'path':'LEF/other.lef'}],'remove':[]})
  result=run_revision(self.work,'v','lib','rev_0003')
  self.assertEqual(result['state'],'PARTIAL')
  data=json.loads(Path(result['check']).read_text())
  self.assertTrue(any(c['result']=='INCONCLUSIVE' and '不唯一' in c['detail'] for c in data['checks']))
  self.assertFalse(any(c['check_id']=='LEF_LIBERTY_PIN_MATCH' and c['result']=='PASS' for c in data['checks']))

 def test_partial_netlist_differences_are_observations_not_pass(self):
  from ai_lib_qor.application.minimal_checks import run_revision
  version='20261003_abcdef12';files={'VERILOG/a.v':'module A(output IN); endmodule\n',
                                      'CDL/a.cdl':'.SUBCKT A VDD IN\nR1 IN VDD 10\n.ENDS A\n',
                                      'SPICE/a.spice':'.SUBCKT A VDD IN\nR1 IN VDD 10\n.ENDS A\n'}
  for rel,text in files.items():
   f=self.raw/'v/lib'/version/rel;f.parent.mkdir(parents=True,exist_ok=True);f.write_text(text)
  build_from_roots(self.raw,self.root/'NL1',self.work)
  ops={'set':[{'view':view,'version':version,'path':path} for view,path in [('VERILOG','VERILOG/a.v'),('CDL','CDL/a.cdl'),('SPICE','SPICE/a.spice')]],'remove':[]}
  update_effective(self.work,'v','lib',ops)
  result=run_revision(self.work,'v','lib','rev_0003')
  data=json.loads(Path(result['check']).read_text())
  for view in ('VERILOG','CDL','SPICE'):
   row=next(x for x in data['partial_comparisons'] if x['view']==view)
   self.assertTrue(row['differences']);self.assertEqual(row['coverage'],'PARTIAL')
  self.assertEqual(result['state'],'PARTIAL')
