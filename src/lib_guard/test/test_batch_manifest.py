from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path


class BatchManifestTest(unittest.TestCase):
    def test_manifest_progress_result_failed_and_rerun_script_are_written(self) -> None:
        from lib_guard.batch.manifest import (
            init_progress,
            make_batch_run_dir,
            update_progress,
            write_failed,
            write_rerun_failed_csh,
            write_result,
            write_selection_manifest,
        )

        with tempfile.TemporaryDirectory() as td:
            run_dir = make_batch_run_dir(td, "scan", run_id="scan_manual")
            selection = write_selection_manifest(
                run_dir,
                {
                    "run_id": "scan_manual",
                    "batch_type": "scan",
                    "selected": [{"library_name": "ucie", "version_id": "stable_20250608"}],
                    "skipped": [{"library_name": "ram", "version_id": "old", "reason": "stage_filter_mismatch"}],
                },
            )
            init_progress(run_dir, total=2, run_id="scan_manual")
            update_progress(run_dir, {"library_name": "ucie", "version_id": "stable_20250608", "status": "PASS", "exit_code": 0})
            failure = {"library_name": "ucie", "version_id": "bad_20250609", "status": "FAILED", "exit_code": 2}
            update_progress(run_dir, failure)
            write_failed(run_dir, [failure])
            rerun = write_rerun_failed_csh(run_dir, [failure], "scan")
            write_result(run_dir, {"status": "FAILED", "selected": 2, "failures": [failure]})

            manifest_data = json.loads(selection.read_text(encoding="utf-8"))
            progress_data = json.loads((run_dir / "progress.json").read_text(encoding="utf-8"))
            failed_data = json.loads((run_dir / "failed.json").read_text(encoding="utf-8"))
            result_data = json.loads((run_dir / "result.json").read_text(encoding="utf-8"))

            self.assertEqual(manifest_data["schema_version"], "batch_selection.v1")
            self.assertEqual(manifest_data["batch_type"], "scan")
            self.assertEqual(progress_data["done"], 2)
            self.assertEqual(progress_data["failed"], 1)
            self.assertEqual(progress_data["status"], "FAILED")
            self.assertEqual(failed_data["failed"][0]["version_id"], "bad_20250609")
            self.assertEqual(result_data["status"], "FAILED")
            self.assertIn("$PROJ/scripts/lg.csh scan ucie bad_20250609", rerun.read_text(encoding="utf-8"))

    def test_compare_rerun_script_uses_diff_command(self) -> None:
        from lib_guard.batch.manifest import make_batch_run_dir, write_rerun_failed_csh

        with tempfile.TemporaryDirectory() as td:
            run_dir = make_batch_run_dir(td, "compare", run_id="compare_manual")
            rerun = write_rerun_failed_csh(
                run_dir,
                [{"library_name": "ucie", "version_id": "stable_20250608", "status": "FAILED"}],
                "compare",
            )
            self.assertIn("$PROJ/scripts/lg.csh diff ucie stable_20250608 --scan-if-missing", rerun.read_text(encoding="utf-8"))


class BatchPlanOnlyCliTest(unittest.TestCase):
    def test_run_batch_plan_only_writes_manifest_without_scan_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            raw = Path(td) / "raw"
            work = Path(td) / "work"
            version = raw / "ucie" / "stable_20250608"
            version.mkdir(parents=True)
            (version / "top.v").write_text("module top; endmodule\n", encoding="utf-8")

            from lib_guard.cli import main

            catalog_dir = work / "catalog"
            self.assertEqual(main(["catalog", "scan", "--root", str(raw), "--out", str(catalog_dir), "--library-type", "ip"]), 0)
            self.assertEqual(
                main(
                    [
                        "run-batch",
                        "--catalog",
                        str(catalog_dir / "catalog.json"),
                        "--library",
                        "ucie",
                        "--workdir",
                        str(work),
                        "--limit",
                        "1",
                        "--plan-only",
                        "--batch-run-id",
                        "scan_plan",
                    ]
                ),
                0,
            )

            run_dir = work / "batch_runs" / "scan_plan"
            manifest = json.loads((run_dir / "selection_manifest.json").read_text(encoding="utf-8"))
            result = json.loads((run_dir / "result.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["batch_type"], "scan")
            self.assertEqual(len(manifest["selected"]), 1)
            self.assertEqual(result["status"], "PLAN_ONLY")
            self.assertFalse((run_dir / "progress.json").exists())
            self.assertFalse((work / "scan_out").exists())

    def test_run_batch_only_missing_reports_existing_scan_skip(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            raw = Path(td) / "raw"
            work = Path(td) / "work"
            version = raw / "ucie" / "stable_20250608"
            version.mkdir(parents=True)
            (version / "top.v").write_text("module top; endmodule\n", encoding="utf-8")

            from lib_guard.cli import main

            catalog_dir = work / "catalog"
            self.assertEqual(main(["catalog", "scan", "--root", str(raw), "--out", str(catalog_dir), "--library-type", "ip"]), 0)
            catalog_path = catalog_dir / "catalog.json"
            scan_dir = work / "scan_out" / "existing"
            scan_dir.mkdir(parents=True)
            data = json.loads(catalog_path.read_text(encoding="utf-8"))
            data["libraries"][0]["versions"][0]["scan"] = {"status": "PASS", "scan_dir": str(scan_dir)}
            catalog_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

            self.assertEqual(
                main(
                    [
                        "run-batch",
                        "--catalog",
                        str(catalog_path),
                        "--library",
                        "ucie",
                        "--workdir",
                        str(work),
                        "--only-missing",
                        "--batch-run-id",
                        "scan_skip",
                    ]
                ),
                0,
            )

            result = json.loads((work / "batch_runs" / "scan_skip" / "result.json").read_text(encoding="utf-8"))
            self.assertEqual(result["selected"], 0)
            self.assertEqual(result["skipped_existing"], 1)

    def test_compare_batch_plan_only_writes_compare_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            raw = Path(td) / "raw"
            work = Path(td) / "work"
            for name in ["stable_20250601", "stable_20250608"]:
                version = raw / "ucie" / name
                version.mkdir(parents=True)
                (version / "top.v").write_text("module top; endmodule\n", encoding="utf-8")

            from lib_guard.cli import main

            catalog_dir = work / "catalog"
            self.assertEqual(main(["catalog", "scan", "--root", str(raw), "--out", str(catalog_dir), "--library-type", "ip"]), 0)
            self.assertEqual(
                main(
                    [
                        "compare-batch",
                        "--catalog",
                        str(catalog_dir / "catalog.json"),
                        "--library",
                        "ucie",
                        "--workdir",
                        str(work),
                        "--limit",
                        "1",
                        "--plan-only",
                        "--batch-run-id",
                        "compare_plan",
                    ]
                ),
                0,
            )

            run_dir = work / "batch_runs" / "compare_plan"
            manifest = json.loads((run_dir / "selection_manifest.json").read_text(encoding="utf-8"))
            result = json.loads((run_dir / "result.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["batch_type"], "compare")
            self.assertEqual(len(manifest["selected"]), 1)
            self.assertEqual(result["status"], "PLAN_ONLY")
            self.assertFalse((run_dir / "progress.json").exists())


if __name__ == "__main__":
    unittest.main()
