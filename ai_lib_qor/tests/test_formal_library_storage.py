import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import os

from ai_lib_qor.sources.delivery_builder import build_delivery
from ai_lib_qor.sources.formal_sync import sync_formal
from ai_lib_qor.application.catalog import load_catalog


class FormalLibraryStorageTests(unittest.TestCase):
    def test_independent_library_snapshots_reuse_and_catalog(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp); work = base / 'work'; work.mkdir()
            formal = base / 'formal'; formal.mkdir()
            deliveries = []
            for name in ('one', 'two'):
                raw = base / name; raw.mkdir(); (raw / 'core.lef').write_text(name)
                (formal / (name + '.lef')).symlink_to(raw / 'core.lef')
                meta = {'delivery_id':'d_' + name, 'vendor_id':'vendor', 'source_library_id':name,
                        'supplier_version':'v1', 'delivery_order':1, 'received_at':'2026-11-17T00:00:00Z',
                        'package_mode':'UNKNOWN', 'scope_confirmed':False}
                deliveries.append(build_delivery(raw, meta, {'core.lef':{'file_key':name + ':lef:core'}}))
            cfg = {'formal_nl_id':'NL1', 'root':str(formal)}
            actual_walk = os.walk
            with patch('os.walk', wraps=actual_walk) as walk:
                first = sync_formal(base / 'runs', cfg, deliveries, work)
            self.assertEqual(walk.call_count, 1, 'NL 目录同步时应只盘点一次')
            self.assertEqual(len(first['snapshots']), 2)
            for name in ('one', 'two'):
                folder = work / 'libraries' / 'vendor' / name
                self.assertEqual(len(list(folder.glob('formal_NL1_*.json'))), 1)
            self.assertEqual(len(load_catalog(work)[1]), 2)
            second = sync_formal(base / 'runs', cfg, deliveries, work)
            self.assertTrue(all(row['action'] == 'REUSED' for row in second['snapshots']))
            (formal / 'one.lef').unlink()
            (base / 'one' / 'new.lef').write_text('new')
            (formal / 'one_new.lef').symlink_to(base / 'one' / 'new.lef')
            meta = {'delivery_id':'d_one2','vendor_id':'vendor','source_library_id':'one',
                    'supplier_version':'v2','delivery_order':2,'received_at':'2026-11-18T00:00:00Z','package_mode':'UNKNOWN'}
            deliveries.append(build_delivery(base/'one',meta,{'new.lef':{'file_key':'one:lef:core'}}))
            third = sync_formal(base/'runs',cfg,deliveries,work)
            actions={row['library']:row for row in third['snapshots']}
            self.assertEqual(actions['one']['action'],'CREATED')
            self.assertEqual(actions['two']['action'],'REUSED')
            snaps=load_catalog(work)[1]
            current=next(s for s in snaps if s['formal_snapshot_id']==actions['one']['snapshot_id'])
            previous=next(row['snapshot_id'] for row in first['snapshots'] if row['library']=='one')
            self.assertEqual(current['previous_snapshot_id'],previous)
            limited = sync_formal(base/'runs', {**cfg, 'libraries':[{'vendor_id':'vendor','source_library_id':'two'}]}, deliveries, work)
            self.assertEqual([row['library'] for row in limited['snapshots']], ['two'])
            self.assertEqual(next(f for f in limited['files'] if f['path']=='one_new.lef')['source_status'], 'OUT_OF_SCOPE')

    def test_losing_last_link_is_reported_without_rewriting_history(self):
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp); work=base/'work'; work.mkdir(); raw=base/'raw'; raw.mkdir()
            formal=base/'formal'; formal.mkdir(); (raw/'x.lef').write_text('LEF')
            (formal/'x.lef').symlink_to(raw/'x.lef')
            meta={'delivery_id':'d','vendor_id':'v','source_library_id':'lib','supplier_version':'v1',
                  'delivery_order':1,'received_at':'2026-11-17T00:00:00Z','package_mode':'UNKNOWN'}
            delivery=build_delivery(raw,meta,{'x.lef':{'file_key':'lib:lef:x'}})
            cfg={'formal_nl_id':'NL','root':str(formal)}
            first=sync_formal(base/'runs',cfg,[delivery],work)
            (formal/'x.lef').unlink()
            second=sync_formal(base/'runs',cfg,[delivery],work)
            self.assertEqual(second['snapshots'][0]['action'],'NONE')
            self.assertIn('无唯一归属',second['snapshots'][0]['note'])
            self.assertEqual(len(load_catalog(work)[1]),1)
            self.assertEqual(first['snapshot_action'],'CREATED')

    def test_unknown_slot_in_other_library_does_not_block_known_library(self):
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp); work=base/'work'; work.mkdir(); formal=base/'formal'; formal.mkdir()
            deliveries=[]
            for name in ('known','unknown'):
                raw=base/name; raw.mkdir(); (raw/'x.lef').write_text('LEF')
                (formal/(name+'.lef')).symlink_to(raw/'x.lef')
                meta={'delivery_id':'d_'+name,'vendor_id':'v','source_library_id':name,'supplier_version':'v1',
                      'delivery_order':1,'received_at':'2026-11-17T00:00:00Z','package_mode':'UNKNOWN'}
                mapping={'x.lef':{'file_key':'known:lef:x'}} if name=='known' else {}
                deliveries.append(build_delivery(raw,meta,mapping))
            result=sync_formal(base/'runs',{'formal_nl_id':'NL','root':str(formal)},deliveries,work)
            self.assertTrue(any(x['library']=='known' and x['action']=='CREATED' for x in result['snapshots']))
            for snap in load_catalog(work)[1]: self.assertEqual(snap['coverage'],'PARTIAL')

    def test_same_reference_across_vendors_is_not_published_as_a_match(self):
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp); work=base/'work'; work.mkdir(); formal=base/'formal'; formal.mkdir()
            deliveries=[]
            for vendor in ('vendor_a','vendor_b'):
                raw=base/vendor; raw.mkdir(); (raw/'x.lef').write_text('LEF')
                (formal/(vendor+'.lef')).symlink_to(raw/'x.lef')
                meta={'delivery_id':'same','vendor_id':vendor,'source_library_id':'lib','supplier_version':'v1',
                      'delivery_order':1,'received_at':'2026-11-17T00:00:00Z','package_mode':'UNKNOWN'}
                deliveries.append(build_delivery(raw,meta,{'x.lef':{'file_key':'lib:lef:x'}}))
            result=sync_formal(base/'runs',{'formal_nl_id':'NL','root':str(formal)},deliveries,work)
            self.assertEqual([x['action'] for x in result['snapshots']],['NONE','NONE'])
            self.assertTrue(all('不唯一' in x['note'] for x in result['snapshots']))
            self.assertEqual(load_catalog(work)[1],[])

    def test_link_changed_after_observation_is_not_published(self):
        from ai_lib_qor.sources.snapshot_builder import build_snapshot
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp); work=base/'work'; work.mkdir(); raw=base/'raw'; raw.mkdir()
            formal=base/'formal'; formal.mkdir()
            (raw/'x.lef').write_text('x'); (raw/'y.lef').write_text('y')
            link=formal/'x.lef'; link.symlink_to(raw/'x.lef')
            meta={'delivery_id':'d','vendor_id':'v','source_library_id':'lib','supplier_version':'v1',
                  'delivery_order':1,'received_at':'2026-11-17T00:00:00Z','package_mode':'UNKNOWN'}
            record=build_delivery(raw,meta,{'x.lef':{'file_key':'lib:lef:x'}})
            def change_then_build(*args,**kwargs):
                link.unlink(); link.symlink_to(raw/'y.lef')
                return build_snapshot(*args,**kwargs)
            with patch('ai_lib_qor.sources.snapshot_builder.build_snapshot',side_effect=change_then_build):
                result=sync_formal(base/'runs',{'formal_nl_id':'NL','root':str(formal)},[record],work)
            self.assertEqual(result['snapshots'][0]['action'],'NONE')
            self.assertIn('变化',result['snapshots'][0]['note'])
            self.assertEqual(load_catalog(work)[1],[])


if __name__ == '__main__': unittest.main()
