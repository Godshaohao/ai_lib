# Type-Aware File Diff Implementation Plan

Status: current

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every single-file diff state its comparison parameters and prevent binary delivery types from exposing a false text-diff workflow.

**Architecture:** Keep parser outputs and semantic-diff calculation unchanged. Add one static capability mapping in `file_diff.py`; the existing HTML report and Markdown summary consume it. Text-capable types continue to produce `raw_text_diff.html`; metadata-only types produce the existing structured artifacts without that file or link.

**Tech Stack:** Python 3.11 standard library, existing static HTML renderer, `unittest`.

## Global Constraints

- Do not change scan, catalog, release, review-gate, parser registration, CLI arguments, or Web routes.
- Do not add dependencies or configuration fields.
- Text capability is limited to the currently supported structured text types.
- DB, GDS, OAS, and NDM must remain metadata-only.
- Keep JSON, Markdown, structured HTML, and ZIP exports.

---

### Task 1: Lock Type Capability Contracts

**Files:**
- Modify: `src/lib_guard/test/test_scan_pipeline.py`

**Interfaces:**
- Consumes: `diff_pairwise_files(file_type, old_file, new_file, out_dir)`.
- Produces: regression assertions for text and binary artifact sets.

- [x] Add a table-driven test over all supported text types. Assert every `index.html` contains `本类型比较参数`, every `pairwise_summary.md` contains the same parameter list, and every output includes `raw_text_diff.html`.
- [x] Add a metadata-only test for `db`, `gds`, `oas`, and `ndm`. Assert `index.html` names the metadata-only evidence mode and does not link to `raw_text_diff.html`; assert no text-diff file is created.
- [x] Run the two tests before implementation. The expected failures were observed before the renderer change.

### Task 2: Add a Single Capability Mapping

**Files:**
- Modify: `src/lib_guard/diff/file_diff.py`

**Interfaces:**
- Produces: `comparison_capability(file_type) -> dict[str, Any]` with `evidence_mode`, `parameters`, and `text_diff_available`.

- [x] Add a fixed mapping for LEF, Liberty, Verilog, CDL, SDC, UPF, CPF, SPEF, Waiver, IBIS, PWL, SNP, CPM, DB, GDS, OAS, and NDM.
- [x] Use explicit Chinese parameter labels, for example LEF uses `Macro、Pin、方向、Layer、Size`; Liberty uses `Library、Cell、Pin、Timing Arc、Corner`.
- [x] Return a metadata-only default for unknown types.
- [x] Use the capability data in the report contract tests.

### Task 3: Render Type Parameters and Correct Evidence Entrypoints

**Files:**
- Modify: `src/lib_guard/diff/file_diff.py`

**Interfaces:**
- Consumes: `comparison_capability()` in `_render_index()` and the Markdown writer.
- Produces: report parameter panel, Markdown parameter section, and conditional dual-text artifact creation/linking.

- [x] Add a `本类型比较参数` panel before field changes in `index.html`.
- [x] Add a matching Markdown heading and parameter list.
- [x] Create and link `raw_text_diff.html` only when `text_diff_available` is true.
- [x] For metadata-only types, render an explicit “不提供文本逐行对比” evidence note and retain JSON/ZIP evidence links.
- [x] Run Task 1 tests. All type-contract tests pass.

### Task 4: Verify Product and Regression Boundaries

**Files:**
- Modify: `src/lib_guard/test/test_scan_pipeline.py`

**Interfaces:**
- Consumes: generated LEF, Verilog, DB, GDS, OAS, and NDM artifacts.
- Produces: stable artifact behavior across structured text and binary delivery inputs.

- [x] Run focused file-diff, Web artifact, and Render Impact tests.
- [x] Run all unit tests with `PYTHONPATH=src python3 -m unittest discover -s src/lib_guard/test -p 'test*.py' -q`.
- [x] Run `PYTHONPATH=src python3 -m compileall -q src`, `node --check src/lib_guard/web/static/app.js`, and `git diff --check`.
- [x] Generate one LEF and one DB output and inspect the final HTML artifacts: LEF has the dual-text link; DB has no text viewer and uses distinct SHA-256 values.
