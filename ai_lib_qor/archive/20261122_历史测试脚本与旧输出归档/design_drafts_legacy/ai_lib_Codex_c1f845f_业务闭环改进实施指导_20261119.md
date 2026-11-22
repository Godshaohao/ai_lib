# ai_lib — Codex 业务闭环改进实施指导（基于 `c1f845f`）

> **性质：可执行的修改规格与验收要求，不代表已完成代码修改。**
>
> **基线**：`Godshaohao/ai_lib`，分支 `codex/ai-lib-qor-workbench`，固定提交 `c1f845f0cae892c42e5bc4a94f7c55a2f232ecbc`（2026-11-19 核查）。
>
> **目标**：在不推翻现有五类契约和 `file_index.v3` 的前提下，打通 `RAW Delivery → EffectiveVersion → FileIndex → FileFacts → CheckResult → 单版本 Excel / IP 汇总 Excel`，补足交付排除和回退，并使数据源、Web、CLI、Agent 消费同一组已归档事实。
>
> **Codex 必须先阅读本文件以及列出的现有代码。不得将“现有部分模拟测试通过”当作真实生产验收完成。**

## 0. 必须遵守的已确认业务规则

1. **每个 SourceLibrary 的产物集中在一个 Library 工作目录**：`work/libraries/<Vendor>/<Library>/`。**不要**为新链路另立 `work/file_facts/`、`work/runs/`、`work/reports/` 等业务产物根目录。旧产物暂时兼容读取，不直接搬走或删除。
2. **五类核心业务契约不变**：DeliveryRecord、FormalSnapshot、EffectiveVersion、FileFacts、CheckResult。`file_index.v3` 是由前三类生成的**可重建读模型**，不是新的事实来源；`AcceptanceEvent` 是既存的人工作业历史，继续保留。
3. `file_index.v3` 的数据必须包括所有已登记 RAW 交付（即使交付后来被排除）、所有可归属 Formal 快照、每个有效集所有已发布 Revision 的完整成员。单次增量交付缺失的文件**不等于删除**。
4. RAW 文件历史、Formal 软链接观察历史、Effective 采用历史是三条独立时间线。每条历史必须完整；**最新/次新只是查询结果**，不可替代完整数组。
5. 交付先后只用已经确定的业务规则 / 明确登记排序。不得从扫描完成时间、文件名编号、`natural_version_key` 或自动补的 `delivery_order` 推断确认顺序。
6. Formal 的 `link_target` 必须忠实保留 `os.readlink()` 采集值。归档路径文本匹配 ≠ 当前软链接仍有效 ≠ 文件内容相同；不可匹配链接保留在 `unmatched_formal`，不能丢失。
7. 一个 Effective Revision 是**完整文件采用集合**，包含新源文件和继承文件。不同 BusinessIP 可有不同有效集，未映射 BusinessIP 的 SourceLibrary 也可以独立管理；不要强行补造 BusinessIP。
8. “来源发生变化”“内容发生变化”“质量 PASS”“人工采纳”是四种不同事实，不能合并统计或相互推断。
9. 检查只对明确选中的真实文件执行。FileFacts 不写进 FileIndex；CheckResult 不写回 Effective。Corner **只列举，不自动断言齐套**。
10. 继续使用已有 `latest_*` **相对软链接**。Latest calculated 与 latest accepted 是两个独立概念；不能用软链接替代人工采纳。
11. 不能修改、重写、删除任何已发布 Delivery、Formal、Effective 历史，也不能覆写真实验收事件。所有演进采用新归档或追加事件。
12. 优先最小改动与 MVP 可复现，**不要新建一套数据库、Agent 框架、重复的状态机或第六种核心业务 JSON**。

## 1. 现状确认：代码事实、缺口、不要误报

| 现有文件 | 核查到的真实能力 | 主要缺口 |
|---|---|---|
| `application/file_index_v3.py` | 从 Delivery、Formal、Effective 建立 `file_index.v3`；三类历史、完整 Rev 成员、未匹配 Formal、父子链校验 | 仍是归档全量重建；对未确认文件身份保守处理；跨库集成需真实验证 |
| `application/file_index.py` | `repository_order`、v2 兼容、`refresh_library_index_locked`、受控强制重建 | 旧 v2 CLI 仍可输出 v2，易被误用；刷新状态 APPEND 不代表低复杂度增量 |
| `application/data_query.py` | RAW 历史、逻辑文件时间线、Rev 比较、Formal 来源对照、Index 状态 | `_verified_file_index()` 常需重建投影；`index-v3` 查询返回现算投影，未真正以已发布 Index 为优先共享数据 |
| `application/effective_json.py` | `create_revision`、父版本继承、`create_formal_revision`、来源差异 | 需要显式调用和选择 View；未从新 Delivery 自动驱动有效版本演化；无排除/回退工作流 |
| `application/effective_publisher.py` | `publish_v2()` 校验、不可变版本写入、EffectiveIndex、Latest 与 FileIndex 刷新 | 还不是“新交付→计算候选→无歧义自动发布”的闭环；Index 刷新失败仅 warning |
| `sources/auto_ingest.py` | RAW 增量发现及 Delivery 发布；不猜 FULL；已接 FileIndex 刷新 | 新交付后不自动生成 Effective；默认分类不等于可信 `file_key` |
| `versions/index_projector.py`、`versions/store.py` | 既存 `ACCEPT`、`ROLLBACK`、`REVOKE` 采纳事件回放；不可变历史 | **采纳回退已有能力**，不要另造同名机制；“有效文件组合回退”不同于采纳回退 |
| `application/v3_checks.py` | 显式 LEF–Liberty 配对；单 Rev / BUSINESS_IP 多 Rev CheckResult、Excel；单次 IP 批运行内 Facts 缓存 | `file_key` 未确认即阻断；尚不自动选适用文件；运行产物在独立 `runs/run_*`；`input_plan.json` 冗余；不比较 Liberty 新旧内容 |
| `reporting/workbook_model.py`、`overall_excel.py` | 已增加有效文件来源 / 版本来源对照与 IP 汇总 | 不能把检查覆盖数当全 Rev 来源变化总数；逻辑身份差异与路径差异需清晰区分 |
| `workbench/app.py` | 文件索引刷新按钮、状态、单 Rev/IP 检查入口 | 页面刷新是否高成本，以及旧 Runs 路径兼容，需端到端确认 |

