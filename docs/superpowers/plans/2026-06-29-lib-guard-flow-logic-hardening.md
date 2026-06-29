# Lib Guard Flow Logic Hardening Implementation Plan

Status: current

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Version Detail update evidence, refresh defaults, pairwise recommendations, file type lanes, render/export boundaries, and documentation all follow the same current-effective-first review model.

**Architecture:** Keep `Version Detail` as the normal reviewer entry and treat `Comparison Review` as a manual/debug view. Centralize file type lane policy in `project_config.py`, consume compare artifacts through `version_update_detail_model`, and keep HTML rendering separate from Markdown export. Continue splitting catalog rendering by moving public Catalog Browser and Library Workspace ownership into `catalog_workspace_report.py` while `catalog_report.py` remains the facade and state adapter.

**Tech Stack:** Python 3.11 standard library, `unittest`, JSON artifacts, static HTML renderers, `scripts/lg.csh` short CLI wrappers.

---

## Scope Check

This plan covers one product surface: the library update review flow. It has four tightly coupled subsystems: short CLI semantics, diff/pairwise policy, Version Detail model/rendering, and catalog render ownership. They should be implemented in the order below because later tasks depend on the regression tests and constants established earlier.

## Execution Note

Task 7 originally allowed a new `catalog_render_common.py` helper module. During execution, the lower-risk path was chosen: keep catalog data helpers in `catalog_report.py`, move public Catalog Browser / Library Workspace page helper ownership into `catalog_workspace_report.py`, and enforce that boundary with a repository cleanup guard. No `catalog_render_common.py` module was created in this implementation round.

## File Structure

Create or modify these files:

- Create: `src/lib_guard/test/test_version_detail_report.py`
  - Dedicated tests for base selection, Version Detail model completeness, Markdown export separation, and page wording.
- Create: `src/lib_guard/test/test_pairwise_policy.py`
  - Dedicated tests for default pairwise task lane policy.
- Create: `src/lib_guard/test/test_short_cli_refresh.py`
  - Dedicated tests for `lg refresh` versus `lg cmp` semantics.
- Modify: `src/lib_guard/project_config.py`
  - Source of truth for `SUMMARY_ONLY_TYPES`, `BINARY_METADATA_ONLY_TYPES`, and `DEFAULT_FILE_DIFF_TYPES`.
- Modify: `src/lib_guard/render/version_detail_report.py`
  - Owns `_select_base`, `_select_diff_dir`, `build_version_update_detail_model`, `render_version_detail_page`, and explicit Markdown export.
- Modify: `src/lib_guard/diff/pairwise.py`
  - Uses default pairwise task types, not all manually supported fd types.
- Modify: `src/lib_guard/diff/scan_diff.py`
  - Uses the same lane constants as Version Detail and pairwise.
- Modify: `src/lib_guard/short_cli.py`
  - Makes `refresh` current/previous-effective first; keeps `cmp` as manual compare.
- Modify: `src/lib_guard/render/catalog_workspace_report.py`
  - Owns public Catalog Browser and Library Workspace page rendering.
- Modify: `src/lib_guard/render/catalog_report.py`
  - Remains the facade and state/task adapter; stops owning public workspace page rendering.
- Modify: `README.md`
  - Main user flow becomes `Catalog -> Version Review -> Release`.
- Modify: `docs/cli_reference.md`
  - Documents `refresh` and `cmp` separately.
- Modify: `docs/data_contract.md`
  - Documents `version_update_detail_model` and file type lanes.
- Modify: `docs/architecture.md`
  - Documents render ownership boundaries.

## Commit Policy

Commit after every task. Use these messages:

```bash
git commit -m "test: cover version detail update semantics"
git commit -m "fix: align version detail base and model"
git commit -m "test: cover pairwise file type lanes"
git commit -m "fix: align pairwise default lanes"
git commit -m "fix: align refresh update detail semantics"
git commit -m "refactor: split catalog workspace rendering ownership"
git commit -m "docs: document current version review flow"
git commit -m "test: add final workflow guardrails"
```

### Task 1: Version Detail Regression Tests

**Files:**
- Create: `src/lib_guard/test/test_version_detail_report.py`
- Modify: none
- Test: `src/lib_guard/test/test_version_detail_report.py`

- [ ] **Step 1: Write failing tests for base selection, model evidence, and Markdown separation**

Create `src/lib_guard/test/test_version_detail_report.py` with this complete content:

