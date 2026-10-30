import unittest
from pathlib import Path

from lib_guard.current_library_set import build_current_file_set, build_interface_groups


class CurrentLibrarySetTests(unittest.TestCase):
    def _build(self, versions, files_by_version, statuses=None):
        statuses = statuses or {}
        inventories = []
        for version in versions:
            version_id = version["id"]
            root = version["path"]
            inventories.append({
                "version_id": version_id,
                "root": root,
                "status": statuses.get(version_id, "COMPLETE"),
                "files": [f"{root}/{relative}" for relative in files_by_version.get(version_id, [])],
            })
        return build_current_file_set(versions, inventories)


    def _fact(self, view, path, *, macros=None, libraries=None, version="V01"):
        data = {"macros": macros or {}, "libraries": libraries or {}}
        return {"file_type": view, "parse_status": "PASS", "data": data,
                "file_identity": {"source_path": path, "source_version": version}}

    def test_multiple_lefs_associate_only_liberty_files_with_matching_macro_and_corner(self):
        file_set = {"status": "COMPLETE", "files": [
            {"view": "lef", "relative_path": "LEF/a.lef", "source_path": "/raw/V03/LEF/a.lef", "source_version": "V03"},
            {"view": "lef", "relative_path": "LEF/b.lef", "source_path": "/raw/V03/LEF/b.lef", "source_version": "V03"},
            {"view": "liberty", "relative_path": "LIB/a_tt.lib", "source_path": "/raw/V02/LIB/a_tt.lib", "source_version": "V02"},
            {"view": "liberty", "relative_path": "LIB/a_ff.lib", "source_path": "/raw/V04/LIB/a_ff.lib", "source_version": "V04"},
            {"view": "liberty", "relative_path": "LIB/b_tt.lib", "source_path": "/raw/V01/LIB/b_tt.lib", "source_version": "V01"},
            {"view": "liberty", "relative_path": "LIB/b_ff.lib", "source_path": "/raw/V04/LIB/b_ff.lib", "source_version": "V04"},
        ]}
        facts = [
            self._fact("lef", "/raw/V03/LEF/a.lef", macros={"MACRO_A": {}}),
            self._fact("lef", "/raw/V03/LEF/b.lef", macros={"MACRO_B": {}}),
            self._fact("liberty", "/raw/V02/LIB/a_tt.lib", libraries={"a_tt": {"cells": {"MACRO_A": {}}, "operating_conditions": {}}}, version="V02"),
            self._fact("liberty", "/raw/V04/LIB/a_ff.lib", libraries={"a_ff": {"cells": {"MACRO_A": {}}, "operating_conditions": {}}}, version="V04"),
            self._fact("liberty", "/raw/V01/LIB/b_tt.lib", libraries={"b_tt": {"cells": {"MACRO_B": {}}, "operating_conditions": {}}}, version="V01"),
            self._fact("liberty", "/raw/V04/LIB/b_ff.lib", libraries={"b_ff": {"cells": {"MACRO_B": {}}, "operating_conditions": {}}}, version="V04"),
        ]
        result = build_interface_groups(file_set, facts)
        groups = {Path(item["lef_file"]).name: {Path(path).name for path in item["liberty_files"]}
                  for item in result["groups"]}
        self.assertEqual(groups, {"a.lef": {"a_tt.lib", "a_ff.lib"},
                                  "b.lef": {"b_tt.lib", "b_ff.lib"}})
        self.assertEqual(result["status"], "COMPLETE")

    def test_duplicate_macro_corner_candidates_across_paths_are_ambiguous(self):
        file_set = {"status": "COMPLETE", "files": [
            {"view": "lef", "relative_path": "LEF/a.lef", "source_path": "/raw/V03/LEF/a.lef", "source_version": "V03"},
            {"view": "liberty", "relative_path": "LIB/tt_old.lib", "source_path": "/raw/V01/LIB/tt_old.lib", "source_version": "V01"},
            {"view": "liberty", "relative_path": "LIB/tt_new.lib", "source_path": "/raw/V03/LIB/tt_new.lib", "source_version": "V03"},
        ]}
        facts = [
            self._fact("lef", "/raw/V03/LEF/a.lef", macros={"MACRO_A": {}}),
            self._fact("liberty", "/raw/V01/LIB/tt_old.lib", libraries={"tt": {"cells": {"MACRO_A": {}}, "operating_conditions": {}}}, version="V01"),
            self._fact("liberty", "/raw/V03/LIB/tt_new.lib", libraries={"tt": {"cells": {"MACRO_A": {}}, "operating_conditions": {}}}, version="V03"),
        ]
        result = build_interface_groups(file_set, facts)
        self.assertEqual(result["status"], "PARTIAL")
        self.assertEqual(result["groups"], [])
        self.assertEqual(result["ambiguous_objects"][0]["macro"], "MACRO_A")
        self.assertEqual(len(result["ambiguous_objects"][0]["sources"]), 2)

    def test_ssg_condition_name_is_process_corner_while_liberty_process_is_only_raw_attribute(self):
        path = "/raw/V1/LIB/model.lib"
        file_set = {"status": "COMPLETE", "files": [
            {"view": "liberty", "relative_path": "LIB/model.lib",
             "source_path": path, "source_version": "V1"},
        ]}
        facts = [self._fact("liberty", path, libraries={"model": {
            "cells": {"MACRO_A": {}},
            "operating_conditions": {"ssg_0p72v_125c": {
                "process": "1", "voltage": "0.72", "temperature": "125"}},
        }})]

        result = build_interface_groups(file_set, facts)

        observed = result["observed_liberties"][0]
        self.assertEqual(observed["corner_axes"]["process_corner"], "SSG")
        self.assertEqual(observed["operating_conditions"]["model"]["ssg_0p72v_125c"]["process"], "1")

    def test_pass_empty_liberty_remains_observable_without_fabricating_an_interface_group(self):
        file_set = {"status": "COMPLETE", "files": [
            {"view": "liberty", "relative_path": "LIB/core_tt.lib",
             "source_path": "/raw/V1/LIB/core_tt.lib", "source_version": "V1"},
        ]}
        facts = [{"file_type": "liberty", "status": "PASS_EMPTY", "data": {"libraries": {}},
                  "file_identity": {"source_path": "/raw/V1/LIB/core_tt.lib", "source_version": "V1"}}]

        result = build_interface_groups(file_set, facts)

        self.assertEqual(result["groups"], [])
        self.assertEqual(result["unresolved"], [])
        self.assertEqual(result["observed_liberties"][0]["corner_axes"]["process_corner"], "TT")
        self.assertEqual(result["observed_liberties"][0]["source_version"], "V1")
        self.assertEqual(result["status"], "PARTIAL")

    def test_same_macro_corner_with_incomplete_operating_condition_identity_is_ambiguous(self):
        file_set = {"status": "COMPLETE", "files": [
            {"view": "lef", "source_path": "/raw/V2/LEF/core.lef", "source_version": "V2"},
            {"view": "liberty", "source_path": "/raw/V1/LIB/core_tt_old.lib", "source_version": "V1"},
            {"view": "liberty", "source_path": "/raw/V2/LIB/core_tt_new.lib", "source_version": "V2"},
        ]}
        facts = [
            self._fact("lef", "/raw/V2/LEF/core.lef", macros={"MACRO_A": {}}),
            self._fact("liberty", "/raw/V1/LIB/core_tt_old.lib",
                       libraries={"tt": {"cells": {"MACRO_A": {}}, "operating_conditions": {}}}, version="V1"),
            self._fact("liberty", "/raw/V2/LIB/core_tt_new.lib",
                       libraries={"tt": {"cells": {"MACRO_A": {}}, "operating_conditions": {
                           "tt_1v0_25c": {"process": 1, "voltage": 1.0, "temperature": 25}}}}, version="V2"),
        ]

        result = build_interface_groups(file_set, facts)

        self.assertEqual(result["groups"], [])
        self.assertTrue(any(item["reason"] == "OPERATING_CONDITION_IDENTITY_INCOMPLETE"
                            for item in result["ambiguous_objects"]))

    def test_full_plus_patch_chain_selects_latest_provider_per_file(self):
        versions = [
            {"id": "V01", "path": "/raw/V01", "delivery_order": 1, "package_type": "FULL_PACKAGE"},
            {"id": "V02", "path": "/raw/V02", "delivery_order": 2, "package_type": "PARTIAL_UPDATE", "previous_effective_version": "V01"},
            {"id": "V03", "path": "/raw/V03", "delivery_order": 3, "package_type": "PARTIAL_UPDATE", "previous_effective_version": "V02"},
            {"id": "V04", "path": "/raw/V04", "delivery_order": 4, "package_type": "PARTIAL_UPDATE", "previous_effective_version": "V03"},
        ]
        result = self._build(versions, {
            "V01": ["LEF/core.lef", "LIB/tt.lib", "LIB/ff.lib", "LIB/ss.lib"],
            "V02": ["LIB/tt.lib"],
            "V03": ["LEF/core.lef"],
            "V04": ["LIB/ff.lib"],
        })
        selected = {item["relative_path"]: item["source_version"] for item in result["files"]}
        self.assertEqual(selected, {"LEF/core.lef": "V03", "LIB/tt.lib": "V02",
                                    "LIB/ff.lib": "V04", "LIB/ss.lib": "V01"})
        self.assertEqual(result["status"], "COMPLETE")

    def test_new_full_package_drops_files_from_replaced_full_scope(self):
        versions = [
            {"id": "V01", "path": "/raw/V01", "delivery_order": 1, "package_type": "FULL_PACKAGE"},
            {"id": "V02", "path": "/raw/V02", "delivery_order": 2, "package_type": "FULL_PACKAGE"},
        ]
        result = self._build(versions, {
            "V01": ["LEF/core.lef", "LIB/old.lib"],
            "V02": ["LEF/core.lef", "LIB/new.lib"],
        })
        names = {item["relative_path"] for item in result["files"]}
        self.assertEqual(names, {"LEF/core.lef", "LIB/new.lib"})

    def test_latest_liberty_occurrence_replaces_its_historical_copy(self):
        versions = [
            {"id": "V01", "path": "/raw/V01", "delivery_order": 1, "package_type": "FULL_PACKAGE"},
            {"id": "V02", "path": "/raw/V02", "delivery_order": 2, "package_type": "PARTIAL_UPDATE", "previous_effective_version": "V01"},
        ]
        result = self._build(versions, {"V01": ["LEF/core.lef", "LIB/tt.lib"],
                                        "V02": ["LIB/tt.lib"]})
        selected = [item for item in result["files"] if item["relative_path"] == "LIB/tt.lib"]
        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0]["source_version"], "V02")

    def test_partial_active_patch_keeps_observed_candidates_and_marks_unseen_history_unknown(self):
        versions = [
            {"id": "V01", "path": "/raw/V01", "delivery_order": 1, "package_type": "FULL_PACKAGE"},
            {"id": "V02", "path": "/raw/V02", "delivery_order": 2, "package_type": "PARTIAL_UPDATE", "previous_effective_version": "V01"},
        ]
        result = self._build(versions, {"V01": ["LEF/core.lef", "LIB/tt.lib"],
                                        "V02": ["LIB/new.lib"]}, {"V02": "PARTIAL"})
        self.assertEqual(result["status"], "PARTIAL")
        self.assertEqual({item["relative_path"] for item in result["files"]}, {"LIB/new.lib"})
        self.assertTrue(any(item["reason"] == "ACTIVE_CHAIN_SCAN_INCOMPLETE"
                            for item in result["unresolved"]))

    def test_unknown_package_semantics_do_not_union_old_files_into_latest_delivery(self):
        versions = [
            {"id": "V01", "path": "/raw/V01", "delivery_order": 1},
            {"id": "V02", "path": "/raw/V02", "delivery_order": 2},
        ]
        result = self._build(versions, {"V01": ["LEF/core.lef", "LIB/old.lib"],
                                        "V02": ["LIB/new.lib"]})
        self.assertEqual(result["status"], "PARTIAL")
        self.assertEqual({item["relative_path"] for item in result["files"]}, {"LIB/new.lib"})
        self.assertTrue(any(item["reason"] == "PACKAGE_SEMANTICS_UNCONFIRMED"
                            for item in result["unresolved"]))


if __name__ == "__main__":
    unittest.main()
