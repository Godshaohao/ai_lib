Status: archived
Archive reason: moved out of current lib_guard documentation.

# Catalog Control Plane Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `catalog.json` the single operational entry for scan, diff, console, and release dry-run workflows.

**Architecture:** Keep manual catalog corrections separate from generated runtime state. Catalog discovery keeps the current two-level fallback, but adds policy-driven path rules and lightweight inventory evidence so real raw trees can be identified by structure plus file contents. CLI commands remain thin wrappers around existing scan, diff, render, and release modules.

**Tech Stack:** Python stdlib, `argparse`, existing `lib_guard.scan`, `lib_guard.diff`, `lib_guard.render`, and `lib_guard.release` modules.

---

### Task 1: Split Catalog Runtime State

**Files:**
- Modify: `src/lib_guard/catalog/index.py`
- Test: `src/lib_guard/test/test_v5_catalog.py`

- [ ] Write failing tests that assert `update_catalog_scan_status()` and `update_catalog_diff_status()` write to `runtime_state`, not `manual_overrides`.
- [ ] Preserve old catalog compatibility by reading legacy runtime fields from `manual_overrides` when present.
- [ ] Rebuild derived library/version objects by overlaying `manual_overrides` first, then `runtime_state`.
- [ ] Verify with `python -m unittest src.lib_guard.test.test_v5_catalog.V5CatalogTest`.

### Task 2: Catalog HTML as Navigation Hub

**Files:**
- Modify: `src/lib_guard/catalog/index.py`
- Test: `src/lib_guard/test/test_v5_catalog.py`

- [ ] Add tests that rendered catalog HTML includes clickable scan, console, diff, and release links when runtime paths exist.
- [ ] Store `scan_html`, `console_html`, and per-mode `diff_html` in runtime state.
- [ ] Render version rows with direct action links instead of opaque status-only cells.
- [ ] Verify generated demo catalog links to scan/console/diff pages.

### Task 3: Batch Commands

**Files:**
- Modify: `src/lib_guard/cli.py`
- Test: `src/lib_guard/test/test_v5_catalog.py`

- [ ] Add tests for `run-batch --only-missing --limit` selecting unscanned versions.
- [ ] Add tests for `compare-batch --only-ready --limit` selecting scanned versions with ready parent scan.
- [ ] Implement batch commands by repeatedly calling existing catalog workflow functions with copied namespace values.
- [ ] Ensure batch commands write compact JSON summaries with successes and failures.

### Task 4: Policy-Driven Discovery Evidence

**Files:**
- Modify: `configs/catalog_policy.json`
- Modify: `src/lib_guard/catalog/index.py`
- Test: `src/lib_guard/test/test_v5_catalog.py`

- [ ] Add tests for policy `version_path_rules` extracting library/version from deeper paths.
- [ ] Add lightweight inventory evidence: file type counts, marker files, confidence score.
- [ ] Keep existing two-level discovery as fallback.
- [ ] Write discovered evidence into each version `detected` block.

### Task 5: Catalog Release Bridge

**Files:**
- Modify: `src/lib_guard/catalog/index.py`
- Modify: `src/lib_guard/cli.py`
- Test: `src/lib_guard/test/test_v5_catalog.py`

- [ ] Add tests for `catalog release-check` resolving `scan_dir` and optional adjacent diff gate from catalog.
- [ ] Add tests for `catalog release-link` defaulting to dry-run and writing release runtime state.
- [ ] Implement release status update helpers in catalog module.
- [ ] Keep existing `release check/link` commands unchanged.

### Task 6: Usage Documentation

**Files:**
- Modify: `docs/lib_guard_v5_catalog_workflow.md`

- [ ] Replace mojibake content with Chinese usage instructions.
- [ ] Document the new shortest workflows: discover, batch scan, batch compare, open catalog HTML, release dry-run.
- [ ] Include troubleshooting for misclassification, missing scan links, blocked release, and large catalogs.