```python
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path


class VersionDetailReportTest(unittest.TestCase):
    def test_current_effective_wins_over_stale_diff_base(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            current_diff = root / "current_diff"
            stale_diff = root / "stale_diff"
            current_diff.mkdir()
            stale_diff.mkdir()
            (current_diff / "diff_summary.json").write_text(
                json.dumps({"status": "DIFF", "changed_files": 1, "view_changes": 1}, ensure_ascii=False),
                encoding="utf-8",
            )
            (current_diff / "view_diff.json").write_text(
                json.dumps({"summary": {"changed": 1}, "changed": [{"view": "lef"}]}, ensure_ascii=False),
                encoding="utf-8",
            )
            (current_diff / "type_diff.json").write_text(
                json.dumps({"summary": {"changed_types": 1}, "changed": [{"file_type": "lef"}]}, ensure_ascii=False),
                encoding="utf-8",
            )
            (current_diff / "release_readiness_diff.json").write_text(
                json.dumps({"status": "DIFF", "regressions": [{"check": "required_view_status"}]}, ensure_ascii=False),
                encoding="utf-8",
            )
            (current_diff / "release_evidence_diff.json").write_text(
                json.dumps({"status": "DIFF", "changed": [{"artifact": "release_readiness.json"}]}, ensure_ascii=False),
                encoding="utf-8",
            )
            (current_diff / "diff_issues.json").write_text(
                json.dumps({"issues": [{"category": "view_diff", "severity": "warning"}]}, ensure_ascii=False),
                encoding="utf-8",
            )
            (current_diff / "file_diff.json").write_text(
                json.dumps({"changed": [{"path": "lef/macro.lef", "file_type": "lef"}]}, ensure_ascii=False),
                encoding="utf-8",
            )
            (stale_diff / "diff_summary.json").write_text(
                json.dumps({"status": "SAME", "changed_files": 0}, ensure_ascii=False),
                encoding="utf-8",
            )

            from lib_guard.render.version_detail_report import build_version_update_detail_model

            model = build_version_update_detail_model(
                root / "html",
                {"library_id": "ip/ucie", "library_name": "ucie"},
                {
                    "version_id": "patch_20260628",
                    "current_effective_ref": "effective_current",
                    "diff": {
                        "base_version": "stale_adjacent_base",
                        "base_source": "adjacent",
                        "base_diff_dir": str(stale_diff),
                        "current_effective_diff_dir": str(current_diff),
                        "adjacent_old_version": "adjacent_only_fallback",
                    },
                },
            )

            self.assertEqual(model["base_ref"], "current_effective")
            self.assertEqual(model["base_version"], "effective_current")
            self.assertEqual(model["base_source"], "current_effective_ref")
            self.assertEqual(model["status"], "CHANGED")
            self.assertEqual(model["diff_summary"]["view_changes"], 1)
            self.assertEqual(model["view_diff"]["summary"]["changed"], 1)
            self.assertEqual(model["type_diff"]["summary"]["changed_types"], 1)
            self.assertEqual(model["release_readiness_diff"]["regressions"][0]["check"], "required_view_status")
            self.assertEqual(model["release_evidence_diff"]["changed"][0]["artifact"], "release_readiness.json")
            self.assertEqual(model["diff_issues"]["issues"][0]["category"], "view_diff")
            self.assertIn("view_diff", model["trace_links"])
            self.assertIn("type_diff", model["trace_links"])
            self.assertIn("release_readiness_diff", model["trace_links"])
            self.assertIn("release_evidence_diff", model["trace_links"])
            self.assertIn("diff_issues", model["trace_links"])

    def test_diff_base_only_high_priority_when_source_is_explicit_or_current_effective(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            diff_dir = root / "explicit_diff"
            diff_dir.mkdir()
            (diff_dir / "diff_summary.json").write_text(json.dumps({"status": "DIFF", "changed_files": 1}), encoding="utf-8")

            from lib_guard.render.version_detail_report import build_version_update_detail_model

            explicit_model = build_version_update_detail_model(
                root / "html",
                {"library_id": "ip/ucie", "library_name": "ucie"},
                {
                    "version_id": "patch_20260628",
                    "diff": {
                        "base_version": "manual_base",
                        "base_source": "explicit",
                        "base_diff_dir": str(diff_dir),
                    },
                },
            )
            current_model = build_version_update_detail_model(
                root / "html",
                {"library_id": "ip/ucie", "library_name": "ucie"},
                {
                    "version_id": "patch_20260629",
                    "diff": {
                        "base_version": "effective_base",
                        "base_source": "current_effective",
                        "current_effective_diff_dir": str(diff_dir),
                    },
                },
            )

            self.assertEqual(explicit_model["base_ref"], "explicit")
            self.assertEqual(explicit_model["base_version"], "manual_base")
            self.assertEqual(current_model["base_ref"], "current_effective")
            self.assertEqual(current_model["base_version"], "effective_base")

    def test_adjacent_is_fallback_and_missing_base_needs_confirmation(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)

            from lib_guard.render.version_detail_report import build_version_update_detail_model

            adjacent_model = build_version_update_detail_model(
                root / "html",
                {"library_id": "ip/ucie", "library_name": "ucie"},
                {
                    "version_id": "patch_20260628",
                    "diff": {"adjacent_old_version": "raw_previous"},
                },
            )
            missing_model = build_version_update_detail_model(
                root / "html",
                {"library_id": "ip/ucie", "library_name": "ucie"},
                {"version_id": "orphan_20260628"},
            )

            self.assertEqual(adjacent_model["base_ref"], "adjacent_fallback")
            self.assertEqual(adjacent_model["base_version"], "raw_previous")
            self.assertEqual(missing_model["status"], "NEEDS_BASE_CONFIRM")
            self.assertEqual(missing_model["base_ref"], "NEEDS_BASE_CONFIRM")

    def test_html_does_not_require_or_auto_export_current_lib_diff_markdown(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)

            from lib_guard.render.version_detail_report import (
                build_version_update_detail_model,
                export_current_lib_diff_markdown,
                render_version_detail_page,
                render_version_update_detail_panel,
            )

            lib = {"library_id": "ip/ucie", "library_name": "ucie"}
            version = {"version_id": "orphan_20260628"}
            model = build_version_update_detail_model(root / "html", lib, version)
            page = Path(render_version_detail_page(root / "html", lib, version))
            panel_before_md = render_version_update_detail_panel(model)
            md_path = page.parent / "current_lib_diff.md"
            export_current_lib_diff_markdown(model, md_path)
            md_text = md_path.read_text(encoding="utf-8")
            md_path.unlink()
            panel_after_delete = render_version_update_detail_panel(model)
            html = page.read_text(encoding="utf-8")

            self.assertFalse(md_path.exists())
            self.assertEqual(panel_before_md, panel_after_delete)
            self.assertIn("NEEDS_BASE_CONFIRM", html)
            self.assertIn("NEEDS_BASE_CONFIRM", md_text)
            self.assertNotIn("NO_DIFF_SUMMARY", html)
            self.assertNotIn("Comparison Review 是唯一 diff 入口", html)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the new tests to verify they fail on unfixed main**

Run:

```bash
PYTHONPATH=src python3 -m unittest src.lib_guard.test.test_version_detail_report -q
```

Expected before implementation: at least one failure mentioning `current_effective`, `release_evidence_diff`, missing `trace_links`, or unexpected `current_lib_diff.md`.

- [ ] **Step 3: Commit the failing tests**

```bash
git add src/lib_guard/test/test_version_detail_report.py
git commit -m "test: cover version detail update semantics"
```

### Task 2: Version Detail Base Selection and Model

**Files:**
- Modify: `src/lib_guard/render/version_detail_report.py`
- Test: `src/lib_guard/test/test_version_detail_report.py`

- [ ] **Step 1: Replace `_select_base` with current-effective-first precedence**

In `src/lib_guard/render/version_detail_report.py`, replace the entire `_select_base` function with:

```python
def _select_base(version: Mapping[str, Any]) -> tuple[str, str, str]:
    diff = _as_mapping(version.get("diff"))
    lineage = _as_mapping(version.get("lineage"))
    explicit = (
        version.get("explicit_base_version")
        or diff.get("explicit_base_version")
        or lineage.get("explicit_base_version")
    )
    if explicit:
        return "explicit", str(explicit), "explicit_base_version"

    for key in ["current_effective", "current_effective_ref", "latest_effective_ref"]:
        value = version.get(key) or diff.get(key) or lineage.get(key)
        if value and not isinstance(value, bool):
            return "current_effective", str(value), key

    previous = version.get("previous_effective_version") or version.get("parent_version") or lineage.get("parent_candidate")
    if previous:
        return "previous_effective", str(previous), "previous_effective_version"

    diff_base = diff.get("base_version")
    diff_base_source = str(diff.get("base_source") or diff.get("base_version_source") or "").lower()
    diff_kind = str(diff.get("kind") or diff.get("diff_kind") or "").lower()
    if diff_base and diff_base_source == "explicit":
        return "explicit", str(diff_base), "diff.base_version:explicit"
    if diff_base and (diff_base_source == "current_effective" or diff_kind == "current_library_diff"):
        return "current_effective", str(diff_base), f"diff.base_version:{diff_base_source or diff_kind}"

    cr = _cr()
    full_base = cr._base_full_version(version)
    if full_base:
        return "base_full", str(full_base), "base_full_version"

    adjacent = diff.get("adjacent_old_version")
    if adjacent:
        return "adjacent_fallback", str(adjacent), "adjacent_old_version"

    if diff_base:
        return "recorded_base", str(diff_base), f"diff.base_version:{diff_base_source or 'fallback'}"

    return "NEEDS_BASE_CONFIRM", "", "missing_base"
