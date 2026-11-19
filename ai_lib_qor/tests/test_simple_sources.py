import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ai_lib_qor.application.simple_sources import simple_raw, simple_formal, build_effective, compare_formal, build_history
from ai_lib_qor.application.data_query import LibraryDataQuery

ROOT=Path(__file__).resolve().parents[1]


class SimpleSourcesTests(unittest.TestCase):
    def test_flat_v1_to_simple_raw_and_formal_without_source_scan(self):
        data=ROOT/'exports/flat_library_review_rdyp0zdh'
        if not data.exists():self.skipTest('本地公开样本不在工作目录')
        q=LibraryDataQuery(data/'work',data/'runs');vendor='SRAM22';lib='sram22_256x16m8w8'
        snapshot=next(s for s in q.snapshots if s['formal_nl_id']=='NL2.5.3' and s['scope']['source_library_ids']==[lib])
        with patch('os.walk',side_effect=AssertionError('不得扫描 RAW')):
            raw=simple_raw(q,vendor,lib,'20261024_de0a9a7')
            formal=simple_formal(q,vendor,lib,'NL2.5.3',snapshot['formal_snapshot_id'])
        self.assertEqual(raw['delivery_id'],'delivery_005')
        self.assertNotIn('file_id',json.dumps(raw));self.assertNotIn('file_key',json.dumps(raw))
        self.assertEqual(len(raw['views']['LIBERTY']['NLDM']),3)
        self.assertEqual(formal['schema'],'formal.simple.v3')
        self.assertNotIn('coverage',formal);self.assertNotIn('unassigned',formal)
        sources=[v for group in formal['views'].values() for v in group.values()]
        self.assertEqual(len(sources),7)
        self.assertTrue(all(x['raw_version']=='20261024_de0a9a7' for x in sources))
        self.assertTrue(all('resolved_path' not in x and 'raw_source' not in x for x in sources))
        self.assertTrue(all(x['link_target'] is None and x['link_target_status']=='NOT_RECORDED' for x in sources))
        self.assertTrue(any(x['match_basis']=='ARCHIVED_PATH_TEXT' for x in sources))

    def test_formal_v2_preserves_unmatched_and_duplicate_version_identity(self):
        from unittest.mock import Mock
        q=Mock();q.work='/work'
        q.repo.formal.return_value=[{'record':{'formal_nl_id':'NL','formal_snapshot_id':'snap'},'path':'/work/libraries/A/L/formal_NL_001.json'}]
        base={'vendor_id':'A','source_library_id':'L','supplier_version':'V1'}
        q.deliveries=[{'record':{**base,'delivery_id':'id1'},'path':'/work/libraries/A/L/delivery_001.json'},
                      {'record':{**base,'delivery_id':'id2'},'path':'/work/libraries/A/L/delivery_002.json'}]
        q.get_formal_files.return_value={'context':{'vendor':'A','library':'L','version':'NL','root':'/nl','recorded_at':'2026-01-01T00:00:00Z','snapshot_id':'snap','coverage':'PARTIAL'},'unassigned':[{'link_path':'unknown','resolved_path':'/missing'}],
            'views':{'LEF':{'l/a':{'raw_source':{'vendor':'A','library':'L','delivery_id':'id1','version':'V1','path':'lef/a'},'resolved_path':'/raw/lef/a','path_match_basis':'CONTRACT_REFERENCE'},
                            'l/b':{'raw_source':None,'resolved_path':'/unmatched/b','path_match_basis':None}}}}
        out=simple_formal(q,'A','L','NL','snap')
        self.assertEqual(out['views']['LEF']['l/a'],{'raw_version':'V1','raw_path':'lef/a','delivery':'delivery_001','link_target':None,'link_target_status':'NOT_RECORDED'})
        self.assertEqual(out['views']['LEF']['l/b']['resolved_path'],'/unmatched/b')
        self.assertEqual(out['unassigned'][0]['resolved_path'],'/missing')

    def test_compare_v2_requires_archived_delivery_version(self):
        raw={'schema':'raw.simple.v1','delivery_id':'delivery_001','context':{'vendor':'A','library':'L','version':'V1','root':'/offline'},'views':{'LEF':['lef/a']}}
        effective=build_effective([raw],['delivery_001'],include_views=['LEF'])
        formal={'schema':'formal.simple.v2','context':{'vendor':'A','library':'L'},'views':{'LEF':{'NL/a':{'raw_version':'V1','raw_path':'lef/a'}}}}
        self.assertEqual(compare_formal(effective,formal)['views']['LEF']['NL/a']['relation'],'UNKNOWN')
        self.assertEqual(compare_formal(effective,formal,[raw])['views']['LEF']['NL/a']['relation'],'SAME_SOURCE')
        formal['schema']='formal.simple.v3';formal['views']['LEF']['NL/a']['link_target']='../raw/lef/a'
        self.assertEqual(compare_formal(effective,formal,[raw])['views']['LEF']['NL/a']['relation'],'SAME_SOURCE')

    def test_compare_v2_duplicate_version_requires_delivery_id(self):
        a={'schema':'raw.simple.v1','delivery_id':'delivery_001','context':{'vendor':'A','library':'L','version':'V1','root':'/offline'},'views':{'LEF':['lef/a']}}
        b=copy.deepcopy(a);b['delivery_id']='delivery_002'
        effective=build_effective([a,b],['delivery_001','delivery_002'],include_views=['LEF'])
        formal={'schema':'formal.simple.v2','context':{'vendor':'A','library':'L'},'views':{'LEF':{'NL/a':{'raw_version':'V1','raw_path':'lef/a'}}}}
        self.assertEqual(compare_formal(effective,formal,[a,b])['views']['LEF']['NL/a']['relation'],'UNKNOWN')
        formal['views']['LEF']['NL/a']['delivery']='delivery_001'
        self.assertEqual(compare_formal(effective,formal,[a,b])['views']['LEF']['NL/a']['relation'],'DIFFERENT_SOURCE')
        missing=copy.deepcopy(a);missing['views']['LEF']=[]
        self.assertEqual(compare_formal(effective,formal,[missing,b])['views']['LEF']['NL/a']['relation'],'UNKNOWN')

    def test_explicit_order_incremental_inherits_and_rejects_collision(self):
        a={'schema':'raw.simple.v1','delivery_id':'delivery_001','context':{'vendor':'A','library':'L','version':'V1','root':'/offline'},'views':{'LEF':['lef/a.lef'],'LIBERTY':{'NLDM':['lib/tt.lib','lib/ff.lib']}}}
        b={'schema':'raw.simple.v1','delivery_id':'delivery_002','context':{'vendor':'A','library':'L','version':'V2','root':'/offline'},'views':{'LIBERTY':{'NLDM':['lib/ff.lib']}}}
        before=copy.deepcopy(a)
        result=build_effective([a,b],['delivery_001','delivery_002'],include_views=['LEF','LIBERTY'])
        self.assertEqual(result['views']['LEF']['lef/a.lef']['delivery'],'delivery_001')
        self.assertEqual(result['views']['LIBERTY']['lib/ff.lib']['delivery'],'delivery_002')
        self.assertEqual(result['views']['LIBERTY']['lib/tt.lib']['delivery'],'delivery_001')
        self.assertEqual(before,a)
        formal={'schema':'formal.simple.v1','coverage':'PARTIAL','views':{'LEF':{'NL/a.lef':{'raw_source':{'vendor':'A','library':'L','delivery':'delivery_001','path':'lef/a.lef'},'resolved_path':'/offline/lef/a.lef','match_basis':'ARCHIVED_PATH_TEXT'}}}}
        compared=compare_formal(result,formal)
        self.assertEqual(compared['views']['LEF']['NL/a.lef']['relation'],'SAME_SOURCE')
        self.assertEqual(compared['meaning'],'RECORDED_SOURCE_ONLY')
        unknown=build_history([a,b]);self.assertEqual(unknown['views']['LIBERTY']['lib/ff.lib']['ordering_status'],'ORDER_UNCONFIRMED')
        self.assertIsNone(unknown['views']['LIBERTY']['lib/ff.lib']['latest'])
        history=build_history([a,b],['delivery_001','delivery_002'])
        self.assertEqual(history['views']['LIBERTY']['lib/ff.lib']['previous']['version'],'V1')
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for name,item in [('a.json',a),('b.json',b),('formal.json',formal)]:
                (root/name).write_text(json.dumps(item))
            with patch('os.walk',side_effect=AssertionError('不得扫描来源')):
                records=[json.loads((root/name).read_text()) for name in ('a.json','b.json')]
                computed=build_effective(records,['delivery_001','delivery_002'],include_views=['LEF','LIBERTY'])
                checked=compare_formal(computed,json.loads((root/'formal.json').read_text()))
            self.assertEqual(checked['views']['LEF']['NL/a.lef']['relation'],'SAME_SOURCE')
        with self.assertRaisesRegex(ValueError,'顺序'):
            build_effective([a,b],['delivery_001'],include_views=['LEF','LIBERTY'])
        c=copy.deepcopy(b);c['context']['vendor']='B';c['delivery_id']='delivery_003'
        with self.assertRaisesRegex(ValueError,'冲突'):
            build_effective([a,b,c],['delivery_001','delivery_002','delivery_003'],include_views=['LEF','LIBERTY'])


if __name__=='__main__': unittest.main()
