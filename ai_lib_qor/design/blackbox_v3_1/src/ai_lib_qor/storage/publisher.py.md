# storage/publisher.py · 设计伪代码

> **拟议，非可执行代码。** 以下接口名、内部结构和错误策略供评审，不声称当前已实现。

- **职责**：验证并发布业务记录。
- **接口**：`publish(candidate, schema, refs, destination) → PublishedRef`
- **输入**：候选对象、v3 Schema、跨记录引用、目标路径。
- **输出**：固定产物引用或已更新投影。
- **配置 / 依赖**：work_root、已确认 Schema、发布策略。

## 算法与处理顺序

```text
过程 publish(candidate, schema, refs, destination) → PublishedRef
    校验 Schema 和跨记录关系；先写临时文件并核验，再按文件系统支持的方式发布；历史记录不可覆盖；索引单独切换
    返回上述输出或明确失败
```

## 异常与边界

并发/崩溃/部分提交需要明确锁与恢复机制；事件追加与索引更新的幂等规则待确认。所有正式业务记录仅通过统一 Publisher 或其事件追加入口发布；本文件只有设计内容。

## 发布协议（伪代码）

```text
validate_schema(candidate); validate_cross_refs(candidate)
获得目标对象的并发协调（具体方式待部署文件系统确认）
if 目标固定历史 ID 已存在:
    if 内容完全一致: 返回已有引用（幂等）
    else: 冲突并拒绝覆盖
在目标文件系统写临时文件并校验写入结果
按已验证的文件系统原子语义发布固定记录
必要时独立地重建并替换索引
返回已发布身份；若索引失败，返回固定记录成功/索引失败以便恢复
```

该协议是要求，不证明跨文件事务已实现。采纳事件的追加与索引切换不是天然原子操作：需要重放事件、去重与恢复方案。

## 对应 v3 JSON 字段与术语

下列字段是本模块**读取、贡献或校验的范围**，并不表示该模块独立写入整份 JSON。字段必需性来自 v3 文档；完整结构及示例见对应字典。

### [DeliveryRecord 字段字典与完整示例](../../../contracts/delivery.md)

| 字段 | 适用 / 必需性 | 类型 | 中文含义与边界 |
|---|---|---|---|
| `delivery_id` | 是 | string | 单次交付唯一；不得简单等于供应商的 V08 |

### [FormalSnapshot 字段字典与完整示例](../../../contracts/formal.md)

| 字段 | 适用 / 必需性 | 类型 | 中文含义与边界 |
|---|---|---|---|
| `formal_snapshot_id` | 是 | string | 固定状态 ID，历史版本引用它 |

### [EffectiveVersion 字段字典与完整示例](../../../contracts/effective.md)

| 字段 | 适用 / 必需性 | 类型 | 中文含义与边界 |
|---|---|---|---|
| `effective_set_id` | 是 | string | 有效文件集标识；默认一个 IP 一套 |
| `revision_id` | 是 | string | `rev_0001`、`rev_0002`，只在当前 Effective Set 内有序 |

### [CheckResult 字段字典与完整示例](../../../contracts/check.md)

| 字段 | 适用 / 必需性 | 类型 | 中文含义与边界 |
|---|---|---|---|
| `check_run_id` | 是 | string | 在目标目录下唯一，允许 `run_001`、`run_002` 重跑 |

### [EffectiveIndex 字段字典与完整示例](../../../contracts/index.md)

| 字段 | 适用 / 必需性 | 类型 | 中文含义与边界 |
|---|---|---|---|
| `latest_calculated_revision` | 是 | string/null | 当前最新**计算成功并发布**的 Rev |
| `current_accepted_revision` | 是 | string/null | 当前已采纳 Rev；可落后于最新计算，未启用采纳时为 null |

### [AcceptanceEvent 字段字典与完整示例](../../../contracts/acceptance.md)

| 字段 | 适用 / 必需性 | 类型 | 中文含义与边界 |
|---|---|---|---|
| `event_id` | 是 | string | 采纳事件唯一 ID |
| `action` | 是 | enum | ACCEPT/ROLLBACK/REVOKE；对应界面“采用/回退/撤销采用” |
| `revision_id` | 是 | string | 作用于哪个固定 Rev |

术语和 source_ref 的完整定义见[中英文术语表](../../../contracts/术语表.md)。
