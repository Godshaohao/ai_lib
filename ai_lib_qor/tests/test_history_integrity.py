import json
import os
import tempfile
import unittest
from pathlib import Path

from ai_lib_qor.sources.root_inventory import build_from_roots


class HistoryIntegrityTests(unittest.TestCase):
 def test_unresolved_formal_links_are_preserved_and_do_not_replace_previous_snapshot(self):
  with tempfile.TemporaryDirectory() as t:
   root=Path(t);raw=root/'raw';nl=root/'NL1';nl.mkdir();work=root/'work'
   p=raw/'v/lib/20260101_a/a.lef';p.parent.mkdir(parents=True);p.write_text('x')
   (nl/'a.lef').symlink_to(p);build_from_roots(raw,nl,work)
   folder=work/'libraries/v/lib';latest=(folder/'latest_formal_NL1.json').readlink()
   (nl/'broken.lef').symlink_to('missing.lef')
   outside=root/'outside.lef';outside.write_text('x');(nl/'outside.lef').symlink_to(outside)
   result=build_from_roots(raw,nl,work)
   self.assertEqual(result['formal_observation_status'],'PARTIAL')
   self.assertEqual({x['path'] for x in result['formal_unresolved']},{'broken.lef'})
   self.assertEqual(result['formal_independent_count'],1)
   self.assertEqual(next(x for x in result['formal_unresolved'] if x['path']=='broken.lef')['target'],'missing.lef')
   self.assertEqual((folder/'latest_formal_NL1.json').readlink(),latest)
   self.assertIn('broken.lef',(work/'formal_observations.tsv').read_text())

 def test_reordering_archived_delivery_history_is_refused(self):
  from ai_lib_qor.application.minimal_file_index import refresh_index
  with tempfile.TemporaryDirectory() as t:
   root=Path(t);raw=root/'raw';work=root/'work'
   for v in ('20260101_a','20260101_b'):
    p=raw/'v/lib'/v/'a.lef';p.parent.mkdir(parents=True);p.write_text(v)
   work.mkdir();cfg={'libraries':{'v':{'lib':{'version_registration_times':{'20260101_a':'2026-02-01T01:00:00Z','20260101_b':'2026-02-01T02:00:00Z'}}}}}
   (work/'path_sources.json').write_text(json.dumps(cfg));build_from_roots(raw,None,work,update_formal=False)
   index=work/'libraries/v/lib/file_index.json';before=index.read_bytes()
   cfg['libraries']['v']['lib']['version_registration_times']={'20260101_a':'2026-02-01T02:00:00Z','20260101_b':'2026-02-01T01:00:00Z'}
   (work/'path_sources.json').write_text(json.dumps(cfg))
   with self.assertRaisesRegex(ValueError,'顺序'):refresh_index(work,'v','lib')
   self.assertEqual(before,index.read_bytes())

 def test_raw_in_place_change_raises_observation_warning_without_rewriting_delivery(self):
  with tempfile.TemporaryDirectory() as t:
   root=Path(t);raw=root/'raw';work=root/'work'
   p=raw/'v/lib/20260101_a/a.lef';p.parent.mkdir(parents=True);p.write_text('one')
   build_from_roots(raw,None,work,update_formal=False)
   delivery=next((work/'libraries/v/lib/delivery').glob('delivery_*.json'));before=delivery.read_bytes()
   p.write_text('changed in place')
   first=build_from_roots(raw,None,work,update_formal=False)
   second=build_from_roots(raw,None,work,update_formal=False)
   self.assertTrue(any('原地修改' in x for x in first['warnings']))
   self.assertTrue(any('原地修改' in x for x in second['warnings']))
   self.assertEqual(delivery.read_bytes(),before)
   from ai_lib_qor.application.minimal_facts import build_facts
   with self.assertRaisesRegex(ValueError,'观察.*变化'):
    build_facts(work,'v','lib','LEF','a.lef',version='20260101_a')

 def test_index_schema_rejects_incomplete_history_rows(self):
  from ai_lib_qor.versions.store import validate
  data={'vendor':'v','library':'lib','deliveries':[],'nl_snapshots':[],'revisions':[],
        'views':{'LEF':{'a.lef':{'raw':[{'version':'V01'}],'nl':[],'effective':[]}}}}
  with self.assertRaisesRegex(ValueError,'Schema'):validate(data,'file_index_path')

if __name__=='__main__':unittest.main()
