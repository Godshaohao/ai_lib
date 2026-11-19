import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ai_lib_qor.application.data_query import LibraryDataQuery
ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'work'
SAMPLE=ROOT/'exports/effective_v2_simulation_20261118'
VENDOR='SRAM22';LIB='sram22_256x16m8w8';SET=LIB

@unittest.skipUnless(SOURCE.is_dir() and SAMPLE.is_dir(),'本地验收样本不可用')
class UnifiedContractQueryTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  self.root=Path(self.tmp.name);self.work=self.root/'work';shutil.copytree(SOURCE,self.work,symlinks=True)
  self.folder=self.work/'libraries'/VENDOR/LIB
  for path in self.folder.glob('effective_*'):
   if path.is_file() and not path.is_symlink():path.unlink()
  for path in SAMPLE.glob('effective_*_00[12].json'):shutil.copy2(path,self.folder/path.name)
  self.q=LibraryDataQuery(self.work,self.root/'runs')
 def test_2_changed_5_inherited_and_missing_source_visible(self):
  with patch('os.walk',side_effect=AssertionError('不得遍历 RAW')):
   view=self.q.get_effective_files(VENDOR,LIB,SET,'rev_0002')
   diff=self.q.compare_revisions(VENDOR,LIB,SET,'rev_0001','rev_0002')
   pairs=self.q.get_changed_file_pairs(VENDOR,LIB,SET,'rev_0001','rev_0002')
  self.assertEqual(sum(x['change']=='SOURCE_CHANGED' for x in diff['files']),2)
  self.assertEqual(sum(x['change']=='UNCHANGED' for x in diff['files']),5)
  self.assertEqual(len(pairs['pairs']),2)
  self.assertEqual(sum(len(v) for v in view['views'].values()),7)
  self.assertTrue(all(x['before']['resolution']=='RECORDED' for x in pairs['pairs']))
  self.assertTrue(all(x['after']['resolution']=='MISSING_DELIVERY' for x in pairs['pairs']))
  self.assertTrue(all(x['content_status']=='NOT_CHECKED' for x in pairs['pairs']))
 def test_formal_and_timeline_use_same_sources_without_scan(self):
  snaps=[x for x in self.q.snapshots if x['formal_nl_id']=='NL2.5.3' and x['scope']['source_library_ids']==[LIB]]
  sid=snaps[0]['formal_snapshot_id']
  with patch('os.walk',side_effect=AssertionError('不得遍历来源')):
   rows=self.q.compare_formal_vs_effective(VENDOR,LIB,'NL2.5.3',sid,SET,'rev_0002')
   timeline=self.q.file_timeline(VENDOR,LIB,SET,'LEF','LEF/sram22_256x16m8w8.lef',['rev_0001','rev_0002'])
  lef=next(r for r in rows['files'] if r['view']=='LEF')
  self.assertEqual(lef['relation'],'DIFFERENT_SOURCE');self.assertTrue(lef['link_target'])
  self.assertEqual([x['source']['version'] for x in timeline['versions']],['20261024_de0a9a7','V06_SIMULATED'])
 def test_configured_order_works_without_evidence(self):
  for p in self.folder.glob('evidence_delivery_*.json'):p.unlink()
  cfg=json.loads((self.work/'scan_sources.json').read_text())
  for item in cfg['sources']:
   if (item['vendor_id'],item['source_library_id'])==(VENDOR,LIB):item['order_rule']={'type':'VERSION_DATE_PREFIX','confirmed':True}
  (self.work/'scan_sources.json').write_text(json.dumps(cfg))
  q=LibraryDataQuery(self.work,self.root/'runs')
  items=q.list_deliveries(VENDOR,LIB)
  self.assertEqual(items['ordering_status'],'CONFIRMED');self.assertEqual(items['deliveries'][-1]['version'],'20261024_de0a9a7')
  h=q.get_file_history(VENDOR,LIB,'LEF','LEF/sram22_256x16m8w8.lef')
  self.assertEqual(h['latest']['version'],'20261024_de0a9a7');self.assertEqual(h['previous']['version'],'20260506_75cbe961')
 def test_v2_with_published_index_is_queryable(self):
  from ai_lib_qor.versions.index_projector import project_simple
  records=[json.loads((self.folder/f'effective_{SET}_{n:03d}.json').read_text()) for n in (1,2)]
  index=project_simple(records,[],SET,'2026-01-01T00:00:00Z')
  (self.folder/f'effective_{SET}_index.json').write_text(json.dumps(index))
  q=LibraryDataQuery(self.work,self.root/'runs')
  self.assertEqual(len(q.compare_revisions(VENDOR,LIB,SET,'rev_0001','rev_0002')['files']),7)
 def test_cli_and_web_share_changed_pairs(self):
  import os,subprocess,sys
  from ai_lib_qor.workbench.app import create_app
  env={**os.environ,'PYTHONPATH':str(ROOT/'src')+os.pathsep+str(ROOT.parent/'src')+os.pathsep+os.environ.get('PYTHONPATH','')}
  args={'vendor':VENDOR,'library':LIB,'set_id':SET,'revision':'rev_0001','other_revision':'rev_0002'}
  cmd=[sys.executable,'-m','ai_lib_qor','data-query','--work',str(self.work),'--runs',str(self.root/'runs'),'--kind','changed-pairs',
       '--vendor',VENDOR,'--library',LIB,'--set-id',SET,'--revision','rev_0001','--other-revision','rev_0002']
  proc=subprocess.run(cmd,text=True,capture_output=True,env=env);self.assertEqual(proc.returncode,0,proc.stderr)
  client=create_app(ROOT/'examples/pipeline',self.root/'runs',self.work).test_client()
  response=client.get('/api/library-data',query_string={'kind':'changed-pairs',**args})
  self.assertEqual(response.status_code,200);self.assertEqual(response.get_json(),json.loads(proc.stdout))
 def test_explicit_delivery_order_without_evidence(self):
  for p in self.folder.glob('evidence_delivery_*.json'):p.unlink()
  cfg=json.loads((self.work/'scan_sources.json').read_text())
  for item in cfg['sources']:
   if (item['vendor_id'],item['source_library_id'])==(VENDOR,LIB):
    records=[x['record'] for x in self.q.deliveries if (x['record']['vendor_id'],x['record']['source_library_id'])==(VENDOR,LIB)]
    item['delivery_orders']={r['supplier_version']:r['delivery_order'] for r in records}
  (self.work/'scan_sources.json').write_text(json.dumps(cfg))
  q=LibraryDataQuery(self.work,self.root/'runs')
  self.assertEqual(q.get_file_history(VENDOR,LIB,'LEF','LEF/sram22_256x16m8w8.lef')['latest']['version'],'20261024_de0a9a7')
  from ai_lib_qor.application.latest_pointers import refresh_library
  refresh_library(self.work,VENDOR,LIB)
  self.assertEqual((self.folder/'latest_delivery.json').readlink().name,'delivery_005.json')
 def test_explicit_selected_lef_only_produces_real_file_facts(self):
  olddir=self.root/'raw_v05';newdir=self.root/'raw_v06'
  for root,size in ((olddir,120),(newdir,124)):
   path=root/'LEF/sram22_256x16m8w8.lef';path.parent.mkdir(parents=True)
   path.write_text(f'MACRO MAC_A\n SIZE {size} BY 80 ;\n PIN A\n DIRECTION INPUT ;\n END A\nEND MAC_A\n')
  oldpath=self.folder/'delivery_005.json';old=json.loads(oldpath.read_text());old['source_root']=str(olddir);oldpath.write_text(json.dumps(old))
  new=dict(old,delivery_id='delivery_006_simulated',supplier_version='V06_SIMULATED',delivery_order=6,source_root=str(newdir))
  new['files']=[f for f in old['files'] if f['relative_path'] in ('LEF/sram22_256x16m8w8.lef','LIB/NLDM/sram22_256x16m8w8_ff_n40C_1v95.lib')]
  new['package_scope']={'file_keys':[f['file_key'] for f in new['files'] if f['file_key']],'scope_confirmed':False}
  (self.folder/'delivery_006.json').write_text(json.dumps(new))
  for n,record in ((5,old),(6,new)):
   (self.folder/f'evidence_delivery_{n:03d}.json').write_text(json.dumps({'classification':{f['relative_path']:{'basis':'explicit'} for f in record['files']}}))
  q=LibraryDataQuery(self.work,self.root/'runs')
  result=q.parse_changed_file_pairs(VENDOR,LIB,SET,'rev_0001','rev_0002',views=['LEF'])
  self.assertEqual(len(result['pairs']),1);item=result['pairs'][0]
  self.assertEqual(item['status'],'PARSED')
  self.assertEqual(item['before_facts']['objects']['macros'][0]['size_um'],[120,80])
  self.assertEqual(item['after_facts']['objects']['macros'][0]['size_um'],[124,80])
  check=q.check_changed_lefs(VENDOR,LIB,SET,'rev_0001','rev_0002',run_id='run_1',ruleset_id='lef_diff',run_at='2026-01-01T00:00:00Z')
  self.assertEqual(check['status'],'CHECKED');self.assertEqual(check['result']['file_changes'][0]['content_status'],'CHANGED')
  attrs=[x['attribute'] for x in check['result']['file_changes'][0]['object_changes']];self.assertIn('SIZE',attrs)
  from ai_lib_qor.application.runs import execute_changed_lefs
  status=execute_changed_lefs(self.work,self.root/'runs',vendor=VENDOR,library=LIB,set_id=SET,before='rev_0001',after='rev_0002')
  self.assertEqual(status['state'],'SUCCEEDED',status.get('error'))
  folder=self.root/'runs'/status['id'];saved=json.loads((folder/'check.json').read_text())
  self.assertEqual(saved['file_changes'][0]['content_status'],'CHANGED')
  self.assertTrue((folder/'report.xlsx').is_file());self.assertEqual(len(list(folder.glob('facts_*.json'))),2)
  libpath='LIB/NLDM/sram22_256x16m8w8_ff_n40C_1v95.lib'
  libfile=newdir/libpath;libfile.parent.mkdir(parents=True)
  libfile.write_text('library(test) { cell(MAC_A) { pin(A) { direction : input; } } }')
  both=execute_changed_lefs(self.work,self.root/'runs',vendor=VENDOR,library=LIB,set_id=SET,before='rev_0001',after='rev_0002',pin_liberty_path=libpath)
  self.assertEqual(both['state'],'SUCCEEDED',both.get('error'))
  combined=json.loads((self.root/'runs'/both['id']/'check.json').read_text())
  self.assertEqual(combined['file_changes'][0]['content_status'],'CHANGED')
  self.assertEqual(combined['quality_checks'][0]['result'],'PASS')
  self.assertEqual(len(list((self.root/'runs'/both['id']).glob('facts_*.json'))),3)
