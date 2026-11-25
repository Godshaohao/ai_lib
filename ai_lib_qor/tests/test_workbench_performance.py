"""Regression & correctness tests for workbench algorithmic optimizations and stat-verified caching."""
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from ai_lib_qor.application.minimal_effective import _history, fast_library_track_revisions
from ai_lib_qor.application.path_acceptance import accept_revision, acceptance_status
from ai_lib_qor.application.path_query import PathDataQuery, workspace_activity_and_readiness
from ai_lib_qor.application.path_refresh import refresh_all
from ai_lib_qor.versions.store import read_json, read_json_readonly, write_atomic
from ai_lib_qor.workbench.path_app import create_path_app
from ai_lib_qor.workbench.read_cache import compute_work_signature


def _write_text(path: Path, text: str = 'dummy\n') -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8')


class WorkbenchPerformanceTests(unittest.TestCase):
    def test_read_json_cache_mutation_safety_and_invalidation(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / 'sample.json'
            write_atomic(p, {'k': 1, 'items': ['a']})
            a = read_json(p, None)
            a['items'].append('mutated')
            # Mutating read_json() result must NOT poison the cache
            b = read_json_readonly(p)
            self.assertEqual(b['items'], ['a'])
            # Atomic overwrite changes inode/mtime and must invalidate immediately
            write_atomic(p, {'k': 2, 'items': ['b']})
            c = read_json_readonly(p)
            self.assertEqual(c['k'], 2)
            self.assertEqual(c['items'], ['b'])

    def test_fast_library_track_revisions_and_cache_invalidation(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            raw = root / 'raw'
            work = root / 'work'
            work.mkdir()

            # Create a multi-track library with 2 business IPs and 2 deliveries for IP_A, 1 for IP_B
            _write_text(raw / 'V1' / 'MULTI' / '20261001_IP_A_v1' / 'LIB' / 'a_ss.lib', 'library(a){}\n')
            _write_text(raw / 'V1' / 'MULTI' / '20261005_IP_A_v2' / 'LIB' / 'a_ss.lib', 'library(a){/*v2*/}\n')
            _write_text(raw / 'V1' / 'MULTI' / '20261002_IP_B_v1' / 'LIB' / 'b_ss.lib', 'library(b){}\n')

            write_atomic(work / 'path_sources.json', {
                'raw_root': str(raw),
                'update_formal': False,
                'libraries': {
                    'V1': {
                        'MULTI': {
                            'ip_type': 'ANALOG',
                            'ip_list': ['IP_A', 'IP_B'],
                        },
                    },
                },
            })
            refresh_all(work)
            accept_revision(work, 'V1', 'MULTI', 'rev_0002', actor='tester', reason='ok', business_ip='IP_A')

            folder = work / 'libraries' / 'V1' / 'MULTI'
            revs_by_ip, accepted_by_ip = fast_library_track_revisions(folder, 'MULTI')
            for ip in ('IP_A', 'IP_B'):
                hist = _history(folder, 'MULTI', business_ip=ip)
                acc = acceptance_status(work, 'V1', 'MULTI', limit=1, business_ip=ip)
                self.assertEqual(revs_by_ip[ip], [row['revision'] for _, _, row in hist])
                self.assertEqual(accepted_by_ip.get(ip), acc.get('accepted_revision'))

            # Fast list_tracks(include_checks=False) matches exact track metadata
            tracks_fast = PathDataQuery(work).list_tracks(vendor='V1', library='MULTI', include_checks=False)
            by_ip = {t['business_ip']: t for t in tracks_fast['tracks']}
            self.assertEqual(by_ip['IP_A']['latest_revision'], 'rev_0002')
            self.assertEqual(by_ip['IP_A']['accepted_revision'], 'rev_0002')
            self.assertIsNone(by_ip['IP_A']['latest_check'])
            self.assertEqual(by_ip['IP_B']['latest_revision'], 'rev_0001')
            self.assertIsNone(by_ip['IP_B']['accepted_revision'])

            # WorkbenchReadCache: warm GET / hits cache, out-of-band acceptance invalidates immediately
            app = create_path_app(work)
            self.addCleanup(app.extensions['jobs'].shutdown, wait=True)
            client = app.test_client()

            r1 = client.get('/')
            self.assertEqual(r1.status_code, 200)
            sig_before = compute_work_signature(work)

            with patch('ai_lib_qor.application.path_refresh.refresh_status', side_effect=AssertionError('Warm GET / should hit read_cache')):
                r2 = client.get('/')
                self.assertEqual(r2.status_code, 200)

            # Out-of-band CLI mutation (not via Web POST!)
            accept_revision(work, 'V1', 'MULTI', 'rev_0001', actor='cli', reason='cli accept', business_ip='IP_B')
            sig_after = compute_work_signature(work)
            self.assertNotEqual(sig_before, sig_after)

            r3 = client.get('/')
            self.assertEqual(r3.status_code, 200)
            html3 = r3.get_data(as_text=True)
            self.assertIn('已采纳 2/2', html3)

    def test_workspace_activity_skips_parsing_out_of_window_deliveries(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            raw = root / 'raw'
            work = root / 'work'
            work.mkdir()

            _write_text(raw / 'V1' / 'LIB1' / '20260101_v1' / 'LIB' / 'old.lib', 'library(old){}\n')
            _write_text(raw / 'V1' / 'LIB1' / '20261120_v2' / 'LIB' / 'new.lib', 'library(new){}\n')
            write_atomic(work / 'path_sources.json', {
                'raw_root': str(raw),
                'update_formal': False,
            })
            refresh_all(work)

            # Backdate old delivery file's mtime by 30 days
            deliv_dir = work / 'libraries' / 'V1' / 'LIB1' / 'delivery'
            old_deliv = next(p for p in deliv_dir.glob('delivery_*.json') if '20260101_v1' in p.name)
            old_ts = (datetime.now(timezone.utc) - timedelta(days=30)).timestamp()
            os.utime(old_deliv, (old_ts, old_ts))

            parsed_paths: list[str] = []
            orig_ro = read_json_readonly

            def _spy_ro(path, schema=None):
                parsed_paths.append(Path(path).name)
                return orig_ro(path, schema)

            with patch('ai_lib_qor.versions.store.read_json_readonly', side_effect=_spy_ro):
                act = workspace_activity_and_readiness(work, days=7)

            self.assertNotIn(old_deliv.name, parsed_paths)
            versions_in_act = [r['version'] for r in act['raw_changes']]
            self.assertIn('20261120_v2', versions_in_act)
            self.assertNotIn('20260101_v1', versions_in_act)

    def test_overview_caps_oversized_activity_table_and_warm_is_fast(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            raw = root / 'raw'
            work = root / 'work'
            work.mkdir()

            # Build 4 libraries × 3 tracks × 2 deliveries to verify cold vs warm switching
            libs_cfg = {}
            for li in range(4):
                lib_name = f'LIB_{li}'
                libs_cfg[lib_name] = {'ip_type': 'ANALOG', 'ip_list': ['IP_0', 'IP_1', 'IP_2']}
                for ip_idx in range(3):
                    ip = f'IP_{ip_idx}'
                    _write_text(raw / 'V1' / lib_name / f'20261101_{ip}_v1' / 'LIB' / f'{ip}.lib', f'library({ip}){{}}\n')
                    _write_text(raw / 'V1' / lib_name / f'20261110_{ip}_v2' / 'LIB' / f'{ip}.lib', f'library({ip}){{/*v2*/}}\n')

            write_atomic(work / 'path_sources.json', {
                'raw_root': str(raw),
                'update_formal': False,
                'libraries': {'V1': libs_cfg},
            })
            refresh_all(work)

            app = create_path_app(work)
            self.addCleanup(app.extensions['jobs'].shutdown, wait=True)
            client = app.test_client()

            t0 = time.perf_counter()
            r_cold = client.get('/')
            cold_ms = (time.perf_counter() - t0) * 1000.0
            self.assertEqual(r_cold.status_code, 200)

            t1 = time.perf_counter()
            r_warm = client.get('/')
            warm_ms = (time.perf_counter() - t1) * 1000.0
            self.assertEqual(r_warm.status_code, 200)
            self.assertLess(warm_ms, cold_ms + 50.0)
            self.assertLess(warm_ms, 500.0)

            # Verify library page track switching works cleanly with cached organizer_state
            r_lib_a = client.get('/path/library?vendor=V1&library=LIB_0&ip=IP_0')
            r_lib_b = client.get('/path/library?vendor=V1&library=LIB_0&ip=IP_1')
            self.assertEqual(r_lib_a.status_code, 200)
            self.assertEqual(r_lib_b.status_code, 200)
            self.assertIn('organizer-initial-data', r_lib_a.get_data(as_text=True))

            # Verify overview caps inline raw_changes rows at 200 when activity has >200 entries
            real_act = workspace_activity_and_readiness(work, days=7)
            tmpl_row = real_act['raw_changes'][0]
            fake_rows = [{**tmpl_row, 'version': f'20261101_IP_0_v{i}'} for i in range(250)]
            fake_act = {**real_act, 'raw_changes': fake_rows}
            app.extensions['read_cache'].invalidate()
            with patch('ai_lib_qor.application.path_query.workspace_activity_and_readiness', return_value=fake_act):
                r_cap = client.get('/?days=7')
                self.assertEqual(r_cap.status_code, 200)
                cap_html = r_cap.get_data(as_text=True)
                self.assertIn('首屏展示最新 200 条', cap_html)
                self.assertIn('20261101_IP_0_v0', cap_html)
                self.assertNotIn('20261101_IP_0_v249', cap_html)


if __name__ == '__main__':
    unittest.main()
