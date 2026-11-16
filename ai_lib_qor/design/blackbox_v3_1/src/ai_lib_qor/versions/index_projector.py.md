# versions/index_projector.py · 设计伪代码

> **拟议，非可执行代码。** 以下接口名、内部结构和错误策略供评审，不声称当前已实现。

- **职责**：计算有效集查询指针。
- **接口**：`project(revisions, events, owner) → EffectiveIndex`
- **输入**：已发布版本与可重放采纳事件。
- **输出**：v3 effective_index.v1 候选。
- **配置 / 依赖**：事件顺序、回退和重放规则待确认。

## 算法与处理顺序

```text
过程 project(revisions, events, owner) → EffectiveIndex
    依据已确认排序计算 latest_calculated_revision；按已确认事件语义计算 current_accepted_revision；保持两者独立
    返回上述输出或明确失败
```

## 异常与边界

规则不明或历史冲突停止更新，不猜测采纳状态。所有正式业务记录仅通过统一 Publisher 或其事件追加入口发布；本文件只有设计内容。

## 对应 v3 JSON 字段与术语

下列字段是本模块**读取、贡献或校验的范围**，并不表示该模块独立写入整份 JSON。字段必需性来自 v3 文档；完整结构及示例见对应字典。

### [EffectiveIndex 字段字典与完整示例](../../../contracts/index.md)

| 字段 | 适用 / 必需性 | 类型 | 中文含义与边界 |
|---|---|---|---|
| `effective_set_id` | 是 | string | 该索引属于哪套有效文件集合 |
| `owner.owner_type / owner.owner_id` | 是 | enum/string | 业务 IP 或无归属 SourceLibrary |
| `owner.home_source_library_id` | 是 | string | 权威 Rev 的唯一保存位置 |
| `latest_calculated_revision` | 是 | string/null | 当前最新**计算成功并发布**的 Rev |
| `current_accepted_revision` | 是 | string/null | 当前已采纳 Rev；可落后于最新计算，未启用采纳时为 null |
| `updated_at` | 是 | ISO 时间 | 最近一次索引切换时间 |

### [AcceptanceEvent 字段字典与完整示例](../../../contracts/acceptance.md)

| 字段 | 适用 / 必需性 | 类型 | 中文含义与边界 |
|---|---|---|---|
| `action` | 是 | enum | ACCEPT/ROLLBACK/REVOKE；对应界面“采用/回退/撤销采用” |
| `revision_id` | 是 | string | 作用于哪个固定 Rev |
| `acted_at` | 是 | ISO 时间 | 决策发生时间 |

术语和 source_ref 的完整定义见[中英文术语表](../../../contracts/术语表.md)。

## 本脚本交付的完整 v3 候选示例

下列内容逐字来自 v3 合成示例；它是经组装后的业务记录格式，实际发布须通过 Schema 与跨记录验证。

```json
{
  "schema_version": "effective_index.v1",
  "effective_set_id": "rtavfs_primary",
  "owner": {
    "owner_type": "BUSINESS_IP",
    "owner_id": "rtavfs",
    "home_source_library_id": "lib_rtavfs"
  },
  "latest_calculated_revision": "rev_0002",
  "current_accepted_revision": "rev_0001",
  "updated_at": "2026-10-20T11:05:00+08:00"
}
```
