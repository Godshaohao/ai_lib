import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ai_lib_qor.sources.root_inventory import build_from_roots
from ai_lib_qor.application.minimal_effective import initialize_from_formal


class MinimalFactsTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.base=Path(self.tmp.name)
  self.work=self.base/'work';raw=self.base/'raw';nl=self.base/'NL1';nl.mkdir()
  version='20261024_abcdef12';self.version=version
  files={'LEF/a.lef':'MACRO A\n SIZE 2 BY 3 ;\n PIN IN\n DIRECTION INPUT ;\n END IN\n PIN VDD\n DIRECTION INOUT ;\n USE POWER ;\n END VDD\nEND A\n',
         'LIB/a.lib':'library(test) { cell(A) { pin(IN) { direction : input; } } }'}
  for path,text in files.items():
   file=raw/'v/lib'/version/path;file.parent.mkdir(parents=True,exist_ok=True);file.write_text(text)
   (nl/file.name).symlink_to(file)
  build_from_roots(raw,nl,self.work)
  self.folder=self.work/'libraries/v/lib'
  initialize_from_formal(self.work,'v','lib',next(self.folder.glob('formal/formal_NL1_*.json')))

 def test_revision_file_facts_use_paths_and_no_old_ids(self):
  from ai_lib_qor.application.minimal_facts import build_facts
  result=build_facts(self.work,'v','lib','LEF','LEF/a.lef',revision='rev_0001')
  facts=json.loads(Path(result['path']).read_text())
  self.assertEqual(facts['source']['version'],self.version)
  self.assertEqual(facts['source']['relative_path'],'LEF/a.lef')
  self.assertEqual(facts['source']['absolute_path'],str(self.base/'raw/v/lib'/self.version/'LEF/a.lef'))
  self.assertEqual(facts['objects']['macros'][0]['size_um'],[2.0,3.0])
  self.assertEqual(facts['source']['historical_content'],'UNVERIFIED')
  self.assertNotIn('delivery_id',json.dumps(facts));self.assertNotIn('file_id',json.dumps(facts))

 def test_exact_version_liberty_and_failed_selection(self):
  from ai_lib_qor.application.minimal_facts import build_facts
  result=build_facts(self.work,'v','lib','LIBERTY','LIB/a.lib',version=self.version)
  facts=json.loads(Path(result['path']).read_text())
  self.assertEqual(facts['objects']['cells'][0]['name'],'A')
  with self.assertRaises(ValueError):build_facts(self.work,'v','lib','LEF','LIB/a.lib',version=self.version)
  with self.assertRaises(ValueError):build_facts(self.work,'v','lib','LEF','LEF/a.lef')

 def test_stale_index_and_changed_file_during_parse_do_not_publish(self):
  from ai_lib_qor.application.minimal_facts import build_facts
  import ai_lib_qor.facts.parsers as parsers
  actual=parsers.parse_file_payload
  def change(path,view,**kwargs):
   result=actual(path,view,**kwargs);Path(path).write_text('modified');return result
  with patch.object(parsers,'parse_file_payload',side_effect=change):
   with self.assertRaisesRegex(ValueError,'变化'):build_facts(self.work,'v','lib','LEF','LEF/a.lef',version=self.version)
  self.assertFalse(list(self.folder.glob('facts_*.json')))

 def test_lef_power_pins_keep_their_type(self):
  from ai_lib_qor.application.minimal_facts import build_facts
  result=build_facts(self.work,'v','lib','LEF','LEF/a.lef',revision='rev_0001')
  fact=json.loads(Path(result['path']).read_text())
  self.assertEqual(next(p for p in fact['objects']['macros'][0]['pins'] if p['name']=='VDD')['use'],'POWER')

 def test_stale_index_and_missing_revision_member_are_rejected(self):
  from ai_lib_qor.application.minimal_facts import build_facts
  from ai_lib_qor.application.minimal_effective import update_effective
  update_effective(self.work,'v','lib',{'set':[],'remove':[{'view':'LEF','path':'LEF/a.lef'}]})
  with self.assertRaisesRegex(ValueError,'没有该文件'):
   build_facts(self.work,'v','lib','LEF','LEF/a.lef',revision='rev_0002')
  archive=next(self.folder.glob('delivery/delivery_*.json'));archive.write_text(archive.read_text().replace('LEF/a.lef','LEF/other.lef'))
  with self.assertRaisesRegex(ValueError,'索引'):
   build_facts(self.work,'v','lib','LIBERTY','LIB/a.lib',version=self.version)
  self.assertFalse(list(self.folder.glob('facts_*.json')))

 def test_source_escaping_symlink_is_rejected(self):
  from ai_lib_qor.application.minimal_facts import build_facts
  source=self.base/'raw/v/lib'/self.version/'LEF/a.lef';outside=self.base/'outside.lef'
  outside.write_text(source.read_text());source.unlink();source.symlink_to(outside)
  with self.assertRaisesRegex(ValueError,'越界|符号链接'):
   build_facts(self.work,'v','lib','LEF','LEF/a.lef',version=self.version)
  self.assertFalse(list(self.folder.glob('facts_*.json')))

 def test_cli_uses_new_contract_without_legacy_sidecars(self):
  import os,subprocess,sys
  cmd=[sys.executable,'-m','ai_lib_qor','minimal-facts','--work',str(self.work),'--vendor','v',
       '--library','lib','--view','LIBERTY','--path','LIB/a.lib','--version',self.version]
  proc=subprocess.run(cmd,capture_output=True,text=True,env=os.environ.copy())
  self.assertEqual(proc.returncode,0,proc.stderr+proc.stdout)
  result=json.loads(proc.stdout);fact=json.loads(Path(result['path']).read_text())
  self.assertEqual(fact['schema_version'],'file_facts.path.v1')
  self.assertFalse(list(self.folder.glob('evidence_delivery*.json')))

 def test_verilog_cdl_spice_are_partial_path_facts(self):
  from ai_lib_qor.application.minimal_facts import build_facts
  from ai_lib_qor.application.minimal_file_index import refresh_index
  from ai_lib_qor.sources.root_inventory import build_from_roots
  raw=self.base/'raw';version='20261025_abcdef12'
  files={'VERILOG/a.v':'module A(input A, output Y); endmodule\n',
         'CDL/a.cdl':'.SUBCKT A A Y VDD VSS\nR1 A Y 10\n.ENDS A\n',
         'SPICE/a.spice':'.SUBCKT A A Y VDD VSS\nR1 A Y 10\n.ENDS A\n'}
  for name,text in files.items():
   p=raw/'v/lib'/version/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(text)
  build_from_roots(raw,self.base/'NL1',self.work)
  for view,path in [('VERILOG','VERILOG/a.v'),('CDL','CDL/a.cdl'),('SPICE','SPICE/a.spice')]:
   result=build_facts(self.work,'v','lib',view,path,version=version)
   data=json.loads(Path(result['path']).read_text())
   self.assertEqual(data['parse_status'],'PARTIAL')
   self.assertEqual(data['view'],view)
   self.assertTrue(data['objects']['modules' if view=='VERILOG' else 'subcircuits'])
