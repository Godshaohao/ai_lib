Status: current

# 跨视图语义检查实施与验收记录

范围：Semantic IR MVP，只读 / advisory，非签核。基线 GitHub main 与本地 HEAD：
`1b7a0fb439b03a96995fafb70ba138eec45c22de`。独立分支：`semantic-ir-mvp-20261014`。
Python 3.14.4；基线全量 835 tests / 13.393 s / OK。
基线日志：`/tmp/ai_lib_semantic_baseline.log`。

目标用户：核查 IP 多视图接口和有效组合变化的库管理者。
判断：来源是否准确，接口是否一致，以及证据是否足够作出结论。
输入：既有 Effective Manifest、Catalog/runtime 和 Scan ParserResult；可选确认的实体映射。
输出：独立目录中的可重建 JSON、中文 Markdown 摘要；不作为发布门禁输入。
禁止：写 RAW/current/catalog/release/review gate，隐式补扫，全库 hash，新主页面或服务。

## Task 0 技术调查

- 复用 `validate_effective_manifest`、`load_catalog_view`、`load_parser_results` 和 atomic 写操作。
- 真实 ASAP7 scan 中 parser key 为 `parser_results/lef/<id>.json`；来源必须核对
  envelope 的 file/abs_path、inventory 和 scan_meta，不能拿 key 或 basename 当来源。
- Effective digest 绑定组成、顺序和快照，不是单文件 hash；文件映射另需来源与 inventory 核对。
- Legacy parser 不声明完整端口覆盖，Parser PASS 不授予 port-set PASS。
- LEF geometry counts-only 不授予精确 shape 结论；缺明确单位的 Size 保留原始值，不输出伪造 um。
- Liberty 时序表、复杂 bus，Verilog 参数 elaboration/实例，SPEF RC 不是本轮目标。
- 为受控专业证据预留显式覆盖声明，但旧 scan 不自动升级；因此真实库可能大量 NOT_CHECKED。
  触发此边界后停止扩张到 Parser 重写或 UI 接入，提交缺口与证据供下一阶段决策。

## 阶段记录

- [x] Task 0 基线与证据调查。
- [x] Task 1 契约及最小测试。
- [x] Task 2 三视图适配。
- [x] Task 3 身份绑定与端口规范化。
- [x] Task 4 一致性检查。
- [x] Task 5 Effective 来源与属性 Delta。
- [x] Task 6 只读诊断、真实试验和全量回归。
- Task 7 HTML 接入后置，本轮不改主页面。

## 执行结果（2026-10-14）

- 专项：49 tests / 0.272 s / OK；`/tmp/ai_lib_semantic_specialized.log`。
- 重点旧回归：206 tests / 3.016 s / OK；`/tmp/ai_lib_semantic_focused.log`。
- 全量：884 tests / 13.691 s / OK；`/tmp/ai_lib_semantic_full.log`。
- compileall、git diff --check 通过；release/window/scan/web/short_cli 相对基线无差异。
- 九个核心模块 621 行；无新依赖、短命令、默认 Web 动作或 Release Gate 修改。
- 第一轮全量真实失败：文档白名单和 Status header 两项。没有削弱测试，将验收记录移入既有
  `docs/superpowers/plans/` 并补 Status header 后通过。
- 独立审查提出 8 条来源/覆盖/输出隔离问题；逐条先补反例（8 FAIL + 1 ERROR），再修复为通过。
  补充检查：输出快照 symlink 重定向拒绝、同代证据失败缓存只加载一次、逻辑源路径与真实目标分开。
- 第二轮复审补 6 个红反例：内部受保护目录重定向、任务状态/版本矛盾、几何实际字段缺失、
  文件/对象覆盖矛盾、null 字段和任务平方级查询。修复后 49 项专项通过，未改变默认业务。
- 最终独立复核：原 8 项和第二轮遗留均关闭，独立重跑 8 个定向用例通过，并模拟正常输出及
  输入碰撞拒绝。只读 advisory MVP 规格/质量复审通过；不代表真实库完整接口或签核验收通过。

### TDD 原始日志

