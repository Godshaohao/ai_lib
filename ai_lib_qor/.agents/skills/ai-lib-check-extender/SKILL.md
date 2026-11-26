---
name: ai-lib-check-extender
description: >-
  用于 ai_lib_qor 维护与扩展检查规则插件（MANIFEST/FACTS/DIFF）、Corner 验收配置表（业务IP->Group->Corner）、
  检查结果的 HTML/Excel 报告展示定制以及 EDA 检查脚本模板（PT/Innovus/Tempus/Calibre 等 .csh/.tcl）。当用户要求
  新增检查项、接入公司已有 EDA 脚本、调整或导入 Corner 验收清单、按单库配置规则参数、或迭代修改检查后的在线/离线
  HTML 与 Excel 报告布局时使用；坚持最小改动与插件化扩展，严守 7 层单向 DAG。
---

# AI Lib Check & Script Extender

本 Skill 专注 **低侵入、可插拔地扩展 `ai_lib_qor` 的质量检查与 EDA 脚本生成能力**，配合 `ai-lib-steward` 使用。

核心理念：**优先通过配置与模板解决，其次外部插件模块，再次内置单文件插件，最后才考虑改核心层或 Parser。** 新增检查插件后，Web 页内看板、Overall 视图、离线 HTML、Excel、`check-pending` 与「单库配置」抽屉均会自动接入，**无需修改路由、前端页面或渲染器**。

---

## 一、最小侵入决策树（先定级，再动手）

| 需求类型 | 优先方案 | 改动面 | 零改动核查 |
| --- | --- | --- | --- |
| **Tier 0 · 纯配置/模板** | 修改 `work/corner_acceptance.json`、`path_sources.json`（`check_plugins` / `check_plugin_params`）或放置 `work/script_templates/<name>.csh.j2` | **0 行源码** | 直接生效，无需发版 |
| **Tier 1 · 项目/工艺专属规则** | 独立 Python 模块调用 `register_path_plugin(...)`，在 `path_sources.json` 的 `plugin_modules` 挂载 | **0 行核心代码** | 不污染主仓库 |
| **Tier 2 · 通用内置插件 / 工具模板** | 在 `src/ai_lib_qor/checks/plugins/<rule>.py` 新增单文件并在 `checks/path_plugins.py` 注册；或在 `src/ai_lib_qor/reporting/script_templates/<tool>.csh.j2` 新增模板 | **1~2 个文件 + 单测** | 不碰 `minimal_checks.py`、`routes_*`、`templates/*.html` |
| **Tier 3 · 新解析事实 / Schema 扩展** | 仅当现有 `FileFacts` 与 `ctx['target']` 均无法提供所需证据时，才扩展 `facts/_compat/` 或向后兼容新增可选字段 | 需同步走 `ai-lib-steward` 影响评估 | 严禁破坏历史记录 |

---

## 二、4 条架构红线（不可违背）

1. **严格 7 层单向 DAG（0 白名单）**：`versions(0) → sources(1) → facts(2) → checks(3) → application(4) → reporting(5) → workbench(6)`。
   - `checks/` 严禁导入 `application/`、`reporting/`、`workbench/`（可使用 `versions.store.validate`）。
   - `reporting/` 严禁导入 `workbench/`。
2. **严禁扫描 RAW 或读取二进制大文件**：
   - 检查插件只消费 `ctx['target']`（有效版本成员路径）、`ctx['baseline']`、`ctx['facts']`、`ctx['obtain']` 与 `ctx['plugin_params']`。
   - **绝不在 Python 插件中读取 `.db` / `.gds` / `.oas` 二进制内容**；清单级规则必须声明 `needs_facts=False, category='MANIFEST'`。
   - EDA 脚本生成器只消费 `PathDataQuery(work).get_check_context(...)`，绝不自扫目录。
