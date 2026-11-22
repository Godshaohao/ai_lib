import json
import tempfile
import unittest
from pathlib import Path
from copy import deepcopy

from ai_lib_qor.application.file_index import (
    IndexErrorValue, load_records, resolve_order, build_index, update_index,
)


def record(tmp, name, version, order, rows, root=None, delivery_id=None):
    path = Path(tmp) / f'delivery_{name}.json'
    data = {
        'schema_version': 'delivery_record.v1',
        'delivery_id': delivery_id or f'dlv_{name}',
        'vendor_id': 'SRAM22',
        'source_library_id': 'mem',
        'supplier_version': version,
        'delivery_order': order,
        'source_root': root or f'/raw/{version}',
        'received_at': '2026-11-18T12:00:00Z',
        'files': [{
            'relative_path': fpath,
            'view': view,
            'file_id': f'f{i}',
            'file_key': (f'{view}:{fpath}' if known else None),
            'classification': ('RESOLVED' if known else 'UNRESOLVED'),
            'corner': None,
            'mode': None,
        } for i, (view, fpath, known) in enumerate(rows)]
    }
    path.write_text(json.dumps(data))
    return path


class IndexTests(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.TemporaryDirectory()
        self.addCleanup(self.t.cleanup)
        self.root = Path(self.t.name)
        self.p1 = record(self.root, '001', 'V01', 1, [('LEF', 'LEF/a.lef', True), ('LIBERTY', 'LIB/NLDM/a_tt.lib', True)])
        self.p2 = record(self.root, '002', 'V02', 2, [('LIBERTY', 'LIB/NLDM/a_tt.lib', True)])
        self.p3 = record(self.root, '003', 'V03', 3, [('GDS', 'GDS/a.gds.gz', False)])
        self.p4 = record(self.root, '004', 'V04', 4, [('LEF', 'LEF/a.lef', True)])

    def recs(self, *paths):
        return load_records(list(paths))

    def test_wrong_schema_is_not_silently_overwritten(self):
        records = self.recs(self.p1)
        with self.assertRaises(IndexErrorValue):
            update_index({'schema':'file_index.v99'}, records, ['dlv_001'])

    def test_discover_legacy_nested_delivery(self):
        from ai_lib_qor.application.file_index import _discover
        folder=self.root/'deliveries'/'d1';folder.mkdir(parents=True)
        (folder/'delivery.json').write_text(self.p1.read_text())
        self.assertIn((folder/'delivery.json').resolve(),_discover([self.root],[]))

    def test_legacy_v2_redundant_fields_migrate_only_when_consistent(self):
        records=self.recs(self.p1,self.p2);order=resolve_order(records,trust_delivery_order=True)
        modern=build_index(records,order);old=deepcopy(modern)
        for item in old['deliveries']:
            rec=records[item['delivery_id']];item['delivery_order']=rec['source_order'];item['file_count']=len(rec['rows'])
        for files in old['views'].values():
            for bucket in files.values():
                for item in bucket['timeline']:item['version']=records[item['delivery_id']]['version']
        migrated,action=update_index(old,records,order)
        self.assertEqual(action,'MIGRATE');self.assertEqual(migrated,modern)
        old['deliveries'][0]['delivery_order']=999
        with self.assertRaises(IndexErrorValue):update_index(old,records,order)

    def test_explicit_sequence_is_the_only_order_in_index(self):
        records=self.recs(self.p1,self.p2)
        ordered=resolve_order(records,order_ids='dlv_001,dlv_002')
        result=build_index(records,ordered)
        self.assertEqual([x['delivery_id'] for x in result['deliveries']],['dlv_001','dlv_002'])
        self.assertTrue(all('delivery_order' not in x for x in result['deliveries']))

    def test_date_order_uses_explicit_registered_time_only_for_missing_dates(self):
        from ai_lib_qor.application.file_index import repository_order
        p1=record(self.root,'101','20250101_old',1,[('LEF','a.lef',True)])
        p2=record(self.root,'102','vendor_release',2,[('LEF','a.lef',True)])
        p3=record(self.root,'103','20250301_new',3,[('LEF','a.lef',True)])
        records=self.recs(p1,p2,p3)
        items=[{'record':{'delivery_id':r['delivery_id'],'supplier_version':r['version'],'delivery_order':r['source_order']},'ordering_status':'UNCONFIRMED'} for r in records.values()]
        source={'order_rule':{'type':'VERSION_DATE_PREFIX','confirmed':True},'order_timezone':'Asia/Singapore',
                'delivery_registration_times':{'dlv_102':'2025-02-15T10:00:00+08:00'}}
        ordered,basis=repository_order(items,source)
        self.assertEqual([x['record']['delivery_id'] for x in ordered],['dlv_101','dlv_102','dlv_103'])
        self.assertEqual(basis,'CONFIRMED_DATE_AND_REGISTERED_TIME')
        source['delivery_orders']={'20250101_old':3,'vendor_release':2,'20250301_new':1}
        self.assertEqual([x['record']['delivery_id'] for x in repository_order(items,source)[0]],['dlv_101','dlv_102','dlv_103'])
        source['delivery_registration_times']['dlv_102']='2025-01-01T10:00:00+08:00'
        self.assertIsNone(repository_order(items,source)[0])
        source['delivery_registration_times']={}
        self.assertIsNone(repository_order(items,source)[0])

    def test_registered_times_require_zone_and_allow_distinct_instants(self):
        from ai_lib_qor.application.file_index import repository_order
        a=record(self.root,'201','release_a',1,[('LEF','a.lef',True)])
        b=record(self.root,'202','release_b',2,[('LEF','a.lef',True)])
        records=self.recs(a,b)
        items=[{'record':{'delivery_id':r['delivery_id'],'supplier_version':r['version'],'delivery_order':r['source_order']},'ordering_status':'UNCONFIRMED'} for r in records.values()]
        source={'order_rule':{'type':'VERSION_DATE_PREFIX','confirmed':True},'order_timezone':'Asia/Singapore',
                'delivery_registration_times':{'dlv_201':'2025-02-15T10:00:00+08:00','dlv_202':'2025-02-15T11:00:00+08:00'}}
        self.assertEqual([x['record']['delivery_id'] for x in repository_order(items,source)[0]],['dlv_201','dlv_202'])
        source['delivery_registration_times']['dlv_202']='2025-02-15T11:00:00'
        self.assertIsNone(repository_order(items,source)[0])

    def test_full_timeline_and_cross_delivery_gap(self):
        records = self.recs(self.p1, self.p2, self.p3, self.p4)
        order = resolve_order(records, trust_delivery_order=True)
        idx = build_index(records, order)
        self.assertEqual([x['version'] for x in idx['deliveries']], ['V04', 'V03', 'V02', 'V01'])
        self.assertEqual([x['delivery_id'] for x in idx['views']['LEF']['LEF/a.lef']['timeline']], ['dlv_004', 'dlv_001'])
        self.assertEqual([x['delivery_id'] for x in idx['views']['LIBERTY']['LIB/NLDM/a_tt.lib']['timeline']], ['dlv_002', 'dlv_001'])
        self.assertTrue(all('delivery_order' not in row and 'file_count' not in row for row in idx['deliveries']))
        self.assertTrue(all('version' not in row for row in idx['views']['LEF']['LEF/a.lef']['timeline']))
        self.assertEqual(idx['views']['GDS']['GDS/a.gds.gz']['timeline'][0]['classification'], 'UNRESOLVED')
        self.assertNotIn('.json', json.dumps(idx['deliveries']))
        self.assertIn('/raw/V04', json.dumps(idx))

    def test_append_and_idempotence(self):
        records = self.recs(self.p1, self.p2, self.p3)
        order = resolve_order(records, trust_delivery_order=True)
        base = build_index(records, order)
        all_records = self.recs(self.p1, self.p2, self.p3, self.p4)
        all_order = resolve_order(all_records, trust_delivery_order=True)
        updated, action = update_index(base, all_records, all_order)
        self.assertEqual(action, 'APPEND')
        self.assertEqual(updated, build_index(all_records, all_order))
        same, action = update_index(updated, all_records, all_order)
        self.assertEqual(action, 'UNCHANGED')
        self.assertEqual(same, updated)

    def test_reorder_rebuild_without_raw_scan(self):
        all_records = self.recs(self.p1, self.p2, self.p3, self.p4)
        order = resolve_order(all_records, trust_delivery_order=True)
        before = build_index(all_records, order)
        reordered = ['dlv_003', 'dlv_004', 'dlv_002', 'dlv_001']
        updated, action = update_index(before, all_records, reordered)
        self.assertEqual(action, 'REORDER_REBUILD')
        self.assertEqual(updated, build_index(all_records, reordered))

    def test_history_mutation_is_blocked(self):
        records = self.recs(self.p1, self.p2)
        idx = build_index(records, resolve_order(records, trust_delivery_order=True))
        orig = json.loads(self.p1.read_text())
        orig['files'].append({'relative_path': 'LEF/new.lef', 'view': 'LEF', 'file_id': 'f99', 'file_key': None, 'classification': 'UNRESOLVED'})
        self.p1.write_text(json.dumps(orig))
        changed = self.recs(self.p1, self.p2)
        with self.assertRaises(IndexErrorValue):
            update_index(idx, changed, resolve_order(changed, trust_delivery_order=True))

    def test_same_version_reissue_needs_distinct_delivery_ids_and_order(self):
        other = record(self.root, '005', 'V04', 5, [('LEF', 'LEF/a.lef', True)])
        records = self.recs(self.p4, other)
        with self.assertRaises(IndexErrorValue):
            resolve_order(records, date_prefix_order=True)
        self.assertEqual(resolve_order(records, order_ids='dlv_005,dlv_004'), ['dlv_005', 'dlv_004'])

    def test_unknown_order_rejected(self):
        recs = self.recs(self.p1, self.p2)
        with self.assertRaises(IndexErrorValue):
            resolve_order(recs)

    def test_raw_simple_with_nested_liberty(self):
        p = self.root / 'delivery_006.json'
        p.write_text(json.dumps({'schema': 'raw.simple.v1', 'delivery_id': 'r06', 'context': {
            'vendor': 'SRAM22', 'library': 'mem', 'version': '20261024_aa', 'root': '/raw/V06',
            'recorded_at': '2026-11-18T12:00:00Z'},
            'views': {'LEF': ['LEF/a.lef'], 'LIBERTY': {'NLDM': ['LIB/NLDM/a_ff.lib']}}}))
        data = self.recs(p)
        idx = build_index(data, ['r06'])
        self.assertEqual(idx['views']['LIBERTY']['LIB/NLDM/a_ff.lib']['timeline'][0]['classification'], 'UNKNOWN')
        self.assertIsNone(idx['views']['LEF']['LEF/a.lef']['timeline'][0]['file_id'])

    def test_scopes_reject_cross_library(self):
        other = record(self.root, '777', 'V77', 77, [('LEF', 'LEF/a.lef', True)])
        d = json.loads(other.read_text()); d['source_library_id'] = 'other'; other.write_text(json.dumps(d))
        with self.assertRaises(IndexErrorValue):
            self.recs(self.p1, other)

    def test_same_delivery_id_rejected(self):
        other = record(self.root, '777', 'V77', 77, [('LEF', 'LEF/a.lef', True)], delivery_id='dlv_001')
        with self.assertRaises(IndexErrorValue):
            self.recs(self.p1, other)


if __name__ == '__main__':
    unittest.main()
