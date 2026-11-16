# versions/acceptance.py · 设计伪代码

> **拟议，非可执行代码。** 以下接口名、内部结构和错误策略供评审，不声称当前已实现。

- **职责**：构造采纳事件。
- **接口**：`prepare_event(set_id, revision, action, actor, reason) → AcceptanceEvent`
- **输入**：存在的版本、授权主体和决定。
- **输出**：v3 acceptance_event.v1 候选。
- **配置 / 依赖**：身份、授权与动作规则。

## 算法与处理顺序

```text
过程 prepare_event(set_id, revision, action, actor, reason) → AcceptanceEvent
    验证版本归属与动作；构造事件唯一 ID、时间和原因；交给单一事件写入入口
    返回上述输出或明确失败
```

## 异常与边界

无授权或无此版本拒绝；不因 PASS 自动写入。所有正式业务记录仅通过统一 Publisher 或其事件追加入口发布；本文件只有设计内容。

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

术语和 source_ref 的完整定义见[中英文术语表](../../../contracts/术语表.md)。

## 本脚本交付的完整 v3 候选示例

下列内容逐字来自 v3 合成示例；它是经组装后的业务记录格式，实际发布须通过 Schema 与跨记录验证。

```jsonl
{"schema_version": "acceptance_event.v1", "event_id": "accept_0001", "effective_set_id": "rtavfs_primary", "action": "ACCEPT", "revision_id": "rev_0001", "acted_at": "2026-09-11T14:00:00+08:00", "actor": "ip_owner", "reason": "初始正式基线核对完成"}
```
