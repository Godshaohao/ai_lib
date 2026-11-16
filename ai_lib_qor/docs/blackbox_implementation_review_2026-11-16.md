# Blackbox v3.1 实现与旧版对照评估（2026-11-16）

## 结论

新工程目前具备 v3 的显式输入 MVP：登记交付和正式快照、解析部分 LEF / Liberty、构造有效版本、有限检查和报告、读取 v3 数据的本机工作台。**尚不是 blackbox v3.1 设计的完整实现，也未达到旧 `src_qor` 的工作台功能覆盖，更没有通过真实库生产验收。**

本审查把设计文件作为目标，不把文件名是否一一对应当作实现标准；相关功能嵌入其他文件时标记为部分实现。原 blackbox README 中“实际 .py 文件尚未创建”是设计文档生成时的历史说明，不代表现在没有可执行代码。

## 功能和脚本对照

| 领域与设计模块 | 旧版参考 | 新版实情 | 结论 |
|---|---|---|---|
| 工程配置：`config.py`、`project.yaml`、`ownership.yaml`、`delivery_rules.yaml`、`checks.yaml` | YAML registry、review 配置 | CLI 使用人工提供的 JSON，版本命令支持显式参数；尚无设计中的统一 YAML 配置、优先级和 profile 加载 | 部分；配置系统未实现 |
| 来源发现：`raw_scanner`、`file_classifier`、`delivery_builder` | `raw_discovery.py`、`ip_file_history.py` | `sources/delivery_builder.py` 可基于明确文件映射扫描、记录未解析文件；工作台不自动发现或登记 RAW、无旧版名单关联流程 | 部分；自动发现、分类及网页登记未迁移 |
| 正式来源：`formal_scanner`、`source_matcher`、`snapshot_builder` | `effective_file_tracker.py` | `snapshot_builder.py` 根据明确配置扫描文件链接和匹配已给交付；界面只能读已有快照；缺正式目录交互式盘点及 formal_nl 索引 | 部分 |
| 有效版本：`delivery_policy`、`slot_resolver`、`composer`、`index_projector`、`acceptance` | 原版 `file_status` / `current_library_set` 等与之并非同一语义 | 有独立实现、CLI 和自动化测试，支持增量保留、显式删除、采纳、回滚、撤销及索引重建；网页只读显示 | 核心部分已实现；真实库、多进程/崩溃恢复完整验收未完成 |
| 解析事实：`facts_assembler`、LEF/Liberty Adapter | `macro_index_parsers`、`parsers` | `facts/parsers.py` 和 `_compat` 支持 LEF Macro SIZE/信号 Pin、Liberty Cell/信号 Pin；旧版 Verilog、CDL 等解析与更完整的 LEF 几何、PG、PVT 等未迁入对应 v3 能力 | 部分；不宣称所有旧数据都能表示 |
| 原始文件内容比对：`content_compare` 插件 | `content_compare.py` | 没有独立原文件内容比较插件；现有 assembler 有 LEF 对象变化时记 CHANGED，否则 UNKNOWN，不能当作通用文件字节比对 | 未实现设计中的完整内容比对 |
| LEF Macro 差异 | `lef_review.py` | `lef_macro_diff.py` 对 Macro、SIZE、Pin 增删和方向作有限比较；几何等旧版详细证据未完整迁入 | 部分 |
| LEF–Liberty 接口 | `lef_liberty_check.py` | `lef_liberty_pin_match.py` 支持显式指定的 LEF/Liberty 信号 Pin 名称、方向；未支持旧版全部 PG/自动配对及范围 | 部分 |
| 选择、计划和插件执行：`selectors`、`plan`、`registry`、`runner` | `applicable_review.py`、`review_runner.py`、`batch_lef_review.py` | `selectors.py` 提供显式覆盖状态下的最近/次近选择；`__main__.py` 直接读取计划并由 assembler 显式调用两个检查。无通用插件注册/执行、profile、自动计划、批量或一键适用检查 | 部分；插件平台和自动编排未实现 |
| 贡献合并：`checks/assembler` | 旧 ReviewResult 汇总 | 能将当前两个硬编码检查拼为 v3 CheckResult；不是 blackbox 定义的通用贡献协议，未证明任意新增插件无需修改核心 | 部分 |
| 证据：`checks/evidence` | 旧版保存检查证据和关联哈希 | 输入会做 Schema、引用与部分覆盖校验，但没有独立证据 Gate 或可重新证明 FileFacts 未被篡改的链路；下方有实测反例 | 未完成；上线阻塞 |
| 发布：`storage/paths`、`publisher` | 旧版 run、latest、任务目录 | `versions/store.py` 具备原子文件写入、版本锁及重放索引；尚无整个系统统一 Publisher、所有跨记录校验和跨文件事务/故障恢复协议 | 部分 |
| 应用层：`application/update/check/accept/report`、`cli.py` | `review_runner.py`、多个 CLI | `__main__.py` 和 `versions/__main__.py` 覆盖显式操作；尚无设计中的独立统一应用服务与自动端到端组装 | 部分，功能散在现有入口 |
| Excel / HTML：`reporting/view/excel/html` | `export_review_excel.py`、旧 Review HTML | 可按单次 CheckResult 生成静态 HTML 和 13 张表的 Excel；用户需要的单 IP 汇总、所有版本自动报告及旧 Excel 字段/规则等价仍未验收 | 部分；不是完整旧版报告迁移 |
| 工作台 | `workbench.py`、模板、前端 | 可浏览现有 v3 IP、源库交付、有效版本、正式快照及事件；可运行已备计划并下载；只读查看不等于创建/采纳 | 部分；见下方交互缺口 |

