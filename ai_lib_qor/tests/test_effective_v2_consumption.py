import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from ai_lib_qor.application.data_query import query_data

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'exports/flat_library_review_rdyp0zdh/work/libraries/SRAM22/sram22_256x16m8w8'
MIGRATION=ROOT/'exports/effective_history_migration_20261118'

@unittest.skipUnless(SOURCE.is_dir() and MIGRATION.is_dir(),'需要模拟迁移样例')
class EffectiveV2ConsumptionTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
  self.base=Path(self.temp.name);self.work=self.base/'work';d=self.work/'libraries/SRAM22/sram22_256x16m8w8';d.mkdir(parents=True)
  for p in SOURCE.glob('delivery_*.json'):shutil.copy2(p,d/p.name)
  for p in SOURCE.glob('evidence_delivery_*.json'):shutil.copy2(p,d/p.name)
  for p in MIGRATION.glob('effective_*_00[12].json'):shutil.copy2(p,d/p.name)
  self.args={'vendor':'SRAM22','library':'sram22_256x16m8w8','set_id':'sram22_256x16m8w8','revision':'rev_0002'}
 def test_offline_shared_query_returns_recorded_paths_and_uncertainty(self):
  with patch('os.walk',side_effect=AssertionError('不能扫描 RAW')):
   result=query_data(self.work,self.base/'runs','effective-v2',**self.args)
  self.assertEqual(result['revision'],'rev_0002')
  self.assertEqual(len(result['files']),2)
  self.assertTrue(all(f['resolution']=='RECORDED' for f in result['files']))
  self.assertTrue(all(f['identity_status']=='CANDIDATE' for f in result['files']))
  self.assertTrue(all(f['content_status']=='NOT_CHECKED' for f in result['files']))
 def test_missing_delivery_is_visible_not_invented(self):
  (self.work/'libraries/SRAM22/sram22_256x16m8w8/delivery_005.json').unlink()
  result=query_data(self.work,self.base/'runs','effective-v2',**self.args)
  self.assertTrue(all(x['resolution']=='MISSING_DELIVERY' for x in result['files']))
 def test_cli_web_parity_and_reject_traversal(self):
  from ai_lib_qor.workbench.app import create_app
  env={**os.environ,'PYTHONPATH':str(ROOT/'src')+os.pathsep+str(ROOT.parent/'src')+os.pathsep+os.environ.get('PYTHONPATH','')}
  p=subprocess.run([sys.executable,'-m','ai_lib_qor','data-query','--work',str(self.work),'--runs',str(self.base/'runs'),
      '--kind','effective-v2','--vendor',self.args['vendor'],'--library',self.args['library'],
      '--set-id',self.args['set_id'],'--revision','rev_0002'],capture_output=True,text=True,env=env)
  self.assertEqual(p.returncode,0,p.stderr)
  client=create_app(ROOT/'examples/pipeline',self.base/'runs',self.work).test_client()
  response=client.get('/api/library-data',query_string={'kind':'effective-v2',**self.args})
  self.assertEqual(response.status_code,200);self.assertEqual(response.get_json(),json.loads(p.stdout))
  response=client.get('/api/library-data',query_string={'kind':'effective-v2',**self.args,'set_id':'../etc'})
  self.assertEqual(response.status_code,400)
 def test_workbench_lists_and_displays_v2_revision(self):
  from ai_lib_qor.workbench.app import create_app
  client=create_app(ROOT/'examples/pipeline',self.base/'runs',self.work).test_client()
  page=client.get('/library',query_string={'vendor':self.args['vendor'],'library':self.args['library']})
  self.assertEqual(page.status_code,200)
  self.assertIn('rev_0002',page.get_data(as_text=True))
  response=client.get('/effective-v2',query_string=self.args,follow_redirects=True)
  html=response.get_data(as_text=True)
  self.assertEqual(response.status_code,200)
  self.assertIn('20261024_de0a9a7',html);self.assertIn('未检查',html)
  self.assertIn('LEF/sram22_256x16m8w8.lef',html)
  self.assertIn('浏览目录',html);self.assertIn('供应商',html);self.assertIn('交付版本时间线',html)
  self.assertIn('rev_0001',html);self.assertIn('rev_0002',html)
  self.assertIn('data-v2-comparison',html);self.assertIn('LIB/NLDM/sram22_256x16m8w8_ff_n40C_1v95.lib',html)
  self.assertIn('暂不能检查',html);self.assertNotIn('运行单版本检查</button>',html)
 def test_unconfirmed_files_cannot_become_check_members(self):
  from ai_lib_qor.application.v2_check_adapter import load_v2_for_check
  path=self.work/'libraries/SRAM22/sram22_256x16m8w8/effective_sram22_256x16m8w8_002.json'
  with self.assertRaisesRegex(ValueError,'确认'):
   load_v2_for_check(path,self.work)
