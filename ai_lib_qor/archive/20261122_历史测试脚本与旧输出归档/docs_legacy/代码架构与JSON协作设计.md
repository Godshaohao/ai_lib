# ai_lib_qor：代码架构、JSON 协作与文件安排

> 2026-11-13。本文是基于工作区 v3、v5 和 v5.1 材料的架构梳理及建议，不是已实现代码的清单。v3 是现有设计契约与合成示例；生产权威版本仍待确认。新项目不沿用旧 `src_qor` 的目录结构。

## 1. 一句话与当前状态

系统把供应商交付、正式库快照和业务 IP 的有效文件集合关联起来，再对选定文件做差异与质量检查。多个专业步骤可以为一个结果提供数据，但**同一个正式产物由一个明确的发布入口写出**。

| 内容 | 实际状态 | 依据 |
|---|---|---|
| v3 契约 | 7 个设计 Schema、合成示例、字段表和验证器 | `ai_lib_qor_contract_v3/schemas/`、`examples/`、`docs/` |
| v3 示例生成 | `build_examples.py` 生成多类合成文件；`build_schemas.py` 生成 Schema | 设计包脚本；不是生产扫描器 |
| v5 检查汇总 | `tools/assemble_checks.py` 将合成贡献组装成 `check_run.v1` 并以独占创建方式发布 | `ai_lib_qor/ai_lib_qor_artifact_first_v5/`；没有运行实际 EDA 检查 |
| v5.1 证据原型 | `evidence_guard.py` 校验示例输入与证据；`make_fixture_manifest.py` 生成夹具清单 | `ai_lib_qor_v5_1_review/`；与正式流程未接通 |
| 新业务源码 | `src/ai_lib_qor/` 是本文方案；当前资料目录未发现这些拟议模块 | `ai_lib_qor/` 目录检查 |
| 旧工具 | `/home/polaris/proj/mx/ai_lib/repo/src_qor/lib_guard/` 存在扫描、解析、比较及报告能力 | 可评估能力复用；不能由此推断新项目已经迁移 |

v5 的 `check_run.v1` 与 v3 的 `check_result.v1` **不是同一结构**。前者使用 `checks` 容纳贡献，后者包含 `file_changes`、`quality_checks`、`summary` 等。必须明确映射和信息缺口，不能直接把 v5 文件改名当 v3 使用。

## 2. 一条典型业务路径

```text
供应商 RAW ──扫描、归属、范围确认──> DeliveryRecord ─┐
                                                   ├─> 版本组合 ─> EffectiveVersion
公共正式 NL ──盘点链接、匹配来源──> FormalSnapshot ──┘                    │
                                                                        ▼
具体文件 ──格式解析 / 事实汇总──> FileFacts ──> 文件差异 + 跨 View 检查 ──> CheckResult
                                                                        │
                                                    ┌───────────────────┴─────────┐
                                                    ▼                             ▼
                                                报告读取                  人工采纳/回退事件
                                                                                  │
                                                                      EffectiveIndex 更新
```

交付可直接进行预检查；不要求先创建有效版本。图中箭头是数据/处理关系，非独立服务或当前已接通的调用链。

## 3. 哪些脚本共同形成一个 JSON？

下表脚本名称均为**新架构的拟议职责**，不是已经存在的程序。共享一个 JSON 指共同贡献或读取数据，**不意味着每个脚本直接写同一个最终文件**。

| 正式记录 | 多个贡献步骤 | 汇总 / 唯一发布职责 | 关键内容与边界 |
|---|---|---|---|
| DeliveryRecord，`deliveries/<delivery_id>.json` | `raw_scanner.py` 发现文件；`file_classifier.py` 识别逻辑文件位；`delivery_policy.py` 结合已确认顺序、包范围和删除声明 | `delivery_builder.py` 组装，`publisher.py` 校验并发布 | `files[]` 是该次实际出现；V08 缺少文件不自动等于删除 |
| FormalSnapshot，`snapshot.json` | `formal_scanner.py` 盘点链接；`source_matcher.py` 关联 RAW；范围/归属配置提供上下文 | `snapshot_builder.py` 组装，`publisher.py` 发布 | `linked_files[]` 固定本次观察；无法匹配 RAW 仍保留真实链接 |
| FileFacts，`<facts_id>.json` | 格式解析器 `lef.py` 或 `liberty.py`；按需元数据/属性提取器 | `facts_assembler.py` 合并单一来源的兼容事实，`publisher.py` 发布 | 每份针对单个具体来源；LEF 和 Liberty 不合并成一份。v3 对多提取器版本、来源、覆盖的表达需先确认 |
| EffectiveVersion，`rev_*.json` | `slot_resolver.py` 解析身份；`composer.py` 读取父版、选择交付或正式文件并计算变化 | `composer.py` 组装，`publisher.py` 发布 | `members` 为完整集合；`changes` 为相对父版来源变化。完成版本不等于采纳 |
| CheckResult，`run_*.json` | `content_diff.py` 比较文件；`lef_diff.py` 归纳 Macro/Pin；`lef_liberty.py` 做跨 View 检查；未来可增加经确认的测量和评价 | `checks/assembler.py` 按 v3 合同组装；`checks/evidence.py` 核对证据；`publisher.py` 发布 | 贡献必须绑定同一检查目标、基线、范围及来源；v5 原型 `checks` 不能直接当作 v3 字段 |
| AcceptanceEvent，`acceptance.jsonl` | 人工或经授权的业务决定；`acceptance.py` 校验目标和事件 | 单一事件写入入口追加 | 检查通过、产生新 Rev、正式 NL 更新均不自动触发采纳 |
| EffectiveIndex，`effective/index.json` | 从已发布 Rev 得出最新计算指针；从真实采纳事件得出当前采纳指针 | `index_projector.py` 形成投影；`publisher.py` 发布 | 可重建的查询入口；不会把最新计算默认当成已采纳。恢复/并发策略待明确 |

