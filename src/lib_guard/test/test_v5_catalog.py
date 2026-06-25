from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


class V5CatalogTest(unittest.TestCase):
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
            diff_html = Path(new_version["diff"]["adjacent_diff_dir"]).parent / "diff_html" / "index.html"
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
                            {"path": "lib/ucie_ss_0p72v_125c.lib", "file_type": "liberty", "corner": {"process": "ss", "voltage": "0.72v", "temperature": "125c"}},
                            {"path": "db/ucie_tt_0p80v_25c.db", "file_type": "db", "corner": {"process": "tt", "voltage": "0.80v", "temperature": "25c"}},
                            {"path": "sdc/ucie.sdc", "file_type": "sdc", "corner": None},
                            {"path": "upf/ucie.upf", "file_type": "upf", "corner": None},
                            {"path": "waiver/lint.waiver", "file_type": "waiver", "corner": None},
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
                        "stats": {"macro_count": 12, "pin_count": 16},
                        "macros": {f"UCIE_MACRO_{i:02d}": {"pin_count": i} for i in range(12)},
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
            }
            (scan_dir / "parser_results.json").write_text(json.dumps(parser_results, ensure_ascii=False), encoding="utf-8")
            (scan_dir / "parser_manifest.json").write_text(
                json.dumps(
                    {
                        "files": [
                            {"file": "lef/ucie.lef", "file_type": "lef", "parser_tasks": [{"parser_name": "LefParser", "result_status": "PASS", "result_path": "parser_results/lef/1.json"}]},
                            {"file": "sdc/ucie.sdc", "file_type": "sdc", "parser_tasks": [{"parser_name": "SdcParser", "result_status": "PASS", "result_path": "parser_results/sdc/1.json"}]},
                            {"file": "upf/ucie.upf", "file_type": "upf", "parser_tasks": [{"parser_name": "UpfParser", "result_status": "PASS", "result_path": "parser_results/upf/1.json"}]},
                            {"file": "waiver/lint.waiver", "file_type": "waiver", "parser_tasks": [{"parser_name": "WaiverParser", "result_status": "PASS", "result_path": "parser_results/waiver/1.json"}]},
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (scan_dir / "summary" / "parser_quality.json").write_text(json.dumps({"status": "PASS", "parsers": []}), encoding="utf-8")
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
                        "removed_files": 0,
                        "changed_files": 3,
                        "view_changes": 2,
                        "release_evidence_changes": 1,
                        "manual_pairwise_tasks": 2,
                        "recommended_actions": ["Review SDC clock delta", "Review UPF isolation delta"],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (diff_dir / "file_diff.json").write_text(
                json.dumps(
                    {
                        "added": [{"path": "upf/new_domain.upf", "file_type": "upf"}],
                        "removed": [],
                        "changed": [
                            {"path": "sdc/ucie.sdc", "file_type": "sdc"},
                            {"path": "upf/ucie.upf", "file_type": "upf"},
                            {"path": "lef/ucie.lef", "file_type": "lef"},
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
            self.assertIn("Raw Version Detail", version_html)
            self.assertIn("Count-only + Corner Summary", version_html)
            self.assertIn("Parser Summary", version_html)
            self.assertLess(version_html.find("更新详情"), version_html.find("Raw Version Detail"))
            self.assertIn("更新详情（vs initial_20250601）", version_html)
            self.assertIn("incremental compare", version_html)
            self.assertIn("missing files are not treated as deletes", version_html)
            self.assertIn("Fixed lane reset timing", version_html)
            self.assertIn("changed_files", version_html)
            self.assertIn("sdc/ucie.sdc", version_html)
            self.assertIn("Review UPF isolation delta", version_html)
            self.assertIn("Parser Details", version_html)
            self.assertIn("UCIE_MACRO_09", version_html)
            self.assertNotIn("UCIE_MACRO_10", version_html)
            self.assertIn("LEF", version_html)
            self.assertIn("Macros", version_html)
            self.assertIn("SDC", version_html)
            self.assertIn("Clocks", version_html)
            self.assertIn("UPF", version_html)
            self.assertIn("Power Domains", version_html)
            self.assertIn("Waiver", version_html)
            self.assertIn("Waivers", version_html)
            self.assertNotIn(str(scan_html).replace("\\", "/"), version_html)
            self.assertNotIn(str(diff_html).replace("\\", "/"), version_html)
            self.assertNotIn("Selected Diff", version_html)
            self.assertNotIn("pairwise_html", version_html)
            self.assertNotIn("release_html", version_html)

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