`/tmp/ai_lib_semantic_task1_red.log` 至 `task6_red.log` 保存各阶段缺失功能失败；对应 green 日志
保存实现后结果。额外红测试包括 `review_red.log`、`index_red.log`、`symlink_red.log`、
`port_identity_red.log`、`alignment_red.log`、`cache_red.log`（共同前缀 `ai_lib_semantic_`）。
Task 4 首轮发现 Snapshot 共享输入对象使位序变化被隐藏，改为独立复制后 T14 检出 CHANGED。

### 真实数据与反例

| 数据 | 输入来源与结论 | 时间 / 不变性 |
| --- | --- | --- |
| 小型真实格式 FULL+FIX | 现有 ScanRunner 实际解析 LEF/LIB/RTL，最终 LEF 来源为 FIX；宽 1000→1100 为 CHANGED；缺 RESET 因旧 parser 未证明覆盖为 NOT_CHECKED，不伪造 PASS | 诊断约 0.022 s；RAW、catalog/runtime/current/release 文件 SHA 校验无变化 |
| 已有 ASAP7 | 当前 205 文件，28 项 parser evidence 可精确定位、177 项缺提取结果；891 个 LEF 对象缺对应语义 view，0 PASS / 0 FAIL / 891 REVIEW_REQUIRED / 2851 NOT_CHECKED / 891 NOT_APPLICABLE | 约 1.07 s；受保护 catalog/runtime/current 校验无变化；默认 RAW 内容读与 hash 均为 0 |
| 受控合成接口反例 | 明确完整覆盖的合成 ParserResult fixture 中删除 CLK，SIGNAL_PORT_SET = FAIL / PORT_SET_MISMATCH；方向因集合未对齐为 NOT_CHECKED，不重复误报方向矛盾 | 独立快照包含三侧 parser refs 与 source_version；不是生产 parser 的完整覆盖承诺 |

真实文件产物在 `work/semantic_ir_validation_20261014/`，不提交测试数据到仓库。
各场景入口：`real_parser/review/summary.json`、`real_parser/cli_review/summary.json`、
`asap7/review/summary.json`、`controlled_failure/review/summary.json`。
`summary.json` 中 artifacts 指向同 generation 的完整 check_results、来源索引、绑定及中文摘要。
`real_parser/audit.json` 与 `asap7/audit.json` 保存执行时间和保护文件 SHA。

## 必测矩阵对应

| 项目 | 测试/证据 |
| --- | --- |
| T01–T06 | binding unique_exact / mismatched_names / duplicate_and_multicorner；adapter corner_not_guessed |
| T07–T11 | complete_signal_ports、real_missing_port_fail、direction_contradiction、incomplete_and_ambiguous、pg_separate |
| T12–T14 | bus_context_no_guess、orientation_separate；width 缺 range 或与 range 矛盾不能作为标量 |
| T15–T17 | geometry_and_units、incomplete_geometry_unknown、size_delta_evidence_tolerance、area_not_cross_compared |
| T18–T20 | final_full_fix_selection_and_delta、order_and_tombstones |
| T21–T24 | legacy_and_no_cross_version_fallback、stale_source_and_snapshot、corrupt_manifest、mixed_scan_generation |
| T25–T26 | failed_empty_and_binary_are_not_semantic_success；缺 pins/ports 不升级成已验证空集合 |
| T27–T30 | CLI missing_base、read_only_repeatability_and_multicorner、no_raw_reads_or_walk_or_hash、index_built_once |

## 判断与保留限制

**底层规则与只读诊断可运行；真实业务全视图完整接口验收尚未通过。** 已触发原计划覆盖熔断：
旧 parser 缺完整 Port 能力声明，真实 ASAP7 大量 NOT_CHECKED。停止 Parser 重写、UI 和门禁扩张。

- 宏键是 library + exact/确认 canonical name + 明确 variant；effective_id、绝对路径不进入 ID。
  多 corner 仅在显式确认、互不重复时合法；未知角标混入多个候选会歧义。不存在模糊匹配。
