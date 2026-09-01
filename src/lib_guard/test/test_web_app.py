from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SMOKE_CONFIG = ROOT / "work" / "single_library_smoke_20260805" / "lib_guard.yml"
LIBRARY = "vendor_A.openroad_platform.openroad_asap7"


class WebAppTest(unittest.TestCase):
    def test_file_change_rows_expose_old_and_new_paths_without_reading_raw(self) -> None:
        from lib_guard.web.read_model import list_file_diff_rows

        with tempfile.TemporaryDirectory() as td:
            diff_dir = Path(td) / "diff"
            diff_dir.mkdir()
            (diff_dir / "file_diff.json").write_text(
                json.dumps(
                    {
                        "added": ["new/gds/chip.gds"],
                        "removed": ["old/rtl/legacy.v"],
                        "changed": ["upstream/LEF/macro.lef"],
                        "renamed_or_moved": [{"old": "package/LEF/macro.lef", "new": "upstream/LEF/macro.lef"}],
                        "unverified": [{"old": "package/LIB/a.lib", "new": "upstream/LIB/a.lib"}],
                    }
                ),
                encoding="utf-8",
            )
            state = {
                "catalog": {
                    "libraries": [
                        {
                            "library_name": "demo",
                            "versions": [
                                {
                                    "version_id": "v2",
                                    "raw_path": str(Path(td) / "raw"),
                                    "diff": {"adjacent_diff_dir": str(diff_dir)},
                                }
                            ],
                        }
                    ]
                }
            }

            rows = list_file_diff_rows(state, "demo", "v2")

            self.assertEqual([row["change"] for row in rows], ["ADDED", "REMOVED", "CHANGED", "PATH_CHANGED", "PATH_CHANGED"])
            moved = next(row for row in rows if row["change"] == "PATH_CHANGED")
            self.assertEqual(moved["old_path"], "package/LEF/macro.lef")
            self.assertEqual(moved["new_path"], "upstream/LEF/macro.lef")
            self.assertTrue(moved["deep_diff_available"])
            self.assertFalse(next(row for row in rows if row["change"] == "ADDED")["deep_diff_available"])

    def test_health_and_library_routes_are_read_only(self) -> None:
        from lib_guard.web.app import create_app

        app = create_app(config_path=SMOKE_CONFIG, cwd=ROOT, test_config={"TESTING": True})
        client = app.test_client()

        self.assertEqual(client.get("/api/health").get_json()["status"], "PASS")
        response = client.get("/api/libraries")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["libraries"][0]["library_name"], LIBRARY)

    def test_unknown_library_is_rejected_before_job_creation(self) -> None:
        from lib_guard.web.app import create_app

        with tempfile.TemporaryDirectory() as td:
            app = create_app(config_path=SMOKE_CONFIG, cwd=ROOT, test_config={"TESTING": True, "job_root": td})
            response = app.test_client().post("/api/libraries/missing.library/versions/v1/scan")

            self.assertEqual(response.status_code, 404)
            self.assertEqual(list(Path(td).iterdir()), [])

    def test_scan_creates_a_validated_job_request(self) -> None:
        from lib_guard.web.app import create_app

        with tempfile.TemporaryDirectory() as td:
            app = create_app(config_path=SMOKE_CONFIG, cwd=ROOT, test_config={"TESTING": True, "job_root": td})
            response = app.test_client().post(
                f"/api/libraries/{LIBRARY}/versions/20260627_asap7/scan",
                json={"parse_jobs": 1},
            )

            self.assertEqual(response.status_code, 202)
            payload = response.get_json()
            request_path = Path(payload["request"])
            request = json.loads(request_path.read_text(encoding="utf-8"))
            self.assertEqual(request["action"], "scan")
            self.assertEqual(request["library"], LIBRARY)
            self.assertEqual(request["version"], "20260627_asap7")
            self.assertNotIn("shell", request)
            self.assertIn("observability", request)
            self.assertIn("progress_roots", request["observability"])

    def test_workspace_route_exposes_read_only_paths_and_scan_defaults(self) -> None:
        from lib_guard.web.app import create_app

        app = create_app(config_path=SMOKE_CONFIG, cwd=ROOT, test_config={"TESTING": True})
        payload = app.test_client().get("/api/workspace").get_json()

        self.assertEqual(payload["status"], "PASS")
        self.assertIn("catalog", payload["paths"])
        self.assertIn("hash_policy", payload["scan_strategy"])

    def test_path_children_defaults_to_configured_raw_root(self) -> None:
        from lib_guard.web.app import create_app

        app = create_app(config_path=SMOKE_CONFIG, cwd=ROOT, test_config={"TESTING": True})
        response = app.test_client().get("/api/path-children")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        raw_root = Path(payload["roots"][0]).resolve()
        current = Path(payload["current_path"]).resolve()
        self.assertEqual(current, raw_root)
        self.assertTrue(payload["children"])
        self.assertTrue(all(item["path"].startswith(str(raw_root) + "/") for item in payload["children"]))

    def test_path_children_rejects_path_outside_allowed_roots(self) -> None:
        from lib_guard.web.app import create_app

        app = create_app(config_path=SMOKE_CONFIG, cwd=ROOT, test_config={"TESTING": True})
        response = app.test_client().get("/api/path-children", query_string={"path": "/etc"})

        self.assertEqual(response.status_code, 400)
        self.assertIn("允许范围", response.get_json()["error"])

    def test_path_children_does_not_follow_symlink_outside_allowed_roots(self) -> None:
        from lib_guard.web.app import create_app

        with tempfile.TemporaryDirectory() as td:
            raw_root = Path(td) / "raw"
            workspace = Path(td) / "workspace"
            raw_root.mkdir()
            workspace.mkdir()
            outside = Path(td) / "outside"
            outside.mkdir()
            (raw_root / "escape").symlink_to(outside, target_is_directory=True)
            catalog_path = workspace / "catalog" / "catalog.json"
            catalog_path.parent.mkdir(parents=True)
            catalog_path.write_text(json.dumps({"libraries": []}), encoding="utf-8")
            config_path = workspace / "lib_guard.yml"
            config_path.write_text(
                "\n".join(
                    [
                        f"workspace: {workspace}",
                        f"raw_root: {raw_root}",
                        f"catalog: {catalog_path}",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            app = create_app(config_path=config_path, cwd=ROOT, test_config={"TESTING": True})

            response = app.test_client().get("/api/path-children")

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.get_json()["children"], [])

    def test_scan_request_accepts_explicit_strategy_settings(self) -> None:
        from lib_guard.web.app import create_app

        with tempfile.TemporaryDirectory() as td:
            app = create_app(config_path=SMOKE_CONFIG, cwd=ROOT, test_config={"TESTING": True, "job_root": td})
            response = app.test_client().post(
                f"/api/libraries/{LIBRARY}/versions/20260627_asap7/scan",
                json={
                    "hash_policy": "smart",
                    "parse_jobs": 4,
                    "parse_file_types": "lef,cdl",
                    "parse_exclude_file_types": "verilog,liberty",
                    "no_render": True,
                },
            )
            request = json.loads(Path(response.get_json()["request"]).read_text(encoding="utf-8"))

            self.assertIn("--hash-policy", request["args"])
            self.assertIn("--parse-file-types", request["args"])
            self.assertIn("--no-render", request["args"])

    def test_boolean_strategy_values_must_be_json_booleans(self) -> None:
        from lib_guard.web.app import create_app

        with tempfile.TemporaryDirectory() as td:
            app = create_app(config_path=SMOKE_CONFIG, cwd=ROOT, test_config={"TESTING": True, "job_root": td})
            response = app.test_client().post(
                f"/api/libraries/{LIBRARY}/versions/20260627_asap7/scan",
                json={"no_render": "false"},
            )

            self.assertEqual(response.status_code, 400)
            self.assertIn("布尔", response.get_json()["error"])
            self.assertEqual(list(Path(td).iterdir()), [])

    def test_non_object_json_is_rejected_without_creating_a_job(self) -> None:
        from lib_guard.web.app import create_app

        with tempfile.TemporaryDirectory() as td:
            app = create_app(config_path=SMOKE_CONFIG, cwd=ROOT, test_config={"TESTING": True, "job_root": td})
            response = app.test_client().post(
                f"/api/libraries/{LIBRARY}/versions/20260627_asap7/scan",
                json=["not", "an", "object"],
            )

            self.assertEqual(response.status_code, 400)
            self.assertIn("JSON 对象", response.get_json()["error"])
            self.assertEqual(list(Path(td).iterdir()), [])

    def test_malformed_json_is_rejected_without_creating_a_job(self) -> None:
        from lib_guard.web.app import create_app

        with tempfile.TemporaryDirectory() as td:
            app = create_app(config_path=SMOKE_CONFIG, cwd=ROOT, test_config={"TESTING": True, "job_root": td})
            response = app.test_client().post(
                f"/api/libraries/{LIBRARY}/versions/20260627_asap7/scan",
                data="{",
                content_type="application/json",
            )

            self.assertEqual(response.status_code, 400)
            self.assertIn("格式无效", response.get_json()["error"])
            self.assertEqual(list(Path(td).iterdir()), [])

    def test_non_json_body_is_rejected_without_creating_a_job(self) -> None:
        from lib_guard.web.app import create_app

        with tempfile.TemporaryDirectory() as td:
            app = create_app(config_path=SMOKE_CONFIG, cwd=ROOT, test_config={"TESTING": True, "job_root": td})
            response = app.test_client().post(
                f"/api/libraries/{LIBRARY}/versions/20260627_asap7/scan",
                data="scan",
                content_type="text/plain",
            )

            self.assertEqual(response.status_code, 400)
            self.assertIn("JSON 对象", response.get_json()["error"])
            self.assertEqual(list(Path(td).iterdir()), [])

    def test_compare_request_accepts_base_and_scan_policy(self) -> None:
        from lib_guard.web.app import create_app

        with tempfile.TemporaryDirectory() as td:
            app = create_app(config_path=SMOKE_CONFIG, cwd=ROOT, test_config={"TESTING": True, "job_root": td})
            response = app.test_client().post(
                f"/api/libraries/{LIBRARY}/versions/20260627_asap7/compare",
                json={"base": "20260624_asap7", "mode": "adjacent", "scan_if_missing": True, "rescan": False},
            )
            request = json.loads(Path(response.get_json()["request"]).read_text(encoding="utf-8"))

            self.assertIn("--base", request["args"])
            self.assertIn("--scan-if-missing", request["args"])

    def test_non_scan_job_does_not_reuse_scan_progress(self) -> None:
        from lib_guard.web.app import create_app

        with tempfile.TemporaryDirectory() as td:
            app = create_app(config_path=SMOKE_CONFIG, cwd=ROOT, test_config={"TESTING": True, "job_root": td})
            response = app.test_client().post(
                f"/api/libraries/{LIBRARY}/versions/20260627_asap7/release-check",
                json={},
            )

            self.assertEqual(response.status_code, 202)
            request = json.loads(Path(response.get_json()["request"]).read_text(encoding="utf-8"))
            self.assertEqual(request["observability"]["progress_roots"], [])

    def test_compare_without_rescan_does_not_reuse_scan_progress(self) -> None:
        from lib_guard.web.app import create_app

        with tempfile.TemporaryDirectory() as td:
            app = create_app(config_path=SMOKE_CONFIG, cwd=ROOT, test_config={"TESTING": True, "job_root": td})
            response = app.test_client().post(
                f"/api/libraries/{LIBRARY}/versions/20260627_asap7/compare",
                json={"base": "20260624_asap7", "mode": "adjacent", "scan_if_missing": False, "rescan": False},
            )

            self.assertEqual(response.status_code, 202)
            request = json.loads(Path(response.get_json()["request"]).read_text(encoding="utf-8"))
            self.assertEqual(request["observability"]["progress_roots"], [])

    def test_compare_rescan_observes_the_new_scan_progress_roots(self) -> None:
        from lib_guard.web.app import create_app

        with tempfile.TemporaryDirectory() as td:
            app = create_app(config_path=SMOKE_CONFIG, cwd=ROOT, test_config={"TESTING": True, "job_root": td})
            response = app.test_client().post(
                f"/api/libraries/{LIBRARY}/versions/20260627_asap7/compare",
                json={"base": "20260624_asap7", "rescan": True},
            )

            self.assertEqual(response.status_code, 202)
            request = json.loads(Path(response.get_json()["request"]).read_text(encoding="utf-8"))
            self.assertTrue(request["observability"]["progress_roots"])

    def test_compare_rejects_base_from_another_library_before_job_creation(self) -> None:
        from lib_guard.web.app import create_app

        with tempfile.TemporaryDirectory() as td:
            app = create_app(config_path=SMOKE_CONFIG, cwd=ROOT, test_config={"TESTING": True, "job_root": td})
            response = app.test_client().post(
                f"/api/libraries/{LIBRARY}/versions/20260627_asap7/compare",
                json={"base": "not_in_this_catalog"},
            )

            self.assertEqual(response.status_code, 409)
            self.assertIn("不属于当前库", response.get_json()["error"])
            self.assertEqual(list(Path(td).iterdir()), [])

    def test_compare_without_catalog_base_is_rejected_before_job_creation(self) -> None:
        from lib_guard.web.app import create_app

        with tempfile.TemporaryDirectory() as td:
            app = create_app(config_path=SMOKE_CONFIG, cwd=ROOT, test_config={"TESTING": True, "job_root": td})
            response = app.test_client().post(
                f"/api/libraries/{LIBRARY}/versions/20260624_asap7/compare",
                json={},
            )

            self.assertEqual(response.status_code, 409)
            self.assertIn("对比基准", response.get_json()["error"])
            self.assertEqual(list(Path(td).iterdir()), [])

    def test_accept_window_without_candidate_is_rejected_before_job_creation(self) -> None:
        from lib_guard.web.app import create_app

        with tempfile.TemporaryDirectory() as td:
            app = create_app(config_path=SMOKE_CONFIG, cwd=ROOT, test_config={"TESTING": True, "job_root": td})
            response = app.test_client().post(
                f"/api/libraries/{LIBRARY}/accept-window",
                json={"accepted_by": "owner"},
            )

            self.assertEqual(response.status_code, 409)
            self.assertIn("候选有效版", response.get_json()["error"])
            self.assertEqual(list(Path(td).iterdir()), [])

    def test_window_actions_are_allowlisted_and_do_not_accept_arbitrary_commands(self) -> None:
        from lib_guard.web.app import create_app

        with tempfile.TemporaryDirectory() as td:
            app = create_app(config_path=SMOKE_CONFIG, cwd=ROOT, test_config={"TESTING": True, "job_root": td})
            client = app.test_client()
            next_response = client.post(f"/api/libraries/{LIBRARY}/next", json={"plan_only": True})
            intake_response = client.post(f"/api/libraries/{LIBRARY}/intake", json={"plan_only": True})

            next_request = json.loads(Path(next_response.get_json()["request"]).read_text(encoding="utf-8"))
            intake_request = json.loads(Path(intake_response.get_json()["request"]).read_text(encoding="utf-8"))
            self.assertEqual(next_request["args"][-2:], [LIBRARY, "--plan-only"])
            self.assertIn("intake", intake_request["args"])
            self.assertNotIn("shell", next_request)

    def test_mark_and_override_requests_validate_allowed_values(self) -> None:
        from lib_guard.web.app import create_app

        with tempfile.TemporaryDirectory() as td:
            app = create_app(config_path=SMOKE_CONFIG, cwd=ROOT, test_config={"TESTING": True, "job_root": td})
            client = app.test_client()
            marked = client.post(
                f"/api/libraries/{LIBRARY}/versions/20260627_asap7/mark",
                json={"type": "FULL", "note": "manual confirmed"},
            )
            overridden = client.post(
                f"/api/libraries/{LIBRARY}/versions/20260627_asap7/override",
                json={"package_type": "FULL_PACKAGE", "compare_default": "previous_effective", "note": "confirmed"},
            )

            mark_request = json.loads(Path(marked.get_json()["request"]).read_text(encoding="utf-8"))
            override_request = json.loads(Path(overridden.get_json()["request"]).read_text(encoding="utf-8"))
            self.assertIn("--type", mark_request["args"])
            self.assertIn("library", override_request["args"])

            rejected = client.post(
                f"/api/libraries/{LIBRARY}/versions/20260627_asap7/mark",
                json={"type": "rm -rf /"},
            )
            self.assertEqual(rejected.status_code, 400)
            self.assertEqual(len(list(Path(td).iterdir())), 2)

    def test_unmanaged_job_is_not_reported_as_still_running_after_restart(self) -> None:
        from lib_guard.web.app import _job_status

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "status.json").write_text(json.dumps({"status": "RUNNING"}), encoding="utf-8")

            status = _job_status(root, None)

            self.assertEqual(status["status"], "UNKNOWN")
            self.assertIn("未接管", status["message"])

    def test_unmanaged_job_with_missing_or_invalid_status_is_terminal_unknown(self) -> None:
        from lib_guard.web.app import _job_status

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            status = _job_status(root, None)
            self.assertEqual(status["status"], "UNKNOWN")
            self.assertIn("状态文件", status["message"])

    def test_run_status_exposes_terminal_tail_and_scan_progress(self) -> None:
        from lib_guard.web.app import _job_status

        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "job"
            progress = Path(td) / "scan" / "logs" / "scan_progress_latest.json"
            root.mkdir()
            progress.parent.mkdir(parents=True)
            (root / "status.json").write_text(
                json.dumps({"status": "COMPLETED", "started_epoch": 100.0, "finished_epoch": 112.5}),
                encoding="utf-8",
            )
            (root / "request.json").write_text(
                json.dumps({"observability": {"progress_paths": [str(progress)]}}),
                encoding="utf-8",
            )
            (root / "stdout.log").write_text("1/7 walk 4/4 100%\nscan finished\n", encoding="utf-8")
            progress.write_text(
                json.dumps({
                    "event": "step",
                    "stage": "4/7 parse",
                    "message": "parser task finished",
                    "done": 8,
                    "total": 10,
                    "percent": 80.0,
                    "performance": {"total_seconds": 12.5},
                }),
                encoding="utf-8",
            )

            status = _job_status(root, None)

            self.assertIn("scan finished", status["log_tail"])
            self.assertEqual(status["elapsed_seconds"], 12.5)
            self.assertEqual(status["progress"]["stage"], "4/7 parse")
            self.assertEqual(status["progress"]["percent"], 80.0)

            (root / "status.json").write_text(json.dumps({"status": "BOGUS"}), encoding="utf-8")
            status = _job_status(root, None)
            self.assertEqual(status["status"], "UNKNOWN")
            self.assertIn("未知", status["message"])

            (root / "status.json").write_text("{", encoding="utf-8")
            status = _job_status(root, None)
            self.assertEqual(status["status"], "UNKNOWN")
            self.assertIn("状态文件", status["message"])

    def test_failed_release_job_exposes_a_short_failure_summary(self) -> None:
        from lib_guard.web.app import _job_status

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "status.json").write_text(
                json.dumps({"status": "FAILED", "return_code": 2, "started_epoch": 100.0, "finished_epoch": 101.0}),
                encoding="utf-8",
            )
            (root / "stdout.log").write_text(
                json.dumps(
                    {
                        "release_check_status": "BLOCK",
                        "block_reasons": ["审查门禁未关闭", "当前有效版对比未完成"],
                        "issues": [{"severity": "blocker", "title": "审查门禁未关闭"}],
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

            status = _job_status(root, None)

            self.assertIn("发布检查被阻塞", status["error"])
            self.assertIn("审查门禁未关闭", status["error"])
            self.assertLessEqual(len(status["error"]), 240)

    def test_arbitrary_action_route_does_not_exist(self) -> None:
        from lib_guard.web.app import create_app

        app = create_app(config_path=SMOKE_CONFIG, cwd=ROOT, test_config={"TESTING": True})

        response = app.test_client().post("/api/run-shell", json={"command": "rm -rf /"})

        self.assertEqual(response.status_code, 404)

    def test_catalog_refresh_and_worklist_routes_expand_to_short_commands(self) -> None:
        from lib_guard.web.app import create_app

        with tempfile.TemporaryDirectory() as td:
            app = create_app(config_path=SMOKE_CONFIG, cwd=ROOT, test_config={"TESTING": True, "job_root": td})
            client = app.test_client()

            catalog = client.post(
                f"/api/libraries/{LIBRARY}/catalog",
                json={"refresh": True, "with_evidence": False, "full": True},
            )
            worklist = client.post("/api/worklist", json={})

            self.assertEqual(catalog.status_code, 202)
            self.assertEqual(worklist.status_code, 202)
            catalog_request = json.loads(Path(catalog.get_json()["request"]).read_text(encoding="utf-8"))
            worklist_request = json.loads(Path(worklist.get_json()["request"]).read_text(encoding="utf-8"))
            self.assertEqual(catalog_request["args"][catalog_request["args"].index("cat") : catalog_request["args"].index("cat") + 2], ["cat", LIBRARY])
            self.assertIn("--refresh-catalog", catalog_request["args"])
            self.assertIn("--full", catalog_request["args"])
            self.assertIn("worklist", worklist_request["args"])

    def test_file_diff_route_uses_catalog_relative_inputs_and_rejects_traversal(self) -> None:
        from lib_guard.web.app import create_app

        with tempfile.TemporaryDirectory() as td:
            app = create_app(config_path=SMOKE_CONFIG, cwd=ROOT, test_config={"TESTING": True, "job_root": td})
            client = app.test_client()
            response = client.post(
                f"/api/libraries/{LIBRARY}/versions/20260627_asap7/file-diff",
                json={"base": "20260624_asap7", "relpath": "lef/asap7.lef", "type": "lef"},
            )
            rejected = client.post(
                f"/api/libraries/{LIBRARY}/versions/20260627_asap7/file-diff",
                json={"base": "20260624_asap7", "relpath": "../outside.lef", "type": "lef"},
            )

            self.assertEqual(response.status_code, 202)
            request = json.loads(Path(response.get_json()["request"]).read_text(encoding="utf-8"))
            start = request["args"].index("fd")
            self.assertEqual(request["args"][start : start + 4], ["fd", LIBRARY, "20260627_asap7", "lef/asap7.lef"])
            self.assertIn("--base", request["args"])
            self.assertNotIn("--force-large", request["args"])
            self.assertEqual(rejected.status_code, 400)
            self.assertIn("相对路径", rejected.get_json()["error"])

    def test_file_diff_route_accepts_linked_old_and_new_paths(self) -> None:
        from lib_guard.web.app import create_app

        with tempfile.TemporaryDirectory() as td:
            app = create_app(config_path=SMOKE_CONFIG, cwd=ROOT, test_config={"TESTING": True, "job_root": td})
            response = app.test_client().post(
                f"/api/libraries/{LIBRARY}/versions/20260627_asap7/file-diff",
                json={
                    "base": "20260624_asap7",
                    "old_relpath": "asap7_source_package/lef/asap7_tech_1x_201209.lef",
                    "relpath": "upstream_ae9a8ed9/lef/asap7_tech_1x_201209.lef",
                    "type": "lef",
                },
            )

            self.assertEqual(response.status_code, 202)
            request = json.loads(Path(response.get_json()["request"]).read_text(encoding="utf-8"))
            start = request["args"].index("fd")
            self.assertEqual(request["args"][start : start + 2], ["fd", "--old"])
            old_path = ROOT / "tests" / "fixtures" / "raw" / "vendor_A" / "openroad_asap7" / "20260624_asap7" / "asap7_source_package" / "lef" / "asap7_tech_1x_201209.lef"
            new_path = ROOT / "tests" / "fixtures" / "raw" / "vendor_A" / "openroad_asap7" / "20260627_asap7" / "upstream_ae9a8ed9" / "lef" / "asap7_tech_1x_201209.lef"
            self.assertIn(str(old_path), request["args"])
            self.assertIn(str(new_path), request["args"])

    def test_file_diff_route_rejects_large_linked_type_without_explicit_opt_in(self) -> None:
        from lib_guard.web.app import create_app

        with tempfile.TemporaryDirectory() as td:
            app = create_app(config_path=SMOKE_CONFIG, cwd=ROOT, test_config={"TESTING": True, "job_root": td})
            response = app.test_client().post(
                f"/api/libraries/{LIBRARY}/versions/20260627_asap7/file-diff",
                json={
                    "base": "20260624_asap7",
                    "old_relpath": "asap7_source_package/lib/CCS/asap7sc7p5t_SEQ_RVT_FF_ccs_220123.lib",
                    "relpath": "upstream_ae9a8ed9/lib/CCS/asap7sc7p5t_SEQ_RVT_FF_ccs_220123.lib",
                    "type": "liberty",
                },
            )

            self.assertEqual(response.status_code, 400)
            self.assertIn("force-large", response.get_json()["error"])
            self.assertEqual(list(Path(td).iterdir()), [])

    def test_file_diff_route_allows_large_linked_type_only_with_opt_in(self) -> None:
        from lib_guard.web.app import create_app

        with tempfile.TemporaryDirectory() as td:
            app = create_app(config_path=SMOKE_CONFIG, cwd=ROOT, test_config={"TESTING": True, "job_root": td})
            response = app.test_client().post(
                f"/api/libraries/{LIBRARY}/versions/20260627_asap7/file-diff",
                json={
                    "base": "20260624_asap7",
                    "old_relpath": "asap7_source_package/lib/CCS/asap7sc7p5t_SEQ_RVT_FF_ccs_220123.lib",
                    "relpath": "upstream_ae9a8ed9/lib/CCS/asap7sc7p5t_SEQ_RVT_FF_ccs_220123.lib",
                    "type": "liberty",
                    "force_large": True,
                },
            )

            self.assertEqual(response.status_code, 202)
            request = json.loads(Path(response.get_json()["request"]).read_text(encoding="utf-8"))
            self.assertIn("--old", request["args"])
            self.assertIn("--new", request["args"])
            self.assertIn("--force-large", request["args"])

    def test_linked_file_diff_request_does_not_overwrite_scan_or_version_diff(self) -> None:
        from lib_guard.web.app import create_app
        from lib_guard.web.read_model import load_web_state

        with tempfile.TemporaryDirectory() as td:
            state = load_web_state(config_path=SMOKE_CONFIG, cwd=ROOT)
            library = next(item for item in state["catalog"]["libraries"] if item.get("library_name") == LIBRARY)
            version = next(item for item in library["versions"] if item.get("version_id") == "20260627_asap7")
            scan_dir = Path(str((version.get("scan") or {}).get("scan_dir") or ""))
            diff_data = version.get("diff") or {}
            diff_dir = Path(str(diff_data.get("adjacent_diff_dir") or diff_data.get("base_diff_dir") or ""))
            before = {
                "catalog": Path(state["catalog_path"]).read_bytes(),
                "scan": (scan_dir / "file_inventory.json").read_bytes(),
                "diff": (diff_dir / "file_diff.json").read_bytes(),
            }
            app = create_app(config_path=SMOKE_CONFIG, cwd=ROOT, test_config={"TESTING": True, "job_root": td})
            response = app.test_client().post(
                f"/api/libraries/{LIBRARY}/versions/20260627_asap7/file-diff",
                json={
                    "base": "20260624_asap7",
                    "old_relpath": "asap7_source_package/lef/asap7_tech_1x_201209.lef",
                    "relpath": "upstream_ae9a8ed9/lef/asap7_tech_1x_201209.lef",
                    "type": "lef",
                },
            )

            self.assertEqual(response.status_code, 202)
            self.assertEqual(before["catalog"], Path(state["catalog_path"]).read_bytes())
            self.assertEqual(before["scan"], (scan_dir / "file_inventory.json").read_bytes())
            self.assertEqual(before["diff"], (diff_dir / "file_diff.json").read_bytes())

    def test_file_changes_endpoint_exposes_existing_diff_rows(self) -> None:
        from lib_guard.web.app import create_app

        with tempfile.TemporaryDirectory() as td:
            app = create_app(config_path=SMOKE_CONFIG, cwd=ROOT, test_config={"TESTING": True, "job_root": td})
            response = app.test_client().get(
                f"/api/libraries/{LIBRARY}/versions/20260627_asap7/file-changes"
            )

            self.assertEqual(response.status_code, 200)
            payload = response.get_json()
            self.assertEqual(payload["source"], "existing_file_diff_evidence")
            self.assertEqual(payload["base_version"], "20260624_asap7")
            self.assertGreater(payload["count"], 0)
            self.assertIn("file_type", payload["rows"][0])

    def test_file_tree_endpoint_exposes_scan_inventory_as_relative_paths(self) -> None:
        from lib_guard.web.app import create_app

        with tempfile.TemporaryDirectory() as td:
            app = create_app(config_path=SMOKE_CONFIG, cwd=ROOT, test_config={"TESTING": True, "job_root": td})
            response = app.test_client().get(
                f"/api/libraries/{LIBRARY}/versions/20260627_asap7/file-tree"
            )

            self.assertEqual(response.status_code, 200)
            payload = response.get_json()
            self.assertEqual(payload["status"], "PASS")
            self.assertEqual(payload["source"], "scan_file_inventory")
            self.assertGreater(payload["file_count"], 0)
            self.assertTrue(payload["files"])
            self.assertTrue(all("abs_path" not in row for row in payload["files"]))
            self.assertTrue(all(not row["path"].startswith("/") for row in payload["files"]))

    def test_review_gate_and_packet_routes_expand_to_fixed_short_commands(self) -> None:
        from lib_guard.web.app import create_app

        with tempfile.TemporaryDirectory() as td:
            app = create_app(config_path=SMOKE_CONFIG, cwd=ROOT, test_config={"TESTING": True, "job_root": td})
            client = app.test_client()
            gate = client.post(
                f"/api/libraries/{LIBRARY}/versions/20260627_asap7/review-gate",
                json={"operation": "check", "gate": "current"},
            )
            packet = client.post(
                f"/api/libraries/{LIBRARY}/versions/20260627_asap7/review-packet",
                json={"operation": "submit", "review_id": "review_01", "decision": "PASS", "note": "checked", "reviewer": "reviewer"},
            )

            self.assertEqual(gate.status_code, 202)
            self.assertEqual(packet.status_code, 202)
            gate_request = json.loads(Path(gate.get_json()["request"]).read_text(encoding="utf-8"))
            packet_request = json.loads(Path(packet.get_json()["request"]).read_text(encoding="utf-8"))
            gate_start = gate_request["args"].index("rv")
            packet_start = packet_request["args"].index("review")
            self.assertEqual(gate_request["args"][gate_start : gate_start + 2], ["rv", "check"])
            self.assertEqual(packet_request["args"][packet_start : packet_start + 2], ["review", "submit"])
            self.assertIn("--reviewer", packet_request["args"])
            self.assertNotIn("shell", gate_request)
            self.assertNotIn("shell", packet_request)

    def test_library_admin_action_file_and_rollback_routes_are_allowlisted(self) -> None:
        from lib_guard.web.app import create_app

        with tempfile.TemporaryDirectory() as td:
            app = create_app(config_path=SMOKE_CONFIG, cwd=ROOT, test_config={"TESTING": True, "job_root": td})
            client = app.test_client()
            requests = [
                ("/api/library/discover", {}, "library"),
                ("/api/library/accept", {}, "library"),
                ("/api/library/apply", {}, "library"),
                ("/api/library/add", {"library_id": "Vendor_Z.demo", "root": str(ROOT / "tests" / "fixtures" / "raw" / "vendor_A")}, "library"),
                (f"/api/libraries/{LIBRARY}/action", {}, "action"),
                (
                    f"/api/libraries/{LIBRARY}/effective-rollback",
                    {"to": "E_old", "by": "owner", "reason": "candidate was incorrect"},
                    "effective",
                ),
            ]

            for endpoint, payload, expected in requests:
                response = client.post(endpoint, json=payload)
                self.assertEqual(response.status_code, 202, endpoint)
                request = json.loads(Path(response.get_json()["request"]).read_text(encoding="utf-8"))
                self.assertIn(expected, request["args"])
                self.assertNotIn("shell", request)

    def test_library_add_rejects_root_outside_configured_browse_scope(self) -> None:
        from lib_guard.web.app import create_app

        with tempfile.TemporaryDirectory() as td:
            app = create_app(config_path=SMOKE_CONFIG, cwd=ROOT, test_config={"TESTING": True, "job_root": td})
            response = app.test_client().post(
                "/api/library/add",
                json={"library_id": "outside.demo", "root": "/etc"},
            )

            self.assertEqual(response.status_code, 400)
            self.assertIn("浏览目录", response.get_json()["error"])
            self.assertEqual(list(Path(td).iterdir()), [])


if __name__ == "__main__":
    unittest.main()
