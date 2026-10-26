from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from lib_guard.raw_discovery import discover_raw_libraries
from lib_guard import raw_discovery


class RawDiscoveryTests(unittest.TestCase):
    def test_maximum_depth_is_reported_as_partial_discovery(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "raw"
            version = root / "Vendor_A" / "group" / "nested" / "ip" / "V01" / "LEF"
            version.mkdir(parents=True)
            (version / "macro.lef").touch()

            with patch.object(raw_discovery, "_MAX_DEPTH", 2):
                report = raw_discovery.discover_raw_report(root)

            self.assertTrue(report["partial_discovery"])
            self.assertIn(str(root / "Vendor_A" / "group"), report["depth_limited_paths"])
            self.assertTrue(any("达到目录深度上限" in item for item in report["warnings"]))

    def test_permission_errors_are_reported_as_incomplete_discovery(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "raw"
            version = root / "Vendor_A" / "ip" / "V01"
            (version / "LEF").mkdir(parents=True)
            (version / "LEF" / "macro.lef").touch()
            denied = version / "restricted"
            denied.mkdir()
            original_scandir = raw_discovery.os.scandir

            def scandir_with_denial(path):
                if Path(path) == denied:
                    raise PermissionError("permission denied for test")
                return original_scandir(path)

            with patch("lib_guard.raw_discovery.os.scandir", side_effect=scandir_with_denial):
                report = raw_discovery.discover_raw_report(root)

            self.assertTrue(report["partial_discovery"])
            self.assertEqual(len(report["scan_errors"]), 1)
            self.assertEqual(report["scan_errors"][0]["path"], str(denied))
            self.assertTrue(any("目录访问失败" in item for item in report["warnings"]))

    def test_reports_incomplete_hint_sampling(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "raw"
            version = root / "Vendor_A" / "ip" / "V01"
            version.mkdir(parents=True)
            (version / "first.lef").touch()
            for index in range(raw_discovery._HINT_ENTRIES):
                (version / f"noise_{index}.txt").touch()
            report = raw_discovery.discover_raw_report(root)
            self.assertTrue(report["partial_discovery"])
            self.assertIn(str(version), report["truncated_hints"])

    def test_reports_colliding_library_ids(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "raw"
            for relative in ("Vendor_A/foo.bar/ip/V01", "Vendor_A/foo/bar/ip/V01"):
                version = root / relative
                version.mkdir(parents=True)
                (version / "cell.lef").touch()
            report = raw_discovery.discover_raw_report(root)
            self.assertEqual(len(report["candidates"]), 2)
            self.assertIn("Vendor_A.foo.bar.ip", report["identity_conflicts"])

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

    def test_date_release_with_netlist_and_spi_is_one_library_version(self):
        with tempfile.TemporaryDirectory() as temp:
            raw = Path(temp) / "raw"
            version = raw / "Metax" / "ddl" / "20260817_ma_ddl_pd_release"
            for relative in ("netlist/ddl.v", "spi/ddl.sp", "def/ddl.def"):
                path = version / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.touch()

            result = discover_raw_libraries(raw)

            self.assertEqual(len(result), 1)
            self.assertEqual(result[0]["library_id"], "Metax.ddl")
            self.assertEqual(result[0]["version_names"], [version.name])
            self.assertEqual(result[0]["versions"][0]["path"], str(version))
            self.assertEqual(result[0]["view_types"], ["DEF", "SPICE", "VERILOG"])

    def test_date_release_with_cell_subdirectories_groups_versions_by_cell(self):
        with tempfile.TemporaryDirectory() as temp:
            raw = Path(temp) / "raw"
            cell = "ln04lpp_sc_hvt_c54104"
            for release in ("20260917_DTCO", "20261001_DTCO"):
                version = raw / "Metax" / "DTCO" / release / "elf" / "psls" / cell
                for relative in ("LEF/cell.lef", "CDL/cell.cdl"):
                    path = version / relative
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.touch()

            result = discover_raw_libraries(raw)

            self.assertEqual(len(result), 1)
            candidate = result[0]
            self.assertEqual(candidate["library_id"], f"Metax.DTCO.elf.psls.{cell}")
            self.assertEqual(candidate["library_name"], cell)
            self.assertEqual(candidate["middle_path"], "DTCO/elf/psls")
            self.assertEqual(candidate["version_names"], ["20260917_DTCO", "20261001_DTCO"])
            self.assertEqual(candidate["versions"][0]["path"],
                             str(raw / "Metax" / "DTCO" / "20260917_DTCO" / "elf" / "psls" / cell))
            self.assertEqual(candidate["view_types"], ["CDL", "LEF"])

    def test_repeated_source_package_is_not_a_cell_library(self):
        with tempfile.TemporaryDirectory() as temp:
            raw = Path(temp) / "raw"
            for release in ("20260917", "20261001"):
                path = raw / "Metax" / "ddl" / release / "source_package" / "lef" / "ddl.lef"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.touch()

            result = discover_raw_libraries(raw)

            self.assertEqual([item["library_id"] for item in result], ["Metax.ddl"])
            self.assertEqual(result[0]["version_names"], ["20260917", "20261001"])

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
            self.assertEqual(set(artifacts), {"json"})
            self.assertIn('"visited_dirs"', artifacts["json"].read_text(encoding="utf-8"))
            self.assertFalse((Path(temp) / "out" / "library.list").exists())
            exported = raw_discovery.write_discovery_artifacts(
                report, Path(temp) / "out", include_human=True)
            self.assertEqual(set(exported), {"list", "json", "html"})
            self.assertIn("Candidate snapshot", exported["list"].read_text(encoding="utf-8"))
            self.assertIn("middle_path", exported["list"].read_text(encoding="utf-8"))
            self.assertIn("待确认", exported["html"].read_text(encoding="utf-8"))
            after = sorted(str(path.relative_to(root)) for path in root.rglob("*"))
            self.assertEqual(after, before)


if __name__ == "__main__":
    unittest.main()
