# Side-by-Side File Diff Implementation Plan

Status: current

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the static `difflib.HtmlDiff` artifact with a self-contained desktop side-by-side review viewer and expose it as the primary file-diff artifact.

**Architecture:** Keep existing parser and semantic evidence unchanged. Build aligned text rows from `difflib.SequenceMatcher`, render one offline HTML document, and reuse the existing Web artifact route.

**Tech Stack:** Python 3.11 standard library, static HTML/CSS/JavaScript, existing Flask artifact endpoint, `unittest`.

## Global Constraints

- Do not change scan, version matching, review gate, or release behavior.
- Do not add runtime dependencies or a new API.
- Desktop browser is the supported review surface.
- Preserve existing JSON, Markdown, ZIP, and structured HTML artifacts.

---

### Task 1: Lock the Viewer Contract

**Files:**
- Modify: `src/lib_guard/test/test_scan_pipeline.py`

**Interfaces:**
- Consumes: `diff_pairwise_files(file_type, old_file, new_file, out_dir)`.
- Produces: assertions for aligned panes, change navigation, display modes, and keyboard controls.

- [ ] Add a focused test that generates a Verilog diff and asserts `raw_text_diff.html` contains `data-diff-row`, `data-change-block`, `diff-prev`, `diff-next`, `diff-mode`, `仅看变化`, and no default `difflib` legend.
- [ ] Run the focused test and confirm it fails because the current artifact is `HtmlDiff` output.

### Task 2: Render the Side-by-Side Viewer

**Files:**
- Modify: `src/lib_guard/diff/file_diff.py`

**Interfaces:**
- Consumes: `list[str]` from `_read_text()` and `Path` labels.
- Produces: `raw_text_diff.html` containing aligned rows and self-contained controls.

- [ ] Build aligned rows from `SequenceMatcher.get_opcodes()` with context grouping and stable change-block IDs.
- [ ] Render escaped paths, line numbers, status labels, compact CSS, and dependency-free JavaScript.
- [ ] Add previous/next change navigation, compact/full mode, keyboard shortcuts, and current-block highlighting.
- [ ] Run the focused test and confirm it passes.

### Task 3: Prioritize the Review Artifact

**Files:**
- Modify: `src/lib_guard/diff/file_diff.py`
- Modify: `src/lib_guard/test/test_scan_pipeline.py`
- Modify if required by current ordering: `src/lib_guard/web/app.py`

**Interfaces:**
- Consumes: existing file-diff artifact map.
- Produces: human labels that place the side-by-side viewer before raw JSON evidence.

- [ ] Update report copy and artifact labels from “原始文本差异” to “双栏文本对比”.
- [ ] Assert the main report and Web artifact map expose the viewer and keep Markdown/ZIP links.
- [ ] Run file-diff and Web artifact tests.

### Task 4: Desktop Browser Verification

**Files:**
- Reuse: `work/web_file_diff_validation/`

**Interfaces:**
- Consumes: generated LEF and Verilog HTML artifacts.
- Produces: browser evidence that controls and layout work at desktop width.

- [ ] Regenerate two existing real/smoke file-diff outputs.
- [ ] Open the viewer at 1280x720 or larger and verify initial layout, next/previous navigation, compact/full mode, keyboard focus, and scrolling.
- [ ] Run `python3 -m unittest` for the focused suites, `python3 -m compileall -q src`, `node --check src/lib_guard/web/static/app.js`, and `git diff --check`.
