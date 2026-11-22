# sources/snapshot_builder.py · 设计伪代码

> **拟议，非可执行代码。** 以下接口名、内部结构和错误策略供评审，不声称当前已实现。

- **职责**：组装正式快照。
- **接口**：`build_snapshot(nl_id, observation, matches, previous) → FormalSnapshot`
- **输入**：正式观察、匹配、上一个固定快照。
- **输出**：v3 formal_snapshot.v1 候选。
- **配置 / 依赖**：来源 scope 与快照身份规则。

## 算法与处理顺序

```text
过程 build_snapshot(nl_id, observation, matches, previous) → FormalSnapshot
    记录链接与 fixed source_ref；比较已确认范围内状态；状态变化时构造新快照
    返回上述输出或明确失败
```

## 异常与边界

不完整观察不假装 COMPLETE_IN_SCOPE；索引方案需另行确认。所有正式业务记录仅通过统一 Publisher 或其事件追加入口发布；本文件只有设计内容。

## 对应 v3 JSON 字段与术语

下列字段是本模块**读取、贡献或校验的范围**，并不表示该模块独立写入整份 JSON。字段必需性来自 v3 文档；完整结构及示例见对应字典。

### [FormalSnapshot 字段字典与完整示例](../../../contracts/formal.md)

| 字段 | 适用 / 必需性 | 类型 | 中文含义与边界 |
|---|---|---|---|
| `schema_version` | 是 | string | `formal_snapshot.v1` |
| `formal_nl_id` | 是 | string | NL 标签，不能作为唯一时间状态身份 |
| `formal_snapshot_id` | 是 | string | 固定状态 ID，历史版本引用它 |
| `previous_snapshot_id` | 是 | string/null | 上一次不同的固定状态；首次为 null |
| `observed_at` | 是 | ISO 时间 | 本次盘点时刻 |
| `coverage` | 是 | enum | COMPLETE_IN_SCOPE/PARTIAL/UNKNOWN，不能把某个 IP 完整误报为整个 NL 完整 |
| `scope.source_library_ids[]` | 是 | array | 此 Snapshot 统计了哪些来源库，或实际适用的已定义范围 |
| `scope.views[]` | 是 | array | 覆盖的视图；可为空但不能同时声称无依据的完全覆盖 |
| `linked_files[]` | 是 | array | 本次状态实际链接的文件集合 |

术语和 source_ref 的完整定义见[中英文术语表](../../../contracts/术语表.md)。

## 本脚本交付的完整 v3 候选示例

下列内容逐字来自 v3 合成示例；它是经组装后的业务记录格式，实际发布须通过 Schema 与跨记录验证。

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