**现有证据**：`exports/v3_multi_vendor_20versions_20261119_review/` 声称 3 供应商、5 库、20 Delivery、20 Revision、3 BusinessIP，并模拟 V04 Pin FAIL；这个目录不包含可移植的真实 RAW、Excel、HTML。GitHub 没有可见的本提交 CI 通过记录。Codex 需要**自己实际执行**测试，报告总数、跳过数和失败数。不得使用“通过若干测试”的未经复核运行结论。

## 2. 修改顺序：分阶段可交付，不要一次大重构

### 2026-11-20 已确认阶段与真实范围

- **A 真实语义**：以五次 Delivery、现有 Effective 和 Formal 归档为准，先只读形成不依赖 FileFacts 的 CheckContext。SRAM22/sram22_256x16m8w8 当前库级有效集 Rev001 为 1 个成员，Rev002 为 2 个成员；两者均不是七文件全集。
- **B 有效版本演化**：Preview → 变更确认 → Apply，继承、替换、明确归属的新增、明确删除及幂等；7→7 是独立模拟 fixture，不能套到真实库。
- **C 排除与恢复**：排除仅影响指定有效集的后续候选，不删除 RAW 历史或修改已发布 Revision；已被采用的来源需提示影响。复用既有采纳事件并区分恢复性新 Revision。
- **D 检查与产物**：先有准确成员与选择依据，再解析、比较和明确配对；单版本与整体检查共用数据源，未检查内容不标 PASS。模拟、真实数据和人工 Excel 验收分别记录。


| 阶段 | 优先级 | 目标 | 允许改动 | 通过后再进入 |
|---|---|---|---|---|
| P0 | 必须先做 | 固定基线、明确真实文件身份策略和测试 | 配置/分类/查询/测试小范围 | P1 |
| P1 | 核心业务 | 从新 Delivery 产生候选 Effective、支持受控自动发布及排除/回退 | `effective_json` / `effective_publisher` / 小型 orchestrator / CLI | P2 |
| P2 | 共享数据 | FileIndex 刷新与消费分离，建立 `get_check_context()`；自动候选选取 | Index/Query/Check/Profile | P3 |
| P3 | 交付收敛 | 新链路 Library 集中存储；Check/Facts 报告统一；兼容旧 Runs | 运行器/存储 adapter / Web / 报告 | P4 |
| P4 | 真实验收 | RAW→Effective→Index→检查→Excel 全链路，故障恢复、性能测试 | 真实样本验收、测试/文档 | 完成 MVP |

原则：**每阶段一组小提交、附独立可运行测试**。若某阶段阻塞，保留已通过阶段，不能用大范围重写绕过。

---

## 3. P0：可信文件身份，不得把“分类成功”当成“来源已确认”

### 3.1 当前真实问题

`file_index.v3` 在 `identity_status != CONFIRMED` 时把 RAW occurrence 的 `file_key` 置 `null`；`v3_checks._source()` 又必须同时满足 `classification == RESOLVED`、`identity_status == CONFIRMED`、`file_key` 非空。于是部分真实库有完整历史但无法运行检查。

**不要**通过删除 `_source()` 的确认条件或把所有 `RESOLVED` 改成 `CONFIRMED` 解决。

### 3.2 最小修正方案

- 复用现有 `scan_sources.json` 与 `registration.py` 的人工显式映射路径，明确可审计的自动识别条件。
- `file_key` 表示**逻辑文件位**，如同一 IP 的同一 LEF / 指定 Liberty 模型+Corner，而不是单次交付绝对路径。路径变化只在确认逻辑身份后才能关联。
- 采用三个层次：
  1. `PATH_OBSERVED`：只确认实际路径与 View，支持完整时间线展示，**不证明同一逻辑文件**；
  2. `CANDIDATE`：分类器给出候选 file_key，不能自动写成已确认事实；
  3. `CONFIRMED`：显式登记或严格、可回溯的配置规则确认，方可作为跨交付逻辑比较 / 部分检查输入。