```

- [ ] **Step 2: Ensure the model reads every compare artifact**

Inside `build_version_update_detail_model`, keep or add these reads immediately after `summary` and `file_diff`:

```python
    view_diff = dict(cr._version_diff_json(diff_dir, "view_diff.json"))
    type_diff = dict(cr._version_diff_json(diff_dir, "type_diff.json"))
    release_readiness_diff = dict(cr._version_diff_json(diff_dir, "release_readiness_diff.json"))
    release_evidence_diff = dict(cr._version_diff_json(diff_dir, "release_evidence_diff.json"))
    diff_issues = dict(cr._version_diff_json(diff_dir, "diff_issues.json"))
```

- [ ] **Step 3: Add structured fields and trace links to the model return value**

In the returned dictionary from `build_version_update_detail_model`, include these keys:

```python
        "diff_summary": summary,
        "view_diff": view_diff,
        "type_diff": type_diff,
        "release_readiness_diff": release_readiness_diff,
        "release_evidence_diff": release_evidence_diff,
        "diff_issues": diff_issues,
        "file_diff": file_diff,
        "trace_links": {
            "diff_summary": str(diff_dir / "diff_summary.json") if diff_dir else "",
            "file_diff": str(diff_dir / "file_diff.json") if diff_dir else "",
            "view_diff": str(diff_dir / "view_diff.json") if diff_dir else "",
            "type_diff": str(diff_dir / "type_diff.json") if diff_dir else "",
            "release_readiness_diff": str(diff_dir / "release_readiness_diff.json") if diff_dir else "",
            "release_evidence_diff": str(diff_dir / "release_evidence_diff.json") if diff_dir else "",
            "diff_issues": str(diff_dir / "diff_issues.json") if diff_dir else "",
            "markdown_export": str(md_path),
        },
```

Keep the existing `summary_metrics`, `file_changes`, `release_notes`, `recommended_actions`, `file_diff_recommendations`, and `metadata_only_changes` keys.

- [ ] **Step 4: Run Version Detail tests**

Run:

```bash
PYTHONPATH=src python3 -m unittest src.lib_guard.test.test_version_detail_report -q
```

Expected: `OK`.

- [ ] **Step 5: Commit implementation**

```bash
git add src/lib_guard/render/version_detail_report.py src/lib_guard/test/test_version_detail_report.py
git commit -m "fix: align version detail base and model"
```

### Task 3: Pairwise Lane Regression Tests

**Files:**
- Create: `src/lib_guard/test/test_pairwise_policy.py`
- Modify: none
- Test: `src/lib_guard/test/test_pairwise_policy.py`

- [ ] **Step 1: Write failing pairwise policy tests**

Create `src/lib_guard/test/test_pairwise_policy.py` with this complete content:

```python
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path


