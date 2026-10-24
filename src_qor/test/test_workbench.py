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
            self.assertIn("库与版本".encode(), response.data)
            self.assertIn("RAW 发现".encode(), response.data)
            self.assertIn(b"data-tab-group=\"main\"", response.data)
            self.assertIn(b"data-workbench-panel=\"config\"", response.data)
            self.assertIn(b"data-workbench-panel=\"history\"", response.data)

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
            for artifact in ("library.list", "library_discovery.json", "library_discovery.html"):
                downloaded = app.test_client().get(f"/discovery-artifact/{artifact}")
                self.assertEqual(downloaded.status_code, 200)
                downloaded.close()

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
            report_path = Path(latest["report_json"])
            self.assertTrue(report_path.is_file())
            self.assertTrue(report_path.is_relative_to(output))
            report_json = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual(report_json["inventories"]["lib_NL2.5_3"]["view_counts"]["lef"], 2)
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