- **这些是算法概念，不要求新增三种 JSON 状态字段**；优先映射现有 `classification / identity_status / evidence`，避免破坏 v1/v2 契约。
- 同一个 Library、同一 View、同一确认 file_key 在一次交付中不能指向两份文件；歧义要报告，不能“选第一份”。
- 单文件定位和 CheckContext 通过明确 Delivery+View+Path+Revision 形成真实成员清单，不依赖 FileFacts 或 CONFIRMED；显式比较需有可核验选取依据，跨路径逻辑身份合并才要求已确认身份。LEF/Liberty 配对应具有明确配对依据。
- `source_ref` 继续完整采用 `Vendor + SourceLibrary + DeliveryID + FileID` 的作用域，不用单独 `file_id` 作全局身份。

**修改入口**：`sources/classifier_adapter.py`、`sources/registration.py`、`application/source_repository.py`、`application/data_query.py`、`application/v3_checks.py`，必要时复用当前 Evidence，**不得直接删除 Evidence 读写**。

**验收**：相同确认的 LEF 改路径时逻辑时间线合并；不确认的改路径不会误合并；同 file_key 冲突明确阻断；一个只有明确 Delivery+View+Path 的单文件解析可以使用且不伪造逻辑对照。

## 4. P1：Effective 自动演化与发布（最高业务优先级）

### 4.1 必须分离计算和发布

新增或复用轻量编排服务（建议先放 `application/effective_workflow.py`，如果已有适合入口则直接复用，不强制新文件），提供两步：

```python
# 设计接口示意，不是现有代码
preview = preview_effective_update(
    work, vendor, library, set_id, delivery_id,
)
# preview 仅内存结果，不新增 preview_*.json / input_plan.json

outcome = apply_effective_update(
    work, vendor, library, set_id, delivery_id,
    expected_parent_revision=preview.parent_revision,
    explicit_decisions=confirmed_decisions,
)
```

**Preview 不修改任何历史文件**。自动发布只在全部条件满足时触发：归属唯一、交付排序可信、来源文件位确认、没有有效成员冲突、不会凭未知交付范围删文件、当前父版本未变且发布目标不存在。

### 4.2 生效算法（可确定时自动，无歧义时一键）

1. 根据 `set_id` 读取现有最新**已计算** Effective（不是最新已采纳）；没有 Effective 时显式选择 RAW-first 初始建库，或符合条件的 Formal 基准建库。
2. 检查 Delivery 是否已归档、顺序正确及是否被排除；不能因该交付已有部分成员被采用就提前判定重复，须比较本次明确操作后的完整目标成员集合。
3. 从父 Revision 的**完整成员**复制开始。
4. 对新 Delivery 中**已确认相同 file_key** 的成员替换来源，保留未提供的其他成员；原交付中未出现文件不代表删除。
5. 新文件无论 SourceLibrary 或 BusinessIP，都只有在能明确归属当前有效集时才加入；无法归属者保留在 RAW/FileIndex 历史，不偷偷加入。
6. 若某个文件改名，但确认了同一逻辑 file_key，应替换旧路径成员，不能并存成两个重复文件。
7. 删除必须依据**明确的删除事实**：优先采用可验证的 `explicit_removed_file_keys`；`package_mode == UNKNOWN` 或 `scope_confirmed == false` 时禁止凭缺失推断删除。即使 FULL 已确认，若覆盖范围语义不完整，也先形成待确认变更，不自动删除。
8. 如果没有成员变更，返回 `NO_CHANGE`，不新增空 Rev；如果存在无法裁决的新增、重名、移除、来源顺序或多有效集归属，返回 `NEEDS_REVIEW` 并附原因。
9. 生成下一个 `rev_NNNN`（父链连续），先在内存中用 `_flat_views()` 与已有 Schema 校验，再调用现有 `publish_v2()` 发布，不自行写新格式。
10. 发布成功后刷新已有 EffectiveIndex、Latest 软链接与 `file_index.v3`；刷新失败不得回滚不可变历史，应明确返回 `PUBLISHED_INDEX_STALE`，使后续读取不把旧索引当最新。

### 4.3 独立模拟场景验收

以下七文件仅为模拟 fixture；真实 SRAM22 当前 Rev001 = 1、Rev002 = 2，不应强制扩充。

- V05 提供 LEF + FF/SS/TT Liberty + GDS + SPICE + Verilog，共 7 项。
- V06 仅提供 LEF 和 FF Liberty，完整 Rev002 应仍有 7 项：**2 项更新 + 5 项继承**。
- V07 不包含 LEF，不能自动把 LEF 从有效版本中删除。
- V08 新增某 Liberty：确认归属后自动加入；归属不明则阻断该候选项。
- V09 明确删除某 `file_key`：才可以生成缺失该成员的新 Rev；RAW 历史和旧 Effective 保留。
- 同一 Delivery 重放且目标完整成员无变化时不得生成重复 Rev；有明确的新成员决策时可以合法扩展，不同有效集各自判断。
- Existing `SOURCE_LIBRARY` owner 不因出现新 Delivery 自动变成 `BUSINESS_IP`。

