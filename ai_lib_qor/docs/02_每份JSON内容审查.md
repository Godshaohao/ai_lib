# v3.0 每份 JSON 实例的实质审查记录

> 审查输入：本包 `examples/` 中 **12 份 `.json` + 1 份 `.jsonl`**，分别覆盖 7 类数据契约。所有数值/路径均为合成演示，审查通过只代表结构与示例的业务关系自洽，不代表已核对企业内网真实输入。
>
> 审查不是“能 parse JSON 就 PASS”，而是逐个检查：身份是否唯一、来源是否存在、是否误用最新指针、业务含义是否对应、是否影响有效版本、是否存在无证据的 Macro/Pin 断言、更新是否会覆盖历史。

## 审查汇总

| 编号 | 具体示例 | JSON 契约 | 核对点 | 审查结论 |
|---|---|---|---|---|
| J01 | `deliveries/dlv_20260907_001/delivery.json` | DeliveryRecord | V07 全包范围、三文件唯一身份、明确的交付顺序 | 合成数据通过 |
| J02 | `deliveries/dlv_20261019_001/delivery.json` | DeliveryRecord | V08 增量包、两文件、没有删除第三文件 | 合成数据通过 |
| J03 | `snapshots/snap_nl253_0001.json` | FormalSnapshot | 首份正式 NL 快照，每一行能引用 V07 的 RAW 文件 | 合成数据通过 |
| J04 | `snapshots/snap_nl253_0002.json` | FormalSnapshot | 同名 NL 更新 tt Liberty，LEF/ff 未随之变动 | 合成数据通过 |
| J05 | `versions/rev_0001.json` | EffectiveVersion | 初始正式基线：3 个完整成员，3 个初始 ADDED | 合成数据通过 |
| J06 | `versions/rev_0002.json` | EffectiveVersion | 从 Rev 001 继承，2 个替换、1 个沿用，来源固定 | 合成数据通过 |
| J07 | `deliveries/dlv_20261019_001/checks/run_001.json` | CheckResult | RAW 对比不会伪装成已采纳的 Rev 差异 | 合成数据通过 |
| J08 | `ips/rtavfs/checks/rev_0002/run_001.json` | CheckResult | Rev 对比；LEF Macro SIZE/Pin 差异；Pin 检查范围 | 合成数据通过 |
| J09 | `file_facts/facts_core_v07.json` | FileFacts | LEF 原始 Macro/Pins、SIZE 单位和覆盖声明 | 合成数据通过 |
| J10 | `file_facts/facts_core_v08.json` | FileFacts | LEF 新 Macro/Pins、增 Pin C、SIZE 改变 | 合成数据通过 |
| J11 | `file_facts/facts_tt_v08.json` | FileFacts | Liberty Cell Pins；未宣称解析 Timing Arc/PG Pin | 合成数据通过 |
| J12 | `effective/index.json` | EffectiveIndex | 最新计算 Rev 002，但已采纳仍 Rev 001 | 合成数据通过 |
| J13 | `effective/acceptance.jsonl` | AcceptanceEvent | 一个真实意义上的接受事件；当前指针与该事件一致 | 合成数据通过 |

## J01–J02：交付 JSON 实际内容审查

**J01 V07**
- `delivery_id=dlv_20260907_001`，而供应商版本标签为 `V07`：避免同名重交引起历史覆盖。
- `delivery_order=7`，与 J02 的 `8` 严格递增。时间仅作证据，文件定位不依赖字母排序或修改时间。
- 交付覆盖 `core.lef`、`func_tt.lib`、`func_ff.lib`，逻辑文件位互不重复；Liberty 的 Corner 和 Mode 显式记录。
- `package_mode=FULL` 仅对 `package_scope.file_keys` 中明确声明的三个文件位有效，并非暗示所有 View 齐套。
- `explicit_removed_file_keys=[]`，没有借缺席推断任何删除。

**J02 V08**
- `package_mode=INCREMENTAL`，两份实际到货文件的 `file_key` 与 V07 对应。一个新交付不等于已经形成新有效版本。
- V08 缺少 `func_ff.lib` **不能**从 Rev 中删除它。J06 继承 Rev 001 中的 ff 来源。
- 检查与计算分开：J07 是入库前比较；J06 是后续选择文件进入有效集，两种记录可以分时生成。
- 实际部署需要由供应商版本、交付顺序配置和扫描结果生成上述字段，不允许随意按时间猜测 FULL/INCREMENTAL。

## J03–J04：正式 Snapshot 实际内容审查

