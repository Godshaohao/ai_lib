import json
import hashlib
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from argparse import Namespace
from pathlib import Path

from lib_guard.diff.file_diff import diff_pairwise_files
from lib_guard.test.semantic_fixture import SemanticFixture, write_json


def record_pair_snapshots(root, old, new, diff_dir):
    scans = []
    for name, source in (('old', old), ('new', new)):
        scan = root / 'scan' / name
        stamp = source.stat()
        raw = root / 'raw' / ('v1' if name == 'old' else 'v2')
        write_json(scan / 'file_inventory.json', {'root_path': str(raw), 'files': [{
            'path': source.relative_to(raw).as_posix(), 'file_type': 'lef', 'size_bytes': stamp.st_size,
            'mtime_ns': stamp.st_mtime_ns, 'sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
        }]})
        scans.append(scan)
    write_json(diff_dir / 'diff_meta.json', {'old_scan': str(scans[0]), 'new_scan': str(scans[1])})
    return {'scan_dir': str(scans[1])}


class ReviewPublicationTest(unittest.TestCase):
    def test_pairwise_result_records_absolute_source_paths(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            old, new = root / 'old.v', root / 'new.v'
            old.write_text('module a; endmodule\n')
            new.write_text('module a; endmodule\n')
            diff_pairwise_files('verilog', os.path.relpath(old), os.path.relpath(new), root / 'out')
            pair = json.loads((root / 'out/pairwise_result.json').read_text())
            self.assertEqual(pair['old_file'], str(old))
            self.assertEqual(pair['new_file'], str(new))

    def test_late_old_file_job_keeps_newer_selection_and_same_pair_history(self):
        from lib_guard.review.publication import publish_file_diff, load_current_file_checks
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for version in ('v1', 'v2'):
                (root / 'raw' / version).mkdir(parents=True)
            old, new = root / 'raw/v1/a.v', root / 'raw/v2/a.v'
            old.write_text('module a(input x); endmodule\n')
            new.write_text('module a(input y); endmodule\n')
            catalog = root / 'catalog/catalog.json'
            write_json(catalog, {'libraries': [{'library_id': 'ip/demo', 'versions': [
                {'version_id': 'v1', 'raw_path': str(old.parent)},
                {'version_id': 'v2', 'raw_path': str(new.parent)}]}]})
            first, second = root / 'first', root / 'second'
            diff_pairwise_files('verilog', old, new, first)
            diff_pairwise_files('verilog', old, new, second)
            newer = publish_file_diff(catalog, root / 'catalog/html', 'ip/demo', 'v2', second,
                                      started_epoch=20)
            publish_file_diff(catalog, root / 'catalog/html', 'ip/demo', 'v2', first,
                              started_epoch=10)
            rows = json.loads((root / 'review_notes/ip_demo/v2/representative_files.json').read_text())['files']
            self.assertEqual(len(rows), 2)
            self.assertEqual(load_current_file_checks(root / 'review_notes', 'ip/demo', 'v2')[0]['evidence_id'],
                             newer['evidence_id'])

    def test_cli_file_diff_publishes_with_catalog_context(self):
        from lib_guard.cli_commands.diff import run_file_diff
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            old, new = root / 'raw/v1/a.v', root / 'raw/v2/a.v'
            for path in (old, new):
                path.parent.mkdir(parents=True)
                path.write_text('module a; endmodule\n')
            catalog = root / 'catalog/catalog.json'
            write_json(catalog, {'libraries': [{'library_id': 'ip/demo', 'library_name': 'demo', 'versions': [
                {'version_id': 'v1', 'raw_path': str(old.parent)},
                {'version_id': 'v2', 'raw_path': str(new.parent)},
            ]}]})
            args = Namespace(file_type='verilog', old=str(old), new=str(new), out=str(root / 'diff'),
                             task_id=None, library_id='ip/demo', version_id='v2', base_version='v1',
                             catalog=str(catalog), catalog_html_out=str(root / 'catalog/html'))
            self.assertEqual(run_file_diff(args), 0)
            self.assertEqual(len(json.loads((root / 'review_notes/ip_demo/v2/representative_files.json').read_text())['files']), 1)

    def test_web_result_sync_skips_arbitrary_pair(self):
        from lib_guard.review.publication import sync_operator_result
        request = {'action': 'file-diff', 'library': 'ip/demo', 'version': 'v2',
                   'payload': {'old_file': '/tmp/old.v', 'new_file': '/tmp/new.v'}}
        self.assertEqual(sync_operator_result(request, {'status': 'SAME'}, '/tmp/catalog.json',
                                              '/tmp/catalog/html', '/tmp/job')['status'], 'SKIPPED')

    def test_reader_does_not_call_hash_confirmed_same_lef_modified(self):
        from lib_guard.review.publication import publish_file_diff
        from lib_guard.render.version_detail_report import build_version_update_detail_model
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            old, new = root / 'raw/v1/lef/a.lef', root / 'raw/v2/lef/a.lef'
            for path in (old, new):
                path.parent.mkdir(parents=True)
                path.write_text('VERSION 5.8 ;\nMACRO a\n SIZE 1 BY 1 ;\nEND a\n')
            diff_dir = root / 'diff'
            write_json(diff_dir / 'diff_summary.json', {'status': 'DIFF', 'changed_files': 1})
            write_json(diff_dir / 'file_diff.json', {'changed': ['lef/a.lef']})
            lib = {'library_id': 'ip/demo', 'library_name': 'demo'}
            version = {'version_id': 'v2', 'raw_path': str(new.parent.parent),
                       'diff': {'base_version': 'v1', 'base_source': 'explicit', 'base_diff_dir': str(diff_dir)}}
            catalog = root / 'catalog/catalog.json'
            lib['versions'] = [{'version_id': 'v1', 'raw_path': str(old.parent.parent)}, version]
            version['scan'] = record_pair_snapshots(root, old, new, diff_dir)
            write_json(catalog, {'libraries': [lib]})
            out = root / 'pair'
            diff_pairwise_files('lef', old, new, out)
            publish_file_diff(catalog, root / 'catalog/html', 'ip/demo', 'v2', out)
            model = build_version_update_detail_model(root / 'catalog/html', lib, version)
            self.assertEqual(model['ip_user_view_model']['comparison']['visible_counts']['changed'], 0)
            self.assertIn('lef/a.lef', str(model['evidence_conflicts']))
            lef_row = next(row for row in model['ip_user_view_model']['view_rows'] if row['view_type'] == 'physical_abstract')
            self.assertEqual(lef_row['changed'], 0)
            self.assertEqual(lef_row['unmatched_new'], 0)
            self.assertEqual(model['confirmed_unchanged_files'], ['lef/a.lef'])
            page = next((root / 'catalog/html/libraries').glob('*/versions/v2/index.html'))
            html = page.read_text()
            self.assertIn('data-section="reader-summary"', html)
            self.assertIn('文件内容未变化', html)
            self.assertIn('正式放行', html)

    def test_same_lef_with_different_package_prefix_reconciles_logical_change(self):
        from lib_guard.review.publication import publish_file_diff
        from lib_guard.render.version_detail_report import build_version_update_detail_model
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            old = root / 'raw/v1/asap7_source_package/lef/a.lef'
            new = root / 'raw/v2/upstream_abc/lef/a.lef'
            for path in (old, new):
                path.parent.mkdir(parents=True)
                path.write_text('VERSION 5.8 ;\nMACRO a\n SIZE 1 BY 1 ;\nEND a\n')
            diff_dir = root / 'diff'
            write_json(diff_dir / 'diff_summary.json', {'status': 'DIFF', 'changed_files': 1})
            write_json(diff_dir / 'file_diff.json', {
                'changed': ['lef/a.lef'],
                'logical_path_changes': [{'logical_path': 'lef/a.lef',
                                          'old': 'asap7_source_package/lef/a.lef',
                                          'new': 'upstream_abc/lef/a.lef'}],
            })
            catalog = root / 'catalog/catalog.json'
            version = {'version_id': 'v2', 'raw_path': str(root / 'raw/v2'),
                       'diff': {'base_version': 'v1', 'base_diff_dir': str(diff_dir)}}
            lib = {'library_id': 'ip/demo', 'library_name': 'demo', 'versions': [
                {'version_id': 'v1', 'raw_path': str(root / 'raw/v1')}, version]}
            version['scan'] = record_pair_snapshots(root, old, new, diff_dir)
            write_json(catalog, {'libraries': [lib]})
            out = root / 'pair'
            diff_pairwise_files('lef', old, new, out)
            publish_file_diff(catalog, root / 'catalog/html', 'ip/demo', 'v2', out)
            model = build_version_update_detail_model(root / 'catalog/html', lib, version)
            self.assertEqual(model['changed_files'], 0)
            self.assertEqual(model['evidence_conflicts'], ['lef/a.lef'])

    def test_file_diff_requires_catalog_ownership_and_keeps_one_current_pair_per_type(self):
        from lib_guard.review.publication import publish_file_diff, load_current_file_checks

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            versions = []
            for name in ('v1', 'v2'):
                raw = root / 'raw' / name
                raw.mkdir(parents=True)
                versions.append({'version_id': name, 'raw_path': str(raw)})
            catalog = root / 'catalog.json'
            write_json(catalog, {'libraries': [{'library_id': 'ip/demo', 'library_name': 'demo', 'versions': versions}]})
            for index in (1, 2):
                old = root / 'raw/v1' / f'{index}.v'
                new = root / 'raw/v2' / f'{index}.v'
                old.write_text('module m(input a); endmodule\n')
                new.write_text('module m(input b); endmodule\n')
                out = root / f'diff{index}'
                diff_pairwise_files('verilog', old, new, out)
                publish_file_diff(catalog, root / 'catalog/html', 'ip/demo', 'v2', out)
            rows = load_current_file_checks(root / 'review_notes', 'ip/demo', 'v2')
            self.assertEqual(len(rows), 1)
            self.assertEqual(Path(rows[0]['new_file']).name, '2.v')
            self.assertEqual(len(json.loads((root / 'review_notes/ip_demo/v2/representative_files.json').read_text())['files']), 2)
            page = next((root / 'catalog/html/libraries').glob('*/versions/v2/index.html'))
            self.assertIn('已加入 1 对文件', page.read_text())
            outside = root / 'outside.v'
            outside.write_text('module outside; endmodule\n')
            out = root / 'outside-diff'
            diff_pairwise_files('verilog', outside, versions[1]['raw_path'] + '/2.v', out)
            with self.assertRaises(ValueError):
                publish_file_diff(catalog, root / 'catalog/html', 'ip/demo', 'v2', out)

    def test_semantic_result_projects_to_last_overlay_and_survives_source_job_removal(self):
        from lib_guard.review.publication import publish_semantic_review, load_semantic_projection
        from lib_guard.semantic.runner import run_semantic_review

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            fixture = SemanticFixture(root)
            fixture.version('full')
            fixture.version('fix', views=('lef',), width=1100)
            catalog = root / 'catalog/catalog.json'
            write_json(catalog, fixture.catalog)
            manifest = root / 'effective.json'
            write_json(manifest, fixture.manifest([('fix', ['lef'])]))
            out = root / 'job/semantic'
            run_semantic_review(manifest, catalog, out)
            published = publish_semantic_review(catalog, root / 'catalog/html', manifest, out)
            self.assertEqual(published['version'], 'fix')
            self.assertEqual(published['components'], ['full', 'fix'])
            projection = load_semantic_projection(root / 'review_notes', 'ip/demo', 'fix')
            self.assertEqual(projection['status'], 'CURRENT')
            self.assertTrue(projection['advisory'])
            self.assertEqual(projection['components'], ['full', 'fix'])
            self.assertTrue(Path(projection['details_path']).is_file())
            page = next((root / 'catalog/html/libraries').glob('*/versions/fix/index.html'))
            page_text = page.read_text()
            self.assertIn('跨视图技术检查', page_text)
            self.assertIn('full → fix', page_text)
            self.assertIn('不代表正式放行', page_text)
            (out / 'summary.json').unlink()
            manifest.unlink()
            self.assertEqual(load_semantic_projection(root / 'review_notes', 'ip/demo', 'fix')['status'], 'CURRENT')
            (root / 'raw/fix/lef/M.lef').write_text('changed')
            self.assertEqual(load_semantic_projection(root / 'review_notes', 'ip/demo', 'fix')['status'], 'STALE')
            index_path = root / 'review_notes/ip_demo/fix/semantic_review.json'
            index_data = json.loads(index_path.read_text())
            saved_row = next(iter(index_data['results'].values()))
            saved_row['markdown_path'] = str(root / 'outside.txt')
            (root / 'outside.txt').write_text('not a report')
            index_path.write_text(json.dumps(index_data))
            self.assertEqual(load_semantic_projection(root / 'review_notes', 'ip/demo', 'fix')['status'], 'INVALID')

    def test_semantic_config_change_is_stale_and_older_completion_does_not_replace_newer(self):
        from lib_guard.review.publication import publish_semantic_review, load_semantic_projection
        from lib_guard.semantic.runner import run_semantic_review
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            fixture = SemanticFixture(root)
            fixture.version('full')
            catalog, manifest = root / 'catalog/catalog.json', root / 'effective.json'
            write_json(catalog, fixture.catalog)
            write_json(manifest, fixture.manifest())
            config = root / 'policy.json'
            config.write_text('{"policy":1}')
            first = root / 'first'
            run_semantic_review(manifest, catalog, first)
            newer = publish_semantic_review(catalog, root / 'catalog/html', manifest, first,
                                            profile_config_path=config, started_epoch=20)
            publish_semantic_review(catalog, root / 'catalog/html', manifest, first,
                                    profile_config_path=config, started_epoch=10)
            current = load_semantic_projection(root / 'review_notes', 'ip/demo', 'full')
            self.assertEqual(current['started_epoch'], 20)
            self.assertEqual(current['generation'], newer['generation'])
            config.write_text('{"policy":2}')
            self.assertEqual(load_semantic_projection(root / 'review_notes', 'ip/demo', 'full')['status'], 'STALE')

    def test_missing_effective_source_is_recorded_not_a_publish_error(self):
        from lib_guard.review.publication import _source_stamps
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            manifest = {'effective_files': {'lef/a.lef': {'raw_root': str(root), 'source_path': 'lef/a.lef'}}}
            self.assertEqual(_source_stamps(manifest)[str((root / 'lef/a.lef').resolve())], {'missing': True})

    def test_semantic_cli_publishes_to_explicit_report_root(self):
        from lib_guard.semantic.cli import main
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            fixture = SemanticFixture(root)
            fixture.version('full')
            catalog = root / 'catalog/catalog.json'
            manifest = root / 'effective.json'
            write_json(catalog, fixture.catalog)
            write_json(manifest, fixture.manifest())
            with redirect_stdout(StringIO()):
                code = main(['--effective-manifest', str(manifest), '--catalog', str(catalog),
                             '--out', str(root / 'semantic'), '--catalog-html-out', str(root / 'catalog/html')])
            self.assertEqual(code, 0)
            self.assertTrue((root / 'review_notes/ip_demo/full/semantic_review.json').is_file())


if __name__ == '__main__':
    unittest.main()
