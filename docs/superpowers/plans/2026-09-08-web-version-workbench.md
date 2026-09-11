# Web Version Workbench Implementation Plan

Status: current

> **For agentic workers:** REQUIRED SUB-SKILL: Use `subagent-driven-development` or `executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make version selection and execution a short, explicit flow while
adding bounded type-level hash overrides and distinct asset tables.

**Architecture:** Keep the existing Catalog and scan facts authoritative. Add
two per-run scan strategy lists through the existing CLI argument path,
derive a presentation-only work-queue task from existing version fields, and
render registered libraries separately from candidate discovery rows.

**Tech Stack:** Python 3 standard library, Flask Web Console, vanilla
JavaScript, static HTML/CSS, unittest.

## Global Constraints

- No new short CLI command or persistent Web-only state.
- Keep `smart` hash behavior unchanged without explicit type overrides.
- Do not modify catalog, diff, release, or effective-version data models.
- Use Chinese UI copy for user-facing controls.
- Every behavior change begins with a failing unittest.

---

### Task 1: Add bounded type-level hash overrides

**Files:**
- Modify: `src/lib_guard/project_config.py`
- Modify: `src/lib_guard/scan/policy.py`
- Modify: `src/lib_guard/cli.py`
- Modify: `src/lib_guard/short_cli.py`
- Modify: `src/lib_guard/cli_commands/scan.py`
- Modify: `src/lib_guard/cli_commands/catalog.py`
- Modify: `src/lib_guard/web/app.py`
- Test: `src/lib_guard/test/test_scan_pipeline.py`
- Test: `src/lib_guard/test/test_web_app.py`

- [ ] Write failing policy tests for forced LEF and skipped Verilog under
  `smart`, and for `none` overriding forced selections.
- [ ] Add `force_hash_file_types` and `skip_hash_file_types` to strategy
  configuration defaults and request parsing.
- [ ] Pass both values through CLI and Web scan arguments.
- [ ] Apply the defined decision order in `ScanPolicy.hash_decision()`.
- [ ] Run focused scan and Web API tests.

### Task 2: Turn the version status table into a work queue

**Files:**
- Modify: `src/lib_guard/web/templates/index.html`
- Modify: `src/lib_guard/web/static/app.js`
- Modify: `src/lib_guard/web/static/styles.css`
- Test: `src/lib_guard/test/test_web_ui_contract.py`

- [ ] Write failing UI contract tests for work-queue columns, current
  processing card, and absence of the release column in the queue.
- [ ] Add pure `deriveVersionTask(item)` logic for the five documented
  status/action cases.
- [ ] Render the selected-version card immediately below the queue.
- [ ] Make the primary button label and explanation match the derived action.
- [ ] Move release checking into advanced actions.
- [ ] Run UI contract tests and JavaScript syntax checks.

### Task 3: Make scan settings understandable and bounded

**Files:**
- Modify: `src/lib_guard/web/templates/index.html`
- Modify: `src/lib_guard/web/static/app.js`
- Modify: `src/lib_guard/web/static/styles.css`
- Test: `src/lib_guard/test/test_web_ui_contract.py`

- [ ] Write failing tests for visible type-level hash controls and a heavy
  binary confirmation control.
- [ ] Replace free-text parse-range controls in the primary area with
  explicit hash enhancement checkboxes.
- [ ] Keep parse include/exclude as advanced expert fields; do not conflate
  them with hashing.
- [ ] Disable hash-type controls for `none` and `full` global policies.
- [ ] Require an explicit check before GDS/OAS/DB can be included.
- [ ] Run UI contract tests.

### Task 4: Separate registered-library and candidate tables

**Files:**
- Modify: `src/lib_guard/web/templates/index.html`
- Modify: `src/lib_guard/web/static/app.js`
- Modify: `src/lib_guard/web/static/styles.css`
- Test: `src/lib_guard/test/test_web_ui_contract.py`

- [ ] Write failing contract tests for registered and candidate table IDs.
- [ ] Add a registered-library management table from the existing loaded
  Catalog library data.
- [ ] Retain candidate selection, filtering, and registration behavior in
  its own table.
- [ ] Replace machine-oriented confidence copy with concise discovery basis
  and clear Chinese status labels.
- [ ] Run UI contract tests and manually inspect the Web Console.

### Task 5: Regression and visual verification

**Files:**
- Test: `src/lib_guard/test/test_scan_pipeline.py`
- Test: `src/lib_guard/test/test_web_app.py`
- Test: `src/lib_guard/test/test_web_ui_contract.py`

- [ ] Run compileall and all unit tests.
- [ ] Start the Web Console against the smoke workspace.
- [ ] Verify by browser that a selected version shows one precise primary
  action, the selected base, advanced release check, type-level hash choices,
  and separated tables.
- [ ] Run `git diff --check` and report any remaining visual limitation.
