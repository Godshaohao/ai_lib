from __future__ import annotations

import compileall
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[3]


class RepositoryCleanupTest(unittest.TestCase):
    def test_compileall_src_passes(self) -> None:
        self.assertTrue(compileall.compile_dir(str(ROOT / "src"), quiet=1, force=True))

    def test_docs_have_status_header(self) -> None:
        missing: list[str] = []
        for path in (ROOT / "docs").rglob("*.md"):
            text = path.read_text(encoding="utf-8", errors="ignore")[:300]
            if "Status: current" not in text and "Status: archived" not in text:
                missing.append(path.relative_to(ROOT).as_posix())
        self.assertFalse(missing, "docs missing status header:\n" + "\n".join(missing))

    def test_current_user_facing_text_has_no_stale_workflow_copy(self) -> None:
        tokens = [
            "File Diff 2/5",
            "done/total",
            "codex-runtimes",
            "lg_effective.csh",
            "lib_guard CLI v5",
            "Build v5 HTML",
        ]
        roots = [ROOT / "README.md", ROOT / "AGENT.md", ROOT / "docs", ROOT / "scripts", ROOT / "src" / "lib_guard"]
        old_policy_name = re.compile(r"(?<!legacy_)summary_policy\.json")
        hits: list[str] = []
        for root in roots:
            paths = [root] if root.is_file() else list(root.rglob("*"))
            for path in paths:
                if not path.is_file():
                    continue
                rel = path.relative_to(ROOT).as_posix()
                if rel.startswith("docs/archive/") or "/test/" in rel:
                    continue
                if path.suffix.lower() not in {".py", ".md", ".csh", ".ps1", ".cmd"}:
                    continue
                text = path.read_text(encoding="utf-8", errors="ignore")
                for token in tokens:
                    if token in text:
                        hits.append(f"{rel}: {token}")
                if not rel.startswith("src/lib_guard/") and old_policy_name.search(text):
                    hits.append(f"{rel}: summary_policy.json")
        self.assertFalse(hits, "stale workflow copy found:\n" + "\n".join(hits))

    def test_readme_documents_normal_version_review_path(self) -> None:
        text = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("Catalog -> Version Review -> Release", text)
        self.assertNotIn("Catalog -> Library Workspace -> Version Review -> Comparison Review -> File Diff -> Release", text)
        self.assertIn("Library Workspace", text)
        self.assertIn("高级", text)
        self.assertIn("Comparison Review", text)
        self.assertIn("手动", text)

    def test_cli_reference_separates_refresh_from_manual_compare(self) -> None:
        text = (ROOT / "docs" / "cli_reference.md").read_text(encoding="utf-8")
        self.assertIn("`refresh`", text)
        self.assertIn("current_effective", text)
        self.assertIn("previous_effective", text)
        self.assertIn("adjacent", text)
        self.assertIn("显式", text)
        self.assertIn("SUMMARY_ONLY_TYPES", text)
        self.assertIn("BINARY_METADATA_ONLY_TYPES", text)
        self.assertIn("DEFAULT_FILE_DIFF_TYPES", text)

    def test_data_contract_documents_update_detail_model_and_lanes(self) -> None:
        text = (ROOT / "docs" / "data_contract.md").read_text(encoding="utf-8")
        required = [
            "version_update_detail_model",
            "diff_summary",
            "view_diff",
            "type_diff",
            "release_readiness_diff",
            "release_evidence_diff",
            "diff_issues",
            "file_diff",
            "release_notes",
            "SUMMARY_ONLY_TYPES",
            "BINARY_METADATA_ONLY_TYPES",
            "DEFAULT_FILE_DIFF_TYPES",
        ]
        missing = [token for token in required if token not in text]
        self.assertFalse(missing, "data contract missing tokens:\n" + "\n".join(missing))

    def test_current_tests_are_not_v5_named(self) -> None:
        stale = sorted((ROOT / "src" / "lib_guard" / "test").glob("test_v5_*.py"))
        self.assertEqual([], [path.relative_to(ROOT).as_posix() for path in stale])

    def test_catalog_workspace_owns_public_catalog_workspace_pages(self) -> None:
        catalog_report = (ROOT / "src" / "lib_guard" / "render" / "catalog_report.py").read_text(encoding="utf-8")
        workspace_report = (ROOT / "src" / "lib_guard" / "render" / "catalog_workspace_report.py").read_text(encoding="utf-8")
        self.assertIn("def render_catalog_html", catalog_report)
        self.assertNotIn("def render_catalog_index_page", catalog_report)
        self.assertNotIn("def render_library_workspace_page", catalog_report)
        self.assertIn("def render_catalog_index_page", workspace_report)
        self.assertIn("def render_library_workspace_page", workspace_report)
        self.assertIn("render_catalog_index_page", catalog_report)
        self.assertIn("render_library_workspace_page", catalog_report)

    def test_catalog_workspace_does_not_call_catalog_report_private_page_helpers(self) -> None:
        workspace_report = (ROOT / "src" / "lib_guard" / "render" / "catalog_workspace_report.py").read_text(encoding="utf-8")
        forbidden = [
            "cr._render_library_home",
            "cr._library_browser",
            "cr._catalog_filter_panel",
            "cr._catalog_browser_styles",
            "cr._command_examples",
            "cr._task_rows",
        ]
        hits = [token for token in forbidden if token in workspace_report]
        self.assertFalse(hits, "catalog_workspace_report still calls private catalog_report helpers:\n" + "\n".join(hits))

    def test_catalog_report_does_not_define_workspace_page_helpers(self) -> None:
        catalog_report = (ROOT / "src" / "lib_guard" / "render" / "catalog_report.py").read_text(encoding="utf-8")
        forbidden = [
            "def _render_library_home",
            "def _library_browser",
            "def _catalog_filter_panel",
            "def _task_rows",
            "def _command_examples",
            "def _catalog_browser_styles",
        ]
        hits = [token for token in forbidden if token in catalog_report]
        self.assertFalse(hits, "catalog_report still defines workspace page helpers:\n" + "\n".join(hits))


if __name__ == "__main__":
    unittest.main()
