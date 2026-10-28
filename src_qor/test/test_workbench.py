import json
import importlib.util
from pathlib import Path
import re
import tempfile
from threading import Barrier
import time
import unittest
import zipfile
from unittest.mock import patch
from werkzeug.datastructures import MultiDict

from lib_guard import workbench
from lib_guard.workbench import _acquire_library_lock, _files_for_selection, _quick_linked_checks, _release_library_lock, _update_task, create_app


class WorkbenchTests(unittest.TestCase):
    def test_scanned_ip_opens_three_task_views_and_defaults_to_file_lookup(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            versions = []
            for n in (1, 2, 3):
                folder = root / f"V{n}"
                (folder / "LEF").mkdir(parents=True)
                if n != 2:
                    (folder / "LEF" / "core.lef").write_text("VERSION 5.8 ;\nEND LIBRARY\n")
                versions.append({"id": f"V{n}", "path": str(folder), "delivery_order": n})
            registry = root / "registry.yml"
            registry.write_text(json.dumps({"ips": [{"id": "A", "library_id": "V.A", "raw_versions": versions}]}))
            client = create_app(registry, root / "out").test_client()
            client.post("/file-status/refresh", data={"ip": "A", "raw_only": "1"})
            page = client.get("/?ip=A&tab=review").get_data(as_text=True)
            self.assertIn('data-task-view="files"', page)
            self.assertIn('data-task-view="compare"', page)
            self.assertIn('data-task-view="formal"', page)
            self.assertIn("文件定位", page)
            self.assertIn("交付对比", page)
            self.assertIn("正式来源", page)
            self.assertIn("V3", page)
            self.assertIn("V1", page)
            self.assertIn('name="base_version" value="V2"', page)
            self.assertIn('name="target_version" value="V3"', page)

    def test_default_delivery_scope_can_compare_without_applying_range_first(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            versions = []
            for n in (1, 2):
                folder = root / f"V{n}"
                (folder / "LEF").mkdir(parents=True)
                (folder / "LEF" / "a.lef").write_text(str(n))
                versions.append({"id": f"V{n}", "path": str(folder), "delivery_order": n})
            registry = root / "registry.yml"
            registry.write_text(json.dumps({"ips": [{"id": "A", "library_id": "V.A", "raw_versions": versions}]}))
            output = root / "out"
            client = create_app(registry, output).test_client()
            client.post("/file-status/refresh", data={"ip": "A", "raw_only": "1"})
            from lib_guard.review_runner import _library_dir
            projection_root = output / "file_versions" / _library_dir("V.A")
            raw = json.loads((projection_root / "latest.json").read_text())["snapshot_id"]
            response = client.post("/file-status/compare", data={"ip": "A", "snapshot_id": raw, "view": "compare", "base_version": "V1", "target_version": "V2", "file_key": "lef:a.lef"})
            self.assertIn("view=compare", response.location)
            pointer = json.loads((projection_root / "latest.json").read_text())
            projection = json.loads((projection_root / pointer["projection_ref"]).read_text())
            self.assertEqual(projection["source_snapshot_id"], raw)
            self.assertEqual(projection["files"][0]["comparison"]["content_status"], "BYTE_DIFFERENT")
            evidence = client.get("/file-status/evidence", query_string={"ip": "A", "snapshot_id": pointer["snapshot_id"], "file_key": "lef:a.lef"})
            self.assertEqual(evidence.status_code, 200)
            self.assertEqual(evidence.get_json()["scope"]["target_version"], "V2")
            self.assertEqual(client.get("/file-status/evidence", query_string={"ip": "A", "snapshot_id": raw, "file_key": "lef:a.lef"}).status_code, 404)

    def test_single_version_rejects_multiple_lef_files(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            raw = root / "V1"
            (raw / "LEF").mkdir(parents=True)
            for name in ("a.lef", "b.lef"):
                (raw / "LEF" / name).write_text("VERSION 5.8 ;\nEND LIBRARY\n")
            registry = root / "registry.yml"
            registry.write_text(json.dumps({"ips": [{"id": "A", "library_id": "V.A", "raw_versions": [{"id": "V1", "path": str(raw)}]}]}))
            output = root / "out"
            client = create_app(registry, output).test_client()
            client.post("/file-status/refresh", data={"ip": "A", "raw_only": "1"})
            from lib_guard.review_runner import _library_dir
            pointer = json.loads((output / "file_versions" / _library_dir("V.A") / "latest.json").read_text())
            response = client.post("/run", data={"mode": "matrix", "id": "A", "library_id": "V.A", "snapshot_id": pointer["snapshot_id"], "file_key": ["lef:a.lef", "lef:b.lef"]})
            self.assertEqual(response.status_code, 400)
            self.assertIn("一次只能选择一个 LEF", response.get_data(as_text=True))

    def test_link_saved_formal_does_not_rescan_raw(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            raw = root / "V1"
            (raw / "LEF").mkdir(parents=True)
            lef = raw / "LEF" / "a.lef"
            lef.write_text("VERSION 5.8 ;\nEND LIBRARY\n")
            formal = root / "lib_NL1" / "IP"
            (formal / "LEF").mkdir(parents=True)
            (formal / "LEF" / "a.lef").symlink_to(lef)
            registry = root / "registry.yml"
            registry.write_text(json.dumps({"ips": [{"id": "A", "library_id": "V.A", "library_name": "A", "vendor": "V", "raw_versions": [{"id": "V1", "path": str(raw)}], "formal_nl_root": str(formal)}]}))
            output = root / "out"
            client = create_app(registry, output).test_client()
            client.post("/file-status/refresh", data={"ip": "A", "raw_only": "1"})
            from lib_guard.review_runner import _library_dir
            projection_root = output / "file_versions" / _library_dir("V.A")
            original = json.loads((projection_root / "latest.json").read_text())["snapshot_id"]
            client.post("/formal-nl/overview/refresh", data={"ip": "A"})
            with patch("lib_guard.workbench.scan_registered_raw_files", side_effect=AssertionError("RAW rescan")):
                formal_page = client.get("/?ip=A&tab=review&view=formal").get_data(as_text=True)
            self.assertIn('data-task-panel="formal"', formal_page)
            self.assertIn('a.lef', formal_page)
            self.assertEqual(json.loads((projection_root / "latest.json").read_text())["snapshot_id"], original)
            with patch("lib_guard.workbench.scan_registered_raw_files", side_effect=AssertionError("RAW rescan")):
                response = client.post("/file-status/link-formal", data={"ip": "A", "snapshot_id": original}, follow_redirects=True)
            self.assertEqual(response.status_code, 200)
            pointer = json.loads((projection_root / "latest.json").read_text())
            self.assertNotEqual(pointer["snapshot_id"], original, response.get_data(as_text=True))
            projection = json.loads((projection_root / pointer["projection_ref"]).read_text())
            self.assertEqual(projection["source_snapshot_id"], original)
            self.assertEqual(projection["files"][0]["formal_usage"]["source_version"], "V1")

    def test_files_tab_first_run_is_raw_first_and_does_not_require_formal_nl(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            raw = root / "raw" / "V1"
            (raw / "LEF").mkdir(parents=True)
            (raw / "LEF" / "top.lef").write_text("lef", encoding="utf-8")
            registry = root / "registry.yml"
            registry.write_text(json.dumps({"ips": [{"id": "A", "library_id": "V.A",
                                                       "library_name": "IP_A",
                                                       "raw_versions": [{"id": "V1", "path": str(raw)}]}]}))
            page = create_app(registry, root / "out").test_client().get(
                "/?ip=A&tab=review&review_tab=files")
            html = page.get_data(as_text=True)
            self.assertEqual(page.status_code, 200)
            self.assertIn("文件定位", html)
            self.assertIn("刷新 RAW 文件清单", html)
            self.assertIn("正式 NL 是可选的来源维度", html)
            self.assertNotIn("先在“正式 NL”页刷新正式目录盘点，再回到这里刷新文件状态", html)

    def test_raw_only_matrix_can_compare_selected_lef_and_liberty_content(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            v1 = root / "V1"
            v2 = root / "V2"
            for version_root, text in ((v1, "same"), (v2, "different")):
                lef = version_root / "LEF" / "core.lef"
                liberty = version_root / "LIB" / "core_tt.lib"
                lef.parent.mkdir(parents=True, exist_ok=True)
                liberty.parent.mkdir(parents=True, exist_ok=True)
                lef.write_text(text, encoding="utf-8")
                liberty.write_text("same", encoding="utf-8")
            registry = root / "registry.yml"
            registry.write_text(
                f"ips:\n  - id: IP_A\n    library_id: Vendor.IP_A\n"
                f"    raw_versions:\n      - id: V1\n        path: {v1}\n        delivery_order: 1\n"
                f"      - id: V2\n        path: {v2}\n        delivery_order: 2\n", encoding="utf-8")
            output = root / "output"
            client = create_app(registry, output).test_client()
            refreshed = client.post("/file-status/refresh", data={"ip": "IP_A", "base_version": "V1",
                                                                   "target_version": "V2", "raw_only": "1"})
            self.assertEqual(refreshed.status_code, 303)
            from lib_guard.review_runner import _library_dir
            projection_root = output / "file_versions" / _library_dir("Vendor.IP_A")
            pointer = json.loads((projection_root / "latest.json").read_text())
            projection = json.loads((projection_root / pointer["projection_ref"]).read_text())
            raw_snapshot = projection["snapshot_id"]
            client.post("/file-status/range", data={"ip": "IP_A", "snapshot_id": raw_snapshot, "base_version": "V1", "target_version": "V2"})
            pointer = json.loads((projection_root / "latest.json").read_text())
            projection = json.loads((projection_root / pointer["projection_ref"]).read_text())
            compare = client.post("/file-status/compare", data={"id": "IP_A", "snapshot_id": projection["snapshot_id"],
                                                                "compare_file_key": ["lef:core.lef", "liberty:core_tt.lib"]})
            self.assertEqual(compare.status_code, 303)
            updated_pointer = json.loads((projection_root / "latest.json").read_text())
            updated = json.loads((projection_root / updated_pointer["projection_ref"]).read_text())
            self.assertEqual(updated["source_snapshot_id"], raw_snapshot)
            self.assertEqual(updated["input_snapshot_id"], projection["snapshot_id"])
            rows = {row["file_key"]: row for row in updated["files"]}
            self.assertEqual(rows["lef:core.lef"]["comparison"]["content_status"], "BYTE_DIFFERENT")
            self.assertEqual(rows["liberty:core_tt.lib"]["comparison"]["content_status"], "BYTE_SAME")
            page = client.get("/?ip=IP_A&tab=review&review_tab=files").get_data(as_text=True)
            self.assertIn(f'name="snapshot_id" value="{updated["snapshot_id"]}"', page)

    def test_content_compare_rejects_file_without_confirmed_pair(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            version = root / "V1"
            (version / "VERILOG").mkdir(parents=True)
            (version / "VERILOG" / "top.v").write_text("module top; endmodule\n", encoding="utf-8")
            registry = root / "registry.yml"
            registry.write_text(json.dumps({"ips": [{"id": "A", "library_id": "V.A",
                                                       "raw_versions": [{"id": "V1", "path": str(version)}]}]}))
            client = create_app(registry, root / "out").test_client()
            refreshed = client.post("/file-status/refresh", data={"ip": "A", "raw_only": "1"})
            self.assertEqual(refreshed.status_code, 303)
            from lib_guard.review_runner import _library_dir
            projection_root = root / "out" / "file_versions" / _library_dir("V.A")
            pointer = json.loads((projection_root / "latest.json").read_text())
            response = client.post("/file-status/compare", data={"id": "A", "snapshot_id": pointer["snapshot_id"],
                                                                    "compare_file_key": "verilog:top.v"},
                                   follow_redirects=True)
            self.assertEqual(response.status_code, 200)
            self.assertIn("尚未形成唯一 Base / Target 配对", response.get_data(as_text=True))

    @unittest.skipUnless(importlib.util.find_spec("xlsxwriter"), "需要已安装的 XlsxWriter")
    def test_raw_only_matrix_without_formal_snapshot(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            versions = []
            for version in ('V1', 'V2'):
                folder = root / version
                (folder / 'LEF').mkdir(parents=True)
                (folder / 'LEF' / 'a.lef').write_text('VERSION 5.8 ;\nEND LIBRARY\n')
                versions.append({'id': version, 'path': str(folder)})
            registry = root / 'registry.yml'
            registry.write_text(json.dumps({'ips': [{'id': 'A', 'library_id': 'V.A', 'library_name': 'IP_A', 'raw_versions': versions}]}))
            client = create_app(registry, root / 'out').test_client()
            result = client.post('/file-status/refresh', data={'ip': 'A', 'base_version': 'V1', 'target_version': 'V2', 'raw_only': '1'})
            self.assertEqual(result.status_code, 303)
            page = client.get('/?ip=A&tab=review&review_tab=files').get_data(as_text=True)
            self.assertIn('a.lef', page)
            self.assertIn('仅对比 RAW', page)
            self.assertIn('IP_A', page)
            self.assertIn('<h2 data-page-title>IP_A</h2>', page)
            self.assertIn('当前读取已登记 RAW 交付', page)
            self.assertNotIn('先在“正式 NL”页刷新正式目录盘点', page)
            self.assertNotIn('当前范围没有可列出的文件', page)
            self.assertIn('data-matrix-selection', page)
            self.assertIn('data-matrix-compare', page)
            self.assertIn('data-matrix-file', page)
            self.assertNotIn('data-compare-file', page)
            self.assertIn('data-projection-status', page)
            self.assertIn('内容比较', page)
            self.assertIn('LEF 结构变化', page)
            from lib_guard.review_runner import _library_dir
            pointer = json.loads((root / 'out' / 'file_versions' / _library_dir('V.A') / 'latest.json').read_text())
            response = client.post('/run', data={'mode': 'matrix', 'id': 'A', 'library_id': 'V.A',
                'snapshot_id': pointer['snapshot_id'], 'file_key': 'lef:a.lef'}, follow_redirects=True)
            self.assertEqual(response.status_code, 200)
            match = re.search(rb'data-task-url="([^"]+)"', response.data)
            self.assertIsNotNone(match)
            for _ in range(1000):
                task = client.get(match.group(1).decode().replace('&amp;', '&')).get_json()
                if task['status'] in {'COMPLETE', 'FAILED'}:
                    break
                time.sleep(.01)
            self.assertEqual(task['execution_status'], 'COMPLETE', task)

    def test_file_status_range_reprojects_without_rescanning_raw(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            versions = []
            for number in (1, 2, 3):
                folder = root / f"V{number}"
                lef = folder / "LEF" / "a.lef"
                lef.parent.mkdir(parents=True)
                lef.write_text(f"version-{number}", encoding="utf-8")
                versions.append({"id": f"V{number}", "path": str(folder), "delivery_order": number})
            registry = root / "registry.yml"
            registry.write_text(json.dumps({"ips": [{"id": "A", "library_id": "V.A", "raw_versions": versions}]}))
            output = root / "out"
            client = create_app(registry, output).test_client()
            self.assertEqual(client.post("/file-status/refresh", data={"ip": "A", "raw_only": "1"}).status_code, 303)
            from lib_guard.review_runner import _library_dir
            projection_root = output / "file_versions" / _library_dir("V.A")
            pointer = json.loads((projection_root / "latest.json").read_text())
            source = json.loads((projection_root / pointer["projection_ref"]).read_text())

            with patch("lib_guard.workbench.scan_registered_raw_files",
                       side_effect=AssertionError("range selection must not rescan RAW")):
                result = client.post("/file-status/range", data={
                    "ip": "A", "snapshot_id": source["snapshot_id"],
                    "base_version": "V1", "target_version": "V3",
                })
            self.assertEqual(result.status_code, 303)
            updated_pointer = json.loads((projection_root / "latest.json").read_text())
            updated = json.loads((projection_root / updated_pointer["projection_ref"]).read_text())
            self.assertNotEqual(updated["snapshot_id"], source["snapshot_id"])
            self.assertEqual(updated["source_snapshot_id"], source["snapshot_id"])
            self.assertEqual(updated["scope"]["base_version"], "V1")
            self.assertEqual(updated["scope"]["target_version"], "V3")
            self.assertEqual(updated["files"][0]["occurrences"], source["files"][0]["occurrences"])

    def test_matrix_can_run_single_latest_lef_check_without_base_target(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            raw = root / "V1"
            lef = raw / "LEF" / "top.lef"
            liberty = raw / "LIB" / "TT" / "top.lib"
            lef.parent.mkdir(parents=True)
            liberty.parent.mkdir(parents=True)
            lef.write_text("VERSION 5.8 ;\nEND LIBRARY\n", encoding="utf-8")
            liberty.write_text("library (top) { cell (top) { pin (A) { direction : input; } } }", encoding="utf-8")
            registry = root / "registry.yml"
            registry.write_text(json.dumps({"ips": [{"id": "A", "library_id": "V.A",
                                                       "raw_versions": [{"id": "V1", "path": str(raw)}]}]}))
            output = root / "out"
            client = create_app(registry, output).test_client()
            self.assertEqual(client.post("/file-status/refresh", data={"ip": "A", "raw_only": "1"}).status_code, 303)
            from lib_guard.review_runner import _library_dir
            projection_root = output / "file_versions" / _library_dir("V.A")
            pointer = json.loads((projection_root / "latest.json").read_text())
            response = client.post("/run", data={"mode": "matrix", "id": "A", "library_id": "V.A",
                                                   "snapshot_id": pointer["snapshot_id"], "file_key": "lef:top.lef"},
                                   follow_redirects=True)
            self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
            match = re.search(rb'data-task-url="([^"]+)"', response.data)
            self.assertIsNotNone(match)
            for _ in range(1000):
                task = client.get(match.group(1).decode().replace("&amp;", "&")).get_json()
                if task["status"] in {"COMPLETE", "FAILED"}:
                    break
                time.sleep(.01)
            self.assertEqual(task["execution_status"], "COMPLETE", task)

    @unittest.skipUnless(importlib.util.find_spec("xlsxwriter"), "需要已安装的 XlsxWriter")
    def test_matrix_selection_runs_batch_and_returns_same_projection_in_excel(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            old_root, new_root = root / "raw" / "20261001_full", root / "raw" / "20261005_fix"
            for version_root, size in ((old_root, 2), (new_root, 3)):
                for name in ("a.lef", "b.lef"):
                    path = version_root / "LEF" / name
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(f"VERSION 5.8 ;\nMACRO A\n SIZE 1 BY {size} ;\nEND A\nEND LIBRARY\n", encoding="utf-8")
            (new_root / "LEF" / "new.lef").write_text("VERSION 5.8 ;\nEND LIBRARY\n", encoding="utf-8")
            formal = root / "lib_NL2.5_3" / "IP"
            (formal / "LEF").mkdir(parents=True)
            (formal / "LEF" / "a.lef").symlink_to(old_root / "LEF" / "a.lef")
            registry = root / "registry.yml"
            registry.write_text(json.dumps({"ips": [{"id": "IP_A", "library_id": "Vendor.IP_A", "vendor": "Vendor",
                "library_name": "IP_A", "raw_versions": [{"id": old_root.name, "path": str(old_root)},
                {"id": new_root.name, "path": str(new_root)}], "formal_nl_root": str(formal), "checks": {}}]}), encoding="utf-8")
            output = root / "output"
            client = create_app(registry, output).test_client()
            self.assertEqual(client.post("/formal-nl/overview/refresh", data={"ip": "IP_A"}).status_code, 302)
            self.assertEqual(client.post("/file-status/refresh", data={"ip": "IP_A", "base_version": old_root.name,
                                                                       "target_version": new_root.name}).status_code, 303)
            from lib_guard.review_runner import _library_dir
            pointer = json.loads((output / "file_versions" / _library_dir("Vendor.IP_A") / "latest.json").read_text())
            for snapshot, key in ((pointer["snapshot_id"], "lef:missing.lef"),
                                  ("snapshot_stale", "lef:a.lef")):
                rejected = client.post("/run", data={"mode": "matrix", "id": "IP_A", "library_id": "Vendor.IP_A",
                    "snapshot_id": snapshot, "file_key": [key]})
                self.assertEqual(rejected.status_code, 400)
            self.assertFalse((output / "libraries" / _library_dir("Vendor.IP_A") / "latest_attempt.json").exists())
            response = client.post("/run", data={"mode": "matrix", "id": "IP_A", "library_id": "Vendor.IP_A",
                "snapshot_id": pointer["snapshot_id"], "file_key": ["lef:a.lef", "lef:b.lef"]}, follow_redirects=True)
            self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
            task_match = re.search(rb'data-task-url="([^"]+)"', response.data)
            self.assertIsNotNone(task_match)
            task_url = task_match.group(1).decode().replace("&amp;", "&")
            for _ in range(1000):
                payload = client.get(task_url).get_json()
                if payload["status"] in {"COMPLETE", "FAILED"}:
                    break
                time.sleep(0.01)
            self.assertEqual(payload["execution_status"], "COMPLETE", payload)
            run_dir = output / "libraries" / _library_dir("Vendor.IP_A") / "runs" / payload["review_id"]
            projection = json.loads((run_dir / "evidence" / "file_version_projection.json").read_text())
            self.assertEqual(projection["source_snapshot_id"], pointer["snapshot_id"])
            self.assertEqual([row["comparison"]["content_status"] for row in projection["files"]], ["BYTE_DIFFERENT", "BYTE_DIFFERENT", "NOT_COMPARED"])
            pair_ref = projection["files"][0]["comparison"]["evidence_refs"][0]
            pair_id = Path(pair_ref).stem
            evidence = client.get(f"/review-evidence/{payload['review_id']}/{pair_id}",
                                  query_string={"library_id": "Vendor.IP_A"})
            self.assertEqual(evidence.status_code, 200)
            self.assertEqual(evidence.get_json()["schema_version"], "lef_analysis.v1")
            evidence.close()
            self.assertEqual(client.get(f"/review-evidence/{payload['review_id']}/{pair_id}",
                                        query_string={"library_id": "Other.IP"}).status_code, 404)
            with zipfile.ZipFile(run_dir / "ip_review.xlsx") as workbook:
                strings = workbook.read("xl/sharedStrings.xml").decode()
                self.assertIn(projection["snapshot_id"], strings)
                self.assertIn("未发现", strings)
                self.assertNotIn("ABSENT_VERIFIED", strings)
                self.assertNotIn(">INDEPENDENT<", strings)
            page = client.get("/?ip=IP_A&tab=review&review_tab=files").get_data(as_text=True)
            self.assertIn(projection["snapshot_id"], page)
            self.assertIn(f'name="snapshot_id" value="{pointer["snapshot_id"]}"', page)
            self.assertIn("未发现", page)
            self.assertIn("已提供", page)
            self.assertNotIn("ABSENT_VERIFIED", page)
            self.assertNotIn(">DIFF / CHANGED", page)
            attempt = output / 'libraries' / _library_dir('Vendor.IP_A') / 'latest_attempt.json'
            latest = json.loads(attempt.read_text())
            latest['review_id'] = 'review_newer_without_matrix'
            attempt.write_text(json.dumps(latest))
            historical = client.get('/',
                query_string={'ip': 'IP_A', 'tab': 'review', 'review_tab': 'files', 'matrix_review': payload['review_id']}).get_data(as_text=True)
            self.assertIn(projection['snapshot_id'], historical)
            self.assertIn('历史检查结果', historical)
            history_page = client.get('/?ip=IP_A&tab=review&review_tab=history').get_data(as_text=True)
            self.assertIn('查看文件矩阵', history_page)
            self.assertEqual((formal / "LEF" / "a.lef").resolve(), old_root / "LEF" / "a.lef")

    def test_legacy_cli_task_uses_saved_quality_summary(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            registry = root / "registry.yml"
            registry.write_text("ips:\n  - {id: IP_A, library_id: Vendor.IP_A}\n", encoding="utf-8")
            from lib_guard.review_runner import _library_dir
            attempt = root / "output" / "libraries" / _library_dir("Vendor.IP_A") / "latest_attempt.json"
            attempt.parent.mkdir(parents=True)
            attempt.write_text(json.dumps({"task_id": "legacy", "status": "COMPLETE", "execution_status": "COMPLETE",
                "summary": {"quality_assessment": {"status": "REVIEW_REQUIRED"}}}), encoding="utf-8")
            response = create_app(registry, root / "output").test_client().get("/?ip=IP_A&tab=review")
            self.assertEqual(response.status_code, 200)
            self.assertIn("质量判断：存在待核实项".encode(), response.data)

    def test_file_status_marks_interrupted_pointer_publication_stale(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            registry = {"ips": [{"id": "IP_A", "library_id": "Vendor.IP_A"}]}
            from lib_guard.review_runner import _library_dir
            status_path = root / "file_status" / _library_dir("Vendor.IP_A") / "latest.json"
            status_path.parent.mkdir(parents=True)
            status_path.write_text(json.dumps({"schema_version": "lef_file_status.v1", "status": "COMPLETE",
                "projection_snapshot_id": "snapshot_new", "registry_fingerprint": workbench._formal_nl_config_fingerprint(registry),
                "formal_snapshot_generated_at": "t1"}), encoding="utf-8")
            pointer_path = root / "file_versions" / _library_dir("Vendor.IP_A") / "latest.json"
            pointer_path.parent.mkdir(parents=True)
            pointer_path.write_text(json.dumps({"snapshot_id": "snapshot_old"}), encoding="utf-8")
            status = workbench._read_lef_file_status(root, registry, registry["ips"][0], {"generated_at": "t1", "stale": False})
            self.assertTrue(status["stale"])
            self.assertEqual(status["status"], "STALE")

    def test_formal_file_inventory_lists_lefs_across_libraries_and_exposes_library_filter(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            registry = root / "registry.yml"
            registry.write_text(
                "ips:\n"
                "  - id: IP_A\n    library_id: Vendor_A.IP_A\n    vendor: Vendor_A\n    library_name: IP_A\n"
                "  - id: IP_B\n    library_id: Vendor_B.IP_B\n    vendor: Vendor_B\n    library_name: IP_B\n",
                encoding="utf-8")
            output = root / "output"
            client = create_app(registry, output).test_client()
            overview = {
                "status": "COMPLETE", "stages": [{"stage": "lib_NL2.5_3", "root": "/formal/IP",
                                                        "file_count": 3, "view_counts": {"lef": 2, "lib": 1},
                                                        "library_count": 2, "status": "COMPLETE"}],
                "stage_labels": ["lib_NL2.5_3"],
                "libraries": [
                    {"vendor": "Vendor_A", "middle_path": "", "library_name": "IP_A",
                     "library_id": "Vendor_A.IP_A", "registration_status": "已登记",
                     "versions": ["V01"], "stages": ["lib_NL2.5_3"], "file_count": 1,
                     "view_counts": {"lef": 1}},
                    {"vendor": "Vendor_B", "middle_path": "", "library_name": "IP_B",
                     "library_id": "Vendor_B.IP_B", "registration_status": "已登记",
                     "versions": ["V02"], "stages": ["lib_NL2.5_3"], "file_count": 2,
                     "view_counts": {"lef": 1, "lib": 1}},
                ],
                "files": [
                    {"stage": "lib_NL2.5_3", "vendor": "Vendor_A", "library_name": "IP_A",
                     "library_id": "Vendor_A.IP_A", "raw_version": "V01", "view": "lef",
                     "published_path": "LEF/a.lef", "source_path": "/raw/V01/LEF/a.lef"},
                    {"stage": "lib_NL2.5_3", "vendor": "Vendor_B", "library_name": "IP_B",
                     "library_id": "Vendor_B.IP_B", "raw_version": "V02", "view": "lef",
                     "published_path": "LEF/b.lef", "source_path": "/raw/V02/LEF/b.lef"},
                    {"stage": "lib_NL2.5_3", "vendor": "Vendor_B", "library_name": "IP_B",
                     "library_id": "Vendor_B.IP_B", "raw_version": "V02", "view": "lib",
                     "published_path": "LIB/b.lib", "source_path": "/raw/V02/LIB/b.lib"},
                ],
                "view_counts": {"lef": 2, "lib": 1}, "stage_count": 1, "library_count": 2,
                "registered_library_count": 2, "unregistered_library_count": 0,
                "raw_version_count": 2, "file_count": 3, "stage_file_record_count": 3,
                "unique_source_count": 3, "unmapped_file_count": 0, "issues": [], "warnings": [],
            }
            with patch("lib_guard.workbench._formal_nl_directory_overview", return_value=overview):
                refreshed = client.post("/formal-nl/overview/refresh", data={"ip": "IP_A"})

            self.assertEqual(refreshed.status_code, 302)
            page = client.get("/?ip=IP_A&tab=formal-nl")
            self.assertEqual(page.status_code, 200, page.get_data(as_text=True))
            self.assertIn(b'data-formal-library-filter', page.data)
            self.assertIn(b'value="Vendor_A.IP_A"', page.data)
            self.assertIn(b'value="Vendor_B.IP_B"', page.data)
            self.assertIn('正式文件链接 · 3 条（默认显示 LEF）'.encode(), page.data)
            self.assertIn(b'<option value="lef" selected>LEF</option>', page.data)
            self.assertLess(page.data.index(b'data-formal-files'), page.data.index(b'class="formal-metrics"'))
            self.assertLess(page.data.index(b'data-formal-files'), page.data.index(b'class="formal-library-section"'))

            files = client.get("/formal-nl/overview/files")
            self.assertEqual(files.status_code, 200)
            payload = files.get_json()
            self.assertEqual([item["library_id"] for item in payload["files"]], [
                "Vendor_A.IP_A", "Vendor_B.IP_B", "Vendor_B.IP_B",
            ])
            self.assertEqual([item["view"] for item in payload["files"]], ["lef", "lef", "lib"])

    def test_review_files_tab_reads_cache_and_refresh_builds_formal_to_raw_lef_status(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            old_root = root / "raw" / "20261001_full"
            new_root = root / "raw" / "20261005_fix"
            old_lef = old_root / "LEF" / "top.lef"
            new_lef = new_root / "LEF" / "top.lef"
            for path in (old_lef, new_lef):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(path.parent.parent.name, encoding="utf-8")
            old_lib = old_root / "LIB" / "z_tt.lib"
            new_lib = new_root / "LIB" / "z_tt.lib"
            new_gds = new_root / "GDS" / "z.gds"
            for path in (old_lib, new_lib, new_gds):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("fixture", encoding="utf-8")
            stage_ip = root / "formal" / "lib_NL2.5_3" / "IP"
            formal_link = stage_ip / "LEF" / "top.lef"
            formal_link.parent.mkdir(parents=True)
            formal_link.symlink_to(old_lef)
            (stage_ip / "LIB").mkdir(parents=True)
            (stage_ip / "LIB" / "z_tt.lib").symlink_to(old_lib)
            registry = root / "registry.yml"
            registry.write_text(
                f"ips:\n  - id: IP_A\n    library_id: Vendor_A.IP_A\n"
                f"    vendor: Vendor_A\n    library_name: IP_A\n"
                f"    raw_versions:\n      - id: 20261001_full\n        path: {old_root}\n"
                f"      - id: 20261005_fix\n        path: {new_root}\n"
                f"    formal_nl_root: {stage_ip}\n",
                encoding="utf-8")
            output = root / "output"
            client = create_app(registry, output).test_client()
            self.assertEqual(client.post("/formal-nl/overview/refresh", data={"ip": "IP_A"}).status_code, 302)

            with patch("lib_guard.workbench.scan_registered_raw_files",
                       side_effect=AssertionError("GET must not scan RAW")):
                page = client.get("/?ip=IP_A&tab=review")
            self.assertEqual(page.status_code, 200, page.get_data(as_text=True))
            self.assertIn("选中库的 RAW 来源追踪".encode(), page.data)
            self.assertIn('data-workbench-tab="files"'.encode(), page.data)

            refreshed = client.post("/file-status/refresh", data={"ip": "IP_A", "base_version": "20261001_full",
                                                                 "target_version": "20261005_fix"})
            self.assertEqual(refreshed.status_code, 303)
            self.assertIn("review_tab=files", refreshed.headers["Location"])
            from lib_guard.review_runner import _library_dir
            status_path = output / "file_status" / _library_dir("Vendor_A.IP_A") / "latest.json"
            status = json.loads(status_path.read_text(encoding="utf-8"))
            projection_root = output / "file_versions" / _library_dir("Vendor_A.IP_A")
            pointer = json.loads((projection_root / "latest.json").read_text(encoding="utf-8"))
            projection = json.loads((projection_root / pointer["projection_ref"]).read_text(encoding="utf-8"))
            self.assertEqual(projection["snapshot_id"], pointer["snapshot_id"])
            self.assertEqual(projection["schema_version"], "file_version_projection.v1")
            self.assertEqual(projection["library_id"], "Vendor_A.IP_A")
            with patch("lib_guard.workbench._write_json", side_effect=OSError("status write failed")):
                client.post("/file-status/refresh", data={"ip": "IP_A"})
            self.assertEqual(json.loads((projection_root / "latest.json").read_text(encoding="utf-8")), pointer)
            old_status_bytes = status_path.read_bytes()
            real_replace = Path.replace
            def fail_projection_pointer(source, target):
                if Path(target) == projection_root / "latest.json":
                    raise OSError("pointer write failed")
                return real_replace(source, target)
            with patch.object(Path, "replace", fail_projection_pointer):
                client.post("/file-status/refresh", data={"ip": "IP_A"})
            self.assertEqual(status_path.read_bytes(), old_status_bytes)
            self.assertEqual(json.loads((projection_root / "latest.json").read_text(encoding="utf-8")), pointer)
            self.assertEqual(status["status"], "COMPLETE")
            self.assertEqual(status["files"][0]["delivery_relation"], "LATER_DELIVERY_HINT")
            self.assertEqual(status["files"][0]["nl_source"]["source_path"], str(old_lef.resolve()))
            self.assertEqual(status["files"][0]["recent_raw_source"]["source_path"], str(new_lef.resolve()))
            self.assertEqual(status["files"][0]["content_check"], "NOT_RUN")
            rows = {item["display_name"]: item for item in status["files"]}
            self.assertEqual(rows["z_tt.lib"]["view"], "liberty")
            self.assertEqual(rows["z_tt.lib"]["recent_raw_source"]["source_path"], str(new_lib))
            self.assertEqual(rows["z.gds"]["delivery_relation"], "RAW_ONLY")
            previous_status = status_path.read_bytes()
            with patch("lib_guard.workbench.scan_registered_raw_files",
                       side_effect=OSError("controlled RAW scan failure")):
                failed_refresh = client.post("/file-status/refresh", data={"ip": "IP_A"})
            self.assertEqual(failed_refresh.status_code, 303)
            self.assertEqual(status_path.read_bytes(), previous_status)

            rendered = client.get(refreshed.headers["Location"])
            self.assertIn(pointer["snapshot_id"].encode(), rendered.data)
            self.assertIn("文件版本矩阵".encode(), rendered.data)
            self.assertIn("未比较内容".encode(), rendered.data)
            self.assertIn("发现较晚交付线索".encode(), rendered.data)
            self.assertIn("唯一归属".encode(), rendered.data)
            self.assertIn(str(formal_link).encode(), rendered.data)
            self.assertIn("较晚交付不等于内容变化".encode(), rendered.data)
            self.assertIn(b'data-file-status-view', rendered.data)
            self.assertIn(b'z_tt.lib', rendered.data)
            self.assertIn(b'z.gds', rendered.data)

    def test_file_status_does_not_guess_between_multiple_formal_stages(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            raw = root / "raw" / "20261001_full"
            source = raw / "LEF" / "top.lef"
            source.parent.mkdir(parents=True)
            source.write_text("lef", encoding="utf-8")
            formal_root = root / "formal"
            for stage in ("lib_NL2.5_2", "lib_NL2.5_3"):
                link = formal_root / stage / "IP" / "LEF" / "top.lef"
                link.parent.mkdir(parents=True)
                link.symlink_to(source)
            registry = root / "registry.yml"
            registry.write_text(
                f"ips:\n  - id: IP_A\n    library_id: Vendor_A.IP_A\n    vendor: Vendor_A\n"
                f"    library_name: IP_A\n    raw_versions: [{{id: 20261001_full, path: {raw}}}]\n"
                f"    formal_nl_root: {formal_root}\n",
                encoding="utf-8")
            output = root / "output"
            client = create_app(registry, output).test_client()
            self.assertEqual(client.post("/formal-nl/overview/refresh", data={"ip": "IP_A"}).status_code, 302)
            response = client.post("/file-status/refresh", data={"ip": "IP_A"}, follow_redirects=True)
            self.assertEqual(response.status_code, 200)
            self.assertIn("当前 NL 阶段无法唯一确定".encode(), response.data)
            self.assertIn("top.lef".encode(), response.data)
            self.assertIn("文件版本矩阵".encode(), response.data)

    def test_formal_stage_hint_must_exist_in_the_refreshed_inventory(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            raw = root / "raw" / "20261001_full"
            source = raw / "LEF" / "top.lef"
            source.parent.mkdir(parents=True)
            source.write_text("lef", encoding="utf-8")
            configured_stage_ip = root / "formal" / "lib_NL2.5_9" / "IP"
            registry = root / "registry.yml"
            registry.write_text(
                f"ips:\n  - id: IP_A\n    library_id: Vendor_A.IP_A\n    vendor: Vendor_A\n"
                f"    library_name: IP_A\n    raw_versions: [{{id: 20261001_full, path: {raw}}}]\n"
                f"    formal_nl_root: {configured_stage_ip}\n",
                encoding="utf-8")
            output = root / "output"
            client = create_app(registry, output).test_client()
            self.assertEqual(client.post("/formal-nl/overview/refresh", data={"ip": "IP_A"}).status_code, 302)
            response = client.post("/file-status/refresh", data={"ip": "IP_A"}, follow_redirects=True)
            self.assertEqual(response.status_code, 200)
            self.assertIn("当前 NL 阶段无法唯一确定".encode(), response.data)
            self.assertIn("top.lef".encode(), response.data)
            self.assertIn("文件版本矩阵".encode(), response.data)

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

            checks, notes = _quick_linked_checks(ip, "V1", "", "", "")
            self.assertEqual(set(checks), {"macro_index"})
            self.assertIn("多个 LEF", " ".join(notes))
            self.assertIn("不影响 Macro", " ".join(notes))

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

            checks, notes = _quick_linked_checks(ip, "V1", "", str(lef), "")
            self.assertEqual(set(checks), {"macro_index"})
            self.assertIn("Liberty 文件列表不完整", " ".join(notes))

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
            self.assertIn("检查报告总览".encode(), html.data)
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

            self.assertEqual(response.status_code, 303)
            self.assertIn("tab=discover", response.headers["Location"])
            body = app.test_client().get(response.headers["Location"]).get_data(as_text=True)
            self.assertIn("有 2 个目录访问失败", body)
            self.assertIn("有 1 个目录达到目录深度上限 8", body)
            self.assertNotIn("文件线索抽样或目录访问达到上限", body)

    def test_discovery_post_redirects_and_get_restores_snapshot_without_rescanning(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            raw = root / "raw"
            view = raw / "Vendor_A" / "phy_ip" / "V01" / "LEF"
            view.mkdir(parents=True)
            (view / "phy.lef").touch()
            registry = root / "registry.yml"
            registry.write_text("ips: []\n", encoding="utf-8")
            client = create_app(registry, root / "output").test_client()

            with patch("lib_guard.workbench.discover_raw_report",
                       wraps=workbench.discover_raw_report) as discover:
                response = client.post("/discover", data={"raw_root": str(raw)})
                self.assertEqual(response.status_code, 303)
                self.assertIn("tab=discover", response.headers["Location"])
                self.assertIn("discovery=latest", response.headers["Location"])
                self.assertEqual(discover.call_count, 1)

                restored = client.get(response.headers["Location"])
                self.assertEqual(restored.status_code, 200)
                self.assertIn(b"Vendor_A.phy_ip", restored.data)
                self.assertIn("发现结果已恢复".encode(), restored.data)
                self.assertEqual(discover.call_count, 1)

    def test_saved_cross_ip_lef_pair_is_explicitly_labeled_in_review_ui(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            old_root = root / "raw" / "Vendor_B" / "RM_IP" / "V01"
            new_root = root / "raw" / "Vendor_A" / "stdcell" / "V02"
            for path in (old_root / "LEF" / "old.lef", new_root / "LEF" / "new.lef"):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("VERSION 5.8 ;\nEND LIBRARY\n", encoding="utf-8")
            registry = root / "registry.yml"
            registry.write_text(
                "ips:\n"
                f"  - id: IP_A\n    library_id: Vendor_A.stdcell\n    name: Stdcell\n"
                f"    raw_versions: [{{id: V02, path: {new_root}}}]\n"
                f"    checks: {{lef_review: {{old_file: {old_root / 'LEF' / 'old.lef'}, new_file: {new_root / 'LEF' / 'new.lef'}}}}}\n"
                f"  - id: IP_B\n    library_id: Vendor_B.RM_IP\n    name: RM IP\n"
                f"    raw_versions: [{{id: V01, path: {old_root}}}]\n    checks: {{}}\n",
                encoding="utf-8")

            response = create_app(registry, root / "output").test_client().get(
                "/?ip=IP_A&tab=review&review_tab=config")

            self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
            self.assertIn(b'data-cross-ip-scope', response.data)
            self.assertIn("独立跨 IP 文件对比".encode(), response.data)
            self.assertIn("Vendor_B.RM_IP".encode(), response.data)
            self.assertIn("Vendor_A.stdcell".encode(), response.data)
            self.assertIn("不代表当前所选库的版本变化".encode(), response.data)

    def test_review_configuration_identifies_per_ip_formal_snapshot_source(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            output = root / "output"
            library_id = "Vendor_A.stdcell"
            from lib_guard.review_runner import _library_dir
            formal_dir = output / "formal_nl" / _library_dir(library_id)
            report_path = formal_dir / "runs" / "formal_01" / "formal_nl.json"
            report_path.parent.mkdir(parents=True)
            report_path.write_text(json.dumps({
                "library_id": library_id, "report_status": "COMPLETE",
                "generated_at": "2026-10-26T10:00:00Z",
                "matches": [{"nl_version": "lib_NL2.5_3"}],
                "inventories": {"lib_NL2.5_3": {"files": []}},
            }), encoding="utf-8")
            (formal_dir / "latest.json").write_text(json.dumps({
                "generated_at": "2026-10-26T10:00:00Z", "report_status": "COMPLETE",
                "report_json": str(report_path),
            }), encoding="utf-8")
            registry = root / "registry.yml"
            registry.write_text(
                "ips:\n  - id: IP_A\n    library_id: Vendor_A.stdcell\n    checks: {}\n",
                encoding="utf-8")

            response = create_app(registry, output).test_client().get(
                "/?ip=IP_A&tab=review&review_tab=config")

            self.assertEqual(response.status_code, 200)
            self.assertIn(b'data-formal-snapshot-source', response.data)
            self.assertIn(b"2026-10-26T10:00:00Z", response.data)
            self.assertIn("全局“正式 NL”总览是另一份快照".encode(), response.data)

    def test_review_snapshot_note_uses_same_successful_inventory_as_excel(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            output = root / "output"
            library_id = "Vendor_A.stdcell"
            from lib_guard.review_runner import _library_dir
            formal_dir = output / "formal_nl" / _library_dir(library_id)
            runs_dir = formal_dir / "runs"
            runs_dir.mkdir(parents=True)
            for run_id, status, generated_at in (
                ("old", "COMPLETE", "2026-10-26T09:00:00Z"),
                ("new", "INCOMPLETE", "2026-10-26T11:00:00Z"),
            ):
                report_path = runs_dir / f"{run_id}.json"
                report_path.write_text(json.dumps({
                    "library_id": library_id, "report_status": status,
                    "generated_at": generated_at,
                    "matches": [{"nl_version": "lib_NL2.5_3"}],
                    "inventories": {"lib_NL2.5_3": {"files": []}},
                }), encoding="utf-8")
                pointer = "latest_check.json" if run_id == "old" else "latest.json"
                (formal_dir / pointer).write_text(json.dumps({
                    "generated_at": generated_at, "report_status": status,
                    "report_json": str(report_path),
                }), encoding="utf-8")
            registry = root / "registry.yml"
            registry.write_text(
                "ips:\n  - id: IP_A\n    library_id: Vendor_A.stdcell\n    checks: {}\n",
                encoding="utf-8")

            response = create_app(registry, output).test_client().get(
                "/?ip=IP_A&tab=review&review_tab=config")

            self.assertEqual(response.status_code, 200)
            note = response.data.split(b'data-formal-snapshot-source', 1)[1].split(b'</details>', 1)[0]
            self.assertIn(b"2026-10-26T09:00:00Z", note)
            self.assertNotIn(b"2026-10-26T11:00:00Z", note)

    def test_manual_lef_paths_do_not_require_raw_version_selection(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            version = root / "raw" / "V01"
            version.mkdir(parents=True)
            registry = root / "registry.yml"
            registry.write_text(
                "ips:\n  - id: IP_A\n    library_id: Vendor_A.stdcell\n    raw_version: V01\n"
                f"    raw_versions: [{{id: V01, path: {version}}}]\n    checks: {{}}\n",
                encoding="utf-8")

            response = create_app(registry, root / "output").test_client().get(
                "/?ip=IP_A&tab=review&review_tab=config")

            self.assertEqual(response.status_code, 200)
            self.assertNotIn(b'name="raw_version" data-scope-target required', response.data)
            self.assertIn("RAW 版本只用于载入文件建议；也可直接填写路径".encode(), response.data)
            self.assertIn(b'name="raw_version" value=""', response.data)

    def test_workbench_headings_and_review_inputs_follow_current_task(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            registry = root / "registry.yml"
            registry.write_text(
                "ips:\n  - id: IP_A\n    library_id: Vendor_A.IP_A\n    name: IP A\n"
                "    raw_versions: []\n    checks: {}\n", encoding="utf-8")
            client = create_app(registry, root / "output").test_client()

            review = client.get("/?ip=IP_A&tab=review&review_tab=config")
            self.assertEqual(review.status_code, 200)
            self.assertIn(b'<h2 data-page-title>IP A</h2>', review.data)
            self.assertLess(review.data.index(b'class="check-list"'),
                            review.data.index(b'data-run-scope-summary'))
            self.assertIn("文件建议来源".encode(), review.data)
            self.assertIn("尚无可复用的本 IP 成功盘点快照".encode(), review.data)

            formal = client.get("/?ip=IP_A&tab=formal-nl")
            self.assertEqual(formal.status_code, 200)
            self.assertIn('<h2 data-page-title>正式 NL</h2>'.encode(), formal.data)
            catalog = client.get("/?ip=IP_A&tab=catalog")
            self.assertIn('<h2 data-page-title>库与版本</h2>'.encode(), catalog.data)
            discover = client.get("/?ip=IP_A&tab=discover")
            self.assertIn('<h2 data-page-title>发现 / 登记 RAW</h2>'.encode(), discover.data)

    def test_clearing_raw_suggestion_source_submits_the_selection(self):
        script = (Path(__file__).parents[1] / "lib_guard" / "static" / "workbench.js").read_text(
            encoding="utf-8")
        self.assertNotIn('if (scopeTarget?.value) versionForm?.requestSubmit();', script)
        self.assertIn('versionForm?.requestSubmit();', script)

    def test_cross_ip_lef_run_carries_scope_into_review_runner_input(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            old_root = root / "raw" / "Vendor_B" / "RM_IP" / "V01"
            new_root = root / "raw" / "Vendor_A" / "stdcell" / "V02"
            old_file, new_file = old_root / "LEF" / "old.lef", new_root / "LEF" / "new.lef"
            for path in (old_file, new_file):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("VERSION 5.8 ;\nEND LIBRARY\n", encoding="utf-8")
            registry = root / "registry.yml"
            registry.write_text(
                "ips:\n"
                f"  - id: IP_A\n    library_id: Vendor_A.stdcell\n    raw_versions: [{{id: V02, path: {new_root}}}]\n    checks: {{}}\n"
                f"  - id: IP_B\n    library_id: Vendor_B.RM_IP\n    raw_versions: [{{id: V01, path: {old_root}}}]\n    checks: {{}}\n",
                encoding="utf-8")
            client = create_app(registry, root / "output").test_client()
            captured = []
            review_result = {"execution_status": "COMPLETE", "review_id": "review_scope",
                             "summary": {"quality_assessment": {"status": "NOT_ASSESSED",
                                                                    "label": "本次范围有限",
                                                                    "boundary": "仅限输入文件"}}}

            with patch("lib_guard.workbench.run", side_effect=lambda config, _out: (
                    captured.append(config) or ([review_result], {}))), \
                    patch.object(workbench._REVIEW_EXECUTOR, "submit", side_effect=lambda fn: fn()):
                response = client.post("/run", data={
                    "id": "IP_A", "library_id": "Vendor_A.stdcell", "checks": ["lef_review"],
                    "lef_old_file": str(old_file), "lef_new_file": str(new_file),
                    "review_tab": "config",
                })

            self.assertEqual(response.status_code, 303)
            scope = captured[0]["ips"][0]["checks"]["lef_review"]["comparison_scope"]
            self.assertEqual(scope["kind"], "INDEPENDENT_CROSS_IP")
            self.assertEqual(scope["old_library_id"], "Vendor_B.RM_IP")
            self.assertEqual(scope["new_library_id"], "Vendor_A.stdcell")

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

    def test_legacy_quick_linked_submit_cannot_bypass_selected_checks(self):
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

            with patch("lib_guard.workbench.run") as runner:
                response = client.post("/run", data={
                    "id": "IP_A", "library_id": "Vendor.IP_A", "quick_linked_check": "1",
                    "quick_raw_version": "V1", "quick_target_lef": str(lef),
                })
            self.assertEqual(response.status_code, 400)
            self.assertIn("至少勾选一项检查".encode(), response.data)
            runner.assert_not_called()

    def test_selected_check_form_runs_once_and_refresh_does_not_repeat_check(self):
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
                    "id": "IP_A", "library_id": "Vendor.IP_A", "raw_version": "V1",
                    "base_raw_version": "V0",
                    "review_tab": "config",
                    "checks": ["macro_index", "lef_liberty_check"],
                    "macro_root": str(version), "macro_version": "V1",
                    "ll_lef_file": str(lef), "ll_liberty_files": str(liberty),
                })
                self.assertEqual(response.status_code, 303)
                self.assertIn("tab=review", response.headers["Location"])
                self.assertIn("review_tab=config", response.headers["Location"])
                self.assertIn("base_raw_version=V0", response.headers["Location"])
                page = client.get(response.headers["Location"])
                self.assertEqual(page.status_code, 200)
                self.assertIn(b'name="checks" value="macro_index" checked', page.data)
                self.assertIn(b'data-task-refresh hidden', page.data)
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
            submitted = runner.call_args.args[0]["ips"][0]
            self.assertEqual(set(submitted["checks"]), {"macro_index", "lef_liberty_check"})
            self.assertEqual(submitted["checks"]["lef_liberty_check"]["lef_file"], str(lef))
            self.assertEqual(submitted["checks"]["lef_liberty_check"]["liberty_files"], [str(liberty)])

    def test_review_configuration_tab_survives_scope_navigation_and_run_redirect(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            raw = root / "raw"
            (raw / "V1").mkdir(parents=True)
            (raw / "V2").mkdir(parents=True)
            registry = root / "registry.yml"
            registry.write_text(
                "ips:\n  - id: IP_A\n    library_id: Vendor.IP_A\n    raw_versions:\n"
                f"      - {{id: V1, path: {raw / 'V1'}}}\n"
                f"      - {{id: V2, path: {raw / 'V2'}}}\n    checks: {{}}\n",
                encoding="utf-8")
            client = create_app(registry, root / "output").test_client()

            page = client.get("/?ip=IP_A&tab=review&review_tab=config&raw_version=V2")
            self.assertEqual(page.status_code, 200)
            self.assertIn(b'name="review_tab" value="config"', page.data)

            with patch("lib_guard.workbench.run", return_value=([{
                "execution_status": "COMPLETE", "review_id": "review_keep_tab", "summary": {},
            }], {})):
                response = client.post("/run", data={
                    "id": "IP_A", "library_id": "Vendor.IP_A", "raw_version": "V2",
                    "base_raw_version": "V1",
                    "review_tab": "config", "checks": ["macro_index"],
                    "macro_root": str(raw / "V2"), "macro_version": "V2",
                })

            self.assertEqual(response.status_code, 303)
            self.assertIn("raw_version=V2", response.headers["Location"])
            self.assertIn("base_raw_version=V1", response.headers["Location"])
            self.assertIn("review_tab=config", response.headers["Location"])
            restored = client.get(response.headers["Location"])
            self.assertIn(b'data-active-review-tab="config"', restored.data)
            self.assertIn(b'aria-selected="true" data-workbench-tab="config"', restored.data)

    def test_run_validation_error_keeps_selected_version_and_review_tab(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            version = root / "raw" / "V07"
            version.mkdir(parents=True)
            registry = root / "registry.yml"
            registry.write_text(
                "ips:\n  - id: IP_A\n    library_id: Vendor.IP_A\n    raw_versions:\n"
                f"      - {{id: V07, path: {version}}}\n    checks: {{}}\n",
                encoding="utf-8")
            client = create_app(registry, root / "output").test_client()

            response = client.post("/run", data={
                "id": "IP_A", "library_id": "Vendor.IP_A", "raw_version": "V07",
                "review_tab": "config", "checks": ["macro_index"],
            })

            self.assertEqual(response.status_code, 400)
            self.assertIn(b'data-active-review-tab="config"', response.data)
            self.assertIn(b'name="raw_version" value="V07"', response.data)
            self.assertIn(b'<option value="V07" selected>V07</option>', response.data)

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

    def test_selected_raw_version_offers_suggestions_without_preselecting_checks(self):
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
            self.assertIn(f'name="macro_root" data-scope-source-input data-input-source="当前 RAW 版本" value="{version}"'.encode(), response.data)
            self.assertNotRegex(response.get_data(as_text=True), r'name="checks" value="macro_index" checked')
            self.assertIn("填入自动建议".encode(), response.data)
            self.assertNotIn("运行自动联动核查".encode(), response.data)
            suggestion_match = re.search(rb'data-suggested-checks>(.*?)</script>', response.data)
            self.assertIsNotNone(suggestion_match)
            suggestions = json.loads(suggestion_match.group(1))
            self.assertEqual(suggestions["macro_index"]["root"], str(version))
            self.assertEqual(suggestions["macro_index"]["version"], "V50")
            self.assertIn(b'data-run-scope-summary', response.data)
            self.assertLess(response.data.index(b'class="check-list"'), response.data.index(b'class="run-scope-summary"'))
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
            self.assertIn(b'name="ll_lef_file"', response.data)
            self.assertIn(b'data-fill-input="ll_lef_file"', response.data)

    def test_multiple_lefs_keep_macro_suggestion_and_offer_readable_file_choices(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            version = root / "raw" / "V02"
            for name in ("block_a.lef", "block_b.lef"):
                path = version / "LEF" / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.touch()
            registry = root / "registry.yml"
            registry.write_text(
                "ips:\n  - id: IP_A\n    library_id: Vendor.IP_A\n    raw_versions:\n"
                f"      - {{id: V02, path: {version}}}\n    checks: {{}}\n", encoding="utf-8")
            response = create_app(registry, root / "output").test_client().get(
                "/?ip=IP_A&tab=review&raw_version=V02")
            page = response.get_data(as_text=True)
            payload = re.search(r'data-suggested-checks>(.*?)</script>', page).group(1)
            self.assertEqual(set(json.loads(payload)), {"macro_index"})
            self.assertIn("不影响 Macro", page)
            self.assertIn('data-lef-search="target"', page)
            self.assertIn('data-lef-path="lef/block_a.lef"', page)
            self.assertIn('data-fill-input="lef_new_file"', page)
            self.assertIn('data-fill-input="ll_lef_file"', page)

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
            self.assertIn("发现 / 登记 RAW".encode(), response.data)
            self.assertIn(b"data-tab-group=\"main\"", response.data)
            self.assertIn(b"data-workbench-panel=\"config\"", response.data)
            self.assertIn(b"data-workbench-panel=\"history\"", response.data)
            self.assertIn(b'data-active-tab="review"', response.data)

    def test_empty_registry_defaults_to_raw_discovery(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            registry = root / "registry.yml"
            registry.write_text("ips: []\n", encoding="utf-8")

            response = create_app(registry, root / "output").test_client().get("/")

            self.assertEqual(response.status_code, 200)
            self.assertIn(b'data-active-tab="discover"', response.data)
            self.assertIn("发现 RAW 库与版本".encode(), response.data)

    def test_main_navigation_prioritizes_review_and_discovery_is_secondary(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            registry = root / "registry.yml"
            registry.write_text("ips:\n  - {id: IP_A, library_id: vendor.ip_a, name: IP A, checks: {}}\n", encoding="utf-8")

            response = create_app(registry, root / "output").test_client().get("/")
            html = response.get_data(as_text=True)
            nav = html.split('<nav class="view-tabs primary-tabs"', 1)[1].split("</nav>", 1)[0]

            self.assertLess(nav.index('data-workbench-tab="review"'), nav.index('data-workbench-tab="catalog"'))
            self.assertLess(nav.index('data-workbench-tab="catalog"'), nav.index('data-workbench-tab="formal-nl"'))
            self.assertIn('class="utility-tab"', nav)

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
            self.assertIn("最近任务".encode(), response.data)
            self.assertIn("最近完整检查报告".encode(), response.data)
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
            self.assertIn("运行日志".encode(), response.data)
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
            self.assertNotIn("暂无运行日志".encode(), response.data)

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

    def test_task_elapsed_timer_freezes_at_terminal_status(self):
        script = (Path(__file__).parents[1] / "lib_guard" / "static" / "workbench.js").read_text(
            encoding="utf-8")

        self.assertIn("let elapsedTimer = null", script)
        self.assertIn("taskBanner.dataset.taskFinishedAt = task.finished_at", script)
        self.assertIn("window.clearInterval(elapsedTimer)", script)

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
            for expected in ("Vendor_A", "phy_ip", "全部", "RAW", "正式 NL", "筛选 Vendor"):
                self.assertIn(expected.encode(), response.data)
            self.assertIn(b"data-sidebar-scope", response.data)
            self.assertIn(b"data-vendor-filter", response.data)
            self.assertIn(b"data-library-filter", response.data)
            self.assertIn(b'data-ip-library="vendor_a.phy_ip"', response.data)
            sidebar = response.get_data(as_text=True).split('<aside class="ip-rail"', 1)[1].split("</aside>", 1)[0]
            for version in ("V01", "V02", "lib_NL2.4_2", "lib_NL2.5_3"):
                self.assertNotIn(version, sidebar)
            self.assertIn("RAW 2 · 正式 2", sidebar)

    def test_formal_check_uses_registered_directories_without_config_file(self):
        previous = {
            "id": "PHY_A", "library_id": "Vendor_A.phy_ip", "name": "PHY A",
            "library_name": "phy_ip", "raw_root": "/raw/Vendor_A/phy_ip",
            "formal_nl_root": "/release/lib_NL2.5_3/IP", "checks": {},
        }
        form = MultiDict([("id", "PHY_A"), ("library_id", "Vendor_A.phy_ip"),
                          ("checks", "formal_nl")])

        with self.assertRaisesRegex(ValueError, "正式 NL.*页面"):
            workbench._entry_from_form(form, previous)

    def test_formal_inventory_is_not_a_manual_review_selection(self):
        previous = {
            "id": "PHY_A", "library_id": "Vendor_A.phy_ip", "name": "PHY A",
            "library_name": "phy_ip", "raw_root": "/raw/Vendor_A/phy_ip",
            "formal_nl_root": "/release/lib_NL2.5_3/IP", "checks": {},
        }
        with tempfile.TemporaryDirectory() as temp:
            registry = Path(temp) / "registry.yml"
            registry.write_text(
                "ips:\n  - id: PHY_A\n    library_id: Vendor_A.phy_ip\n"
                "    name: PHY A\n    library_name: phy_ip\n"
                "    formal_nl_root: /release/lib_NL2.5_3/IP\n    checks: {}\n",
                encoding="utf-8")
            response = create_app(registry, registry.parent / "output").test_client().get(
                "/?ip=PHY_A&tab=review")
            page = response.get_data(as_text=True)
            review_form = page.split('data-review-form', 1)[1].split('</form>', 1)[0]

            self.assertEqual(response.status_code, 200)
            self.assertNotIn('name="checks" value="formal_nl"', review_form)
            self.assertNotIn("正式目录盘点", review_form)
            self.assertIn("正式 NL 总览", page)
            with self.assertRaisesRegex(ValueError, "正式 NL.*页面"):
                workbench._entry_from_form(MultiDict([
                    ("id", "PHY_A"), ("library_id", "Vendor_A.phy_ip"),
                    ("checks", "formal_nl")]), previous)

    def test_formal_check_config_is_not_a_manual_review_input(self):
        previous = {"id": "PHY_A", "library_id": "Vendor_A.phy_ip", "name": "PHY A",
                    "raw_root": "/raw/default", "formal_nl_root": "/release/default", "checks": {}}
        form = MultiDict([("id", "PHY_A"), ("library_id", "Vendor_A.phy_ip"),
                          ("checks", "formal_nl"), ("formal_config", "/configs/formal.yml")])

        with self.assertRaisesRegex(ValueError, "正式 NL.*页面"):
            workbench._entry_from_form(form, previous)

    def test_manual_review_does_not_offer_formal_config_selector(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            registry = root / "registry.yml"
            registry.write_text(
                "ips:\n  - id: PHY_A\n    library_id: Vendor_A.phy_ip\n"
                "    formal_nl_root: /release/default\n    checks: {}\n", encoding="utf-8")
            audit = root / "formal_audit.yml"
            audit.write_text("library:\n  ip_directory_name: phy_ip\nformal_nl:\n  root: /release/custom\n",
                             encoding="utf-8")
            (root / "unrelated.yml").write_text("ips: []\n", encoding="utf-8")

            response = create_app(registry, root / "output").test_client().get("/?ip=PHY_A")

            self.assertEqual(response.status_code, 200)
            review_form = response.get_data(as_text=True).split('data-review-form', 1)[1].split('</form>', 1)[0]
            self.assertNotIn('data-fill-input="formal_config"', review_form)
            self.assertNotIn(str(audit), review_form)
            self.assertNotIn("formal_config", review_form)

    def test_sidebar_shows_version_counts_without_guessing_latest_or_rendering_tree(self):
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
            sidebar = html.split('<aside class="ip-rail"', 1)[1].split("</aside>", 1)[0]
            self.assertIn("RAW 3 · 正式 2", sidebar)
            self.assertNotIn("V2", sidebar)
            self.assertNotIn("V3", sidebar)
            self.assertNotIn("V10", sidebar)
            self.assertNotIn("排序最新", sidebar)
            self.assertNotIn("ip-version-tree", sidebar)

    def test_sidebar_hides_even_single_raw_and_formal_version_names(self):
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
            sidebar = html.split('<aside class="ip-rail"', 1)[1].split("</aside>", 1)[0]
            self.assertNotIn("V01", sidebar)
            self.assertNotIn("lib_NL2.5_3", sidebar)
            self.assertIn("RAW 1 · 正式 1", sidebar)

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

            self.assertEqual(response.status_code, 303)
            page = app.test_client().get(response.headers["Location"])
            self.assertEqual(page.status_code, 200)
            self.assertIn(b"IP A", page.data)
            saved = __import__("yaml").safe_load(registry.read_text(encoding="utf-8"))
            self.assertEqual(saved["ips"][0]["checks"]["macro_index"]["report_json"], str(report))
            overview = (root / "output" / "ip_checks" / "index.html").read_text(encoding="utf-8")
            self.assertIn("IP A", overview)
            self.assertIn("尚无完整检查报告", overview)

    def test_run_rejects_different_explicit_interface_lef_before_queueing(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            registry = root / "registry.yml"
            registry.write_text("ips:\n  - {id: IP_A, library_id: vendor.ip_a, checks: {}}\n", encoding="utf-8")
            client = create_app(registry, root / "output").test_client()
            response = client.post("/run", data={
                "id": "IP_A", "library_id": "vendor.ip_a",
                "checks": ["lef_review", "lef_liberty_check"],
                "lef_old_file": str(root / "old.lef"), "lef_new_file": str(root / "new.lef"),
                "ll_lef_file": str(root / "different.lef"), "ll_liberty_files": str(root / "tt.lib"),
            })
            self.assertEqual(response.status_code, 400)
            self.assertIn("LEF", response.get_data(as_text=True))
            self.assertIn("不一致", response.get_data(as_text=True))
            self.assertFalse(list((root / "output").rglob("latest_attempt.json")))

    @unittest.skipUnless(importlib.util.find_spec("xlsxwriter"), "需要已安装的 XlsxWriter")
    def test_five_versions_mixed_formal_sources_through_review_and_excel(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            library_root = root / "raw" / "Vendor" / "IP_A"
            versions = []
            lef_text = "VERSION 5.8 ;\nMACRO TOP\n  CLASS BLOCK ;\n  SIZE 1 BY 2 ;\nEND TOP\nEND LIBRARY\n"
            for number in range(1, 6):
                version = f"V{number:02}"
                version_root = library_root / version
                lef = version_root / "LEF" / "top.lef"
                lef.parent.mkdir(parents=True)
                lef.write_text(lef_text, encoding="utf-8")
                versions.append({"id": version, "path": str(version_root)})
            for corner in ("TT", "SS"):
                lib = library_root / "V05" / "LIB" / f"top_{corner}.lib"
                lib.parent.mkdir(parents=True, exist_ok=True)
                lib.write_text(f"library ({corner}) {{ cell (TOP) {{ }} }}", encoding="utf-8")
            old_lib = library_root / "V03" / "LIB" / "top_TT.lib"
            old_lib.parent.mkdir(parents=True)
            old_lib.write_text("library (TT) { cell (TOP) {} }", encoding="utf-8")
            formal = root / "lib_NL2.5_3" / "IP"
            for view, name, source in (("LEF", "top.lef", library_root / "V01" / "LEF" / "top.lef"),
                                       ("LIB", "top_TT.lib", old_lib)):
                (formal / view).mkdir(parents=True, exist_ok=True)
                (formal / view / name).symlink_to(source)
            registry = root / "registry.yml"
            registry.write_text(json.dumps({"raw_root": str(root / "raw"), "ips": [{
                "id": "IP_A", "library_id": "Vendor.IP_A", "vendor": "Vendor", "library_name": "IP_A",
                "raw_root": str(library_root), "raw_versions": versions,
                "formal_nl_root": str(formal), "formal_nl_stages": ["lib_NL2.5_3"], "checks": {},
            }]}), encoding="utf-8")
            output = root / "output"
            client = create_app(registry, output).test_client()
            refreshed = client.post("/formal-nl/overview/refresh", data={"ip": "IP_A"})
            self.assertEqual(refreshed.status_code, 302)
            page = client.get(refreshed.headers["Location"]).get_data(as_text=True)
            self.assertIn("V01", page)
            self.assertIn("V03", page)
            response = client.post("/run", data={
                "id": "IP_A", "library_id": "Vendor.IP_A", "raw_version": "V05",
                "checks": ["macro_index", "lef_review", "lef_liberty_check"],
                "macro_root": str(library_root / "V05"), "macro_version": "V05",
                "lef_old_file": str(library_root / "V04" / "LEF" / "top.lef"),
                "lef_new_file": str(library_root / "V05" / "LEF" / "top.lef"),
                "ll_lef_file": str(library_root / "V05" / "LEF" / "top.lef"),
                "ll_liberty_files": "\n".join(str(library_root / "V05" / "LIB" / f"top_{c}.lib") for c in ("TT", "SS")),
            }, follow_redirects=True)
            self.assertEqual(response.status_code, 200)
            task_match = re.search(rb'data-task-url="([^"]+)"', response.data)
            self.assertIsNotNone(task_match)
            task_url = task_match.group(1).decode().replace("&amp;", "&")
            for _ in range(1000):
                payload = client.get(task_url).get_json()
                if payload["status"] in {"COMPLETE", "FAILED"}:
                    break
                time.sleep(0.01)
            self.assertEqual(payload["status"], "COMPLETE", payload)
            review_path = next(output.rglob("review_result.json"))
            record = json.loads(review_path.read_text(encoding="utf-8"))
            self.assertEqual(record["context"]["target_raw_versions"], ["V05"])
            self.assertEqual(set(record["requested_checks"]), {"macro_index", "lef_review", "lef_liberty_check"})
            self.assertEqual(record["checks"]["lef_liberty_check"]["execution_status"], "COMPLETE")
            self.assertTrue((review_path.parent / "ip_review.xlsx").is_file())
            with zipfile.ZipFile(review_path.parent / "ip_review.xlsx") as workbook:
                shared = workbook.read("xl/sharedStrings.xml").decode("utf-8")
                self.assertIn("V05", shared)
                self.assertIn("top_TT.lib", shared)
                self.assertIn("top_SS.lib", shared)
            cross = json.loads((review_path.parent / "evidence" / "lef_liberty_check.json").read_text(encoding="utf-8"))
            self.assertEqual(len(cross["files"]), 2)
            self.assertEqual(Path(cross["lef_source"]["path"]), library_root / "V05" / "LEF" / "top.lef")
            self.assertEqual((formal / "LEF" / "top.lef").resolve(), library_root / "V01" / "LEF" / "top.lef")
            self.assertEqual((formal / "LIB" / "top_TT.lib").resolve(), old_lib)

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
            overview = (root / "output" / "ip_checks" / "index.html").read_text(encoding="utf-8")
            self.assertIn("review_", overview)
            self.assertIn("打开 Excel", overview)
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
            overview = (output / "ip_checks" / "index.html").read_text(encoding="utf-8")
            self.assertIn(task_id, overview)
            self.assertIn("执行失败", overview)

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
                "id": "IP_A", "library_id": "vendor.ip_a", "name": "IP A", "checks": ["macro_index"],
                "review_tab": "history",
            })

            self.assertEqual(response.status_code, 400)
            self.assertIn("缺少所需路径".encode(), response.data)
            self.assertIn(b'data-active-tab="review"', response.data)
            self.assertIn(b'data-active-review-tab="history"', response.data)
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

            self.assertEqual(response.status_code, 303)
            page = app.test_client().get(response.headers["Location"])
            self.assertEqual(page.status_code, 200)
            self.assertIn(b"Vendor_A", page.data)
            self.assertIn(b"phy_ip", page.data)
            self.assertIn(b"V01", page.data)
            self.assertIn("分组路径".encode(), page.data)
            self.assertIn(b"library_discovery.json", page.data)
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

            self.assertEqual(registered.status_code, 303)
            self.assertIn("tab=catalog", registered.headers["Location"])
            self.assertIn("registered=1", registered.headers["Location"])
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

            self.assertEqual(refreshed.status_code, 303)
            updated = __import__("yaml").safe_load(registry.read_text(encoding="utf-8"))["ips"][0]
            self.assertEqual([item["id"] for item in updated["raw_versions"]], ["V01", "V02", "V03"])
            self.assertEqual(updated["checks"]["macro_index"]["root"], "/kept/input")

    def test_register_date_cell_layout_keeps_real_version_paths(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            raw = root / "raw"
            cell = "ln04lpp_sc_hvt_c54104"
            for release in ("20260917_DTCO", "20261001_DTCO"):
                view = raw / "Metax" / "DTCO" / release / "elf" / "psls" / cell / "LEF"
                view.mkdir(parents=True)
                (view / "cell.lef").touch()
            registry = root / "registry.yml"
            registry.write_text("ips: []\n", encoding="utf-8")
            client = create_app(registry, root / "output").test_client()
            library_id = f"Metax.DTCO.elf.psls.{cell}"

            response = client.post("/register-discovered", data={
                "raw_root": str(raw), "library_ids": [library_id]
            })

            self.assertEqual(response.status_code, 303)
            entry = __import__("yaml").safe_load(registry.read_text(encoding="utf-8"))["ips"][0]
            self.assertEqual(entry["library_id"], library_id)
            self.assertEqual(entry["middle_path"], "DTCO/elf/psls")
            self.assertEqual([item["id"] for item in entry["raw_versions"]],
                             ["20260917_DTCO", "20261001_DTCO"])
            self.assertEqual(entry["raw_versions"][0]["path"],
                             str(raw / "Metax" / "DTCO" / "20260917_DTCO" / "elf" / "psls" / cell))

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
            self.assertEqual(discovered.status_code, 303)
            discovered_page = client.get(discovered.headers["Location"])
            self.assertEqual(discovered_page.status_code, 200)
            self.assertIn("未登记".encode(), discovered_page.data)
            self.assertIn(b'name="register_one"', discovered_page.data)
            self.assertIn("全选当前结果".encode(), discovered_page.data)
            self.assertNotIn("库候选".encode(), discovered_page.data)

            registered = client.post("/register-discovered", data={
                "raw_root": str(raw), "register_one": "Vendor_A.phy_ip"
            })
            self.assertEqual(registered.status_code, 303)
            data = __import__("yaml").safe_load(registry.read_text(encoding="utf-8"))
            self.assertEqual([entry["library_id"] for entry in data["ips"]], ["Vendor_A.phy_ip"])
            entry_id = data["ips"][0]["id"]
            refreshed_view = client.post("/discover", data={"raw_root": str(raw)})
            self.assertEqual(refreshed_view.status_code, 303)
            refreshed_page = client.get(refreshed_view.headers["Location"])
            self.assertIn("已登记".encode(), refreshed_page.data)
            self.assertIn("更新登记".encode(), refreshed_page.data)
            catalog = client.get("/")
            self.assertIn("登记信息".encode(), catalog.data)
            self.assertIn("移除".encode(), catalog.data)
            review = client.get(f"/?ip={entry_id}&tab=review&raw_version=V01")
            self.assertIn(b"data-check-select-all", review.data)
            self.assertIn(b"data-lib-search", review.data)

            edited = client.post("/save", data={
                "id": entry_id, "library_id": "Vendor_A.phy_ip", "name": "renamed display",
                "vendor": "Vendor_A", "middle_path": "group/subgroup", "library_name": "phy_ip",
            })
            self.assertEqual(edited.status_code, 303)
            saved = __import__("yaml").safe_load(registry.read_text(encoding="utf-8"))["ips"][0]
            self.assertEqual(saved["name"], "renamed display")
            self.assertEqual(saved["middle_path"], "group/subgroup")
            self.assertEqual(saved["raw_versions"][0]["path"], str(raw / "Vendor_A" / "phy_ip" / "V01"))

            history = root / "output" / "libraries" / "Vendor_A.phy_ip" / "runs" / "old"
            history.mkdir(parents=True)
            marker = history / "review_result.json"
            marker.write_text("{}", encoding="utf-8")
            removed = client.post("/unregister", data={"id": entry_id})
            self.assertEqual(removed.status_code, 303)
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
            self.assertEqual(response.status_code, 303)
            response = client.get(response.headers["Location"])
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

            self.assertEqual(response.status_code, 303)
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
            self.assertEqual(discovered.status_code, 303)
            discovered_page = app.test_client().get(discovered.headers["Location"])
            self.assertEqual(discovered_page.status_code, 200)
            self.assertIn(b"Vendor_A.phy_ip", discovered_page.data)

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
            self.assertIn("只读盘点".encode(), response.data)
            self.assertIn(str(formal).encode(), response.data)

    def test_formal_nl_tab_shows_single_stage_snapshot_without_discovery_pointer(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            registry = root / "registry.yml"
            formal_ip = root / "lib_NL2.5_3" / "IP"
            formal_ip.mkdir(parents=True)
            raw_root = root / "raw" / "IP_A"
            raw_root.mkdir(parents=True)
            raw_lef = raw_root / "V01" / "LEF" / "IP_A.lef"
            raw_lef.parent.mkdir(parents=True)
            raw_lef.write_text("LEF evidence\n", encoding="utf-8")
            formal_lef = formal_ip / "LEF" / "IP_A.lef"
            formal_lef.parent.mkdir(parents=True)
            formal_lef.symlink_to(raw_lef)
            registry.write_text(
                f"ips:\n  - id: IP_A\n    library_id: Vendor_A.IP_A\n    name: IP A\n"
                f"    library_name: IP_A\n    raw_root: {raw_root}\n"
                f"    formal_nl_root: {formal_ip}\n    checks: {{}}\n", encoding="utf-8")
            output = root / "output"
            formal_dir = output / "formal_nl" / workbench._library_dir("Vendor_A.IP_A")
            run_dir = formal_dir / "runs" / "single-stage-run"
            run_dir.mkdir(parents=True)
            report_path = run_dir / "formal_nl.json"
            report_path.write_text(json.dumps({
                "report_status": "COMPLETE",
                "formal_scope": "SINGLE_STAGE",
                "formal_nl_root": str(formal_ip),
                "matches": [{
                    "nl_version": "lib_NL2.5_3",
                    "link_path": str(formal_ip),
                    "target_path": str(formal_ip),
                    "layout": "FLAT_FILE_LINKS",
                    "classification": "SELECTED_STAGE",
                    "file_count": 1,
                }],
                "inventories": {"lib_NL2.5_3": {
                    "file_count": 1,
                    "view_counts": {"lef": 1},
                    "files": [{"view": "lef", "published_path": "LEF/IP_A.lef",
                               "source_path": str(raw_root / "V01" / "LEF" / "IP_A.lef")}],
                }},
                "filename_coverage": {"lib_NL2.5_3": {"corner_counts": {}}},
            }), encoding="utf-8")
            (formal_dir / "latest_check.json").write_text(json.dumps({
                "generated_at": "2026-10-25T00:00:00+00:00",
                "report_status": "COMPLETE",
                "discovery_status": "SINGLE_STAGE",
                "report_json": str(report_path),
            }), encoding="utf-8")

            response = create_app(registry, output).test_client().get("/?ip=IP_A&tab=formal-nl")

            self.assertEqual(response.status_code, 200)
            self.assertIn("lib_NL2.5_3".encode(), response.data)
            self.assertIn(b"lef 1", response.data)
            self.assertIn("LEF/IP_A.lef".encode(), response.data)
            self.assertIn(str(raw_root / "V01" / "LEF" / "IP_A.lef").encode(), response.data)

            selected_stage = create_app(registry, output).test_client().post("/formal-nl", data={
                "id": "IP_A", "formal_nl_root": str(formal_ip), "formal_stage": "lib_NL2.5_3",
            })

            self.assertEqual(selected_stage.status_code, 303, selected_stage.get_data(as_text=True))

    def test_formal_nl_tab_summarizes_flattened_tree_by_source_library_version_and_view(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            raw_root = root / "raw"
            formal_ip = root / "lib_NL2.5_3" / "IP"
            formal_ip.mkdir(parents=True)
            registered = [
                ("IP_A", "Vendor_A", "IP_A", "V01", "LEF", "a.lef"),
                ("IP_B", "Vendor_B", "IP_B", "V02", "LIB", "b_tt.lib"),
            ]
            for ip_id, vendor, library, version, view, filename in registered:
                source = raw_root / vendor / library / version / view / filename
                source.parent.mkdir(parents=True, exist_ok=True)
                source.write_text("source\n", encoding="utf-8")
                link = formal_ip / view / filename
                link.parent.mkdir(parents=True, exist_ok=True)
                link.symlink_to(source)
            unregistered_source = raw_root / "Vendor_C" / "IP_C" / "V03" / "GDS" / "c.gds"
            unregistered_source.parent.mkdir(parents=True, exist_ok=True)
            unregistered_source.write_text("source\n", encoding="utf-8")
            unregistered_link = formal_ip / "GDS" / "c.gds"
            unregistered_link.parent.mkdir(parents=True, exist_ok=True)
            unregistered_link.symlink_to(unregistered_source)

            registry = root / "registry.yml"
            lines = [f"raw_root: {raw_root}", "ips:"]
            for ip_id, vendor, library, version, _view, _filename in registered:
                version_root = raw_root / vendor / library / version
                lines.extend([
                    f"  - id: {ip_id}", f"    library_id: {vendor}.{library}",
                    f"    vendor: {vendor}", f"    library_name: {library}",
                    f"    raw_root: {raw_root / vendor / library}",
                    f"    raw_versions:", f"      - id: {version}", f"        path: {version_root}",
                    f"    formal_nl_root: {formal_ip}", f"    formal_nl_stages: [lib_NL2.5_3]",
                    "    checks: {}",
                ])
            registry.write_text("\n".join(lines) + "\n", encoding="utf-8")

            client = create_app(registry, root / "output").test_client()
            response = client.post("/formal-nl/overview/refresh", data={"ip": "IP_A"})

            self.assertEqual(response.status_code, 302)
            self.assertIn("formal_refreshed=1", response.headers["Location"])
            page = client.get(response.headers["Location"])
            self.assertEqual(page.status_code, 200, page.get_data(as_text=True))
            self.assertIn("正式 NL 总览".encode(), page.data)
            self.assertIn("来源 IP".encode(), page.data)
            self.assertIn("引用 RAW 版本".encode(), page.data)
            self.assertIn("阶段 × 文件记录".encode(), page.data)
            self.assertIn("正式目录变更后请重新刷新".encode(), page.data)
            self.assertIn(b"LEF 1", page.data)
            self.assertIn(b"LIBERTY 1", page.data)
            self.assertIn(b"GDS 1", page.data)
            self.assertIn("Vendor_A".encode(), page.data)
            self.assertIn("Vendor_B".encode(), page.data)
            self.assertIn("Vendor_C".encode(), page.data)
            self.assertIn("未登记".encode(), page.data)
            self.assertIn("正式文件链接 ·".encode(), page.data)
            self.assertNotIn(str(unregistered_source).encode(), page.data)
            file_payload = client.get("/formal-nl/overview/files").get_json()
            self.assertIn(str(unregistered_source.resolve()),
                          [item["source_path"] for item in file_payload["files"]])

            catalog_response = client.get("/?ip=IP_A&tab=catalog")
            self.assertEqual(catalog_response.status_code, 200, catalog_response.get_data(as_text=True))
            self.assertIn(b"LEF 1", catalog_response.data)
            self.assertIn(b"LIBERTY 1", catalog_response.data)
            self.assertIn(b"GDS 1", catalog_response.data)

    def test_formal_nl_source_mapping_uses_raw_discovery_middle_path(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            raw_root = root / "raw"
            source = raw_root / "Vendor_A" / "memory" / "sram" / "SRAM_A" / "V50" / "LEF" / "sram.lef"
            source.parent.mkdir(parents=True)
            source.write_text("LEF", encoding="utf-8")
            formal_ip = root / "formal" / "lib_NL2.5_3" / "IP"
            link = formal_ip / "LEF" / "sram.lef"
            link.parent.mkdir(parents=True)
            link.symlink_to(source)
            registry = root / "registry.yml"
            registry.write_text(f"raw_root: {raw_root}\nips:\n  - id: unrelated\n    formal_nl_root: {formal_ip.parent.parent}\n",
                                encoding="utf-8")

            from lib_guard.workbench import _formal_nl_directory_overview
            overview = _formal_nl_directory_overview(
                [{"id": "unrelated", "formal_nl_root": str(formal_ip.parent.parent)}], registry)

            self.assertEqual(overview["library_count"], 1)
            self.assertEqual(overview["libraries"][0]["vendor"], "Vendor_A")
            self.assertEqual(overview["libraries"][0]["middle_path"], "memory/sram")
            self.assertEqual(overview["libraries"][0]["library_name"], "SRAM_A")
            self.assertEqual(overview["libraries"][0]["versions"], ["V50"])
            self.assertEqual(overview["unmapped_file_count"], 0)

    def test_formal_nl_ambiguous_raw_discovery_source_is_not_guessed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            raw_root = root / "raw"
            source = raw_root / "Vendor_A" / "IP_A" / "V01" / "LEF" / "a.lef"
            source.parent.mkdir(parents=True)
            source.write_text("LEF", encoding="utf-8")
            formal_ip = root / "formal" / "lib_NL2.5_3" / "IP"
            link = formal_ip / "LEF" / "a.lef"
            link.parent.mkdir(parents=True)
            link.symlink_to(source)
            registry = root / "registry.yml"
            registry.write_text(f"raw_root: {raw_root}\nips: []\n", encoding="utf-8")
            duplicated_path = str(source.parents[1])
            discovery = {"candidates": [
                {"vendor": "Vendor_A", "middle_path": "group_a", "library_name": "IP_A",
                 "library_id": "Vendor_A.group_a.IP_A", "versions": [{"id": "V01", "path": duplicated_path}]},
                {"vendor": "Vendor_A", "middle_path": "group_b", "library_name": "IP_B",
                 "library_id": "Vendor_A.group_b.IP_B", "versions": [{"id": "V01", "path": duplicated_path}]},
            ]}

            with patch("lib_guard.workbench.discover_raw_report", return_value=discovery):
                from lib_guard.workbench import _formal_nl_directory_overview
                overview = _formal_nl_directory_overview(
                    [{"id": "unrelated", "formal_nl_root": str(formal_ip.parent.parent)}], registry)

            self.assertEqual(overview["unmapped_file_count"], 1)
            self.assertEqual(overview["files"][0]["registration_status"], "来源匹配不唯一")
            self.assertEqual(overview["files"][0]["library_name"], "来源未确定")

    def test_formal_nl_counts_stage_file_records_separately_from_unique_sources(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            raw_root = root / "raw"
            source = raw_root / "Vendor_A" / "IP_A" / "V01" / "LEF" / "a.lef"
            source.parent.mkdir(parents=True)
            source.write_text("LEF", encoding="utf-8")
            formal_root = root / "formal"
            for stage in ("lib_NL2.5_3", "lib_NL2.5_4"):
                link = formal_root / stage / "IP" / "LEF" / "a.lef"
                link.parent.mkdir(parents=True)
                link.symlink_to(source)
            registry = root / "registry.yml"
            registry.write_text(f"raw_root: {raw_root}\nips: []\n", encoding="utf-8")

            from lib_guard.workbench import _formal_nl_directory_overview
            overview = _formal_nl_directory_overview(
                [{"id": "IP_A", "formal_nl_root": str(formal_root)}], registry)

            self.assertEqual(overview["file_count"], 2)
            self.assertEqual(overview["stage_file_record_count"], 2)
            self.assertEqual(overview["unique_source_count"], 1)

    def test_formal_nl_page_reads_snapshot_and_explicit_refresh_creates_it(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            raw_root = root / "raw"
            source = raw_root / "Vendor_A" / "IP_A" / "V01" / "LEF" / "a.lef"
            source.parent.mkdir(parents=True)
            source.write_text("LEF", encoding="utf-8")
            formal_ip = root / "formal" / "lib_NL2.5_3" / "IP"
            link = formal_ip / "LEF" / "a.lef"
            link.parent.mkdir(parents=True)
            link.symlink_to(source)
            registry = root / "registry.yml"
            registry.write_text(
                f"raw_root: {raw_root}\nips:\n  - id: IP_A\n    library_id: Vendor_A.IP_A\n"
                f"    vendor: Vendor_A\n    library_name: IP_A\n    raw_versions: []\n"
                f"    formal_nl_root: {root / 'formal'}\n    formal_nl_stages: [lib_NL2.5_3]\n",
                encoding="utf-8")
            client = create_app(registry, root / "output").test_client()

            with patch("lib_guard.workbench._formal_nl_directory_overview",
                       side_effect=AssertionError("page render must not walk Formal NL")):
                initial = client.get("/?ip=IP_A&tab=catalog")
            self.assertEqual(initial.status_code, 200)

            refreshed = client.post("/formal-nl/overview/refresh", data={"ip": "IP_A"})
            self.assertEqual(refreshed.status_code, 302)
            snapshot_path = root / "output" / "formal_nl" / "overview" / "latest.json"
            snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
            self.assertTrue(snapshot["generated_at"])
            self.assertEqual(snapshot["overview"]["library_count"], 1)

            with patch("lib_guard.workbench._formal_nl_directory_overview",
                       side_effect=AssertionError("snapshot read must not walk Formal NL")):
                page = client.get("/?ip=IP_A&tab=formal-nl")
            self.assertEqual(page.status_code, 200, page.get_data(as_text=True))
            self.assertIn(snapshot["generated_at"].encode(), page.data)
            self.assertIn("阶段 × 文件记录".encode(), page.data)
            self.assertIn("只读目录清点 · 快照完整（生成时）".encode(), page.data)

            files = client.get("/formal-nl/overview/files")
            self.assertEqual(files.status_code, 200)
            self.assertEqual(files.get_json()["files"][0]["source_path"], str(source.resolve()))

    def test_formal_nl_snapshot_marks_registry_changes_stale_without_rescan(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            registry = root / "registry.yml"
            first_formal = root / "formal_a"
            registry.write_text(
                f"ips:\n  - id: IP_A\n    library_id: Vendor_A.IP_A\n"
                f"    formal_nl_root: {first_formal}\n    formal_nl_stages: []\n",
                encoding="utf-8")
            client = create_app(registry, root / "output").test_client()
            client.post("/formal-nl/overview/refresh", data={"ip": "IP_A"})
            registry.write_text(
                f"ips:\n  - id: IP_A\n    library_id: Vendor_A.IP_A\n"
                f"    formal_nl_root: {root / 'formal_b'}\n    formal_nl_stages: []\n",
                encoding="utf-8")

            with patch("lib_guard.workbench._formal_nl_directory_overview",
                       side_effect=AssertionError("staleness check must not rescan")):
                response = client.get("/?ip=IP_A&tab=formal-nl")

            self.assertEqual(response.status_code, 200)
            self.assertIn("快照已过期".encode(), response.data)

    def test_formal_nl_refresh_failure_preserves_last_successful_snapshot(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            raw_root = root / "raw"
            source = raw_root / "Vendor_A" / "IP_A" / "V01" / "LEF" / "a.lef"
            source.parent.mkdir(parents=True)
            source.write_text("LEF", encoding="utf-8")
            formal_ip = root / "formal" / "lib_NL2.5_3" / "IP"
            link = formal_ip / "LEF" / "a.lef"
            link.parent.mkdir(parents=True)
            link.symlink_to(source)
            registry = root / "registry.yml"
            registry.write_text(
                f"raw_root: {raw_root}\nips:\n  - id: IP_A\n    library_id: Vendor_A.IP_A\n"
                f"    vendor: Vendor_A\n    library_name: IP_A\n    raw_root: {raw_root / 'Vendor_A' / 'IP_A'}\n"
                f"    raw_versions:\n      - id: V01\n        path: {source.parents[2]}\n"
                f"    formal_nl_root: {root / 'formal'}\n    formal_nl_stages: [lib_NL2.5_3]\n",
                encoding="utf-8")
            output = root / "output"
            client = create_app(registry, output).test_client()
            self.assertEqual(client.post("/formal-nl/overview/refresh", data={"ip": "IP_A"}).status_code, 302)
            snapshot_path = output / "formal_nl" / "overview" / "latest.json"
            previous_snapshot = snapshot_path.read_bytes()

            with patch("lib_guard.workbench._formal_nl_directory_overview",
                       side_effect=OSError("controlled scan failure")):
                failed = client.post("/formal-nl/overview/refresh", data={"ip": "IP_A"})

            self.assertEqual(failed.status_code, 400)
            self.assertIn("上次成功快照保留".encode(), failed.data)
            self.assertEqual(snapshot_path.read_bytes(), previous_snapshot)
            details = client.get("/formal-nl/overview/files")
            self.assertEqual(details.status_code, 200)
            self.assertEqual(details.get_json()["files"][0]["published_path"], str(link))

    def test_formal_nl_link_changes_enter_snapshot_only_after_explicit_refresh(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            raw_root = root / "raw"
            version_root = raw_root / "Vendor_A" / "IP_A" / "V01"
            source_a = version_root / "LEF" / "a.lef"
            source_b = version_root / "LEF" / "b.lef"
            source_a.parent.mkdir(parents=True)
            source_a.write_text("A", encoding="utf-8")
            source_b.write_text("B", encoding="utf-8")
            formal_ip = root / "formal" / "lib_NL2.5_3" / "IP"
            link_a = formal_ip / "LEF" / "a.lef"
            link_a.parent.mkdir(parents=True)
            link_a.symlink_to(source_a)
            registry = root / "registry.yml"
            registry.write_text(
                f"raw_root: {raw_root}\nips:\n  - id: IP_A\n    library_id: Vendor_A.IP_A\n"
                f"    vendor: Vendor_A\n    library_name: IP_A\n    raw_root: {raw_root / 'Vendor_A' / 'IP_A'}\n"
                f"    raw_versions:\n      - id: V01\n        path: {version_root}\n"
                f"    formal_nl_root: {root / 'formal'}\n    formal_nl_stages: [lib_NL2.5_3]\n",
                encoding="utf-8")
            output = root / "output"
            client = create_app(registry, output).test_client()
            self.assertEqual(client.post("/formal-nl/overview/refresh", data={"ip": "IP_A"}).status_code, 302)
            link_a.unlink()
            link_b = formal_ip / "LEF" / "b.lef"
            link_b.symlink_to(source_b)

            with patch("lib_guard.workbench._formal_nl_directory_overview",
                       side_effect=AssertionError("GET must use the saved snapshot")):
                page = client.get("/?ip=IP_A&tab=formal-nl")
                details_before_refresh = client.get("/formal-nl/overview/files")

            self.assertEqual(page.status_code, 200)
            self.assertIn("正式目录变更后请重新刷新".encode(), page.data)
            self.assertEqual(details_before_refresh.status_code, 200)
            self.assertEqual(details_before_refresh.get_json()["files"][0]["published_path"], str(link_a))
            refreshed = client.post("/formal-nl/overview/refresh", data={"ip": "IP_A"})
            self.assertEqual(refreshed.status_code, 302)
            details_after_refresh = client.get("/formal-nl/overview/files")
            self.assertEqual(details_after_refresh.status_code, 200)
            self.assertEqual(details_after_refresh.get_json()["files"][0]["published_path"], str(link_b))

    def test_malformed_formal_nl_snapshot_does_not_break_page_or_file_endpoint(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            registry = root / "registry.yml"
            registry.write_text(
                f"ips:\n  - id: IP_A\n    library_id: Vendor_A.IP_A\n"
                f"    name: IP A\n    formal_nl_root: {root / 'formal'}\n",
                encoding="utf-8")
            output = root / "output"
            snapshot = output / "formal_nl" / "overview" / "latest.json"
            snapshot.parent.mkdir(parents=True)
            snapshot.write_text("[]", encoding="utf-8")
            client = create_app(registry, output).test_client()

            page = client.get("/?ip=IP_A&tab=formal-nl")
            files = client.get("/formal-nl/overview/files")

            self.assertEqual(page.status_code, 200)
            self.assertIn("正式 NL 快照无法读取".encode(), page.data)
            self.assertEqual(files.status_code, 409)
            self.assertIn("快照无法读取", files.get_json()["error"])

    def test_formal_nl_overview_keeps_distinct_roots_with_same_stage_name(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            registry = root / "registry.yml"
            entries = []
            for vendor, library, version, view, filename in (
                ("Vendor_A", "IP_A", "V01", "LEF", "a.lef"),
                ("Vendor_B", "IP_B", "V02", "GDS", "b.gds"),
            ):
                library_root = root / "raw" / vendor / library
                source = library_root / version / view / filename
                source.parent.mkdir(parents=True, exist_ok=True)
                source.write_text("source\n", encoding="utf-8")
                formal_root = root / f"formal_{vendor}" / "lib_NL2.5_3" / "IP"
                link = formal_root / view / filename
                link.parent.mkdir(parents=True, exist_ok=True)
                link.symlink_to(source)
                entries.append({
                    "id": f"{vendor}.{library}", "library_id": f"{vendor}.{library}",
                    "vendor": vendor, "library_name": library, "raw_root": str(library_root),
                    "raw_versions": [{"id": version, "path": str(source.parents[2])}],
                    "formal_nl_root": str(formal_root.parents[1]),
                    "formal_nl_stages": ["lib_NL2.5_3"],
                })

            from lib_guard.workbench import _formal_nl_directory_overview

            overview = _formal_nl_directory_overview(entries, registry)

            self.assertEqual(overview["stage_count"], 2)
            self.assertEqual(overview["library_count"], 2)
            self.assertEqual(overview["file_count"], 2)
            self.assertEqual(overview["view_counts"], {"gds": 1, "lef": 1})

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

            self.assertEqual(saved.status_code, 303)
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

            self.assertEqual(response.status_code, 303, response.get_data(as_text=True))
            page = client.get(response.headers["Location"])
            self.assertEqual(page.status_code, 200, page.get_data(as_text=True))
            self.assertIn("lib_NL2.5_3".encode(), page.data)
            self.assertIn("lib_NL2.4_2".encode(), page.data)
            self.assertIn("liberty".encode(), page.data)
            self.assertIn("LEF".encode(), page.data)
            self.assertIn("DB".encode(), page.data)
            self.assertIn("TT".encode(), page.data)
            self.assertIn("目录名排序靠前".encode(), page.data)
            self.assertIn("目录名排序第二".encode(), page.data)
            self.assertIn(str(formal_root / "lib_NL2.5_3" / "IP" / "IP_A").encode(), page.data)
            self.assertIn(b"lef 2", page.data)
            self.assertIn(b"formal-report/json", page.data)
            saved = __import__("yaml").safe_load(registry.read_text(encoding="utf-8"))
            self.assertEqual(saved["ips"][0]["formal_nl_root"], str(formal_root))
            self.assertEqual(saved["ips"][0]["formal_nl_stages"], ["lib_NL2.5_3", "lib_NL2.4_2"])
            sidebar = page.get_data(as_text=True).split('<aside class="ip-rail"', 1)[1].split("</aside>", 1)[0]
            self.assertIn("正式 2", sidebar)
            self.assertNotIn("lib_NL2.5_3", sidebar)
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
            self.assertEqual(stage_response.status_code, 303, stage_response.get_data(as_text=True))
            self.assertEqual(latest_path.read_bytes(), browse_pointer)
            stage_reports = [json.loads(path.read_text(encoding="utf-8"))
                             for path in (latest_path.parent / "runs").glob("*/formal_nl.json")]
            stage_report = next(item for item in stage_reports if item["formal_scope"] == "SINGLE_STAGE")
            self.assertEqual(stage_report["report_status"], "COMPLETE")
            check_pointer = latest_path.parent / "latest_check.json"
            self.assertEqual(check_pointer.exists(), stage_report["report_status"] == "COMPLETE")
            review = client.get("/?ip=IP_A&tab=formal-nl&formal_stage=lib_NL2.5_3")
            self.assertEqual(review.status_code, 200)
            self.assertIn("最近完成的单阶段核查".encode(), review.data)
            self.assertIn(b"scope=check", review.data)
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
            self.assertEqual(first.status_code, 303, first.get_data(as_text=True))
            latest_path = next(output.glob("formal_nl/*/latest.json"))
            previous_pointer = latest_path.read_bytes()

            failed = client.post("/formal-nl", data={"id": "IP_A", "formal_nl_root": str(root / "missing")})

            self.assertEqual(failed.status_code, 400)
            self.assertIn("上次成功盘点仍保留".encode(), failed.data)
            self.assertIn("lib_NL2.5_3".encode(), failed.data)
            self.assertEqual(latest_path.read_bytes(), previous_pointer)


if __name__ == "__main__":
    unittest.main()