**J03 snap_0001**
- `formal_nl_id=NL2.5.3` 是标签；唯一历史身份是 `formal_snapshot_id=snap_nl253_0001`。
- `linked_files[]` 包含 core LEF、tt/ff Liberty，共 3 行，和 V07 中 3 个来源对应。
- 每行同时保留 `link_path`、`resolved_path` 与匹配到 RAW 的 typed `source_ref`：保留“正式链接了什么”和“来自 RAW 哪次交付”两层事实。
- `coverage=COMPLETE_IN_SCOPE` 的范围为本示例指定的 lib/LEF/Liberty；并非整个公司 NL 的六大 View 盘点已完整。

**J04 snap_0002**
- `previous_snapshot_id` 正确指向 J03，而不是指向某个 `latest.json`。
- 两个 Snapshot 都叫 `NL2.5.3`，但 `func_tt.lib` 的 `resolved_path` 与 RAW 来源从 V07 更新为 V08。
- `core.lef` 和 `func_ff.lib` 来源保持 V07，因此 J06 中“最新有效文件集采用 V08 core.lef”并不能自动推论“正式 NL 也采用了 V08 core.lef”。
- **特殊边界**：正式 NL 指向不在 RAW Registry 里的文件时，`source_match=UNMATCHED` 且 `source_ref=null` 合法，应保留真实 `resolved_path`，不伪造 RAW。历史物理文件原地覆盖则需要另行记录“不可复现”的证据状态。

## J05–J06：有效版本实际内容审查

**J05 Rev 001**
- 原因是 `FORMAL_BASELINE`，从固定 J03 正式 Snapshot 建立初始文件组合。
- `members` 同时包含三个文件位，均指向 J03 中固定的正式文件行。不是指向目前 `NL2.5.3` 的“最新”链接。
- `parent_revision_id=null`，因此 `changes` 中三条 ADDED 是“相对空集合”，不是说 J03 对所有 RAW 都执行了更新。

**J06 Rev 002**
- `parent_revision_id=rev_0001`。`members` 完整包含 core、tt、ff 三项；前两项引用 V08 RAW 文件，第三项继续引用 J03 里的 ff 正式文件。
- `changes` **仅包含 core 和 tt 两项**；经程序比较父子版本的 `members`，这两项是确实更换了来源引用。
- 此处 `action=REPLACED` 的严格含义为**有效成员采用来源被替换**，不是“LEF/LIB 解析内容肯定改变”。内容差异在 J08 的 CheckResult 中。
- `reason.kind=RAW_DELIVERY` 说明该版本由 V08 更新推动，但是否采纳由 J13 决定；版本本身无 `accepted:true`。
- **跨库边界**：如果某个成员来自其他 SourceLibrary，来源引用仍可跨库解析；不会在第二个库目录重新保存一份同名权威 Rev。

## J07–J08：检查结果实际内容审查

**J07 针对 V08 入库前检查**
- `target.kind=RAW_DELIVERY`，`baseline.kind=RAW_DELIVERY`；比较的是 V08 与 V07 交付中**真正共同出现**的两个逻辑文件位。
- `source_changed=true` 仅指交付来源不同，不是有效版本 REPLACED。即使当前已采纳版本仍是 Rev 001，这个入库前检查也可以存在。
- core LEF 有固定 Parser Fact 支持的 SIZE 差异；tt Liberty 尚未进行内容对比，必须写 `content_status=UNKNOWN`。
- 没有执行 LEF–Liberty 质量检查时 `quality_checks=[]`，不填虚假的 PASS。

**J08 针对 Rev 002 的检查**
- `target.kind=EFFECTIVE_REVISION`，`baseline.kind=EFFECTIVE_REVISION`；它是有效版本差异，不再混成“供应商历史最近两次出现”的结果。
- LEF `MAC_A.SIZE`: `[120.0,80.0]` → `[124.0,80.0]`，单位 um；新增 `MAC_A/C` Pin 的存在性变化。两者由 J09/J10 的解析事实支持。
- tt Liberty 来源采用了 V08，但本示例没有旧 Liberty 的完整可比内容事实，因此该文件 `content_status=UNKNOWN`，不是“内容没有变化”。
- LEF–Liberty Pin 匹配 PASS **仅针对示例 `MAC_A` 的信号 Pin 名称与方向**，因为 J10/J11 的相关解析范围均完整；不扩张为 Timing Arc、PG Pin 或所有 Liberty 质量检查通过。
- 同一个 Rev 的规则改变可以新增 `run_002`；**不会因此生成 Rev 003**。

## J09–J11：三个 Parser 事实实例审查

