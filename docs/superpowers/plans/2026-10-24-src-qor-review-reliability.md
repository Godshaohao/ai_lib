# src_qor Review Reliability and Workbench Implementation Plan

Status: current

> **For agentic workers:** Execute this plan task-by-task with test-first checkpoints. Keep changes within `src_qor/` and this plan unless a concrete integration test requires otherwise.

**Goal:** Make per-IP review records context-safe and truthful, make the Excel findings/checklist useful, and provide a small persistent local workbench over the existing four checks.

**Architecture:** Keep the four existing checkers as the only analysis engines. `review_runner` will attach explicit per-check input identity and normalized findings; workbook and overview are projections of those records. A small loopback-only Flask workbench will edit a YAML IP registry and invoke the same runner; JSON files remain the history/latest source, with no database, background queue, plugin system, Scan/Diff, or Release Gate changes.

**Tech Stack:** Python 3.11+, PyYAML, XlsxWriter, Flask 3.x, unittest, Playwright CLI for browser smoke validation when available.

## Global Constraints

- Four check names remain exactly `formal_nl`, `macro_index`, `lef_review`, and `lef_liberty_check`.
- A completed check is not a quality pass, release approval, or proof of complete coverage.
- Different input versions remain separate evidence scopes; cross-check synthesis requires an explicit binding.
- Failed or incomplete checks must not produce normal successful QA answers or replace a previous latest pointer.
- Formal NL inventory remains read-only; existing Release Gate, Catalog, Effective Pointer, and legacy Scan/Diff behavior are out of scope.
- Do not modify or stage unrelated pre-existing worktree changes.

## File Map

- `src_qor/lib_guard/review_runner.py`: per-check identity, normalized findings, accurate summaries/QA, and transactional report publication.
- `src_qor/lib_guard/export_review_excel.py`: workbook layout and filtering/freeze behavior.
- `src_qor/lib_guard/ip_check_overview.py`: roster/latest-run read model and overview rendering.
- `src_qor/lib_guard/workbench.py` and `src_qor/lib_guard/templates/workbench.html`: local registry-backed check-selection/run/download UI.
- `src_qor/configs/ip_registry.example.yml`: persistent IP/check registry example.
- `src_qor/requirements.txt`: declare Flask runtime dependency.
- `src_qor/test/test_review_runner.py`, `test_workbench.py`: regression, persistence, and local UI behavior.
- `src_qor/README.md`: install, run, registry, data-scope and security instructions.
- `docs/superpowers/plans/2026-10-24-src-qor-review-reliability.md`: this executable plan and completion evidence.

---

### Task 1: Truthful normalized findings and failed-check QA

**Files:**
- Modify: `src_qor/lib_guard/review_runner.py`
- Test: `src_qor/test/test_review_runner.py`

**Interfaces:** `_finding_rows(review)` will return stable fields `category`, `kind`, `object`, `count`, `message`, `status`, `action`, `evidence`, plus existing Chinese display fields. `kind` is one of `CHANGED`, `MISMATCH`, `UNVERIFIED`, `SCOPE_INFO`. `_review_summary` counts normalized kinds and separately reports finding rows and affected objects. `_qa_rows` emits a successful answer only for a `COMPLETE` check; failed/incomplete checks get an explicit unavailable answer.

- [x] Add regression cases for unmatched Macro objects, broken formal links, incomplete check, and failed formal inventory.
- [x] Run those tests and observe expected failures against current behavior.
- [x] Implement normalized finding records and status-gated QA rows.
- [x] Run focused runner tests and verify counts distinguish finding rows from affected-object counts.

### Task 2: Explicit input identity and safe cross-check scope

**Files:**
- Modify: `src_qor/lib_guard/review_runner.py`
- Test: `src_qor/test/test_review_runner.py`

**Interfaces:** Add `input_identity` to each check record. It records check-specific source paths, declared source versions/stages, and LEF SHA binding where available. Add run-level `context_alignment` with `ALIGNED_EXPLICIT`, `MIXED_EXPLICIT`, or `INDEPENDENT`; this is informational and never guesses a relationship. The existing LEF-to-Liberty exact source binding remains mandatory when that report is reused.

- [x] Add failing tests for mixed declared RAW versions, unrelated formal stage, and independent inputs with no declared version.
- [x] Run tests to confirm review JSON initially omitted the context alignment and serialized identity.
- [x] Implement deterministic identity extraction from explicit config/result fields only.
- [x] Verify mixed evidence is labeled, not merged or rejected solely because versions differ.

### Task 3: Engineering checklist and filterable Macro-to-View mapping

**Files:**
- Modify: `src_qor/lib_guard/review_runner.py`
- Modify if needed: `src_qor/lib_guard/export_review_excel.py`
- Test: `src_qor/test/test_review_runner.py`

**Interfaces:** Add `04-MacroView文件` with one row per Macro × View file association and columns for IP, RAW version, Macro, View, Corner/name clue, source version, path, mapping evidence, and status. Retain `04-MacroView` as a compact per-Macro summary. Add the ten existing engineering checklist topics from `ai_lib_IP检查_概览问答与证据_优化版.xlsx`: RAW inventory; file Delta; formal files and RAW origin; Macro list/source/update; six-View Macro mapping; Signoff Corner coverage; LEF physical Delta; interface/cross-view consistency; other View internal objects; documentation Delta. Per-IP state is `SUPPORTED_BY_SELECTED_EVIDENCE`, `PARTIAL`, `NOT_CHECKED`, or `NOT_APPLICABLE`; execution status remains separate and no category gets an inferred pass.

