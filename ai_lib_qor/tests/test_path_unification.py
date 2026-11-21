import json
import tempfile
import unittest
from pathlib import Path

from ai_lib_qor.sources.root_inventory import build_from_roots
from ai_lib_qor.application.minimal_effective import initialize_from_formal, update_effective


class PathUnificationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        self.work, self.raw, self.nl = base/'work', base/'raw', base/'NL1'
        self.nl.mkdir()
        self.versions = ('20260101_a', '20260102_b')
        for version in self.versions:
            for name in ('LEF/a.lef', 'LIB/a.lib'):
                f = self.raw/'v'/'lib'/version/name
                f.parent.mkdir(parents=True, exist_ok=True)
                f.write_text('data')
        (self.nl/'a.lef').symlink_to(self.raw/'v'/'lib'/self.versions[0]/'LEF/a.lef')
        (self.nl/'a.lib').symlink_to(self.raw/'v'/'lib'/self.versions[0]/'LIB/a.lib')
        build_from_roots(self.raw, self.nl, self.work)
        self.folder = self.work/'libraries'/'v'/'lib'
        initialize_from_formal(self.work, 'v', 'lib', next(self.folder.glob('formal_NL1_*.json')))

    def test_check_context_contains_only_actual_members_and_baseline(self):
        from ai_lib_qor.application.path_query import PathDataQuery
        update_effective(self.work, 'v', 'lib', {'set':[{'view':'LEF', 'version':self.versions[1], 'path':'LEF/a.lef'}], 'remove':[]})
        context = PathDataQuery(self.work).get_check_context('v', 'lib', 'rev_0002')
        self.assertEqual(context['baseline'], 'rev_0001')
        self.assertEqual(len(context['members']), 2)
        lef = next(x for x in context['members'] if x['view'] == 'LEF')
        self.assertEqual(lef['version'], self.versions[1])
        self.assertEqual(lef['baseline']['version'], self.versions[0])
        with self.assertRaisesRegex(ValueError, '不存在'):
            PathDataQuery(self.work).get_check_context('v', 'lib', 'rev_9999')

    def test_preview_no_write_stale_apply_and_restore(self):
        from ai_lib_qor.application.minimal_effective import preview_update, apply_update, restore_revision
        ops = {'set':[{'view':'LEF', 'version':self.versions[1], 'path':'LEF/a.lef'}], 'remove':[]}
        preview = preview_update(self.work, 'v', 'lib', ops)
        self.assertEqual(preview['parent'], 'rev_0001')
        self.assertEqual(len(preview['changes']), 1)
        self.assertEqual(len(list(self.folder.glob('effective_lib_*.json'))), 1)
        result = apply_update(self.work, 'v', 'lib', ops, expected_parent='rev_0001')
        self.assertEqual(result['revision'], 'rev_0002')
        with self.assertRaisesRegex(ValueError, '父版本'):
            apply_update(self.work, 'v', 'lib', ops, expected_parent='rev_0001')
        result = restore_revision(self.work, 'v', 'lib', 'rev_0001', expected_parent='rev_0002')
        self.assertEqual(result['revision'], 'rev_0003')
        first = json.loads((self.folder/'effective_lib_001.json').read_text())
        restored = json.loads((self.folder/'effective_lib_003.json').read_text())
        self.assertEqual(first['views'], restored['views'])

    def test_unified_configuration_registration_times(self):
        from ai_lib_qor.application.path_config import load_path_config
        config = {'raw_root':str(self.raw), 'nl_root':str(self.nl), 'nl_version':'NL1',
                  'libraries': {'v': {'lib': {'version_registration_times': {'V01':'2026-01-01T12:00:00Z'}}}}}
        (self.work/'path_sources.json').write_text(json.dumps(config))
        self.assertEqual(load_path_config(self.work)['libraries']['v']['lib']['version_registration_times']['V01'], '2026-01-01T12:00:00Z')

    def test_delivery_preview_updates_only_existing_scope_and_exclusion_does_not_remove_history(self):
        from ai_lib_qor.application.minimal_effective import preview_delivery, apply_update
        from ai_lib_qor.application.path_config import set_version_excluded
        result = preview_delivery(self.work, 'v', 'lib', self.versions[1])
        self.assertEqual(len(result['changes']), 2)
        self.assertEqual(len(result['operations']['set']), 2)
        set_version_excluded(self.work, 'v', 'lib', self.versions[1], True)
        self.assertTrue((self.folder/'delivery_lib_20260102_001.json').exists())
        with self.assertRaisesRegex(ValueError, '排除'):
            preview_delivery(self.work, 'v', 'lib', self.versions[1])
        with self.assertRaisesRegex(ValueError, '排除'):
            apply_update(self.work, 'v', 'lib', result['operations'], expected_parent='rev_0001')
        set_version_excluded(self.work, 'v', 'lib', self.versions[1], False)
        self.assertEqual(apply_update(self.work, 'v', 'lib', result['operations'], expected_parent='rev_0001')['revision'], 'rev_0002')
        impact = set_version_excluded(self.work, 'v', 'lib', self.versions[1], True)
        self.assertTrue(impact['currently_used'])
        self.assertEqual(json.loads((self.folder/'effective_lib_002.json').read_text())['revision'], 'rev_0002')

    def test_legacy_migration_translates_members_without_identity_sidecars(self):
        from ai_lib_qor.application.path_migration import migrate_legacy_library
        import shutil
        legacy=Path(self.tmp.name)/'legacy';folder=legacy/'libraries/v/lib';folder.mkdir(parents=True)
        for i,version in enumerate(self.versions,1):
            source=next(self.folder.glob('delivery_lib_'+version[:8]+'_*.json'))
            shutil.copy(source,folder/f'delivery_{i:03}.json')
            delivery=json.loads(source.read_text())
            evidence={'legacy_compatibility':{'metadata':{'delivery_id':f'old{i}'},
                     'files':{path:{'file_id':f'{view}-{path}', 'view':view} for view,paths in delivery['views'].items() for path in paths}}}
            (folder/f'evidence_delivery_{i:03}.json').write_text(json.dumps(evidence))
        formal=json.loads(next(self.folder.glob('formal_NL1_*.json')).read_text())
        (folder/'formal_NL1_001.json').write_text(json.dumps(formal))
        for i in (1,2):
            old={'schema_version':'effective_version.v1','owner':{'owner_type':'SOURCE_LIBRARY','owner_id':'lib'},
                 'revision_id':f'rev_{i:04}', 'created_at':'2026-01-02T00:00:00Z',
                 'members':[{'source_ref':{'kind':'delivery_file','source_library_id':'lib','delivery_id':f'old{i}','file_id':'LEF-LEF/a.lef'}}]}
            (folder/f'effective_lib_{i:03}.json').write_text(json.dumps(old))
        dest=Path(self.tmp.name)/'migrated'
        result=migrate_legacy_library(legacy,dest,'v','lib')
        self.assertEqual(result['revisions'],2)
        out=dest/'libraries/v/lib'
        self.assertFalse(list(out.glob('evidence_delivery_*.json')))
        self.assertEqual(json.loads((out/'effective_lib_002.json').read_text())['views']['LEF'][self.versions[1]], ['LEF/a.lef'])
        self.assertTrue((out/'latest_delivery.json').is_symlink())
        self.assertTrue((out/'latest_effective.json').is_symlink())


if __name__ == '__main__':
    unittest.main()
