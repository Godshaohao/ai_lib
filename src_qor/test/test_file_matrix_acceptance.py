import gzip
import json
import tempfile
import unittest
from pathlib import Path


class FileMatrixAcceptanceTests(unittest.TestCase):
    def _delivery(self, root, version, files, order, status="COMPLETE"):
        version_root = root / version
        paths = []
        for relative, content in files:
            path = version_root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            if relative.endswith(".gz"):
                path.write_bytes(gzip.compress(content.encode("utf-8"), mtime=1))
            else:
                path.write_text(content, encoding="utf-8")
            paths.append(str(path))
        return {"id": version, "path": str(version_root), "delivery_order": order}, {
            "version_id": version, "root": str(version_root), "files": paths, "status": status,
        }

    def test_five_delivery_matrix_keeps_file_specific_latest_previous_and_formal_source(self):
        from lib_guard.file_version_projection import build_projection

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            versions, inventories = [], []
            for index in range(1, 6):
                version, inventory = self._delivery(root, f"V0{index}", [], index)
                versions.append(version)
                inventories.append(inventory)
            def add(version_index, relative, text):
                version_root = root / f"V0{version_index}"
                path = version_root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text, encoding="utf-8")
                inventories[version_index - 1]["files"].append(str(path))
            add(1, "LEF/core.lef", "core-v1")
            add(3, "LEF/core.lef", "core-v3")
            add(5, "LEF/core.lef", "core-v5")
            add(2, "LEF/sram.lef", "sram-v2")
            add(4, "LEF/sram.lef", "sram-v4")
            add(1, "LIB/core_tt.lib", "tt-v1")
            add(4, "LIB/core_tt.lib", "tt-v4")
            add(3, "LIB/core_ss.lib", "ss-v3")
            add(1, "LIB/core_ss.lib", "ss-v1")
            add(5, "LEF/new_io.lef", "new")
            formal = [{"view": "lef", "source_path": str(root / "V01" / "LEF" / "core.lef"),
                       "published_path": "/formal/LEF/core.lef"}]

            projection = build_projection("IP_A", versions, inventories, formal, formal_stage="lib_NL2",
                                         base_version="V03", target_version="V05")
            rows = {row["file_key"]: row for row in projection["files"]}
            self.assertEqual((rows["lef:core.lef"]["latest"]["version"], rows["lef:core.lef"]["previous"]["version"]), ("V05", "V03"))
            self.assertEqual((rows["lef:sram.lef"]["latest"]["version"], rows["lef:sram.lef"]["previous"]["version"]), ("V04", "V02"))
            self.assertEqual(rows["lef:new_io.lef"]["previous"]["status"], "NONE")
            self.assertEqual(rows["lef:core.lef"]["formal_usage"]["source_version"], "V01")
            self.assertEqual(rows["liberty:core_tt.lib"]["latest"]["version"], "V04")
            self.assertEqual(rows["liberty:core_ss.lib"]["latest"]["version"], "V03")
            self.assertEqual(projection["version_order"]["basis"], "EXPLICIT")

    def test_partial_target_and_gzip_compare_keep_uncertainty_and_content_semantics(self):
        from lib_guard.content_compare import compare_files
        from lib_guard.file_version_projection import build_projection

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            v1, i1 = self._delivery(root, "V01", [("LIB/core.lib.gz", "library (core) {}")], 1)
            v2, i2 = self._delivery(root, "V02", [], 2, status="PARTIAL")
            projection = build_projection("IP_A", [v1, v2], [i1, i2], [], base_version="V01", target_version="V02")
            row = projection["files"][0]
            self.assertEqual(row["comparison"]["delivery_relation"], "UNKNOWN_COVERAGE")
            self.assertEqual(row["latest"]["status"], "UNKNOWN_COVERAGE")
            compressed_a = root / "a.lib.gz"
            compressed_b = root / "b.lib.gz"
            compressed_a.write_bytes(gzip.compress(b"same", mtime=1))
            compressed_b.write_bytes(gzip.compress(b"same", mtime=2))
            compared = compare_files(compressed_a, compressed_b)
            self.assertEqual(compared["status"], "SAME")
            self.assertEqual(compared["comparison_mode"], "DECOMPRESSED_CONTENT")


if __name__ == "__main__":
    unittest.main()
