from datetime import datetime, timezone
from pathlib import Path
import unittest
import tempfile


ROOT = Path(__file__).resolve().parents[3]


class LibraryOverviewUITest(unittest.TestCase):
    def test_directory_updates_use_recorded_mtime_not_version_name_or_scan_time(self):
        from lib_guard.web.read_model import _library_directory_updated_at
        versions = [
            {'version_id': '20990101_full', 'detected': {'mtime': '2026-01-02T10:00:00Z'}},
            {'version_id': 'older', 'detected': {'mtime': '2026-01-03T09:00:00+08:00'}},
            {'version_id': 'bad', 'detected': {'mtime': 'invalid'}, 'scan': {'last_scan_at': '2099-01-01'}},
        ]
        result = _library_directory_updated_at(versions)
        self.assertEqual(datetime.fromisoformat(result.replace('Z', '+00:00')), datetime(2026, 1, 3, 1, tzinfo=timezone.utc))
        self.assertIsNone(_library_directory_updated_at([{'version_id': '20261013_full'}]))

    def test_overview_precedes_discovery_and_manual_add_is_secondary(self):
        template = (ROOT / 'src/lib_guard/web/templates/index.html').read_text()
        self.assertLess(template.index('id="registered-library-heading"'), template.index('id="candidate-discover-root"'))
        self.assertLess(template.index('id="candidate-discover-root"'), template.index('id="library-add-disclosure"'))
        self.assertEqual(template.count('id="registered-library-table-body"'), 1)
        for label in ['原始库版本概览', '最新版本', '最新更新时间', '重新发现候选库', '手动添加库（补充）', '读取上次结果']:
            self.assertIn(label, template)

    def test_overview_counts_actual_versions_and_exposes_mtime_source(self):
        from lib_guard.web.read_model import list_library_rows
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            versions = [{'version_id': '20260101_full', 'detected': {'mtime': '2026-01-02T01:00:00Z'}},
                        {'version_id': '20260103_full', 'detected': {'mtime': '2026-01-04T01:00:00Z'}}]
            state = {'workspace': root, 'catalog_path': root / 'catalog/catalog.json', 'catalog_html': root / 'catalog/html',
                     'catalog': {'libraries': [{'library_name': 'A', 'library_type': 'ip', 'versions': versions, 'summary': {'version_count': 999}}]}}
            row = list_library_rows(state)[0]
            self.assertEqual(row['version_count'], 2)
            self.assertEqual(row['latest_version'], '20260103_full')
            self.assertEqual(row['raw_updated_at'], '2026-01-04T01:00:00Z')
            self.assertEqual(row['raw_updated_at_source'], 'catalog_version_directory_mtime')
