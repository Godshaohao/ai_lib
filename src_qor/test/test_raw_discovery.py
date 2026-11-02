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
            version = root / "Vendor_A" / "ip" / "V01" / "one" / "two" / "three" / "LEF"
            version.mkdir(parents=True)
            (version / "macro.lef").touch()

            with patch.object(raw_discovery, "_MAX_DEPTH", 2):
                report = raw_discovery.discover_raw_report(root)

            self.assertTrue(report["partial_discovery"])
            self.assertIn(str(root / "Vendor_A" / "ip" / "V01"), report["depth_limited_paths"])
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
            for relative in ("Vendor_A/foo@bar/V01", "Vendor_A/foo#bar/V01"):
                version = root / relative
                (version / "LEF").mkdir(parents=True)
                (version / "LEF" / "cell.lef").touch()
            report = raw_discovery.discover_raw_report(root)
            self.assertEqual(len(report["candidates"]), 2)
            self.assertIn("Vendor_A.foo_bar", report["identity_conflicts"])

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

    def test_product_line_candidate_keeps_date_named_root_and_does_not_split_cells(self):
        with tempfile.TemporaryDirectory() as temp:
            raw = Path(temp) / "raw"
            product_line = "20261001_DTCO"
            cell = "ln04lpp_sc_hvt_c54104"
            for release in ("20260917", "20261001"):
                version = raw / "Metax" / product_line / release / "elf" / "psls" / cell
                for relative in ("LEF/cell.lef", "CDL/cell.cdl"):
                    path = version / relative
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.touch()

            result = discover_raw_libraries(raw)

            self.assertEqual(len(result), 1)
            candidate = result[0]
            self.assertEqual(candidate["library_id"], f"Metax.{product_line}")
            self.assertEqual(candidate["library_name"], product_line)
            self.assertEqual(candidate["middle_path"], "")
            self.assertEqual(candidate["version_names"], ["20260917", "20261001"])
            self.assertEqual(candidate["root_abs"], str(raw / "Metax" / product_line))
            self.assertEqual(candidate["view_types"], ["CDL", "LEF"])

    def test_flat_product_line_is_a_single_self_delivery(self):
        with tempfile.TemporaryDirectory() as temp:
            raw = Path(temp) / "raw"
            product_line = raw / "Vendor_A" / "flat_ip"
            (product_line / "LEF").mkdir(parents=True)
            (product_line / "LEF" / "flat.lef").touch()

            result = discover_raw_libraries(raw)

            self.assertEqual(len(result), 1)
            self.assertEqual(result[0]["library_id"], "Vendor_A.flat_ip")
            self.assertEqual(result[0]["version_count"], 1)
            self.assertEqual(result[0]["versions"][0]["id"], "flat_ip")
            self.assertEqual(result[0]["versions"][0]["path"], str(product_line))
            self.assertEqual(result[0]["view_types"], ["LEF"])

    def test_deep_view_scan_ignores_hack_lef_and_drops_all_other_candidate(self):
        with tempfile.TemporaryDirectory() as temp:
            raw = Path(temp) / "raw"
            version = raw / "Vendor_A" / "real_ip" / "v01"
            deep_lef = version / "payload" / "release" / "views" / "LEF"
            deep_lef.mkdir(parents=True)
            (deep_lef / "core.lef").touch()
            hack = version / "hack_lef"
            hack.mkdir()
            (hack / "debug.gds").touch()
            other = raw / "Vendor_A" / "docs_only" / "v01"
            other.mkdir(parents=True)
            (other / "readme.xyz").touch()

            result = discover_raw_libraries(raw)

            self.assertEqual([item["library_id"] for item in result], ["Vendor_A.real_ip"])
            self.assertEqual(result[0]["view_types"], ["LEF"])

    def test_deep_view_scan_reaches_max_depth(self):
        with tempfile.TemporaryDirectory() as temp:
            raw = Path(temp) / "raw"
            view = raw / "Vendor_A" / "deep_ip" / "v01"
            for part in ("one", "two", "three", "four", "five"):
                view = view / part
            view = view / "LEF"
            view.mkdir(parents=True)
            (view / "core.lef").touch()

            result = discover_raw_libraries(raw)

            self.assertEqual(len(result), 1)
            self.assertEqual(result[0]["view_types"], ["LEF"])

    def test_nested_source_package_views_stay_under_product_line(self):
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

    def test_discovers_vendor_product_line_and_preserves_views(self):
        with tempfile.TemporaryDirectory() as temp:
            raw = Path(temp) / "raw"
            version = raw / "Vendor_D" / "sram_256x16" / "20261024_drop"
            (version / "LIB" / "NLDM").mkdir(parents=True)
            (version / "LIB" / "NLDM" / "sram.lib.gz").touch()
            (version / "LEF").mkdir()
            (version / "LEF" / "sram.lef").touch()

            result = discover_raw_libraries(raw)

            self.assertEqual(len(result), 1)
            candidate = result[0]
            self.assertEqual(candidate["vendor"], "Vendor_D")
            self.assertEqual(candidate["middle_path"], "")
            self.assertEqual(candidate["library_name"], "sram_256x16")
            self.assertEqual(candidate["library_id"], "Vendor_D.sram_256x16")
            self.assertEqual(candidate["versions"][0]["id"], "20261024_drop")
            self.assertEqual(candidate["versions"][0]["views"], ["LEF", "LIB"])

    def test_ignores_non_library_trees_and_nested_product_lines(self):
        with tempfile.TemporaryDirectory() as temp:
            raw = Path(temp) / "raw"
            # These files resemble deliveries, but are documentation/report noise.
            for directory in ("Vendor_E/reports/run1", "Vendor_E/catalog/snapshot"):
                path = raw / directory
                path.mkdir(parents=True)
                (path / "noise.lef").touch()
            # Product candidates are only immediate Vendor children; nested IPs stay out of scope.
            version = raw / "Vendor_E" / "group" / "ip_e" / "20261024"
            (version / "LEF").mkdir(parents=True)
            (version / "LEF" / "macro.lef").touch()

            result = discover_raw_libraries(raw)

            self.assertEqual(result, [])

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
            version = root / "Vendor_F" / "phy_ip" / "20261024_drop"
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
            self.assertEqual(candidate["middle_path"], "")
            self.assertEqual(candidate["version_count"], 1)
            self.assertEqual(candidate["version_names"], ["20261024_drop"])
            self.assertEqual(candidate["view_types"], ["LEF", "LIB"])
            self.assertEqual(candidate["example_versions"], ["20261024_drop"])
            self.assertEqual(candidate["root_abs"], str(root / "Vendor_F" / "phy_ip"))
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

    def test_hack_lef_directory_does_not_contribute_view_types(self):
        with tempfile.TemporaryDirectory() as temp:
            raw = Path(temp) / "raw"
            version = raw / "Vendor_A" / "phy_ip" / "v01"
            (version / "LEF").mkdir(parents=True)
            (version / "LEF" / "core.lef").touch()
            (version / "hack_lef").mkdir()
            (version / "hack_lef" / "debug.gds").touch()

            result = discover_raw_libraries(raw)

            self.assertEqual(result[0]["view_types"], ["LEF"])


if __name__ == "__main__":
    unittest.main()
