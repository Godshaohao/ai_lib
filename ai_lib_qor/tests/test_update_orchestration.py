import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ai_lib_qor.application.minimal_file_index import _ordered
from ai_lib_qor.sources.root_inventory import build_from_roots
from ai_lib_qor.application.minimal_effective import initialize_from_formal


class UpdateOrchestrationTests(unittest.TestCase):
 def test_same_date_uses_registration_timestamps_only_to_break_ties(self):
  rows=[{'version':'20260101_a','version_date':'2026-01-01'}, {'version':'20260101_b','version_date':'2026-01-01'}]
  times={'20260101_a':'2026-03-02T09:00:00Z','20260101_b':'2026-03-01T09:00:00Z'}
  self.assertEqual([x['version'] for x in _ordered(rows,times)],['20260101_b','20260101_a'])
  with self.assertRaisesRegex(ValueError,'顺序'):_ordered(rows,{'20260101_a':times['20260101_a']})

 def test_cli_reads_saved_update_defaults_and_overrides(self):
  from ai_lib_qor.cli import parser,run
  with tempfile.TemporaryDirectory() as t:
   p=Path(t);(p/'path_sources.json').write_text(json.dumps({'update_raw':False,'update_formal':False,'update_index':True,'auto_effective':False}))
   with patch('ai_lib_qor.sources.root_inventory.build_from_roots',return_value={}) as call:
    run(parser().parse_args(['inventory-roots','--output',str(p)]))
    self.assertFalse(call.call_args.kwargs['update_raw']);self.assertFalse(call.call_args.kwargs['update_formal'])
    self.assertTrue(call.call_args.kwargs['update_index']);self.assertFalse(call.call_args.kwargs['auto_effective'])
   with patch('ai_lib_qor.sources.root_inventory.build_from_roots',return_value={}) as call:
    run(parser().parse_args(['inventory-roots','--output',str(p),'--raw','--no-index']))
    self.assertTrue(call.call_args.kwargs['update_raw']);self.assertFalse(call.call_args.kwargs['update_index'])

 def test_auto_publish_new_versions_in_order_inherit_and_exclude(self):
  from ai_lib_qor.application.path_config import set_version_excluded
  with tempfile.TemporaryDirectory() as t:
   root=Path(t);raw=root/'raw';nl=root/'NL1';nl.mkdir();work=root/'work';first='20260101_a'
   for name in ('a.lef','b.lib'):
    p=raw/'v/lib'/first/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(name);(nl/name).symlink_to(p)
   build_from_roots(raw,nl,work)
   folder=work/'libraries/v/lib';initialize_from_formal(work,'v','lib',next(folder.glob('formal/formal_NL1_*.json')))
   p=raw/'v/lib/20260102_b/a.lef';p.parent.mkdir(parents=True);p.write_text('updated')
   r=build_from_roots(raw,nl,work)
   self.assertEqual(r['effective_published'],1)
   effective=json.loads((folder/'effective/effective_lib_002.json').read_text())
   self.assertEqual(effective['views']['LEF']['20260102_b'],['a.lef'])
   self.assertEqual(effective['views']['LIBERTY'][first],['b.lib'])
   self.assertEqual(build_from_roots(raw,nl,work)['effective_published'],0)
   p=raw/'v/lib/20260103_c/a.lef';p.parent.mkdir(parents=True);p.write_text('third')
   build_from_roots(raw,nl,work,auto_effective=False)
   set_version_excluded(work,'v','lib','20260103_c',True)
   self.assertEqual(build_from_roots(raw,nl,work)['effective_published'],0)
   self.assertFalse((folder/'effective/effective_lib_003.json').exists())

 def test_pending_same_day_retries_after_registration_and_never_regresses(self):
  from ai_lib_qor.versions.store import write_atomic
  with tempfile.TemporaryDirectory() as t:
   root=Path(t);raw=root/'raw';nl=root/'NL1';nl.mkdir();work=root/'work'
   old=raw/'v/lib/20260101_a/a.lef';old.parent.mkdir(parents=True);old.write_text('old');(nl/'a.lef').symlink_to(old)
   build_from_roots(raw,nl,work);folder=work/'libraries/v/lib'
   initialize_from_formal(work,'v','lib',next(folder.glob('formal/formal_NL1_*.json')))
   newer=raw/'v/lib/20260101_b/a.lef';newer.parent.mkdir(parents=True);newer.write_text('new')
   r=build_from_roots(raw,nl,work)
   self.assertEqual(r['effective_published'],0);self.assertEqual(r['effective_pending'],1)
   write_atomic(work/'path_sources.json',{'libraries':{'v':{'lib':{'version_registration_times':{'20260101_a':'2026-02-01T10:00:00Z','20260101_b':'2026-02-01T11:00:00Z'}}}}})
   r=build_from_roots(raw,nl,work)
   self.assertEqual(r['effective_published'],1);self.assertEqual(r['effective_pending'],0)
   older=raw/'v/lib/20251231_c/a.lef';older.parent.mkdir(parents=True);older.write_text('older')
   r=build_from_roots(raw,nl,work)
   self.assertEqual(r['effective_published'],0)
   self.assertEqual((folder/'latest_effective.json').readlink().name,'effective_lib_002.json')

 def test_web_settings_are_the_cli_defaults(self):
  from ai_lib_qor.workbench.path_app import create_path_app
  from ai_lib_qor.cli import parser,run
  with tempfile.TemporaryDirectory() as t:
   work=Path(t);client=create_path_app(work).test_client();client.get('/')
   with client.session_transaction() as session:csrf=session['csrf']
   response=client.post('/path/update',data={'csrf':csrf,'index':'1','save_settings':'1'})
   self.assertEqual(response.status_code,302)
   with patch('ai_lib_qor.sources.root_inventory.build_from_roots',return_value={}) as call:
    run(parser().parse_args(['inventory-roots','--output',str(work)]))
    self.assertEqual({k:call.call_args.kwargs[k] for k in ('update_raw','update_formal','update_index','auto_effective')},
                     {'update_raw':False,'update_formal':False,'update_index':True,'auto_effective':False})

 def test_birthtime_change_is_not_misreported_as_content_change(self):
  with tempfile.TemporaryDirectory() as t:
   root=Path(t);raw=root/'raw';work=root/'work'
   p=raw/'v/lib/20260101_a/a.lef';p.parent.mkdir(parents=True);p.write_text('x')
   with patch('ai_lib_qor.sources.root_inventory.directory_birthtime',return_value=None):
    build_from_roots(raw,None,work,update_formal=False)
   with patch('ai_lib_qor.sources.root_inventory.directory_birthtime',return_value='2026-01-01T00:00:00Z'):
    result=build_from_roots(raw,None,work,update_formal=False)
   self.assertTrue(any('目录创建时间' in x for x in result['warnings']))
   self.assertFalse(any('内容发生变化' in x for x in result['warnings']))

 def test_retry_repairs_pointer_if_publish_was_interrupted(self):
  from ai_lib_qor.sources.root_inventory import update_pointer
  with tempfile.TemporaryDirectory() as t:
   root=Path(t);raw=root/'raw';nl=root/'NL1';nl.mkdir();work=root/'work'
   p=raw/'v/lib/20260101_a/a.lef';p.parent.mkdir(parents=True);p.write_text('one');(nl/'a.lef').symlink_to(p)
   build_from_roots(raw,nl,work);folder=work/'libraries/v/lib';initialize_from_formal(work,'v','lib',next(folder.glob('formal/formal_NL1_*.json')))
   p=raw/'v/lib/20260102_b/a.lef';p.parent.mkdir(parents=True);p.write_text('two')
   def fail(folder,name,target):
    if name=='latest_effective.json':raise OSError('simulated crash')
    return update_pointer(folder,name,target)
   with patch('ai_lib_qor.application.minimal_effective.update_pointer',side_effect=fail):
    r=build_from_roots(raw,nl,work)
   self.assertEqual(r['effective_pending'],1)
   self.assertEqual((folder/'latest_effective.json').readlink().name,'effective_lib_001.json')
   self.assertTrue((folder/'effective/effective_lib_002.json').is_file())
   self.assertEqual(build_from_roots(raw,nl,work)['effective_pending'],0)
   self.assertEqual((folder/'latest_effective.json').readlink().name,'effective_lib_002.json')
   import csv
   with (folder/'log/effective_operations.tsv').open(newline='') as stream:events=list(csv.DictReader(stream,delimiter='\t'))
   self.assertTrue(any(x['revision']=='rev_0002' and x['status']=='RECOVERED' for x in events))

if __name__=='__main__':unittest.main()
