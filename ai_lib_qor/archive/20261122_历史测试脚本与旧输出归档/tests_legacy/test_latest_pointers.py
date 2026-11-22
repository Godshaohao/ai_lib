import json
import shutil
import tempfile
import unittest
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

from ai_lib_qor.application.latest_pointers import refresh_library, refresh_all

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'exports/flat_library_review_rdyp0zdh/work'

@unittest.skipUnless(SOURCE.is_dir(),'需要隔离样例')
class LatestPointersTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  self.work=Path(self.tmp.name)/'work';shutil.copytree(SOURCE,self.work)
  self.lib=self.work/'libraries/SRAM22/sram22_256x16m8w8'
 def read(self,name):return json.loads((self.lib/name).read_text())
 def test_unknown_order_is_not_fabricated_and_effective_is_separate(self):
  with patch('os.walk',side_effect=AssertionError('不得扫描来源')):
   refresh_library(self.work,'SRAM22','sram22_256x16m8w8')
  self.assertFalse((self.lib/'latest_delivery.json').exists())
  self.assertTrue((self.lib/'latest_effective.json').is_symlink())
  self.assertEqual(os.readlink(self.lib/'latest_effective.json'),'effective_sram22_256x16m8w8_002.json')
 def test_unrelated_library_corruption_does_not_block_pointer(self):
  p=self.work/'libraries/IHP/sg13g2_stdcell/delivery_001.json';p.write_text('{invalid')
  refresh_library(self.work,'SRAM22','sram22_256x16m8w8')
  self.assertFalse((self.lib/'latest_delivery.json').exists())
 def test_confirmed_date_rule_and_new_empty_libraries(self):
  config=json.loads((self.work/'scan_sources.json').read_text())
  for s in config['sources']:
   if (s['vendor_id'],s['source_library_id'])==('SRAM22','sram22_256x16m8w8'):s['order_rule']={'type':'VERSION_DATE_PREFIX','confirmed':True}
  (self.work/'scan_sources.json').write_text(json.dumps(config))
  refresh_all(self.work)
  self.assertTrue((self.lib/'latest_delivery.json').is_symlink())
  self.assertEqual(os.readlink(self.lib/'latest_delivery.json'),'delivery_005.json')
  empty=self.work/'libraries/IHP/sg13g2_stdcell/latest_effective.json'
  self.assertFalse(empty.exists())
 def test_stale_index_is_not_advertised(self):
  refresh_library(self.work,'SRAM22','sram22_256x16m8w8')
  self.assertTrue((self.lib/'latest_effective.json').is_symlink())
  p=self.lib/'effective_sram22_256x16m8w8_index.json';idx=json.loads(p.read_text());idx['latest_calculated_revision']='rev_0001';p.write_text(json.dumps(idx))
  refresh_library(self.work,'SRAM22','sram22_256x16m8w8')
  self.assertFalse((self.lib/'latest_effective.json').exists())
 def test_unknown_regular_file_is_not_overwritten(self):
  p=self.lib/'latest_delivery.json';p.write_text('{"my_data":"keep"}')
  with self.assertRaises(ValueError):refresh_library(self.work,'SRAM22','sram22_256x16m8w8')
  self.assertEqual(p.read_text(),'{"my_data":"keep"}')
 def test_formal_latest_refuses_forked_snapshot_history(self):
  refresh_library(self.work,'SRAM22','sram22_256x16m8w8')
  link=self.lib/'latest_formal_NL2.5.3.json'
  self.assertTrue(link.is_symlink())
  source=self.lib/'formal_NL2.5.3_001.json';base=json.loads(source.read_text())
  for n in (2,3):
   child=dict(base,formal_snapshot_id=f'snap_fork_{n}',previous_snapshot_id=base['formal_snapshot_id'])
   (self.lib/f'formal_NL2.5.3_{n:03d}.json').write_text(json.dumps(child))
  result=refresh_library(self.work,'SRAM22','sram22_256x16m8w8')
  self.assertEqual(result['formal']['NL2.5.3']['status'],'UNAVAILABLE')
  self.assertFalse(link.is_symlink());self.assertTrue(source.is_file())
 def test_version_rebuild_creates_pointers(self):
  from ai_lib_qor.versions.service import run_version
  run_version('rebuild-index',effective_dir=self.lib/'effective_sram22_256x16m8w8')
  self.assertEqual(os.readlink(self.lib/'latest_effective.json'),'effective_sram22_256x16m8w8_002.json')
  self.assertFalse((self.lib/'latest_delivery.json').exists())
 def test_v2_history_and_index_are_validated(self):
  v2=ROOT/'exports/effective_history_migration_20261118'
  for path in v2.glob('effective_*_00[12].json'):shutil.copy2(path,self.lib/path.name)
  refresh_library(self.work,'SRAM22','sram22_256x16m8w8')
  self.assertEqual(os.readlink(self.lib/'latest_effective.json'),'effective_sram22_256x16m8w8_002.json')
 def test_v2_history_without_index_still_has_latest_pointer(self):
  v2=ROOT/'exports/effective_history_migration_20261118'
  for path in v2.glob('effective_*_00[12].json'):shutil.copy2(path,self.lib/path.name)
  (self.lib/'effective_sram22_256x16m8w8_index.json').unlink()
  refresh_library(self.work,'SRAM22','sram22_256x16m8w8')
  self.assertEqual(os.readlink(self.lib/'latest_effective.json'),'effective_sram22_256x16m8w8_002.json')
 def test_cli_rebuilds_without_source_scan(self):
  proc=subprocess.run([sys.executable,'-m','ai_lib_qor','latest-refresh','--work',str(self.work)],
                      text=True,capture_output=True,env=os.environ.copy())
  self.assertEqual(proc.returncode,0,proc.stderr)
  self.assertEqual(len(json.loads(proc.stdout)['libraries']),5)
 def test_v2_build_with_work_updates_effective_pointer(self):
  from ai_lib_qor.application.data_query import LibraryDataQuery
  from ai_lib_qor.application.simple_sources import simple_raw
  q=LibraryDataQuery(self.work,self.work/'runs')
  raw=simple_raw(q,'SRAM22','sram22_256x16m8w8','20261024_de0a9a7')
  source=self.work.parent/'raw.json';source.write_text(json.dumps(raw))
  out=self.lib/'effective_newset_001.json'
  proc=subprocess.run([sys.executable,'-m','ai_lib_qor','effective-build','--raw',str(source),'--out',str(out),
    '--work',str(self.work),'--owner-type','SOURCE_LIBRARY','--owner-id','sram22_256x16m8w8','--revision','rev_0001','--view','LEF'],
    text=True,capture_output=True,env=os.environ.copy())
  self.assertEqual(proc.returncode,0,proc.stderr)
  self.assertFalse((self.lib/'latest_effective.json').exists())
  self.assertEqual(os.readlink(self.lib/'latest_effective_newset.json'),'effective_newset_001.json')
  self.assertEqual(os.readlink(self.lib/'latest_effective_sram22_256x16m8w8.json'),'effective_sram22_256x16m8w8_002.json')
 def test_v2_initial_publish_rejects_existing_orphan_index(self):
  from ai_lib_qor.application.data_query import LibraryDataQuery
  from ai_lib_qor.application.simple_sources import simple_raw
  q=LibraryDataQuery(self.work,self.work/'runs');raw=simple_raw(q,'SRAM22','sram22_256x16m8w8','20261024_de0a9a7')
  source=self.work.parent/'raw.json';source.write_text(json.dumps(raw));out=self.lib/'effective_newset_001.json'
  index=self.lib/'effective_newset_index.json';index.write_text('{}')
  proc=subprocess.run([sys.executable,'-m','ai_lib_qor','effective-build','--raw',str(source),'--out',str(out),'--work',str(self.work),
    '--owner-type','SOURCE_LIBRARY','--owner-id','sram22_256x16m8w8','--revision','rev_0001','--view','LEF'],
    text=True,capture_output=True,env=os.environ.copy())
  self.assertNotEqual(proc.returncode,0);self.assertEqual(index.read_text(),'{}');self.assertFalse(out.exists())
 def test_v2_new_revision_updates_relative_link(self):
  from ai_lib_qor.application.data_query import LibraryDataQuery
  from ai_lib_qor.application.simple_sources import simple_raw
  q=LibraryDataQuery(self.work,self.work/'runs')
  raw1=simple_raw(q,'SRAM22','sram22_256x16m8w8','20260506_75cbe961')
  raw2=simple_raw(q,'SRAM22','sram22_256x16m8w8','20261024_de0a9a7')
  p1=self.work.parent/'v1.json';p2=self.work.parent/'v2.json';p1.write_text(json.dumps(raw1));p2.write_text(json.dumps(raw2))
  out1=self.lib/'effective_newset_001.json';out2=self.lib/'effective_newset_002.json'
  def publish(raw,out,revision,parent=None):
   args=[sys.executable,'-m','ai_lib_qor','effective-build','--raw',str(raw),'--out',str(out),'--work',str(self.work),
         '--owner-type','SOURCE_LIBRARY','--owner-id','sram22_256x16m8w8','--revision',revision,'--view','LEF']
   if parent:args+=['--parent',str(parent)]
   p=subprocess.run(args,text=True,capture_output=True,env=os.environ.copy());self.assertEqual(p.returncode,0,p.stderr)
  publish(p1,out1,'rev_0001');self.assertEqual(os.readlink(self.lib/'latest_effective_newset.json'),out1.name)
  publish(p2,out2,'rev_0002',out1);self.assertEqual(os.readlink(self.lib/'latest_effective_newset.json'),out2.name)

