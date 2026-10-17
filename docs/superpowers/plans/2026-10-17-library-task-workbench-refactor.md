# Library-Centered Web Workbench Refactor Implementation Plan

Status: current

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reorganize the Lib Guard Web interface around the library maintainer's task and current next step, while preserving existing scan, compare, effective, review, release, audit, and evidence behavior.

**Architecture:** Keep the existing Flask routes, `read_model`, job requests, persisted workflow records, and decision/gate logic as the only sources of truth. Change the presentation layer to derive a task-oriented view from those existing fields; do not add a parallel workflow state machine or duplicate `pending_window`, `action_readiness`, or `current_effective`. Keep the user's requested Scan/Compare/File Diff/Checks/Review tabs directly accessible as peer actions; keep low-frequency configuration and raw evidence contextual. Release-center viewing stays separate from source-library review while sharing navigation.

**Tech Stack:** Python 3.11+, Flask, existing HTML template, vanilla JavaScript, CSS, unittest, local Web app and browser interaction validation.

## Global Constraints

- The interface is for desktop engineering use; responsive behavior must not compromise the desktop information density or create an unsupported mobile-first redesign.
- Do not change scan, compare, effective composition, review gate, release gate, link creation, or CLI business rules in this UI-only refactor.
- Do not add a parallel state machine, second usage decision, or derived state that can disagree with existing read-model fields.
- Reuse existing routes and APIs. Add a read-model field only when a visible interaction cannot be implemented from existing response data; document and test that field.
- `next-preview`, `next-apply`, `accept-window`, and existing evidence/job mechanisms remain authoritative. Preview and execution must use the same selected composition and order.
- Preserve audit identity, confirmation prompts, version notes, deep file comparison, HTML reports, old URLs, run history, and failure diagnostics.
- Do not make scan/apply/accept/release actions execute as a side effect of selection or navigation.
- No React migration or broad backend rewrite in this work.

---

## Baseline and Scope

The attached review is based on GitHub `main` commit `1b7a0fb`. The current repository also contains later semantic-review work on branch `semantic-ir-mvp-20261014` (commit `af701d0`). At implementation time, first inspect the actual target branch and reconcile these changes before coding; do not reset or overwrite the semantic-review work. The plan concerns Web information architecture and interaction only.

Primary files:

- `src/lib_guard/web/templates/index.html`: navigation, library workspace, version list, analysis, effective composition, release center, version notes, expert disclosures.
- `src/lib_guard/web/static/app.js`: route/tab state, current-library and selected-version rendering, readiness-driven action selection, forms and action submission.
- `src/lib_guard/web/static/styles.css`: desktop layout, table density, task card, status hierarchy, task progress and runtime feedback.
- `src/lib_guard/web/read_model.py`: existing library/version/readiness/effective/release projections. Modify only if a required display field cannot be derived from its current contract.
- `src/lib_guard/web/app.py`: route/API contracts. Modify only if read-only projection data is missing; do not add mutation behavior for presentation convenience.
- `src/lib_guard/test/test_web_ui_contract.py`: structural and interaction contracts for HTML and JavaScript.
- `src/lib_guard/test/test_web_app.py`: route/read-model response contracts and safety boundaries.
- `src/lib_guard/test/test_version_detail_ui_contract.py`: preserve version-detail and report compatibility.
- `docs/web_console_checklist.md` and `docs/basic_tutorial.md`: update only after behavior and wording stabilize.

Existing contracts to inspect before implementation:

- Library read model fields: `pending_window`, `action_readiness`, `current_effective_stack`, package/version status, scan/compare evidence references, release state.
- Existing actions: `next-preview`, `next-apply`, `accept-window`, `scan`, `compare`, `file-diff`, `checks`, `review`, effective rollback, single/multi-library release and published-directory inspection.
- Existing URL state: selected library/version, directory mode, stage, active analysis action, filters and result links.
- Existing job lifecycle and persisted run history; the UI must not replace or hide them after a task completes.

### Existing Field-to-View Map

Use these fields as the starting contract. Verify actual response nesting while implementing; do not add replacement fields with different semantics.

