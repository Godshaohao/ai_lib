from __future__ import annotations

import json
import inspect
import argparse
import contextlib
import io
import tempfile
import unittest
from pathlib import Path


class WindowIntakeTest(unittest.TestCase):
    def _write_catalog(self, root: Path, versions: list[dict[str, object]]) -> Path:
        catalog = {
            "libraries": [
                {
                    "library_id": "ip/ucie",
                    "formal_library_id": "Vendor_A.ucie",
                    "library_type": "ip",
                    "library_name": "ucie",
                    "aliases": ["ucie"],
                    "versions": versions,
                }
            ]
        }
        path = root / "catalog" / "catalog.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(catalog, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def test_latest_full_in_window_becomes_candidate_base(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            catalog = self._write_catalog(
                root,
                [
                    {
                        "version_id": "full1",
                        "version_key": "ip/ucie/full1",
                        "package_type": "FULL_PACKAGE",
                        "scan": {"status": "PASS", "scan_dir": str(root / "scan" / "full1")},
                    },
                    {"version_id": "fix1", "version_key": "ip/ucie/fix1", "package_type": "PARTIAL_UPDATE"},
                    {"version_id": "full2", "version_key": "ip/ucie/full2", "package_type": "FULL_PACKAGE"},
                    {"version_id": "fix2", "version_key": "ip/ucie/fix2", "package_type": "HOTFIX"},
                ],
            )
            (root / "scan" / "full1").mkdir(parents=True)

            from lib_guard.window.resolver import resolve_review_window

            window = resolve_review_window(
                catalog_path=catalog,
                library="ucie",
                workdir=root / "work",
                catalog_html_out=root / "catalog" / "html",
            )

            self.assertEqual(window["base_effective"]["target"], "raw:full1")
            self.assertEqual(window["candidate_effective"]["base_full"], "full2")
            self.assertEqual(window["candidate_effective"]["overlays"], ["fix2"])
            self.assertEqual(window["candidate_effective"]["intermediate_items"], ["fix1"])
            self.assertEqual(window["scan_versions"], ["fix1", "full2", "fix2"])
            self.assertEqual(window["compare"]["old"], "raw:full1")
            self.assertEqual(window["compare"]["new"], "effective:candidate_fix2")

    def test_current_pointer_limits_window_to_versions_after_current_base(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            catalog = self._write_catalog(
                root,
                [
                    {"version_id": "full1", "version_key": "ip/ucie/full1", "package_type": "FULL_PACKAGE"},
                    {"version_id": "full2", "version_key": "ip/ucie/full2", "package_type": "FULL_PACKAGE"},
                    {"version_id": "fix11", "version_key": "ip/ucie/fix11", "package_type": "HOTFIX"},
                ],
            )
            pointer = root / "catalog" / "html" / "libraries" / "ip_ucie" / "effective" / "current_effective.json"
            pointer.parent.mkdir(parents=True)
            pointer.write_text(
                json.dumps(
                    {
                        "current_effective_id": "E_full2",
                        "manifest": str(pointer.parent / "E_full2" / "effective_manifest.json"),
                        "base_full_version": "full2",
                        "accepted_updates": [],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            from lib_guard.window.resolver import resolve_review_window

            window = resolve_review_window(
                catalog_path=catalog,
                library="ucie",
                workdir=root / "work",
                catalog_html_out=root / "catalog" / "html",
            )

            self.assertEqual(window["base_effective"]["target"], "effective:E_full2")
            self.assertEqual([item["version"] for item in window["items"]], ["fix11"])
            self.assertEqual(window["candidate_effective"]["base_full"], "full2")
            self.assertEqual(window["candidate_effective"]["overlays"], ["fix11"])

    def test_short_cli_window_commands_and_mark_use_real_version_key(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._write_catalog(
                root,
                [
                    {"version_id": "full1", "version_key": "ip/ucie/full1", "package_type": "FULL_PACKAGE"},
                    {"version_id": "fix1", "version_key": "ip/ucie/custom_fix_key", "package_type": "UNKNOWN_PACKAGE"},
                ],
            )
            from lib_guard.short_cli import build_cli_commands, write_default_config

            write_default_config(root, raw_root=root / "raw")
            intake = build_cli_commands(["intake", "ucie", "--plan-only"], cwd=root)[0]
            self.assertEqual(intake[:2], ["window", "intake"])
            self.assertIn("--plan-only", intake)
            self.assertEqual(intake[intake.index("--library") + 1], "ucie")

            mark = build_cli_commands(["mark", "ucie", "fix1", "--type", "FIX"], cwd=root)[0]
            self.assertEqual(mark[:2], ["catalog", "override"])
            self.assertEqual(mark[mark.index("--version") + 1], "ip/ucie/custom_fix_key")
            self.assertEqual(mark[mark.index("--package-type") + 1], "PARTIAL_UPDATE")
            self.assertIn("--catalog-html-out", mark)

            accept = build_cli_commands(["accept-window", "ucie", "--accepted-by", "owner"], cwd=root)[0]
            self.assertEqual(accept[:2], ["window", "accept"])
            self.assertIn("--catalog", accept)
            self.assertIn("--library", accept)
            self.assertIn("--catalog-html-out", accept)
            self.assertEqual(accept[accept.index("--library") + 1], "ucie")

    def test_window_intake_and_accept_refresh_version_detail_projection(self) -> None:
        from lib_guard.window.cli import cmd_accept, cmd_intake

        self.assertIn("_attach_render_impact", inspect.getsource(cmd_intake))
        self.assertIn("_attach_render_impact", inspect.getsource(cmd_accept))

    def test_intake_plan_only_prints_confirm_and_relation_fix_commands(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            catalog = self._write_catalog(
                root,
                [
                    {"version_id": "full1", "version_key": "ip/ucie/full1", "package_type": "FULL_PACKAGE"},
                    {"version_id": "fix1", "version_key": "ip/ucie/fix1", "package_type": "HOTFIX"},
                ],
            )
            from lib_guard.window.cli import cmd_intake

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                code = cmd_intake(
                    argparse.Namespace(
                        catalog=str(catalog),
                        library="ucie",
                        workdir=str(root / "work"),
                        catalog_html_out=str(root / "catalog" / "html"),
                        since=None,
                        window_file=None,
                        rebuild=False,
                        parse_jobs="",
                        hash_policy="",
                        parse_file_types="",
                        parse_exclude_file_types="",
                        plan_only=True,
                    )
                )

            self.assertEqual(code, 0)
            output = json.loads(stdout.getvalue())
            self.assertEqual(output["confirm_command"], "lg intake ucie")
            self.assertIn("lg mark ucie <VERSION> --type FULL", output["relation_fix_commands"])
            self.assertIn("lg library override ucie <FIX_VERSION>", output["relation_fix_commands"][1])
            self.assertIn("lg accept-window ucie", output["accept_command"])


if __name__ == "__main__":
    unittest.main()
