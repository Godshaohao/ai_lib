from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


class EffectivePointerTest(unittest.TestCase):
    def test_normalize_effective_ref_uses_canonical_prefixes(self) -> None:
        from lib_guard.effective.pointer import normalize_effective_ref

        self.assertEqual(normalize_effective_ref("stable_20250608"), "raw:stable_20250608")
        self.assertEqual(normalize_effective_ref("raw:stable_20250608"), "raw:stable_20250608")
        self.assertEqual(normalize_effective_ref("effective:ucie_effective_20260627_01"), "effective:ucie_effective_20260627_01")
        self.assertEqual(normalize_effective_ref(""), "")

    def test_latest_effective_ref_for_library_prefers_summary_and_reads_legacy(self) -> None:
        from lib_guard.effective.pointer import latest_effective_ref_for_library

        self.assertEqual(
            latest_effective_ref_for_library({"summary": {"latest_effective_ref": "effective:E2"}, "current_version": "stale_raw"}),
            "effective:E2",
        )
        self.assertEqual(
            latest_effective_ref_for_library({"current_version": "stable_20250608"}),
            "raw:stable_20250608",
        )
        self.assertEqual(
            latest_effective_ref_for_library({"current_effective_version": "E1_20260624"}),
            "effective:E1_20260624",
        )

    def test_write_latest_effective_ref_only_writes_library_summary(self) -> None:
        from lib_guard.effective.pointer import write_latest_effective_ref

        catalog = {
            "libraries": [
                {
                    "library_id": "ip/ucie",
                    "library_name": "ucie",
                    "latest_effective_ref": "legacy",
                    "summary": {"current_version": "old"},
                }
            ]
        }

        updated = write_latest_effective_ref(catalog, "ip/ucie", "effective:E3")
        lib = updated["libraries"][0]

        self.assertEqual(lib["summary"]["latest_effective_ref"], "effective:E3")
        self.assertEqual(lib["latest_effective_ref"], "legacy")
        self.assertEqual(lib["summary"]["current_version"], "old")
        self.assertNotIn("current_effective_ref", lib)


if __name__ == "__main__":
    unittest.main()
