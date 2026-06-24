from __future__ import annotations

import gzip
import json
import tempfile
import unittest
from pathlib import Path


class InventorySmokeTest(unittest.TestCase):
    def test_gz_file_type_classification(self) -> None:
        from src.lib_guard.scan.inventory import FileClassifier

        classifier = FileClassifier()
        lef = classifier.classify({"path": "lef/a.lef.gz", "name": "a.lef.gz"})
        lib = classifier.classify({"path": "lib/a.lib.gz", "name": "a.lib.gz"})
        self.assertEqual(lef["file_type"], "lef")
        self.assertEqual(lef["compression"], "gzip")
        self.assertEqual(lib["file_type"], "liberty")
        self.assertEqual(lib["compression"], "gzip")

    def test_file_walker_ignores_generated_dirs(self) -> None:
        from src.lib_guard.scan.inventory import FileWalker

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "lef").mkdir()
            (root / "reports").mkdir()
            (root / "diff").mkdir()
            (root / "lef" / "a.lef").write_text("MACRO A\n", encoding="utf-8")
            (root / "reports" / "noise.txt").write_text("ignore\n", encoding="utf-8")
            (root / "diff" / "noise.txt").write_text("ignore\n", encoding="utf-8")
            paths = {item["path"].replace("\\", "/") for item in FileWalker().walk(root)}
            self.assertIn("lef/a.lef", paths)
            self.assertNotIn("reports/noise.txt", paths)
            self.assertNotIn("diff/noise.txt", paths)


class FileDiffSmokeTest(unittest.TestCase):
    def test_read_text_supports_gzip(self) -> None:
        from src.lib_guard.diff.file_diff import _read_text

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "a.lib.gz"
            with gzip.open(path, "wt", encoding="utf-8") as fh:
                fh.write("library(a) {\n}\n")
            self.assertEqual(_read_text(path), ["library(a) {", "}"])


class ShortCliOverrideSmokeTest(unittest.TestCase):
    def test_override_expands_to_catalog_override(self) -> None:
        from src.lib_guard.short_cli import build_cli_commands, write_default_config

        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp) / "work"
            write_default_config(work, raw_root=work / "raw", library_type="ip")
            catalog = work / "catalog" / "catalog.json"
            catalog.parent.mkdir(parents=True, exist_ok=True)
            catalog.write_text(
                json.dumps(
                    {
                        "libraries": [
                            {
                                "library_id": "ip/ucie",
                                "library_type": "ip",
                                "library_name": "ucie",
                                "aliases": [],
                                "versions": [
                                    {"version_id": "stable_20260601", "raw_path": str(work / "raw" / "ucie" / "stable_20260601")},
                                    {"version_id": "update_20260612", "raw_path": str(work / "raw" / "ucie" / "update_20260612")},
                                ],
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            commands = build_cli_commands(
                [
                    "--config",
                    str(work / "lib_guard.yml"),
                    "override",
                    "ucie",
                    "update_20260612",
                    "--package-type",
                    "PARTIAL_UPDATE",
                    "--update-scope",
                    "lib,lef",
                    "--base-full",
                    "stable_20260601",
                    "--previous-effective",
                    "stable_20260601",
                ],
                cwd=work,
            )
            self.assertEqual(len(commands), 1)
            command = commands[0]
            self.assertEqual(command[:2], ["catalog", "override"])
            self.assertIn("--base-full", command)
            self.assertIn("stable_20260601", command)
            self.assertIn("--previous-effective", command)
            self.assertIn("ip/ucie/update_20260612", command)


if __name__ == "__main__":
    unittest.main()