**修改入口**：`application/effective_json.py`、`application/effective_publisher.py`、`application/latest_pointers.py`、`versions/index_projector.py`（优先复用不改投影语义）、`cli.py`、新 workflow 最多一个薄层。不要增设版本发布服务 / 队列 / 新 DB。

### 4.4 交付排除：排除“参与后续计算”，不删除交付历史

**必须先明确排除语义**：`EXCLUDED` 不是 RAW 不存在，也不是质检失败；它表示某个 **Delivery 不允许作为指定有效集后续自动计算的候选来源**。默认按 `set_id + delivery_id` 生效；只有用户明确选择“整个 SourceLibrary 全部有效集排除”时才扩大作用域。

建议最小持久承载：优先利用已有 `scan_sources.json` / 有效集配置中一份明确的 `excluded_delivery_ids` 或 `set_id → delivery_ids` 策略，配合**同 Library 的操作审计日志**记录变更（操作者、时间、原因、前后状态）。不要把排除记录写到 Delivery JSON、file_index RAW 时间线或 AcceptanceEvent 里；后者已有严格的采纳事件 Schema。

**检查规则**：
- 排除操作不删除 RAW Delivery、Formal、FileIndex RAW 出现历史；已有 Effective Revision 不回写。
- 一个已经被旧 Rev 采用的交付变为排除状态后，历史 Rev 仍能准确复现；后续计算不得默认继续选它作为更新来源。
- 排除被撤销后，重新执行 Preview，再依据当前有效父版本计算；不在旧 Rev 里修改成员。
- 当前最新有效版本如果已经引用被排除交付：系统应报告影响范围并要求明确选择“创建恢复性新 Rev”或“不操作历史”，不能暗中把当前成员改掉。
- 同一排除请求重复操作要幂等，错误 ID / 错误 scope / 权限不明均阻断。

**注意**：这是**建议实现规则**，并非仓库目前已有的交付排除功能。Codex 必须在 PR 中声明采用了哪个现有配置承载，不得暗加独立 authoritative JSON。

### 4.5 回退：明确两种完全不同的操作

| 操作 | 目的 | 已有可复用机制 | 不能做的事 |
|---|---|---|---|
| **已采纳版本回退** | 人工采纳从 Rev004 回到 Rev002 | `acceptance_event.v1` 的 `ROLLBACK`、`versions/index_projector.py` | 不生成新 Rev、不删除 Rev003/Rev004、不更改最新已计算 Rev |
| **有效文件组合恢复** | 计算侧从当前 Rev004 的采用文件恢复到 Rev002 的文件集合 | 以 Rev004 为 parent，创建新的 Rev005，成员复制 Rev002 | 不覆盖 Rev004、不破坏父版本链、不把恢复误写为采纳事件 |

第一版至少可靠实现“已采纳版本回退”；若实现第二种，必须在 CLI/Web 上命名为“基于历史 Revision 创建恢复版本”，并要求指定目标和说明原因，检查来源仍可访问 / 不存在被排除的冲突，按不可变发布途径生成新 Rev。

**请勿**把 `ACCEPT / ROLLBACK / REVOKE` 事件挪进 `runs.jsonl` 后抹掉原有采纳历史；可集中放在同一 Library 目录中，但它们的语义仍须独立。

---

## 5. P2：FileIndex 只读消费与真正统一的检查输入

### 5.1 冻结 `file_index.v3`，不设计 v4

保持：

```text
scope
├─ vendor / library
deliveries[]            真实交付身份、版本、来源根目录；完整业务顺序
formal_nl{nl}.snapshots[]  完整 Formal 父子快照顺序
effective_sets{set_id}.revisions[] 完整有效版本顺序
views{view}.files{path}  raw[] / formal[] / effective{set_id}[]
views{view}.unmatched_formal[]   未确认链接不丢失
```

遵守：不把文件名 `delivery_006.json` 作为业务 ID；三条时间线完整，按各自已确认顺序；Effective 每个 Rev 的完整采用成员必须可查询；不写最新/次新字段；不写 FileFacts、CheckResult、人工采纳。

### 5.2 修复查询时全量重建

现状 `LibraryDataQuery._verified_file_index()` 与 `v3_checks._setup()` 会重建归档投影来比较，`data-query --kind index-v3` 返回现算投影。这虽然正确性保守，但背离“后台先构建数据源，Web 和检查只读消费”。

分两段实施：

- **优先正确性**：保留 `refresh_library_index_locked()` 的全量归档重建和历史保护；只有显式刷新、归档发布后的同步、强制核验允许重建。仍不得重扫 RAW。
- **普通查询**：优先读取已发布 Index，校验必要结构和 Library 归属；依据归档清单变化检测 `VALID / STALE / INVALID / MISSING / ORDER_UNCONFIRMED`。状态不可靠时禁止执行检查，不得把过期 Index 伪装为有效。Web 展示可明确报告陈旧并提示刷新。
- 实现轻量 freshness 检查（只访问同库归档文件名与必要元信息，避免读取全部历史 JSON/RAW）。如果现有数据不足以可靠判断，请**先保留完整校验作为保护**，提交性能基线，再提出最少构建元数据方案；不得为了优化而牺牲一致性。
- 进程内缓存必须有明确失效条件（同库新 Delivery、Formal、Effective、排除策略变化），不能因 Flask 长驻而一直读到旧数据。
- 明确报表读出的 Index 快照版本与检查目标一致；检查前若源记录或 Index 被替换，要报并发变化，不继续输出伪造 PASS。

