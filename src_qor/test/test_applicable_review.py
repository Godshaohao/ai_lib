import unittest

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

    def test_unique_latest_lef_and_liberty_form_an_explicit_bound_pair(self):
        projection = self.projection(
            lef_rows=[("lef:core.lef", "lef", "core.lef", [
                self.occurrence("V1", "/raw/V1/LEF/core.lef"),
                self.occurrence("V2", "/raw/V2/LEF/core.lef")])],
            lib_rows=[("liberty:core_tt.lib", "liberty", "core_tt.lib", [
                self.occurrence("V2", "/raw/V2/LIB/core_tt.lib")])],
        )

        plan = build_applicable_plan(projection, {"V1": "/raw/V1", "V2": "/raw/V2"})

        self.assertEqual(plan["scope"], {"base_version": "V1", "target_version": "V2"})
        self.assertEqual(plan["checks"]["lef_review"]["pairs"][0]["file_key"], "lef:core.lef")
        interface = plan["checks"]["lef_liberty_check"]
        self.assertEqual(interface["lef_file"], "/raw/V2/LEF/core.lef")
        self.assertEqual(interface["liberty_files"], ["/raw/V2/LIB/core_tt.lib"])
        self.assertEqual(interface["source_versions"], {
            "lef": "V2", "liberties": {"/raw/V2/LIB/core_tt.lib": "V2"}})

    def test_ambiguous_interface_inputs_are_not_guessed(self):
        projection = self.projection(
            lef_rows=[(f"lef:{name}", "lef", name, [self.occurrence("V2", f"/raw/V2/LEF/{name}")])
                      for name in ("a.lef", "b.lef")],
            lib_rows=[(f"liberty:{name}", "liberty", name, [self.occurrence("V2", f"/raw/V2/LIB/{name}")])
                      for name in ("a.lib", "b.lib")],
        )

        plan = build_applicable_plan(projection, {"V1": "/raw/V1", "V2": "/raw/V2"})

        self.assertNotIn("lef_liberty_check", plan["checks"])
        row = next(row for row in plan["engineering_checklist"] if row["id"] == "cross_view")
        self.assertEqual(row["execution"], "未执行")
        self.assertIn("输入组合待确认", row["reason"])

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


if __name__ == "__main__":
    unittest.main()
