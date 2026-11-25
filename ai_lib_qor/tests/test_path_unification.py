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
        initialize_from_formal(self.work, 'v', 'lib', next(self.folder.glob('formal/formal_NL1_*.json')))

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
        self.assertEqual(len(list(self.folder.glob('effective/effective_lib_*.json'))), 1)
        result = apply_update(self.work, 'v', 'lib', ops, expected_parent='rev_0001')
        self.assertEqual(result['revision'], 'rev_0002')
        with self.assertRaisesRegex(ValueError, '父版本'):
            apply_update(self.work, 'v', 'lib', ops, expected_parent='rev_0001')
        result = restore_revision(self.work, 'v', 'lib', 'rev_0001', expected_parent='rev_0002')
        self.assertEqual(result['revision'], 'rev_0003')
        first = json.loads((self.folder/'effective/effective_lib_001.json').read_text())
        restored = json.loads((self.folder/'effective/effective_lib_003.json').read_text())
        self.assertEqual(first['views'], restored['views'])

    def test_batch_apply_records_audit_and_invalid_batch_is_atomic(self):
        import csv
        from ai_lib_qor.application.minimal_effective import preview_update,apply_update
        ops={'set':[{'view':'LEF','version':self.versions[1],'path':'LEF/a.lef'}],
             'remove':[{'view':'LIBERTY','path':'LIB/a.lib'}]}
        preview=preview_update(self.work,'v','lib',ops)
        self.assertEqual(len(preview['changes']),2)
        result=apply_update(self.work,'v','lib',ops,expected_parent='rev_0001',actor='test')
        self.assertEqual(result['revision'],'rev_0002')
        with (self.folder/'log/effective_operations.tsv').open(newline='') as stream:rows=list(csv.DictReader(stream,delimiter='\t'))
        event=next(r for r in rows if r['revision']=='rev_0002' and r['status']=='PUBLISHED')
        self.assertEqual(event['actor'],'test');self.assertEqual(event['parent'],'rev_0001')
        self.assertEqual(len(json.loads(event['changes'])),2)
        with self.assertRaises(ValueError):
            apply_update(self.work,'v','lib',{'set':[{'view':'LEF','version':self.versions[0],'path':'missing'}],'remove':[]},expected_parent='rev_0002',actor='test')
        self.assertFalse((self.folder/'effective/effective_lib_003.json').exists())
        with (self.folder/'log/effective_operations.tsv').open(newline='') as stream:rows=list(csv.DictReader(stream,delimiter='\t'))
        self.assertTrue(any(r['actor']=='test' and r['status']=='REJECTED' for r in rows))

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
        self.assertTrue((self.folder/'delivery/delivery_lib__20260102_b.json').exists())
        with self.assertRaisesRegex(ValueError, '排除'):
            preview_delivery(self.work, 'v', 'lib', self.versions[1])
        with self.assertRaisesRegex(ValueError, '排除'):
            apply_update(self.work, 'v', 'lib', result['operations'], expected_parent='rev_0001')
        set_version_excluded(self.work, 'v', 'lib', self.versions[1], False)
        self.assertEqual(apply_update(self.work, 'v', 'lib', result['operations'], expected_parent='rev_0001')['revision'], 'rev_0002')
        impact = set_version_excluded(self.work, 'v', 'lib', self.versions[1], True)
        self.assertTrue(impact['currently_used'])
        self.assertEqual(json.loads((self.folder/'effective/effective_lib_002.json').read_text())['revision'], 'rev_0002')


if __name__ == '__main__':
    unittest.main()
