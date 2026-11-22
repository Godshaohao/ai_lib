import json
import tempfile
import unittest
from pathlib import Path

from ai_lib_qor.sources.auto_ingest import auto_ingest
from ai_lib_qor.sources.update_scan import scan_library
from ai_lib_qor.versions.store import read_json


class MinimalDeliveryTests(unittest.TestCase):
 def test_scan_persists_seven_fields_and_legacy_consumers_read_identity(self):
  with tempfile.TemporaryDirectory() as d:
   base=Path(d);work=base/'work';work.mkdir();raw=base/'raw';version='20261024_hash'
   lef=raw/version/'LEF/a.lef';lef.parent.mkdir(parents=True);lef.write_text('fixture')
   source={'vendor_id':'SRAM22','source_library_id':'lib','root':str(raw),'version_paths':{version:version}}
   out=auto_ingest(work,source,scan_library(raw,'SRAM22','lib',metadata_only=True))
   self.assertEqual(out['created'],1)
   path=next(work.glob('libraries/SRAM22/lib/delivery_*.json'))
   data=json.loads(path.read_text())
   self.assertEqual(set(data),{'vendor','library','version','version_date','directory_created_at','root','views'})
   self.assertEqual(data['version_date'],'2026-10-24');self.assertEqual(data['views']['LEF'],['LEF/a.lef'])
   legacy=read_json(path,'delivery_record')
   self.assertEqual(legacy['delivery_id'],out['created_delivery_ids'][0]);self.assertEqual(legacy['files'][0]['relative_path'],'LEF/a.lef')
   self.assertEqual(auto_ingest(work,source,scan_library(raw,'SRAM22','lib',metadata_only=True))['duplicates'],1)

 def test_version_date_must_be_valid_and_absence_is_null(self):
  from ai_lib_qor.sources.minimal_delivery import version_date
  self.assertEqual(version_date('20261024_hash'),'2026-10-24')
  self.assertIsNone(version_date('V07'));self.assertIsNone(version_date('20261340_bad'))

 def test_spice_view_uses_extension_without_changing_legacy_identity(self):
  from ai_lib_qor.sources.minimal_delivery import simplify,compatibility,expand
  with tempfile.TemporaryDirectory() as d:
   from ai_lib_qor.sources.delivery_builder import build_delivery
   root=Path(d);p=root/'SPICE/a.spice';p.parent.mkdir();p.write_text('fixture')
   metadata={'delivery_id':'d1','vendor_id':'v','source_library_id':'lib','supplier_version':'V1','delivery_order':1,'received_at':'2026-01-01T00:00:00Z','package_mode':'UNKNOWN'}
   record=build_delivery(root,metadata,{'SPICE/a.spice':{'file_key':'a','view':'CDL'}})
   data=simplify(record)
   self.assertEqual(data['views']['SPICE'],['SPICE/a.spice'])
   self.assertEqual(expand(data,{'legacy_compatibility':compatibility(record)}),record)

 def test_migration_preserves_archived_references_and_is_idempotent(self):
  from test_v3_index_check_flow import make_fixture
  from ai_lib_qor.application.data_query import LibraryDataQuery
  from ai_lib_qor.sources.minimal_delivery import migrate_library
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);work,_=make_fixture(root);folder=work/'libraries/v/lib'
   before=LibraryDataQuery(work,root/'runs').get_check_context('v','lib','core_ip','rev_0003')
   old={p.name:read_json(p,'delivery_record') for p in folder.glob('delivery_*.json')}
   result=migrate_library(work,'v','lib');self.assertEqual(result['converted'],len(old))
   for name,record in old.items():
    self.assertEqual(read_json(folder/name,'delivery_record'),record)
    self.assertEqual(len(json.loads((folder/name).read_text())),7)
   after=LibraryDataQuery(work,root/'runs').get_check_context('v','lib','core_ip','rev_0003')
   self.assertEqual(after['selected_files'],before['selected_files'])
   self.assertEqual(migrate_library(work,'v','lib')['converted'],0)
