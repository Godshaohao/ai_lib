# IP 多版本文件矩阵 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在现有 `src_qor` 工作台中完成 R1 文件最新/次新与 Formal 对账、R2 两次交付真实内容比较、R3 既有检查器联动和 Web/Excel 一致性。

**Architecture:** 复用 `file_version_projection.py` 作为唯一事实投影，增加确定性版本顺序与 coverage-aware 派生字段；新增的内容读取仅封装在一个小型标准库比较模块中。Workbench 只读快照，显式刷新/比较/质检写不可变快照和历史 Review；Web 与 Excel 都读取同一 Projection。

**Tech Stack:** Python 3.11+、标准库 `pathlib/gzip`、现有 Flask/Jinja、现有 `lef_review`/`lef_liberty_check`/`macro_index`、现有 XlsxWriter 导出器、unittest、Node `--check`。

## Global Constraints

- 只修改 `src_qor` 及当前项目 README/CI/测试；保留用户已有未提交改动。
- 不新增数据库、常驻扫描、Release/Effective 审批、自动 Formal 替换、模糊配对或 Hash UI。
- RAW/Formal 只读；快照历史不可变，latest 指针原子更新；失败结果不得替换上一次完整 Excel。
- `file_version_projection.v1` 必须可读；v2 只能向后兼容扩展。
- `COMPLETE` 只表示执行完毕，不等于质量 PASS。
- 测试使用项目 bundled Python 依赖路径；不得修改依赖目录。

---

### Task 1: 统一版本顺序、身份和 latest/previous 派生

**Files:**
- Modify: `src_qor/lib_guard/file_version_projection.py`
- Modify: `src_qor/lib_guard/file_status.py`
- Modify: `src_qor/lib_guard/effective_file_tracker.py`（仅规范化身份契约）
- Test: `src_qor/test/test_file_version_projection.py`
- Test: `src_qor/test/test_file_status.py`

**Interfaces:**
- `build_projection(...) -> dict` 保持现有参数，支持 `delivery_order` 和 v1 输入兼容。
- 新增纯函数 `resolve_version_order(versions) -> dict`、`rank_occurrences(occurrences, order, inventories) -> tuple[dict, dict]`，供 Workbench/Excel 只读结果。

- [ ] **Step 1: Write failing tests**：覆盖显式顺序五版本、日期顺序、同日重复、无日期、部分显式、重复显式、大小写不同路径、Corner 歧义、PARTIAL 最新版本和无 Formal RAW-only。
- [ ] **Step 2: Run red tests**：`PYTHONPATH=src_qor /usr/bin/python3 -m unittest src_qor.test.test_file_version_projection src_qor.test.test_file_status -v`；预期新行为失败而不是导入错误。
- [ ] **Step 3: Implement minimal deterministic helpers**：显式顺序完整唯一时 `EXPLICIT`；所有日期唯一时 `DATE_HINT`；其他情况 `UNKNOWN`。同一 `file_key` 只跨不同 version_id 排名；coverage 不完整时返回 `LATEST_OBSERVED` 或 `UNKNOWN_COVERAGE`，绝不确认删除。
- [ ] **Step 4: Run focused tests**：同一命令预期 PASS。
- [ ] **Step 5: Run legacy projection tests**：`PYTHONPATH=src_qor /usr/bin/python3 -m unittest src_qor.test.test_file_version_projection src_qor.test.test_workbench -q`；预期现有 v1 断言保持通过。

### Task 2: Formal 对账和 RAW-only 刷新

**Files:**
- Modify: `src_qor/lib_guard/file_version_projection.py`
- Modify: `src_qor/lib_guard/file_status.py`
- Modify: `src_qor/lib_guard/workbench.py`
- Modify: `src_qor/lib_guard/effective_file_tracker.py`
- Test: `src_qor/test/test_workbench.py`
- Test: `src_qor/test/test_file_version_projection.py`

**Interfaces:**
- Formal 没有快照时 `build_projection(..., formal_files=None)` 仍返回完整 RAW 文件行，Formal 为 `NOT_AVAILABLE`。
- 多阶段无法确定时只将 Formal 列置为 `FORMAL_CONTEXT_REQUIRED`，不阻断 RAW 排名。

