# EffectiveIndex · v3 字段字典与完整示例

> 设计契约和合成数据；表格来自 v3 逐字段确认表，不代表已完成业务确认。`是` / `LEF` / `Liberty` 原样保留，条件必需性需结合对应 Schema 验证。

| 字段路径 | 必需性 / 适用视图 | 类型 | 含义和检查要点 |
|---|---|---|---|
| `schema_version` | 是 | string | `effective_index.v1` |
| `effective_set_id` | 是 | string | 该索引属于哪套有效文件集合 |
| `owner.owner_type / owner.owner_id` | 是 | enum/string | 业务 IP 或无归属 SourceLibrary |
| `owner.home_source_library_id` | 是 | string | 权威 Rev 的唯一保存位置 |
| `latest_calculated_revision` | 是 | string/null | 当前最新**计算成功并发布**的 Rev |
| `current_accepted_revision` | 是 | string/null | 当前已采纳 Rev；可落后于最新计算，未启用采纳时为 null |
| `updated_at` | 是 | ISO 时间 | 最近一次索引切换时间 |

## 完整合成示例

来源：`ai_lib_qor_contract_v3/examples/work/vendors/vendor_orion/libraries/lib_rtavfs/ips/rtavfs/effective/index.json`

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
