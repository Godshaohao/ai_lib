"""Tests for configurable Liberty (.lib) threshold + keyword sampling during QoR checks."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import openpyxl

from ai_lib_qor.application.minimal_checks import _file_digest as real_file_digest, run_revision
from ai_lib_qor.application.path_config import liberty_parse_filter, select_liberty_files
from ai_lib_qor.application.path_refresh import refresh_all
from ai_lib_qor.versions.store import validate
from ai_lib_qor.workbench.path_app import create_path_app


_LEF = (
    'MACRO CELL_TOP\n SIZE 10 BY 10 ;\n'
    ' PIN CLK\n  DIRECTION INPUT ;\n END CLK\n'
    ' PIN DOUT\n  DIRECTION OUTPUT ;\n END DOUT\n'
    'END CELL_TOP\n'
)
_LIB = 'library(demo) { cell(CELL_TOP) { pin(CLK) { direction : input; } pin(DOUT) { direction : output; } } }\n'


class LibertyParseFilterTests(unittest.TestCase):
    def test_selector_threshold_keywords_exclude_round_robin_and_fallbacks(self):
        paths = [
            'LIB/cell_ccs_tt_25c.lib',
            'LIB/cell_ff_m40c.lib',
            'LIB/cell_ff_125c.lib',
            'LIB/cell_lvf_ss_125c.lib',
            'LIB/cell_ss_m40c.lib',
            'LIB/cell_ss_125c.lib',
            'LIB/cell_tt_25c.lib',
            'LIB/cell_tt_85c.lib',
        ]
        # 1) At or below threshold -> parse all
        r0 = select_liberty_files(paths, {'enabled': True, 'threshold': 8, 'keywords': ['tt'], 'exclude_keywords': [], 'max_selected': 2, 'fallback': 'first_n'})
        self.assertFalse(r0['applied'])
        self.assertEqual(r0['selected_count'], 8)

        # 2) Above threshold with keywords + exclude_keywords + max_selected=3 -> round-robin 1 tt + 1 ss + 1 ff, no ccs/lvf
        r1 = select_liberty_files(paths, {
            'enabled': True, 'threshold': 4, 'keywords': ['tt', 'ss', 'ff'],
            'exclude_keywords': ['ccs', 'lvf'], 'max_selected': 3, 'fallback': 'first_n',
        })
        self.assertTrue(r1['applied'])
        self.assertEqual(r1['selected'], ['LIB/cell_ff_125c.lib', 'LIB/cell_ss_125c.lib', 'LIB/cell_tt_25c.lib'])
        self.assertEqual(r1['skipped_count'], 5)
        self.assertFalse(r1['fallback_used'])

        # 3) Keyword match with no max_selected -> all matching non-excluded files
        r2 = select_liberty_files(paths, {
            'enabled': True, 'threshold': 4, 'keywords': ['tt'],
            'exclude_keywords': ['ccs'], 'max_selected': None, 'fallback': 'first_n',
        })
        self.assertEqual(r2['selected'], ['LIB/cell_tt_25c.lib', 'LIB/cell_tt_85c.lib'])

        # 4) No keyword match -> fallback='first_n' vs fallback='skip'
        r3 = select_liberty_files(paths, {
            'enabled': True, 'threshold': 4, 'keywords': ['nonexistent_corner'],
            'exclude_keywords': ['ccs', 'lvf'], 'max_selected': 2, 'fallback': 'first_n',
        })
        self.assertTrue(r3['fallback_used'])
        self.assertEqual(len(r3['selected']), 2)
        self.assertTrue(all('ccs' not in p and 'lvf' not in p for p in r3['selected']))

        r4 = select_liberty_files(paths, {
            'enabled': True, 'threshold': 4, 'keywords': ['nonexistent_corner'],
            'exclude_keywords': [], 'max_selected': 2, 'fallback': 'skip',
        })
        self.assertFalse(r4['fallback_used'])
        self.assertEqual(r4['selected'], [])
        self.assertEqual(r4['skipped_count'], 8)

        # 5) Threshold only (no keywords) -> deterministic first threshold files
        r5 = select_liberty_files(paths, {
            'enabled': True, 'threshold': 3, 'keywords': [],
            'exclude_keywords': ['ccs'], 'max_selected': None, 'fallback': 'first_n',
        })
        self.assertEqual(r5['selected_count'], 3)
        self.assertTrue(all('ccs' not in p for p in r5['selected']))

    def test_config_global_default_library_override_and_validation(self):
        with tempfile.TemporaryDirectory() as td:
            work = Path(td)
            (work / 'path_sources.json').write_text(json.dumps({
                'liberty_parse_filter': {
                    'threshold': 6,
                    'keywords': ['tt', 'ss'],
                    'exclude_keywords': ['ccs'],
                    'max_selected': 4,
                },
                'libraries': {
                    'V1': {
                        'LIB_OVERRIDE': {
                            'liberty_parse_filter': {'threshold': 2, 'keywords': ['ff']},
                        },
                        'LIB_DISABLED': {
                            'liberty_parse_filter': {'enabled': False},
                        },
                        'LIB_NULL_OPT_OUT': {
                            'liberty_parse_filter': None,
                        },
                    }
                },
            }), encoding='utf-8')

            p_def = liberty_parse_filter(work, 'V1', 'OTHER_LIB')
            self.assertTrue(p_def['enabled'])
            self.assertEqual(p_def['threshold'], 6)
            self.assertEqual(p_def['keywords'], ['tt', 'ss'])
            self.assertEqual(p_def['exclude_keywords'], ['ccs'])

            p_ovr = liberty_parse_filter(work, 'V1', 'LIB_OVERRIDE')
            self.assertTrue(p_ovr['enabled'])
            self.assertEqual(p_ovr['threshold'], 2)
            self.assertEqual(p_ovr['keywords'], ['ff'])
            self.assertEqual(p_ovr['exclude_keywords'], ['ccs'])  # inherited from workspace default

            self.assertFalse(liberty_parse_filter(work, 'V1', 'LIB_DISABLED')['enabled'])
            self.assertFalse(liberty_parse_filter(work, 'V1', 'LIB_NULL_OPT_OUT')['enabled'])

            # Invalid config raises ValueError
            (work / 'path_sources.json').write_text(json.dumps({'liberty_parse_filter': {'threshold': -1}}), encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'threshold'):
                liberty_parse_filter(work, 'V1', 'OTHER_LIB')

    def test_check_skips_unselected_liberty_without_disk_read_and_renders_excel_and_web(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            raw, nl, work = root / 'raw', root / 'NL1', root / 'work'
            nl.mkdir()
            work.mkdir()
            v1 = raw / 'V1/BIG_STD/20261001_v1'
            lib_files = [
                'LIB/std_ccs_tt_25c.lib',
                'LIB/std_ff_m40c.lib',
                'LIB/std_lvf_ss_125c.lib',
                'LIB/std_ss_125c.lib',
                'LIB/std_tt_25c.lib',
                'LIB/std_tt_85c.lib',
            ]
            lef_path = v1 / 'LEF/std.lef'
            lef_path.parent.mkdir(parents=True)
            lef_path.write_text(_LEF, encoding='utf-8')
            (nl / 'std.lef').symlink_to(lef_path)
            for rel in lib_files:
                fp = v1 / rel
                fp.parent.mkdir(parents=True, exist_ok=True)
                fp.write_text(_LIB, encoding='utf-8')
                (nl / fp.name).symlink_to(fp)

            (work / 'path_sources.json').write_text(json.dumps({
                'raw_root': str(raw),
                'nl_root': str(nl),
                'nl_version': 'NL1',
                'liberty_parse_filter': {
                    'threshold': 3,
                    'keywords': ['tt', 'ss', 'ff'],
                    'exclude_keywords': ['ccs', 'lvf'],
                    'max_selected': 2,
                },
            }), encoding='utf-8')
            refresh_all(work)

            # Spy on _file_digest to prove skipped .lib files are NEVER hashed or parsed from disk!
            hashed_names = []

            def spy_digest(path):
                hashed_names.append(Path(path).name)
                return real_file_digest(path)

            with patch('ai_lib_qor.application.minimal_checks._file_digest', side_effect=spy_digest):
                res = run_revision(work, 'V1', 'BIG_STD', 'rev_0001', render=True)

            # Only std.lef + 2 selected libs (std_tt_25c.lib, std_ss_125c.lib) touched on disk!
            self.assertEqual(sorted(hashed_names), ['std.lef', 'std_ss_125c.lib', 'std_tt_25c.lib'])

            report = json.loads(Path(res['check']).read_text(encoding='utf-8'))
            validate(report, 'check_result_path')
            # Truthfulness red line: skipped .lib files keep overall run state PARTIAL
            self.assertEqual(report['state'], 'PARTIAL')
            lf_meta = report['tooling']['liberty_filter']
            self.assertTrue(lf_meta['applied'])
            self.assertEqual((lf_meta['total_liberty_files'], lf_meta['selected_count'], lf_meta['skipped_count']), (6, 2, 4))
            self.assertIn('LIBERTY 共 6 个超过阈值 3', report['note'])
            self.assertNotIn('LIBERTY 等视图暂未检查', report['note'])

            parsed_libs = [f['path'] for f in report['files'] if f['view'] == 'LIBERTY' and f['status'] == 'PARSED']
            skipped_libs = [f for f in report['files'] if f['view'] == 'LIBERTY' and f['status'] == 'NOT_CHECKED']
            self.assertEqual(sorted(parsed_libs), ['LIB/std_ss_125c.lib', 'LIB/std_tt_25c.lib'])
            self.assertEqual(len(skipped_libs), 4)
            self.assertTrue(all('liberty_parse_filter' in f['note'] for f in skipped_libs))

            # Pin match checks ran ONLY for the 2 selected Liberty files and both passed
            pin_checks = [c for c in report['checks'] if c['check_id'] == 'LEF_LIBERTY_PIN_MATCH']
            self.assertEqual(len(pin_checks), 2)
            self.assertTrue(all(c['result'] == 'PASS' for c in pin_checks))

            # Excel 02-文件版本矩阵 distinguishes '按配置跳过(NOT_CHECKED)'
            wb = openpyxl.load_workbook(res['excel'], data_only=True)
            sh2 = list(wb['02-文件版本矩阵'].iter_rows(min_row=6, values_only=True))
            skipped_excel_rows = [r for r in sh2 if r[6] == '按配置跳过(NOT_CHECKED)']
            self.assertEqual(len(skipped_excel_rows), 4)

            # Web check analysis discloses Liberty sampling policy & Web config form persists settings cleanly
            app = create_path_app(work)
            self.addCleanup(app.extensions['jobs'].shutdown, wait=True)
            client = app.test_client()
            cv_html = client.get('/path/check/view', query_string={
                'vendor': 'V1', 'library': 'BIG_STD', 'name': Path(res['check']).name,
            }).get_data(as_text=True)
            self.assertIn('Liberty 抽样策略', cv_html)
            self.assertIn('已解析 2 / 6 个', cv_html)

            lib_html = client.get('/path/library?vendor=V1&library=BIG_STD').get_data(as_text=True)
            preview = lib_html.split('id="liberty-check-preview"', 1)[1].split('</details>', 1)[0]
            self.assertIn('2 / 6', preview)
            self.assertIn('LIB/std_ss_125c.lib', preview)
            self.assertIn('LIB/std_tt_25c.lib', preview)
            self.assertNotIn('LIB/std_ff_125c.lib', preview)

            client.get('/')
            with client.session_transaction() as sess:
                csrf = sess['csrf']
            r_save = client.post('/path/update', data={
                'csrf': csrf, 'save_settings': '1',
                'raw_root': str(raw), 'nl_root': str(nl), 'nl_version': 'NL1',
                'lib_filter_threshold': '5',
                'lib_filter_keywords': 'tt_25c, ss_125c',
                'lib_filter_exclude': 'ccs, ecsm',
                'lib_filter_max_selected': '3',
            })
            self.assertEqual(r_save.status_code, 302)
            saved_lf = liberty_parse_filter(work, 'V1', 'BIG_STD')
            self.assertEqual(saved_lf['threshold'], 5)
            self.assertEqual(saved_lf['keywords'], ['tt_25c', 'ss_125c'])
            self.assertEqual(saved_lf['exclude_keywords'], ['ccs', 'ecsm'])
            self.assertEqual(saved_lf['max_selected'], 3)

    def test_skip_parse_views_defaults_to_netlist_and_verilog_with_zero_disk_io(self):
        import openpyxl
        from ai_lib_qor.application.minimal_checks import _file_digest as real_file_digest, run_revision
        from ai_lib_qor.application.path_config import skip_parse_views
        from ai_lib_qor.application.path_refresh import refresh_all
        from ai_lib_qor.versions.store import validate
        from ai_lib_qor.workbench.path_app import create_path_app

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            raw, nl, work = root / 'raw', root / 'NL1', root / 'work'
            nl.mkdir()
            work.mkdir()
            v1 = raw / 'V1/BIG_NETLIST/20261001_v1'
            files = {
                'LEF/std.lef': _LEF,
                'LIB/std_tt_25c.lib': _LIB,
                'VERILOG/std.v': 'module INV_X1(input A, output Y); endmodule\n',
                'CDL/std.cdl': '.SUBCKT INV_X1 A Y\n.ENDS INV_X1\n',
                'SPICE/std.sp': '.SUBCKT INV_X1 A Y\n.ENDS INV_X1\n',
            }
            for rel, content in files.items():
                fp = v1 / rel
                fp.parent.mkdir(parents=True, exist_ok=True)
                fp.write_text(content, encoding='utf-8')
                (nl / fp.name).symlink_to(fp)

            (work / 'path_sources.json').write_text(json.dumps({
                'raw_root': str(raw),
                'nl_root': str(nl),
                'nl_version': 'NL1',
            }), encoding='utf-8')
            self.assertEqual(skip_parse_views(work, 'V1', 'BIG_NETLIST'), ['CDL', 'SPICE', 'VERILOG'])
            refresh_all(work)

            # 1) Default behavior: CDL / SPICE / VERILOG are skipped with ZERO disk reads or hashing!
            hashed_names = []

            def spy_digest(path):
                hashed_names.append(Path(path).name)
                return real_file_digest(path)

            with patch('ai_lib_qor.application.minimal_checks._file_digest', side_effect=spy_digest):
                res = run_revision(work, 'V1', 'BIG_NETLIST', 'rev_0001', render=True)

            self.assertEqual(sorted(hashed_names), ['std.lef', 'std_tt_25c.lib'])
            report = json.loads(Path(res['check']).read_text(encoding='utf-8'))
            validate(report, 'check_result_path')
            self.assertEqual(report['state'], 'PARTIAL')
            self.assertEqual(report['tooling']['skipped_views'], ['CDL', 'SPICE', 'VERILOG'])
            self.assertIn('已按 skip_parse_views 跳过 CDL(1)/SPICE(1)/VERILOG(1) 共 3 个文件的解析', report['note'])

            by_view = {r['view']: r for r in report['files']}
            for sv in ('CDL', 'SPICE', 'VERILOG'):
                self.assertEqual(by_view[sv]['status'], 'NOT_CHECKED')
                self.assertIn('skip_parse_views', by_view[sv]['note'])
            self.assertEqual(by_view['LEF']['status'], 'PARSED')
            self.assertEqual(by_view['LIBERTY']['status'], 'PARSED')
            self.assertTrue(any(c['check_id'] == 'LEF_LIBERTY_PIN_MATCH' and c['result'] == 'PASS' for c in report['checks']))

            # Excel marks skipped netlist/verilog as 按配置跳过(NOT_CHECKED)
            wb = openpyxl.load_workbook(res['excel'], data_only=True)
            sh2 = list(wb['02-文件版本矩阵'].iter_rows(min_row=6, values_only=True))
            self.assertEqual(sum(1 for r in sh2 if r[6] == '按配置跳过(NOT_CHECKED)'), 3)

            # Web check view displays skipped_views strip and config form persists override
            app = create_path_app(work)
            self.addCleanup(app.extensions['jobs'].shutdown, wait=True)
            client = app.test_client()
            cv_html = client.get('/path/check/view', query_string={
                'vendor': 'V1', 'library': 'BIG_NETLIST', 'name': Path(res['check']).name,
            }).get_data(as_text=True)
            self.assertIn('跳过解析视图', cv_html)
            self.assertIn('CDL', cv_html)

            # 2) Per-library override `skip_parse_views: []` re-enables CDL / SPICE / VERILOG parsing
            cfg = json.loads((work / 'path_sources.json').read_text(encoding='utf-8'))
            cfg['libraries'] = {'V1': {'BIG_NETLIST': {'skip_parse_views': []}}}
            (work / 'path_sources.json').write_text(json.dumps(cfg), encoding='utf-8')
            self.assertEqual(skip_parse_views(work, 'V1', 'BIG_NETLIST'), [])
            self.assertEqual(skip_parse_views(work, 'V1', 'OTHER_LIB'), ['CDL', 'SPICE', 'VERILOG'])

            hashed_names.clear()
            with patch('ai_lib_qor.application.minimal_checks._file_digest', side_effect=spy_digest):
                res_all = run_revision(work, 'V1', 'BIG_NETLIST', 'rev_0001', render=False)
            self.assertEqual(sorted(hashed_names), ['std.cdl', 'std.lef', 'std.sp', 'std.v', 'std_tt_25c.lib'])
            report_all = json.loads(Path(res_all['check']).read_text(encoding='utf-8'))
            self.assertNotIn('skipped_views', report_all['tooling'])

            # 3) Web form saving skip_parse_views checkbox subset persists cleanly
            client.get('/')
            with client.session_transaction() as sess:
                csrf = sess['csrf']
            r_save = client.post('/path/update', data={
                'csrf': csrf, 'save_settings': '1',
                'raw_root': str(raw), 'nl_root': str(nl), 'nl_version': 'NL1',
                'skip_parse_views_present': '1',
                'skip_parse_views': ['CDL', 'SPICE'],
            })
            self.assertEqual(r_save.status_code, 302)
            self.assertEqual(skip_parse_views(work, 'V1', 'OTHER_LIB'), ['CDL', 'SPICE'])

    def test_default_sampling_protection_and_large_scale_rules_and_preview_widgets(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            raw, work = root / 'raw', root / 'work'
            work.mkdir()
            v1 = raw / 'V1/HUGE_LIB/20261101_v1'
            lef_path = v1 / 'LEF/top.lef'
            lef_path.parent.mkdir(parents=True)
            lef_path.write_text(_LEF, encoding='utf-8')
            # 25 .lib files (> default threshold 12, and > UI collapse limit 20)
            for i in range(25):
                corner = ('tt', 'ss', 'ff')[i % 3]
                p = v1 / 'LIB' / f'cell_{corner}_{i:02d}.lib'
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(_LIB, encoding='utf-8')

            # 1) No liberty_parse_filter key in path_sources.json -> built-in default protection active
            (work / 'path_sources.json').write_text(json.dumps({
                'raw_root': str(raw),
                'update_formal': False,
            }), encoding='utf-8')
            refresh_all(work)

            default_pol = liberty_parse_filter(work, 'V1', 'HUGE_LIB')
            self.assertTrue(default_pol['enabled'])
            self.assertEqual(default_pol['threshold'], 12)
            self.assertEqual(default_pol['keywords'], ['tt', 'ss', 'ff'])
            self.assertEqual(default_pol['max_selected'], 6)

            app = create_path_app(work)
            self.addCleanup(app.extensions['jobs'].shutdown, wait=True)
            client = app.test_client()

            # Preview reflects built-in protection: 6 / 25 selected
            html_def = client.get('/path/library?vendor=V1&library=HUGE_LIB').get_data(as_text=True)
            self.assertIn('6 / 25', html_def)
            self.assertIn('data-lib-preview-search', html_def)

            # 2) Explicitly disable global sampling -> all 25 selected -> UI preview & rules collapse beyond 20
            (work / 'path_sources.json').write_text(json.dumps({
                'raw_root': str(raw),
                'update_formal': False,
                'liberty_parse_filter': None,
            }), encoding='utf-8')
            self.assertFalse(liberty_parse_filter(work, 'V1', 'HUGE_LIB')['enabled'])

            res = run_revision(work, 'V1', 'HUGE_LIB', 'rev_0001', render=False)
            lib_html = client.get('/path/library?vendor=V1&library=HUGE_LIB').get_data(as_text=True)
            self.assertIn('25 / 25', lib_html)
            self.assertIn('展开其余 5 个 .lib', lib_html)
            self.assertIn('data-overflow="1" hidden', lib_html)

            # Check rules widget on both library page and analysis page has category tabs, status filter, inner search & >20 collapse
            for html in (
                lib_html,
                client.get('/path/check/view', query_string={
                    'vendor': 'V1', 'library': 'HUGE_LIB', 'name': Path(res['check']).name,
                }).get_data(as_text=True),
            ):
                self.assertIn('data-rule-cat-seg', html)
                self.assertIn('data-cat="MANIFEST"', html)
                self.assertIn('data-cat="FACTS"', html)
                self.assertIn('data-cat="DIFF"', html)
                self.assertIn('data-rule-status-seg', html)
                self.assertIn('data-status="FAIL"', html)
                self.assertIn('data-status="INCONCLUSIVE"', html)
                self.assertIn('data-status="PASS"', html)
                self.assertIn('data-rule-inner-search', html)
                self.assertIn('展开其余 5 条结论', html)


if __name__ == '__main__':
    unittest.main()