- 显式确认 alias 可只适用于新侧；旧侧不强迫存在新名字。拼写错、无命中新侧的映射拒绝执行。
- PG 与信号分开，Verilog 不要求出现 PG。declared orientation 与 bit-set 变化分别记录。
- 来源按最终 effective_files，核对 scan_id、snapshot、inventory、当前 parser task 和逻辑 file/abs_path。
  外部 resolved source 默认 NOT_CHECKED；旧格式缺 generation/task 证据不能借同名文件回退。
- SIZE 使用明确单位和 1e-6 um 绝对容差；LIB area 不与 LEF size 比较。
- 属性 Delta 缺旧侧/覆盖/单位时 UNKNOWN；没有实现凭不完整对象列表宣布 Macro ADDED/REMOVED。
- 新鲜度只核对 metadata；同大小且 mtime 被恢复的内容变化无法检测，明确 content_verified=false。
- Liberty 复杂 bus/嵌套完整性、Verilog 参数 elaboration、完整 LEF shapes、DB/GDS 内部语义仍不支持。
- 下一阶段专业 Adapter 的最小边界是产生来源、快照、单位、完整端口/bit/方向及受验证覆盖声明；
  只替换该类文件事实的生产者，不改变 Effective 选择、Binding、Gate 或默认扫描策略。本轮未实现工具接入。
- 当前分支未推送、未合并 main、未接受有效版、未执行真实发布。

## 正式发布库管理验收（2026-10-15）

正式发布库是已交付结果的只读管理边界，不是新的 RAW 候选库，也不是新的 Semantic
事实源。验收使用现有 `release_manifest.json`、发布目录链接、`current/latest` 指针和现有
Catalog 关联信息；不扫描正式目录内容，不把目录重新加入 `scan/cmp/intake`。

本轮复用的真实工作区数据：

| 数据 | 结果 |
| --- | --- |
| `work/partial_release_ui_20261009/release_area` | `lib_NL2.1.0` 包含 A/B 两库，当前指针有效；交付状态 `PARTIAL_APPLIED`，2 个同名冲突被跳过，已交付链接可核对，结论为部分发布、需复核 |
| `work/multi_release_ui_20261008/published` | `lib_NL2.1.0` 包含 A/B 两库，当前指针有效；状态 `APPLIED`，无跳过，2 个交付文件链接核对通过 |
| `work/link_acceptance_20261008_140215816855/release_area` | 存在无 manifest 的 `R2` 当前指针，按未登记交付报告；不伪造为正式发布库 |

正式发布核对的最小判断是：

1. 清单能被读取，库 ID、版本、发布名和来源清单路径可追溯。
2. `current/latest` 指针确实指向发布阶段。
3. 发布 manifest 中的每个交付文件都能按目标路径核对链接目标。
4. 同名冲突的跳过数量和部分发布状态必须保留，不能只看已创建链接数量。
5. 没有 manifest 的旧目录只能归入“未登记交付”，不能反推库、版本或当前有效版。

可复跑入口仍为：

```bash
PYTHONPATH=src python3 work/semantic_existing_acceptance_20261014/accept_existing.py
```

正式发布细节位于 `work/semantic_existing_acceptance_20261014/formal/*/acceptance.json`。
本轮正式发布检查与 Semantic 检查合计 61 条通过；其中 `formal_partial` 仍是业务上的
`PARTIAL_REVIEW_REQUIRED`，不是可直接作为完整正式交付的 PASS。正式目录的交付状态、链接
状态、版本来源和 Semantic 语义结果仍需在 UI 中分区显示，不能合并成一个“总体 PASS”。

## 现有数据独立验收（2026-10-14）

**结论：只读诊断工程约束通过，真实库语义业务验收未通过。** 本轮没有重新生成库、补扫、
补充完整覆盖声明或修复既有扫描事实。ASAP7 显式选择 `20260624_asap7` → `20260627_asap7`，
使用已有清单；旧版 UCIe、A、B 直接读取现有有效组合。小型 FULL+FIX 是上一轮生成且实际解析过的
演练数据，本轮只重用，不能算生产库完整验证。

