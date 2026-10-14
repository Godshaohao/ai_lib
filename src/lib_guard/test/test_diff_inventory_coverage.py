import unittest
from pathlib import Path
from unittest.mock import patch

from lib_guard.diff.scan_diff import _file_diff, _inventory_coverage
from lib_guard.render.version_detail_report import _package_root_unmatched_counts
from lib_guard.render.version_review_model import build_ip_change_projection
from lib_guard.render.version_review_render import render_ip_user_view


class DiffInventoryCoverageTest(unittest.TestCase):
    def test_walk_errors_are_not_a_complete_inventory(self):
        from lib_guard.scan.inventory import FileWalker
        walker = FileWalker()
        def walk(root, **kwargs):
            kwargs['onerror'](PermissionError(13, 'denied', '/blocked'))
            return []
        with patch('lib_guard.scan.inventory.os.walk', side_effect=walk):
            list(walker.walk('/tmp'))
        self.assertFalse(walker.coverage['complete'])
        self.assertEqual(walker.coverage['skipped_count'], 1)
        meta = {'status': 'PASS_WITH_WARNING', 'inventory_walk': walker.coverage,
                'input_fingerprint': {'mode': 'scan_inventory', 'entry_count': 0, 'truncated': False}}
        self.assertFalse(_inventory_coverage(meta, 0)['complete'])

    def test_matrix_explains_inventory_difference(self):
        html = render_ip_user_view({'view_rows': [{'view_type': 'liberty', 'base_count': 4,
            'delivery_count': 112, 'added': 108, 'delta_total': 108}]})
        self.assertIn('基准 4', html)
        self.assertIn('本版', html)
        self.assertIn('+108', html)

    def compare(self, truncated=False, status='PASS'):
        def record(path):
            return {'path': path, 'file_type': 'liberty', 'size_bytes': 8, 'hash': path.split('/')[-1]}
        old = {'old_source_package/lib/common.lib': record('old_source_package/lib/common.lib')}
        new = {path: record(path) for path in ('upstream_new/lib/common.lib', 'upstream_new/lib/c.lib', 'upstream_new/lib/d.lib')}
        def meta(count):
            return {'status': status, 'input_fingerprint': {'mode': 'scan_inventory', 'entry_count': count, 'truncated': truncated}}
        with patch('lib_guard.diff.scan_diff._inventory_index', side_effect=[old, new]):
            return _file_diff(Path('/old'), Path('/new'), old_meta=meta(1), new_meta=meta(3))

    def test_complete_inventory_expansion_is_not_manual_matching_work(self):
        result = self.compare()
        self.assertEqual(len(result['added']), 2)
        self.assertEqual(result['counts']['unmatched_added_under_package_root'], 0)
        self.assertTrue(result['inventory_coverage']['old']['complete'])
        self.assertEqual(_package_root_unmatched_counts(result, {'suspected': True, 'new_root': 'upstream_new'}), {'new': 0, 'base': 0})

    def test_truncated_inventory_remains_uncertain(self):
        result = self.compare(truncated=True)
        self.assertEqual(result['counts']['unmatched_added_under_package_root'], 2)
        self.assertFalse(result['inventory_coverage']['old']['complete'])

    def test_parser_warning_does_not_make_inventory_incomplete(self):
        result = self.compare(status='PASS_WITH_WARNING')
        self.assertEqual(result['counts']['unmatched_added_under_package_root'], 0)
        self.assertTrue(result['inventory_coverage']['old']['complete'])

    def test_failed_scan_cannot_claim_complete_inventory(self):
        result = self.compare(status='FAILED')
        self.assertFalse(result['inventory_coverage']['old']['complete'])
        self.assertEqual(result['counts']['unmatched_added_under_package_root'], 2)

    def test_one_ambiguous_path_does_not_demote_every_added_file(self):
        model = {'package_root_unmatched': {'new': 1}, 'path_restructure': {'new_root': 'wrapper'},
                 'file_diff': {'unmatched_added_under_package_root': ['wrapper/a.lib'], 'unmatched_removed_under_package_root': []}}
        items = [{'path': 'wrapper/a.lib', 'change': 'added'}, {'path': 'wrapper/b.lib', 'change': 'added'}]
        counts = build_ip_change_projection(model, items)['visible_counts']
        self.assertEqual(counts['unmatched_new'], 1)
        self.assertEqual(counts['added'], 1)

    def test_matrix_links_selected_deep_result_without_promoting_the_whole_view(self):
        html = render_ip_user_view({'view_rows': [{'view_type': 'physical_abstract', 'delivery_count': 27, 'added': 23, 'delta_total': 23}],
            'representative_files': [{'file_type': 'lef', 'result': 'SAME', 'freshness': '文件状态未改变'}]})
        self.assertIn('已保存所选文件核查', html)
        self.assertIn('仅所选文件', html)
        self.assertIn('#file-checks', html)


if __name__ == '__main__':
    unittest.main()
