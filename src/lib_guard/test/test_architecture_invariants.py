from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest.mock import patch

from lib_guard.render.impact import RenderImpact


ROOT = Path(__file__).resolve().parents[3]
SMOKE_CONFIG = ROOT / "work" / "single_library_smoke_20260805" / "lib_guard.yml"
LIBRARY = "vendor_A.openroad_platform.openroad_asap7"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class ArchitectureInvariantTest(unittest.TestCase):
    def test_repository_declares_stable_console_entry_points_and_quality_gates(self) -> None:
        project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        scripts = project["project"]["scripts"]

        self.assertEqual(scripts["lg"], "lib_guard.short_cli:main")
        self.assertEqual(scripts["lib-guard"], "lib_guard.cli:main")
        self.assertEqual(project["project"]["requires-python"], ">=3.11")
        self.assertIn("lib_guard.test*", project["tool"]["setuptools"]["packages"]["find"]["exclude"])

        workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        self.assertIn("python -m compileall -q src", workflow)
        self.assertIn("python -m unittest discover -s src/lib_guard/test -p 'test*.py' -q", workflow)
        self.assertIn("python -m lib_guard.short_cli --help", workflow)
        self.assertIn("python -m lib_guard.cli --help", workflow)

        template = (ROOT / ".github" / "pull_request_template.md").read_text(encoding="utf-8")
        for heading in ("事实层影响", "兼容性", "验证", "投影影响"):
            self.assertIn(heading, template)

    def test_web_mutating_routes_are_frozen_to_the_workbench_allowlist(self) -> None:
        from lib_guard.web.app import WEB_ACTION_SPECS, WEB_MUTATING_ACTIONS, create_app

        app = create_app(config_path=SMOKE_CONFIG, cwd=ROOT, test_config={"TESTING": True})
        post_routes = {
            rule.rule
            for rule in app.url_map.iter_rules()
            if "POST" in rule.methods
        }

        self.assertEqual(
            WEB_MUTATING_ACTIONS,
            frozenset(
                {
                    "catalog-refresh",
                    "worklist",
                    "library-discover",
                    "library-accept",
                    "library-apply",
                    "library-add",
                    "scan",
                    "cmp",
                    "rel",
                    "release-plan",
                    "release-apply",
                    "release-set-plan",
                    "release-set-apply",
                    "release-overwrite-preview",
                    "release-force",
                    "next",
                    "intake",
                    "window",
                    "accept-window",
                    "mark",
                    "override",
                    "file-diff",
                    # Explicit report-only diagnostic action; no governance or release mutation.
                    "semantic-review",
                    "review-gate",
                    "review-packet",
                    "action-file",
                    "effective-rollback",
                }
            ),
        )
        self.assertEqual(WEB_MUTATING_ACTIONS, frozenset(WEB_ACTION_SPECS))
        self.assertEqual(WEB_ACTION_SPECS["scan"].scope, "version")
        self.assertEqual(WEB_ACTION_SPECS["cmp"].cli_action, "cmp")
        self.assertEqual(WEB_ACTION_SPECS["rel"].cli_action, "rel")
        self.assertEqual(WEB_ACTION_SPECS["release-overwrite-preview"].cli_action, "rel")
        self.assertEqual(WEB_ACTION_SPECS["worklist"].scope, "workspace")
        self.assertEqual(
            post_routes,
            {
                "/api/worklist",
                "/api/workspace/init",
                "/api/workspace/config",
                "/api/library/discover",
                "/api/library/accept",
                "/api/library/apply",
                "/api/library/add",
                "/api/libraries/<library>/catalog",
                "/api/libraries/<library>/versions/<version>/scan",
                "/api/libraries/<library>/versions/<version>/compare",
                "/api/libraries/<library>/versions/<version>/release-check",
                "/api/libraries/<library>/versions/<version>/release-plan",
                "/api/libraries/<library>/versions/<version>/release-apply",
                "/api/release-libraries/refresh",
                "/api/formal-directory/refresh",
                "/api/release-libraries/<path:formal_library>/versions/<version>/preview-overwrite",
                "/api/release-libraries/<path:formal_library>/versions/<version>/force-overwrite",
                "/api/libraries/<library>/next",
                "/api/libraries/<library>/intake",
                "/api/libraries/<library>/window",
                "/api/libraries/<library>/accept-window",
                "/api/libraries/<library>/semantic-review",
                "/api/libraries/<library>/versions/<version>/mark",
                "/api/libraries/<library>/versions/<version>/override",
                # Human-authored note write.  It is intentionally not a
                # background action and must not be added to WEB_MUTATING_ACTIONS.
                "/api/libraries/<library>/versions/<version>/update-note",
                "/api/libraries/<library>/versions/<version>/representative-files",
                "/api/libraries/<library>/versions/<version>/file-diff",
                "/api/libraries/<library>/versions/<version>/review-gate",
                "/api/libraries/<library>/versions/<version>/review-packet",
                "/api/libraries/<library>/action",
                "/api/libraries/<library>/effective-rollback",
                "/api/release-set/build",
                "/api/release-set/plan",
                "/api/release-set/apply",
                "/api/release-set/compare",
            },
        )

    def test_web_job_result_is_structured_and_execution_state_only(self) -> None:
        from lib_guard.web.app import _job_status, parse_machine_result

        class FinishedProcess:
            pid = 123

            @staticmethod
            def poll() -> int:
                return 0

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            job_dir = root / "jobs" / "scan_demo"
            job_dir.mkdir(parents=True)
            facts = root / "facts" / "catalog.json"
            facts.parent.mkdir()
            facts.write_text('{"libraries": []}', encoding="utf-8")
            before = _sha256(facts)
            (job_dir / "status.json").write_text(
                json.dumps({"status": "RUNNING", "created_epoch": 1, "started_epoch": 2}),
                encoding="utf-8",
            )
            (job_dir / "stdout.log").write_text(
                "scan progress\n"
                "{\n"
                '  "status": "PASS",\n'
                '  "run_manifest": "/tmp/run_manifest.json"\n'
                "}\n",
                encoding="utf-8",
            )

            parsed = parse_machine_result(job_dir / "stdout.log")
            status = _job_status(job_dir, FinishedProcess())
            after = _sha256(facts)
            result_artifact = json.loads((job_dir / "result.json").read_text(encoding="utf-8"))

            unstructured = job_dir / "unstructured.log"
            unstructured.write_text('message contains "run_manifest": "/tmp/fake.json" only', encoding="utf-8")

            self.assertEqual(parsed["run_manifest"], "/tmp/run_manifest.json")
            self.assertEqual(status["status"], "COMPLETED")
            self.assertEqual(status["run_manifest"], "/tmp/run_manifest.json")
            self.assertEqual(result_artifact["schema_version"], "web_job_result.v1")
            self.assertEqual(result_artifact["cli_result"], parsed)
            self.assertIsNone(parse_machine_result(unstructured))
            self.assertEqual(before, after)
            self.assertFalse(
                {"review_status", "effective_state", "release_lifecycle", "usage_decision"}
                & set(status)
            )

    def test_ten_impacted_versions_load_and_merge_catalog_once(self) -> None:
        from lib_guard.catalog import runtime as catalog_runtime
        from lib_guard.render import version_detail_fast
        from lib_guard.review import state as review_state

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            catalog_path = root / "catalog.json"
            versions = [
                {
                    "version_id": f"v{index}",
                    "version_key": f"demo:v{index}",
                    "raw_path": str(root / "raw" / f"v{index}"),
                    "scan": {"status": "SCANNED"},
                    "diff": {},
                }
                for index in range(10)
            ]
            catalog_path.write_text(
                json.dumps(
                    {
                        "libraries": [
                            {
                                "library_id": "demo",
                                "library_name": "demo",
                                "formal_library_id": "demo",
                                "report_slug": "demo",
                                "versions": versions,
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            impacts = [
                RenderImpact(kind="version_detail", library="demo", version=f"v{index}", reason="test")
                for index in range(10)
            ]

            with (
                patch.object(
                    version_detail_fast,
                    "load_catalog_view",
                    wraps=version_detail_fast.load_catalog_view,
                ) as load_catalog,
                patch.object(
                    catalog_runtime,
                    "merge_catalog_runtime",
                    wraps=catalog_runtime.merge_catalog_runtime,
                ) as runtime_merge,
                patch.object(
                    review_state,
                    "merge_catalog_runtime",
                    wraps=review_state.merge_catalog_runtime,
                ) as review_merge,
                patch("lib_guard.render.version_detail_report.render_version_detail_page") as render_page,
            ):
                render_page.side_effect = lambda _out, _lib, version, **_kwargs: str(
                    root / "html" / str(version["version_id"]) / "index.html"
                )
                result = version_detail_fast.render_impacted_version_details(
                    catalog_path=catalog_path,
                    out_dir=root / "html",
                    impacts=impacts,
                )

        self.assertEqual(result["rendered_versions"], 10)
        self.assertEqual(load_catalog.call_count, 1)
        self.assertEqual(runtime_merge.call_count, 1)
        self.assertEqual(review_merge.call_count, 0)

    def test_web_does_not_publish_an_independent_ip_usage_decision(self) -> None:
        from lib_guard.web.read_model import list_version_rows, load_web_state

        state = load_web_state(config_path=SMOKE_CONFIG, cwd=ROOT)
        row = list_version_rows(state, LIBRARY)[0]

        self.assertNotIn("ip_decision", row)
        self.assertNotIn("usage_decision", row)
        self.assertIn("workflow_status", row)
        self.assertEqual(row["usage_decision_source"], "version_detail_model")
        self.assertTrue(row["version_detail_url"])

    def test_version_detail_projection_is_rebuilt_without_changing_facts(self) -> None:
        from lib_guard.render.version_detail_fast import render_version_detail_only

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            raw = root / "raw" / "v2"
            scan_dir = root / "scan" / "v2"
            diff_dir = root / "diff" / "v2"
            html_root = root / "catalog" / "html"
            raw.mkdir(parents=True)
            scan_dir.mkdir(parents=True)
            diff_dir.mkdir(parents=True)
            (raw / "macro.lef").write_text("MACRO demo\nEND demo\n", encoding="utf-8")
            inventory = scan_dir / "file_inventory.json"
            inventory.write_text(
                json.dumps(
                    {
                        "root_path": str(raw),
                        "files": [
                            {
                                "path": "macro.lef",
                                "name": "macro.lef",
                                "file_type": "lef",
                                "size_bytes": 20,
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            scan_meta = scan_dir / "scan_meta.json"
            scan_meta.write_text(json.dumps({"status": "PASS", "scan_id": "scan-v2"}), encoding="utf-8")
            diff_summary = diff_dir / "diff_summary.json"
            diff_summary.write_text(
                json.dumps({"status": "PASS", "base_version": "v1", "added": 1, "removed": 0, "changed": 0}),
                encoding="utf-8",
            )
            file_diff = diff_dir / "file_diff.json"
            file_diff.write_text(json.dumps({"added": ["macro.lef"], "removed": [], "changed": []}), encoding="utf-8")
            catalog_path = root / "catalog" / "catalog.json"
            catalog_path.parent.mkdir(parents=True, exist_ok=True)
            catalog_path.write_text(
                json.dumps(
                    {
                        "libraries": [
                            {
                                "library_id": "demo",
                                "library_name": "demo",
                                "formal_library_id": "demo",
                                "report_slug": "demo",
                                "versions": [
                                    {"version_id": "v1", "raw_path": str(root / "raw" / "v1")},
                                    {"version_id": "v2", "raw_path": str(raw)},
                                ],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            runtime_path = catalog_path.with_name("catalog_runtime.json")
            runtime_path.write_text(
                json.dumps(
                    {
                        "schema_version": "catalog_runtime.v1",
                        "runtime_state": {
                            "demo:v2": {
                                "scan": {"status": "SCANNED", "scan_id": "scan-v2", "scan_dir": str(scan_dir)},
                                "diff": {
                                    "adjacent_status": "DIFF",
                                    "adjacent_old_version": "v1",
                                    "adjacent_diff_dir": str(diff_dir),
                                },
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            effective_root = html_root / "libraries" / "demo" / "effective"
            effective_manifest = effective_root / "E_v2" / "effective_manifest.json"
            effective_manifest.parent.mkdir(parents=True)
            effective_manifest.write_text(
                json.dumps({"effective_id": "E_v2", "library": "demo", "base_full": "v2"}),
                encoding="utf-8",
            )
            effective_pointer = effective_root / "current_effective.json"
            effective_pointer.write_text(
                json.dumps({"current_effective_id": "E_v2", "manifest": str(effective_manifest)}),
                encoding="utf-8",
            )
            fact_paths = [catalog_path, runtime_path, inventory, scan_meta, diff_summary, file_diff, effective_manifest, effective_pointer]
            before = {str(path): _sha256(path) for path in fact_paths}

            first = render_version_detail_only(
                catalog_path=catalog_path,
                out_dir=html_root,
                library="demo",
                version="v2",
            )
            page = Path(first["version_detail_html"])
            self.assertTrue(page.is_file())
            first_text = page.read_text(encoding="utf-8")

            page.unlink()
            jobs = root / "web_jobs"
            job_dir = jobs / "scan_demo"
            job_dir.mkdir(parents=True)
            (job_dir / "status.json").write_text('{"status": "COMPLETED"}', encoding="utf-8")
            (job_dir / "stdout.log").write_text("transient web output", encoding="utf-8")
            shutil.rmtree(jobs)

            second = render_version_detail_only(
                catalog_path=catalog_path,
                out_dir=html_root,
                library="demo",
                version="v2",
            )
            rebuilt = Path(second["version_detail_html"])
            rebuilt_exists = rebuilt.is_file()
            rebuilt_text = rebuilt.read_text(encoding="utf-8")
            after = {str(path): _sha256(path) for path in fact_paths}

        self.assertTrue(rebuilt_exists)
        self.assertIn("v2", first_text)
        self.assertIn("当前有效版", rebuilt_text)
        self.assertEqual(first_text, rebuilt_text)
        self.assertEqual(before, after)

    def test_catalog_render_text_write_keeps_previous_page_until_replace_succeeds(self) -> None:
        from lib_guard.render.catalog_render_common import write_text

        with tempfile.TemporaryDirectory() as td:
            page = Path(td) / "catalog" / "html" / "libraries" / "demo" / "versions" / "v2" / "index.html"
            page.parent.mkdir(parents=True)
            page.write_text("old complete page", encoding="utf-8")

            with patch("lib_guard.atomic.os.replace", side_effect=RuntimeError("replace failed")):
                with self.assertRaises(RuntimeError):
                    write_text(page, "new complete page")

            self.assertEqual(page.read_text(encoding="utf-8"), "old complete page")


if __name__ == "__main__":
    unittest.main()
