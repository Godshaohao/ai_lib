import copy
import unittest
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from ai_lib_qor.application.effective_json import create_revision

class EffectiveJsonTests(unittest.TestCase):
    def setUp(self):
        self.raw={'schema':'raw.simple.v1','delivery_id':'delivery_005',
            'context':{'vendor':'A','library':'L','version':'V05','root':'/offline/V05'},
            'views':{'LEF':['LEF/a.lef'],'LIBERTY':{'NLDM':['LIB/ff.lib','LIB/ss.lib']},'GDS':['GDS/a.gds']}}
        self.owner={'type':'SOURCE_LIBRARY','id':'L'}
    def test_initial_and_incremental_inheritance(self):
        a=create_revision(self.raw,owner=self.owner,revision='rev_0001',created_at='2026-11-18T00:00:00Z',include_views=['LEF','LIBERTY','GDS'])
        self.assertEqual(a['views']['LIBERTY']['NLDM']['LIB/ss.lib'],'V05')
        b=copy.deepcopy(self.raw);b['delivery_id']='delivery_006';b['context']['version']='V06'
        b['views']={'LEF':['LEF/a.lef'],'LIBERTY':{'NLDM':['LIB/ff.lib']}}
        c=create_revision(b,owner=self.owner,revision='rev_0002',created_at='2026-11-18T00:00:00Z',include_views=['LEF','LIBERTY'],parent=a)
        self.assertEqual(c['views']['LEF']['LEF/a.lef'],'V06')
        self.assertEqual(c['views']['LIBERTY']['NLDM']['LIB/ss.lib'],'V05')
        self.assertEqual(c['views']['GDS']['GDS/a.gds'],'V05')
        self.assertEqual(c['sources'],{'V05':'delivery_005','V06':'delivery_006'})
        self.assertEqual(c['parent'],'rev_0001')
        self.assertNotIn('changes',c)
    def test_reject_ambiguous_same_version_and_wrong_scope(self):
        a=create_revision(self.raw,owner=self.owner,revision='rev_0001',created_at='now',include_views=['LEF'])
        b=copy.deepcopy(self.raw);b['delivery_id']='different'
        with self.assertRaisesRegex(ValueError,'版本'):
            create_revision(b,owner=self.owner,revision='rev_0002',created_at='now',include_views=['LEF'],parent=a)
        b=copy.deepcopy(self.raw);b['context']['vendor']='B';b['context']['version']='V06'
        with self.assertRaisesRegex(ValueError,'范围'):
            create_revision(b,owner=self.owner,revision='rev_0002',created_at='now',include_views=['LEF'],parent=a)
    def test_empty_selection_and_unsafe_path_rejected(self):
        with self.assertRaises(ValueError):create_revision(self.raw,owner=self.owner,revision='rev_0001',created_at='now',include_views=[])
        self.raw['views']['LEF']=['../escape']
        with self.assertRaises(ValueError):create_revision(self.raw,owner=self.owner,revision='rev_0001',created_at='now',include_views=['LEF'])
    def test_reject_parent_with_missing_source(self):
        parent=create_revision(self.raw,owner=self.owner,revision='rev_0001',created_at='now',include_views=['LEF'])
        parent['sources'].clear()
        with self.assertRaisesRegex(ValueError,'无法解析'):
            create_revision(self.raw,owner=self.owner,revision='rev_0002',created_at='now',include_views=['LEF'],parent=parent)
    def test_reject_same_path_under_different_subgroup(self):
        parent=create_revision(self.raw,owner=self.owner,revision='rev_0001',created_at='now',include_views=['LIBERTY'])
        updated=copy.deepcopy(self.raw);updated['delivery_id']='delivery_006';updated['context']['version']='V06'
        updated['views']={'LIBERTY':{'CCS':['LIB/ff.lib']}}
        with self.assertRaisesRegex(ValueError,'重复'):
            create_revision(updated,owner=self.owner,revision='rev_0002',created_at='now',include_views=['LIBERTY'],parent=parent)
    def test_cli_build_immutable_and_explicit_view(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); raw=root/'raw.json';out=root/'rev.json';raw.write_text(json.dumps(self.raw))
            args=[sys.executable,'-m','ai_lib_qor','effective-build','--raw',str(raw),'--out',str(out),
                  '--owner-type','SOURCE_LIBRARY','--owner-id','L','--revision','rev_0001','--view','LEF']
            result=subprocess.run(args,text=True,capture_output=True,env=os.environ.copy())
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual(set(json.loads(out.read_text())['views']),{'LEF'})
            result=subprocess.run(args,text=True,capture_output=True,env=os.environ.copy())
            self.assertNotEqual(result.returncode,0)
