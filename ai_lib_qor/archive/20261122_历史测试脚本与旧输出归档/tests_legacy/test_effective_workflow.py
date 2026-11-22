import json
import tempfile
import unittest
from pathlib import Path

from ai_lib_qor.application.data_query import LibraryDataQuery
from ai_lib_qor.application.effective_json import create_revision, _flat_views
from ai_lib_qor.application.effective_publisher import publish_v2
from ai_lib_qor.application.simple_sources import simple_raw
from ai_lib_qor.sources.delivery_builder import build_delivery


class EffectiveWorkflowTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
  self.root=Path(self.tmp.name); self.work=self.root/'work'; self.folder=self.work/'libraries/v/lib'; self.folder.mkdir(parents=True)
  self.source={'vendor_id':'v','source_library_id':'lib','root':str(self.root/'raw'),'delivery_orders':{'V05':5,'V06':6,'V07':7}}
  (self.work/'scan_sources.json').write_text(json.dumps({'sources':[self.source]}))
  self.files={'lef/a.lef':'lef','lib/ff.lib':'ff','lib/ss.lib':'ss','lib/tt.lib':'tt','gds/a.gds':'gds','cdl/a.cdl':'cdl','verilog/a.v':'verilog'}
  self.delivery(5,self.files)
  self.delivery(6,{'lef/renamed.lef':'lef','lib/ff.lib':'ff'})
  q=LibraryDataQuery(self.work,self.root/'runs'); raw=simple_raw(q,'v','lib','V05')
  self.parent=create_revision(raw,owner={'type':'SOURCE_LIBRARY','id':'lib'},revision='rev_0001',created_at='2026-01-01',include_views=list(raw['views']))
  publish_v2(self.work,self.folder/'effective_lib_001.json',self.parent)
 def delivery(self,n,files,basis='explicit'):
  raw=self.root/'raw'/f'V{n:02}'; raw.mkdir(parents=True)
  for path in files:
   f=raw/path;f.parent.mkdir(parents=True,exist_ok=True);f.write_text('fixture')
  metadata={'delivery_id':f'd{n}','vendor_id':'v','source_library_id':'lib','supplier_version':f'V{n:02}','delivery_order':n,'received_at':'2026-01-01T00:00:00Z','package_mode':'UNKNOWN'}
  record=build_delivery(raw,metadata,{p:{'file_key':key} for p,key in files.items()})
  (self.folder/f'delivery_{n:03}.json').write_text(json.dumps(record))
  (self.folder/f'evidence_delivery_{n:03}.json').write_text(json.dumps({'order_basis':'configured_order','classification':{p:{'basis':basis} for p in files}}))
 def test_preview_and_apply_partial_delivery_rename_and_replay(self):
  from ai_lib_qor.application.effective_workflow import preview_effective_update, apply_effective_update
  preview=preview_effective_update(self.work,'v','lib','lib','d6')
  self.assertEqual(preview['state'],'READY',preview)
  files=_flat_views(preview['candidate']);self.assertEqual(len(files),7)
  self.assertIn(('LEF','lef/renamed.lef'),files);self.assertNotIn(('LEF','lef/a.lef'),files)
  self.assertEqual(sum(x['version']=='V06' for x in files.values()),2)
  self.assertFalse((self.folder/'effective_lib_002.json').exists())
  out=apply_effective_update(self.work,'v','lib','lib','d6',expected_parent_revision='rev_0001')
  self.assertIn(out['state'],('PUBLISHED','PUBLISHED_INDEX_STALE'));self.assertEqual(out['revision'],'rev_0002')
  index=json.loads((self.folder/'effective_lib_index.json').read_text());self.assertEqual(index['current_accepted_revision'],'rev_0002')
  self.assertEqual(preview_effective_update(self.work,'v','lib','lib','d6')['state'],'NO_CHANGE')
 def test_new_delivery_automatically_updates_existing_set(self):
  from ai_lib_qor.application.effective_workflow import process_registered_delivery
  outcomes=process_registered_delivery(self.work,'v','lib','d6')
  self.assertEqual(len(outcomes),1)
  self.assertEqual(outcomes[0]['set_id'],'lib')
  self.assertIn(outcomes[0]['state'],('PUBLISHED','PUBLISHED_INDEX_STALE'))
  self.assertEqual(len(_flat_views(json.loads((self.folder/'effective_lib_002.json').read_text()))),7)
 def test_scan_registers_and_automatically_publishes_confirmed_update(self):
  from ai_lib_qor.application.effective_workflow import apply_effective_update
  from ai_lib_qor.sources.auto_ingest import auto_ingest
  from ai_lib_qor.sources.update_scan import scan_library
  apply_effective_update(self.work,'v','lib','lib','d6',expected_parent_revision='rev_0001')
  new=self.root/'raw/V07/lef/renamed.lef';new.parent.mkdir(parents=True);new.write_text('LEF')
  self.source.update(version_paths={'V05':'V05','V06':'V06','V07':'V07'},file_mapping={'V07/lef/renamed.lef':{'file_key':'lef'}})
  (self.work/'scan_sources.json').write_text(json.dumps({'sources':[self.source]}))
  result=auto_ingest(self.work,self.source,scan_library(self.root/'raw','v','lib',metadata_only=True))
  self.assertEqual(result['created'],1,result)
  self.assertEqual(result['effective_updates'][0]['state'],'PUBLISHED',result)
  self.assertTrue((self.folder/'effective_lib_003.json').is_file())
 def test_cli_preview_is_read_only_and_machine_readable(self):
  import os, subprocess, sys
  cmd=[sys.executable,'-m','ai_lib_qor','effective-preview','--work',str(self.work),'--vendor','v','--library','lib','--set-id','lib','--delivery-id','d6']
  process=subprocess.run(cmd,capture_output=True,text=True,env=os.environ.copy())
  self.assertEqual(process.returncode,0,process.stderr)
  self.assertEqual(json.loads(process.stdout)['state'],'READY')
  self.assertFalse((self.folder/'effective_lib_002.json').exists())
 def test_same_delivery_can_extend_explicit_set_and_replay_is_idempotent(self):
  from ai_lib_qor.application.effective_workflow import preview_effective_update,apply_effective_update
  raw=self.root/'raw/V06';extra=raw/'lib/new.lib';extra.write_text('fixture')
  path=self.folder/'delivery_006.json';old=json.loads(path.read_text())
  metadata={key:old[key] for key in ('delivery_id','vendor_id','source_library_id','supplier_version','delivery_order','received_at','package_mode')}
  paths={'lef/renamed.lef':'lef','lib/ff.lib':'ff','lib/new.lib':'new'}
  path.write_text(json.dumps(build_delivery(raw,metadata,{p:{'file_key':key} for p,key in paths.items()})))
  (self.folder/'evidence_delivery_006.json').write_text(json.dumps({'order_basis':'configured_order','classification':{p:{'basis':'explicit'} for p in paths}}))
  self.assertEqual(preview_effective_update(self.work,'v','lib','lib','d6')['state'],'NEEDS_REVIEW')
  selection=preview_effective_update(self.work,'v','lib','lib','d6',include_file_keys=['lef','ff'])
  first=apply_effective_update(self.work,'v','lib','lib','d6',expected_parent_revision='rev_0001',include_file_keys=['lef','ff'],expected_preview_token=selection['preview_token'])
  self.assertEqual(first['revision'],'rev_0002')
  second=preview_effective_update(self.work,'v','lib','lib','d6',include_file_keys=['new'])
  self.assertEqual(second['state'],'READY',second);self.assertEqual(len(_flat_views(second['candidate'])),8)
  self.assertEqual(apply_effective_update(self.work,'v','lib','lib','d6',expected_parent_revision='rev_0002',include_file_keys=['new'],expected_preview_token=second['preview_token'])['revision'],'rev_0003')
  self.assertEqual(preview_effective_update(self.work,'v','lib','lib','d6',include_file_keys=['new'])['state'],'NO_CHANGE')
 def test_changed_selection_cannot_reuse_confirmation(self):
  from ai_lib_qor.application.effective_workflow import preview_effective_update,apply_effective_update
  preview=preview_effective_update(self.work,'v','lib','lib','d6',include_file_keys=['lef'])
  with self.assertRaisesRegex(ValueError,'预览'):
   apply_effective_update(self.work,'v','lib','lib','d6',expected_parent_revision='rev_0001',include_file_keys=['ff'],expected_preview_token=preview['preview_token'])
  self.assertFalse((self.folder/'effective_lib_002.json').exists())
 def test_explicit_removal_requires_selection_and_is_idempotent(self):
  from ai_lib_qor.application.effective_workflow import preview_effective_update,apply_effective_update
  path=self.folder/'delivery_006.json';record=json.loads(path.read_text())
  record['explicit_removed_file_keys']=['ss'];path.write_text(json.dumps(record))
  selected=preview_effective_update(self.work,'v','lib','lib','d6',include_file_keys=['lef'])
  self.assertEqual(len(_flat_views(selected['candidate'])),7)
  apply_effective_update(self.work,'v','lib','lib','d6',expected_parent_revision='rev_0001',include_file_keys=['lef'],expected_preview_token=selected['preview_token'])
  removal=preview_effective_update(self.work,'v','lib','lib','d6',include_file_keys=['ss'])
  self.assertEqual(len(_flat_views(removal['candidate'])),6)
  apply_effective_update(self.work,'v','lib','lib','d6',expected_parent_revision='rev_0002',include_file_keys=['ss'],expected_preview_token=removal['preview_token'])
  self.assertEqual(preview_effective_update(self.work,'v','lib','lib','d6',include_file_keys=['ss'])['state'],'NO_CHANGE')
 def test_new_file_requires_scope_confirmation_for_source_library(self):
  from ai_lib_qor.application.effective_workflow import preview_effective_update,apply_effective_update
  apply_effective_update(self.work,'v','lib','lib','d6',expected_parent_revision='rev_0001')
  self.delivery(7,{'lib/new.lib':'new'})
  self.assertEqual(preview_effective_update(self.work,'v','lib','lib','d7')['state'],'NEEDS_REVIEW')
  self.assertEqual(preview_effective_update(self.work,'v','lib','lib','d7',include_file_keys=['new'])['state'],'READY')
 def test_unconfirmed_file_requires_review(self):
  from ai_lib_qor.application.effective_workflow import preview_effective_update
  self.delivery(7,{'lib/new.lib':'new'},basis='filename_unique_candidate')
  out=preview_effective_update(self.work,'v','lib','lib','d7')
  self.assertEqual(out['state'],'NEEDS_REVIEW');self.assertFalse((self.folder/'effective_lib_002.json').exists())

