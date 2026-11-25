"""Tests for read-only workspace source readiness and 7-day/30-day RAW & Formal (NL) activity tables."""
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


def _lef(w: int) -> str:
    return f'VERSION 5.8 ;\nMACRO A\n SIZE {w} BY 2 ;\n PIN IN\n  DIRECTION INPUT ;\n END IN\nEND A\nEND LIBRARY\n'


class WorkspaceActivityReadinessTests(unittest.TestCase):
    def test_readiness_zero_scan_and_7d_vs_30d_raw_and_nl_change_tables(self):
        from ai_lib_qor.application.path_query import workspace_activity_and_readiness
        from ai_lib_qor.application.path_refresh import refresh_all, refresh_l3, refresh_status
        from ai_lib_qor.workbench.path_app import create_path_app

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            raw, nl, work = root / 'raw', root / 'NL1', root / 'work'
            nl.mkdir()
            work.mkdir()

            # 1) Existing library LIB_OLD: v1 archived 20 days ago, v2 archived 1 day ago (same lib -> "新增交付")
            old_v1_lef = raw / 'V1/LIB_OLD/20261001_v1/LEF/a.lef'
            old_v1_gds = raw / 'V1/LIB_OLD/20261001_v1/GDS/a.gds'
            old_v1_lef.parent.mkdir(parents=True)
            old_v1_gds.parent.mkdir(parents=True)
            old_v1_lef.write_text(_lef(10), encoding='utf-8')
            old_v1_gds.write_text('gds', encoding='utf-8')
            (nl / 'a.lef').symlink_to(old_v1_lef)
            (nl / 'a.gds').symlink_to(old_v1_gds)

            (work / 'path_sources.json').write_text(json.dumps({
                'raw_root': str(raw),
                'nl_root': str(nl),
                'nl_version': 'NL1',
            }), encoding='utf-8')
            refresh_all(work)

            now_dt = datetime(2026, 11, 24, 12, 0, 0, tzinfo=timezone.utc)
            ts_20d = (now_dt - timedelta(days=20)).timestamp()
            ts_2d = (now_dt - timedelta(days=2)).timestamp()
            ts_1d = (now_dt - timedelta(days=1)).timestamp()

            # Backdate LIB_OLD v1 delivery & first formal snapshot to 20 days ago
            old_lib_dir = work / 'libraries/V1/LIB_OLD'
            d_old_v1 = old_lib_dir / 'delivery/delivery_LIB_OLD__20261001_v1.json'
            os.utime(d_old_v1, (ts_20d, ts_20d))
            f1 = next((old_lib_dir / 'formal').glob('formal_NL1_*.json'))
            f1_doc = json.loads(f1.read_text(encoding='utf-8'))
            f1_doc['observed_at'] = '2026-11-04T12:00:00Z'
            f1.write_text(json.dumps(f1_doc), encoding='utf-8')

            # 2) Add LIB_OLD v2 (1 day ago) and update Formal NL: switch a.lef v1->v2, remove a.gds, add b.lib
            old_v2_lef = raw / 'V1/LIB_OLD/20261123_v2/LEF/a.lef'
            old_v2_lib = raw / 'V1/LIB_OLD/20261123_v2/LIB/b.lib'
            old_v2_lef.parent.mkdir(parents=True)
            old_v2_lib.parent.mkdir(parents=True)
            old_v2_lef.write_text(_lef(12), encoding='utf-8')
            old_v2_lib.write_text('library(t){cell(A){pin(IN){direction:input;}}}', encoding='utf-8')
            (nl / 'a.lef').unlink()
            (nl / 'a.lef').symlink_to(old_v2_lef)
            (nl / 'a.gds').unlink()
            (nl / 'b.lib').symlink_to(old_v2_lib)

            # 3) Add brand-new library LIB_NEW (2 days ago -> "新增库")
            new_v1_lef = raw / 'V2/LIB_NEW/20261122_r1/LEF/new.lef'
            new_v1_lef.parent.mkdir(parents=True)
            new_v1_lef.write_text(_lef(5), encoding='utf-8')

            refresh_all(work)
            d_old_v2 = old_lib_dir / 'delivery/delivery_LIB_OLD__20261123_v2.json'
            os.utime(d_old_v2, (ts_1d, ts_1d))
            d_new_v1 = work / 'libraries/V2/LIB_NEW/delivery/delivery_LIB_NEW__20261122_r1.json'
            os.utime(d_new_v1, (ts_2d, ts_2d))
            f_snaps = sorted((old_lib_dir / 'formal').glob('formal_NL1_*.json'))
            self.assertEqual(len(f_snaps), 2)
            f2_doc = json.loads(f_snaps[1].read_text(encoding='utf-8'))
            f2_doc['observed_at'] = '2026-11-23T12:00:00Z'
            f_snaps[1].write_text(json.dumps(f2_doc), encoding='utf-8')
            refresh_l3(work, force_verify=True)

            st = refresh_status(work, limit=5)

            # Strictly ZERO os.walk during readiness/activity queries!
            with patch('os.walk', side_effect=AssertionError('只读查询不得扫描外部 RAW/Formal')):
                act7 = workspace_activity_and_readiness(work, days=7, now=now_dt, refresh_info=st)
                act30 = workspace_activity_and_readiness(work, days=30, now=now_dt, refresh_info=st)

            # Readiness check
            self.assertEqual(act7['readiness']['raw_status'], 'READY')
            self.assertEqual(act7['readiness']['formal_status'], 'READY')
            self.assertEqual(act7['readiness']['formal_version'], 'NL1')
            self.assertEqual(act7['readiness']['skip_parse_views'], ['CDL', 'SPICE', 'VERILOG'])
            self.assertEqual(act7['readiness']['initial_delivery_tail'], 3)

            # 7-day window: includes LIB_NEW (新增库) + LIB_OLD v2 (新增交付), excludes LIB_OLD v1 (20d ago)
            self.assertEqual(act7['counts']['new_libraries'], 1)
            self.assertEqual(act7['counts']['raw_deliveries'], 2)
            by_ver7 = {r['version']: r for r in act7['raw_changes']}
            self.assertEqual(set(by_ver7), {'20261122_r1', '20261123_v2'})
            self.assertTrue(by_ver7['20261122_r1']['is_new_library'])
            self.assertEqual(by_ver7['20261122_r1']['change_badge'], '新增库')
            self.assertFalse(by_ver7['20261123_v2']['is_new_library'])
            self.assertEqual(by_ver7['20261123_v2']['change_badge'], '新增交付')

            # 30-day window includes all 3 deliveries
            self.assertEqual(act30['counts']['raw_deliveries'], 3)

            # 7-day Formal (NL) change table shows ONLY the updated snapshot with exact +1 / ~1 / -1 diff!
            self.assertEqual(act7['counts']['nl_changes'], 1)
            nl_row = act7['nl_changes'][0]
            self.assertEqual(nl_row['change_kind'], 'UPDATED')
            self.assertEqual((nl_row['added'], nl_row['switched'], nl_row['removed']), (1, 1, 1))
            self.assertIn('新增 +1', nl_row['summary_text'])
            self.assertIn('切版 1', nl_row['summary_text'])
            self.assertIn('移除 -1', nl_row['summary_text'])
            self.assertTrue(any('20261001_v1 → 20261123_v2' in s for s in nl_row['samples']))

            # 30-day Formal (NL) change table includes both initial + updated snapshots
            self.assertEqual(act30['counts']['nl_changes'], 2)
            self.assertEqual(act30['nl_changes'][1]['change_kind'], 'INITIAL')

            # Web overview + /api/v1/activity render cleanly without touching RAW
            app = create_path_app(work)
            self.addCleanup(app.extensions['jobs'].shutdown, wait=True)
            client = app.test_client()
            with patch('os.walk', side_effect=AssertionError('打开页面不得扫描 RAW')):
                r_page = client.get('/?days=30')
                r_api = client.get('/api/v1/activity?days=30')
            self.assertEqual(r_page.status_code, 200)
            html = r_page.get_data(as_text=True)
            self.assertIn('动态与就绪', html)
            self.assertIn('id="app-sidebar"', html)
            self.assertIn('id="sidebar-toggle-btn"', html)
            self.assertIn('id="raw-act-seg"', html)
            self.assertIn('id="nl-act-seg"', html)
            self.assertIn('data-auto-filter="1"', html)
            self.assertNotIn('>筛选</button>', html)
            self.assertIn('recent-raw-table', html)
            self.assertIn('recent-nl-table', html)
            self.assertIn('RAW 数据源', html)
            self.assertIn('Formal (NL) 数据源', html)

            # Focused ?view=libraries hides activity head & sync-center and shows libraries-section cleanly
            r_libs = client.get('/?view=libraries')
            self.assertEqual(r_libs.status_code, 200)
            libs_html = r_libs.get_data(as_text=True)
            self.assertIn('id="domain-head-activity" class="domain-head-block" hidden', libs_html)
            self.assertIn('id="sync-center-section" class="card scroll-anchor" aria-label="三层数据刷新中心" hidden', libs_html)
            self.assertIn('id="libraries-section" class="card scroll-anchor" aria-label="来源库清单" >', libs_html)

            # Focused ?view=config decouples KPI & sync buttons and supports save_only=1 without scanning RAW
            r_cfg = client.get('/?view=config')
            self.assertEqual(r_cfg.status_code, 200)
            cfg_html = r_cfg.get_data(as_text=True)
            self.assertIn('id="domain-head-activity" class="domain-head-block" hidden', cfg_html)
            self.assertIn('id="domain-head-config" class="domain-head-block" >', cfg_html)
            self.assertIn('仅保存配置', cfg_html)

            with client.session_transaction() as sess:
                csrf = sess['csrf']
            with patch('os.walk', side_effect=AssertionError('仅保存配置不得扫描外部 RAW')):
                r_save = client.post('/path/update', data={
                    'csrf': csrf,
                    'save_only': '1',
                    'raw_roots': str(raw),
                    'nl_root': str(nl),
                    'nl_version': 'NL1',
                    'skip_parse_views_present': '1',
                    'skip_parse_views': ['CDL', 'SPICE'],
                    'initial_delivery_tail': '5',
                })
            self.assertEqual(r_save.status_code, 302)
            saved_cfg = json.loads((work / 'path_sources.json').read_text(encoding='utf-8'))
            self.assertEqual(saved_cfg.get('initial_delivery_tail'), 5)
            self.assertEqual(saved_cfg.get('skip_parse_views'), ['CDL', 'SPICE'])

            # Organizer API includes files_by_view for in-place inspector drawer
            r_org = client.get('/api/v1/organizer?vendor=V2&library=LIB_NEW')
            self.assertEqual(r_org.status_code, 200)
            self.assertIn('LEF/new.lef', r_org.get_json()['order'][0]['files_by_view']['LEF'])

            # File index page uses zero-click auto-filter without manual "筛选" submit button
            r_idx = client.get('/path/index?vendor=V2&library=LIB_NEW')
            self.assertEqual(r_idx.status_code, 200)
            idx_html = r_idx.get_data(as_text=True)
            self.assertIn('data-auto-filter="1"', idx_html)
            self.assertNotIn('>筛选</button>', idx_html)

            self.assertEqual(r_api.status_code, 200)
            payload = r_api.get_json()
            self.assertEqual(payload['readiness']['raw_status'], 'READY')
            self.assertEqual(payload['counts']['raw_deliveries'], 3)


if __name__ == '__main__':
    unittest.main()