class LatestAutoIngestTests(unittest.TestCase):
 def test_successful_scan_updates_both_pointers(self):
  from ai_lib_qor.application.scans import run_scan_and_ingest
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);work=root/'work';work.mkdir();raw=root/'raw';p=raw/'V07/core.lef';p.parent.mkdir(parents=True);p.write_text('LEF')
   source={'vendor_id':'V','source_library_id':'L','root':str(raw),'version_paths':{'V07':'V07'},'delivery_orders':{'V07':7}}
   run_scan_and_ingest(root/'runs',work,source)
   folder=work/'libraries/V/L'
   self.assertEqual(os.readlink(folder/'latest_delivery.json'),'delivery_001.json')
   self.assertFalse((folder/'latest_effective.json').exists())
 def test_failed_scan_still_creates_empty_pointers(self):
  from ai_lib_qor.application.scans import run_scan_and_ingest
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);work=root/'work';work.mkdir();source={'vendor_id':'V','source_library_id':'L','root':str(root/'missing')}
   result=run_scan_and_ingest(root/'runs',work,source)
   self.assertEqual(result['status'],'FAILED')
   folder=work/'libraries/V/L'
   self.assertFalse((folder/'latest_delivery.json').exists())
   self.assertFalse((folder/'latest_effective.json').exists())
 def test_manual_registration_creates_pointers_and_confirmation_evidence(self):
  from ai_lib_qor.sources.registration import register_delivery
  from ai_lib_qor.sources.update_scan import scan_library
  from ai_lib_qor.application.source_repository import SourceRepository
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);work=root/'work';work.mkdir();raw=root/'raw';p=raw/'V07/core.lef';p.parent.mkdir(parents=True);p.write_text('LEF')
   source={'vendor_id':'V','source_library_id':'L','root':str(raw)}
   scan=scan_library(raw,'V','L',metadata_only=True)
   register_delivery(work,source,scan,'V07',{'delivery_id':'d7','supplier_version':'V07','delivery_order':7,'package_mode':'FULL'},
                     {'core.lef':{'file_key':'L:lef:core','view':'LEF','corner':None,'mode':None}})
   folder=work/'libraries/V/L';self.assertEqual(os.readlink(folder/'latest_delivery.json'),'delivery_001.json')
   item=SourceRepository(work).deliveries()[0];self.assertEqual(item['files'][0]['identity_status'],'CONFIRMED')
