import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ai_lib_qor.sources.delivery_builder import build_delivery
from ai_lib_qor.sources.formal_sync import sync_formal
from ai_lib_qor.application.data_query import LibraryDataQuery
from ai_lib_qor.application.simple_sources import simple_formal


class FormalLinkTargetTests(unittest.TestCase):
    def test_formal_comparison_distinguishes_real_link_observation_and_stale_archive(self):
        from ai_lib_qor.application.simple_sources import simple_raw
        from ai_lib_qor.application.effective_json import create_revision
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp);work=base/'work';work.mkdir();raw=base/'raw';raw.mkdir()
            (raw/'core.lef').write_text('LEF');formal=base/'formal';formal.mkdir()
            link=formal/'core.lef';link.symlink_to('../raw/core.lef')
            meta={'delivery_id':'d1','vendor_id':'v','source_library_id':'lib','supplier_version':'V01',
                  'delivery_order':1,'received_at':'2026-11-18T00:00:00Z','package_mode':'UNKNOWN'}
            delivery=build_delivery(raw,meta,{'core.lef':{'file_key':'lib:lef:core'}})
            folder=work/'libraries/v/lib';folder.mkdir(parents=True)
            delivery_path=folder/'delivery_001.json';delivery_path.write_text(json.dumps(delivery))
            observed=sync_formal(base/'runs',{'formal_nl_id':'NL1','root':str(formal)},[delivery],work)
            self.assertEqual(observed['snapshot_action'],'CREATED')
            snap=json.loads((folder/'formal_NL1_001.json').read_text());entry=snap['linked_files'][0]
            self.assertEqual(entry['link_target'],os.readlink(link))
            self.assertEqual(entry['resolved_path'],str(link.resolve(strict=True)))
            self.assertEqual(entry['resolved_path'],str(raw/'core.lef'))
            self.assertEqual(entry['source_match'],'MATCHED_RAW')
            self.assertEqual(entry['source_ref']['delivery_id'],delivery['delivery_id'])
            q=LibraryDataQuery(work,base/'runs')
            rev=create_revision(simple_raw(q,'v','lib','V01'),owner={'type':'SOURCE_LIBRARY','id':'lib'},revision='rev_0001',created_at='2026-01-01',include_views=['LEF'])
            (folder/'effective_lib_001.json').write_text(json.dumps(rev))
            def compare():
                q=LibraryDataQuery(work,base/'runs')
                return q.compare_formal_vs_effective('v','lib','NL1',observed['snapshot_id'],'lib','rev_0001')['files'][0]
            with patch('os.readlink',side_effect=AssertionError('普通查询不得重读链接')):
                same=compare()
            self.assertEqual(same['relation'],'SAME_SOURCE')
            self.assertEqual(same['archived_path_status'],'MATCH')
            self.assertEqual(same['verification_scope'],'ARCHIVED_RECORDS_ONLY')
            # Simulate a copied Delivery whose root no longer matches the archived observation.
            other=base/'other';other.mkdir();(other/'core.lef').write_text('LEF')
            delivery['source_root']=str(other);delivery_path.write_text(json.dumps(delivery))
            stale=compare()
            self.assertEqual(stale['archived_path_status'],'MISMATCH_OR_INDIRECT')
            self.assertEqual(stale['relation'],'UNKNOWN')

    def test_link_update_failure_reports_published_snapshot(self):
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp);work=base/'work';work.mkdir();raw=base/'raw';raw.mkdir();(raw/'core.lef').write_text('LEF')
            formal=base/'formal';formal.mkdir();(formal/'core.lef').symlink_to(raw/'core.lef')
            meta={'delivery_id':'d1','vendor_id':'v','source_library_id':'lib','supplier_version':'V01','delivery_order':1,'received_at':'2026-11-18T00:00:00Z','package_mode':'UNKNOWN'}
            delivery=build_delivery(raw,meta,{'core.lef':{'file_key':'lib:lef:core'}})
            with patch('ai_lib_qor.application.latest_pointers.refresh_formal_locked',side_effect=OSError('链接写入失败')):
                result=sync_formal(base/'runs',{'formal_nl_id':'NL1','root':str(formal)},[delivery],work)
            row=result['snapshots'][0]
            self.assertEqual(row['action'],'CREATED');self.assertIn('链接',row['note'])
            self.assertEqual(result['status'],'PARTIAL')
            self.assertTrue((work/'libraries/v/lib/formal_NL1_001.json').is_file())
    def test_non_object_snapshot_reports_validation_error(self):
        from ai_lib_qor.versions.store import validate
        with self.assertRaises(ValueError):validate([], 'formal_snapshot')

    def test_relative_target_is_immutable_and_text_change_creates_snapshot(self):
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp);work=base/'work';work.mkdir();raw=base/'raw';raw.mkdir();(raw/'core.lef').write_text('LEF')
            formal=base/'formal';formal.mkdir();link=formal/'core.lef';link.symlink_to('../raw/core.lef')
            meta={'delivery_id':'d1','vendor_id':'v','source_library_id':'lib','supplier_version':'V01',
                  'delivery_order':1,'received_at':'2026-11-18T00:00:00Z','package_mode':'UNKNOWN'}
            delivery=build_delivery(raw,meta,{'core.lef':{'file_key':'lib:lef:core'}})
            folder=work/'libraries/v/lib';folder.mkdir(parents=True);(folder/'delivery_001.json').write_text(json.dumps(delivery))
            cfg={'formal_nl_id':'NL1','root':str(formal)}
            first=sync_formal(base/'runs',cfg,[delivery],work)
            self.assertTrue((folder/'latest_formal_NL1.json').is_symlink())
            self.assertEqual(os.readlink(folder/'latest_formal_NL1.json'),'formal_NL1_001.json')
            snap=json.loads((folder/'formal_NL1_001.json').read_text())
            self.assertEqual(snap['schema_version'],'formal_snapshot.v2')
            self.assertEqual(snap['linked_files'][0]['link_target'],'../raw/core.lef')
            self.assertEqual(first['files'][0]['link_target'],'../raw/core.lef')
            link.unlink();link.symlink_to(raw/'core.lef')
            second=sync_formal(base/'runs',cfg,[delivery],work)
            self.assertEqual(os.readlink(folder/'latest_formal_NL1.json'),'formal_NL1_002.json')
            self.assertEqual(second['snapshot_action'],'CREATED')
            self.assertNotEqual(first['snapshot_id'],second['snapshot_id'])
            self.assertEqual(json.loads((folder/'formal_NL1_001.json').read_text())['linked_files'][0]['link_target'],'../raw/core.lef')
            self.assertEqual(json.loads((folder/'formal_NL1_002.json').read_text())['linked_files'][0]['link_target'],str(raw/'core.lef'))
            with patch('os.walk',side_effect=AssertionError('查询不得重新扫描')), patch('os.readlink',side_effect=AssertionError('查询不得重新读取链接')):
                q=LibraryDataQuery(work,base/'runs');view=simple_formal(q,'v','lib','NL1',first['snapshot_id'])
            self.assertEqual(view['schema'],'formal.simple.v3')
            self.assertEqual(view['views']['LEF']['core.lef']['link_target'],'../raw/core.lef')
            (raw/'core.lef').unlink()
            broken=sync_formal(base/'runs',cfg,[delivery],work)
            self.assertEqual(broken['status'],'PARTIAL')
            self.assertEqual(broken['files'][0]['link_status'],'BROKEN')
            self.assertEqual(broken['files'][0]['link_target'],str(raw/'core.lef'))
            self.assertEqual(len(list(folder.glob('formal_NL1_*.json'))),2)

    def test_broken_and_regular_file_observation(self):
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp);formal=base/'formal';formal.mkdir()
            (formal/'missing.lef').symlink_to('../raw/missing.lef');(formal/'regular.txt').write_text('doc')
            result=sync_formal(base/'runs',{'formal_nl_id':'NL','root':str(formal)},[])
            files={x['path']:x for x in result['files']}
            self.assertEqual(files['missing.lef']['link_target'],'../raw/missing.lef')
            self.assertEqual(files['missing.lef']['link_status'],'BROKEN')
            self.assertIsNone(files['regular.txt']['link_target'])
            self.assertEqual(files['regular.txt']['link_status'],'REGULAR')

    def test_multihop_keeps_final_target_in_addition_to_link_text(self):
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp);work=base/'work';work.mkdir();raw=base/'raw';raw.mkdir();(raw/'core.lef').write_text('LEF')
            alias=base/'alias';alias.mkdir();(alias/'core.lef').symlink_to('../raw/core.lef')
            formal=base/'formal';formal.mkdir();(formal/'core.lef').symlink_to('../alias/core.lef')
            meta={'delivery_id':'d1','vendor_id':'v','source_library_id':'lib','supplier_version':'V01',
                  'delivery_order':1,'received_at':'2026-11-18T00:00:00Z','package_mode':'UNKNOWN'}
            delivery=build_delivery(raw,meta,{'core.lef':{'file_key':'lib:lef:core'}})
            folder=work/'libraries/v/lib';folder.mkdir(parents=True);(folder/'delivery_001.json').write_text(json.dumps(delivery))
            result=sync_formal(base/'runs',{'formal_nl_id':'NL','root':str(formal)},[delivery],work)
            view=simple_formal(LibraryDataQuery(work,base/'runs'),'v','lib','NL',result['snapshot_id'])
            item=view['views']['LEF']['core.lef']
            self.assertEqual(item['link_target'],'../alias/core.lef')
            self.assertEqual(item['resolved_path'],str(raw/'core.lef'))
            from ai_lib_qor.sources.snapshot_builder import build_snapshot
            (raw/'other.lef').write_text('OTHER')
            def swap_intermediate(*args,**kwargs):
                candidate=build_snapshot(*args,**kwargs)
                (alias/'core.lef').unlink();(alias/'core.lef').symlink_to('../raw/other.lef')
                return candidate
            with patch('ai_lib_qor.sources.snapshot_builder.build_snapshot',side_effect=swap_intermediate):
                changed=sync_formal(base/'runs',{'formal_nl_id':'NL','root':str(formal)},[delivery],work)
            self.assertEqual(changed['snapshot_action'],'NONE')
            self.assertIn('解析目标',changed['snapshot_note'])


if __name__=='__main__':unittest.main()
