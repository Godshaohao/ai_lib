import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ai_lib_qor.sources.root_inventory import build_from_roots
from ai_lib_qor.application.minimal_effective import initialize_from_formal


class PathWorkbenchTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);root=Path(self.tmp.name)
  self.root=root;self.work=root/'work';self.raw=root/'raw';self.nl=root/'NL1';self.nl.mkdir();(root/'plans').mkdir()
  p=self.raw/'v/lib/20261001_abcdef12/LEF/a.lef';p.parent.mkdir(parents=True);p.write_text('MACRO A\n SIZE 2 BY 3 ;\n PIN IN\n DIRECTION INPUT ;\n END IN\nEND A\n')
  (self.nl/'a.lef').symlink_to(p)
  build_from_roots(self.raw,self.nl,self.work)
  folder=self.work/'libraries/v/lib';initialize_from_formal(self.work,'v','lib',next(folder.glob('formal_NL1_*.json')))
  from ai_lib_qor.workbench.app import create_app
  self.app=create_app(root/'plans',root/'runs',self.work);self.client=self.app.test_client()
  self.client.get('/')
  with self.client.session_transaction() as sess:self.csrf=sess['csrf']

 def test_three_levels_follow_real_saved_path_records(self):
  first=self.client.get('/');self.assertEqual(first.status_code,200);self.assertIn('来源总览',first.get_data(as_text=True));self.assertIn('v',first.get_data(as_text=True))
  second=self.client.get('/path/library',query_string={'vendor':'v','library':'lib'})
  self.assertEqual(second.status_code,200);self.assertIn('rev_0001',second.get_data(as_text=True))
  third=self.client.get('/path/index',query_string={'vendor':'v','library':'lib','view':'LEF'})
  self.assertEqual(third.status_code,200);self.assertIn('LEF/a.lef',third.get_data(as_text=True));self.assertIn('20261001_abcdef12',third.get_data(as_text=True))

 def test_index_only_update_is_shared_and_no_scan(self):
  with patch('os.walk',side_effect=AssertionError('不扫描')):
   response=self.client.post('/path/update',data={'csrf':self.csrf,'index':'1'},follow_redirects=True)
  self.assertEqual(response.status_code,200);self.assertIn('索引',response.get_data(as_text=True))
  self.assertEqual(self.client.post('/path/update',data={'csrf':'wrong','index':'1'}).status_code,403)

 def test_selected_update_options_are_saved(self):
  response=self.client.post('/path/update',data={'csrf':self.csrf,'index':'1','save_settings':'1'},follow_redirects=True)
  self.assertEqual(response.status_code,200)
  cfg=json.loads((self.work/'path_sources.json').read_text())
  self.assertFalse(cfg['update_raw']);self.assertFalse(cfg['update_formal']);self.assertTrue(cfg['update_index'])

 def test_check_and_fact_artifacts_available(self):
  response=self.client.post('/path/check',data={'csrf':self.csrf,'vendor':'v','library':'lib','revision':'rev_0001'},follow_redirects=True)
  self.assertEqual(response.status_code,200);self.assertIn('检查部分完成',response.get_data(as_text=True))
  folder=self.work/'libraries/v/lib';report=next(folder.glob('report_run_*.xlsx'))
  download=self.client.get('/path/artifact',query_string={'vendor':'v','library':'lib','name':report.name})
  self.assertEqual(download.status_code,200);download.close()
  response=self.client.post('/path/facts',data={'csrf':self.csrf,'vendor':'v','library':'lib','view':'LEF','path':'LEF/a.lef','version':'20261001_abcdef12'},follow_redirects=True)
  self.assertEqual(response.status_code,200);self.assertIn('下载 JSON',response.get_data(as_text=True))

 def test_stale_index_not_displayed_and_invalid_scope_rejected(self):
  folder=self.work/'libraries/v/lib';p=next(folder.glob('delivery_*.json'));item=json.loads(p.read_text());item['views']['LEF']=[];p.write_text(json.dumps(item))
  response=self.client.get('/path/index',query_string={'vendor':'v','library':'lib'})
  self.assertEqual(response.status_code,200);self.assertIn('索引不可用',response.get_data(as_text=True))
  self.assertEqual(self.client.get('/path/index',query_string={'vendor':'..','library':'lib'}).status_code,400)

 def test_file_removal_preview_and_restore_do_not_rewrite_history(self):
  folder=self.work/'libraries/v/lib';before=(folder/'effective_lib_001.json').read_bytes()
  data={'csrf':self.csrf,'vendor':'v','library':'lib','action':'remove','view':'LEF','path':'LEF/a.lef'}
  preview=self.client.post('/path/effective/preview',data=data)
  self.assertEqual(preview.status_code,200);self.assertIn('确认发布',preview.get_data(as_text=True))
  self.assertEqual((folder/'effective_lib_001.json').read_bytes(),before)
  self.assertFalse((folder/'effective_lib_002.json').exists())
  response=self.client.post('/path/effective/apply',data={'csrf':self.csrf,'vendor':'v','library':'lib'},follow_redirects=True)
  self.assertEqual(response.status_code,200);self.assertTrue((folder/'effective_lib_002.json').exists())
  preview=self.client.post('/path/effective/preview',data={'csrf':self.csrf,'vendor':'v','library':'lib','action':'restore','revision':'rev_0001'})
  self.assertIn('确认发布',preview.get_data(as_text=True))
  self.client.post('/path/effective/apply',data={'csrf':self.csrf,'vendor':'v','library':'lib'})
  self.assertEqual(json.loads((folder/'effective_lib_003.json').read_text())['views'],json.loads(before)['views'])

 def test_file_add_from_index_and_stale_preview_is_rejected(self):
  folder=self.work/'libraries/v/lib'
  p=self.raw/'v/lib/20261002_abcdef12/LEF/b.lef';p.parent.mkdir(parents=True);p.write_text('MACRO B\n END B\n')
  build_from_roots(self.raw,self.nl,self.work)
  data={'csrf':self.csrf,'vendor':'v','library':'lib','action':'set','view':'LEF','path':'LEF/b.lef','version':'20261002_abcdef12'}
  response=self.client.post('/path/effective/preview',data=data)
  self.assertEqual(response.status_code,200);self.assertIn('确认发布',response.get_data(as_text=True))
  from ai_lib_qor.application.minimal_effective import update_effective
  update_effective(self.work,'v','lib',{'set':[],'remove':[{'view':'LEF','path':'LEF/a.lef'}]})
  response=self.client.post('/path/effective/apply',data={'csrf':self.csrf,'vendor':'v','library':'lib'},follow_redirects=True)
  self.assertIn('父版本',response.get_data(as_text=True));self.assertFalse((folder/'effective_lib_003.json').exists())

 def test_restore_preview_warns_when_source_is_excluded_or_missing(self):
  from ai_lib_qor.application.path_config import set_version_excluded
  from ai_lib_qor.application.minimal_effective import update_effective
  update_effective(self.work,'v','lib',{'set':[],'remove':[{'view':'LEF','path':'LEF/a.lef'}]})
  set_version_excluded(self.work,'v','lib','20261001_abcdef12',True)
  (self.raw/'v/lib/20261001_abcdef12/LEF/a.lef').unlink()
  preview=self.client.post('/path/effective/preview',data={'csrf':self.csrf,'vendor':'v','library':'lib','action':'restore','revision':'rev_0001'})
  self.assertEqual(preview.status_code,200)
  self.assertIn('已排除来源',preview.get_data(as_text=True));self.assertIn('来源文件不可用',preview.get_data(as_text=True))

 def test_batch_edit_preview_apply_and_audit(self):
  import csv
  p=self.raw/'v/lib/20261002_abcdef12/LEF/b.lef';p.parent.mkdir(parents=True);p.write_text('MACRO B\nEND B\n')
  build_from_roots(self.raw,self.nl,self.work)
  selections=[json.dumps({'action':'remove','view':'LEF','path':'LEF/a.lef'}),json.dumps({'action':'set','view':'LEF','path':'LEF/b.lef','version':'20261002_abcdef12'})]
  response=self.client.post('/path/effective/preview',data={'csrf':self.csrf,'vendor':'v','library':'lib','action':'batch','selection':selections})
  self.assertEqual(response.status_code,200);body=response.get_data(as_text=True)
  self.assertIn('LEF/a.lef',body);self.assertIn('LEF/b.lef',body)
  self.client.post('/path/effective/apply',data={'csrf':self.csrf,'vendor':'v','library':'lib'})
  folder=self.work/'libraries/v/lib';row=json.loads((folder/'effective_lib_002.json').read_text())
  self.assertEqual(row['views']['LEF']['20261002_abcdef12'],['LEF/b.lef'])
  with (folder/'effective_operations.tsv').open(newline='') as stream:events=list(csv.DictReader(stream,delimiter='\t'))
  event=next(x for x in events if x['revision']=='rev_0002' and x['status']=='PUBLISHED')
  self.assertEqual(event['actor'],'web');self.assertEqual(len(json.loads(event['changes'])),2)
  response=self.client.get('/path/artifact',query_string={'vendor':'v','library':'lib','name':'effective_operations.tsv'})
  self.assertEqual(response.status_code,200);response.close()

 def test_restore_rejects_new_exclusion_after_preview(self):
  from ai_lib_qor.application.minimal_effective import update_effective
  from ai_lib_qor.application.path_config import set_version_excluded
  folder=self.work/'libraries/v/lib'
  update_effective(self.work,'v','lib',{'set':[],'remove':[{'view':'LEF','path':'LEF/a.lef'}]})
  preview=self.client.post('/path/effective/preview',data={'csrf':self.csrf,'vendor':'v','library':'lib','action':'restore','revision':'rev_0001'})
  self.assertEqual(preview.status_code,200)
  set_version_excluded(self.work,'v','lib','20261001_abcdef12',True)
  response=self.client.post('/path/effective/apply',data={'csrf':self.csrf,'vendor':'v','library':'lib'},follow_redirects=True)
  self.assertIn('来源状态已变化',response.get_data(as_text=True))
  self.assertFalse((folder/'effective_lib_003.json').exists())