- [ ] **Step 1: Add failing Web tests**：没有 Formal 也能刷新/展示；Formal V01 与 RAW latest V05 同行独立展示；多阶段不选最高 NL；缺失源、未登记源和重复正式链接显示准确状态。
- [ ] **Step 2: Run red tests**：`PYTHONPATH=src_qor /usr/bin/python3 -m unittest src_qor.test.test_workbench -k formal -v`。
- [ ] **Step 3: Refactor refresh path**：RAW-only 走同一 `publish_projection`，Formal 对账只填 `formal_usage`；修复 `_view_relative_key` 与 `_identity` 大小写契约；保留旧状态快照和原子 rollback。
- [ ] **Step 4: Run focused Web tests**：预期 PASS，并验证 GET 不触发扫描。

### Task 3: 按需真实内容比较

**Files:**
- Create: `src_qor/lib_guard/content_compare.py`
- Modify: `src_qor/lib_guard/file_version_projection.py`
- Modify: `src_qor/lib_guard/review_runner.py`
- Test: `src_qor/test/test_content_compare.py`
- Test: `src_qor/test/test_file_version_projection.py`

**Interfaces:**
- `compare_files(base_path, target_path, *, chunk_size=1024*1024) -> dict` 返回 `status`、`comparison_mode`、`bytes_read`、`stat_before`、`stat_after`、`reason`。
- `compare_projection_files(projection, base_version, target_version, selected_keys=None) -> dict` 只更新唯一配对行，保留 `NOT_COMPARED`。

- [ ] **Step 1: Write failing tests**：普通字节相同/不同、缺失、stat 变化、gzip header 时间不同但解压内容相同、坏 gzip；状态矩阵覆盖 NEWLY_PROVIDED、NOT_PROVIDED_IN_TARGET、NOT_PROVIDED_BOTH、UNKNOWN_COVERAGE、AMBIGUOUS。
- [ ] **Step 2: Run red tests**：`PYTHONPATH=src_qor /usr/bin/python3 -m unittest src_qor.test.test_content_compare -v`。
- [ ] **Step 3: Implement stream comparator**：普通文件按块提前退出；`.gz` 以解压文本比较并记录模式；任何不确定性返回 `UNVERIFIED`/`FAILED`，不使用 Hash 作为 UI 结论。
- [ ] **Step 4: Bind explicit comparison route**：Workbench 只在用户选择后调用；LEF 内容不同或用户明确下钻时调用现有 `lef_review.analyze`，其他 View 不伪造专业语义。
- [ ] **Step 5: Run content and regression tests**：focused tests plus `test_review_runner` matrix tests，预期 PASS。

### Task 4: R3 检查器与批量 LEF 证据完整性

**Files:**
- Modify: `src_qor/lib_guard/review_runner.py`
- Modify: `src_qor/lib_guard/batch_lef_review.py`
- Modify: `src_qor/lib_guard/workbench.py`
- Test: `src_qor/test/test_review_runner.py`
- Test: `src_qor/test/test_batch_lef_review.py`

**Interfaces:**
- 批量每个 pair 的 evidence ref 必须含 `file_key`/`pair_id`；`_lef_rows(review)` 逐证据展开，不跨 pair 合并。
- LEF–Liberty 仍要求唯一 LEF 证据和明确 Corner/文件绑定；批量 LEF 与接口检查拒绝混跑。

- [ ] **Step 1: Add failing tests**：10 对 1 失败仍有 9 对 evidence；`08-LEF宏` 每对目标文件都有 Macro 行；第二个 Check 不覆盖旧 Review；未知 Corner/不同 Liberty 明确拒绝混绑。
- [ ] **Step 2: Run red tests**：`PYTHONPATH=src_qor /usr/bin/python3 -m unittest src_qor.test.test_batch_lef_review src_qor.test.test_review_runner -v`。
- [ ] **Step 3: Implement scoped evidence aggregation**：以 `file_key/pair_id` 作为行级作用域，独立保留失败状态；确保 COMPLETE/quality status 分离；复用当前最多 50 组、两 worker/8 队列约束。
- [ ] **Step 4: Run focused tests**：预期 PASS。

### Task 5: Web 主视图、历史 Review 和可访问交互

**Files:**
- Modify: `src_qor/lib_guard/templates/workbench.html`
- Modify: `src_qor/lib_guard/static/workbench.js`
- Modify: `src_qor/lib_guard/workbench.py`
- Test: `src_qor/test/test_workbench.py`

**Interfaces:**
- Web 排名只显示 Projection 的 `latest`/`previous`；JS 只做搜索、View/状态过滤、选择和详情展开。
- 历史 Review 通过 review_id 只读加载，历史页禁用新检查。