不要将“`APPEND` 返回值”写成已实现低复杂度增量。当前实现仍全量重建投影，应如实记录性能。

### 5.3 一个统一的 `get_check_context()`（仅内存，非新 JSON 契约）

建议入口：

```python
# 设计接口示意
context = query.get_check_context(
    vendor=vendor, library=library, set_id=set_id,
    revision='rev_0002', baseline='rev_0001',
    selected_views=None,
)
```

CheckContext 同时支持 SourceLibrary 和 BusinessIP；跨库来源必须按已归档来源范围定位。返回需要包含（可用 Python TypedDict/dataclass/普通 dict，Context 本身无需额外持久化）：

- `target`: owner、set_id、revision、parent、文件来源确定的范围；
- `selected_files[]`: 当前 Rev **所有实际采用文件**的 `view / logical key if confirmed / effective_path / source_scope / delivery_id / source_relative_path / absolute_path / file_id / identity_status / subtype or corner when available`；
- `baseline_files[]`: 指定基准完整文件成员；
- `source_changes[]`: `ADDED / REMOVED / SOURCE_CHANGED / UNCHANGED` 的**全成员**来源对照；
- `logical_matches[]`: 仅确认 file_key 后合并跨路径改名；未确认按 View+精确路径比较；
- `formal_refs[]`: 可关联的 Formal 快照及真实 `link_target`，缺匹配时保留原因；
- `unresolved[]`: 无法确认、来源缺失、路径不安全或可疑的成员，显式列出；
- `provenance`: 当前消费的 Index 来源 / 校验结果，不假装有新的内容验证。

**不得**返回 FileFacts、质量 PASS，也不要求把这个内存 context 另写 JSON。

### 5.4 单版本 / IP 检查共用一个选择器

- 对单个 Rev：从 CheckContext 选中适用文件，再执行已支持的 LEF Macro + LEF/Liberty 信号 Pin 规则；对未选择的文件输出 `NOT_CHECKED` / 覆盖范围，不输出 PASS。
- 对整个 BusinessIP：遍历该有效集所有 Rev，重复调用同一个选择器；合并 CheckResult，而不是创建另一套文件定位算法。
- 不要求用户为每个 Revision 手工复制同一批 `pin_pairs`；可基于已确认逻辑 file_key、Macro/Cell 归属、模型/Corner 属性提出候选，对多个可能 LEF/Liberty 对必须显式确认。**不猜 Corner 齐套，不把名称相似当真实配对**。
- 当前 `v3_checks._setup()` 只接受 `{pin_pairs: [...]} ` 且至少一对。扩展时保持这类旧 Profile 仍能运行；新模式可允许 `selected_views + inferred_candidates`，但不可静默启用新规则。
- 当前不支持新旧 Liberty 全内容比较，不能在 Excel 中表述为已检查。可另列下一迭代，优先确保来源组合 / Macro / Pin 结果完整可见。

### 5.5 Excel 的统计口径

分别列示：

1. **版本级文件来源变化**：整个 Rev 的 `SOURCE_CHANGED / ADDED / REMOVED / UNCHANGED`，来自 FileIndex/Effective；
2. **本次实际解析文件数量**：选取的 FileFacts 覆盖（去重）；
3. **本次确认的内容变化**：只针对已解析并比较的文件；
4. **质量检查结果**：PASS / FAIL / INCONCLUSIVE 及覆盖；
5. **整体 IP 完整性**：如果未覆盖全部必需规则，标为“未完成全面检查”，不能因脚本 SUCCEEDED 写成整体 PASS。

保留已有 `12-有效文件来源`、`13-版本来源对照`。改名导致的**路径增删**与**逻辑同一文件来源变化**要分栏或文字明确区分。

---

## 6. P3：统一单 Library 目录，不再产生冗余 Input Plan

### 6.1 目标布局（**仅新链路**，不强行迁移旧历史）

```text
work/libraries/<Vendor>/<Library>/
  delivery_001.json
  delivery_002.json
  latest_delivery.json              # 已有相对 symlink
  formal_<NL>_001.json
  latest_formal_<NL>.json           # 已有相对 symlink
  effective_<set>_001.json
  effective_<set>_002.json
  latest_effective.json             # 已有相对 symlink / 多集合既有命名
  effective_<set>_index.json       # 既存派生索引
  effective_<set>_acceptance.jsonl # 既存采纳事件，不能删
  file_index.json                  # file_index.v3
  facts_<facts_id>.json            # 经验证可跨 Run 复用的解析事实
  check_<run_id>.json              # 本次检查业务结论
  report_<run_id>.xlsx
  report_<run_id>.html
  overall_<run_id>.xlsx            # 需要时生成
  runs.jsonl                       # 本库新运行日志，必要的执行参数/状态
```

