import json
from pathlib import Path
import re
import tempfile
from threading import Barrier
import time
import unittest
from unittest.mock import patch

from lib_guard import workbench
from lib_guard.workbench import _acquire_library_lock, _files_for_selection, _quick_linked_checks, _release_library_lock, _update_task, create_app


class WorkbenchTests(unittest.TestCase):
    def test_file_selection_reports_walk_permission_errors_as_truncation(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "raw"
            root.mkdir()
            expected = root / "part.lib"

            def walk_with_error(path, followlinks=False, onerror=None):
                onerror(PermissionError(13, "permission denied", str(root / "restricted")))
                yield str(root), [], [expected.name]

            with patch("lib_guard.workbench.os.walk", side_effect=walk_with_error):
                files, reason = _files_for_selection(str(root), (".lib",))

            self.assertEqual(files, [str(expected)])
            self.assertEqual(reason, "ACCESS_ERROR")

    def test_file_selection_preserves_permission_error_when_limit_is_hit(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "raw"
            root.mkdir()
            names = [f"part_{index:03}.lib" for index in range(200)]

            def walk_with_error_and_limit(path, followlinks=False, onerror=None):
                onerror(PermissionError(13, "permission denied", str(root / "restricted")))
                yield str(root), [], names

            with patch("lib_guard.workbench.os.walk", side_effect=walk_with_error_and_limit):
                files, reason = _files_for_selection(str(root), (".lib",))

            self.assertEqual(len(files), 200)
            self.assertEqual(set(reason.split("+")), {"ACCESS_ERROR", "LIMIT"})

    def test_start_status_write_failure_releases_task_slot_and_library_lock(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            registry = root / "registry.yml"
            registry.write_text("ips:\n  - {id: IP_A, library_id: vendor.ip_a, checks: {}}\n", encoding="utf-8")
            client = create_app(registry, root / "output").test_client()
            original_update = workbench._update_task
            running_write_attempted = __import__("threading").Event()

            def fail_running_write(task_path, latest_path, task):
                if task.get("status") == "RUNNING":
                    running_write_attempted.set()
                    raise OSError("controlled task-state write failure")
                return original_update(task_path, latest_path, task)

            with patch("lib_guard.workbench._update_task", side_effect=fail_running_write):
                response = client.post("/run", data={
                    "id": "IP_A", "library_id": "vendor.ip_a", "checks": ["macro_index"],
                    "macro_report_json": str(root / "existing.json"),
                }, follow_redirects=True)
                self.assertEqual(response.status_code, 200)
                self.assertTrue(running_write_attempted.wait(timeout=1))
                for _ in range(100):
                    slots = [workbench._REVIEW_TASK_SLOTS.acquire(blocking=False) for _ in range(8)]
                    if all(slots):
                        for _ in slots:
                            workbench._REVIEW_TASK_SLOTS.release()
                        break
                    for acquired in slots:
                        if acquired:
                            workbench._REVIEW_TASK_SLOTS.release()
                    time.sleep(0.01)

            self.assertEqual(slots, [True] * 8)
            lock_handle = _acquire_library_lock(root / "output", "vendor.ip_a")
            self.assertIsNotNone(lock_handle)
            _release_library_lock(lock_handle)

    def test_library_lock_is_shared_across_workbench_instances(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp)
            first = _acquire_library_lock(output, "vendor.ip_a")
            try:
                self.assertIsNotNone(first)
                self.assertIsNone(_acquire_library_lock(output, "vendor.ip_a"))
            finally:
                _release_library_lock(first)
            second = _acquire_library_lock(output, "vendor.ip_a")
            self.assertIsNotNone(second)
            _release_library_lock(second)

    def test_quick_linked_checks_builds_macro_lef_and_liberty_inputs_from_versions(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            old_root, new_root = root / "raw" / "V1", root / "raw" / "V2"
            old_lef = old_root / "LEF" / "top.lef"
            new_lef = new_root / "LEF" / "top.lef"
            liberty = new_root / "LIB" / "TT" / "top_tt.lib.gz"
            for path in (old_lef, new_lef, liberty):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.touch()
            ip = {"id": "IP_A", "library_id": "Vendor.IP_A", "raw_versions": [
                {"id": "V1", "path": str(old_root)}, {"id": "V2", "path": str(new_root)}]}

            checks, notes = _quick_linked_checks(ip, "V2", "V1", "", "")

            self.assertEqual(set(checks), {"macro_index", "lef_review", "lef_liberty_check"})
            self.assertEqual(checks["macro_index"]["root"], str(new_root))
            self.assertEqual(checks["lef_review"]["old_file"], str(old_lef))
            self.assertEqual(checks["lef_review"]["new_file"], str(new_lef))
            self.assertEqual(checks["lef_liberty_check"]["liberty_files"], [str(liberty)])
            self.assertIn("LEF：1 个", " ".join(notes))

    def test_quick_linked_checks_supports_single_version_without_fake_lef_delta(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "raw" / "V1"
            lef, liberty = root / "LEF" / "top.lef", root / "LIB" / "TT" / "top.lib"
            for path in (lef, liberty):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.touch()
            ip = {"id": "IP_A", "library_id": "Vendor.IP_A", "raw_versions": [
                {"id": "V1", "path": str(root)}]}

            checks, _ = _quick_linked_checks(ip, "V1", "", "", "")

            self.assertEqual(set(checks), {"macro_index", "lef_liberty_check"})
            self.assertEqual(checks["lef_liberty_check"]["lef_file"], str(lef))
            self.assertNotIn("lef_review", checks)

    def test_quick_linked_checks_does_not_guess_between_multiple_lefs(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "raw" / "V1"
            for name in ("a.lef", "b.lef"):
                (root / "LEF" / name).parent.mkdir(parents=True, exist_ok=True)
                (root / "LEF" / name).touch()
            liberty = root / "LIB" / "TT" / "top.lib"
            liberty.parent.mkdir(parents=True)
            liberty.touch()
            ip = {"id": "IP_A", "library_id": "Vendor.IP_A", "raw_versions": [
                {"id": "V1", "path": str(root)}]}

            with self.assertRaisesRegex(ValueError, "多个 LEF.*明确选择"):
                _quick_linked_checks(ip, "V1", "", "", "")

    def test_quick_linked_checks_rejects_truncated_liberty_file_list(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "raw" / "V1"
            lef = root / "LEF" / "top.lef"
            lef.parent.mkdir(parents=True)
            lef.touch()
            liberty_dir = root / "LIB"
            liberty_dir.mkdir(parents=True)
            for index in range(201):
                (liberty_dir / f"part_{index:03}.lib").touch()
            ip = {"id": "IP_A", "library_id": "Vendor.IP_A", "raw_versions": [
                {"id": "V1", "path": str(root)}]}

            with self.assertRaisesRegex(ValueError, "Liberty 文件列表不完整.*超过工作台枚举上限"):
                _quick_linked_checks(ip, "V1", "", str(lef), "")

    def test_catalog_places_download_link_next_to_latest_success(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            registry = root / "registry.yml"
            registry.write_text("ips:\n  - {id: IP_A, library_id: vendor.ip_a, name: IP A, checks: {}}\n", encoding="utf-8")
            from lib_guard.review_runner import _library_dir
            library_dir = root / "output" / "libraries" / _library_dir("vendor.ip_a")
            run_dir = library_dir / "runs" / "review_20261024T000000Z_abcd1234"
            run_dir.mkdir(parents=True)
            (library_dir / "latest.json").write_text(
                '{"review_id":"review_20261024T000000Z_abcd1234"}', encoding="utf-8")
            (library_dir / "latest_workbook.json").write_text(json.dumps({
                "review_id": "review_20261024T000000Z_abcd1234",
                "generated_at": "2026-10-24T00:00:00+00:00",
            }), encoding="utf-8")
            (run_dir / "review_result.json").write_text(json.dumps({
                "review_id": "review_20261024T000000Z_abcd1234", "execution_status": "COMPLETE",
                "summary": {},
            }), encoding="utf-8")
            (run_dir / "ip_review.xlsx").write_bytes(b"xlsx")
            (library_dir / "latest.xlsx").write_bytes(b"stable xlsx")
            report_dir = root / "output" / "ip_checks"
            report_dir.mkdir(parents=True)
            (report_dir / "index.html").write_text("<h1>IP 检查总览</h1>", encoding="utf-8")

            client = create_app(registry, root / "output").test_client()
            response = client.get("/?ip=IP_A&tab=catalog")

            self.assertEqual(response.status_code, 200)
            self.assertIn("最近完整 Excel".encode(), response.data)
            self.assertIn(b"/review-reports/libraries/", response.data)
            self.assertIn("检查结果 HTML".encode(), response.data)
            html = client.get("/review-reports/ip_checks/index.html")
            self.assertEqual(html.status_code, 200)
            self.assertIn("IP 检查总览".encode(), html.data)
            html.close()
            response.close()

    def test_review_overview_relative_latest_workbook_link_is_served_from_output(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            registry = root / "registry.yml"
            registry.write_text("ips:\n  - {id: IP_A, library_id: vendor.ip_a, checks: {}}\n", encoding="utf-8")
            from lib_guard.review_runner import _library_dir
            library_dir = root / "output" / "libraries" / _library_dir("vendor.ip_a")
            library_dir.mkdir(parents=True)
            (library_dir / "latest.xlsx").write_bytes(b"workbook")
            reports = root / "output" / "ip_checks"
            reports.mkdir(parents=True)
            (reports / "index.html").write_text(
                f'<a href="../libraries/{library_dir.name}/latest.xlsx">最新 Excel</a>', encoding="utf-8")
            client = create_app(registry, root / "output").test_client()

            overview = client.get("/review-reports/ip_checks/index.html")
            workbook = client.get(f"/review-reports/libraries/{library_dir.name}/latest.xlsx")
            unknown = client.get("/review-reports/libraries/not-registered/latest.xlsx")

            self.assertEqual(overview.status_code, 200)
            self.assertEqual(workbook.status_code, 200)
            self.assertEqual(workbook.data, b"workbook")
            self.assertIn("vendor.ip_a_latest.xlsx", workbook.headers.get("Content-Disposition", ""))
            self.assertEqual(unknown.status_code, 404)
            overview.close()
            workbook.close()
            unknown.close()

    def test_latest_excel_display_stays_on_last_complete_run_after_newer_incomplete_run(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            registry = root / "registry.yml"
            registry.write_text("ips:\n  - {id: IP_A, library_id: vendor.ip_a, checks: {}}\n", encoding="utf-8")
            from lib_guard.review_runner import _library_dir
            library_dir = root / "output" / "libraries" / _library_dir("vendor.ip_a")
            good_id = "review_20261024T010000Z_aaaaaaaa"
            bad_id = "review_20261024T020000Z_bbbbbbbb"
            for review_id, status in ((good_id, "COMPLETE"), (bad_id, "INCOMPLETE")):
                run_dir = library_dir / "runs" / review_id
                run_dir.mkdir(parents=True)
                (run_dir / "ip_review.xlsx").write_bytes(review_id.encode())
                (run_dir / "review_result.json").write_text(json.dumps({
                    "review_id": review_id, "execution_status": status, "generated_at": review_id,
                    "summary": {},
                }), encoding="utf-8")
            (library_dir / "latest_workbook.json").write_text(json.dumps({
                "review_id": good_id, "generated_at": "2026-10-24T01:00:00+00:00",
            }), encoding="utf-8")
            (library_dir / "latest.xlsx").write_bytes(b"stable")
            (library_dir / "latest.json").write_text(json.dumps({"review_id": bad_id}), encoding="utf-8")

            response = create_app(registry, root / "output").test_client().get("/?ip=IP_A&tab=catalog")
            body = response.get_data(as_text=True)
            heading = re.search(r'<div class="latest-chip">(.*?)</div>', body, re.S).group(1)

            self.assertIn(good_id, heading)
            self.assertNotIn(bad_id, heading)
            self.assertIn("最近完整 Excel", heading)
            response.close()

    def test_discover_page_displays_specific_partial_discovery_warnings(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            registry = root / "registry.yml"
            registry.write_text("ips: []\n", encoding="utf-8")
            app = create_app(registry, root / "output")
            report = {
                "candidates": [], "partial_discovery": True, "identity_conflicts": [],
                "warnings": ["有 2 个目录访问失败，发现结果可能不完整。",
                             "有 1 个目录达到目录深度上限 8，未继续检查其下级目录。"],
            }

            with patch("lib_guard.workbench.discover_raw_report", return_value=report):
                response = app.test_client().post("/discover", data={"raw_root": str(root)})

            body = response.get_data(as_text=True)
            self.assertEqual(response.status_code, 200)
            self.assertIn("有 2 个目录访问失败", body)
            self.assertIn("有 1 个目录达到目录深度上限 8", body)
            self.assertNotIn("文件线索抽样或目录访问达到上限", body)

    def test_excel_link_uses_latest_complete_run_when_latest_pointer_is_not_enabled(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            registry = root / "registry.yml"
            registry.write_text("ips:\n  - {id: IP_A, library_id: vendor.ip_a, name: IP A, checks: {}}\n", encoding="utf-8")
            from lib_guard.review_runner import _library_dir
            review_id = "review_20261024T010000Z_abcd1234"
            run_dir = root / "output" / "libraries" / _library_dir("vendor.ip_a") / "runs" / review_id
            run_dir.mkdir(parents=True)
            (run_dir / "review_result.json").write_text(
                json.dumps({"review_id": review_id, "execution_status": "COMPLETE", "summary": {}}), encoding="utf-8")
            (run_dir / "ip_review.xlsx").write_bytes(b"xlsx")

            response = create_app(registry, root / "output").test_client().get("/?ip=IP_A&tab=review")

            self.assertEqual(response.status_code, 200)
            self.assertIn("最近完整检查报告".encode(), response.data)
            self.assertIn("最近完整 Excel".encode(), response.data)
            self.assertIn(review_id.encode(), response.data)
            self.assertIn(f"/download?library_id=vendor.ip_a&amp;review_id={review_id}".encode(), response.data)

    def test_legacy_complete_run_is_exposed_through_stable_latest_excel_route(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            registry = root / "registry.yml"
            registry.write_text("ips:\n  - {id: IP_A, library_id: vendor.ip_a, name: IP A, vendor: V, checks: {}}\n", encoding="utf-8")
            from lib_guard.review_runner import _library_dir
            library_dir = root / "output" / "libraries" / _library_dir("vendor.ip_a")
            run_dir = library_dir / "runs" / "review_20261024T010000Z_abcd1234"
            run_dir.mkdir(parents=True)
            (run_dir / "review_result.json").write_text(json.dumps({
                "review_id": "review_20261024T010000Z_abcd1234",
                "execution_status": "COMPLETE", "generated_at": "2026-10-24T01:00:00Z", "summary": {},
            }), encoding="utf-8")
            (run_dir / "ip_review.xlsx").write_bytes(b"legacy workbook")

            client = create_app(registry, root / "output").test_client()
            page = client.get("/?ip=IP_A&tab=catalog")
            workbook = client.get(f"/review-reports/libraries/{library_dir.name}/latest.xlsx")

            self.assertIn(b"COMPLETE", page.data)
            self.assertIn(b"/review-reports/libraries/", page.data)
            self.assertEqual(workbook.status_code, 200)
            self.assertEqual(workbook.data, b"legacy workbook")
            self.assertIn("vendor.ip_a_latest.xlsx", workbook.headers.get("Content-Disposition", ""))
            page.close()
            workbook.close()

    def test_quick_linked_form_submits_auto_configured_check_inputs(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            version = root / "raw" / "V1"
            lef = version / "LEF" / "top.lef"
            liberty = version / "LIB" / "TT" / "top.lib"
            for path in (lef, liberty):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.touch()
            registry = root / "registry.yml"
            registry.write_text(
                "ips:\n  - id: IP_A\n    library_id: Vendor.IP_A\n    raw_versions:\n"
                f"      - {{id: V1, path: {version}}}\n    checks: {{}}\n", encoding="utf-8")
            app = create_app(registry, root / "output")
            client = app.test_client()

            with patch("lib_guard.workbench.run", return_value=([{
                "execution_status": "COMPLETE", "review_id": "review_test", "summary": {},
            }], {})) as runner:
                response = client.post("/run", data={
                    "id": "IP_A", "library_id": "Vendor.IP_A", "quick_linked_check": "1",
                    "quick_raw_version": "V1", "quick_target_lef": str(lef),
                }, follow_redirects=True)
                self.assertEqual(response.status_code, 200)
                task_url = re.search(rb'data-task-url="([^"]+)"', response.data).group(1).decode()
                task_url = task_url.replace("&amp;", "&")
                for _ in range(100):
                    task = client.get(task_url).get_json()
                    if task["status"] in {"COMPLETE", "FAILED"}:
                        break
                    time.sleep(0.01)

            self.assertEqual(task["status"], "COMPLETE", task)
            submitted = runner.call_args.args[0]["ips"][0]
            self.assertEqual(submitted["raw_version"], "V1")
            self.assertEqual(set(submitted["checks"]), {"macro_index", "lef_liberty_check"})
            self.assertEqual(submitted["checks"]["macro_index"]["root"], str(version.resolve()))
            self.assertEqual(submitted["checks"]["lef_liberty_check"]["lef_file"], str(lef.resolve()))
            self.assertEqual(submitted["checks"]["lef_liberty_check"]["liberty_files"], [str(liberty)])

    def test_run_uses_post_redirect_get_so_refresh_does_not_repeat_check(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            version = root / "raw" / "V1"
            lef = version / "LEF" / "top.lef"
            liberty = version / "LIB" / "TT" / "top.lib"
            for path in (lef, liberty):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.touch()
            registry = root / "registry.yml"
            registry.write_text(
                "ips:\n  - id: IP_A\n    library_id: Vendor.IP_A\n    raw_versions:\n"
                f"      - {{id: V1, path: {version}}}\n    checks: {{}}\n", encoding="utf-8")
            client = create_app(registry, root / "output").test_client()
            with patch("lib_guard.workbench.run", return_value=([{
                "execution_status": "COMPLETE", "review_id": "review_refresh_guard", "summary": {},
            }], {})) as runner:
                response = client.post("/run", data={
                    "id": "IP_A", "library_id": "Vendor.IP_A", "quick_linked_check": "1",
                    "quick_raw_version": "V1", "quick_target_lef": str(lef),
                })
                self.assertEqual(response.status_code, 303)
                self.assertIn("tab=review", response.headers["Location"])
                page = client.get(response.headers["Location"])
                self.assertEqual(page.status_code, 200)
                task_url = re.search(rb'data-task-url="([^"]+)"', page.data).group(1).decode()
                task_url = task_url.replace("&amp;", "&")
                for _ in range(100):
                    task = client.get(task_url).get_json()
                    if task["status"] in {"COMPLETE", "FAILED"}:
                        break
                    time.sleep(0.01)
                self.assertEqual(task["phase"], "已完成")
                self.assertTrue(any("检查完成" in event["message"] for event in task["events"]))
                client.get(response.headers["Location"])
                self.assertEqual(runner.call_count, 1)

    def test_new_queued_task_becomes_latest_without_old_worker_replacing_it(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            task_path = root / "tasks" / "task_new.json"
            latest_path = root / "latest_attempt.json"
            latest_path.write_text(json.dumps({"task_id": "task_old", "status": "RUNNING"}), encoding="utf-8")

            _update_task(task_path, latest_path, {"task_id": "task_new", "status": "QUEUED"})
            _update_task(root / "tasks" / "task_old.json", latest_path,
                         {"task_id": "task_old", "status": "COMPLETE"})

            latest = json.loads(latest_path.read_text(encoding="utf-8"))
            self.assertEqual(latest["task_id"], "task_new")
            self.assertEqual(latest["status"], "QUEUED")

    def test_selected_raw_version_prefills_macro_input_without_saving(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            version = root / "raw" / "V50"
            version.mkdir(parents=True)
            registry = root / "registry.yml"
            original = ("ips:\n  - id: IP_A\n    library_id: Vendor.IP_A\n"
                        f"    raw_versions: [{{id: V50, path: {version}}}]\n"
                        "    checks:\n      macro_index: {report_json: /old/report.json}\n")
            registry.write_text(original, encoding="utf-8")
            response = create_app(registry, root / "output").test_client().get("/?ip=IP_A&tab=review&raw_version=V50")
            self.assertEqual(response.status_code, 200)
            self.assertIn(f'name="macro_root" value="{version}"'.encode(), response.data)
            self.assertIn(b'name="macro_version" value="V50"', response.data)
            self.assertIn("运行自动联动核查".encode(), response.data)
            self.assertLess(response.data.index(b'class="quick-review"'), response.data.index(b'class="identity-details"'))
            self.assertNotIn(b'/old/report.json', response.data)
            self.assertEqual(registry.read_text(encoding="utf-8"), original)
            with patch("lib_guard.workbench.run", side_effect=RuntimeError("captured")) as runner:
                posted = create_app(registry, root / "output").test_client().post("/run", data={
                    "id": "IP_A", "library_id": "Vendor.IP_A", "raw_version": "V50",
                    "checks": "macro_index", "macro_root": str(version), "macro_version": "V50",
                    "macro_library_id": "Vendor.IP_A",
                }, follow_redirects=True)
                self.assertEqual(posted.status_code, 200)
                task_url = re.search(rb'data-task-url="([^"]+)"', posted.data).group(1).decode()
                client = create_app(registry, root / "output").test_client()
                for _ in range(100):
                    payload = client.get(task_url).get_json()
                    if payload["status"] in {"COMPLETE", "FAILED"}:
                        break
                    time.sleep(0.01)
                self.assertEqual(payload["status"], "FAILED")
            spec = runner.call_args.args[0]["ips"][0]["checks"]["macro_index"]
            self.assertEqual(spec["root"], str(version))
            self.assertNotIn("report_json", spec)
            self.assertEqual(registry.read_text(encoding="utf-8"), original)

    def test_registered_versions_offer_lef_and_liberty_file_choices(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            old = root / "raw" / "V01" / "LEF" / "cell.lef"
            new = root / "raw" / "V02" / "LEF" / "cell_new.lef"
            lib = root / "raw" / "V02" / "LIB" / "TT" / "cell.lib.gz"
            for path in (old, new, lib):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.touch()
            registry = root / "registry.yml"
            registry.write_text(
                "ips:\n  - id: IP_A\n    library_id: Vendor.IP_A\n    raw_versions:\n"
                f"      - {{id: V01, path: {old.parents[1]}}}\n"
                f"      - {{id: V02, path: {new.parents[1]}}}\n"
                "    checks: {}\n", encoding="utf-8")
            response = create_app(registry, root / "output").test_client().get(
                "/?ip=IP_A&tab=review&raw_version=V02&base_raw_version=V01")
            self.assertEqual(response.status_code, 200)
            self.assertIn(f'value="{old}"'.encode(), response.data)
            self.assertIn(f'value="{new}"'.encode(), response.data)
            self.assertIn(f'value="{lib}"'.encode(), response.data)
            self.assertIn(b'data-fill-input="lef_old_file"', response.data)
            self.assertIn(b'data-lib-file', response.data)

    def test_duplicate_library_id_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            registry = root / "registry.yml"
            registry.write_text("ips:\n  - {id: A, library_id: shared}\n  - {id: B, library_id: shared}\n", encoding="utf-8")
            response = create_app(registry, root / "output").test_client().get("/")
            self.assertEqual(response.status_code, 400)
            self.assertIn("重复 library_id".encode(), response.data)

    def test_colliding_discovery_ids_cannot_be_registered(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            raw = root / "raw"
            for relative in ("Vendor_A/foo.bar/ip/V01", "Vendor_A/foo/bar/ip/V01"):
                path = raw / relative / "LEF"
                path.mkdir(parents=True)
                (path / "cell.lef").touch()
            registry = root / "registry.yml"
            registry.write_text("ips: []\n", encoding="utf-8")
            response = create_app(registry, root / "output").test_client().post(
                "/register-discovered", data={"raw_root": str(raw), "library_ids": "Vendor_A.foo.bar.ip"})
            self.assertEqual(response.status_code, 400)
            self.assertEqual(__import__("yaml").safe_load(registry.read_text(encoding="utf-8"))["ips"], [])

    def test_invalid_run_does_not_change_saved_registry(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            registry = root / "registry.yml"
            original = "ips:\n  - id: IP_A\n    library_id: Vendor.IP_A\n    checks: {}\n"
            registry.write_text(original, encoding="utf-8")
            response = create_app(registry, root / "output").test_client().post(
                "/run", data={"id": "IP_A", "library_id": "Vendor.IP_A", "checks": "macro_index"})
            self.assertEqual(response.status_code, 400)
            self.assertEqual(registry.read_text(encoding="utf-8"), original)

    def test_new_ip_link_opens_blank_registration_form_without_selecting_first_ip(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            registry = root / "registry.yml"
            registry.write_text("ips:\n  - id: IP_A\n    library_id: vendor.ip_a\n    name: Existing IP\n    checks: {}\n", encoding="utf-8")
            app = create_app(registry, root / "output")

            response = app.test_client().get("/?new=1")

            self.assertEqual(response.status_code, 200)
            self.assertIn("登记 IP".encode(), response.data)
            self.assertNotIn(b'value="Existing IP"', response.data)

    def test_standalone_app_uses_src_qor_assets_and_has_no_catalog_navigation(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            registry = root / "registry.yml"
            registry.write_text("ips:\n  - id: IP_A\n    library_id: vendor.ip_a\n    name: IP A\n    checks: {}\n", encoding="utf-8")
            app = create_app(registry, root / "output")

            self.assertIn("src_qor", str(app.static_folder))
            self.assertNotIn("src/lib_guard/web/static", str(app.static_folder))
            page = app.test_client().get("/")
            self.assertEqual(page.status_code, 200)
            self.assertNotIn("返回库目录".encode(), page.data)
            self.assertIn(b"data-workbench-tab", page.data)
            self.assertIn(b"/static/workbench.css", page.data)

            with app.test_client().get("/static/workbench.css") as stylesheet:
                self.assertEqual(stylesheet.status_code, 200)
                self.assertIn(b".app-shell", stylesheet.data)
                self.assertIn(b".ip-item[hidden]", stylesheet.data)

    def test_get_lists_registered_ip_and_latest_history(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            registry = root / "registry.yml"
            registry.write_text("ips:\n  - id: IP_A\n    library_id: vendor.ip_a\n    name: IP A\n    checks: {}\n", encoding="utf-8")
            app = create_app(registry, root / "output")

            response = app.test_client().get("/")

            self.assertEqual(response.status_code, 200)
            self.assertIn(b"IP A", response.data)
            self.assertIn(b"formal_nl", response.data)
            self.assertIn(b"macro_index", response.data)
            self.assertIn("库与版本".encode(), response.data)
            self.assertIn("RAW 发现".encode(), response.data)
            self.assertIn(b"data-tab-group=\"main\"", response.data)
            self.assertIn(b"data-workbench-panel=\"config\"", response.data)
            self.assertIn(b"data-workbench-panel=\"history\"", response.data)

    def test_catalog_distinguishes_latest_attempt_from_latest_success(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            registry = root / "registry.yml"
            registry.write_text(
                "ips:\n  - {id: IP_A, library_id: vendor.ip_a, name: IP A, vendor: Vendor_A, checks: {}}\n",
                encoding="utf-8")
            output = root / "output"
            from lib_guard.review_runner import _library_dir
            library_dir = output / "libraries" / _library_dir("vendor.ip_a")
            library_dir.mkdir(parents=True)
            (library_dir / "latest.json").write_text(
                '{"review_id":"review_good","execution_status":"COMPLETE"}', encoding="utf-8")
            (library_dir / "latest_attempt.json").write_text(
                '{"task_id":"task_123","status":"FAILED","execution_status":"FAILED"}', encoding="utf-8")

            response = create_app(registry, output).test_client().get("/?ip=IP_A&tab=catalog")

            self.assertEqual(response.status_code, 200)
            self.assertIn("最近尝试".encode(), response.data)
            self.assertIn("最近完整报告".encode(), response.data)
            self.assertIn(b"task_123", response.data)
            self.assertIn(b"review_good", response.data)

    def test_task_status_and_check_conclusion_are_labeled_separately(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            registry = root / "registry.yml"
            registry.write_text(
                "ips:\n  - {id: IP_A, library_id: vendor.ip_a, name: IP A, checks: {}}\n",
                encoding="utf-8")
            from lib_guard.review_runner import _library_dir
            library_dir = root / "output" / "libraries" / _library_dir("vendor.ip_a")
            library_dir.mkdir(parents=True)
            (library_dir / "latest_attempt.json").write_text(
                json.dumps({"task_id": "task_incomplete", "library_id": "vendor.ip_a",
                            "status": "COMPLETE", "execution_status": "COMPLETE",
                            "quality_status": "REVIEW_REQUIRED",
                            "worker_session": workbench._WORKBENCH_SESSION_ID}), encoding="utf-8")

            response = create_app(registry, root / "output").test_client().get("/?ip=IP_A&tab=review")

            self.assertEqual(response.status_code, 200)
            self.assertIn("运行状态".encode(), response.data)
            self.assertIn("任务执行：COMPLETE；质量判断：存在待核实项".encode(), response.data)
            self.assertIn("不等同正式发布放行".encode(), response.data)
            self.assertNotIn("最近一次尝试".encode(), response.data)

    def test_task_window_is_visible_on_other_workbench_tabs_with_phase_and_dynamics(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            registry = root / "registry.yml"
            registry.write_text(
                "ips:\n  - {id: IP_A, library_id: vendor.ip_a, name: IP A, checks: {}}\n",
                encoding="utf-8")
            from lib_guard.review_runner import _library_dir
            library_dir = root / "output" / "libraries" / _library_dir("vendor.ip_a")
            library_dir.mkdir(parents=True)
            task = {
                "task_id": "task_" + "a" * 32, "library_id": "vendor.ip_a", "ip_id": "IP_A",
                "status": "RUNNING", "execution_status": "PENDING", "phase": "执行检查",
                "worker_session": workbench._WORKBENCH_SESSION_ID,
                "progress_message": "正在执行：Macro / View 文件索引",
                "submitted_at": "2026-10-24T10:00:00+00:00", "started_at": "2026-10-24T10:00:01+00:00",
                "requested_checks": ["macro_index"],
                "events": [{"at": "2026-10-24T10:00:01+00:00", "message": "开始执行：Macro / View 文件索引"}],
            }
            (library_dir / "latest_attempt.json").write_text(json.dumps(task), encoding="utf-8")
            response = create_app(registry, root / "output").test_client().get("/?ip=IP_A&tab=catalog")

            self.assertEqual(response.status_code, 200)
            self.assertIn(b'data-runtime-window', response.data)
            self.assertIn(b'data-task-stage', response.data)
            self.assertIn("执行检查".encode(), response.data)
            self.assertIn("运行动态".encode(), response.data)
            self.assertIn("正在执行：Macro / View 文件索引".encode(), response.data)
            self.assertIn("data-task-started-at".encode(), response.data)

    def test_task_window_shows_legacy_failure_without_empty_dynamics(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            registry = root / "registry.yml"
            registry.write_text("ips:\n  - {id: IP_A, library_id: vendor.ip_a, name: IP A, checks: {}}\n", encoding="utf-8")
            from lib_guard.review_runner import _library_dir
            library_dir = root / "output" / "libraries" / _library_dir("vendor.ip_a")
            library_dir.mkdir(parents=True)
            (library_dir / "latest_attempt.json").write_text(json.dumps({
                "task_id": "task_legacy", "library_id": "vendor.ip_a", "ip_id": "IP_A",
                "status": "FAILED", "execution_status": "FAILED",
                "error": "导出 Excel 需要 XlsxWriter",
                "submitted_at": "2026-10-24T10:00:00+00:00",
                "finished_at": "2026-10-24T10:00:02+00:00",
            }), encoding="utf-8")

            response = create_app(registry, root / "output").test_client().get("/?ip=IP_A&tab=catalog")

            self.assertEqual(response.status_code, 200)
            self.assertIn("阶段：已失败".encode(), response.data)
            self.assertIn("导出 Excel 需要 XlsxWriter".encode(), response.data)
            self.assertNotIn("暂无运行动态".encode(), response.data)

    def test_task_status_api_reports_real_phase_and_event_updates(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            registry = root / "registry.yml"
            registry.write_text("ips: []\n", encoding="utf-8")
            from lib_guard.review_runner import _library_dir
            library_dir = root / "output" / "libraries" / _library_dir("vendor.ip_a")
            task_id = "task_" + "b" * 32
            task_path = library_dir / "tasks" / f"{task_id}.json"
            task_path.parent.mkdir(parents=True)
            task_path.write_text(json.dumps({
                "task_id": task_id, "library_id": "vendor.ip_a", "status": "RUNNING",
                "execution_status": "PENDING", "phase": "执行检查",
                "worker_session": workbench._WORKBENCH_SESSION_ID,
                "progress_message": "正在执行：LEF 双文件核查",
                "events": [{"at": "2026-10-24T10:00:01+00:00", "message": "开始执行：LEF 双文件核查"}],
            }), encoding="utf-8")

            response = create_app(registry, root / "output").test_client().get(
                f"/tasks/{task_id}?library_id=vendor.ip_a")

            self.assertEqual(response.status_code, 200)
            payload = response.get_json()
            self.assertEqual(payload["phase"], "执行检查")
            self.assertEqual(payload["progress_message"], "正在执行：LEF 双文件核查")
            self.assertEqual(payload["events"][0]["message"], "开始执行：LEF 双文件核查")

    def test_sidebar_exposes_vendor_library_raw_and_formal_versions_with_filters(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            registry = root / "registry.yml"
            registry.write_text(
                "ips:\n  - id: PHY_A\n    library_id: Vendor_A.phy_ip\n    name: PHY IP\n"
                "    vendor: Vendor_A\n    middle_path: physical\n    library_name: phy_ip\n"
                "    raw_root: /raw/Vendor_A/physical/phy_ip\n"
                "    raw_versions:\n      - id: V01\n        path: /raw/V01\n"
                "      - id: V02\n        path: /raw/V02\n"
                "    formal_nl_root: /release/NL\n"
                "    formal_nl_stages: [lib_NL2.4_2, lib_NL2.5_3]\n    checks: {}\n",
                encoding="utf-8")
            app = create_app(registry, root / "output")

            response = app.test_client().get("/?ip=PHY_A")

            self.assertEqual(response.status_code, 200)
            for expected in ("Vendor_A", "phy_ip", "V01", "V02", "lib_NL2.4_2", "lib_NL2.5_3",
                             "全部", "RAW", "正式 NL", "筛选 Vendor"):
                self.assertIn(expected.encode(), response.data)
            self.assertIn(b"data-sidebar-scope", response.data)
            self.assertIn(b"data-vendor-filter", response.data)

    def test_sidebar_collapses_multiple_versions_and_shows_naturally_latest(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            registry = root / "registry.yml"
            registry.write_text(
                "ips:\n  - id: PHY_A\n    library_id: Vendor_A.phy_ip\n    name: PHY IP\n"
                "    vendor: Vendor_A\n    library_name: phy_ip\n    raw_versions:\n"
                "      - id: V2\n        path: /raw/V2\n"
                "      - id: V10\n        path: /raw/V10\n"
                "      - id: V3\n        path: /raw/V3\n"
                "    formal_nl_root: /release/NL\n"
                "    formal_nl_stages: [lib_NL2.5_3, lib_NL2.10_1]\n    checks: {}\n",
                encoding="utf-8")
            app = create_app(registry, root / "output")

            response = app.test_client().get("/?ip=PHY_A")
            html = response.get_data(as_text=True)

            self.assertEqual(response.status_code, 200)
            self.assertIn("排序最新版本：V10（共 3）".encode(), response.data)
            self.assertIn("排序最新阶段：lib_NL2.10_1（共 2）".encode(), response.data)
            self.assertIn('class="sidebar-version-details"', html)
            self.assertNotIn('<details class="sidebar-version-details" open', html)
            self.assertIn("V2".encode(), response.data)
            self.assertIn("V3".encode(), response.data)

    def test_sidebar_keeps_single_raw_and_formal_version_directly_visible(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            registry = root / "registry.yml"
            registry.write_text(
                "ips:\n  - id: PHY_A\n    library_id: Vendor_A.phy_ip\n    name: PHY IP\n"
                "    raw_versions: [{id: V01, path: /raw/V01}]\n"
                "    formal_nl_stages: [lib_NL2.5_3]\n    checks: {}\n",
                encoding="utf-8")
            app = create_app(registry, root / "output")

            response = app.test_client().get("/?ip=PHY_A")
            html = response.get_data(as_text=True)

            self.assertEqual(response.status_code, 200)
            self.assertIn('title="/raw/V01">V01</a>', html)
            self.assertIn(">lib_NL2.5_3</a>", html)
            self.assertNotIn("sidebar-version-details", html)

    def test_simulation_registry_warns_that_data_is_not_a_real_ip_delivery(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            registry = root / "registry.yml"
            registry.write_text("environment: SIMULATION\nips: []\n", encoding="utf-8")
            app = create_app(registry, root / "output")

            response = app.test_client().get("/")

            self.assertIn("模拟数据 · 不可用于 EDA 或发布".encode(), response.data)

    def test_save_persists_ip_and_selected_check_inputs(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            registry = root / "registry.yml"
            registry.write_text("ips: []\n", encoding="utf-8")
            report = root / "macro.json"
            report.write_text(json.dumps({"status": "COMPLETE", "macro_index": {"macros": {}}}), encoding="utf-8")
            app = create_app(registry, root / "output")

            response = app.test_client().post("/save", data={
                "id": "IP_A", "library_id": "vendor.ip_a", "name": "IP A", "raw_version": "V2",
                "checks": ["macro_index"], "macro_report_json": str(report),
            })

            self.assertEqual(response.status_code, 200)
            self.assertIn(b"IP A", response.data)
            saved = __import__("yaml").safe_load(registry.read_text(encoding="utf-8"))
            self.assertEqual(saved["ips"][0]["checks"]["macro_index"]["report_json"], str(report))

    def test_run_executes_existing_runner_and_downloads_per_ip_workbook(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            report = root / "macro.json"
            report.write_text(json.dumps({"status": "COMPLETE", "macro_index": {
                "baseline": {"macro_count": 1, "status": "LEF_PARSED"},
                "macros": {"MACRO_A": {}}, "unmatched_files": [], "unmatched_objects": {},
            }}), encoding="utf-8")
            registry = root / "registry.yml"
            registry.write_text("ips: []\n", encoding="utf-8")
            app = create_app(registry, root / "output")
            client = app.test_client()
            client.post("/save", data={"id": "IP_A", "library_id": "vendor.ip_a", "name": "IP A",
                                       "checks": ["macro_index"], "macro_report_json": str(report),
                                       "publish_latest": "on"})

            with patch("lib_guard.review_runner.export_review_excel",
                       side_effect=lambda model, path, scope_note: Path(path).write_bytes(b"xlsx")):
                response = client.post("/run", data={"id": "IP_A", "library_id": "vendor.ip_a", "name": "IP A",
                                                   "checks": ["macro_index"], "macro_report_json": str(report),
                                                   "publish_latest": "on"}, follow_redirects=True)

                self.assertEqual(response.status_code, 200)
                task_match = re.search(rb'data-task-url="([^"]+)"', response.data)
                self.assertIsNotNone(task_match)
                task_url = task_match.group(1).decode().replace("&amp;", "&")
                for _ in range(100):
                    status = client.get(task_url)
                    payload = status.get_json()
                    if payload["status"] in {"COMPLETE", "FAILED"}:
                        break
                    time.sleep(0.01)
            self.assertEqual(payload["status"], "COMPLETE", payload)
            result = next((root / "output" / "libraries").rglob("review_result.json"))
            review_id = json.loads(result.read_text(encoding="utf-8"))["review_id"]
            download = client.get("/download", query_string={"library_id": "vendor.ip_a", "review_id": review_id})
            self.assertEqual(download.status_code, 200)
            self.assertEqual(download.mimetype, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            download.close()

    def test_failed_attempt_is_visible_without_replacing_last_success(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            registry = root / "registry.yml"
            registry.write_text("ips:\n  - {id: IP_A, library_id: vendor.ip_a, checks: {}}\n", encoding="utf-8")
            output = root / "output"
            from lib_guard.review_runner import _library_dir
            library_dir = output / "libraries" / _library_dir("vendor.ip_a")
            library_dir.mkdir(parents=True)
            success_pointer = '{"review_id":"review_old","execution_status":"COMPLETE"}\n'
            (library_dir / "latest.json").write_text(success_pointer, encoding="utf-8")
            app = create_app(registry, output)
            client = app.test_client()
            with patch("lib_guard.workbench.run", side_effect=RuntimeError("controlled failure")):
                response = client.post("/run", data={
                    "id": "IP_A", "library_id": "vendor.ip_a", "checks": ["macro_index"],
                    "macro_report_json": str(root / "existing.json"),
                }, follow_redirects=True)
                task_match = re.search(rb'data-task-url="([^"]+)"', response.data)
                self.assertIsNotNone(task_match)
                task_url = task_match.group(1).decode().replace("&amp;", "&")
                task_id = re.search(r"task_([0-9a-f]{32})", task_url).group(0)
                for _ in range(100):
                    payload = client.get(task_url).get_json()
                    if payload["status"] in {"COMPLETE", "FAILED"}:
                        break
                    time.sleep(0.01)
            self.assertEqual(payload["status"], "FAILED")
            self.assertEqual(payload["error"], "controlled failure")
            self.assertEqual((library_dir / "latest.json").read_text(encoding="utf-8"), success_pointer)
            latest_attempt = json.loads((library_dir / "latest_attempt.json").read_text(encoding="utf-8"))
            self.assertEqual(latest_attempt["task_id"], task_id)
            self.assertEqual(latest_attempt["status"], "FAILED")

    def test_two_review_jobs_can_run_concurrently(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            registry = root / "registry.yml"
            registry.write_text(
                "ips:\n  - {id: IP_A, library_id: vendor.ip_a, checks: {}}\n"
                "  - {id: IP_B, library_id: vendor.ip_b, checks: {}}\n", encoding="utf-8")
            client = create_app(registry, root / "output").test_client()
            barrier = Barrier(2)

            def concurrent_run(config, output):
                barrier.wait(timeout=3)
                entry = config["ips"][0]
                return ([{"review_id": f"review_{entry['id']}", "execution_status": "COMPLETE", "summary": {}}], {})

            task_urls = []
            with patch("lib_guard.workbench.run", side_effect=concurrent_run):
                for ip_id, library_id in (("IP_A", "vendor.ip_a"), ("IP_B", "vendor.ip_b")):
                    response = client.post("/run", data={
                        "id": ip_id, "library_id": library_id, "checks": ["macro_index"],
                        "macro_report_json": str(root / "existing.json"),
                    }, follow_redirects=True)
                    self.assertEqual(response.status_code, 200)
                    task_urls.append(re.search(rb'data-task-url="([^"]+)"', response.data).group(1).decode())
                tasks = []
                for task_url in task_urls:
                    for _ in range(100):
                        task = client.get(task_url).get_json()
                        if task["status"] in {"COMPLETE", "FAILED"}:
                            break
                        time.sleep(0.01)
                    tasks.append(task)
            self.assertEqual([task["status"] for task in tasks], ["COMPLETE", "COMPLETE"])

    def test_same_ip_cannot_run_concurrent_jobs_that_race_latest_pointer(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            registry = root / "registry.yml"
            registry.write_text("ips:\n  - {id: IP_A, library_id: vendor.ip_a, checks: {}}\n", encoding="utf-8")
            client = create_app(registry, root / "output").test_client()
            started = __import__("threading").Event()
            release = __import__("threading").Event()

            def slow_run(config, output):
                started.set()
                release.wait(timeout=3)
                return ([{"review_id": "review_one", "execution_status": "COMPLETE", "summary": {}}], {})

            with patch("lib_guard.workbench.run", side_effect=slow_run):
                first = client.post("/run", data={
                    "id": "IP_A", "library_id": "vendor.ip_a", "checks": ["macro_index"],
                    "macro_report_json": str(root / "existing.json"), "publish_latest": "on",
                }, follow_redirects=True)
                self.assertEqual(first.status_code, 200)
                self.assertTrue(started.wait(timeout=1))
                second = client.post("/run", data={
                    "id": "IP_A", "library_id": "vendor.ip_a", "checks": ["macro_index"],
                    "macro_report_json": str(root / "existing.json"), "publish_latest": "on",
                })
                release.set()
                task_url = re.search(rb'data-task-url="([^"]+)"', first.data).group(1).decode()
                for _ in range(100):
                    task = client.get(task_url).get_json()
                    if task["status"] in {"COMPLETE", "FAILED"}:
                        break
                    time.sleep(0.01)

            self.assertEqual(second.status_code, 409)
            self.assertIn("该 IP 已有检查任务正在".encode(), second.data)

    def test_review_queue_rejects_submission_when_bounded_capacity_is_full(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            registry = root / "registry.yml"
            registry.write_text("ips: []\n", encoding="utf-8")
            client = create_app(registry, root / "output").test_client()
            with patch("lib_guard.workbench._REVIEW_TASK_SLOTS.acquire", return_value=False):
                response = client.post("/run", data={
                    "id": "IP_A", "library_id": "vendor.ip_a", "checks": ["macro_index"],
                    "macro_report_json": str(root / "existing.json"),
                })
            self.assertEqual(response.status_code, 429)
            self.assertIn("队列已满".encode(), response.data)
            self.assertFalse((root / "output" / "libraries").exists())

    def test_task_from_previous_workbench_process_becomes_interrupted(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            registry = root / "registry.yml"
            registry.write_text("ips: []\n", encoding="utf-8")
            output = root / "output"
            from lib_guard.review_runner import _library_dir
            library_dir = output / "libraries" / _library_dir("vendor.ip_a")
            task_id = "task_" + "a" * 32
            task_path = library_dir / "tasks" / f"{task_id}.json"
            old_task = {"task_id": task_id, "library_id": "vendor.ip_a", "status": "RUNNING",
                        "execution_status": "PENDING", "worker_session": "previous-process"}
            task_path.parent.mkdir(parents=True)
            task_path.write_text(json.dumps(old_task), encoding="utf-8")
            (library_dir / "latest_attempt.json").write_text(json.dumps(old_task), encoding="utf-8")

            response = create_app(registry, output).test_client().get(
                f"/tasks/{task_id}?library_id=vendor.ip_a")

            self.assertEqual(response.status_code, 200)
            payload = response.get_json()
            self.assertEqual(payload["status"], "INTERRUPTED")
            self.assertIn("进程重启", payload["error"])
            self.assertEqual(json.loads(task_path.read_text(encoding="utf-8"))["status"], "INTERRUPTED")

    def test_unknown_ip_cannot_download_artifact(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            registry = root / "registry.yml"
            registry.write_text("ips: []\n", encoding="utf-8")
            app = create_app(registry, root / "output")

            response = app.test_client().get("/download?library_id=outside&review_id=review_20260101T000000Z_abcd1234")

            self.assertEqual(response.status_code, 404)

    def test_missing_path_is_reported_and_entered_ip_config_is_preserved(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            registry = root / "registry.yml"
            registry.write_text("ips: []\n", encoding="utf-8")
            app = create_app(registry, root / "output")

            response = app.test_client().post("/run", data={
                "id": "IP_A", "library_id": "vendor.ip_a", "name": "IP A", "checks": ["macro_index"]
            })

            self.assertEqual(response.status_code, 400)
            self.assertIn("缺少所需路径".encode(), response.data)
            saved = __import__("yaml").safe_load(registry.read_text(encoding="utf-8"))
            self.assertEqual(saved["ips"], [])

    def test_browser_cannot_save_unsupported_governance_check(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            registry = root / "registry.yml"
            registry.write_text("ips: []\n", encoding="utf-8")
            app = create_app(registry, root / "output")

            response = app.test_client().post("/save", data={
                "id": "IP_A", "library_id": "vendor.ip_a", "checks": ["release_gate"]
            })

            self.assertEqual(response.status_code, 400)
            self.assertIn("不支持的检查名".encode(), response.data)
            self.assertEqual(__import__("yaml").safe_load(registry.read_text(encoding="utf-8"))["ips"], [])

    def test_raw_discovery_previews_vendor_library_versions_without_registering(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            raw = root / "raw"
            version = raw / "Vendor_A" / "phy_ip" / "V01" / "LEF"
            version.mkdir(parents=True)
            (version / "phy.lef").touch()
            registry = root / "registry.yml"
            registry.write_text("ips: []\n", encoding="utf-8")
            app = create_app(registry, root / "output")

            response = app.test_client().post("/discover", data={"raw_root": str(raw)})

            self.assertEqual(response.status_code, 200)
            self.assertIn(b"Vendor_A", response.data)
            self.assertIn(b"phy_ip", response.data)
            self.assertIn(b"V01", response.data)
            self.assertIn("分组路径".encode(), response.data)
            self.assertIn(b"library_discovery.json", response.data)
            self.assertEqual(__import__("yaml").safe_load(registry.read_text(encoding="utf-8"))["ips"], [])
            self.assertTrue((root / "output" / "discovery" / "library_discovery.json").exists())
            self.assertFalse((root / "output" / "discovery" / "library.list").exists())
            for artifact in ("library_discovery.json", "library_discovery.html"):
                downloaded = app.test_client().get(f"/discovery-artifact/{artifact}")
                self.assertEqual(downloaded.status_code, 200)
                downloaded.close()
                if artifact.endswith(".html"):
                    self.assertFalse((root / "output" / "discovery" / "library.list").exists())
            listed = app.test_client().get("/discovery-artifact/library.list")
            self.assertEqual(listed.status_code, 200)
            listed.close()

    def test_register_discovered_library_persists_all_versions_and_refresh_keeps_checks(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            raw = root / "raw"
            for version_name in ("V01", "V02"):
                view = raw / "Vendor_A" / "phy_ip" / version_name / "LEF"
                view.mkdir(parents=True)
                (view / "phy.lef").touch()
            registry = root / "registry.yml"
            registry.write_text("ips: []\n", encoding="utf-8")
            app = create_app(registry, root / "output")
            client = app.test_client()

            registered = client.post("/register-discovered", data={
                "raw_root": str(raw), "library_ids": ["Vendor_A.phy_ip"]
            })

            self.assertEqual(registered.status_code, 200)
            data = __import__("yaml").safe_load(registry.read_text(encoding="utf-8"))
            entry = data["ips"][0]
            self.assertEqual(entry["vendor"], "Vendor_A")
            self.assertEqual(entry["middle_path"], "")
            self.assertEqual([item["id"] for item in entry["raw_versions"]], ["V01", "V02"])
            entry["checks"] = {"macro_index": {"root": "/kept/input"}}
            registry.write_text(__import__("yaml").safe_dump(data, sort_keys=False), encoding="utf-8")

            newer = raw / "Vendor_A" / "phy_ip" / "V03" / "GDS"
            newer.mkdir(parents=True)
            (newer / "phy.gds").touch()
            refreshed = client.post("/register-discovered", data={
                "raw_root": str(raw), "library_ids": ["Vendor_A.phy_ip"]
            })

            self.assertEqual(refreshed.status_code, 200)
            updated = __import__("yaml").safe_load(registry.read_text(encoding="utf-8"))["ips"][0]
            self.assertEqual([item["id"] for item in updated["raw_versions"]], ["V01", "V02", "V03"])
            self.assertEqual(updated["checks"]["macro_index"]["root"], "/kept/input")

    def test_discovery_supports_single_row_registration_and_catalog_edit_remove_actions(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            raw = root / "raw"
            version = raw / "Vendor_A" / "phy_ip" / "V01" / "LEF"
            version.mkdir(parents=True)
            (version / "phy.lef").touch()
            lib = raw / "Vendor_A" / "phy_ip" / "V01" / "LIB" / "TT" / "phy.lib"
            lib.parent.mkdir(parents=True)
            lib.touch()
            registry = root / "registry.yml"
            registry.write_text("ips: []\n", encoding="utf-8")
            client = create_app(registry, root / "output").test_client()

            discovered = client.post("/discover", data={"raw_root": str(raw)})
            self.assertEqual(discovered.status_code, 200)
            self.assertIn("未登记".encode(), discovered.data)
            self.assertIn(b'name="register_one"', discovered.data)
            self.assertIn("全选当前结果".encode(), discovered.data)
            self.assertNotIn("库候选".encode(), discovered.data)

            registered = client.post("/register-discovered", data={
                "raw_root": str(raw), "register_one": "Vendor_A.phy_ip"
            })
            self.assertEqual(registered.status_code, 200)
            data = __import__("yaml").safe_load(registry.read_text(encoding="utf-8"))
            self.assertEqual([entry["library_id"] for entry in data["ips"]], ["Vendor_A.phy_ip"])
            entry_id = data["ips"][0]["id"]
            refreshed_view = client.post("/discover", data={"raw_root": str(raw)})
            self.assertIn("已登记".encode(), refreshed_view.data)
            self.assertIn("更新登记".encode(), refreshed_view.data)
            catalog = client.get("/")
            self.assertIn("修改登记".encode(), catalog.data)
            self.assertIn("移除登记".encode(), catalog.data)
            review = client.get(f"/?ip={entry_id}&tab=review&raw_version=V01")
            self.assertIn(b"data-check-select-all", review.data)
            self.assertIn(b"data-lib-search", review.data)

            edited = client.post("/save", data={
                "id": entry_id, "library_id": "Vendor_A.phy_ip", "name": "renamed display",
                "vendor": "Vendor_A", "middle_path": "group/subgroup", "library_name": "phy_ip",
            })
            self.assertEqual(edited.status_code, 200)
            saved = __import__("yaml").safe_load(registry.read_text(encoding="utf-8"))["ips"][0]
            self.assertEqual(saved["name"], "renamed display")
            self.assertEqual(saved["middle_path"], "group/subgroup")
            self.assertEqual(saved["raw_versions"][0]["path"], str(raw / "Vendor_A" / "phy_ip" / "V01"))

            history = root / "output" / "libraries" / "Vendor_A.phy_ip" / "runs" / "old"
            history.mkdir(parents=True)
            marker = history / "review_result.json"
            marker.write_text("{}", encoding="utf-8")
            removed = client.post("/unregister", data={"id": entry_id})
            self.assertEqual(removed.status_code, 200)
            self.assertEqual(__import__("yaml").safe_load(registry.read_text(encoding="utf-8"))["ips"], [])
            self.assertTrue((raw / "Vendor_A" / "phy_ip" / "V01" / "LEF" / "phy.lef").exists())
            self.assertTrue(marker.exists())

    def test_discovery_filter_and_multiselect_controls_are_scoped(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            raw = root / "raw"
            version = raw / "Vendor_A" / "phy_ip" / "V01" / "LEF"
            version.mkdir(parents=True)
            (version / "phy.lef").touch()
            registry = root / "registry.yml"
            registry.write_text("ips: []\n", encoding="utf-8")
            client = create_app(registry, root / "output").test_client()
            response = client.post("/discover", data={"raw_root": str(raw)})
            self.assertEqual(response.status_code, 200)
            for control in (b"data-discovery-search", b"data-discovery-vendor",
                            b"data-discovery-view", b"data-discovery-state",
                            b"data-select-visible", b"data-clear-visible"):
                self.assertIn(control, response.data)
            script = client.get("/static/workbench.js")
            self.assertIn(b"data-select-visible", script.data)
            self.assertIn(b"data-lib-search", script.data)
            script.close()

    def test_register_discovered_keeps_middle_path_as_catalog_metadata(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            raw = root / "raw"
            view = raw / "Vendor_A" / "memory" / "sram" / "phy_ip" / "20261024" / "LEF"
            view.mkdir(parents=True)
            (view / "phy.lef").touch()
            registry = root / "registry.yml"
            registry.write_text("ips: []\n", encoding="utf-8")
            app = create_app(registry, root / "output")

            response = app.test_client().post("/register-discovered", data={
                "raw_root": str(raw), "library_ids": ["Vendor_A.memory.sram.phy_ip"]
            })

            self.assertEqual(response.status_code, 200)
            entry = __import__("yaml").safe_load(registry.read_text(encoding="utf-8"))["ips"][0]
            self.assertEqual(entry["vendor"], "Vendor_A")
            self.assertEqual(entry["middle_path"], "memory/sram")
            self.assertEqual(entry["library_name"], "phy_ip")

    def test_raw_discovery_rejects_invalid_path(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            registry = root / "registry.yml"
            registry.write_text("ips: []\n", encoding="utf-8")
            app = create_app(registry, root / "output")

            response = app.test_client().post("/discover", data={"raw_root": str(root / "missing")})

            self.assertEqual(response.status_code, 400)
            self.assertIn("RAW 根目录".encode(), response.data)

    def test_relative_raw_root_resolves_from_registry_directory(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            raw = root / "raw-root" / "Vendor_A" / "phy_ip" / "V01" / "LEF"
            raw.mkdir(parents=True)
            (raw / "phy.lef").touch()
            registry = root / "config" / "registry.yml"
            registry.parent.mkdir()
            registry.write_text("raw_root: ../raw-root\nips: []\n", encoding="utf-8")
            app = create_app(registry, root / "output")

            page = app.test_client().get("/?tab=discover")
            discovered = app.test_client().post("/discover", data={"raw_root": "../raw-root"})

            self.assertIn(str(root / "raw-root").encode(), page.data)
            self.assertEqual(discovered.status_code, 200)
            self.assertIn(b"Vendor_A.phy_ip", discovered.data)

    def test_formal_nl_tab_is_available_and_restores_saved_root(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            registry = root / "registry.yml"
            formal = root / "formal"
            registry.write_text(
                f"ips:\n  - id: IP_A\n    library_id: Vendor_A.IP_A\n    name: IP A\n"
                f"    library_name: IP_A\n    raw_root: {root / 'raw' / 'Vendor_A' / 'IP_A'}\n"
                f"    formal_nl_root: {formal}\n    checks: {{}}\n", encoding="utf-8")
            app = create_app(registry, root / "output")

            response = app.test_client().get("/?id=IP_A&tab=formal-nl")

            self.assertEqual(response.status_code, 200)
            self.assertIn("正式 NL".encode(), response.data)
            self.assertIn("只读路径盘点".encode(), response.data)
            self.assertIn(str(formal).encode(), response.data)

    def test_saving_check_configuration_preserves_formal_nl_root(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            registry = root / "registry.yml"
            formal = root / "formal"
            registry.write_text(
                f"ips:\n  - id: IP_A\n    library_id: Vendor_A.IP_A\n    name: IP A\n"
                f"    formal_nl_root: {formal}\n    checks: {{}}\n", encoding="utf-8")
            client = create_app(registry, root / "output").test_client()

            saved = client.post("/save", data={"id": "IP_A", "library_id": "Vendor_A.IP_A", "name": "IP A"})

            self.assertEqual(saved.status_code, 200)
            persisted = __import__("yaml").safe_load(registry.read_text(encoding="utf-8"))
            self.assertEqual(persisted["ips"][0]["formal_nl_root"], str(formal))

    def test_formal_nl_scan_shows_stage_views_and_downloads_reports_without_writing_inputs(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            raw_root = root / "raw" / "Vendor_A" / "IP_A"
            for version in ("V01", "V02"):
                for view, filename in (("LEF", "macro.lef"), ("LIB/NLDM", "macro_tt.lib"),
                                       ("DB", "macro_tt.db")):
                    source = raw_root / version / view / filename
                    source.parent.mkdir(parents=True, exist_ok=True)
                    source.write_text("inventory marker\n", encoding="utf-8")
            formal_root = root / "formal"
            symlinks = []
            for stage in ("lib_NL2.4_2", "lib_NL2.5_3"):
                ip_root = formal_root / stage / "IP"
                ip_root.mkdir(parents=True)
                link = ip_root / "IP_A"
                link.symlink_to(raw_root, target_is_directory=True)
                symlinks.append((link, link.resolve()))
            registry = root / "registry.yml"
            registry.write_text(
                f"ips:\n  - id: IP_A\n    library_id: Vendor_A.IP_A\n    name: IP A\n"
                f"    library_name: IP_A\n    raw_root: {raw_root}\n    checks: {{}}\n", encoding="utf-8")
            output = root / "output"
            app = create_app(registry, output)
            client = app.test_client()

            response = client.post("/formal-nl", data={"id": "IP_A", "formal_nl_root": str(formal_root)})

            self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
            self.assertIn("lib_NL2.5_3".encode(), response.data)
            self.assertIn("lib_NL2.4_2".encode(), response.data)
            self.assertIn("liberty".encode(), response.data)
            self.assertIn("LEF".encode(), response.data)
            self.assertIn("DB".encode(), response.data)
            self.assertIn("TT".encode(), response.data)
            self.assertIn("目录名排序靠前".encode(), response.data)
            self.assertIn("目录名排序第二".encode(), response.data)
            self.assertIn(str(formal_root / "lib_NL2.5_3" / "IP" / "IP_A").encode(), response.data)
            self.assertIn(b"lef 2", response.data)
            self.assertIn(b"formal-report/json", response.data)
            saved = __import__("yaml").safe_load(registry.read_text(encoding="utf-8"))
            self.assertEqual(saved["ips"][0]["formal_nl_root"], str(formal_root))
            self.assertEqual(saved["ips"][0]["formal_nl_stages"], ["lib_NL2.5_3", "lib_NL2.4_2"])
            self.assertIn(b'class="sidebar-version formal-version"', response.data)
            latest_path = next(output.glob("formal_nl/*/latest.json"))
            latest = json.loads(latest_path.read_text(encoding="utf-8"))
            browse_pointer = latest_path.read_bytes()
            report_path = Path(latest["report_json"])
            self.assertTrue(report_path.is_file())
            self.assertTrue(report_path.is_relative_to(output))
            report_json = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual(report_json["inventories"]["lib_NL2.5_3"]["view_counts"]["lef"], 2)
            self.assertEqual(latest["discovery_status"], "DISCOVERED")
            self.assertEqual(latest["report_status"], "INCOMPLETE")
            self.assertFalse((latest_path.parent / "latest_check.json").exists())
            stage_response = client.post("/formal-nl", data={"id": "IP_A", "formal_nl_root": str(formal_root),
                                                             "formal_stage": "lib_NL2.5_3"})
            self.assertEqual(stage_response.status_code, 200, stage_response.get_data(as_text=True))
            self.assertEqual(latest_path.read_bytes(), browse_pointer)
            stage_reports = [json.loads(path.read_text(encoding="utf-8"))
                             for path in (latest_path.parent / "runs").glob("*/formal_nl.json")]
            stage_report = next(item for item in stage_reports if item["formal_scope"] == "SINGLE_STAGE")
            self.assertEqual(stage_report["report_status"], "COMPLETE")
            check_pointer = latest_path.parent / "latest_check.json"
            self.assertEqual(check_pointer.exists(), stage_report["report_status"] == "COMPLETE")
            review = client.get("/?ip=IP_A&tab=review&formal_stage=lib_NL2.5_3")
            self.assertEqual(review.status_code, 200)
            self.assertIn(b'name="formal_stage" value="lib_NL2.5_3"', review.data)
            self.assertIn(json.loads(check_pointer.read_text(encoding="utf-8"))["report_json"].encode(), review.data)
            for link, target in symlinks:
                self.assertTrue(link.is_symlink())
                self.assertEqual(link.resolve(), target)
            with client.get(f"/formal-report/json?id=IP_A") as report_download:
                self.assertEqual(report_download.status_code, 200)
                self.assertEqual(json.loads(report_download.data)["formal_nl_root"], str(formal_root))

    def test_formal_nl_scan_rejects_unregistered_ip(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            registry = root / "registry.yml"
            registry.write_text("ips: []\n", encoding="utf-8")
            client = create_app(registry, root / "output").test_client()

            response = client.post("/formal-nl", data={"id": "MISSING", "formal_nl_root": str(root)})

            self.assertEqual(response.status_code, 404)

    def test_failed_formal_nl_refresh_preserves_previous_report(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            raw_root = root / "raw" / "Vendor_A" / "IP_A"
            (raw_root / "V01" / "LEF").mkdir(parents=True)
            (raw_root / "V01" / "LEF" / "macro.lef").write_text("marker\n", encoding="utf-8")
            formal_root = root / "formal"
            ip_root = formal_root / "lib_NL2.5_3" / "IP"
            ip_root.mkdir(parents=True)
            (ip_root / "IP_A").symlink_to(raw_root, target_is_directory=True)
            registry = root / "registry.yml"
            registry.write_text(
                f"ips:\n  - id: IP_A\n    library_id: Vendor_A.IP_A\n    name: IP A\n"
                f"    library_name: IP_A\n    raw_root: {raw_root}\n    checks: {{}}\n", encoding="utf-8")
            output = root / "output"
            client = create_app(registry, output).test_client()
            first = client.post("/formal-nl", data={"id": "IP_A", "formal_nl_root": str(formal_root)})
            self.assertEqual(first.status_code, 200, first.get_data(as_text=True))
            latest_path = next(output.glob("formal_nl/*/latest.json"))
            previous_pointer = latest_path.read_bytes()

            failed = client.post("/formal-nl", data={"id": "IP_A", "formal_nl_root": str(root / "missing")})

            self.assertEqual(failed.status_code, 400)
            self.assertIn("上次成功盘点仍保留".encode(), failed.data)
            self.assertIn("lib_NL2.5_3".encode(), failed.data)
            self.assertEqual(latest_path.read_bytes(), previous_pointer)


if __name__ == "__main__":
    unittest.main()
