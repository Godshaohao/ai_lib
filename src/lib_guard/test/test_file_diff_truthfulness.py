"""Raw bytes and parsed fields must remain separate pairwise evidence."""

from __future__ import annotations

import json
import gzip
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from lib_guard.diff.file_diff import diff_pairwise_files


class FileDiffTruthfulnessTest(unittest.TestCase):
    def compare(self, kind: str, ext: str, before: str, after: str):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            old = root / ("old" + ext)
            new = root / ("new" + ext)
            old.write_text(before, encoding="utf-8")
            new.write_text(after, encoding="utf-8")
            output = root / "out"
            result = diff_pairwise_files(kind, old, new, output)
            summary = json.loads((output / "file_diff_summary.json").read_text())
            semantic = json.loads((output / "semantic_diff.json").read_text())
            pairwise = json.loads((output / "pairwise_result.json").read_text())
            return result, summary, semantic, pairwise

    def assert_source_changed_but_extracted_same(self, result, summary, semantic, pairwise):
        self.assertEqual(summary["source_content_status"], "DIFF")
        self.assertEqual(summary["parsed_fields_status"], "SAME")
        self.assertTrue(summary["unexplained_change"])
        self.assertNotEqual(summary["content_sha256"]["old"], summary["content_sha256"]["new"])
        self.assertEqual(result["status"], "DIFF")
        self.assertEqual(pairwise["result"], "DIFF")
        self.assertEqual(semantic["status"], "SAME")

    def test_verilog_assign_change_must_not_be_top_level_same(self):
        before = "module top(input a, output y); assign y = a; endmodule\n"
        after = "module top(input a, output y); assign y = ~a; endmodule\n"
        self.assert_source_changed_but_extracted_same(*self.compare("verilog", ".v", before, after))

    def test_liberty_timing_table_change_must_not_be_top_level_same(self):
        def liberty(values: str) -> str:
            return ("library (L) { cell (M) { area : 100; pin (A) { direction : input; } "
                    "pin (Y) { direction : output; timing () { related_pin : \"A\"; "
                    "cell_rise (T) { values (\"%s\"); } } } } }\n") % values

        self.assert_source_changed_but_extracted_same(
            *self.compare("liberty", ".lib", liberty("0.10, 0.12"), liberty("0.15, 0.18"))
        )

    def test_identical_bytes_in_different_paths_still_same(self):
        content = "module top(input a, output y); assign y = a; endmodule\n"
        result, summary, semantic, pairwise = self.compare("verilog", ".v", content, content)
        self.assertEqual(result["status"], "SAME")
        self.assertEqual(pairwise["result"], "SAME")
        self.assertEqual(summary["source_content_status"], "SAME")
        self.assertEqual(summary["parsed_fields_status"], "SAME")
        self.assertFalse(summary["unexplained_change"])
        self.assertEqual(semantic["status"], "SAME")

    def test_comment_only_change_is_raw_difference_not_parser_change(self):
        before = "// build A\nmodule top(input a, output y); assign y = a; endmodule\n"
        after = "// build B\nmodule top(input a, output y); assign y = a; endmodule\n"
        result, summary, semantic, pairwise = self.compare("verilog", ".v", before, after)
        self.assertEqual(summary["source_content_status"], "DIFF")
        self.assertEqual(summary["parsed_fields_status"], "SAME")
        self.assertEqual(result["status"], "DIFF")
        self.assertEqual(semantic["status"], "SAME")
        self.assertEqual(pairwise["result"], "DIFF")

    def test_lef_rect_coordinate_change_has_raw_and_extracted_difference(self):
        from lib_guard.test.test_lef_check_facts import LEF

        result, summary, semantic, pairwise = self.compare(
            "lef", ".lef", LEF, LEF.replace("RECT 0 0 1 1 ;", "RECT 0 0 2 1 ;")
        )
        self.assertEqual(result["status"], "DIFF")
        self.assertEqual(summary["source_content_status"], "DIFF")
        self.assertEqual(summary["parsed_fields_status"], "DIFF")
        self.assertFalse(summary["unexplained_change"])
        self.assertEqual(semantic["status"], "DIFF")
        self.assertEqual(pairwise["result"], "DIFF")

    def test_gzip_header_change_does_not_claim_raw_equality(self):
        text = b"library (L) { cell (M) { area : 100; pin (A) { direction : input; } } }\n"
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            old, new = root / "old.lib.gz", root / "new.lib.gz"
            old.write_bytes(gzip.compress(text, mtime=1))
            new.write_bytes(gzip.compress(text, mtime=2))
            result = diff_pairwise_files("liberty", old, new, root / "out")
            summary = result["summary"]
            self.assertEqual(summary["source_content_status"], "DIFF")
            self.assertEqual(summary["parsed_fields_status"], "SAME")
            self.assertTrue(summary["unexplained_change"])

    def test_binary_same_size_different_bytes_has_no_parser_claim(self):
        _, summary, semantic, pairwise = self.compare("gds", ".gds", "ABCD", "ABCE")
        self.assertEqual(summary["source_content_status"], "DIFF")
        self.assertEqual(summary["parsed_fields_status"], "NOT_APPLICABLE")
        self.assertEqual(semantic["status"], "NOT_APPLICABLE")
        self.assertEqual(semantic["summary"]["change_count"], 0)
        self.assertEqual(pairwise["result"], "DIFF")

    def test_parser_failure_keeps_raw_difference_without_field_same(self):
        from lib_guard.diff import file_diff

        parse = file_diff._parse_file

        def failing_old(kind, path):
            result = parse(kind, path)
            if path.name == "old.v":
                return {**result, "status": "FAILED"}
            return result

        with patch.object(file_diff, "_parse_file", side_effect=failing_old):
            result, summary, _, pairwise = self.compare(
                "verilog", ".v", "module top(input a); endmodule\n",
                "module top(input b); endmodule\n",
            )
        self.assertEqual(result["status"], "FAILED")
        self.assertEqual(summary["source_content_status"], "DIFF")
        self.assertEqual(summary["parsed_fields_status"], "NOT_CHECKED")
        self.assertEqual(pairwise["result"], "FAILED")

    def test_hash_read_failure_is_unverified_and_failed(self):
        from lib_guard.diff import file_diff

        with patch.object(file_diff, "_sha256_file", side_effect=OSError("read denied")):
            result, summary, _, pairwise = self.compare(
                "verilog", ".v", "module top; endmodule\n", "module other; endmodule\n"
            )
        self.assertEqual(result["status"], "FAILED")
        self.assertEqual(summary["source_content_status"], "UNVERIFIED")
        self.assertEqual(summary["parsed_fields_status"], "NOT_CHECKED")
        self.assertEqual(pairwise["result"], "FAILED")

    def test_file_replaced_while_hashing_is_not_confirmed(self):
        from lib_guard.diff import file_diff

        sha = file_diff._sha256_file

        def replacing_new(path):
            digest = sha(path)
            if path.name == "new.v":
                path.write_text("module changed(input b); endmodule\n", encoding="utf-8")
            return digest

        with patch.object(file_diff, "_sha256_file", side_effect=replacing_new):
            result, summary, _, pairwise = self.compare(
                "verilog", ".v", "module top(input a); endmodule\n",
                "module top(input a); endmodule\n",
            )
        self.assertEqual(result["status"], "FAILED")
        self.assertEqual(summary["source_content_status"], "UNVERIFIED")
        self.assertEqual(pairwise["result"], "FAILED")

    def test_reports_explain_raw_and_extracted_results_separately(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            old, new = root / "old.v", root / "new.v"
            old.write_text("module top(input a, output y); assign y=a; endmodule\n")
            new.write_text("module top(input a, output y); assign y=~a; endmodule\n")
            out = root / "out"
            diff_pairwise_files("verilog", old, new, out)
            markdown = (out / "pairwise_summary.md").read_text()
            page = (out / "index.html").read_text()
            self.assertIn("源文件字节不同", markdown)
            self.assertIn("已提取字段无差异", markdown)
            self.assertIn("源文件字节不同", page)
            self.assertIn("已提取字段无差异", page)
            self.assertNotIn("基于工程内容字段", page)

    def test_legacy_report_task_list_explains_zero_extracted_changes(self):
        from lib_guard.render.html_report import _pairwise_result_for

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            old, new = root / "old.v", root / "new.v"
            old.write_text("module top(input a, output y); assign y=a; endmodule\n")
            new.write_text("module top(input a, output y); assign y=~a; endmodule\n")
            out = root / "out"
            diff_pairwise_files("verilog", old, new, out)
            status, note, href = _pairwise_result_for({"expected_output": str(out)})
            self.assertEqual(status, "DONE")
            self.assertIn("源文件字节不同", note)
            self.assertIn("已提取字段无差异", note)
            self.assertNotIn("changes=0", note)
            self.assertTrue(href)

    def test_running_generation_does_not_reuse_previous_html_or_count_done(self):
        from lib_guard.render.html_report import _pairwise_result_for
        from lib_guard.review.state import _pairwise

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            diff_dir, out = root / "diff", root / "pair"
            diff_dir.mkdir()
            out.mkdir()
            (out / "index.html").write_text("old completed report")
            (out / "pairwise_result.json").write_text(json.dumps({"status": "RUNNING"}))
            task = {"expected_output": str(out)}
            (diff_dir / "manual_pairwise_tasks.json").write_text(json.dumps({"tasks": [task]}))

            status, note, href = _pairwise_result_for(task)
            self.assertEqual(status, "RUNNING")
            self.assertFalse(href)
            overall, tasks, counts = _pairwise({"diff": {"diff_dir": str(diff_dir)}})
            self.assertEqual(overall, "PAIRWISE_PENDING")
            self.assertEqual(counts, {"total": 1, "done": 0, "pending": 1, "failed": 0})
            self.assertEqual(tasks[0]["status"], "RUNNING")

    def test_failed_summary_fallback_is_not_done(self):
        from lib_guard.review.state import _pairwise_results_for_task
        from lib_guard.render.html_report import _pairwise_result_for

        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            (out / "file_diff_summary.json").write_text(json.dumps({"status": "FAILED", "changed": False}))
            result = _pairwise_results_for_task({"expected_output": str(out)})
            self.assertEqual(result["status"], "FAILED")
            (out / "index.html").write_text("old completed report")
            status, _, href = _pairwise_result_for({"expected_output": str(out)})
            self.assertEqual(status, "FAILED")
            self.assertFalse(href)

    def test_legacy_summary_only_report_does_not_claim_byte_verification(self):
        from lib_guard.render.html_report import _pairwise_result_for

        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            (out / "index.html").write_text("legacy report")
            (out / "file_diff_summary.json").write_text(json.dumps({"status": "SAME", "changed": False}))
            status, note, href = _pairwise_result_for({"expected_output": str(out)})
            self.assertEqual(status, "DONE")
            self.assertIn("源文件内容未验证", note)
            self.assertTrue(href)

    def test_old_web_summary_does_not_claim_source_bytes_same(self):
        from lib_guard.web.app import _job_result_summary

        old = {"status": "SAME", "pairwise_result": "/tmp/legacy/pairwise_result.json",
               "summary": {"file_type": "verilog", "status": "SAME", "changed": False}}
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "result.json").write_text(json.dumps({"cli_result": old}))
            self.assertIn("源文件内容未验证", _job_result_summary(root))
            new = {**old, "summary": {**old["summary"], "source_content_status": "SAME"}}
            (root / "result.json").write_text(json.dumps({"cli_result": new}))
            self.assertIn("源文件字节相同", _job_result_summary(root))