`latest_*` 具体命名兼容现有实现；多有效集不因为目标布局丢失各自 Latest。`facts_*`、`check_*` 不必再套 `file_facts/` 或 `runs/` 子目录。为了避免文件名冲突，命名可沿用项目实际规则，但**路径必须归属同一个 Library**。

### 6.2 已有功能兼容，分两步迁移

1. 新产物 writer 支持 Library 本地输出，Web/CLI 新入口使用新位置；旧 `runs/run_*/check.json` 通过 read adapter 仍可查看、下载，不迁移历史文件。
2. 报告 `render_report()` 和 `overall_excel` 只接收显式传入的文件/数据，不在渲染时临时扫描 RAW 或重建 Index。

### 6.3 运行日志与排除审计

- 检查须保存最小执行快照：实际选中文件、规则、目标和基线；可放在既有 `runs.jsonl` 或明确版本化的运行记录中，不要求另立独立 InputPlan 契约。若记录不足以复现，不得删除唯一依据。
- `runs.jsonl` 每次执行至少记录 `run_id / kind / target / baseline / profile_or_ruleset / start_at / end_at / state / error / check_result`；可采用 START/END 事件，但不要为同一事实再复制多份 JSON。
- 排除策略修改记录 actor、reason、目标、结果、操作时间；**不要混入 AcceptanceEvent**，已有 `ROLLBACK` 语义是采纳回退。
- 失败运行不能生成假的 CheckResult PASS；部分已产生的文件保留可诊断，但明确标记不完整。
- 日志写入遵守单库锁或安全 append（原子单行 + fsync），并可验证重复 Run ID。

### 6.4 FileFacts 持久复用

先保证单次 Run 的事实复用；跨 Run 持久复用只在来源、解析器和文件稳定性证据可靠时启用，不得只用 `file_id` 或路径命中。

推荐复用键至少覆盖：

`Vendor + SourceLibrary + DeliveryID + FileID + Parser名称/版本 + 输入文件稳定性证据`。

- 对同一次来源、相同解析器、已验证未变化文件可复用已有 Facts；
- 无可信文件稳定性证据时不可宣称缓存长期有效；可重新解析并记录限制；
- `size/mtime` 一致不代表字节完全相同，不要编造内容哈希，也不要求对整库 hash；
- 不重复写同一可复用 Facts，报告通过 `facts_id` 引用；
- FileFacts 仍是一份源文件对应的一份解析事实，不进入 `file_index.json`。

---

## 7. P4：必须完成的验收用例

### 7.1 核心数据与版本演化

| ID | 测试 | 通过标准 |
|---|---|---|
| T01 | 7 文件 V05 + 部分 V06 | Rev002 有 7 成员：2 来源变化、5 继承 |
| T02 | V07 不含 LEF | LEF 继续保留在有效版本，不误删除 |
| T03 | V08 新增明确归属 Liberty | 新文件被正确加入，旧文件保留 |
| T04 | V08 新文件归属不明 | Preview 返回待确认，RAW/FileIndex 仍包含历史 |
| T05 | 明确删除 file_key | 只有确认的删除才影响新 Rev，不改旧 Rev |
| T06 | 相同 Delivery 重放 | 不重复产生 Effective Rev / FileIndex occurrence |
| T07 | 同名供应商版本的两次交付 | 使用真实 Delivery ID 区分；排序无法确认则阻断自动应用 |
| T08 | 未确认业务交付顺序 | 不按扫描时间或自然排序推断最新 |
| T09 | 有 Formal 基准与没有 Formal | 两类初始建库都能运行；不把 RAW-first 伪装为 Formal |
| T10 | 同库多个有效集 | 分别计算互不覆盖；不会强制绑定 BusinessIP |
| T11 | 跨库被确认采用的文件 | source_scope/source_path 正确，不伪装本库 RAW |
| T12 | 已发布 Rev 与原父链 | 历史不可变；新版本序号、parent 正确 |

### 7.2 排除、回退、历史不可变

| ID | 测试 | 通过标准 |
|---|---|---|
| T13 | 排除 Delivery V06 | RAW 历史不丢，后续候选跳过 V06 |
| T14 | 排除影响当前 Rev 已采用源 | 清楚报告影响，不静默修改旧 Rev |
| T15 | 撤销排除 | 可重新 Preview，重复操作幂等 |
| T16 | 采纳 Rev004 后 ROLLBACK Rev002 | AcceptanceEvent 回放后 accepted=Rev002，最新 calculated Rev004 保留 |
| T17 | 恢复旧文件组合 | 新 Rev005 parent=Rev004、成员可复制 Rev002；Rev001~004 不变 |
| T18 | 非法回退目标 / 重复事件 | 明确拒绝并保留原索引/采纳历史 |

### 7.3 统一索引、查询和检查

