import copy
import unittest
from unittest.mock import Mock
from ai_lib_qor.application.effective_json import create_revision, create_formal_revision, compare_revisions, file_timeline

class MigrationTests(unittest.TestCase):
 def setUp(self):
  self.a={'schema':'raw.simple.v1','delivery_id':'delivery_001','context':{'vendor':'A','library':'L1','version':'V1','root':'/v1'},'views':{'LEF':['lef/a.lef']}}
  self.owner={'type':'BUSINESS_IP','id':'IP'}
  self.r1=create_revision(self.a,owner=self.owner,revision='rev_0001',created_at='t1',include_views=['LEF'])
 def test_cross_library_same_version_explicit(self):
  b=copy.deepcopy(self.a);b['context'].update(vendor='B',library='L2');b['delivery_id']='delivery_001'
  b['views']={'LEF':['lef/b.lef']}
  with self.assertRaises(ValueError):create_revision(b,owner=self.owner,revision='rev_0002',created_at='t2',include_views=['LEF'],parent=self.r1)
  r=create_revision(b,owner=self.owner,revision='rev_0002',created_at='t2',include_views=['LEF'],parent=self.r1,allow_cross_library=True)
  k=r['views']['LEF']['lef/b.lef'];self.assertEqual(r['sources'][k],{'vendor':'B','library':'L2','version':'V1','delivery':'delivery_001'})
  self.assertEqual(r['views']['LEF']['lef/a.lef'],'V1')
 def test_formal_baseline_validates_links(self):
  formal={'schema':'formal.simple.v3','snapshot_id':'formal_NL_001','context':{'vendor':'A','library':'L1','version':'NL','root':'/nl','recorded_at':'t'},
          'views':{'LEF':{'nl/a.lef':{'raw_version':'V1','raw_path':'lef/a.lef','link_target':'../v1/lef/a.lef'}}}}
  r=create_formal_revision(formal,[self.a],owner=self.owner,created_at='t1',include_views=['LEF'])
  self.assertEqual(r['formal_baseline'],'formal_NL_001');self.assertEqual(r['views']['LEF']['lef/a.lef'],'V1')
  formal['views']['LEF']['nl/a.lef']['raw_path']='missing';
  with self.assertRaises(ValueError):create_formal_revision(formal,[self.a],owner=self.owner,created_at='t1',include_views=['LEF'])
 def test_formal_cross_library_needs_explicit_permission(self):
  raw=copy.deepcopy(self.a);raw['context'].update(vendor='B',library='L2')
  formal={'schema':'formal.simple.v3','snapshot_id':'snap','context':{'vendor':'A','library':'L1','version':'NL','root':'/nl','recorded_at':'t'},
          'views':{'LEF':{'nl/a':{'vendor':'B','library':'L2','raw_version':'V1','raw_path':'lef/a.lef','link_target':'/v1/lef/a.lef'}}}}
  with self.assertRaisesRegex(ValueError,'跨库'):create_formal_revision(formal,[raw],owner=self.owner,created_at='t1',include_views=['LEF'])
  r=create_formal_revision(formal,[raw],owner=self.owner,created_at='t1',include_views=['LEF'],allow_cross_library=True)
  key=r['views']['LEF']['lef/a.lef'];self.assertEqual(r['sources'][key]['library'],'L2')
 def test_formal_rejects_missing_context_and_link_observation(self):
  formal={'schema':'formal.simple.v3','snapshot_id':'snap','context':{'vendor':'A','library':'L1','version':'NL'},
          'views':{'LEF':{'nl/a':{'raw_version':'V1','raw_path':'lef/a.lef'}}}}
  with self.assertRaisesRegex(ValueError,'Schema'):
   create_formal_revision(formal,[self.a],owner=self.owner,created_at='t1',include_views=['LEF'])
 def test_compare_and_timeline(self):
  b=copy.deepcopy(self.a);b['context']['version']='V2';b['delivery_id']='delivery_002';b['views']['LEF'].append('lef/b.lef')
  r2=create_revision(b,owner=self.owner,revision='rev_0002',created_at='t2',include_views=['LEF'],parent=self.r1)
  diff=compare_revisions(self.r1,r2)
  self.assertEqual({(x['path'],x['change']) for x in diff['files']},{('lef/a.lef','SOURCE_CHANGED'),('lef/b.lef','ADDED')})
  self.assertEqual([x['source']['version'] for x in file_timeline([self.r1,r2],'LEF','lef/a.lef')['versions']],['V1','V2'])
 def test_legacy_cross_library_export_preserves_identity(self):
  from ai_lib_qor.application.simple_sources import simple_effective
  q=Mock();q.work='/work'
  q._revision.return_value={'owner':{'owner_type':'BUSINESS_IP','owner_id':'IP'},'revision_id':'rev_0001',
    'parent_revision_id':None,'created_at':'t','reason':{'kind':'RAW_DELIVERY','ref_id':'d'}}
  q.get_effective_files.return_value={'unresolved':[],'views':{'LEF':{'lef/b.lef':{'vendor':'B','library':'L2','delivery_id':'d',
    'version':'V1','path':'lef/b.lef','view':'LEF'}}}}
  q.deliveries=[{'record':{'vendor_id':'B','source_library_id':'L2','supplier_version':'V1','delivery_id':'d'},
                 'path':'/work/libraries/B/L2/delivery_001.json'}]
  out=simple_effective(q,'A','L1','IP','rev_0001');key=out['views']['LEF']['lef/b.lef']
  self.assertEqual(out['sources'][key],{'vendor':'B','library':'L2','version':'V1','delivery':'delivery_001'})
