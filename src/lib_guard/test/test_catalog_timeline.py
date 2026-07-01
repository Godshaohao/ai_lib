from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


class CatalogTimelineTest(unittest.TestCase):
    def test_catalog_split_public_apis_exist(self) -> None:
        from lib_guard.render.catalog_report import render_catalog_html
        from lib_guard.render.catalog_workspace_report import (
            build_library_report_index_entry,
            render_catalog_index_page,
            render_library_workspace_page,
        )
        from lib_guard.render.version_detail_report import (
            build_version_update_detail_model,
            export_current_lib_diff_markdown,
            render_version_detail_page,
            render_version_update_detail_panel,
        )

        for item in [
            render_catalog_html,
            render_catalog_index_page,
            render_library_workspace_page,
            build_library_report_index_entry,
            render_version_detail_page,
            build_version_update_detail_model,
            render_version_update_detail_panel,
            export_current_lib_diff_markdown,
        ]:
            self.assertTrue(callable(item))

    def test_version_update_detail_model_exports_markdown_without_html_dependency(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            diff_dir = root / "diff"
            diff_dir.mkdir()
            (diff_dir / "diff_summary.json").write_text(
                json.dumps(
                    {
                        "status": "DIFF",
                        "changed_files": 2,
                        "recommended_actions": ["Review LEF macro delta"],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (diff_dir / "file_diff.json").write_text(
                json.dumps(
                    {
                        "changed": [
                            {"path": "lef/macro.lef", "file_type": "lef"},
                            {"path": "db/macro.db", "file_type": "db"},
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            raw = root / "raw"
            raw.mkdir()
            (raw / "release_note.txt").write_text("Updated macro shape.\n", encoding="utf-8")
            version = {
                "version_id": "patch_20260627",
                "raw_path": str(raw),
                "package_type": "PARTIAL_UPDATE",
                "previous_effective_version": "effective_20260620",
                "diff": {"adjacent_diff_dir": str(diff_dir), "adjacent_old_version": "effective_20260620"},
            }
            lib = {"library_id": "ip/ucie", "library_name": "ucie", "display_name": "ucie"}

            from lib_guard.render.version_detail_report import (
                build_version_update_detail_model,
                export_current_lib_diff_markdown,
                render_version_update_detail_panel,
            )

            model = build_version_update_detail_model(root / "html", lib, version)
            md_path = root / "current_lib_diff.md"
            export_current_lib_diff_markdown(model, md_path)
            panel_html = render_version_update_detail_panel(model)
            md_text = md_path.read_text(encoding="utf-8")
            md_path.unlink()
            panel_html_after_delete = render_version_update_detail_panel(model)

            self.assertEqual(model["schema_version"], "version_update_detail.v1")
            self.assertEqual(model["base_ref"], "previous_effective")
            self.assertEqual(model["base_version"], "effective_20260620")
            self.assertEqual(model["comparison_semantics"], "incremental")
            self.assertEqual(model["delete_semantics"], "out_of_scope_missing")
            self.assertEqual(model["changed_files"], 2)
            self.assertIn("effective_20260620", panel_html)
            self.assertIn("2", panel_html)
            self.assertIn("effective_20260620", md_text)
            self.assertIn("changed_files: 2", md_text)
            self.assertIn("Metadata-only", panel_html)
            self.assertIn("lef/macro.lef", panel_html)
            self.assertNotIn("$PROJ/scripts/lg.csh fd ucie patch_20260627 db/macro.db", panel_html)
            self.assertEqual(panel_html, panel_html_after_delete)

    def test_version_update_detail_prefers_current_effective_over_diff_base(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            current_diff = root / "current_diff"
            stale_diff = root / "stale_diff"
            current_diff.mkdir()
            stale_diff.mkdir()
            (current_diff / "diff_summary.json").write_text(
                json.dumps({"status": "DIFF", "changed_files": 1, "view_changes": 1}, ensure_ascii=False),
                encoding="utf-8",
            )
            (current_diff / "view_diff.json").write_text(json.dumps({"summary": {"changed": 1}}, ensure_ascii=False), encoding="utf-8")
            (current_diff / "type_diff.json").write_text(json.dumps({"summary": {"changed_types": 1}}, ensure_ascii=False), encoding="utf-8")
            (current_diff / "release_readiness_diff.json").write_text(json.dumps({"status": "PASS"}, ensure_ascii=False), encoding="utf-8")
            (current_diff / "diff_issues.json").write_text(json.dumps({"issues": [{"category": "view_diff"}]}, ensure_ascii=False), encoding="utf-8")
            (current_diff / "file_diff.json").write_text(
                json.dumps({"changed": [{"path": "lef/macro.lef", "file_type": "lef"}]}, ensure_ascii=False),
                encoding="utf-8",
            )
            (stale_diff / "diff_summary.json").write_text(json.dumps({"status": "SAME"}, ensure_ascii=False), encoding="utf-8")

            from lib_guard.render.version_detail_report import build_version_update_detail_model

            model = build_version_update_detail_model(
                root / "html",
                {"library_id": "ip/ucie", "library_name": "ucie"},
                {
                    "version_id": "patch_20260628",
                    "current_effective_ref": "effective_current",
                    "diff": {
                        "base_version": "stale_base",
                        "base_source": "adjacent",
                        "base_diff_dir": str(stale_diff),
                        "current_effective_diff_dir": str(current_diff),
                        "adjacent_old_version": "adjacent_only_fallback",
                    },
                },
            )

            self.assertEqual(model["base_ref"], "current_effective")
            self.assertEqual(model["base_version"], "effective_current")
            self.assertEqual(model["base_source"], "current_effective_ref")
            self.assertEqual(model["status"], "CHANGED")
            self.assertEqual(model["diff_summary"]["view_changes"], 1)
            self.assertEqual(model["view_diff"]["summary"]["changed"], 1)
            self.assertEqual(model["type_diff"]["summary"]["changed_types"], 1)
            self.assertEqual(model["release_readiness_diff"]["status"], "PASS")
            self.assertEqual(model["diff_issues"]["issues"][0]["category"], "view_diff")

    def test_version_detail_needs_base_and_does_not_auto_export_markdown(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            out = root / "html"

            from lib_guard.render.version_detail_report import build_version_update_detail_model, render_version_detail_page

            lib = {"library_id": "ip/ucie", "library_name": "ucie"}
            version = {"version_id": "orphan_20260628"}
            model = build_version_update_detail_model(out, lib, version)
            page = Path(render_version_detail_page(out, lib, version))
            html = page.read_text(encoding="utf-8")

            self.assertEqual(model["status"], "NEEDS_BASE_CONFIRM")
            self.assertIn("NEEDS_BASE_CONFIRM", html)
            self.assertNotIn("NO_DIFF_SUMMARY", html)
            self.assertNotIn("Comparison Review 是唯一 diff 入口", html)
            self.assertFalse((page.parent / "current_lib_diff.md").exists())

    def test_catalog_scan_library_refresh_keeps_other_libraries(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            raw = root / "raw"
            out = root / "catalog"
            for rel in ["ucie/initial_20250601", "pcie/stable_20250601"]:
                path = raw / rel
                path.mkdir(parents=True)
                (path / "top.v").write_text("module top; endmodule\n", encoding="utf-8")

            from lib_guard.catalog.index import scan_catalog

            initial = scan_catalog(raw, out_dir=out, library_type="ip")["catalog"]
            self.assertEqual(initial["summary"]["library_count"], 2)

            new_ucie = raw / "ucie" / "stable_20250608"
            new_ucie.mkdir(parents=True)
            (new_ucie / "top.v").write_text("module top2; endmodule\n", encoding="utf-8")

            refreshed = scan_catalog(raw, out_dir=out, library_type="ip", library="ucie")["catalog"]
            names = {lib["library_name"]: lib for lib in refreshed["libraries"]}
            self.assertEqual(set(names), {"pcie", "ucie"})
            self.assertEqual({v["version_id"] for v in names["pcie"]["versions"]}, {"stable_20250601"})
            self.assertIn("stable_20250608", {v["version_id"] for v in names["ucie"]["versions"]})
            self.assertEqual(refreshed["partial_refresh"]["library"], "ucie")

    def test_catalog_scan_writes_state_and_skips_unchanged_default_refresh(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            raw = root / "raw"
            out = root / "catalog"
            version = raw / "ucie" / "stable_20250608"
            version.mkdir(parents=True)
            (version / "top.v").write_text("module top; endmodule\n", encoding="utf-8")

            from lib_guard.catalog.index import scan_catalog

            first = scan_catalog(raw, out_dir=out, library_type="ip")
            self.assertFalse(first.get("skipped", False))
            state = json.loads((out / "catalog_state.json").read_text(encoding="utf-8"))
            self.assertEqual(state["raw_root"], str(raw))
            self.assertIn("ucie", state["libraries"])

            second = scan_catalog(raw, out_dir=out, library_type="ip")
            self.assertTrue(second.get("skipped"))
            self.assertEqual(second["catalog"]["incremental_refresh"]["mode"], "skipped")

            forced = scan_catalog(raw, out_dir=out, library_type="ip", force=True)
            self.assertFalse(forced.get("skipped", False))

    def test_catalog_marks_scan_stale_when_version_fingerprint_changes(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            raw = root / "raw"
            out = root / "catalog"
            version = raw / "ucie" / "stable_20250608"
            version.mkdir(parents=True)
            source = version / "top.v"
            source.write_text("module top; endmodule\n", encoding="utf-8")

            from lib_guard.catalog.index import scan_catalog, update_catalog_scan_status

            first = scan_catalog(raw, out_dir=out, library_type="ip", collect_evidence=True)["catalog"]
            version_key = "ip/ucie/stable_20250608"
            detected = first["libraries"][0]["versions"][0]["detected"]
            update_catalog_scan_status(
                out / "catalog.json",
                version_key=version_key,
                scan_dir=root / "scan_out" / "ucie" / "stable_20250608",
                scan_id="scan_1",
                status="PASS",
                input_fingerprint=detected["inventory"]["fingerprint"],
            )

            source.write_text("module top; wire changed; endmodule\n", encoding="utf-8")
            refreshed = scan_catalog(raw, out_dir=out, library_type="ip", collect_evidence=True, force=True)["catalog"]
            version_after = refreshed["libraries"][0]["versions"][0]

            self.assertEqual(version_after["scan"]["status"], "STALE_SCAN")
            self.assertEqual(version_after["scan"]["stale_reason"], "version_fingerprint_changed")
            self.assertNotEqual(version_after["scan"]["input_fingerprint"], version_after["detected"]["inventory"]["fingerprint"])

    def test_catalog_scan_uses_library_map_and_alias_resolution(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            raw = root / "raw"
            out = root / "catalog"
            library_root = raw / "vendorA" / "analog_ip" / "UVIP"
            for rel in ["initial_20250601", "stable_20250608"]:
                version = library_root / rel
                version.mkdir(parents=True)
                (version / "rtl").mkdir()
                (version / "rtl" / "top.v").write_text("module top; endmodule\n", encoding="utf-8")

            library_map = root / "library_map.yml"
            library_map.write_text(
                "\n".join(
                    [
                        "libraries:",
                        "  vendorA.analog_ip.UVIP:",
                        "    root: raw/vendorA/analog_ip/UVIP",
                        "    display_name: UVIP",
                        "    vendor: vendorA",
                        "    category: analog_ip",
                        "    library_type: ip",
                        "    aliases:",
                        "      - ucie",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            policy = root / "catalog_policy.json"
            policy.write_text(
                json.dumps(
                    {
                        "library_type": "ip",
                        "discovery": {
                            "library_map": str(library_map),
                            "pattern_fallback": False,
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            from lib_guard.catalog.index import find_catalog_version, scan_catalog

            result = scan_catalog(raw, out_dir=out, library_type="ip", policy_path=policy)
            catalog = result["catalog"]
            self.assertEqual(catalog["summary"]["library_count"], 1)
            lib = catalog["libraries"][0]
            self.assertEqual(lib["library_id"], "ip/vendorA.analog_ip.UVIP")
            self.assertEqual(lib["library_name"], "vendorA.analog_ip.UVIP")
            self.assertEqual(lib["display_name"], "UVIP")
            self.assertEqual(lib["aliases"], ["ucie"])
            self.assertEqual(lib["vendor"], "vendorA")
            self.assertEqual(lib["category"], "analog_ip")
            self.assertEqual(Path(lib["library_root"]), library_root)

            version = {v["version_id"]: v for v in lib["versions"]}["stable_20250608"]
            self.assertEqual(Path(version["raw_path"]), library_root / "stable_20250608")
            self.assertEqual(Path(version["library_root"]), library_root)
            self.assertEqual(version["detected"]["discovery_source"], "library_map")
            self.assertEqual(version["detected"]["structure_rule"], "library_map:{version}")

            resolved = find_catalog_version(out / "catalog.json", "ucie", "stable_20250608")
            self.assertEqual(resolved["library_name"], "vendorA.analog_ip.UVIP")
            self.assertEqual(resolved["version_key"], "ip/vendorA.analog_ip.UVIP/stable_20250608")

    def test_catalog_scan_resolves_library_map_from_raw_root(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            raw = root / "raw"
            out = root / "catalog"
            policy_dir = root / "configs"
            library_root = raw / "vendorA" / "UVIP"
            version = library_root / "stable_20250608"
            version.mkdir(parents=True)
            (version / "rtl").mkdir()
            (version / "rtl" / "top.v").write_text("module top; endmodule\n", encoding="utf-8")

            (raw / "library_map.yml").write_text(
                "\n".join(
                    [
                        "libraries:",
                        "  vendorA.UVIP:",
                        "    root: vendorA/UVIP",
                        "    display_name: UVIP",
                        "    vendor: vendorA",
                        "    library_type: ip",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            policy_dir.mkdir()
            policy = policy_dir / "catalog_policy.json"
            policy.write_text(
                json.dumps(
                    {
                        "library_type": "ip",
                        "discovery": {
                            "library_map": "library_map.yml",
                            "pattern_fallback": False,
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            from lib_guard.catalog.index import scan_catalog

            result = scan_catalog(raw, out_dir=out, library_type="ip", policy_path=policy)
            catalog = result["catalog"]
            self.assertEqual(catalog["summary"]["library_count"], 1)
            lib = catalog["libraries"][0]
            self.assertEqual(lib["library_id"], "ip/vendorA.UVIP")
            self.assertEqual(Path(lib["library_root"]), library_root)
            self.assertEqual(lib["versions"][0]["version_id"], "stable_20250608")

    def test_catalog_scan_applies_manual_overrides_and_recommends_tasks(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            raw = Path(td) / "raw"
            work = Path(td) / "work"
            for rel in [
                "ucie/initial_20250501",
                "ucie/stable_20250601",
                "ucie/stable_20250608",
                "ucie/ad-hoc_fix_20250612",
            ]:
                path = raw / rel
                path.mkdir(parents=True)
                (path / "top.v").write_text("module top(input a); endmodule\n", encoding="utf-8")

            from lib_guard.catalog.index import apply_catalog_override, scan_catalog

            result = scan_catalog(raw, out_dir=work / "catalog", library_type="ip")
            self.assertEqual(result["status"], "PASS")
            catalog = result["catalog"]
            self.assertEqual(catalog["summary"]["library_count"], 1)
            self.assertEqual(catalog["summary"]["version_count"], 4)
            self.assertEqual(catalog["summary"]["stage_counts"]["stable"], 2)
            self.assertEqual(catalog["summary"]["stage_counts"]["ad-hoc"], 1)

            ucie = catalog["libraries"][0]
            self.assertEqual(ucie["library_id"], "ip/ucie")
            versions = {v["version_id"]: v for v in ucie["versions"]}
            self.assertEqual(versions["stable_20250608"]["lineage"]["parent_candidate"], "stable_20250601")
            self.assertEqual(versions["stable_20250608"]["lineage"]["base_candidate"], "initial_20250501")
            self.assertTrue(versions["ad-hoc_fix_20250612"]["manual_review"])
            self.assertIn("manual_review", {t["task_type"] for t in catalog["recommended_tasks"]})

            updated = apply_catalog_override(
                work / "catalog" / "catalog.json",
                version_key="ip/ucie/ad-hoc_fix_20250612",
                stage="ad-hoc",
                parent_version="stable_20250608",
                base_version="stable_20250608",
                note="人工确认归属 stable_20250608",
                updated_by="tester",
            )
            fixed = {
                v["version_id"]: v
                for lib in updated["catalog"]["libraries"]
                for v in lib["versions"]
            }["ad-hoc_fix_20250612"]
            self.assertFalse(fixed["manual_review"])
            self.assertEqual(fixed["lineage"]["parent_candidate"], "stable_20250608")
            self.assertEqual(fixed["lineage"]["source"], "manual")

    def test_catalog_render_writes_chinese_html_and_copyable_commands(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            raw = Path(td) / "raw"
            out = Path(td) / "catalog"
            (raw / "ucie" / "stable_20250608").mkdir(parents=True)
            (raw / "ucie" / "stable_20250608" / "top.v").write_text("module top; endmodule\n", encoding="utf-8")

            from lib_guard.catalog.index import render_catalog_html, scan_catalog

            scan_catalog(raw, out_dir=out, library_type="ip")
            result = render_catalog_html(out / "catalog.json", out / "html")

            self.assertEqual(result["status"], "PASS")
            html = (out / "html" / "index.html").read_text(encoding="utf-8")
            self.assertIn("Library Catalog", html)
            self.assertIn("Library Browser", html)
            self.assertNotIn("<aside", html)
            self.assertNotIn("class='sidebar'", html)
            self.assertIn("class='library-name-row'", html)
            self.assertIn("class='library-path-row'", html)
            self.assertIn("Catalog 总览", html)
            self.assertIn("Suggested Commands", html)
            self.assertIn("Trace Evidence", html)
            self.assertIn("面向 IP 使用者", html)
            self.assertIn("manager_tasks.json", html)
            self.assertIn("catalog_state.json", html)
            self.assertNotIn("review_tasks.json", html)
            self.assertNotIn("review_state.json", html)
            self.assertIn("主流程是获取库更新信息", html)
            self.assertNotIn("基线</b><em title='?'>?", html)
            self.assertNotIn("前版</b><em title='?'>?", html)
            self.assertNotIn("file-diff ", html)
            self.assertTrue((out / "html" / "catalog_state.json").exists())
            self.assertTrue((out / "html" / "manager_tasks.json").exists())
            self.assertFalse((out / "html" / "review_state.json").exists())
            self.assertFalse((out / "html" / "review_tasks.json").exists())
            self.assertFalse((out / "html" / "libraries" / "ip_ucie" / "diff_timeline.html").exists())
            self.assertFalse((out / "html" / "libraries" / "ip_ucie" / "diff_index.json").exists())
            self.assertTrue((out / "html" / "libraries" / "ip_ucie" / "versions" / "stable_20250608" / "index.html").exists())
            library_html = (out / "html" / "libraries" / "ip_ucie" / "index.html").read_text(encoding="utf-8")
            self.assertIn("Library Workspace", library_html)
            self.assertIn("Compare 索引", library_html)
            self.assertNotIn("diff_timeline.html", html + library_html)
            self.assertNotIn("done / total", library_html)

    def test_cli_catalog_scan_render_and_override(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            raw = Path(td) / "raw"
            out = Path(td) / "catalog"
            (raw / "ucie" / "unknown_drop").mkdir(parents=True)
            (raw / "ucie" / "unknown_drop" / "README.txt").write_text("drop\n", encoding="utf-8")

            from lib_guard.cli import main

            self.assertEqual(main(["catalog", "scan", "--root", str(raw), "--out", str(out), "--library-type", "ip"]), 0)
            self.assertTrue((out / "catalog.json").exists())
            self.assertEqual(
                main(
                    [
                        "catalog",
                        "override",
                        "--catalog",
                        str(out / "catalog.json"),
                        "--version",
                        "ip/ucie/unknown_drop",
                        "--stage",
                        "stable",
                        "--note",
                        "人工修正为 stable",
                    ]
                ),
                0,
            )
            self.assertEqual(main(["catalog", "render", "--catalog", str(out / "catalog.json"), "--out", str(out / "html")]), 0)
            catalog = json.loads((out / "catalog.json").read_text(encoding="utf-8"))
            version = catalog["libraries"][0]["versions"][0]
            self.assertEqual(version["stage"], "stable")
            self.assertFalse(version["manual_review"])
            self.assertTrue((out / "html" / "index.html").exists())

    def test_cli_run_and_compare_use_catalog_version_relationships(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            raw = Path(td) / "raw"
            work = Path(td) / "work"
            old = raw / "ucie" / "stable_20250601"
            new = raw / "ucie" / "stable_20250608"
            old.mkdir(parents=True)
            new.mkdir(parents=True)
            (old / "top.v").write_text("module top(a, data);\ninput a;\noutput [31:0] data;\nendmodule\n", encoding="utf-8")
            (new / "top.v").write_text("module top(data);\noutput [63:0] data;\nendmodule\n", encoding="utf-8")

            from lib_guard.cli import main

            catalog = work / "catalog" / "catalog.json"
            self.assertEqual(main(["catalog", "scan", "--root", str(raw), "--out", str(work / "catalog"), "--library-type", "ip"]), 0)
            for version in ["stable_20250601", "stable_20250608"]:
                self.assertEqual(
                    main(
                        [
                            "run",
                            "--catalog",
                            str(catalog),
                            "--library",
                            "ucie",
                            "--version",
                            version,
                            "--workdir",
                            str(work),
                            "--mode",
                            "signature",
                            "--parse-jobs",
                            "1",
                        ]
                    ),
                    0,
                )

            data = json.loads(catalog.read_text(encoding="utf-8"))
            versions = {
                version["version_id"]: version
                for lib in data["libraries"]
                for version in lib["versions"]
            }
            self.assertEqual(versions["stable_20250608"]["lineage"]["parent_candidate"], "stable_20250601")
            self.assertEqual(versions["stable_20250608"]["scan"]["status"], "SCANNED")
            self.assertTrue(Path(versions["stable_20250608"]["scan"]["scan_dir"]).exists())

            self.assertEqual(
                main(
                    [
                        "compare",
                        "--catalog",
                        str(catalog),
                        "--library",
                        "ucie",
                        "--new",
                        "stable_20250608",
                        "--mode",
                        "adjacent",
                        "--workdir",
                        str(work),
                    ]
                ),
                0,
            )
            data = json.loads(catalog.read_text(encoding="utf-8"))
            new_version = {
                version["version_id"]: version
                for lib in data["libraries"]
                for version in lib["versions"]
            }["stable_20250608"]
            self.assertEqual(new_version["diff"]["adjacent_status"], "DIFF_DONE")
            self.assertTrue(Path(new_version["diff"]["adjacent_diff_dir"]).exists())
            diff_html = Path(new_version["diff"]["adjacent_diff_html"])
            self.assertTrue(diff_html.exists())
            catalog_html = work / "catalog" / "html" / "libraries" / "ip_ucie" / "index.html"
            self.assertTrue(catalog_html.exists())
            catalog_text = catalog_html.read_text(encoding="utf-8")
            self.assertIn("Compare 索引", catalog_text)
            self.assertIn(str(diff_html).replace("\\", "/"), catalog_text)
            self.assertNotIn("diff_timeline.html", catalog_text)

            self.assertEqual(
                main(
                    [
                        "compare",
                        "--catalog",
                        str(catalog),
                        "--library",
                        "ucie",
                        "--new",
                        "stable_20250608",
                        "--base",
                        "stable_20250601",
                        "--workdir",
                        str(work),
                    ]
                ),
                0,
            )
            data = json.loads(catalog.read_text(encoding="utf-8"))
            new_version = {
                version["version_id"]: version
                for lib in data["libraries"]
                for version in lib["versions"]
            }["stable_20250608"]
            self.assertEqual(new_version["diff"]["base_status"], "DIFF_DONE")
            self.assertEqual(new_version["diff"]["base_version"], "stable_20250601")
            self.assertTrue(Path(new_version["diff"]["base_diff_dir"]).exists())
            self.assertTrue(Path(new_version["diff"]["base_diff_html"]).exists())
            self.assertNotEqual(new_version["diff"]["adjacent_diff_html"], new_version["diff"]["base_diff_html"])

    def test_runtime_state_is_separate_and_catalog_html_links_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            raw = Path(td) / "raw"
            out = Path(td) / "catalog"
            scan_dir = Path(td) / "work" / "scan"
            scan_html = Path(td) / "work" / "scan_html" / "index.html"
            console_html = Path(td) / "work" / "console" / "index.html"
            diff_dir = Path(td) / "work" / "diff"
            diff_html = Path(td) / "work" / "diff_html" / "index.html"
            release_json = Path(td) / "work" / "scan" / "release" / "release_check.json"
            for p in [scan_dir, scan_html.parent, console_html.parent, diff_dir, diff_html.parent, release_json.parent]:
                p.mkdir(parents=True, exist_ok=True)
            scan_html.write_text("<html>scan</html>", encoding="utf-8")
            console_html.write_text("<html>console</html>", encoding="utf-8")
            diff_html.write_text("<html>diff</html>", encoding="utf-8")
            release_json.write_text("{}", encoding="utf-8")
            (scan_dir / "summary").mkdir(parents=True, exist_ok=True)
            (scan_dir / "scan_meta.json").write_text(
                json.dumps({"library_name": "ucie", "release_version": "stable_20250608", "package_type": "FULL_PACKAGE"}),
                encoding="utf-8",
            )
            (scan_dir / "file_inventory.json").write_text(
                json.dumps(
                    {
                        "files": [
                            {"path": "lef/ucie.lef", "file_type": "lef", "corner": None},
                            {"path": "cdl/ucie.cdl", "file_type": "cdl", "corner": None},
                            {"path": "lib/ucie_ss_0p72v_125c.lib", "file_type": "liberty", "corner": {"process": "ss", "voltage": "0.72v", "temperature": "125c"}},
                            {"path": "db/ucie_tt_0p80v_25c.db", "file_type": "db", "corner": {"process": "tt", "voltage": "0.80v", "temperature": "25c"}},
                            {"path": "sdc/ucie.sdc", "file_type": "sdc", "corner": None},
                            {"path": "upf/ucie.upf", "file_type": "upf", "corner": None},
                            {"path": "waiver/lint.waiver", "file_type": "waiver", "corner": None},
                            {"path": "doc/release_note.txt", "file_type": "doc", "role": "release_note", "doc_type": "release_note", "is_key_doc": True, "corner": None},
                        ],
                        "corner_filename_summary": {
                            "total_corner_files": 2,
                            "process_counts": {"ss": 1, "tt": 1},
                            "voltage_counts": {"0.72v": 1, "0.80v": 1},
                            "temperature_counts": {"125c": 1, "25c": 1},
                            "examples": [],
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            parser_results = {
                "parser_results/lef/1.json": {
                    "parser_name": "LefParser",
                    "file_type": "lef",
                    "file": "lef/ucie.lef",
                    "status": "PASS",
                    "data": {
                        "stats": {"macro_count": 12, "pin_count": 16, "layer_count": 1, "pin_rect_count": 8, "obs_rect_count": 1},
                                "layers": {
                                    "LVTN": {},
                                    "M1": {"type": "ROUTING", "direction": "HORIZONTAL", "width": 0.02},
                                },
                        "macros": {
                            f"UCIE_MACRO_{i:02d}": {
                                "class": "BLOCK",
                                "size": {"x": 10.0 + i, "y": 20.0},
                                "pin_count": i,
                                "pins": {
                                    "CLK": {"direction": "INPUT", "use": "SIGNAL", "layers": ["M1"], "rect_count": 1}
                                }
                                if i == 0
                                else {},
                            }
                            for i in range(12)
                        },
                    },
                },
                "parser_results/cdl/1.json": {
                    "parser_name": "CdlParser",
                    "file_type": "cdl",
                    "file": "cdl/ucie.cdl",
                    "status": "PASS",
                    "data": {
                        "stats": {"subckt_count": 1, "pin_count": 4, "instance_count": 1},
                        "subckts": {
                            "UCIE_WRAP": {
                                "name": "UCIE_WRAP",
                                "pins": ["A", "Y", "VDD", "VSS"],
                                "pin_count": 4,
                                "instance_count": 1,
                                "instances": [{"name": "XINV", "kind": "subckt", "target": "INV", "pin_count": 4}],
                            }
                        },
                        "instances": [{"name": "XINV", "kind": "subckt", "target": "INV", "pin_count": 4}],
                    },
                },
                "parser_results/sdc/1.json": {
                    "parser_name": "SdcParser",
                    "file_type": "sdc",
                    "file": "sdc/ucie.sdc",
                    "status": "PASS",
                    "data": {"stats": {"clock_count": 2, "clock_group_count": 1, "load_count": 3, "uncertainty_count": 1}},
                },
                "parser_results/upf/1.json": {
                    "parser_name": "UpfParser",
                    "file_type": "upf",
                    "file": "upf/ucie.upf",
                    "status": "PASS",
                    "data": {"stats": {"power_domain_count": 2, "supply_count": 4, "isolation_count": 1}},
                },
                "parser_results/waiver/1.json": {
                    "parser_name": "WaiverParser",
                    "file_type": "waiver",
                    "file": "waiver/lint.waiver",
                    "status": "PASS",
                    "data": {"stats": {"waiver_count": 5}},
                },
                "parser_results/verilog/1.json": {
                    "parser_name": "VerilogParser",
                    "file_type": "verilog",
                    "file": "rtl/top.v",
                    "status": "PASS",
                    "data": {
                        "parse_strategy": "lightweight_rtl_interface",
                        "parsed_fields": ["module", "port", "direction", "width", "declared_range", "module_count", "port_count"],
                        "unparsed_features": ["instance", "parameter_value", "generate_block", "gate_netlist_connectivity"],
                        "stats": {"module_count": 1, "port_count": 3},
                        "modules": {
                            "top": {
                                "name": "top",
                                "ports": {
                                    "clk": {"direction": "input", "width": 1, "declared_range": None},
                                    "data": {"direction": "input", "width": 8, "declared_range": "[7:0]"},
                                    "done": {"direction": "output", "width": 1, "declared_range": None},
                                },
                            }
                        },
                    },
                },
            }
            (scan_dir / "parser_results.json").write_text(json.dumps(parser_results, ensure_ascii=False), encoding="utf-8")
            (scan_dir / "parser_manifest.json").write_text(
                json.dumps(
                    {
                        "files": [
                            {"file": "lef/ucie.lef", "file_type": "lef", "parser_tasks": [{"parser_name": "LefParser", "result_status": "PASS", "result_path": "parser_results/lef/1.json"}]},
                            {"file": "cdl/ucie.cdl", "file_type": "cdl", "parser_tasks": [{"parser_name": "CdlParser", "result_status": "PASS", "result_path": "parser_results/cdl/1.json"}]},
                            {"file": "sdc/ucie.sdc", "file_type": "sdc", "parser_tasks": [{"parser_name": "SdcParser", "result_status": "PASS", "result_path": "parser_results/sdc/1.json"}]},
                            {"file": "upf/ucie.upf", "file_type": "upf", "parser_tasks": [{"parser_name": "UpfParser", "result_status": "PASS", "result_path": "parser_results/upf/1.json"}]},
                            {"file": "waiver/lint.waiver", "file_type": "waiver", "parser_tasks": [{"parser_name": "WaiverParser", "result_status": "PASS", "result_path": "parser_results/waiver/1.json"}]},
                            {"file": "rtl/top.v", "file_type": "verilog", "parser_tasks": [{"parser_name": "VerilogParser", "result_status": "PASS", "result_path": "parser_results/verilog/1.json"}]},
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (scan_dir / "summary" / "parser_quality.json").write_text(json.dumps({"status": "PASS", "parsers": []}), encoding="utf-8")
            (scan_dir / "summary" / "release_readiness.json").write_text(
                json.dumps(
                    {
                        "doc_summary": {
                            "release_note_found": True,
                            "files": [
                                {
                                    "path": "doc/release_note.txt",
                                    "role": "release_note",
                                    "doc_type": "release_note",
                                    "summary": "Fixed lane reset timing and updated UPF isolation coverage.",
                                }
                            ],
                        }
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (raw / "ucie" / "stable_20250608").mkdir(parents=True)
            (raw / "ucie" / "stable_20250608" / "top.v").write_text("module top; endmodule\n", encoding="utf-8")
            (raw / "ucie" / "stable_20250608" / "doc").mkdir()
            (raw / "ucie" / "stable_20250608" / "doc" / "release_note.txt").write_text(
                "Fixed lane reset timing and updated UPF isolation coverage.\nSecond line stays in the summary.",
                encoding="utf-8",
            )
            (diff_dir / "diff_summary.json").write_text(
                json.dumps(
                    {
                        "status": "DIFF",
                        "risk_level": "warning",
                        "added_files": 1,
                        "removed_files": 1,
                        "changed_files": 14,
                        "view_changes": 2,
                        "release_evidence_changes": 1,
                        "manual_pairwise_tasks": 2,
                        "parser_regressions": 1,
                        "recommended_actions": ["Review SDC clock delta", "Review UPF isolation delta", "Review removed waiver"],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (diff_dir / "file_diff.json").write_text(
                json.dumps(
                    {
                        "added": [{"path": "upf/new_domain.upf", "file_type": "upf"}],
                        "removed": [{"path": "waiver/legacy.waiver", "file_type": "waiver"}],
                        "changed": [
                            {"path": "sdc/ucie.sdc", "file_type": "sdc"},
                            {"path": "upf/ucie.upf", "file_type": "upf"},
                            {"path": "lef/ucie.lef", "file_type": "lef"},
                            {"path": "db/ucie_tt_0p80v_25c.db", "file_type": "db"},
                            {"path": "rtl/top.v", "file_type": "verilog"},
                            {"path": "rtl/subsystem/lane0/reset_sync_with_a_very_long_relative_path_for_scroll_check.v", "file_type": "verilog"},
                            {"path": "rtl/subsystem/lane1/reset_sync_with_a_very_long_relative_path_for_scroll_check.v", "file_type": "verilog"},
                            {"path": "rtl/subsystem/lane2/reset_sync_with_a_very_long_relative_path_for_scroll_check.v", "file_type": "verilog"},
                            {"path": "rtl/subsystem/lane3/reset_sync_with_a_very_long_relative_path_for_scroll_check.v", "file_type": "verilog"},
                            {"path": "sdc/corners/ss_0p72v_125c/ucie_lane_constraints_with_long_relative_path.sdc", "file_type": "sdc"},
                            {"path": "sdc/corners/tt_0p80v_25c/ucie_lane_constraints_with_long_relative_path.sdc", "file_type": "sdc"},
                            {"path": "upf/domains/low_power/isolation_strategy_with_long_relative_path.upf", "file_type": "upf"},
                            {"path": "doc/release/deep_change_note_with_long_relative_path.md", "file_type": "doc"},
                            {"path": "waiver/lint/legacy_rule_replacement_with_long_relative_path.waiver", "file_type": "waiver"},
                            {"path": "lef/macros/ucie_macro_variant_with_long_relative_path.lef", "file_type": "lef"},
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            from lib_guard.catalog.index import (
                apply_catalog_override,
                render_catalog_html,
                scan_catalog,
                update_catalog_diff_status,
                update_catalog_release_status,
                update_catalog_scan_status,
            )

            scan_catalog(raw, out_dir=out, library_type="ip")
            catalog_path = out / "catalog.json"
            apply_catalog_override(
                catalog_path,
                version_key="ip/ucie/stable_20250608",
                package_type="PARTIAL_UPDATE",
                update_scope=["sdc", "upf", "lef"],
                standalone=False,
                base_required=True,
                base_full_version="stable_20250608",
                previous_effective_version="initial_20250601",
                compare_default="previous_effective",
            )
            update_catalog_scan_status(
                catalog_path,
                version_key="ip/ucie/stable_20250608",
                scan_dir=scan_dir,
                scan_id="scan_1",
                status="PASS",
                scan_html=scan_html,
                console_html=console_html,
            )
            update_catalog_diff_status(
                catalog_path,
                version_key="ip/ucie/stable_20250608",
                mode="adjacent",
                old_version="initial_20250601",
                diff_dir=diff_dir,
                status="DIFF",
                diff_html=diff_html,
            )
            update_catalog_release_status(
                catalog_path,
                version_key="ip/ucie/stable_20250608",
                action="check",
                status="PASS",
                result_path=release_json,
            )

            catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
            self.assertEqual(catalog.get("manual_overrides", {}).get("ip/ucie/stable_20250608", {}).get("package_type"), "PARTIAL_UPDATE")
            state = catalog["runtime_state"]["ip/ucie/stable_20250608"]
            self.assertEqual(state["scan"]["scan_html"], str(scan_html))
            self.assertEqual(state["scan"]["console_html"], str(console_html))
            self.assertEqual(state["diff"]["adjacent_diff_html"], str(diff_html))
            self.assertEqual(state["release"]["check_status"], "PASS")
            version = catalog["libraries"][0]["versions"][0]
            self.assertEqual(version["scan"]["status"], "SCANNED")
            self.assertEqual(version["scan"]["scan_html"], str(scan_html))

            result = render_catalog_html(catalog_path, out / "html")
            html_out = out / "html"
            html = (html_out / "index.html").read_text(encoding="utf-8")
            self.assertIn("report_index.json", html)
            self.assertNotIn(str(console_html), html)
            self.assertIn("Release", html)
            self.assertTrue((html_out / "index.html").exists())
            self.assertTrue((html_out / "libraries" / "ip_ucie" / "index.html").exists())
            self.assertTrue((html_out / "libraries" / "ip_ucie" / "versions" / "stable_20250608" / "index.html").exists())
            self.assertTrue((html_out / "report_index.json").exists())
            self.assertTrue((html_out / "catalog_state.json").exists())
            self.assertTrue((html_out / "manager_tasks.json").exists())
            report_index = json.loads(Path(result["report_index"]).read_text(encoding="utf-8"))
            report_blob = json.dumps(report_index, ensure_ascii=False)
            self.assertIn(Path(os.path.relpath(scan_html, html_out)).as_posix(), report_blob)
            self.assertIn(Path(os.path.relpath(diff_html, html_out)).as_posix(), report_blob)
            catalog_state = json.loads((out / "html" / "catalog_state.json").read_text(encoding="utf-8"))
            review_version = catalog_state["libraries"][0]["versions"][0]
            self.assertEqual(review_version["scan_status"], "SCAN_PASS")
            self.assertEqual(review_version["diff_status"], "DIFF_REVIEW")
            self.assertEqual(review_version["release_status"], "RELEASE_READY")
            library_html = (html_out / "libraries" / "ip_ucie" / "index.html").read_text(encoding="utf-8")
            self.assertIn("Library Version Timeline", library_html)
            self.assertIn("latest_effective_ref", library_html)
            self.assertIn("Compare 索引", library_html)
            version_html = (html_out / "libraries" / "ip_ucie" / "versions" / "stable_20250608" / "index.html").read_text(encoding="utf-8")
            self.assertIn("版本审查总览", version_html)
            self.assertIn("版本上下文", version_html)
            self.assertIn("绝对 Raw 路径", version_html)
            self.assertIn(str(raw / "ucie" / "stable_20250608"), version_html)
            self.assertLess(version_html.find("版本审查总览"), version_html.find("更新详情"))
            self.assertNotIn(f"<b>Raw Path</b><em>{raw / 'ucie' / 'stable_20250608'}</em>", version_html)
            self.assertIn("大文件与 PVT Corner", version_html)
            self.assertIn("Parser 覆盖汇总", version_html)
            self.assertIn("对比前检查", version_html)
            self.assertIn("原始证据", version_html)
            self.assertLess(version_html.find("更新详情"), version_html.find("证据质量"))
            self.assertIn("更新详情（vs previous_effective / initial_20250601）", version_html)
            self.assertIn("增量对比 (incremental compare)", version_html)
            self.assertIn("缺失文件不视为删除", version_html)
            self.assertIn("Markdown 导出", version_html)
            self.assertIn("Fixed lane reset timing", version_html)
            self.assertIn("Release note</div><div class='metric-value'>1", version_html)
            self.assertIn("version-scroll-table metric-scroll", version_html)
            self.assertIn("version-scroll-table change-scroll", version_html)
            self.assertIn("faceted-table-tools", version_html)
            self.assertIn("id='tbl-change-scroll'", version_html)
            self.assertIn("data-filter-columns='0:变化|1:类型|3:审查级别'", version_html)
            self.assertIn("id='parser-aggregate'", version_html)
            self.assertIn("applyTableFilters", version_html)
            self.assertIn("height:420px", version_html)
            self.assertIn("min-width:1800px", version_html)
            self.assertIn("removed_files", version_html)
            self.assertIn("parser_regressions", version_html)
            self.assertIn("changed_files", version_html)
            self.assertIn("变化文件", version_html)
            self.assertIn("建议动作", version_html)
            self.assertNotIn("NO_DIFF_SUMMARY", version_html)
            self.assertNotIn("暂无自动 diff 结果", version_html)
            self.assertNotIn("暂无文件级 diff 明细", version_html)
            self.assertNotIn("暂无推荐动作", version_html)
            self.assertIn("upf/new_domain.upf", version_html)
            self.assertIn("waiver/legacy.waiver", version_html)
            self.assertIn("db/ucie_tt_0p80v_25c.db", version_html)
            self.assertIn("Metadata-only", version_html)
            self.assertIn("rtl/top.v", version_html)
            self.assertIn("doc/release/deep_change_note_with_long_relative_path.md", version_html)
            self.assertIn("sdc/ucie.sdc", version_html)
            self.assertIn("Review UPF isolation delta", version_html)
            self.assertIn("Review removed waiver", version_html)
            self.assertIn("doc/release_note.txt", version_html)
            self.assertNotIn(str(raw / "ucie" / "stable_20250608" / "doc" / "release_note.txt"), version_html)
            self.assertNotIn("summary/dashboard_summary.json", version_html)
            self.assertNotIn("summary rebuild", version_html)
            self.assertIn("Parser Details", version_html)
            self.assertIn("UCIE_MACRO_09", version_html)
            self.assertNotIn("UCIE_MACRO_10", version_html)
            self.assertIn("LEF", version_html)
            self.assertIn("Macros", version_html)
            self.assertIn("Used Layers", version_html)
            self.assertIn("Pin Directions", version_html)
            self.assertIn("INPUT:1", version_html)
            self.assertIn("Layer Types", version_html)
            self.assertIn("ROUTING:1", version_html)
            self.assertIn("Top Layers", version_html)
            self.assertIn("M1", version_html)
            self.assertIn("CDL", version_html)
            self.assertIn("Subckts", version_html)
            self.assertIn("Instances", version_html)
            self.assertIn("UCIE_WRAP", version_html)
            self.assertIn("XINV", version_html)
            self.assertIn("SDC", version_html)
            self.assertIn("Clocks", version_html)
            self.assertIn("UPF", version_html)
            self.assertIn("Power Domains", version_html)
            self.assertIn("Waiver", version_html)
            self.assertIn("Waivers", version_html)
            self.assertIn("VERILOG", version_html)
            self.assertIn("Parsed Scope", version_html)
            self.assertIn("module, port, direction, width, declared_range, module_count, port_count", version_html)
            self.assertIn("Not Parsed", version_html)
            self.assertIn("instance, parameter_value, generate_block, gate_netlist_connectivity", version_html)
            self.assertNotIn("Defines", version_html)
            self.assertNotIn(str(scan_html).replace("\\", "/"), version_html)
            self.assertNotIn(str(diff_html).replace("\\", "/"), version_html)
            self.assertNotIn("Selected Diff", version_html)
            self.assertNotIn("Open comparison from Library Workspace", version_html)
            self.assertNotIn("comparison review lives in the library workspace", version_html)
            self.assertNotIn("Raw Version Detail", version_html)
            self.assertNotIn("Count-only + Corner Summary", version_html)
            self.assertNotIn("Parser Summary", version_html)
            self.assertNotIn("Pre-Diff Readiness", version_html)
            self.assertNotIn("File Diff 2/5", version_html)
            self.assertNotIn("done/total", version_html)
            self.assertNotIn("pairwise_html", version_html)
            self.assertNotIn("release_html", version_html)

    def test_version_detail_shows_delivery_view_coverage_and_parser_meaning(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            raw = root / "raw" / "asap7"
            scan_dir = root / "scan"
            out = root / "html"
            raw.mkdir(parents=True)
            (scan_dir / "summary").mkdir(parents=True)
            (scan_dir / "parser_results" / "verilog").mkdir(parents=True)
            inventory = {
                "files": [
                    {"path": "verilog/fakeram7_128x64.v", "file_type": "verilog", "role": "verilog"},
                    {"path": "lef/fakeram7_128x64.lef", "file_type": "lef", "role": "lef"},
                    {"path": "lib/fakeram7_tt.lib.gz", "file_type": "liberty", "role": "liberty"},
                    {"path": "gds/fakeram7.gds", "file_type": "gds", "role": "gds", "is_large_hash_skipped": True, "hash_reason": "heavy_eda_or_archive_extension"},
                    {"path": "constraints.sdc", "file_type": "sdc", "role": "sdc"},
                    {"path": "openRoad/pdn.cfg", "file_type": "flow_config", "role": "flow_config"},
                    {"path": "drc/asap7.lydrc", "file_type": "tech_config", "role": "drc_rule"},
                    {"path": "README.md", "file_type": "doc", "role": "readme"},
                    {"path": "misc/unclassified.foo", "file_type": "unknown", "role": "unknown"},
                    {"path": "LICENSE_BUILD_RUN_SCRIPTS", "file_type": "unknown", "role": "unknown"},
                ],
                "corner_filename_summary": {
                    "total_corner_files": 1,
                    "process_counts": {"tt": 1},
                    "voltage_counts": {},
                    "temperature_counts": {},
                    "examples": [
                        {
                            "file": "lib/fakeram7_tt.lib.gz",
                            "file_type": "liberty",
                            "corner": {"process": "tt", "voltage": None, "temperature": None},
                        }
                    ],
                },
            }
            (scan_dir / "file_inventory.json").write_text(json.dumps(inventory, ensure_ascii=False), encoding="utf-8")
            (scan_dir / "parser_manifest.json").write_text(
                json.dumps(
                    {
                        "files": [
                            {
                                "file": "yoSys/cells_adders_L.v",
                                "file_type": "verilog",
                                "parser_tasks": [
                                    {
                                        "parser_name": "VerilogParser",
                                        "status": "PASS",
                                        "result_status": "PASS",
                                        "result_path": "parser_results/verilog/cells_adders_l.json",
                                    }
                                ],
                            },
                            {
                                "file": "yoSys/cells_adders_R.v",
                                "file_type": "verilog",
                                "parser_tasks": [
                                    {
                                        "parser_name": "VerilogParser",
                                        "status": "PASS",
                                        "result_status": "PASS",
                                        "result_path": "parser_results/verilog/cells_adders_r.json",
                                    }
                                ],
                            },
                            {
                                "file": "lef/tech.lef",
                                "file_type": "lef",
                                "parser_tasks": [
                                    {
                                        "parser_name": "LefParser",
                                        "status": "PASS",
                                        "result_status": "PASS",
                                        "result_path": "parser_results/lef/tech.json",
                                    }
                                ],
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (scan_dir / "parser_results.json").write_text(
                json.dumps(
                    {
                        "parser_results/verilog/cells_adders_l.json": {
                            "status": "PASS",
                            "file": "yoSys/cells_adders_L.v",
                            "file_type": "verilog",
                            "data": {
                                "modules": {
                                    "_tech_fa": {
                                        "name": "_tech_fa",
                                    },
                                    "fakeram7_128x64": {
                                        "name": "fakeram7_128x64",
                                        "port_count": 4,
                                    },
                                    "OPENROAD_CLKGATE": {
                                        "name": "OPENROAD_CLKGATE",
                                        "port_count": 3,
                                    },
                                },
                                "stats": {"module_count": 2, "port_count": 7},
                                "parsed_fields": ["module", "port", "direction"],
                                "unparsed_features": ["instance", "always_block"],
                            },
                        },
                        "parser_results/verilog/cells_adders_r.json": {
                            "status": "PASS",
                            "file": "yoSys/cells_adders_R.v",
                            "file_type": "verilog",
                            "data": {
                                "modules": {
                                    "_tech_fa": {
                                        "name": "_tech_fa",
                                    },
                                },
                                "stats": {"module_count": 1, "port_count": 5},
                                "parsed_fields": ["module", "port", "direction"],
                                "unparsed_features": ["instance", "always_block"],
                            },
                        },
                        "parser_results/lef/tech.json": {
                            "status": "PASS",
                            "file": "lef/tech.lef",
                            "file_type": "lef",
                            "data": {
                                "layers": {
                                    "LVTN": {},
                                    "M1": {"type": "ROUTING", "direction": "HORIZONTAL", "width": 0.02},
                                },
                                "stats": {"macro_count": 0, "pin_count": 0, "layer_count": 2},
                            },
                        }
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (scan_dir / "summary" / "release_readiness.json").write_text(
                json.dumps(
                    {
                        "bundle_status": "PASS_WITH_WARNING",
                        "required_view_status": "PASS",
                        "release_level_candidate": "L1",
                        "components": [
                            {
                                "required_views": ["verilog", "lef", "liberty"],
                                "optional_views": ["gds", "sdc", "doc", "flow_config", "tech_config"],
                                "required_view_results": {
                                    "verilog": {"status": "PASS", "found": True, "parser_status": "PASS", "validation_level": "parsed_required"},
                                    "lef": {"status": "PASS", "found": True, "parser_status": "PASS", "validation_level": "parsed_required"},
                                    "liberty": {"status": "PASS", "found": True, "parser_status": "METADATA_ONLY", "validation_level": "metadata_required"},
                                },
                                "optional_view_results": {
                                    "gds": {"status": "PASS", "found": True, "parser_status": "METADATA_ONLY", "validation_level": "metadata_required"},
                                    "sdc": {"status": "PASS", "found": True, "parser_status": "PASS", "validation_level": "parsed_required"},
                                    "doc": {"status": "INFO", "found": True, "parser_status": "DOC_REVIEW", "validation_level": "doc_review_required"},
                                    "flow_config": {"status": "WARNING", "found": True, "parser_status": "PASS_THROUGH", "validation_level": "manual_review"},
                                    "tech_config": {"status": "WARNING", "found": True, "parser_status": "PASS_THROUGH", "validation_level": "manual_review"},
                                },
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            version = {
                "version_id": "20260627_asap7",
                "raw_path": str(raw),
                "package_type": "FULL_PACKAGE",
                "scan": {"scan_dir": str(scan_dir), "scan_id": "scan_asap7"},
            }
            lib = {
                "library_id": "ip/vendor_A.openroad_platform.openroad_asap7",
                "library_name": "vendor_A.openroad_platform.openroad_asap7",
                "display_name": "openroad_asap7",
            }

            from lib_guard.render.version_detail_report import render_version_detail_page

            page = Path(render_version_detail_page(out, lib, version))
            html = page.read_text(encoding="utf-8")

            self.assertIn("交付 View 覆盖", html)
            self.assertIn("完整性判断", html)
            self.assertIn("必需", html)
            self.assertIn("可选", html)
            self.assertIn("rtl / verilog", html)
            self.assertIn("lib / liberty", html)
            self.assertIn("flow / flow_config", html)
            self.assertIn("tech / tech_config", html)
            self.assertIn("未知 / 待确认", html)
            self.assertIn("未知文件细分", html)
            self.assertIn("无扩展名", html)
            self.assertIn(".foo", html)
            self.assertIn("misc/unclassified.foo", html)
            self.assertIn("LICENSE_BUILD_RUN_SCRIPTS", html)
            self.assertIn("大文件与 PVT Corner", html)
            self.assertIn("GDS/SPEF/Liberty/DB", html)
            self.assertIn("PVT Corner 明细", html)
            self.assertIn("corner-detail-scroll", html)
            self.assertIn("id='count-only-files'", html)
            self.assertIn("id='tbl-view-coverage-scroll'", html)
            self.assertIn("data-filter-columns='0:View / Scope|1:要求|3:状态|4:Parser|5:校验级别'", html)
            self.assertNotIn("只计数视图与 Corner 汇总", html)
            self.assertNotIn("重文件", html)
            self.assertIn("代表对象", html)
            self.assertIn("来源文件", html)
            self.assertIn("审查含义", html)
            self.assertIn("macro_stub", html)
            self.assertIn("clock_gate", html)
            self.assertIn("yosys_cell_model", html)
            self.assertNotIn("tech_cell", html)
            self.assertIn("另有 1 个来源", html)
            self.assertIn("module declaration", html)
            self.assertEqual(html.count("<td>_tech_fa</td>"), 1)
            self.assertIn("fakeram7_128x64", html)
            self.assertIn("yoSys/cells_adders_L.v", html)
            self.assertNotIn("<td>LVTN</td><td><code>lef/tech.lef</code></td><td>routing_layer</td><td>LVTN</td>", html)
            self.assertIn("<td>LVTN</td><td><code>lef/tech.lef</code></td><td>tech_layer</td><td><span class='muted'>-</span></td>", html)
            self.assertIn("type=ROUTING, direction=HORIZONTAL, width=0.02", html)
            self.assertLess(html.index("<td>M1</td>"), html.index("<td>LVTN</td>"))

    def test_version_detail_empty_raw_scan_explains_partial_update_context(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            raw = root / "raw" / "sky130ram_update"
            scan_dir = root / "scan"
            out = root / "html"
            raw.mkdir(parents=True)
            scan_dir.mkdir()
            (raw / "release_note.txt").write_text("Only docs changed.\n", encoding="utf-8")
            (scan_dir / "file_inventory.json").write_text(
                json.dumps(
                    {
                        "files": [
                            {"path": "release_note.txt", "file_type": "doc"}
                        ],
                        "corner_filename_summary": {
                            "total_corner_files": 0,
                            "process_counts": {},
                            "voltage_counts": {},
                            "temperature_counts": {},
                            "examples": [],
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (scan_dir / "parser_manifest.json").write_text(
                json.dumps(
                    {
                        "files": [
                            {
                                "file": "release_note.txt",
                                "file_type": "doc",
                                "parser_tasks": [
                                    {
                                        "parser_name": None,
                                        "status": "SKIPPED",
                                        "result_status": "SKIPPED",
                                    }
                                ],
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (scan_dir / "parser_results.json").write_text("{}", encoding="utf-8")
            version = {
                "version_id": "20260626_sky130ram_update",
                "raw_path": str(raw),
                "package_type": "PARTIAL_UPDATE",
                "previous_effective_version": "20260619_sky130ram",
                "scan": {"scan_dir": str(scan_dir), "scan_id": "scan_empty"},
            }
            lib = {
                "library_id": "ip/vendor_C.openroad_platform.openroad_sky130ram",
                "library_name": "vendor_C.openroad_platform.openroad_sky130ram",
                "display_name": "openroad_sky130ram",
            }

            from lib_guard.render.version_detail_report import render_version_detail_page

            page = Path(render_version_detail_page(out, lib, version))
            html = page.read_text(encoding="utf-8")

            self.assertIn("版本审查总览", html)
            self.assertIn("当前版本是增量包", html)
            self.assertIn("本页 Raw Scan 只统计本次交付内容", html)
            self.assertIn("继承文件请查看 effective 或 base 视图", html)
            self.assertIn("当前 Raw Scan 没有发现大文件计数项", html)
            self.assertIn("当前 Scan 没有生成可展示的 Parser 结果", html)
            self.assertIn("scan_empty", html)
            self.assertNotIn("No parser summary is available for this version", html)
            self.assertNotIn("No count-only views", html)

    def test_policy_path_rules_and_inventory_evidence_reduce_misclassification(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            raw = Path(td) / "raw"
            out = Path(td) / "catalog"
            version = raw / "bundles" / "ucie" / "releases" / "stable_20250608"
            version.mkdir(parents=True)
            (version / "rtl").mkdir()
            (version / "rtl" / "top.v").write_text("module top; endmodule\n", encoding="utf-8")
            (version / "lef").mkdir()
            (version / "lef" / "macro.lef").write_text("MACRO M\nEND M\n", encoding="utf-8")
            (version / "README.md").write_text("ucie release\n", encoding="utf-8")
            policy = Path(td) / "catalog_policy.json"
            policy.write_text(
                json.dumps(
                    {
                        "library_type": "ip",
                        "version_path_rules": [
                            {"pattern": "bundles/{library}/releases/{version}"}
                        ],
                        "marker_files": ["README.md", "VERSION"],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            from lib_guard.catalog.index import scan_catalog

            catalog = scan_catalog(raw, out_dir=out, policy_path=policy, collect_evidence=True)["catalog"]
            lib = catalog["libraries"][0]
            self.assertEqual(lib["library_name"], "ucie")
            detected = lib["versions"][0]["detected"]
            self.assertEqual(lib["versions"][0]["version_id"], "stable_20250608")
            self.assertEqual(detected["structure_rule"], "bundles/{library}/releases/{version}")
            self.assertEqual(detected["inventory"]["file_type_counts"]["verilog"], 1)
            self.assertEqual(detected["inventory"]["file_type_counts"]["lef"], 1)
            self.assertIn("README.md", detected["markers"])
            self.assertGreaterEqual(detected["confidence"], 0.7)

    def test_flat_version_root_groups_by_policy_library_and_ignores_source_package(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            raw = Path(td) / "raw"
            out = Path(td) / "catalog"
            for rel in [
                "UCIe_stable_20250601",
                "UCIe_stable_20250608",
                "source_package",
            ]:
                path = raw / rel
                path.mkdir(parents=True)
                (path / "top.v").write_text("module top; endmodule\n", encoding="utf-8")
            policy = Path(td) / "catalog_policy.json"
            policy.write_text(
                json.dumps(
                    {
                        "library_type": "ip",
                        "library_name": "ucie",
                        "version_path_rules": [
                            {"pattern": "{version}"}
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            from lib_guard.catalog.index import scan_catalog

            catalog = scan_catalog(raw, out_dir=out, policy_path=policy)["catalog"]
            self.assertEqual(catalog["summary"]["library_count"], 1)
            self.assertEqual(catalog["summary"]["version_count"], 2)
            lib = catalog["libraries"][0]
            self.assertEqual(lib["library_id"], "ip/ucie")
            versions = {v["version_id"]: v for v in lib["versions"]}
            self.assertEqual(set(versions), {"UCIe_stable_20250601", "UCIe_stable_20250608"})
            self.assertEqual(versions["UCIe_stable_20250608"]["lineage"]["parent_candidate"], "UCIe_stable_20250601")

    def test_ucie_date_version_root_with_package_subdirs_builds_one_chain(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            raw = Path(td) / "ucie"
            out = Path(td) / "catalog"
            for rel in [
                "20250626_UCIe_UAXI_SP_MX_EVAL/UVIP_UCIe_UAXI_SP_MX_EVAL_syn_250626",
                "20250826_UCIe_UAXI_SP_X16_MX_Initial/UVIP_UCIe_UAXI_SP_X16_MX_Initial_250826",
                "source_package/UVIP_UCIe_source_package",
                "pages/catalog_html/libraries",
                "work/scan_out/ucie/20250626_UCIe_UAXI_SP_MX_EVAL",
                "diff/ucie/20250826_UCIe_UAXI_SP_X16_MX_Initial/adjacent",
            ]:
                path = raw / rel
                path.mkdir(parents=True)
                (path / "top.v").write_text("module top; endmodule\n", encoding="utf-8")

            from lib_guard.catalog.index import scan_catalog

            catalog = scan_catalog(raw, out_dir=out, library_type="ip")["catalog"]
            self.assertEqual(catalog["summary"]["library_count"], 1)
            self.assertEqual(catalog["summary"]["version_count"], 2)
            lib = catalog["libraries"][0]
            self.assertEqual(lib["library_id"], "ip/ucie")
            versions = {v["version_id"]: v for v in lib["versions"]}
            self.assertEqual(
                set(versions),
                {
                    "20250626_UCIe_UAXI_SP_MX_EVAL",
                    "20250826_UCIe_UAXI_SP_X16_MX_Initial",
                },
            )
            self.assertIsNone(versions["20250626_UCIe_UAXI_SP_MX_EVAL"]["lineage"]["parent_candidate"])
            self.assertEqual(versions["20250626_UCIe_UAXI_SP_MX_EVAL"]["stage"], "dated")
            self.assertEqual(
                versions["20250826_UCIe_UAXI_SP_X16_MX_Initial"]["lineage"]["parent_candidate"],
                "20250626_UCIe_UAXI_SP_MX_EVAL",
            )
            self.assertEqual(
                versions["20250826_UCIe_UAXI_SP_X16_MX_Initial"]["lineage"]["base_candidate"],
                "20250626_UCIe_UAXI_SP_MX_EVAL",
            )
            self.assertEqual(catalog["summary"]["stage_counts"]["dated"], 1)
            self.assertFalse(any(issue["category"] == "stage_unknown" for issue in catalog["issues"]))

    def test_cli_batch_and_catalog_release_bridge_update_runtime_state(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            raw = Path(td) / "raw"
            work = Path(td) / "work"
            old = raw / "ucie" / "stable_20250601"
            new = raw / "ucie" / "stable_20250608"
            old.mkdir(parents=True)
            new.mkdir(parents=True)
            (old / "top.v").write_text("module top(input a); endmodule\n", encoding="utf-8")
            (new / "top.v").write_text("module top(input a); endmodule\n", encoding="utf-8")
            release_policy = Path(td) / "release_policy.json"
            release_policy.write_text(
                json.dumps(
                    {
                        "required_views": {"ip": ["verilog"]},
                        "require_doc_types": [],
                        "require_signatures": False,
                        "require_summaries": False,
                        "release_link_mode": "copy",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            from lib_guard.cli import main

            catalog = work / "catalog" / "catalog.json"
            self.assertEqual(main(["catalog", "scan", "--root", str(raw), "--out", str(work / "catalog"), "--library-type", "ip"]), 0)
            self.assertEqual(
                main(
                    [
                        "run-batch",
                        "--catalog",
                        str(catalog),
                        "--library",
                        "ucie",
                        "--workdir",
                        str(work),
                        "--mode",
                        "signature",
                        "--only-missing",
                        "--limit",
                        "2",
                    ]
                ),
                0,
            )
            self.assertEqual(
                main(
                    [
                        "compare-batch",
                        "--catalog",
                        str(catalog),
                        "--library",
                        "ucie",
                        "--workdir",
                        str(work),
                        "--mode",
                        "adjacent",
                        "--only-ready",
                        "--limit",
                        "1",
                    ]
                ),
                0,
            )
            self.assertEqual(
                main(
                    [
                        "catalog",
                        "release-check",
                        "--catalog",
                        str(catalog),
                        "--library",
                        "ucie",
                        "--version",
                        "stable_20250608",
                        "--policy",
                        str(release_policy),
                        "--diff-mode",
                        "adjacent",
                    ]
                ),
                0,
            )
            self.assertEqual(
                main(
                    [
                        "catalog",
                        "release-link",
                        "--catalog",
                        str(catalog),
                        "--library",
                        "ucie",
                        "--version",
                        "stable_20250608",
                        "--policy",
                        str(release_policy),
                        "--release-root",
                        str(work / "release_area"),
                    ]
                ),
                0,
            )
            self.assertEqual(
                main(
                    [
                        "release-batch",
                        "--catalog",
                        str(catalog),
                        "--library",
                        "ucie",
                        "--version",
                        "stable_20250608",
                        "--policy",
                        str(release_policy),
                        "--release-root",
                        str(work / "release_area"),
                    ]
                ),
                0,
            )

            data = json.loads(catalog.read_text(encoding="utf-8"))
            runtime = data["runtime_state"]["ip/ucie/stable_20250608"]
            self.assertTrue(runtime["scan"]["scan_html"].endswith("index.html"))
            self.assertTrue(runtime["scan"]["console_html"].endswith("index.html"))
            self.assertTrue(runtime["diff"]["adjacent_diff_html"].endswith("index.html"))
            self.assertEqual(runtime["release"]["check_status"], "PASS")
            self.assertEqual(runtime["release"]["link_status"], "DRY_RUN")
            self.assertTrue(runtime["release"]["manifest_json"].endswith("release_manifest.json"))


if __name__ == "__main__":
    unittest.main()
