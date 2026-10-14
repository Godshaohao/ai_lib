from __future__ import annotations

import unittest

from lib_guard.render.version_file_evidence import _evidence_records, render_version_file_evidence_section
from lib_guard.render.version_review_model import build_ip_change_projection, build_ip_user_view_model, build_review_report
from lib_guard.render.version_review_render import render_ip_user_view
from lib_guard.render.version_detail_report import _version_overview_panel


class ReaderReportTest(unittest.TestCase):
    def test_full_report_focus_keeps_reader_classification(self):
        item = {'path': 'new_wrap/a.lef', 'change': 'added', 'file_type': 'lef', 'review_lane': 'P0'}
        model = {'status': 'CHANGED', 'path_restructure': {'new_root': 'new_wrap', 'old_root': 'old_wrap'},
            'package_root_unmatched': {'new': 1}, 'file_changes': [item], 'recommended_file_diff': [item]}
        report = build_review_report(model, build_ip_user_view_model(model))
        self.assertEqual(report['focus_file_analysis']['items'][0]['display_change'], 'UNMATCHED_NEW')
        self.assertEqual(report['view_delta_analysis']['evidence_reconciliation']['file_tree_changes']['unmatched_new'], 1)

    def test_logical_matched_file_is_not_duplicated_by_inventory(self):
        model = {'source_roots': {'current': '/raw/new'},
            'file_changes': [{'path': 'lef/a.lef', 'change': 'changed', 'file_type': 'lef'}],
            'file_diff': {'logical_path_changes': [{'logical_path': 'lef/a.lef', 'old': 'old_wrap/lef/a.lef', 'new': 'new_wrap/lef/a.lef'}]},
            'scan_evidence': {'inventory': {'files': [{'path': 'new_wrap/lef/a.lef', 'file_type': 'lef'}]}}}
        rows = _evidence_records(model)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['path'], 'new_wrap/lef/a.lef')
        self.assertEqual(rows[0]['source_path'], '/raw/new/new_wrap/lef/a.lef')

    def test_matrix_explains_uncertainty_without_plus_question_marker(self):
        html = render_ip_user_view({'view_rows': [{'view_type': 'liberty', 'delivery_count': 112,
            'unmatched_new': 108, 'unmatched_base': 2, 'delta_total': 110, 'evidence_level': 'Metadata-only'}]})
        self.assertNotIn('?+', html)
        self.assertNotIn('未匹配新侧', html)
        self.assertIn('待核对', html)
        self.assertIn('本版 108', html)
        self.assertIn('基准版 2', html)
        self.assertIn('不计为新增或删除', html)
        self.assertIn('仅检查文件信息', html)

    def test_tree_uses_same_projection_and_preserves_baseline_paths(self):
        model = {'source_roots': {'current': '/raw/new', 'base': '/raw/old'},
            'path_restructure': {'new_root': 'new_wrap', 'old_root': 'old_wrap'},
            'package_root_unmatched': {'new': 1, 'base': 1},
            'file_changes': [
                {'path': 'new_wrap/a.lib', 'change': 'added', 'file_type': 'liberty'},
                {'path': 'old_wrap/b.lib', 'change': 'removed', 'file_type': 'liberty'}]}
        rows = _evidence_records(model)
        self.assertEqual([row['change'] for row in rows], ['unmatched_new', 'unmatched_base'])
        self.assertEqual(rows[1]['source_path'], '/raw/old/old_wrap/b.lib')
        html = render_version_file_evidence_section(model)
        self.assertIn("value='unmatched_new'", html)
        self.assertIn('本版待核对', html)
        self.assertIn('基准版待核对', html)
        self.assertNotIn("data-tree-status='added'", html)
        self.assertNotIn("data-tree-status='removed'", html)

    def test_summary_is_reader_facing_and_does_not_call_uncertain_files_changes(self):
        model = {'version_id': 'v2', 'ip_user_view_model': {
            'decision': {'status': 'USAGE_REVIEW_REQUIRED', 'reason': '系统投影需要运行 lg cmp'},
            'comparison': {'base_label': 'v1', 'visible_counts': {'changed': 1, 'unmatched_new': 108}},
            'view_rows': [{'view': 'Liberty', 'usage_area': '时序分析', 'unmatched_new': 108}]}}
        html = _version_overview_panel(model)
        self.assertIn('已确认变化', html)
        self.assertIn('本版 108', html)
        self.assertIn('使用影响', html)
        self.assertNotIn('系统投影', html)
        self.assertNotIn('lg cmp', html)
        self.assertNotIn('下一步', html)
        self.assertNotIn('没有额外待确认', html)

    def test_single_version_summary_does_not_imply_comparison(self):
        html = _version_overview_panel({'version_id': 'v1', 'review_mode': 'first_version',
            'scan_evidence': {'file_total': 3}, 'ip_user_view_model': {'comparison': {}, 'view_rows': []}})
        self.assertIn('首版交付', html)
        self.assertIn('3', html)
        self.assertNotIn('新增 0', html)
        self.assertIn('没有基准版', html)
