# EffectiveVersion · v3 字段字典与完整示例

> 设计契约和合成数据；表格来自 v3 逐字段确认表，不代表已完成业务确认。`是` / `LEF` / `Liberty` 原样保留，条件必需性需结合对应 Schema 验证。

| 字段路径 | 必需性 / 适用视图 | 类型 | 含义和检查要点 |
|---|---|---|---|
| `schema_version` | 是 | string | `effective_version.v1` |
| `effective_set_id` | 是 | string | 有效文件集标识；默认一个 IP 一套 |
| `owner.owner_type` | 是 | enum | BUSINESS_IP 或 SOURCE_LIBRARY |
| `owner.owner_id` | 是 | string | 对应 IP ID 或无 IP 的来源库 ID |
| `owner.home_source_library_id` | 是 | string | 唯一权威文件存放位置的来源库 |
| `revision_id` | 是 | string | `rev_0001`、`rev_0002`，只在当前 Effective Set 内有序 |
| `parent_revision_id` | 是 | string/null | 继承的上一个 Rev，初次构建可为 null |
| `created_at` | 是 | ISO 时间 | 有效版本被计算并固定的时间 |
| `reason.kind` | 是 | enum | FORMAL_BASELINE / RAW_DELIVERY / FORMAL_ADOPTION / MANUAL_CORRECTION / IMPORT_BASELINE |
| `reason.ref_id` | 是 | string | 本次主要触发来源的固定 ID，不能引用 latest 指针 |
| `members[]` | 是 | array | **完整**有效文件成员集合，不只本次变更文件 |
| `members[].file_key` | 是 | string | 不允许重复；同时引用相同文件位不同来源时属于冲突，需先解决 |
| `members[].source_ref` | 是 | object | 这个文件位最终选用的 RAW 或正式来源 |
| `changes[]` | 是 | array | 与前驱 Rev 的文件成员差异，**不是 Macro/PIN 语义差异** |
| `changes[].file_key` | 是 | string | 哪个逻辑文件位发生采用变化 |
| `changes[].action` | 是 | enum | ADDED / REPLACED / REMOVED |
| `changes[].old_source_ref` | 是 | object/null | 旧版选用的来源；新增文件为 null |
| `changes[].new_source_ref` | 是 | object/null | 新版选用的来源；移除文件为 null |

## 完整合成示例

来源：`ai_lib_qor_contract_v3/examples/work/vendors/vendor_orion/libraries/lib_rtavfs/ips/rtavfs/effective/versions/rev_0002.json`

```json
{
  "schema_version": "effective_version.v1",
  "effective_set_id": "rtavfs_primary",
  "owner": {
    "owner_type": "BUSINESS_IP",
    "owner_id": "rtavfs",
    "home_source_library_id": "lib_rtavfs"
  },
  "revision_id": "rev_0002",
  "parent_revision_id": "rev_0001",
  "created_at": "2026-10-20T11:00:00+08:00",
  "reason": {
    "kind": "RAW_DELIVERY",
    "ref_id": "dlv_20261019_001"
  },
  "members": [
    {
      "file_key": "lib_rtavfs:lef:core",
      "source_ref": {
        "kind": "delivery_file",
        "source_library_id": "lib_rtavfs",
        "delivery_id": "dlv_20261019_001",
        "file_id": "f001"
      }
    },
    {
      "file_key": "lib_rtavfs:liberty:func_tt",
      "source_ref": {
        "kind": "delivery_file",
        "source_library_id": "lib_rtavfs",
        "delivery_id": "dlv_20261019_001",
        "file_id": "f002"
      }
    },
    {
      "file_key": "lib_rtavfs:liberty:func_ff",
      "source_ref": {
        "kind": "formal_file",
        "formal_nl_id": "NL2.5.3",
        "formal_snapshot_id": "snap_nl253_0001",
        "file_id": "nf003"
      }
    }
  ],
  "changes": [
    {
      "file_key": "lib_rtavfs:lef:core",
      "action": "REPLACED",
      "old_source_ref": {
        "kind": "formal_file",
        "formal_nl_id": "NL2.5.3",
        "formal_snapshot_id": "snap_nl253_0001",
        "file_id": "nf001"
      },
      "new_source_ref": {
        "kind": "delivery_file",
        "source_library_id": "lib_rtavfs",
        "delivery_id": "dlv_20261019_001",
        "file_id": "f001"
      }
    },
    {
      "file_key": "lib_rtavfs:liberty:func_tt",
      "action": "REPLACED",
      "old_source_ref": {
        "kind": "formal_file",
        "formal_nl_id": "NL2.5.3",
        "formal_snapshot_id": "snap_nl253_0001",
        "file_id": "nf002"
      },
      "new_source_ref": {
        "kind": "delivery_file",
        "source_library_id": "lib_rtavfs",
        "delivery_id": "dlv_20261019_001",
        "file_id": "f002"
      }
    }
  ]
}
```
