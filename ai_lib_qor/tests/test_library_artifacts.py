import json
import tempfile
import unittest
from pathlib import Path
from test_v3_index_check_flow import make_fixture
from ai_lib_qor.application.v3_checks import run_v3_revision, run_v3_ip


class LibraryArtifactsTests(unittest.TestCase):
 def setUp(self):
  self.t=tempfile.TemporaryDirectory();self.addCleanup(self.t.cleanup);self.root=Path(self.t.name)
  self.work,self.profile=make_fixture(self.root);self.runs=self.root/'runs';self.library=self.work/'libraries/v/lib'
 def test_single_revision_writes_flat_library_artifacts(self):
  result=run_v3_revision(self.work,self.runs,vendor='v',library='lib',set_id='core_ip',revision='rev_0003',profile=self.profile)
  self.assertEqual(result['state'],'SUCCEEDED',result.get('error'));ident=result['id']
  for path in (f'check_{ident}.json',f'report_{ident}.xlsx',f'report_{ident}.html'):
   self.assertTrue((self.library/path).is_file(),path)
  self.assertFalse((self.runs/ident).exists());self.assertTrue((self.library/'runs.jsonl').is_file())
  events=[json.loads(line) for line in (self.library/'runs.jsonl').read_text().splitlines()]
  self.assertTrue(any(e.get('id')==ident and e.get('state')=='SUCCEEDED' for e in events))
  record=next(e for e in events if e.get('id')==ident and e.get('state')=='SUCCEEDED')
  self.assertEqual({row['view'] for row in record['execution_snapshot']['target_files']},{'LEF','LIBERTY'})
  self.assertTrue(all(row['delivery_id'] and row['file_id'] for row in record['execution_snapshot']['target_files']))
  self.assertEqual(record['execution_snapshot']['baseline_revision'],'rev_0002')
  self.assertFalse(list(self.library.glob('input_plan*.json')))
 def test_ip_batch_and_web_artifact_access(self):
  from ai_lib_qor.workbench.app import create_app
  result=run_v3_ip(self.work,self.runs,vendor='v',library='lib',set_id='core_ip',profile=self.profile)
  self.assertEqual(result['state'],'SUCCEEDED',result.get('error'));ident=result['id']
  self.assertTrue((self.library/f'overall_{ident}.xlsx').exists())
  self.assertFalse((self.runs/ident).exists())
  for child in result['children']:self.assertTrue((self.library/f"check_{child['id']}.json").is_file())
  plans=self.root/'plans';plans.mkdir();client=create_app(plans,self.runs,self.work).test_client()
  self.assertEqual(client.get('/runs/'+ident).status_code,200)
  response=client.get('/runs/'+ident+'/artifacts/overall.xlsx');self.assertEqual(response.status_code,200);response.close()
  child=result['children'][1]['id'];response=client.get('/runs/'+child+'/artifacts/check.json');self.assertEqual(response.status_code,200);response.close()
  self.assertEqual(client.get('/runs/'+child+'/artifacts/../../scan_sources.json').status_code,404)
 def test_existing_legacy_run_remains_readable(self):
  from ai_lib_qor.workbench.app import create_app
  import uuid
  ident='run_'+uuid.uuid4().hex;folder=self.runs/ident;folder.mkdir()
  (folder/'status.json').write_text(json.dumps({'id':ident,'state':'SUCCEEDED','plan':'legacy','started_at':'2026-01-01'}))
  (folder/'report.html').write_text('<html>legacy</html>')
  plans=self.root/'plans';plans.mkdir();client=create_app(plans,self.runs,self.work).test_client()
  self.assertEqual(client.get('/runs/'+ident).status_code,200)
  response=client.get('/runs/'+ident+'/preview/report.html');self.assertEqual(response.status_code,200);response.close()
 def test_duplicate_run_id_cannot_overwrite_prior_outputs(self):
  from unittest.mock import patch
  from uuid import UUID
  fixed=UUID('11111111-1111-4111-8111-111111111111')
  with patch('ai_lib_qor.application.v3_checks.uuid.uuid4',return_value=fixed):
   first=run_v3_revision(self.work,self.runs,vendor='v',library='lib',set_id='core_ip',revision='rev_0002',profile=self.profile)
   self.assertEqual(first['state'],'SUCCEEDED')
   report=self.library/f"report_{first['id']}.xlsx";before=report.read_bytes()
   with self.assertRaisesRegex(ValueError,'运行 ID 已存在'):
    run_v3_revision(self.work,self.runs,vendor='v',library='lib',set_id='core_ip',revision='rev_0002',profile=self.profile)
   self.assertEqual(report.read_bytes(),before)