| User-visible fact | Existing source | Allowed presentation use |
|---|---|---|
| Version identity and raw source path | `list_version_rows()` → `version_id`, `raw_path` | Version table, selected-version context, copy/open-source affordance |
| Package type and base | `package_type`, `base_version`, `adjacent_base_version`, `cumulative_base_version` | Compact row and expanded comparison context; never auto-correct package type in the view |
| Scan evidence | `scan_status`, `scan_evidence_ready`, `scan_dir`, `scan_html`, `action_readiness.scan` | Show whether evidence is absent, usable or needs repair; do not equate PASS with approval |
| Version comparison | `diff_status`, `diff_html`, `change_summary`, `action_readiness.compare` | Result summary and evidence link; do not infer path movement as a true new file |
| Version task | `workflow_status.label`, `.reason`, `.next_action`, plus `action_readiness` | Choose the single primary UI action and explain why; keep decision semantics in the existing model |
| Current effective composition | library row `current_effective_stack` | Show current Base FULL, overlays and provenance |
| Pending candidate composition | library row `pending_window.candidate_effective_stack`, `.candidate_effective_id`, `.state` | Show proposed composition and whether its preview/manifest exists; never label it current |
| Release inspection | `list_release_library_rows()` and `release_stage_detail()` | Read-only published directory inventory, actual paths, source versions and link check results |
| Job progress and history | existing job/run APIs and run records | Show active stage/progress and retain terminal status, log/artifacts after completion |

The current selectors are in `src/lib_guard/web/read_model.py`: `list_version_rows`, `_action_readiness`, `_workflow_status`, `_pending_window`, `list_library_rows`, `list_release_library_rows`, and `release_stage_detail`. If a row needs one extra display field, add a test in `test_web_app.py` first and project only a value already supported by persisted facts; do not make the HTML or JavaScript calculate a new workflow decision.

## Target Information Architecture

Top-level navigation has two destinations:

1. **库工作台**: discover/register and maintain source libraries, see version history, process an update, inspect results and manage the effective combination.
2. **发布中心**: inspect actual published directories, review source and link integrity, and prepare/execute single- or multi-library publication.

Settings and exceptional maintenance are contextual secondary entry points, not daily top-level destinations.

Selecting a source library opens one task-oriented workspace with this order:

1. Library identity, current effective combination and one concise actionable summary.
2. Version table, open by default, with only the columns needed to select and understand work.
3. A task panel for the selected version, showing current step, one primary action, secondary inspect actions and a clear effect statement.
4. Result/evidence view, shown when available; it leads with changes, evidence coverage and unresolved review decisions.
5. Effective current-versus-candidate composition and editor, available in the same library context but collapsed until relevant.
6. Expert actions, raw evidence and lower-frequency maintenance behind named disclosures.

The default version-table facets are **待处理**, **全部版本**, and **异常**. Advanced filtering may expose evidence state, package type, current-effective role and date. The table keeps full version identifiers available through copy/selection and detail, but does not spread low-value diagnostic fields across every row.

## Implementation Tasks

### Task 1: Lock Existing Data and Mutation Contracts

**Files:**
- Inspect: `src/lib_guard/web/read_model.py`
- Inspect: `src/lib_guard/web/app.py`
- Inspect: `src/lib_guard/web/static/app.js`
- Test: `src/lib_guard/test/test_web_app.py`
- Test: `src/lib_guard/test/test_web_ui_contract.py`

**Interfaces:**
- Consumes: existing library, version, readiness, effective, release, and job-response fields.
- Produces: a documented field-to-view map in this plan's implementation notes; no new state API unless a failing test demonstrates a concrete missing field.

- [x] **Step 1: Inventory current responses and actions**. The field-to-view map above records existing source fields and read-model consumers; no new state API was needed.
- [x] **Step 2: Add safety tests before changing navigation**. Added a read-only page/library/version route test asserting no job root is created; existing job and acceptance contracts remain in place.
- [x] **Step 3: Add source-of-truth assertions**. The next-action presentation helper consumes `action_readiness` and the existing version task derivation; it does not write workflow state.
- [x] **Step 4: Run focused tests**.

Run: `PYTHONPATH=src python3 -m unittest src.lib_guard.test.test_web_app src.lib_guard.test.test_web_ui_contract -q`

Expected: all existing and new tests pass; no mutation occurs during read-only page load.

### Task 2: Simplify Navigation and Make the Library Workspace Task-First

