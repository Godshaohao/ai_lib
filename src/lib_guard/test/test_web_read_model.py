from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SMOKE_CONFIG = ROOT / "work" / "single_library_smoke_20260805" / "lib_guard.yml"
LIBRARY = "vendor_A.openroad_platform.openroad_asap7"


class WebReadModelTest(unittest.TestCase):
    def test_no_baseline_is_not_presented_as_completed_compare(self):
        from lib_guard.web.read_model import _action_readiness
        from unittest.mock import patch
        with patch('lib_guard.web.read_model._diff_status', return_value='NO_DIFF'):
            compare = _action_readiness({'version_id': 'first'}, scan_ready=False)['compare']
        self.assertFalse(compare['enabled'])
        self.assertEqual(compare['label'], '无可比基准')
        self.assertNotEqual(compare['button_label'], '按需重跑')

    def test_source_library_rows_preserve_typed_identity_for_release_navigation(self):
        from lib_guard.web.read_model import list_library_rows
        state = {'config': {}, 'catalog': {'libraries': [
            {'library_id': 'ip/A', 'library_name': 'A', 'library_type': 'ip', 'versions': []},
            {'library_id': 'stdcell/A', 'library_name': 'A', 'library_type': 'stdcell', 'versions': []},
        ]}}
        with tempfile.TemporaryDirectory() as td:
            state['catalog_html'] = td
            rows = list_library_rows(state)
        self.assertEqual({row['library_id'] for row in rows}, {'ip/A', 'stdcell/A'})

    def test_formal_release_libraries_are_a_separate_read_projection(self) -> None:
        from lib_guard.web.read_model import list_release_library_rows

        with tempfile.TemporaryDirectory() as td:
            index_path = Path(td) / "release_libraries" / "latest.json"
            index_path.parent.mkdir(parents=True)
            index_path.write_text(
                json.dumps(
                    {
                        "schema_version": "release_library_index.v1",
                        "release_root": "/formal/release",
                        "refreshed_at": "2026-09-21T00:00:00Z",
                        "summary": {"library_count": 1, "release_count": 2},
                        "libraries": [
                            {
                                "library_id": "ip/ucie",
                                "source_type": "正式发布库",
                                "release_count": 2,
                                "current": {
                                    "release_id": "R2",
                                    "version_id": "v2",
                                    "alias": "current",
                                    "link_mode": "symlink",
                                    "published_at": "2026-09-21T00:00:00Z",
                                    "source": "alias_link",
                                },
                                "releases": [{"release_id": "R2"}, {"release_id": "R1"}],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            state = {"config": {"release_library_index": str(index_path)}, "catalog": {"libraries": []}}

            result = list_release_library_rows(state)

        self.assertEqual(result["status"], "READY")
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["libraries"][0]["library_id"], "ip/ucie")
        self.assertEqual(result["libraries"][0]["raw_catalog_match"], "")
        self.assertEqual(result["libraries"][0]["current_alias"], "current")
        self.assertEqual(result["libraries"][0]["current_link_mode"], "symlink")
        self.assertEqual(result["libraries"][0]["current_published_at"], "2026-09-21T00:00:00Z")

    def test_formal_release_library_requires_exact_catalog_library_id(self) -> None:
        """A same-name library in another type must never become an overwrite target."""
        from lib_guard.web.read_model import list_release_library_rows

        with tempfile.TemporaryDirectory() as td:
            index_path = Path(td) / "release_libraries" / "latest.json"
            index_path.parent.mkdir(parents=True)
            index_path.write_text(
                json.dumps(
                    {
                        "schema_version": "release_library_index.v1",
                        "libraries": [
                            {
                                "library_id": "ip/ucie",
                                "release_count": 1,
                                "current": {"release_id": "R1", "version_id": "v1"},
                                "releases": [{"release_id": "R1"}],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            state = {
                "config": {"release_library_index": str(index_path)},
                "catalog": {
                    "libraries": [
                        {"library_id": "stdcell/ucie", "library_name": "ucie", "versions": []}
                    ]
                },
            }

            result = list_release_library_rows(state)

        self.assertEqual(result["libraries"][0]["raw_catalog_match"], "")

    def test_formal_release_library_returns_typed_catalog_token_for_actions(self) -> None:
        from lib_guard.web.read_model import list_release_library_rows, list_version_rows

        with tempfile.TemporaryDirectory() as td:
            index_path = Path(td) / "release_libraries" / "latest.json"
            index_path.parent.mkdir(parents=True)
            index_path.write_text(
                json.dumps(
                    {
                        "schema_version": "release_library_index.v1",
                        "libraries": [
                            {
                                "library_id": "ip/ucie",
                                "release_count": 1,
                                "current": {"release_id": "R1", "version_id": "v1"},
                                "releases": [{"release_id": "R1"}],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            state = {
                "config": {"release_library_index": str(index_path)},
                "catalog_html": Path(td) / "html",
                "catalog": {
                    "libraries": [
                        {"library_id": "stdcell/ucie", "library_name": "ucie", "versions": []},
                        {
                            "library_id": "ip/ucie",
                            "library_name": "ucie",
                            "versions": [{"version_id": "v2", "scan": {"status": "NOT_SCANNED"}}],
                        },
                    ]
                },
            }

            release_row = list_release_library_rows(state)["libraries"][0]
            versions = list_version_rows(state, release_row["raw_catalog_match"])

        self.assertEqual(release_row["raw_catalog_match"], "ip/ucie")
        self.assertEqual(release_row["raw_catalog_name"], "ucie")
        self.assertEqual([row["version_id"] for row in versions], ["v2"])

    def test_load_web_state_reads_existing_catalog_without_discovering_raw(self) -> None:
        from lib_guard.web.read_model import load_web_state

        state = load_web_state(config_path=SMOKE_CONFIG, cwd=ROOT)

        self.assertEqual(state["catalog_path"].name, "catalog.json")
        self.assertEqual([item["library_name"] for item in state["catalog"]["libraries"]], [LIBRARY])
        self.assertEqual(state["config"]["raw_root"], str(ROOT / "tests" / "fixtures" / "raw"))

    def test_list_library_rows_keeps_formal_name_and_latest_summary(self) -> None:
        from lib_guard.web.read_model import list_library_rows, load_web_state

        rows = list_library_rows(load_web_state(config_path=SMOKE_CONFIG, cwd=ROOT))

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["library_name"], LIBRARY)
        self.assertEqual(rows[0]["version_count"], 2)
        self.assertEqual(rows[0]["latest_version"], "20260627_asap7")

    def test_library_pending_count_excludes_scanned_initial_baseline(self) -> None:
        from lib_guard.web.read_model import list_library_rows

        with tempfile.TemporaryDirectory() as td:
            scan_dir = Path(td) / "scan"
            raw_dir = Path(td) / "raw"
            scan_dir.mkdir()
            raw_dir.mkdir()
            (scan_dir / "file_inventory.json").write_text(json.dumps({"files": []}), encoding="utf-8")
            state = {
                "catalog_html": Path(td),
                "catalog": {
                    "libraries": [
                        {
                            "library_name": "demo.lib",
                            "summary": {"version_count": 2, "latest_version": "v2"},
                            "versions": [
                                {
                                    "version_id": "v1",
                                    "raw_path": str(raw_dir),
                                    "scan": {"status": "SCANNED", "scan_dir": str(scan_dir)},
                                    "diff": {"adjacent_status": "NOT_APPLICABLE"},
                                    "release": {"check_status": "UNKNOWN"},
                                },
                                {
                                    "version_id": "v2",
                                    "scan": {"status": "NOT_SCANNED"},
                                    "diff": {"adjacent_old_version": "v1", "adjacent_status": "PENDING"},
                                },
                            ],
                        }
                    ]
                },
            }

            row = list_library_rows(state)[0]

        self.assertEqual(row["workflow_pending_count"], 1)

    def test_library_pending_count_only_tracks_focus_versions_not_all_history(self) -> None:
        from lib_guard.web.read_model import list_library_rows, list_version_rows

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            ready_scan = root / "scan_ready"
            raw_root = root / "raw"
            ready_scan.mkdir()
            raw_root.mkdir()
            (ready_scan / "file_inventory.json").write_text(json.dumps({"files": []}), encoding="utf-8")
            versions = []
            for idx in range(1, 51):
                version_id = f"202607{idx:02d}_demo"
                versions.append(
                    {
                        "version_id": version_id,
                        "raw_path": str(raw_root),
                        "scan": {"status": "NOT_SCANNED"},
                        "diff": {"adjacent_old_version": f"202607{idx - 1:02d}_demo" if idx > 1 else ""},
                    }
                )
            versions[38]["scan"] = {"status": "SCANNED", "scan_dir": str(ready_scan)}
            versions[39]["scan"] = {"status": "SCANNED", "scan_dir": str(ready_scan)}
            versions[39]["current_effective"] = True
            versions[48]["scan"] = {"status": "SCANNED", "scan_dir": str(ready_scan)}
            state = {
                "catalog_html": root,
                "catalog": {
                    "libraries": [
                        {
                            "library_name": "demo.lib",
                            "summary": {"version_count": 50, "latest_version": "20260750_demo"},
                            "versions": versions,
                        }
                    ]
                },
            }

            library_row = list_library_rows(state)[0]
            version_rows = list_version_rows(state, "demo.lib")

        self.assertEqual(library_row["version_count"], 50)
        self.assertEqual(library_row["focus_version_count"], 3)
        self.assertEqual(library_row["workflow_pending_count"], 1)
        self.assertEqual(library_row["new_candidate_pending_count"], 1)
        self.assertEqual(library_row["base_scan_pending_count"], 0)
        self.assertEqual(library_row["effective_hygiene_count"], 0)
        focus_ids = {row["version_id"] for row in version_rows if row["focus_scope"]}
        self.assertEqual(
            focus_ids,
            {"20260740_demo", "20260749_demo", "20260750_demo"},
        )
        self.assertFalse(next(row for row in version_rows if row["version_id"] == "20260701_demo")["focus_scope"])

    def test_library_rows_expose_asset_facets_for_web_navigation(self) -> None:
        from lib_guard.web.read_model import list_library_rows

        with tempfile.TemporaryDirectory() as td:
            state = {
                "catalog_html": Path(td),
                "catalog": {
                    "libraries": [
                        {
                            "library_name": "Vendor_A.ucie",
                            "root_abs": "/proj/libs/Vendor_A/ucie",
                            "vendor": "Vendor_A",
                            "category": "IP",
                            "library_type": "UCIE",
                            "platform": "N7",
                            "summary": {"version_count": 1, "latest_version": "v2"},
                            "versions": [
                                {
                                    "version_id": "v2",
                                    "release": {"status": "RELEASE_BLOCKED", "check_status": "BLOCKED"},
                                }
                            ],
                        }
                    ]
                },
            }

            row = list_library_rows(state)[0]

        self.assertEqual(row["root_abs"], "/proj/libs/Vendor_A/ucie")
        self.assertEqual(row["library_type"], "UCIE")
        self.assertEqual(row["platform"], "N7")
        self.assertEqual(row["release_blocked_count"], 1)
        self.assertEqual(row["has_current_effective"], False)

    def test_library_rows_show_raw_source_root_without_claiming_it_is_registered(self) -> None:
        """Older catalogs may lack a library-level root while versions retain RAW paths."""
        from lib_guard.web.read_model import list_library_rows

        with tempfile.TemporaryDirectory() as td:
            library_root = Path(td) / "raw" / "Vendor_A" / "ucie"
            first = library_root / "20260601"
            second = library_root / "20260608"
            state = {
                "catalog_html": Path(td) / "html",
                "catalog": {
                    "libraries": [
                        {
                            "library_name": "Vendor_A.ucie",
                            "versions": [
                                {"version_id": "20260601", "raw_path": str(first)},
                                {"version_id": "20260608", "raw_path": str(second)},
                            ],
                        }
                    ]
                },
            }

            row = list_library_rows(state)[0]

        self.assertEqual(row["root_abs"], "")
        self.assertEqual(row["root_display"], str(library_root))
        self.assertEqual(row["root_source"], "version_raw_path")

    def test_library_rows_expose_current_effective_stack_and_source(self) -> None:
        from lib_guard.effective.manifest import build_effective_manifest
        from lib_guard.effective.pointer import write_current_pointer
        from lib_guard.web.read_model import list_library_rows

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            effective_dir = root / "libraries" / "ip_demo" / "effective" / "E_fix1"
            effective_dir.mkdir(parents=True)
            catalog = {
                "libraries": [
                    {
                        "library_id": "ip/demo",
                        "library_name": "demo",
                        "versions": [
                            {"version_id": "full", "scan": {"snapshot_identity": {"digest": "sha256:full", "strength": "full"}}},
                            {"version_id": "fix1", "scan": {"snapshot_identity": {"digest": "sha256:fix1", "strength": "full"}}, "update_scope": ["lef"]},
                        ],
                    }
                ]
            }
            manifest = build_effective_manifest(catalog, "demo", "full", [("fix1", ["lef"])], effective_id="E_fix1")
            manifest_path = effective_dir / "effective_manifest.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            write_current_pointer(manifest_path, accepted_by="owner", note="reviewed")
            state = {"catalog_html": root, "catalog": catalog}

            row = list_library_rows(state)[0]

        self.assertEqual(row["current_effective_stack"]["source"], "current_effective_pointer")
        self.assertEqual(row["current_effective_stack"]["base_full_version"], "full")
        self.assertEqual(row["current_effective_stack"]["accepted_updates"], ["fix1"])
        self.assertEqual(row["current_effective_stack"]["source_label"], "当前有效指针")
        self.assertIn("effective_digest", row["current_effective_stack"])

    def test_pending_window_exposes_only_existing_compare_and_saved_combinations(self) -> None:
        from lib_guard.web.read_model import _pending_window
        from lib_guard.window.resolver import default_window_path

        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "html"
            library = {"library_id": "ip/demo", "library_name": "demo"}
            path = default_window_path(root, library, "demo")
            path.parent.mkdir(parents=True)
            compare = path.parent.parent / "compare" / "update" / "index.html"
            snapshot = path.parent.parent / "effective" / "E_old" / "effective_manifest.json"
            snapshot.parent.mkdir(parents=True)
            snapshot.write_text("not read by navigation", encoding="utf-8")
            path.write_text(json.dumps({"state": "PENDING", "compare": {"html": str(compare)}}))
            state = {"catalog_html": root}
            missing = _pending_window(state, library)
            self.assertEqual(missing["compare_url"], "")
            self.assertEqual(missing["saved_combinations"], [{"effective_id": "E_old"}])
            compare.parent.mkdir(parents=True)
            compare.write_text("report")
            candidate_html = snapshot.parent/'index.html'
            candidate_html.write_text('composition and conflicts')
            path.write_text(json.dumps({'state': 'PENDING', 'compare': {'html': str(compare)}, 'candidate_effective': {'html': str(candidate_html), 'rule': 'manual_selection'}}))
            ready = _pending_window(state, library)
            self.assertEqual(ready['candidate_html_url'], '/artifacts/' + candidate_html.relative_to(root).as_posix())
            self.assertEqual(ready['candidate_effective_stack']['source_label'], '人工选择')
            self.assertEqual(ready["compare_url"], "/artifacts/" + compare.relative_to(root).as_posix())
            outside = root.parent / "outside.html"
            outside.write_text("outside report")
            path.write_text(json.dumps({"compare": {"html": str(outside)}}))
            self.assertEqual(_pending_window(state, library)["compare_url"], "")
            path.unlink()
            without_window = _pending_window(state, library)
            self.assertEqual(without_window["state"], "MISSING")
            self.assertEqual(without_window["saved_combinations"], [{"effective_id": "E_old"}])

    def test_initial_baseline_has_own_review_label_without_comparison(self) -> None:
        from lib_guard.web.read_model import _workflow_status

        with tempfile.TemporaryDirectory() as td:
            scan_dir = Path(td) / "scan"
            raw_dir = Path(td) / "raw"
            scan_dir.mkdir()
            raw_dir.mkdir()
            (scan_dir / "file_inventory.json").write_text(json.dumps({"files": []}), encoding="utf-8")

            result = _workflow_status(
                {
                    "raw_path": str(raw_dir),
                    "scan": {"status": "SCANNED", "scan_dir": str(scan_dir)},
                    "diff": {"adjacent_status": "NOT_APPLICABLE"},
                    "release": {"check_status": "UNKNOWN"},
                },
                is_initial_baseline=True,
            )

        self.assertEqual(result["label"], "初始基线")
        self.assertEqual(result["next_action"], "查看详情")

    def test_list_version_rows_returns_statuses_and_existing_detail_link(self) -> None:
        from lib_guard.web.read_model import list_version_rows, load_web_state

        state = load_web_state(config_path=SMOKE_CONFIG, cwd=ROOT)
        rows = list_version_rows(state, LIBRARY)

        self.assertEqual([row["version_id"] for row in rows], ["20260627_asap7", "20260624_asap7"])
        self.assertIn(rows[0]["scan_status"], {"PASS", "SCANNED", "NOT_SCANNED", "STALE_SCAN"})
        self.assertIn("version_detail_path", rows[0])

    def test_list_version_rows_exposes_action_readiness_for_the_workbench(self) -> None:
        from lib_guard.web.read_model import list_version_rows, load_web_state

        state = load_web_state(config_path=SMOKE_CONFIG, cwd=ROOT)
        rows = list_version_rows(state, LIBRARY)

        newest = rows[0]
        self.assertEqual(newest["action_readiness"]["scan"]["enabled"], True)
        self.assertEqual(newest["action_readiness"]["compare"]["enabled"], True)
        self.assertEqual(newest["action_readiness"]["release-check"]["enabled"], True)

        from lib_guard.web.read_model import _action_readiness

        unscanned = _action_readiness({"scan": {"status": "NOT_SCANNED"}})
        self.assertEqual(unscanned["compare"]["enabled"], False)
        self.assertIn("先完成扫描", unscanned["compare"]["reason"])
        self.assertEqual(unscanned["release-check"]["enabled"], False)
        self.assertIn("先完成扫描", unscanned["release-check"]["reason"])

    def test_unscanned_version_prioritizes_scan_before_missing_base(self) -> None:
        from lib_guard.web.read_model import _action_readiness, _workflow_status

        version = {"scan": {"status": "NOT_SCANNED"}}
        readiness = _action_readiness(version)

        self.assertIn("先完成扫描", readiness["compare"]["reason"])
        self.assertEqual(_workflow_status(version)["label"], "待生成扫描")
        self.assertEqual(_workflow_status(version)["next_action"], "生成扫描")

    def test_scanned_catalog_record_without_evidence_requires_rescan(self) -> None:
        from lib_guard.web.read_model import _action_readiness, _change_summary, _workflow_status, scan_evidence_ready

        version = {
            "scan": {"status": "SCANNED", "scan_dir": "/tmp/lib_guard_missing_scan_evidence"},
            "diff": {"base_version": "v1", "base_status": "DIFF_DONE"},
        }
        readiness = _action_readiness(version)

        self.assertFalse(scan_evidence_ready(version))
        self.assertEqual(readiness["scan"]["label"], "需补扫")
        self.assertEqual(readiness["scan"]["button_label"], "补扫")
        self.assertIn("证据文件不可用", readiness["scan"]["reason"])
        self.assertEqual(readiness["compare"]["enabled"], False)
        self.assertEqual(readiness["release-check"]["enabled"], False)
        self.assertEqual(_change_summary(version, scan_ready=False), "对比记录待验证")
        self.assertEqual(_workflow_status(version, scan_ready=False)["label"], "需补扫")

    def test_explicit_effective_pointer_overrides_catalog_review_flag(self) -> None:
        from lib_guard.web.read_model import _workflow_status

        with tempfile.TemporaryDirectory() as td:
            scan_dir = Path(td) / "scan"
            scan_dir.mkdir()
            (scan_dir / "file_inventory.json").write_text(json.dumps({"files": []}), encoding="utf-8")
            version = {
                "current_effective": False,
                "scan": {"status": "SCANNED", "scan_dir": str(scan_dir)},
                "diff": {"adjacent_status": "NOT_APPLICABLE"},
                "release": {"check_status": "UNKNOWN"},
            }

            self.assertEqual(_workflow_status(version, current_effective=True)["label"], "当前可用版本")

    def test_completed_compare_and_release_results_get_repeat_labels(self) -> None:
        from lib_guard.web.read_model import _action_readiness, _diff_status

        readiness = _action_readiness(
            {
                "scan": {"status": "SCANNED"},
                "scan_dir": str(ROOT / "work" / "single_library_smoke_20260805" / "scan_out" / "ip" / "vendor_A.openroad_platform.openroad_asap7" / "20260627_asap7" / "runs" / "scan_20260825_154920"),
                "diff": {"base_version": "v1", "base_status": "DIFF_DONE"},
                "release": {"check_status": "CHECKED"},
            }
        )

        self.assertEqual(readiness["scan"]["label"], "已有扫描")
        self.assertIn("无需重复扫描", readiness["scan"]["reason"])
        self.assertEqual(readiness["compare"]["label"], "已有对比")
        self.assertIn("默认沿用已有扫描证据", readiness["compare"]["reason"])
        self.assertEqual(readiness["release-check"]["label"], "重新检查")

        version = {
            "diff": {
                "adjacent_old_version": "adjacent",
                "adjacent_status": "PENDING",
                "base_version": "explicit",
                "base_status": "DIFF_DONE",
            }
        }
        self.assertEqual(_diff_status(version), "PENDING")
        self.assertEqual(_diff_status(version, "cumulative"), "DIFF_DONE")

        same_base = {
            "diff": {
                "adjacent_old_version": "v1",
                "adjacent_status": "PENDING",
                "base_version": "v1",
                "base_status": "DIFF_DONE",
            }
        }
        self.assertEqual(_diff_status(same_base), "DIFF_DONE")

    def test_malformed_pending_window_is_visible_as_invalid(self) -> None:
        from lib_guard.web.read_model import _pending_window
        from lib_guard.window.resolver import default_window_path

        with tempfile.TemporaryDirectory() as td:
            library = {"library_id": "ip/vendor_A.ucie", "library_name": "vendor_A.ucie"}
            path = default_window_path(td, library, library["library_name"])
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps([]), encoding="utf-8")

            result = _pending_window({"catalog_html": td}, library)

        self.assertEqual(result["state"], "INVALID")
        self.assertEqual(result["candidate_effective_id"], "")

    def test_corrupt_catalog_is_not_reported_as_an_empty_pass(self) -> None:
        from lib_guard.web.read_model import load_web_state

        with tempfile.TemporaryDirectory() as td:
            catalog = Path(td) / "catalog.json"
            catalog.write_text("{bad json", encoding="utf-8")

            with self.assertRaises(OSError):
                load_web_state(
                    config={"catalog": str(catalog), "workspace": td, "raw_root": td},
                    cwd=td,
                )

    def test_missing_catalog_can_be_loaded_as_explicit_bootstrap_state(self) -> None:
        from lib_guard.web.read_model import load_web_state

        with tempfile.TemporaryDirectory() as td:
            catalog = Path(td) / "catalog" / "catalog.json"

            state = load_web_state(
                config={"catalog": str(catalog), "workspace": td, "raw_root": td},
                cwd=td,
                allow_missing_catalog=True,
            )

        self.assertEqual(state["catalog"]["libraries"], [])
        self.assertEqual(state["catalog_state"], "NOT_INITIALIZED")
        self.assertEqual(state["runtime_state"]["status"], "MISSING")

    def test_library_candidate_snapshot_is_read_only_and_enriches_rows(self) -> None:
        """Candidate display reads the saved snapshot; it never walks RAW again."""

        from lib_guard.library_registry import write_library_rows
        from lib_guard.web.read_model import list_library_candidate_rows

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            candidate_root = root / "raw" / "Vendor_A" / "ucie"
            candidate_root.mkdir(parents=True)
            candidates = root / "config" / "library_candidates" / "latest.tsv"
            registry = root / "config" / "library_registry.tsv"
            write_library_rows(
                candidates,
                [{
                    "status": "REVIEW",
                    "library_id": "Vendor_A.ucie",
                    "root_abs": str(candidate_root),
                    "display_name": "ucie",
                    "vendor": "Vendor_A",
                    "middle_path": "",
                }],
            )
            candidates.with_suffix(".json").write_text(
                json.dumps({
                    "warnings": ["目录遍历已受上限约束"],
                    "truncated": False,
                    "candidates": [{
                        "library_id": "Vendor_A.ucie",
                        "root_abs": str(candidate_root),
                        "version_count": 3,
                        "example_versions": ["v1", "v2"],
                        "confidence": 0.92,
                        "reason": "同级目录包含多个版本",
                    }],
                }),
                encoding="utf-8",
            )

            result = list_library_candidate_rows({
                "config": {"library_candidates": str(candidates), "library_registry": str(registry)},
            })

            self.assertEqual(result["status"], "READY")
            self.assertEqual(result["count"], 1)
            self.assertEqual(result["warnings"], ["目录遍历已受上限约束"])
            row = result["candidates"][0]
            self.assertTrue(row["candidate_id"])
            self.assertEqual(row["version_count"], 3)
            self.assertEqual(row["confidence"], 0.92)
            self.assertFalse(row["already_registered"])

            write_library_rows(registry, [{**row, "status": "OK"}])
            registered = list_library_candidate_rows({
                "config": {"library_candidates": str(candidates), "library_registry": str(registry)},
            })
            self.assertTrue(registered["candidates"][0]["already_registered"])

            other_root = root / "raw" / "Vendor_A" / "ucie_other"
            other_root.mkdir()
            write_library_rows(registry, [{
                "status": "OK",
                "library_id": "Vendor_A.ucie",
                "root_abs": str(other_root),
                "display_name": "ucie_other",
                "vendor": "Vendor_A",
                "middle_path": "",
            }])
            conflicting = list_library_candidate_rows({
                "config": {"library_candidates": str(candidates), "library_registry": str(registry)},
            })
            self.assertFalse(conflicting["candidates"][0]["already_registered"])
            self.assertTrue(conflicting["candidates"][0]["name_conflict"])

    def test_scan_evidence_requires_this_version_inventory(self) -> None:
        from lib_guard.web.read_model import scan_evidence_ready

        with tempfile.TemporaryDirectory() as td:
            scan_dir = Path(td) / "scan"
            raw_dir = Path(td) / "raw"
            scan_dir.mkdir()
            raw_dir.mkdir()
            self.assertFalse(scan_evidence_ready({"scan": {"status": "SCANNED", "scan_dir": str(scan_dir)}}))
            (scan_dir / "file_inventory.json").write_text(json.dumps({"files": []}), encoding="utf-8")
            self.assertTrue(scan_evidence_ready({"raw_path": str(raw_dir), "scan": {"status": "SCANNED", "scan_dir": str(scan_dir)}}))

    def test_scan_evidence_rejects_missing_raw_path_even_when_old_scan_exists(self) -> None:
        from lib_guard.web.read_model import scan_evidence_ready

        with tempfile.TemporaryDirectory() as td:
            scan_dir = Path(td) / "scan"
            scan_dir.mkdir()
            missing_raw = Path(td) / "missing-raw"
            (scan_dir / "scan_meta.json").write_text(
                json.dumps({"scan_id": "old", "root_path": str(missing_raw), "status": "PASS"}),
                encoding="utf-8",
            )
            (scan_dir / "file_inventory.json").write_text(json.dumps({"files": [{"path": "LEF/a.lef"}]}), encoding="utf-8")

            self.assertFalse(
                scan_evidence_ready(
                    {"raw_path": str(missing_raw), "scan": {"status": "SCANNED", "scan_dir": str(scan_dir), "scan_id": "old"}}
                )
            )

    def test_file_tree_reports_stale_scan_when_raw_root_moved(self) -> None:
        from lib_guard.web.read_model import list_file_tree_rows

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            scan_dir = root / "scan"
            scan_dir.mkdir()
            missing_raw = root / "missing-raw"
            (scan_dir / "scan_meta.json").write_text(
                json.dumps({"scan_id": "old", "root_path": str(missing_raw), "status": "PASS"}),
                encoding="utf-8",
            )
            (scan_dir / "file_inventory.json").write_text(json.dumps({"files": [{"path": "LEF/a.lef"}]}), encoding="utf-8")
            state = {
                "catalog": {
                    "libraries": [
                        {
                            "library_name": "demo",
                            "versions": [
                                {
                                    "version_id": "v1",
                                    "raw_path": str(missing_raw),
                                    "scan": {"status": "SCANNED", "scan_dir": str(scan_dir), "scan_id": "old"},
                                }
                            ],
                        }
                    ]
                }
            }

            result = list_file_tree_rows(state, "demo", "v1")

        self.assertEqual(result["status"], "STALE")
        self.assertEqual(result["file_count"], 0)

    def test_scan_evidence_rejects_mismatched_scan_identity(self) -> None:
        from lib_guard.web.read_model import scan_evidence_ready

        with tempfile.TemporaryDirectory() as td:
            scan_dir = Path(td) / "scan"
            scan_dir.mkdir()
            (scan_dir / "file_inventory.json").write_text(
                json.dumps({"scan_id": "old", "root_path": str(Path(td) / "old-root"), "files": []}),
                encoding="utf-8",
            )
            version = {
                "raw_path": str(Path(td) / "new-root"),
                "scan": {"status": "SCANNED", "scan_dir": str(scan_dir), "scan_id": "new"},
            }

            self.assertFalse(scan_evidence_ready(version))

    def test_failed_compare_is_not_reported_as_completed(self) -> None:
        from lib_guard.web.read_model import _workflow_status

        with tempfile.TemporaryDirectory() as td:
            scan_dir = Path(td) / "scan"
            scan_dir.mkdir()
            (scan_dir / "file_inventory.json").write_text(json.dumps({"files": []}), encoding="utf-8")
            result = _workflow_status(
                {
                    "scan": {"status": "SCANNED", "scan_dir": str(scan_dir)},
                    "diff": {"base_version": "base", "base_status": "FAILED"},
                    "release": {"check_status": "UNKNOWN"},
                }
            )

        self.assertEqual(result["label"], "对比失败")
        self.assertEqual(result["next_action"], "查看对比结果")

    def test_unknown_library_returns_empty_version_rows(self) -> None:
        from lib_guard.web.read_model import list_version_rows, load_web_state

        state = load_web_state(config_path=SMOKE_CONFIG, cwd=ROOT)

        self.assertEqual(list_version_rows(state, "missing.library"), [])

    def test_file_tree_reads_inventory_without_walking_raw(self) -> None:
        from lib_guard.web.read_model import list_file_tree_rows

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            scan_dir = root / "scan"
            raw_dir = root / "raw"
            scan_dir.mkdir()
            raw_dir.mkdir()
            (scan_dir / "file_inventory.json").write_text(
                json.dumps(
                    {
                        "root_path": str(root / "raw"),
                        "files": [
                            {"path": "LEF/macro.lef", "file_type": "lef", "size_bytes": 42, "role": "physical"},
                            {"path": "LIB/slow.lib", "file_type": "liberty", "size_bytes": 2048, "is_large_hash_skipped": True},
                        ],
                    }
                ),
                encoding="utf-8",
            )
            state = {
                "catalog": {
                    "libraries": [
                        {
                            "library_name": "demo",
                            "versions": [{"version_id": "v1", "raw_path": str(raw_dir), "scan": {"status": "SCANNED", "scan_dir": str(scan_dir)}}],
                        }
                    ]
                }
            }
            result = list_file_tree_rows(state, "demo", "v1")

        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["file_count"], 2)
        self.assertEqual([item["path"] for item in result["files"]], ["LEF/macro.lef", "LIB/slow.lib"])
        self.assertEqual([item["display_path"] for item in result["files"]], ["LEF/macro.lef", "LIB/slow.lib"])
        self.assertEqual(result["files"][1]["evidence"], "大文件未读取完整内容")

    def test_file_tree_hides_single_packaging_root_only_in_display_path(self) -> None:
        from lib_guard.web.read_model import list_file_tree_rows

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            scan_dir = root / "scan"
            raw_dir = root / "raw"
            scan_dir.mkdir()
            raw_dir.mkdir()
            (scan_dir / "file_inventory.json").write_text(
                json.dumps(
                    {
                        "root_path": str(root / "raw"),
                        "files": [
                            {"path": "upstream_ae9a8ed9/lef/macro.lef", "size_bytes": 3},
                            {"path": "upstream_ae9a8ed9/lib/cell.lib", "size_bytes": 4},
                        ],
                    }
                ),
                encoding="utf-8",
            )
            state = {
                "catalog": {
                    "libraries": [
                        {
                            "library_name": "demo",
                            "versions": [{"version_id": "v1", "raw_path": str(raw_dir), "scan": {"status": "SCANNED", "scan_dir": str(scan_dir)}}],
                        }
                    ]
                }
            }
            result = list_file_tree_rows(state, "demo", "v1")

        self.assertEqual([item["path"] for item in result["files"]], ["upstream_ae9a8ed9/lef/macro.lef", "upstream_ae9a8ed9/lib/cell.lib"])
        self.assertEqual([item["display_path"] for item in result["files"]], ["lef/macro.lef", "lib/cell.lib"])

    def test_file_tree_missing_inventory_is_explicit(self) -> None:
        from lib_guard.web.read_model import list_file_tree_rows

        state = {
            "catalog": {
                "libraries": [
                    {"library_name": "demo", "versions": [{"version_id": "v1", "scan": {"scan_dir": "/missing/scan"}}]}
                ]
            }
        }

        result = list_file_tree_rows(state, "demo", "v1")

        self.assertEqual(result["status"], "NOT_READY")
        self.assertEqual(result["files"], [])


if __name__ == "__main__":
    unittest.main()
