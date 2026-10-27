import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path


class LefFileStatusTests(unittest.TestCase):
    def test_multiview_formal_and_raw_only_files_keep_distinct_corners(self):
        from lib_guard.file_status import build_file_status, scan_registered_raw_files
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            old, new = root / "20261001_full", root / "20261005_fix"
            for path in (old / "LIB" / "phy_tt.lib", old / "LIB" / "phy_ff.lib",
                         new / "LIB" / "phy_tt.lib", new / "GDS" / "phy.gds"):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("test", encoding="utf-8")
            versions = [{"id": p.name, "path": str(p)} for p in (old, new)]
            formal = [{"view": "liberty", "published_path": f"/nl/LIB/{name}",
                       "source_path": str(old / "LIB" / name)} for name in ("phy_tt.lib", "phy_ff.lib")]
            result = build_file_status(formal, versions, scan_registered_raw_files(versions), context={})
            rows = {row["display_name"]: row for row in result["files"]}
            self.assertEqual(set(rows), {"phy_tt.lib", "phy_ff.lib", "phy.gds"})
            self.assertEqual(rows["phy_tt.lib"]["recent_raw_source"]["delivery_label"], new.name)
            self.assertEqual(rows["phy_ff.lib"]["delivery_relation"], "NO_LATER_DELIVERY_HINT")
            self.assertEqual(rows["phy.gds"]["delivery_relation"], "RAW_ONLY")
            self.assertIsNone(rows["phy.gds"]["nl_source"]["delivery_label"])

    def test_raw_only_equal_date_does_not_guess_latest(self):
        from lib_guard.file_status import build_file_status, scan_registered_raw_files
        with tempfile.TemporaryDirectory() as temp:
            roots = [Path(temp) / name for name in ("20261001_a", "20261001_b")]
            for root in roots:
                path = root / "LIB" / "phy_tt.lib"
                path.parent.mkdir(parents=True)
                path.write_text("fixture", encoding="utf-8")
            versions = [{"id": root.name, "path": str(root)} for root in roots]
            row = build_file_status([], versions, scan_registered_raw_files(versions), context={})["files"][0]
            self.assertEqual(row["delivery_relation"], "RAW_ONLY")
            self.assertIsNone(row["recent_raw_source"])

    def _build(self, formal_files, versions, inventories):
        from lib_guard.file_status import build_lef_file_status

        return build_lef_file_status(
            formal_files,
            versions,
            inventories,
            context={"library_id": "Vendor.IP_A", "stage": "lib_NL2.5_3"},
        )

    def test_fifty_deliveries_keep_only_actual_lef_occurrences_and_do_not_infer_deletion(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            versions = []
            inventories = []
            occurrences = (1, 20, 50)
            for index in range(1, 51):
                version_id = (date(2026, 1, 1) + timedelta(days=index - 1)).strftime("%Y%m%d") + "_release"
                root = base / version_id
                versions.append({"id": version_id, "path": str(root)})
                files = []
                if index in occurrences:
                    lef = root / "LEF" / "top.lef"
                    lef.parent.mkdir(parents=True, exist_ok=True)
                    lef.write_text(f"version {index}", encoding="utf-8")
                    files.append(str(lef))
                inventories.append({"version_id": version_id, "root": str(root),
                                    "files": files, "status": "COMPLETE"})
            formal_source = base / versions[0]["id"] / "LEF" / "top.lef"
            result = self._build([{"library_id": "Vendor.IP_A", "stage": "lib_NL2.5_3",
                                   "view": "lef", "published_path": "/formal/IP/top.lef",
                                   "source_path": str(formal_source)}], versions, inventories)

            self.assertEqual(result["raw_scope"]["registered_deliveries"], 50)
            row = result["files"][0]
            self.assertEqual([item["delivery_label"] for item in row["history"]],
                             [item["id"] for item in (versions[49], versions[19], versions[0])])
            self.assertEqual(row["recent_raw_source"]["delivery_label"], versions[49]["id"])
            self.assertEqual(row["content_check"], "NOT_RUN")
            self.assertNotIn("DELETE", str(row))

    def test_path_identity_does_not_pair_by_basename_across_different_view_subtrees(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "20261001_v1"
            formal = root / "LEF" / "LEF" / "a.lef"
            formal.parent.mkdir(parents=True)
            formal.write_text("formal", encoding="utf-8")
            raw_a = root / "LEF" / "LEF" / "a.lef"
            raw_b = root / "LEF" / "hack_lef" / "a.lef"
            raw_b.parent.mkdir(parents=True)
            raw_b.write_text("other", encoding="utf-8")
            result = self._build(
                [{"library_id": "Vendor.IP_A", "stage": "lib_NL2.5_3", "view": "lef",
                  "published_path": "/formal/a.lef", "source_path": str(formal)}],
                [{"id": "20261001_v1", "path": str(root)}],
                [{"version_id": "20261001_v1", "root": str(root),
                  "files": [str(raw_a), str(raw_b)], "status": "COMPLETE"}],
            )

            self.assertEqual(len(result["files"]), 1)
            self.assertEqual(result["files"][0]["identity_status"], "UNIQUE")
            self.assertEqual([item["source_path"] for item in result["files"][0]["history"]],
                             [str(raw_a)])

    def test_duplicate_date_hints_do_not_select_a_latest_delivery(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            roots = [base / "20261001_a", base / "20261001_b"]
            for root in roots:
                path = root / "LEF" / "top.lef"
                path.parent.mkdir(parents=True)
                path.write_text("lef", encoding="utf-8")
            formal = roots[0] / "LEF" / "top.lef"
            result = self._build(
                [{"library_id": "Vendor.IP_A", "stage": "lib_NL2.5_3", "view": "lef",
                  "published_path": "/formal/top.lef", "source_path": str(formal)}],
                [{"id": root.name, "path": str(root)} for root in roots],
                [{"version_id": root.name, "root": str(root),
                  "files": [str(root / "LEF" / "top.lef")], "status": "COMPLETE"}
                 for root in roots],
            )

            row = result["files"][0]
            self.assertEqual(row["delivery_relation"], "UNDETERMINED")
            self.assertIsNone(row["recent_raw_source"])

    def test_unregistered_formal_source_is_not_compared_to_raw_basename(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "outside" / "top.lef"
            source.parent.mkdir()
            source.write_text("lef", encoding="utf-8")
            result = self._build(
                [{"library_id": "Vendor.IP_A", "stage": "lib_NL2.5_3", "view": "lef",
                  "published_path": "/formal/top.lef", "source_path": str(source)}],
                [{"id": "20261001_v1", "path": str(Path(temp) / "raw")}],
                [],
            )

            self.assertEqual(result["files"][0]["identity_status"], "UNREGISTERED_SOURCE")
            self.assertEqual(result["files"][0]["delivery_relation"], "UNDETERMINED")

    def test_incomplete_raw_inventory_cannot_claim_no_later_delivery(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "20261001_v1"
            formal = root / "LEF" / "top.lef"
            formal.parent.mkdir(parents=True)
            formal.write_text("lef", encoding="utf-8")
            result = self._build(
                [{"library_id": "Vendor.IP_A", "stage": "lib_NL2.5_3", "view": "lef",
                  "published_path": "/formal/top.lef", "source_path": str(formal)}],
                [{"id": root.name, "path": str(root)}],
                [{"version_id": root.name, "root": str(root),
                  "files": [str(formal)], "status": "PARTIAL"}],
            )

            self.assertEqual(result["files"][0]["delivery_relation"], "UNDETERMINED")
            self.assertEqual(result["raw_scope"]["scan_status"], "PARTIAL")

    def test_scanner_includes_compressed_lef_and_marks_unfollowed_or_escaping_symlinks_incomplete(self):
        from lib_guard.file_status import scan_registered_raw_lefs

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "raw"
            compressed = root / "LEF" / "top.LEF.GZ"
            compressed.parent.mkdir(parents=True)
            compressed.write_bytes(b"gzip placeholder")
            external = Path(temp) / "outside.lef"
            external.write_text("outside", encoding="utf-8")
            (root / "LEF" / "escape.lef").symlink_to(external)
            external_dir = Path(temp) / "external-view"
            external_dir.mkdir()
            (external_dir / "hidden.lef").write_text("outside", encoding="utf-8")
            (root / "linked_view").symlink_to(external_dir, target_is_directory=True)

            result = scan_registered_raw_lefs([{"id": "20261001_v1", "path": str(root)}])[0]

            self.assertEqual(result["files"], [str(compressed.resolve())])
            self.assertEqual(result["status"], "INCOMPLETE")
            self.assertIn("SOURCE_UNAVAILABLE", result["errors"])
            self.assertIn("SYMLINK_DIRECTORY_NOT_FOLLOWED", result["errors"])


if __name__ == "__main__":
    unittest.main()