| ID | 测试 | 通过标准 |
|---|---|---|
| T19 | V01 有 LEF、V02/V03 无、V04 有 | 完整时间线 V04→V01；可以任选历史项，非最新/次新限定 |
| T20 | 已确认同一 file_key 发生改名 | 逻辑比较归为同一文件；路径变化仍可查询 |
| T21 | 未确认改名 | 不伪造逻辑同一性，显示独立路径/不确定 |
| T22 | Formal 链接路径与 RAW 不一致 | 保留 unmatched、link_target 原值，不丢文件、不报已确认匹配 |
| T23 | 正常 Formal 路径匹配 | 只报告归档路径可关联，不报告当前软链接/内容已验证 |
| T24 | 新 Delivery 发布但 Index 刷新中断 | Index 标 STALE，刷新从权威记录恢复，不扫描 RAW |
| T25 | 历史归档损坏或引用缺失 | 拒绝覆盖已发布索引，显示错误并可按流程显式修复 |
| T26 | CLI / Web 对同一个 Rev 和 Index | 文件清单、来源关系和差异口径一致 |
| T27 | 单 Rev 选择检查 | 取该有效集实际完整成员；七文件只用于模拟，仅选定部分才解析；未选不算 PASS |
| T28 | 整 IP N 个 Rev | 复用单 Rev Context；失败和未覆盖在整体 Excel 中可见 |
| T29 | 新旧 Liberty 未比较 | Excel 不宣称 Liberty 内容相同或已覆盖 |
| T30 | 单次 Run & 多 Run FileFacts | 身份+解析器+稳定性正确命中；来源变化或未验证不错误复用 |

### 7.4 统一目录与安全性

| ID | 测试 | 通过标准 |
|---|---|---|
| T31 | 新检查产物位置 | 全部位于对应 `work/libraries/Vendor/Library/`，不产生新的独立根 runs 业务目录 |
| T32 | 旧 runs 与 report 兼容 | 历史下载、查看不受影响，不删除旧文件 |
| T33 | 路径遍历 / 软链接越界 | 禁止文件读写越出选定 Library 或 RAW 来源作用域 |
| T34 | 两进程同时发布 | 现有 Library 锁生效，无重复 Rev / 部分 Index / 部分覆盖 |
| T35 | 测试环境干净克隆 | 新测试不依赖私有 `work/` 或未提交模拟目录；fixture 在 `tempfile` 中生成 RAW |
| T36 | 文件内容在解析中变化 | 不输出伪造 CheckResult；保留失败诊断 |

### 7.5 性能基线（必须有数字，暂不规定虚假阈值）

使用模拟规模与至少一个经允许的真实库，测量：

- 仅检查 Index 状态 / 读已发布 Index 耗时；
- 显式重新构建 Index 耗时；
- 交付追加后同步刷新耗时；
- 单 Rev 生成文件上下文耗时；
- 单次 IP 多 Rev 报告耗时，解析时间单独列出；
- 是否因打开 Web 页面触发 RAW 扫描（应为 **0 次**）。

**不要**在没有数据时宣称 O(1) / O(delta) 增量、毫秒级响应或生产性能已验收。

---

## 8. 修改建议按文件落实

| 文件 | 主要工作 | 必须保持的兼容性 |
|---|---|---|
| `sources/classifier_adapter.py`、`registration.py` | 身份确认入口与可审计映射 | 不把候选变确认；原 Evidence / Delivery 可读 |
| `sources/auto_ingest.py` | 新交付后触发 Effective Preview/受控计算 | RAW-first；不静默 FULL/删除；索引失败可恢复 |
| `application/effective_json.py` | 基于父版本完整继承、明确替换/新增/删除；可复用已有函数 | `effective.simple.v2`、连续 parent、旧归档不可变 |
| `application/effective_publisher.py` | 发布的锁/幂等/Latest/Index 一致性处理 | `publish_v2()` 原入口与已保存版本规则 |
| `application/file_index_v3.py` | 保证三类来源完整、跨库 scope、未匹配保留 | 不改成 v4，Index 可重建 |
| `application/file_index.py` | 统一刷新入口、顺序、异常后恢复、减少旧 v2 CLI 误用 | 已有相对 latest 链接、安全规则 |
| `application/data_query.py` | `get_check_context()`、正常读已发布 Index、状态校验 | CLI/Web/旧查询结果兼容，避免查询时写源文件 |
| `application/v3_checks.py` | 共用检查输入选择器，自动候选但阻断歧义，输出集中 | 老 Profile 能跑；质量覆盖结论准确 |
| `versions/index_projector.py` / `store.py` | 复用 ACCEPT/ROLLBACK/REVOKE；新恢复性 Rev 仍走发布 | 不扩展 acceptance schema 到交付排除 |
| `reporting/workbook_model.py`、`overall_excel.py` | 版本来源统计 vs 检查范围统计分开，目录位置 adapter | 已有工作表/Macro/Pin 证据不丢 |
| `workbench/app.py` / 模板 | 索引状态、Preview/发布/排除/回退明确操作、旧 report 下载兼容 | CSRF、危险操作显式确认、权限、无隐式写入 |
| `cli.py` | 文件索引刷新、Preview/Apply、采纳回退、Run 命令可脚本化 | `tcsh/csh` 用户可用 `python3 -m ai_lib_qor ...`，不强迫更换登录 shell |

**请先定位现有类/函数再改；本文件里的新函数名仅为建议接口，不要求机械创建同名文件。**

## 9. Codex 实施方式与提交要求

### 9.1 在动手前

