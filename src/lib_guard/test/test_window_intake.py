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

    def _write_multi_catalog(self, root: Path) -> Path:
        catalog = {
            "libraries": [
                {
                    "library_id": "ip/ready",
                    "library_type": "ip",
                    "library_name": "ready",
                    "versions": [
                        {
                            "version_id": "full1",
                            "version_key": "ip/ready/full1",
                            "package_type": "FULL_PACKAGE",
                            "scan": {"status": "PASS", "scan_dir": str(root / "scan" / "ready" / "full1")},
                        },
                        {
                            "version_id": "fix1",
                            "version_key": "ip/ready/fix1",
                            "package_type": "PARTIAL_UPDATE",
                        },
                    ],
                },
                {
                    "library_id": "ip/blocked",
                    "library_type": "ip",
                    "library_name": "blocked",
                    "versions": [
                        {"version_id": "full1", "version_key": "ip/blocked/full1", "package_type": "FULL_PACKAGE"},
                        {"version_id": "adhoc1", "version_key": "ip/blocked/adhoc1", "package_type": "UNKNOWN_PACKAGE"},
                    ],
                },
                {
                    "library_id": "ip/empty",
                    "library_type": "ip",
                    "library_name": "empty",
                    "versions": [
                        {"version_id": "full1", "version_key": "ip/empty/full1", "package_type": "FULL_PACKAGE"},
                    ],
                },
            ]
        }
        (root / "scan" / "ready" / "full1").mkdir(parents=True)
        path = root / "catalog" / "catalog.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(catalog, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def _write_accept_fixture(self, root: Path, compare_manifest: dict[str, object]) -> tuple[Path, Path, Path, Path]:
        window = root / "pending_window.json"
        effective_dir = root / "effective" / "candidate_fix1"
        effective_dir.mkdir(parents=True)
        manifest = effective_dir / "effective_manifest.json"
        manifest.write_text(
            json.dumps({"effective_id": "candidate_fix1", "summary": {"conflict_count": 0}}),
            encoding="utf-8",
        )
        pointer = effective_dir.parent / "current_effective.json"
        pointer.write_text(json.dumps({"current_effective_id": "E0", "revision": 3}), encoding="utf-8")
        compare_dir = root / "compare"
        compare_dir.mkdir()
        (compare_dir / "compare_manifest.json").write_text(json.dumps(compare_manifest), encoding="utf-8")
        window.write_text(
            json.dumps(
                {
                    "state": "PENDING",
                    "base_effective": {"target": "effective:E0", "current_effective_id": "E0"},
                    "candidate_effective": {"effective_id": "candidate_fix1", "manifest": str(manifest)},
                    "compare": {
                        "old": "effective:E0",
                        "new": "effective:candidate_fix1",
                        "out_dir": str(compare_dir),
                    },
                    "items": [{"version": "fix1", "kind": "PARTIAL_UPDATE"}],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        plan_dir = root / "work" / "state" / "ucie"
        plan_dir.mkdir(parents=True)
        (plan_dir / "current_plan.json").write_text(
            json.dumps({"library": "ucie", "state": "DONE", "tasks": [{"id": "effective-compare", "status": "DONE"}]}),
            encoding="utf-8",
        )
        return window, manifest, pointer, effective_dir / "review_approval.json"

    def test_latest_full_fallback_becomes_review_base(self) -> None:
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

            self.assertEqual(window["base_effective"]["target"], "raw:full2")
            self.assertEqual(window["base_effective"]["source"], "latest_full_fallback")
            self.assertEqual(window["candidate_effective"]["base_full"], "full2")
            self.assertEqual(window["candidate_effective"]["overlays"], ["fix2"])
            self.assertEqual(window["candidate_effective"]["intermediate_items"], [])
            self.assertEqual(window["scan_versions"], ["full2", "fix2"])
            self.assertEqual(window["compare"]["old"], "raw:full2")
            self.assertEqual(window["compare"]["new"], "effective:candidate_fix2")

    def test_pending_window_compare_id_uses_real_old_target_not_checkpoint(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            catalog = self._write_catalog(
                root,
                [
                    {"version_id": "full1", "version_key": "ip/ucie/full1", "package_type": "FULL_PACKAGE"},
                    {"version_id": "fix1", "version_key": "ip/ucie/fix1", "package_type": "PARTIAL_UPDATE"},
                    {"version_id": "fix2", "version_key": "ip/ucie/fix2", "package_type": "PARTIAL_UPDATE"},
                ],
            )
            pending = root / "pending_window.json"
            pending.write_text(
                json.dumps(
                    {
                        "state": "PENDING",
                        "base_effective": {
                            "source": "latest_full_fallback",
                            "target": "raw:full1",
                            "base_full": "full1",
                            "accepted_updates": [],
                        },
                        "items": [{"version": "fix1"}],
                        "last_seen_version": "fix1",
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
                window_path=pending,
            )

            self.assertEqual(window["compare"]["old"], "raw:full1")
            self.assertEqual(window["compare"]["compare_id"], "window_raw_full1_to_candidate_fix2")

    def test_accepted_window_without_new_versions_reports_current_effective_pointer(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            catalog = self._write_catalog(
                root,
                [
                    {"version_id": "full1", "version_key": "ip/ucie/full1", "package_type": "FULL_PACKAGE"},
                    {"version_id": "fix1", "version_key": "ip/ucie/fix1", "package_type": "PARTIAL_UPDATE"},
                ],
            )
            html = root / "catalog" / "html"
            pointer_dir = html / "libraries" / "ip_ucie" / "effective"
            pointer_dir.mkdir(parents=True)
            (pointer_dir / "current_effective.json").write_text(
                json.dumps(
                    {
                        "schema_version": "current_effective.v1",
                        "library_id": "ip/ucie",
                        "current_effective_id": "candidate_fix1",
                        "base_full_version": "full1",
                        "accepted_updates": ["fix1"],
                        "manifest": str(pointer_dir / "candidate_fix1" / "effective_manifest.json"),
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            pending = html / "libraries" / "ip_ucie" / "window" / "pending_window.json"
            pending.parent.mkdir(parents=True)
            pending.write_text(
                json.dumps(
                    {
                        "state": "ACCEPTED",
                        "base_effective": {"source": "latest_full_fallback", "target": "raw:full1", "base_full": "full1"},
                        "last_seen_version": "fix1",
                        "items": [{"version": "fix1"}],
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
                catalog_html_out=html,
            )

            self.assertEqual(window["state"], "EMPTY")
            self.assertFalse(window["changed"])
            self.assertEqual(window["base_effective"]["source"], "current_effective_pointer")
            self.assertEqual(window["base_effective"]["target"], "effective:candidate_fix1")
            self.assertEqual(window["base_effective"]["accepted_updates"], ["fix1"])

            from lib_guard.window.cli import cmd_show

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                code = cmd_show(
                    argparse.Namespace(
                        catalog=str(catalog),
                        library="ucie",
                        workdir=str(root / "work"),
                        catalog_html_out=str(html),
                        since=None,
                        parse_jobs="",
                        window_file=None,
                        format="text",
                    )
                )
            self.assertEqual(code, 0)
            text = stdout.getvalue()
            self.assertIn("来源：当前Effective指针", text)
            self.assertIn("当前Base：effective:candidate_fix1", text)
            self.assertIn("当前没有新的待审查版本", text)
            self.assertIn("无需修正", text)
            self.assertNotIn("lg window ucie", text)
            self.assertNotIn("lg accept-window ucie", text)

            from lib_guard.window.cli import cmd_intake

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                code = cmd_intake(
                    argparse.Namespace(
                        catalog=str(catalog),
                        library="ucie",
                        workdir=str(root / "work"),
                        catalog_html_out=str(html),
                        since=None,
                        window_file=None,
                        rebuild=False,
                        parse_jobs="",
                        hash_policy="",
                        parse_file_types="",
                        parse_exclude_file_types="",
                        plan_only=True,
                        format="text",
                    )
                )
            self.assertEqual(code, 0)
            plan_text = stdout.getvalue()
            self.assertIn("当前没有新的待审查版本", plan_text)
            self.assertIn("确认执行：无需执行", plan_text)
            self.assertIn("接受窗口：无需执行", plan_text)
            self.assertNotIn("lg accept-window ucie", plan_text)

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                code = cmd_intake(
                    argparse.Namespace(
                        catalog=str(catalog),
                        library="ucie",
                        workdir=str(root / "work"),
                        catalog_html_out=str(html),
                        since=None,
                        window_file=None,
                        rebuild=False,
                        parse_jobs="",
                        hash_policy="",
                        parse_file_types="",
                        parse_exclude_file_types="",
                        plan_only=True,
                        format="json",
                    )
                )
            self.assertEqual(code, 0)
            plan_json = json.loads(stdout.getvalue())
            self.assertEqual(plan_json["accept_command"], "无需执行：没有 candidate effective，不能接受新有效版")
            self.assertNotIn("lg accept-window", plan_json["accept_command"])

    def test_window_output_contains_human_review_table_and_fix_commands(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            catalog = self._write_catalog(
                root,
                [
                    {"version_id": "full_old", "version_key": "ip/ucie/full_old", "package_type": "FULL_PACKAGE"},
                    {"version_id": "full_new", "version_key": "ip/ucie/full_new", "package_type": "FULL_PACKAGE"},
                    {"version_id": "adhoc_fix", "version_key": "ip/ucie/adhoc_fix", "package_type": "UNKNOWN_PACKAGE"},
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
                        rebuild=True,
                        parse_jobs="",
                        hash_policy="",
                        parse_file_types="",
                        parse_exclude_file_types="",
                        plan_only=True,
                    )
                )

            self.assertEqual(code, 0)
            output = json.loads(stdout.getvalue())
            self.assertEqual(output["base_review"]["状态"], "需确认")
            self.assertEqual(output["base_review"]["当前Base"], "raw:full_new")
            self.assertEqual(output["版本选择表"][-1]["版本名"], "adhoc_fix")
            self.assertEqual(output["版本选择表"][-1]["类型猜测"], "FIX")
            self.assertEqual(output["版本选择表"][-1]["Catalog类型"], "UNKNOWN_PACKAGE")
            self.assertTrue(any("lg mark ucie adhoc_fix --type FIX" in command for command in output["建议修正命令"]))
            self.assertIn("lg library override ucie adhoc_fix", output["建议修正命令"][-1])

    def test_worklist_summarizes_ready_blocked_and_empty_libraries(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            catalog = self._write_multi_catalog(root)

            from lib_guard.window.cli import cmd_worklist

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                code = cmd_worklist(
                    argparse.Namespace(
                        catalog=str(catalog),
                        workdir=str(root / "work"),
                        catalog_html_out=str(root / "catalog" / "html"),
                        format="json",
                        ready=False,
                        blocked=False,
                    )
                )

            self.assertEqual(code, 0)
            output = json.loads(stdout.getvalue())
            self.assertEqual(output["summary"]["可执行"], 1)
            self.assertEqual(output["summary"]["需确认包类型"], 1)
            self.assertEqual(output["summary"]["无新版本"], 1)
            rows = {row["库"]: row for row in output["rows"]}
            self.assertEqual(rows["ready"]["状态"], "可执行")
            self.assertEqual(rows["ready"]["建议动作"], "lg next ready --apply")
            self.assertEqual(rows["blocked"]["状态"], "需确认包类型")
            self.assertEqual(rows["blocked"]["建议动作"], "lg next blocked --fix")
            self.assertEqual(rows["empty"]["状态"], "无新版本")
            self.assertEqual(rows["empty"]["建议动作"], "无需执行")

    def test_rollback_sets_current_effective_to_existing_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            catalog = self._write_catalog(
                root,
                [{"version_id": "full1", "version_key": "ip/ucie/full1", "package_type": "FULL_PACKAGE"}],
            )
            html = root / "catalog" / "html"
            eff_dir = html / "libraries" / "ip_ucie" / "effective" / "E_old"
            eff_dir.mkdir(parents=True)
            manifest = eff_dir / "effective_manifest.json"
            manifest.write_text(
                json.dumps(
                    {
                        "effective_id": "E_old",
                        "library_id": "ip/ucie",
                        "base_full_version": "full1",
                        "accepted_updates": [],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            from lib_guard.window.cli import cmd_rollback

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                code = cmd_rollback(
                    argparse.Namespace(
                        catalog=str(catalog),
                        library="ucie",
                        workdir=str(root / "work"),
                        catalog_html_out=str(html),
                        to="E_old",
                        by="owner",
                        reason="wrong candidate accepted",
                    )
                )

            self.assertEqual(code, 0)
            output = json.loads(stdout.getvalue())
            self.assertEqual(output["status"], "PASS")
            pointer = json.loads((html / "libraries" / "ip_ucie" / "effective" / "current_effective.json").read_text(encoding="utf-8"))
            self.assertEqual(pointer["current_effective_id"], "E_old")
            self.assertEqual(pointer["accepted_by"], "owner")
            self.assertIn("rollback", pointer["note"])

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
            self.assertEqual(intake[intake.index("--format") + 1], "text")
            self.assertEqual(intake[intake.index("--library") + 1], "ucie")

            intake_json = build_cli_commands(["intake", "ucie", "--plan-only", "--json"], cwd=root)[0]
            self.assertIn("--plan-only", intake_json)
            self.assertNotIn("--format", intake_json)

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

            window = build_cli_commands(["window", "ucie"], cwd=root)[0]
            self.assertEqual(window[:2], ["window", "show"])
            self.assertEqual(window[window.index("--format") + 1], "text")

            window_json = build_cli_commands(["window", "ucie", "--json"], cwd=root)[0]
            self.assertEqual(window_json[:2], ["window", "show"])
            self.assertNotIn("--format", window_json)

    def test_json_short_commands_do_not_echo_expanded_commands(self) -> None:
        from lib_guard.short_cli import _build_parser, _should_echo_commands

        parser = _build_parser()
        self.assertFalse(_should_echo_commands(parser.parse_args(["window", "ucie"])))
        self.assertFalse(_should_echo_commands(parser.parse_args(["intake", "ucie", "--plan-only"])))
        self.assertFalse(_should_echo_commands(parser.parse_args(["window", "ucie", "--json"])))
        self.assertFalse(_should_echo_commands(parser.parse_args(["intake", "ucie", "--plan-only", "--json"])))
        self.assertTrue(_should_echo_commands(parser.parse_args(["--dry-run", "window", "ucie", "--json"])))

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
            self.assertEqual(output["confirm_command"], "lg next ucie --apply")
            self.assertIn("lg mark ucie <VERSION> --type FULL", output["relation_fix_commands"])
            self.assertIn("lg library override ucie <FIX_VERSION>", output["relation_fix_commands"][1])
            self.assertIn("lg next ucie --accept", output["accept_command"])

    def test_intake_plan_only_text_keeps_base_and_next_action_visible(self) -> None:
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
                        format="text",
                    )
                )

            self.assertEqual(code, 0)
            text = stdout.getvalue()
            self.assertIn("基线确认", text)
            self.assertIn("当前Base：raw:full1", text)
            self.assertIn("版本选择表", text)
            self.assertIn("执行计划", text)
            self.assertIn("确认执行：lg next ucie --apply", text)

    def test_intake_plan_text_explains_full_and_incremental_flow(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            catalog = self._write_catalog(
                root,
                [
                    {"version_id": "full1", "version_key": "ip/ucie/full1", "package_type": "FULL_PACKAGE"},
                    {"version_id": "full2", "version_key": "ip/ucie/full2", "package_type": "FULL_PACKAGE"},
                    {"version_id": "fix2", "version_key": "ip/ucie/fix2", "package_type": "HOTFIX"},
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
                        format="text",
                    )
                )

            self.assertEqual(code, 0)
            text = stdout.getvalue()
            self.assertIn("流程判断", text)
            self.assertIn("FULL流程", text)
            self.assertIn("增量流程", text)
            self.assertIn("最新FULL：full2", text)
            self.assertIn("增量包：fix2", text)

    def test_worklist_text_points_to_next_command_not_internal_intake(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            catalog = self._write_multi_catalog(root)

            from lib_guard.window.cli import cmd_worklist

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                code = cmd_worklist(
                    argparse.Namespace(
                        catalog=str(catalog),
                        workdir=str(root / "work"),
                        catalog_html_out=str(root / "catalog" / "html"),
                        format="text",
                        ready=False,
                        blocked=False,
                    )
                )

            self.assertEqual(code, 0)
            text = stdout.getvalue()
            self.assertIn("lg next ready --apply", text)
            self.assertIn("lg next blocked --fix", text)
            self.assertNotIn("lg intake ready", text)

    def test_intake_blocks_execution_when_package_type_is_unknown_and_writes_plan(self) -> None:
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
                    {"version_id": "fix1", "version_key": "ip/ucie/fix1", "package_type": "UNKNOWN_PACKAGE"},
                ],
            )
            (root / "scan" / "full1").mkdir(parents=True)

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
                        plan_only=False,
                    )
                )

            self.assertEqual(code, 2)
            output = json.loads(stdout.getvalue())
            self.assertEqual(output["status"], "NEEDS_PACKAGE_CONFIRM")
            self.assertEqual(output["plan_state"], "BLOCKED")
            self.assertEqual(output["next_action"], "confirm_package_type")
            self.assertIn("fix1", output["blocked_reason"])
            self.assertIn("存在未确认包类型", output["blocked_reason"])
            self.assertNotIn("requires owner confirmation", output["blocked_reason"])
            plan = json.loads(Path(output["plan"]).read_text(encoding="utf-8"))
            self.assertEqual(plan["state"], "BLOCKED")
            self.assertEqual(plan["next_action"], "confirm_package_type")

    def test_accept_window_rejects_unknown_package_type(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            window = root / "pending_window.json"
            manifest = root / "effective_manifest.json"
            manifest.write_text("{}", encoding="utf-8")
            window.write_text(
                json.dumps(
                    {
                        "state": "PENDING",
                        "candidate_effective": {
                            "manifest": str(manifest),
                            "unknown_package_versions": ["fix1"],
                        },
                        "items": [{"version": "fix1", "kind": "UNKNOWN", "requires_package_type_confirmation": True}],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            from lib_guard.window.cli import cmd_accept

            with self.assertRaisesRegex(ValueError, "confirmed package_type"):
                cmd_accept(
                    argparse.Namespace(
                        catalog=None,
                        library="ucie",
                        workdir=str(root / "work"),
                        catalog_html_out=str(root / "catalog" / "html"),
                        window_file=str(window),
                        accepted_by="owner",
                        note="review passed",
                    )
                )

    def test_accept_window_rejects_pending_or_failed_intake_plan(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            window = root / "pending_window.json"
            manifest = root / "effective_manifest.json"
            manifest.write_text(json.dumps({"effective_id": "candidate_fix1"}), encoding="utf-8")
            compare_dir = root / "compare"
            compare_dir.mkdir()
            (compare_dir / "compare_manifest.json").write_text(json.dumps({"compare_id": "cmp1"}), encoding="utf-8")
            window.write_text(
                json.dumps(
                    {
                        "state": "PENDING",
                        "candidate_effective": {"manifest": str(manifest)},
                        "compare": {"compare_id": "cmp1", "out_dir": str(compare_dir), "html": str(compare_dir / "index.html")},
                        "items": [{"version": "fix1", "kind": "PARTIAL_UPDATE"}],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            plan_dir = root / "work" / "state" / "ucie"
            plan_dir.mkdir(parents=True)
            (plan_dir / "current_plan.json").write_text(
                json.dumps(
                    {
                        "library": "ucie",
                        "state": "PENDING",
                        "tasks": [{"id": "scan:fix1", "status": "PENDING"}],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            from lib_guard.window.cli import cmd_accept

            with self.assertRaisesRegex(ValueError, "plan.*DONE"):
                cmd_accept(
                    argparse.Namespace(
                        catalog=None,
                        library="ucie",
                        workdir=str(root / "work"),
                        catalog_html_out=str(root / "catalog" / "html"),
                        window_file=str(window),
                        accepted_by="owner",
                        note="review passed",
                    )
                )

    def test_accept_window_rejects_incomplete_compare_before_writing_side_effects(self) -> None:
        cases = [
            (
                "empty compare manifest",
                {},
                "compare manifest is empty or invalid; rebuild compare",
            ),
            (
                "missing old target",
                {
                    "new_target": {
                        "type": "effective",
                        "id": "candidate_fix1",
                        "spec": "effective:candidate_fix1",
                    }
                },
                "compare manifest missing valid old_target; rebuild compare",
            ),
            (
                "missing new target",
                {"old_target": {"type": "effective", "id": "E0", "spec": "effective:E0"}},
                "compare manifest missing valid new_target; rebuild compare",
            ),
            (
                "effective candidate without lock",
                {
                    "old_target": {"type": "effective", "id": "E0", "spec": "effective:E0"},
                    "new_target": {"type": "effective", "id": "candidate_fix1", "spec": "effective:candidate_fix1"},
                },
                "new effective target must include effective_digest or manifest_sha256; rebuild compare",
            ),
        ]

        for name, compare_manifest, error in cases:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as td:
                root = Path(td)
                window, _manifest, pointer, approval = self._write_accept_fixture(root, compare_manifest)
                pointer_before = pointer.read_text(encoding="utf-8")
                from lib_guard.window.cli import cmd_accept

                with self.assertRaisesRegex(ValueError, error):
                    cmd_accept(
                        argparse.Namespace(
                            catalog=None,
                            library="ucie",
                            workdir=str(root / "work"),
                            catalog_html_out=str(root / "catalog" / "html"),
                            window_file=str(window),
                            accepted_by="owner",
                            note="review passed",
                        )
                    )

                self.assertFalse(approval.exists())
                self.assertEqual(pointer.read_text(encoding="utf-8"), pointer_before)

    def test_accept_window_rejects_compare_for_different_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            window = root / "pending_window.json"
            manifest = root / "effective_manifest.json"
            manifest.write_text(json.dumps({"effective_id": "candidate_fix1"}), encoding="utf-8")
            compare_dir = root / "compare"
            compare_dir.mkdir()
            (compare_dir / "compare_manifest.json").write_text(
                json.dumps(
                    {
                        "compare_id": "cmp1",
                        "old_target": "effective:E0",
                        "new_target": {
                            "type": "effective",
                            "id": "stale_candidate",
                            "spec": "effective:stale_candidate",
                            "manifest_sha256": "sha256:stale",
                        },
                    }
                ),
                encoding="utf-8",
            )
            window.write_text(
                json.dumps(
                    {
                        "state": "PENDING",
                        "base_effective": {"target": "effective:E0"},
                        "candidate_effective": {"effective_id": "candidate_fix1", "manifest": str(manifest)},
                        "compare": {
                            "compare_id": "cmp1",
                            "old": "effective:E0",
                            "new": "effective:candidate_fix1",
                            "out_dir": str(compare_dir),
                            "html": str(compare_dir / "index.html"),
                        },
                        "items": [{"version": "fix1", "kind": "PARTIAL_UPDATE"}],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            plan_dir = root / "work" / "state" / "ucie"
            plan_dir.mkdir(parents=True)
            (plan_dir / "current_plan.json").write_text(
                json.dumps(
                    {
                        "library": "ucie",
                        "state": "DONE",
                        "tasks": [{"id": "effective-compare", "status": "DONE"}],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            from lib_guard.window.cli import cmd_accept

            with self.assertRaisesRegex(ValueError, "compare evidence does not match pending window"):
                cmd_accept(
                    argparse.Namespace(
                        catalog=None,
                        library="ucie",
                        workdir=str(root / "work"),
                        catalog_html_out=str(root / "catalog" / "html"),
                        window_file=str(window),
                        accepted_by="owner",
                        note="review passed",
                    )
                )

    def test_accept_window_rejects_rebuilt_manifest_after_real_compare_generation(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            catalog = {
                "libraries": [
                    {
                        "library_id": "ip/ucie",
                        "library_name": "ucie",
                        "versions": [
                            {"version_id": "full1", "scan": {"snapshot_identity": {"digest": "sha256:full", "strength": "full"}}},
                            {"version_id": "fix1", "scan": {"snapshot_identity": {"digest": "sha256:fix-a", "strength": "full"}}},
                        ],
                    }
                ]
            }
            from lib_guard.effective.compare import build_compare_manifest, write_compare_manifest
            from lib_guard.effective.manifest import build_effective_manifest

            manifest_path = root / "libraries" / "ip_ucie" / "effective" / "candidate_fix1" / "effective_manifest.json"
            manifest_path.parent.mkdir(parents=True)
            original = build_effective_manifest(catalog, "ucie", "full1", [("fix1", ["lef"])], effective_id="candidate_fix1")
            manifest_path.write_text(json.dumps(original), encoding="utf-8")
            compare_dir = root / "compare"
            compare_manifest = build_compare_manifest(
                catalog,
                "ucie",
                "raw:full1",
                "effective:candidate_fix1",
                search_roots=[root],
                compare_id="cmp1",
            )
            compare_path = write_compare_manifest(compare_dir, compare_manifest)
            self.assertEqual(compare_manifest["new_target"]["effective_digest"], original["identity"]["digest"])

            changed_catalog = json.loads(json.dumps(catalog))
            changed_catalog["libraries"][0]["versions"][1]["scan"]["snapshot_identity"]["digest"] = "sha256:fix-b"
            replacement = build_effective_manifest(
                changed_catalog,
                "ucie",
                "full1",
                [("fix1", ["lef"])],
                effective_id="candidate_fix1",
            )
            manifest_path.write_text(json.dumps(replacement), encoding="utf-8")

            window = root / "pending_window.json"
            window.write_text(
                json.dumps(
                    {
                        "library": "ucie",
                        "state": "PENDING",
                        "base_effective": {"target": "raw:full1"},
                        "candidate_effective": {"effective_id": "candidate_fix1", "manifest": str(manifest_path)},
                        "compare": {"old": "raw:full1", "new": "effective:candidate_fix1", "out_dir": str(compare_dir)},
                        "items": [{"version": "fix1", "kind": "PARTIAL_UPDATE"}],
                    }
                ),
                encoding="utf-8",
            )
            plan_dir = root / "work" / "state" / "ucie"
            plan_dir.mkdir(parents=True)
            (plan_dir / "current_plan.json").write_text(
                json.dumps({"state": "DONE", "tasks": [{"id": "effective-compare", "status": "DONE"}]}),
                encoding="utf-8",
            )

            from lib_guard.window.cli import cmd_accept

            with self.assertRaisesRegex(ValueError, "effective digest changed after compare"):
                cmd_accept(
                    argparse.Namespace(
                        catalog=None,
                        library="ucie",
                        workdir=str(root / "work"),
                        catalog_html_out=str(root / "catalog" / "html"),
                        window_file=str(window),
                        accepted_by="owner",
                        note="review passed",
                    )
                )

            self.assertTrue(compare_path.exists())

    def test_accept_window_writes_review_approval_and_pointer_revision(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            window = root / "pending_window.json"
            effective_dir = root / "effective" / "candidate_fix1"
            effective_dir.mkdir(parents=True)
            manifest = effective_dir / "effective_manifest.json"
            manifest.write_text(
                json.dumps({"effective_id": "candidate_fix1", "summary": {"conflict_count": 0}}),
                encoding="utf-8",
            )
            pointer = effective_dir.parent / "current_effective.json"
            pointer.write_text(json.dumps({"current_effective_id": "E0", "revision": 3}), encoding="utf-8")
            compare_dir = root / "compare"
            compare_dir.mkdir()
            from lib_guard.effective.pointer import sha256_file

            (compare_dir / "compare_manifest.json").write_text(
                json.dumps(
                    {
                        "compare_id": "cmp1",
                        "old_target": {"type": "effective", "id": "E0", "spec": "effective:E0"},
                        "new_target": {
                            "type": "effective",
                            "id": "candidate_fix1",
                            "spec": "effective:candidate_fix1",
                            "manifest_sha256": sha256_file(manifest),
                        },
                    }
                ),
                encoding="utf-8",
            )
            window.write_text(
                json.dumps(
                    {
                        "state": "PENDING",
                        "base_effective": {"target": "effective:E0", "current_effective_id": "E0"},
                        "candidate_effective": {"effective_id": "candidate_fix1", "manifest": str(manifest)},
                        "compare": {
                            "compare_id": "cmp1",
                            "old": "effective:E0",
                            "new": "effective:candidate_fix1",
                            "out_dir": str(compare_dir),
                        },
                        "items": [{"version": "fix1", "kind": "PARTIAL_UPDATE"}],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            plan_dir = root / "work" / "state" / "ucie"
            plan_dir.mkdir(parents=True)
            (plan_dir / "current_plan.json").write_text(
                json.dumps({"library": "ucie", "state": "DONE", "tasks": [{"id": "effective-compare", "status": "DONE"}]}),
                encoding="utf-8",
            )
            from lib_guard.window.cli import cmd_accept

            with contextlib.redirect_stdout(io.StringIO()):
                code = cmd_accept(
                    argparse.Namespace(
                        catalog=None,
                        library="ucie",
                        workdir=str(root / "work"),
                        catalog_html_out=str(root / "catalog" / "html"),
                        window_file=str(window),
                        accepted_by="owner",
                        note="review passed",
                    )
                )

            self.assertEqual(code, 0)
            pointer_data = json.loads(pointer.read_text(encoding="utf-8"))
            approval_path = Path(pointer_data["review_approval"])
            approval = json.loads(approval_path.read_text(encoding="utf-8"))
            self.assertEqual(pointer_data["revision"], 4)
            self.assertEqual(pointer_data["previous_effective_id"], "E0")
            self.assertEqual(pointer_data["manifest_sha256"], sha256_file(manifest))
            self.assertEqual(pointer_data["approval_sha256"], sha256_file(approval_path))
            self.assertEqual(approval["candidate_effective_sha256"], sha256_file(manifest))
            self.assertEqual(approval["compare_manifest_sha256"], sha256_file(compare_dir / "compare_manifest.json"))
            self.assertTrue(approval["candidate_effective_digest"])

            accepted_window = json.loads(window.read_text(encoding="utf-8"))
            accepted_window["review_approval"] = str(root / "missing_approval.json")
            window.write_text(json.dumps(accepted_window), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "approval integrity is MISSING"):
                cmd_accept(
                    argparse.Namespace(
                        catalog=None,
                        library="ucie",
                        workdir=str(root / "work"),
                        catalog_html_out=str(root / "catalog" / "html"),
                        window_file=str(window),
                        accepted_by="owner",
                        note="review passed",
                    )
                )

            accepted_window["review_approval"] = str(approval_path)
            accepted_window["approval_sha256"] = "wrong"
            window.write_text(json.dumps(accepted_window), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "approval integrity is MISMATCH"):
                cmd_accept(
                    argparse.Namespace(
                        catalog=None,
                        library="ucie",
                        workdir=str(root / "work"),
                        catalog_html_out=str(root / "catalog" / "html"),
                        window_file=str(window),
                        accepted_by="owner",
                        note="review passed",
                    )
                )

            approval["candidate_effective_digest"] = "sha256:wrong"
            approval_path.write_text(json.dumps(approval), encoding="utf-8")
            accepted_window["approval_sha256"] = sha256_file(approval_path)
            window.write_text(json.dumps(accepted_window), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "approval integrity is MISMATCH"):
                cmd_accept(
                    argparse.Namespace(
                        catalog=None,
                        library="ucie",
                        workdir=str(root / "work"),
                        catalog_html_out=str(root / "catalog" / "html"),
                        window_file=str(window),
                        accepted_by="owner",
                        note="review passed",
                    )
                )

    def test_accept_window_rejects_conflicted_effective_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            window = root / "pending_window.json"
            manifest = root / "effective_manifest.json"
            manifest.write_text(json.dumps({"effective_id": "candidate_fix1", "summary": {"conflict_count": 1}}), encoding="utf-8")
            compare_dir = root / "compare"
            compare_dir.mkdir()
            (compare_dir / "compare_manifest.json").write_text(
                json.dumps({"old_target": {"spec": "effective:E0"}, "new_target": {"spec": "effective:candidate_fix1"}}),
                encoding="utf-8",
            )
            window.write_text(
                json.dumps(
                    {
                        "state": "PENDING",
                        "base_effective": {"target": "effective:E0"},
                        "candidate_effective": {"effective_id": "candidate_fix1", "manifest": str(manifest)},
                        "compare": {"old": "effective:E0", "new": "effective:candidate_fix1", "out_dir": str(compare_dir)},
                        "items": [{"version": "fix1", "kind": "PARTIAL_UPDATE"}],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            plan_dir = root / "work" / "state" / "ucie"
            plan_dir.mkdir(parents=True)
            (plan_dir / "current_plan.json").write_text(json.dumps({"state": "DONE", "tasks": []}), encoding="utf-8")
            from lib_guard.window.cli import cmd_accept

            with self.assertRaisesRegex(ValueError, "effective manifest has unresolved conflicts"):
                cmd_accept(
                    argparse.Namespace(
                        catalog=None,
                        library="ucie",
                        workdir=str(root / "work"),
                        catalog_html_out=str(root / "catalog" / "html"),
                        window_file=str(window),
                        accepted_by="owner",
                        note="review passed",
                    )
                )

    def test_accept_window_rejects_when_current_effective_changed(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            effective_dir = root / "effective" / "candidate_fix1"
            effective_dir.mkdir(parents=True)
            manifest = effective_dir / "effective_manifest.json"
            manifest.write_text(json.dumps({"effective_id": "candidate_fix1", "summary": {"conflict_count": 0}}), encoding="utf-8")
            (effective_dir.parent / "current_effective.json").write_text(
                json.dumps({"current_effective_id": "E2", "revision": 8}),
                encoding="utf-8",
            )
            compare_dir = root / "compare"
            compare_dir.mkdir()
            (compare_dir / "compare_manifest.json").write_text(
                json.dumps({"old_target": {"spec": "effective:E0"}, "new_target": {"spec": "effective:candidate_fix1"}}),
                encoding="utf-8",
            )
            window = root / "pending_window.json"
            window.write_text(
                json.dumps(
                    {
                        "state": "PENDING",
                        "base_effective": {"target": "effective:E0", "current_effective_id": "E0"},
                        "candidate_effective": {"effective_id": "candidate_fix1", "manifest": str(manifest)},
                        "compare": {"old": "effective:E0", "new": "effective:candidate_fix1", "out_dir": str(compare_dir)},
                        "items": [{"version": "fix1", "kind": "PARTIAL_UPDATE"}],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            plan_dir = root / "work" / "state" / "ucie"
            plan_dir.mkdir(parents=True)
            (plan_dir / "current_plan.json").write_text(json.dumps({"state": "DONE", "tasks": []}), encoding="utf-8")
            from lib_guard.window.cli import cmd_accept

            with self.assertRaisesRegex(ValueError, "current effective changed"):
                cmd_accept(
                    argparse.Namespace(
                        catalog=None,
                        library="ucie",
                        workdir=str(root / "work"),
                        catalog_html_out=str(root / "catalog" / "html"),
                        window_file=str(window),
                        accepted_by="owner",
                        note="review passed",
                    )
                )

    def test_plan_engine_skips_done_tasks_on_same_input_fingerprint(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            from lib_guard.plan.engine import build_plan_from_window, execute_plan, load_plan, plan_path_for

            window = {
                "state": "PENDING",
                "last_seen_version": "fix1",
                "commands": [
                    ["run", "--catalog", "catalog.json", "--library", "ucie", "--version", "fix1", "--workdir", "work"],
                    ["effective", "build", "--catalog", "catalog.json", "--library", "ucie", "--base-full", "full1", "--effective-id", "candidate_fix1", "--out", "manifest.json"],
                    ["effective", "compare", "--catalog", "catalog.json", "--library", "ucie", "--old", "raw:full1", "--new", "effective:candidate_fix1", "--compare-id", "cmp1", "--out-dir", "cmp"],
                ],
            }
            path = plan_path_for(root / "work", "ucie")
            calls: list[list[str]] = []
            plan = build_plan_from_window(workdir=root / "work", library="ucie", window=window)
            code, first = execute_plan(plan_path=path, plan=plan, runner=lambda command: calls.append(command) or 0)
            self.assertEqual(code, 0)
            self.assertEqual(len(calls), 3)
            self.assertEqual(first["state"], "DONE")

            calls.clear()
            second_plan = build_plan_from_window(workdir=root / "work", library="ucie", window=window, existing=load_plan(path))
            code, second = execute_plan(plan_path=path, plan=second_plan, runner=lambda command: calls.append(command) or 0)
            self.assertEqual(code, 0)
            self.assertEqual(calls, [])
            self.assertEqual(second["state"], "DONE")


if __name__ == "__main__":
    unittest.main()
