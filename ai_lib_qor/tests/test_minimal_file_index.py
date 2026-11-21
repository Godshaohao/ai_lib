import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ai_lib_qor.sources.root_inventory import build_from_roots
from ai_lib_qor.application.minimal_effective import initialize_from_formal,update_effective


class MinimalFileIndexTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  root=Path(self.tmp.name);self.root=root;self.raw=root/'raw';self.nl=root/'NL1';self.nl.mkdir();self.work=root/'work'
  self.versions=('20261001_abcdef12','20261002_abcdef12')
  for ver in self.versions:
   for name in ('LEF/a.lef','LIB/a.lib'):
    p=self.raw/'v/lib'/ver/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(ver)
  (self.nl/'a.lef').symlink_to(self.raw/'v/lib'/self.versions[0]/'LEF/a.lef')
  (self.nl/'a.lib').symlink_to(self.raw/'v/lib'/self.versions[0]/'LIB/a.lib')
  self.result=build_from_roots(self.raw,self.nl,self.work)
  self.folder=self.work/'libraries/v/lib'

 def test_four_contracts_automatic_refresh_and_query(self):
  from ai_lib_qor.application.minimal_file_index import refresh_index,query_path
  index=json.loads((self.folder/'file_index.json').read_text())
  self.assertEqual(set(index),{'vendor','library','deliveries','nl_snapshots','revisions','views'})
  row=index['views']['LEF']['LEF/a.lef']
  self.assertEqual([x['version'] for x in row['raw']],list(self.versions))
  self.assertEqual(row['nl'][0]['source_match'],'MATCHED_RAW');self.assertEqual(row['effective'],[])
  formal=next(self.folder.glob('formal_NL1_*.json'))
  initialize_from_formal(self.work,'v','lib',formal,include=[('LEF','LEF/a.lef')])
  result=update_effective(self.work,'v','lib',{'set':[{'view':'LEF','version':self.versions[1],'path':'LEF/a.lef'}],'remove':[]})
  self.assertEqual(result['revision'],'rev_0002')
  index=json.loads((self.folder/'file_index.json').read_text());self.assertEqual(index['revisions'],['rev_0001','rev_0002'])
  result=query_path(self.work,'v','lib','LEF','LEF/a.lef',revision='rev_0002')
  self.assertEqual(result['effective']['version'],self.versions[1])
  old=(self.folder/'file_index.json').stat().st_mtime_ns
  with patch('os.walk',side_effect=AssertionError('索引不得扫描 RAW')):
   self.assertEqual(refresh_index(self.work,'v','lib')['state'],'UNCHANGED')
  self.assertEqual((self.folder/'file_index.json').stat().st_mtime_ns,old)

 def test_stale_and_missing_sources_cannot_serve_wrong_results(self):
  from ai_lib_qor.application.minimal_file_index import refresh_index,query_path
  path=next(self.folder.glob('delivery_*20261001*.json'))
  obj=json.loads(path.read_text());obj['views']['LEF']=[];path.write_text(json.dumps(obj))
  with self.assertRaisesRegex(ValueError,'索引.*过期'):query_path(self.work,'v','lib','LEF','LEF/a.lef')
  with self.assertRaisesRegex(ValueError,'正式|来源'):refresh_index(self.work,'v','lib')

 def test_same_date_order_needs_confirmation(self):
  from ai_lib_qor.application.minimal_file_index import refresh_index
  path=next(self.folder.glob('delivery_*20261002*.json'));value=json.loads(path.read_text())
  value['version_date']='2026-10-01';path.write_text(json.dumps(value))
  with self.assertRaisesRegex(ValueError,'顺序'):refresh_index(self.work,'v','lib')

 def test_archived_resolved_path_does_not_override_conflicting_link_text(self):
  from ai_lib_qor.application.minimal_file_index import build_index
  path=next(self.folder.glob('formal_NL1_*.json'));data=json.loads(path.read_text())
  data['views']['LEF'][self.versions[0]][0]['target']='/another/source/a.lef';path.write_text(json.dumps(data))
  index=build_index(self.work,'v','lib')
  self.assertEqual(index['views']['LEF']['LEF/a.lef']['nl'][0]['source_match'],'UNVERIFIED')

 def test_changed_archived_history_does_not_overwrite_published_index(self):
  from ai_lib_qor.application.minimal_file_index import refresh_index
  path=next(self.folder.glob('delivery_*20261002*.json'));data=json.loads(path.read_text())
  data['views']['LIBERTY']=[];path.write_text(json.dumps(data))
  index=self.folder/'file_index.json';before=index.read_bytes()
  with self.assertRaisesRegex(ValueError,'历史'):refresh_index(self.work,'v','lib')
  self.assertEqual(index.read_bytes(),before)

 def test_undated_versions_require_registered_times(self):
  from ai_lib_qor.application.minimal_file_index import refresh_index
  root=self.root/'other';raw=root/'raw';nl=root/'NL1';nl.mkdir(parents=True)
  for version in ('V01','V02'):
   p=raw/'v/lib'/version/'a.lef';p.parent.mkdir(parents=True);p.write_text('x')
  work=root/'work';build_from_roots(raw,nl,work)
  self.assertFalse((work/'libraries/v/lib/file_index.json').exists())
  config={'sources':[{'vendor_id':'v','source_library_id':'lib','version_registration_times':{'V01':'2026-01-01T12:00:00Z','V02':'2026-01-02T12:00:00Z'}}]}
  (work/'scan_sources.json').write_text(json.dumps(config))
  self.assertEqual(refresh_index(work,'v','lib')['state'],'UPDATED')
  data=json.loads((work/'libraries/v/lib/file_index.json').read_text())
  self.assertEqual([x['version'] for x in data['deliveries']],['V01','V02'])
  build_from_roots(raw,nl,work)
  self.assertEqual((work/'libraries/v/lib/latest_delivery.json').readlink().name,'delivery_lib_undated_002.json')

 def test_query_as_of_delivery_inherits_last_observation(self):
  from ai_lib_qor.application.minimal_file_index import query_path
  root=self.root/'asof';raw=root/'raw';nl=root/'NL1';nl.mkdir(parents=True)
  for version,name in [('20260101_a','a.lef'),('20260102_b','only.lib'),('20260103_c','a.lef')]:
   f=raw/'v/lib'/version/name;f.parent.mkdir(parents=True);f.write_text(name)
  work=root/'work';build_from_roots(raw,nl,work)
  row=query_path(work,'v','lib','LEF','a.lef',version='20260102_b')
  self.assertEqual(row['as_of']['version'],'20260101_a')