class PairwisePolicyTest(unittest.TestCase):
    def _tasks_for_types(self, changed_types: list[str]) -> dict[str, object]:
        with tempfile.TemporaryDirectory() as td:
            old_scan = Path(td) / "old_scan"
            new_scan = Path(td) / "new_scan"
            old_scan.mkdir()
            new_scan.mkdir()
            (old_scan / "scan_meta.json").write_text(json.dumps({"library_name": "demo", "version": "base"}), encoding="utf-8")
            (new_scan / "scan_meta.json").write_text(json.dumps({"library_name": "demo", "version": "new"}), encoding="utf-8")
            file_diff = {"changed": [], "_old_items": {}, "_new_items": {}}
            for file_type in changed_types:
                rel = f"{file_type}/block.{file_type}"
                file_diff["changed"].append(rel)
                file_diff["_old_items"][rel] = {"path": rel, "file_type": file_type, "root_path": str(old_scan)}
                file_diff["_new_items"][rel] = {"path": rel, "file_type": file_type, "root_path": str(new_scan)}

            from lib_guard.diff.pairwise import build_pairwise_diff_tasks

            return build_pairwise_diff_tasks(old_scan, new_scan, file_diff, output_root=Path(td) / "pairwise")

    def test_default_pairwise_tasks_exclude_summary_and_binary_types(self) -> None:
        tasks = self._tasks_for_types(["lef", "cdl", "sdc", "verilog", "systemverilog", "liberty", "lib", "spef", "db", "gds", "oas", "layout", "milkyway", "ndm"])
        task_types = {item["file_type"] for item in tasks["tasks"]}
        commands = "\n".join(item["command"] for item in tasks["tasks"])

        self.assertEqual(task_types, {"lef", "cdl", "sdc"})
        for file_type in ["verilog", "systemverilog", "liberty", "lib", "spef", "db", "gds", "oas", "layout", "milkyway", "ndm"]:
            self.assertNotIn(f"--type {file_type}", commands)

    def test_lane_constants_are_shared_by_pairwise_scan_diff_and_version_detail(self) -> None:
        from lib_guard.diff.pairwise import DEFAULT_PAIRWISE_FILE_DIFF_TYPES
        from lib_guard.project_config import BINARY_METADATA_ONLY_TYPES, DEFAULT_FILE_DIFF_TYPES, SUMMARY_ONLY_TYPES
        from lib_guard.render.version_detail_report import BINARY_METADATA_ONLY_TYPES as DETAIL_BINARY_TYPES
        from lib_guard.render.version_detail_report import SUMMARY_ONLY_TYPES as DETAIL_SUMMARY_TYPES

        self.assertEqual(DEFAULT_PAIRWISE_FILE_DIFF_TYPES, DEFAULT_FILE_DIFF_TYPES)
        self.assertIn("verilog", SUMMARY_ONLY_TYPES)
        self.assertIn("liberty", SUMMARY_ONLY_TYPES)
        self.assertIn("spef", SUMMARY_ONLY_TYPES)
        self.assertIn("db", BINARY_METADATA_ONLY_TYPES)
        self.assertIn("gds", BINARY_METADATA_ONLY_TYPES)
        self.assertEqual(DETAIL_SUMMARY_TYPES, SUMMARY_ONLY_TYPES)
        self.assertEqual(DETAIL_BINARY_TYPES, BINARY_METADATA_ONLY_TYPES)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the new tests to verify they fail on unfixed main**

Run:

```bash
PYTHONPATH=src python3 -m unittest src.lib_guard.test.test_pairwise_policy -q
```

Expected before implementation: failure showing summary-only or binary types generated default pairwise tasks.

- [ ] **Step 3: Commit the failing tests**

```bash
git add src/lib_guard/test/test_pairwise_policy.py
git commit -m "test: cover pairwise file type lanes"
```

### Task 4: Pairwise Default Lane Implementation

**Files:**
- Modify: `src/lib_guard/project_config.py`
- Modify: `src/lib_guard/diff/pairwise.py`
- Modify: `src/lib_guard/diff/scan_diff.py`
- Modify: `src/lib_guard/render/version_detail_report.py`
- Test: `src/lib_guard/test/test_pairwise_policy.py`

- [ ] **Step 1: Centralize lane constants**

In `src/lib_guard/project_config.py`, ensure these exact constants exist:

```python
SUMMARY_ONLY_TYPES = {"verilog", "systemverilog", "liberty", "lib", "spef"}
BINARY_METADATA_ONLY_TYPES = {"db", "gds", "oas", "layout", "milkyway", "ndm"}
DEFAULT_FILE_DIFF_TYPES = {
    "lef",
    "cdl",
    "spice",
    "sp",
    "sdc",
    "upf",
    "cpf",
    "waiver",
    "ibis",
    "pwl",
    "snp",
    "touchstone",
    "cpm",
}
```

- [ ] **Step 2: Make pairwise default tasks use only default file diff types**

In `src/lib_guard/diff/pairwise.py`, import `DEFAULT_FILE_DIFF_TYPES` and define:

```python
from lib_guard.project_config import DEFAULT_FILE_DIFF_TYPES


DEFAULT_PAIRWISE_FILE_DIFF_TYPES = set(DEFAULT_FILE_DIFF_TYPES)
```

