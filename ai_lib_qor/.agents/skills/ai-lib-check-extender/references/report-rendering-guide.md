# 检查结果 HTML 与 Excel 展示联动与定制指南

`ai_lib_qor` 将「检查执行与数据存储」和「4 条只读展示管道」完全解耦：

```text
log/check_*.json & log/overall_*.json（权威不可变 JSON）
  ├── 1. 在线 Web HTML  : reporting/qor_views.py -> workbench/templates/{path_library,path_analysis}.html
  ├── 2. 离线单文件 HTML : reporting/qor_views.py -> reporting/html_report.py
  ├── 3. Excel 报告     : reporting/check_renderer.py -> path_workbook_model.py + workbook_diff.py
  │                       -> excel.py / overall_excel.py / work_overview_excel.py + excel_style.py
  └── 4. EDA .csh 脚本  : reporting/eda_scripts.py -> script_templates/*.csh.j2
```

---

## 一、零代码自动适配原则（新增检查插件时优先遵守）

绝大多数新检查规则**不需要修改任何 HTML 或 Excel 代码**，只要插件按以下规范输出 `checks[*]` 与 `findings[*]`，在线 HTML、离线 HTML 与 Excel 会自动完整展示：

1. **必填摘要字段**：
   - `check_id`：规则 ID（作为表格第一列与筛选键）
   - `result`：`PASS` / `FAIL` / `INCONCLUSIVE`（全局统一由 `checks/path_plugins.py:evaluate_check_verdict` 汇总，**严禁在 HTML 或 Excel 里另写一套结论判别逻辑**）
   - `coverage`：`COMPLETE` / `PARTIAL` / `MANIFEST` / `UNKNOWN`
   - `detail`：单行可读中文结论（写清数量、关键缺失项样例及覆盖边界）
   - `scope_file_keys`：关联相对路径列表
2. **结构化明细 `findings[*]`（自动展开到 Excel 差异明细 Sheet）**：
   `reporting/workbook_diff.py:unpack_plugin_findings` 会自动读取每条 `finding` 并映射为 10 列 Excel 明细行：

   | `finding` 字段 | Excel 明细列 | 推荐写法示例（如缺失 Corner / 缺 `.db`） |
   | --- | --- | --- |
   | `view` | View | `'DB'` / `'LIBERTY'` |
   | `path` | 文件路径 | `'LIB/sram_tt_25c.lib'`（可为空串，默认回退 `scope_file_keys`） |
   | `object_type` | 对象类别 | `'LIB_DB_PAIR'` / `'LIBERTY_CORNER'` |
   | `object_name` | 对象名 | `'sram_ss_125c.lib'` / `'ss\|slow+125c'` |
   | `diff_type` | 差异类型 | `'MISSING_DB'` / `'ORPHAN_DB'` / `'MISSING_CORNER'` |
   | `old_value` | 期望/基线值 | `'至少 1 个匹配'` |
   | `new_value` | 实际/当前值 | `'实际命中 0 个'` |
   | `detail` | 说明 | 具体缺失或不一致原因 |

> 注意：`unpack_plugin_findings` 单规则最多展开 `MAX_PLUGIN_FINDINGS_PER_CHECK` 条明细，超出部分自动生成折叠提示行，避免超大列表撑爆 Excel。

---

## 二、需要单独定制 HTML 或 Excel 时的最小改动定位表

只有当用户明确要求**改版面、增删列、新增专属汇总区块/Sheet 或调整视觉样式**时，才按以下边界定点修改，做到**改一处不伤另一处**：

| 迭代目标 | 精确改动文件 | 不应触碰 |
| --- | --- | --- |
| **只改库页 TAB 2 页内直显看板** | `workbench/templates/path_library.html`（`#inline-check-dashboard`）、必要时 `reporting/qor_views.py` | 不碰 `excel*.py`、`minimal_checks.py` |
| **只改单版/多版完整在线分析页** | `workbench/templates/path_analysis.html`、必要时 `reporting/qor_views.py` | 不碰 `excel*.py`、`html_report.py` |
| **只改离线单文件 HTML 报告** | `reporting/html_report.py`（复用 `qor_views.py` 数据） | 不碰 `workbench/`、`excel*.py` |
| **只改单版本 Excel Sheet / 列 / 解包** | `reporting/path_workbook_model.py`、`reporting/workbook_diff.py`、`reporting/excel.py`、`reporting/excel_style.py` | 不碰 `qor_views.py`、`html_report.py`、`workbench/templates/` |
| **只改多版本汇总 Excel（Overall）** | `reporting/overall_excel.py`、`reporting/check_renderer.py` | 不碰 `html_report.py`、`minimal_checks.py` |
| **只改全工作区总览 Excel** | `reporting/work_overview_excel.py` | 不碰单库检查与 HTML |
| **HTML 与 Excel 同步新增公共统计指标** | 先在 `checks/`（如 `evaluate_check_verdict`）或 `reporting/qor_views.py` 与 `path_workbook_model.py` 保持同源计算口径 | 严禁把状态判定写死在 Jinja 模板或前端 JS 中 |

---

## 三、修改 Excel / HTML 后的缓存与验证要点

1. **Excel 派生缓存刷新（免重跑检查）**：
   修改 Excel 布局或配色后，已保存的 `log/check_*.json` 无需重跑；执行：
   ```bash
   PYTHONPATH=src python3 -m ai_lib_qor cache-clean --work <work_dir> --apply
   ```
   清理派生 `.xlsx` 缓存（权威 `.json` 历史完整保留），下次点击下载或运行 `minimal-render-excel` 即按新模板自动重生成。
2. **HTML 与 Excel 双通道回归验证**：
   - 在线/离线 HTML：`tests/test_html_check_reports.py`
   - Excel 报表：`tests/test_excel_reports.py`、`tests/test_pluggable_qor_views.py`
   - 一键扩展自检：`verify_extension.py` 内置 HTML + Excel 渲染冒烟测试。
