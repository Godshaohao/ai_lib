# ai_lib · file_index.v3 设计原稿（讨论版）

> 对照 `/mnt/data/file_index(2).json` 中的 RAW 时间线，以及 SRAM22 已讨论的两份 `effective.simple.v2` 和历史 `FormalSnapshot`。本说明对应 `file_index_v3_设计原稿_SRAM22.json`。**样本包含模拟 V06；Formal 使用历史快照，不是对模拟目录重新扫描。** `file_index.v3.draft` 仅为原稿标识，尚未实现成生产 Schema。

## 1. 定位与文件放置

- 一个 SourceLibrary 一份 `work/libraries/<vendor>/<library>/file_index.json`。
- 唯一派生查询索引：输入是同库的多次 Delivery、多次 Formal Snapshot、多次 Effective Revision，不把已有权威记录替换掉。
- 完整文件来源关系：RAW 的“出现”，Formal 的“实际链接”，Effective 的“采用”，**三条独立时间线**。
- 不保存 FileFacts/CheckResult、Macro/Pin 值、检查 PASS/FAIL，也不保存重复的 latest、next、`status`、`basis`。
- `file_index` 可以大，但不重复保存每一份 Delivery 的所有原始字段；重点保存下游需要的完整路径定位、引用及历史关系。

## 2. 顶层字段与数组元素

| 路径 | 结构/元素 | 说明 |
|---|---|---|
| `schema` | string | 当前示例 `file_index.v3.draft` |
| `scope` | `{vendor,library}` | 一个 SourceLibrary 的归属范围 |
| `deliveries[]` | object | **从新到旧**的完整已确认交付序列，元素 `delivery_id`（真实内部身份，不是 JSON 文件名）、`version`（供应商版本文字）、`root`（当时归档的 RAW 根目录）、`recorded_at`（仅供展示，不用于业务排序） |
| `formal_nl[NL].snapshots[]` | object | 每个 NL **沿可确认的父子链从新到旧**；`snapshot_id`、`parent`、`root`、`observed_at`、`coverage`；`PARTIAL` 不代表不存在的文件已删除 |
| `effective_sets[set_id]` | object | `owner` 为 `SOURCE_LIBRARY` 或 `BUSINESS_IP`；一个 Library 可有多个有效集合 |
| `effective_sets[set_id].revisions[]` | object | **从新到旧**，元素 `revision`、`parent`；真正采用的文件全集在下方每个文件的 `effective` 时间线中（含继承未变化的成员） |
| `views[VIEW].files` | map | 键为 **RAW 相对路径**；这样在文件发生改名时可保留两段物理历史，并使用已确认 `file_key` 将它们关联查询 |
| `views[VIEW].files[path].model` | string, optional | 仅在源分类足以确定时使用，例如 Liberty 的 `NLDM`；不猜测复杂 Corner/PVT |
| `views[VIEW].files[path].raw[]` | object | **从新到旧**的每次实际出现；`delivery_id`、`file_id`、`file_key`（可为空）、`classification`，以及实际存在的 `corner`/`mode` |
| `views[VIEW].files[path].formal[]` | object | **从新到旧**的已匹配 Formal 链接；`nl`、`snapshot_id`、`link_path`、`link_target`、`resolved_path`、`source_match`、`raw_source{delivery_id,file_id}`；只在确实匹配成功时挂在 RAW 文件下 |
| `views[VIEW].files[path].effective[set_id][]` | object | 按对应有效集 Revision 从新到旧，元素 `revision` 和 `delivery_id`；**每个 Rev 的全部采用文件**都应出现，不只是改变文件 |
| `views[VIEW].unmatched_formal[]` | object, optional | 记录属于本 Library、但未唯一匹配某 RAW 文件的正式链接：`nl`、`snapshot_id`、`link_path`、`link_target`、`resolved_path`、`source_match`；不得凭路径相似性强行合并 |

**只在引用身份被确认后建立关联。** `file_key` 为 `null` 并不意味没有文件，它仍在 `raw[]`。但 `file_key=null` 不应被冒充已确认逻辑文件位。

## 3. 数据如何被消费

1. **RAW 历史**：选择 `views[view].files[path].raw`，用 `delivery_id` 找 `deliveries[]`，得到版本及 `root/path`；可以选择时间线上任意两个出现记录。
2. **Formal 对照**：读取 `formal_nl[NL].snapshots` 和每个文件的 `formal[]`；未确认匹配的链接在 `unmatched_formal[]`；从 `link_target` 与 `resolved_path` 看真实观察，不因 `source_match=UNMATCHED` 直接声称源文件不存在。
3. **单有效版本检查**：选择 `(set_id,revision)`，遍历 `views[*].files[*].effective[set_id]` 中匹配的 Revision，获得当前全部文件；其关联的 `(delivery_id,view,path)` 决定可解析文件的输入，不需要另存 InputPlan JSON。
4. **A/B Revision 比较**：分别收集完整集合，按已确认逻辑 `file_key`，否则按 `(view,path)` 对齐，输出 ADDED/REMOVED/SOURCE_CHANGED/UNCHANGED；输出属于查询结果，而非另一份权威文件。
5. **IP 检查**：选择 BusinessIP 所属的一个或多个有效集，遍历其各 Revision 复用同一查询。检查规则和启用范围仍从配置取得，FileFacts 由 Parser 按需解析，CheckResult 保存检查结果。
6. **文件改名**：默认不同物理路径，`file_key` 经确认一致时，查询层合并**逻辑**时间线；没有确认时不擅自将两个不同文件视为同一对象。