In `build_pairwise_diff_tasks`, keep both task-generation loops gated on `DEFAULT_PAIRWISE_FILE_DIFF_TYPES`:

```python
        if old_type != new_type or old_type not in DEFAULT_PAIRWISE_FILE_DIFF_TYPES:
            continue
```

and:

```python
    for file_type in sorted(DEFAULT_PAIRWISE_FILE_DIFF_TYPES):
```

Leave `SUPPORTED_PAIRWISE_TYPES` only for manual low-level fd capability if existing callers still need it. Do not use it for default recommendation generation.

- [ ] **Step 3: Make scan diff and Version Detail import the same constants**

In `src/lib_guard/diff/scan_diff.py`, use:

```python
from lib_guard.project_config import BINARY_METADATA_ONLY_TYPES, DEFAULT_FILE_DIFF_TYPES, SUMMARY_ONLY_TYPES
```

Set the review mode using the shared constants:

```python
            "review_mode": (
                "metadata_only"
                if file_type in BINARY_METADATA_ONLY_TYPES
                else "summary_only"
                if file_type in SUMMARY_ONLY_TYPES
                else "manual_pairwise"
                if file_type in DEFAULT_FILE_DIFF_TYPES
                else "governance"
            ),
```

In `src/lib_guard/render/version_detail_report.py`, use:

```python
from lib_guard.project_config import BINARY_METADATA_ONLY_TYPES, DEFAULT_FILE_DIFF_TYPES, SUMMARY_ONLY_TYPES
```

- [ ] **Step 4: Run pairwise policy tests**

Run:

```bash
PYTHONPATH=src python3 -m unittest src.lib_guard.test.test_pairwise_policy -q
```

Expected: `OK`.

- [ ] **Step 5: Run scan pipeline tests that cover pairwise artifacts**

Run:

```bash
PYTHONPATH=src python3 -m unittest src.lib_guard.test.test_scan_pipeline.ScanPipelineTest.test_pairwise_default_lane_excludes_summary_and_binary_metadata_types -q
```

Expected: `OK`.

- [ ] **Step 6: Commit implementation**

```bash
git add src/lib_guard/project_config.py src/lib_guard/diff/pairwise.py src/lib_guard/diff/scan_diff.py src/lib_guard/render/version_detail_report.py src/lib_guard/test/test_pairwise_policy.py
git commit -m "fix: align pairwise default lanes"
```

### Task 5: Short CLI Refresh Semantics

**Files:**
- Create: `src/lib_guard/test/test_short_cli_refresh.py`
- Modify: `src/lib_guard/short_cli.py`
- Test: `src/lib_guard/test/test_short_cli_refresh.py`

- [ ] **Step 1: Write short CLI refresh tests**

Create `src/lib_guard/test/test_short_cli_refresh.py` with this complete content:

```python
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path


class ShortCliRefreshTest(unittest.TestCase):
    def _workspace(self) -> Path:
        root = Path(tempfile.mkdtemp())
        catalog = root / "catalog" / "catalog.json"
        catalog.parent.mkdir(parents=True)
        catalog.write_text(
            json.dumps(
                {
                    "libraries": [
                        {
                            "library_name": "ucie",
                            "summary": {"current_effective": "effective_20260620"},
                            "versions": [
                                {
                                    "version_id": "patch_20260628",
                                    "current_effective_ref": "effective_20260620",
                                    "diff": {"adjacent_old_version": "raw_adjacent_wrong"},
                                }
                            ],
                        }
                    ]
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        (root / "lib_guard.yml").write_text(
            "\n".join(
                [
                    f"workspace: {root}",
                    "raw_root: raw",
                    f"catalog: {catalog}",
                    f"catalog_html: {root / 'catalog' / 'html'}",
                    "reports: reports",
                    "diff: diff",
                    "file_diff: file_diff",
                    "release_root: release_area",
                    "library_type: ip",
                    "mode: candidate",
                    "parse_jobs: '8'",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        return root

    def test_refresh_defaults_to_effective_base_not_adjacent_mode(self) -> None:
        workspace = self._workspace()

        from lib_guard.short_cli import build_cli_commands

        commands = build_cli_commands(["refresh", "ucie"], cwd=workspace)
        self.assertEqual(len(commands), 1)
        command = commands[0]
        self.assertEqual(command[0], "compare")
        self.assertIn("--base", command)
        self.assertIn("effective_20260620", command)
        self.assertNotIn("raw_adjacent_wrong", command)
        self.assertNotIn("--mode", command)

    def test_refresh_adjacent_requires_explicit_mode(self) -> None:
        workspace = self._workspace()

        from lib_guard.short_cli import build_cli_commands

        commands = build_cli_commands(["refresh", "ucie", "--mode", "adjacent"], cwd=workspace)
        command = commands[0]
        self.assertIn("--mode", command)
        self.assertIn("adjacent", command)
        self.assertNotIn("--base", command)

    def test_cmp_keeps_manual_adjacent_default(self) -> None:
        workspace = self._workspace()

        from lib_guard.short_cli import build_cli_commands

        commands = build_cli_commands(["cmp", "ucie", "patch_20260628"], cwd=workspace)
        command = commands[0]
        self.assertEqual(command[0], "compare")
        self.assertIn("--mode", command)
        self.assertIn("adjacent", command)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the new tests to verify they fail on unfixed main**

Run:

```bash
PYTHONPATH=src python3 -m unittest src.lib_guard.test.test_short_cli_refresh -q
```

Expected before implementation: failure where `refresh` uses `--mode adjacent` or does not choose `effective_20260620`.

- [ ] **Step 3: Implement current/previous-effective refresh base resolution**

In `src/lib_guard/short_cli.py`, ensure `_refresh_base_version` is:

```python
def _refresh_base_version(library: dict[str, Any], version: dict[str, Any], mode: str) -> str | None:
    target = str(version.get("version_id") or "")
    lineage = version.get("lineage", {}) or {}
    diff = version.get("diff", {}) or {}
    if mode == "adjacent":
        return _version_ref(diff.get("adjacent_old_version"), target)
    if mode == "cumulative":
        return _version_ref(diff.get("cumulative_base_version") or version.get("base_full_version") or version.get("base_version") or lineage.get("base_candidate"), target)
    if mode == "current_effective":
        return (
            _version_ref(version.get("current_effective_ref"), target)
            or _version_ref(version.get("latest_effective_ref"), target)
            or _library_summary_ref(library, target, ["current_effective", "current_effective_ref", "latest_effective_ref", "current_version"])
            or _version_ref(version.get("previous_effective_version") or version.get("parent_version") or lineage.get("parent_candidate"), target)
        )
    return (
        _version_ref(version.get("previous_effective_version") or version.get("parent_version") or lineage.get("parent_candidate"), target)
        or _version_ref(version.get("current_effective_ref"), target)
        or _version_ref(version.get("latest_effective_ref"), target)
        or _library_summary_ref(library, target, ["current_effective", "current_effective_ref", "latest_effective_ref", "current_version"])
    )
