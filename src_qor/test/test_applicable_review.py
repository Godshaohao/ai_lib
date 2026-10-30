import tempfile
import unittest
from pathlib import Path

from lib_guard.applicable_review import build_applicable_plan


class ApplicableReviewPlanTests(unittest.TestCase):
    def projection(self, *, ordered=("V1", "V2"), lef_rows=None, lib_rows=None):
        rows = []
        for file_key, view, name, occurrences in (lef_rows or []) + (lib_rows or []):
            rows.append({
                "file_key": file_key, "view": view, "display_name": name,
                "identity_status": "EXACT_RELATIVE_PATH",
                "comparison": {"delivery_relation": "READY_TO_COMPARE",
                               "base_presence": "PRESENT", "target_presence": "PRESENT"},
                "occurrences": occurrences,
            })
        return {
            "schema_version": "file_version_projection.v1", "snapshot_id": "raw-snapshot",
            "library_id": "V.IP", "version_order": {"status": "KNOWN", "ordered_ids": list(ordered)},
            "scope": {"registered_versions": list(ordered), "inventory_status": {v: "COMPLETE" for v in ordered}},
            "coverage": {"raw_inventory": "COMPLETE"}, "files": rows,
        }

    def occurrence(self, version, path):
        return {"version": version, "source_path": path}

    def test_current_file_set_uses_per_file_latest_sources_across_deliveries(self):
        projection = self.projection(
            lef_rows=[("lef:core.lef", "lef", "core.lef", [
                self.occurrence("V1", "/raw/V1/LEF/core.lef"),
                self.occurrence("V2", "/raw/V2/LEF/core.lef")])],
            lib_rows=[("liberty:core_tt.lib", "liberty", "core_tt.lib", [
                self.occurrence("V2", "/raw/V2/LIB/core_tt.lib")])],
        )

        current_set = {"status": "COMPLETE", "candidate_version": "V2", "files": [
            {"view": "lef", "source_path": "/raw/V2/LEF/core.lef", "source_version": "V2"},
            {"view": "liberty", "source_path": "/raw/V1/LIB/core_tt.lib", "source_version": "V1"},
        ]}
        groups = {"status": "COMPLETE", "groups": [{
            "lef_file": "/raw/V2/LEF/core.lef", "liberty_files": ["/raw/V1/LIB/core_tt.lib"],
            "source_versions": {"lef": "V2", "liberties": {"/raw/V1/LIB/core_tt.lib": "V1"}},
            "macro_names": ["SRAM"], "objects": [],
        }], "ambiguous_objects": [], "unresolved": []}
        plan = build_applicable_plan(projection, {"V1": "/raw/V1", "V2": "/raw/V2"},
                                     current_file_set=current_set, interface_groups=groups,
                                     current_filemap_json="/tmp/filemap.json")

        self.assertEqual(plan["scope"], {"base_version": "V1", "target_version": "V2"})
        self.assertEqual(plan["checks"]["lef_review"]["pairs"][0]["file_key"], "lef:core.lef")
        interface = plan["checks"]["lef_liberty_check"]
        self.assertEqual(interface["groups"][0]["lef_file"], "/raw/V2/LEF/core.lef")
        self.assertEqual(interface["groups"][0]["liberty_files"], ["/raw/V1/LIB/core_tt.lib"])
        self.assertEqual(interface["groups"][0]["source_versions"]["lef"], "V2")

    def test_one_lef_associates_with_current_liberties_from_any_delivery(self):
        projection = self.projection(
            lef_rows=[("lef:core.lef", "lef", "core.lef", [
                self.occurrence("V2", "/raw/V2/LEF/core.lef")])],
            lib_rows=[(f"liberty:{name}", "liberty", name, [
                self.occurrence("V2", f"/raw/V2/LIB/{name}")])
                for name in ("core_ff.lib", "core_ss.lib", "core_tt.lib")],
        )

        current_set = {"status": "COMPLETE", "candidate_version": "V2", "files": [
            {"view": "lef", "source_path": "/raw/V2/LEF/core.lef", "source_version": "V2"},
            *[{"view": "liberty", "source_path": f"/raw/V{version}/LIB/{name}", "source_version": f"V{version}"}
              for name, version in (("core_ff.lib", "1"), ("core_ss.lib", "2"), ("core_tt.lib", "1"))],
        ]}
        libs = [item["source_path"] for item in current_set["files"] if item["view"] == "liberty"]
        groups = {"status": "COMPLETE", "groups": [{
            "lef_file": "/raw/V2/LEF/core.lef", "liberty_files": libs,
            "source_versions": {"lef": "V2", "liberties": {path: path.split("/raw/")[1][:2] for path in libs}},
            "macro_names": ["SRAM"], "objects": [],
        }], "ambiguous_objects": [], "unresolved": []}
        plan = build_applicable_plan(projection, {"V1": "/raw/V1", "V2": "/raw/V2"},
                                     current_file_set=current_set, interface_groups=groups,
                                     current_filemap_json="/tmp/filemap.json")

        interface = plan["checks"]["lef_liberty_check"]
        self.assertEqual(set(interface["groups"][0]["liberty_files"]), set(libs))
        self.assertEqual(interface["groups"][0]["source_versions"]["liberties"]["/raw/V1/LIB/core_tt.lib"], "V1")
        cross_view = next(row for row in plan["engineering_checklist"] if row["id"] == "cross_view")
        self.assertEqual(cross_view["execution"], "计划执行")

    def test_ambiguous_objects_do_not_block_other_confirmed_groups(self):
        projection = self.projection(
            lef_rows=[(f"lef:{name}", "lef", name, [self.occurrence("V2", f"/raw/V2/LEF/{name}")])
                      for name in ("a.lef", "b.lef")],
            lib_rows=[(f"liberty:{name}", "liberty", name, [self.occurrence("V2", f"/raw/V2/LIB/{name}")])
                      for name in ("a.lib", "b.lib")],
        )

        groups = {"status": "PARTIAL", "groups": [{
            "lef_file": "/raw/V2/LEF/a.lef", "liberty_files": ["/raw/V2/LIB/a.lib"],
            "source_versions": {"lef": "V2", "liberties": {"/raw/V2/LIB/a.lib": "V2"}},
            "macro_names": ["A"], "objects": [],
        }], "ambiguous_objects": [{"macro": "B", "reason": "MULTIPLE_CURRENT_LIBERTY_CANDIDATES"}],
          "unresolved": []}
        plan = build_applicable_plan(projection, {"V1": "/raw/V1", "V2": "/raw/V2"},
                                     current_file_set={"status": "PARTIAL", "files": [{"view": "lef"}]},
                                     interface_groups=groups, current_filemap_json="/tmp/filemap.json")

        self.assertIn("lef_liberty_check", plan["checks"])
        row = next(row for row in plan["engineering_checklist"] if row["id"] == "cross_view")
        self.assertEqual(row["execution"], "部分覆盖")
        self.assertIn("歧义", row["reason"])

    def test_single_known_delivery_sets_projection_target_without_delta_base(self):
        projection = self.projection(ordered=("V1",))
        with tempfile.TemporaryDirectory() as temp:
            raw_root = Path(temp) / "V1"
            raw_root.mkdir()

            plan = build_applicable_plan(projection, {"V1": str(raw_root)})

        self.assertEqual(plan["scope"], {"base_version": "", "target_version": "V1"})
        self.assertEqual(plan["projection"]["scope"]["target_version"], "V1")
        self.assertEqual(plan["projection"]["scope"]["base_version"], "")
        self.assertIn("macro_index", plan["checks"])
        self.assertNotIn("lef_review", plan["checks"])
        view = next(row for row in plan["engineering_checklist"] if row["id"] == "view_completeness")
        self.assertEqual(view["execution"], "计划执行")
        self.assertIn("macro_index", view["check_names"])
        self.assertNotIn("doc_delta", {row["id"] for row in plan["engineering_checklist"]})

    def test_unknown_delivery_order_does_not_invent_a_delta_scope(self):
        projection = self.projection(ordered=())
        projection["version_order"] = {"status": "UNKNOWN", "ordered_ids": []}
        projection["scope"]["registered_versions"] = ["V1", "V2"]

        plan = build_applicable_plan(projection, {"V1": "/raw/V1", "V2": "/raw/V2"})

        self.assertEqual(plan["scope"], {"base_version": "", "target_version": ""})
        self.assertNotIn("lef_review", plan["checks"])
        row = next(row for row in plan["engineering_checklist"] if row["id"] == "file_delta")
        self.assertEqual(row["execution"], "未执行")
        self.assertIn("交付顺序", row["reason"])

    def test_corner_summary_uses_process_corner_name_not_liberty_numeric_process_attribute(self):
        observed = [{
            "source_path": "/raw/LIB/model.lib",
            "corner_axes": {"process_corner": "SSG", "rc_corner": None},
            "operating_conditions": {"model": {"ssg_0p72v_125c": {
                "process": "1", "voltage": "0.72", "temperature": "125"}}},
        }]
        plan = build_applicable_plan(
            self.projection(ordered=("V1",)), {"V1": "/raw/V1"},
            interface_groups={"status": "COMPLETE", "groups": [{}],
                              "observed_liberties": observed})

        corner = next(row for row in plan["engineering_checklist"] if row["id"] == "corner_coverage")
        self.assertIn("Process=SSG", corner["result"])
        self.assertIn("V=0.72", corner["result"])
        self.assertIn("T=125", corner["result"])
        self.assertNotIn("P=1", corner["result"])


if __name__ == "__main__":
    unittest.main()