- J09、J10 都为 LEF，`objects.macros[]`：Macro 名称、um 尺寸、信号 Pin 名称及方向。
- J11 是 Liberty，使用 `objects.cells[]` 而不是错误地塞入 LEF `macros[]`；目前仅覆盖 Cell/Pin 名称/方向。
- `parse_status=COMPLETE` 只对 `covered_sections` 明确列出的这几项而言；未声明 Timing Arc 被解析。
- `units` 写明从 LEF/Liberty 来源单位规范化后的单位；生产实现需依照 Parser 的真实单位数据，不能无条件假定所有库都写 um/ns/pf。
- 三份事实 `source_ref` 均可以追溯到具体 V07/V08 文件行；Check 引用 `facts_id`，不用复制整个 Macro 或 Cell 列表。
- **未扩展的工程属性**：LEF OBS/ORIGIN/SITE/多 PORT/PG pin、Liberty TimingArc/Power/Area/OperatingConditions 等，实际 Parser 已有且业务检查需要时通过已有事实模型补充，v3.0 示例不虚构其值。完整实现不能拿本演示视为“所有 Macro 验收项已覆盖”。

## J12–J13：当前入口与采纳事实

**J12 index.json**
- `latest_calculated_revision=rev_0002`：最新已计算发布的是 Rev 002。
- `current_accepted_revision=rev_0001`：IP Owner 尚未决定采纳 Rev 002。
- Index 不保存完整版本表，也不保存 Formal Snapshot 的可变路径；它是可以重建的小指针。

**J13 acceptance.jsonl**
- 只有一次 ACCEPT Rev 001 的示例事件，并非“每个计算版本都自动 Accept”。
- `actor/reason/acted_at` 足以理解谁做了什么决定，不必为了 MVP 引入多级审批工作流。
- 采纳一旦发生，追加新事件后再更新 `index.json`，不修改旧 Rev。若未启用人工采纳，则可以不创建该文件，Index 中 accepted 为 null。

## 与 v2.2 的取舍审查：删除的是重复权威，不是功能

| v2.2 对象 | v3.0 决策 | 依据 |
|---|---|---|
| RegistrySnapshot、DeliveryPolicy | 继续读现有配置，必要时为一次 Run 固定配置版本；暂不增加两类必写业务 JSON | 配置是输入，不需要重复维护两套相同属性 |
| RawInventory + FileOccurrence | 合并为 DeliveryRecord；File Occurrence 只在索引中重建 | 同一交付事实只保留一个权威 |
| FormalObservation + FormalSnapshot | 正式 Snapshot 保留权威文件状态；观察/扫描日志交给已有运行日志 | 避免两个带完整文件清单的永久“快照”事实 |
| IPFormalReference | 从 Formal Snapshot + Ownership 产生可缓存的按 IP 视图 | 减少未归属和映射变更引起的同步问题 |
| EffectiveSet + EffectiveRevision | EffectiveSet 作为 owner/set ID，Revision 持久化完整文件 | 默认一个 IP 一套，无需独立 set.json |
| FileComparison + IPReviewResult | 同一个 CheckResult 分清 file_changes 与 quality_checks | 避免差异结果和审查结果重复保存且互不一致 |
| QoRMeasurement | 仅真实运行指标时在现有 QoR 测量结构中保留，或为 Check 增加专门指标证据 | MacroCount 不要冒充 STA QoR，减少未用对象 |
| AcceptanceEvent | 可选 acceptance.jsonl；Index 只保留当前指针 | 决策历史与当前状态职责不同，不能合并成可覆盖的一份状态 |
| FileLocator / RevisionHistory / ReportModel | 根据权威记录生成 HTML/Excel 查询视图 | 不新增平级永久 JSON 类型 |

## 仍需真实运行验证，不能宣布通过的内容

- 这些是**合成示例**，不能证明企业 RAW 与 NL 的具体 symlink 行为、文件是否被原地覆盖。
- `library_ownership.yaml` 的映射粒度可能比示例复杂；需用真实数据确认 `file_key` 的 View、Corner、Mode、Variant 生成规则。
- LEF/Liberty 实际 Parser 是否能提供 Macro、Signal Pin、PG Pin、单位、Timing Arc 与覆盖证据，需要对接真实产物。
- FULL 包是否可以推断删除、如何处理补丁叠加，以及跨 IP 共享宏文件，仍以已经明确的交付包语义与业务确认范围为准。
- UI/Excel 的全部验收 Sheet 保持原有；v3.0 仅调整源数据权威与映射关系，不自动删除历史报告。

## 增补：不增加生产 JSON 种类的两个边界测试

**RAW-only 来源库**：测试在不包含任何正式 NL 的情况下建立 `owner_type=SOURCE_LIBRARY` 的初始有效版本。内部 `revision_id=rev_0001` 可以与其他有效集的 Rev 001 同名，因为真正身份是 `(effective_set_id, revision_id)`。所有文件来源均为 RAW Delivery，历史可独立还原。

**BusinessIP 跨 SourceLibrary**：测试在 home library 保持不变时，加入来自 `lib_extra` 的文件来源引用。它成为同一套 IP 有效版本的一个成员，不在第二个 Library 下另建重复有效版本。

上述两项只在 Python 内存中构造测试数据，不额外持久化 10 多份所谓“特殊场景业务 JSON”，避免重蹈 v2.2 交付包的数量误导。
