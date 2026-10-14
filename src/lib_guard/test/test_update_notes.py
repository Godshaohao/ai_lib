from __future__ import annotations

import json
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


class VersionUpdateNotesTest(unittest.TestCase):
    def test_update_note_save_load_and_history_are_separate_from_scan_facts(self) -> None:
        from lib_guard.review.update_notes import load_update_note, save_update_note

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            first = save_update_note(
                root,
                "vendor.demo",
                "v2",
                {
                    "use_suggestion": "条件使用",
                    "summary": "本版只影响物理抽象，时序视图未变化。",
                    "impact_areas": ["物理实现"],
                    "key_changes": ["LEF pin 顺序调整"],
                    "risks": ["需要确认宏列表是否同步"],
                    "must_check": ["确认 Innovus 读取 LEF 无报错"],
                    "evidence_refs": ["scan_report.html"],
                },
                updated_by="alice",
                publish=False,
            )
            second = save_update_note(
                root,
                "vendor.demo",
                "v2",
                {
                    "use_suggestion": "推荐使用",
                    "summary": "复核完成，可用于集成。",
                    "impact_areas": ["集成验证"],
                },
                updated_by="bob",
                publish=True,
            )
            loaded = load_update_note(root, "vendor.demo", "v2")

        self.assertEqual(first["status"], "draft")
        self.assertEqual(second["status"], "published")
        self.assertEqual(loaded["summary"], "复核完成，可用于集成。")
        self.assertEqual(loaded["updated_by"], "bob")
        self.assertEqual(loaded["history"][0]["summary"], "本版只影响物理抽象，时序视图未变化。")
        self.assertEqual(loaded["history"][0]["status"], "draft")

    def test_version_detail_places_human_note_before_machine_summary_and_warns_on_conflict(self) -> None:
        from lib_guard.review.update_notes import review_notes_root, save_update_note
        from lib_guard.render.version_detail_report import render_version_detail_page

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            html_root = root / "catalog" / "html"
            diff_dir = root / "diff"
            diff_dir.mkdir(parents=True)
            (diff_dir / "diff_summary.json").write_text(
                json.dumps({"status": "DIFF", "added_files": 1, "removed_files": 0, "changed_files": 0}, ensure_ascii=False),
                encoding="utf-8",
            )
            (diff_dir / "file_diff.json").write_text(
                json.dumps({"added": [{"path": "LEF/top.lef", "file_type": "lef"}]}, ensure_ascii=False),
                encoding="utf-8",
            )
            save_update_note(
                review_notes_root(catalog_html_out=html_root),
                "vendor.demo",
                "v2",
                {
                    "use_suggestion": "推荐使用",
                    "summary": "负责人确认本版可接入。",
                    "impact_areas": ["物理实现", "集成验证"],
                    "key_changes": ["新增 LEF 交付"],
                    "risks": ["仍需检查下游脚本引用"],
                    "must_check": ["确认 macro list 已更新"],
                },
                updated_by="owner",
                publish=True,
            )

            page = Path(
                render_version_detail_page(
                    html_root,
                    {"library_id": "ip/vendor.demo", "library_name": "vendor.demo"},
                    {
                        "version_id": "v2",
                        "raw_path": str(root / "raw" / "v2"),
                        "diff": {"base_version": "v1", "base_source": "explicit", "base_diff_dir": str(diff_dir)},
                    },
                )
            )
            html = page.read_text(encoding="utf-8")

        self.assertIn("版本更新备注", html)
        self.assertIn("负责人确认本版可接入。", html)
        self.assertIn("人工备注与机器证据不一致，需要复核", html)
        self.assertLess(html.index("版本更新备注"), html.index("版本摘要"))
        self.assertLess(html.index("版本更新备注"), html.index("视图变化矩阵"))

    def test_web_update_note_save_is_not_a_background_scan_or_compare_job(self) -> None:
        from lib_guard.web.app import create_app

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            workspace = root / "work"
            catalog = workspace / "catalog" / "catalog.json"
            catalog.parent.mkdir(parents=True)
            raw_version = root / "raw" / "vendor.demo" / "v1"
            raw_version.mkdir(parents=True)
            catalog.write_text(
                json.dumps(
                    {
                        "libraries": [
                            {
                                "library_id": "ip/vendor.demo",
                                "library_name": "vendor.demo",
                                "report_slug": "ip_vendor.demo",
                                "versions": [{"version_id": "v1", "raw_path": str(raw_version)}],
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            config = workspace / "lib_guard.yml"
            config.write_text(
                "\n".join(
                    [
                        f"workspace: {workspace}",
                        f"raw_root: {root / 'raw'}",
                        f"catalog: {catalog}",
                        f"catalog_html: {workspace / 'catalog' / 'html'}",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            jobs = workspace / "jobs"
            app = create_app(config_path=config, cwd=Path(__file__).resolve().parents[3], test_config={"TESTING": True, "job_root": str(jobs)})
            client = app.test_client()

            response = client.post(
                "/api/libraries/vendor.demo/versions/v1/update-note",
                json={
                    "status": "published",
                    "use_suggestion": "推荐使用",
                    "summary": "首版已由负责人确认，供集成同学先接入。",
                    "impact_areas": ["集成验证"],
                    "key_changes": ["首版交付"],
                    "must_check": ["确认引用路径"],
                    "updated_by": "owner",
                },
            )
            payload = response.get_json()
            loaded = client.get("/api/libraries/vendor.demo/versions/v1/update-note").get_json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["status"], "PASS")
        self.assertEqual(payload["note"]["summary"], "首版已由负责人确认，供集成同学先接入。")
        self.assertEqual(loaded["note"]["use_suggestion"], "推荐使用")
        self.assertEqual(list(jobs.glob("*")), [])
        self.assertEqual(payload["render"]["status"], "PASS")

    def test_web_update_note_rejects_overlong_input_without_overwriting_existing_note(self) -> None:
        from lib_guard.web.app import create_app

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            workspace = root / "work"
            catalog = workspace / "catalog" / "catalog.json"
            catalog.parent.mkdir(parents=True)
            raw_version = root / "raw" / "vendor.demo" / "v1"
            raw_version.mkdir(parents=True)
            catalog.write_text(
                json.dumps(
                    {
                        "libraries": [
                            {
                                "library_id": "ip/vendor.demo",
                                "library_name": "vendor.demo",
                                "report_slug": "ip_vendor.demo",
                                "versions": [{"version_id": "v1", "raw_path": str(raw_version)}],
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            config = workspace / "lib_guard.yml"
            config.write_text(
                "\n".join(
                    [
                        f"workspace: {workspace}",
                        f"raw_root: {root / 'raw'}",
                        f"catalog: {catalog}",
                        f"catalog_html: {workspace / 'catalog' / 'html'}",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            app = create_app(config_path=config, cwd=Path(__file__).resolve().parents[3], test_config={"TESTING": True})
            client = app.test_client()

            ok = client.post(
                "/api/libraries/vendor.demo/versions/v1/update-note",
                json={
                    "status": "published",
                    "summary": "这是一条有效备注。",
                    "updated_by": "owner",
                },
            )
            rejected = client.post(
                "/api/libraries/vendor.demo/versions/v1/update-note",
                json={
                    "status": "draft",
                    "summary": "x" * 5000,
                    "updated_by": "owner",
                },
            )
            loaded = client.get("/api/libraries/vendor.demo/versions/v1/update-note").get_json()

        self.assertEqual(ok.status_code, 200)
        self.assertEqual(rejected.status_code, 400)
        self.assertIn("备注摘要", rejected.get_json()["error"])
        self.assertEqual(loaded["note"]["summary"], "这是一条有效备注。")
        self.assertEqual(loaded["note"]["status"], "published")

    def test_concurrent_update_note_saves_preserve_recent_history(self) -> None:
        from lib_guard.review.update_notes import load_update_note, save_update_note

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)

            def save(index: int) -> None:
                save_update_note(
                    root,
                    "vendor.demo",
                    "v2",
                    {"summary": f"并发备注 {index}", "updated_by": f"user_{index}"},
                    updated_by=f"user_{index}",
                    publish=True,
                )

            with ThreadPoolExecutor(max_workers=12) as executor:
                futures = [executor.submit(save, index) for index in range(30)]
                for future in as_completed(futures):
                    future.result()

            loaded = load_update_note(root, "vendor.demo", "v2")

        self.assertEqual(loaded["status"], "published")
        self.assertEqual(len(loaded["history"]), 20)
        self.assertTrue(str(loaded["summary"]).startswith("并发备注 "))


if __name__ == "__main__":
    unittest.main()