**Files:**
- Modify: `src/lib_guard/web/templates/index.html`
- Modify: `src/lib_guard/web/static/app.js`
- Modify: `src/lib_guard/web/static/styles.css`
- Test: `src/lib_guard/test/test_web_ui_contract.py`
- Test: `src/lib_guard/test/test_web_app.py`

**Interfaces:**
- Consumes: existing directory mode, selected library/version, URL state and library read model.
- Produces: two clear primary destinations (库工作台, 发布中心), a default-expanded version list, and a selected-version task panel.

- [x] **Step 1: Add failing HTML contract tests**. Contracts cover the two work domains, expanded version table, scoped internal views and legacy published-directory route.
- [x] **Step 2: Add failing JavaScript contract tests**. Read-only route/job creation and version task readiness are covered; browser selection was verified without executing a job.
- [x] **Step 3: Reorganize template markup**. Library management is a disclosure; version list precedes analysis; published-directory inspection is under 发布中心.
- [x] **Step 4: Simplify default library filters**. Three main facets remain visible; detailed facets are in 高级筛选.
- [x] **Step 5: Implement state mapping with existing data**. `versionPrimaryAction()` maps current readiness to one primary version action.
- [x] **Step 6: Run focused tests and syntax check**.

Run: `PYTHONPATH=src python3 -m unittest src.lib_guard.test.test_web_ui_contract src.lib_guard.test.test_web_app -q`

Run: `node --check src/lib_guard/web/static/app.js`

Expected: focused tests pass; selecting/navigation remains read-only; existing result deep links work.

### Task 3: Build One State-Driven Update Task Panel

**Files:**
- Modify: `src/lib_guard/web/templates/index.html`
- Modify: `src/lib_guard/web/static/app.js`
- Modify: `src/lib_guard/web/static/styles.css`
- Test: `src/lib_guard/test/test_web_ui_contract.py`
- Test: `src/lib_guard/test/test_web_app.py`

**Interfaces:**
- Consumes: `pending_window`, `action_readiness`, existing package type/base information, current effective, scan/compare evidence state and job response.
- Produces: one primary action appropriate to the current state, explicit impact text, and non-destructive secondary routes to evidence and expert operations.

- [x] **Step 1: Define the UI state table in tests**. The table distinguishes per-version work from library-level composition:

  | Existing state | Primary action | Required behavior |
  |---|---|---|
  | Package type unknown | Confirm package type | No scan/preview until saved; explain classification impact |
  | Candidate combination not selected | Preview update | Plan-only; no scan, effective switch or release link |
  | Preview is current | Execute and generate candidate | Reuse that exact preview selection and order |
  | Task running | View progress | Do not allow duplicate submission for the same in-flight action |
  | Evidence ready, candidate not accepted | Confirm as current effective | Show exact old/new composition and confirmation identity |
  | Blocked/failed | Inspect blocker or retry | Preserve old effective; show error and run/log entry |
  | No version selected / no pending version task | Disabled selection prompt or existing detail action | Do not fabricate a scan/compare action; candidate composition is handled by the library-level composition workflow |

- [x] **Step 2: Add failing behavior tests**. Contracts cover unknown package type, scan/compare ready and blocked states, selected/no-selection behavior, primary action disabled while another action runs, exact preview payload/order reuse, stale candidate rejection, reviewer identity validation, and read-only tab/route selection.
- [x] **Step 3: Implement the task panel**. The version focus now has one readiness-driven primary action and a lower-weight detail action; no action runs on selection.
- [x] **Step 4: Consolidate progress feedback**. Existing runtime strip remains collapsed when idle and retains run output/artifacts after tasks.
- [x] **Step 5: Verify failure preservation**. `test_failed_next_apply_preserves_current_stack_selection_and_run_log` asserts the apply request reuses the exact preview payload/order, leaves the old effective and candidate identity untouched on failure, preserves the selected draft/preview, clears the busy state, and retains the run-log URL and failure summary. This is a focused UI-state contract test; a real browser job failure remains part of Task 7.
- [x] **Step 6: Run focused tests**. Fresh focused Web/UI tests pass; see verification below.

Run: `PYTHONPATH=src python3 -m unittest src.lib_guard.test.test_web_ui_contract src.lib_guard.test.test_web_app -q`

Expected: all task-state cases pass with no second state machine and no accidental mutation.

### Task 4: Combine Current and Candidate Effective Composition

