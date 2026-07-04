from __future__ import annotations

import argparse
import contextlib
import gzip
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


class ScanPipelineTest(unittest.TestCase):
    def test_scan_pipeline_writes_core_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "raw"
            out = Path(td) / "scan_out"
            root.mkdir()
            (root / "top.v").write_text("module top(input a, output y); assign y = a; endmodule\n", encoding="utf-8")
            (root / "README.md").write_text("release note\n", encoding="utf-8")

            from lib_guard.scan.scanner import ScanRunner

            result = ScanRunner(
                SimpleNamespace(
                    root_path=str(root),
                    out_dir=str(out),
                    library_type="ip",
                    library_name="demo",
                    version="v1",
                    scan_mode="signature",
                    scan_id="20260531_000001",
                    state_dir=str(Path(td) / "state"),
                    cache_dir=str(Path(td) / "cache"),
                    skip_cache=False,
                    no_cache=False,
                    parse_file_types=["verilog"],
                    tool_version="0.5.0",
                    schema_version="1.0",
                )
            ).run()

            self.assertEqual(result.status, "PASS")
            self.assertTrue((out / "scan_meta.json").exists())
            self.assertTrue((out / "file_inventory.json").exists())
            self.assertTrue((out / "parser_manifest.json").exists())
            self.assertTrue((out / "parser_results.json").exists())
            self.assertTrue((out / "summary" / "parser_quality.json").exists())
            self.assertTrue((out / "summary" / "release_readiness.json").exists())
            self.assertFalse((out / "summaries").exists())
            self.assertTrue((out / "signatures" / "signatures.json").exists())

            meta = json.loads((out / "scan_meta.json").read_text(encoding="utf-8"))
            self.assertEqual(meta["library_id"], "ip/demo/v1")
            parser_results = json.loads((out / "parser_results.json").read_text(encoding="utf-8"))
            for result in parser_results.values():
                self.assertEqual(result["result_type"], "parser_result")
                self.assertIn("parser_name", result)
                self.assertNotIn("parser", result)
                self.assertEqual(result["parser_version"], "2.0")

            parser_manifest = json.loads((out / "parser_manifest.json").read_text(encoding="utf-8"))
            tasks = [
                task
                for item in parser_manifest["files"]
                for task in item["parser_tasks"]
                if task.get("parser_name")
            ]
            self.assertEqual(tasks, [])

    def test_full_scan_runs_key_eda_parsers(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "raw"
            out = Path(td) / "scan_out"
            root.mkdir()
            (root / "top.v").write_text("module top(input a, output y); assign y = a; endmodule\n", encoding="utf-8")

            from lib_guard.scan.scanner import ScanRunner

            ScanRunner(
                SimpleNamespace(
                    root_path=str(root),
                    out_dir=str(out),
                    library_type="ip",
                    library_name="demo",
                    version="v1",
                    scan_mode="full",
                    scan_id="20260531_000001_full",
                    state_dir=str(Path(td) / "state"),
                    cache_dir=str(Path(td) / "cache"),
                    skip_cache=False,
                    no_cache=False,
                    parse_file_types=["verilog"],
                    tool_version="0.5.0",
                    schema_version="1.0",
                )
            ).run()

            parser_results = json.loads((out / "parser_results.json").read_text(encoding="utf-8"))
            self.assertTrue((out / "parser_results" / "verilog").exists())
            for result in parser_results.values():
                self.assertEqual(result["result_type"], "parser_result")
                self.assertIn("parser_name", result)
                self.assertNotIn("parser", result)
                self.assertEqual(result["parser_version"], "2.0")

            parser_manifest = json.loads((out / "parser_manifest.json").read_text(encoding="utf-8"))
            tasks = [
                task
                for item in parser_manifest["files"]
                for task in item["parser_tasks"]
                if task.get("parser_name")
            ]
            self.assertEqual(len(tasks), 1)
            task = tasks[0]
            self.assertEqual(task["parser_name"], "VerilogParser")
            self.assertEqual(task["parser_version"], "2.0")
            self.assertEqual(task["parser_schema_version"], "1.0")
            self.assertIn("parser_version=2.0", task["cache_key"])
            self.assertIn("parser_schema_version=1.0", task["cache_key"])
            self.assertEqual(task["cache_status"], "MISS")
            self.assertIn(task["result_status"], {"PASS", "PASS_EMPTY"})
            self.assertTrue(task["result_path"].startswith("parser_results/verilog/"))
            self.assertTrue((out / task["result_path"]).exists())

    def test_default_scan_keeps_heavy_views_count_only_and_reports_parser_summary(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "raw"
            out = Path(td) / "scan_out"
            html = Path(td) / "html"
            root.mkdir()
            (root / "rtl").mkdir()
            (root / "lef").mkdir()
            (root / "timing").mkdir()
            (root / "parasitic").mkdir()
            (root / "constraints").mkdir()
            (root / "power").mkdir()
            (root / "pkg").mkdir()
            (root / "rtl" / "top.v").write_text("module top(input clk); endmodule\n", encoding="utf-8")
            (root / "lef" / "block.lef").write_text("VERSION 5.8 ;\nMACRO TOP\nEND TOP\n", encoding="utf-8")
            (root / "timing" / "block_ss_0p72v_125c.lib").write_text("library(ss) { cell(TOP) { area : 1.0; } }\n", encoding="utf-8")
            (root / "timing" / "block_tt_0p80v_25c.db").write_text("db-placeholder\n", encoding="utf-8")
            (root / "parasitic" / "block_ff_0p88v_m40c.spef").write_text("*SPEF \"IEEE 1481-1998\"\n*D_NET n1 0.1\n", encoding="utf-8")
            (root / "constraints" / "block.sdc").write_text("create_clock -name clk -period 1.0 [get_ports clk]\n", encoding="utf-8")
            (root / "power" / "block.upf").write_text("create_power_domain PD_TOP\n", encoding="utf-8")
            (root / "pkg" / "chan.s2p").write_text("# Hz S RI R 50\n1 0 0 0 0\n", encoding="utf-8")
            (root / "pkg" / "wave.pwl").write_text("0 0\n1n 1\n", encoding="utf-8")
            (root / "pkg" / "model.cpm").write_text("pin A\n", encoding="utf-8")

            from lib_guard.scan.scanner import ScanRunner
            from lib_guard.render.html_report import render_scan_html

            ScanRunner(
                SimpleNamespace(
                    root_path=str(root),
                    out_dir=str(out),
                    library_type="ip",
                    library_name="demo",
                    version="stable_20250608",
                    scan_mode="full",
                    scan_id="COUNT_ONLY",
                    state_dir=str(Path(td) / "state"),
                    cache_dir=str(Path(td) / "cache"),
                    skip_cache=True,
                    no_cache=True,
                    no_progress=True,
                    progress_interval=1,
                    parse_jobs=1,
                    tool_version="0.5.0",
                    schema_version="1.0",
                )
            ).run()
            render_scan_html(out, html)

            task_list = json.loads((out / "parser_task_list.json").read_text(encoding="utf-8"))
            parser_types = {task["file_type"] for task in task_list["tasks"]}
            self.assertNotIn("verilog", parser_types)
            self.assertNotIn("liberty", parser_types)
            self.assertNotIn("db", parser_types)
            self.assertNotIn("spef", parser_types)
            self.assertTrue({"lef", "sdc", "upf", "snp", "pwl", "cpm"}.issubset(parser_types))

            inventory = json.loads((out / "file_inventory.json").read_text(encoding="utf-8"))
            corner_summary = inventory["corner_filename_summary"]
            self.assertEqual(corner_summary["total_corner_files"], 3)
            self.assertEqual(corner_summary["process_counts"]["ss"], 1)
            self.assertEqual(corner_summary["process_counts"]["tt"], 1)
            self.assertEqual(corner_summary["process_counts"]["ff"], 1)

            review = json.loads((html / "scan_review.json").read_text(encoding="utf-8"))
            self.assertEqual(review["count_only"]["file_type_counts"]["verilog"], 1)
            self.assertEqual(review["count_only"]["file_type_counts"]["liberty"], 1)
            self.assertEqual(review["count_only"]["file_type_counts"]["db"], 1)
            self.assertEqual(review["count_only"]["file_type_counts"]["spef"], 1)
            self.assertGreaterEqual(review["parser_summary"]["parsed_tasks"], 6)
            self.assertEqual(review["corner_summary"]["total_corner_files"], 3)

            html_text = (html / "index.html").read_text(encoding="utf-8")
            self.assertIn("Count-only", html_text)
            self.assertIn("Corner Summary", html_text)
            self.assertIn("Parser Summary", html_text)
            self.assertIn("Scan 结论", html_text)
            self.assertIn("核心视图", html_text)
            self.assertNotIn("Version Detail", html_text)
            self.assertNotIn("delivery type", html_text)
            self.assertNotIn("Metadata only", html_text)
            self.assertIn("metadata-only", html_text)

    def test_scan_classifies_gzip_files_and_writes_typed_parser_results(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "raw"
            out = Path(td) / "scan_out"
            root.mkdir()
            with gzip.open(root / "block.lef.gz", "wt", encoding="utf-8") as fh:
                fh.write("VERSION 5.8 ;\nMACRO NAND2\nEND NAND2\n")

            from lib_guard.scan.scanner import ScanRunner

            ScanRunner(
                SimpleNamespace(
                    root_path=str(root),
                    out_dir=str(out),
                    library_type="ip",
                    library_name="demo",
                    version="v1",
                    scan_mode="full",
                    scan_id="20260531_000010",
                    state_dir=str(Path(td) / "state"),
                    cache_dir=str(Path(td) / "cache"),
                    skip_cache=True,
                    no_cache=False,
                    tool_version="0.5.0",
                    schema_version="1.0",
                )
            ).run()

            inventory = json.loads((out / "file_inventory.json").read_text(encoding="utf-8"))
            record = inventory["files"][0]
            self.assertEqual(record["extension"], ".gz")
            self.assertEqual(record["combined_extension"], ".lef.gz")
            self.assertEqual(record["compression"], "gzip")
            self.assertEqual(record["file_type"], "lef")

            manifest = json.loads((out / "parser_manifest.json").read_text(encoding="utf-8"))
            task = manifest["files"][0]["parser_tasks"][0]
            self.assertEqual(task["parser_name"], "LefParser")
            self.assertTrue(task["result_path"].startswith("parser_results/lef/"))
            result = json.loads((out / task["result_path"]).read_text(encoding="utf-8"))
            self.assertEqual(result["result_type"], "parser_result")
            self.assertEqual(result["compression"], "gzip")
            self.assertEqual(result["file_type"], "lef")

    def test_openroad_flow_setup_files_are_classified_for_manual_review(self) -> None:
        from lib_guard.scan.inventory import FileClassifier

        classifier = FileClassifier()
        samples = {
            "config.mk": ("flow_config", "flow_setup"),
            "fastroute.tcl": ("flow_config", "flow_script"),
            "pdn.cfg": ("flow_config", "flow_config"),
            "rcx_patterns.rules": ("tech_config", "tech_rule"),
            "asap7.lyp": ("tech_config", "klayout"),
            "asap7.lyt": ("tech_config", "klayout"),
            "asap7.lydrc": ("tech_config", "drc_rule"),
            "no_synth.cells": ("flow_config", "cell_list"),
        }

        for name, (file_type, role) in samples.items():
            with self.subTest(name=name):
                record = classifier.classify({"path": f"openroad/{name}", "name": name})
                self.assertEqual(record["file_type"], file_type)
                self.assertEqual(record["role"], role)
                self.assertNotEqual(record["domain"], "unknown")

    def test_parser_cache_is_v2_isolated_and_manifest_reports_hit(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "raw"
            out1 = Path(td) / "scan_out_1"
            out2 = Path(td) / "scan_out_2"
            cache = Path(td) / "cache"
            root.mkdir()
            (root / "top.v").write_text("module top(input a); endmodule\n", encoding="utf-8")

            from lib_guard.scan.scanner import ScanRunner

            base = dict(
                root_path=str(root),
                library_type="ip",
                library_name="demo",
                version="v1",
                scan_mode="full",
                state_dir=str(Path(td) / "state"),
                cache_dir=str(cache),
                skip_cache=False,
                no_cache=False,
                parse_file_types=["verilog"],
                tool_version="0.5.0",
                schema_version="1.0",
            )
            ScanRunner(SimpleNamespace(**base, out_dir=str(out1), scan_id="20260531_000011")).run()
            ScanRunner(SimpleNamespace(**base, out_dir=str(out2), scan_id="20260531_000012")).run()

            manifest = json.loads((out2 / "parser_manifest.json").read_text(encoding="utf-8"))
            task = manifest["files"][0]["parser_tasks"][0]
            self.assertEqual(task["cache_status"], "HIT")
            self.assertEqual(task["result_status"], "PASS")
            self.assertIn("parser_version=2.0", task["cache_key"])
            self.assertIn("parser_schema_version=1.0", task["cache_key"])

    def test_progress_v2_and_parser_task_list_are_written(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "raw"
            out = Path(td) / "scan_out"
            root.mkdir()
            (root / "top.v").write_text("module top(input a); endmodule\n", encoding="utf-8")
            (root / "empty.lef").write_text("VERSION 5.8 ;\n", encoding="utf-8")

            from lib_guard.scan.scanner import ScanRunner

            ScanRunner(
                SimpleNamespace(
                    root_path=str(root),
                    out_dir=str(out),
                    library_type="ip",
                    library_name="demo",
                    version="v1",
                    scan_mode="full",
                    scan_id="20260531_000016",
                    state_dir=str(Path(td) / "state"),
                    cache_dir=str(Path(td) / "cache"),
                    skip_cache=True,
                    no_cache=False,
                    no_progress=True,
                    progress_interval=1,
                    parse_jobs=1,
                    tool_version="0.5.0",
                    schema_version="1.0",
                )
            ).run()

            task_list = json.loads((out / "parser_task_list.json").read_text(encoding="utf-8"))
            self.assertEqual(task_list["task_count"], 1)
            self.assertEqual(task_list["parse_jobs"], 1)
            task = task_list["tasks"][0]
            self.assertIn("task_id", task)
            self.assertIn("cache_key", task)
            self.assertIn("priority", task)
            self.assertIn("estimated_cost", task)

            latest = json.loads((out / "logs" / "scan_progress_latest.json").read_text(encoding="utf-8"))
            self.assertEqual(latest["stage"], "finish")
            self.assertIn("by_type", latest)
            self.assertIn("summary", latest)
            self.assertIn("active_workers", latest)
            self.assertEqual(latest["summary"]["completed"], 1)
            self.assertEqual(latest["summary"]["pass_empty"], 1)
            self.assertEqual(latest["by_type"]["lef"]["pass_empty"], 1)

            events = [
                json.loads(line)["event"]
                for line in (out / "logs" / "scan_progress.jsonl").read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            self.assertIn("task_start", events)
            self.assertIn("task_finish", events)

    def test_scan_writes_incremental_parser_outputs_and_status_payload(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "raw"
            out = Path(td) / "scan_out"
            root.mkdir()
            (root / "top.v").write_text("module top(input a); endmodule\n", encoding="utf-8")

            from lib_guard.scan.scanner import ScanRunner
            from lib_guard.cli import build_scan_status

            ScanRunner(
                SimpleNamespace(
                    root_path=str(root),
                    out_dir=str(out),
                    library_type="ip",
                    library_name="demo",
                    version="v1",
                    scan_mode="full",
                    scan_id="20260531_000017",
                    state_dir=str(Path(td) / "state"),
                    cache_dir=str(Path(td) / "cache"),
                    skip_cache=True,
                    no_cache=False,
                    no_progress=True,
                    progress_interval=1,
                    parse_jobs=1,
                    parse_file_types=["verilog"],
                    tool_version="0.5.0",
                    schema_version="1.0",
                )
            ).run()

            task_list = json.loads((out / "parser_task_list.json").read_text(encoding="utf-8"))
            manifest = json.loads((out / "parser_manifest.json").read_text(encoding="utf-8"))
            task = manifest["files"][0]["parser_tasks"][0]
            self.assertEqual(task_list["task_count"], 1)
            self.assertTrue((out / task["result_path"]).exists())

            status = build_scan_status(out)
            self.assertEqual(status["status"], "FINISHED")
            self.assertEqual(status["summary"]["completed"], 1)
            self.assertTrue(status["outputs"]["parser_manifest"])
            self.assertTrue(status["outputs"]["parser_results_dir"])

    def test_parallel_parse_jobs_match_serial_semantics(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "raw"
            serial = Path(td) / "serial"
            parallel = Path(td) / "parallel"
            root.mkdir()
            (root / "top.v").write_text("module top(input a); endmodule\n", encoding="utf-8")
            (root / "block.lef").write_text("VERSION 5.8 ;\nMACRO NAND2\nEND NAND2\n", encoding="utf-8")
            (root / "empty.sdc").write_text("# no known SDC commands\n", encoding="utf-8")

            from lib_guard.scan.scanner import ScanRunner

            base = dict(
                root_path=str(root),
                library_type="ip",
                library_name="demo",
                version="v1",
                scan_mode="release",
                state_dir=str(Path(td) / "state"),
                cache_dir=str(Path(td) / "cache"),
                skip_cache=True,
                no_cache=True,
                no_progress=True,
                progress_interval=1,
                parse_file_types=["verilog", "lef", "sdc"],
                tool_version="0.5.0",
                schema_version="1.0",
            )
            ScanRunner(SimpleNamespace(**base, out_dir=str(serial), scan_id="20260531_SERIAL", parse_jobs=1)).run()
            ScanRunner(SimpleNamespace(**base, out_dir=str(parallel), scan_id="20260531_PARALLEL", parse_jobs=4)).run()
            def load(scan: Path, rel: str):
                return json.loads((scan / rel).read_text(encoding="utf-8"))

            self.assertEqual(
                self._normalize_parser_results(load(serial, "parser_results.json")),
                self._normalize_parser_results(load(parallel, "parser_results.json")),
            )
            self.assertEqual(
                self._normalize_manifest(load(serial, "parser_manifest.json")),
                self._normalize_manifest(load(parallel, "parser_manifest.json")),
            )
            self.assertEqual(
                self._normalize_quality(load(serial, "summary/parser_quality.json")),
                self._normalize_quality(load(parallel, "summary/parser_quality.json")),
            )
            self.assertEqual(
                self._normalize_readiness(load(serial, "summary/release_readiness.json")),
                self._normalize_readiness(load(parallel, "summary/release_readiness.json")),
            )
            latest = load(parallel, "logs/scan_progress_latest.json")
            self.assertEqual(latest["summary"]["completed"], 3)
            self.assertIn("active_workers", latest)
            progress_events = [
                json.loads(line)
                for line in (parallel / "logs" / "scan_progress.jsonl").read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            self.assertTrue(any(len(event.get("active_workers", [])) > 1 for event in progress_events))

    def _normalize_parser_results(self, data):
        out = {}
        for key, value in sorted(data.items()):
            clean = dict(value)
            clean.pop("abs_path", None)
            out[key] = clean
        return out

    def _normalize_manifest(self, data):
        items = []
        for file_entry in data.get("files", []):
            for task in file_entry.get("parser_tasks", []):
                if not task.get("parser_name"):
                    continue
                clean = {
                    "file": file_entry.get("file"),
                    "file_type": file_entry.get("file_type"),
                    "parser_name": task.get("parser_name"),
                    "result_status": task.get("result_status"),
                    "cache_status": task.get("cache_status"),
                    "result_path": task.get("result_path"),
                }
                items.append(clean)
        return sorted(items, key=lambda item: (item["file"], item["parser_name"]))

    def _normalize_quality(self, data):
        return {
            parser["parser_name"]: {
                "status": parser.get("status"),
                "file_count": parser.get("file_count"),
                "parsed_count": parser.get("parsed_count"),
                "failed_count": parser.get("failed_count"),
                "pass_empty_count": parser.get("pass_empty_count"),
                "object_count": parser.get("object_count"),
            }
            for parser in data.get("parsers", [])
        }

    def _normalize_readiness(self, data):
        return {
            "bundle_status": data.get("bundle_status"),
            "release_channel": data.get("release_channel"),
            "blocking": [(item.get("category"), item.get("file_type"), item.get("severity")) for item in data.get("blocking_items", [])],
            "manual": [(item.get("approval_scope"), item.get("file_type"), item.get("risk_level")) for item in data.get("manual_review_items", [])],
        }

    def test_non_doc_pass_empty_stays_out_of_scan_issues(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "raw"
            out = Path(td) / "scan_out"
            root.mkdir()
            (root / "empty.v").write_text("// no modules here\n", encoding="utf-8")

            from lib_guard.scan.scanner import ScanRunner

            result = ScanRunner(
                SimpleNamespace(
                    root_path=str(root),
                    out_dir=str(out),
                    library_type="ip",
                    library_name="demo",
                    version="v1",
                    scan_mode="full",
                    scan_id="20260531_000013",
                    state_dir=str(Path(td) / "state"),
                    cache_dir=str(Path(td) / "cache"),
                    skip_cache=True,
                    no_cache=False,
                    parse_file_types=["verilog"],
                    tool_version="0.5.0",
                    schema_version="1.0",
                )
            ).run()

            self.assertEqual(result.status, "PASS")
            manifest = json.loads((out / "parser_manifest.json").read_text(encoding="utf-8"))
            task = manifest["files"][0]["parser_tasks"][0]
            self.assertEqual(task["result_status"], "PASS_EMPTY")

            parser_quality = json.loads((out / "summary" / "parser_quality.json").read_text(encoding="utf-8"))
            self.assertEqual(parser_quality["status"], "PASS_WITH_WARNING")
            self.assertEqual(parser_quality["parsers"][0]["pass_empty_count"], 1)

            issues = json.loads((out / "scan_issues.json").read_text(encoding="utf-8"))
            self.assertEqual(issues["summary"]["warning"], 0)
            self.assertEqual(issues["issues"], [])

    def test_scan_writes_release_readiness_components(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "raw"
            out = Path(td) / "scan_out"
            root.mkdir()
            (root / "empty.v").write_text("// required view exists but parser extracts no module\n", encoding="utf-8")

            from lib_guard.scan.scanner import ScanRunner

            ScanRunner(
                SimpleNamespace(
                    root_path=str(root),
                    out_dir=str(out),
                    library_type="ip",
                    library_name="demo",
                    version="v1",
                    scan_mode="release",
                    scan_id="20260531_000014",
                    state_dir=str(Path(td) / "state"),
                    cache_dir=str(Path(td) / "cache"),
                    skip_cache=True,
                    no_cache=False,
                    tool_version="0.5.0",
                    schema_version="1.0",
                )
            ).run()

            readiness = json.loads((out / "summary" / "release_readiness.json").read_text(encoding="utf-8"))
            self.assertEqual(readiness["bundle_status"], "PASS")
            self.assertEqual(readiness["release_channel"], "metadata_only")
            self.assertEqual(len(readiness["components"]), 1)
            component = readiness["components"][0]
            self.assertEqual(component["component_id"], "ip/demo/v1")
            self.assertEqual(component["release_channel"], "metadata_only")
            self.assertIn("verilog", component["required_views"])
            self.assertEqual(component["required_view_results"]["verilog"]["status"], "PASS")
            self.assertEqual(component["required_view_results"]["verilog"]["parser_status"], "METADATA_ONLY")
            self.assertEqual(component["required_view_results"]["verilog"]["validation_level"], "metadata_required")
            self.assertFalse(readiness["blocking_items"])
            self.assertTrue(readiness["manual_review_items"])

    def test_release_check_uses_release_readiness_gate(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "raw"
            out = Path(td) / "scan_out"
            root.mkdir()
            (root / "empty.v").write_text("// no modules\n", encoding="utf-8")

            from lib_guard.scan.scanner import ScanRunner
            from lib_guard.release.checker import check_release_scan

            ScanRunner(
                SimpleNamespace(
                    root_path=str(root),
                    out_dir=str(out),
                    library_type="ip",
                    library_name="demo",
                    version="v1",
                    scan_mode="release",
                    scan_id="20260531_000015",
                    state_dir=str(Path(td) / "state"),
                    cache_dir=str(Path(td) / "cache"),
                    skip_cache=True,
                    no_cache=False,
                    tool_version="0.5.0",
                    schema_version="1.0",
                )
            ).run()
            result = check_release_scan(out, policy_path="configs/release_policy.json")

            self.assertEqual(result["release_check_status"], "PASS_WITH_WARNING")
            self.assertEqual(result["release_readiness"]["bundle_status"], "PASS")
            self.assertFalse(any(issue["category"] == "release_readiness" for issue in result["issues"]))
            self.assertFalse(any(issue["category"] == "summary" for issue in result["issues"]))

    def test_release_link_force_records_override_and_applies_blocked_release(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "raw"
            scan = Path(td) / "scan"
            release_root = Path(td) / "release_area"
            policy = Path(td) / "release_policy.json"
            root.mkdir()
            (root / "empty.v").write_text("// no modules\n", encoding="utf-8")
            policy.write_text(
                json.dumps(
                    {
                        "required_views": {"ip": ["verilog"]},
                        "validation_levels": {"verilog": "parsed_required"},
                        "require_doc_types": [],
                        "require_signatures": False,
                        "require_summaries": False,
                        "release_link_mode": "copy",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            from lib_guard.scan.scanner import ScanRunner
            from lib_guard.release.linker import link_release_from_scan
            from lib_guard.summary.readiness import build_release_readiness

            ScanRunner(
                SimpleNamespace(
                    root_path=str(root),
                    out_dir=str(scan),
                    library_type="ip",
                    library_name="demo",
                    version="hotfix_v1.0.1",
                    scan_mode="release",
                    scan_id="FORCE",
                    state_dir=str(Path(td) / "state"),
                    cache_dir=str(Path(td) / "cache"),
                    skip_cache=True,
                    no_cache=True,
                    no_progress=True,
                    progress_interval=1,
                    parse_jobs=1,
                    parse_file_types=["verilog"],
                    tool_version="0.5.0",
                    schema_version="1.0",
                )
            ).run()
            (scan / "summary" / "release_readiness.json").write_text(
                json.dumps(build_release_readiness(scan, policy_path=policy), indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            blocked = link_release_from_scan(scan, release_root, alias="current", dry_run=False, policy_path=policy)
            self.assertEqual(blocked["status"], "BLOCKED")

            forced = link_release_from_scan(
                scan,
                release_root,
                alias="current",
                dry_run=False,
                policy_path=policy,
                force=True,
                force_reason="manual waiver approved for emergency hotfix",
            )

            self.assertEqual(forced["status"], "FORCED_DONE")
            self.assertTrue((release_root / "ip" / "demo" / "hotfix_v1.0.1").exists())
            override = json.loads((scan / "release" / "release_override.json").read_text(encoding="utf-8"))
            self.assertTrue(override["force"])
            self.assertEqual(override["force_reason"], "manual waiver approved for emergency hotfix")

    def test_release_link_blocks_existing_target_without_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "raw"
            scan = Path(td) / "scan"
            release_root = Path(td) / "release_area"
            policy = Path(td) / "release_policy.json"
            root.mkdir()
            (root / "top.v").write_text("module top(input a); endmodule\n", encoding="utf-8")
            policy.write_text(
                json.dumps(
                    {
                        "required_views": {"ip": ["verilog"]},
                        "require_doc_types": [],
                        "require_signatures": False,
                        "require_summaries": False,
                        "release_link_mode": "copy",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            from lib_guard.scan.scanner import ScanRunner
            from lib_guard.release.linker import link_release_from_scan

            ScanRunner(
                SimpleNamespace(
                    root_path=str(root),
                    out_dir=str(scan),
                    library_type="ip",
                    library_name="demo",
                    version="stable_v1",
                    scan_mode="release",
                    scan_id="OVERWRITE",
                    state_dir=str(Path(td) / "state"),
                    cache_dir=str(Path(td) / "cache"),
                    skip_cache=True,
                    no_cache=True,
                    no_progress=True,
                    progress_interval=1,
                    parse_jobs=1,
                    tool_version="0.5.0",
                    schema_version="1.0",
                )
            ).run()
            first = link_release_from_scan(scan, release_root, alias="current", dry_run=False, policy_path=policy)
            second = link_release_from_scan(scan, release_root, alias="current", dry_run=False, policy_path=policy)
            third = link_release_from_scan(scan, release_root, alias="current", dry_run=False, policy_path=policy, overwrite=True)

            self.assertEqual(first["status"], "DONE")
            self.assertEqual(second["status"], "BLOCKED")
            self.assertTrue(second["release_dir_check"]["target_exists"])
            self.assertEqual(third["status"], "DONE")

    def test_diff_scan_reports_inventory_and_summary_changes(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            old_root = Path(td) / "old_raw"
            new_root = Path(td) / "new_raw"
            old_out = Path(td) / "old_scan"
            new_out = Path(td) / "new_scan"
            old_root.mkdir()
            new_root.mkdir()
            (old_root / "top.v").write_text("module top(input a); endmodule\n", encoding="utf-8")
            (new_root / "top.v").write_text("module top(input a); endmodule\n// metadata comment change\n", encoding="utf-8")
            (new_root / "block.lef").write_text("VERSION 5.8 ;\nMACRO NAND2\nEND NAND2\n", encoding="utf-8")

            from lib_guard.scan.scanner import ScanRunner
            from lib_guard.diff.scan_diff import diff_scan_outputs
            from lib_guard.summary.readiness import build_release_readiness
            from lib_guard.summary.readiness import build_release_readiness

            base = dict(
                library_type="ip",
                library_name="demo",
                version="v1",
                scan_mode="signature",
                state_dir=str(Path(td) / "state"),
                cache_dir=str(Path(td) / "cache"),
                skip_cache=True,
                no_cache=True,
                no_progress=True,
                progress_interval=1,
                parse_jobs=1,
                parse_file_types=["verilog"],
                tool_version="0.5.0",
                schema_version="1.0",
            )
            ScanRunner(SimpleNamespace(**base, root_path=str(old_root), out_dir=str(old_out), scan_id="OLD")).run()
            ScanRunner(SimpleNamespace(**base, root_path=str(new_root), out_dir=str(new_out), scan_id="NEW")).run()

            result = diff_scan_outputs(old_out, new_out)
            self.assertEqual(result["status"], "DIFF")
            self.assertIn("block.lef", result["inventory"]["added"])
            self.assertIn("top.v", result["inventory"]["changed"])
            self.assertTrue(result["summary"]["changed_files"] >= 1)

    def test_diff_scan_writes_p0_release_bundle_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            old_root = Path(td) / "old_raw"
            new_root = Path(td) / "new_raw"
            old_out = Path(td) / "old_scan"
            new_out = Path(td) / "new_scan"
            diff_out = Path(td) / "diff_out"
            old_root.mkdir()
            new_root.mkdir()
            (old_root / "top.v").write_text("module top(input a); endmodule\n", encoding="utf-8")
            (new_root / "top.v").write_text("// parser empty after risky hotfix\n", encoding="utf-8")

            from lib_guard.scan.scanner import ScanRunner
            from lib_guard.diff.scan_diff import diff_scan_outputs
            from lib_guard.summary.readiness import build_release_readiness

            base = dict(
                library_type="ip",
                library_name="demo",
                scan_mode="release",
                state_dir=str(Path(td) / "state"),
                cache_dir=str(Path(td) / "cache"),
                skip_cache=True,
                no_cache=True,
                no_progress=True,
                progress_interval=1,
                parse_jobs=1,
                parse_file_types=["verilog"],
                tool_version="0.5.0",
                schema_version="1.0",
            )
            ScanRunner(SimpleNamespace(**base, root_path=str(old_root), out_dir=str(old_out), scan_id="OLD", version="full_v1.0")).run()
            ScanRunner(SimpleNamespace(**base, root_path=str(new_root), out_dir=str(new_out), scan_id="NEW", version="hotfix_v1.0.1")).run()
            strict_policy = {"required_views": {"ip": ["verilog"]}, "validation_levels": {"verilog": "parsed_required"}}
            for scan_dir in [old_out, new_out]:
                (scan_dir / "summary" / "release_readiness.json").write_text(
                    json.dumps(build_release_readiness(scan_dir, policy_path=strict_policy), indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8",
                )
            result = diff_scan_outputs(
                old_out,
                new_out,
                out_path=diff_out,
                version_relation={
                    "diff_mode": "adjacent",
                    "new_version_type": "hotfix",
                    "parent_version": "full_v1.0",
                    "base_version": "full_v1.0",
                    "release_line": "v1.0",
                },
            )

            self.assertEqual(result["status"], "BLOCK")
            self.assertEqual(result["version_relation"]["new_version_type"], "hotfix")
            self.assertTrue((diff_out / "diff_meta.json").exists())
            self.assertTrue((diff_out / "diff_summary.json").exists())
            self.assertTrue((diff_out / "file_diff.json").exists())
            self.assertTrue((diff_out / "component_diff.json").exists())
            self.assertTrue((diff_out / "release_readiness_diff.json").exists())
            self.assertTrue((diff_out / "diff_issues.json").exists())
            self.assertTrue((diff_out / "diff_report.md").exists())
            summary = json.loads((diff_out / "diff_summary.json").read_text(encoding="utf-8"))
            self.assertNotIn("changed_summaries", summary)

            readiness = json.loads((diff_out / "release_readiness_diff.json").read_text(encoding="utf-8"))
            self.assertEqual(readiness["bundle_status"]["old"], "PASS")
            self.assertEqual(readiness["bundle_status"]["new"], "BLOCK")
            issues = json.loads((diff_out / "diff_issues.json").read_text(encoding="utf-8"))
            self.assertTrue(any(item["severity"] == "blocker" and item["category"] == "release_readiness" for item in issues["issues"]))

    def test_version_index_resolves_adjacent_and_cumulative_diff_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            full_root = Path(td) / "full_raw"
            hotfix_root = Path(td) / "hotfix_raw"
            full_out = Path(td) / "full_scan"
            hotfix_out = Path(td) / "hotfix_scan"
            work = Path(td) / "work"
            full_root.mkdir()
            hotfix_root.mkdir()
            (full_root / "top.v").write_text("module top(input a); endmodule\n", encoding="utf-8")
            (hotfix_root / "top.v").write_text("module top(input a, output y); endmodule\n", encoding="utf-8")

            from lib_guard.scan.scanner import ScanRunner
            from lib_guard.version.index import register_scan_version, resolve_adjacent_pair, resolve_cumulative_pair

            base = dict(
                library_type="ip",
                library_name="demo",
                scan_mode="release",
                state_dir=str(Path(td) / "state"),
                cache_dir=str(Path(td) / "cache"),
                skip_cache=True,
                no_cache=True,
                no_progress=True,
                progress_interval=1,
                parse_jobs=1,
                tool_version="0.5.0",
                schema_version="1.0",
            )
            ScanRunner(SimpleNamespace(**base, root_path=str(full_root), out_dir=str(full_out), scan_id="FULL", version="full_v1.0")).run()
            ScanRunner(SimpleNamespace(**base, root_path=str(hotfix_root), out_dir=str(hotfix_out), scan_id="HOTFIX", version="hotfix_v1.0.1")).run()
            register_scan_version(full_out, workdir=work, version_id="full_v1.0", version_type="full", release_line="v1.0")
            register_scan_version(hotfix_out, workdir=work, version_id="hotfix_v1.0.1", version_type="hotfix", release_line="v1.0", parent_version="full_v1.0", base_version="full_v1.0")

            adjacent = resolve_adjacent_pair("ip/demo", "hotfix_v1.0.1", workdir=work)
            cumulative = resolve_cumulative_pair("ip/demo", "hotfix_v1.0.1", workdir=work)

            self.assertEqual(Path(adjacent["old_scan"]), full_out)
            self.assertEqual(Path(adjacent["new_scan"]), hotfix_out)
            self.assertEqual(adjacent["version_relation"]["diff_mode"], "adjacent")
            self.assertEqual(Path(cumulative["old_scan"]), full_out)
            self.assertEqual(Path(cumulative["new_scan"]), hotfix_out)
            self.assertEqual(cumulative["version_relation"]["diff_mode"], "cumulative")

    def test_version_register_supports_raw_root_and_requires_scan_for_diff(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            raw_full = Path(td) / "raw_full"
            raw_hotfix = Path(td) / "raw_hotfix"
            work = Path(td) / "work"
            raw_full.mkdir()
            raw_hotfix.mkdir()

            from lib_guard.version.index import register_scan_version, resolve_adjacent_pair

            register_scan_version(
                None,
                workdir=work,
                library_id="project_x/bundle_a",
                version_id="full_v1.0",
                version_type="full",
                release_line="v1.0",
                raw_root=raw_full,
            )
            register_scan_version(
                None,
                workdir=work,
                library_id="project_x/bundle_a",
                version_id="hotfix_v1.0.1",
                version_type="hotfix",
                release_line="v1.0",
                parent_version="full_v1.0",
                base_version="full_v1.0",
                raw_root=raw_hotfix,
            )

            with self.assertRaisesRegex(ValueError, "raw_root.*no scan_dir"):
                resolve_adjacent_pair("project_x/bundle_a", "hotfix_v1.0.1", workdir=work)

            data = json.loads((work / "index" / "version_history" / "index.json").read_text(encoding="utf-8"))
            record = data["libraries"]["project_x/bundle_a"]["versions"]["hotfix_v1.0.1"]
            self.assertEqual(record["raw_root"], str(raw_hotfix))
            self.assertIsNone(record["scan_dir"])

    def test_release_check_consumes_blocking_diff_gate(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "raw"
            scan = Path(td) / "scan"
            diff = Path(td) / "diff"
            root.mkdir()
            (root / "top.v").write_text("module top(input a); endmodule\n", encoding="utf-8")

            from lib_guard.scan.scanner import ScanRunner
            from lib_guard.release.checker import check_release_scan

            ScanRunner(
                SimpleNamespace(
                    root_path=str(root),
                    out_dir=str(scan),
                    library_type="ip",
                    library_name="demo",
                    version="hotfix_v1.0.1",
                    scan_mode="release",
                    scan_id="HOTFIX",
                    state_dir=str(Path(td) / "state"),
                    cache_dir=str(Path(td) / "cache"),
                    skip_cache=True,
                    no_cache=True,
                    no_progress=True,
                    progress_interval=1,
                    parse_jobs=1,
                    tool_version="0.5.0",
                    schema_version="1.0",
                )
            ).run()
            diff.mkdir()
            (diff / "diff_summary.json").write_text(json.dumps({"status": "BLOCK", "risk_level": "blocker"}), encoding="utf-8")
            (diff / "diff_issues.json").write_text(json.dumps({"issues": [{"severity": "blocker", "category": "object_diff", "title": "Port removed", "message": "port removed"}]}), encoding="utf-8")

            result = check_release_scan(scan, policy_path="configs/release_policy.json", diff_dir=diff)

            self.assertEqual(result["release_check_status"], "BLOCK")
            self.assertTrue(any(issue["category"] == "diff" for issue in result["issues"]))
            self.assertEqual(result["diff_gate"]["status"], "BLOCK")

    def test_governance_diff_writes_pairwise_tasks_without_object_gate_block(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            old_root = Path(td) / "old_raw"
            new_root = Path(td) / "new_raw"
            old_scan = Path(td) / "old_scan"
            new_scan = Path(td) / "new_scan"
            diff_out = Path(td) / "diff"
            old_root.mkdir()
            new_root.mkdir()
            (old_root / "block.lef").write_text("VERSION 5.8 ;\nMACRO A\n  SIZE 1 BY 1 ;\n  PIN P\n    DIRECTION INPUT ;\n  END P\nEND A\nMACRO B\nEND B\n", encoding="utf-8")
            (new_root / "block.lef").write_text("VERSION 5.8 ;\nMACRO A\n  SIZE 1 BY 2 ;\nEND A\n", encoding="utf-8")
            (old_root / "top.v").write_text("module top(a, data);\ninput a;\noutput [31:0] data;\nendmodule\n", encoding="utf-8")
            (new_root / "top.v").write_text("module top(data);\noutput [63:0] data;\nendmodule\n", encoding="utf-8")
            (old_root / "cell.lib").write_text("library(L) {\n  cell(INV_X1) {\n    pin(A) {\n      direction : input;\n    }\n  }\n}\n", encoding="utf-8")
            (new_root / "cell.lib").write_text("library(L) {\n}\n", encoding="utf-8")

            from lib_guard.scan.scanner import ScanRunner
            from lib_guard.diff.scan_diff import diff_scan_outputs

            base = dict(
                library_type="ip",
                library_name="demo",
                version="v1",
                scan_mode="release",
                state_dir=str(Path(td) / "state"),
                cache_dir=str(Path(td) / "cache"),
                skip_cache=True,
                no_cache=True,
                no_progress=True,
                progress_interval=1,
                parse_jobs=1,
                tool_version="0.5.0",
                schema_version="1.0",
            )
            ScanRunner(SimpleNamespace(**base, root_path=str(old_root), out_dir=str(old_scan), scan_id="OLD")).run()
            ScanRunner(SimpleNamespace(**base, root_path=str(new_root), out_dir=str(new_scan), scan_id="NEW")).run()
            result = diff_scan_outputs(old_scan, new_scan, out_path=diff_out)

            self.assertEqual(result["status"], "DIFF")
            self.assertFalse((diff_out / "parser_result_diff" / "lef_diff.json").exists())
            tasks = json.loads((diff_out / "pairwise_diff_tasks.json").read_text(encoding="utf-8"))
            self.assertEqual(len(tasks["tasks"]), 1)
            self.assertEqual(tasks["tasks"][0]["file_type"], "lef")
            self.assertNotIn("command", tasks["tasks"][0])
            self.assertNotIn("low_level_command", tasks["tasks"][0])
            status = json.loads((diff_out / "pairwise_diff_task_status.json").read_text(encoding="utf-8"))
            self.assertEqual(status["summary"]["pending"], len(tasks["tasks"]))
            issues = json.loads((diff_out / "diff_issues.json").read_text(encoding="utf-8"))
            self.assertFalse(any(item["category"] == "object_diff" for item in issues["issues"]))
            summary = json.loads((diff_out / "diff_summary.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["pairwise_tasks"], len(tasks["tasks"]))
            self.assertTrue((diff_out / "view_diff.json").exists())
            self.assertTrue((diff_out / "type_diff.json").exists())
            self.assertTrue((diff_out / "release_evidence_diff.json").exists())
            self.assertTrue((diff_out / "metadata_review_tasks.json").exists())
            self.assertTrue((diff_out / "manual_pairwise_tasks.json").exists())
            view_diff = json.loads((diff_out / "view_diff.json").read_text(encoding="utf-8"))
            self.assertEqual(view_diff["status"], "PASS")
            type_diff = json.loads((diff_out / "type_diff.json").read_text(encoding="utf-8"))
            self.assertIn("lef", type_diff["by_type"])
            self.assertIn("verilog", type_diff["by_type"])
            manual_tasks = json.loads((diff_out / "manual_pairwise_tasks.json").read_text(encoding="utf-8"))
            self.assertEqual(manual_tasks["summary"]["total"], len(tasks["tasks"]))
            self.assertEqual(summary["view_changes"], view_diff["summary"]["changed"])
            self.assertEqual(summary["type_changes"], type_diff["summary"]["changed_types"])

    def test_pairwise_default_lane_excludes_summary_and_binary_metadata_types(self) -> None:
        from lib_guard.diff.pairwise import DEFAULT_PAIRWISE_FILE_DIFF_TYPES, build_pairwise_diff_tasks
        from lib_guard.project_config import BINARY_METADATA_ONLY_TYPES, DEFAULT_FILE_DIFF_TYPES, SUMMARY_ONLY_TYPES
        from lib_guard.render.version_detail_report import BINARY_METADATA_ONLY_TYPES as DETAIL_BINARY_TYPES
        from lib_guard.render.version_detail_report import SUMMARY_ONLY_TYPES as DETAIL_SUMMARY_TYPES

        self.assertEqual(DEFAULT_PAIRWISE_FILE_DIFF_TYPES, DEFAULT_FILE_DIFF_TYPES)
        self.assertEqual(DETAIL_SUMMARY_TYPES, SUMMARY_ONLY_TYPES)
        self.assertEqual(DETAIL_BINARY_TYPES, BINARY_METADATA_ONLY_TYPES)

        with tempfile.TemporaryDirectory() as td:
            old_scan = Path(td) / "old_scan"
            new_scan = Path(td) / "new_scan"
            old_scan.mkdir()
            new_scan.mkdir()
            (old_scan / "scan_meta.json").write_text(json.dumps({"library_name": "demo", "version": "base"}), encoding="utf-8")
            (new_scan / "scan_meta.json").write_text(json.dumps({"library_name": "demo", "version": "new"}), encoding="utf-8")
            changed_types = ["lef", "verilog", "systemverilog", "liberty", "spef", "db", "gds", "oas"]
            file_diff = {
                "changed": [f"{file_type}/block.{file_type}" for file_type in changed_types],
                "_old_items": {},
                "_new_items": {},
            }
            for file_type in changed_types:
                rel = f"{file_type}/block.{file_type}"
                file_diff["_old_items"][rel] = {"path": rel, "file_type": file_type, "root_path": str(old_scan)}
                file_diff["_new_items"][rel] = {"path": rel, "file_type": file_type, "root_path": str(new_scan)}

            tasks = build_pairwise_diff_tasks(old_scan, new_scan, file_diff, output_root=Path(td) / "pairwise")
            task_types = {item["file_type"] for item in tasks["tasks"]}

            self.assertEqual(task_types, {"lef"})
            for item in tasks["tasks"]:
                self.assertNotIn("command", item)
                self.assertNotIn("low_level_command", item)
            for file_type in ["verilog", "systemverilog", "liberty", "spef", "db", "gds", "oas"]:
                self.assertNotIn(file_type, task_types)

    def test_diff_treats_same_hash_path_prefix_change_as_move_not_added_removed(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            old_root = Path(td) / "old_raw"
            new_root = Path(td) / "new_raw"
            old_scan = Path(td) / "old_scan"
            new_scan = Path(td) / "new_scan"
            diff_out = Path(td) / "diff"
            old_root.mkdir()
            new_root.mkdir()
            (old_root / "asap7_source_package").mkdir()
            (new_root / "upstream_ae9a8ed9").mkdir()
            sdc = "create_clock -name core -period 1.0 [get_ports clk]\n"
            (old_root / "asap7_source_package" / "constraints.sdc").write_text(sdc, encoding="utf-8")
            (new_root / "upstream_ae9a8ed9" / "constraints.sdc").write_text(sdc, encoding="utf-8")

            from lib_guard.scan.scanner import ScanRunner
            from lib_guard.diff.scan_diff import diff_scan_outputs

            base = dict(
                library_type="ip",
                library_name="demo",
                version="v1",
                scan_mode="release",
                state_dir=str(Path(td) / "state"),
                cache_dir=str(Path(td) / "cache"),
                skip_cache=True,
                no_cache=True,
                no_progress=True,
                progress_interval=1,
                parse_jobs=1,
                tool_version="0.5.0",
                schema_version="1.0",
            )
            ScanRunner(SimpleNamespace(**base, root_path=str(old_root), out_dir=str(old_scan), scan_id="OLD")).run()
            ScanRunner(SimpleNamespace(**base, root_path=str(new_root), out_dir=str(new_scan), scan_id="NEW")).run()

            diff_scan_outputs(old_scan, new_scan, out_path=diff_out)

            file_diff = json.loads((diff_out / "file_diff.json").read_text(encoding="utf-8"))
            self.assertEqual(file_diff["counts"]["renamed_or_moved"], 1)
            self.assertEqual(file_diff["counts"]["added"], 0)
            self.assertEqual(file_diff["counts"]["removed"], 0)
            self.assertEqual(file_diff["added"], [])
            self.assertEqual(file_diff["removed"], [])
            summary = json.loads((diff_out / "diff_summary.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["renamed_or_moved"], 1)
            tasks = json.loads((diff_out / "pairwise_diff_tasks.json").read_text(encoding="utf-8"))
            self.assertEqual(tasks["summary"]["total"], 0)

    def test_diff_treats_wrapper_path_change_with_content_delta_as_logical_change(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            old_root = Path(td) / "old_raw"
            new_root = Path(td) / "new_raw"
            old_scan = Path(td) / "old_scan"
            new_scan = Path(td) / "new_scan"
            diff_out = Path(td) / "diff"
            old_root.mkdir()
            new_root.mkdir()
            (old_root / "asap7_source_package" / "lef").mkdir(parents=True)
            (new_root / "upstream_ae9a8ed9" / "lef").mkdir(parents=True)
            (old_root / "asap7_source_package" / "lef" / "macro.lef").write_text("MACRO M\n  SIZE 1 BY 1 ;\nEND M\n", encoding="utf-8")
            (new_root / "upstream_ae9a8ed9" / "lef" / "macro.lef").write_text("MACRO M\n  SIZE 2 BY 2 ;\nEND M\n", encoding="utf-8")

            from lib_guard.diff.scan_diff import diff_scan_outputs
            from lib_guard.scan.scanner import ScanRunner

            base = dict(
                library_type="ip",
                library_name="demo",
                version="v1",
                scan_mode="release",
                state_dir=str(Path(td) / "state"),
                cache_dir=str(Path(td) / "cache"),
                skip_cache=True,
                no_cache=True,
                no_progress=True,
                progress_interval=1,
                parse_jobs=1,
                tool_version="0.5.0",
                schema_version="1.0",
            )
            ScanRunner(SimpleNamespace(**base, root_path=str(old_root), out_dir=str(old_scan), scan_id="OLD")).run()
            ScanRunner(SimpleNamespace(**base, root_path=str(new_root), out_dir=str(new_scan), scan_id="NEW")).run()

            diff_scan_outputs(old_scan, new_scan, out_path=diff_out)

            file_diff = json.loads((diff_out / "file_diff.json").read_text(encoding="utf-8"))
            self.assertEqual(file_diff["counts"]["added"], 0)
            self.assertEqual(file_diff["counts"]["removed"], 0)
            self.assertEqual(file_diff["counts"]["changed"], 1)
            self.assertEqual(file_diff["changed"], ["lef/macro.lef"])
            self.assertEqual(
                file_diff["logical_path_changes"],
                [
                    {
                        "logical_path": "lef/macro.lef",
                        "old": "asap7_source_package/lef/macro.lef",
                        "new": "upstream_ae9a8ed9/lef/macro.lef",
                    }
                ],
            )
            summary = json.loads((diff_out / "diff_summary.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["changed_files"], 1)

    def test_diff_reports_package_root_migration_from_logical_path_pairs(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            old_scan = Path(td) / "old_scan"
            new_scan = Path(td) / "new_scan"
            diff_out = Path(td) / "diff"
            for scan, version, root, files in [
                (
                    old_scan,
                    "base",
                    "asap7_source_package",
                    [
                        ("asap7_source_package/lef/a.lef", "lef", "same-digest", 100),
                        ("asap7_source_package/lef/b.lef", "lef", "same-digest", 100),
                    ],
                ),
                (
                    new_scan,
                    "target",
                    "upstream_ae9a8ed9",
                    [
                        ("upstream_ae9a8ed9/lef/a.lef", "lef", "same-digest", 100),
                        ("upstream_ae9a8ed9/lef/b.lef", "lef", "same-digest", 100),
                        ("upstream_ae9a8ed9/lib/c.lib", "liberty", "new-digest", 200),
                    ],
                ),
            ]:
                scan.mkdir()
                (scan / "summary").mkdir()
                (scan / "signatures").mkdir()
                (scan / "parser_results").mkdir()
                (scan / "scan_meta.json").write_text(
                    json.dumps({"library_type": "ip", "library_name": "demo", "release_version": version, "scan_id": version}),
                    encoding="utf-8",
                )
                (scan / "manifest.json").write_text(json.dumps({"files": []}), encoding="utf-8")
                (scan / "parser_manifest.json").write_text(json.dumps({"files": []}), encoding="utf-8")
                (scan / "scan_issues.json").write_text(json.dumps({"issues": []}), encoding="utf-8")
                (scan / "summary" / "parser_quality.json").write_text(json.dumps({"status": "PASS"}), encoding="utf-8")
                (scan / "summary" / "release_readiness.json").write_text(json.dumps({"components": []}), encoding="utf-8")
                (scan / "signatures" / "signatures.json").write_text(json.dumps({}), encoding="utf-8")
                (scan / "file_inventory.json").write_text(
                    json.dumps(
                        {
                            "root_path": root,
                            "files": [
                                {"path": path, "file_type": file_type, "hash": digest, "size_bytes": size}
                                for path, file_type, digest, size in files
                            ],
                        }
                    ),
                    encoding="utf-8",
                )

            from lib_guard.diff.scan_diff import diff_scan_outputs

            diff_scan_outputs(old_scan, new_scan, out_path=diff_out)

            file_diff = json.loads((diff_out / "file_diff.json").read_text(encoding="utf-8"))
            self.assertEqual(file_diff["counts"]["added"], 1)
            self.assertEqual(file_diff["counts"]["removed"], 0)
            self.assertEqual(file_diff["counts"]["renamed_or_moved"], 2)
            self.assertEqual(file_diff["counts"]["package_root_migrations"], 1)
            self.assertEqual(file_diff["counts"]["package_root_migration_matched_files"], 2)
            migration = file_diff["package_root_migrations"][0]
            self.assertEqual(migration["old_root"], "asap7_source_package")
            self.assertEqual(migration["new_root"], "upstream_ae9a8ed9")
            self.assertEqual(migration["matched_logical_paths"], 2)
            self.assertEqual(migration["old_root_file_count"], 2)
            self.assertEqual(migration["new_root_file_count"], 3)
            self.assertEqual(file_diff["added"], ["upstream_ae9a8ed9/lib/c.lib"])
            self.assertEqual(file_diff["removed"], [])

            summary = json.loads((diff_out / "diff_summary.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["package_root_migrations"], 1)
            self.assertEqual(summary["package_root_migration_matched_files"], 2)

    def test_diff_rejects_malformed_inventory_json(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            old_scan = Path(td) / "old_scan"
            new_scan = Path(td) / "new_scan"
            old_scan.mkdir()
            new_scan.mkdir()
            (old_scan / "scan_meta.json").write_text("{}", encoding="utf-8")
            (new_scan / "scan_meta.json").write_text("{}", encoding="utf-8")
            (old_scan / "file_inventory.json").write_text("{bad json", encoding="utf-8")
            (new_scan / "file_inventory.json").write_text(json.dumps({"files": []}), encoding="utf-8")

            from lib_guard.diff.scan_diff import diff_scan_outputs

            with self.assertRaises(json.JSONDecodeError):
                diff_scan_outputs(old_scan, new_scan, out_path=Path(td) / "diff")

    def test_diff_render_writes_html_with_pairwise_task_commands(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            old_root = Path(td) / "old_raw"
            new_root = Path(td) / "new_raw"
            old_scan = Path(td) / "old_scan"
            new_scan = Path(td) / "new_scan"
            diff_out = Path(td) / "diff"
            html_out = Path(td) / "diff_html"
            old_root.mkdir()
            new_root.mkdir()
            (old_root / "constraints.sdc").write_text("create_clock -name core -period 1.0 [get_ports clk]\n", encoding="utf-8")
            (new_root / "constraints.sdc").write_text("create_clock -name core -period 2.0 [get_ports clk]\n", encoding="utf-8")

            from lib_guard.scan.scanner import ScanRunner
            from lib_guard.diff.scan_diff import diff_scan_outputs
            from lib_guard.render.html_report import render_diff_html

            base = dict(
                library_type="ip",
                library_name="demo",
                version="v1",
                scan_mode="release",
                state_dir=str(Path(td) / "state"),
                cache_dir=str(Path(td) / "cache"),
                skip_cache=True,
                no_cache=True,
                no_progress=True,
                progress_interval=1,
                parse_jobs=1,
                tool_version="0.5.0",
                schema_version="1.0",
            )
            ScanRunner(SimpleNamespace(**base, root_path=str(old_root), out_dir=str(old_scan), scan_id="OLD")).run()
            ScanRunner(SimpleNamespace(**base, root_path=str(new_root), out_dir=str(new_scan), scan_id="NEW")).run()
            diff_scan_outputs(old_scan, new_scan, out_path=diff_out)
            tasks = json.loads((diff_out / "manual_pairwise_tasks.json").read_text(encoding="utf-8"))
            first_task = tasks["tasks"][0]
            from lib_guard.diff.file_diff import diff_pairwise_files

            diff_pairwise_files(
                first_task["file_type"],
                first_task["old_file"],
                first_task["new_file"],
                first_task["expected_output"],
                task_id=first_task["task_id"],
            )

            result = render_diff_html(diff_out, html_out)

            self.assertEqual(result["status"], "PASS")
            html = (html_out / "index.html").read_text(encoding="utf-8")
            self.assertIn("Comparison 结论", html)
            self.assertIn("结构概览", html)
            self.assertIn("View 全量状态", html)
            self.assertIn("File Type 全量变化", html)
            self.assertIn("重点文件确认项", html)
            self.assertNotIn("$PROJ/scripts/lg.csh fd", html)
            self.assertNotIn("python -m lib_guard.cli file-diff", html)
            self.assertNotIn("<th>命令</th>", html)
            self.assertIn("打开 File Diff", html)
            self.assertIn("DONE", html)
            self.assertNotIn("done / total", html)

    def test_file_diff_verilog_writes_pairwise_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            old_file = Path(td) / "old.v"
            new_file = Path(td) / "new.v"
            out = Path(td) / "pair"
            old_file.write_text("module top(a);\ninput a;\nendmodule\n", encoding="utf-8")
            new_file.write_text("module top(a,b);\ninput a;\noutput b;\nendmodule\n", encoding="utf-8")

            from lib_guard.diff.file_diff import diff_pairwise_files

            result = diff_pairwise_files("verilog", old_file, new_file, out)

            self.assertEqual(result["status"], "DIFF")
            self.assertTrue((out / "file_diff_summary.json").exists())
            detail = json.loads((out / "file_diff_detail.json").read_text(encoding="utf-8"))
            self.assertEqual(detail["file_type"], "verilog")
            self.assertIn("modules", json.dumps(detail, ensure_ascii=False))
            self.assertTrue((out / "index.html").exists())
            self.assertTrue((out / "old_extract.json").exists())
            self.assertTrue((out / "new_extract.json").exists())
            self.assertTrue((out / "semantic_diff.json").exists())
            self.assertTrue((out / "raw_text_diff.html").exists())
            self.assertTrue((out / "pairwise_result.json").exists())
            pairwise = json.loads((out / "pairwise_result.json").read_text(encoding="utf-8"))
            self.assertEqual(pairwise["schema_version"], "pairwise_result.v1")
            self.assertEqual(pairwise["status"], "DONE")
            self.assertEqual(pairwise["result"], "DIFF")
            self.assertGreaterEqual(pairwise["change_count"], 1)
            html = (out / "index.html").read_text(encoding="utf-8")
            self.assertIn("单文件深度对比报告", html)
            self.assertIn("专家复核提示", html)

    def test_file_diff_does_not_hide_parser_registry_failure(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            old_file = Path(td) / "old.lef"
            new_file = Path(td) / "new.lef"
            out = Path(td) / "pair"
            old_file.write_text("MACRO M\nEND M\n", encoding="utf-8")
            new_file.write_text("MACRO M\nEND M\n", encoding="utf-8")

            from lib_guard.diff.file_diff import diff_pairwise_files

            with patch("lib_guard.scan.parser_engine.ParserRegistry.default", side_effect=RuntimeError("registry broken")):
                with self.assertRaises(RuntimeError):
                    diff_pairwise_files("lef", old_file, new_file, out)

    def test_file_diff_semantic_formats_are_structured(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            samples = {
                "liberty": (
                    root / "old.lib",
                    root / "new.lib",
                    "library(test) {\n  cell(PAD_A) {\n    area : 1.0;\n    is_macro : false;\n    is_pad : false;\n  }\n}\n",
                    "library(test) {\n  cell(PAD_A) {\n    area : 2.0;\n    is_macro : true;\n    is_pad : true;\n  }\n}\n",
                    ["is_macro", "is_pad"],
                ),
                "sdc": (
                    root / "old.sdc",
                    root / "new.sdc",
                    "create_clock -name CORE -period 10 [get_ports clk]\nset_clock_uncertainty 0.1 [get_clocks CORE]\n",
                    "create_clock -name CORE -period 8 [get_ports clk]\nset_clock_uncertainty 0.2 [get_clocks CORE]\nset_load 0.05 [get_ports data]\n",
                    ["clocks", "period", "uncertainty", "loads"],
                ),
                "upf": (
                    root / "old.upf",
                    root / "new.upf",
                    "create_power_domain PD_CORE -elements {u_core}\ncreate_supply_net VDD -domain PD_CORE\n",
                    "create_power_domain PD_CORE -elements {u_core u_io}\ncreate_supply_net VDD_NEW -domain PD_CORE\nset_isolation ISO_CORE -domain PD_CORE -clamp_value 0\n",
                    ["power_domains", "supply_nets", "isolation"],
                ),
                "ibis": (
                    root / "old.ibs",
                    root / "new.ibs",
                    "[IBIS Ver] 5.0\n[Component] U1\n[Pin]\n1 A signal MODEL_A\n[Model] MODEL_A\nModel_type Input\n",
                    "[IBIS Ver] 5.0\n[Component] U1\n[Pin]\n1 A signal MODEL_A\n2 Y signal MODEL_Y\n[Model] MODEL_Y\nModel_type Output\n",
                    ["components", "pins", "models"],
                ),
                "pwl": (
                    root / "old.pwl",
                    root / "new.pwl",
                    "0 0\n1n 1.0\n",
                    "0 0\n1n 1.2\n2n 0\n",
                    ["points", "point_count"],
                ),
                "snp": (
                    root / "old.s2p",
                    root / "new.s4p",
                    "# Hz S RI R 50\n1e9 0 0 0 0 0 0 0 0\n",
                    "# GHz S DB R 50\n1 0 0 0 0 0 0 0 0\n2 0 0 0 0 0 0 0 0\n",
                    ["option_line", "data_line_count", "ports"],
                ),
                "cpm": (
                    root / "old.cpm",
                    root / "new.cpm",
                    "COMPONENT U1\nPIN A INPUT\n",
                    "COMPONENT U1\nPIN A INPUT\nPIN Y OUTPUT\n",
                    ["components", "pins"],
                ),
                "waiver": (
                    root / "old.waiver",
                    root / "new.waiver",
                    "waive RULE_A top/u0\n",
                    "waive RULE_A top/u0\nwaive RULE_B top/u1\n",
                    ["entries", "line"],
                ),
            }

            from lib_guard.diff.file_diff import diff_pairwise_files

            for file_type, (old_file, new_file, old_text, new_text, expected_terms) in samples.items():
                old_file.write_text(old_text, encoding="utf-8")
                new_file.write_text(new_text, encoding="utf-8")
                out = root / "out" / file_type

                result = diff_pairwise_files(file_type, old_file, new_file, out)

                self.assertEqual(result["status"], "DIFF", file_type)
                semantic_text = (out / "semantic_diff.json").read_text(encoding="utf-8")
                html = (out / "index.html").read_text(encoding="utf-8")
                for term in expected_terms:
                    self.assertIn(term, semantic_text, file_type)
                self.assertIn("定位", html)
                self.assertIn("字段变化", html)

    def test_file_diff_supported_types_write_review_html(self) -> None:
        samples = {
            "lef": (
                "VERSION 5.8 ;\nMACRO U\n  SIZE 1 BY 1 ;\nEND U\n",
                "VERSION 5.8 ;\nMACRO U\n  SIZE 2 BY 1 ;\nEND U\n",
                "old.lef",
                "new.lef",
            ),
            "liberty": (
                "library(test) { cell(U) { pin(A) { direction : input; } } }\n",
                "library(test) { cell(U) { pin(A) { direction : input; } pin(Y) { direction : output; } } }\n",
                "old.lib",
                "new.lib",
            ),
            "verilog": (
                "module top(input a); endmodule\n",
                "module top(input a, output y); endmodule\n",
                "old.v",
                "new.v",
            ),
            "cdl": (
                ".SUBCKT U A VSS\nM1 A A VSS VSS N\n.ENDS U\n",
                ".SUBCKT U A Y VSS\nM1 Y A VSS VSS N\n.ENDS U\n",
                "old.cdl",
                "new.cdl",
            ),
            "sdc": (
                "create_clock -name CLK -period 10 [get_ports clk]\n",
                "create_clock -name CLK -period 8 [get_ports clk]\n",
                "old.sdc",
                "new.sdc",
            ),
            "upf": (
                "create_power_domain PD_CORE -elements {u_core}\n",
                "create_power_domain PD_CORE -elements {u_core u_io}\n",
                "old.upf",
                "new.upf",
            ),
            "cpf": (
                "create_power_domain PD_CORE -instances u_core\n",
                "create_power_domain PD_CORE -instances {u_core u_io}\n",
                "old.cpf",
                "new.cpf",
            ),
            "spef": (
                "*SPEF \"IEEE 1481-1998\"\n*DESIGN \"top\"\n*D_NET net1 1.0\n",
                "*SPEF \"IEEE 1481-1998\"\n*DESIGN \"top\"\n*D_NET net1 1.0\n*D_NET net2 2.0\n",
                "old.spef",
                "new.spef",
            ),
            "db": (
                "old db placeholder\n",
                "new db placeholder with changed size\n",
                "old.db",
                "new.db",
            ),
            "waiver": (
                "waive RULE_A top\n",
                "waive RULE_A top\nwaive RULE_B top\n",
                "old.waiver",
                "new.waiver",
            ),
            "ibis": (
                "[IBIS Ver] 5.0\n[Component] U1\n[Pin]\n1 A signal MODEL_A\n",
                "[IBIS Ver] 5.0\n[Component] U1\n[Pin]\n1 A signal MODEL_A\n2 Y signal MODEL_Y\n",
                "old.ibs",
                "new.ibs",
            ),
            "pwl": (
                "0 0\n1n 1\n",
                "0 0\n1n 1\n2n 0\n",
                "old.pwl",
                "new.pwl",
            ),
            "snp": (
                "# Hz S RI R 50\n1e9 0 0 0 0 0 0 0 0\n",
                "# Hz S RI R 50\n1e9 0 0 0 0 0 0 0 0\n2e9 0 0 0 0 0 0 0 0\n",
                "old.s2p",
                "new.s2p",
            ),
            "cpm": (
                "COMPONENT U1\nPIN A INPUT\n",
                "COMPONENT U1\nPIN A INPUT\nPIN Y OUTPUT\n",
                "old.cpm",
                "new.cpm",
            ),
        }
        with tempfile.TemporaryDirectory() as td:
            from lib_guard.diff.file_diff import diff_pairwise_files

            for file_type, (old_text, new_text, old_name, new_name) in samples.items():
                old_file = Path(td) / file_type / old_name
                new_file = Path(td) / file_type / new_name
                old_file.parent.mkdir(parents=True, exist_ok=True)
                old_file.write_text(old_text, encoding="utf-8")
                new_file.write_text(new_text, encoding="utf-8")
                out = Path(td) / "out" / file_type

                result = diff_pairwise_files(file_type, old_file, new_file, out)

                self.assertIn(result["status"], {"SAME", "DIFF", "FAILED"})
                html = (out / "index.html").read_text(encoding="utf-8")
                self.assertIn("单文件深度对比报告", html)
                self.assertIn("结构化变化", html)
                self.assertIn("原始文本差异", html)
                self.assertIn(file_type, html)
                self.assertNotIn("鍗曟枃浠", html)

    def test_file_diff_cli_exposes_all_review_types(self) -> None:
        from lib_guard.cli import build_parser

        parser = build_parser()
        for file_type in ["lef", "liberty", "verilog", "cdl", "sdc", "upf", "cpf", "spef", "db", "waiver", "ibis", "pwl", "snp", "cpm"]:
            args = parser.parse_args(["file-diff", file_type, "--old", "old", "--new", "new", "--out", "out"])
            self.assertEqual(args.file_type, file_type)

    def test_short_cli_expands_catalog_commands(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            workspace = Path(td)
            raw = workspace / "raw"
            catalog = workspace / "catalog" / "catalog.json"
            old_file = raw / "ucie" / "initial_20250601" / "lef" / "ucie.lef"
            new_file = raw / "ucie" / "stable_20250608" / "lef" / "ucie.lef"
            old_file.parent.mkdir(parents=True, exist_ok=True)
            new_file.parent.mkdir(parents=True, exist_ok=True)
            old_file.write_text("MACRO U\nEND U\n", encoding="utf-8")
            new_file.write_text("MACRO U\n  SIZE 2 BY 1 ;\nEND U\n", encoding="utf-8")
            catalog.parent.mkdir(parents=True, exist_ok=True)
            catalog.write_text(
                json.dumps(
                    {
                        "schema_version": "1.0",
                        "libraries": [
                            {
                                "library_id": "ucie",
                                "library_name": "ucie",
                                "versions": [
                                    {"version_id": "initial_20250601", "version_key": "ip/ucie/initial_20250601", "raw_path": str(raw / "ucie" / "initial_20250601")},
                                    {
                                        "version_id": "stable_20250608",
                                        "version_key": "ip/ucie/stable_20250608",
                                        "raw_path": str(raw / "ucie" / "stable_20250608"),
                                        "previous_effective_version": "initial_20250601",
                                        "diff": {"adjacent_old_version": "wrong_adjacent"},
                                    },
                                ],
                            },
                            {
                                "library_id": "pcie",
                                "library_name": "pcie",
                                "versions": [
                                    {"version_id": "base_20250601", "version_key": "ip/pcie/base_20250601", "raw_path": str(raw / "pcie" / "base_20250601")},
                                    {
                                        "version_id": "latest_20250608",
                                        "version_key": "ip/pcie/latest_20250608",
                                        "raw_path": str(raw / "pcie" / "latest_20250608"),
                                        "current_effective": True,
                                        "previous_effective_version": "base_20250601",
                                        "diff": {"adjacent_old_version": "wrong_adjacent"},
                                    },
                                ],
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            from lib_guard.short_cli import build_cli_command, build_cli_commands, write_default_config

            write_default_config(workspace, raw_root=raw)

            library_discover_cmds = build_cli_commands(["library", "discover"], cwd=workspace)
            self.assertEqual(library_discover_cmds[0][0:2], ["library", "discover"])
            self.assertIn(str(workspace / "config" / "library_candidates" / "latest.tsv"), library_discover_cmds[0])
            self.assertNotIn(str(workspace / "config" / "library.list"), library_discover_cmds[0])

            library_apply_cmds = build_cli_commands(["library", "apply"], cwd=workspace)
            self.assertEqual(library_apply_cmds[0][0:2], ["library", "apply"])
            self.assertIn(str(workspace / "config" / "library_registry.tsv"), library_apply_cmds[0])
            self.assertIn(str(workspace / "config" / "library_catalog.yml"), library_apply_cmds[0])

            library_add_cmds = build_cli_commands(
                [
                    "library",
                    "add",
                    "vendor_A.openroad_platform.openroad_asap7",
                    "--root",
                    str(raw / "vendor_A" / "openroad_asap7"),
                    "--vendor",
                    "vendor_A",
                    "--display-name",
                    "openroad_asap7",
                ],
                cwd=workspace,
            )
            self.assertEqual(library_add_cmds[0][0:2], ["library", "add"])
            self.assertIn("--registry", library_add_cmds[0])
            self.assertIn(str(workspace / "config" / "library_registry.tsv"), library_add_cmds[0])

            library_accept_cmds = build_cli_commands(["library", "accept"], cwd=workspace)
            self.assertEqual(library_accept_cmds[0][0:2], ["library", "accept"])
            self.assertIn(str(workspace / "config" / "library_candidates" / "latest.tsv"), library_accept_cmds[0])
            self.assertIn(str(workspace / "config" / "library_registry.tsv"), library_accept_cmds[0])

            library_list_cmds = build_cli_commands(["library", "list"], cwd=workspace)
            self.assertEqual(library_list_cmds[0][0:2], ["catalog", "list"])
            self.assertIn("--catalog", library_list_cmds[0])
            self.assertIn(str(workspace / "catalog" / "catalog.json"), library_list_cmds[0])

            library_list_versions_cmds = build_cli_commands(
                ["library", "list", "vendor_A.openroad_platform.openroad_asap7", "--versions"],
                cwd=workspace,
            )
            self.assertEqual(library_list_versions_cmds[0][0:2], ["catalog", "list"])
            self.assertIn("--library", library_list_versions_cmds[0])
            self.assertIn("vendor_A.openroad_platform.openroad_asap7", library_list_versions_cmds[0])
            self.assertIn("--versions", library_list_versions_cmds[0])

            catalog_cmds = build_cli_commands(["catalog"], cwd=workspace)
            self.assertEqual(len(catalog_cmds), 1)
            self.assertEqual(catalog_cmds[0][:4], ["catalog", "scan", "--root", str(raw)])

            catalog_lib_cmds = build_cli_commands(["catalog", "ucie"], cwd=workspace)
            self.assertEqual(len(catalog_lib_cmds), 1)
            self.assertEqual(catalog_lib_cmds[0][:4], ["catalog", "scan", "--root", str(raw)])
            self.assertIn("--library", catalog_lib_cmds[0])
            self.assertIn("ucie", catalog_lib_cmds[0])

            catalog_version_cmds = build_cli_commands(["cat", "ucie", "stable_20250608"], cwd=workspace)
            self.assertEqual(len(catalog_version_cmds), 1)
            self.assertEqual(catalog_version_cmds[0][:4], ["catalog", "render", "--catalog", str(workspace / "catalog" / "catalog.json")])
            self.assertIn("--library", catalog_version_cmds[0])
            self.assertIn("ucie", catalog_version_cmds[0])
            self.assertIn("--version", catalog_version_cmds[0])
            self.assertIn("stable_20250608", catalog_version_cmds[0])
            self.assertNotIn("--root", catalog_version_cmds[0])
            self.assertNotIn("--with-evidence", catalog_version_cmds[0])

            all_scan_cmds = build_cli_commands(["scan"], cwd=workspace)
            self.assertEqual(len(all_scan_cmds), 1)
            self.assertEqual(all_scan_cmds[0][:4], ["catalog", "scan", "--root", str(raw)])

            full_catalog_cmds = build_cli_commands(["catalog", "--full"], cwd=workspace)
            self.assertEqual(full_catalog_cmds[0][:2], ["catalog", "scan"])
            self.assertIn("--full", full_catalog_cmds[0])

            with self.assertRaises(ValueError) as scan_error:
                build_cli_commands(["scan", "ucie"], cwd=workspace)
            self.assertIn("scan 'ucie' is ambiguous", str(scan_error.exception))

            lib_scan_cmds = build_cli_commands(["scan", "ucie", "--all-versions"], cwd=workspace)
            self.assertEqual(lib_scan_cmds[0][:4], ["catalog", "scan", "--root", str(raw)])
            self.assertIn("--library", lib_scan_cmds[0])
            self.assertIn("ucie", lib_scan_cmds[0])
            self.assertEqual(lib_scan_cmds[1][0], "run-batch")
            self.assertIn("--library", lib_scan_cmds[1])
            self.assertIn("ucie", lib_scan_cmds[1])
            self.assertNotIn("--version", lib_scan_cmds[1])
            self.assertIn("--parse-jobs", lib_scan_cmds[1])
            self.assertIn("8", lib_scan_cmds[1])

            version_scan_cmds = build_cli_commands(["scan", "ucie", "stable_20250608"], cwd=workspace)
            self.assertEqual(len(version_scan_cmds), 1)
            self.assertEqual(version_scan_cmds[0][:5], ["run", "--catalog", str(catalog), "--library", "ucie"])
            self.assertIn("--version", version_scan_cmds[0])
            self.assertIn("stable_20250608", version_scan_cmds[0])
            self.assertIn("--parse-jobs", version_scan_cmds[0])
            self.assertIn("8", version_scan_cmds[0])

            undiscovered_scan_cmds = build_cli_commands(["scan", "ucie", "future_20250615"], cwd=workspace)
            self.assertEqual(len(undiscovered_scan_cmds), 2)
            self.assertEqual(undiscovered_scan_cmds[0][:2], ["catalog", "scan"])
            self.assertEqual(undiscovered_scan_cmds[1][0], "run")
            self.assertIn("future_20250615", undiscovered_scan_cmds[1])

            evidence_scan_cmds = build_cli_commands(["scan", "ucie", "stable_20250608", "--with-evidence"], cwd=workspace)
            self.assertEqual(len(evidence_scan_cmds), 2)
            self.assertEqual(evidence_scan_cmds[0][:2], ["catalog", "scan"])
            self.assertIn("--with-evidence", evidence_scan_cmds[0])
            self.assertEqual(evidence_scan_cmds[1][0], "run")

            scan_cmd = build_cli_command(["scan", "ucie", "stable_20250608"], cwd=workspace)
            self.assertEqual(scan_cmd, version_scan_cmds[-1])

            file_diff_cmd = build_cli_command(["file-diff", "ucie", "stable_20250608", "lef/ucie.lef"], cwd=workspace)
            self.assertEqual(file_diff_cmd[0:2], ["file-diff", "lef"])
            self.assertIn(str(old_file), file_diff_cmd)
            self.assertIn(str(new_file), file_diff_cmd)

            diff_cmds = build_cli_commands(["diff", "ucie", "stable_20250608"], cwd=workspace)
            self.assertEqual(len(diff_cmds), 1)
            self.assertEqual(diff_cmds[0][0], "compare")
            self.assertNotIn("--scan-if-missing", diff_cmds[0])

            refresh_diff_cmds = build_cli_commands(["diff", "ucie", "stable_20250608", "--refresh-catalog"], cwd=workspace)
            self.assertEqual(refresh_diff_cmds[0][:2], ["catalog", "scan"])
            self.assertEqual(refresh_diff_cmds[-1][0], "compare")

            explicit_diff_cmds = build_cli_commands(["diff", "ucie", "stable_20250608", "--base", "initial_20250601", "--auto-scan"], cwd=workspace)
            self.assertEqual(len(explicit_diff_cmds), 1)
            self.assertEqual(explicit_diff_cmds[0][0], "compare")
            self.assertIn("--scan-if-missing", explicit_diff_cmds[0])
            self.assertIn("--parse-jobs", explicit_diff_cmds[0])
            self.assertIn("8", explicit_diff_cmds[0])
            self.assertIn("--base", explicit_diff_cmds[-1])

            refresh_latest_cmds = build_cli_commands(["refresh", "ucie"], cwd=workspace)
            self.assertEqual(len(refresh_latest_cmds), 1)
            self.assertEqual(refresh_latest_cmds[0][0], "compare")
            self.assertIn("--library", refresh_latest_cmds[0])
            self.assertIn("ucie", refresh_latest_cmds[0])
            self.assertIn("--new", refresh_latest_cmds[0])
            self.assertIn("stable_20250608", refresh_latest_cmds[0])
            self.assertIn("--base", refresh_latest_cmds[0])
            self.assertIn("initial_20250601", refresh_latest_cmds[0])
            self.assertNotIn("wrong_adjacent", refresh_latest_cmds[0])
            self.assertNotIn("--mode", refresh_latest_cmds[0])
            self.assertIn("--scan-if-missing", refresh_latest_cmds[0])
            self.assertNotIn("--scan-mode", refresh_latest_cmds[0])
            self.assertIn("--parse-jobs", refresh_latest_cmds[0])

            refresh_all_cmds = build_cli_commands(["refresh", "--all"], cwd=workspace)
            self.assertEqual(len(refresh_all_cmds), 2)
            self.assertEqual(refresh_all_cmds[0][0], "compare")
            self.assertIn("stable_20250608", refresh_all_cmds[0])
            self.assertIn("--base", refresh_all_cmds[0])
            self.assertIn("initial_20250601", refresh_all_cmds[0])
            self.assertIn("pcie", refresh_all_cmds[1])
            self.assertIn("latest_20250608", refresh_all_cmds[1])
            self.assertIn("--base", refresh_all_cmds[1])
            self.assertIn("base_20250601", refresh_all_cmds[1])

    def test_short_cli_can_use_env_config_without_repeating_config_arg(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            workspace = Path(td)
            caller = workspace.parent / f"{workspace.name}_caller"
            caller.mkdir()
            raw = workspace / "raw"
            catalog = workspace / "catalog" / "catalog.json"
            catalog.parent.mkdir(parents=True, exist_ok=True)
            catalog.write_text(json.dumps({"schema_version": "1.0", "libraries": []}), encoding="utf-8")

            from lib_guard.short_cli import build_cli_commands, write_default_config

            config = write_default_config(workspace, raw_root=raw)
            with patch.dict(os.environ, {"LIB_GUARD_CONFIG": str(config)}):
                scan_cmds = build_cli_commands(["scan"], cwd=caller)

            self.assertEqual(len(scan_cmds), 1)
            self.assertEqual(scan_cmds[0][:4], ["catalog", "scan", "--root", str(raw)])
            self.assertIn(str(catalog.parent), scan_cmds[0])

    def test_short_cli_simplifies_v6_file_diff_scenarios(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            workspace = Path(td)
            raw = workspace / "raw"
            old_root = raw / "ucie" / "initial_20250601"
            new_root = raw / "ucie" / "stable_20250608"
            catalog = workspace / "catalog" / "catalog.json"
            catalog.parent.mkdir(parents=True, exist_ok=True)
            for relpath in ["model/ucie.ibs", "wave/ucie.pwl", "touch/chan.s2p", "pkg/ucie.cpm", "waiver/rules.waiver"]:
                (old_root / relpath).parent.mkdir(parents=True, exist_ok=True)
                (new_root / relpath).parent.mkdir(parents=True, exist_ok=True)
                (old_root / relpath).write_text("old\n", encoding="utf-8")
                (new_root / relpath).write_text("new\n", encoding="utf-8")
            catalog.write_text(
                json.dumps(
                    {
                        "schema_version": "1.0",
                        "libraries": [
                            {
                                "library_id": "ip/ucie",
                                "library_name": "ucie",
                                "aliases": ["u"],
                                "versions": [
                                    {"version_id": "initial_20250601", "raw_path": str(old_root)},
                                    {
                                        "version_id": "stable_20250608",
                                        "raw_path": str(new_root),
                                        "diff": {"adjacent_old_version": "initial_20250601"},
                                    },
                                ],
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            from lib_guard.short_cli import build_cli_command, build_cli_commands, write_default_config

            write_default_config(workspace, raw_root=raw)

            ibis_cmd = build_cli_command(["fd", "u", "stable_20250608", "model\\ucie.ibs"], cwd=workspace)
            self.assertEqual(ibis_cmd[0:2], ["file-diff", "ibis"])
            self.assertIn(str(old_root / "model" / "ucie.ibs"), ibis_cmd)
            self.assertIn(str(new_root / "model" / "ucie.ibs"), ibis_cmd)
            self.assertIn("--library-id", ibis_cmd)
            self.assertIn("ip/ucie", ibis_cmd)
            self.assertIn("--version-id", ibis_cmd)
            self.assertIn("stable_20250608", ibis_cmd)
            self.assertIn("--base-version", ibis_cmd)
            self.assertIn("initial_20250601", ibis_cmd)

            expected_types = [
                ("wave/ucie.pwl", "pwl"),
                ("touch/chan.s2p", "snp"),
                ("pkg/ucie.cpm", "cpm"),
                ("waiver/rules.waiver", "waiver"),
            ]
            for relpath, file_type in expected_types:
                with self.subTest(relpath=relpath):
                    cmd = build_cli_command(["file-diff", "u", "stable_20250608", relpath], cwd=workspace)
                    self.assertEqual(cmd[0:2], ["file-diff", file_type])

            explicit_cmd = build_cli_command(["file-diff", "u", "stable_20250608", "touch/chan.s2p", "--type", "snp"], cwd=workspace)
            self.assertEqual(explicit_cmd[0:2], ["file-diff", "snp"])

            catalog_alias_cmd = build_cli_commands(["cat", "u"], cwd=workspace)
            self.assertEqual(catalog_alias_cmd[0][0:2], ["catalog", "scan"])
            diff_alias_cmd = build_cli_commands(["cmp", "u", "stable_20250608", "--base", "initial_20250601"], cwd=workspace)
            self.assertEqual(diff_alias_cmd[0][0], "compare")
            self.assertIn("--base", diff_alias_cmd[0])

    def test_csh_short_command_wrapper_is_available(self) -> None:
        root = Path(__file__).resolve().parents[3]
        wrapper = root / "scripts" / "lg.csh"

        self.assertTrue(wrapper.exists())
        text = wrapper.read_text(encoding="utf-8")
        self.assertIn("lib_guard.short_cli", text)
        self.assertIn("PYTHONPATH", text)

    def test_short_cli_help_shows_minimal_workflow_examples(self) -> None:
        from lib_guard.short_cli import _build_parser

        help_text = _build_parser().format_help()

        self.assertIn("示例", help_text)
        self.assertIn("日常流程", help_text)
        self.assertIn("lg.csh scan", help_text)
        self.assertIn("lg.csh refresh", help_text)
        self.assertIn("lg.ps1 scan", help_text)
        self.assertIn("file-diff -> fd", help_text)
        self.assertIn("diff -> cmp", help_text)
        self.assertIn("--force-large", help_text)
        self.assertIn("spice", help_text)
        self.assertIn("touchstone", help_text)
        supported_types = help_text.split("支持的两两文件 diff 类型:", 1)[1].splitlines()[1]
        self.assertNotIn("verilog", supported_types)
        self.assertNotIn("liberty", supported_types)
        self.assertNotIn("spef", supported_types)
        self.assertNotIn("db", supported_types)
        self.assertIn("lg.csh override", help_text)
        self.assertIn("lg.csh action", help_text)
        self.assertIn("lg.csh rv-accept", help_text)
        for token in ["waiver", "ibis", "pwl", "snp", "cpm"]:
            self.assertIn(token, supported_types)
        self.assertNotIn("filediff", help_text)
        self.assertNotIn("refresh-diff", help_text)

    def test_short_cli_file_diff_help_documents_force_large(self) -> None:
        from lib_guard.short_cli import _build_parser

        parser = _build_parser()
        subparsers = [action for action in parser._actions if isinstance(action, argparse._SubParsersAction)]
        self.assertEqual(1, len(subparsers))
        file_diff_parser = subparsers[0].choices["file-diff"]
        help_text = file_diff_parser.format_help()

        self.assertIn("--force-large", help_text)
        self.assertIn("Expert opt-in", help_text)

    def test_short_cli_rejects_removed_legacy_aliases(self) -> None:
        from lib_guard.short_cli import _build_parser

        parser = _build_parser()
        with contextlib.redirect_stderr(io.StringIO()):
            for argv in [
                ["filediff", "ucie", "v1", "lef/ucie.lef"],
                ["refresh-diff", "ucie"],
                ["lib", "discover"],
                ["act", "ucie"],
                ["review", "ucie"],
                ["compare", "ucie", "v1"],
                ["rf", "ucie"],
            ]:
                with self.subTest(argv=argv):
                    with self.assertRaises(SystemExit):
                        parser.parse_args(argv)

    def test_low_level_cli_hides_removed_update_command(self) -> None:
        from lib_guard.cli import build_parser

        help_text = build_parser().format_help()
        self.assertNotIn("update", help_text)

    def test_short_cli_action_file_skips_existing_and_supports_redo_verbs(self) -> None:
        from lib_guard.short_cli import build_cli_commands, write_default_config

        with tempfile.TemporaryDirectory() as td:
            workspace = Path(td)
            raw = workspace / "raw"
            raw.mkdir()
            write_default_config(workspace, raw_root=raw)
            config_dir = workspace / "config"
            config_dir.mkdir(exist_ok=True)
            actions = workspace / "actions"
            actions.mkdir()
            catalog_dir = workspace / "catalog"
            existing_scan = workspace / "scan_out" / "ucie" / "stable_20260601"
            existing_scan.mkdir(parents=True)
            catalog_dir.mkdir()
            (catalog_dir / "catalog.json").write_text(
                json.dumps(
                    {
                        "libraries": [
                            {
                                "library_id": "ip/ucie",
                                "library_type": "ip",
                                "library_name": "ucie",
                                "versions": [
                                    {
                                        "version_id": "stable_20260601",
                                        "version_key": "ip/ucie/stable_20260601",
                                        "raw_path": str(raw / "ucie" / "stable_20260601"),
                                        "scan": {"scan_dir": str(existing_scan), "status": "PASS"},
                                    },
                                    {
                                        "version_id": "adhoc_01",
                                        "version_key": "ip/ucie/adhoc_01",
                                        "raw_path": str(raw / "ucie" / "adhoc_01"),
                                        "scan": {"status": "NOT_SCANNED"},
                                    },
                                    {
                                        "version_id": "final_20260625",
                                        "version_key": "ip/ucie/final_20260625",
                                        "raw_path": str(raw / "ucie" / "final_20260625"),
                                        "scan": {"status": "NOT_SCANNED"},
                                    },
                                ],
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (config_dir / "library_versions.tsv").write_text(
                "library_id\tversion_ref\tversion_id\n"
                "ucie\tlib1\tstable_20260601\n"
                "ucie\tlib2\tadhoc_01\n"
                "ucie\tlib3\tfinal_20260625\n",
                encoding="utf-8",
            )
            (actions / "ucie.action").write_text(
                "@effect rec_20260624 lib1 lib2\n"
                "@scan auto lib3\n"
                "@rescan lib1\n"
                "@diff current rec_20260624 main\n"
                "@rediff rec_20260624 lib3 final_check\n"
                "@release rec_20260624\n"
                "@rerelease rec_20260624\n",
                encoding="utf-8",
            )

            commands = build_cli_commands(["action", "ucie"], cwd=workspace)
            rendered = [" ".join(cmd) for cmd in commands]

            self.assertTrue(any("run --catalog" in cmd and "--version adhoc_01" in cmd for cmd in rendered))
            self.assertTrue(any("run --catalog" in cmd and "--version final_20260625" in cmd for cmd in rendered))
            self.assertTrue(any("run --catalog" in cmd and "--version stable_20260601" in cmd for cmd in rendered))
            self.assertEqual(sum(1 for cmd in rendered if "run --catalog" in cmd and "--version stable_20260601" in cmd), 1)
            self.assertTrue(any("effective build" in cmd and "--effective-id rec_20260624" in cmd for cmd in rendered))
            self.assertTrue(any("effective compare" in cmd and "--compare-id main" in cmd for cmd in rendered))
            self.assertTrue(any("effective compare" in cmd and "--compare-id final_check" in cmd for cmd in rendered))
            self.assertEqual(sum(1 for cmd in rendered if "effective release-preview" in cmd), 2)

    def test_short_cli_action_all_redo_forces_every_action(self) -> None:
        from lib_guard.short_cli import build_cli_commands, write_default_config

        with tempfile.TemporaryDirectory() as td:
            workspace = Path(td)
            raw = workspace / "raw"
            raw.mkdir()
            write_default_config(workspace, raw_root=raw)
            actions = workspace / "actions"
            actions.mkdir()
            catalog_dir = workspace / "catalog"
            catalog_dir.mkdir()
            existing_scan = workspace / "scan_out" / "ucie" / "stable_20260601"
            existing_scan.mkdir(parents=True)
            effective_dir = catalog_dir / "html" / "libraries" / "ip_ucie" / "effective" / "rec_20260624"
            release_dir = effective_dir / "release_preview"
            compare_dir = catalog_dir / "html" / "libraries" / "ip_ucie" / "compare" / "main"
            release_dir.mkdir(parents=True)
            compare_dir.mkdir(parents=True)
            (effective_dir / "effective_manifest.json").write_text("{}", encoding="utf-8")
            (release_dir / "release_manifest.json").write_text("{}", encoding="utf-8")
            (compare_dir / "compare_manifest.json").write_text("{}", encoding="utf-8")
            (catalog_dir / "catalog.json").write_text(
                json.dumps(
                    {
                        "libraries": [
                            {
                                "library_id": "ip/ucie",
                                "library_type": "ip",
                                "library_name": "ucie",
                                "versions": [
                                    {
                                        "version_id": "stable_20260601",
                                        "version_key": "ip/ucie/stable_20260601",
                                        "raw_path": str(raw / "ucie" / "stable_20260601"),
                                        "scan": {"scan_dir": str(existing_scan), "status": "PASS"},
                                    }
                                ],
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            action_path = actions / "ucie.action"
            action_path.write_text(
                "@ALL redo\n"
                "@effect rec_20260624 stable_20260601\n"
                "@scan auto\n"
                "@diff current rec_20260624 main\n"
                "@release rec_20260624\n",
                encoding="utf-8",
            )

            commands = build_cli_commands(["action", "ucie"], cwd=workspace)
            rendered = [" ".join(cmd) for cmd in commands]

            self.assertTrue(any("run --catalog" in cmd and "--version stable_20260601" in cmd for cmd in rendered))
            self.assertTrue(any("effective build" in cmd and "--effective-id rec_20260624" in cmd for cmd in rendered))
            self.assertTrue(any("effective compare" in cmd and "--compare-id main" in cmd for cmd in rendered))
            self.assertTrue(any("effective release-preview" in cmd for cmd in rendered))

            from lib_guard.short_cli import _parse_review_actions

            plan = _parse_review_actions(action_path)["action_plan"]
            self.assertTrue(plan["force_all_redo"])
            self.assertEqual(plan["source"], "@ALL redo")
            self.assertEqual(plan["warning"], "All existing outputs may be regenerated.")

    def test_short_cli_action_auto_scan_refreshes_stale_scan_evidence(self) -> None:
        from lib_guard.short_cli import build_cli_commands, write_default_config

        with tempfile.TemporaryDirectory() as td:
            workspace = Path(td)
            raw = workspace / "raw"
            raw.mkdir()
            write_default_config(workspace, raw_root=raw)
            actions = workspace / "actions"
            actions.mkdir()
            catalog_dir = workspace / "catalog"
            stale_scan = workspace / "scan_out" / "ucie" / "stable_20260601"
            stale_scan.mkdir(parents=True)
            catalog_dir.mkdir()
            (catalog_dir / "catalog.json").write_text(
                json.dumps(
                    {
                        "libraries": [
                            {
                                "library_id": "ip/ucie",
                                "library_type": "ip",
                                "library_name": "ucie",
                                "versions": [
                                    {
                                        "version_id": "stable_20260601",
                                        "version_key": "ip/ucie/stable_20260601",
                                        "raw_path": str(raw / "ucie" / "stable_20260601"),
                                        "scan": {
                                            "scan_dir": str(stale_scan),
                                            "status": "STALE_SCAN",
                                            "stale_reason": "version_fingerprint_changed",
                                        },
                                    }
                                ],
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (actions / "ucie.action").write_text(
                "@effect rec_20260624 stable_20260601\n"
                "@scan auto\n",
                encoding="utf-8",
            )

            commands = build_cli_commands(["action", "ucie"], cwd=workspace)
            rendered = [" ".join(cmd) for cmd in commands]

            self.assertTrue(any("run --catalog" in cmd and "--version stable_20260601" in cmd for cmd in rendered))

    def test_catalog_workflow_does_not_trigger_summary_rebuild(self) -> None:
        import inspect

        from lib_guard.cli_commands.catalog import run_catalog_workflow

        source = inspect.getsource(run_catalog_workflow)
        self.assertNotIn("rebuild_summary_from_scan", source)
        self.assertNotIn("rebuilt_summaries", source)
        self.assertNotIn("developer_artifacts", source)

    def test_scan_cli_exposes_one_scan_mode_and_strategy_controls_depth(self) -> None:
        from lib_guard.cli import build_parser

        parser = build_parser()

        direct = parser.parse_args(["scan", "--root", "raw", "--profile", "ip", "--name", "ucie", "--version", "stable_20250608"])
        run = parser.parse_args(["run", "--catalog", "catalog.json", "--library", "ucie", "--version", "stable_20250608"])
        batch = parser.parse_args(["run-batch", "--catalog", "catalog.json"])
        compare = parser.parse_args(["compare", "--catalog", "catalog.json", "--library", "ucie", "--new", "stable_20250608", "--scan-if-missing"])
        render = parser.parse_args(["render", "--latest", "--library-id", "ip/ucie/stable_20250608"])
        status = parser.parse_args(["scan-status", "--latest", "--library-id", "ip/ucie/stable_20250608"])

        self.assertEqual(direct.mode, "scan")
        self.assertEqual(run.mode, "scan")
        self.assertEqual(batch.mode, "scan")
        self.assertEqual(compare.scan_mode, "scan")
        self.assertEqual(render.mode, "scan")
        self.assertEqual(status.mode, "scan")

        with self.assertRaises(SystemExit):
            parser.parse_args(["scan", "--root", "raw", "--profile", "ip", "--name", "ucie", "--version", "stable_20250608", "--mode", "candidate"])

    def test_short_cli_init_defaults_to_version_review_scan_mode(self) -> None:
        from lib_guard.short_cli import write_default_config

        with tempfile.TemporaryDirectory() as td:
            config = write_default_config(Path(td), raw_root=Path(td) / "raw")

            self.assertIn("mode: scan", config.read_text(encoding="utf-8"))

    def test_short_cli_uses_scan_strategy_config_without_mode_flags(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            workspace = Path(td)
            raw = workspace / "raw"
            catalog = workspace / "catalog" / "catalog.json"
            catalog.parent.mkdir(parents=True, exist_ok=True)
            catalog.write_text(
                json.dumps(
                    {
                        "schema_version": "1.0",
                        "libraries": [
                            {
                                "library_id": "ip/ucie",
                                "library_name": "ucie",
                                "versions": [
                                    {"version_id": "initial_20250601", "version_key": "ip/ucie/initial_20250601", "raw_path": str(raw / "ucie" / "initial_20250601")},
                                    {
                                        "version_id": "stable_20250608",
                                        "version_key": "ip/ucie/stable_20250608",
                                        "raw_path": str(raw / "ucie" / "stable_20250608"),
                                        "previous_effective_version": "initial_20250601",
                                    },
                                ],
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            from lib_guard.short_cli import build_cli_commands, write_default_config

            config = write_default_config(workspace, raw_root=raw)
            config.write_text(
                config.read_text(encoding="utf-8")
                + "hash_policy: full\n"
                + "parse_file_types: lef,cdl\n"
                + "parse_exclude_file_types: verilog,liberty\n",
                encoding="utf-8",
            )

            scan_cmd = build_cli_commands(["scan", "ucie", "stable_20250608"], cwd=workspace)[0]
            refresh_cmd = build_cli_commands(["refresh", "ucie"], cwd=workspace)[0]
            batch_cmd = build_cli_commands(["scan", "ucie", "--missing"], cwd=workspace)[1]

            for command in [scan_cmd, refresh_cmd, batch_cmd]:
                self.assertNotIn("--mode", command)
                self.assertNotIn("--scan-mode", command)
                self.assertIn("--hash-policy", command)
                self.assertIn("full", command)
                self.assertIn("--parse-file-types", command)
                self.assertIn("lef,cdl", command)
                self.assertIn("--parse-exclude-file-types", command)
                self.assertIn("verilog,liberty", command)

    def test_short_cli_config_paths_follow_project_config_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            workspace = Path(td)
            raw = workspace / "raw"

            from lib_guard.project_config import workspace_defaults
            from lib_guard.short_cli import _load_config, write_default_config

            config = write_default_config(workspace, raw_root=raw)
            cfg = _load_config(workspace, str(config))
            defaults = workspace_defaults(workspace, raw_root=raw)

            for key in ["catalog", "catalog_html", "library_registry", "library_candidates", "library_catalog", "library_versions", "actions_dir"]:
                self.assertEqual(cfg[key], defaults[key])

    def test_scan_writer_keeps_release_readiness_as_derived_output(self) -> None:
        import inspect

        from lib_guard.scan.report import ScanReportWriter
        from lib_guard.scan.scanner import ScanRunner

        writer_source = inspect.getsource(ScanReportWriter.write_bundle)
        self.assertNotIn("build_release_readiness", writer_source)

        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "raw"
            out = Path(td) / "scan"
            root.mkdir()
            (root / "top.v").write_text("module top(input a); endmodule\n", encoding="utf-8")

            ScanRunner(
                SimpleNamespace(
                    root_path=str(root),
                    out_dir=str(out),
                    library_type="ip",
                    library_name="demo",
                    version="stable_20250608",
                    scan_mode="scan",
                    scan_id="DERIVED",
                    state_dir=str(Path(td) / "state"),
                    cache_dir=str(Path(td) / "cache"),
                    skip_cache=True,
                    no_cache=True,
                    no_progress=True,
                    progress_interval=1,
                    parse_jobs=1,
                )
            ).run()
            self.assertTrue((out / "summary" / "release_readiness.json").exists())

    def test_scan_writes_parser_manifest_once_after_parse_stage(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "raw"
            out = Path(td) / "scan"
            root.mkdir()
            (root / "a.v").write_text("module a; endmodule\n", encoding="utf-8")
            (root / "b.v").write_text("module b; endmodule\n", encoding="utf-8")

            from lib_guard.scan.scanner import ScanRunner

            original = ScanRunner._write_incremental_json
            counts: dict[str, int] = {}

            def counting_write(self: object, path: str | Path, data: object) -> None:
                name = Path(path).name
                counts[name] = counts.get(name, 0) + 1
                return original(self, path, data)

            with patch.object(ScanRunner, "_write_incremental_json", counting_write):
                ScanRunner(
                    SimpleNamespace(
                        root_path=str(root),
                        out_dir=str(out),
                        library_type="ip",
                        library_name="demo",
                        version="stable_20250608",
                        scan_mode="scan",
                        scan_id="MANIFEST_ONCE",
                        state_dir=str(Path(td) / "state"),
                        cache_dir=str(Path(td) / "cache"),
                        skip_cache=True,
                        no_cache=True,
                        no_progress=True,
                        progress_interval=1,
                        parse_jobs=1,
                        parse_file_types=["verilog"],
                    )
                ).run()

            self.assertEqual(counts.get("parser_manifest.json"), 1)

    def test_parser_task_planning_does_not_probe_parser_cache(self) -> None:
        import inspect

        from lib_guard.scan.scanner import ScanRunner

        source = inspect.getsource(ScanRunner._build_parser_task_list)
        self.assertNotIn("get_parser_result", source)

    def test_scan_signature_uses_smart_hash_policy_for_heavy_eda_files(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "raw"
            out = Path(td) / "scan"
            root.mkdir()
            (root / "top.v").write_text("module top(input a); endmodule\n", encoding="utf-8")
            (root / "block.lef").write_text("VERSION 5.8 ;\nMACRO B\nEND B\n", encoding="utf-8")
            (root / "cell.lib").write_text("library(test) { cell(B) { area : 1; } }\n", encoding="utf-8")
            (root / "README.md").write_text("release note\n", encoding="utf-8")

            from lib_guard.scan.scanner import ScanRunner

            ScanRunner(
                SimpleNamespace(
                    root_path=str(root),
                    out_dir=str(out),
                    library_type="ip",
                    library_name="demo",
                    version="stable_20250608",
                    scan_mode="signature",
                    scan_id="SMART",
                    state_dir=str(Path(td) / "state"),
                    cache_dir=str(Path(td) / "cache"),
                    skip_cache=True,
                    no_cache=True,
                    no_progress=True,
                    progress_interval=1,
                    parse_jobs=1,
                    tool_version="0.5.0",
                    schema_version="1.0",
                )
            ).run()

            inventory = json.loads((out / "file_inventory.json").read_text(encoding="utf-8"))
            by_path = {item["path"]: item for item in inventory["files"]}
            self.assertEqual(by_path["block.lef"]["hash_status"], "SKIPPED_BY_SMART_POLICY")
            self.assertIsNone(by_path["block.lef"].get("hash"))
            self.assertEqual(by_path["cell.lib"]["hash_status"], "SKIPPED_BY_SMART_POLICY")
            self.assertEqual(by_path["top.v"]["hash_status"], "CALCULATED")
            self.assertIn("sha256:", by_path["top.v"].get("hash", ""))
            version_profile = json.loads((out / "version_profile.json").read_text(encoding="utf-8"))
            self.assertEqual(version_profile["hash_policy"]["policy"], "smart")
            self.assertIn("version_kind", version_profile)

    def test_governance_diff_pairs_unique_added_removed_file_type(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            old_root = Path(td) / "old_raw"
            new_root = Path(td) / "new_raw"
            old_scan = Path(td) / "old_scan"
            new_scan = Path(td) / "new_scan"
            diff_out = Path(td) / "diff"
            (old_root / "old_view").mkdir(parents=True)
            (new_root / "new_view").mkdir(parents=True)
            (old_root / "old_view" / "block.lef").write_text("VERSION 5.8 ;\nMACRO A\n  SIZE 1 BY 1 ;\nEND A\n", encoding="utf-8")
            (new_root / "new_view" / "block.lef").write_text("VERSION 5.8 ;\nMACRO A\n  SIZE 2 BY 1 ;\nEND A\n", encoding="utf-8")

            from lib_guard.scan.scanner import ScanRunner
            from lib_guard.diff.scan_diff import diff_scan_outputs

            base = dict(
                library_type="ip",
                library_name="demo",
                version="v1",
                scan_mode="release",
                state_dir=str(Path(td) / "state"),
                cache_dir=str(Path(td) / "cache"),
                skip_cache=True,
                no_cache=True,
                no_progress=True,
                progress_interval=1,
                parse_jobs=1,
                tool_version="0.5.0",
                schema_version="1.0",
            )
            ScanRunner(SimpleNamespace(**base, root_path=str(old_root), out_dir=str(old_scan), scan_id="OLD")).run()
            ScanRunner(SimpleNamespace(**base, root_path=str(new_root), out_dir=str(new_scan), scan_id="NEW")).run()
            diff_scan_outputs(old_scan, new_scan, out_path=diff_out)

            tasks = json.loads((diff_out / "pairwise_diff_tasks.json").read_text(encoding="utf-8"))
            self.assertEqual(tasks["summary"]["by_type"]["lef"], 1)
            self.assertEqual(tasks["tasks"][0]["pairing_confidence"], "unique_file_type")
            self.assertNotIn("command", tasks["tasks"][0])
            self.assertNotIn("low_level_command", tasks["tasks"][0])

    def test_legacy_extractor_paths_are_removed(self) -> None:
        import importlib

        with self.assertRaises(ModuleNotFoundError):
            importlib.import_module("lib_guard.scan.extractors")
        with self.assertRaises(ModuleNotFoundError):
            importlib.import_module("lib_guard.extractors.verilog_extractor")

    def test_scanner_services_do_not_include_summary_builders(self) -> None:
        from lib_guard.scan.scanner import ScannerServices

        self.assertNotIn("summary_builders", ScannerServices.__dataclass_fields__)
        self.assertNotIn("extractors", ScannerServices.__dataclass_fields__)

    def test_parser_file_apis_output_v2_result_without_legacy_parser_key(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            samples = {
                "verilog": (Path(td) / "top.v", "module top(input a); endmodule\n"),
                "lef": (Path(td) / "block.lef", "VERSION 5.8 ;\nMACRO NAND2\nEND NAND2\n"),
                "liberty": (Path(td) / "cell.lib", "library(test) { cell(NAND2) { area : 1.0; } }\n"),
                "cdl": (Path(td) / "netlist.cdl", ".SUBCKT INV A Y VDD VSS\nM1 Y A VDD VDD pmos\n.ENDS INV\n"),
                "sdc": (Path(td) / "block.sdc", "create_clock -name clk -period 1.0 [get_ports clk]\n"),
                "upf": (Path(td) / "block.upf", "create_power_domain PD_TOP\n"),
                "cpf": (Path(td) / "block.cpf", "create_power_domain PD_TOP\n"),
                "spef": (Path(td) / "block.spef", "*SPEF \"IEEE 1481-1998\"\n*D_NET net1 0.1\n"),
                "filelist": (Path(td) / "files.f", "+incdir+rtl\nrtl/top.v\n"),
                "package": (Path(td) / "model.s2p", "# Hz S RI R 50\n1 0 0 0 0\n"),
                "waiver": (Path(td) / "rules.waiver", "waive RULE_A top\n"),
                "db": (Path(td) / "lib.db", "binary-placeholder"),
            }
            for path, text in samples.values():
                path.write_text(text, encoding="utf-8")

            from lib_guard.scan.parsers.verilog import parse_verilog_file
            from lib_guard.scan.parsers.lef import parse_lef_file
            from lib_guard.scan.parsers.liberty import parse_liberty_file
            from lib_guard.scan.parsers.cdl import parse_cdl_file
            from lib_guard.scan.parsers.sdc import parse_sdc_file
            from lib_guard.scan.parsers.upf import parse_upf_file
            from lib_guard.scan.parsers.cpf import parse_cpf_file
            from lib_guard.scan.parsers.spef import parse_spef_file
            from lib_guard.scan.parsers.filelist import parse_filelist_file
            from lib_guard.scan.parsers.package import parse_package_file, parse_touchstone_file
            from lib_guard.scan.parsers.waiver import parse_waiver_file
            from lib_guard.scan.parsers.db import parse_db_file

            for result, parser_name, file_type in [
                (parse_verilog_file(samples["verilog"][0]), "VerilogParser", "verilog"),
                (parse_lef_file(samples["lef"][0]), "LefParser", "lef"),
                (parse_liberty_file(samples["liberty"][0]), "LibertyParser", "liberty"),
                (parse_cdl_file(samples["cdl"][0]), "CdlParser", "cdl"),
                (parse_sdc_file(samples["sdc"][0]), "SdcParser", "sdc"),
                (parse_upf_file(samples["upf"][0]), "UpfParser", "upf"),
                (parse_cpf_file(samples["cpf"][0]), "CpfParser", "cpf"),
                (parse_spef_file(samples["spef"][0]), "SpefParser", "spef"),
                (parse_filelist_file(samples["filelist"][0]), "FilelistParser", "filelist"),
                (parse_package_file(samples["package"][0]), "PackageParser", "package"),
                (parse_touchstone_file(samples["package"][0]), "PackageParser", "touchstone"),
                (parse_waiver_file(samples["waiver"][0]), "WaiverParser", "waiver"),
                (parse_db_file(samples["db"][0]), "DbParser", "db"),
            ]:
                self.assertEqual(result["result_type"], "parser_result")
                self.assertEqual(result["parser_name"], parser_name)
                self.assertEqual(result["parser_version"], "2.0")
                self.assertEqual(result["parser_schema_version"], "1.0")
                self.assertEqual(result["file_type"], file_type)
                self.assertEqual(result["compression"], None)
                self.assertIn(result["status"], {"PASS", "PASS_EMPTY", "METADATA_ONLY"})
                self.assertIn("object_count", result["stats"])
                self.assertNotIn("parser", result)

    def test_cdl_parser_extracts_subckt_pins_and_instances(self) -> None:
        from lib_guard.scan.parsers.cdl import parse_cdl_text

        data = parse_cdl_text(
            "\n".join(
                [
                    '.INCLUDE "models.sp"',
                    ".SUBCKT SRAM A0 A1",
                    "+ D0 D1 VDD VSS",
                    "M0 D0 A0 VDD VDD pmos L=0.15 W=1.0",
                    "XBUF A0 D0 VDD VSS INV",
                    "RKEEP D1 VSS 1k",
                    ".ENDS SRAM",
                ]
            )
        )

        self.assertEqual(data["stats"]["subckt_count"], 1)
        self.assertEqual(data["stats"]["include_count"], 1)
        self.assertEqual(data["stats"]["pin_count"], 6)
        self.assertEqual(data["stats"]["instance_count"], 3)
        sram = data["subckts"]["SRAM"]
        self.assertEqual(sram["pins"], ["A0", "A1", "D0", "D1", "VDD", "VSS"])
        self.assertEqual(sram["pin_count"], 6)
        self.assertEqual(sram["instance_count"], 3)
        self.assertEqual([item["name"] for item in sram["instances"]], ["M0", "XBUF", "RKEEP"])
        self.assertEqual(sram["instances"][0]["target"], "pmos")
        self.assertEqual(sram["instances"][0]["kind"], "mos")
        self.assertEqual(sram["instances"][1]["target"], "INV")
        self.assertEqual(sram["instances"][1]["kind"], "subckt")

    def test_lef_parser_extracts_technology_layers_and_pin_geometry(self) -> None:
        from lib_guard.scan.parsers.lef import parse_lef_text

        data = parse_lef_text(
            "\n".join(
                [
                    "VERSION 5.8 ;",
                    "UNITS",
                    "  DATABASE MICRONS 2000 ;",
                    "END UNITS",
                    "LAYER M1",
                    "  TYPE ROUTING ;",
                    "  DIRECTION HORIZONTAL ;",
                    "  PITCH 0.040 ;",
                    "  WIDTH 0.020 ;",
                    "END M1",
                    "MACRO SRAM",
                    "  CLASS BLOCK ;",
                    "  ORIGIN 0 0 ;",
                    "  SIZE 10 BY 20 ;",
                    "  PIN CLK",
                    "    DIRECTION INPUT ;",
                    "    USE SIGNAL ;",
                    "    PORT",
                    "      LAYER M1 ;",
                    "      RECT 0 0 1 1 ;",
                    "    END",
                    "  END CLK",
                    "  OBS",
                    "    LAYER M1 ;",
                    "    RECT 0 0 10 20 ;",
                    "  END",
                    "END SRAM",
                ]
            )
        )

        self.assertEqual(data["database_microns"], 2000)
        self.assertEqual(data["stats"]["macro_count"], 1)
        self.assertEqual(data["stats"]["pin_count"], 1)
        self.assertEqual(data["stats"]["layer_count"], 1)
        self.assertEqual(data["stats"]["pin_rect_count"], 1)
        self.assertEqual(data["stats"]["obs_rect_count"], 1)
        self.assertEqual(data["layers"]["M1"]["type"], "ROUTING")
        self.assertEqual(data["layers"]["M1"]["direction"], "HORIZONTAL")
        self.assertEqual(data["layers"]["M1"]["width"], 0.02)
        macro = data["macros"]["SRAM"]
        self.assertEqual(macro["class"], "BLOCK")
        self.assertEqual(macro["size"], {"x": 10.0, "y": 20.0})
        self.assertEqual(macro["area"], 200.0)
        pin = macro["pins"]["CLK"]
        self.assertEqual(pin["direction"], "INPUT")
        self.assertEqual(pin["use"], "SIGNAL")
        self.assertEqual(pin["layers"], ["M1"])
        self.assertEqual(pin["layer_count"], 1)
        self.assertEqual(pin["rect_count"], 1)

    def test_verilog_parser_declares_lightweight_scope_and_unparsed_features(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "top.v"
            path.write_text(
                "\n".join(
                    [
                        "module child(input a, output b); endmodule",
                        "module top(input clk, input [3:0] data, output done);",
                        "  child u_child(.a(clk), .b(done));",
                        "endmodule",
                    ]
                ),
                encoding="utf-8",
            )

            from lib_guard.scan.parsers.verilog import parse_verilog_file

            result = parse_verilog_file(path)
            data = result["data"]
            self.assertEqual(data["stats"]["module_count"], 2)
            self.assertEqual(data["stats"]["port_count"], 5)
            self.assertEqual(data["parse_strategy"], "lightweight_rtl_interface")
            self.assertEqual(
                data["parsed_fields"],
                ["module", "port", "direction", "width", "declared_range", "module_count", "port_count"],
            )
            self.assertIn("instance", data["unparsed_features"])
            self.assertIn("gate_netlist_connectivity", data["unparsed_features"])
            self.assertNotIn("instances", data)
            self.assertNotIn("instance_count", data["stats"])


if __name__ == "__main__":
    unittest.main()
