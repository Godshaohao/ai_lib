"""Targeted regression tests for first-layer redesign of 97acef8.

Run inside ai_lib_qor with both new and legacy source roots on PYTHONPATH.
"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class L1SourceDiscoveryTests(unittest.TestCase):
    def test_auto_version_discovery_is_metadata_only(self):
        from ai_lib_qor.sources.source_discovery import discover_version_paths
        scan = {'files': [
            {'path': 'V07/lef/core.lef', 'size': 1, 'mtime_ns': 1},
            {'path': 'V09/lib/func_tt.lib', 'size': 1, 'mtime_ns': 1},
            {'path': 'doc/readme.pdf', 'size': 1, 'mtime_ns': 1},
        ]}
        versions, warnings = discover_version_paths(scan, {'vendor_id': 'v', 'source_library_id': 'lib'})
        self.assertEqual(versions, {'V07': 'V07', 'V09': 'V09'})
        self.assertEqual(warnings, [])

    def test_deep_version_path_rule(self):
        from ai_lib_qor.sources.source_discovery import discover_version_paths
        scan = {'files': [{'path': 'bundles/lib/releases/V08/lib/tt.lib', 'size': 1, 'mtime_ns': 1}]}
        found, warnings = discover_version_paths(scan, {
            'source_library_id': 'lib', 'vendor_id': 'v',
            'version_path_rules': [{'pattern': 'bundles/{library}/releases/{version}'}]
        })
        self.assertEqual(found, {'V08': 'bundles/lib/releases/V08'})
        self.assertFalse(warnings)

    def test_library_map_adds_source_without_manual_per_library_entry(self):
        from ai_lib_qor.sources.source_discovery import load_scan_sources
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); work = root / 'work'; work.mkdir()
            raw = root / 'raw'; (raw / 'vendor_a' / 'lib1').mkdir(parents=True)
            (work / 'library_map.yml').write_text(
                'libraries:\n  vendor_a.lib1:\n    root: vendor_a/lib1\n    vendor: vendor_a\n    library_type: ip\n')
            (work / 'scan_sources.json').write_text(json.dumps({
                'raw_root': str(raw), 'library_map': 'library_map.yml', 'sources': []
            }))
            items = load_scan_sources(work)
            self.assertEqual(len(items), 1)
            self.assertEqual(items[0]['vendor_id'], 'vendor_a')
            self.assertEqual(items[0]['source_library_id'], 'vendor_a.lib1')


class L1ClassificationTests(unittest.TestCase):
    def test_discovery_includes_legacy_date_suffix_and_excludes_view_folders(self):
        from ai_lib_qor.sources.source_discovery import discover_version_paths
        paths=['20241117_cb95ccae/lef/core.lef','20260506_75cbe961/lib/core_tt.lib','lef/core.lef','lib/core_tt.lib']
        scan={'files':[{'path':p,'size':1,'mtime_ns':1} for p in paths]}
        found,_=discover_version_paths(scan,{'vendor_id':'v','source_library_id':'lib'})
        self.assertEqual(set(found),{'20241117_cb95ccae','20260506_75cbe961'})
    def test_old_embedded_classification_remains_visible(self):
        import json
        from ai_lib_qor.workbench.scans import run_scan
        from ai_lib_qor.workbench.l1_models import library_model
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);work=root/'work';work.mkdir();raw=root/'raw';raw.mkdir();(raw/'unknown.lef').write_text('x')
            source={'vendor_id':'v','source_library_id':'lib','root':str(raw)}
            (work/'scan_sources.json').write_text(json.dumps({'sources':[source]}))
            scan=run_scan(root/'runs',source)
            ingest=root/'runs'/'ingest';ingest.mkdir()
            (ingest/(scan['scan_id']+'.json')).write_text(json.dumps({'classified':[{'path':'unknown.lef','view':'LEF','file_key':None,'classification':'UNRESOLVED','reason':'未知'}]}))
            self.assertEqual(library_model(work,root/'runs','v','lib')['classified'][0]['path'],'unknown.lef')
    def test_normalized_names_do_not_merge_distinct_paths_across_versions(self):
        from ai_lib_qor.sources.classifier_adapter import classify_observation
        paths=['V07/lef/core-a.lef','V08/lef/core_a.lef']
        scan={'status':'COMPLETE','comparison_method':'size_mtime_ns','source_library_id':'lib',
              'files':[{'path':p,'size':1,'mtime_ns':1} for p in paths]}
        rows=classify_observation(scan,{'source_library_id':'lib'})['files']
        self.assertTrue(all(row['file_key'] is None for row in rows))
    def test_critical_file_slots_auto_and_corner_mode_retained(self):
        from ai_lib_qor.sources.classifier_adapter import classify_observation
        files = ['V07/lef/core.lef', 'V07/lib/func_tt.lib.gz',
                 'V08/lib/func_tt.lib.gz', 'V08/doc/readme.pdf']
        scan = {'status': 'COMPLETE', 'comparison_method': 'size_mtime_ns',
                'files': [{'path': f, 'size': 1, 'mtime_ns': 1} for f in files]}
        cfg = {'vendor_id': 'v', 'source_library_id': 'lib'}
        rows = {x['path']: x for x in classify_observation(scan, cfg)['files']}
        self.assertEqual(rows[files[0]]['file_key'], 'lib:lef:core')
        self.assertEqual(rows[files[1]]['file_key'], rows[files[2]]['file_key'])
        self.assertEqual(rows[files[1]]['corner'], 'tt')
        self.assertEqual(rows[files[1]]['mode'], 'func')
        self.assertIsNone(rows[files[3]]['file_key'])

    def test_duplicate_basename_never_collapses_distinct_files(self):
        from ai_lib_qor.sources.classifier_adapter import classify_observation
        scan = {'status': 'COMPLETE', 'comparison_method': 'size_mtime_ns',
                'files': [{'path': p, 'size': 1, 'mtime_ns': 1} for p in
                          ('V07/a/core.lef', 'V07/b/core.lef')]}
        rows = classify_observation(scan, {'vendor_id': 'v', 'source_library_id': 'l'})['files']
        self.assertTrue(all(x['classification'] == 'UNRESOLVED' for x in rows))

    def test_different_ip_path_context_is_not_collapsed(self):
        from ai_lib_qor.sources.classifier_adapter import classify_observation
        paths = ['V07/IP_A/lef/core.lef', 'V08/IP_B/lef/core.lef']
        scan = {'status': 'COMPLETE', 'comparison_method': 'size_mtime_ns',
                'files': [{'path': p, 'size': 1, 'mtime_ns': 1} for p in paths]}
        rows = classify_observation(scan, {'source_library_id': 'lib', 'vendor_id': 'v'})['files']
        self.assertNotEqual(rows[0]['file_key'], rows[1]['file_key'])

    def test_explicit_mapping_preserves_corner_and_mode(self):
        from ai_lib_qor.sources.classifier_adapter import classify_observation
        scan = {'status': 'COMPLETE', 'comparison_method': 'size_mtime_ns',
                'files': [{'path': 'V07/custom/foo.lib', 'size': 1, 'mtime_ns': 1}]}
        result = classify_observation(scan, {'vendor_id': 'v', 'source_library_id': 'lib',
            'file_mapping': {'V07/custom/foo.lib': {'file_key': 'lib:liberty:func_tt',
                                                    'corner': 'tt_0p85v', 'mode': 'func'}}})
        self.assertEqual(result['files'][0]['corner'], 'tt_0p85v')
        self.assertEqual(result['files'][0]['mode'], 'func')


class L1IngestTests(unittest.TestCase):
    def test_auto_ingest_resolved_lef_lib_and_unresolved_document(self):
        from ai_lib_qor.workbench.scans import run_scan_and_ingest
        from ai_lib_qor.versions.store import read_json
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); raw = root / 'raw'; work = root / 'work'; work.mkdir()
            for name in ('V07/core.lef', 'V07/func_tt.lib', 'V07/README.pdf',
                         'V08/func_tt.lib'):
                p = raw / name; p.parent.mkdir(parents=True, exist_ok=True); p.write_text('test')
            cfg = {'vendor_id': 'v', 'source_library_id': 'lib', 'root': str(raw)}
            scan = run_scan_and_ingest(root / 'runs', work, cfg)
            ingest = json.loads((root/'runs'/'ingest'/f"{scan['scan_id']}.json").read_text())
            self.assertEqual(ingest['created'], 2)
            delivered = [read_json(p, 'delivery_record') for p in work.glob('libraries/*/*/delivery_*.json')]
            self.assertEqual(len(delivered), 2)
            self.assertEqual(sorted(d['supplier_version'] for d in delivered), ['V07', 'V08'])
            for d in delivered:
                for f in d['files']:
                    if f['view'] == 'LIBERTY':
                        self.assertEqual((f['corner'], f['mode']), ('tt', 'func'))
                    if f['view'] == 'OTHER':
                        self.assertEqual(f['classification'], 'UNRESOLVED')
            self.assertEqual(run_scan_and_ingest(root/'runs', work, cfg)['status'], 'COMPLETE')
            self.assertEqual(len(list(work.glob('libraries/*/*/delivery_*.json'))), 2)

    def test_apply_selected_known_keys_without_unknown_document(self):
        from ai_lib_qor.versions.delivery_policy import apply_delivery
        with tempfile.TemporaryDirectory() as tmp:
            raw = Path(tmp); (raw/'core.lef').write_text('LEF'); (raw/'README.pdf').write_text('doc')
            d = {'source_root': str(raw), 'source_library_id': 'lib', 'delivery_id': 'd1',
                 'explicit_removed_file_keys': [], 'files': [
                     {'file_id': 'f1', 'file_key': 'lib:lef:core', 'relative_path': 'core.lef', 'classification': 'RESOLVED'},
                     {'file_id': 'f2', 'file_key': None, 'relative_path': 'README.pdf', 'classification': 'UNRESOLVED'}]}
            with self.assertRaisesRegex(ValueError, '未确认文件身份'):
                apply_delivery({}, d)
            result = apply_delivery({}, d, selected_keys=['lib:lef:core'])
            self.assertEqual(set(result), {'lib:lef:core'})


class L1FormalTests(unittest.TestCase):
    def test_same_formal_links_reuse_snapshot(self):
        from ai_lib_qor.sources.formal_sync import sync_formal
        from ai_lib_qor.sources.delivery_builder import build_delivery
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp); raw = base/'raw'; raw.mkdir(); work = base/'work'; work.mkdir()
            (raw/'core.lef').write_text('LEF')
            formal = base/'formal'; formal.mkdir()
            (formal/'core.lef').symlink_to(raw/'core.lef')
            metadata = {'delivery_id':'d1', 'vendor_id':'v', 'source_library_id':'lib',
                        'supplier_version':'V07', 'delivery_order':1,
                        'received_at':'2026-11-17T00:00:00Z', 'package_mode':'UNKNOWN', 'scope_confirmed':False}
            delivery = build_delivery(raw, metadata, {'core.lef':{'file_key':'lib:lef:core'}})
            cfg = {'formal_nl_id':'NL2.5.3', 'root':str(formal)}
            first = sync_formal(base/'runs', cfg, [delivery], work)
            second = sync_formal(base/'runs', cfg, [delivery], work)
            self.assertEqual(first['snapshot_action'], 'CREATED')
            self.assertEqual(second['snapshot_action'], 'REUSED')
            self.assertEqual(first['snapshot_id'], second['snapshot_id'])
            self.assertEqual(len(list((work/'libraries/v/lib').glob('formal_*.json'))), 1)


if __name__ == '__main__':
    unittest.main()
