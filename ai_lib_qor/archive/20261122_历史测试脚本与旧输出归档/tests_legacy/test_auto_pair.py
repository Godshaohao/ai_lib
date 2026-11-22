import copy
import json
import unittest
from pathlib import Path
from ai_lib_qor.checks.plan import pair_interfaces

ROOT=Path(__file__).resolve().parents[1]/'examples/file_facts'

def item(key,name): return {'file_key':key,'facts':json.loads((ROOT/name).read_text())}

class PairTests(unittest.TestCase):
    def test_pair_unique_macro_and_cell(self):
        lef=item('lef','facts_core_v08.json'); lib=item('tt','facts_tt_v08.json')
        result=pair_interfaces([lef,lib]);self.assertEqual([(x['lef_key'],x['liberty_key']) for x in result],[('lef','tt')])
    def test_ambiguous_ownership_is_rejected(self):
        lef=item('lef','facts_core_v08.json'); other=copy.deepcopy(lef);other['file_key']='lef2'
        with self.assertRaises(ValueError): pair_interfaces([lef,other,item('tt','facts_tt_v08.json')])
    def test_incomplete_or_no_match_does_not_create_pair(self):
        lef=item('lef','facts_core_v08.json'); lib=item('tt','facts_tt_v08.json'); lib['facts']['parse_status']='PARTIAL'
        with self.assertRaises(ValueError): pair_interfaces([lef,lib])