验收入口：`work/semantic_existing_acceptance_20261014/acceptance.md`。
机器记录：同目录 `acceptance.json`；每场景提供 `file_evidence.csv` 和同代 JSON/Markdown 快照。
复跑命令（在 repo 根目录执行）：

```bash
PYTHONPATH=src python3 work/semantic_existing_acceptance_20261014/accept_existing.py
```

| 检查场景 | 结果 | 判断 |
| --- | --- | --- |
| ASAP7 两个已有版本 | 新侧 205 文件、28 份可定位结果（27 LEF + 1 SDC）；177 份缺结果。112 Liberty、36 Verilog 文件没有对应提取结果 | 来源核对通过；跨视图接口不能验收 |
| ASAP7 无基准 / 自身对比 | 均没有接口 PASS，属性变化均 UNKNOWN | 不把缺证据误报成一致；没有自动选择基准 |
| 已有 FULL+FIX 演练 | 最终 LEF 来自 FIX，LIB/RTL 来自 FULL；宽 1000→1100 检出 CHANGED | 覆盖来源与尺寸变化通过；完整接口仍未验证 |
| 已有 FULL+FIX 的 RESET | LEF 仅提取 CLK；LIB/RTL 提取 CLK、RESET；完整覆盖未证明 | 差异可追溯，但不能据此冒充正式接口 FAIL 或 PASS |
| UCIe / A / B 旧组合 | 身份 MISSING、没有语义事实、没有 PASS | 不回退借用其他版本；未改写旧组合 |
| 输出隔离与重复诊断 | RAW/scan 输出被拒绝，七个场景各重跑一次完全相同 | 58 条工程验收检查通过 |

### 新发现的实质失败：LEF 属性定义作用域

ASAP7 当前已有 `LefParser 2.1` 证据把 `PROPERTYDEFINITIONS` 内的
`MACRO width INTEGER ;` 当成真正实体。代表源文件 `fakeram7_64x21.lef` 第 5 行是属性定义，
第 9 行才是 `MACRO fakeram7_64x21`；已有 ParserResult 却只有宏 `width`，状态仍为 PASS。
15 份选中的 FakeRAM LEF 证据出现该假实体。**之前记录的 891 是旧解析器提取出的对象数，
不是已核实的真实宏数；不能用于签核或覆盖率分母。**

根因：`scan/parsers/lef.py` 没有跳过 `PROPERTYDEFINITIONS` 作用域，直接用 MACRO 正则创建实体，
随后真正的宏声明处于错误实体上下文。Semantic 层忠实保留了坏证据，没有因此产生接口 PASS，
但这不足以使提取质量合格。没有用名称黑名单或展示层隐藏来掩盖问题。

- 完整失败链：`work/semantic_existing_acceptance_20261014/source_quality_failure.json`。
- 内存中的最小解析复现预期 `['fakeram7_64x21']`，实际 `['width']`，断言失败、返回码 1。
  日志：同目录 `property_scope_red.log`。这是验收红反例，不是全量回归成功用例。
- 人工单独只读了一个源文件头部核对；七场景诊断通过 open/scan/walk 拦截执行，RAW 内容打开和补扫尝试为 0。
- 229 个已有证据/治理/代码文件 SHA 不变；245 个所选 RAW 目标大小/mtime 不变。不对 RAW 全量 hash，
  元数据不变也不等于完整内容验证。
- 全量现有回归：884 tests / 13.352 s / OK。日志：同目录 `full_regression.log`。
  全量回归通过不抵消上述新红反例，真实数据验收仍是 NOT_ACCEPTED。

### 最小后续修复范围

按原计划的证据完整性停止扩张边界，本轮不自行扩展 Parser 重写、专业工具、Web/HTML 或 Gate。
后续优先增加属性定义作用域回归，再定向修复 LEF 解析器并使旧缓存失效；仅重提取受影响 LEF。
之后针对代表性 LIB/RTL 补可靠提取与覆盖证明，再运行接口一致性验收。不能靠手动填完整标记、
全库 hash、放宽绑定或强制发布绕过。分支仍未提交、未推送；现有 Release Gate 未修改。
