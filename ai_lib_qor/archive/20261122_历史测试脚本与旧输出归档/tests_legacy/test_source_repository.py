import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ai_lib_qor.application.source_repository import SourceRepository

ROOT=Path(__file__).resolve().parents[1]
FIXTURE=ROOT/'examples/work/vendors/vendor_orion/libraries/lib_rtavfs/deliveries/dlv_20260907_001/delivery.json'


class SourceRepositoryTests(unittest.TestCase):
    def test_old_evidence_and_new_layout_deduplicate_without_source_access(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); data=json.loads(FIXTURE.read_text()); data['source_root']='/missing/raw'
            old=root/'vendors/vendor_orion/libraries/lib_rtavfs/deliveries/dlv_20260907_001'
            old.mkdir(parents=True); (old/'delivery.json').write_text(json.dumps(data))
            first=data['files'][0]
            evidence={'classification':{first['relative_path']:{'basis':'filename_unique_candidate'}},
                      'files':[{'path':first['relative_path'],'size':123,'mtime_ns':456}],
                      'order_basis':'natural_name_hint_or_system_receipt'}
            (old/'source_evidence.json').write_text(json.dumps(evidence))
            modern=root/'raw/vendor_orion/lib_rtavfs';modern.mkdir(parents=True)
            (modern/(data['delivery_id']+'.json')).write_text(json.dumps(data))
            before=(old/'delivery.json').read_bytes()
            with patch('os.walk',side_effect=AssertionError('unexpected walk')):
                records=SourceRepository(root).deliveries()
            self.assertEqual(len(records),1)
            self.assertEqual(records[0]['files'][0]['identity_status'],'CANDIDATE')
            self.assertEqual(records[0]['files'][0]['observation'],{'size':123,'mtime_ns':456})
            self.assertEqual(records[0]['ordering_status'],'UNCONFIRMED')
            self.assertEqual(before,(old/'delivery.json').read_bytes())
            history=SourceRepository(root).file_history('vendor_orion','lib_rtavfs',first['file_key'])
            self.assertEqual(history['ordering_status'],'ORDER_UNCONFIRMED')
            self.assertIsNone(history['latest'])

    def test_conflicting_duplicate_fails_with_both_paths(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); data=json.loads(FIXTURE.read_text())
            old=root/'vendors/vendor_orion/libraries/lib_rtavfs/deliveries/dlv_20260907_001';old.mkdir(parents=True)
            (old/'delivery.json').write_text(json.dumps(data))
            new=root/'raw/vendor_orion/lib_rtavfs';new.mkdir(parents=True)
            data['supplier_version']='conflict'; (new/(data['delivery_id']+'.json')).write_text(json.dumps(data))
            with self.assertRaisesRegex(ValueError,'冲突'):
                SourceRepository(root).deliveries()

    def test_formal_new_and_legacy_layout_dedup_and_conflict(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            fixture=ROOT/'examples/work/formal_nl/NL2.5.3/snapshots/snap_nl253_0001.json'
            data=json.loads(fixture.read_text())
            old=root/'formal_nl/NL2.5.3/snapshots';old.mkdir(parents=True)
            (old/'old.json').write_text(json.dumps(data))
            new=root/'formal/NL2.5.3';new.mkdir(parents=True)
            path=new/(data['formal_snapshot_id']+'.json');path.write_text(json.dumps(data))
            self.assertEqual(len(SourceRepository(root).formal()),1)
            data['source_root']='/changed';path.write_text(json.dumps(data))
            with self.assertRaisesRegex(ValueError,'冲突'):
                SourceRepository(root).formal()

    def test_catalog_sees_source_and_formal_in_compact_layout_without_ip(self):
        from ai_lib_qor.application.library_catalog import LibraryCatalog
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);work=root/'work';work.mkdir()
            data=json.loads(FIXTURE.read_text()); new=work/'raw/vendor_orion/lib_rtavfs';new.mkdir(parents=True)
            (new/(data['delivery_id']+'.json')).write_text(json.dumps(data))
            fixture=ROOT/'examples/work/formal_nl/NL2.5.3/snapshots/snap_nl253_0001.json'
            snapshot=json.loads(fixture.read_text());formal=work/'formal/NL2.5.3';formal.mkdir(parents=True)
            (formal/(snapshot['formal_snapshot_id']+'.json')).write_text(json.dumps(snapshot))
            catalog=LibraryCatalog(work,root/'runs').refresh()
            self.assertEqual(len(catalog.libraries[('vendor_orion','lib_rtavfs')]['deliveries']),1)
            self.assertEqual(len(catalog.formal_detail('NL2.5.3')['snapshots']),1)

    def test_ip_catalog_reads_compact_delivery_records(self):
        from ai_lib_qor.application.catalog import load_catalog
        with tempfile.TemporaryDirectory() as temp:
            work=Path(temp)/'work';shutil.copytree(ROOT/'examples/work',work)
            folder=work/'vendors/vendor_orion/libraries/lib_rtavfs/deliveries'
            new=work/'raw/vendor_orion/lib_rtavfs';new.mkdir(parents=True)
            for old in folder.glob('*/delivery.json'):
                item=json.loads(old.read_text());(new/(item['delivery_id']+'.json')).write_text(json.dumps(item))
            shutil.rmtree(folder)
            entries,_,warnings=load_catalog(work)
            self.assertFalse(warnings)
            self.assertEqual(len(entries[0]['deliveries']),2)


if __name__=='__main__':unittest.main()
