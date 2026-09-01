from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class MultiVersionHardeningTest(unittest.TestCase):
    def test_web_state_reports_catalog_runtime_sidecar_health(self) -> None:
        from lib_guard.web.read_model import load_web_state

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            catalog = root / "catalog.json"
            catalog.write_text(json.dumps({"libraries": []}), encoding="utf-8")
            (root / "catalog_runtime.json").write_text(
                json.dumps(
                    {
                        "schema_version": "catalog_runtime.v1",
                        "runtime_state": {"ip/demo/v1": {"scan": {"status": "PASS"}}},
                    }
                ),
                encoding="utf-8",
            )

            state = load_web_state(
                config={"catalog": str(catalog), "workspace": str(root), "raw_root": str(root)},
                cwd=root,
            )

        self.assertEqual(state["runtime_state"]["status"], "AVAILABLE")
        self.assertEqual(state["runtime_state"]["source"], "catalog_runtime.json")
        self.assertEqual(state["runtime_state"]["entry_count"], 1)

    def test_web_state_reports_missing_runtime_sidecar_without_hiding_it(self) -> None:
        from lib_guard.web.read_model import load_web_state

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            catalog = root / "catalog.json"
            catalog.write_text(json.dumps({"libraries": []}), encoding="utf-8")
            state = load_web_state(
                config={"catalog": str(catalog), "workspace": str(root), "raw_root": str(root)},
                cwd=root,
            )

        self.assertEqual(state["runtime_state"]["status"], "MISSING")
        self.assertEqual(state["runtime_state"]["entry_count"], 0)

    def test_large_file_metadata_candidate_is_not_reported_as_added_or_removed(self) -> None:
        from lib_guard.diff.scan_diff import _file_diff

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            old = root / "old"
            new = root / "new"
            old.mkdir()
            new.mkdir()
            (old / "file_inventory.json").write_text(
                json.dumps(
                    {
                        "files": [
                            {
                                "path": "old_root/lef/a/core.lef",
                                "file_type": "lef",
                                "size_bytes": 100_000_000,
                                "hash": None,
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            (new / "file_inventory.json").write_text(
                json.dumps(
                    {
                        "files": [
                            {
                                "path": "new_root/lef/b/core.lef",
                                "file_type": "lef",
                                "size_bytes": 100_000_000,
                                "hash": None,
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            result = _file_diff(old, new)

        self.assertEqual(result["added"], [])
        self.assertEqual(result["removed"], [])
        self.assertEqual(len(result["unverified"]), 1)
        self.assertEqual(result["unverified"][0]["reason"], "metadata_name_size_candidate")

    def test_version_rows_use_one_scan_evidence_check_per_version(self) -> None:
        from lib_guard.web.read_model import list_version_rows

        state = {
            "catalog_html": tempfile.gettempdir(),
            "catalog": {
                "libraries": [
                    {
                        "library_name": "demo",
                        "versions": [
                            {
                                "version_id": "v1",
                                "scan": {"status": "SCANNED", "scan_dir": "/scan/v1"},
                                "diff": {"base_version": "base", "base_status": "DIFF_DONE"},
                            }
                        ],
                    }
                ]
            },
        }

        with patch("lib_guard.web.read_model.scan_evidence_ready", return_value=True) as ready:
            list_version_rows(state, "demo")

        self.assertEqual(ready.call_count, 1)

    def test_scan_readiness_uses_scan_metadata_without_parsing_inventory(self) -> None:
        from lib_guard.web.read_model import scan_evidence_ready

        with tempfile.TemporaryDirectory() as td:
            scan_dir = Path(td) / "scan"
            scan_dir.mkdir()
            (scan_dir / "file_inventory.json").write_text("not-json", encoding="utf-8")
            (scan_dir / "scan_meta.json").write_text(
                json.dumps({"scan_id": "scan-1", "status": "PASS", "root_path": "/raw/demo/v1"}),
                encoding="utf-8",
            )

            self.assertTrue(
                scan_evidence_ready(
                    {
                        "raw_path": "/raw/demo/v1",
                        "scan": {"status": "SCANNED", "scan_dir": str(scan_dir), "scan_id": "scan-1"},
                    }
                )
            )

    def test_version_rows_support_bounded_pagination(self) -> None:
        from lib_guard.web.read_model import list_version_rows

        state = {
            "catalog_html": tempfile.gettempdir(),
            "catalog": {
                "libraries": [
                    {
                        "library_name": "demo",
                        "versions": [{"version_id": f"v{i}"} for i in range(5)],
                    }
                ]
            },
        }

        rows = list_version_rows(state, "demo", offset=1, limit=2)

        self.assertEqual([row["version_id"] for row in rows], ["v3", "v2"])

    def test_versions_endpoint_reports_catalog_total_for_pagination(self) -> None:
        from lib_guard.web.app import create_app

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            catalog = root / "catalog.json"
            catalog.write_text(
                json.dumps(
                    {
                        "libraries": [
                            {
                                "library_name": "demo",
                                "versions": [{"version_id": f"v{i}"} for i in range(3)],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            config = root / "lib_guard.yml"
            config.write_text(
                f"workspace: {root}\ncatalog: {catalog}\nraw_root: {root}\n",
                encoding="utf-8",
            )
            app = create_app(config_path=config, cwd=root, test_config={"TESTING": True})
            with patch("lib_guard.web.app.list_library_rows", side_effect=AssertionError("不应计算全库摘要")):
                with app.test_client() as client:
                    response = client.get("/api/libraries/demo/versions?offset=0&limit=2")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["pagination"], {"offset": 0, "limit": 2, "total": 3, "next_offset": 2})


if __name__ == "__main__":
    unittest.main()
