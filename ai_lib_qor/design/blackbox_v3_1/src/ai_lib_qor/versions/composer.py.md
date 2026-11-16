# versions/composer.py · 设计伪代码

> **拟议，非可执行代码。** 以下接口名、内部结构和错误策略供评审，不声称当前已实现。

- **职责**：生成完整有效版本。
- **接口**：`compose(owner, parent, candidate_changes, reason) → EffectiveVersion`
- **输入**：owner、固定父版、确定的成员变化。
- **输出**：v3 effective_version.v1 候选。
- **配置 / 依赖**：ownership、版本身份规则。

## 算法与处理顺序

```text
过程 compose(owner, parent, candidate_changes, reason) → EffectiveVersion
    从父版成员复制；按唯一 file_key 应用新增/替换/移除；生成 members 全集和 changes；核对二者一致
    返回上述输出或明确失败
```

## 异常与边界

重复成员、坏引用或父版不一致拒绝发布；不采纳。所有正式业务记录仅通过统一 Publisher 或其事件追加入口发布；本文件只有设计内容。

## 对应 v3 JSON 字段与术语

下列字段是本模块**读取、贡献或校验的范围**，并不表示该模块独立写入整份 JSON。字段必需性来自 v3 文档；完整结构及示例见对应字典。

### [EffectiveVersion 字段字典与完整示例](../../../contracts/effective.md)

| 字段 | 适用 / 必需性 | 类型 | 中文含义与边界 |
|---|---|---|---|
| `effective_set_id` | 是 | string | 有效文件集标识；默认一个 IP 一套 |
| `owner.owner_type` | 是 | enum | BUSINESS_IP 或 SOURCE_LIBRARY |
| `owner.owner_id` | 是 | string | 对应 IP ID 或无 IP 的来源库 ID |
| `owner.home_source_library_id` | 是 | string | 唯一权威文件存放位置的来源库 |
| `revision_id` | 是 | string | `rev_0001`、`rev_0002`，只在当前 Effective Set 内有序 |
| `parent_revision_id` | 是 | string/null | 继承的上一个 Rev，初次构建可为 null |
| `reason.kind` | 是 | enum | FORMAL_BASELINE / RAW_DELIVERY / FORMAL_ADOPTION / MANUAL_CORRECTION / IMPORT_BASELINE |
| `reason.ref_id` | 是 | string | 本次主要触发来源的固定 ID，不能引用 latest 指针 |
| `members[]` | 是 | array | **完整**有效文件成员集合，不只本次变更文件 |
| `changes[]` | 是 | array | 与前驱 Rev 的文件成员差异，**不是 Macro/PIN 语义差异** |

术语和 source_ref 的完整定义见[中英文术语表](../../../contracts/术语表.md)。

## 本脚本交付的完整 v3 候选示例

下列内容逐字来自 v3 合成示例；它是经组装后的业务记录格式，实际发布须通过 Schema 与跨记录验证。

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
