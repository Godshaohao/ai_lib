import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from lib_guard.diff.file_diff import diff_pairwise_files


LEF = '''VERSION 5.8 ;
BUSBITCHARS "[]" ;
MACRO M
 CLASS BLOCK ;
 ORIGIN 0 0 ;
 SIZE 1 BY 2 ;
 SITE siteA ;
 PIN A
  DIRECTION INPUT ;
  USE SIGNAL ;
  PORT
   LAYER M1 ;
   RECT 0 0 0.1 0.1 ;
  END
 END A
 PIN VDD
  DIRECTION INOUT ;
  USE POWER ;
  PORT
   LAYER M1 ;
   RECT 0 1 1 1.1 ;
  END
 END VDD
 OBS
  LAYER M2 ;
  RECT 0.2 0.2 0.8 1.8 ;
 END
END M
END LIBRARY
'''


def pair(root, kind, old, new):
    a, b = root / 'v1' / ('a.' + kind), root / 'v2' / ('b.' + kind)
    for path, text in ((a, old), (b, new)):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    out = root / ('pair_' + kind)
    diff_pairwise_files(kind, a, b, out)
    row = json.loads((out / 'pairwise_result.json').read_text())
    row.update(evidence_dir=str(out), file_type=kind, base_version='v1',
               freshness='文件状态未改变', evidence_id='sample', report_alignment='ALIGNED')
    return row


def bind_snapshots(root, row):
    scans = {}
    for side, version in (('old', 'v1'), ('new', 'v2')):
        scan = root / 'scans' / version
        scan.mkdir(parents=True)
        source = Path(row[side + '_file'])
        inventory = {'root_path': str(source.parent), 'files': [{
            'path': source.name, 'size_bytes': row['source_stamps'][side]['size'],
            'mtime_ns': row['source_stamps'][side]['mtime_ns'],
            'sha256': row['content_sha256'][side],
        }]}
        (scan / 'file_inventory.json').write_text(json.dumps(inventory))
        scans[side] = (scan, inventory)
    return {'base_version': 'v1', 'source_roots': {'current': str(root / 'v2'), 'base': str(root / 'v1')},
            'diff_meta': {'old_scan': str(scans['old'][0]), 'new_scan': str(scans['new'][0])},
            'scan_evidence': {'context': {'scan_dir': str(scans['new'][0])}, 'inventory': scans['new'][1]}}


