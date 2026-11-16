import copy
import json
import unittest
from pathlib import Path

from ai_lib_qor.reporting.view import build_report

ROOT = Path(__file__).resolve().parents[1]

class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.check = json.loads((ROOT / 'tests/fixtures/check_result.json').read_text())

    def test_reject_mismatching_summary(self):
        self.check['summary']['failed_checks'] = 999
        with self.assertRaises(ValueError): build_report(self.check)

    def test_reject_duplicate_file_changes(self):
        self.check['file_changes'].append(copy.deepcopy(self.check['file_changes'][0]))
        with self.assertRaises(ValueError): build_report(self.check)

    def test_reject_pass_without_complete_coverage(self):
        self.check['quality_checks'][0]['coverage'] = 'UNKNOWN'
        with self.assertRaises(ValueError): build_report(self.check)

    def test_reject_false_source_changed(self):
        change = self.check['file_changes'][0]
        change['source_changed'] = not change['source_changed']
        with self.assertRaises(ValueError): build_report(self.check)

    def test_initial_revision_report_does_not_present_zero_as_comparison(self):
        from ai_lib_qor.reporting.workbook_model import build_sheets
        self.check['baseline']=None;self.check['file_changes']=[]
        self.check['summary']['files_with_new_source']=0
        self.check['summary']['files_with_confirmed_content_change']=0
        overview=build_sheets(build_report(self.check))[0][2][0]
        self.assertEqual(overview[7:9],['未对比','未对比'])
