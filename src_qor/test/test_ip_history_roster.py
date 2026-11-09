import json
import importlib.util
import tempfile
import unittest
from pathlib import Path

from lib_guard.ip_file_history import (read_ip_roster, run_roster, discover_raw_libraries,
                             parse_formal_manifest)


class RosterTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.raw = self.root / 'RAW' / 'Supplier' / 'physical_library'
        for v in ('V01', 'V02', 'V03'):
            (self.raw / v / 'LEF').mkdir(parents=True, exist_ok=True)
        (self.raw / 'V01' / 'LEF' / 'core.lef').write_text('old')
        (self.raw / 'V03' / 'LEF' / 'core.lef').write_text('new')
        (self.raw / 'V01' / 'LEF' / 'alone.lef').write_text('old')
        self.formal = self.root / 'NL' / 'IP' / 'LEF'
        self.formal.mkdir(parents=True)
        (self.formal / 'core.lef').symlink_to(self.raw / 'V03' / 'LEF' / 'core.lef')
        (self.root / 'formal.list').write_text('#business_ip#\ncore.lef IP/LEF/\n'
                                              '#absent_ip#\nmissing.lef IP/LEF/\n')
        (self.root / 'ipall.list').write_text('business_ip\nabsent_ip\n')
        (self.root / 'config.json').write_text(json.dumps({
            'ip_list': 'ipall.list', 'raw_root': 'RAW',
            'formal_manifest': 'formal.list', 'formal_root': 'NL'}))

    def test_roster_parsing_and_repeated_ip_rejected(self):
        self.assertEqual(read_ip_roster(self.root/'ipall.list'), ['business_ip', 'absent_ip'])
        (self.root/'ipall.list').write_text('IP_A\n# comment\nIP_A # repeated\n')
        with self.assertRaisesRegex(ValueError, '重复'):
            read_ip_roster(self.root/'ipall.list')

    def test_formal_group_parser_from_screenshot_format(self):
        records, errors = parse_formal_manifest(self.root / 'formal.list')
        self.assertFalse(errors)
        self.assertEqual([x['group'] for x in records], ['business_ip', 'absent_ip'])
        self.assertEqual(records[0]['directory'], 'IP/LEF/')

    def test_auto_discovery_not_same_name_as_ip(self):
        libs, warnings = discover_raw_libraries(self.root/'RAW')
        self.assertFalse(warnings)
        self.assertEqual(libs[0]['library_id'], 'Supplier.physical_library')
        self.assertEqual([x['id'] for x in libs[0]['deliveries']], ['V01','V02','V03'])

    def test_formal_real_source_maps_different_business_and_raw_names(self):
        out = self.root/'out'
        summary = run_roster(self.root/'config.json',out)
        self.assertEqual(summary['requested_ip_count'],2)
        self.assertEqual(summary['ready_count'],1)
        self.assertEqual(summary['unmapped_count'],1)
        report = json.loads((out/'ip_overview.json').read_text())
        ip = report['ip_results'][0]
        self.assertEqual(ip['ip'], 'business_ip')
        self.assertEqual(ip['mapping_basis'], 'FORMAL_REAL_SOURCE')
        self.assertEqual(ip['libraries'], ['Supplier.physical_library'])
        detail = json.loads((out/ip['detail_path']/'result.json').read_text())
        row = [x for x in detail['file_histories'] if x['identity_path']=='core.lef'][0]
        self.assertEqual(row['latest']['version'], 'V03')
        self.assertEqual(row['previous']['version'], 'V01')
        self.assertEqual(detail['formal_manifest'][0]['formal_relation'], 'LATEST')
        self.assertEqual(report['ip_results'][1]['status'], 'UNMAPPED')

    def test_workbench_registry_is_generated_from_proven_mapping(self):
        out = self.root / 'out'
        run_roster(self.root / 'config.json', out)
        registry = json.loads((out / 'workbench_registry.json').read_text())
        self.assertEqual(len(registry['ips']), 1)
        entry = registry['ips'][0]
        self.assertEqual(entry['name'], 'business_ip')
        self.assertEqual(entry['library_id'], 'Supplier.physical_library')
        self.assertEqual([v['delivery_order'] for v in entry['raw_versions']], [1, 2, 3])
        self.assertEqual(entry['raw_versions'][0]['path'], str(self.raw / 'V01'))
        self.assertEqual(entry['formal_nl_root'], str(self.root / 'NL'))

    def test_shared_library_is_not_silently_assigned_to_two_business_ips(self):
        conf = json.loads((self.root / 'config.json').read_text())
        conf['ip_library_map'] = {'business_ip': ['Supplier.physical_library'],
                                  'absent_ip': ['Supplier.physical_library']}
        (self.root / 'config.json').write_text(json.dumps(conf))
        out = self.root / 'out'
        run_roster(self.root / 'config.json', out)
        registry = json.loads((out / 'workbench_registry.json').read_text())
        report = json.loads((out / 'ip_overview.json').read_text())
        self.assertEqual(registry['ips'], [])
        self.assertIn('Supplier.physical_library', report['workbench_registry_issues'][0])

    def test_explicit_mapping_can_link_without_soft_links(self):
        conf=json.loads((self.root/'config.json').read_text())
        conf['ip_library_map']={'absent_ip': ['Supplier.physical_library']}
        (self.root/'config.json').write_text(json.dumps(conf))
        run_roster(self.root/'config.json',self.root/'out')
        report=json.loads((self.root/'out'/'ip_overview.json').read_text())
        self.assertEqual(report['ip_results'][1]['mapping_basis'],'EXPLICIT_MAPPING')
        self.assertEqual(report['ip_results'][1]['status'],'READY')

    def test_without_actual_link_does_not_guess_from_manifest_filename(self):
        (self.formal/'core.lef').unlink()
        run_roster(self.root/'config.json',self.root/'out')
        report=json.loads((self.root/'out'/'ip_overview.json').read_text())
        self.assertEqual(report['ip_results'][0]['status'],'UNMAPPED')

    def test_plain_file_under_raw_root_is_not_formal_link_evidence(self):
        direct = self.raw / 'V03' / 'IP' / 'LEF'
        direct.mkdir(parents=True)
        (direct / 'core.lef').write_text('copy')
        conf = json.loads((self.root / 'config.json').read_text())
        conf['formal_root'] = str(self.raw / 'V03')
        (self.root / 'config.json').write_text(json.dumps(conf))
        run_roster(self.root / 'config.json', self.root / 'out')
        report = json.loads((self.root / 'out' / 'ip_overview.json').read_text())
        self.assertEqual(report['ip_results'][0]['status'], 'UNMAPPED')

    def test_ambiguous_link_owner_blocks_automatic_mapping(self):
        conf = json.loads((self.root / 'config.json').read_text())
        deliveries = [{'id': v, 'order': i, 'root': str(self.raw / v)}
                      for i, v in enumerate(('V01', 'V02', 'V03'), 1)]
        conf['libraries'] = [{'library_id': 'A.lib', 'deliveries': deliveries},
                             {'library_id': 'B.lib', 'deliveries': deliveries}]
        (self.root / 'config.json').write_text(json.dumps(conf))
        run_roster(self.root / 'config.json', self.root / 'out')
        report = json.loads((self.root / 'out' / 'ip_overview.json').read_text())
        self.assertEqual(report['ip_results'][0]['mapping_basis'], 'AMBIGUOUS_FORMAL_SOURCE')
        self.assertEqual(report['ip_results'][0]['libraries'], [])

    def test_generated_registry_opens_in_workbench(self):
        from lib_guard.workbench import create_app
        out = self.root / 'out'
        run_roster(self.root / 'config.json', out)
        client = create_app(out / 'workbench_registry.json', self.root / 'workbench').test_client()
        response = client.get('/')
        self.assertEqual(response.status_code, 200)
        self.assertIn('business_ip', response.get_data(as_text=True))

    @unittest.skipUnless(importlib.util.find_spec('xlsxwriter'), '需要 XlsxWriter')
    def test_generated_registry_runs_applicable_review_and_exports_excel(self):
        from lib_guard.workbench import _prepare_applicable_review, _read_registry
        from lib_guard.review_runner import build_workbook_model, run
        (self.root / 'NL').rename(self.root / 'lib_NL1')
        conf = json.loads((self.root / 'config.json').read_text())
        conf['formal_root'] = 'lib_NL1'
        (self.root / 'config.json').write_text(json.dumps(conf))
        out = self.root / 'history'
        run_roster(self.root / 'config.json', out)
        registry_path = out / 'workbench_registry.json'
        registry = _read_registry(registry_path)
        workbench_out = self.root / 'workbench'
        entry = _prepare_applicable_review(registry['ips'][0], registry, registry_path, workbench_out)
        reviews, _ = run({'ips': [entry]}, workbench_out)
        self.assertTrue((Path(reviews[0]['run_dir']) / 'ip_review.xlsx').is_file())
        core = next(row for row in reviews[0]['file_version_projection']['files']
                    if row['display_name'] == 'core.lef')
        self.assertEqual(core['formal_usage']['source_version'], 'V03')
        self.assertEqual(core['formal_usage']['raw_version_relation'], 'LATEST')
        formal_row = next(row for row in build_workbook_model(reviews)['07-正式文件']
                          if row['相对路径'].endswith('core.lef'))
        self.assertEqual(formal_row['Formal 与 RAW 排名'], '正式来源为 RAW 最新')

    def test_formal_group_remapping_supported(self):
        (self.root/'ipall.list').write_text('renamed_business_ip\n')
        conf=json.loads((self.root/'config.json').read_text())
        conf['formal_group_map']={'renamed_business_ip': ['business_ip']}
        (self.root/'config.json').write_text(json.dumps(conf))
        run_roster(self.root/'config.json',self.root/'out')
        report=json.loads((self.root/'out'/'ip_overview.json').read_text())
        self.assertEqual(report['ip_results'][0]['status'],'READY')

    def test_scanning_unknown_delivery_order_must_not_guess(self):
        bad = self.root/'RAW'/'Supplier'/'bad_lib'
        (bad/'oct_release'/'LEF').mkdir(parents=True)
        (bad/'nov_release'/'LEF').mkdir(parents=True)
        libs, issues=discover_raw_libraries(self.root/'RAW')
        self.assertEqual([lib['library_id'] for lib in libs], ['Supplier.physical_library'])

    def test_discovery_rejects_mixed_or_unrecognized_delivery_directories(self):
        mixed = self.root / 'RAW' / 'Supplier' / 'mixed'
        (mixed / 'V01').mkdir(parents=True)
        (mixed / '20261003').mkdir()
        unknown = self.root / 'RAW' / 'Supplier' / 'unknown'
        (unknown / 'V01').mkdir(parents=True)
        (unknown / 'release_new').mkdir()
        libraries, issues = discover_raw_libraries(self.root / 'RAW')
        self.assertEqual([lib['library_id'] for lib in libraries], ['Supplier.physical_library'])
        self.assertTrue(any('mixed' in issue for issue in issues))
        self.assertTrue(any('unknown' in issue for issue in issues))


if __name__ == '__main__':
    unittest.main()