正式 NL 的 `index.json` 是用户希望的**另一个拟议查询入口**，并非上表的 EffectiveIndex；其字段、快照选择与重建规则尚未确定，不能声称已经属于 v3 Schema。

### 3.1 一个检查结果的具体协作

```text
checks/plan.py：确定目标、基线、文件引用、范围与规则
    ├─ content_diff.py  ──> 文件来源 / 内容比较贡献
    ├─ lef_diff.py      ──> Macro、Pin 变化贡献
    └─ lef_liberty.py   ──> 信号 Pin 名称 / 方向等检查贡献
                    ↓
checks/assembler.py：校验身份与冲突，映射到 v3 的 file_changes / quality_checks
                    ↓
checks/evidence.py + 合同 / 引用校验 → publisher.py → run_001.json
                    ↓
reporting/：根据同一个选定 Run 与关联事实构建 HTML / Excel
```

- 贡献可以在内存中传递；需要调试或并行时再放入 `staging/<job_id>/`。临时片段不作为额外权威业务记录。
- 同一条字段若多个步骤都声明所有权，先报冲突并处理，不用最后写入覆盖前者。
- 检查缺失、失败、覆盖不足分别保留真实状态；差异事实不等于质量 FAIL，质量 PASS 不等于人工采纳。
- v3 当前是否能保留每个贡献的完整证据、依赖和插件身份需要逐字段确认；表达不下时先记录差异，不静默丢弃。
- v5.1 证据原型已发现 Gate 依赖可被伪造的反例，不能作为生产证据门禁直接复用。

### 3.2 一个 FileFacts 的协作

以同一个具体 `core.lef` 来源为例：LEF 解析器可提取 Macro 尺寸，Pin 提取步骤可提供名称和方向；汇总时以同一来源和对象身份关联，记录实际覆盖。`func_tt.lib` 是另一个来源文件，应有独立事实；两个文件的关联判断进入 CheckResult。v3 的 `file_facts` Schema 使用分支，完整性、解析器信息和多提取器的证据表达需结合具体分支审查，不能凭 v5 方案声称已经支持多代事实及多 Parser 元数据。

## 4. 新源码目录（提案，按需创建）

```text
ai_lib_qor/
├── pyproject.toml                 # 项目、依赖及命令入口
├── src/ai_lib_qor/
│   ├── cli.py                     # 参数和命令入口，不承载检查算法
│   ├── config.py                  # 读取归属、顺序、范围等配置
│   ├── sources/
│   │   ├── raw_scanner.py         # RAW 发现与盘点
│   │   ├── formal_scanner.py      # 正式 NL 链接观察
│   │   ├── file_classifier.py     # 逻辑文件身份/类型候选
│   │   ├── source_matcher.py      # 正式目标与交付来源匹配
│   │   ├── delivery_builder.py    # 交付记录组装
│   │   └── snapshot_builder.py    # 正式快照组装
│   ├── facts/
│   │   ├── parsers/lef.py         # LEF 事实提取
│   │   ├── parsers/liberty.py     # Liberty 事实提取
│   │   └── facts_assembler.py     # 同一来源事实组装
│   ├── versions/
│   │   ├── slot_resolver.py       # 逻辑文件位与身份
│   │   ├── delivery_policy.py     # 已确认的包范围和继承规则
│   │   ├── composer.py            # 父 Rev + 明确选择 → 完整 Rev
│   │   ├── acceptance.py          # 人工采纳 / 回退事件
│   │   └── index_projector.py     # 计算当前版本入口
│   ├── checks/
│   │   ├── plan.py                # 冻结检查目标、范围、基线与输入
│   │   ├── content_diff.py        # 文件来源 / 内容比较
│   │   ├── lef_diff.py            # Macro / Pin 差异
│   │   ├── lef_liberty.py         # 跨 View 质量检查
│   │   ├── evidence.py            # 来源、覆盖和依赖证据校验
│   │   └── assembler.py           # 检查贡献 → v3 CheckResult
│   ├── storage/
│   │   ├── paths.py               # 业务 ID 到产物路径的定位
│   │   └── publisher.py           # 合同校验、固定记录发布、索引更新
│   └── reporting/
│       ├── view.py                # 只读查询与展示数据
│       ├── html.py                # HTML 呈现
│       └── excel.py               # Excel 呈现
├── config/                        # 归属、交付顺序、检查范围（用户维护）
├── schemas/                       # 设计合同；权威性确认后使用
├── tests/                         # 真实语义及合同 / 业务关系测试
├── docs/                          # 设计、字段、使用说明
└── work/                          # 运行数据；可部署在项目外
```

