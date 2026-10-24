import gzip
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from lib_guard.lef_liberty_check import (
    analyze, analyze_many, parse_liberty_interface_data_file, render_markdown,
)


def lef_analysis(macros, *, complete=True):
    return {
        'schema_version': 'lef_analysis.v1',
        'sources': {'new': {'path': '/fixture/new.lef', 'sha256': 'sha256:lef'}},
        'extraction': {
            'new': {
                'source': {'path': '/fixture/new.lef', 'sha256': 'sha256:lef'},
                'macro_names': sorted(macros),
                'data': {'macros': macros},
            },
        },
        'statistics': {
            'new': {
                'macro_set_complete': complete,
                'port_set_complete': complete,
            },
        },
    }


def lef_macro(pins):
    return {
        'pins': {
            name: {'name': name, 'direction': direction, 'use': use}
            for name, direction, use in pins
        },
    }


class LefLibertyCheckTest(unittest.TestCase):
    def test_interface_parser_streams_gzip_and_skips_timing_tables(self):
        liberty_text = '''library (TT) {
 cell (LOGIC) {
  timing () {
   cell_rise (table) { values ("1,2,3 { comment-like // text }"); }
  }
  pin (A) { direction : input; }
  pg_pin (VDD) { pg_type : primary_power; }
  pg_pin (VSS) { pg_type : primary_ground; }
 }
}'''
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'cells.lib.gz'
            with gzip.open(path, 'wt', encoding='utf-8') as stream:
                stream.write(liberty_text)
            data = parse_liberty_interface_data_file(path, chunk_size=17)

        cell = data['libraries']['TT']['cells']['LOGIC']
        self.assertEqual(cell['line_start'], 2)
        self.assertEqual(cell['pins']['A']['direction'], 'input')
        self.assertEqual(cell['pins']['A']['line_start'], 6)
        self.assertEqual(cell['pg_pins']['VDD']['pg_type'], 'primary_power')
        self.assertEqual(cell['pg_pins']['VDD']['line_start'], 7)
        self.assertEqual(cell['pg_pins']['VSS']['pg_type'], 'primary_ground')
        self.assertEqual(data['semantic_coverage']['port_set'], 'PRESENT')
        self.assertEqual(data['stats']['cell_count'], 1)

    def test_interface_parser_expands_explicit_bus_pin_groups(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'bus.lib'
            path.write_text('''library (TT) { cell (LOGIC) {
 bus (COARSE_CTRL) {
  direction : input;
  pin (COARSE_CTRL[0]) { }
  pin (COARSE_CTRL[1]) { direction : input; }
 }
} }''', encoding='utf-8')
            data = parse_liberty_interface_data_file(path, chunk_size=5)
        self.assertEqual(data['semantic_coverage']['port_set'], 'PRESENT')
        pins = data['libraries']['TT']['cells']['LOGIC']['pins']
        self.assertEqual(sorted(pins), ['COARSE_CTRL[0]', 'COARSE_CTRL[1]'])
        self.assertEqual(pins['COARSE_CTRL[0]']['direction'], 'input')
        self.assertEqual(pins['COARSE_CTRL[1]']['direction'], 'input')

    def test_empty_library_with_unknown_statements_is_not_claimed_as_pin_coverage(self):
        text = '''library (EMPTY) {
  vendor_extension (opaque) { arbitrary_token; }
}'''
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'empty.lib'
            path.write_text(text, encoding='utf-8')
            data = parse_liberty_interface_data_file(path)
        self.assertFalse(data['semantic_coverage']['validated'])
        self.assertEqual(data['semantic_coverage']['port_set'], 'NOT_EXTRACTED')
        self.assertEqual(data['semantic_coverage']['pg_port_set'], 'NOT_EXTRACTED')
        self.assertEqual(data['semantic_coverage']['validation_scope'], 'supported_interface_extraction_only')

    def test_split_liberty_files_report_input_set_union_coverage(self):
        lef = lef_analysis({
            'A': lef_macro([('A_IN', 'INPUT', 'SIGNAL')]),
            'B': lef_macro([('B_IN', 'INPUT', 'SIGNAL')]),
        })
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            lef_path = root / 'lef.json'
            lef_path.write_text(json.dumps(lef), encoding='utf-8')
            part_a = root / 'part_A.lib'
            part_b = root / 'part_B.lib'
            part_a.write_text('library (TT) { cell (A) { pin (A_IN) { direction : input; } } }', encoding='utf-8')
            part_b.write_text('library (TT) { cell (B) { pin (B_IN) { direction : input; } } }', encoding='utf-8')
            result = analyze_many(lef_path, [part_a, part_b])
            report = render_markdown(result)
        self.assertEqual(result['set_coverage']['matched_macro_count'], 2)
        self.assertEqual(result['set_coverage']['lef_only_macro_count'], 0)
        self.assertIn('单文件覆盖', report)
        self.assertIn('本次输入 Liberty 集合覆盖', report)
        self.assertIn('2/2（100.0%）', report)

    def test_liberty_set_coverage_does_not_merge_distinct_corners(self):
        lef = lef_analysis({
            'A': lef_macro([('A_IN', 'INPUT', 'SIGNAL')]),
            'B': lef_macro([('B_IN', 'INPUT', 'SIGNAL')]),
        })
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            lef_path = root / 'lef.json'
            lef_path.write_text(json.dumps(lef), encoding='utf-8')
            tt = root / 'cells_TT.lib'
            ss = root / 'cells_SS.lib'
            tt.write_text('library (TT) { cell (A) { pin (A_IN) { direction : input; } } }', encoding='utf-8')
            ss.write_text('library (SS) { cell (B) { pin (B_IN) { direction : input; } } }', encoding='utf-8')
            result = analyze_many(lef_path, [tt, ss])
            report = render_markdown(result)
        self.assertEqual(len(result['set_coverages']), 2)
        self.assertEqual({row['process_corner'] for row in result['set_coverages']}, {'TT', 'SS'})
        self.assertTrue(all(row['matched_macro_count'] == 1 for row in result['set_coverages']))
        self.assertIn('按识别到的工艺角/RC 角分组统计，不跨组补齐', report)
        self.assertNotIn('集合覆盖 2/2（100.0%）', report)

    def test_bus_member_pins_are_used_in_lef_liberty_comparison(self):
        lef = lef_analysis({'LOGIC': lef_macro([
            ('COARSE_CTRL[0]', 'INPUT', 'SIGNAL'),
            ('COARSE_CTRL[1]', 'INPUT', 'SIGNAL'),
        ])})
        liberty = '''library (ddl_delay_path_TT) { cell (LOGIC) {
 bus (COARSE_CTRL) {
  direction : input;
  pin (COARSE_CTRL[0]) { }
  pin (COARSE_CTRL[1]) { direction : input; }
 }
} }'''
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report_path = root / 'lef_analysis.json'
            report_path.write_text(json.dumps(lef), encoding='utf-8')
            lib_path = root / 'bus_TT.lib'
            lib_path.write_text(liberty, encoding='utf-8')
            result = analyze(report_path, lib_path)
        self.assertEqual(result['summary']['signal_pin_checked_count'], 2)
        self.assertEqual(result['summary']['signal_pin_missing_count'], 0)
        self.assertEqual(result['summary']['signal_pin_extra_count'], 0)
        self.assertEqual(result['summary']['unverified_cell_count'], 0)

    def test_empty_liberty_pg_inventory_is_reported_as_zero_not_none(self):
        lef = lef_analysis({'LOGIC': lef_macro([('A', 'INPUT', 'SIGNAL')])})
        liberty = 'library (TT) { cell (LOGIC) { pin (A) { direction : input; } } }'
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report_path = root / 'lef_analysis.json'
            report_path.write_text(json.dumps(lef), encoding='utf-8')
            lib_path = root / 'cells_TT.lib'
            lib_path.write_text(liberty, encoding='utf-8')
            report = render_markdown(analyze_many(report_path, [lib_path]))
        self.assertIn('0 电源地 Pin', report)
        self.assertNotIn('None 电源地 Pin', report)

    def test_bus_group_without_explicit_member_pins_stays_unverified(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'bus.lib'
            path.write_text('library (TT) { cell (LOGIC) { bus (DATA) { direction : input; } } }', encoding='utf-8')
            data = parse_liberty_interface_data_file(path, chunk_size=5)
        self.assertEqual(data['semantic_coverage']['port_set'], 'NOT_EXTRACTED')
        self.assertTrue(any(row['reason'] == 'bus_without_explicit_member_pins'
                            for row in data['parse_limitations']))

    def test_gzip_liberty_matches_macro_signal_pin_direction_and_supply_pins(self):
        lef = lef_analysis({
            'LOGIC': lef_macro([
                ('A', 'INPUT', 'SIGNAL'), ('Y', 'OUTPUT', 'SIGNAL'),
                ('VDD', 'INOUT', 'POWER'), ('VSS', 'INOUT', 'GROUND'),
            ]),
        })
        liberty_text = '''library (TT) {
 cell (LOGIC) {
  pin (A) { direction : input; }
  pin (Y) { direction : output; }
  pg_pin (VDD) { pg_type : primary_power; }
  pg_pin (VSS) { pg_type : primary_ground; }
 }
}'''
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report_path = root / 'lef_analysis.json'
            report_path.write_text(json.dumps(lef), encoding='utf-8')
            lib_path = root / 'cells.lib.gz'
            with gzip.open(lib_path, 'wt', encoding='utf-8') as stream:
                stream.write(liberty_text)
            result = analyze(report_path, lib_path)

        self.assertEqual(result['summary']['matched_macro_count'], 1)
        self.assertEqual(result['summary']['mismatch_cell_count'], 0)
        self.assertEqual(result['summary']['lef_only_macro_count'], 0)
        row = result['cells'][0]
        self.assertEqual(row['status'], 'MATCH')
        self.assertEqual(row['power_ground']['lef_power_pins'], ['VDD'])
        self.assertEqual(row['power_ground']['liberty_power_pins'], ['VDD'])
        self.assertEqual(row['power_ground']['lef_ground_pins'], ['VSS'])
        self.assertEqual(row['power_ground']['liberty_ground_pins'], ['VSS'])

    def test_reports_macro_pin_direction_supply_and_extra_cell_mismatches(self):
        lef = lef_analysis({
            'LOGIC': lef_macro([
                ('A', 'INPUT', 'SIGNAL'), ('Y', 'OUTPUT', 'SIGNAL'),
                ('VDD', 'INOUT', 'POWER'), ('VSS', 'INOUT', 'GROUND'),
            ]),
        })
        liberty_text = '''library (TT) {
 cell (LOGIC) {
  pin (A) { direction : output; }
  pin (Z) { direction : output; }
  pg_pin (VDD) { pg_type : primary_ground; }
 }
 cell (LIB_ONLY) { pin (A) { direction : input; } }
}'''
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report_path = root / 'lef_analysis.json'
            report_path.write_text(json.dumps(lef), encoding='utf-8')
            lib_path = root / 'cells.lib'
            lib_path.write_text(liberty_text, encoding='utf-8')
            result = analyze(report_path, lib_path)
            report = render_markdown(result)

        self.assertEqual(result['comparison']['liberty_only_cells'], ['LIB_ONLY'])
        self.assertIn('/fixture/new.lef', report)
        self.assertNotIn('| — | — | 全部匹配 |', report)
        row = result['cells'][0]
        self.assertEqual(row['status'], 'MISMATCH')
        self.assertEqual(row['signal_pins']['missing_in_liberty'], ['Y'])
        self.assertEqual(row['signal_pins']['extra_in_liberty'], ['Z'])
        self.assertEqual(row['signal_pins']['direction_mismatch'], [{'pin': 'A', 'lef': 'INPUT', 'liberty': 'output'}])
        self.assertEqual(row['power_ground']['wrong_type'], [{'pin': 'VDD', 'lef_use': 'POWER', 'liberty_pg_type': 'primary_ground'}])
        self.assertEqual(row['power_ground']['missing_in_liberty'], ['VSS'])
        self.assertIn('LOGIC', report)
        self.assertIn('LIB_ONLY', report)
        self.assertIn('VDD', report)

    def test_incomplete_lef_coverage_yields_unverified_instead_of_missing_claim(self):
        lef = lef_analysis({'LOGIC': lef_macro([('A', 'INPUT', 'SIGNAL')])}, complete=False)
        liberty_text = 'library (TT) { cell (LOGIC) { pin (A) { direction : input; } } }'
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report_path = root / 'lef_analysis.json'
            report_path.write_text(json.dumps(lef), encoding='utf-8')
            lib_path = root / 'cells.lib'
            lib_path.write_text(liberty_text, encoding='utf-8')
            result = analyze(report_path, lib_path)

        self.assertEqual(result['cells'][0]['status'], 'UNVERIFIED')
        self.assertGreater(result['summary']['unverified_cell_count'], 0)

    def test_partial_liberty_reports_scope_gap_without_claiming_all_cells_match(self):
        lef = lef_analysis({
            'LOGIC': lef_macro([('A', 'INPUT', 'SIGNAL')]),
            'ONLY_IN_LEF': lef_macro([('A', 'INPUT', 'SIGNAL')]),
        })
        liberty_text = 'library (TT) { cell (LOGIC) { pin (A) { direction : input; } } }'
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report_path = root / 'lef_analysis.json'
            report_path.write_text(json.dumps(lef), encoding='utf-8')
            lib_path = root / 'subset.lib'
            lib_path.write_text(liberty_text, encoding='utf-8')
            result = analyze(report_path, lib_path)
            report = render_markdown(result)

        self.assertEqual(result['summary']['lef_only_macro_count'], 1)
        self.assertEqual(result['summary']['mismatch_cell_count'], 0)
        self.assertIn('`ONLY_IN_LEF`', report)
        self.assertIn('同名对象的 Pin 和电源脚均匹配', report)
        self.assertNotIn('全部匹配', report)

    def test_batch_keeps_corner_results_separate_and_reports_each_file(self):
        lef = lef_analysis({'LOGIC': lef_macro([
            ('A', 'INPUT', 'SIGNAL'), ('VDD', 'INOUT', 'POWER'), ('VSS', 'INOUT', 'GROUND'),
        ])})
        good = 'library (TT) { cell (LOGIC) { pin (A) { direction : input; } pg_pin (VDD) { pg_type : primary_power; } pg_pin (VSS) { pg_type : primary_ground; } } }'
        bad = 'library (SS) { cell (LOGIC) { pin (A) { direction : output; } pg_pin (VDD) { pg_type : primary_ground; } } }'
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report_path = root / 'lef_analysis.json'
            report_path.write_text(json.dumps(lef), encoding='utf-8')
            tt, ss = root / 'tt.lib', root / 'ss.lib.gz'
            tt.write_text(good, encoding='utf-8')
            with gzip.open(ss, 'wt', encoding='utf-8') as stream:
                stream.write(bad)
            result = analyze_many(report_path, [tt, ss])
            report = render_markdown(result)

        self.assertEqual(len(result['files']), 2)
        self.assertEqual(result['files'][0]['summary']['mismatch_cell_count'], 0)
        self.assertEqual(result['files'][1]['summary']['mismatch_cell_count'], 1)
        self.assertEqual(result['files'][1]['library_names'], ['SS'])
        self.assertEqual(result['summary']['liberty_file_count'], 2)
        self.assertEqual(result['summary']['files_with_mismatches'], 1)
        self.assertEqual(result['summary']['files_with_scope_gaps'], 0)
        self.assertIn('LEF-only / LIB-only', report)
        self.assertIn('`TT`', report)

    def test_batch_summarizes_corner_pin_and_power_ground_checks(self):
        lef = lef_analysis({'LOGIC': lef_macro([
            ('A', 'INPUT', 'SIGNAL'), ('Y', 'OUTPUT', 'SIGNAL'),
            ('VDD', 'INOUT', 'POWER'), ('VSS', 'INOUT', 'GROUND'),
        ])})
        liberty = '''library (asap7_TT) {
 operating_conditions (typical) { process : 1; voltage : 0.8; temperature : 25; }
 cell (LOGIC) {
  pin (A) { direction : input; } pin (Y) { direction : output; }
  pg_pin (VDD) { pg_type : primary_power; } pg_pin (VSS) { pg_type : primary_ground; }
 }
}'''
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report_path = root / 'lef_analysis.json'
            report_path.write_text(json.dumps(lef), encoding='utf-8')
            lib_path = root / 'asap7_TT.lib'
            lib_path.write_text(liberty, encoding='utf-8')
            result = analyze_many(report_path, [lib_path])
            report = render_markdown(result)

        stats = result['files'][0]['summary']
        self.assertEqual(result['summary']['recognized_corners'], ['TT'])
        self.assertEqual(result['summary']['recognized_corner_count'], 1)
        self.assertEqual(result['summary']['corner_file_counts'], {'TT': 1})
        self.assertEqual(result['summary']['files_with_unknown_corner'], 0)
        self.assertEqual(stats['signal_pin_checked_count'], 2)
        self.assertEqual(stats['signal_pin_missing_count'] + stats['signal_pin_extra_count']
                         + stats['signal_pin_direction_mismatch_count'], 0)
        self.assertEqual(stats['lef_power_pin_count'], 1)
        self.assertEqual(stats['lef_ground_pin_count'], 1)
        self.assertEqual(stats['power_ground_checked_count'], 2)
        self.assertIn('工艺角 TT 1', report)
        self.assertIn('未标 RC 角 1 个', report)
        self.assertIn('信号 Pin 对照：2 项', report)
        self.assertIn('电源/地脚对照：2 项', report)
        self.assertIn('process=1', report)

    def test_batch_reports_unknown_corner_without_inference_and_deduplicates_scope_gaps(self):
        lef = lef_analysis({
            'A': lef_macro([('A', 'INPUT', 'SIGNAL')]),
            'B': lef_macro([('A', 'INPUT', 'SIGNAL')]),
        })
        text = 'library (unnamed_library) { cell (A) { pin (A) { direction : input; } } }'
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report_path = root / 'lef_analysis.json'
            report_path.write_text(json.dumps(lef), encoding='utf-8')
            libs = []
            for name in ('vendor_alpha.lib', 'vendor_beta.lib'):
                path = root / name
                path.write_text(text, encoding='utf-8')
                libs.append(path)
            result = analyze_many(report_path, libs)
            report = render_markdown(result)

        self.assertEqual(result['summary']['files_with_unknown_corner'], 2)
        self.assertEqual(result['summary']['recognized_corners'], [])
        self.assertEqual(result['summary']['identical_scope_gap_groups'], 1)
        self.assertEqual(result['summary']['files_in_identical_scope_gap_groups'], 2)
        self.assertEqual(report.count('涉及 2 个文件'), 1)
        self.assertIn('工艺角未识别 2 个', report)

    def test_batch_lists_checks_not_performed_as_explicit_scope(self):
        lef = lef_analysis({'LOGIC': lef_macro([('A', 'INPUT', 'SIGNAL')])})
        text = 'library (TT) { cell (LOGIC) { pin (A) { direction : input; } } }'
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report_path = root / 'lef_analysis.json'
            report_path.write_text(json.dumps(lef), encoding='utf-8')
            lib_path = root / 'cells_TT.lib'
            lib_path.write_text(text, encoding='utf-8')
            report = render_markdown(analyze_many(report_path, [lib_path]))

        self.assertIn('本报告未检查', report)
        self.assertIn('时序弧与时序数值', report)
        self.assertIn('正式发布放行', report)

    def test_batch_separates_lef_inventory_from_liberty_comparison_coverage(self):
        lef = lef_analysis({'LOGIC': lef_macro([
            ('A', 'INPUT', 'SIGNAL'), ('VDD', 'INOUT', 'POWER'), ('VSS', 'INOUT', 'GROUND'),
        ])})
        lef['statistics']['new'].update({
            'macro_count': 1, 'pin_count': 3, 'layer_count': 4, 'used_layer_count': 4,
            'pin_rect_count': 7, 'obs_rect_count': 2,
            'pin_use_counts': {'SIGNAL': 1, 'POWER': 1, 'GROUND': 1},
            'class_counts': {'CORE': 1}, 'size_range_um': {'macro_count': 1, 'width': [1.0, 1.0], 'height': [2.0, 2.0]},
        })
        text = 'library (TT) { cell (LOGIC) { pin (A) { direction : input; } pg_pin (VDD) { pg_type : primary_power; } pg_pin (VSS) { pg_type : primary_ground; } } }'
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report_path = root / 'lef_analysis.json'
            report_path.write_text(json.dumps(lef), encoding='utf-8')
            lib_path = root / 'cells_TT.lib'
            lib_path.write_text(text, encoding='utf-8')
            result = analyze_many(report_path, [lib_path])
            report = render_markdown(result)

        self.assertEqual(result['lef_inventory']['pin_count'], 3)
        self.assertEqual(result['lef_inventory']['pin_use_counts']['POWER'], 1)
        self.assertEqual(result['files'][0]['liberty_inventory']['pg_pin_count'], 2)
        self.assertIn('LEF 基准规模', report)
        self.assertIn('| 1 | 3 |', report)
        self.assertIn('1 Cell / 1 信号 Pin / 2 电源地 Pin', report)
        self.assertIn('CORE: 1', report)
        self.assertIn('1.0–1.0 × 2.0–2.0 μm', report)

    def test_batch_report_frontloads_per_file_cell_coverage_and_pin_scope(self):
        lef = lef_analysis({
            'LOGIC_A': lef_macro([('A', 'INPUT', 'SIGNAL')]),
            'LOGIC_B': lef_macro([('B', 'OUTPUT', 'SIGNAL')]),
        })
        text = 'library (TT) { cell (LOGIC_A) { pin (A) { direction : input; } } }'
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report_path = root / 'lef_analysis.json'
            report_path.write_text(json.dumps(lef), encoding='utf-8')
            lib_path = root / 'cells_TT.lib'
            lib_path.write_text(text, encoding='utf-8')
            report = render_markdown(analyze_many(report_path, [lib_path]))

        self.assertIn('本节先给出本次输入文件集合的并集，再列单文件覆盖', report)
        self.assertIn('1/2（50.0%）', report)
        self.assertIn('LEF 有、当前 Liberty 文件未包含 1 个 Macro', report)
        self.assertIn('Pin 差异只适用于这 1 个同名对象', report)
        self.assertLess(report.index('### 本次输入 Liberty 集合覆盖'), report.index('## LEF 基准规模'))

    def test_corner_axes_recognize_ffpg_sspg_tt_and_rc_labels(self):
        lef = lef_analysis({'LOGIC': lef_macro([('A', 'INPUT', 'SIGNAL')])})
        liberty = 'library (L) { cell (LOGIC) { pin (A) { direction : input; } } }'
        names = [
            'ddl_delay_path_ffpg_sigrcmin_0p715v_0c.lib',
            'ddl_delay_path_sspg_sigrcmax_0p675v_125c.lib',
            'ddl_delay_path_tt_nominal_0p75v_85c.lib',
        ]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            lef_path = root / 'lef_analysis.json'
            lef_path.write_text(json.dumps(lef), encoding='utf-8')
            libs = []
            for name in names:
                path = root / name
                path.write_text(liberty, encoding='utf-8')
                libs.append(path)
            result = analyze_many(lef_path, libs)
            report = render_markdown(result)

        self.assertEqual(result['summary']['process_corner_file_counts'], {'FFPG': 1, 'SSPG': 1, 'TT': 1})
        self.assertEqual(result['summary']['rc_corner_file_counts'], {'SIGRCMAX': 1, 'SIGRCMIN': 1})
        self.assertEqual(result['summary']['files_with_unknown_process_corner'], 0)
        self.assertEqual(result['summary']['files_with_unknown_rc_corner'], 1)
        self.assertIn('工艺角 FFPG 1、SSPG 1、TT 1', report)
        self.assertIn('RC 角 SIGRCMAX 1、SIGRCMIN 1', report)

    def test_screenshot_corner_mix_is_counted_by_independent_axes(self):
        lef = lef_analysis({'LOGIC': lef_macro([('A', 'INPUT', 'SIGNAL')])})
        liberty = 'library (L) { cell (LOGIC) { pin (A) { direction : input; } } }'
        names = (
            [f'ddl_delay_path_ffpg_sigrcmin_{voltage}_{temp}.lib'
             for voltage in ('0p715v', '0p825v', '0p935v') for temp in ('0c', '125c')]
            + [f'ddl_delay_path_sspg_sigrcmax_{voltage}_{temp}.lib'
               for voltage in ('0p675v', '0p765v') for temp in ('0c', '125c')]
            + ['ddl_delay_path_tt_nominal_0p75v_85c.lib',
               'ddl_delay_path_tt_nominal_0p85v_85c.lib']
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            lef_path = root / 'lef_analysis.json'
            lef_path.write_text(json.dumps(lef), encoding='utf-8')
            paths = []
            for name in names:
                path = root / name
                path.write_text(liberty, encoding='utf-8')
                paths.append(path)
            result = analyze_many(lef_path, paths)
            report = render_markdown(result)
        summary = result['summary']
        self.assertEqual(summary['liberty_file_count'], 12)
        self.assertEqual(summary['process_corner_file_counts'], {'FFPG': 6, 'SSPG': 4, 'TT': 2})
        self.assertEqual(summary['rc_corner_file_counts'], {'SIGRCMIN': 6, 'SIGRCMAX': 4})
        self.assertEqual(summary['files_with_unknown_process_corner'], 0)
        self.assertEqual(summary['files_with_unknown_rc_corner'], 2)
        self.assertIn('工艺角 FFPG 6、SSPG 4、TT 2', report)
        self.assertIn('RC 角 SIGRCMAX 4、SIGRCMIN 6', report)
        self.assertIn('无 RC 角标', report)

    def test_cli_script_runs_when_copied_outside_package(self):
        lef = lef_analysis({'LOGIC': lef_macro([('A', 'INPUT', 'SIGNAL')])})
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            script = root / 'lef_liberty_check.py'
            source_script = Path(__file__).resolve().parents[1] / 'lef_liberty_check.py'
            shutil.copy2(source_script, script)
            lef_path = root / 'lef_analysis.json'
            lef_path.write_text(json.dumps(lef), encoding='utf-8')
            liberty_path = root / 'standalone_TT.lib.gz'
            with gzip.open(liberty_path, 'wt', encoding='utf-8') as stream:
                stream.write('library (TT) { cell (LOGIC) { pin (A) { direction : input; } } }')
            completed = subprocess.run(
                [sys.executable, '-I', str(script), str(lef_path), str(liberty_path),
                 '--out-dir', str(root / 'output')],
                cwd=root, text=True, capture_output=True, check=False,
            )
            report_exists = (root / 'output' / 'lef_liberty_check.md').is_file()

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn('"status": "DONE"', completed.stdout)
        self.assertTrue(report_exists)


if __name__ == '__main__':
    unittest.main()