3. **诚实覆盖度与不伪造 PASS**：
   - 仅基于文件名/清单的检查必须在 `coverage` 标明 `'MANIFEST'`（或 `'PARTIAL'`），并在 `detail` 写明边界（例如“不代表 `.db` 内部编译模型一致”）。
   - 无适用对象或未配置验收表时：自动全跑返回 `{'checks': []}`（记录为 `NOT_APPLICABLE`），已配置表但当前 IP 未映射时返回 `INCONCLUSIVE`（可配 `fail_on_unmapped_ip` 升级为 `FAIL`），**严禁静默返回 `PASS`**。
4. **保持多轨隔离**：插件和脚本生成器天然运行在单轨道 `(vendor, library, business_ip)` 上下文中，严禁在插件内部跨轨道读取其他 IP 的文件。

---

## 三、标准执行流程

### 流程 A：新增检查规则插件（MANIFEST / FACTS / DIFF）
详细接口与字段见 [references/plugin-contract.md](./references/plugin-contract.md)。
1. **判别类型**：
   - 仅看有效版本文件清单/命名/配对（如 `.lib/.db`、Corner 清单、GDS/CDL 存在性）→ 选模板 [templates/manifest_plugin.py.tmpl](./templates/manifest_plugin.py.tmpl)（`needs_facts=False, category='MANIFEST'`）。
   - 需要 `FileFacts` 结构内容（如 LEF/Liberty/Verilog/CDL 解析结果或跨版 Diff）→ 选模板 [templates/facts_plugin.py.tmpl](./templates/facts_plugin.py.tmpl)（`needs_facts=True, category='FACTS'|'DIFF'`）。
2. **参数外置**：规则阈值、白名单、必选清单、严格度一律从 `ctx.get('plugin_params', {}).get('<PLUGIN_ID>', {})` 读取，不写死工艺常量。
3. **结构化输出**：返回 `{'checks': [...]}`，每条必填 `check_id`、`scope_file_keys`、`result`（`PASS`/`FAIL`/`INCONCLUSIVE`）、`coverage`、`facts_refs`、`detail`，并推荐附带 `severity`（`ERROR`/`WARNING`/`INFO`）与 `findings` 列表。
4. **注册挂载**：
   - 内置规则：放入 `src/ai_lib_qor/checks/plugins/<name>.py`，在 `src/ai_lib_qor/checks/path_plugins.py` 注册到 `PATH_CHECK_PLUGINS` 与 `PATH_CHECK_PLUGIN_META`。
   - 外部规则：在外部模块顶层调用 `register_path_plugin(...)`，在 `path_sources.json` 添加 `plugin_modules`。
5. **编写单测**：基于 [templates/plugin_test.py.tmpl](./templates/plugin_test.py.tmpl) 覆盖 `PASS` / `FAIL` / `INCONCLUSIVE` / `CheckResult` Schema 校验。

### 流程 B：接入 / 维护 Corner 验收表（业务 IP → Group → Corner）
详细规范见 [references/corner-table-guide.md](./references/corner-table-guide.md)。
1. 当用户提供 Excel/CSV/Markdown/口述的 Corner 验收表时，先整理为 `schemas/corner_acceptance.schema.json` 极简格式（参考 `examples/corner_acceptance.example.json`，顶部保留 `_note` 语法备注）：
   - `groups`: 每组直接写必选 Corner 关键词数组，仅用 `+`（且）和 `|`（或）两个符号。
   - `ip_groups`: 直接映射 `业务IP（或单轨库名，支持 * 通配符） -> 分组名（或分组数组）`（只面向业务 IP，不使用 `@ip_type`）。
2. 默认输出到 `<work>/corner_acceptance.json`（或在 `path_sources.json` 配 `check_plugin_params.LIBERTY_CORNER_COVERAGE.table_file`）。
3. 必须运行 Schema 校验与针对现有库的只读演练，核对有无未映射 IP（`INCONCLUSIVE`）或关键词误命中。

