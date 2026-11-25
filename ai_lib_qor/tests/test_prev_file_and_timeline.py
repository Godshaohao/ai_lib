"""Tests for Mode A per-file chronological predecessor baseline (`__prev_file__`) and column-appending timeline Excel."""
import json
from pathlib import Path
import tempfile
import time
import unittest

import openpyxl

from ai_lib_qor.application.minimal_checks import run_revision
from ai_lib_qor.application.path_refresh import refresh_all
from ai_lib_qor.reporting.check_renderer import render_excel_from_check, render_timeline_excel_for_scope
from ai_lib_qor.versions.store import validate
from ai_lib_qor.workbench.path_app import create_path_app


def _lef(w: int) -> str:
    return f'VERSION 5.8 ;\nMACRO TOP\n SIZE {w} BY 2 ;\n PIN IN\n  DIRECTION INPUT ;\n END IN\nEND TOP\nEND LIBRARY\n'


_LIB = 'library(t) { cell(TOP) { pin(IN) { direction : input; } } }\n'


class PrevFileAndTimelineTests(unittest.TestCase):
    def test_prev_file_baseline_compares_folded_rev1_and_isolates_multi_ip_tracks(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            raw, work = root / 'raw', root / 'work'
            work.mkdir()

            # Multi-track library: IP_A has v1 (SIZE 10) -> v2 (SIZE 14) -> v3 (SIZE 18),
            # while IP_B has the EXACT same relative path LEF/top.lef (SIZE 99) dated between IP_A v1 & v2!
            # With initial_delivery_tail=1, v1+v2 are folded into rev_0001 (pointing to v2!), and v3 is rev_0002.
            for rel, txt in (
                ('V1/MULTI/20261001_IP_A_v1/LEF/top.lef', _lef(10)),
                ('V1/MULTI/20261001_IP_A_v1/LIB/top_tt.lib', _LIB),
                ('V1/MULTI/20261005_IP_B_v1/LEF/top.lef', _lef(99)),
                ('V1/MULTI/20261005_IP_B_v1/LIB/top_tt.lib', _LIB),
                ('V1/MULTI/20261010_IP_A_v2/LEF/top.lef', _lef(14)),
                ('V1/MULTI/20261010_IP_A_v2/LIB/top_tt.lib', _LIB),
                ('V1/MULTI/20261015_IP_A_v3/LEF/top.lef', _lef(18)),
                ('V1/MULTI/20261015_IP_A_v3/LIB/top_tt.lib', _LIB),
            ):
                p = raw / rel
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(txt, encoding='utf-8')

            # initial_delivery_tail=1 folds IP_A v1+v2 into a SINGLE rev_0001 pointing at v2!
            (work / 'path_sources.json').write_text(json.dumps({
                'raw_root': str(raw),
                'update_formal': False,
                'initial_delivery_tail': 1,
                'libraries': {'V1': {'MULTI': {'ip_type': 'ANALOG', 'ip_list': ['IP_A', 'IP_B']}}},
            }), encoding='utf-8')
            refresh_all(work)

            # Mode A on rev_0001 MUST compare IP_A v2 (14) against IP_A v1 (10) — NEVER IP_B v1 (99)!
            res = run_revision(
                work, 'V1', 'MULTI', 'rev_0001',
                baseline='__prev_file__',
                business_ip='IP_A',
                render=True,
                single_renderer=render_excel_from_check,
            )
            report = json.loads(Path(res['check']).read_text(encoding='utf-8'))
            validate(report, 'check_result_path')
            self.assertEqual(report['baseline'], '__prev_file__')
            self.assertEqual(len(report['comparisons']), 1)
            comp = report['comparisons'][0]
            self.assertEqual(comp['baseline_version'], '20261001_IP_A_v1')
            self.assertEqual(comp['version'], '20261010_IP_A_v2')
            self.assertEqual(comp['content_status'], 'CURRENT_CONTENT_DIFF')
            self.assertTrue(any(
                ch['attribute'] == 'SIZE' and ch['old_value'] == [10.0, 2.0] and ch['new_value'] == [14.0, 2.0]
                for ch in report['changes']
            ))

            # Single-rev Excel displays human-readable baseline label instead of raw __prev_file__
            wb1 = openpyxl.load_workbook(res['excel'], data_only=True)
            sheet0_text = '\n'.join(
                str(cell)
                for row in wb1.worksheets[0].iter_rows(values_only=True)
                for cell in row if cell is not None
            )
            self.assertIn('按文件上一时间版本', sheet0_text)
            self.assertNotIn('__prev_file__', sheet0_text)
            wb1.close()

    def test_dual_excel_and_incremental_column_appending_timeline(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            raw, work = root / 'raw', root / 'work'
            work.mkdir()

            # Start with 1 delivery -> rev_0001
            for rel, txt in (
                ('V1/TL_LIB/20261001_v1/LEF/top.lef', _lef(10)),
                ('V1/TL_LIB/20261001_v1/LIB/top_tt.lib', _LIB),
            ):
                p = raw / rel
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(txt, encoding='utf-8')

            (work / 'path_sources.json').write_text(json.dumps({
                'raw_root': str(raw),
                'update_formal': False,
            }), encoding='utf-8')
            refresh_all(work)

            app = create_path_app(work)
            self.addCleanup(app.extensions['jobs'].shutdown, wait=True)
            client = app.test_client()
            client.get('/path/library?vendor=V1&library=TL_LIB')
            with client.session_transaction() as sess:
                csrf = sess['csrf']

            # 1) Check rev_0001 via Web POST -> produces BOTH single-rev Excel AND timeline.xlsx (1 column)
            r_post1 = client.post('/path/check', data={
                'csrf': csrf, 'vendor': 'V1', 'library': 'TL_LIB',
                'revision': 'rev_0001', 'baseline': '__prev_file__',
                'lazy_excel': '0', 'update_timeline': '1',
            })
            self.assertEqual(r_post1.status_code, 302)

            log_dir = work / 'libraries/V1/TL_LIB/log'
            tl_path = log_dir / 'timeline.xlsx'
            self.assertTrue(tl_path.is_file())
            self.assertTrue(any(log_dir.glob('check_TL_LIB_rev_0001_*.xlsx')))

            wb_t1 = openpyxl.load_workbook(tl_path, data_only=True)
            self.assertEqual(wb_t1.sheetnames, ['00-版本演进时间线', '01-文件演进时间线', '02-规则与异常流水'])
            hdr_t1 = [c.value for c in wb_t1['00-版本演进时间线'][4] if c.value is not None]
            self.assertEqual(hdr_t1, ['演进指标', '有效版 #1 (rev_0001)'])

            # 2) Add delivery v2 -> refresh creates rev_0002 -> check ONLY latest rev_0002!
            for rel, txt in (
                ('V1/TL_LIB/20261010_v2/LEF/top.lef', _lef(16)),
                ('V1/TL_LIB/20261010_v2/LIB/top_tt.lib', _LIB),
            ):
                p = raw / rel
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(txt, encoding='utf-8')
            refresh_all(work)

            r_post2 = client.post('/path/check', data={
                'csrf': csrf, 'vendor': 'V1', 'library': 'TL_LIB',
                'revision': 'rev_0002', 'baseline': '__prev_file__',
                'lazy_excel': '0', 'update_timeline': '1',
            })
            self.assertEqual(r_post2.status_code, 302)
            self.assertTrue(any(log_dir.glob('check_TL_LIB_rev_0002_*.xlsx')))

            # Timeline Excel now has 2 columns (rev_0001 preserved + rev_0002 appended on the right!)
            wb_t2 = openpyxl.load_workbook(tl_path, data_only=True)
            hdr_t2 = [c.value for c in wb_t2['00-版本演进时间线'][4] if c.value is not None]
            self.assertEqual(hdr_t2, ['演进指标', '有效版 #1 (rev_0001)', '有效版 #2 (rev_0002)'])
            file_rows = list(wb_t2['01-文件演进时间线'].iter_rows(min_row=5, values_only=True))
            lef_row = next(r for r in file_rows if r[0] == 'LEF' and r[1] == 'LEF/top.lef')
            self.assertIn('20261001_v1', str(lef_row[2]))
            self.assertIn('20261010_v2', str(lef_row[3]))
            self.assertIn('内容变化', str(lef_row[3]))

            # 3) Artifact download endpoint serves fresh timeline.xlsx cleanly
            r_dl = client.get('/path/artifact?vendor=V1&library=TL_LIB&name=timeline.xlsx')
            self.assertEqual(r_dl.status_code, 200)
            self.assertGreater(len(r_dl.data), 1000)
            r_dl.close()

            # 4) Web library page embeds the 2-column timeline table and both Excel download links
            html = client.get('/path/library?vendor=V1&library=TL_LIB').get_data(as_text=True)
            self.assertIn('id="timeline-matrix-table"', html)
            self.assertIn('有效版 #1 (rev_0001)', html)
            self.assertIn('有效版 #2 (rev_0002)', html)
            self.assertIn('首版仅静态核验，其余以上一有效版本为基线', html)

            # A finished job links to its immutable report with the submitted scope.
            response = client.post('/api/v1/jobs/check', data={
                'csrf': csrf, 'vendor': 'V1', 'library': 'TL_LIB',
                'revision': 'rev_0002', 'baseline': '__prev_file__',
            })
            self.assertEqual(response.status_code, 202)
            job_url = '/api/v1/jobs/' + response.json['job_id']
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                job = client.get(job_url).json
                if job['status'] in ('SUCCEEDED', 'FAILED', 'CANCELLED'):
                    break
                time.sleep(0.02)
            self.assertEqual(job['status'], 'SUCCEEDED')
            report_link = job['result']['report_url']
            self.assertIn('/path/check/view?', report_link)
            self.assertIn(Path(job['result']['check']).name, report_link)
            self.assertEqual(client.get(report_link).status_code, 200)
            self.assertIn('下载本版明细 Excel', html)
            self.assertIn('下载演进时间线 Excel', html)
            self.assertIn('查最新版 rev_0002', html)


if __name__ == '__main__':
    unittest.main()
