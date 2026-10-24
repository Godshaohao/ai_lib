from pathlib import Path
import tempfile
import unittest

from lib_guard.raw_discovery import discover_raw_libraries
from lib_guard import raw_discovery


class RawDiscoveryTests(unittest.TestCase):
    def test_discovers_vendor_library_and_single_version(self):
        with tempfile.TemporaryDirectory() as temp:
            raw = Path(temp) / "3rd_IP"
            version = raw / "Vendor_A" / "phy_ip" / "20261020_drop"
            (version / "LEF").mkdir(parents=True)
            (version / "LEF" / "phy.lef.gz").touch()
            (version / "README").write_text("not a view", encoding="utf-8")

            result = discover_raw_libraries(raw)

            self.assertEqual(len(result), 1)
            self.assertEqual(result[0]["vendor"], "Vendor_A")
            self.assertEqual(result[0]["library_name"], "phy_ip")
            self.assertEqual(result[0]["versions"][0]["id"], "20261020_drop")
            self.assertEqual(result[0]["versions"][0]["views"], ["LEF"])
            self.assertTrue((version / "README").is_file())

    def test_discovers_multiple_versions_and_view_types_deterministically(self):
        with tempfile.TemporaryDirectory() as temp:
            raw = Path(temp) / "raw"
            for version_name, files in {
                "v02": ("LIB/NLDM/cell.lib.gz", "GDS/cell.gds"),
                "v01": ("LEF/cell.lef", "VERILOG/cell.v"),
            }.items():
                for relative in files:
                    path = raw / "Vendor_B" / "memory_ip" / version_name / relative
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.touch()

            result = discover_raw_libraries(raw)

            self.assertEqual([item["id"] for item in result[0]["versions"]], ["v01", "v02"])
            self.assertEqual(result[0]["versions"][0]["views"], ["LEF", "VERILOG"])
            self.assertEqual(result[0]["versions"][1]["views"], ["GDS", "LIB"])

    def test_rejects_missing_root_and_ignores_version_dirs_without_views(self):
        with tempfile.TemporaryDirectory() as temp:
            raw = Path(temp) / "raw"
            raw.mkdir()
            (raw / "Vendor_C" / "ip_c" / "release-notes").mkdir(parents=True)

            self.assertEqual(discover_raw_libraries(raw), [])
            with self.assertRaises(FileNotFoundError):
                discover_raw_libraries(raw / "missing")

    def test_discovers_nested_library_roots_and_preserves_catalog_hierarchy(self):
        with tempfile.TemporaryDirectory() as temp:
            raw = Path(temp) / "raw"
            version = raw / "Vendor_D" / "memory" / "sram" / "sram_256x16" / "20261024_drop"
            (version / "LIB" / "NLDM").mkdir(parents=True)
            (version / "LIB" / "NLDM" / "sram.lib.gz").touch()
            (version / "LEF").mkdir()
            (version / "LEF" / "sram.lef").touch()

            result = discover_raw_libraries(raw)

            self.assertEqual(len(result), 1)
            candidate = result[0]
            self.assertEqual(candidate["vendor"], "Vendor_D")
            self.assertEqual(candidate["middle_path"], "memory/sram")
            self.assertEqual(candidate["library_name"], "sram_256x16")
            self.assertEqual(candidate["library_id"], "Vendor_D.memory.sram.sram_256x16")
            self.assertEqual(candidate["versions"][0]["id"], "20261024_drop")
            self.assertEqual(candidate["versions"][0]["views"], ["LEF", "LIB"])

    def test_ignores_non_library_trees_and_does_not_promote_version_views(self):
        with tempfile.TemporaryDirectory() as temp:
            raw = Path(temp) / "raw"
            # These files resemble deliveries, but are documentation/report noise.
            for directory in ("Vendor_E/reports/run1", "Vendor_E/catalog/snapshot"):
                path = raw / directory
                path.mkdir(parents=True)
                (path / "noise.lef").touch()
            # A view directory inside the actual version is not another library.
            version = raw / "Vendor_E" / "group" / "ip_e" / "20261024"
            (version / "LEF").mkdir(parents=True)
            (version / "LEF" / "macro.lef").touch()

            result = discover_raw_libraries(raw)

            self.assertEqual([(item["library_name"], item["middle_path"]) for item in result], [("ip_e", "group")])

    def test_simulation_subtree_is_not_mixed_into_real_raw_discovery(self):
        with tempfile.TemporaryDirectory() as temp:
            raw = Path(temp) / "3rd_IP"
            real = raw / "Vendor_Real" / "real_ip" / "20261024" / "LEF"
            simulated = raw / "_simulation" / "RAW" / "Vendor_Demo" / "demo_ip" / "V01" / "LEF"
            real.mkdir(parents=True)
            simulated.mkdir(parents=True)
            (real / "real.lef").touch()
            (simulated / "demo.lef").touch()

            result = discover_raw_libraries(raw)

            self.assertEqual([item["vendor"] for item in result], ["Vendor_Real"])

    def test_discover_report_preserves_legacy_candidate_fields_and_writes_review_artifacts(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "raw"
            version = root / "Vendor_F" / "category" / "phy_ip" / "20261024_drop"
            for relative in ("LEF/phy.lef", "LIB/NLDM/phy.lib.gz"):
                path = version / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.touch()
            before = sorted(str(path.relative_to(root)) for path in root.rglob("*"))

            report = raw_discovery.discover_raw_report(root)
            artifacts = raw_discovery.write_discovery_artifacts(report, Path(temp) / "out")

            candidate = report["candidates"][0]
            self.assertEqual(candidate["status"], "REVIEW")
            self.assertEqual(candidate["display_name"], "phy_ip")
            self.assertEqual(candidate["vendor"], "Vendor_F")
            self.assertEqual(candidate["middle_path"], "category")
            self.assertEqual(candidate["version_count"], 1)
            self.assertEqual(candidate["version_names"], ["20261024_drop"])
            self.assertEqual(candidate["view_types"], ["LEF", "LIB"])
            self.assertEqual(candidate["example_versions"], ["20261024_drop"])
            self.assertEqual(candidate["root_abs"], str(root / "Vendor_F" / "category" / "phy_ip"))
            self.assertIn("Candidate snapshot", artifacts["list"].read_text(encoding="utf-8"))
            self.assertEqual(set(artifacts), {"list", "json", "html"})
            self.assertIn("middle_path", artifacts["list"].read_text(encoding="utf-8"))
            self.assertIn('"visited_dirs"', artifacts["json"].read_text(encoding="utf-8"))
            self.assertIn("待确认", artifacts["html"].read_text(encoding="utf-8"))
            after = sorted(str(path.relative_to(root)) for path in root.rglob("*"))
            self.assertEqual(after, before)


if __name__ == "__main__":
    unittest.main()
