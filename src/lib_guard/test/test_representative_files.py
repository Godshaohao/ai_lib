import json
import shutil
import tempfile
import unittest
from pathlib import Path

from lib_guard.diff.file_diff import diff_pairwise_files


class RepresentativeFilesTest(unittest.TestCase):
    def test_save_replace_stale_and_reconstruct(self):
        from lib_guard.review.representative_files import save_representative_file, load_representative_files
        from lib_guard.render.version_file_checks import render_file_checks
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            old, new = root / 'old.v', root / 'renamed.v'
            old.write_text('module top(input a); endmodule')
            new.write_text('module top(input a, output b); endmodule')
            out = root / 'job' / 'out'
            diff_pairwise_files('verilog', old, new, out)
            saved = save_representative_file(root / 'notes', 'A', 'v2', out, note='<manual>', updated_by='tester')
            self.assertEqual(saved['file_type'], 'verilog')
            self.assertEqual(saved['freshness'], '文件状态未改变')
            save_representative_file(root / 'notes', 'A', 'v2', out, note='updated', updated_by='tester')
            rows = load_representative_files(root / 'notes', 'A', 'v2')
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]['note'], 'updated')
            shutil.rmtree(root / 'job')
            page = root / 'html' / 'index.html'
            html = render_file_checks(rows, {}, page)
            self.assertIn('代表文件深度核查', html)
            self.assertTrue((page.parent / 'representative' / 'verilog' / rows[0]['evidence_id'] / 'index.html').is_file())
            new.write_text('module changed; endmodule')
            self.assertEqual(load_representative_files(root / 'notes', 'A', 'v2')[0]['freshness'], '源文件已变化，需重新核查')

    def test_reject_failed_result_and_preserve_existing(self):
        from lib_guard.review.representative_files import save_representative_file
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / 'out'
            out.mkdir()
            (out / 'pairwise_result.json').write_text(json.dumps({'file_type': 'lef', 'status': 'FAILED', 'result': 'FAILED'}))
            with self.assertRaises(ValueError):
                save_representative_file(Path(td) / 'notes', 'A', 'v2', out)

    def test_types_are_independent_and_notes_are_escaped(self):
        from lib_guard.review.representative_files import save_representative_file, load_representative_files
        from lib_guard.render.version_file_checks import render_file_checks
        samples = {
            'lef': 'VERSION 5.8 ;\nMACRO top\n SIZE 1 BY 2 ;\n PIN A\n DIRECTION INPUT ;\n END A\nEND top\n',
            'liberty': 'library(top) {\n cell(top) {\n pin(A) {\n direction : input;\n }\n }\n}\n',
            'verilog': 'module top(input a); endmodule\n',
            'cdl': '.SUBCKT top A B\n.ENDS top\n',
        }
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for kind, text in samples.items():
                old, new = root / ('old.' + kind), root / ('renamed.' + kind)
                old.write_text(text)
                new.write_text(text)
                out = root / kind
                diff_pairwise_files(kind, old, new, out)
                save_representative_file(root / 'notes', 'A', 'v2', out, note='<script>bad</script>')
            rows = load_representative_files(root / 'notes', 'A', 'v2')
            self.assertEqual({row['file_type'] for row in rows}, set(samples))
            html = render_file_checks(rows, {}, root / 'html/index.html')
            self.assertNotIn('<script>bad</script>', html)
            self.assertIn('&lt;script&gt;', html)
            self.assertIn('原始路径', html)
            self.assertIn('复制新文件路径', html)
            self.assertIn('LEF', html)
            self.assertIn('代表文件深度核查', html)
            self.assertIn('class="check-source-name"', html)

    def test_web_attach_validates_scope_and_refreshes_only_selected_page(self):
        from lib_guard.web.app import create_app
        with tempfile.TemporaryDirectory() as td:
            workspace = Path(td)
            raw = workspace / 'raw'
            raw.mkdir()
            old, new = raw / 'old.v', raw / 'new.v'
            old.write_text('module top(input a); endmodule')
            new.write_text('module top(input a); endmodule')
            catalog = workspace / 'catalog/catalog.json'
            catalog.parent.mkdir()
            catalog.write_text(json.dumps({'libraries': [{'library_name': 'A', 'library_id': 'ip/A', 'library_type': 'ip', 'versions': [{'version_id': 'v2', 'raw_path': str(raw)}]}]}))
            config = workspace / 'lib_guard.yml'
            config.write_text(f'workspace: {workspace}\nraw_root: {raw}\ncatalog: {catalog}\ncatalog_html: {workspace / "reports/site"}\n')
            out = workspace / 'file_diff/pair'
            result = diff_pairwise_files('verilog', old, new, out)
            job = workspace / 'web_jobs/file-diff_test'
            job.mkdir(parents=True)
            job_request = {'action': 'file-diff', 'library': 'A', 'version': 'v2'}
            (job / 'request.json').write_text(json.dumps(job_request))
            (job / 'result.json').write_text(json.dumps({'exit_code': 0, 'result': 'ok', 'cli_result': result}))
            client = create_app(config_path=config, cwd=workspace, test_config={'TESTING': True}).test_client()
            response = client.post('/api/libraries/A/versions/v2/representative-files', json={'job_id': job.name, 'note': '人工核查'})
            self.assertEqual(response.status_code, 200, response.get_json())
            self.assertEqual(response.get_json()['render']['status'], 'PASS', response.get_json())
            page = Path(response.get_json()['render']['version_detail_html'])
            self.assertIn('人工核查', page.read_text())
            foreign = workspace / 'other_library.v'
            foreign.write_text('module other(input x); endmodule')
            foreign_result = diff_pairwise_files('verilog', old, foreign, workspace / 'file_diff/foreign')
            (job / 'result.json').write_text(json.dumps({'exit_code': 0, 'result': 'ok', 'cli_result': foreign_result}))
            foreign_response = client.post('/api/libraries/A/versions/v2/representative-files', json={'job_id': job.name})
            self.assertEqual(foreign_response.status_code, 400)
            self.assertIn('不属于当前版本', foreign_response.get_json()['error'])
            (job / 'result.json').write_text(json.dumps({'exit_code': 0, 'result': 'ok', 'cli_result': result}))
            (out / 'pairwise_result.json').write_text(json.dumps({'status': 'DONE', 'result': 'SAME', 'generated_at': 'overwritten'}))
            stale = client.post('/api/libraries/A/versions/v2/representative-files', json={'job_id': job.name})
            self.assertEqual(stale.status_code, 400)
            self.assertIn('替换', stale.get_json()['error'])
            job_request['library'] = 'B'
            (job / 'request.json').write_text(json.dumps(job_request))
            self.assertEqual(client.post('/api/libraries/A/versions/v2/representative-files', json={'job_id': job.name}).status_code, 400)
            shutil.rmtree(job)
            self.assertEqual(len(client.get('/api/libraries/A/versions/v2/representative-files').get_json()['rows']), 1)
            shutil.rmtree(workspace / 'reports/site')
            from lib_guard.render.version_detail_fast import render_version_detail_only
            reconstructed = render_version_detail_only(catalog_path=catalog, out_dir=workspace / 'reports/site', library='A', version='v2')
            self.assertIn('人工核查', Path(reconstructed['version_detail_html']).read_text())

    def test_copy_and_rerun_share_one_output_lock(self):
        from threading import Event, Thread
        from unittest.mock import patch
        from lib_guard.review.representative_files import save_representative_file
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            old, new = root / 'old.v', root / 'new.v'
            old.write_text('module top(input a); endmodule')
            new.write_text(old.read_text())
            other = root / 'other.v'
            other.write_text('module top(input a, output b); endmodule')
            out = root / 'out'
            diff_pairwise_files('verilog', old, new, out)
            started, completed = Event(), Event()
            def rerun():
                started.set()
                diff_pairwise_files('verilog', old, other, out)
                completed.set()
            worker = Thread(target=rerun)
            original_copy = shutil.copy2
            def copying(source, destination):
                if not started.is_set():
                    worker.start()
                    self.assertTrue(started.wait(1))
                    self.assertFalse(completed.wait(0.05))
                return original_copy(source, destination)
            with patch('lib_guard.review.representative_files.shutil.copy2', side_effect=copying):
                saved = save_representative_file(root / 'notes', 'A', 'v2', out)
            worker.join(3)
            self.assertTrue(completed.is_set())
            evidence = Path(saved['evidence_dir'])
            self.assertEqual(json.loads((evidence / 'semantic_diff.json').read_text())['status'], 'SAME')

    def test_failed_rerun_cannot_leave_old_done_generation_attachable(self):
        from unittest.mock import patch
        from lib_guard.diff import file_diff
        from lib_guard.review.representative_files import save_representative_file
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            old, new = root / 'old.v', root / 'new.v'
            old.write_text('module top(input a); endmodule')
            new.write_text(old.read_text())
            out = root / 'out'
            original = diff_pairwise_files('verilog', old, new, out)
            previous = save_representative_file(root / 'notes', 'A', 'v2', out)
            new.write_text('module top(input a, output b); endmodule')
            write = file_diff._write_json
            def fail_after_semantic(path, data):
                write(path, data)
                if Path(path).name == 'semantic_diff.json':
                    raise OSError('injected write failure')
            with patch.object(file_diff, '_write_json', side_effect=fail_after_semantic):
                with self.assertRaises(OSError):
                    diff_pairwise_files('verilog', old, new, out)
            self.assertEqual(json.loads((out / 'pairwise_result.json').read_text())['status'], 'RUNNING')
            with self.assertRaises(ValueError):
                save_representative_file(root / 'notes', 'A', 'v2', out, expected_generation=original['generated_at'])
            self.assertEqual(json.loads((Path(previous['evidence_dir']) / 'semantic_diff.json').read_text())['status'], 'SAME')
