from __future__ import annotations

import json
import tempfile
import unittest
from argparse import Namespace
from importlib.resources import files
from pathlib import Path


class ArtifactContractTest(unittest.TestCase):
    def test_direct_scan_config_uses_canonical_default_path(self) -> None:
        from lib_guard.cli_commands.scan import build_scan_config

        args = Namespace(
            out=None,
            out_template=None,
            workdir="/tmp/work",
            profile="ip",
            name="ucie",
            version="v1",
            mode="scan",
            scan_id="S1",
            root="/tmp/raw/ucie/v1",
            state_dir=None,
            cache_dir=None,
            config=None,
            no_progress=True,
            console_progress=False,
            progress_interval=1,
            parse_jobs=1,
            skip_cache=False,
            no_cache=False,
            hash_policy=None,
            parse_file_types=None,
            parse_exclude_file_types=None,
            package_type=None,
            update_scope=None,
            standalone=None,
            base_required=None,
            base_version=None,
            write_raw_parser_results=False,
        )

        config = build_scan_config(args)
        self.assertEqual(config.out_dir, "/tmp/work/scan_out/ip/ucie/v1/runs/scan_S1")

    def test_scan_path_is_identical_for_direct_and_catalog_workflows(self) -> None:
        from lib_guard.artifacts import canonical_scan_dir

        expected = Path("/tmp/work/scan_out/ip/ucie/v1/runs/scan_S1")
        self.assertEqual(
            canonical_scan_dir(
                "/tmp/work",
                library_type="ip",
                library_name="ucie",
                version="v1",
                mode="scan",
                scan_id="S1",
            ),
            expected,
        )

    def test_run_manifest_lists_facts_reports_and_comparison(self) -> None:
        from lib_guard.artifacts import write_run_manifest

        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "scan"
            manifest_path = write_run_manifest(
                root,
                operation="compare",
                status="DIFF",
                run_id="base_v0_to_v1",
                library_type="ip",
                library_name="ucie",
                version="v1",
                inputs={"catalog": "/tmp/work/catalog/catalog.json"},
                comparison={
                    "base_version": "v0",
                    "base_source": "current_effective",
                    "base_scan_dir": "/tmp/work/scan_out/ip/ucie/v0/runs/scan_B1",
                },
                artifacts={
                    "facts": {"diff": str(root / "diff.json")},
                    "reports": {"compare_html": str(root / "report.html")},
                    "projections": {"version_detail": "/tmp/work/catalog/html/libraries/ip_ucie/versions/v1/index.html"},
                },
            )

            self.assertEqual(manifest_path, root / "run_manifest.json")
            self.assertFalse((root / ".run_manifest.json.lock").exists())
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(data["schema_version"], "run_manifest.v1")
            self.assertEqual(data["producer"], "lib_guard")
            self.assertEqual(data["generated_at"], data["created_at"])
            self.assertEqual(
                data["identity"],
                {
                    "library_id": "ucie",
                    "version_id": "v1",
                    "run_id": "base_v0_to_v1",
                    "evidence_id": "compare:base_v0_to_v1",
                },
            )
            self.assertEqual(data["operation"], "compare")
            self.assertEqual(data["comparison"]["base_version"], "v0")
            self.assertEqual(data["artifacts"]["facts"]["diff"], str(root / "diff.json"))
            self.assertEqual(data["artifacts"]["reports"]["compare_html"], str(root / "report.html"))

    def test_manifest_write_does_not_delete_existing_evidence(self) -> None:
        from lib_guard.artifacts import write_run_manifest

        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "scan"
            evidence = root / "scan_meta.json"
            evidence.parent.mkdir(parents=True)
            evidence.write_text('{"status":"PASS"}\n', encoding="utf-8")

            write_run_manifest(
                root,
                operation="scan",
                status="PASS",
                run_id="scan_S1",
                library_type="ip",
                library_name="ucie",
                version="v1",
                artifacts={"facts": {"scan_meta": str(evidence)}},
            )

            self.assertEqual(evidence.read_text(encoding="utf-8"), '{"status":"PASS"}\n')

    def test_compare_artifacts_uses_actual_diff_fact_names(self) -> None:
        from lib_guard.artifacts import compare_artifacts

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "diff_summary.json").write_text("{}\n", encoding="utf-8")
            (root / "view_diff.json").write_text("{}\n", encoding="utf-8")
            (root / "diff.json").write_text("{}\n", encoding="utf-8")

            artifacts = compare_artifacts(root, compare_html=str(root / "diff_html" / "index.html"))

            self.assertIn("diff_summary.json", artifacts["facts"])
            self.assertIn("view_diff.json", artifacts["facts"])
            self.assertNotIn("diff.json", artifacts["facts"])
            self.assertEqual(artifacts["reports"]["compare_html"], str(root / "diff_html" / "index.html"))

    def test_run_manifest_schema_covers_the_public_contract(self) -> None:
        schema_resource = files("lib_guard").joinpath("schemas/run_manifest.v1.schema.json")
        self.assertTrue(schema_resource.is_file())
        schema = json.loads(schema_resource.read_text(encoding="utf-8"))

        self.assertEqual(schema["$id"], "https://lib-guard.local/schemas/run_manifest.v1.schema.json")
        self.assertEqual(schema["properties"]["schema_version"]["const"], "run_manifest.v1")
        self.assertTrue(
            {"schema_version", "producer", "generated_at", "operation", "status", "identity", "artifacts"}
            <= set(schema["required"])
        )
        self.assertTrue(
            {"library_id", "version_id", "run_id", "evidence_id"}
            <= set(schema["properties"]["identity"]["required"])
        )


if __name__ == "__main__":
    unittest.main()