**Files:**
- Modify: `src/lib_guard/web/templates/index.html`
- Modify: `src/lib_guard/web/static/app.js`
- Modify: `src/lib_guard/web/static/styles.css`
- Test: `src/lib_guard/test/test_web_ui_contract.py`
- Test: `src/lib_guard/test/test_web_app.py`

**Interfaces:**
- Consumes: existing `current_effective_stack`, pending candidate stack, preview payload and composition-selection form.
- Produces: one side-by-side/current-versus-candidate composition view and a disclosure-based editor, preserving current data contracts.

- [x] **Step 1: Add tests for composition display**. Contracts cover composition rows/order, current-versus-candidate labels, accepted-candidate handling, confirmation text, and an empty composition state. Missing scan/version evidence is shown as “未读取/待补齐”, not as an inferred pass.
- [x] **Step 2: Add tests for manual choices**. Tests cover single Base FULL, ordered multi-overlay choices, draft persistence, preview invalidation on changed order, exact preview reuse for apply and stale-candidate acceptance rejection.
- [x] **Step 3: Render the comparison card**. Existing current/candidate summary and composition table show Base FULL and ordered overlays; source labels come from existing read-model provenance. No new decision is inferred.
- [x] **Step 4: Keep the editor contextual**. The selector/editor remains inside the effective-composition section, not a new page. The table is directly available for checkbox/selection and order edits, matching the requested low-friction composition workflow.
- [x] **Step 5: Run focused effective and Web tests**. Covered by the 184-test focused run recorded below.

Run: `PYTHONPATH=src python3 -m unittest src.lib_guard.test.test_web_ui_contract src.lib_guard.test.test_web_app -q`

Expected: selection, preview and acceptance tests pass; current/candidate provenance and order remain consistent.

### Task 5: Make Version Analysis Result-First and Simplify Version Notes

**Files:**
- Modify: `src/lib_guard/web/templates/index.html`
- Modify: `src/lib_guard/web/static/app.js`
- Modify: `src/lib_guard/web/static/styles.css`
- Test: `src/lib_guard/test/test_web_ui_contract.py`
- Test: `src/lib_guard/test/test_version_detail_ui_contract.py`
- Test: `src/lib_guard/test/test_web_app.py`

**Interfaces:**
- Consumes: scan and compare result summaries, version-note fields and existing detail/report links. Technical review conclusions remain on the existing Version Detail/review surfaces; this summary must not create a second decision projection.
- Produces: result-first analysis view and a concise default version-note editor without changing report or decision models.

- [x] **Step 1: Add result hierarchy tests**. Contracts assert the existing result summary precedes action controls, shows scan/compare facts and report links, and does not infer risk. Added a test for the recorded `base_version`; adjacent suggested base is not substituted. Human review decisions stay in existing review surfaces because the current response has no authoritative unresolved-decision projection.
- [x] **Step 2: Add note compatibility tests**. Added a UI contract for concise default fields, advanced detail fields and the updated action label; existing note/detail contracts remain.
- [x] **Step 3: Reorder analysis regions**. The result summary is above the direct peer action tabs. Scan/Compare/File Diff/Checks/Review remain directly accessible per the workflow requirement; file rows have a dedicated view in the same workspace. No navigation action submits a task.
- [x] **Step 4: Simplify note editing**. Renamed the action to “更新版本说明”; summary/impact/advice remain in the default form, while detailed risks/checks/evidence are collapsed. Existing audit and save behavior is unchanged.
- [x] **Step 5: Run result/detail tests**. The 184-test focused run includes Web/UI, route, formal-inventory and Version Detail contracts.

Run: `PYTHONPATH=src python3 -m unittest src.lib_guard.test.test_web_ui_contract src.lib_guard.test.test_version_detail_ui_contract src.lib_guard.test.test_web_app -q`

Expected: result, notes and evidence links remain correct; no release or usage decision is inferred by the view.

### Task 6: Unify Published-Directory Inspection and Release Operations in a Release Center

**Files:**
- Modify: `src/lib_guard/web/templates/index.html`
- Modify: `src/lib_guard/web/static/app.js`
- Modify: `src/lib_guard/web/static/styles.css`
- Modify only when a required read projection is missing: `src/lib_guard/web/read_model.py`, `src/lib_guard/web/app.py`
- Test: `src/lib_guard/test/test_web_ui_contract.py`
- Test: `src/lib_guard/test/test_web_app.py`