```

In `_refresh_commands`, set the default:

```python
        mode = getattr(args, "mode", "previous_effective")
```

and call `_refresh_compare_command` like this:

```python
                mode=mode if mode in {"adjacent", "cumulative"} else None,
                base=base,
```

- [ ] **Step 4: Update the refresh parser help**

In `src/lib_guard/short_cli.py`, make the refresh parser:

```python
    p = sub.add_parser("refresh", help="刷新 latest/current raw version 的更新详情 diff")
    p.add_argument("library", nargs="?")
    p.add_argument("--all", action="store_true", help="Refresh latest/current raw version diff for every catalog library")
    p.add_argument("--mode", default="previous_effective", choices=["previous_effective", "current_effective", "adjacent", "cumulative"], help="更新详情默认使用 previous/current effective；adjacent 仅用于显式手动 compare")
    p.add_argument("--rescan", action="store_true", help="Force rescan before compare instead of scanning only missing evidence")
    p.add_argument("--refresh-catalog", action="store_true", help="Refresh catalog before resolving latest/current versions")
    p.add_argument("--with-evidence", action="store_true", help="When --refresh-catalog is used, collect file-type evidence during catalog refresh")
```

- [ ] **Step 5: Run short CLI tests**

Run:

```bash
PYTHONPATH=src python3 -m unittest src.lib_guard.test.test_short_cli_refresh -q
```

Expected: `OK`.

- [ ] **Step 6: Commit implementation**

```bash
git add src/lib_guard/short_cli.py src/lib_guard/test/test_short_cli_refresh.py
git commit -m "fix: align refresh update detail semantics"
```

### Task 6: Render and Export Boundary

**Files:**
- Modify: `src/lib_guard/render/version_detail_report.py`
- Test: `src/lib_guard/test/test_version_detail_report.py`

- [ ] **Step 1: Make Markdown export explicit**

In `src/lib_guard/render/version_detail_report.py`, ensure `render_version_detail_page` has this signature and export block:

```python
def render_version_detail_page(out: str | Path, lib: Mapping[str, Any], version: Mapping[str, Any], *, export_markdown: bool = False) -> str:
    cr = _cr()
    out_path = Path(out)
    safe_lib = cr._safe(_library_id(lib))
    safe_ver = cr._safe(_version_id(version))
    page = out_path / "libraries" / safe_lib / "versions" / safe_ver / "index.html"
    page.parent.mkdir(parents=True, exist_ok=True)
    model = build_version_update_detail_model(out_path, lib, version)
    md_path = page.parent / "current_lib_diff.md"
    model["markdown_export_path"] = str(md_path)
    if export_markdown:
        export_current_lib_diff_markdown(model, md_path)
```

Keep the rest of the function body rendering HTML from `model`.

- [ ] **Step 2: Keep trace text honest when Markdown is absent**

In the trace link list for Version Detail, use the existing path only if the file exists:

```python
                    ("current_lib_diff.md", cr._href(md_path) if md_path.exists() else "", "显式导出时由 version_update_detail_model 生成"),
```

- [ ] **Step 3: Run Version Detail tests**

Run:

```bash
PYTHONPATH=src python3 -m unittest src.lib_guard.test.test_version_detail_report -q
```

Expected: `OK`.

- [ ] **Step 4: Commit render/export split**

```bash
git add src/lib_guard/render/version_detail_report.py src/lib_guard/test/test_version_detail_report.py
git commit -m "fix: split version detail render and export"
```

### Task 7: Catalog Workspace Render Ownership

**Files:**
- Modify: `src/lib_guard/render/catalog_workspace_report.py`
- Modify: `src/lib_guard/test/test_repository_cleanup.py`
- Test: `src/lib_guard/test/test_repository_cleanup.py`

- [ ] **Step 1: Add a guard test for private reverse-calls**

In `src/lib_guard/test/test_repository_cleanup.py`, add this test method to `RepositoryCleanupTest`:

```python
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
```

- [ ] **Step 2: Run the guard test to verify it fails before the split**

Run:

```bash
PYTHONPATH=src python3 -m unittest src.lib_guard.test.test_repository_cleanup.RepositoryCleanupTest.test_catalog_workspace_does_not_call_catalog_report_private_page_helpers -q
```

Expected before implementation: failure listing private helper calls.

- [ ] **Step 3: Move page helper ownership into catalog_workspace_report**

Move the bodies of these helpers from `src/lib_guard/render/catalog_report.py` into `src/lib_guard/render/catalog_workspace_report.py`:

```python
_catalog_browser_styles
_catalog_filter_panel
_library_browser
_render_library_home
_task_rows
_command_examples
```

If a moved helper still needs a pure state helper from `catalog_report.py`, keep that data helper in `catalog_report.py` and call it through `_cr()`. Do not call the six page helpers listed in Step 1 from `catalog_workspace_report.py`.

- [ ] **Step 4: Update catalog_workspace_report to call local page helpers**

In `render_catalog_index_page`, replace:

```python
        cr._catalog_browser_styles()
