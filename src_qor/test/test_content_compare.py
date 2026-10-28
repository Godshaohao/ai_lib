import gzip
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


try:
    from lib_guard.content_compare import compare_files, compare_projection_files
except ModuleNotFoundError:
    compare_files = None
    compare_projection_files = None


class _StatProxy:
    def __init__(self, source, **updates):
        self._source = source
        self._updates = updates

    def __getattr__(self, name):
        if name in self._updates:
            return self._updates[name]
        return getattr(self._source, name)


class ContentCompareTests(unittest.TestCase):
    def setUp(self):
        if compare_files is None:
            self.fail("lib_guard.content_compare.compare_files is not implemented")

    def test_same_regular_files_compare_in_chunks_and_record_stats(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            base = root / "base.lef"
            target = root / "target.lef"
            payload = b"0123456789" * 4
            base.write_bytes(payload)
            target.write_bytes(payload)

            result = compare_files(base, target, chunk_size=7)

            self.assertEqual(result["status"], "SAME")
            self.assertEqual(result["comparison_mode"], "RAW_BYTES")
            self.assertEqual(result["bytes_read"], len(payload) * 2)
            self.assertEqual(set(result["stat_before"]), {"base", "target"})
            self.assertEqual(set(result["stat_after"]), {"base", "target"})
            self.assertIsNone(result["reason"])

    def test_different_regular_files_can_exit_after_first_different_chunk(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            base = root / "base.lef"
            target = root / "target.lef"
            base.write_bytes(b"AAAA" + b"B" * 100)
            target.write_bytes(b"AAAX" + b"B" * 100)

            result = compare_files(base, target, chunk_size=4)

            self.assertEqual(result["status"], "DIFF")
            self.assertLess(result["bytes_read"], 2 * len(base.read_bytes()))

    def test_missing_file_returns_failed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            target = root / "target.lef"
            target.write_bytes(b"content")

            result = compare_files(root / "missing.lef", target)

            self.assertEqual(result["status"], "FAILED")
            self.assertEqual(result["reason"], "path_error")

    def test_directory_path_returns_failed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            target = root / "target.lef"
            target.write_bytes(b"content")

            result = compare_files(root, target)

            self.assertEqual(result["status"], "FAILED")
            self.assertEqual(result["reason"], "path_error")

    def test_gzip_header_time_difference_compares_decompressed_content(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            base = root / "base.lib.gz"
            target = root / "target.lib.gz"
            payload = b"library (demo) { cell (A) { } }\n"
            base.write_bytes(gzip.compress(payload, mtime=1))
            target.write_bytes(gzip.compress(payload, mtime=2))
            self.assertNotEqual(base.read_bytes(), target.read_bytes())

            result = compare_files(base, target, chunk_size=5)

            self.assertEqual(result["status"], "SAME")
            self.assertEqual(result["comparison_mode"], "DECOMPRESSED_CONTENT")
            self.assertEqual(result["bytes_read"], len(payload) * 2)

    def test_gzip_and_plain_file_compare_effective_content(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            compressed = root / "base.lef.gz"
            plain = root / "target.lef"
            with gzip.open(compressed, "wb") as stream:
                stream.write(b"VERSION 5.8 ;\n")
            plain.write_bytes(b"VERSION 5.8 ;\n")
            result = compare_files(compressed, plain)
            self.assertEqual(result["status"], "SAME")
            self.assertEqual(result["comparison_mode"], "DECOMPRESSED_CONTENT")

    def test_bad_gzip_returns_failed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            base = root / "base.lib.gz"
            target = root / "target.lib.gz"
            base.write_bytes(b"not a gzip stream")
            target.write_bytes(gzip.compress(b"content"))

            result = compare_files(base, target)

            self.assertEqual(result["status"], "FAILED")
            self.assertEqual(result["reason"], "invalid_gzip")

    def test_stat_change_during_read_returns_unverified(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            base = root / "base.lef"
            target = root / "target.lef"
            base.write_bytes(b"stable content")
            target.write_bytes(b"stable content")
            real_stat = os.stat
            calls = []

            def stat_with_change(path):
                current = real_stat(path)
                calls.append(Path(path))
                if len(calls) == 3 and Path(path) == base:
                    return _StatProxy(current, st_mtime_ns=current.st_mtime_ns + 1)
                return current

            with patch("lib_guard.content_compare.os.stat", side_effect=stat_with_change):
                result = compare_files(base, target)

            self.assertEqual(result["status"], "UNVERIFIED")
            self.assertEqual(result["reason"], "source_changed_during_read")

    def test_projection_compare_updates_only_selected_unique_pairs(self):
        from lib_guard.file_version_projection import build_projection
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            base = root / "V1" / "LEF" / "a.lef"
            target = root / "V2" / "LEF" / "a.lef"
            base.parent.mkdir(parents=True)
            target.parent.mkdir(parents=True)
            base.write_text("same", encoding="utf-8")
            target.write_text("same", encoding="utf-8")
            projection = build_projection("IP_A", [
                {"id": "V1", "path": str(root / "V1"), "delivery_order": 1},
                {"id": "V2", "path": str(root / "V2"), "delivery_order": 2},
            ], [
                {"version_id": "V1", "status": "COMPLETE", "files": [str(base)]},
                {"version_id": "V2", "status": "COMPLETE", "files": [str(target)]},
            ], [], base_version="V1", target_version="V2")

            updated = compare_projection_files(projection, selected_keys=["lef:a.lef"])

            self.assertIs(updated, projection)
            self.assertEqual(projection["files"][0]["comparison"]["content_status"], "BYTE_SAME")
            self.assertEqual(projection["coverage"]["content_comparison"], "COMPLETE")


if __name__ == "__main__":
    unittest.main()
