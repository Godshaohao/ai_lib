import json
from pathlib import Path
import tempfile
import unittest

from lib_guard.workbench import create_app


class WorkbenchTests(unittest.TestCase):
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
            self.assertIn(b"data-workbench-panel=\"config\"", response.data)
            self.assertIn(b"data-workbench-panel=\"history\"", response.data)

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

            response = client.post("/run", data={"id": "IP_A", "library_id": "vendor.ip_a", "name": "IP A",
                                               "checks": ["macro_index"], "macro_report_json": str(report),
                                               "publish_latest": "on"})

            self.assertEqual(response.status_code, 200)
            self.assertIn(b"COMPLETE", response.data)
            result = next((root / "output" / "libraries").rglob("review_result.json"))
            review_id = json.loads(result.read_text(encoding="utf-8"))["review_id"]
            download = client.get("/download", query_string={"library_id": "vendor.ip_a", "review_id": review_id})
            self.assertEqual(download.status_code, 200)
            self.assertEqual(download.mimetype, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            download.close()

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
            self.assertEqual(saved["ips"][0]["id"], "IP_A")
            self.assertIn("macro_index", saved["ips"][0]["checks"])

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


if __name__ == "__main__":
    unittest.main()
