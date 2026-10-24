from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "effective_file_tracker.py"
SPEC = importlib.util.spec_from_file_location("effective_file_tracker", SCRIPT)
tracker = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(tracker)


class FormalNlLinkDiscoveryTests(unittest.TestCase):
    def test_view_detection_handles_nested_ip_view_directories_and_spice_suffix(self) -> None:
        self.assertEqual(
            tracker._view_for_path(Path("RM_IHPSG13_1P_64x16_c2/SPICE/RM_IHPSG13_1P_64x16_c2.spice")),
            "spice",
        )
        self.assertEqual(
            tracker._view_for_path(Path("RM_IHPSG13_1P_64x16_c2/SPICE/netlist.spice.gz")),
            "spice",
        )

    def test_candidate_filemap_accumulates_selected_full_and_incremental_chain(self) -> None:
        raw = {
            "inventories": {
                "V01": {"status": "COMPLETE", "files": [
                    {"view": "liberty", "relative_path": "LIB/a_tt.lib", "source_path": "/raw/V01/LIB/a_tt.lib"},
                    {"view": "liberty", "relative_path": "LIB/a_ff.lib", "source_path": "/raw/V01/LIB/a_ff.lib"},
                ]},
                "V02": {"status": "COMPLETE", "files": [
                    {"view": "lef", "relative_path": "LEF/a.lef", "source_path": "/raw/V02/LEF/a.lef"},
                ]},
                "V03": {"status": "COMPLETE", "files": [
                    {"view": "liberty", "relative_path": "LIB/a_tt.lib", "source_path": "/raw/V03/LIB/a_tt.lib"},
                ]},
                "V04": {"status": "COMPLETE", "files": [
                    {"view": "lef", "relative_path": "LEF/a.lef", "source_path": "/raw/V04/LEF/a.lef"},
                ]},
                "V05": {"status": "COMPLETE", "files": [
                    {"view": "gds", "relative_path": "GDS/a.gds", "source_path": "/raw/V05/GDS/a.gds"},
                ]},
            }
        }
        metadata = {
            "V01": {"package_type": "FULL_PACKAGE"},
            "V02": {"package_type": "PARTIAL_UPDATE", "previous_effective_version": "V01"},
            "V03": {"package_type": "HOTFIX", "previous_effective_version": "V02"},
            "V04": {"package_type": "PARTIAL_UPDATE", "previous_effective_version": "V03"},
            "V05": {"package_type": "PARTIAL_UPDATE", "previous_effective_version": "V04"},
        }
        result = tracker.build_candidate_filemap(raw, metadata, "V05")
        self.assertEqual(result["status"], "COMPLETE")
        self.assertEqual(result["chain"], ["V01", "V02", "V03", "V04", "V05"])
        by_path = {item["identity_path"]: item for item in result["files"]}
        self.assertEqual(set(by_path), {"liberty/a_tt.lib", "liberty/a_ff.lib", "lef/a.lef", "gds/a.gds"})
        self.assertEqual(by_path["liberty/a_tt.lib"]["source_version"], "V03")
        self.assertEqual(by_path["liberty/a_ff.lib"]["source_version"], "V01")
        self.assertEqual(by_path["liberty/a_ff.lib"]["candidate_operation"], "KEEP")
        self.assertEqual(by_path["lef/a.lef"]["source_version"], "V04")
        self.assertEqual(by_path["gds/a.gds"]["operation"], "ADD")
        self.assertEqual(by_path["liberty/a_tt.lib"]["operation"], "REPLACE")

    def test_candidate_filemap_does_not_infer_chain_from_numeric_version_order(self) -> None:
        raw = {"inventories": {"V02": {"status": "COMPLETE", "files": []}}}
        result = tracker.build_candidate_filemap(
            raw, {"V02": {"package_type": "PARTIAL_UPDATE"}}, "V02"
        )
        self.assertEqual(result["status"], "NEEDS_CONFIRMED_BASE")
        self.assertEqual(result["files"], [])

    def test_candidate_filemap_unknown_package_type_is_not_applied(self) -> None:
        raw = {"inventories": {"V01": {"status": "COMPLETE", "files": []}}}
        result = tracker.build_candidate_filemap(
            raw, {"V01": {"package_type": "UNKNOWN_PACKAGE"}}, "V01"
        )
        self.assertEqual(result["status"], "PACKAGE_TYPE_UNCONFIRMED")
        self.assertEqual(result["files"], [])

    def test_candidate_filemap_full_package_resets_and_reports_deletions_from_former_base(self) -> None:
        raw = {"inventories": {
            "V01": {"status": "COMPLETE", "files": [
                {"view": "lef", "relative_path": "LEF/old.lef", "source_path": "/raw/V01/LEF/old.lef"},
            ]},
            "V02": {"status": "COMPLETE", "files": [
                {"view": "lef", "relative_path": "LEF/new.lef", "source_path": "/raw/V02/LEF/new.lef"},
            ]},
        }}
        metadata = {
            "V01": {"package_type": "FULL_PACKAGE"},
            "V02": {"package_type": "FULL_PACKAGE", "previous_effective_version": "V01"},
        }
        result = tracker.build_candidate_filemap(raw, metadata, "V02")
        self.assertEqual(result["status"], "COMPLETE")
        self.assertEqual(result["chain"], ["V02"])
        self.assertEqual([item["identity_path"] for item in result["files"]], ["lef/new.lef"])
        self.assertEqual(result["operations"]["reset"], 1)

    def test_candidate_filemap_only_deletes_explicitly_declared_paths(self) -> None:
        raw = {"inventories": {
            "V01": {"status": "COMPLETE", "files": [
                {"view": "lef", "relative_path": "LEF/a.lef", "source_path": "/raw/V01/LEF/a.lef"},
            ]},
            "V02": {"status": "COMPLETE", "files": []},
        }}
        metadata = {
            "V01": {"package_type": "FULL_PACKAGE"},
            "V02": {"package_type": "PARTIAL_UPDATE", "previous_effective_version": "V01"},
        }
        result = tracker.build_candidate_filemap(raw, metadata, "V02", explicit_deletions={"V02": ["LEF/a.lef"]})
        self.assertEqual(result["status"], "COMPLETE")
        self.assertEqual(result["files"], [])
        self.assertEqual([item["operation"] for item in result["changes"]], ["RESET", "ADD", "DELETE"])

    def test_candidate_filemap_rejects_overlay_with_conflicting_full_base(self) -> None:
        raw = {"inventories": {
            "V01": {"status": "COMPLETE", "files": []},
            "V02": {"status": "COMPLETE", "files": []},
        }}
        metadata = {
            "V01": {"package_type": "FULL_PACKAGE"},
            "V02": {"package_type": "PARTIAL_UPDATE", "previous_effective_version": "V01",
                    "base_full_version": "V00"},
        }
        result = tracker.build_candidate_filemap(raw, metadata, "V02")
        self.assertEqual(result["status"], "BASE_FULL_MISMATCH")

    def test_candidate_filemap_resets_only_explicitly_reissued_view(self) -> None:
        raw = {"inventories": {
            "V01": {"status": "COMPLETE", "files": [
                {"view": "lef", "relative_path": "LEF/a.lef", "source_path": "/raw/V01/LEF/a.lef"},
                {"view": "lef", "relative_path": "LEF/b.lef", "source_path": "/raw/V01/LEF/b.lef"},
                {"view": "liberty", "relative_path": "LIB/a_tt.lib", "source_path": "/raw/V01/LIB/a_tt.lib"},
            ]},
            "V02": {"status": "COMPLETE", "files": [
                {"view": "lef", "relative_path": "LEF/a.lef", "source_path": "/raw/V02/LEF/a.lef"},
            ]},
        }}
        metadata = {
            "V01": {"package_type": "FULL_PACKAGE"},
            "V02": {"package_type": "PARTIAL_UPDATE", "previous_effective_version": "V01",
                    "base_full_version": "V01"},
        }
        result = tracker.build_candidate_filemap(raw, metadata, "V02", explicit_resets={"V02": ["lef"]})
        self.assertEqual(result["status"], "COMPLETE")
        self.assertEqual({item["identity_path"] for item in result["files"]},
                         {"lef/a.lef", "liberty/a_tt.lib"})
        self.assertEqual([item for item in result["changes"] if item.get("view")],
                         [{"version": "V02", "operation": "RESET", "view": "lef"}])

    def test_formal_to_candidate_comparison_reports_keep_replace_add_and_delete(self) -> None:
        formal = {"status": "COMPLETE", "files": [
            {"view": "lef", "relative_path": "LEF/a.lef", "source_path": "/raw/V01/LEF/a.lef", "raw_version": "V01"},
            {"view": "liberty", "relative_path": "LIB/a_tt.lib", "source_path": "/raw/V01/LIB/a_tt.lib", "raw_version": "V01"},
            {"view": "gds", "relative_path": "GDS/removed.gds", "source_path": "/raw/V01/GDS/removed.gds", "raw_version": "V01"},
        ]}
        candidate = {"status": "COMPLETE", "files": [
            {"view": "lef", "relative_path": "LEF/a.lef", "source_path": "/raw/V02/LEF/a.lef", "source_version": "V02"},
            {"view": "liberty", "relative_path": "LIB/a_tt.lib", "source_path": "/raw/V01/LIB/a_tt.lib", "source_version": "V01"},
            {"view": "db", "relative_path": "DB/a.db", "source_path": "/raw/V02/DB/a.db", "source_version": "V02"},
        ]}
        result = tracker.compare_formal_to_filemap(formal, candidate)
        self.assertEqual(result["counts"], {"ADD": 1, "DELETE": 1, "KEEP": 1, "REPLACE": 1})
        self.assertEqual({item["identity_path"]: item["operation"] for item in result["changes"]}, {
            "lef/a.lef": "REPLACE", "liberty/a_tt.lib": "KEEP",
            "gds/removed.gds": "DELETE", "db/a.db": "ADD",
        })

    def test_run_uses_catalog_chain_and_renders_formal_candidate_filemap(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            raw_root = base / "raw" / "demo_ip"
            v01, v02 = raw_root / "V01", raw_root / "V02"
            for root, files in ((v01, {"LEF/a.lef": "old", "LIB/a_tt.lib": "tt", "LIB/a_ff.lib": "ff"}),
                                (v02, {"LEF/a.lef": "new", "GDS/a.gds": "gds"})):
                for relative, content in files.items():
                    path = root / relative
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(content, encoding="utf-8")
            formal_root = base / "formal" / "lib_NL2.5_3" / "IP"
            for relative in ("LEF/a.lef", "LIB/a_tt.lib", "LIB/a_ff.lib"):
                link = formal_root / relative
                link.parent.mkdir(parents=True, exist_ok=True)
                link.symlink_to(v01 / relative)
            catalog = base / "catalog.json"
            catalog.write_text(json.dumps({"libraries": [{
                "library_id": "ip/demo_ip", "library_name": "demo_ip",
                "library_root": str(raw_root), "versions": [
                    {"version_id": "V01", "raw_path": str(v01), "package_type": "FULL_PACKAGE"},
                    {"version_id": "V02", "raw_path": str(v02), "package_type": "PARTIAL_UPDATE",
                     "previous_effective_version": "V01"},
                ],
            }]}), encoding="utf-8")
            config = base / "tracker.yml"
            config.write_text(
                f"library:\n  id: ip/demo_ip\n  root: {raw_root}\n  ip_directory_name: demo_ip\n  catalog: {catalog}\n"
                f"formal_nl:\n  root: {formal_root}\n"
                "output:\n  report_json: ./out/report.json\n  report_md: ./out/report.md\n",
                encoding="utf-8",
            )
            result = tracker.run(config)
            report = (base / "out" / "report.md").read_text(encoding="utf-8")

        self.assertEqual(result["candidate_filemap"]["status"], "COMPLETE")
        self.assertEqual(result["candidate_filemap"]["chain"], ["V01", "V02"])
        self.assertEqual(result["formal_candidate_comparison"]["counts"], {"KEEP": 2, "REPLACE": 1, "ADD": 1})
        self.assertEqual(result["chart_data"]["formal_candidate_operation_counts"], [
            {"operation": "ADD", "file_count": 1},
            {"operation": "KEEP", "file_count": 2},
            {"operation": "REPLACE", "file_count": 1},
        ])
        self.assertIn("正式文件与候选文件集合", report)
        self.assertIn("叠加链：`V01` → `V02`", report)
        self.assertNotIn("发布通过", report)

    def _pairing_fixture(self, base: Path, *, formal_names=None, raw_names=None):
        formal_names = formal_names or ["vendor_old/LEF/cell.lef"]
        raw_names = raw_names or ["vendor_new/lef/cell.lef"]
        old_root = base / "raw" / "v01"
        new_root = base / "raw" / "v02"
        old_files = []
        new_files = []
        formal_files = []
        for name in formal_names:
            source = old_root / name
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_text("old fixture", encoding="utf-8")
            formal_files.append({
                "view": "lef", "relative_path": f"LEF/{Path(name).name}",
                "source_path": str(source.resolve()), "published_path": f"/formal/LEF/{Path(name).name}",
                "raw_version": "v01",
            })
            old_files.append({"view": "lef", "relative_path": name,
                              "source_path": str(source.resolve())})
        for name in raw_names:
            source = new_root / name
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_text("new fixture", encoding="utf-8")
            new_files.append({"view": "lef", "relative_path": name,
                              "source_path": str(source.resolve())})
        return {
            "formal_scope": "SINGLE_STAGE",
            "matches": [{"nl_version": "lib_NL2.5_3"}],
            "inventories": {"lib_NL2.5_3": {"status": "COMPLETE", "files": formal_files}},
            "raw_library": {
                "root_path": str(base / "raw"),
                "version_candidates": {"latest": "v02", "next_latest": "v01"},
                "versions": [
                    {"version_id": "v02", "resolved_path": str(new_root.resolve())},
                    {"version_id": "v01", "resolved_path": str(old_root.resolve())},
                ],
                "inventories": {
                    "v02": {"status": "COMPLETE", "files": new_files},
                    "v01": {"status": "COMPLETE", "files": old_files},
                },
            },
        }

    def test_resolve_file_pairs_matches_same_view_relative_path_across_package_roots(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = self._pairing_fixture(Path(tmp))
            pairs = tracker.resolve_file_pairs(result)
        self.assertEqual(pairs["status"], "COMPLETE")
        self.assertEqual(len(pairs["pairs"]), 1)
        self.assertEqual(pairs["pairs"][0]["status"], "MATCHED")
        self.assertEqual(pairs["pairs"][0]["match_method"], "VIEW_RELATIVE_PATH")
        self.assertEqual(pairs["pairs"][0]["formal_source"]["raw_version"], "v01")
        self.assertTrue(pairs["pairs"][0]["raw_file"]["source_path"].endswith("v02/vendor_new/lef/cell.lef"))

    def test_resolve_file_pairs_returns_review_candidate_for_basename_only_match(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = self._pairing_fixture(
                Path(tmp), formal_names=["vendor_old/LEF/blocks/cell.lef"],
                raw_names=["vendor_new/lef/macros/cell.lef"],
            )
            pairs = tracker.resolve_file_pairs(result)
        self.assertEqual(pairs["pairs"][0]["status"], "REVIEW_CANDIDATE")
        self.assertEqual(pairs["pairs"][0]["match_method"], "VIEW_AND_BASENAME_CANDIDATE")
        self.assertIsNone(pairs["pairs"][0]["formal_source"])
        self.assertEqual(len(pairs["pairs"][0]["candidates"]), 1)

    def test_resolve_file_pairs_does_not_choose_between_duplicate_formal_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = self._pairing_fixture(
                Path(tmp), formal_names=["vendor_old/LEF/a/cell.lef", "vendor_old/LEF/b/cell.lef"],
                raw_names=["vendor_new/lef/cell.lef"],
            )
            pairs = tracker.resolve_file_pairs(result)
        self.assertEqual(pairs["pairs"][0]["status"], "AMBIGUOUS")
        self.assertIsNone(pairs["pairs"][0]["formal_source"])
        self.assertEqual(len(pairs["pairs"][0]["candidates"]), 2)

    def test_resolve_file_pairs_does_not_pair_across_views(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = self._pairing_fixture(Path(tmp))
            result["inventories"]["lib_NL2.5_3"]["files"][0]["view"] = "liberty"
            pairs = tracker.resolve_file_pairs(result)
        self.assertEqual(pairs["pairs"][0]["status"], "UNMATCHED")
        self.assertEqual(pairs["pairs"][0]["candidates"], [])

    def test_resolve_file_pairs_requires_explicit_stage_when_formal_scope_is_ambiguous(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = self._pairing_fixture(Path(tmp))
            result["formal_scope"] = "MULTI_STAGE_DISCOVERY"
            pairs = tracker.resolve_file_pairs(result)
        self.assertEqual(pairs["status"], "NEEDS_FORMAL_STAGE")
        self.assertEqual(pairs["pairs"], [])

    def test_resolve_file_pairs_requires_explicit_stage_for_multiple_matches(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = self._pairing_fixture(Path(tmp))
            result["matches"].append({"nl_version": "lib_NL2.5_2"})
            pairs = tracker.resolve_file_pairs(result)
        self.assertEqual(pairs["status"], "NEEDS_FORMAL_STAGE")
        self.assertEqual(pairs["pairs"], [])

    def test_resolve_file_pairs_reports_new_file_without_formal_counterpart(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = self._pairing_fixture(
                Path(tmp), formal_names=["vendor_old/LEF/old.lef"],
                raw_names=["vendor_new/lef/new.lef"],
            )
            pairs = tracker.resolve_file_pairs(result)
        self.assertEqual(pairs["summary"]["unmatched"], 1)
        self.assertEqual(pairs["pairs"][0]["status"], "UNMATCHED")
        self.assertIsNone(pairs["pairs"][0]["formal_source"])

    def test_resolve_file_pairs_counts_formal_sources_outside_raw_version_roots(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = self._pairing_fixture(Path(tmp))
            result["inventories"]["lib_NL2.5_3"]["files"][0]["raw_version"] = None
            pairs = tracker.resolve_file_pairs(result)
        self.assertEqual(pairs["summary"]["formal_sources_without_raw_origin"], 1)
        self.assertEqual(pairs["pairs"][0]["status"], "UNMATCHED")

    def test_root_level_compressed_lef_is_classified_as_lef(self) -> None:
        self.assertEqual(tracker._view_for_path(Path("phy.lef.gz")), "lef")

    def test_configured_root_can_be_one_formal_nl_ip_view_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            raw = base / "3rd_release" / "IP" / "demo_ip"
            formal_ip = base / "formal" / "lib_NL2.5_3" / "IP"
            for view, filename in (("LEF", "macro.lef"), ("LIB", "macro_TT.lib.gz"),
                                   ("DB", "macro_TT.db"), ("VERILOG", "macro.v")):
                source = raw / "v07" / view / filename
                source.parent.mkdir(parents=True, exist_ok=True)
                source.write_text("controlled fixture", encoding="utf-8")
                link = formal_ip / view / filename
                link.parent.mkdir(parents=True, exist_ok=True)
                link.symlink_to(source)
            config = base / "tracker.yml"
            config.write_text(
                "library:\n  root: ./3rd_release/IP/demo_ip\n  ip_directory_name: demo_ip\n"
                "formal_nl:\n  root: ./formal/lib_NL2.5_3/IP\n"
                "output:\n  report_json: ./out/report.json\n  report_md: ./out/report.md\n",
                encoding="utf-8",
            )

            result = tracker.run(config)
            report = (base / "out" / "report.md").read_text(encoding="utf-8")

        self.assertEqual(result["status"], "MATCHED")
        self.assertEqual(result["schema_version"], "formal_nl_ip_links.v5")
        self.assertEqual(result["report_status"], "COMPLETE")
        self.assertEqual(result["formal_scope"], "SINGLE_STAGE")
        self.assertEqual(result["file_pairs"]["summary"]["matched"], 4)
        self.assertEqual([(item["nl_version"], item["classification"]) for item in result["matches"]],
                         [("lib_NL2.5_3", "SELECTED_STAGE")])
        self.assertEqual(result["comparison"]["status"], "NOT_REQUESTED")
        self.assertEqual(result["inventories"]["lib_NL2.5_3"]["view_counts"],
                         {"db": 1, "lef": 1, "liberty": 1, "verilog": 1})
        self.assertIn("正式阶段：`lib_NL2.5_3`", report)
        self.assertIn("不进行正式阶段之间的比较", report)
        self.assertIn("正式路径 → 原始来源", report)
        self.assertIn("新 RAW 文件与正式来源配对", report)
        self.assertIn("唯一匹配 4", report)
        self.assertIn("`LEF/macro.lef`", report)
        self.assertIn("/v07/LEF/macro.lef", report)
        self.assertNotIn("最高编号", report)
        self.assertNotIn("次高", report)

    def test_formal_link_names_show_corner_and_lib_db_file_gaps(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            raw = base / "raw" / "demo_ip" / "v01"
            raw.mkdir(parents=True)
            formal = base / "formal" / "lib_NL2.5_3" / "IP"
            names = {
                "LIB": ["core_TT_SIGRCMIN_nldm.lib.gz", "core_SS_nldm.lib.gz", "misc.lib"],
                "DB": ["core_TT_SIGRCMIN_nldm.db", "core_FF_nldm.db"],
                "LEF": ["core.lef"],
            }
            for view, files in names.items():
                (formal / view).mkdir(parents=True)
                for name in files:
                    source = raw / name
                    source.write_text("fixture", encoding="utf-8")
                    (formal / view / name).symlink_to(source)
            foreign = base / "raw" / "other_ip" / "v01" / "foreign_SS.db"
            foreign.parent.mkdir(parents=True)
            foreign.write_text("fixture", encoding="utf-8")
            (formal / "DB" / foreign.name).symlink_to(foreign)
            config = base / "tracker.yml"
            config.write_text(
                "library:\n  root: ./raw/demo_ip\n  ip_directory_name: demo_ip\n"
                "formal_nl:\n  root: ./formal\n"
                "output:\n  report_json: ./out/report.json\n  report_md: ./out/report.md\n",
                encoding="utf-8",
            )

            result = tracker.run(config)
            report = (base / "out" / "report.md").read_text(encoding="utf-8")

        self.assertEqual(result["report_status"], "INCOMPLETE")
        audit = result["filename_coverage"]["lib_NL2.5_3"]
        self.assertEqual(audit["corner_counts"], {
            "db": {"FF": 1, "TT": 1},
            "liberty": {"SS": 1, "TT": 1, "未识别": 1},
        })
        self.assertEqual(
            [(row["key"], row["status"]) for row in audit["lib_db_pairs"]],
            [("core_ff_nldm", "DB_ONLY"), ("core_ss_nldm", "LIB_ONLY"),
             ("core_tt_sigrcmin_nldm", "PAIRED"), ("misc", "LIB_ONLY")],
        )
        self.assertNotIn("foreign_SS.db", report)
        file_paths = {item["relative_path"] for item in result["inventories"]["lib_NL2.5_3"]["files"]}
        self.assertIn("LIB/core_SS_nldm.lib.gz", file_paths)
        self.assertIn("DB/core_FF_nldm.db", file_paths)
        self.assertIn("配置的正式根不是单阶段 IP 目录", report)

    def test_filename_corner_conflict_and_duplicate_name_are_not_silent_matches(self) -> None:
        result = {"inventories": {"lib_NL3": {"files": [
            {"view": "liberty", "relative_path": "LIB/core_TT_SS.lib",
             "source_path": "/raw/old.lib"},
            {"view": "liberty", "relative_path": "LIB/core_TT_SS.lib.gz",
             "source_path": "/raw/new.lib.gz"},
            {"view": "db", "relative_path": "DB/core_TT_SS.db",
             "source_path": "/raw/core.db"},
            {"view": "liberty", "relative_path": "LIB/logic_FFPG_SIGRCMIN.lib",
             "source_path": "/raw/logic.lib"},
        ]}}}

        tracker.add_filename_coverage(result)

        audit = result["filename_coverage"]["lib_NL3"]
        self.assertEqual(audit["corner_counts"]["liberty"], {"FFPG": 1, "标签冲突": 2})
        self.assertEqual(audit["rc_corner_counts"]["liberty"], {"SIGRCMIN": 1, "未标注": 2})
        self.assertEqual(audit["lib_db_pairs"][0]["status"], "AMBIGUOUS")
        self.assertEqual(audit["lib_db_pairs"][1]["status"], "LIB_ONLY")

    def test_filename_coverage_keeps_fast_typ_slow_labels_as_written(self) -> None:
        result = {"inventories": {"lib_NL2.5_3": {"files": [
            {"view": "liberty", "relative_path": f"LIB/macro_{corner}_1p20V_25C.lib",
             "source_path": f"/raw/macro_{corner}.lib"}
            for corner in ("fast", "typ", "slow")
        ]}}}
        tracker.add_filename_coverage(result)
        self.assertEqual(
            result["filename_coverage"]["lib_NL2.5_3"]["corner_counts"]["liberty"],
            {"FAST": 1, "SLOW": 1, "TYP": 1},
        )

    def test_eleven_raw_versions_with_flat_formal_links_cli_and_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            raw = base / "3rd_release" / "IP" / "demo_ip"
            for number in range(1, 12):
                (raw / f"v{number:02d}").mkdir(parents=True)
            for number in (10, 11):
                version = raw / f"v{number:02d}"
                (version / "cell.lef").write_text(f"LEF {number}", encoding="utf-8")
                (version / "cell_tt.lib").write_text(f"LIB {number}", encoding="utf-8")
            (raw / "v11" / "README.md").write_text("not linked", encoding="utf-8")
            other = base / "3rd_release" / "IP" / "other_ip" / "v11"
            other.mkdir(parents=True)
            (other / "foreign.lef").write_text("other IP", encoding="utf-8")
            for nl, source_version in (("lib_NL2.9_0", "v10"), ("lib_NL2.10_0", "v11")):
                ip_area = base / "formal" / nl / "IP"
                (ip_area / "LEF").mkdir(parents=True)
                (ip_area / "LIB").mkdir()
                (ip_area / "LEF" / "cell.lef").symlink_to(raw / source_version / "cell.lef")
                (ip_area / "LIB" / "cell_tt.lib").symlink_to(raw / source_version / "cell_tt.lib")
                (ip_area / "LEF" / "foreign.lef").symlink_to(other / "foreign.lef")
            config = base / "tracker.yml"
            config.write_text(
                "library:\n  root: ./3rd_release/IP/demo_ip\n  ip_directory_name: demo_ip\n"
                "formal_nl:\n  root: ./formal\n"
                "output:\n  report_json: ./out/report.json\n  report_md: ./out/report.md\n",
                encoding="utf-8",
            )

            completed = subprocess.run(
                [sys.executable, str(SCRIPT), "--config", str(config)],
                cwd=base, text=True, capture_output=True, check=False,
            )
            saved = json.loads((base / "out" / "report.json").read_text(encoding="utf-8"))
            markdown = (base / "out" / "report.md").read_text(encoding="utf-8")

        self.assertEqual(completed.returncode, 1, completed.stderr)
        self.assertEqual(saved["status"], "MATCHED")
        self.assertEqual(saved["report_status"], "INCOMPLETE")
        self.assertEqual(saved["raw_library"]["version_count"], 11)
        self.assertEqual([item["nl_version"] for item in saved["matches"][:2]], ["lib_NL2.10_0", "lib_NL2.9_0"])
        self.assertEqual(set(saved["raw_library"]["inventories"]), {
            f"v{number:02}" for number in range(1, 12)
        })
        self.assertEqual(sum(item["inventory_status"] == "NOT_SCANNED" for item in saved["raw_library"]["versions"]), 0)
        self.assertEqual(saved["inventories"]["lib_NL2.10_0"]["file_count"], 2)
        self.assertEqual(saved["inventories"]["lib_NL2.10_0"]["ignored_outside_source_count"], 1)
        self.assertEqual(saved["comparison"]["counts"]["source_updated"], 2)
        self.assertEqual(saved["raw_library"]["formal_coverage"]["v11"]["unlinked_unique_source_count"], 1)
        self.assertIn("配置的正式根不是单阶段 IP 目录", markdown)

    def test_flat_view_file_links_match_by_raw_ip_source_without_nl_in_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            raw = base / "3rd_release" / "IP" / "demo_ip"
            other = base / "3rd_release" / "IP" / "other_ip"
            for version in ("v01", "v02"):
                (raw / version).mkdir(parents=True)
                (raw / version / "a.lef").write_text(version, encoding="utf-8")
            (other / "v02").mkdir(parents=True)
            (other / "v02" / "b.lef").write_text("other", encoding="utf-8")
            formal = base / "formal"
            for nl, source_version in (("lib_NL2.5_2", "v01"), ("lib_NL2.5_3", "v02")):
                view = formal / nl / "IP" / "LEF"
                view.mkdir(parents=True)
                (view / "a.lef").symlink_to(raw / source_version / "a.lef")
                (view / "b.lef").symlink_to(other / "v02" / "b.lef")
            config = base / "tracker.yml"
            config.write_text(
                "library:\n  ip_directory_name: demo_ip\n  root: ./3rd_release/IP/demo_ip\n"
                "formal_nl:\n  root: ./formal\n"
                "output:\n  report_json: ./out/report.json\n  report_md: ./out/report.md\n",
                encoding="utf-8",
            )

            result = tracker.run(config)
            markdown = (base / "out" / "report.md").read_text(encoding="utf-8")

        self.assertEqual(result["status"], "MATCHED")
        self.assertEqual(result["report_status"], "INCOMPLETE")
        self.assertEqual([item["nl_version"] for item in result["matches"][:2]], ["lib_NL2.5_3", "lib_NL2.5_2"])
        self.assertEqual([item["layout"] for item in result["matches"][:2]], ["FLAT_FILE_LINKS", "FLAT_FILE_LINKS"])
        self.assertEqual(result["inventories"]["lib_NL2.5_3"]["file_count"], 1)
        self.assertEqual(result["inventories"]["lib_NL2.5_3"]["ignored_outside_source_count"], 1)
        self.assertEqual(result["inventories"]["lib_NL2.5_3"]["files"][0]["relative_path"], "LEF/a.lef")
        self.assertEqual(result["comparison"]["counts"]["source_updated"], 1)
        self.assertIn("配置的正式根不是单阶段 IP 目录", markdown)

    def test_flat_view_file_links_without_raw_root_do_not_guess_ip_ownership(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            raw_file = base / "raw" / "demo_ip" / "v01" / "a.lef"
            raw_file.parent.mkdir(parents=True)
            raw_file.write_text("lef", encoding="utf-8")
            view = base / "formal" / "lib_NL2.5_3" / "IP" / "LEF"
            view.mkdir(parents=True)
            (view / "a.lef").symlink_to(raw_file)

            result = tracker.discover_formal_ip_links(base / "formal", "demo_ip")

        self.assertEqual(result["status"], "NOT_FOUND")
        self.assertIn("library.root", result["classification_note"])

    def test_real_asap7_sources_work_with_flat_nl_view_links(self) -> None:
        raw = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "raw" / "vendor_A" / "openroad_asap7"
        older = raw / "20260624_asap7" / "asap7_source_package"
        newer = raw / "20260627_asap7" / "upstream_ae9a8ed9"
        lef_name = "asap7sc7p5t_28_SL_1x_220121a.lef"
        liberty_name = "asap7sc7p5t_SIMPLE_SLVT_TT_nldm_211120.lib.gz"
        self.assertTrue((older / "lef" / lef_name).is_file())
        self.assertTrue((newer / "lib" / "NLDM" / liberty_name).is_file())
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            for nl, source in (("lib_NL2.9_0", older), ("lib_NL2.10_0", newer)):
                ip_area = base / "formal" / nl / "IP"
                (ip_area / "LEF").mkdir(parents=True)
                (ip_area / "LIB").mkdir()
                (ip_area / "LEF" / lef_name).symlink_to(source / "lef" / lef_name)
                if source == newer:
                    (ip_area / "LIB" / liberty_name).symlink_to(source / "lib" / "NLDM" / liberty_name)
            config = base / "tracker.yml"
            config.write_text(
                f"library:\n  root: {raw}\n  ip_directory_name: openroad_asap7\n"
                "formal_nl:\n  root: ./formal\n"
                "output:\n  report_json: ./out/report.json\n  report_md: ./out/report.md\n",
                encoding="utf-8",
            )

            result = tracker.run(config)
            markdown = (base / "out" / "report.md").read_text(encoding="utf-8")

        self.assertEqual(result["report_status"], "INCOMPLETE")
        self.assertEqual(result["inventories"]["lib_NL2.10_0"]["view_counts"], {"lef": 1, "liberty": 1})
        self.assertEqual(result["formal_sources"]["lib_NL2.10_0"]["counts_by_raw_version"], {"20260627_asap7": 2})
        self.assertIn("配置的正式根不是单阶段 IP 目录", markdown)

    def test_matches_ip_link_target_and_ranks_latest_two_nl_versions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "formal"
            ip = "vendor_A.ucie"
            targets = []
            for version in ("lib_NL2.9_0", "lib_NL2.10_0"):
                target = Path(tmp) / version / "IP" / ip
                target.mkdir(parents=True)
                link_dir = root / version / "IP"
                link_dir.mkdir(parents=True)
                (link_dir / ip).symlink_to(target, target_is_directory=True)
                targets.append(target)

            result = tracker.discover_formal_ip_links(root, ip)

        self.assertEqual(result["status"], "MATCHED")
        self.assertEqual([item["classification"] for item in result["matches"]], ["LATEST", "SECOND_LATEST"])
        self.assertEqual([item["nl_version"] for item in result["matches"]], ["lib_NL2.10_0", "lib_NL2.9_0"])

    def test_does_not_match_same_ip_name_when_target_lacks_ip_and_nl_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "formal"
            target = Path(tmp) / "misc" / "vendor_A.ucie"
            target.mkdir(parents=True)
            link_dir = root / "unversioned" / "IP"
            link_dir.mkdir(parents=True)
            (link_dir / "vendor_A.ucie").symlink_to(target, target_is_directory=True)

            result = tracker.discover_formal_ip_links(root, "vendor_A.ucie")

        self.assertEqual(result["status"], "NOT_FOUND")
        self.assertEqual(result["matches"], [])

    def test_duplicate_targets_for_same_nl_version_are_reported_ambiguous(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "formal"
            ip = "vendor_A.ucie"
            version = Path(tmp) / "lib_NL2.5_1" / "IP"
            for n in ("one", "two"):
                target = version / n / ip
                target.mkdir(parents=True)
                link_dir = root / n / "IP"
                link_dir.mkdir(parents=True)
                (link_dir / ip).symlink_to(target, target_is_directory=True)

            result = tracker.discover_formal_ip_links(root, ip)

        self.assertEqual(result["status"], "AMBIGUOUS")
        self.assertEqual(result["matches"], [])
        self.assertEqual(len(result["ambiguous_versions"]), 1)

    def test_yaml_config_writes_read_only_discovery_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = base / "formal"
            target = base / "lib_NL2.5_1" / "IP" / "demo_ip"
            target.mkdir(parents=True)
            link_dir = root / "release" / "IP"
            link_dir.mkdir(parents=True)
            (link_dir / "demo_ip").symlink_to(target, target_is_directory=True)
            config = base / "tracker.yml"
            config.write_text(
                "library:\n  id: demo_ip\n  root: /unused/demo_ip\n"
                "formal_nl:\n  root: ./formal\n"
                "output:\n  report_json: ./out/report.json\n",
                encoding="utf-8",
            )

            result = tracker.run(config)
            saved = json.loads((base / "out" / "report.json").read_text(encoding="utf-8"))

        self.assertEqual(result["status"], "MATCHED")
        self.assertEqual(saved["matches"][0]["classification"], "LATEST")
        self.assertNotIn("report_json", saved)

    def test_cli_runs_without_project_pythonpath(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = base / "formal"
            target = base / "lib_NL3.0" / "IP" / "demo_ip"
            target.mkdir(parents=True)
            (base / "raw" / "demo_ip" / "v01").mkdir(parents=True)
            link_dir = root / "NL" / "IP"
            link_dir.mkdir(parents=True)
            (link_dir / "demo_ip").symlink_to(target, target_is_directory=True)
            config = base / "tracker.yml"
            config.write_text(
                "library:\n  root: ./raw/demo_ip\n"
                "formal_nl:\n  root: ./formal\n"
                "output:\n  report_json: ./out/report.json\n",
                encoding="utf-8",
            )
            env = dict(os.environ)
            env.pop("PYTHONPATH", None)
            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--config", str(config)],
                cwd=base,
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )

        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn('"classification": "LATEST"', result.stdout)
        self.assertIn('"report_status": "INCOMPLETE"', result.stdout)

    def test_report_output_cannot_write_inside_read_only_formal_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = base / "formal"
            target = base / "lib_NL3.0" / "IP" / "demo_ip"
            target.mkdir(parents=True)
            link_dir = root / "NL" / "IP"
            link_dir.mkdir(parents=True)
            (link_dir / "demo_ip").symlink_to(target, target_is_directory=True)
            config = base / "tracker.yml"
            config.write_text(
                "library:\n  ip_directory_name: demo_ip\n"
                "formal_nl:\n  root: ./formal\n"
                "output:\n  report_json: ./formal/report.json\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "正式 NL 根目录之外"):
                tracker.run(config)

            self.assertFalse((root / "report.json").exists())

    def test_report_answers_file_scope_and_source_questions_with_chart_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = base / "formal"
            shared = base / "shared" / "a.lef"
            shared.parent.mkdir()
            shared.write_text("same source", encoding="utf-8")
            for version in ("lib_NL2.9_0", "lib_NL2.10_0"):
                target = base / "published" / version / "IP" / "demo_ip"
                (target / "LEF").mkdir(parents=True)
                (target / "LEF" / "a.lef").symlink_to(shared)
                (target / "LIB").mkdir()
                (target / "LIB" / "a_tt.lib.gz").write_text(version, encoding="utf-8")
                if version == "lib_NL2.9_0":
                    (target / "GDS").mkdir()
                    (target / "GDS" / "a.gds").write_text("old", encoding="utf-8")
                else:
                    (target / "LIB" / "a_ss.lib.gz").write_text("new", encoding="utf-8")
                link_dir = root / version / "IP"
                link_dir.mkdir(parents=True)
                (link_dir / "demo_ip").symlink_to(target, target_is_directory=True)
            config = base / "tracker.yml"
            config.write_text(
                "library:\n  ip_directory_name: demo_ip\n"
                "formal_nl:\n  root: ./formal\n"
                "output:\n  report_json: ./out/report.json\n"
                "  report_md: ./out/report.md\n",
                encoding="utf-8",
            )

            result = tracker.run(config)
            saved = json.loads((base / "out" / "report.json").read_text(encoding="utf-8"))
            markdown = (base / "out" / "report.md").read_text(encoding="utf-8")

        self.assertEqual(result["comparison"]["counts"], {
            "added": 1, "removed": 1, "source_updated": 1, "same_source": 1,
        })
        self.assertEqual(saved["matches"][0]["view_counts"], {"lef": 1, "liberty": 2})
        self.assertEqual(saved["matches"][1]["view_counts"], {"gds": 1, "lef": 1, "liberty": 1})
        self.assertEqual(saved["matches"][0]["unique_source_count"], 3)
        self.assertEqual(len(saved["inventories"]["lib_NL2.10_0"]["files"]), 3)
        self.assertEqual(len(saved["chart_data"]["view_counts"]), 5)
        self.assertEqual(len(saved["chart_data"]["view_transition_counts"]), 4)
        self.assertIn("配置的正式根不是单阶段 IP 目录", markdown)
        self.assertNotIn("按视图看，哪些文件来源发生了变化", markdown)
        self.assertEqual(result["report_md"], str((base / "out" / "report.md").resolve()))

    def test_one_version_report_marks_comparison_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            target = base / "lib_NL2.5_1" / "IP" / "demo_ip"
            (target / "LEF").mkdir(parents=True)
            (target / "LEF" / "a.lef").write_text("data", encoding="utf-8")
            link_dir = base / "formal" / "IP"
            link_dir.mkdir(parents=True)
            (link_dir / "demo_ip").symlink_to(target, target_is_directory=True)
            result = tracker.discover_formal_ip_links(base / "formal", "demo_ip")
            tracker.add_delivery_evidence(result)
            markdown = tracker.render_markdown(result)

        self.assertEqual(result["comparison"]["status"], "NO_SECOND_VERSION")
        self.assertEqual(result["matches"][0]["file_count"], 1)
        self.assertIn("配置的正式根不是单阶段 IP 目录", markdown)

    def test_inventory_follows_linked_view_directory_without_reading_file_content(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            target = base / "lib_NL3.0" / "IP" / "demo_ip"
            target.mkdir(parents=True)
            linked_view = base / "raw_lef"
            linked_view.mkdir()
            (linked_view / "a.lef").write_text("source", encoding="utf-8")
            (target / "LEF").symlink_to(linked_view, target_is_directory=True)

            inventory = tracker.inventory_for_ip_target(target)

        self.assertEqual(inventory["status"], "COMPLETE")
        self.assertEqual(inventory["view_counts"], {"lef": 1})
        self.assertEqual(inventory["files"][0]["relative_path"], "LEF/a.lef")

    def test_alias_paths_are_counted_separately_from_distinct_sources(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            source = base / "raw" / "a.lef"
            source.parent.mkdir()
            source.write_text("data", encoding="utf-8")
            target = base / "lib_NL3.0" / "IP" / "demo_ip"
            (target / "LEF").mkdir(parents=True)
            (target / "LEF" / "a.lef").symlink_to(source)
            (target / "LEF" / "alias.lef").symlink_to(source)

            inventory = tracker.inventory_for_ip_target(target)

        self.assertEqual(inventory["file_count"], 2)
        self.assertEqual(inventory["unique_source_count"], 1)

    def test_markdown_output_cannot_be_inside_formal_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            target = base / "lib_NL3.0" / "IP" / "demo_ip"
            target.mkdir(parents=True)
            link_dir = base / "formal" / "IP"
            link_dir.mkdir(parents=True)
            (link_dir / "demo_ip").symlink_to(target, target_is_directory=True)
            config = base / "tracker.yml"
            config.write_text(
                "library:\n  ip_directory_name: demo_ip\n"
                "formal_nl:\n  root: ./formal\n"
                "output:\n  report_json: ./out/report.json\n"
                "  report_md: ./formal/report.md\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "正式 NL 根目录之外"):
                tracker.run(config)

            self.assertFalse((base / "out" / "report.json").exists())

    def test_broken_view_link_keeps_inventory_incomplete_and_withholds_delta(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = base / "formal"
            for version in ("lib_NL2.9", "lib_NL2.10"):
                target = base / version / "IP" / "demo_ip"
                target.mkdir(parents=True)
                (target / "LEF").mkdir()
                (target / "LEF" / "a.lef").write_text("data", encoding="utf-8")
                if version == "lib_NL2.10":
                    (target / "LIB").symlink_to(base / "missing", target_is_directory=True)
                link_dir = root / version / "IP"
                link_dir.mkdir(parents=True)
                (link_dir / "demo_ip").symlink_to(target, target_is_directory=True)

            result = tracker.discover_formal_ip_links(root, "demo_ip")
            tracker.add_delivery_evidence(result)
            markdown = tracker.render_markdown(result)

        self.assertEqual(result["inventories"]["lib_NL2.10"]["status"], "INCOMPLETE")
        self.assertEqual(result["comparison"]["status"], "INCOMPLETE")
        self.assertEqual(result["comparison"]["counts"], {})
        self.assertIn("配置的正式根不是单阶段 IP 目录", markdown)

    def test_ambiguous_version_does_not_claim_current_file_counts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = base / "formal"
            for index in (1, 2):
                target = base / "lib_NL3.0" / f"source_{index}" / "demo_ip"
                target.mkdir(parents=True)
                link_dir = root / f"area_{index}"
                link_dir.mkdir(parents=True)
                (link_dir / "demo_ip").symlink_to(target, target_is_directory=True)
            result = tracker.discover_formal_ip_links(root, "demo_ip")
            tracker.add_delivery_evidence(result)
            markdown = tracker.render_markdown(result)

        self.assertEqual(result["comparison"]["status"], "AMBIGUOUS")
        self.assertEqual(result["inventories"], {})
        self.assertIn("配置的正式根不是单阶段 IP 目录", markdown)

    def test_combined_report_attributes_formal_files_to_raw_versions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            raw = base / "raw" / "demo_ip"
            for version in ("v00", "v01", "v02", "v03"):
                (raw / version).mkdir(parents=True)
            (raw / "v00" / "old.lef").write_text("unused", encoding="utf-8")
            (raw / "v01" / "a.lef").write_text("old", encoding="utf-8")
            (raw / "v02" / "a_tt.lib").write_text("timing", encoding="utf-8")
            (raw / "v03" / "a.lef").write_text("new", encoding="utf-8")
            (raw / "v03" / "README.md").write_text("not published", encoding="utf-8")
            formal = base / "formal"
            for nl_version, lef_version in (("lib_NL2.9", "v01"), ("lib_NL2.10", "v03")):
                target = base / "published" / nl_version / "IP" / "demo_ip"
                (target / "LEF").mkdir(parents=True)
                (target / "LIB").mkdir()
                (target / "LEF" / "a.lef").symlink_to(raw / lef_version / "a.lef")
                (target / "LIB" / "a_tt.lib").symlink_to(raw / "v02" / "a_tt.lib")
                link_dir = formal / nl_version / "IP"
                link_dir.mkdir(parents=True)
                (link_dir / "demo_ip").symlink_to(target, target_is_directory=True)
            config = base / "tracker.yml"
            config.write_text(
                "library:\n  ip_directory_name: demo_ip\n  root: ./raw/demo_ip\n"
                "formal_nl:\n  root: ./formal\n"
                "output:\n  report_json: ./out/report.json\n  report_md: ./out/report.md\n",
                encoding="utf-8",
            )

            result = tracker.run(config)
            saved = json.loads((base / "out" / "report.json").read_text(encoding="utf-8"))
            markdown = (base / "out" / "report.md").read_text(encoding="utf-8")

        self.assertEqual(result["raw_library"]["status"], "COMPLETE")
        self.assertEqual(result["report_status"], "INCOMPLETE")
        self.assertEqual(result["raw_library"]["version_count"], 4)
        self.assertEqual(set(result["raw_library"]["inventories"]), {"v00", "v01", "v02", "v03"})
        self.assertEqual(result["raw_library"]["versions"][0]["version_id"], "v03")
        self.assertEqual(result["formal_sources"]["lib_NL2.10"]["counts_by_raw_version"], {"v02": 1, "v03": 1})
        self.assertEqual(result["formal_sources"]["lib_NL2.9"]["counts_by_raw_version"], {"v01": 1, "v02": 1})
        self.assertEqual(result["raw_library"]["formal_coverage"]["v03"]["unlinked_unique_source_count"], 1)
        self.assertEqual(result["raw_library"]["formal_coverage"]["v03"]["unlinked_files"][0]["relative_path"], "README.md")
        self.assertIn(
            {"raw_version": "v03", "view": "other", "raw_source_count": 1, "formal_source_count": 0},
            saved["chart_data"]["raw_formal_view_coverage"],
        )
        self.assertEqual(saved["chart_data"]["formal_source_mix"], [
            {"nl_version": "lib_NL2.10", "raw_version": "v02", "file_count": 1},
            {"nl_version": "lib_NL2.10", "raw_version": "v03", "file_count": 1},
            {"nl_version": "lib_NL2.9", "raw_version": "v01", "file_count": 1},
            {"nl_version": "lib_NL2.9", "raw_version": "v02", "file_count": 1},
        ])
        self.assertIn("配置的正式根不是单阶段 IP 目录", markdown)
        self.assertEqual(saved["chart_data_meta"]["formal_source_mix"]["scope"], "按指定阶段与原始版本分组")
        self.assertEqual(saved["chart_data_meta"]["raw_formal_view_coverage"]["unit"], "去重后的原始文件来源路径")

    def test_formal_source_outside_raw_root_is_explicitly_unmapped(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            raw = base / "raw" / "demo_ip"
            (raw / "v01").mkdir(parents=True)
            outside = base / "external" / "a.lef"
            outside.parent.mkdir()
            outside.write_text("x", encoding="utf-8")
            target = base / "lib_NL1.0" / "IP" / "demo_ip"
            (target / "LEF").mkdir(parents=True)
            (target / "LEF" / "a.lef").symlink_to(outside)
            formal = base / "formal"
            link_dir = formal / "IP"
            link_dir.mkdir(parents=True)
            (link_dir / "demo_ip").symlink_to(target, target_is_directory=True)

            result = tracker.discover_formal_ip_links(formal, "demo_ip")
            tracker.add_delivery_evidence(result)
            tracker.add_raw_library_evidence(result, raw)
            markdown = tracker.render_markdown(result)

        self.assertEqual(result["formal_sources"]["lib_NL1.0"]["unmapped_count"], 1)
        self.assertEqual(result["formal_sources"]["lib_NL1.0"]["counts_by_raw_version"], {})
        self.assertIn("配置的正式根不是单阶段 IP 目录", markdown)

    def test_raw_root_missing_is_reported_not_silently_treated_as_complete(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            formal = base / "formal"
            formal.mkdir()
            result = tracker.discover_formal_ip_links(formal, "demo_ip")
            tracker.add_delivery_evidence(result)
            tracker.add_raw_library_evidence(result, base / "missing")

        self.assertEqual(result["raw_library"]["status"], "ROOT_NOT_FOUND")
        self.assertIn("配置的正式根不是单阶段 IP 目录", tracker.render_markdown(result))

    def test_report_output_cannot_write_inside_raw_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / "raw" / "demo_ip" / "v01").mkdir(parents=True)
            (base / "formal").mkdir()
            config = base / "tracker.yml"
            config.write_text(
                "library:\n  ip_directory_name: demo_ip\n  root: ./raw/demo_ip\n"
                "formal_nl:\n  root: ./formal\n"
                "output:\n  report_json: ./out/report.json\n"
                "  report_md: ./raw/demo_ip/report.md\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "只读输入目录之外"):
                tracker.run(config)
            self.assertFalse((base / "out" / "report.json").exists())

    def test_raw_formal_coverage_uses_raw_source_view_when_link_is_renamed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            raw = base / "raw" / "demo_ip"
            (raw / "v01").mkdir(parents=True)
            source = raw / "v01" / "source.dat"
            source.write_text("data", encoding="utf-8")
            target = base / "lib_NL3.0" / "IP" / "demo_ip"
            (target / "LEF").mkdir(parents=True)
            (target / "LEF" / "renamed.lef").symlink_to(source)
            formal = base / "formal" / "lib_NL2.5_3" / "IP"
            formal.mkdir(parents=True)
            (formal / "demo_ip").symlink_to(target, target_is_directory=True)

            result = tracker.discover_formal_ip_links(base / "formal", "demo_ip")
            tracker.add_delivery_evidence(result)
            tracker.add_raw_library_evidence(result, raw)

        self.assertEqual(result["chart_data"]["raw_formal_view_coverage"], [
            {"raw_version": "v01", "view": "other", "raw_source_count": 1, "formal_source_count": 1},
        ])

    def test_markdown_file_examples_sample_each_view(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = base / "formal"
            for nl_version in ("lib_NL1.0", "lib_NL2.0"):
                target = base / nl_version / "IP" / "demo_ip"
                target.mkdir(parents=True)
                if nl_version == "lib_NL2.0":
                    (target / "LEF").mkdir()
                    for number in range(25):
                        (target / "LEF" / f"cell_{number:02}.lef").write_text("x", encoding="utf-8")
                    (target / "LIB").mkdir()
                    (target / "LIB" / "timing.lib").write_text("y", encoding="utf-8")
                link_dir = root / nl_version / "IP"
                link_dir.mkdir(parents=True)
                (link_dir / "demo_ip").symlink_to(target, target_is_directory=True)

            result = tracker.discover_formal_ip_links(root, "demo_ip")
            tracker.add_delivery_evidence(result)
            tracker.add_raw_library_evidence(result, None)
            markdown = tracker.render_markdown(result)

        self.assertIn("配置的正式根不是单阶段 IP 目录", markdown)

    def test_readme_under_view_directory_is_not_counted_as_a_view(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            target = base / "lib_NL3.0" / "IP" / "demo_ip"
            (target / "VERILOG").mkdir(parents=True)
            (target / "VERILOG" / "README.md").write_text("notes", encoding="utf-8")
            (target / "VERILOG" / "cell.v").write_text("module cell; endmodule", encoding="utf-8")
            link_dir = base / "formal" / "IP"
            link_dir.mkdir(parents=True)
            (link_dir / "demo_ip").symlink_to(target, target_is_directory=True)

            result = tracker.discover_formal_ip_links(base / "formal", "demo_ip")
            tracker.add_delivery_evidence(result)
            tracker.add_raw_library_evidence(result, None)
            markdown = tracker.render_markdown(result)

        self.assertEqual(result["matches"][0]["view_counts"], {"other": 1, "verilog": 1})
        self.assertIn("配置的正式根不是单阶段 IP 目录", markdown)

    def test_report_output_cannot_write_inside_resolved_formal_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            target = base / "published" / "lib_NL3.0" / "IP" / "demo_ip"
            target.mkdir(parents=True)
            raw = base / "raw" / "demo_ip" / "v01"
            raw.mkdir(parents=True)
            link_dir = base / "formal" / "IP"
            link_dir.mkdir(parents=True)
            (link_dir / "demo_ip").symlink_to(target, target_is_directory=True)
            config = base / "tracker.yml"
            config.write_text(
                "library:\n  ip_directory_name: demo_ip\n  root: ./raw/demo_ip\n"
                "formal_nl:\n  root: ./formal\n"
                f"output:\n  report_json: {target / 'report.json'}\n"
                "  report_md: ./out/report.md\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "只读输入目录之外"):
                tracker.run(config)

            self.assertFalse((target / "report.json").exists())

    def test_cli_marks_missing_raw_root_as_incomplete_without_release_claim(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            target = base / "lib_NL3.0" / "IP" / "demo_ip"
            target.mkdir(parents=True)
            link_dir = base / "formal" / "IP"
            link_dir.mkdir(parents=True)
            (link_dir / "demo_ip").symlink_to(target, target_is_directory=True)
            config = base / "tracker.yml"
            config.write_text(
                "library:\n  ip_directory_name: demo_ip\n  root: ./raw/missing\n"
                "formal_nl:\n  root: ./formal\n"
                "output:\n  report_json: ./out/report.json\n  report_md: ./out/report.md\n",
                encoding="utf-8",
            )
            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--config", str(config)],
                cwd=base, text=True, capture_output=True, check=False,
            )
            saved = json.loads((base / "out" / "report.json").read_text(encoding="utf-8"))

        self.assertEqual(result.returncode, 1)
        self.assertEqual(saved["report_status"], "INCOMPLETE")
        self.assertEqual(saved["raw_library"]["status"], "ROOT_NOT_FOUND")

    def test_fifty_raw_versions_inventory_link_sources_and_latest_two_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            raw = base / "raw" / "demo_ip"
            for number in range(50):
                version = raw / f"v{number:02}"
                version.mkdir(parents=True)
                (version / "file.lef").write_text(str(number), encoding="utf-8")
            formal = base / "formal" / "lib_NL3.0" / "IP"
            (formal / "LEF").mkdir(parents=True)
            (formal / "LEF" / "file.lef").symlink_to(raw / "v49" / "file.lef")

            result = tracker.discover_formal_ip_links(formal, "demo_ip", raw)
            tracker.add_delivery_evidence(result)
            tracker.add_raw_library_evidence(result, raw)
            markdown = tracker.render_markdown(result)

        self.assertEqual(result["raw_library"]["version_count"], 50)
        self.assertEqual(set(result["raw_library"]["inventories"]), {f"v{number:02}" for number in range(50)})
        self.assertEqual(len(result["chart_data"]["raw_version_file_counts"]), 50)
        self.assertEqual(result["chart_data"]["raw_version_file_counts"][0]["raw_version"], "v49")
        self.assertEqual(result["chart_data"]["raw_version_file_counts"][0]["file_count"], 1)
        self.assertEqual(result["raw_library"]["version_candidates"]["latest"], "v49")
        self.assertEqual(result["raw_library"]["version_candidates"]["next_latest"], "v48")
        self.assertEqual(len(result["raw_library"]["inventories"]), 50)
        self.assertEqual(len(result["raw_library"]["version_evolution"]), 49)
        self.assertIn("RAW 原始版本逐级演进", markdown)
        self.assertIn("仅新版本路径", markdown)
        self.assertEqual(result["raw_library"]["versions"][-1]["inventory_status"], "COMPLETE")
        self.assertIn("正式阶段：`lib_NL3.0`", markdown)

    def test_single_stage_report_orders_raw_versions_and_compares_latest_two(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            raw = base / "raw" / "demo_ip"
            versions = {
                "20260601_release": {"LEF/a.lef", "LIB/a_TT.lib"},
                "20260615_release": {"LEF/a.lef", "LIB/a_TT.lib", "DB/a_TT.db"},
                "20260620_release": {"LEF/a.lef", "LIB/a_TT.lib", "DB/a_TT.db", "GDS/a.gds"},
            }
            for version, paths in versions.items():
                for relative in paths:
                    source = raw / version / relative
                    source.parent.mkdir(parents=True, exist_ok=True)
                    source.write_text(version, encoding="utf-8")
            formal_ip = base / "formal" / "lib_NL2.5_3" / "IP"
            (formal_ip / "LEF").mkdir(parents=True)
            (formal_ip / "LEF" / "a.lef").symlink_to(raw / "20260615_release" / "LEF/a.lef")
            config = base / "tracker.yml"
            config.write_text(
                "library:\n  root: ./raw/demo_ip\n  ip_directory_name: demo_ip\n"
                "formal_nl:\n  root: ./formal/lib_NL2.5_3/IP\n"
                "output:\n  report_json: ./out/report.json\n  report_md: ./out/report.md\n",
                encoding="utf-8",
            )

            result = tracker.run(config)
            report = (base / "out" / "report.md").read_text(encoding="utf-8")

        raw_data = result["raw_library"]
        self.assertEqual(raw_data["version_candidates"]["latest"], "20260620_release")
        self.assertEqual(raw_data["version_candidates"]["next_latest"], "20260615_release")
        self.assertEqual(raw_data["comparison"]["status"], "COMPLETE")
        self.assertEqual(raw_data["comparison"]["counts"], {
            "same_path": 3, "only_latest": 1, "only_next_latest": 0,
        })
        self.assertEqual(set(raw_data["inventories"]), {
            "20260601_release", "20260615_release", "20260620_release",
        })
        self.assertEqual(len(raw_data["version_evolution"]), 2)
        self.assertIn("按原始目录名推断", report)
        self.assertIn("20260620_release", report)
        self.assertIn("20260615_release", report)
        self.assertIn("仅最新目录有", report)
        self.assertNotIn("lib_NL2.5_3 与 lib_NL", report)

    def test_multistage_root_does_not_render_formal_stage_ranking_as_current_report(self) -> None:
        result = {
            "formal_scope": "MULTI_STAGE_DISCOVERY",
            "formal_nl_root": "/formal",
            "ip_directory_name": "demo_ip",
            "matches": [{"nl_version": "lib_NL2.10_0"}, {"nl_version": "lib_NL2.9_0"}],
        }
        report = tracker.render_markdown(result)

        self.assertIn("配置的正式根不是单阶段 IP 目录", report)
        self.assertIn("lib_NL<阶段号>/IP", report)
        self.assertNotIn("最高编号目录", report)
        self.assertNotIn("次高编号目录", report)


if __name__ == "__main__":
    unittest.main()
