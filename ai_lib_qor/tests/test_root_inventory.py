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
   (nl/'IP/LEF/broken.lef').symlink_to('/missing/file.lef')
   result=build_from_roots(raw,nl,out,nl_version='NL2.5.3')
   self.assertEqual(result['delivery_created'],2);self.assertEqual(result['formal_created'],2)
   self.assertTrue(any('broken.lef' in e for e in result['warnings']))
   folder=out/'libraries/VENDOR_A/LIB_A'
   delivery=json.loads((folder/'delivery_LIB_A_20261024_001.json').read_text())
   self.assertEqual(set(delivery),{'vendor','library','version','version_date','directory_created_at','root','views'})
   self.assertEqual(delivery['version_date'],'2026-10-24')
   formal_path=next(folder.glob('formal_NL2.5.3_*.json'))
   self.assertRegex(formal_path.name,r'^formal_NL2\.5\.3_\d{8}T\d{6}Z_\d{3}\.json$')
   formal=json.loads(formal_path.read_text())
   self.assertRegex(formal['observed_at'],r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$')
   if delivery['directory_created_at'] is not None:self.assertRegex(delivery['directory_created_at'],r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$')
   self.assertEqual(set(formal),{'version','vendor','library','root','observed_at','views'})
   link=formal['views']['LEF']['20261024_abcdef12'][0]
   self.assertEqual(link,{'path':'IP/LEF/a.lef','target':os.readlink(nl/'IP/LEF/a.lef'),'resolved':str(a)})
   self.assertNotIn('delivery_id',json.dumps(formal));self.assertNotIn('file_id',json.dumps(formal))
   repeat=build_from_roots(raw,nl,out,nl_version='NL2.5.3')
   self.assertEqual(repeat['delivery_created'],0);self.assertEqual(repeat['formal_created'],0)
   self.assertEqual(len(list(folder.glob('delivery_*.json'))),1)
   self.assertEqual((folder/'latest_delivery.json').readlink().name,'delivery_LIB_A_20261024_001.json')
   from ai_lib_qor.application.minimal_effective import initialize_from_formal,update_effective
   result=initialize_from_formal(out,'VENDOR_A','LIB_A',formal_path)
   self.assertEqual(result['revision'],'rev_0001')
   effective=json.loads((folder/'effective_LIB_A_001.json').read_text())
   self.assertRegex(effective['created_at'],r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$')
   self.assertEqual(effective['views']['LEF']['20261024_abcdef12'],['LEF/a.lef'])
   self.assertEqual((folder/'latest_effective.json').readlink().name,'effective_LIB_A_001.json')
   updated=update_effective(out,'VENDOR_A','LIB_A',{'set':[],'remove':[{'view':'LEF','path':'LEF/a.lef'}]})
   self.assertEqual(updated['revision'],'rev_0002')
   self.assertEqual(json.loads((folder/'effective_LIB_A_002.json').read_text())['views'],{})

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
   folder=work/'libraries/v/lib';initialize_from_formal(work,'v','lib',next(folder.glob('formal_NL2.5.3_*.json')))
   actions={'set':[{'view':'LEF','version':new.name,'path':'a.lef'},{'view':'LIBERTY','version':new.name,'path':'b.lib'}],'remove':[]}
   self.assertEqual(update_effective(work,'v','lib',actions)['revision'],'rev_0002')
   views=json.loads((folder/'effective_lib_002.json').read_text())['views']
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
   for version in ('V01','V02'):
    f=raw/'v/lib'/version/'a.lef';f.parent.mkdir(parents=True);f.write_text('LEF')
   result=build_from_roots(raw,nl,root/'work')
   self.assertTrue(any('次序未确认' in x for x in result['warnings']))
   self.assertFalse((root/'work/libraries/v/lib/latest_delivery.json').exists())

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
   folder=work/'libraries/v/lib';files=sorted(p.name for p in folder.glob('formal_NL1_*.json'))
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