class EngineeringReportTest(unittest.TestCase):
    def test_same_source_bytes_do_not_become_engineering_change_from_parser_drift(self):
        from lib_guard.review.engineering import build_engineering_report
        with tempfile.TemporaryDirectory() as td:
            row = pair(Path(td), 'lef', LEF, LEF)
            semantic_path = Path(row['evidence_dir']) / 'semantic_diff.json'
            semantic = json.loads(semantic_path.read_text())
            semantic['changes'] = [{'path': 'macros.M.size.x', 'old': 1.0, 'new': 3.0}]
            semantic_path.write_text(json.dumps(semantic))
            row['parsed_fields_status'] = 'DIFF'
            report = build_engineering_report({'representative_files': [row]})
            self.assertEqual(report['changed'], 0)
            self.assertEqual(report['same_files'], 1)
            self.assertTrue(any('解析结果与文件内容相同的证据冲突' in text for text in report['limitations']))

    def test_history_summary_is_rebuilt_without_copying_old_large_exports(self):
        from lib_guard.review.representative_files import save_representative_file
        from lib_guard.review.publication import load_current_file_checks
        from lib_guard.render.version_file_checks import render_file_checks
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            first = pair(root, 'lef', LEF, LEF)
            first_saved = save_representative_file(root / 'notes', 'demo', 'v2', first['evidence_dir'], started_epoch=1)
            second = pair(root, 'lef', LEF, LEF.replace('SIZE 1 BY 2', 'SIZE 3 BY 2'))
            save_representative_file(root / 'notes', 'demo', 'v2', second['evidence_dir'], started_epoch=2)
            rows = load_current_file_checks(root / 'notes', 'demo', 'v2')
            page = root / 'html/index.html'
            html = render_file_checks(rows, {}, page)
            self.assertIn('历史核查摘要', html)
            old_dir = page.parent / 'representative/lef' / first_saved['evidence_id']
            self.assertTrue((old_dir / 'pairwise_summary.md').is_file())
            self.assertFalse((old_dir / 'file_diff_export.zip').exists())

    def test_combination_delta_has_field_values_and_uncovered_objects_are_grouped(self):
        from lib_guard.review.engineering import build_engineering_report
        semantic = {'status': 'CURRENT', 'effective_id': 'full_fix', 'generation': 'a' * 64,
                    'object_names': {'M': 'Macro M'}, 'delta': [{
                        'check_id': 'LEF_PHYSICAL_DELTA', 'macro_id': 'M', 'attribute': 'size_um',
                        'status': 'CHANGED', 'details': {'old': [1, 2], 'new': [3, 2]},
                        'old_evidence': {'parser_result_ref': '/scan/old.json'},
                        'new_evidence': {'parser_result_ref': '/scan/new.json'},
                    }], 'checks': [{
                        'check_id': 'SIGNAL_PORT_SET', 'macro_id': str(i), 'status': 'NOT_CHECKED',
                        'reason_code': 'UNCONFIRMED_BINDING', 'evidence_refs': ['/scan/new.json'],
                    } for i in range(12)]}
        report = build_engineering_report({'semantic_check': semantic})
        change = next(item for item in report['findings'] if item['status'] == 'CHANGED')
        self.assertEqual(change['old'], [1, 2])
        self.assertEqual(change['new'], [3, 2])
        self.assertIn('/scan/new.json', change['source'])
        pending = [item for item in report['findings'] if item['status'] == 'NOT_CHECKED']
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]['item_count'], 12)
        self.assertEqual(report['pending'], 12)

    def test_actual_page_prioritizes_engineering_content_and_uses_qualified_note_status(self):
        from lib_guard.render.version_detail_report import render_version_detail_page
        from lib_guard.review.update_notes import save_update_note
        from lib_guard.test.semantic_fixture import SemanticFixture
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            fixture = SemanticFixture(root)
            version = fixture.version('full', views=('lef',))
            save_update_note(root / 'review_notes', 'demo', 'full', {'summary': '接口更新说明'}, publish=True)
            page = Path(render_version_detail_page(root / 'catalog/html', fixture.catalog['libraries'][0], version, export_markdown=True))
            html = page.read_text()
            self.assertLess(html.index('data-section="engineering-overview"'), html.index('data-section="view-delta"'))
            self.assertLess(html.index('data-section="engineering-findings"'), html.index('data-section="file-structure"'))
            self.assertIn('备注已发布', html)
            self.assertIn('对象与接口规格', html)
            markdown = (page.parent / 'current_lib_diff.md').read_text()
            self.assertLess(markdown.index('工程阅读摘要'), markdown.index('文件变化'))

    def test_aligned_same_hash_corrects_only_its_file_without_rechecking_raw(self):
        from lib_guard.review.publication import publish_file_diff
        from lib_guard.render.version_detail_report import build_version_update_detail_model
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            row = pair(root, 'lef', LEF, LEF)
            bound = bind_snapshots(root, row)
            diff = root / 'diff'
            diff.mkdir()
            (diff / 'diff_meta.json').write_text(json.dumps(bound['diff_meta']))
            (diff / 'file_diff.json').write_text(json.dumps({'changed': ['lef/shared.lef'], 'counts': {'added': 0, 'removed': 0, 'changed': 1}, 'logical_path_changes': [
                {'logical_path': 'lef/shared.lef', 'old': 'a.lef', 'new': 'b.lef'}]}))
            (diff / 'diff_summary.json').write_text(json.dumps({'status': 'DIFF', 'changed_files': 1}))
            new = {'version_id': 'v2', 'raw_path': str(root / 'v2'), 'scan': {'scan_dir': bound['diff_meta']['new_scan']},
                   'diff': {'base_version': 'v1', 'base_diff_dir': str(diff)}}
            lib = {'library_id': 'demo', 'library_name': 'demo', 'versions': [
                {'version_id': 'v1', 'raw_path': str(root / 'v1')}, new]}
            catalog = root / 'catalog/catalog.json'
            catalog.parent.mkdir()
            catalog.write_text(json.dumps({'libraries': [lib]}))
            publish_file_diff(catalog, root / 'catalog/html', 'demo', 'v2', row['evidence_dir'], refresh=False)
            model = build_version_update_detail_model(root / 'catalog/html', lib, new)
            self.assertEqual(model['confirmed_unchanged_files'], ['lef/shared.lef'])
            self.assertEqual(model['changed_files'], 0)
            self.assertEqual(model['engineering_report']['same_files'], 1)
            self.assertEqual(model['ip_user_view_model']['comparison']['visible_counts']['unmatched_new'], 0)
            self.assertEqual(model['review_report']['view_delta_analysis']['evidence_reconciliation']['status'], 'RECONCILED')

    def test_same_file_alignment_requires_both_snapshot_stamps_and_hash_identity(self):
        from lib_guard.review.engineering import file_check_alignment
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            row = pair(root, 'lef', LEF, LEF)
            model = bind_snapshots(root, row)
            self.assertEqual(file_check_alignment(model, row), 'ALIGNED')
            model['scan_evidence']['inventory']['files'][0]['sha256'] = 'f' * 64
            self.assertEqual(file_check_alignment(model, row), 'SOURCE_ONLY')
            model['scan_evidence']['inventory']['files'][0]['sha256'] = row['content_sha256']['new']
            row['base_version'] = 'other'
            self.assertEqual(file_check_alignment(model, row), 'SOURCE_ONLY')

    def test_same_lef_has_usable_object_and_pin_facts_with_explicit_scope(self):
        from lib_guard.review.engineering import build_engineering_report
        with tempfile.TemporaryDirectory() as td:
            row = pair(Path(td), 'lef', LEF, LEF)
            report = build_engineering_report({'representative_files': [row]})
            source = report['sources'][0]
            self.assertEqual(source['object_count'], 1)
            self.assertEqual(source['pin_count'], 2)
            self.assertEqual(source['objects'][0]['size'], {'x': 1.0, 'y': 2.0})
            self.assertEqual(source['objects'][0]['site'], 'siteA')
            self.assertEqual(source['objects'][0]['signal_pins'], 1)
            self.assertEqual(source['objects'][0]['power_pins'], 1)
            self.assertIn('所选', source['scope'])
            self.assertEqual(report['same_files'], 1)
            self.assertEqual(report['changed'], 0)
            self.assertTrue(any('内容未变化' in line for line in report['key_facts']))
            self.assertTrue(any('siteA' in line and '2.0 µm' in line for line in report['key_facts']))

    def test_controlled_lef_changes_locate_object_field_values_and_action(self):
        from lib_guard.review.engineering import build_engineering_report
        with tempfile.TemporaryDirectory() as td:
            changed = LEF.replace('SIZE 1 BY 2', 'SIZE 3 BY 2').replace('DIRECTION INPUT', 'DIRECTION OUTPUT')
            changed = changed.replace('RECT 0 0 0.1 0.1', 'RECT 0 0 0.3 0.1').replace('RECT 0.2 0.2 0.8 1.8', 'RECT 0.3 0.2 0.8 1.8')
            changed = changed.replace(' OBS', ' PIN B\n DIRECTION INPUT ;\n USE SIGNAL ;\n END B\n OBS')
            row = pair(Path(td), 'lef', LEF, changed)
            report = build_engineering_report({'representative_files': [row]})
            findings = report['findings']
            for topic in ('size', 'direction', 'geometry', 'obs', 'pin_set'):
                matches = [item for item in findings if item['topic'] == topic and item['status'] == 'CHANGED']
                self.assertTrue(matches, topic)
                self.assertTrue(all(item['object'].startswith('M') and item['advice'] and item['source'] for item in matches))
            width = next(item for item in findings if item['topic'] == 'size')
            self.assertNotEqual(width['old'], width['new'])
            self.assertIn('µm', width['label'])
            added_pin = next(item for item in findings if item['label'] == '接口 Pin · B')
            self.assertNotIn('line_start', str(added_pin['new']))
            self.assertNotIn('line_end', str(added_pin['new']))

    def test_partial_or_stale_evidence_is_not_a_current_change(self):
        from lib_guard.review.engineering import build_engineering_report
        with tempfile.TemporaryDirectory() as td:
            row = pair(Path(td), 'lef', LEF, LEF.replace('DIRECTION INPUT', 'DIRECTION OUTPUT'))
            path = Path(row['evidence_dir']) / 'new_extract.json'
            payload = json.loads(path.read_text())
            payload['data']['semantic_coverage']['port_set'] = 'NOT_EXTRACTED'
            path.write_text(json.dumps(payload))
            report = build_engineering_report({'representative_files': [row]})
            directions = [item for item in report['findings'] if item['topic'] == 'direction']
            self.assertTrue(directions)
            self.assertTrue(all(item['status'] == 'NOT_CHECKED' for item in directions))
            row['freshness'] = '源文件已变化，需重新核查'
            report = build_engineering_report({'representative_files': [row]})
            self.assertEqual(report['changed'], 0)
            self.assertEqual(report['same_files'], 0)
            self.assertFalse(report['sources'][0]['current'])

    def test_liberty_verilog_and_cdl_show_interfaces_without_inventing_timing(self):
        from lib_guard.review.engineering import build_engineering_report
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            liberty = 'library (L) { operating_conditions (tt) { voltage : 0.7; temperature : 25; } cell (M) { area : 2; pin (A) { direction : input; } pg_pin (VDD) { pg_type : primary_power; } } }'
            rows = [pair(root, 'liberty', liberty, liberty),
                    pair(root, 'verilog', 'module M(input [1:0] A); endmodule', 'module M(input [3:0] A); endmodule'),
                    pair(root, 'cdl', '.SUBCKT M A VDD\n.ENDS M\n', '.SUBCKT M A B VDD\n.ENDS M\n')]
            report = build_engineering_report({'representative_files': rows})
            by_type = {item['file_type']: item for item in report['sources']}
            self.assertEqual(by_type['liberty']['contexts'][0]['name'], 'tt')
            self.assertIn('时序性能尚未比较', by_type['liberty']['limitations'])
            self.assertEqual(by_type['verilog']['objects'][0]['ports'][0]['width'], 4)
            self.assertEqual(by_type['cdl']['objects'][0]['ports'][1]['name'], 'B')
            self.assertTrue(any(item['topic'] == 'width' and item['status'] == 'CHANGED' for item in report['findings']))
            self.assertTrue(any(item['label'] == '端口范围 · A' for item in report['findings']))
            self.assertFalse(any('declared_range' in item['label'] for item in report['findings']))

    def test_first_version_uses_existing_scan_result_without_raw_reads(self):
        from lib_guard.review.engineering import build_engineering_report
        from lib_guard.scan.parsers.lef import parse_lef_text
        result = {'file_type': 'lef', 'file': 'lef/a.lef', 'status': 'PASS', 'data': parse_lef_text(LEF)}
        model = {'review_mode': 'first_version', 'scan_evidence': {
            'context': {'scan_dir': '/scan', 'raw_path': '/raw'},
            'parser_results': {'parser_results/lef/a.json': result},
            'inventory': {'files': [{'path': 'lef/a.lef', 'file_type': 'lef'}]},
        }}
        with patch('pathlib.Path.read_text', side_effect=AssertionError('unexpected file read')):
            report = build_engineering_report(model)
        self.assertEqual(report['sources'][0]['object_count'], 1)
        self.assertEqual(report['changed'], 0)
        self.assertEqual(report['same_files'], 0)
        self.assertIn('未执行版本深度对比', report['limitations'])

    def test_reader_has_delivery_requirements_and_absence_of_optional_db_is_neutral(self):
        from lib_guard.review.engineering import build_engineering_report
        report = build_engineering_report({'ip_user_view_model': {'delivery_completeness': {
            'status': 'PASS', 'required_total': 1, 'required_present': 1, 'missing': [],
            'delivery_requirements': {'status': 'PASS'},
        }}, 'lib_db_correspondence': {'liberty_count': 1, 'db_count': 0}})
        self.assertIn('1 / 1', report['delivery_summary'])
        self.assertNotIn('DB', report['delivery_summary'])
        self.assertEqual(report['contact'], '未登记')

    def test_unconfigured_context_and_metadata_only_view_are_not_full_delivery_pass(self):
        from lib_guard.review.engineering import build_engineering_report
        report = build_engineering_report({'ip_user_view_model': {'delivery_completeness': {
            'status': 'PASS', 'required_total': 1, 'required_present': 1,
            'required_views': ['RTL 模型'], 'missing': [],
            'required_view_evidence': [{'view': 'rtl_model', 'validation_level': 'metadata_required'}],
            'delivery_requirement_status': 'NOT_CONFIGURED',
            'delivery_requirements': {
                'views': {'status': 'PASS'},
                'modes': {'status': 'NOT_CONFIGURED'},
                'corners': {'status': 'NOT_CONFIGURED'},
            },
        }}})
        self.assertIn('RTL 模型 1 / 1', report['delivery_summary'])
        self.assertIn('元数据级', report['delivery_summary'])
        self.assertIn('模式/工艺角未配置', report['delivery_summary'])
        self.assertNotIn('已满足现有配置', report['delivery_summary'])
        self.assertTrue(any('不代表整库交付齐全' in item for item in report['limitations']))

    def test_projected_readiness_without_context_details_still_names_the_gap(self):
        from lib_guard.review.engineering import build_engineering_report
        report = build_engineering_report({'ip_user_view_model': {'delivery_completeness': {
            'status': 'PASS', 'required_total': 1, 'required_present': 1,
            'required_views': ['RTL 模型'], 'missing': [],
            'required_view_evidence': [{'view': 'rtl_model', 'validation_level': 'metadata_required'}],
            'delivery_requirement_status': 'NOT_CONFIGURED', 'delivery_requirements': {},
        }}})
        self.assertIn('模式/工艺角要求未配置', report['delivery_summary'])

    def test_metadata_only_delivery_does_not_render_zero_of_zero_parsed_files(self):
        from lib_guard.review.engineering import build_engineering_report
        from lib_guard.render.version_engineering import render_engineering_report
        delivery = {'status': 'PASS', 'required_total': 1, 'required_present': 1,
                    'required_views': ['RTL 模型'], 'missing': [],
                    'required_view_evidence': [{
                        'view': 'rtl_model', 'status': 'PASS', 'validation_level': 'metadata_required',
                        'total': 0, 'satisfied': 0, 'message': '已记录元数据；该视图不要求深度解析。',
                    }], 'delivery_requirement_status': 'NOT_CONFIGURED'}
        report = build_engineering_report({'ip_user_view_model': {'delivery_completeness': delivery}})
        html = render_engineering_report(report, Path('/tmp/version-detail.html'))
        self.assertIn('文件已发现；未要求深度解析', html)
        self.assertNotIn('0 / 0 文件满足检查口径', html)

    def test_reader_summary_keeps_file_changes_separate_from_engineering_findings(self):
        from lib_guard.render.version_detail_report import _reader_summary
        model = {
            'engineering_report': {
                'delivery_summary': 'RTL 模型 1 / 1', 'key_facts': ['所选 LEF 文件内容未变化'],
                'limitations': ['跨视图组合检查尚未执行'], 'same_files': 1,
                'changed': 0, 'failures': 0, 'findings': [], 'contact': '未登记',
            },
            'ip_user_view_model': {'comparison': {'visible_counts': {
                'added': 2, 'removed': 1, 'changed': 3, 'unmatched_new': 1, 'unmatched_base': 0,
            }}},
            'status': 'CHANGED', 'review_mode': 'baseline',
        }
        html = _reader_summary(model, {})
        self.assertIn('文件范围', html)
        self.assertIn('新增 2', html)
        self.assertIn('删除 1', html)
        self.assertIn('修改 3', html)
        self.assertIn('待核对 1', html)
        self.assertIn('不等同于已确认的单元或接口变化', html)
        self.assertIn('未完成核查：跨视图组合检查尚未执行', html)
        self.assertIn('先核对本版文件变化', html)
        self.assertNotIn('可沿用该文件的已有定义', html)

    def test_reader_summary_puts_action_before_secondary_scope(self):
        from lib_guard.render.version_detail_report import _reader_summary
        model = {
            'engineering_report': {'delivery_summary': 'RTL 模型已发现',
                                   'key_facts': ['所选 LEF 文件内容未变化'],
                                   'limitations': ['跨视图组合检查尚未执行'], 'findings': []},
            'ip_user_view_model': {'comparison': {'visible_counts': {'added': 2}}},
            'status': 'CHANGED', 'review_mode': 'baseline',
        }
        html = _reader_summary(model, {})
        self.assertIn('<h2>阅读要点</h2>', html)
        self.assertLess(html.index('建议动作'), html.index('交付情况'))
        self.assertIn('<details class="reader-file-counts">', html)
        self.assertLess(html.index('reader-file-counts'), html.index('新增 2'))

    def test_note_details_are_available_without_dominating_first_screen(self):
        from lib_guard.render.version_detail_report import _version_update_note_panel
        html = _version_update_note_panel({'update_note': {
            'status': 'published', 'summary': '验证物理视图',
            'key_changes': ['LEF 更新'], 'risks': ['GDS 待核对'],
            'must_check': ['核对 Pin'],
        }})
        self.assertIn('<details class="update-note-more">', html)
        self.assertLess(html.index('验证物理视图'), html.index('update-note-more'))
        self.assertIn('LEF 更新', html)

    def test_reader_summary_does_not_invent_file_changes_for_first_version(self):
        from lib_guard.render.version_detail_report import _reader_summary
        model = {'review_mode': 'first_version', 'status': 'FIRST_VERSION',
                 'engineering_report': {'delivery_summary': '交付要求待确认',
                                        'key_facts': ['所选 LEF 文件规格已提取'],
                                        'limitations': [], 'same_files': 0, 'findings': []},
                 'ip_user_view_model': {'comparison': {'visible_counts': {'added': 9}}}}
        html = _reader_summary(model, {})
        self.assertNotIn('文件范围：新增', html)

    def test_confirmed_engineering_issue_precedes_unconfigured_contract_advice(self):
        from lib_guard.render.version_detail_report import _reader_summary
        model = {'status': 'CHANGED', 'review_mode': 'baseline',
                 'engineering_report': {
                     'delivery_summary': 'RTL 模型 1 / 1', 'limitations': ['不代表整库交付齐全'],
                     'key_facts': ['单元 M 的 Pin 已变化'], 'changed': 1, 'failures': 0,
                     'findings': [{'status': 'CHANGED', 'advice': '核对 M 的实例连接'}],
                 },
                 'ip_user_view_model': {'comparison': {'visible_counts': {'changed': 1}}}}
        html = _reader_summary(model, {})
        self.assertIn('<strong>建议动作</strong><p>核对 M 的实例连接', html)

    def test_engineering_html_has_searchable_object_and_finding_tables_before_file_counts(self):
        from lib_guard.review.engineering import build_engineering_report
        from lib_guard.render.version_engineering import render_engineering_report
        with tempfile.TemporaryDirectory() as td:
            row = pair(Path(td), 'lef', LEF, LEF.replace('SIZE 1 BY 2', 'SIZE 3 BY 2'))
            report = build_engineering_report({'representative_files': [row]})
            html = render_engineering_report(report, Path(td) / 'index.html')
            for text in ('库内容概览', '工程变化与检查结果', '对象', '检查项', '旧值', '新值', '接入关注点', '证据范围'):
                self.assertIn(text, html)
            self.assertIn('data-filterable-table', html)
            self.assertIn('engineering-scroll', html)
            self.assertIn('M', html)

    def test_large_object_inventory_is_collapsed_but_findings_remain_visible(self):
        from lib_guard.review.engineering import build_engineering_report
        from lib_guard.render.version_engineering import render_engineering_report
        with tempfile.TemporaryDirectory() as td:
            same = pair(Path(td), 'lef', LEF, LEF)
            same_html = render_engineering_report(build_engineering_report({'representative_files': [same]}), Path(td) / 'index.html')
            self.assertIn('<details class="engineering-object-list">', same_html)
            self.assertIn('engineering-objects', same_html)
            self.assertNotIn("id='engineering-findings'", same_html)
            changed = pair(Path(td), 'lef', LEF, LEF.replace('SIZE 1 BY 2', 'SIZE 3 BY 2'))
            changed_html = render_engineering_report(build_engineering_report({'representative_files': [changed]}), Path(td) / 'index.html')
            self.assertIn("id='engineering-findings'", changed_html)


if __name__ == '__main__':
    unittest.main()