class IdentityConflictTests(unittest.TestCase):
 def test_archived_confirmed_duplicate_identity_is_rejected(self):
  from ai_lib_qor.application.source_repository import SourceRepository
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);work=root/'work';folder=work/'libraries/v/lib';folder.mkdir(parents=True);raw=root/'raw';raw.mkdir()
   for path in ('a.lef','b.lef'):(raw/path).write_text('fixture')
   meta={'delivery_id':'d1','vendor_id':'v','source_library_id':'lib','supplier_version':'V1','delivery_order':1,'received_at':'2026-01-01T00:00:00Z','package_mode':'UNKNOWN'}
   record=build_delivery(raw,meta,{'a.lef':{'file_key':'a'},'b.lef':{'file_key':'b'}})
   record['files'][1]['file_key']='a';record['package_scope']['file_keys']=['a']
   (folder/'delivery_001.json').write_text(json.dumps(record))
   (folder/'evidence_delivery_001.json').write_text(json.dumps({'classification':{'a.lef':{'basis':'explicit'},'b.lef':{'basis':'explicit'}}}))
   with self.assertRaisesRegex(ValueError,'身份.*重复'):
    SourceRepository(work).deliveries(vendor='v',library='lib')

class DeliveryExclusionTests(EffectiveWorkflowTests):
 def test_exclusion_preserves_history_and_can_be_reversed(self):
  from ai_lib_qor.application.effective_workflow import set_delivery_exclusion, preview_effective_update, apply_effective_update
  before=(self.folder/'delivery_006.json').read_bytes(); parent=(self.folder/'effective_lib_001.json').read_bytes()
  result=set_delivery_exclusion(self.work,'v','lib','lib','d6',excluded=True,actor='operator',reason='验证')
  self.assertEqual(result['state'],'EXCLUDED')
  self.assertEqual(preview_effective_update(self.work,'v','lib','lib','d6')['state'],'EXCLUDED')
  self.assertEqual(apply_effective_update(self.work,'v','lib','lib','d6',expected_parent_revision='rev_0001')['state'],'EXCLUDED')
  repeat=set_delivery_exclusion(self.work,'v','lib','lib','d6',excluded=True,actor='operator',reason='验证')
  self.assertEqual(repeat['state'],'UNCHANGED')
  self.assertEqual((self.folder/'delivery_006.json').read_bytes(),before);self.assertEqual((self.folder/'effective_lib_001.json').read_bytes(),parent)
  restored=set_delivery_exclusion(self.work,'v','lib','lib','d6',excluded=False,actor='operator',reason='恢复')
  self.assertEqual(restored['state'],'INCLUDED')
  self.assertEqual(preview_effective_update(self.work,'v','lib','lib','d6')['state'],'READY')
  self.assertEqual(len((self.folder/'runs.jsonl').read_text().splitlines()),2)
 def test_exclusion_reports_current_use(self):
  from ai_lib_qor.application.effective_workflow import set_delivery_exclusion
  result=set_delivery_exclusion(self.work,'v','lib','lib','d5',excluded=True,actor='operator',reason='暂不使用')
  self.assertTrue(result['current_revision_uses_delivery']);self.assertEqual(result['current_revision'],'rev_0001')
 def test_acceptance_rollback_keeps_latest_calculated_and_history(self):
  from ai_lib_qor.application.effective_workflow import apply_effective_update, rollback_acceptance
  apply_effective_update(self.work,'v','lib','lib','d6',expected_parent_revision='rev_0001')
  second=(self.folder/'effective_lib_002.json').read_bytes()
  result=rollback_acceptance(self.work,'v','lib','lib','rev_0001',actor='operator',reason='回退')
  self.assertEqual(result['index']['current_accepted_revision'],'rev_0001')
  self.assertEqual(result['index']['latest_calculated_revision'],'rev_0002')
  self.assertEqual((self.folder/'effective_lib_002.json').read_bytes(),second)
  with self.assertRaises(ValueError):rollback_acceptance(self.work,'v','lib','lib','rev_0002',actor='operator',reason='无效')
 def test_restore_creates_new_revision_with_historical_contents(self):
  from ai_lib_qor.application.effective_workflow import apply_effective_update, restore_effective_revision
  apply_effective_update(self.work,'v','lib','lib','d6',expected_parent_revision='rev_0001')
  previous=(self.folder/'effective_lib_002.json').read_bytes()
  result=restore_effective_revision(self.work,'v','lib','lib','rev_0001',expected_parent_revision='rev_0002',actor='operator',reason='恢复')
  self.assertEqual(result['state'],'PUBLISHED');self.assertEqual(result['revision'],'rev_0003')
  restored=json.loads((self.folder/'effective_lib_003.json').read_text())
  self.assertEqual(restored['parent'],'rev_0002');self.assertEqual(_flat_views(restored),_flat_views(self.parent))
  self.assertEqual((self.folder/'effective_lib_002.json').read_bytes(),previous)
 def test_publish_rechecks_exclusion_under_library_lock(self):
  from unittest.mock import patch
  from ai_lib_qor.application import effective_publisher
  from ai_lib_qor.application.effective_workflow import apply_effective_update,set_delivery_exclusion
  original=effective_publisher.publish_v2
  def race(*args,**kwargs):
   set_delivery_exclusion(self.work,'v','lib','lib','d6',excluded=True,actor='operator',reason='并发排除')
   return original(*args,**kwargs)
  with patch.object(effective_publisher,'publish_v2',side_effect=race):
   with self.assertRaisesRegex(ValueError,'已被排除'):
    apply_effective_update(self.work,'v','lib','lib','d6',expected_parent_revision='rev_0001')
  self.assertFalse((self.folder/'effective_lib_002.json').exists())
 def test_two_processes_do_not_publish_two_revisions(self):
  import multiprocessing
  from ai_lib_qor.application.effective_workflow import apply_effective_update
  ctx=multiprocessing.get_context('fork');start=ctx.Event();queue=ctx.Queue()
  def run():
   start.wait()
   try:queue.put(apply_effective_update(self.work,'v','lib','lib','d6',expected_parent_revision='rev_0001')['state'])
   except (ValueError,OSError) as exc:queue.put('REJECTED:'+str(exc))
  workers=[ctx.Process(target=run) for _ in range(2)]
  for process in workers:process.start()
  start.set()
  for process in workers:process.join(15);self.assertEqual(process.exitcode,0)
  results=[queue.get(timeout=2) for _ in workers]
  self.assertEqual(sum(x in ('PUBLISHED','PUBLISHED_INDEX_STALE') for x in results),1,results)
  self.assertTrue((self.folder/'effective_lib_002.json').is_file())
  self.assertFalse((self.folder/'effective_lib_003.json').exists())
 def test_restore_rejects_excluded_historical_source(self):
  from ai_lib_qor.application.effective_workflow import apply_effective_update,restore_effective_revision,set_delivery_exclusion
  apply_effective_update(self.work,'v','lib','lib','d6',expected_parent_revision='rev_0001')
  set_delivery_exclusion(self.work,'v','lib','lib','d5',excluded=True,actor='operator',reason='排除')
  with self.assertRaisesRegex(ValueError,'已排除'):
   restore_effective_revision(self.work,'v','lib','lib','rev_0001',expected_parent_revision='rev_0002',actor='operator',reason='恢复')
  self.assertFalse((self.folder/'effective_lib_003.json').exists())
 def test_exclusion_rejects_unknown_ids_without_mutation(self):
  from ai_lib_qor.application.effective_workflow import set_delivery_exclusion
  data=(self.work/'scan_sources.json').read_bytes()
  with self.assertRaises(ValueError):set_delivery_exclusion(self.work,'v','lib','lib','unknown',excluded=True,actor='operator',reason='test')
  self.assertEqual((self.work/'scan_sources.json').read_bytes(),data)
