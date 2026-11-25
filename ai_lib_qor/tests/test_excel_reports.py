"""Comprehensive content, layout, formula, multi-corner dedup, stress and integration tests for v3 Excel reports."""
from io import BytesIO
import json
from pathlib import Path
import tempfile
import unittest

import openpyxl

from ai_lib_qor.application.minimal_checks import (
    load_check_bundle,
    render_excel_from_check,
    render_overall_excel_from_saved,
    run_library,
    run_revision,
)
from ai_lib_qor.application.minimal_effective import initialize_from_formal, update_effective
from ai_lib_qor.application.path_acceptance import accept_revision
from ai_lib_qor.cli import parser as cli_parser, run as cli_run
from ai_lib_qor.reporting.excel import render_excel
from ai_lib_qor.reporting.path_workbook_model import extract_corner_hint
from ai_lib_qor.reporting.work_overview_excel import render_work_overview_excel
from ai_lib_qor.sources.root_inventory import build_from_roots
from ai_lib_qor.workbench.path_app import create_path_app


class ExcelReportsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.root = root
        self.raw = root / 'raw'
        self.nl = root / 'NL2_5'
        self.nl.mkdir()
        self.work = root / 'work'
        self.v1 = '20261001_v01'
        self.v2 = '20261015_v02'
        self.v3 = '20261101_v03'

        def write_ver(ver, lef_txt, lib_files, v_txt, cdl_txt, extra_unselected=False, link_nl=False):
            files = {
                'LEF/ip_top.lef': lef_txt,
                **lib_files,
                'VERILOG/ip_top.v': v_txt,
                'CDL/ip_top.cdl': cdl_txt,
                'GDS/ip_top.gds': 'opaque-gds',
            }
            if extra_unselected:
                files['SPICE/unselected.spice'] = '.SUBCKT UNSEL A\n.ENDS UNSEL\n'
            for rel, body in files.items():
                p = self.raw / 'ACME/sram_macro' / ver / rel
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(body, encoding='utf-8')
                if link_nl and not rel.startswith('SPICE/'):
                    (self.nl / p.name).symlink_to(p)

        # v1: clean baseline with 2 Liberty corners (ff & ss)
        lib_v1 = 'library(tt) { cell(SRAM_TOP) { pin(CLK) { direction : input; } pin(DOUT) { direction : output; } } }\n'
        write_ver(
            self.v1,
            (
                'MACRO SRAM_TOP\n SIZE 100.5 BY 40.2 ;\n'
                ' PIN CLK\n  DIRECTION INPUT ;\n END CLK\n'
                ' PIN DOUT\n  DIRECTION OUTPUT ;\n END DOUT\n'
                ' PIN VDD\n  DIRECTION INOUT ;\n  USE POWER ;\n END VDD\n'
                'END SRAM_TOP\n'
            ),
            {'LIB/ip_ff_n40C_1v95.lib': lib_v1, 'LIB/ip_ss_125C_1v60.lib': lib_v1},
            'module SRAM_TOP(input CLK, output [3:0] DOUT); endmodule\n',
            '.SUBCKT INT_BITCELL A B\nM1 A B B B nmos\n.ENDS INT_BITCELL\n.SUBCKT SRAM_TOP CLK DOUT VDD\nX1 CLK DOUT INT_BITCELL\n.ENDS SRAM_TOP\n',
            extra_unselected=True,
            link_nl=True,
        )
        # v2: size change, added bus pins (A_DIN[1], A_DIN[2], A_DIN[10]) missing in BOTH corners,
        # PLUS corner-specific EXTRA_SS_PIN only in ss corner!
        lib_v2_ff = 'library(ff) { cell(SRAM_TOP) { pin(CLK) { direction : input; } pin(DOUT) { direction : output; } } }\n'
        lib_v2_ss = 'library(ss) { cell(SRAM_TOP) { pin(CLK) { direction : input; } pin(DOUT) { direction : output; } pin(EXTRA_SS_PIN) { direction : input; } } }\n'
        write_ver(
            self.v2,
            (
                'MACRO SRAM_TOP\n SIZE 112.0 BY 40.2 ;\n'
                ' PIN CLK\n  DIRECTION INPUT ;\n END CLK\n'
                ' PIN DOUT\n  DIRECTION INOUT ;\n END DOUT\n'
                ' PIN A_DIN[10]\n  DIRECTION INPUT ;\n END A_DIN[10]\n'
                ' PIN A_DIN[2]\n  DIRECTION INPUT ;\n END A_DIN[2]\n'
                ' PIN A_DIN[1]\n  DIRECTION INPUT ;\n END A_DIN[1]\n'
                ' PIN VDD\n  DIRECTION INOUT ;\n  USE POWER ;\n END VDD\n'
                'END SRAM_TOP\n'
            ),
            {'LIB/ip_ff_n40C_1v95.lib': lib_v2_ff, 'LIB/ip_ss_125C_1v60.lib': lib_v2_ss},
            'module SRAM_TOP(input CLK, inout [7:0] DOUT, input CEN); endmodule\n',
            '.SUBCKT INT_BITCELL A B\nM1 A B B B nmos\n.ENDS INT_BITCELL\n.SUBCKT SRAM_TOP CLK CEN DOUT VDD\nX1 CLK DOUT INT_BITCELL\n.ENDS SRAM_TOP\n',
        )
        # v3: fixed lib + remove GDS
        lib_v3 = 'library(tt) { cell(SRAM_TOP) { pin(CLK) { direction : input; } pin(DOUT) { direction : inout; } } }\n'
        write_ver(
            self.v3,
            (
                'MACRO SRAM_TOP\n SIZE 112.0 BY 40.2 ;\n'
                ' PIN CLK\n  DIRECTION INPUT ;\n END CLK\n'
                ' PIN DOUT\n  DIRECTION INOUT ;\n END DOUT\n'
                ' PIN VDD\n  DIRECTION INOUT ;\n  USE POWER ;\n END VDD\n'
                'END SRAM_TOP\n'
            ),
            {'LIB/ip_ff_n40C_1v95.lib': lib_v3, 'LIB/ip_ss_125C_1v60.lib': lib_v3},
            'module SRAM_TOP(input CLK, inout [7:0] DOUT); endmodule\n',
            '.SUBCKT SRAM_TOP CLK DOUT VDD\n.ENDS SRAM_TOP\n',
        )

        build_from_roots(self.raw, self.nl, self.work, auto_effective=False)
        (self.work / 'path_sources.json').write_text(json.dumps({'skip_parse_views': []}), encoding='utf-8')
        self.folder = self.work / 'libraries/ACME/sram_macro'
        initialize_from_formal(self.work, 'ACME', 'sram_macro', next((self.folder / 'formal').glob('formal_*.json')))
        update_effective(self.work, 'ACME', 'sram_macro', {
            'set': [
                {'view': 'LEF', 'version': self.v2, 'path': 'LEF/ip_top.lef'},
                {'view': 'LIBERTY', 'version': self.v2, 'path': 'LIB/ip_ff_n40C_1v95.lib'},
                {'view': 'LIBERTY', 'version': self.v2, 'path': 'LIB/ip_ss_125C_1v60.lib'},
                {'view': 'VERILOG', 'version': self.v2, 'path': 'VERILOG/ip_top.v'},
                {'view': 'CDL', 'version': self.v2, 'path': 'CDL/ip_top.cdl'},
            ],
            'remove': [],
        })
        update_effective(self.work, 'ACME', 'sram_macro', {
            'set': [
                {'view': 'LEF', 'version': self.v3, 'path': 'LEF/ip_top.lef'},
                {'view': 'LIBERTY', 'version': self.v3, 'path': 'LIB/ip_ff_n40C_1v95.lib'},
                {'view': 'LIBERTY', 'version': self.v3, 'path': 'LIB/ip_ss_125C_1v60.lib'},
            ],
            'remove': [{'view': 'GDS', 'path': 'GDS/ip_top.gds'}],
        })
        accept_revision(self.work, 'ACME', 'sram_macro', 'rev_0001', actor='qa-lead', reason='首版人工签署通过')

    def test_corner_hint_extractor(self):
        self.assertEqual(extract_corner_hint('LIB/NLDM/RM_IHPSG13_1P_64x16_c2_fast_1p32V_m55C.lib'), 'fast_1p32V_m55C')
        self.assertEqual(extract_corner_hint('LIB/NLDM/sram22_256x16m8w8_ff_n40C_1v95.lib'), 'ff_n40C_1v95')
        self.assertEqual(extract_corner_hint('LIB/gf180mcu_fd_sc_mcu7t5v0__ss_125C_4v50.lib.gz'), 'ss_125C_4v50')
        self.assertEqual(extract_corner_hint('LIB/plain.lib'), '未识别')

    def test_single_revision_v3_structure_formulas_dedup_and_links(self):
        r2 = run_revision(self.work, 'ACME', 'sram_macro', 'rev_0002', render=True)
        wb_f = openpyxl.load_workbook(r2['excel'], data_only=False)
        wb_v = openpyxl.load_workbook(r2['excel'], data_only=True)
        expected_sheets = [
            '00-决策概览', '01-风险与检查', '02-文件版本矩阵', '03-对象与接口差异',
            '04-MacroView对齐', '05-LEF宏明细', '06-Liberty单元明细', '07-正式库与证据溯源',
        ]
        self.assertEqual(wb_f.sheetnames, expected_sheets)

        # 00-决策概览: action callout, Vendor, Verdict, Acceptance separated from latest, 7 hyperlinks & COUNTA formulas
        ov_v = wb_v['00-决策概览']
        ov_f = wb_f['00-决策概览']
        ov_text = '\n'.join(str(v) for row in ov_v.iter_rows(values_only=True) for v in row if v is not None)
        self.assertIn('阻塞 · 建议暂缓采纳', ov_text)
        self.assertIn('ACME', ov_text)
        self.assertIn('质检失败', ov_text)
        self.assertIn('已采纳 rev_0001（非本次检查版本）', ov_text)
        self.assertIn('rev_0003', ov_text)
        links = [c.hyperlink.target or c.hyperlink.location for row in ov_f.iter_rows() for c in row if c.hyperlink]
        self.assertEqual(len(links), 7)
        formulas_ov = [str(c.value) for row in ov_f.iter_rows() for c in row if isinstance(c.value, str) and c.value.startswith('=')]
        self.assertGreaterEqual(len(formulas_ov), 6)

        # 01-风险与检查: back-link in banner, FAIL first, drill-down link to 03-对象与接口差异
        sh1_f = wb_f['01-风险与检查']
        sh1_links = [c.hyperlink.location or c.hyperlink.target for row in sh1_f.iter_rows() for c in row if c.hyperlink]
        self.assertTrue(any('00-决策概览' in str(x) for x in sh1_links))
        self.assertTrue(any('03-对象与接口差异' in str(x) for x in sh1_links))
        sh1_v = list(wb_v['01-风险与检查'].iter_rows(min_row=5, values_only=True))
        self.assertEqual(sh1_v[0][2], 'LEF_LIBERTY_PIN_MATCH')
        self.assertEqual(sh1_v[0][3], 'FAIL')
        self.assertIn('facts/fact_ca_', str(sh1_v[0][8]))

        # 02-文件版本矩阵: dynamic SUBTOTAL row 4, data starts row 6, RAW version count col J
        self.assertIn('SUBTOTAL(103', str(wb_f['02-文件版本矩阵']['C4'].value))
        sh2 = list(wb_v['02-文件版本矩阵'].iter_rows(min_row=6, values_only=True))
        unselected = next(r for r in sh2 if r[2] == 'SPICE/unselected.spice')
        self.assertEqual(unselected[0], '未纳入当前有效集')
        self.assertEqual(unselected[6], '未纳入有效集')
        lef_row = next(r for r in sh2 if r[2] == 'LEF/ip_top.lef')
        self.assertEqual(lef_row[3], '来源变化')
        self.assertEqual(lef_row[7], '内容变化')
        self.assertEqual(lef_row[9], 3)  # 3 RAW delivery versions

        # 03-对象与接口差异: multi-corner deduplication!
        # Raw = 4 mismatches in ff + 5 mismatches in ss = 9; deduped = 5 (4 affecting all 2 corners + 1 corner-specific!)
        sh3_ws = wb_v['03-对象与接口差异']
        self.assertIn('原始 9 条 → 5 条', str(sh3_ws['A2'].value))
        self.assertIn('角点特异性异常 1 条', str(sh3_ws['A2'].value))
        sh3 = list(sh3_ws.iter_rows(min_row=5, values_only=True))
        missing_pins = [r[4] for r in sh3 if r[0] == '跨视图Pin核验' and r[5] == 'Pin缺失']
        self.assertEqual(missing_pins, ['SRAM_TOP / A_DIN[1]', 'SRAM_TOP / A_DIN[2]', 'SRAM_TOP / A_DIN[10]'])
        extra_pin_row = next(r for r in sh3 if r[5] == 'Pin多余')
        self.assertIn('角点特异性异常', extra_pin_row[8])

        # 04-MacroView对齐: CDL internal subckt filtered out
        sh4_ws = wb_v['04-MacroView对齐']
        self.assertIn('1 个非顶层内部子电路已过滤', str(sh4_ws['A2'].value))
        sh4 = list(sh4_ws.iter_rows(min_row=5, values_only=True))
        self.assertEqual(len(sh4), 1)
        self.assertEqual(sh4[0][0], 'SRAM_TOP')

        # 05-LEF宏明细: SUBTOTAL strip + live area/aspect formulas + PG Pin names
        sh5_f = wb_f['05-LEF宏明细']
        self.assertIn('SUBTOTAL(109', str(sh5_f['F4'].value))
        self.assertIn('ROUND(D6*E6', str(sh5_f['F6'].value))
        self.assertIn('D6/E6', str(sh5_f['G6'].value))
        sh5_v = list(wb_v['05-LEF宏明细'].iter_rows(min_row=6, values_only=True))
        self.assertAlmostEqual(float(sh5_v[0][5]), 112.0 * 40.2, places=3)
        self.assertAlmostEqual(float(sh5_v[0][6]), round(112.0 / 40.2, 3), places=3)
        self.assertEqual((sh5_v[0][7], sh5_v[0][8], sh5_v[0][9]), (6, 5, 1))
        self.assertEqual(sh5_v[0][10], 'VDD')

        # 06-Liberty单元明细: SUBTOTAL strip, filename corner hint, cross-check vs LEF signal pins
        self.assertIn('SUBTOTAL(109', str(wb_f['06-Liberty单元明细']['E4'].value))
        sh6_v = list(wb_v['06-Liberty单元明细'].iter_rows(min_row=6, values_only=True))
        hints = sorted(r[1] for r in sh6_v)
        self.assertEqual(hints, ['ff_n40C_1v95', 'ss_125C_1v60'])
        self.assertTrue(all('差异 (Lib' in str(r[5]) and 'LEF 5)' in str(r[5]) for r in sh6_v))

        # 07-正式库与证据溯源: 9-col aligned Formal NL table + FileFacts pool provenance
        sh7_ws = wb_v['07-正式库与证据溯源']
        self.assertEqual(sh7_ws.max_column, 9)
        sh7_all = '\n'.join(str(v) for row in sh7_ws.iter_rows(values_only=True) for v in row if v is not None)
        self.assertIn('漂移', sh7_all)
        self.assertIn('facts/fact_ca_LEF_', sh7_all)

    def test_empty_diff_message_never_says_not_provided(self):
        r1 = run_revision(self.work, 'ACME', 'sram_macro', 'rev_0001', render=True)
        wb = openpyxl.load_workbook(r1['excel'], data_only=True)
        diff_msg = str(wb['03-对象与接口差异']['A5'].value)
        self.assertNotEqual(diff_msg, '未提供')
        self.assertIn('无对比基线', diff_msg)
        # Liberty cross-check column on rev_0001 should show '一致 (2=2)'
        sh6_v = list(wb['06-Liberty单元明细'].iter_rows(min_row=6, values_only=True))
        self.assertTrue(all(r[5] == '一致 (2=2)' for r in sh6_v))

    def test_cell_truncation_and_pin_diff_cap_prevent_excel_crash(self):
        r1 = run_revision(self.work, 'ACME', 'sram_macro', 'rev_0001', render=False)
        bundle = load_check_bundle(self.work, 'ACME', 'sram_macro', Path(r1['check']).name)
        report = json.loads(json.dumps(bundle['report']))
        lef_ref = next(f['facts'] for f in report['files'] if f['view'] == 'LEF')
        lib_ref = next(f['facts'] for f in report['files'] if f['view'] == 'LIBERTY')
        big_facts = dict(bundle['facts'])
        big_lef = json.loads(json.dumps(big_facts[lef_ref]))
        big_lef['objects']['macros'][0]['pins'] = [{'name': f'P_{i}', 'direction': 'INPUT'} for i in range(600)]
        big_facts[lef_ref] = big_lef
        report['checks'].append({
            'check_id': 'LEF_LIBERTY_PIN_MATCH',
            'scope_file_keys': ['LEF/ip_top.lef', 'LIB/ip_ff_n40C_1v95.lib'],
            'result': 'FAIL',
            'coverage': 'COMPLETE',
            'facts_refs': [lef_ref, lib_ref],
            'detail': 'X' * 40000,
        })
        out = self.root / 'huge_stress.xlsx'
        render_excel({**report, '_path_context': {'index': bundle['index'], 'facts': big_facts}}, out)
        wb = openpyxl.load_workbook(out, data_only=True)
        # Detail is cleanly summarized (well under 32767) and 03 sheet folds >500 pins
        detail_val = str(wb['01-风险与检查']['H5'].value)
        self.assertLessEqual(len(detail_val), 32767)
        self.assertLessEqual(wb['03-对象与接口差异'].max_row, 510)
        last_note = str(wb['03-对象与接口差异'].cell(wb['03-对象与接口差异'].max_row, 9).value)
        self.assertIn('已折叠', last_note)

    def test_overall_3_sheet_workbook_and_readonly_rerender(self):
        run_revision(self.work, 'ACME', 'sram_macro', 'rev_0001', render=False)
        run_revision(self.work, 'ACME', 'sram_macro', 'rev_0002', render=False)
        ov = run_library(self.work, 'ACME', 'sram_macro', rerun=False)
        wb_f = openpyxl.load_workbook(ov['excel'], data_only=False)
        wb_v = openpyxl.load_workbook(ov['excel'], data_only=True)
        self.assertEqual(wb_v.sheetnames, ['00-版本运行汇总', '01-逐项检查汇总', '02-跨版本对象变化'])
        self.assertIn('SUBTOTAL(109', str(wb_f['00-版本运行汇总']['H4'].value))
        rows = list(wb_v['00-版本运行汇总'].iter_rows(min_row=6, values_only=True))
        self.assertEqual([r[0] for r in rows], ['rev_0001', 'rev_0002', 'rev_0003'])
        self.assertEqual([r[1] for r in rows], ['当前已采纳', '历史版本', '最新计算'])
        self.assertEqual([r[3] for r in rows], ['部分完成', '部分完成', '未检查'])
        self.assertEqual([r[4] for r in rows], ['部分覆盖 / 无结论', '质检失败', '未检查'])
        self.assertEqual((rows[1][7], rows[1][8], rows[1][9]), (0, 5, 0))
        self.assertEqual((rows[2][7], rows[2][8], rows[2][9]), (0, 3, 1))
        chg_rows = list(wb_v['02-跨版本对象变化'].iter_rows(min_row=5, values_only=True))
        self.assertTrue(any(r[6] == '尺寸变化' and '100.5 × 40.2 um' in str(r[7]) for r in chg_rows))

        # Re-render saved overall JSON cleanly to a custom path without mutating runs.jsonl
        runs_before = (self.folder / 'log/runs.jsonl').read_text(encoding='utf-8')
        re_out = self.root / 'overall_rerendered.xlsx'
        render_overall_excel_from_saved(self.work, 'ACME', 'sram_macro', Path(ov['overall']).name, re_out)
        self.assertTrue(re_out.is_file())
        self.assertEqual((self.folder / 'log/runs.jsonl').read_text(encoding='utf-8'), runs_before)

    def test_work_overview_excel_cli_and_web_readonly(self):
        run_revision(self.work, 'ACME', 'sram_macro', 'rev_0003', render=False)
        out = self.root / 'overview.xlsx'
        before_files = sorted(str(p.relative_to(self.work)) for p in self.work.rglob('*'))
        args = cli_parser().parse_args(['export-overview-excel', '--work', str(self.work), '--out', str(out)])
        res = cli_run(args)
        self.assertEqual(res['state'], 'SUCCEEDED')
        self.assertTrue(out.is_file())
        after_files = sorted(str(p.relative_to(self.work)) for p in self.work.rglob('*'))
        self.assertEqual(before_files, after_files)

        wb_f = openpyxl.load_workbook(out, data_only=False)
        wb_v = openpyxl.load_workbook(out, data_only=True)
        self.assertEqual(wb_v.sheetnames, ['00-全库总览', '01-待处理与风险清单'])
        self.assertIn('SUBTOTAL(109', str(wb_f['00-全库总览']['C5'].value))
        ov_rows = list(wb_v['00-全库总览'].iter_rows(min_row=7, values_only=True))
        self.assertEqual(len(ov_rows), 1)
        self.assertEqual(ov_rows[0][0], 'ACME')
        self.assertEqual(ov_rows[0][4], 'rev_0003')
        self.assertEqual(ov_rows[0][5], 'rev_0001')
        self.assertEqual(ov_rows[0][7], '已同步')
        self.assertEqual(ov_rows[0][9], 'rev_0002')  # baseline col

        app = create_path_app(self.work)
        client = app.test_client()
        resp = client.get('/path/overview/export.xlsx')
        self.assertEqual(resp.status_code, 200)
        wb_web = openpyxl.load_workbook(BytesIO(resp.data), data_only=True)
        self.assertEqual(wb_web.sheetnames, ['00-全库总览', '01-待处理与风险清单'])


if __name__ == '__main__':
    unittest.main()
