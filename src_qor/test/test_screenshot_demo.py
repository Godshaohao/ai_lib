import json
import importlib.util
from copy import deepcopy
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

from lib_guard.ip_file_history import parse_formal_manifest, read_ip_roster, run_roster
from lib_guard.file_status import scan_registered_raw_files
from lib_guard.file_version_projection import build_projection
from lib_guard.workbench import create_app


class ScreenshotDemoTests(unittest.TestCase):
    def test_missing_manifest_copy_and_unspecified_stage_remain_unverified(self):
        from lib_guard.workbench import _formal_manifest_snapshot, _prepare_applicable_review, _read_registry
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / 'demo'
            generator = Path(__file__).resolve().parents[1] / 'examples/screenshot_roster/make_demo.py'
            subprocess.run([sys.executable, str(generator), '--out', str(root)], check=True, capture_output=True)
            run_roster(root / 'roster_config.json', root / 'batch')
            registry_path = root / 'batch/workbench_registry.json'
            registry = _read_registry(registry_path)
            entry = next(item for item in registry['ips'] if item['name'] == 'MXCML2CMOS')
            prepared = _prepare_applicable_review(entry, registry, registry_path, root / 'web')
            snapshot = prepared['formal_manifest_snapshot']
            self.assertEqual(snapshot['records'][0]['status'], 'PUBLISHED_FOUND_SOURCE_UNKNOWN')
            self.assertEqual(snapshot['records'][0]['formal_relation'], 'UNVERIFIED')
            checklist = next(item for item in prepared['engineering_checklist'] if item['id'] == 'formal_source')
            self.assertEqual(checklist['execution'], '部分覆盖')
            self.assertIn('待核实', checklist['reason'])
            unscoped = _formal_manifest_snapshot(entry, registry_path, prepared['file_version_projection'], None)
            self.assertEqual(unscoped['status'], 'PARTIAL')
            self.assertEqual(unscoped['records'][0]['formal_relation'], 'UNVERIFIED')
            self.assertNotEqual(unscoped['records'][0]['status'], 'PUBLISHED_FILE_MISSING')
            missing = _formal_manifest_snapshot({**entry, 'formal_manifest': str(root / 'missing.list')},
                                                 registry_path, prepared['file_version_projection'], None)
            self.assertEqual(missing['status'], 'FAILED')
            self.assertTrue(missing['errors'])
            (root / 'formal_files.list').write_text('#MXCML2CMOS#\ninvalid row with too many fields\n')
            malformed = _formal_manifest_snapshot(entry, registry_path, prepared['file_version_projection'], root / 'lib_NL_demo')
            self.assertEqual(malformed['status'], 'PARTIAL')
            self.assertTrue(malformed['errors'])

    @unittest.skipUnless(importlib.util.find_spec('xlsxwriter'), '需要 XlsxWriter')
    def test_manifest_records_are_bound_to_review_and_excel_snapshot(self):
        from lib_guard.workbench import _prepare_applicable_review, _read_registry
        from lib_guard.review_runner import build_workbook_model, run
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / 'demo'
            generator = Path(__file__).resolve().parents[1] / 'examples/screenshot_roster/make_demo.py'
            subprocess.run([sys.executable, str(generator), '--out', str(root)], check=True, capture_output=True)
            batch = root / 'batch'
            run_roster(root / 'roster_config.json', batch)
            registry_path = batch / 'workbench_registry.json'
            registry = _read_registry(registry_path)
            entry = next(item for item in registry['ips'] if item['name'] == 'dwc_128g_phy_pma_ns_cm_serdes_top')
            self.assertEqual(entry['formal_manifest'], str(root / 'formal_files.list'))
            self.assertEqual(entry['formal_groups'], ['dwc_128g_phy_pma_ns_cm_serdes_top'])
            output = root / 'web'
            prepared = _prepare_applicable_review(entry, registry, registry_path, output)
            snapshot = prepared['formal_manifest_snapshot']
            self.assertEqual(snapshot['status'], 'COMPLETE')
            self.assertEqual(snapshot['raw_projection_snapshot_id'], prepared['raw_snapshot_id'])
            records = snapshot['records']
            self.assertEqual(len(records), 9)
            self.assertTrue(any(row['status'] == 'PUBLISHED_FILE_MISSING' for row in records))
            self.assertTrue({'LATEST', 'PREVIOUS', 'UNVERIFIED'} <= {row['formal_relation'] for row in records})
            from lib_guard.workbench import _formal_manifest_snapshot
            from lib_guard.review_runner import _finding_rows
            uncertain_projection = deepcopy(prepared['file_version_projection'])
            for item in uncertain_projection['files']:
                item['latest'] = {'status': 'UNKNOWN_ORDER'}
                item['previous'] = {'status': 'UNKNOWN_ORDER'}
            uncertain = _formal_manifest_snapshot(entry, registry_path, uncertain_projection, root / 'lib_NL_demo')
            self.assertTrue(any(row['status'] == 'SOURCE_PATH_CONFIRMED' and row['formal_relation'] == 'RANK_UNCERTAIN'
                                for row in uncertain['records']))
            self.assertTrue(any('排名未确认' in row['发现'] for row in _finding_rows({'formal_manifest_snapshot': uncertain})))
            original_hash = snapshot['sha256']
            (root / 'formal_files.list').write_text('#changed#\nnew.lef IP/LEF/\n')
            reviews, _ = run({'ips': [prepared]}, output)
            evidence = Path(reviews[0]['run_dir']) / 'evidence' / 'formal_manifest.json'
            saved = json.loads(evidence.read_text())
            self.assertEqual(saved['sha256'], original_hash)
            self.assertEqual(len(saved['records']), 9)
            rows = build_workbook_model(reviews)['07-正式文件']
            declared = [row for row in rows if row.get('记录类型') == '清单声明']
            self.assertEqual(len(declared), 9)
            self.assertTrue(any(row.get('清单核对') == '正式文件缺失' for row in declared))
            self.assertTrue(any(row.get('Formal 与 RAW 排名') == '正式来源为 RAW 次新' for row in declared))
            self.assertFalse(any('txrx_top' in str(row.get('相对路径')) for row in declared))
            self.assertTrue(any(row.get('类别') == '正式清单' for row in build_workbook_model(reviews)['04-关注项']))
            with zipfile.ZipFile(Path(reviews[0]['run_dir']) / 'ip_review.xlsx') as workbook:
                strings = workbook.read('xl/sharedStrings.xml').decode()
                self.assertIn('正式文件缺失', strings)
                self.assertIn('正式来源为 RAW 次新', strings)
                self.assertIn(original_hash, strings)

    def test_demo_lists_mapping_and_workbench(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / 'demo'
            generator = Path(__file__).resolve().parents[1] / 'examples/screenshot_roster/make_demo.py'
            subprocess.run([sys.executable, str(generator), '--out', str(root)], check=True, capture_output=True, text=True)
            ips = read_ip_roster(root / 'ipall.list')
            records, errors = parse_formal_manifest(root / 'formal_files.list')
            self.assertFalse(errors)
            self.assertGreaterEqual(len(ips), 5)
            self.assertIn('dwc_128g_phy_pma_ns_cm_serdes_top', ips)
            self.assertTrue({'LEF', 'LIB', 'DB', 'VERILOG', 'GDS', 'CDL', 'NDM'} <= {r['view'] for r in records})
            output = root / 'batch'
            run_roster(root / 'roster_config.json', output)
            report = json.loads((output / 'ip_overview.json').read_text())
            results = {row['ip']: row for row in report['ip_results']}
            first = results['dwc_128g_phy_pma_ns_cm_serdes_top']
            self.assertEqual(first['mapping_basis'], 'FORMAL_REAL_SOURCE')
            self.assertEqual(first['libraries'], ['DemoVendor.serdes_physical'])
            self.assertEqual(results['unknown_ip_not_delivered']['status'], 'UNMAPPED')
            details = json.loads((output / first['detail_path'] / 'result.json').read_text())
            lef = next(row for row in details['file_histories'] if row['identity_path'].endswith('_merged.lef'))
            self.assertEqual((lef['latest']['version'], lef['previous']['version']), ('V03', 'V01'))
            relations = {row['formal_relation'] for row in details['formal_manifest']}
            self.assertTrue({'LATEST', 'PREVIOUS', 'UNVERIFIED'} <= relations)
            copied = results['MXCML2CMOS']
            self.assertEqual(copied['mapping_basis'], 'EXACT_LIBRARY_NAME')
            copied_detail = json.loads((output / copied['detail_path'] / 'result.json').read_text())
            self.assertEqual(copied_detail['formal_manifest'][0]['formal_relation'], 'UNVERIFIED')
            self.assertEqual(copied_detail['formal_manifest'][0]['status'], 'PUBLISHED_FOUND_SOURCE_UNKNOWN')
            registry_data = json.loads((output / 'workbench_registry.json').read_text())
            entry = next(item for item in registry_data['ips'] if item['name'] == first['ip'])
            versions = entry['raw_versions']
            inventories = scan_registered_raw_files(versions)
            projection = build_projection(entry['library_id'], versions, inventories, [])
            ndm = next(row for row in projection['files'] if row['view'] == 'ndm')
            self.assertEqual(ndm['latest']['version'], 'V01')
            self.assertEqual(ndm['latest']['status'], 'CONFIRMED')
            registry = root / 'registry.json'
            registry.write_text('{"ips": []}')
            web_output = root / 'workbench'
            client = create_app(registry, web_output).test_client()
            response = client.post('/file-history/config', data={
                'action': 'test', 'ip_list': str(root / 'ipall.list'),
                'formal_manifest': str(root / 'formal_files.list'),
                'raw_root': str(root / 'RAW'), 'formal_root': str(root / 'lib_NL_demo')}, follow_redirects=True)
            self.assertEqual(response.status_code, 200)
            html = response.get_data(as_text=True)
            self.assertIn('dwc_128g_phy_pma_ns_cm_serdes_top', html)
            self.assertIn('DemoVendor.serdes_physical', html)
            self.assertIn('unknown_ip_not_delivered', html)

    def test_generator_does_not_overwrite_existing_directory(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / 'already_exists'
            root.mkdir()
            marker = root / 'ipall.list'
            marker.write_text('keep me')
            generator = Path(__file__).resolve().parents[1] / 'examples/screenshot_roster/make_demo.py'
            result = subprocess.run([sys.executable, str(generator), '--out', str(root)], capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(marker.read_text(), 'keep me')