- [x] Add workbook model assertions for vertical mapping rows and exactly these ten checklist categories: RAW version/file inventory; file update Delta; formal files/RAW origin; Macro inventory/source/update; Macro six-View mapping; Signoff Corner coverage; LEF physical Delta; cross-View interface consistency; other View internal objects; documentation Delta.
- [x] Run tests to establish the current workbook omitted vertical rows/checklist.
- [x] Implement rows using existing FileMap, parser facts, formal inventory, and review findings.
- [x] Verify exporter applies filterable tables and frozen heading rows; added assertions cover separate IP identity and table sheets.

### Task 4: Atomic result publication and persistent IP latest overview

**Files:**
- Modify: `src_qor/lib_guard/review_runner.py`
- Modify: `src_qor/lib_guard/ip_check_overview.py`
- Test: `src_qor/test/test_review_runner.py`

**Interfaces:** Export workbook to a temporary sibling file, verify non-empty output, then atomically rename it before writing `review_result.json` and updating `latest.json`. Failed export must not advertise a missing workbook or change latest. The overview reads registry entries and each library's `latest.json`/`review_result.json`, and shows the last run even when the current invocation contains only a subset of IPs.

- [x] Add failing test that simulates export failure and asserts no new result/latest is published.
- [x] Add failing test that renders two registered IPs when only one is run in the current invocation.
- [x] Implement staged output publication and registry/latest read model.
- [x] Run runner/overview tests and inspect generated links remain relative and IP-specific.

### Task 5: Local persistent workbench over the existing runner

**Files:**
- Create: `src_qor/lib_guard/workbench.py`
- Create: `src_qor/lib_guard/templates/workbench.html`
- Create: `src_qor/configs/ip_registry.example.yml`
- Modify: `src_qor/requirements.txt`
- Test: `src_qor/test/test_workbench.py`

**Interfaces:** `create_app(registry_path, output_dir)` serves on loopback when run as a module. The page lists registered IPs and last-run status; users can add/edit an IP label, paths, explicit raw/formal identity, and select the four checks. POST validates check names, writes the YAML registry atomically, invokes the existing runner for that IP, and returns run state/artifact links. No shell command or arbitrary command execution is accepted from the browser.

- [x] Write tests for registry load/save, check allowlist, path resolution, and run/output link behavior using a temporary directory.
- [x] Run tests and verify the workbench module was missing before implementation.
- [x] Add the minimal Flask app and one-page form; bind only to `127.0.0.1` by default.
- [x] Add example registry and dependency; malformed YAML is rendered as a visible page error.

### Task 6: Documentation and end-to-end verification

**Files:**
- Modify: `src_qor/README.md`
- Test/verify: all `src_qor/test/`; browser smoke against local workbench.

- [x] Document registry ownership, local-only binding, per-IP output/history, and limits of each status.
- [x] Run `PYTHONPATH=src_qor python3 -m unittest discover -s src_qor/test -v` (25 tests passed; bundled XlsxWriter runtime path was required in this environment).
- [x] Run a controlled two-IP fixture scenario with `RAW_A` and `RAW_B`; verified separate result/workbook directories and latest pointers, with each source version retained only under its own IP.
- [x] Start the workbench on loopback port 5078; in the in-app browser, inspect the registered IP, run the selected Macro Index check, confirm `COMPLETE`, verify the history row and workbook download link. Flask test-client coverage also fetched the XLSX response successfully.
- [x] Review focused `src_qor` diff and `git diff --check`; no Release Gate/legacy workflow code was edited. Other dirty paths were left untouched.

### Completion Evidence (2026-10-24)

- Baseline: branch `semantic-ir-mvp-20261014`, HEAD `99c1e62`; working tree contained unrelated existing modifications before/alongside this task.
- Regression: `Ran 25 tests ... OK`.
- Syntax/whitespace: `py_compile` passed for changed Python modules/tests; `git diff --check` passed.
- Browser: local workbench rendered at `http://127.0.0.1:5078/`; selected `macro_index` ran against the registered smoke report and created `review_20261024T071542Z_28494cd2`, a non-empty `ip_review.xlsx`, `review_result.json`, latest pointer, and history row.
- Multi-IP: two separate libraries produced two workbooks and two latest pointers; explicit source contexts remained `vendor.ip_a=RAW_A` and `vendor.ip_b=RAW_B`.
- Limits: browser execution is synchronous; the in-app browser viewport is narrow and uses the responsive single-column layout. No background queue, live progress, or concurrent run manager was added.

## Acceptance Contract

- Summary counts include unmatched-object and broken-link findings and identify whether a number counts rows or affected objects.
- Failed/incomplete checks cannot say an inventory is empty or imply successful review.
- Every check records its evidence identity; cross-check joins are explicit or labeled independent/mixed.
- Workbook has a filterable vertical Macro-View file mapping and a ten-category execution/coverage checklist without claiming unrun checks passed.
- A workbook export failure does not publish a result record pointing to a missing workbook and does not replace latest.
- IP registry and latest results persist across workbench restarts; reports remain one workbook per IP.
- Existing and new `src_qor` tests pass; real-browser smoke is reported separately from unit tests.
- No legacy Scan/Diff, Catalog, Release Gate, or Effective behavior changes.
