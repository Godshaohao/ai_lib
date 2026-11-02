import unittest
from lib_guard.applicable_review import build_applicable_plan
from lib_guard.current_library_set import build_current_file_set
from lib_guard.file_version_projection import build_projection
from lib_guard.review_runner import _corner_coverage_observation


class ReviewQualityRegressions(unittest.TestCase):
    def test_chain_ignores_metadata_before_latest_full(self):
        versions = [
            {'id':'V0','path':'/raw/V0','delivery_order':0},
            {'id':'V1','path':'/raw/V1','delivery_order':1,'package_type':'FULL_PACKAGE'},
            {'id':'V2','path':'/raw/V2','delivery_order':2,'package_type':'PARTIAL_UPDATE','previous_effective_version':'V1'},
        ]
        inventories = [{'version_id':v['id'],'status':'COMPLETE','files':[v['path'] + '/LEF/core.lef']} for v in versions]
        current = build_current_file_set(versions, inventories)
        self.assertEqual(current['status'], 'COMPLETE')
        self.assertEqual(current['chain'], ['V1', 'V2'])
        self.assertEqual(current['files'][0]['source_version'], 'V2')

    def test_lef_pairs_use_each_files_latest_and_previous_occurrences(self):
        versions = [{'id':f'V{i}','path':f'/raw/V{i}','delivery_order':i} for i in range(1,5)]
        inventories = [{'version_id':f'V{i}','status':'COMPLETE','files': [f'/raw/V{i}/LEF/core.lef'] if i in (1,3) else [f'/raw/V{i}/LIB/tt.lib']} for i in range(1,5)]
        projection = build_projection('IP', versions, inventories, None)
        plan = build_applicable_plan(projection, {v['id']:v['path'] for v in versions})
        pair = plan['checks']['lef_review']['pairs'][0]
        self.assertEqual(pair['source_versions'], {'old':'V1','new':'V3'})
        self.assertEqual(pair['old_file'], '/raw/V1/LEF/core.lef')
        self.assertEqual(pair['new_file'], '/raw/V3/LEF/core.lef')

    def test_lef_pairs_skip_uncertain_previous(self):
        versions = [{'id':f'V{i}','path':f'/raw/V{i}','delivery_order':i} for i in range(1,4)]
        inventories = [{'version_id':f'V{i}','status':'PARTIAL' if i == 2 else 'COMPLETE','files': [f'/raw/V{i}/LEF/core.lef'] if i != 2 else []} for i in range(1,4)]
        plan = build_applicable_plan(build_projection('IP', versions, inventories, None), {})
        self.assertNotIn('lef_review', plan['checks'])
        row = next(row for row in plan['engineering_checklist'] if row['id'] == 'lef_delta')
        self.assertIn('不确定', row['reason'])

    def test_corner_observation_complete_without_expected_signoff_rules(self):
        review = {'checks': {'lef_liberty_check': {'selected':True, 'status':'COMPLETE', 'result': {
            'candidate_status':'COMPLETE', 'summary': {'liberty_file_count':1, 'process_corner_file_counts':{'SSG':1}},
            'observed_liberties':[{'source_path':'/raw/ssg.lib', 'corner_axes':{'process_corner':'SSG'}}]
        }}}}
        result = _corner_coverage_observation(review)
        self.assertEqual(result['execution'], '已执行')
        self.assertIn('不据此判断齐套', result['reason'])

    def test_partial_current_file_set_remains_partial_corner_observation(self):
        review = {'checks': {'lef_liberty_check': {'selected':True, 'status':'COMPLETE', 'result': {
            'candidate_status':'PARTIAL', 'summary': {'liberty_file_count':1}, 'observed_liberties':[{'source_path':'/raw/ssg.lib'}]
        }}}}
        result = _corner_coverage_observation(review)
        self.assertEqual(result['execution'], '部分覆盖')
        self.assertIn('不完整', result['reason'])

    def test_run_uses_per_file_pair_without_mislabeling_global_range(self):
        import json
        import tempfile
        from pathlib import Path
        from lib_guard.review_runner import run_review
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            versions, inventories = [], []
            for i in range(1, 5):
                version = f'V{i}'
                path = root / version
                path.mkdir()
                versions.append({'id':version, 'path':str(path), 'delivery_order':i})
                files = []
                if i in (1, 3):
                    lef = path / 'LEF' / 'core.lef'
                    lef.parent.mkdir()
                    lef.write_text(f'VERSION 5.8 ;\nMACRO CORE\n SIZE {i} BY 2 ;\nEND CORE\nEND LIBRARY\n')
                    files.append(str(lef))
                inventories.append({'version_id':version, 'status':'COMPLETE', 'files':files})
            projection = build_projection('IP', versions, inventories, None)
            projection['snapshot_id'] = 'raw1'
            plan = build_applicable_plan(projection, {v['id']:v['path'] for v in versions})
            projection_path = root / 'projection.json'
            projection_path.write_text(json.dumps(plan['projection']))
            result = run_review({'ips':[{'id':'IP', 'library_id':'IP', 'raw_version':'V4',
                'projection_json':str(projection_path), 'one_click_applicable':True,
                'checks':plan['checks']}]}, root / 'out')[0]
            check = result['checks']['lef_review']
            self.assertEqual(check['status'], 'COMPLETE', check)
            self.assertEqual(check['result']['pairs'][0]['source_versions'], {'old':'V1', 'new':'V3'})
            row = next(x for x in result['file_version_projection']['files'] if x['view'] == 'lef')
            self.assertEqual(row['comparison']['base_version'], 'V3')
            self.assertEqual(row['comparison']['target_version'], 'V4')
            self.assertEqual(row['comparison']['semantic_status'], 'NOT_CHECKED')
            self.assertEqual(row['comparison']['evidence_refs'], [])

    def test_partial_liberty_parse_does_not_mark_corner_observation_complete(self):
        from lib_guard.current_library_set import build_interface_groups
        path = '/raw/V1/LIB/tt.lib'
        file_set = {'status':'COMPLETE', 'files':[{'view':'liberty', 'source_path':path}]}
        facts = [{'status':'PASS_EMPTY', 'file_identity':{'source_path':path}, 'data':{'libraries':{}}}]
        groups = build_interface_groups(file_set, facts)
        self.assertEqual(groups['corner_observation_status'], 'PARTIAL')

    def test_corner_rows_include_unmatched_observed_liberties_once(self):
        from lib_guard.review_runner import _liberty_rows
        observed = [{'source_path':f'/raw/{name}.lib', 'library_names':[name],
                     'corner_axes':{'process_corner':name.upper()}, 'operating_conditions':{}}
                    for name in ('tt', 'ss')]
        reports = [{'liberty_source':'/raw/tt.lib', 'library_names':['tt'],
                    'corner_axes':{'process_corner':'TT'}, 'cells':[]} for _ in range(2)]
        review = {'ip':{'id':'IP'}, 'checks':{'lef_liberty_check':{'selected':True,'status':'COMPLETE',
                  'result':{'observed_liberties':observed, 'files':reports}}}}
        corners, _ = _liberty_rows(review)
        self.assertEqual([row['Liberty文件'] for row in corners], ['/raw/tt.lib', '/raw/ss.lib'])
        self.assertEqual(corners[1]['信号Pin差异'], '未确认')

    def test_lef_delta_does_not_include_files_excluded_by_current_full_package(self):
        versions = [{'id':f'V{i}', 'path':f'/raw/V{i}', 'delivery_order':i} for i in range(1, 4)]
        inventories = [{'version_id':f'V{i}', 'status':'COMPLETE', 'files':
                        [f'/raw/V{i}/LEF/old.lef'] if i < 3 else ['/raw/V3/LEF/new.lef']}
                       for i in range(1, 4)]
        projection = build_projection('IP', versions, inventories, None)
        current = {'status':'COMPLETE', 'files':[{'view':'lef', 'source_path':'/raw/V3/LEF/new.lef'}]}
        plan = build_applicable_plan(projection, {}, current_file_set=current)
        self.assertNotIn('lef_review', plan['checks'])

    def test_partial_current_set_marks_unresolved_historical_lef_as_uncertain(self):
        versions = [{'id':f'V{i}', 'path':f'/raw/V{i}', 'delivery_order':i} for i in range(1, 4)]
        inventories = [{'version_id':f'V{i}', 'status':'COMPLETE', 'files':
                        [f'/raw/V{i}/LEF/core.lef'] if i < 3 else []} for i in range(1, 4)]
        projection = build_projection('IP', versions, inventories, None)
        plan = build_applicable_plan(projection, {}, current_file_set={'status':'PARTIAL', 'files':[]})
        self.assertNotIn('lef_review', plan['checks'])
        row = next(row for row in plan['engineering_checklist'] if row['id'] == 'lef_delta')
        self.assertEqual(row['execution'], '部分覆盖')
        self.assertIn('不确定', row['reason'])