目录是职责地图，不要求每个步骤一定单独成文件或立即开发。首版仅实现必要链路；CLI / 报告只调用业务能力或读取结果，不直接修改交付、版本和采纳事实。正式生产实现选择既有解析能力前，需要检查调用接口、覆盖、许可证和行为兼容性；不以旧目录作为新目录骨架。

## 5. 运行数据目录（提案）

```text
work/
├── vendors/<vendor_id>/libraries/<source_library_id>/
│   ├── deliveries/<delivery_id>.json
│   ├── delivery_checks/<delivery_id>/run_001.json  # 交付预检查，可选
│   └── ips/<ip_id>/
│       ├── effective/
│       │   ├── index.json                          # 计算与采纳的两个指针
│       │   ├── versions/rev_0001.json
│       │   ├── versions/rev_0002.json
│       │   └── acceptance.jsonl                   # 有事件才产生
│       └── checks/rev_0002/run_001.json
├── formal_nl/NL2.5.3/
│   ├── index.json                                 # 拟议，Schema 尚未定义
│   └── snapshots/
│       ├── snap_0001/snapshot.json
│       └── snap_0002/snapshot.json
├── file_facts/<facts_id>.json                     # 文件来源的事实；代次规则待定
├── staging/<job_id>/                              # 可选临时贡献，不是权威记录
└── reports/                                       # 可重新生成的 HTML / Excel
```

`delivery_id` 而非 `V08` 必须确定单次交付身份；供应商版本标签可重复。正式库独立存放，不按 Vendor 复制。跨库 IP 需要一个明确的权威存放位置；无 IP 的来源库也要有可管理的有效集合，具体路径及映射规则待确认。目录中的正式快照层级不同于 v3 示例 `snapshots/<snapshot_id>.json`：这是路径提案，读取历史示例需要适配，不是修改了 v3 Schema。

## 6. 最小发布与失败边界

1. 锁定输入、身份、目标、基线和范围；如未确认，保留未知或不执行需要它的步骤。
2. 各贡献步骤产生可检查的内存结果；按实际需要写临时目录，不直接改写已发布文件。
3. 汇总器检查对象身份、字段归属、重复贡献和可映射性；证据检查验证来源与覆盖，再执行 Schema 与跨记录校验。
4. 固定记录发布成功后，才按需要更新可重建入口；写入失败应保留可恢复的既有状态。并发、锁、崩溃恢复和文件系统语义需在实现时明确，不能仅凭“单写入者”宣称已经解决。
5. 采纳动作使用单独的授权业务路径。事件追加及索引更新之间的崩溃恢复，需要明确重放、幂等和冲突策略。

## 7. 建议实施次序与验收

| 阶段 | 最小目标 | 最低核验 |
|---|---|---|
| M0 合同 | 确认 v3 权威版本；列出 v5 检查贡献到 v3 的字段映射和不能表达的内容 | 逐字段审阅，禁止静默丢数据；区分 Schema 约束与业务规则 |
| M1 文件来源 | 一次真实交付的登记与单个 LEF 解析 | 文件身份、来源可追溯；解析失败和未覆盖可见 |
| M2 一个 CheckResult | 一对真实 LEF 的内容与 Macro 差异形成 v3 结果 | 与事实、基线一致，Schema / 引用校验通过；旧记录保留 |
| M3 多步骤协作 | 同一目标再加入 LEF–Liberty | 冲突、缺项、跨目标、覆盖不足与证据不成立均有可见结果；修复 v5.1 已知依赖缺口 |
| M4 采纳与展示 | 显示计算、采纳与正式状态，明确人工采纳路径 | 采纳独立于 PASS；同一结果的 HTML / Excel 对照一致，失败后可恢复 |

首版优先重新运行受影响检查；复用历史结果需先证明输入内容、实现、参数、依赖和环境身份充分一致，且旧结果完整。是否支持多代事实、Run 参数身份以及 Formal NL 索引需要另外确定契约。
