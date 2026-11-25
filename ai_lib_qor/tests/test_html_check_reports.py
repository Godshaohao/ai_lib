"""Tests for inline HTML check dashboard, multi-version Overall HTML view, and self-contained offline HTML export."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


def _lef(w: int) -> str:
    return f'VERSION 5.8 ;\nMACRO A\n SIZE {w} BY 2 ;\n PIN IN\n  DIRECTION INPUT ;\n END IN\nEND A\nEND LIBRARY\n'


class HtmlCheckReportsTests(unittest.TestCase):
    def test_inline_check_dashboard_overall_view_and_offline_html_exports(self):
        from ai_lib_qor.application.minimal_checks import run_library, run_revision
        from ai_lib_qor.application.path_acceptance import accept_revision
        from ai_lib_qor.application.path_config import update_library_config
        from ai_lib_qor.application.path_refresh import refresh_all
        from ai_lib_qor.workbench.path_app import create_path_app

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            raw, work = root / 'raw', root / 'work'
            work.mkdir()

            for ver, w in (('20261001_v1', 10), ('20261010_v2', 14)):
                p_lef = raw / f'V1/LIB_HTML/{ver}/LEF/a.lef'
                p_lib = raw / f'V1/LIB_HTML/{ver}/LIB/a.lib'
                p_lef.parent.mkdir(parents=True, exist_ok=True)
                p_lib.parent.mkdir(parents=True, exist_ok=True)
                p_lef.write_text(_lef(w), encoding='utf-8')
                p_lib.write_text('library(t){cell(A){pin(IN){direction:input;}}}', encoding='utf-8')

            (work / 'path_sources.json').write_text(json.dumps({
                'raw_root': str(raw),
                'update_formal': False,
            }), encoding='utf-8')
            refresh_all(work)
            ov_res = run_library(work, 'V1', 'LIB_HTML', rerun=True)
            accept_revision(work, 'V1', 'LIB_HTML', 'rev_0002', actor='qa', reason='approved')

            ov_name = Path(ov_res['overall']).name
            chk_name = Path(ov_res['versions'][-1]['check']).name

            app = create_path_app(work)
            self.addCleanup(app.extensions['jobs'].shutdown, wait=True)
            client = app.test_client()

            # Strictly zero os.walk during all HTML views & offline exports
            with patch('os.walk', side_effect=AssertionError('只读报告渲染不得扫描外部 RAW')):
                r_lib = client.get('/path/library?vendor=V1&library=LIB_HTML')
                r_cv = client.get(f'/path/check/view?vendor=V1&library=LIB_HTML&name={chk_name}')
                r_chk_html = client.get(f'/path/check/export.html?vendor=V1&library=LIB_HTML&name={chk_name}')
                r_ov_view = client.get(f'/path/overall/view?vendor=V1&library=LIB_HTML&name={ov_name}')
                r_ov_html = client.get(f'/path/overall/export.html?vendor=V1&library=LIB_HTML&name={ov_name}')

            # 1) Library page renders inline HTML check dashboard directly in TAB 2
            self.assertEqual(r_lib.status_code, 200)
            lib_html = r_lib.get_data(as_text=True)
            self.assertIn('id="inline-check-dashboard"', lib_html)
            self.assertIn('view-cov-grid', lib_html)
            self.assertIn('LEF_LIBERTY_PIN_MATCH', lib_html)
            self.assertIn('规则详情', lib_html)
            self.assertIn('LEF/Liberty 信号 Pin 一致性核验', lib_html)
            self.assertIn('id="check-scope"', lib_html)
            cv_html = r_cv.get_data(as_text=True)
            self.assertIn('id="check-rules"', cv_html)
            self.assertIn('class="check-rule"', cv_html)
            self.assertIn('LEF/a.lef', cv_html)
            self.assertIn('查看结构证据', cv_html)
            self.assertIn('HTML 汇总', lib_html)
            self.assertIn('导出离线 HTML', lib_html)

            # 2) Single-version offline HTML export is self-contained and complete
            self.assertEqual(r_chk_html.status_code, 200)
            self.assertIn('text/html', r_chk_html.content_type)
            chk_dl = r_chk_html.get_data(as_text=True)
            self.assertIn('<style>', chk_dl)
            self.assertNotIn('<link rel="stylesheet"', chk_dl)
            self.assertIn('AI LIB 离线质量检查报告', chk_dl)
            self.assertIn('LEF/a.lef', chk_dl)
            self.assertIn('rev_0002', chk_dl)

            # 3) Multi-version Overall interactive HTML view renders matrix + acceptance badge
            self.assertEqual(r_ov_view.status_code, 200)
            ov_view_html = r_ov_view.get_data(as_text=True)
            self.assertIn('跨版本检查结果矩阵', ov_view_html)
            self.assertIn('rev_0001', ov_view_html)
            self.assertIn('rev_0002', ov_view_html)
            self.assertIn('LEF_LIBERTY_PIN_MATCH: PASS', ov_view_html)
            self.assertIn('已采纳', ov_view_html)

            # 4) Multi-version Overall offline HTML export is self-contained
            self.assertEqual(r_ov_html.status_code, 200)
            self.assertIn('text/html', r_ov_html.content_type)
            ov_dl = r_ov_html.get_data(as_text=True)
            self.assertIn('<style>', ov_dl)
            self.assertNotIn('<link rel="stylesheet"', ov_dl)
            self.assertIn('AI LIB 离线多版本质量汇总报告', ov_dl)
            self.assertIn('当前已采纳', ov_dl)

            # No parsed LEF produces an inconclusive verdict without fictitious paths or evidence.
            update_library_config(work, 'V1', 'LIB_HTML', {'skip_parse_views': ['LEF']})
            new_run = run_revision(work, 'V1', 'LIB_HTML', 'rev_0002', plugins=['LEF_LIBERTY_PIN_MATCH'])
            new_html = client.get('/path/check/view', query_string={
                'vendor': 'V1', 'library': 'LIB_HTML', 'name': Path(new_run['check']).name,
            }).get_data(as_text=True)
            self.assertIn('无结论 1', new_html)
            self.assertIn('本条结论未关联文件', new_html)
            self.assertIn('本条结论无结构证据', new_html)

            # 5) Single-library workbench keeps check-scope inside tab-checks, shows readable rev labels,
            #    exposes inline diff selector & embeds overall check dashboard directly inside TAB 2.
            self.assertGreater(lib_html.index('id="check-scope"'), lib_html.index('id="tab-checks"'))
            self.assertIn('有效版 #2 (rev_0002)', lib_html)
            self.assertIn('id="check-target-rev"', lib_html)
            self.assertIn('id="check-baseline-rev"', lib_html)
            self.assertIn('检查当前版本', lib_html)
            self.assertIn('逐文件对比各自的上一交付', lib_html)
            self.assertIn('查最新版 rev_0002', lib_html)
            self.assertIn('id="inline-overall-dashboard"', lib_html)
            self.assertIn('id="timeline-matrix-table"', lib_html)
            self.assertIn('本库有效版本演进时间线', lib_html)

    def test_multi_track_library_exposes_all_ips_overview_matrix_and_batch_check(self):
        from ai_lib_qor.application.minimal_checks import run_library
        from ai_lib_qor.application.path_refresh import refresh_all
        from ai_lib_qor.workbench.path_app import create_path_app

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            raw, work = root / 'raw', root / 'work'
            work.mkdir()
            lib_txt = 'library(t){cell(A){pin(IN){direction:input;}}}'
            for rel, txt in (
                ('V1/MULTI/20261001_IP_A_v1/LEF/a.lef', _lef(10)),
                ('V1/MULTI/20261001_IP_A_v1/LIB/a_tt.lib', lib_txt),
                ('V1/MULTI/20261005_IP_A_v2/LEF/a.lef', _lef(14)),
                ('V1/MULTI/20261005_IP_A_v2/LIB/a_tt.lib', lib_txt),
                ('V1/MULTI/20261002_IP_B_v1/LEF/b.lef', _lef(10)),
                ('V1/MULTI/20261002_IP_B_v1/LIB/b_tt.lib', lib_txt),
            ):
                p = raw / rel
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(txt, encoding='utf-8')
            (work / 'path_sources.json').write_text(json.dumps({
                'raw_root': str(raw),
                'update_formal': False,
                'libraries': {'V1': {'MULTI': {'ip_type': 'ANALOG', 'ip_list': ['IP_A', 'IP_B']}}},
            }), encoding='utf-8')
            refresh_all(work)
            run_library(work, 'V1', 'MULTI', business_ip='IP_A', rerun=True)

            app = create_path_app(work)
            self.addCleanup(app.extensions['jobs'].shutdown, wait=True)
            html = app.test_client().get('/path/library?vendor=V1&library=MULTI&ip=IP_A').get_data(as_text=True)
            self.assertIn('id="inline-overall-dashboard"', html)
            self.assertIn('id="inline-all-ips-dashboard"', html)
            self.assertIn('本库全部业务 IP 有效版本核查总览', html)
            self.assertIn('一键核查待检 IP 最新版', html)
            self.assertIn('IP_A', html)
            self.assertIn('IP_B', html)


if __name__ == '__main__':
    unittest.main()
