from pathlib import Path
import tempfile
import unittest


class FormalDirectoryAuditTest(unittest.TestCase):
    def test_manifest_is_optional_and_current_pointer_is_a_first_class_fact(self):
        from lib_guard.release.inventory import audit_formal_directory

        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "formal"
            package = root / "lib_NL2.5_1"
            (package / "LEF").mkdir(parents=True)
            (package / "LIB").mkdir()
            (package / "README.txt").write_text("delivery note", encoding="utf-8")
            (package / "LEF" / "cell.lef").write_text("VERSION 5.8 ;", encoding="utf-8")
            (package / "LIB" / "cell.lib").write_text("library(cell) {}", encoding="utf-8")
            root.mkdir(exist_ok=True)
            (root / "current").symlink_to(package)

            result = audit_formal_directory(root, {})

            self.assertEqual(result["audit_status"], "部分可用")
            self.assertFalse(result["manifest_present"])
            self.assertEqual(result["package_count"], 1)
            self.assertEqual(result["packages"][0]["name"], "lib_NL2.5_1")
            self.assertEqual(result["current_pointer"]["name"], "current")
            self.assertEqual(result["current_pointer"]["target"], "lib_NL2.5_1")
            self.assertEqual(result["view_counts"], {"LEF": 1, "LIB": 1})
            self.assertEqual(result["warnings"], ["发现 1 个非交付内容：lib_NL2.5_1/README.txt"])

    def test_broken_pointer_and_unknown_view_are_reported_without_version_diff(self):
        from lib_guard.release.inventory import audit_formal_directory

        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "lib_NL3.0.0"
            (root / "LEF").mkdir(parents=True)
            (root / "CUSTOM").mkdir()
            (root / "LEF" / "a.lef").write_text("VERSION 5.8 ;", encoding="utf-8")
            (root / "CUSTOM" / "a.bin").write_bytes(b"x")
            (root / "latest").symlink_to(root / "missing")

            result = audit_formal_directory(root, {})

            self.assertEqual(result["audit_status"], "不可用")
            self.assertEqual(result["package_count"], 1)
            self.assertEqual(result["current_pointer"]["status"], "断链")
            self.assertEqual(result["view_counts"], {"CUSTOM": 1, "LEF": 1})
            self.assertIn("latest 指向不存在的目录", result["warnings"])
            self.assertEqual(result["version_comparisons"], 0)

    def test_formal_root_audit_ignores_history_and_only_counts_current_packages(self):
        from lib_guard.release.inventory import audit_formal_directory

        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "formal"
            (root / "lib_NL2.5_1" / "LEF").mkdir(parents=True)
            (root / "lib_NL2.5_1" / "LEF" / "current.lef").write_text("VERSION 5.8 ;", encoding="utf-8")
            (root / "history" / "lib_NL2.4_0" / "LEF").mkdir(parents=True)
            (root / "history" / "lib_NL2.4_0" / "LEF" / "old.lef").write_text("VERSION 5.8 ;", encoding="utf-8")

            result = audit_formal_directory(root, {})

            self.assertEqual(result["package_count"], 1)
            self.assertEqual(result["file_count"], 1)
            self.assertEqual(result["view_counts"], {"LEF": 1})


if __name__ == "__main__":
    unittest.main()