### 流程 C：将用户已有 EDA 脚本适配为可复用 `.csh.j2` 模板
详细模板变量与覆写机制见 [references/eda-script-templates.md](./references/eda-script-templates.md)。
1. **获取用户原始脚本**（PT / Innovus / Tempus / Calibre / StarRC / RedHawk 等 `.csh` / `.tcl`）。
2. **最小化参数化替换（保留用户原有工具命令与公司环境习惯）**：
   - 顶部插入标准溯源头注释（`vendor` / `library` / `business_ip` / `revision` / `deliveries_used`）。
   - 把硬编码的 `.lef` / `.db` / `.lib` / `.v` / `.gds` / `.cdl` 路径替换为 `{% for item in db_files %}"{{ item.absolute_path }}"{% endfor %}` 等标准变量（基于模板 [templates/eda_script.csh.j2.tmpl](./templates/eda_script.csh.j2.tmpl)）。
   - 对用户仍需按环境调整的项（如 `TECH_LEF`、队列参数、工具版本）保留清晰 `# [TODO: 按环境确认]` 注释。
   - **注意 Jinja2 转义**：Tcl 中的 `{` / `}` 通常无需转义，但若出现连续 `{{` 或 `{%`，用 `{% raw %}...{% endraw %}` 包裹。
3. **落盘位置选择**：
   - 公司私有/项目定制脚本 → 直接放到 `<work>/script_templates/<name>.csh.j2`（**零代码改动**，自动被 `export-script` 与 `/api/v1/scripts/export` 发现或覆写内置模板）。
   - 通用内置模板 → 放入 `src/ai_lib_qor/reporting/script_templates/<name>.csh.j2`，并在 `src/ai_lib_qor/reporting/eda_scripts.py` 的 `BUILTIN_TEMPLATE_META` 补一行说明。

### 流程 D：检查结果的 HTML / Excel 报告联动与后续迭代修改
详细字段映射与定点修改范围见 [references/report-rendering-guide.md](./references/report-rendering-guide.md)。
1. **新增规则时默认零改渲染层**：只要插件规范填充 `checks[*]` 与 `findings[*]`（含 `view`/`path`/`object_type`/`object_name`/`diff_type`/`old_value`/`new_value`/`detail`），在线 HTML（`path_library.html`/`path_analysis.html`）、离线 HTML（`html_report.py`）和 Excel（`workbook_diff.py:unpack_plugin_findings`）均会自动展示。
2. **需要定制报告布局/列/样式时按管道隔离修改**：
   - 在线 HTML：`qor_views.py` + `path_library.html` / `path_analysis.html`（不碰 Excel）。
   - 离线 HTML：`html_report.py`（不碰在线模板和 Excel）。
   - Excel 报表：`path_workbook_model.py` / `workbook_diff.py` / `excel.py` / `overall_excel.py` / `excel_style.py`（不碰 HTML；改完后可通过 `cache-clean --apply` 清派生 `.xlsx` 缓存，免重跑检查直接按新模板重渲染）。
3. **结论口径单一真源**：严禁在 HTML 或 Excel 各自重算通过/失败状态，统一复用 `checks/path_plugins.py:evaluate_check_verdict`。

---

## 四、强制验证清单（每次扩展必跑）

1. **一键扩展健康检查**（AST 0 白名单 DAG + BOM + 插件元数据 + 模板编译 + HTML/Excel 渲染冒烟 + Schema 校验）：
   ```bash
   PYTHONPATH=src python3 .agents/skills/ai-lib-check-extender/scripts/verify_extension.py --work <work_dir>
   ```
   （不指定 `--work` 时校验源码、内置插件、内置模板与 HTML/Excel 冒烟；指定 `--work` 时额外校验工作区 `path_sources.json`、`ip_partition_*.json`、`corner_acceptance.json` 与 `script_templates/`。）
2. **针对性单元测试 + DAG 守护测试**：
   ```bash
   PYTHONPATH=src:tests python3 -m unittest tests.test_manifest_plugins_and_eda_scripts tests.test_html_check_reports tests.test_excel_reports tests.test_architecture_p0_p2.ArchitectureP0P2Tests.test_package_dependency_dag_invariants -v
   ```
3. **涉及公用代码时跑全量回归**：
   ```bash
   PYTHONPATH=src python3 -m unittest discover -s tests -p "test_*.py" -q
   ```
4. **真实数据边界声明**：单元测试与模板渲染通过不等于真实 PT/Innovus 工具环境执行验收通过，答复中必须明确区分。
