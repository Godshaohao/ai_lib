import gzip
import tempfile
import unittest
from pathlib import Path

from lib_guard.ip_file_history import (build_history, check_formal_manifest, compare_content,
                             file_identity, parse_formal_manifest)


class TestIPFileHistory(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def put(self, v, relative, text, *, compressed=False):
        path = self.base / f"V{v}" / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        if compressed:
            with gzip.open(path, "wb") as f:
                f.write(text.encode("utf-8"))
        else:
            path.write_text(text, encoding="utf-8")
        return path

    def library(self, n):
        return {"library_id": "Vendor.physical_lib", "deliveries": [
            {"id": f"V{i}", "order": i, "root": f"V{i}"} for i in range(1, n + 1)
        ]}

    def test_no_package_metadata_latest_previous(self):
        self.put(1, "LEF/core.lef", "old")
        self.put(1, "LIB/tt.lib", "old")
        (self.base / "V2").mkdir()
        self.put(3, "LEF/core.lef", "new")
        self.put(3, "LIB/tt.lib", "old")
        rows, scans = build_history(self.library(3), self.base, 100, True)
        by = {h["identity_path"]: h for h in rows}
        self.assertEqual((by["core.lef"]["latest"]["version"],
                          by["core.lef"]["previous"]["version"]), ("V3", "V1"))
        self.assertEqual(by["core.lef"]["comparison"]["status"], "CHANGED")
        self.assertEqual(by["tt.lib"]["comparison"]["status"], "SAME")
        self.assertTrue(all(s["scan_status"] == "COMPLETE" for s in scans))

    def test_latest_uncertain_when_later_delivery_missing(self):
        self.put(1, "LEF/core.lef", "old")
        rows, scans = build_history(self.library(2), self.base, 100, True)
        self.assertEqual(scans[1]["scan_status"], "PARTIAL")
        self.assertEqual(rows[0]["latest_status"], "UNCERTAIN")
        self.assertEqual(rows[0]["comparison"]["status"], "NOT_RUN")

    def test_previous_uncertain_when_intermediate_scan_missing(self):
        self.put(1, "LEF/core.lef", "old")
        self.put(3, "LEF/core.lef", "new")
        rows, _ = build_history(self.library(3), self.base, 100, True)
        self.assertEqual(rows[0]["latest_status"], "CONFIRMED")
        self.assertEqual(rows[0]["previous_status"], "UNCERTAIN")
        self.assertEqual(rows[0]["comparison"]["status"], "NOT_RUN")

    def test_case_sensitive_identity(self):
        a = file_identity("X", "LEF", Path("LEF/Top.lef"))
        b = file_identity("X", "LEF", Path("LEF/top.lef"))
        self.assertNotEqual(a, b)

    def test_same_basename_under_different_subdirs(self):
        self.put(1, "LEF/one/mem.lef", "one")
        self.put(1, "LEF/two/mem.lef", "two")
        rows, _ = build_history(self.library(1), self.base, 100, True)
        self.assertEqual(len(rows), 2)
        self.assertEqual({h["identity_path"] for h in rows}, {"one/mem.lef", "two/mem.lef"})

    def test_gzip_contents_not_wrappers(self):
        a = self.put(1, "LIB/tt.lib.gz", "same", compressed=True)
        b = self.put(2, "LIB/tt.lib.gz", "same", compressed=True)
        self.assertEqual(compare_content(str(a), str(b))["status"], "SAME")

    def test_doc_no_content_comparison(self):
        self.put(1, "DOC/readme.md", "old")
        self.put(2, "DOC/readme.md", "new")
        rows, _ = build_history(self.library(2), self.base, 100, True)
        self.assertEqual(rows[0]["comparison"]["status"], "NOT_RUN")

    def test_same_file_id_twice_in_one_delivery_is_ambiguous(self):
        self.put(1, "LEF/Top.lef", "A")
        self.put(1, "LEF_ALT/Top.lef", "B")
        # Matching *known* wrappers cause a collision; two different leaf files can't be chosen.
        self.put(1, "LEF/one/Top.lef", "C")
        self.put(1, "LIB/Top.lef", "D")
        rows, _ = build_history(self.library(1), self.base, 100, True)
        # LEF/Top.lef and LIB/Top.lef both map to LEF|Top.lef.
        row = next(h for h in rows if h["identity_path"] == "Top.lef")
        self.assertEqual(row["latest_status"], "AMBIGUOUS")

    def test_formal_list_and_source_symlink(self):
        raw = self.put(1, "LIB/tt.lib.gz", "x", compressed=True)
        formal_dir = self.base / "formal" / "IP" / "LIB"
        formal_dir.mkdir(parents=True)
        (formal_dir / "tt.lib.gz").symlink_to(raw)
        manifest = self.base / "formal.list"
        manifest.write_text("#BUSINESS_IP#\ntt.lib.gz IP/LIB/\n", encoding="utf-8")
        rows, _ = build_history(self.library(1), self.base, 100, False)
        config = {"ip_name": "BUSINESS_IP", "formal_manifest": "formal.list",
                  "formal_root": "formal"}
        matches, errors = check_formal_manifest(config, self.base, rows)
        self.assertFalse(errors)
        self.assertEqual(matches[0]["status"], "SOURCE_PATH_CONFIRMED")
        self.assertEqual(matches[0]["observed_source_version"], "V1")

    def test_manifest_without_actual_file_is_not_confirmed(self):
        self.put(1, "LIB/tt.lib", "x")
        manifest = self.base / "formal.list"
        manifest.write_text("#BUSINESS_IP#\ntt.lib IP/LIB/\n", encoding="utf-8")
        rows, _ = build_history(self.library(1), self.base, 100, False)
        config = {"ip_name": "BUSINESS_IP", "formal_manifest": "formal.list"}
        matches, _ = check_formal_manifest(config, self.base, rows)
        self.assertEqual(matches[0]["status"], "NAME_ONLY_CANDIDATE")
        self.assertEqual(matches[0]["observed_source_version"], "")


    def _formal_link_fixture(self, linked_version: int, *, missing_latest: bool = False):
        for version in (1, 2, 3):
            if missing_latest and version == 3:
                continue
            self.put(version, "LIB/tt.lib", f"cell version {version}")
        raw = self.base / f"V{linked_version}" / "LIB" / "tt.lib"
        formal_dir = self.base / "formal" / "IP" / "LIB"
        formal_dir.mkdir(parents=True, exist_ok=True)
        (formal_dir / "tt.lib").symlink_to(raw)
        (self.base / "formal.list").write_text("#IP#\ntt.lib IP/LIB/\n", encoding="utf-8")
        rows, _ = build_history(self.library(3), self.base, 100, False)
        return check_formal_manifest({
            "ip_name": "IP", "formal_manifest": "formal.list", "formal_root": "formal"
        }, self.base, rows)[0][0]

    def test_formal_links_latest(self):
        item = self._formal_link_fixture(3)
        self.assertEqual(item["formal_relation"], "LATEST")
        self.assertEqual((item["raw_latest_version"], item["raw_previous_version"]), ("V3", "V2"))

    def test_formal_links_previous_not_latest(self):
        item = self._formal_link_fixture(2)
        self.assertEqual(item["formal_relation"], "PREVIOUS")
        self.assertEqual(item["observed_source_version"], "V2")
        self.assertEqual(item["raw_latest_version"], "V3")

    def test_formal_links_older_than_previous(self):
        item = self._formal_link_fixture(1)
        self.assertEqual(item["formal_relation"], "OLDER")
        self.assertEqual(item["observed_source_version"], "V1")
        self.assertEqual(item["raw_previous_version"], "V2")

    def test_formal_link_uncertain_when_later_delivery_not_scanned(self):
        item = self._formal_link_fixture(2, missing_latest=True)
        self.assertEqual(item["status"], "SOURCE_PATH_CONFIRMED")
        self.assertEqual(item["formal_relation"], "RANK_UNCERTAIN")

    def test_formal_copied_file_does_not_invent_linked_version(self):
        raw = self.put(1, "LIB/tt.lib", "same content")
        formal_dir = self.base / "formal" / "IP" / "LIB"
        formal_dir.mkdir(parents=True)
        (formal_dir / "tt.lib").write_text(raw.read_text())
        (self.base / "formal.list").write_text("#IP#\ntt.lib IP/LIB/\n")
        rows, _ = build_history(self.library(1), self.base, 100, False)
        item = check_formal_manifest({
            "ip_name": "IP", "formal_manifest": "formal.list", "formal_root": "formal"
        }, self.base, rows)[0][0]
        self.assertEqual(item["status"], "PUBLISHED_FOUND_SOURCE_UNKNOWN")
        self.assertEqual(item["formal_relation"], "UNVERIFIED")


if __name__ == "__main__":
    unittest.main()
