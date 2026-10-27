import tempfile
import unittest
from pathlib import Path


class BatchLefReviewTests(unittest.TestCase):
    def test_ten_pairs_one_failure_keeps_nine_independent_results(self):
        from lib_guard.batch_lef_review import analyze_pairs
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            old = root / "old.lef"
            new = root / "new.lef"
            for path in (old, new):
                path.write_text("VERSION 5.8 ;\nMACRO A\nEND A\nEND LIBRARY\n", encoding="utf-8")
            pairs = [{"pair_id": f"pair_{index}", "old_file": str(old),
                      "new_file": str(root / "missing.lef" if index == 4 else new)} for index in range(10)]
            result = analyze_pairs(pairs, root / "evidence")
            self.assertEqual(result["status"], "INCOMPLETE")
            self.assertEqual(sum(item["execution_status"] == "COMPLETE" for item in result["pairs"]), 9)
            self.assertEqual(len(list((root / "evidence").glob("*.json"))), 9)

    def test_failed_pair_preserves_other_pair_and_evidence(self):
        from lib_guard.batch_lef_review import analyze_pairs
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            old = root / "old.lef"
            new = root / "new.lef"
            for path in (old, new):
                path.write_text("VERSION 5.8 ;\nMACRO A\nEND A\nEND LIBRARY\n", encoding="utf-8")
            result = analyze_pairs([
                {"pair_id": "valid", "old_file": str(old), "new_file": str(new)},
                {"pair_id": "missing", "old_file": str(old), "new_file": str(root / "missing.lef")},
            ], root / "evidence")
            self.assertEqual(result["status"], "INCOMPLETE")
            self.assertEqual(result["pairs"][0]["execution_status"], "COMPLETE")
            self.assertEqual(result["pairs"][1]["execution_status"], "FAILED")
            self.assertTrue((root / "evidence" / result["pairs"][0]["evidence_ref"]).is_file())
            self.assertIsNone(result["pairs"][1]["evidence_ref"])

    def test_duplicate_pair_ids_are_rejected(self):
        from lib_guard.batch_lef_review import analyze_pairs
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(ValueError):
                analyze_pairs([{"pair_id": "same"}, {"pair_id": "same"}], Path(temp))
