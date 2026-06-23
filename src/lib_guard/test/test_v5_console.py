from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


class V5ConsoleTest(unittest.TestCase):
    def test_console_build_from_latest_writes_pages_and_data(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            root = base / "raw"
            out = base / "scan"
            console = base / "console"
            root.mkdir()
            (root / "top.v").write_text("module top(input a, output y); assign y = a; endmodule\n", encoding="utf-8")
            (root / "mystery.xyz").write_text("unknown\n", encoding="utf-8")

            from lib_guard.cli import main

            self.assertEqual(
                main(
                    [
                        "scan",
                        "--root",
                        str(root),
                        "--profile",
                        "ip",
                        "--name",
                        "demo",
                        "--version",
                        "v1",
                        "--mode",
                        "signature",
                        "--out",
                        str(out),
                        "--workdir",
                        str(base / "work"),
                    ]
                ),
                0,
            )

            self.assertEqual(
                main(
                    [
                        "console",
                        "build",
                        "--latest",
                        "--library-id",
                        "ip/demo/v1",
                        "--mode",
                        "signature",
                        "--out",
                        str(console),
                        "--workdir",
                        str(base / "work"),
                    ]
                ),
                0,
            )

            for name in ["index.html", "config.html", "quality.html", "release.html", "history.html", "review.html"]:
                self.assertTrue((console / name).exists(), name)
            for name in ["control_data.json", "config_view.json", "review_items.json", "recommended_actions.json", "approval_snapshot.json"]:
                self.assertTrue((console / "data" / name).exists(), name)

            control_data = json.loads((console / "data" / "control_data.json").read_text(encoding="utf-8"))
            self.assertEqual(control_data["library_id"], "ip/demo/v1")
            self.assertEqual(control_data["status"]["scan"], "PASS")
            self.assertIn("parser_quality", control_data["status"])
            self.assertGreaterEqual(control_data["counts"]["review_items"], 1)

            review_items = json.loads((console / "data" / "review_items.json").read_text(encoding="utf-8"))
            categories = {item["category"] for item in review_items["review_items"]}
            self.assertIn("file_inventory", categories)

            actions = json.loads((console / "data" / "recommended_actions.json").read_text(encoding="utf-8"))
            commands = [item["command"] for item in actions["recommended_actions"]]
            self.assertFalse(any("summary rebuild" in command for command in commands))

    def test_console_config_and_review_commands_export_json(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            root = base / "raw"
            scan = base / "scan"
            root.mkdir()
            (root / "top.v").write_text("module top; endmodule\n", encoding="utf-8")

            from lib_guard.cli import main

            self.assertEqual(
                main(
                    [
                        "scan",
                        "--root",
                        str(root),
                        "--profile",
                        "ip",
                        "--name",
                        "demo",
                        "--version",
                        "v1",
                        "--mode",
                        "signature",
                        "--out",
                        str(scan),
                        "--workdir",
                        str(base / "work"),
                    ]
                ),
                0,
            )

            config_out = base / "config_view.json"
            review_out = base / "review_items.json"
            self.assertEqual(main(["console", "config", "--library-id", "ip/demo/v1", "--workdir", str(base / "work"), "--out", str(config_out)]), 0)
            self.assertEqual(
                main(
                    [
                        "console",
                        "review",
                        "--latest",
                        "--library-id",
                        "ip/demo/v1",
                        "--mode",
                        "signature",
                        "--workdir",
                        str(base / "work"),
                        "--out",
                        str(review_out),
                    ]
                ),
                0,
            )

            config = json.loads(config_out.read_text(encoding="utf-8"))
            self.assertTrue(any(item["name"] == "release_policy.required_docs" for item in config["configs"]))
            review = json.loads(review_out.read_text(encoding="utf-8"))
            self.assertEqual(review["library_id"], "ip/demo/v1")
            self.assertIn("review_items", review)


if __name__ == "__main__":
    unittest.main()
