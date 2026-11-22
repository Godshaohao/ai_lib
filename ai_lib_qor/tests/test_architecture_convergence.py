import io
import json
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from ai_lib_qor.application.minimal_checks import run_revision
from ai_lib_qor.application.path_acceptance import accept_revision, acceptance_status, rollback_acceptance
from ai_lib_qor.application.path_batch import check_pending
from ai_lib_qor.application.path_refresh import refresh_all
from ai_lib_qor.application.path_storage import clean_cache, storage_stats
from ai_lib_qor.cli import format_table, main as cli_main, parser, run as cli_run
from ai_lib_qor.facts.parsers import parse_file_payload
from ai_lib_qor.workbench.path_app import create_path_app


class ArchitectureConvergenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.root = root
        self.raw = root / 'raw'
        self.nl = root / 'NL1'
        self.nl.mkdir()
        self.work = root / 'work'
        self.work.mkdir()

        # Library 1: 2 versions with real LEF size diff & matching Liberty (many pins to test server pagination)
        v1, v2 = '20261001_r01', '20261002_r02'
        lef_pins = '\n'.join(f' PIN P{i:02d}\n  DIRECTION {"INPUT" if i % 2 == 0 else "OUTPUT"} ;\n END P{i:02d}' for i in range(25))
        lib_pins = ' '.join(f'pin(P{i:02d}) {{ direction : {"input" if i % 2 == 0 else "output"}; }}' for i in range(25))
        lef_v1 = f'MACRO CELL_A\n SIZE 2 BY 3 ;\n{lef_pins}\nEND CELL_A\n'
        lef_v2 = f'MACRO CELL_A\n SIZE 4 BY 3 ;\n{lef_pins}\nEND CELL_A\n'
        lib_txt = f'library(demo) {{ cell(CELL_A) {{ {lib_pins} }} }}\n'

        for ver, lef_txt in ((v1, lef_v1), (v2, lef_v2)):
            lp = self.raw / 'V1/lib_a' / ver / 'LEF/a.lef'
            lp.parent.mkdir(parents=True, exist_ok=True)
            lp.write_text(lef_txt, encoding='utf-8')
            bp = self.raw / 'V1/lib_a' / ver / 'LIB/a.lib'
            bp.parent.mkdir(parents=True, exist_ok=True)
            bp.write_text(lib_txt, encoding='utf-8')
            if ver == v1:
                (self.nl / 'V1/lib_a/a.lef').parent.mkdir(parents=True, exist_ok=True)
                (self.nl / 'V1/lib_a/a.lef').symlink_to(lp)
                (self.nl / 'V1/lib_a/a.lib').symlink_to(bp)

        # Library 2: SRAM with Liberty type() + bus() syntax
        sram_lef = (
            'MACRO SRAM_4X2\n SIZE 10 BY 10 ;\n'
            ' PIN clk\n  DIRECTION INPUT ;\n END clk\n'
            ' PIN dout[1]\n  DIRECTION OUTPUT ;\n END dout[1]\n'
            ' PIN dout[0]\n  DIRECTION OUTPUT ;\n END dout[0]\n'
            'END SRAM_4X2\n'
        )
        sram_lib = (
            'library(sram_lib) {\n'
            '  type (DATA2) { base_type : array; data_type : bit; bit_width : 2; bit_from : 1; bit_to : 0; downto : true; }\n'
            '  cell(SRAM_4X2) {\n'
            '    pin(clk) { direction : input; }\n'
            '    bus(dout) { bus_type : DATA2; direction : output; }\n'
            '  }\n'
            '}\n'
        )
        sp_lef = self.raw / 'V2/sram_b' / v1 / 'LEF/sram.lef'
        sp_lef.parent.mkdir(parents=True, exist_ok=True)
        sp_lef.write_text(sram_lef, encoding='utf-8')
        sp_lib = self.raw / 'V2/sram_b' / v1 / 'LIB/sram.lib'
        sp_lib.parent.mkdir(parents=True, exist_ok=True)
        sp_lib.write_text(sram_lib, encoding='utf-8')
        (self.nl / 'V2/sram_b/sram.lef').parent.mkdir(parents=True, exist_ok=True)
        (self.nl / 'V2/sram_b/sram.lef').symlink_to(sp_lef)
        (self.nl / 'V2/sram_b/sram.lib').symlink_to(sp_lib)

        (self.work / 'path_sources.json').write_text(json.dumps({
            'raw_root': str(self.raw),
            'nl_root': str(self.nl),
            'nl_version': 'NL1',
        }), encoding='utf-8')
        refresh_all(self.work)

    def test_liberty_bus_type_expansion_and_pin_match(self):
        # Verify synthetic SRAM bus() expands dout[1], dout[0] and passes LEF/Liberty pin match
        res = run_revision(self.work, 'V2', 'sram_b', 'rev_0001', render=False)
        self.assertEqual(res['state'], 'SUCCEEDED')
        report = json.loads(Path(res['check']).read_text(encoding='utf-8'))
        pin_chk = next(c for c in report['checks'] if c['check_id'] == 'LEF_LIBERTY_PIN_MATCH')
        self.assertEqual(pin_chk['result'], 'PASS')

        # If real downloaded fakeram45 seed exists in repo, verify it parses cleanly too
        seed = Path(__file__).resolve().parents[1] / 'examples/open_pdk_seeds/nangate45/lib/fakeram45_256x32.lib'
        if seed.is_file():
            payload = parse_file_payload(seed, 'LIBERTY', allow_pg=True)
            self.assertEqual(payload['parse_status'], 'COMPLETE')
            self.assertGreater(len(payload['objects']['cells'][0]['pins']), 100)

    def test_acceptance_pointer_separated_from_latest_and_web_flow(self):
        st0 = acceptance_status(self.work, 'V1', 'lib_a')
        self.assertEqual(st0['latest_revision'], 'rev_0002')
        self.assertIsNone(st0['accepted_revision'])
        self.assertFalse(st0['is_latest_accepted'])

        # Accept rev_0001 via CLI
        args = parser().parse_args([
            'accept-revision', '--work', str(self.work), '--vendor', 'V1', '--library', 'lib_a',
            '--revision', 'rev_0001', '--reason', '初版人工复核通过', '--actor', 'qa-lead',
        ])
        res1 = cli_run(args)
        self.assertEqual(res1['state'], 'ACCEPTED')
        st1 = acceptance_status(self.work, 'V1', 'lib_a')
        self.assertEqual(st1['latest_revision'], 'rev_0002')
        self.assertEqual(st1['accepted_revision'], 'rev_0001')
        self.assertFalse(st1['is_latest_accepted'])

        # Accept rev_0002 then rollback to rev_0001 via Web POST /path/acceptance
        app = create_path_app(self.work)
        self.addCleanup(app.extensions['jobs'].shutdown, wait=True)
        client = app.test_client()
        client.get('/')
        with client.session_transaction() as sess:
            csrf = sess['csrf']
        r_acc = client.post('/path/acceptance', data={
            'csrf': csrf, 'vendor': 'V1', 'library': 'lib_a',
            'action': 'accept', 'revision': 'rev_0002', 'reason': '升级采纳',
        }, follow_redirects=True)
        self.assertEqual(r_acc.status_code, 200)
        self.assertIn('已人工采纳 rev_0002', r_acc.get_data(as_text=True))

        rb = rollback_acceptance(self.work, 'V1', 'lib_a', 'rev_0001', actor='qa-lead', reason='回退至稳定版')
        self.assertEqual(rb['state'], 'ROLLED_BACK')
        st2 = acceptance_status(self.work, 'V1', 'lib_a')
        self.assertEqual(st2['latest_revision'], 'rev_0002')
        self.assertEqual(st2['accepted_revision'], 'rev_0001')
        self.assertEqual(len(st2['history']), 3)

    def test_check_pending_incremental_and_storage_cache_clean(self):
        # First check_pending runs on both libraries (render_excel=False by default)
        first = check_pending(self.work, render_excel=False)
        self.assertEqual(first['checked_count'], 2)
        self.assertEqual(first['skipped_already_checked_count'], 0)

        # Second check_pending skips both because latest revisions already have saved checks
        second = check_pending(self.work, render_excel=False)
        self.assertEqual(second['checked_count'], 0)
        self.assertEqual(second['skipped_already_checked_count'], 2)

        # Eagerly render an Excel, then test storage_stats + cache_clean (dry_run vs apply)
        r_xlsx = run_revision(self.work, 'V1', 'lib_a', 'rev_0002', render=True)
        xlsx_path = Path(r_xlsx['excel'])
        self.assertTrue(xlsx_path.is_file())

        # Create an unreferenced orphan pool file to verify orphan cleanup
        orphan = self.work / 'libraries/V1/lib_a/facts/fact_ca_LEF_0000000000000000.json.gz'
        orphan.write_bytes(b'orphan')

        stats = storage_stats(self.work)
        self.assertEqual(stats['library_count'], 2)
        self.assertGreater(stats['authoritative_bytes'], 0)
        self.assertGreater(stats['rebuildable_cache_bytes'], 0)
        self.assertIn('工作目录', format_table('storage-stats', stats))

        dry = clean_cache(self.work, clean_excel=True, clean_orphan_facts=True, dry_run=True)
        self.assertGreaterEqual(dry['removed_count'], 2)
        self.assertTrue(xlsx_path.is_file())
        self.assertTrue(orphan.is_file())

        applied = clean_cache(self.work, clean_excel=True, clean_orphan_facts=True, dry_run=False)
        self.assertEqual(applied['removed_count'], dry['removed_count'])
        self.assertFalse(xlsx_path.exists())
        self.assertFalse(orphan.exists())
        # Authoritative check JSON & effective history MUST remain untouched
        self.assertTrue(Path(r_xlsx['check']).is_file())
        self.assertTrue((self.work / 'libraries/V1/lib_a/effective/effective_lib_a_002.json').is_file())

    def test_web_json_api_pagination_and_async_jobs(self):
        r = run_revision(self.work, 'V1', 'lib_a', 'rev_0002', render=False)
        check_name = Path(r['check']).name
        report = json.loads(Path(r['check']).read_text(encoding='utf-8'))
        lef_ref = Path(next(f['facts'] for f in report['files'] if f['view'] == 'LEF')).name

        app = create_path_app(self.work)
        self.addCleanup(app.extensions['jobs'].shutdown, wait=True)
        client = app.test_client()
        client.get('/')
        with client.session_transaction() as sess:
            csrf = sess['csrf']

        # Read-only JSON APIs
        ov = client.get('/api/v1/overview')
        self.assertEqual(ov.status_code, 200)
        self.assertEqual(ov.get_json()['storage']['library_count'], 2)

        lib_api = client.get('/api/v1/library', query_string={'vendor': 'V1', 'library': 'lib_a'})
        self.assertEqual(lib_api.status_code, 200)
        self.assertEqual(lib_api.get_json()['revisions'], ['rev_0001', 'rev_0002'])

        chk_api = client.get('/api/v1/check', query_string={'vendor': 'V1', 'library': 'lib_a', 'name': check_name})
        self.assertEqual(chk_api.status_code, 200)
        self.assertEqual(chk_api.get_json()['report']['revision'], 'rev_0002')

        # Verify Liberty lowercase direction is normalized to uppercase in KPI metrics (not 0 / 0)
        lib_ref = Path(next(f['facts'] for f in report['files'] if f['view'] == 'LIBERTY')).name
        lib_api = client.get('/api/v1/facts', query_string={
            'vendor': 'V1', 'library': 'lib_a', 'check': check_name, 'ref': lib_ref,
        })
        self.assertEqual(lib_api.status_code, 200)
        lmetrics = {m['label']: m['value'] for m in lib_api.get_json()['summary_metrics']}
        self.assertEqual(lmetrics['INPUT / OUTPUT'], '13 / 12')
        self.assertEqual(lmetrics['INOUT / 其他'], 0)

        # Server-side pagination on /api/v1/facts and /path/facts/view (25 pins -> per_page=10 -> 3 pages)
        f_api = client.get('/api/v1/facts', query_string={
            'vendor': 'V1', 'library': 'lib_a', 'check': check_name, 'ref': lef_ref, 'per_page': '10', 'pin_page': '2',
        })
        self.assertEqual(f_api.status_code, 200)
        fdata = f_api.get_json()
        self.assertEqual(len(fdata['pins']), 10)
        self.assertEqual(fdata['pagination']['pin_total'], 25)
        self.assertEqual(fdata['pagination']['pin_pages'], 3)
        self.assertEqual(fdata['pagination']['pin_page'], 2)

        html_page = client.get('/path/facts/view', query_string={
            'vendor': 'V1', 'library': 'lib_a', 'check': check_name, 'ref': lef_ref, 'per_page': '10', 'pin_page': '2',
        })
        self.assertEqual(html_page.status_code, 200)
        self.assertIn('Pin 第 2 / 3 页', html_page.get_data(as_text=True))

        # CSRF enforced on async job endpoints
        self.assertEqual(client.post('/api/v1/jobs/check', data={'kind': 'pending'}).status_code, 403)

        # Submit async job & poll to SUCCEEDED
        sub = client.post('/api/v1/jobs/check', data={
            'csrf': csrf, 'kind': 'pending', 'lazy_excel': '1',
        })
        self.assertEqual(sub.status_code, 202)
        job_id = sub.get_json()['job_id']

        final_job = None
        for _ in range(50):
            poll = client.get(f'/api/v1/jobs/{job_id}')
            self.assertEqual(poll.status_code, 200)
            final_job = poll.get_json()
            if final_job['status'] in ('SUCCEEDED', 'FAILED'):
                break
            time.sleep(0.05)
        self.assertIsNotNone(final_job)
        self.assertEqual(final_job['status'], 'SUCCEEDED', final_job)
        self.assertEqual(final_job['result']['checked_count'], 1)  # V2/sram_b was still pending

        # CLI --format table works cleanly via main()
        buf = io.StringIO()
        with patch('sys.argv', ['ai_lib_qor', 'refresh-status', '--work', str(self.work), '--format', 'table']), redirect_stdout(buf):
            rc = cli_main()
        self.assertEqual(rc, 0)
        self.assertIn('lib_a', buf.getvalue())
        self.assertIn('sram_b', buf.getvalue())


if __name__ == '__main__':
    unittest.main()
