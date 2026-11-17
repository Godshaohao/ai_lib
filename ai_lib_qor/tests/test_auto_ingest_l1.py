import tempfile
import unittest
from pathlib import Path
from ai_lib_qor.sources.update_scan import scan_library

class AutoIngestTests(unittest.TestCase):
    def test_web_scan_records_auto_ingest_result(self):
        from ai_lib_qor.workbench.scans import run_scan_and_ingest
        import json
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);raw=root/'raw';work=root/'work';runs=root/'runs';work.mkdir();p=raw/'V07/core.lef';p.parent.mkdir(parents=True);p.write_text('LEF')
            source={'vendor_id':'v','source_library_id':'lib','root':str(raw),'version_paths':{'V07':'V07'}}
            scan=run_scan_and_ingest(runs,work,source)
            result=json.loads((runs/'ingest'/f"{scan['scan_id']}.json").read_text())
            self.assertEqual(result['created'],1)
            self.assertEqual(len(list(work.rglob('delivery.json'))),1)
    def test_idempotent_ingest_keeps_unresolved_and_detects_in_place_changes(self):
        from ai_lib_qor.sources.auto_ingest import auto_ingest
        from ai_lib_qor.versions.store import read_json
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);raw=root/'raw';work=root/'work';work.mkdir(); p=raw/'V07/lef/core.lef';p.parent.mkdir(parents=True);p.write_text('LEF')
            source={'vendor_id':'v','source_library_id':'lib','root':str(raw),'version_paths':{'V07':'V07'}}
            scan=scan_library(raw,'v','lib',metadata_only=True)
            result=auto_ingest(work,source,scan)
            self.assertEqual(result['created'],1)
            path=next(work.glob('vendors/v/libraries/lib/deliveries/*/delivery.json'))
            record=read_json(path,'delivery_record')
            self.assertEqual(record['package_mode'],'UNKNOWN')
            self.assertFalse(record['package_scope']['scope_confirmed'])
            self.assertEqual(record['files'][0]['classification'],'UNRESOLVED')
            self.assertEqual(auto_ingest(work,source,scan)['duplicates'],1)
            p.write_text('modified original path')
            fresh=scan_library(raw,'v','lib',metadata_only=True)
            result=auto_ingest(work,source,fresh)
            self.assertEqual(result['modified'],1)
            self.assertEqual(len(list(work.glob('vendors/v/libraries/lib/deliveries/*/delivery.json'))),1)
            self.assertEqual(read_json(path,'delivery_record'),record)

    def test_changed_after_scan_does_not_publish(self):
        from ai_lib_qor.sources.auto_ingest import auto_ingest
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); raw=root/'raw';work=root/'work';work.mkdir();p=raw/'V07/core.lef';p.parent.mkdir(parents=True);p.write_text('a')
            source={'vendor_id':'v','source_library_id':'lib','root':str(raw),'version_paths':{'V07':'V07'}}
            scan=scan_library(raw,'v','lib',metadata_only=True);p.write_text('changed')
            result=auto_ingest(work,source,scan)
            self.assertEqual(result['blocked'],1)
            self.assertFalse(list(work.rglob('delivery.json')))