**Interfaces:**
- Consumes: existing formal directory inventory, published source/link checks, single/multi-library release plan and job endpoints.
- Produces: one Release Center with distinct “已发布目录” and “发起发布” subviews; no duplicate release rule or link semantics.

- [x] **Step 1: Add navigation and separation tests**. Contracts distinguish the two work domains and the mutually exclusive single/multi/inventory views; API tests keep formal inventory refresh read-only, release plan dry-run only, and actual apply behind confirmation.
- [x] **Step 2: Reorganize published view**. Existing directory inventory remains in the separate “已发布目录” work view; browser-tested legacy `directory=published` deep links restore that view.
- [x] **Step 3: Reorganize release actions**. Single-library release, multi-library release and release-stage inventory now have mutually exclusive subviews. Existing paths, collision behavior and confirmations are unchanged.
- [x] **Step 4: Verify the complete interaction paths**. `test_formal_inventory.py` proves inventory refresh leaves Catalog, effective pointer, and existing symlinks unchanged and preserves the prior snapshot after invalid-root failure. `test_web_app.py` covers dry-run release planning and explicit confirmed apply request construction; release-flow and multi-stage tests cover collision/failure preservation and partial results. No real external release root was mutated.
- [x] **Step 5: Run route and UI tests**. Focused Web/UI, formal inventory, and Version Detail contracts pass (183 tests before the added comparison-base test; rerun evidence is recorded below).

Run: `PYTHONPATH=src python3 -m unittest src.lib_guard.test.test_web_ui_contract src.lib_guard.test.test_web_app -q`

Expected: published inventory and source release actions are discoverable in one destination but remain behaviorally distinct.

### Task 7: Browser Acceptance, Regression, and Documentation

**Files:**
- Update after the UI stabilizes: `docs/web_console_checklist.md`
- Update after behavior stabilizes: `docs/basic_tutorial.md`
- Test: all `src/lib_guard/test/test*.py`

**Interfaces:**
- Consumes: completed UI and existing synthetic/fixture workspaces.
- Produces: reproducible browser evidence for all six scenarios, full regression output, updated user instructions.

- [ ] **Step 1: Prepare deterministic test workspaces**. Use isolated temporary roots and synthetic catalogs for: a first single-version library, a normal FULL+FIX sequence, UNKNOWN package type, multiple overlays, a failed job, and a published directory with valid and broken links. Do not run destructive release operations against a real release root.
- [ ] **Step 2: Execute six browser scenarios**:
  1. First use: browse a raw path, discover and register a new library, then see its version in the workspace.
  2. Normal update: preview and process an incremental version, inspect results, and confirm the candidate only after evidence is ready.
  3. Unknown package type: identify the required correction without attempting scan/apply prematurely.
  4. Multiple overlays: change selection/order, regenerate preview and verify the candidate uses the exact order.
  5. Mid-run failure: find the failure reason, retry safely and confirm the old effective remains active until explicit acceptance.
  6. Formal publication: distinguish accepted effective composition from actual published directory; inspect links and only execute a temporary-root publish after explicit confirmation.
- [ ] **Step 3: Record measurable acceptance**. For normal update, a first-time maintainer can identify the single next action without opening expert controls; each state has one primary action; selection/navigation causes no mutation; no task feedback disappears after completion; failed/retried work cannot accept a stale candidate; release-view refresh never creates links.
- [ ] **Step 4: Run browser interaction checks**. Use the installed desktop browser session at a desktop viewport. Capture screenshots for initial library workspace, result-first analysis, current-vs-candidate composition, release center, and a failed-job state. Record the test workspace/config path and URLs so another reviewer can replay the session.
- [x] **Step 5: Run all tests and syntax checks**.

Run: `PYTHONPATH=src python3 -m unittest discover -s src/lib_guard/test -p 'test*.py' -q`

Run: `node --check src/lib_guard/web/static/app.js`

Run: `git diff --check`

Expected: the full suite passes; browser scenarios meet the stated outcomes; screenshots show no clipped content, accidental duplicate action or stale status. Automated suite and syntax checks passed. A fresh 5080 browser session verified the 4 x 50-version workspace, result summary and Release Center, but the six full browser scenarios remain open (see Iteration Evidence).

