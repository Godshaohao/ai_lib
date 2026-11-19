import json
import unittest
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch, Mock

from ai_lib_qor.application.data_query import LibraryDataQuery, query_data

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'exports/flat_library_review_rdyp0zdh'


@unittest.skipUnless(DATA.is_dir(), '本地模拟记录不存在')
class SimpleEffectiveExportTests(unittest.TestCase):
    def test_cli_success_with_sources_dictionary(self):
        proc = subprocess.run([sys.executable, '-m', 'ai_lib_qor', 'data-query', '--kind', 'simple-effective',
                               '--work', str(DATA/'work'), '--runs', str(DATA/'runs'), '--vendor', 'SRAM22',
                               '--library', 'sram22_256x16m8w8', '--owner', 'sram22_256x16m8w8',
                               '--revision', 'rev_0001'], text=True, capture_output=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(json.loads(proc.stdout)['sources']['20261024_de0a9a7'], 'delivery_005')

    def test_existing_revision_preserves_actual_members_and_alias(self):
        with patch('os.walk', side_effect=AssertionError('不能扫描来源')):
            result = query_data(DATA/'work', DATA/'runs', 'simple-effective',
                                vendor='SRAM22', library='sram22_256x16m8w8',
                                owner='sram22_256x16m8w8', revision='rev_0001')
        self.assertEqual(result['schema'], 'effective.simple.v2')
        self.assertEqual(result['revision'], 'rev_0001')
        self.assertIsNone(result['parent'])
        self.assertEqual(result['sources'], {'20261024_de0a9a7':'delivery_005'})
        self.assertEqual(result['views'], {'LEF': {'LEF/sram22_256x16m8w8.lef':'20261024_de0a9a7'}})
        self.assertNotIn('changes', result)

    def test_missing_archived_source_is_rejected(self):
        q = LibraryDataQuery(DATA/'work', DATA/'runs')
        q.deliveries.clear()
        q._refs.clear()
        from ai_lib_qor.application.simple_sources import simple_effective
        with self.assertRaisesRegex(ValueError, '无法解析'):
            simple_effective(q,'SRAM22','sram22_256x16m8w8','sram22_256x16m8w8','rev_0001')

    def test_formal_baseline_uses_archived_raw_path_and_records_snapshot(self):
        from ai_lib_qor.application.simple_sources import simple_effective
        q=Mock(); q.work='/work'
        q._revision.return_value={'owner':{'owner_type':'SOURCE_LIBRARY','owner_id':'L'},
                                  'revision_id':'rev_0001','parent_revision_id':None,'created_at':'now',
                                  'reason':{'kind':'FORMAL_BASELINE','ref_id':'snap_1'}}
        q.get_effective_files.return_value={'unresolved':[], 'views':{'LEF':{'nl/a.lef':{
            'formal_ref':{}, 'raw_source':{'vendor':'A','library':'L','delivery_id':'d1',
                                          'version':'V1','path':'lef/a.lef','view':'LEF'}}}}}
        q.deliveries=[{'record':{'vendor_id':'A','source_library_id':'L','supplier_version':'V1','delivery_id':'d1'},
                       'path':'/work/libraries/A/L/delivery_001.json'}]
        out=simple_effective(q,'A','L','L','rev_0001')
        self.assertEqual(out['formal_baseline'],'snap_1')
        self.assertEqual(out['views']['LEF'],{'lef/a.lef':'V1'})

    def test_same_version_multiple_deliveries_rejected(self):
        q = LibraryDataQuery(DATA/'work', DATA/'runs')
        d = next(x for x in q.deliveries if x['record']['supplier_version']=='20261024_de0a9a7' and x['record']['source_library_id']=='sram22_256x16m8w8')
        duplicate = dict(d); duplicate['record'] = dict(d['record'], delivery_id='another')
        q.deliveries.append(duplicate)
        from ai_lib_qor.application.simple_sources import simple_effective
        with self.assertRaisesRegex(ValueError, '不唯一'):
            simple_effective(q,'SRAM22','sram22_256x16m8w8','sram22_256x16m8w8','rev_0001')
