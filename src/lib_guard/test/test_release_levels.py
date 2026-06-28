from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def _scan(root: Path, out: Path, *, mode: str, version: str = "v1", parse_file_types: list[str] | None = None) -> None:
    from lib_guard.scan.scanner import ScanRunner

    ScanRunner(
        SimpleNamespace(
            root_path=str(root),
            out_dir=str(out),
            library_type="ip",
            library_name="demo",
            version=version,
            scan_mode=mode,
            scan_id=f"{mode.upper()}_{version}",
            state_dir=str(out.parent / "state"),
            cache_dir=str(out.parent / "cache"),
            skip_cache=True,
            no_cache=True,
            no_progress=True,
            progress_interval=1,
            parse_jobs=1,
            parse_file_types=parse_file_types,
            tool_version="0.5.0",
            schema_version="1.0",
        )
    ).run()


def _write_diff(out: Path, *, diff_level: str, status: str = "SAME", issues: list[dict] | None = None) -> None:
    deep = diff_level == "P2"
    out.mkdir(parents=True, exist_ok=True)
    (out / "diff_summary.json").write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "status": status,
                "risk_level": "info" if status != "BLOCK" else "blocker",
                "diff_level": diff_level,
                "deep_diff_completed": deep,
                "sufficient_for_release_levels": ["L0", "L1", "L2"] if deep else ["L0", "L1"],
                "not_sufficient_for_release_levels": [] if deep else ["L2"],
                "sufficient_for_aliases": ["stage", "current", "approved"] if deep else ["stage", "current"],
                "not_sufficient_for_aliases": [] if deep else ["approved"],
            }
        ),
        encoding="utf-8",
    )
    (out / "diff_issues.json").write_text(json.dumps({"schema_version": "1.0", "issues": issues or []}), encoding="utf-8")


class ReleaseLevelTest(unittest.TestCase):
    def test_inventory_scan_is_l0_and_only_stage_alias_is_allowed(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            root = base / "raw"
            scan = base / "scan"
            root.mkdir()
            (root / "top.v").write_text("module top(input a); endmodule\n", encoding="utf-8")
            (root / "README.md").write_text("demo readme\n", encoding="utf-8")

            _scan(root, scan, mode="inventory")

            from lib_guard.release.checker import check_release_scan

            readiness = json.loads((scan / "summary" / "release_readiness.json").read_text(encoding="utf-8"))
            self.assertEqual(readiness["release_level_candidate"], "L0")
            self.assertEqual(readiness["validation_depth"], "inventory")
            self.assertIn("stage", readiness["allowed_aliases"])
            self.assertIn("current", readiness["blocked_aliases"])
            self.assertIn("approved", readiness["blocked_aliases"])
            self.assertIn("doc_summary", readiness)

            stage = check_release_scan(scan, alias="stage")
            current = check_release_scan(scan, alias="current")
            approved = check_release_scan(scan, alias="approved")

            self.assertTrue(stage["allowed_to_apply"])
            self.assertEqual(stage["required_release_level"], "L0")
            self.assertFalse(current["allowed_to_apply"])
            self.assertEqual(current["release_check_status"], "BLOCK")
            self.assertIn("current requires L1 release level", current["block_reasons"])
            self.assertFalse(approved["allowed_to_apply"])
            self.assertIn("approved requires L2 release level", approved["block_reasons"])

    def test_current_alias_accepts_l1_with_p0_diff_and_approved_requires_p2(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            root = base / "raw"
            scan = base / "scan"
            diff = base / "diff_p0"
            root.mkdir()
            (root / "top.v").write_text("module top(input a, output y); assign y = a; endmodule\n", encoding="utf-8")
            (root / "README.md").write_text("demo readme\n", encoding="utf-8")
            (root / "release_note.txt").write_text("release note for v1\n", encoding="utf-8")

            _scan(root, scan, mode="signature")
            _write_diff(diff, diff_level="P0")

            from lib_guard.release.checker import check_release_scan

            current = check_release_scan(scan, diff_dir=diff, alias="current")
            approved = check_release_scan(scan, diff_dir=diff, alias="approved")

            self.assertEqual(current["actual_release_level"], "L1")
            self.assertEqual(current["diff_level"], "P0")
            self.assertTrue(current["allowed_to_apply"])
            self.assertFalse(approved["allowed_to_apply"])
            self.assertIn("approved requires P2 deep diff", approved["block_reasons"])

    def test_approved_alias_accepts_l2_when_p2_diff_is_present(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            root = base / "raw"
            scan = base / "scan"
            diff = base / "diff_p2"
            root.mkdir()
            (root / "top.v").write_text("module top(input a, output y); assign y = a; endmodule\n", encoding="utf-8")
            (root / "README.md").write_text("demo readme\n", encoding="utf-8")
            (root / "release_note.txt").write_text("release note for v1\n", encoding="utf-8")

            _scan(root, scan, mode="signature", parse_file_types=["verilog"])
            from lib_guard.summary.readiness import DEFAULT_VALIDATION_LEVELS, build_release_readiness

            strict_policy = {
                "required_views": {"ip": ["verilog"]},
                "validation_levels": {**DEFAULT_VALIDATION_LEVELS, "verilog": "parsed_required"},
            }
            (scan / "summary" / "release_readiness.json").write_text(
                json.dumps(build_release_readiness(scan, policy_path=strict_policy), indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            _write_diff(diff, diff_level="P2")

            from lib_guard.release.checker import check_release_scan

            approved = check_release_scan(scan, diff_dir=diff, alias="approved")

            self.assertEqual(approved["required_release_level"], "L2")
            self.assertEqual(approved["actual_release_level"], "L2")
            self.assertEqual(approved["diff_level"], "P2")
            self.assertTrue(approved["allowed_to_apply"])

    def test_release_link_apply_is_blocked_by_alias_gate(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            root = base / "raw"
            scan = base / "scan"
            diff = base / "diff_p0"
            release_root = base / "release_root"
            root.mkdir()
            (root / "top.v").write_text("module top(input a, output y); assign y = a; endmodule\n", encoding="utf-8")
            (root / "README.md").write_text("demo readme\n", encoding="utf-8")
            (root / "release_note.txt").write_text("release note for v1\n", encoding="utf-8")

            _scan(root, scan, mode="signature")
            _write_diff(diff, diff_level="P0")

            from lib_guard.release.linker import link_release_from_scan

            result = link_release_from_scan(scan, release_root, alias="approved", dry_run=False, diff_dir=diff)

            self.assertEqual(result["status"], "BLOCKED")
            self.assertFalse(result["release_check"]["allowed_to_apply"])
            self.assertIn("approved requires P2 deep diff", result["block_reasons"])
            self.assertFalse((release_root / "ip" / "demo" / "approved").exists())


if __name__ == "__main__":
    unittest.main()