- [x] **Step 6: Update user documentation**. Tutorial and acceptance checklist now describe the two work domains, analysis result ordering, explicit update-note behavior, failure preservation, read-only inventory refresh and separate publication action. CLI references remain supplementary.

## Acceptance Criteria

- A first-time maintainer can select a library and determine what needs attention and what the primary next action does without reading CLI command names or opening expert controls.
- Only one primary action is visually emphasized for a selected workflow state. A blocked state offers the blocker/evidence or a safe retry, never a false accept/release action.
- Version history is visible by default, searchable and usable at 1, 50 and 500 versions without losing full identifiers or creating an unusable table.
- Current effective and proposed candidate are compared in one place; the Base FULL, overlay membership, order, provenance and current/candidate labels are accurate.
- Preview and execution share one exact composition; changed selection invalidates stale preview; stale candidates cannot be accepted.
- Scan/compare completion is not represented as technical approval, and file counts are not represented as risk.
- Results, notes, run history and raw evidence remain discoverable after navigation or refresh; failed runs remain inspectable.
- Published-directory inspection and link checks remain read-only; actual release/link creation requires the existing explicit action and confirmation.
- All existing CLI and Web routes, run logs, audit records and result URLs remain compatible unless a separately reviewed migration is approved.
- No release-gate behavior or underlying technical judgment changes in this UI refactor.

## Risks and Mitigations

- **Risk: presentation state diverges from backend readiness.** Mitigation: Task 1 contracts make existing read-model fields authoritative; keep only labels/presentation mapping in JS.
- **Risk: visual consolidation hides advanced capability.** Mitigation: each moved control has a named expert disclosure, a stable deep link, and an interaction test.
- **Risk: moving release views mixes source and formal paths.** Mitigation: the Release Center shares navigation only; read-only inventory and mutation actions remain distinct subviews and endpoints.
- **Risk: preview and apply use different composition.** Mitigation: preserve the existing preview payload as the apply input and test the exact selected order and candidate identity.
- **Risk: broad edits to a large template/JS file cause regressions.** Mitigation: one task/one interaction contract at a time, preserve stable IDs, run focused tests after each task, then full regression and browser acceptance.
- **Risk: existing users have direct links to old workspaces.** Mitigation: preserve URL parameters and add route/UI tests for old library, version, analysis result and published-directory links.

## Execution Order

1. Task 1: lock existing sources and safety boundaries.
2. Task 2: task-first library workspace and navigation.
3. Task 3: state-driven update task panel.
4. Task 4: current/candidate composition comparison.
5. Task 5: result-first analysis and concise version notes.
6. Task 6: Release Center.
7. Task 7: browser acceptance, full regression and docs.

Do not start Tasks 2-6 until Task 1's source-of-truth and mutation-boundary tests pass. Do not start Task 7 until the focused tests for Tasks 2-6 pass.

## Iteration Evidence (2026-10-17)

- Added a result-summary contract for the actual recorded comparison base (`base_version`); the adjacent-base suggestion is deliberately not substituted. The initial test failed because the UI had no base field; it passes after the view change.
- Focused verification: `PYTHONPATH=src python3 -m unittest src.lib_guard.test.test_web_ui_contract src.lib_guard.test.test_web_app src.lib_guard.test.test_formal_inventory src.lib_guard.test.test_version_detail_ui_contract -q` passes: 185 tests.
- Full regression: `PYTHONPATH=src python3 -m unittest discover -s src/lib_guard/test -p 'test*.py' -q` passes: 996 tests.
- Static checks: `node --check src/lib_guard/web/static/app.js` and `git diff --check` pass.
- Added a red/green contract for the primary version action while another job is running. The extracted predicate retains that behavior and makes it directly testable.
- Fresh browser check: started the current app at `http://127.0.0.1:5080/` against `work/many_versions_ui_20260909/lib_guard.yml`. The UI lists four libraries with 50 versions each, defaults to 3/50 focused versions, shows the recorded comparison base, and renders the Release Center. Desktop screenshots and accessibility state were inspected; browser console had no errors. No write actions were submitted.
- Fixture limitation: the selected version reports stale/mismatched scan evidence against its current raw tree, so release actions correctly remain disabled. This is fixture data, not a passing release flow. The six mutating/long-running browser scenarios in Task 7 Step 2 and the corresponding acceptance measurements remain unverified; Task 7 is therefore not complete.
