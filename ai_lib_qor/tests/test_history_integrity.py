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
   self.assertEqual({x['path'] for x in result['formal_unresolved']},{'broken.lef','outside.lef'})
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

 def test_migrate_true_v1_delivery_and_v2_effective(self):
  from ai_lib_qor.sources.delivery_builder import build_delivery
  from ai_lib_qor.application.effective_json import create_revision
  from ai_lib_qor.application.path_migration import migrate_legacy_library
  with tempfile.TemporaryDirectory() as t:
   root=Path(t);source=root/'old';folder=source/'libraries/v/lib';folder.mkdir(parents=True)
   raw=root/'raw/20260101_a';p=raw/'LEF/a.lef';p.parent.mkdir(parents=True);p.write_text('LEF')
   metadata={'delivery_id':'old1','vendor_id':'v','source_library_id':'lib','supplier_version':'20260101_a','delivery_order':1,'received_at':'2026-01-01T00:00:00Z','package_mode':'UNKNOWN'}
   record=build_delivery(raw,metadata,{'LEF/a.lef':{'file_key':'a','view':'LEF'}})
   (folder/'delivery_001.json').write_text(json.dumps(record))
   raw_simple={'schema':'raw.simple.v1','delivery_id':'old1','context':{'vendor':'v','library':'lib','version':'20260101_a','root':str(raw)},'views':{'LEF':['LEF/a.lef']}}
   eff=create_revision(raw_simple,owner={'type':'SOURCE_LIBRARY','id':'lib'},revision='rev_0001',created_at='2026-01-01T01:00:00Z',include_views=['LEF'])
   (folder/'effective_lib_001.json').write_text(json.dumps(eff))
   raw2=root/'raw/20260102_b';p2=raw2/'LEF/a.lef';p2.parent.mkdir(parents=True);p2.write_text('LEF2')
   metadata2={**metadata,'delivery_id':'old2','supplier_version':'20260102_b','delivery_order':2}
   record2=build_delivery(raw2,metadata2,{'LEF/a.lef':{'file_key':'a','view':'LEF'}})
   (folder/'delivery_002.json').write_text(json.dumps(record2))
   raw_simple2={**raw_simple,'delivery_id':'old2','context':{**raw_simple['context'],'version':'20260102_b','root':str(raw2)}}
   eff2=create_revision(raw_simple2,owner={'type':'SOURCE_LIBRARY','id':'lib'},revision='rev_0002',created_at='2026-01-02T01:00:00Z',include_views=['LEF'],parent=eff)
   (folder/'effective_lib_002.json').write_text(json.dumps(eff2))
   dest=root/'new';migrate_legacy_library(source,dest,'v','lib')
   out=json.loads((dest/'libraries/v/lib/effective_lib_001.json').read_text())
   self.assertEqual(out['views'],{'LEF':{'20260101_a':['LEF/a.lef']}})
   out2=json.loads((dest/'libraries/v/lib/effective_lib_002.json').read_text())
   self.assertEqual(out2['views'],{'LEF':{'20260102_b':['LEF/a.lef']}})
   self.assertEqual(json.loads((folder/'delivery_001.json').read_text()),record)
   event={'schema_version':'acceptance_event.v1','event_id':'e1','effective_set_id':'lib','action':'ACCEPT','revision_id':'rev_0001','acted_at':'2026-01-01T02:00:00Z','actor':'test','reason':'verified'}
   (folder/'effective_lib_acceptance.jsonl').write_text(json.dumps(event)+'\n')
   migrated=migrate_legacy_library(source,root/'another','v','lib')
   self.assertEqual(migrated['legacy_accepted_revision'],'rev_0001')
   self.assertTrue(migrated['warnings'])
   self.assertIn('rev_0001',(root/'another/libraries/v/lib/legacy_acceptance.tsv').read_text())

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

 def test_unmatched_formal_is_migrated_and_index_differences_reported(self):
  from ai_lib_qor.sources.delivery_builder import build_delivery
  from ai_lib_qor.application.path_migration import migrate_legacy_library
  with tempfile.TemporaryDirectory() as t:
   root=Path(t);old=root/'old';folder=old/'libraries/v/lib';folder.mkdir(parents=True)
   raw=root/'raw/20260101_a';f=raw/'a.lef';f.parent.mkdir(parents=True);f.write_text('x')
   meta={'delivery_id':'d1','vendor_id':'v','source_library_id':'lib','supplier_version':'20260101_a','delivery_order':1,'received_at':'2026-01-01T00:00:00Z','package_mode':'UNKNOWN'}
   record=build_delivery(raw,meta,{'a.lef':{'file_key':'a','view':'LEF'}});(folder/'delivery_001.json').write_text(json.dumps(record))
   formal={'formal_nl_id':'NL1','observed_at':'2026-01-01T00:00:00Z','source_root':str(root/'nl'), 'linked_files':[{'link_path':'x.lef','link_target':'../missing.lef','resolved_path':str(root/'missing.lef')}]}
   (folder/'formal_NL1_001.json').write_text(json.dumps(formal))
   idx={'schema':'file_index.v3','scope':{'vendor':'v','library':'lib'},'deliveries':[{'delivery_id':'d1','version':'20260101_a','root':str(raw)}], 'formal_nl':{},'effective_sets':{},'views':{'LEF':{'files':{'a.lef':{'raw':[{'delivery_id':'d1','file_id':record['files'][0]['file_id']}]}}}}}
   (folder/'file_index.json').write_text(json.dumps(idx))
   result=migrate_legacy_library(old,root/'new','v','lib');out=Path(result['path'])
   self.assertEqual(result['formal_unresolved'],1)
   self.assertIn('../missing.lef',(out/'formal_observations.tsv').read_text())
   self.assertTrue((out/'file_index_reconciliation.tsv').is_file())
   self.assertEqual(result['index_reconciliation']['missing'],0)
   self.assertIn('delivery',(out/'file_index_reconciliation.tsv').read_text())
   idx['deliveries'][0]['root']=str(root/'wrong-root')
   (folder/'file_index.json').write_text(json.dumps(idx))
   mismatch=migrate_legacy_library(old,root/'wrong','v','lib')
   self.assertGreater(mismatch['index_reconciliation']['missing'],0)
   idx['deliveries'][0]['root']=str(raw)
   idx['views']['LEF']['files']['a.lef']['raw'].append({'delivery_id':'missing','file_id':'bad'})
   (folder/'file_index.json').write_text(json.dumps(idx))
   result=migrate_legacy_library(old,root/'other','v','lib')
   self.assertEqual(result['index_reconciliation']['unresolved'],1)
   self.assertIn('UNRESOLVED',(Path(result['path'])/'file_index_reconciliation.tsv').read_text())

 def test_index_order_discrepancy_is_reported(self):
  from ai_lib_qor.application.path_migration import _reconcile_index
  with tempfile.TemporaryDirectory() as t:
   old={'schema':'file_index.v3','scope':{'vendor':'v','library':'l'},
        'deliveries':[{'delivery_id':'d1','version':'V1','root':'/r1'},{'delivery_id':'d2','version':'V2','root':'/r2'}],
        'formal_nl':{},'views':{'LEF':{'files':{'a.lef':{'raw':[{'delivery_id':'d1','file_id':'f1'},{'delivery_id':'d2','file_id':'f2'}]}}}}}
   new={'deliveries':[{'version':'V1','root':'/r1'},{'version':'V2','root':'/r2'}], 'views':{'LEF':{'a.lef':{'raw':[{'version':'V1','path':'/r1/a.lef'},{'version':'V2','path':'/r2/a.lef'}],'nl':[],'effective':[]}}}}
   refs={('d1','f1'):('LEF','V1','a.lef'),('d2','f2'):('LEF','V2','a.lef')}
   result=_reconcile_index(old,new,refs,'v','l',Path(t)/'report.tsv')
   self.assertEqual(result['missing'],0);self.assertEqual(result['order_differences'],2)

if __name__=='__main__':unittest.main()
