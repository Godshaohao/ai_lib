import json
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from ai_lib_qor.application.minimal_file_index import index_manifest_matches, read_manifest
from ai_lib_qor.application.path_query import PathDataQuery
from ai_lib_qor.application.path_refresh import refresh_all, refresh_l1, refresh_status
from ai_lib_qor.workbench.jobs import JobManager, check_cancel, emit_progress
from ai_lib_qor.workbench.path_app import create_path_app


class ScaleDefenseAndJobsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.raw = root / 'raw'
        self.nl = root / 'NL1'
        self.nl.mkdir()
        self.work = root / 'work'
        self.work.mkdir()

        # Two libraries with LEF + .db + .gds + ignored noise files
        for v, lib in (('V1', 'lib_a'), ('V2', 'lib_b')):
            for ver in ('20261001_r01', '20261002_r02'):
                base = self.raw / v / lib / ver
                (base / 'LEF').mkdir(parents=True, exist_ok=True)
                (base / 'GDS').mkdir(parents=True, exist_ok=True)
                (base / 'DB').mkdir(parents=True, exist_ok=True)
                (base / 'tmp_logs').mkdir(parents=True, exist_ok=True)
                lef = base / 'LEF/cell.lef'
                lef.write_text('MACRO A\n SIZE 2 BY 3 ;\n PIN IN\n  DIRECTION INPUT ;\n END IN\nEND A\n', encoding='utf-8')
                (base / 'GDS/cell.gds').write_bytes(b'BINARY_GDS_DATA')
                (base / 'DB/cell.db').write_bytes(b'BINARY_DB_DATA')
                (base / 'tmp_logs/debug.log').write_text('noise', encoding='utf-8')
                (base / 'LEF/junk.tmp').write_text('noise', encoding='utf-8')
                if ver == '20261001_r01':
                    lnk = self.nl / v / lib / 'cell.lef'
                    lnk.parent.mkdir(parents=True, exist_ok=True)
                    lnk.symlink_to(lef)

        (self.work / 'path_sources.json').write_text(json.dumps({
            'raw_root': str(self.raw),
            'nl_root': str(self.nl),
            'nl_version': 'NL1',
            'ignore_patterns': ['*.tmp', 'tmp_logs'],
        }), encoding='utf-8')

    def test_l1_incremental_skip_single_library_direct_and_ignore_patterns(self):
        # First full refresh walks all 4 version dirs, ignores *.tmp & tmp_logs, records GDS/DB without reading content
        res1 = refresh_all(self.work)
        self.assertEqual(res1['l1']['raw_versions_walked'], 4)
        self.assertEqual(res1['l1']['raw_versions_skipped'], 0)

        idx = PathDataQuery(self.work).index('V1', 'lib_a')
        self.assertIn('GDS', idx['views'])
        self.assertIn('DB', idx['views'])
        all_paths = {p for grp in idx['views'].values() for p in grp}
        self.assertNotIn('LEF/junk.tmp', all_paths)
        self.assertNotIn('tmp_logs/debug.log', all_paths)

        # Second incremental L1 skips os.walk on all 4 already-archived version dirs (even with Formal enabled!)
        res2 = refresh_l1(self.work, raw=True, formal=True, verify_raw=False)
        self.assertEqual(res2['raw_versions_walked'], 0)
        self.assertEqual(res2['raw_versions_skipped'], 4)

        # Explicit verify_raw=True walks all 4 historical version dirs
        res_verify = refresh_l1(self.work, raw=True, formal=False, verify_raw=True)
        self.assertEqual(res_verify['raw_versions_walked'], 4)
        self.assertEqual(res_verify['raw_versions_skipped'], 0)

        # Adding a 3rd version in V1/lib_a and running single-library refresh walks ONLY that 1 new version!
        v3 = self.raw / 'V1/lib_a/20261003_r03/LEF/cell.lef'
        v3.parent.mkdir(parents=True)
        v3.write_text('MACRO A\n SIZE 3 BY 3 ;\n PIN IN\n  DIRECTION INPUT ;\n END IN\nEND A\n', encoding='utf-8')
        res_single = refresh_l1(self.work, raw=True, formal=False, vendor='V1', library='lib_a', verify_raw=False)
        self.assertEqual(res_single['raw_versions_walked'], 1)
        self.assertEqual(res_single['raw_versions_skipped'], 2)
        self.assertEqual(res_single['delivery_created'], 1)

    def test_fast_manifest_overview_vs_strict_sha256_on_library_read(self):
        refresh_all(self.work)
        manifest = read_manifest(self.work, 'V1', 'lib_a')
        self.assertIn('fast_stat', manifest)

        # Fast mode matches without hashing
        ok_fast, _ = index_manifest_matches(self.work, 'V1', 'lib_a', fast=True)
        self.assertTrue(ok_fast)

        # Tamper delivery JSON with preserved size & mtime -> strict PathDataQuery.index() STILL catches it!
        dfile = next((self.work / 'libraries/V1/lib_a/delivery').glob('delivery_*.json'))
        st = dfile.stat()
        original = dfile.read_text(encoding='utf-8')
        tampered = original.replace('LEF/cell.lef', 'LEF/xxxx.lef')
        self.assertEqual(len(tampered), len(original))
        dfile.write_text(tampered, encoding='utf-8')
        os.utime(dfile, ns=(st.st_atime_ns, st.st_mtime_ns))

        # Overview fast status sees unchanged stat, while strict library read catches content tampering!
        st_overview = refresh_status(self.work)
        self.assertEqual(st_overview['totals']['libraries'], 2)
        with self.assertRaisesRegex(ValueError, '索引'):
            PathDataQuery(self.work).index('V1', 'lib_a')

    def test_job_manager_progress_and_cooperative_cancellation_via_web_api(self):
        refresh_all(self.work)
        app = create_path_app(self.work)
        self.addCleanup(app.extensions['jobs'].shutdown, wait=True)
        client = app.test_client()
        client.get('/')
        with client.session_transaction() as sess:
            csrf = sess['csrf']

        # Submit a controlled long-running job directly on app's JobManager to test progress + Web cancel API
        started = threading.Event()
        jm: JobManager = app.extensions['jobs']

        def slow_task(progress_cb, cancel_event):
            emit_progress(progress_cb, 'STEP', '步骤 1/5', completed=1, total=5)
            started.set()
            for i in range(2, 50):
                check_cancel(cancel_event, '用户点击终止任务')
                emit_progress(progress_cb, 'STEP', f'步骤 {i}/50', completed=i, total=50)
                time.sleep(0.02)
            return {'done': True}

        job = jm.submit('demo', '长耗时模拟任务', slow_task)
        jid = job['job_id']
        self.assertTrue(started.wait(timeout=2.0))

        # Cancel without CSRF -> 403
        self.assertEqual(client.post(f'/api/v1/jobs/{jid}/cancel').status_code, 403)

        # Cancel with X-CSRF-Token -> 200 & transitions to CANCELLING -> CANCELLED
        cancel_resp = client.post(f'/api/v1/jobs/{jid}/cancel', headers={'X-CSRF-Token': csrf})
        self.assertEqual(cancel_resp.status_code, 200)
        self.assertIn(cancel_resp.get_json()['status'], ('CANCELLING', 'CANCELLED'))

        final_job = None
        for _ in range(50):
            r = client.get(f'/api/v1/jobs/{jid}')
            self.assertEqual(r.status_code, 200)
            final_job = r.get_json()
            if final_job['status'] in ('CANCELLED', 'SUCCEEDED', 'FAILED'):
                break
            time.sleep(0.03)
        self.assertIsNotNone(final_job)
        self.assertEqual(final_job['status'], 'CANCELLED', final_job)
        self.assertTrue(final_job['cancel_requested'])
        self.assertTrue(any('终止' in e for e in final_job['events']))


if __name__ == '__main__':
    unittest.main()
