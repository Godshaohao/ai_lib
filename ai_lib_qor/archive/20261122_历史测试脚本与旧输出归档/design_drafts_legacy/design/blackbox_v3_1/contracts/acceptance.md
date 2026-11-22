# AcceptanceEvent · v3 字段字典与完整示例

> 设计契约和合成数据；表格来自 v3 逐字段确认表，不代表已完成业务确认。`是` / `LEF` / `Liberty` 原样保留，条件必需性需结合对应 Schema 验证。

| 字段路径 | 必需性 / 适用视图 | 类型 | 含义和检查要点 |
|---|---|---|---|
| `schema_version` | 是 | string | `acceptance_event.v1` |
| `event_id` | 是 | string | 采纳事件唯一 ID |
| `effective_set_id` | 是 | string | 被决定的有效文件集 |
| `action` | 是 | enum | ACCEPT/ROLLBACK/REVOKE；对应界面“采用/回退/撤销采用” |
| `revision_id` | 是 | string | 作用于哪个固定 Rev |
| `acted_at` | 是 | ISO 时间 | 决策发生时间 |
| `actor` | 是 | string | 作出决策的责任人/角色 |
| `reason` | 是 | string | 业务理由，不是 Parser 检查状态 |

## 完整合成示例

来源：`ai_lib_qor_contract_v3/examples/work/vendors/vendor_orion/libraries/lib_rtavfs/ips/rtavfs/effective/acceptance.jsonl`

```jsonl
{"schema_version": "acceptance_event.v1", "event_id": "accept_0001", "effective_set_id": "rtavfs_primary", "action": "ACCEPT", "revision_id": "rev_0001", "acted_at": "2026-09-11T14:00:00+08:00", "actor": "ip_owner", "reason": "初始正式基线核对完成"}
```
