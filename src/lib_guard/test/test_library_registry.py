from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


class LibraryRegistryTest(unittest.TestCase):
    def test_discover_uses_sibling_cohorts_and_suppresses_parent_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            raw = Path(td) / "raw"
            asap7 = raw / "vendor_A" / "openroad_asap7"
            gf180 = raw / "vendor_A" / "openroad_gf180"
            sky130ram = raw / "vendor_C" / "openroad_sky130ram"
            for version in ["20260624_asap7", "20260627_asap7"]:
                (asap7 / version / "asap7_source_package").mkdir(parents=True)
                (asap7 / version / "asap7_source_package" / "tech.lef").write_text("MACRO A\n", encoding="utf-8")
            for version in ["20260612_gf180", "20260623_gf180_update"]:
                (gf180 / version / "gf180_source_package" / "gds" / "gf180mcu_6LM_1TM_9K").mkdir(parents=True)
                (gf180 / version / "gf180_source_package" / "gds" / "gf180mcu_6LM_1TM_9K" / "top.gds").write_text("gds\n", encoding="utf-8")
            for version in ["20260619_sky130ram", "20260626_sky130ram_update"]:
                (sky130ram / version / "sky130ram_source_package" / "sky130_sram_1rw1r_128x256_8").mkdir(parents=True)
                (sky130ram / version / "sky130ram_source_package" / "sky130_sram_1rw1r_128x256_8" / "macro.lib").write_text("library(x){}\n", encoding="utf-8")

            from lib_guard.library_registry import discover_library_candidates

            candidates = discover_library_candidates(raw, default_status="OK")
            active_ids = [item.library_id for item in candidates if item.status == "REVIEW"]

            self.assertEqual(
                active_ids,
                [
                    "vendor_A_openroad_asap7",
                    "vendor_A_openroad_gf180",
                    "vendor_C_openroad_sky130ram",
                ],
            )
            self.assertEqual({item.status for item in candidates if item.library_id in active_ids}, {"REVIEW"})
            self.assertFalse(any(item.library_id == "vendor_A" for item in candidates))
            self.assertFalse(any("source_package" in item for item in active_ids))
            self.assertFalse(any(item.status == "IGNORE" for item in candidates))

    def test_discover_deduplicates_same_resolved_library_root(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            raw = Path(td) / "raw"
            root = raw / "vendor_A" / "openroad_asap7"
            for version in ["20260624_asap7", "20260627_asap7"]:
                view_dir = root / version / "lef"
                view_dir.mkdir(parents=True)
                (view_dir / "tech.lef").write_text("MACRO A\n", encoding="utf-8")

            from lib_guard.library_registry import LibraryCandidate, _suppress_ancestor_candidates

            duplicate = LibraryCandidate(
                status="REVIEW",
                library_id="vendor_A_openroad_asap7",
                root_abs=str(root.resolve()),
                display_name="openroad_asap7",
                vendor="vendor_A",
                middle_path="",
                version_count=2,
                example_versions=["20260624_asap7", "20260627_asap7"],
                confidence=0.8,
                reason="test",
            )
            parent = LibraryCandidate(
                status="REVIEW",
                library_id="vendor_A",
                root_abs=str((raw / "vendor_A").resolve()),
                display_name="vendor_A",
                vendor="vendor_A",
                middle_path="",
                version_count=2,
                example_versions=["openroad_asap7"],
                confidence=0.6,
                reason="test",
            )

            candidates = _suppress_ancestor_candidates([parent, duplicate, duplicate])

            self.assertEqual([item.library_id for item in candidates], ["vendor_A_openroad_asap7"])

    def test_discover_does_not_promote_top_level_vendor_as_library(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            raw = Path(td) / "raw"
            vendor = raw / "Vendor_A"
            for version in ["20251213_ANA_IP_N7_Final_Release", "20260306_Analog_IP_P3_Final_Release_Maintenance"]:
                view_dir = vendor / version / "payload" / "lef"
                view_dir.mkdir(parents=True)
                (view_dir / "macro.lef").write_text("MACRO X\n", encoding="utf-8")

            from lib_guard.library_registry import discover_library_candidates

            candidates = discover_library_candidates(raw, max_depth=4)

            self.assertFalse(candidates)

    def test_discover_accepts_arbitrary_instance_names_when_cohort_has_view_hints(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            raw = Path(td) / "raw"
            root = raw / "vendor_X" / "custom_ip"
            for instance in ["R1P0", "revA", "drop_7", "golden"]:
                view_dir = root / instance / "payload" / "lef"
                view_dir.mkdir(parents=True)
                (view_dir / f"{instance}.lef").write_text("MACRO X\n", encoding="utf-8")
            (root / "latest_clean" / "docs").mkdir(parents=True)

            from lib_guard.library_registry import discover_library_candidates

            candidates = discover_library_candidates(raw)
            active = [item for item in candidates if item.status == "REVIEW"]

            self.assertEqual([item.library_id for item in active], ["vendor_X_custom_ip"])
            self.assertEqual(active[0].version_count, 4)
            self.assertIn("cohort_core_views", active[0].reason)
            self.assertIn("R1P0", active[0].example_versions)

    def test_discover_does_not_promote_view_or_source_package_directories(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            raw = Path(td) / "raw"
            root = raw / "vendor_Y" / "macro"
            for instance in ["BETA_3", "2024Q4"]:
                (root / instance / "source_package" / "lef").mkdir(parents=True)
                (root / instance / "source_package" / "lef" / "macro.lef").write_text("MACRO Y\n", encoding="utf-8")
                (root / instance / "source_package" / "lib").mkdir(parents=True)
                (root / instance / "source_package" / "lib" / "macro.lib").write_text("library(y){}\n", encoding="utf-8")

            from lib_guard.library_registry import discover_library_candidates

            candidates = discover_library_candidates(raw)
            active_ids = [item.library_id for item in candidates if item.status == "REVIEW"]

            self.assertEqual(active_ids, ["vendor_Y_macro"])
            self.assertFalse(any(part in item for item in active_ids for part in ["source_package", "_lef", "_lib"]))

    def test_discover_stops_at_version_dirs_and_does_not_promote_deep_views(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            raw = Path(td) / "raw"
            root = raw / "Vendor_A" / "Analog_IP"
            releases = [
                "20251213_ANA_IP_N7_Final_Release",
                "20260306_Analog_IP_P3_Final_Release_Maintenance",
            ]
            for release in releases:
                phys = (
                    root
                    / release
                    / f"UVIP_{release}_MX"
                    / "decap_soc"
                    / "MA_DECAP_H"
                    / "phys_ver"
                )
                phys.mkdir(parents=True)
                (phys / "macro.lef").write_text("MACRO X\n", encoding="utf-8")
                for corner_drop in ["R1", "R2"]:
                    nested = phys / corner_drop
                    nested.mkdir()
                    (nested / "macro.lef").write_text("MACRO X\n", encoding="utf-8")
                dft = root / release / f"UVIP_{release}_MX" / "fnpll" / "ma_fnpll" / "dft"
                dft.mkdir(parents=True)
                (dft / "top.v").write_text("module top; endmodule\n", encoding="utf-8")
                for corner_drop in ["R1", "R2"]:
                    nested = dft / corner_drop
                    nested.mkdir()
                    (nested / "top.v").write_text("module top; endmodule\n", encoding="utf-8")

            from lib_guard.library_registry import discover_to_files

            out = Path(td) / "candidates.tsv"
            result = discover_to_files(raw, list_out=out, max_depth=8, max_dirs=1000)
            text = out.read_text(encoding="utf-8")
            data_lines = [line for line in text.splitlines() if line and not line.startswith("#")]
            data_text = "\n".join(data_lines)

            self.assertEqual(result["status"], "PASS")
            self.assertIn("Vendor_A_Analog_IP", data_text)
            self.assertNotIn("phys_ver", data_text)
            self.assertNotIn("\tdft\t", data_text)
            self.assertLess(result["visited_dirs"], 20)

    def test_apply_writes_dotted_formal_ids_and_underscore_aliases(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            raw = Path(td) / "raw"
            out = Path(td) / "library_catalog.yml"
            for version in ["20260624_asap7", "20260627_asap7"]:
                (raw / "vendor_A" / "openroad_asap7" / version).mkdir(parents=True)
            for version in ["20260619_sky130ram", "20260626_sky130ram_update"]:
                (raw / "vendor_C" / "openroad_sky130ram" / version).mkdir(parents=True)

            rows = [
                {
                    "status": "OK",
                    "library_id": "vendor_A_openroad_asap7",
                    "root_abs": str(raw / "vendor_A" / "openroad_asap7"),
                    "display_name": "openroad_asap7",
                    "vendor": "vendor_A",
                    "middle_path": "",
                },
                {
                    "status": "OK",
                    "library_id": "vendor_C_openroad_sky130ram",
                    "root_abs": str(raw / "vendor_C" / "openroad_sky130ram"),
                    "display_name": "openroad_sky130ram",
                    "vendor": "vendor_C",
                    "middle_path": "",
                },
            ]

            from lib_guard.library_registry import write_library_catalog
            from lib_guard.discovery import load_library_map

            result = write_library_catalog(raw, rows, out, library_type="ip")
            refs = load_library_map(raw, {"library_map": str(out)}, out)
            ids = [ref.library_id for ref in refs]
            aliases = {ref.library_id: set(ref.aliases) for ref in refs}

            self.assertEqual(result["status"], "PASS")
            self.assertEqual(ids, ["vendor_A.openroad_platform.openroad_asap7", "vendor_C.openroad_platform.openroad_sky130ram"])
            self.assertIn("vendor_A_openroad_asap7", aliases["vendor_A.openroad_platform.openroad_asap7"])
            self.assertIn("openroad_asap7", aliases["vendor_A.openroad_platform.openroad_asap7"])

    def test_apply_rejects_overlapping_ok_library_roots(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            raw = Path(td) / "raw"
            parent = raw / "vendor_A"
            child = parent / "openroad_asap7"
            for version in ["20260624_asap7", "20260627_asap7"]:
                (child / version).mkdir(parents=True)
            out = Path(td) / "library_catalog.yml"
            rows = [
                {
                    "status": "OK",
                    "library_id": "vendor_A",
                    "root_abs": str(parent),
                    "display_name": "vendor_A",
                    "vendor": "vendor_A",
                    "middle_path": "",
                },
                {
                    "status": "OK",
                    "library_id": "vendor_A.openroad_platform.openroad_asap7",
                    "root_abs": str(child),
                    "display_name": "openroad_asap7",
                    "vendor": "vendor_A",
                    "middle_path": "openroad_platform",
                },
            ]

            from lib_guard.library_registry import write_library_catalog

            result = write_library_catalog(raw, rows, out, library_type="ip")

            self.assertEqual(result["status"], "FAILED")
            self.assertTrue(any("overlap" in error for error in result["errors"]))
            self.assertFalse(out.exists())

    def test_apply_rejects_source_package_as_formal_library_root(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            raw = Path(td) / "raw"
            package_root = raw / "vendor_A" / "openroad_asap7" / "20260627_asap7" / "asap7_source_package"
            package_root.mkdir(parents=True)
            out = Path(td) / "library_catalog.yml"
            rows = [
                {
                    "status": "OK",
                    "library_id": "vendor_A.openroad_platform.asap7_source_package",
                    "root_abs": str(package_root),
                    "display_name": "asap7_source_package",
                    "vendor": "vendor_A",
                    "middle_path": "openroad_platform",
                }
            ]

            from lib_guard.library_registry import write_library_catalog

            result = write_library_catalog(raw, rows, out, library_type="ip")

            self.assertEqual(result["status"], "FAILED")
            self.assertTrue(any("not a library root" in error for error in result["errors"]))
            self.assertFalse(out.exists())

    def test_library_add_writes_stable_registry_without_discovery(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            raw = Path(td) / "raw"
            root = raw / "vendor_A" / "openroad_asap7"
            root.mkdir(parents=True)
            registry = Path(td) / "config" / "library_registry.tsv"
            catalog = Path(td) / "config" / "library_catalog.yml"

            from lib_guard.library_registry import add_library_to_registry, apply_list_to_catalog
            from lib_guard.discovery import load_library_map

            result = add_library_to_registry(
                raw,
                registry_path=registry,
                library_id="vendor_A.openroad_platform.openroad_asap7",
                root_abs=root,
                display_name="openroad_asap7",
                vendor="vendor_A",
                middle_path="",
            )
            self.assertEqual(result["status"], "PASS")
            text = registry.read_text(encoding="utf-8")
            self.assertIn("vendor_A.openroad_platform.openroad_asap7", text)

            apply_result = apply_list_to_catalog(raw, list_path=registry, out_path=catalog, library_type="ip")
            refs = load_library_map(raw, {"library_map": str(catalog)}, catalog)
            self.assertEqual(apply_result["selected"], 1)
            self.assertEqual([ref.library_id for ref in refs], ["vendor_A.openroad_platform.openroad_asap7"])

    def test_library_apply_blocks_accidental_catalog_shrink(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            raw = Path(td) / "raw"
            ucie = raw / "vendor_A" / "ucie"
            pcie = raw / "vendor_A" / "pcie"
            for root in [ucie, pcie]:
                root.mkdir(parents=True)
            catalog = Path(td) / "config" / "library_catalog.yml"
            catalog.parent.mkdir()
            full_registry = Path(td) / "full_registry.tsv"
            single_registry = Path(td) / "single_registry.tsv"
            header = "status\tlibrary_id\troot_abs\tdisplay_name\tvendor\tmiddle_path\n"
            full_registry.write_text(
                header
                + f"OK\tvendor_A.ucie\t{ucie}\tucie\tvendor_A\t\n"
                + f"OK\tvendor_A.pcie\t{pcie}\tpcie\tvendor_A\t\n",
                encoding="utf-8",
            )
            single_registry.write_text(
                header
                + f"OK\tvendor_A.ucie\t{ucie}\tucie\tvendor_A\t\n",
                encoding="utf-8",
            )

            from lib_guard.library_registry import apply_list_to_catalog
            from lib_guard.discovery import load_library_map

            first = apply_list_to_catalog(raw, list_path=full_registry, out_path=catalog, library_type="ip")
            blocked = apply_list_to_catalog(raw, list_path=single_registry, out_path=catalog, library_type="ip")
            refs = load_library_map(raw, {"library_map": str(catalog)}, catalog)

            self.assertEqual(first["status"], "PASS")
            self.assertEqual(blocked["status"], "FAILED")
            self.assertEqual(blocked["reason"], "library_catalog_shrink_guard")
            self.assertEqual(blocked["previous_library_count"], 2)
            self.assertEqual(blocked["new_library_count"], 1)
            self.assertEqual({ref.library_id for ref in refs}, {"vendor_A.pcie", "vendor_A.ucie"})

    def test_library_accept_merges_only_approved_candidates_into_registry(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            raw = Path(td) / "raw"
            good = raw / "vendor_A" / "openroad_asap7"
            review = raw / "vendor_A" / "openroad_gf180"
            ignored = raw / "vendor_A"
            for path in [good, review, ignored]:
                path.mkdir(parents=True, exist_ok=True)
            candidates = Path(td) / "candidates.tsv"
            registry = Path(td) / "library_registry.tsv"
            candidates.write_text(
                "\n".join(
                    [
                        "status\tlibrary_id\troot_abs\tdisplay_name\tvendor\tmiddle_path",
                        f"OK\tvendor_A_openroad_asap7\t{good}\topenroad_asap7\tvendor_A\t",
                        f"REVIEW\tvendor_A_openroad_gf180\t{review}\topenroad_gf180\tvendor_A\t",
                        f"IGNORE\tvendor_A\t{ignored}\tvendor_A\tvendor_A\t",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            from lib_guard.library_registry import accept_candidates_to_registry, read_library_list

            result = accept_candidates_to_registry(raw, candidates_path=candidates, registry_path=registry)
            rows = read_library_list(registry)

            self.assertEqual(result["accepted"], 1)
            self.assertEqual([row["library_id"] for row in rows], ["vendor_A_openroad_asap7"])
            self.assertEqual(rows[0]["status"], "OK")

    def test_discover_writes_candidate_snapshot_without_touching_registry(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            raw = Path(td) / "raw"
            root = raw / "vendor_X" / "custom_ip"
            for version in ["R1", "R2"]:
                view = root / version / "lef"
                view.mkdir(parents=True)
                (view / "macro.lef").write_text("MACRO X\n", encoding="utf-8")
            registry = Path(td) / "config" / "library_registry.tsv"
            registry.parent.mkdir()
            registry.write_text(
                "status\tlibrary_id\troot_abs\tdisplay_name\tvendor\tmiddle_path\n"
                f"OK\tvendor_old.ip\t{raw}\told\tvendor_old\t\n",
                encoding="utf-8",
            )
            candidates = Path(td) / "config" / "library_candidates" / "latest.tsv"

            from lib_guard.library_registry import discover_to_files

            discover_to_files(raw, list_out=candidates)

            self.assertTrue(candidates.exists())
            self.assertIn("vendor_X_custom_ip", candidates.read_text(encoding="utf-8"))
            self.assertIn("vendor_old.ip", registry.read_text(encoding="utf-8"))

    def test_discover_limits_large_raw_tree_and_reports_truncation(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            raw = Path(td) / "raw"
            for idx in range(40):
                noisy = raw / f"vendor_{idx:02d}" / f"misc_{idx:02d}"
                noisy.mkdir(parents=True)
                (noisy / "README.txt").write_text("not a library\n", encoding="utf-8")

            from lib_guard.library_registry import discover_to_files

            out = Path(td) / "candidates.tsv"
            result = discover_to_files(raw, list_out=out, max_dirs=10, max_candidates=5)

            self.assertEqual(result["status"], "PASS")
            self.assertLessEqual(result["visited_dirs"], 10)
            self.assertTrue(result["truncated"])
            self.assertTrue(any("max_dirs" in warning for warning in result["warnings"]))


if __name__ == "__main__":
    unittest.main()
