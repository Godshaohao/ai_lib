from __future__ import annotations

import unittest


class ArchitectureBoundariesTest(unittest.TestCase):
    def test_view_type_mapping_is_canonical_for_ui_and_release(self) -> None:
        from lib_guard.view_types import canonical_file_type, canonical_view_type, release_view_dir

        self.assertEqual(canonical_file_type("lib"), "liberty")
        self.assertEqual(canonical_view_type("systemverilog"), "rtl_model")
        self.assertEqual(canonical_view_type("lydrc"), "tech_flow_config")
        self.assertEqual(canonical_view_type("md"), "doc_evidence")
        self.assertEqual(release_view_dir("lef"), "LEF")
        self.assertEqual(release_view_dir("systemverilog"), "RTL")
        self.assertEqual(release_view_dir("liberty"), "LIB")

    def test_package_classifier_uses_same_type_mapping(self) -> None:
        from lib_guard.package.classifier import file_type_to_view

        self.assertEqual(file_type_to_view("systemverilog"), "rtl")
        self.assertEqual(file_type_to_view("lib"), "lib")
        self.assertEqual(file_type_to_view("md"), "doc")
        self.assertEqual(file_type_to_view("lydrc"), "tech")

    def test_path_match_evidence_is_explainable_and_not_rename_truth(self) -> None:
        from lib_guard.diff.file_match import default_path_match_evidence, path_match_evidence

        evidence = path_match_evidence(
            {
                "added": ["new_root/lef/core.lef"],
                "removed": ["old_root/lef/core.lef"],
                "renamed_or_moved": [
                    {
                        "old": "old_root/cdl/a.sp",
                        "new": "new_root/cdl/a.sp",
                        "reason": "hash_match",
                    }
                ],
            }
        )

        self.assertEqual(evidence["new_root/cdl/a.sp"]["match_status"], "matched_move")
        self.assertEqual(evidence["new_root/cdl/a.sp"]["match_kind"], "evidence")
        self.assertEqual(evidence["new_root/cdl/a.sp"]["match_confidence"], "high")
        self.assertEqual(evidence["new_root/cdl/a.sp"]["match_reason"], "hash_match")
        self.assertEqual(evidence["new_root/lef/core.lef"]["match_status"], "candidate_match")
        self.assertEqual(evidence["new_root/lef/core.lef"]["match_confidence"], "low")
        self.assertNotIn("rename", evidence["new_root/lef/core.lef"]["match_reason"].lower())

        unmatched = default_path_match_evidence("added", "new_root/lib/a.lib")
        self.assertEqual(unmatched["match_status"], "unmatched")
        self.assertEqual(unmatched["match_kind"], "evidence")
        self.assertEqual(unmatched["match_confidence"], "none")


if __name__ == "__main__":
    unittest.main()
