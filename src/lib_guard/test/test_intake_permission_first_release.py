import errno
import json
import tempfile
import unittest
from argparse import Namespace
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from lib_guard.library_registry import _discover_library_candidates_with_stats as discover_library_candidates_with_stats
from lib_guard.scan.inventory import FileWalker
from lib_guard.release.checker import check_release_scan
from lib_guard.test.test_release_levels import _scan
from lib_guard.web.app import _job_failure_summary


class IntakePermissionFirstReleaseTest(unittest.TestCase):
    def test_unreadable_scan_root_is_not_an_empty_success(self):
        def walk(root, **kwargs):
            kwargs['onerror'](PermissionError(errno.EACCES, 'Permission denied', str(root)))
            return []
        with patch('lib_guard.scan.inventory.os.walk', side_effect=walk):
            with self.assertRaises(PermissionError):
                list(FileWalker().walk('/tmp'))

    def test_unreadable_link_resolution_keeps_other_inventory(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / 'good.v').write_text('module good; endmodule')
            bad = root / 'blocked.v'
            bad.write_text('blocked')
            resolve = Path.resolve
            def guarded(path, *args, **kwargs):
                if path == bad:
                    raise PermissionError(errno.EACCES, 'Permission denied', str(path))
                return resolve(path, *args, **kwargs)
            walker = FileWalker()
            with patch.object(Path, 'resolve', guarded):
                try:
                    rows = list(walker.walk(root))
                except PermissionError:
                    self.fail('one unreadable link aborted the complete inventory')
            self.assertEqual([row['name'] for row in rows], ['good.v'])
            self.assertFalse(walker.coverage['complete'])
            self.assertEqual(walker.coverage['skipped_count'], 1)
            self.assertEqual(walker.coverage['examples'][0]['path'], str(bad))

    def test_compressed_only_single_version_is_discovered(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            version = root / 'Vendor_A' / 'demo' / 'v1'
            version.mkdir(parents=True)
            (version / 'demo.lib.gz').write_bytes(b'compressed fixture')
            result = discover_library_candidates_with_stats(root)
            self.assertEqual([row.root_abs for row in result['candidates']], [str(version.parent)])

    def test_discovery_permission_skip_is_visible(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            blocked = root / 'Vendor_A' / 'demo' / 'v1'
            blocked.mkdir(parents=True)
            scandir = __import__('os').scandir
            def guarded(path):
                if Path(path) == blocked:
                    raise PermissionError(errno.EACCES, 'Permission denied', str(path))
                return scandir(path)
            with patch('lib_guard.library_registry.os.scandir', guarded):
                result = discover_library_candidates_with_stats(root)
            self.assertTrue(result['warnings'], 'permission errors must not look like empty discovery')
            self.assertIn(str(blocked), ' '.join(result['warnings']))

    def test_web_permission_message_is_not_python_dict(self):
        message = _job_failure_summary(json.dumps({'scan_error': {
            'type': 'PermissionError', 'message': "[Errno 13] Permission denied: '/raw/blocked'",
            'traceback': 'Traceback noisy details'}}))
        self.assertIn('权限', message)
        self.assertIn('/raw/blocked', message)
        self.assertNotIn('traceback', message)
        self.assertNotIn("{'type'", message)

    def test_first_full_catalog_check_and_real_link_apply(self):
        from lib_guard.cli_commands.catalog import run_catalog_release_check, run_catalog_release_link
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            root = base / 'raw'
            root.mkdir()
            (root / 'top.v').write_text('module top(input a); endmodule\n')
            scan = base / 'scan'
            _scan(root, scan, mode='signature')
            catalog = base / 'catalog.json'
            version = {'version_id': 'v1', 'version_key': 'ip/demo/v1', 'package_type': 'FULL_PACKAGE',
                       'stage': 'final', 'standalone': True, 'raw_path': str(root),
                       'scan': {'scan_dir': str(scan), 'status': 'PASS'}}
            catalog.write_text(json.dumps({'libraries': [{'library_name': 'demo', 'library_id': 'demo',
                'library_type': 'ip', 'versions': [version]}]}))
            args = Namespace(catalog=str(catalog), library='demo', version='v1', alias='current',
                             policy=None, diff=None, diff_mode=None, review_gate=None, explain=False,
                             release_root=str(base / 'release'), apply=True)
            with redirect_stdout(StringIO()) as output:
                code = run_catalog_release_check(args)
            self.assertEqual(code, 0, output.getvalue())
            self.assertEqual(json.loads(output.getvalue())['diff_gate']['status'], 'NOT_APPLICABLE')
            with redirect_stdout(StringIO()) as output:
                code = run_catalog_release_link(args)
            self.assertEqual(code, 0, output.getvalue())
            self.assertEqual(json.loads(output.getvalue())['status'], 'APPLIED')
            current = base / 'release' / 'current'
            self.assertTrue(current.is_symlink())
            link = current / 'VERILOG' / 'top.v'
            self.assertTrue(link.is_symlink())
            self.assertEqual(link.resolve(), root / 'top.v')

    def test_readlink_permission_is_also_a_skipped_entry(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / 'good.v').write_text('module good; endmodule')
            (root / 'link.v').symlink_to(root / 'good.v')
            walker = FileWalker()
            with patch('lib_guard.scan.inventory.os.readlink', side_effect=PermissionError(13, 'denied', str(root / 'link.v'))):
                # Resolve itself may read the link before the explicit readlink.
                rows = list(walker.walk(root))
            self.assertEqual([row['name'] for row in rows], ['good.v'])
            self.assertFalse(walker.coverage['complete'])

    def test_first_full_package_does_not_require_nonexistent_diff(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            root = base / 'raw'
            root.mkdir()
            (root / 'top.v').write_text('module top(input a); endmodule\n')
            scan = base / 'scan'
            _scan(root, scan, mode='signature')
            catalog = base / 'catalog.json'
            version = {'version_id': 'v1', 'package_type': 'FULL_PACKAGE',
                       'scan': {'scan_dir': str(scan)}}
            catalog.write_text(json.dumps({'libraries': [{'library_name': 'demo', 'versions': [version]}]}))
            try:
                result = check_release_scan(scan, alias='current', catalog_path=catalog)
            except TypeError as error:
                self.fail(str(error))
            self.assertTrue(result['allowed_to_apply'], result['block_reasons'])
            self.assertEqual(result['diff_gate']['status'], 'NOT_APPLICABLE')
            # The exemption must not survive an actual predecessor, or a FIX.
            for versions in ([version, {'version_id': 'v0'}],
                             [{**version, 'package_type': 'PARTIAL_UPDATE'}]):
                catalog.write_text(json.dumps({'libraries': [{'library_name': 'demo', 'versions': versions}]}))
                result = check_release_scan(scan, alias='current', catalog_path=catalog)
                self.assertFalse(result['allowed_to_apply'])
            catalog.write_text(json.dumps({'libraries': [{'library_name': 'demo', 'versions': [version]}]}))
            result = check_release_scan(scan, alias='current', catalog_path=catalog,
                                        review_gate={'status': 'BLOCKED', 'blocking_open': 1})
            self.assertEqual(result['release_check_status'], 'BLOCK')
