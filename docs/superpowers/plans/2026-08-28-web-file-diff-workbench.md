# Web File Diff Workbench Implementation Plan

Status: current

> **For agentic workers:** Execute the tasks in order with test-first checkpoints. Do not add a second review page or a second diff fact model.

**Goal:** 在版本详情工作区内，让用户从已有变化清单选择一对旧/新文件并执行受控的深度文件对比。

**Architecture:** Web 读取当前 Catalog 和已有 Diff 的 `file_changes`，只负责筛选、路径校验、动作提交和结果展示。相同相对路径继续调用现有 `lg fd <library> <version> <relpath> --base`；路径迁移使用服务端从 Catalog 解析出的绝对路径调用现有 `lg fd --old --new`，不接受浏览器提交的绝对路径。新增文件或删除文件不生成伪造的双文件 Diff。

**Tech Stack:** Flask、现有 `short_cli`、现有 `file_diff`、原生 HTML/CSS/JavaScript、Python `unittest`。

## Global Constraints

- Version Detail 仍是唯一审查投影；不新增审查页面。
- 不自动对全部变化文件做深度读取或哈希。
- 浏览器只能提交当前 Catalog 库/版本内的相对路径。
- Verilog/Liberty/SPEF 和二进制视图默认保留轻量证据；深度读取必须显式确认。
- 运行结果写入既有 Web job 和 Diff 输出目录，不覆盖历史扫描或对比结果。

### Task 1: Read Existing File-Change Pairs

**Files:**
- Modify: `src/lib_guard/web/read_model.py`
- Test: `src/lib_guard/test/test_web_app.py`

**Interfaces:**
- Add `list_file_diff_rows(web_state, library, version) -> list[dict[str, Any]]`.
- Each row contains `change`, `file_type`, `new_path`, `old_path`, `evidence_mode`, `review_lane`, and `deep_diff_available`.

- [x] Write a failing test for changed and moved rows, and assert added/deleted rows are marked unavailable.
- [x] Run the targeted test and verify it fails because the reader is absent.
- [x] Read only the selected version's existing `diff.file_diff`; normalize old/new path fields without walking RAW.
- [x] Run the targeted test and verify it passes.

### Task 2: Add Safe Linked File-Diff Request

**Files:**
- Modify: `src/lib_guard/web/app.py`
- Test: `src/lib_guard/test/test_web_app.py`

**Interfaces:**
- Extend the existing `POST /api/libraries/<library>/versions/<version>/file-diff` payload with optional `old_relpath`.
- Same-path requests use the existing library/version CLI form.
- Different-path requests resolve both paths from the selected Catalog versions and use existing explicit `fd --old --new`.

- [x] Write failing tests for a moved pair, path traversal, a cross-library base, and a binary request without `force_large`.
- [x] Run those tests and verify the expected failures.
- [x] Validate both relative paths with the existing bounded path rules; resolve them only against Catalog `raw_path`; reject missing files and invalid pairing before job creation.
- [x] Preserve `force_large` as an explicit opt-in and keep all requests as argument arrays.
- [x] Run the targeted tests and verify they pass.

### Task 3: Add the Desktop Linked/Deep Diff Controls

**Files:**
- Modify: `src/lib_guard/web/templates/index.html`
- Modify: `src/lib_guard/web/static/app.js`
- Modify: `src/lib_guard/web/static/styles.css`
- Test: `src/lib_guard/test/test_version_detail_ui_contract.py`
- Test: `src/lib_guard/test/test_web_ui_contract.py`

**Interfaces:**
- Add a collapsed `文件核对` block inside the existing version action area.
- Add filters for view type and change type, a search field, a scrollable result table, selected old/new path fields, and one `运行深度核对` action.
- Selecting an eligible row fills the paths and type; the action is disabled for added/deleted/unknown rows.
- On completion, show the existing job log and generated result link in the current `最近运行` area.

- [x] Add failing static contract tests for the file-change table, filters, old/new path fields, and the linked action.
- [x] Run the UI tests and verify the missing-control failure.
- [x] Render rows from `/api/libraries/<library>/versions/<version>/file-changes`; keep the table height bounded with scrolling.
- [x] Submit the selected pair to the existing file-diff endpoint and reuse the existing job polling state.
- [x] Add concise Chinese copy explaining why one-sided and light-evidence rows are not directly deep-compared.
- [x] Run the UI tests and verify they pass.

### Task 4: Verify Result Linking and Regression Boundaries

**Files:**
- Modify: `docs/web_console_checklist.md`
- Test: `src/lib_guard/test/test_web_app.py`
- Test: `src/lib_guard/test/test_version_detail_ui_contract.py`

- [x] Test that a completed file-diff request does not mutate prior scan or whole-version diff records.
- [x] Test that the result is discoverable through the existing job status/log response and current version detail link.
- [x] Test desktop HTML markers, duplicate IDs, Python compilation, JavaScript syntax, and full unit suite.
- [x] Update the Web checklist with linked selection, path-migration pairing, one-sided rows, and explicit large-file confirmation.

Validation commands:

```bash
PYTHONPYCACHEPREFIX=work/.pycache PYTHONPATH=src:work/web_deps python3 -m unittest src.lib_guard.test.test_web_app src.lib_guard.test.test_version_detail_ui_contract src.lib_guard.test.test_web_ui_contract -q
PYTHONPYCACHEPREFIX=work/.pycache PYTHONPATH=src:work/web_deps python3 -m compileall -q src
node --check src/lib_guard/web/static/app.js
PYTHONPYCACHEPREFIX=work/.pycache PYTHONPATH=src:work/web_deps python3 -m unittest discover -s src/lib_guard/test -p 'test*.py' -q
```