## 4. 精简但重要的完整性规则

- `deliveries[].delivery_id` 在本 `scope` 内唯一，数组顺序是**经过业务规则确认**的顺序；不能按到达时间、文件编号擅自推断。排序无法确认时可保留原始 Delivery，但**不得发布虚假的有序 Index**。
- `raw[]` 中每个 `delivery_id` 必须存在于相同库的 `deliveries[]`，每条 `(view,path,delivery_id)` 在历史中最多出现一次。
- `formal[]` 中的 `snapshot_id` 必须属于对应 `nl` 的快照列表；`raw_source` 与同节点 `raw[]` 的 `(delivery_id,file_id)` 完全对应。Formal 路径不是 RAW 路径：`IP/LEF/a.lef` 可以链接 `LEF/a.lef`。
- `effective` 中每个 `revision` 必须在同名 `effective_sets[set_id].revisions[]` 中；选定一份 Revision 时，扫描全索引获得的文件集合须与权威 EffectiveVersion 的全集相同，**不能只取变化文件**。
- 对单份文件的 `raw`、`formal`、`effective` 时间线分别有序；不能把三个源不同含义的时间戳统一排序。
- 真实交付 ID 与归档文件名可能不同，如 `delivery_fe933...` 与 `delivery_005.json`；统一索引要将后者解析到前者，且有重复/歧义时停止发布，不能把归档别名当成逻辑 ID。
- `raw.source_root` 和 `formal.root` 属于当时的路径事实；文件当前是否可读，需运行检查时核验，不能从记录推断。
- `root` 为历史真实绝对路径，跨机器克隆仅能查询历史关系，不能保证直接访问文件。不可通过指针转换假装历史 RAW 内容仍可重现。
- 同名供应商版本可能对应不同交付；只能由真实 `delivery_id` 区分，绝不能仅按版本文字合并。
- **跨库 BusinessIP**：在 Home Library 的有效集可以引用外库文件；正式实现需为这类有效条目增加可选 `source_scope{vendor,library}` 与 `source_path`，并由统一查询读取来源库索引；本 SRAM22 单库示例没有跨库数据，故不造虚假样例。

## 5. 增量更新与故障恢复

- RAW 新交付：在既有 Library 锁内发布不可变 Delivery，验证新交付序列是否可在头部追加；增量更新 `deliveries` 及实际包含文件的 `raw[]`，未出现的文件历史不删除。
- 新 Formal Snapshot：追加相应 NL 的 `snapshots` 和此快照中的 Formal 引用；对 `coverage=PARTIAL` 的快照，不得把未观察到的链接解释成删除。
- 新 Effective Revision：追加 `revisions`，并**对其全部采用成员**在 `effective[set_id][]` 中追加引用，未变化文件也要出现；版本无变化时不生成新 Rev。
- 人工重排顺序、历史损坏、来源归属修复：从已归档的 Delivery、Formal、Effective 全部 JSON 重建 Index；不重扫历史 RAW。
- 同一内容重复导入/重复运行必须幂等，原有出现事件不重复插入。
- 统一使用 `versions.store.locked()` / `write_atomic()` 或现有项目同等功能；只能原子替换**单个** Index 文件，不能承诺 Delivery + Formal + Effective + Index + Latest 的跨文件事务。
- 来源历史发布成功但索引更新失败：查询不得静默使用过期 Index；通过已归档历史的身份集合与索引目录比对进行恢复或明确失败；Run 日志记录原因。
- 建议先采取“从已归档 JSON 重建 + 原子替换”确保正确性，测试通过后再引入真实增量合并优化，避免早期同时维护两套有差异的算法。

## 6. 此原稿刻意不包含

- 单独 `latest`/`next` 数组、`status`/`basis`、人工采纳事件、扫描 Evidence、日志、InputPlan、Macro/Pin、FileFacts、CheckResult。
- “所有 Corner 已齐套”的判断；仅记录已有文件的分类/Corner。
- 将 Formal 的 `UNMATCHED` 静默变成 `MATCHED_RAW`，或把历史快照重新解释成针对模拟 RAW 目录实际重扫过。

## 7. 本次完整样例校验（静态关系检查）

- RAW：2 次交付，7 个唯一文件路径，9 条文件出现记录。
- Formal：1 个 NL Snapshot，4 条已匹配 RAW 的链接和 3 条保留为未匹配的链接。
- Effective：1 个有效集、2 个 Revision，每个 Revision 均包含 7 份采用文件，合计 14 条采用关系。
- 对比：Rev001→Rev002 中 LEF 与 Liberty FF 的采用来源变化，其他 5 份继承 V05。

**原稿尚未与 GitHub `5f5c8ee` 自动构建/读取代码接通，也不是生产验证结果。**
