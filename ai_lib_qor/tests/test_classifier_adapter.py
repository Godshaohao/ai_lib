import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from ai_lib_qor.sources.update_scan import scan_library

class ClassificationTests(unittest.TestCase):
    def test_scan_and_classification_use_metadata_and_preserve_unknown(self):
        from ai_lib_qor.sources.classifier_adapter import classify_observation
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            for name in ('V07/lef/core.lef.gz','V07/lib/func_tt.lib.gz','V07/doc/readme.pdf','V07/mystery.xyz'):
                p=root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b'test')
            with patch('pathlib.Path.open',side_effect=AssertionError('content read')):
                scan=scan_library(root,'vendor','lib',metadata_only=True)
                result=classify_observation(scan, {'version_paths': {'V07':'V07'}})
            self.assertEqual(scan['status'],'COMPLETE')
            rows={r['path']:r for r in result['files']}
            self.assertEqual(rows['V07/lef/core.lef.gz']['view'],'LEF')
            self.assertEqual(rows['V07/lib/func_tt.lib.gz']['view'],'LIBERTY')
            self.assertEqual(rows['V07/doc/readme.pdf']['file_type'],'doc')
            self.assertEqual(rows['V07/mystery.xyz']['file_type'],'unknown')
            self.assertTrue(all(x['file_key'] is None and x['classification']=='UNRESOLVED' for x in rows.values()))
            self.assertTrue(all('sha256' not in x for x in scan['files']))

    def test_deep_version_roots_and_ambiguous_prefixes(self):
        from ai_lib_qor.sources.classifier_adapter import classify_observation
        scan={'status':'COMPLETE','comparison_method':'size_mtime_ns','files':[{'path':'bundles/lib/releases/V08/lib/scan_tt.lib','size':1,'mtime_ns':1}]}
        result=classify_observation(scan,{'version_paths':{'V08':'bundles/lib/releases/V08'}})
        self.assertEqual(result['files'][0]['supplier_version'],'V08')
        conflict=classify_observation(scan,{'version_paths':{'a':'bundles/lib/releases','b':'bundles/lib/releases/V08'}})
        self.assertIsNone(conflict['files'][0]['supplier_version'])
        self.assertIn('版本范围重叠',conflict['files'][0]['reason'])

    def test_unsupported_or_partial_scans_are_rejected(self):
        from ai_lib_qor.sources.classifier_adapter import classify_observation
        for scan in ({'status':'PARTIAL','comparison_method':'size_mtime_ns','files':[]},
                     {'status':'COMPLETE','comparison_method':'sha256','files':[]}):
            with self.assertRaises(ValueError): classify_observation(scan,{})

    def test_distinct_names_never_become_invented_file_keys(self):
        from ai_lib_qor.sources.classifier_adapter import classify_observation
        names=('V07/lib/scan_tt.lib','V07/lib/func_tt.lib','V07/lib/tt_0p75v85c.lib','V07/lib/tt_0p85v125c.lib','V07/rtl/design.sv','V07/net/design.cdl')
        scan={'status':'COMPLETE','comparison_method':'size_mtime_ns','files':[{'path':p,'size':1,'mtime_ns':1} for p in names]}
        rows=classify_observation(scan,{'version_paths':{'V07':'V07'}})['files']
        self.assertEqual(len(rows),len(names))
        self.assertTrue(all(row['file_key'] is None for row in rows))
        self.assertEqual(rows[-2]['view'],'VERILOG')
        self.assertEqual(rows[-1]['view'],'CDL')

    def test_confirmed_mapping_is_stable_and_duplicates_are_unresolved(self):
        from ai_lib_qor.sources.classifier_adapter import classify_observation
        paths=('V07/lef/core.lef','V08/lef/core.lef','V08/lef/duplicate.lef')
        scan={'status':'COMPLETE','comparison_method':'size_mtime_ns','files':[{'path':p,'size':1,'mtime_ns':1} for p in paths]}
        config={'version_paths':{'V07':'V07','V08':'V08'},'file_mapping':{
            'V07/lef/core.lef':{'file_key':'lib:lef:core'},
            'V08/lef/core.lef':{'file_key':'lib:lef:core'},
            'V08/lef/duplicate.lef':{'file_key':'lib:lef:core'}}}
        rows={x['path']:x for x in classify_observation(scan,config)['files']}
        self.assertEqual(rows[paths[0]]['file_key'],'lib:lef:core')
        for p in paths[1:]:
            self.assertIsNone(rows[p]['file_key'])
            self.assertEqual(rows[p]['classification'],'UNRESOLVED')
            self.assertIn('冲突',rows[p]['reason'])
