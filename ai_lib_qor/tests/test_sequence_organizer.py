"""Tests for the delivery sequence & business-IP track organizer (Policy A safe archive-and-rebuild)."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


def _lef(w: int) -> str:
    return f'VERSION 5.8 ;\nMACRO A\n SIZE {w} BY 2 ;\n PIN IN\n  DIRECTION INPUT ;\n END IN\nEND A\nEND LIBRARY\n'


class SequenceOrganizerTests(unittest.TestCase):
    def test_multi_ip_incremental_rebuild_and_acceptance_protection(self):
        from ai_lib_qor.application.minimal_effective import _history
        from ai_lib_qor.application.path_acceptance import accept_revision
        from ai_lib_qor.application.path_refresh import refresh_all
        from ai_lib_qor.application.sequence_organizer import apply_sequence_plan, get_organizer_state
        from ai_lib_qor.workbench.path_app import create_path_app

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            raw, work = root / 'raw', root / 'work'
            work.mkdir()

            # Build multi-IP library with IP_A, IP_B, 1 conflict, and 1 unassigned delivery
            for rel, w in (
                ('V1/MULTI/20261001_IP_A_v1/LEF/a.lef', 10),
                ('V1/MULTI/20261005_IP_A_v2/LEF/a.lef', 12),
                ('V1/MULTI/20261002_IP_B_v1/LEF/b.lef', 20),
                ('V1/MULTI/20261008_IP_A_IP_B_mix/LEF/mix.lef', 30),
                ('V1/MULTI/20261009_misc_notes/DOC/readme.txt', 1),
            ):
                p = raw / rel
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(_lef(w) if rel.endswith('.lef') else 'notes', encoding='utf-8')

            (work / 'path_sources.json').write_text(json.dumps({
                'raw_root': str(raw),
                'update_formal': False,
                'libraries': {
                    'V1': {
                        'MULTI': {
                            'ip_type': 'SRAM',
                            'ip_list': ['IP_A', 'IP_B'],
                        }
                    }
                },
            }), encoding='utf-8')
            refresh_all(work)

            # 1) Read-only state check (strictly zero os.walk)
            with patch('os.walk', side_effect=AssertionError('只读编排状态不得扫描外部 RAW')):
                st = get_organizer_state(work, 'V1', 'MULTI')
            self.assertEqual(st['mode'], 'multi_track')
            self.assertEqual([x['version'] for x in st['tracks']['IP_A']], ['20261001_IP_A_v1', '20261005_IP_A_v2'])
            self.assertEqual([x['version'] for x in st['tracks']['IP_B']], ['20261002_IP_B_v1'])
            self.assertEqual(
                {x['version']: x['review_kind'] for x in st['needs_review']},
                {'20261008_IP_A_IP_B_mix': 'CONFLICT', '20261009_misc_notes': 'UNASSIGNED'},
            )

            # 2) Incremental assignment: assign conflict -> IP_B, exclude unassigned -> NO rebuild needed!
            res1 = apply_sequence_plan(
                work, 'V1', 'MULTI',
                tracks={
                    'IP_A': ['20261001_IP_A_v1', '20261005_IP_A_v2'],
                    'IP_B': ['20261002_IP_B_v1', '20261008_IP_A_IP_B_mix'],
                },
                excluded=['20261009_misc_notes'],
                rebuild_tracks=[],
                refresh=True,
                actor='test',
            )
            self.assertEqual(res1['archived_tracks'], [])
            self.assertEqual(res1['touched_evolved_tracks'], [])
            folder = work / 'libraries/V1/MULTI'
            self.assertEqual(len(_history(folder, 'MULTI', business_ip='IP_B')), 2)

            # 3) Policy A Archive-and-Rebuild on unaccepted track: move evolved 20261005_IP_A_v2 from IP_A -> IP_B
            res2 = apply_sequence_plan(
                work, 'V1', 'MULTI',
                tracks={
                    'IP_A': ['20261001_IP_A_v1'],
                    'IP_B': ['20261002_IP_B_v1', '20261005_IP_A_v2', '20261008_IP_A_IP_B_mix'],
                },
                excluded=['20261009_misc_notes'],
                rebuild_tracks=['IP_A', 'IP_B'],
                refresh=True,
                actor='test',
            )
            self.assertEqual(len(res2['archived_tracks']), 2)
            for arch in res2['archived_tracks']:
                arch_dir = work / arch['archive_dir']
                self.assertTrue((arch_dir / 'manifest.json').is_file())
            self.assertEqual(len(_history(folder, 'MULTI', business_ip='IP_A')), 1)
            self.assertEqual(len(_history(folder, 'MULTI', business_ip='IP_B')), 3)

            # 4) Acceptance protection: once IP_A is human-accepted, rebuild MUST be rejected!
            accept_revision(work, 'V1', 'MULTI', 'rev_0001', actor='reviewer', reason='verified', business_ip='IP_A')
            with self.assertRaises(ValueError) as ctx:
                apply_sequence_plan(
                    work, 'V1', 'MULTI',
                    tracks={
                        'IP_A': ['20261001_IP_A_v1', '20261005_IP_A_v2'],
                        'IP_B': ['20261002_IP_B_v1', '20261008_IP_A_IP_B_mix'],
                    },
                    excluded=['20261009_misc_notes'],
                    rebuild_tracks=['IP_A'],
                    refresh=True,
                )
            self.assertIn('受保护禁止归档重建', str(ctx.exception))

            # 5) Web page + Organizer API endpoints
            app = create_path_app(work)
            self.addCleanup(app.extensions['jobs'].shutdown, wait=True)
            client = app.test_client()
            with patch('os.walk', side_effect=AssertionError('Web 不得扫描 RAW')):
                r_api = client.get('/api/v1/organizer?vendor=V1&library=MULTI')
                r_page = client.get('/path/library?vendor=V1&library=MULTI&ip=IP_A')
            self.assertEqual(r_api.status_code, 200)
            self.assertTrue(r_api.get_json()['track_statuses']['IP_A']['is_accepted'])
            self.assertEqual(r_page.status_code, 200)
            html = r_page.get_data(as_text=True)
            self.assertIn('organizer-initial-data', html)
            self.assertIn('sequence_organizer.js', html)

            # POST /api/v1/organizer/apply rejects protected IP_A rebuild with HTTP 400
            with client.session_transaction() as sess:
                csrf = sess['csrf']
            r_bad = client.post(
                '/api/v1/organizer/apply',
                headers={'X-CSRF-Token': csrf},
                json={
                    'vendor': 'V1',
                    'library': 'MULTI',
                    'tracks': {'IP_A': ['20261001_IP_A_v1'], 'IP_B': ['20261002_IP_B_v1', '20261005_IP_A_v2']},
                    'excluded': ['20261008_IP_A_IP_B_mix', '20261009_misc_notes'],
                    'rebuild_tracks': ['IP_A'],
                },
            )
            self.assertEqual(r_bad.status_code, 400)
            self.assertIn('受保护禁止归档重建', r_bad.get_json()['error'])

    def test_single_track_registration_times_ordering_and_rebuild(self):
        from ai_lib_qor.application.minimal_effective import _deliveries, _history
        from ai_lib_qor.application.path_acceptance import accept_revision
        from ai_lib_qor.application.path_config import registration_times
        from ai_lib_qor.application.path_refresh import refresh_all
        from ai_lib_qor.application.sequence_organizer import apply_sequence_plan, get_organizer_state
        from ai_lib_qor.sources.minimal_delivery import order_deliveries

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            raw, work = root / 'raw', root / 'work'
            work.mkdir()

            # Same-day pair + undated hotfix + later dated delivery
            for rel, w in (
                ('V1/SINGLE/20261001_v1/LEF/a.lef', 10),
                ('V1/SINGLE/20261001_v2/LEF/a.lef', 12),
                ('V1/SINGLE/rel_hotfix/LEF/a.lef', 14),
                ('V1/SINGLE/20261010_v3/LEF/a.lef', 16),
            ):
                p = raw / rel
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(_lef(w), encoding='utf-8')

            # Give initial same-day times so initial refresh succeeds cleanly
            (work / 'path_sources.json').write_text(json.dumps({
                'raw_root': str(raw),
                'update_formal': False,
                'libraries': {
                    'V1': {
                        'SINGLE': {
                            'version_registration_times': {
                                '20261001_v1': '2026-10-01T01:00:00Z',
                                '20261001_v2': '2026-10-01T02:00:00Z',
                            }
                        }
                    }
                },
            }), encoding='utf-8')
            refresh_all(work)

            st = get_organizer_state(work, 'V1', 'SINGLE')
            self.assertEqual(st['mode'], 'single_track')

            # Cross-date inversion MUST be rejected cleanly
            with self.assertRaises(ValueError) as inv_ctx:
                apply_sequence_plan(
                    work, 'V1', 'SINGLE',
                    order=['20261010_v3', '20261001_v1', '20261001_v2', 'rel_hotfix'],
                    excluded=[],
                    rebuild_tracks=[],
                )
            self.assertIn('目录日期优先规则不允许跨日期倒排', str(inv_ctx.exception))

            # Valid reorder: swap same-day (v2 before v1) AND place undated rel_hotfix between them + Policy A rebuild!
            desired = ['20261001_v2', 'rel_hotfix', '20261001_v1', '20261010_v3']
            res = apply_sequence_plan(
                work, 'V1', 'SINGLE',
                order=desired,
                excluded=[],
                rebuild_tracks=['__single__'],
                refresh=True,
                actor='test',
            )
            self.assertEqual(len(res['archived_tracks']), 1)
            self.assertTrue((work / res['archived_tracks'][0]['archive_dir'] / 'manifest.json').is_file())

            # Verify written version_registration_times reproduces desired order identically!
            folder = work / 'libraries/V1/SINGLE'
            reg = registration_times(work, 'V1', 'SINGLE')
            ordered_after = [r['version'] for r in order_deliveries(list(_deliveries(folder, 'V1', 'SINGLE').values()), reg)]
            self.assertEqual(ordered_after, desired)
            self.assertGreaterEqual(len(_history(folder, 'SINGLE')), 2)

            # Accepted single-track library is protected against rebuild
            accept_revision(work, 'V1', 'SINGLE', 'rev_0001', actor='reviewer', reason='locked')
            with self.assertRaises(ValueError) as acc_ctx:
                apply_sequence_plan(
                    work, 'V1', 'SINGLE',
                    order=['20261001_v1', '20261001_v2', 'rel_hotfix', '20261010_v3'],
                    excluded=[],
                    rebuild_tracks=['__single__'],
                )
            self.assertIn('受保护禁止归档重建', str(acc_ctx.exception))


if __name__ == '__main__':
    unittest.main()