- [ ] **Step 1: Add failing HTML/route tests**：打开即有文件矩阵；显示 latest/previous/formal/order basis/coverage；过滤“无法确定/已有变化”；历史 Review 不影响当前快照且不能提交检查。
- [ ] **Step 2: Run red tests**：`PYTHONPATH=src_qor /usr/bin/python3 -m unittest src_qor.test.test_workbench -v`。
- [ ] **Step 3: Implement minimal template/JS changes**：主表固定关键列，长路径/occurrences 放详情，空态给出下一动作，按钮有 disabled/loading/aria 状态，不增加第二页面。
- [ ] **Step 4: Run route tests and `node --check`**：预期 PASS。

### Task 6: Excel 同源矩阵与 README/CI

**Files:**
- Modify: `src_qor/lib_guard/review_runner.py`
- Modify: `src_qor/lib_guard/export_review_excel.py`
- Modify: `src_qor/README.md`
- Modify: `.github/workflows/ci.yml`
- Test: `src_qor/test/test_review_runner.py`
- Test: `src_qor/test/test_excel_report_fixtures.py`

**Interfaces:**
- `build_workbook_model()` 读取 Projection 派生字段，不在 exporter 里排序/推断。
- `文件版本矩阵` 增加 latest/previous/order/coverage/formal/comparison/scope/evidence；无质检时仍可导出轻量清单。

- [ ] **Step 1: Add failing workbook tests**：Web/Excel 同一 `file_key/latest/previous/formal/comparison`；批量 Macro 明细逐 pair；无检查仍能导出；部分结果不替换 latest.xlsx。
- [ ] **Step 2: Run red tests**：`PYTHONPATH=src_qor /usr/bin/python3 -m unittest src_qor.test.test_review_runner src_qor.test.test_excel_report_fixtures -v`。
- [ ] **Step 3: Implement render-only changes**：保留既有 Sheet，增加必需列、冻结/筛选表头和证据相对路径，不添加重复门户或业务排序逻辑。
- [ ] **Step 4: Update docs/CI**：README 写入无 Formal 路径、Formal 路径、只查单文件路径和限制；CI 加入 projection/content/workbench/JS 命令但不破坏旧 `src/lib_guard/test`。
- [ ] **Step 5: Run workbook tests**：使用工作区 bundled site-packages 与 `/usr/bin/python3`，预期 PASS。

### Task 7: 真实目录 fixture 与整体验收

**Files:**
- Create: `src_qor/test/fixtures/file_matrix/fixture_a/...`
- Create: `src_qor/test/fixtures/file_matrix/fixture_b/...`
- Create: `src_qor/test/test_file_matrix_acceptance.py`
- Modify: `src_qor/test/test_file_version_projection.py`（只补必要契约断言）

- [ ] **Step 1: Build Fixture A**：五版本、PARTIAL、同内容重复、多 LEF、多 Corner、大小写不同、改名文件、无 Formal。
- [ ] **Step 2: Build Fixture B**：Formal 指向 V01/V03、新增 V05、断链、多个 `lib_NL*` 阶段。
- [ ] **Step 3: Add end-to-end tests**：覆盖需求文档列出的 26 场景中至少 20 个，并分别断言 Projection/Web/Excel/证据边界。
- [ ] **Step 4: Run complete verification**：
  `PYTHONPATH=/home/polaris/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/lib/python3.12/site-packages:src_qor /usr/bin/python3 -m unittest discover -s src_qor/test -p 'test*.py' -v`
  `PYTHONPYCACHEPREFIX=/tmp/ai_lib_pycache python3 -m compileall -q src_qor/lib_guard`
  `node --check src_qor/lib_guard/static/workbench.js`
  `PYTHONPATH=src_qor /usr/bin/python3 -m lib_guard.workbench --help`
- [ ] **Step 5: Audit requirement coverage**：逐项记录实现/未实现/环境限制，禁止用旧测试数字替代本次结果。

---

## Implementation Ponytail Review

- Keep: existing projection, status scanner, review runner, batch evidence, workbook exporter and Workbench routes.
- Delete/avoid: database, generic File Facts store, background daemon, full parser framework, automatic fuzzy matching, Hash UI, release/effective workflow.
- Simplify: one explicit `content_compare.py`; one version-order helper; all views consume the same projection.
- Boundary violations to watch: exporter must not rank versions; JS must not calculate business status; formal snapshot must not be required for RAW-only; `COMPLETE` must not imply quality PASS.
- Validation: bundled dependency test command plus compile/JS/help commands and real-directory fixtures.