## 与旧工作台的主要差距

1. 旧版能从 RAW 查找候选并登记、配置业务 IP 和正式文件清单；新版未做网页发现登记，`--work` 只读取已有 v3 数据。
2. 旧版可刷新 RAW 盘点、文件版本投影、比较所选文件与一键适用检查；新版文件矩阵只读取提供的交付，未按 IP 过滤，也没有从界面一键形成可信检查计划或自动配对。
3. 旧版可扫描浏览正式 NL 及处理多阶段；新版只展示人工选择的已有快照，不支持从页面创建、刷新正式快照或自动记录 formal index。
4. 旧版有后台任务队列、并发约束、进度、中断恢复和每 IP 运行隔离；新版同步请求、只记录简单状态；计划和运行历史目前没有强制与所选 IP 绑定。
5. 旧版有每 IP 的历史和最近完整 Excel 等机制；新版每个 Run 生成一个 HTML/Excel，没有等价的完整报告指针与跨版本自动报告。两类 Excel 的真实库验收未完成。
6. 新版有独立的版本和采纳模型，网页能读取展示；但页面不提供生成、采纳或回滚的交互，相关能力在版本 CLI。

## 本次测试

- 执行 `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="src:<bundled-python-site-packages>" python3 -m unittest discover -s tests -q`：**47 项通过**。
- 测试覆盖示例：V07/V08 合成交付、增量保留、版本与采纳、指定事实的 LEF/Liberty 检查、HTML/Excel 构造、工作台路由与下载。多数使用临时合成数据；**未在真实生产 RAW 库执行端到端验收**。
- 反例 1：对已有 CheckResult 将 `summary.failed_checks` 改成 999，与明细矛盾；Schema 与 `reporting.view.build_report` 均接受。
- 反例 2：重复添加相同 `file_changes` 文件行；Schema 与 `build_report` 均接受。
- 反例 3：将质量结果改为 `PASS`，同时将覆盖改为 `UNKNOWN`；Schema 与 `build_report` 均接受。
- 反例 4：保持 `facts_id` 不变，手工将 LEF 事实的 SIZE 改为 `[9999,9999]`，检查仍生成结果，LEF–Liberty Pin 检查仍为 `PASS / COMPLETE`。该 PASS 只针对相关 Pin 检查，并不是对 SIZE 的 PASS；反例说明事实内容没有被认证，并非证明每个结果都错误。

这些反例针对报告消费与现有信任边界；并不意味着正常检查路径没有任何校验，也不否定现有 47 项测试结果。

## 设计验收场景状态

| 设计场景 | 本次判断 |
|---|---|
| 配置优先级、来源只读、完整路径隔离 | 未完成：无统一 config；路径边界尚需端到端验收 |
| V07/V08 增量保留 | 合成测试通过；真实库未验收 |
| 交付预检查、最近/次近 | 选择器有合成测试；工作台尚未完整使用其覆盖状态 |
| PASS / FAIL / NOT_RUN / INCONCLUSIVE | 现有检查有部分覆盖和边界测试；全范围、插件运行及报告再校验未完成 |
| 多插件贡献、冲突和 Gate | 两个固定算法已接入；通用贡献/Gate 未实现，报告反例存在 |
| 新插件注册无需改核心 | 未实现；当前显式调用 |
| 检查与采纳独立 | 版本合成测试通过；网页只读 |
| 不可覆盖、并发、中断恢复 | 有不可变文件写入、锁和索引重建；全流程幂等/故障/并发验收不足 |
| 同 Run HTML/Excel 一致 | 基础测试通过；两个业务报告及旧版逐项等价未验收 |
| Schema 与跨记录全校验 | 部分校验；上述三个反例未被报告入口拒绝 |

## 推荐优先级

1. **先保障可信结果**：明确证据承载方式，校验事实身份/字节与引用；报告入口拒绝重复文件、错误汇总和 PASS/覆盖矛盾；补对应回归测试。
2. **贯通真实用户流程**：按现有 v3 契约迁移 RAW 发现登记、IP 归属、文件矩阵、明确的计划生成、结果按 IP/版本归档；使用不修改来源的真实 RAW 副本做端到端验证。
3. **补旧版能力**：通用文件内容比对、正式目录浏览、适用检查与后台任务、旧报告差异逐项补齐。
4. **再扩展 blackbox 插件**：在贡献和证据契约明确后实现配置、plan/registry/runner 和 Publisher；避免把目录骨架误当成已支持任意插件。

## 主要依据

- 设计入口：`design/blackbox_v3_1/README.md` 和 `tests/验收场景.md`。
- 新版入口：`src/ai_lib_qor/__main__.py`、`versions/__main__.py`、`workbench/`、`checks/`、`reporting/`。
- 旧版：`../src_qor/README.md` 与 `lib_guard/`。
- 现有说明：`PIPELINE_README.md`、`WORKBENCH_README.md`、`VERSIONS_README.md`。
