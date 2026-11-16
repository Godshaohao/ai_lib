# application/accept.py · 设计伪代码

> **拟议，非可执行代码。** 以下接口名、内部结构和错误策略供评审，不声称当前已实现。

- **职责**：组织业务采纳或回退。
- **接口**：`accept(config, set_id, revision_id, actor, action, reason) → EventRef`
- **输入**：授权主体、动作、目标 Rev 和原因。
- **输出**：实际采纳事件及投影更新结果。
- **配置 / 依赖**：ownership、身份和授权来源由部署确认。

## 算法与处理顺序

```text
过程 accept(config, set_id, revision_id, actor, action, reason) → EventRef
    核验授权与目标引用；构造唯一事件；经单写入口追加；重放事件形成有效索引并更新
    返回上述输出或明确失败
```

## 异常与边界

事件追加成功而索引更新失败须返回可恢复状态；幂等与并发策略在实施前确定。所有正式业务记录仅通过统一 Publisher 或其事件追加入口发布；本文件只有设计内容。

## 对应 v3 JSON 字段与术语

下列字段是本模块**读取、贡献或校验的范围**，并不表示该模块独立写入整份 JSON。字段必需性来自 v3 文档；完整结构及示例见对应字典。

### [AcceptanceEvent 字段字典与完整示例](../../../contracts/acceptance.md)

| 字段 | 适用 / 必需性 | 类型 | 中文含义与边界 |
|---|---|---|---|
| `event_id` | 是 | string | 采纳事件唯一 ID |
| `effective_set_id` | 是 | string | 被决定的有效文件集 |
| `action` | 是 | enum | ACCEPT/ROLLBACK/REVOKE；对应界面“采用/回退/撤销采用” |
| `revision_id` | 是 | string | 作用于哪个固定 Rev |
| `acted_at` | 是 | ISO 时间 | 决策发生时间 |
| `actor` | 是 | string | 作出决策的责任人/角色 |
| `reason` | 是 | string | 业务理由，不是 Parser 检查状态 |

### [EffectiveIndex 字段字典与完整示例](../../../contracts/index.md)

| 字段 | 适用 / 必需性 | 类型 | 中文含义与边界 |
|---|---|---|---|
| `latest_calculated_revision` | 是 | string/null | 当前最新**计算成功并发布**的 Rev |
| `current_accepted_revision` | 是 | string/null | 当前已采纳 Rev；可落后于最新计算，未启用采纳时为 null |

术语和 source_ref 的完整定义见[中英文术语表](../../../contracts/术语表.md)。
