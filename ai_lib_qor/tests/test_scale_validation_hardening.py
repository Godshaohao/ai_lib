"""Regression tests for 500-library scale hardening and unified Schema-validated reads."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from ai_lib_qor.application.facts_pool import load_check_bundle
from ai_lib_qor.application.minimal_checks import run_library, run_revision
from ai_lib_qor.application.path_query import find_latest_check
from ai_lib_qor.application.path_refresh import refresh_l1, refresh_l2, refresh_l3
from ai_lib_qor.application.path_storage import StorageStatsCache, _measure_folder, storage_stats
from ai_lib_qor.reporting.qor_views import build_overall_view
from ai_lib_qor.reporting.timeline_excel import build_timeline_model
from ai_lib_qor.sources.layout import library_folder
from ai_lib_qor.versions import store as version_store
from ai_lib_qor.workbench.path_app import create_path_app
from ai_lib_qor.workbench.read_cache import WorkbenchReadCache


def _write_delivery(raw_root: Path, vendor: str, lib: str, version: str, cell_suffix: str):
    ver_dir = raw_root / vendor / lib / version
    (ver_dir / 'lef').mkdir(parents=True, exist_ok=True)
    (ver_dir / 'lib').mkdir(parents=True, exist_ok=True)
    (ver_dir / 'lef' / 'std.lef').write_text(
        f'VERSION 5.8 ;\nMACRO INV_{cell_suffix}\n  CLASS CORE ;\n  SIZE 1.0 BY 2.0 ;\n'
        f'  PIN A\n    DIRECTION INPUT ;\n  END A\n  PIN Y\n    DIRECTION OUTPUT ;\n  END Y\n'
        f'END INV_{cell_suffix}\nEND LIBRARY\n',
        encoding='utf-8',
    )
    (ver_dir / 'lib' / 'tt_0p80v_25c.lib').write_text(
        f'library(demo_{cell_suffix}) {{\n'
        f'  nom_process : 1.0;\n  nom_voltage : 0.80;\n  nom_temperature : 25.0;\n'
        f'  cell(INV_{cell_suffix}) {{\n'
        f'    area : 2.0;\n'
        f'    pin(A) {{ direction : input; }}\n'
        f'    pin(Y) {{ direction : output; }}\n'
        f'  }}\n'
        f'}}\n',
        encoding='utf-8',
    )


class TestScaleValidationHardening(unittest.TestCase):
    def test_corrupt_check_result_rejected_everywhere(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw = root / 'raw'
            work = root / 'work'
            _write_delivery(raw, 'v1', 'libA', '20260101_v1', 'A')
            _write_delivery(raw, 'v1', 'libA', '20260102_v2', 'B')
            refresh_l1(work, raw_root=raw, raw=True, formal=False)
            refresh_l2(work)
            refresh_l3(work)

            r1 = run_revision(work, 'v1', 'libA', 'rev_0001', render=False)
            r2 = run_revision(work, 'v1', 'libA', 'rev_0002', baseline='rev_0001', render=False)
            folder = library_folder(work, 'v1', 'libA')
            log_dir = folder / 'log'

            # Write a corrupt newer check_*.json missing required field `note` and log it in runs.jsonl
            valid_doc = json.loads(Path(r2['check']).read_text(encoding='utf-8'))
            corrupt_doc = dict(valid_doc)
            corrupt_doc.pop('note', None)
            corrupt_doc['run_id'] = 'corrupt_999'
            corrupt_path = log_dir / 'check_libA_rev_0002_20991231_99.json'
            corrupt_path.write_text(json.dumps(corrupt_doc, ensure_ascii=False), encoding='utf-8')
            with (log_dir / 'runs.jsonl').open('a', encoding='utf-8') as stream:
                stream.write(json.dumps({
                    'type': 'CHECK',
                    'run_id': 'corrupt_999',
                    'revision': 'rev_0002',
                    'baseline': 'rev_0001',
                    'state': 'SUCCEEDED',
                    'time': '2099-12-31T00:00:00+00:00',
                    'json': f'log/{corrupt_path.name}',
                    'excel': None,
                }) + '\n')

            # 1. Lookup MUST skip the corrupt check and select the valid earlier check
            hit = find_latest_check(work, 'v1', 'libA', revision='rev_0002', baseline='rev_0001')
            self.assertIsNotNone(hit)
            self.assertEqual(hit['run_id'], r2['run_id'])
            self.assertNotEqual(hit['check_name'], corrupt_path.name)

            # 2. Strict bundle loader rejects corrupt file and caches the validation failure
            with self.assertRaises(ValueError):
                load_check_bundle(work, 'v1', 'libA', corrupt_path.name)
            with mock.patch.object(version_store, 'validate', wraps=version_store.validate) as m_val:
                with self.assertRaises(ValueError):
                    load_check_bundle(work, 'v1', 'libA', corrupt_path.name)
                check_val_calls = [c for c in m_val.call_args_list if c.args[1] == 'check_result_path']
                self.assertEqual(len(check_val_calls), 0)

            # 3. Overall view explicitly marks corrupt record and excludes it from PASS/FAIL counts
            ov_path = log_dir / 'overall_libA_20991231.json'
            ov_path.write_text(json.dumps({
                'vendor': 'v1',
                'library': 'libA',
                'versions': [
                    {'revision': 'rev_0001', 'state': 'SUCCEEDED', 'run_id': r1['run_id'], 'check': f'log/{Path(r1["check"]).name}'},
                    {'revision': 'rev_0002', 'state': 'SUCCEEDED', 'run_id': 'corrupt_999', 'check': f'log/{corrupt_path.name}'},
                ],
            }), encoding='utf-8')
            ov_view = build_overall_view(work, 'v1', 'libA', ov_path.name)
            self.assertEqual(ov_view['totals']['corrupt_count'], 1)
            self.assertEqual(ov_view['totals']['pass_count'] + ov_view['totals']['fail_count'] + ov_view['totals']['partial_count'], 1)
            corrupt_row = next(r for r in ov_view['versions'] if r['revision'] == 'rev_0002')
            self.assertTrue(corrupt_row['is_corrupt'])
            self.assertEqual(corrupt_row['quality']['code'], 'CORRUPT')
            self.assertIsNone(corrupt_row['check_name'])

            # 4. Timeline model skips corrupt file and uses valid check cleanly
            tl = build_timeline_model(work, 'v1', 'libA')
            self.assertEqual(len(tl['columns']), 2)
            self.assertEqual(tl['columns'][1]['run_id'], r2['run_id'])

            # 5. Web UI lists corrupt record as excluded and does NOT emit a broken HTML detail link
            app = create_path_app(work)
            client = app.test_client()
            resp = client.get('/path/library?vendor=v1&library=libA')
            self.assertEqual(resp.status_code, 200)
            html = resp.get_data(as_text=True)
            self.assertIn('记录损坏（Schema 无效）', html)
            self.assertNotIn(f'name={corrupt_path.name}', html)

    def test_l1_noop_sync_reads_deliveries_linearly(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw = root / 'raw'
            work = root / 'work'
            n_deliv = 20
            for i in range(1, n_deliv + 1):
                _write_delivery(raw, 'v1', 'libL1', f'202601{i:02d}_v{i}', f'C{i}')
            refresh_l1(work, raw_root=raw, raw=True, formal=False)

            # Clear in-memory read cache so we measure worst-case cold no-op disk reads
            with version_store._READ_CACHE_LOCK:
                version_store._READ_CACHE.clear()

            delivery_disk_reads = 0
            orig_read_text = Path.read_text

            def counting_read_text(self, *args, **kwargs):
                nonlocal delivery_disk_reads
                if self.name.startswith('delivery_') and self.name.endswith('.json'):
                    delivery_disk_reads += 1
                return orig_read_text(self, *args, **kwargs)

            with mock.patch.object(Path, 'read_text', counting_read_text):
                res = refresh_l1(work, raw_root=raw, raw=True, formal=False, verify_raw=False)

            self.assertEqual(res['delivery_created'], 0)
            self.assertEqual(res['delivery_unchanged'], n_deliv)
            self.assertEqual(res['raw_versions_walked'], 0)
            # Previously O(D^2) = 20*20 + 60 = 460+ reads; now <= D reads even from cold cache!
            self.assertLessEqual(delivery_disk_reads, n_deliv)

    def test_l2_batch_evolution_reuses_loaded_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw = root / 'raw'
            work = root / 'work'
            _write_delivery(raw, 'v1', 'libL2', '20260201_v01', 'D01')
            refresh_l1(work, raw_root=raw, raw=True, formal=False)
            refresh_l2(work)

            # Add 12 more deliveries and evolve all 12 in a single L2 batch
            n_batch = 12
            for i in range(2, n_batch + 2):
                _write_delivery(raw, 'v1', 'libL2', f'202602{i:02d}_v{i:02d}', f'D{i:02d}')
            refresh_l1(work, raw_root=raw, raw=True, formal=False)

            from ai_lib_qor.application import minimal_effective, path_refresh

            hist_calls = 0
            deliv_calls = 0
            orig_hist = minimal_effective._history
            orig_deliv = minimal_effective._deliveries

            def count_hist(*args, **kwargs):
                nonlocal hist_calls
                hist_calls += 1
                return orig_hist(*args, **kwargs)

            def count_deliv(*args, **kwargs):
                nonlocal deliv_calls
                deliv_calls += 1
                return orig_deliv(*args, **kwargs)

            with (
                mock.patch.object(minimal_effective, '_history', side_effect=count_hist),
                mock.patch.object(path_refresh, '_history', side_effect=count_hist),
                mock.patch.object(minimal_effective, '_deliveries', side_effect=count_deliv),
                mock.patch.object(path_refresh, '_deliveries', side_effect=count_deliv),
            ):
                res = refresh_l2(work)

            self.assertEqual(res['effective_published'], n_batch)
            # Constant per-library calls (was 3*D = 36+ history calls and D+2 = 14+ delivery scans)
            self.assertLessEqual(hist_calls, 4)
            self.assertLessEqual(deliv_calls, 3)

    def test_run_library_reduces_archive_enumerations_and_guards_tampering(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw = root / 'raw'
            work = root / 'work'
            for i in range(1, 7):
                _write_delivery(raw, 'v1', 'libChk', f'202603{i:02d}_v{i}', f'E{i}')
            refresh_l1(work, raw_root=raw, raw=True, formal=False)
            refresh_l2(work)
            refresh_l3(work)

            from ai_lib_qor.application import minimal_file_index

            with mock.patch.object(
                minimal_file_index, '_archive_stat_summary', wraps=minimal_file_index._archive_stat_summary
            ) as m_stat:
                run_library(work, 'v1', 'libChk', rerun=True, render_single_excel=False)
                rerun_enums = m_stat.call_count

            with mock.patch.object(
                minimal_file_index, '_archive_stat_summary', wraps=minimal_file_index._archive_stat_summary
            ) as m_stat:
                run_library(work, 'v1', 'libChk', rerun=False, render_single_excel=False)
                reuse_enums = m_stat.call_count

            # 6 revisions: reuse previously did 7+, now <= 3; rerun previously did 13+, now <= 9
            self.assertLessEqual(reuse_enums, 3)
            self.assertLessEqual(rerun_enums, 9)

    def test_storage_stats_cache_staggered_and_budgeted_recheck(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            work = root / 'work'
            libs_root = work / 'libraries' / 'v1'
            for i in range(30):
                d = libs_root / f'lib_{i:02d}' / 'delivery'
                d.mkdir(parents=True, exist_ok=True)
                (d / f'delivery_lib_{i:02d}__v1.json').write_text('{}', encoding='utf-8')

            now_val = [1000.0]
            cache = StorageStatsCache(max_age=60, recheck_budget=4, stagger_ratio=0.5)

            with (
                mock.patch('ai_lib_qor.application.path_storage.monotonic', side_effect=lambda: now_val[0]),
                mock.patch('ai_lib_qor.application.path_storage._measure_folder', wraps=_measure_folder) as m_meas,
            ):
                storage_stats(work, cache=cache)
                self.assertEqual(m_meas.call_count, 30)

                # Warm read: 0 rescans
                m_meas.reset_mock()
                now_val[0] = 1010.0
                storage_stats(work, cache=cache)
                self.assertEqual(m_meas.call_count, 0)

                # All 30 expired simultaneously (+200s): capped to recheck_budget=4, no 30-library storm!
                m_meas.reset_mock()
                now_val[0] = 1200.0
                storage_stats(work, cache=cache)
                self.assertEqual(m_meas.call_count, 4)

                # Modify 1 library: that library MUST rescan immediately in addition to any budget
                m_meas.reset_mock()
                changed_file = libs_root / 'lib_29' / 'delivery' / 'delivery_lib_29__v2.json'
                changed_file.write_text('{"extra": true}', encoding='utf-8')
                storage_stats(work, cache=cache)
                # 4 budgeted expired + 1 actually changed (or 4 if lib_29 was inside the 4)
                self.assertLessEqual(m_meas.call_count, 5)
                measured_folders = {call.args[0].name for call in m_meas.call_args_list}
                self.assertIn('lib_29', measured_folders)

    def test_http_request_computes_work_signature_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw = root / 'raw'
            work = root / 'work'
            _write_delivery(raw, 'v1', 'libSig', '20260401_v1', 'S1')
            refresh_l1(work, raw_root=raw, raw=True, formal=False)
            refresh_l2(work)
            refresh_l3(work)

            app = create_path_app(work)
            client = app.test_client()

            with mock.patch.object(WorkbenchReadCache, 'signature', wraps=WorkbenchReadCache.signature, autospec=True) as m_sig:
                r_home = client.get('/')
                self.assertEqual(r_home.status_code, 200)
                self.assertLessEqual(m_sig.call_count, 1)

                m_sig.reset_mock()
                r_lib = client.get('/path/library?vendor=v1&library=libSig')
                self.assertEqual(r_lib.status_code, 200)
                # Single-library page now uses library_signature + sidebar_signature (0 full-work signature calls!)
                self.assertEqual(m_sig.call_count, 0)

    def test_workspace_activity_top_k_avoids_reading_all_deliveries(self):
        from ai_lib_qor.application.path_query import workspace_activity_and_readiness

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw = root / 'raw'
            work = root / 'work'
            for i in range(1, 21):
                _write_delivery(raw, 'v1', 'libTopK', f'202605{i:02d}_v{i:02d}', f'T{i:02d}')
            refresh_l1(work, raw_root=raw, raw=True, formal=False)

            with version_store._READ_CACHE_LOCK:
                version_store._READ_CACHE.clear()
            reads = [0]
            orig_rt = Path.read_text

            def count_rt(self, *a, **kw):
                if self.name.startswith('delivery_') and self.name.endswith('.json'):
                    reads[0] += 1
                return orig_rt(self, *a, **kw)

            with mock.patch.object(Path, 'read_text', count_rt):
                act = workspace_activity_and_readiness(work, days=7, max_raw_rows=5)

            self.assertEqual(act['counts']['raw_deliveries'], 20)
            self.assertEqual(len(act['raw_changes']), 5)
            self.assertTrue(act['raw_changes_truncated'])
            self.assertLessEqual(reads[0], 5)

    def test_single_pass_liberty_lef_hashing_and_strict_utf8(self):
        import gzip
        import hashlib
        from ai_lib_qor.facts import parsers

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            lib_plain = root / 'demo.lib'
            lib_gz = root / 'demo.lib.gz'
            lef_plain = root / 'demo.lef'
            bad_utf8 = root / 'bad.lib'

            lib_txt = (
                'library(demo_sp) {\n'
                '  nom_process : 1.0;\n  nom_voltage : 0.8;\n  nom_temperature : 25.0;\n'
                '  cell(INV_X1) { area : 1.0; pin(A) { direction : input; } pin(Y) { direction : output; } }\n'
                '}\n'
            )
            lef_txt = (
                'VERSION 5.8 ;\nMACRO INV_X1\n  CLASS CORE ;\n  SIZE 1.0 BY 2.0 ;\n'
                '  PIN A\n    DIRECTION INPUT ;\n  END A\nEND INV_X1\nEND LIBRARY\n'
            )
            lib_plain.write_text(lib_txt, encoding='utf-8')
            with gzip.open(lib_gz, 'wb') as gz:
                gz.write(lib_txt.encode('utf-8'))
            lef_plain.write_text(lef_txt, encoding='utf-8')
            bad_utf8.write_bytes(b'library(bad) { \xff\xfe }\n')

            for target_path, view in ((lib_plain, 'LIBERTY'), (lib_gz, 'LIBERTY'), (lef_plain, 'LEF')):
                open_cnt = [0]
                orig_open = Path.open

                def spy_open(self, *a, **kw):
                    if self.resolve() == target_path.resolve():
                        open_cnt[0] += 1
                    return orig_open(self, *a, **kw)

                digest_box = {}
                with mock.patch.object(Path, 'open', spy_open):
                    payload = parsers.parse_file_payload(target_path, view, allow_pg=True, digest_out=digest_box)
                self.assertEqual(payload['view'], view)
                self.assertEqual(digest_box['sha256'], hashlib.sha256(target_path.read_bytes()).hexdigest())
                self.assertEqual(open_cnt[0], 1)

            with self.assertRaises(UnicodeDecodeError):
                parsers.parse_file_payload(bad_utf8, 'LIBERTY', allow_pg=True, digest_out={})

    def test_large_workspace_lazy_tabs_pagination_and_sidebar_api(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            work = root / 'work'
            for i in range(60):
                d = work / 'libraries' / f'V{i // 20}' / f'LIB_{i:03d}' / 'delivery'
                d.mkdir(parents=True, exist_ok=True)
                (d / f'delivery_LIB_{i:03d}__v1.json').write_text(
                    json.dumps({'vendor': f'V{i // 20}', 'library': f'LIB_{i:03d}', 'version': 'v1', 'version_date': '2026-01-01', 'root': '/tmp/x', 'views': {}}),
                    encoding='utf-8',
                )

            app = create_path_app(work)
            client = app.test_client()

            # 1. Default overview skips collect_json_inventory and renders compact sidebar & lazy libraries
            with mock.patch('ai_lib_qor.workbench.routes_pages._collect_json_inventory') as m_inv:
                r_home = client.get('/')
                self.assertEqual(r_home.status_code, 200)
                self.assertEqual(m_inv.call_count, 0)
            home_html = r_home.get_data(as_text=True)
            self.assertIn('data-remote-search="1"', home_html)
            self.assertIn('来源库清单已启用分页按需加载（共 60 个库）', home_html)

            # 2. ?view=libraries paginates 50 per page (page 2 has 10 rows)
            r_p2 = client.get('/?view=libraries&lib_page=2')
            self.assertEqual(r_p2.status_code, 200)
            p2_html = r_p2.get_data(as_text=True)
            self.assertIn('第 2 / 2 页', p2_html)
            self.assertIn('LIB_059', p2_html)
            self.assertNotIn('LIB_000', p2_html.split('id="libraries-table"')[1])

            # 3. /api/v1/libraries searches across all 60 libraries
            r_api = client.get('/api/v1/libraries?q=lib_05')
            self.assertEqual(r_api.status_code, 200)
            data = r_api.get_json()
            self.assertEqual(data['total'], 60)
            self.assertEqual(data['matched'], 10)

    def test_subprocess_isolated_job_runs_in_child_pid(self):
        import os
        import time

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw = root / 'raw'
            work = root / 'work'
            _write_delivery(raw, 'v1', 'libSub', '20260601_v1', 'SUB1')
            refresh_l1(work, raw_root=raw, raw=True, formal=False)
            refresh_l2(work)
            refresh_l3(work)

            app = create_path_app(work, subprocess_jobs=True)
            self.addCleanup(app.extensions['jobs'].shutdown, wait=True)
            client = app.test_client()
            client.get('/')
            with client.session_transaction() as sess:
                csrf = sess['csrf']

            resp = client.post('/api/v1/jobs/check', data={
                'csrf': csrf,
                'kind': 'single',
                'vendor': 'v1',
                'library': 'libSub',
                'revision': 'rev_0001',
                'lazy_excel': '1',
                'update_timeline': '0',
            })
            self.assertEqual(resp.status_code, 202)
            job_id = resp.get_json()['job_id']

            deadline = time.monotonic() + 20.0
            final_job = None
            while time.monotonic() < deadline:
                st = client.get(f'/api/v1/jobs/{job_id}').get_json()
                if st['status'] in ('SUCCEEDED', 'FAILED', 'CANCELLED', 'PARTIAL'):
                    final_job = st
                    break
                time.sleep(0.1)

            self.assertIsNotNone(final_job)
            self.assertEqual(final_job['status'], 'SUCCEEDED', msg=str(final_job))
            self.assertNotEqual(final_job['result'].get('_worker_pid'), os.getpid())
            # Also confirm zero leaked .staging.tmp files in facts/
            facts_dir = library_folder(work, 'v1', 'libSub') / 'facts'
            self.assertEqual(list(facts_dir.glob('*.staging.tmp')), [])


if __name__ == '__main__':
    unittest.main()
