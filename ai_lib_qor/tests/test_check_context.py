import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from test_v3_index_check_flow import make_fixture
from ai_lib_qor.application.data_query import LibraryDataQuery, query_data


class CheckContextTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
  self.work,_=make_fixture(self.root);self.q=LibraryDataQuery(self.work,self.root/'runs')
 def test_context_has_complete_target_baseline_and_source_only_changes(self):
  ctx=self.q.get_check_context('v','lib','core_ip','rev_0003')
  self.assertEqual(ctx['target']['revision'],'rev_0003')
  self.assertEqual(ctx['target']['parent'],'rev_0002')
  self.assertEqual(len(ctx['selected_files']),2);self.assertEqual(len(ctx['baseline_files']),2)
  self.assertTrue(any(x['change']=='SOURCE_CHANGED' for x in ctx['source_changes']))
  self.assertTrue(all(x['content_status']=='NOT_CHECKED' for x in ctx['source_changes']))
  self.assertEqual(ctx['provenance']['status'],'VALID')
  self.assertTrue(any(x.get('link_target') for x in ctx['formal_refs']))
 def test_query_returns_verified_published_index_not_rebuild_twice(self):
  import ai_lib_qor.application.file_index_v3 as m
  original=m.build_library_index
  with patch.object(m,'build_library_index',wraps=original) as builder:
   value=query_data(self.work,self.root/'runs','index-v3',vendor='v',library='lib')
   self.assertEqual(value['index_status'],'VALID');self.assertEqual(value['index']['schema'],'file_index.v3')
   self.assertEqual(builder.call_count,1)
 def test_stale_index_cannot_prepare_check_context(self):
  (self.work/'libraries/v/lib/file_index.json').unlink()
  with self.assertRaisesRegex(ValueError,'索引'):
   self.q.get_check_context('v','lib','core_ip','rev_0003')

 def test_context_does_not_parse_files(self):
  with patch('ai_lib_qor.facts.parsers.parse_delivery_file',side_effect=AssertionError('上下文不应解析文件')):
   value=query_data(self.work,self.root/'runs','check-context',vendor='v',library='lib',set_id='core_ip',revision='rev_0003')
  self.assertEqual(len(value['selected_files']),2)
  self.assertTrue(all(item['delivery_id'] and item['file_id'] for item in value['selected_files']))

 def test_unobserved_source_is_not_reused_across_runs(self):
  import ai_lib_qor.application.v3_checks as checks
  index=self.q.published_v3_index('v','lib')
  source=checks._source(self.q,index,'core_ip','rev_0003','LEF','lef/core.lef')
  source['file']['observation']={}
  folder=self.work/'libraries/v/lib';original=checks.parse_delivery_file
  with patch.object(checks,'parse_delivery_file',wraps=original) as parser:
   for _ in range(2):checks._fact(source,{}, {'parsed':0,'reused':0,'unverified':0},folder)
  self.assertEqual(parser.call_count,2)

 def test_facts_reused_between_runs_and_change_rejected(self):
  from ai_lib_qor.application.v3_checks import run_v3_revision
  from unittest.mock import patch
  import ai_lib_qor.application.v3_checks as checks
  profile={'pin_pairs':[{'lef_path':'lef/core.lef','liberty_path':'lib/core.lib'}]}
  first=run_v3_revision(self.work,self.root/'runs',vendor='v',library='lib',set_id='core_ip',revision='rev_0003',profile=profile)
  self.assertEqual(first['state'],'SUCCEEDED',first.get('error'))
  self.assertTrue(list((self.work/'libraries/v/lib').glob('facts_*.json')))
  with patch.object(checks,'parse_delivery_file',side_effect=AssertionError('应该复用已验证的解析结果')):
   second=run_v3_revision(self.work,self.root/'runs',vendor='v',library='lib',set_id='core_ip',revision='rev_0003',profile=profile)
  self.assertEqual(second['state'],'SUCCEEDED',second.get('error'))
  (self.root/'raw/V03/lib/core.lib').write_text('changed')
  third=run_v3_revision(self.work,self.root/'runs',vendor='v',library='lib',set_id='core_ip',revision='rev_0003',profile=profile)
  self.assertEqual(third['state'],'FAILED');self.assertIn('不一致',third['error'])

 def test_archive_change_during_check_rejects_result(self):
  from ai_lib_qor.application.v3_checks import run_v3_revision
  from unittest.mock import patch
  import ai_lib_qor.application.v3_checks as checks
  original=checks._fact;changed=[]
  def mutate(*args,**kwargs):
   result=original(*args,**kwargs)
   if not changed:
    path=self.work/'libraries/v/lib/delivery_003.json'
    path.write_text(path.read_text()+'\n');changed.append(True)
   return result
  profile={'pin_pairs':[{'lef_path':'lef/core.lef','liberty_path':'lib/core.lib'}]}
  with patch.object(checks,'_fact',side_effect=mutate):
   result=run_v3_revision(self.work,self.root/'runs',vendor='v',library='lib',set_id='core_ip',revision='rev_0003',profile=profile)
  self.assertEqual(result['state'],'FAILED');self.assertIn('归档',result['error'])
  self.assertFalse((self.work/'libraries/v/lib'/f"check_{result['id']}.json").exists())

 def test_long_lived_query_does_not_keep_valid_status_after_archive_change(self):
  self.assertEqual(self.q.file_index_status('v','lib')['status'],'VALID')
  archive=self.work/'libraries/v/lib/delivery_003.json'
  archive.write_text(archive.read_text()+'\n')
  self.assertNotEqual(self.q.file_index_status('v','lib')['status'],'VALID')
  with self.assertRaisesRegex(ValueError,'索引'):self.q.get_check_context('v','lib','core_ip','rev_0003')
