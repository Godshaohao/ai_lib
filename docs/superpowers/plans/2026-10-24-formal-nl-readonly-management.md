# Formal NL Read-Only Management Implementation Plan

> **For agentic workers:** Execute this plan inline with test-first checkpoints; preserve unrelated working-tree changes.

**Goal:** Add a read-only Formal NL workspace to the standalone `src_qor` workbench by reusing `effective_file_tracker.run()`.

**Architecture:** The Flask workbench accepts an IP and formal-root path, stores only that path in the existing YAML registry, runs the existing tracker into an immutable per-IP report directory, and renders a compact stage/view summary with expandable file evidence. No formal directory writes, link mutations, new persistence service, or second inventory algorithm.

**Tech Stack:** Python 3, Flask, PyYAML, Jinja, existing JavaScript tab controller, unittest.

## Global Constraints

- Formal NL management is read-only; never create, replace, or delete formal links.
- Keep Formal NL inventory separate from RAW registration and technical release judgments.
- A visible path or filename-derived Corner label is not a completeness or release conclusion.
- Failed scans must not replace the latest successful report.
- Preserve all unrelated existing worktree changes.

---

### Task 1: Formal NL route and report persistence

**Files:**
- Modify: `src_qor/lib_guard/workbench.py`
- Test: `src_qor/test/test_workbench.py`

**Interfaces:**
- `POST /formal-nl` accepts registered `id` and `formal_nl_root`; returns the Formal NL tab with latest report or clear error.
- `GET /formal-report/<kind>?id=<ip-id>` serves only the selected IP's latest `json` or `md` report under workbench output.
- IP YAML stores `formal_nl_root`; run reports are stored under `output/formal_nl/<safe-library-id>/runs/<run-id>/` and latest pointer under the same IP directory.

- [ ] Add failing tests for persisted path, multi-stage report generation, output report links, and invalid path preserving latest success.
- [ ] Run only those tests and confirm the expected failure is the missing route/behavior.
- [ ] Implement the minimal route using `effective_file_tracker.run()` and atomic latest-pointer update only after report files exist.
- [ ] Re-run focused tests; confirm Formal input roots are read-only and report outputs remain under workbench output.

### Task 2: Formal NL view

**Files:**
- Modify: `src_qor/lib_guard/workbench.py`
- Modify: `src_qor/lib_guard/templates/workbench.html`
- Modify: `src_qor/lib_guard/static/workbench.js`
- Modify: `src_qor/lib_guard/static/workbench.css`
- Test: `src_qor/test/test_workbench.py`

**Interfaces:**
- Main tab key: `formal-nl`.
- Template receives the selected IP's stored `formal_nl_root` and a bounded summary containing matches, stage inventories, View/Corner filename counts, broken links, ambiguities, and report paths.

- [ ] Add failing rendering assertions for the tab, readonly scope notice, stage summary, paths, and downloadable reports.
- [ ] Implement a tab with a per-IP root form, summary table, expandable file paths, issue lists, and JSON/Markdown links.
- [ ] Preserve the active tab and typed path on scan errors; show prior successful snapshot without replacing it.
- [ ] Verify existing Catalog, RAW Discover, and Review tabs still switch correctly.

### Task 3: Regression and live browser verification

**Files:**
- Test: `src_qor/test/test_workbench.py`
- Test: existing `src_qor/test` suite

- [ ] Test multi-stage root, single-stage `lib_NL*/IP` root, no match, broken link, ambiguous target, and scan failure.
- [ ] Snapshot formal-tree paths before/after and assert no formal file or symlink is changed.
- [ ] Run full `src_qor` tests and `git diff --check`.
- [ ] Open the running workbench in a desktop browser; verify the Formal NL tab, one successful scan, error retention, and report download.
