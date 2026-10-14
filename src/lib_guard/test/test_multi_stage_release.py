from __future__ import annotations

import json
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from lib_guard.effective.pointer import write_current_pointer


class MultiStageReleaseTest(unittest.TestCase):
    def test_collisions_skip_all_candidates_but_publish_other_libraries_files(self):
        from lib_guard.release.postcheck import verify_release_manifest
        from lib_guard.web.app import _release_plan_projection
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for name in ('A', 'B'):
                self.effective(root, name, 'top.lef')
                path = root / 'html/libraries' / f'ip_{name}' / 'effective/E1/effective_manifest.json'
                manifest = json.loads(path.read_text())
                source = root / 'raw' / name / f'{name}.lef'
                source.write_text(name)
                manifest['effective_files'][f'lef/{name}.lef'] = {'source_abs': str(source), 'file_type': 'lef'}
                path.write_text(json.dumps(manifest))
                write_current_pointer(path, accepted_by='test_owner', note='confirmed')
            preview = self.publish(root, apply=False)
            self.assertEqual(preview['status'], 'PARTIAL_DRY_RUN')
            self.assertFalse((root / 'published/latest').exists())
            result = self.publish(root, apply=True)
            self.assertEqual(result['status'], 'PARTIAL_APPLIED')
            directory = root / 'published/lib_NL2.1.0'
            self.assertFalse((directory / 'LEF/top.lef').exists())
            for name in ('A', 'B'):
                self.assertEqual((directory / f'LEF/{name}.lef').resolve(), root / 'raw' / name / f'{name}.lef')
            self.assertEqual((root / 'published/latest').resolve(), directory)
            link = result['link_result']
            self.assertEqual(link['summary']['skipped_files'], 2)
            self.assertEqual(link['summary']['created_files'], 2)
            delivered = json.loads((directory / 'release_manifest.json').read_text())
            self.assertEqual(len(delivered['files']), 2)
            self.assertEqual(len(delivered['skipped_files']), 2)
            self.assertEqual(delivered['delivery_status'], 'PARTIAL_APPLIED')
            self.assertEqual(verify_release_manifest(directory / 'release_manifest.json')['status'], 'PASS_WITH_WARNING')
            projection = _release_plan_projection(result, {'action': 'release-set-apply'})
            self.assertEqual(projection['scope'], 'release_set')
            self.assertEqual(projection['skipped_files'], 2)
            self.assertEqual(len(projection['link_rows']), 4)
            self.assertTrue(any('同名' in item['message'] for item in projection['issues']))
            from lib_guard.release.library_index import build_release_library_index
            from lib_guard.web.read_model import release_stage_detail
            index = root / 'index.json'
            indexed = build_release_library_index(root / 'published')
            self.assertEqual(indexed['stages'][0]['skipped_count'], 2)
            index.write_text(json.dumps(indexed))
            state = {'config': {'release_library_index': str(index)}, 'catalog': {'libraries': []}}
            stage = release_stage_detail(state, 'lib_NL2.1.0')['stage']
            self.assertEqual(stage['delivery_status'], 'PARTIAL_APPLIED')
            self.assertEqual(stage['skipped_count'], 2)
            second = self.publish(root, apply=True)
            backup = Path(second['link_result']['daily_backup'])
            self.assertTrue((backup / 'LEF/A.lef').is_symlink())
            self.assertEqual(json.loads((backup / 'release_manifest.json').read_text())['delivery_status'], 'PARTIAL_APPLIED')
            original = (directory / 'release_manifest.json').read_bytes()
            backup_original = (backup / 'release_manifest.json').read_bytes()
            calls = 0
            def reject_final_check(*args, **kwargs):
                nonlocal calls
                calls += 1
                return {'status': 'FAILED', 'issues': []} if calls == 2 else verify_release_manifest(*args, **kwargs)
            with patch('lib_guard.release.postcheck.verify_release_manifest', side_effect=reject_final_check):
                rejected = self.publish(root, apply=True)
            self.assertEqual(rejected['status'], 'FAILED')
            self.assertEqual((directory / 'release_manifest.json').read_bytes(), original)
            self.assertEqual((backup / 'release_manifest.json').read_bytes(), backup_original)
            self.assertEqual((root / 'published/latest').resolve(), directory)

    def test_missing_unique_source_aborts_partial_overwrite_and_preserves_delivery(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self.effective(root, 'A', 'a.lef')
            self.effective(root, 'B', 'b.lef')
            self.publish(root, apply=True)
            original = (root / 'published/lib_NL2.1.0/release_manifest.json').read_bytes()
            for name in ('A', 'B'):
                self.effective(root, name, 'top.lef')
            path = root / 'html/libraries/ip_A/effective/E1/effective_manifest.json'
            manifest = json.loads(path.read_text())
            manifest['effective_files']['lef/missing.lef'] = {
                'source_abs': str(root / 'raw/A/missing.lef'), 'file_type': 'lef'}
            path.write_text(json.dumps(manifest))
            write_current_pointer(path, accepted_by='test_owner', note='confirmed')
            result = self.publish(root, apply=True)
            self.assertEqual(result['status'], 'FAILED')
            self.assertEqual((root / 'published/lib_NL2.1.0/release_manifest.json').read_bytes(), original)
            self.assertTrue((root / 'published/latest/LEF/a.lef').is_file())

    def test_delivery_inventory_groups_views_and_recorded_corners(self):
        from lib_guard.web.read_model import release_stage_detail
        from lib_guard.release.library_index import build_release_library_index
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self.effective(root, 'A', 'a.lef')
            self.effective(root, 'B', 'b.lef')
            self.publish(root, apply=True)
            index = root / 'index.json'
            index.write_text(json.dumps(build_release_library_index(root / 'published')))
            state = {'config': {'release_library_index': str(index)}, 'catalog': {'libraries': []}}
            path = root / 'published/lib_NL2.1.0/release_manifest.json'
            manifest = json.loads(path.read_text())
            self.assertEqual(manifest['files'][0]['delivery_action'], 'LINK')
            manifest['files'][0]['corner'] = 'ss_0p72v_125c'
            manifest['files'][0]['source_version'] = 'full'
            path.write_text(json.dumps(manifest))
            result = release_stage_detail(state, 'lib_NL2.1.0', library='ip/B')
            inventory = result['inventory']
            self.assertEqual(inventory[0]['file_count'], 1)
            self.assertEqual(inventory[0]['views'], [{'view': 'LEF', 'count': 1}])
            self.assertEqual(inventory[0]['corners'], ['ss_0p72v_125c'])
            self.assertEqual(inventory[1]['corner_unrecorded'], 1)
            self.assertEqual(result['view_inventory'][0]['file_count'], 2)
            self.assertEqual(result['total'], 1)
            self.assertEqual(inventory[0]['delivery_actions'], {'LINK': 1})

    def test_delivery_metadata_is_live_even_when_index_is_stale(self):
        from lib_guard.web.read_model import release_stage_detail
        from lib_guard.release.library_index import build_release_library_index
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self.effective(root, 'A', 'a.lef')
            self.effective(root, 'B', 'b.lef')
            self.publish(root, apply=True)
            index = root / 'index.json'
            index.write_text(json.dumps(build_release_library_index(root / 'published')))
            state = {'config': {'release_library_index': str(index)}, 'catalog': {'libraries': []}}
            path = root / 'published/lib_NL2.1.0/release_manifest.json'
            manifest = json.loads(path.read_text())
            manifest['files'] = manifest['files'][:1]
            manifest['release_components'] = manifest['release_components'][:1]
            manifest['release_components'][0]['version_id'] = 'E2'
            path.write_text(json.dumps(manifest))
            (root / 'published/latest').unlink()
            result = release_stage_detail(state, 'lib_NL2.1.0')
            self.assertEqual(result['stage']['file_count'], 1)
            self.assertEqual(result['stage']['library_count'], 1)
            self.assertEqual(result['stage']['libraries'][0]['version_id'], 'E2')
            self.assertFalse(result['stage']['is_latest'])
            page = release_stage_detail(state, 'lib_NL2.1.0', offset=100)
            self.assertEqual(page['offset'], 0)
            self.assertEqual(len(page['files']), 1)
            for invalid in ([], {'files': [None]}, {'files': {}, 'release_components': []}):
                path.write_text(json.dumps(invalid))
                with self.assertRaisesRegex(ValueError, '清单'):
                    release_stage_detail(state, 'lib_NL2.1.0')

    def test_published_detail_uses_delivery_not_current_effective_or_catalog(self):
        from lib_guard.web.read_model import release_stage_detail
        from lib_guard.release.library_index import build_release_library_index
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self.effective(root, 'A', 'a.lef')
            self.effective(root, 'B', 'b.lef')
            self.publish(root, apply=True)
            index = root / 'index.json'
            index.write_text(json.dumps(build_release_library_index(root / 'published')))
            state = {'config': {'release_library_index': str(index)}, 'catalog': {'libraries': []}}
            result = release_stage_detail(state, 'lib_NL2.1.0', limit=1)
            self.assertEqual(result['total'], 2)
            self.assertTrue(result['has_more'])
            self.assertEqual(result['check']['checked_count'], 1)
            self.assertEqual(result['check']['scope_count'], 2)
            self.assertFalse(result['check']['complete'])
            self.assertEqual(result['check']['abnormal_count'], 0)
            self.assertEqual(result['files'][0]['link_status'], 'READY')
            filtered = release_stage_detail(state, 'lib_NL2.1.0', query='b.lef')
            self.assertEqual(filtered['total'], 1)
            self.assertEqual(filtered['files'][0]['target_relpath'], 'LEF/b.lef')
            from lib_guard.web.app import create_app
            config = root / 'lib_guard.yml'
            config.write_text(f'workspace: {root}\nrelease_root: {root}/published\nrelease_library_index: {index}\n')
            client = create_app(config_path=config, test_config={'TESTING': True}).test_client()
            response = client.get('/api/release-stages/lib_NL2.1.0/files?library=ip/B')
            self.assertEqual(response.status_code, 200, response.get_json())
            self.assertEqual(response.get_json()['total'], 1)
            self.assertEqual(client.get('/api/release-stages/nonexistent/files').status_code, 400)
            self.assertFalse((root / 'web_jobs').exists(), 'Reading a delivery must not start jobs')
            only_b = release_stage_detail(state, 'lib_NL2.1.0', library='ip/B')
            self.assertEqual(only_b['total'], 1)
            target = root / 'published/lib_NL2.1.0/LEF/b.lef'
            target.unlink()
            target.symlink_to(root / 'raw/A/a.lef')
            self.assertEqual(release_stage_detail(state, 'lib_NL2.1.0', library='ip/B')['files'][0]['link_status'], 'MISMATCH')
            anomalies = release_stage_detail(state, 'lib_NL2.1.0', view='LEF', link_status='abnormal')
            self.assertEqual(anomalies['total'], 1)
            self.assertTrue(anomalies['check']['complete'])
            self.assertEqual(anomalies['check']['abnormal_count'], 1)
            self.assertEqual(anomalies['files'][0]['library_id'], 'ip/B')
            response = client.get('/api/release-stages/lib_NL2.1.0/files?view=LEF&link_status=abnormal')
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.get_json()['total'], 1)
            self.assertEqual(release_stage_detail(state, 'lib_NL2.1.0', view='GDS')['total'], 0)
            self.assertEqual(release_stage_detail(state, 'lib_NL2.1.0')['views'], ['LEF'])
            target.unlink()
            self.assertEqual(release_stage_detail(state, 'lib_NL2.1.0', library='ip/B')['files'][0]['link_status'], 'MISSING')
            target.write_text('copied file')
            manifest_path = root / 'published/lib_NL2.1.0/release_manifest.json'
            manifest = json.loads(manifest_path.read_text())
            manifest['link_mode'] = 'copy'
            manifest_path.write_text(json.dumps(manifest))
            self.assertEqual(release_stage_detail(state, 'lib_NL2.1.0', library='ip/B')['files'][0]['link_status'], 'COPIED')
            manifest['files'] = manifest['files'] * 150
            manifest_path.write_text(json.dumps(manifest))
            original_is_file = Path.is_file
            checked = []
            def is_file(path):
                if path.parent.name == 'LEF':
                    checked.append(path)
                return original_is_file(path)
            with patch.object(Path, 'is_file', is_file):
                page = release_stage_detail(state, 'lib_NL2.1.0', limit=999)
            self.assertEqual(len(checked), 100, 'Ordinary paging must not check every delivery file')
            self.assertEqual(len(page['files']), 100)
            self.assertTrue(page['has_more'])
            manifest['files'][0]['target_relpath'] = '../escape'
            manifest_path.write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, '越界'):
                release_stage_detail(state, 'lib_NL2.1.0')
            with self.assertRaisesRegex(ValueError, '阶段'):
                release_stage_detail(state, '../escape')

    def effective(self, root: Path, name: str, filename: str, content: str = 'old') -> None:
        source = root / 'raw' / name / filename
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text(content)
        directory = root / 'html' / 'libraries' / f'ip_{name}' / 'effective' / 'E1'
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / 'effective_manifest.json'
        path.write_text(json.dumps({
            'library_id': f'ip/{name}', 'library_type': 'ip', 'library_name': name,
            'effective_id': 'E1', 'base_full_version': 'full', 'accepted_updates': [],
            'effective_files': {f'lef/{filename}': {'source_abs': str(source), 'file_type': 'lef'}},
        }))
        write_current_pointer(path, accepted_by='test_owner', note='isolated acceptance')

    def publish(self, root: Path, *, apply: bool):
        from lib_guard.release.set_publish import publish_release_set
        return publish_release_set(root / 'html', ['ip/A', 'ip/B'], root / 'published',
                                   publish_name='lib_NL2.1.0', latest_name='latest',
                                   out_dir=root / 'run', apply=apply)

    def test_preview_apply_and_same_stage_overwrite(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self.effective(root, 'A', 'a.lef')
            self.effective(root, 'B', 'b.lef')
            preview = self.publish(root, apply=False)
            self.assertTrue(preview['dry_run'])
            self.assertFalse((root / 'published/lib_NL2.1.0').exists())
            result = self.publish(root, apply=True)
            self.assertEqual(result['link_status'], 'APPLIED')
            self.assertEqual(result['verify_status'], 'PASS')
            self.assertTrue((root / 'published/lib_NL2.1.0/LEF/a.lef').is_symlink())
            self.assertEqual((root / 'published/latest').resolve(), root / 'published/lib_NL2.1.0')
            self.publish(root, apply=True)
            self.assertTrue(Path(result['link_result']['release_dir']).exists())
            self.assertEqual(len(list((root / 'published/history').iterdir())), 1)
            from lib_guard.release.library_index import build_release_library_index
            index = build_release_library_index(root / 'published')
            self.assertEqual(len(index['stages']), 1)
            self.assertEqual(index['stages'][0]['library_count'], 2)

    def test_collision_and_missing_current_never_replace_release(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self.effective(root, 'A', 'top.lef')
            self.effective(root, 'B', 'top.lef')
            result = self.publish(root, apply=True)
            self.assertNotEqual(result['link_status'], 'APPLIED')
            self.assertFalse((root / 'published/latest').exists())
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self.effective(root, 'A', 'a.lef')
            with self.assertRaisesRegex(ValueError, '有效'):
                self.publish(root, apply=True)

    def test_different_stages_are_retained_and_collision_preserves_latest(self):
        from lib_guard.release.set_publish import publish_release_set
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self.effective(root, 'A', 'a.lef')
            self.effective(root, 'B', 'b.lef')
            self.publish(root, apply=True)
            result = publish_release_set(root / 'html', ['ip/A', 'ip/B'], root / 'published',
                                         publish_name='lib_NL2.2.0', latest_name='latest',
                                         out_dir=root / 'run2', apply=True)
            self.assertEqual(result['verify_status'], 'PASS')
            self.assertTrue((root / 'published/lib_NL2.1.0/LEF/a.lef').is_file())
            self.assertEqual((root / 'published/latest').resolve(), root / 'published/lib_NL2.2.0')
            self.effective(root, 'B', 'a.lef')
            result = self.publish(root, apply=True)
            self.assertNotEqual(result['link_status'], 'APPLIED')
            self.assertEqual((root / 'published/latest').resolve(), root / 'published/lib_NL2.2.0')
            self.assertTrue((root / 'published/lib_NL2.1.0/LEF/b.lef').is_file())
