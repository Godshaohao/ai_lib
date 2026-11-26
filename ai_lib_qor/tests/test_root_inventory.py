import json
import os
import tempfile
import unittest
from pathlib import Path


class RootInventoryTests(unittest.TestCase):
 def test_two_root_split_links_and_repeat(self):
  from ai_lib_qor.sources.root_inventory import build_from_roots
  with tempfile.TemporaryDirectory() as tmp:
   base=Path(tmp);raw=base/'raw';nl=base/'NL2.5.3';out=base/'work'
   a=raw/'VENDOR_A/LIB_A/20261024_abcdef12/LEF/a.lef';a.parent.mkdir(parents=True);a.write_text('LEF')
   b=raw/'VENDOR_B/LIB_B/V02/LIB/a.lib';b.parent.mkdir(parents=True);b.write_text('LIB')
   (nl/'IP/LEF').mkdir(parents=True);(nl/'IP/LIB').mkdir()
   (nl/'IP/LEF/a.lef').symlink_to(os.path.relpath(a,nl/'IP/LEF'))
   (nl/'IP/LIB/a.lib').symlink_to(os.path.relpath(b,nl/'IP/LIB'))
   result=build_from_roots(raw,nl,out,nl_version='NL2.5.3')
   self.assertEqual(result['delivery_created'],2);self.assertEqual(result['formal_created'],2)
   folder=out/'libraries/VENDOR_A/LIB_A'
   delivery=json.loads((folder/'delivery/delivery_LIB_A__20261024_abcdef12.json').read_text())
   self.assertEqual(set(delivery),{'vendor','library','version','version_date','directory_mtime','root','views'})
   self.assertEqual(delivery['version_date'],'2026-10-24')
   self.assertRegex(delivery['directory_mtime'],r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$')
   formal_path=next(folder.glob('formal/formal_NL2.5.3_*.json'))
   self.assertRegex(formal_path.name,r'^formal_NL2\.5\.3_\d{8}T\d{6}Z_\d{3}\.json$')
   formal=json.loads(formal_path.read_text())
   self.assertRegex(formal['observed_at'],r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$')
   self.assertEqual(set(formal),{'version','vendor','library','root','observed_at','views'})
   link=formal['views']['LEF']['20261024_abcdef12'][0]
   self.assertEqual(link,{'path':'IP/LEF/a.lef','target':os.readlink(nl/'IP/LEF/a.lef'),'resolved':str(a)})
   self.assertNotIn('delivery_id',json.dumps(formal));self.assertNotIn('file_id',json.dumps(formal))
   (nl/'IP/LEF/broken.lef').symlink_to('/missing/file.lef')
   repeat=build_from_roots(raw,nl,out,nl_version='NL2.5.3')
   self.assertTrue(any('broken.lef' in e for e in repeat['warnings']))
   self.assertEqual(repeat['delivery_created'],0);self.assertEqual(repeat['formal_created'],0)
   self.assertEqual(len(list(folder.glob('delivery/delivery_*.json'))),1)
   self.assertEqual((folder/'latest_delivery.json').readlink().name,'delivery_LIB_A__20261024_abcdef12.json')
   self.assertTrue((out/'libraries/VENDOR_B/LIB_B/delivery/delivery_LIB_B__V02.json').is_file())
   from ai_lib_qor.application.minimal_effective import initialize_from_formal,update_effective
   result=initialize_from_formal(out,'VENDOR_A','LIB_A',formal_path)
   self.assertEqual(result['revision'],'rev_0001')
   effective=json.loads((folder/'effective/effective_LIB_A_001.json').read_text())
   self.assertRegex(effective['created_at'],r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$')
   self.assertEqual(effective['views']['LEF']['20261024_abcdef12'],['LEF/a.lef'])
   self.assertEqual((folder/'latest_effective.json').readlink().name,'effective_LIB_A_001.json')
   updated=update_effective(out,'VENDOR_A','LIB_A',{'set':[],'remove':[{'view':'LEF','path':'LEF/a.lef'}]})
   self.assertEqual(updated['revision'],'rev_0002')
   self.assertEqual(json.loads((folder/'effective/effective_LIB_A_002.json').read_text())['views'],{})

 def test_nonempty_output_inside_raw_or_formal_is_refused(self):
  from ai_lib_qor.sources.root_inventory import build_from_roots
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);(root/'raw').mkdir();(root/'NL1').mkdir()
   with self.assertRaises(ValueError):build_from_roots(root/'raw',root/'NL1',root/'raw/output',nl_version='NL1')

 def test_date_version_accepts_short_non_hash_suffix(self):
  from ai_lib_qor.sources.root_inventory import _version_directory
  self.assertTrue(_version_directory('20261001_a1'))
  self.assertFalse(_version_directory('20261340_bad'))

 def test_two_changed_five_inherited_and_replay(self):
  from ai_lib_qor.sources.root_inventory import build_from_roots
  from ai_lib_qor.application.minimal_effective import initialize_from_formal,update_effective
  with tempfile.TemporaryDirectory() as tmp:
   base=Path(tmp);raw=base/'raw';nl=base/'NL2.5.3';work=base/'work';old=raw/'v/lib/20261001_abcdef12';new=raw/'v/lib/20261002_abcdef12'
   paths=['a.lef','b.lib','c.lib','d.lib','e.gds','f.spice','g.v']
   nl.mkdir()
   for name in paths:
    f=old/name;f.parent.mkdir(parents=True,exist_ok=True);f.write_text(name)
    (nl/name).symlink_to(f)
   for name in paths[:2]:
    f=new/name;f.parent.mkdir(parents=True,exist_ok=True);f.write_text(name+'new')
   build_from_roots(raw,nl,work)
   folder=work/'libraries/v/lib';initialize_from_formal(work,'v','lib',next(folder.glob('formal/formal_NL2.5.3_*.json')))
   actions={'set':[{'view':'LEF','version':new.name,'path':'a.lef'},{'view':'LIBERTY','version':new.name,'path':'b.lib'}],'remove':[]}
   self.assertEqual(update_effective(work,'v','lib',actions)['revision'],'rev_0002')
   views=json.loads((folder/'effective/effective_lib_002.json').read_text())['views']
   self.assertEqual(sum(len(paths) for versions in views.values() for paths in versions.values()),7)
   self.assertEqual(sum(len(paths) for versions in views.values() for version,paths in versions.items() if version==new.name),2)
   self.assertEqual(sum(len(paths) for versions in views.values() for version,paths in versions.items() if version==old.name),5)
   index=json.loads((folder/'file_index.json').read_text());self.assertEqual(index['revisions'],['rev_0001','rev_0002'])
   rows=[entry for group in index['views'].values() for entry in group.values()]
   self.assertEqual(sum(1 for row in rows if len(row['effective'])==2 and row['effective'][0]['version']!=row['effective'][1]['version']),2)
   self.assertEqual(sum(1 for row in rows if len(row['effective'])==2 and row['effective'][0]['version']==row['effective'][1]['version']),5)
   self.assertEqual(update_effective(work,'v','lib',actions)['state'],'UNCHANGED')
   self.assertEqual((folder/'latest_effective.json').readlink().name,'effective_lib_002.json')

 def test_ambiguous_order_does_not_invent_latest(self):
  from ai_lib_qor.sources.root_inventory import build_from_roots
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);raw=root/'raw';nl=root/'NL1';nl.mkdir()
   same_ts=1767225600
   for version in ('20260101_a','20260101_b'):
    vdir=raw/'v/lib'/version;f=vdir/'a.lef';f.parent.mkdir(parents=True);f.write_text('LEF')
    os.utime(vdir,(same_ts,same_ts))
   result=build_from_roots(raw,nl,root/'work')
   self.assertTrue(any('次序未确认' in x for x in result['warnings']))
   self.assertFalse((root/'work/libraries/v/lib/latest_delivery.json').exists())

 def test_undated_and_same_day_versions_order_by_mtime_while_directory_date_takes_priority(self):
  from ai_lib_qor.sources.root_inventory import build_from_roots
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);raw=root/'raw';nl=root/'NL1';nl.mkdir();work=root/'work'
   # 1) Undated versions with distinct directory mtime: ordered by mtime without version_registration_times
   v1=raw/'v/undated_lib/V01';(v1/'a.lef').parent.mkdir(parents=True);(v1/'a.lef').write_text('v1')
   v2=raw/'v/undated_lib/V02';(v2/'a.lef').parent.mkdir(parents=True);(v2/'a.lef').write_text('v2')
   os.utime(v1,(1767268800,1767268800))  # 2026-01-01T12:00:00Z
   os.utime(v2,(1767355200,1767355200))  # 2026-01-02T12:00:00Z
   # 2) Dated versions where older date has NEWER mtime: directory version_date MUST win over mtime
   d_old=raw/'v/dated_lib/20260101_old';(d_old/'a.lef').parent.mkdir(parents=True);(d_old/'a.lef').write_text('old')
   d_new=raw/'v/dated_lib/20260105_new';(d_new/'a.lef').parent.mkdir(parents=True);(d_new/'a.lef').write_text('new')
   os.utime(d_old,(1767960000,1767960000))  # 2026-01-09T12:00:00Z (copied later!)
   os.utime(d_new,(1767614400,1767614400))  # 2026-01-05T12:00:00Z
   # 3) Same-day dated versions with distinct mtime: tie broken by mtime without registration config
   s1=raw/'v/sameday_lib/20260201_b';(s1/'a.lef').parent.mkdir(parents=True);(s1/'a.lef').write_text('s1')
   s2=raw/'v/sameday_lib/20260201_a';(s2/'a.lef').parent.mkdir(parents=True);(s2/'a.lef').write_text('s2')
   os.utime(s1,(1769932800,1769932800))  # 2026-02-01T08:00:00Z
   os.utime(s2,(1769936400,1769936400))  # 2026-02-01T09:00:00Z

   build_from_roots(raw,nl,work)

   u_folder=work/'libraries/v/undated_lib'
   self.assertTrue((u_folder/'delivery/delivery_undated_lib__V01.json').is_file())
   self.assertTrue((u_folder/'delivery/delivery_undated_lib__V02.json').is_file())
   self.assertEqual((u_folder/'latest_delivery.json').readlink().name,'delivery_undated_lib__V02.json')
   u_idx=json.loads((u_folder/'file_index.json').read_text())
   self.assertEqual([d['version'] for d in u_idx['deliveries']],['V01','V02'])

   d_folder=work/'libraries/v/dated_lib'
   self.assertEqual((d_folder/'latest_delivery.json').readlink().name,'delivery_dated_lib__20260105_new.json')
   d_idx=json.loads((d_folder/'file_index.json').read_text())
   self.assertEqual([d['version'] for d in d_idx['deliveries']],['20260101_old','20260105_new'])

   s_folder=work/'libraries/v/sameday_lib'
   self.assertEqual((s_folder/'latest_delivery.json').readlink().name,'delivery_sameday_lib__20260201_a.json')
   s_idx=json.loads((s_folder/'file_index.json').read_text())
   self.assertEqual([d['version'] for d in s_idx['deliveries']],['20260201_b','20260201_a'])

 def test_legacy_seven_field_delivery_coexists_with_new_mtime_delivery(self):
  import ai_lib_qor.sources.minimal_delivery as md
  from ai_lib_qor.sources.root_inventory import build_from_roots
  from ai_lib_qor.versions.store import validate, write_atomic
  self.assertFalse(hasattr(md, 'directory_birthtime'))
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);raw=root/'raw';nl=root/'NL1';nl.mkdir();work=root/'work'
   v1=raw/'v/lib/20260101_r1';(v1/'a.lef').parent.mkdir(parents=True);(v1/'a.lef').write_text('v1')
   folder=work/'libraries/v/lib'
   (folder/'delivery').mkdir(parents=True)
   # Seed legacy 7-field delivery (old filename & legacy directory_created_at)
   legacy={
    'vendor':'v','library':'lib','version':'20260101_r1','version_date':'2026-01-01',
    'directory_created_at':None,'root':str(v1),'views':{'LEF':['a.lef']},
   }
   write_atomic(folder/'delivery/delivery_lib_20260101_001.json',legacy)
   # Invalid mixed delivery with both directory_created_at and directory_mtime must be rejected
   with self.assertRaisesRegex(ValueError,'Schema'):
    validate({**legacy,'directory_mtime':'2026-01-01T00:00:00Z'},'delivery_minimal')
   # Add new second version on disk
   v2=raw/'v/lib/20260102_r2';(v2/'a.lef').parent.mkdir(parents=True);(v2/'a.lef').write_text('v2')
   res=build_from_roots(raw,nl,work)
   self.assertEqual(res['delivery_created'],1)
   self.assertEqual(res['delivery_unchanged'],1)
   self.assertEqual(res['warnings'],[])
   new_file=folder/'delivery/delivery_lib__20260102_r2.json'
   self.assertTrue(new_file.is_file())
   new_doc=json.loads(new_file.read_text())
   self.assertEqual(set(new_doc),{'vendor','library','version','version_date','directory_mtime','root','views'})
   self.assertEqual((folder/'latest_delivery.json').readlink().name,'delivery_lib__20260102_r2.json')
   idx=json.loads((folder/'file_index.json').read_text())
   self.assertEqual([d['version'] for d in idx['deliveries']],['20260101_r1','20260102_r2'])

 def test_mtime_ordering_mixed_and_registration_override_and_mtime_drift_warning(self):
  from ai_lib_qor.sources.minimal_delivery import order_deliveries
  from ai_lib_qor.sources.root_inventory import build_from_roots
  # Mixed dated + undated: version_date day compared against undated mtime day
  rows=[
   {'version':'20260105_dated','version_date':'2026-01-05','directory_mtime':'2026-01-20T00:00:00Z'},
   {'version':'V01','version_date':None,'directory_mtime':'2026-01-02T08:00:00Z'},
   {'version':'V02','version_date':None,'directory_mtime':'2026-01-10T08:00:00Z'},
  ]
  self.assertEqual([r['version'] for r in order_deliveries(rows,{})],['V01','20260105_dated','V02'])
  # Explicit version_registration_times overrides directory_mtime
  undated=[
   {'version':'V01','version_date':None,'directory_mtime':'2026-01-10T08:00:00Z'},
   {'version':'V02','version_date':None,'directory_mtime':'2026-01-02T08:00:00Z'},
  ]
  self.assertEqual([r['version'] for r in order_deliveries(undated,{})],['V02','V01'])
  self.assertEqual(
   [r['version'] for r in order_deliveries(undated,{'V01':'2026-01-01T00:00:00Z','V02':'2026-01-03T00:00:00Z'})],
   ['V01','V02'],
  )
  # Directory mtime change on disk warns without overwriting archived immutable delivery
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);raw=root/'raw';work=root/'work'
   vdir=raw/'v/lib/V01';(vdir/'a.lef').parent.mkdir(parents=True);(vdir/'a.lef').write_text('x')
   os.utime(vdir,(1767268800,1767268800))
   build_from_roots(raw,None,work,update_formal=False)
   dfile=work/'libraries/v/lib/delivery/delivery_lib__V01.json'
   before=dfile.read_bytes()
   os.utime(vdir,(1767355200,1767355200))
   res=build_from_roots(raw,None,work,update_formal=False)
   self.assertTrue(any('目录修改时间(mtime)' in w for w in res['warnings']))
   self.assertEqual(dfile.read_bytes(),before)

 def test_same_second_snapshot_changes_are_numbered_and_latest_is_correct(self):
  from unittest.mock import patch
  from ai_lib_qor.sources.root_inventory import build_from_roots
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);raw=root/'raw';nl=root/'NL1';nl.mkdir();work=root/'work'
   for v in ('20261001_abcdef12','20261002_abcdef12'):
    p=raw/'v/lib'/v/'a.lef';p.parent.mkdir(parents=True);p.write_text(v)
   link=nl/'a.lef';link.symlink_to(raw/'v/lib/20261001_abcdef12/a.lef')
   with patch('ai_lib_qor.sources.root_inventory.utc_text',return_value='2026-11-20T12:34:56Z'):
    build_from_roots(raw,nl,work);link.unlink();link.symlink_to(raw/'v/lib/20261002_abcdef12/a.lef')
    build_from_roots(raw,nl,work);result=build_from_roots(raw,nl,work)
   folder=work/'libraries/v/lib';files=sorted(p.name for p in folder.glob('formal/formal_NL1_*.json'))
   self.assertEqual(files,['formal_NL1_20261120T123456Z_001.json','formal_NL1_20261120T123456Z_002.json'])
   self.assertEqual((folder/'latest_formal_NL1.json').readlink().name,files[-1])
   self.assertEqual(result['formal_unchanged'],1)

 def test_update_options_index_only_does_not_scan_raw_or_nl(self):
  from unittest.mock import patch
  from ai_lib_qor.sources.root_inventory import build_from_roots
  with tempfile.TemporaryDirectory() as tmp:
   base=Path(tmp);raw=base/'raw';nl=base/'NL1';nl.mkdir();work=base/'work'
   p=raw/'v/lib/20261001_abcdef12/LEF/a.lef';p.parent.mkdir(parents=True);p.write_text('x')
   build_from_roots(raw,nl,work)
   with patch('os.walk',side_effect=AssertionError('仅索引更新不能扫描来源')):
    result=build_from_roots(None,None,work,update_raw=False,update_formal=False,update_index=True)
   self.assertEqual(result['indexes_unchanged'],1)

 def test_raw_only_does_not_observe_nl(self):
  from unittest.mock import patch
  from ai_lib_qor.sources.root_inventory import build_from_roots
  with tempfile.TemporaryDirectory() as tmp:
   base=Path(tmp);raw=base/'raw';p=raw/'v/lib/20261001_abcdef12/a.lef';p.parent.mkdir(parents=True);p.write_text('x')
   with patch('ai_lib_qor.sources.root_inventory._inventory_formal',side_effect=AssertionError('不应盘点 NL')):
    result=build_from_roots(raw,None,base/'work',update_formal=False)
   self.assertEqual(result['delivery_created'],1)
