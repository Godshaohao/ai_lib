import json, os, subprocess, sys, tempfile, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV = {**os.environ, 'PYTHONPATH': str(ROOT / 'src')}
EX = ROOT / 'examples/work'

class VersionFlow(unittest.TestCase):
 def setUp(self):
  self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
  self.root = Path(self.tmp.name); self.work = self.root/'effective'
  self.raw = self.root/'raw'; (self.raw/'V07/lef').mkdir(parents=True); (self.raw/'V08/lef').mkdir(parents=True)
  (self.raw/'V07/lef/core.lef').write_text('MACRO MAC_A\n SIZE 120 BY 80 ;\nEND MAC_A\n')
  (self.raw/'V08/lef/core.lef').write_text('MACRO MAC_A\n SIZE 124 BY 80 ;\nEND MAC_A\n')
  for ver in ('V07','V08'):
   (self.raw/ver/'lib').mkdir()
   (self.raw/ver/'lib/func_tt.lib').write_text('library(tt) {}\n')
  (self.raw/'V07/lib/func_ff.lib').write_text('library(ff) {}\n')
  self.input_dir=self.root/'inputs'; self.input_dir.mkdir()
  self.d07=self.copy_fixture('vendors/vendor_orion/libraries/lib_rtavfs/deliveries/dlv_20260907_001/delivery.json','d07.json','V07')
  self.d08=self.copy_fixture('vendors/vendor_orion/libraries/lib_rtavfs/deliveries/dlv_20261019_001/delivery.json','d08.json','V08')
 def copy_fixture(self, rel, name, ver):
  data=json.loads((EX/rel).read_text()); data['source_root']=str(self.raw/ver)
  dest=self.input_dir/name; dest.write_text(json.dumps(data)); return dest
 def cmd(self,*args, ok=True):
  p=subprocess.run([sys.executable,'-m','ai_lib_qor.versions',*map(str,args)],env=ENV,text=True,capture_output=True)
  if ok:self.assertEqual(p.returncode,0,p.stderr)
  else:self.assertNotEqual(p.returncode,0,p.stdout)
  return p
 def init(self):
  return self.cmd('init','--effective-dir',self.work,'--delivery',self.d07,'--set-id','rtavfs_primary','--owner-type','BUSINESS_IP','--owner-id','rtavfs','--home-library','lib_rtavfs')
 def test_incremental_preserves_missing_and_acceptance_is_independent(self):
  self.init();self.cmd('accept','--effective-dir',self.work,'--revision','rev_0001','--actor','owner','--reason','baseline')
  self.cmd('apply','--effective-dir',self.work,'--delivery',self.d08)
  r=json.loads((self.work/'versions/rev_0002.json').read_text());members={m['file_key']:m['source_ref']['delivery_id'] for m in r['members']}
  self.assertEqual(members['lib_rtavfs:liberty:func_ff'],'dlv_20260907_001')
  self.assertEqual(members['lib_rtavfs:lef:core'],'dlv_20261019_001');self.assertEqual(len(r['changes']),2)
  index=json.loads((self.work/'index.json').read_text());self.assertEqual(index['latest_calculated_revision'],'rev_0002');self.assertEqual(index['current_accepted_revision'],'rev_0001')
  before=(self.work/'versions/rev_0001.json').read_bytes();self.cmd('apply','--effective-dir',self.work,'--delivery',self.d08)
  self.assertFalse((self.work/'versions/rev_0003.json').exists());self.assertEqual(before,(self.work/'versions/rev_0001.json').read_bytes())
  self.assertEqual((self.raw/'V08/lef/core.lef').read_text(),'MACRO MAC_A\n SIZE 124 BY 80 ;\nEND MAC_A\n')
 def test_reject_unresolved_and_unknown_removal(self):
  self.init();d=json.loads(self.d08.read_text());d['files'][0]['classification']='UNRESOLVED';d['files'][0]['file_key']=None;self.d08.write_text(json.dumps(d))
  self.cmd('apply','--effective-dir',self.work,'--delivery',self.d08,ok=False);self.assertFalse((self.work/'versions/rev_0002.json').exists())
 def test_rollback_revoke_and_index_recovery(self):
  self.init();self.cmd('apply','--effective-dir',self.work,'--delivery',self.d08)
  for action,rev in [('accept','rev_0001'),('accept','rev_0002'),('rollback','rev_0001')]:self.cmd(action,'--effective-dir',self.work,'--revision',rev,'--actor','owner','--reason','review')
  (self.work/'index.json').unlink();self.cmd('rebuild-index','--effective-dir',self.work)
  index=json.loads((self.work/'index.json').read_text());self.assertEqual(index['current_accepted_revision'],'rev_0001');self.assertEqual(index['latest_calculated_revision'],'rev_0002')
  self.cmd('revoke','--effective-dir',self.work,'--revision','rev_0001','--actor','owner','--reason','review')
  self.assertIsNone(json.loads((self.work/'index.json').read_text())['current_accepted_revision'])
 def test_reject_missing_file_and_tampered_parent(self):
  self.init();(self.raw/'V08/lef/core.lef').unlink();self.cmd('apply','--effective-dir',self.work,'--delivery',self.d08,'--verify-files',ok=False)
  r=self.work/'versions/rev_0001.json';data=json.loads(r.read_text());data['changes']=[];r.write_text(json.dumps(data))
  self.cmd('rebuild-index','--effective-dir',self.work,ok=False)
 def test_reject_older_delivery_and_changed_record_identity(self):
  self.init();self.cmd('apply','--effective-dir',self.work,'--delivery',self.d08)
  self.cmd('apply','--effective-dir',self.work,'--delivery',self.d07,ok=False)
  record=json.loads(self.d08.read_text());record['supplier_version']='V08-rewritten';self.d08.write_text(json.dumps(record))
  self.cmd('apply','--effective-dir',self.work,'--delivery',self.d08,ok=False)
  self.assertFalse((self.work/'versions/rev_0003.json').exists())
 def test_reject_unconfigured_cross_library(self):
  self.init();record=json.loads(self.d08.read_text());record['source_library_id']='another_lib';self.d08.write_text(json.dumps(record))
  self.cmd('apply','--effective-dir',self.work,'--delivery',self.d08,ok=False)
  self.assertFalse((self.work/'versions/rev_0002.json').exists())
 def test_explicit_cross_library_can_add_member(self):
  self.init();record=json.loads(self.d08.read_text());record['source_library_id']='another_lib';record['delivery_id']='cross_001';record['delivery_order']=1
  record['files']=record['files'][:1];record['files'][0]['file_key']='another_lib:lef:core';record['package_scope']['file_keys']=['another_lib:lef:core'];self.d08.write_text(json.dumps(record))
  self.cmd('apply','--effective-dir',self.work,'--delivery',self.d08,'--allow-source-library','another_lib')
  rev=json.loads((self.work/'versions/rev_0002.json').read_text());self.assertIn('another_lib:lef:core',[m['file_key'] for m in rev['members']])
 def test_apply_selected_file_only(self):
  self.init();self.cmd('apply','--effective-dir',self.work,'--delivery',self.d08,'--file-key','lib_rtavfs:lef:core')
  r=json.loads((self.work/'versions/rev_0002.json').read_text());m={x['file_key']:x['source_ref']['delivery_id'] for x in r['members']}
  self.assertEqual(m['lib_rtavfs:lef:core'],'dlv_20261019_001');self.assertEqual(m['lib_rtavfs:liberty:func_tt'],'dlv_20260907_001')
  self.cmd('apply','--effective-dir',self.work,'--delivery',self.d08,'--file-key','not-present',ok=False)
 def test_can_rebuild_existing_v3_example_history(self):
  source=EX/'vendors/vendor_orion/libraries/lib_rtavfs/ips/rtavfs/effective'
  (self.work/'versions').mkdir(parents=True)
  for file in ('rev_0001.json','rev_0002.json'):
   (self.work/'versions'/file).write_text((source/'versions'/file).read_text())
  (self.work/'acceptance.jsonl').write_text((source/'acceptance.jsonl').read_text())
  self.cmd('rebuild-index','--effective-dir',self.work)
  index=json.loads((self.work/'index.json').read_text());self.assertEqual(index['current_accepted_revision'],'rev_0001');self.assertEqual(index['latest_calculated_revision'],'rev_0002')
 def test_snapshot_baseline_and_explicit_remove(self):
  snap=EX/'formal_nl/NL2.5.3/snapshots/snap_nl253_0001.json'
  self.cmd('init','--effective-dir',self.work,'--snapshot',snap,'--set-id','rtavfs_primary','--owner-type','BUSINESS_IP','--owner-id','rtavfs','--home-library','lib_rtavfs')
  d=json.loads(self.d08.read_text());d['explicit_removed_file_keys']=['lib_rtavfs:liberty:func_ff'];self.d08.write_text(json.dumps(d))
  self.cmd('apply','--effective-dir',self.work,'--delivery',self.d08)
  rev=json.loads((self.work/'versions/rev_0002.json').read_text());self.assertNotIn('lib_rtavfs:liberty:func_ff',[m['file_key'] for m in rev['members']]);self.assertEqual({c['action'] for c in rev['changes']},{'REMOVED','REPLACED'})

if __name__=='__main__':unittest.main()
