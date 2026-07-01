from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


class LibraryRegistryTest(unittest.TestCase):
    def test_discover_prunes_at_library_roots_and_ignores_digit_only_names(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            raw = Path(td) / "raw"
            asap7 = raw / "vendor_A" / "openroad_asap7"
            gf180 = raw / "vendor_A" / "openroad_gf180"
            sky130ram = raw / "vendor_C" / "openroad_sky130ram"
            for version in ["20260624_asap7", "20260627_asap7"]:
                (asap7 / version / "asap7_source_package").mkdir(parents=True)
            for version in ["20260612_gf180", "20260623_gf180_update"]:
                (gf180 / version / "gf180_source_package" / "gds" / "gf180mcu_6LM_1TM_9K").mkdir(parents=True)
            for version in ["20260619_sky130ram", "20260626_sky130ram_update"]:
                (sky130ram / version / "sky130ram_source_package" / "sky130_sram_1rw1r_128x256_8").mkdir(parents=True)

            from lib_guard.library_registry import discover_library_candidates

            candidates = discover_library_candidates(raw, default_status="OK")
            ids = [item.library_id for item in candidates]

            self.assertEqual(
                ids,
                [
                    "vendor_A_openroad_asap7",
                    "vendor_A_openroad_gf180",
                    "vendor_C_openroad_sky130ram",
                ],
            )
            self.assertNotIn("vendor_A", ids)
            self.assertFalse(any("source_package" in item for item in ids))

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


if __name__ == "__main__":
    unittest.main()
