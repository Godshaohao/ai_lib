Status: archived

# Effective Baseline Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `executing-plans` task-by-task. Each task uses test-first validation.

**Goal:** Ensure that only an accepted current-effective pointer represents an effective library; a library without one enters an explicit initial-baseline review flow.

**Architecture:** Keep the existing `FULL + accepted FIX overlays -> effective_manifest -> compare -> accept -> current_effective.json` pipeline. Change only the window resolver's no-pointer branch: it must produce a reviewable bootstrap candidate, never silently treat a raw FULL as an accepted base. Intake preview becomes read-only; execution remains the only operation that persists a window and plan.

**Tech Stack:** Python 3.11, `unittest`, JSON artifacts, static HTML impact rendering.

## Global Constraints

- Do not add a new CLI command, page, service, database, or workflow engine.
- `current_effective.json` remains the only accepted-effective fact in this change.
- Catalog version list order remains the explicit source order; reject duplicate version IDs rather than guessing chronological order.
- Keep existing FULL/FIX composition, compare, approval, and render-impact mechanisms.
- Do not alter scan/parser/release behavior.

---

### Task 1: Lock explicit initial-baseline behavior

**Files:**
- Modify: `src/lib_guard/test/test_window_intake.py`
- Modify: `src/lib_guard/window/resolver.py`

**Interfaces:**
- Consumes: Catalog versions with explicit `package_type`.
- Produces: `resolve_review_window(...)["state"]`, `review_kind`, `base_effective`, `candidate_effective`, `scan_versions`, and `compare`.

- [x] Write failing tests for these cases:
  - no pointer + one FULL -> `PENDING`, `review_kind == "INITIAL_BASELINE"`, no accepted base, one scan target, raw FULL to effective identity compare;
  - no pointer + historical FULL/FIX plus later FULL/FIX -> latest FULL plus later FIX become candidate, earlier versions are intermediate evidence and are not scanned;
  - no pointer + no FULL -> `NEEDS_FULL_BASE`, with no candidate commands.
- [x] Run the focused test module and confirm the old latest-full fallback expectation fails.
- [x] Replace the no-pointer fallback anchor with `uninitialized`; use the latest FULL only while building the bootstrap candidate.
- [x] Mark bootstrap comparisons as `bootstrap_identity`, retaining the existing compare command and acceptance evidence contract.
- [x] Limit bootstrap scans to the candidate base and overlays, excluding intermediate evidence.
- [x] Run `test_window_intake.py` and confirm it passes.

### Task 2: Make inspection non-mutating and ordering deterministic

**Files:**
- Modify: `src/lib_guard/test/test_window_intake.py`
- Modify: `src/lib_guard/window/cli.py`
- Modify: `src/lib_guard/window/resolver.py`

**Interfaces:**
- Consumes: `cmd_intake(..., plan_only=True)` and catalog version arrays.
- Produces: preview output without `pending_window.json` or `current_plan.json`; deterministic failure for duplicate version IDs.

- [x] Write failing tests that verify plan-only intake creates no window or plan files, and duplicate version IDs raise a clear `ValueError`.
- [x] Run those focused tests and confirm they fail for the expected old behavior.
- [x] Persist `pending_window.json` and `current_plan.json` only during `--apply`; preserve output generation in plan-only mode.
- [x] Validate duplicate version IDs in resolver before any window is computed.
- [x] Update the `--fix` help text so it states that it only shows correction guidance and makes no changes.
- [x] Run the focused modules and confirm they pass.

### Task 3: Verify the user-facing worklist contract

**Files:**
- Modify: `src/lib_guard/test/test_window_intake.py`
- Modify: `src/lib_guard/window/cli.py`

**Interfaces:**
- Consumes: bootstrap and no-full window states.
- Produces: Chinese worklist status/action text that distinguishes initial review from an accepted effective library.

- [x] Write failing worklist assertions:
  - bootstrap appears as `待建立有效版`, with `lg next <LIBRARY> --apply`;
  - no-full appears as `缺少完整包基线`, with the non-mutating correction guide.
- [x] Implement only the required labels and actions in `_worklist_row` / text formatting.
- [x] Run the focused test module and inspect text output from the fixture catalog.

### Task 4: Regression verification

**Files:**
- No production files beyond Tasks 1-3.

- [x] Run `PYTHONPATH=src python3 -m unittest src.lib_guard.test.test_window_intake src.lib_guard.test.test_effective_pointer src.lib_guard.test.test_short_cli_command_surface -q`.
- [x] Run `PYTHONPATH=src python3 -m unittest discover -s src/lib_guard/test -p 'test*.py' -q`.
- [x] Run `PYTHONPATH=src python3 -m lib_guard.window.cli worklist --catalog work/library_registry_smoke/catalog/catalog.json --workdir work/library_registry_smoke --catalog-html-out work/library_registry_smoke/catalog/html --format text` and verify that no-pointer libraries are no longer reported as `无新版本`.
- [x] Record any unrelated existing failure without modifying unrelated modules.

## Execution Result

- All 433 unit tests and source compilation passed on 2026-07-22.
- The fixture worklist reports `待建立有效版` for all nine libraries without an accepted pointer; it no longer reports `无新版本` merely because a raw FULL exists.
- The expected invalid legacy scan-mode diagnostic is exercised by the test suite and does not fail verification.

## Explicit Deferrals

- Canonical-pointer migration and duplicate pointer reconciliation.
- Rollback CAS hardening.
- Bulk package-type editing UI/table.
- Version-detail UI redesign and catalog schema changes.
- AI-driven approval or automated acceptance.