1. 在 `codex/ai-lib-qor-workbench` 检查 `git status --short`、`git rev-parse HEAD`，确认以 `c1f845f` 为可追踪基线；若 HEAD 已前进，先列出新增差异再调整实施计划，**不得覆盖他人提交**。
2. 列出已有 CLI、Schema、有效集/采纳入口、Web 下载路径、相关 tests；标记本文建议功能中实际已经具备的部分，禁止重复实现。
3. 执行原有测试（记录总数、通过、跳过、失败、环境依赖）；仓库模拟目录不包含 RAW 源文件时，用 `tempfile` 固定 fixture，不依赖历史本机绝对路径。
4. 输出一张“已实现 / 部分 / 未实现”表作为 PR 开始基线，不能把本文的规划文字称为已实现。

### 9.2 每阶段必须输出

- 新增/修改文件清单、调用链和数据流示意；
- 对应业务规则和最小测试；
- 当前保留的兼容适配器及理由；
- 执行的**真实命令**、输出的通过/跳过数量；
- 模拟与真实数据分别说明；
- 已知不支持的 View、Parser 和检查规则；
- 可恢复失败情形和需要人工确认的分支。

### 9.3 推荐命令（按项目实际依赖调整，不要伪造输出）

```bash
# 在 ai_lib_qor 目录，从 shell 直接执行；tcsh 也可用 env 传递变量
env PYTHONPATH="$PWD/src:$PWD/../src" python3 -m unittest discover -s tests -p 'test_*.py'

# 显式刷新同一 Library 的 v3 Index
python3 -m ai_lib_qor file-index-refresh --work "$WORK" \
  --vendor "$VENDOR" --library "$LIBRARY"

# 查询时只读权威已发布索引/一致的读模型
python3 -m ai_lib_qor data-query --work "$WORK" \
  --kind index-v3 --vendor "$VENDOR" --library "$LIBRARY"
```

新增 `effective-preview` / `effective-apply` / `delivery-exclude` / `acceptance-rollback` 等命令名称为**拟议接口**，不要假装当前 CLI 已存在。实施时保持命名简洁，输出可机器读取的 JSON，并在既有运行记录中保存最小实际选择依据。

### 9.4 明确禁止事项

- 不重命名或清理历史 Delivery/Formal/Effective，不强推 `main`，不破坏已有合法分支数据。
- 不把 `file_index.json` 当新的权威记录，不通过修改 Index 实施交付排除或有效版本回退。
- 不把 `RESOLVED/CANDIDATE` 自动升级为 `CONFIRMED`，不以文件名猜 Macro/Pin/Corner 同一性。
- 不因为 V06 缺失五个文件就认为全量包删除；不自动删除历史文件。
- 不把 `SUCCEEDED` 当质量 PASS，不把少量 LEF/Liberty 检查当完整 IP 验收。
- 不每次打开网页全量重扫 RAW、解析全部文件或生成新的业务报告。
- 不新增多个候选清单、查询快照、InputPlan、RunStatus 等权威 JSON 来替代现有五类数据。
- 不一次删除 Evidence / v1/v2 兼容代码；任何移除必须有全量回归与迁移数据证明。
- 不先追求复杂增量算法。**正确性、可恢复与可复现优先于“增量”名称。**

## 10. 最终验收 Gate（必须逐项回答 YES/NO/UNKNOWN）

| Gate | 必答问题 | 达标 |
|---|---|---|
| G1 | 真实交付能够产生稳定、可解释的文件身份吗？ | 选定真实 LEF/Liberty 成功，未知身份不伪造 |
| G2 | 新交付自动生成了完整而不是只有变化文件的有效 Rev 吗？ | 7→7，2 更新 / 5 继承，用归档证据复现 |
| G3 | 排除交付不破坏 RAW/Formal/Effective 历史吗？ | 可审计、可取消、无隐式删除 |
| G4 | 采纳回退和文件组合恢复是否正确区分？ | AcceptanceEvent 与新 Revision 两条语义独立 |
| G5 | Index 是否由三类权威记录共同构建、可重建、不可伪造最新？ | 归档不完整即阻断，三条历史完整 |
| G6 | Web/CLI 正常读取是否不触发 RAW 扫描、不无故重建索引？ | 有真实调用计数与性能对比 |
| G7 | 单 Rev/IP 检查是否真正共用同一 Context 与算法？ | 同一 Rev 的输入、检查覆盖、报表一致 |
| G8 | 新 FileFacts/CheckResult/Excel 是否集中到 Library 目录？ | 无新独立业务根目录；旧路径仍可读 |
| G9 | 是否干净克隆可复现而非依赖内网本机路径？ | 隔离 fixture 测试通过、跳过明确 |
| G10 | 是否完成真实 RAW 与 Formal 路径验证和人工 Excel 验收？ | 提供真实证据；若尚无则填 UNKNOWN，不可谎称完成 |

**最终交付**：PR/commit 列表 + 测试证据 + 一份干净环境模拟验收结果 + 至少一条可允许的真实库小范围验收记录 + 未完成事项清单。若只实现 P0/P1，应明确说明“仅核心有效版本自动化完成”，不得宣称整个 ai_lib 生产级闭环已完成。
