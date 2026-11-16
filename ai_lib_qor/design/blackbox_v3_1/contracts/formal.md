# FormalSnapshot · v3 字段字典与完整示例

> 设计契约和合成数据；表格来自 v3 逐字段确认表，不代表已完成业务确认。`是` / `LEF` / `Liberty` 原样保留，条件必需性需结合对应 Schema 验证。

| 字段路径 | 必需性 / 适用视图 | 类型 | 含义和检查要点 |
|---|---|---|---|
| `schema_version` | 是 | string | `formal_snapshot.v1` |
| `formal_nl_id` | 是 | string | NL 标签，不能作为唯一时间状态身份 |
| `formal_snapshot_id` | 是 | string | 固定状态 ID，历史版本引用它 |
| `previous_snapshot_id` | 是 | string/null | 上一次不同的固定状态；首次为 null |
| `observed_at` | 是 | ISO 时间 | 本次盘点时刻 |
| `source_root` | 是 | string | 正式 NL 根路径 |
| `coverage` | 是 | enum | COMPLETE_IN_SCOPE/PARTIAL/UNKNOWN，不能把某个 IP 完整误报为整个 NL 完整 |
| `scope.source_library_ids[]` | 是 | array | 此 Snapshot 统计了哪些来源库，或实际适用的已定义范围 |
| `scope.views[]` | 是 | array | 覆盖的视图；可为空但不能同时声称无依据的完全覆盖 |
| `scope.note` | 是 | string | 给人看的范围文字，防止误会“全部 NL 完整” |
| `linked_files[]` | 是 | array | 本次状态实际链接的文件集合 |
| `linked_files[].file_id` | 是 | string | 固定快照内文件行 ID |
| `linked_files[].file_key` | 是 | string/null | 归属明确的逻辑文件位 |
| `linked_files[].link_path` | 是 | string | 相对正式 NL 根的链接位置 |
| `linked_files[].resolved_path` | 是 | string | 扫描当时所解析的实际目标路径 |
| `linked_files[].source_match` | 是 | enum | 是否已匹配 RAW 文件来源 |
| `linked_files[].source_ref` | 是 | object/null | 能匹配时引用对应 `delivery_file`；未知时 null，不得编造交付记录 |

## 完整合成示例

来源：`ai_lib_qor_contract_v3/examples/work/formal_nl/NL2.5.3/snapshots/snap_nl253_0002.json`

```json
{
  "schema_version": "formal_snapshot.v1",
  "formal_nl_id": "NL2.5.3",
  "formal_snapshot_id": "snap_nl253_0002",
  "previous_snapshot_id": "snap_nl253_0001",
  "observed_at": "2026-10-21T10:00:00+08:00",
  "source_root": "/example/library/lib_NL2.5.3",
  "coverage": "COMPLETE_IN_SCOPE",
  "scope": {
    "source_library_ids": [
      "lib_rtavfs"
    ],
    "views": [
      "LEF",
      "LIBERTY"
    ],
    "note": "本示例只扫描该 SourceLibrary 的 LEF 与 func Liberty"
  },
  "linked_files": [
    {
      "file_id": "nf001",
      "file_key": "lib_rtavfs:lef:core",
      "link_path": "lef/core.lef",
      "resolved_path": "/example/raw/vendor_orion/lib_rtavfs/V07/lef/core.lef",
      "source_match": "MATCHED_RAW",
      "source_ref": {
        "kind": "delivery_file",
        "source_library_id": "lib_rtavfs",
        "delivery_id": "dlv_20260907_001",
        "file_id": "f001"
      }
    },
    {
      "file_id": "nf002",
      "file_key": "lib_rtavfs:liberty:func_tt",
      "link_path": "lib/func_tt.lib",
      "resolved_path": "/example/raw/vendor_orion/lib_rtavfs/V08/lib/func_tt.lib",
      "source_match": "MATCHED_RAW",
      "source_ref": {
        "kind": "delivery_file",
        "source_library_id": "lib_rtavfs",
        "delivery_id": "dlv_20261019_001",
        "file_id": "f002"
      }
    },
    {
      "file_id": "nf003",
      "file_key": "lib_rtavfs:liberty:func_ff",
      "link_path": "lib/func_ff.lib",
      "resolved_path": "/example/raw/vendor_orion/lib_rtavfs/V07/lib/func_ff.lib",
      "source_match": "MATCHED_RAW",
      "source_ref": {
        "kind": "delivery_file",
        "source_library_id": "lib_rtavfs",
        "delivery_id": "dlv_20260907_001",
        "file_id": "f003"
      }
    }
  ]
}
```