```

with:

```python
        _catalog_browser_styles()
```

Replace:

```python
cr._catalog_filter_panel(state)
cr._library_browser(out_path, state, effective_by_lib)
cr._task_rows(tasks)
cr._command_examples()
```

with:

```python
_catalog_filter_panel(state)
_library_browser(out_path, state, effective_by_lib)
_task_rows(tasks)
_command_examples()
```

In `render_library_workspace_page`, replace:

```python
return cr._render_library_home(Path(out), lib, effective_items, compare_items)
```

with:

```python
return _render_library_home(Path(out), lib, effective_items, compare_items)
```

- [ ] **Step 5: Run repository cleanup tests**

Run:

```bash
PYTHONPATH=src python3 -m unittest src.lib_guard.test.test_repository_cleanup -q
```

Expected: `OK`.

- [ ] **Step 6: Run catalog timeline tests**

Run:

```bash
PYTHONPATH=src python3 -m unittest src.lib_guard.test.test_catalog_timeline -q
```

Expected: `OK`.

- [ ] **Step 7: Commit render ownership split**

```bash
git add src/lib_guard/render/catalog_workspace_report.py src/lib_guard/test/test_repository_cleanup.py
git commit -m "refactor: split catalog workspace rendering ownership"
```

### Task 8: Documentation and Command Surface Cleanup

**Files:**
- Modify: `README.md`
- Modify: `docs/cli_reference.md`
- Modify: `docs/data_contract.md`
- Modify: `docs/architecture.md`
- Modify: `docs/command_surface.md`
- Test: `src/lib_guard/test/test_repository_cleanup.py`

- [ ] **Step 1: Update README main workflow**

In `README.md`, make the workflow block exactly:

````markdown
## 当前主流程

```text
Catalog -> Version Review -> Release
```
````

Include these bullets under it:

```markdown
- Version Review 是普通 reviewer 的主页面，包含 release notes、scan evidence、parser summary、count/corner summary、readiness，以及相对当前有效库的更新证据。
- Library Workspace 是高级账本，用来查看单库 timeline、effective 组合和历史报告。
- Comparison Review 是手动 compare / debug 入口，不是普通用户查看更新详情的唯一入口。
- File Diff 只用于推荐下钻的关键文件，不是全量完成度 scoreboard。
```

- [ ] **Step 2: Update CLI reference for refresh/cmp/fd**

In `docs/cli_reference.md`, include this section:

````markdown
## `refresh` 和 `cmp` 的边界

`refresh` 是版本详情页更新证据的日常入口。默认行为是：

- 优先使用 `current_effective`。
- 没有当前有效库时使用 `previous_effective`。
- 找不到可信 base 时让状态进入 `NEEDS_BASE_CONFIRM`，不伪装成真实 diff。

`adjacent` 只用于手动 compare 场景，必须显式指定：

```csh
lg.csh refresh ucie --mode adjacent
lg.csh cmp ucie stable_20250608 --mode adjacent --scan-if-missing
```

`cmp` 是手动比较工具，适合指定 `--base`、调试 adjacent/cumulative，或生成独立 Comparison Review。
````

- [ ] **Step 3: Update data contract for update detail model and lanes**

In `docs/data_contract.md`, include these exact tokens in the Version update section:

```markdown
`version_update_detail_model`
`diff_summary`
`view_diff`
`type_diff`
`release_readiness_diff`
`release_evidence_diff`
`diff_issues`
`file_diff`
`release_notes`
`SUMMARY_ONLY_TYPES`
`BINARY_METADATA_ONLY_TYPES`
`DEFAULT_FILE_DIFF_TYPES`
```

- [ ] **Step 4: Update architecture ownership**

In `docs/architecture.md`, include this ownership table:

```markdown
| Page / boundary | Owner |
| --- | --- |
| Catalog render orchestration | `src/lib_guard/render/catalog_report.py::render_catalog_html` |
| Catalog Browser and Library Workspace pages | `src/lib_guard/render/catalog_workspace_report.py` |
| Version Detail and update detail model | `src/lib_guard/render/version_detail_report.py` |
| Shared visual components | `src/lib_guard/render/product_theme.py` |
```

- [ ] **Step 5: Add repository cleanup doc guard**

In `src/lib_guard/test/test_repository_cleanup.py`, add this method:

```python
    def test_docs_define_version_review_as_normal_path(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        cli_ref = (ROOT / "docs" / "cli_reference.md").read_text(encoding="utf-8")
        contract = (ROOT / "docs" / "data_contract.md").read_text(encoding="utf-8")
        self.assertIn("Catalog -> Version Review -> Release", readme)
        self.assertNotIn("Catalog -> Library Workspace -> Version Review -> Comparison Review -> File Diff -> Release", readme)
        self.assertIn("`refresh` 是版本详情页更新证据的日常入口", cli_ref)
        self.assertIn("`cmp` 是手动比较工具", cli_ref)
        self.assertIn("version_update_detail_model", contract)
        self.assertIn("DEFAULT_FILE_DIFF_TYPES", contract)
        self.assertIn("SUMMARY_ONLY_TYPES", contract)
        self.assertIn("BINARY_METADATA_ONLY_TYPES", contract)
```

- [ ] **Step 6: Run documentation guard tests**

Run:

```bash
PYTHONPATH=src python3 -m unittest src.lib_guard.test.test_repository_cleanup -q
```

Expected: `OK`.

- [ ] **Step 7: Commit documentation cleanup**

```bash
git add README.md docs/cli_reference.md docs/data_contract.md docs/architecture.md docs/command_surface.md src/lib_guard/test/test_repository_cleanup.py
git commit -m "docs: document current version review flow"
```

### Task 9: Final Validation and PR Update

**Files:**
- Modify: none unless tests expose failures.
- Test: all test files touched by this plan.

- [ ] **Step 1: Compile all source**

Run:

```bash
PYTHONPATH=src python3 -m compileall -q src
```

Expected: exit code `0` and no Python syntax output.

- [ ] **Step 2: Run focused test suites**

Run:

```bash
PYTHONPATH=src python3 -m unittest src.lib_guard.test.test_version_detail_report -q
PYTHONPATH=src python3 -m unittest src.lib_guard.test.test_pairwise_policy -q
PYTHONPATH=src python3 -m unittest src.lib_guard.test.test_short_cli_refresh -q
PYTHONPATH=src python3 -m unittest src.lib_guard.test.test_repository_cleanup -q
PYTHONPATH=src python3 -m unittest src.lib_guard.test.test_catalog_timeline -q
PYTHONPATH=src python3 -m unittest src.lib_guard.test.test_scan_pipeline -q
```

Expected: every command exits `0` and prints `OK`.

- [ ] **Step 3: Run full unittest discovery**

Run:

```bash
PYTHONPATH=src python3 -m unittest discover -s src/lib_guard/test -p "test*.py" -q
```

Expected: exit code `0` and `OK`.

- [ ] **Step 4: Inspect git status**

Run:

```bash
git status -sb
```

Expected: only intentional tracked changes are present before the final commit. Untracked local files such as editor swap files must not be staged.

- [ ] **Step 5: Commit final guardrail changes if any remain**

If Task 9 exposed a small missing guardrail, commit it with:

```bash
git add <exact changed files>
git commit -m "test: add final workflow guardrails"
```

Use the exact changed file list from `git status -sb`; do not use `git add .`.

- [ ] **Step 6: Push the branch**

Run:

```bash
git push
```

Expected: push updates the current branch on GitHub.

- [ ] **Step 7: Update PR body**

Run:

```bash
gh api -X PATCH repos/Godshaohao/ai_lib/issues/2 -f body=$'## Summary\n- Aligned Version Detail base selection with explicit/current-effective/previous-effective precedence.\n- Split refresh update detail semantics from manual cmp adjacent compare.\n- Centralized file type lanes and stopped default pairwise fd tasks for summary-only and binary metadata-only views.\n- Expanded version_update_detail_model to include diff_summary, view_diff, type_diff, release_readiness_diff, release_evidence_diff, diff_issues, file_diff, and release_notes.\n- Kept HTML rendering independent from current_lib_diff.md export.\n- Continued catalog render ownership split so catalog_report remains a facade and catalog_workspace_report owns public workspace pages.\n- Updated Chinese docs for the normal Catalog -> Version Review -> Release path.\n\n## Validation\n- PYTHONPATH=src python3 -m compileall -q src\n- PYTHONPATH=src python3 -m unittest src.lib_guard.test.test_version_detail_report -q\n- PYTHONPATH=src python3 -m unittest src.lib_guard.test.test_pairwise_policy -q\n- PYTHONPATH=src python3 -m unittest src.lib_guard.test.test_short_cli_refresh -q\n- PYTHONPATH=src python3 -m unittest src.lib_guard.test.test_repository_cleanup -q\n- PYTHONPATH=src python3 -m unittest src.lib_guard.test.test_catalog_timeline -q\n- PYTHONPATH=src python3 -m unittest src.lib_guard.test.test_scan_pipeline -q\n- PYTHONPATH=src python3 -m unittest discover -s src/lib_guard/test -p "test*.py" -q'
```

Expected: GitHub API returns issue JSON containing `"number":2`.

## Self-Review

**Spec coverage:**  
P0-1 refresh semantics are covered by Task 5. P0-2 base precedence is covered by Tasks 1 and 2. P0-3 pairwise/file type lanes are covered by Tasks 3 and 4. P0-4 model completeness is covered by Tasks 1 and 2. P0-5 render/export split is covered by Task 6. P1 catalog workspace ownership is covered by Task 7. README/CLI/data contract/architecture documentation is covered by Task 8. Full validation and PR update are covered by Task 9.

**Placeholder scan:**  
The red-flag phrase scan from the skill was run against this plan. Every code-changing task includes concrete code blocks or exact replacement snippets.

**Type consistency:**  
The plan consistently uses `version_update_detail_model`, `SUMMARY_ONLY_TYPES`, `BINARY_METADATA_ONLY_TYPES`, `DEFAULT_FILE_DIFF_TYPES`, `DEFAULT_PAIRWISE_FILE_DIFF_TYPES`, `build_version_update_detail_model`, `render_version_detail_page`, and `export_current_lib_diff_markdown`.
