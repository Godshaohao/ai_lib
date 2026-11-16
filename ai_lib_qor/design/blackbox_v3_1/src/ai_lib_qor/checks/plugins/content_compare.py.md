# checks/plugins/content_compare.py · 设计伪代码

> **拟议，非可执行代码。** 以下接口名、内部结构和错误策略供评审，不声称当前已实现。

- **职责**：比较固定文件来源及内容。
- **接口**：`run(context, params) → CheckContribution`
- **输入**：同 file_key 的旧/新来源与可读取证据。
- **输出**：file_changes 贡献。
- **配置 / 依赖**：profile 的输入选择和比较范围。

## 算法与处理顺序

```text
过程 run(context, params) → CheckContribution
    分别判断 source_changed 和可证明的内容变化；无法读取时 content_status 为 UNKNOWN 或 NOT_CHECKED
    返回上述输出或明确失败
```

## 异常与边界

来源变化不等于内容变化；不直接改写 JSON。所有正式业务记录仅通过统一 Publisher 或其事件追加入口发布；本文件只有设计内容。

## 对应 v3 JSON 字段与术语

下列字段是本模块**读取、贡献或校验的范围**，并不表示该模块独立写入整份 JSON。字段必需性来自 v3 文档；完整结构及示例见对应字典。

### [CheckResult 字段字典与完整示例](../../../../contracts/check.md)

| 字段 | 适用 / 必需性 | 类型 | 中文含义与边界 |
|---|---|---|---|
| `file_changes[].file_key` | 是 | string | 哪个逻辑文件位 |
| `file_changes[].old_source_ref` | 是 | object/null | 比较前来源；引用旧交付或旧 Rev 的文件成员 |
| `file_changes[].new_source_ref` | 是 | object/null | 比较后来源 |
| `file_changes[].source_changed` | 是 | bool | 两份来源引用是否不同（不等于内容变化） |
| `file_changes[].content_status` | 是 | enum | CHANGED/UNCHANGED/UNKNOWN/NOT_CHECKED |

术语和 source_ref 的完整定义见[中英文术语表](../../../../contracts/术语表.md)。

## 本脚本输出的内存贡献示例

以下是拟议的临时片段，不是完整 v3 JSON；由 Runner 绑定 plan、目标、范围后交给汇总器。片段中缺失字段表示“本插件未贡献”，不表示 JSON null，也不允许直接发布。

```json
{
  "check_id": "CONTENT_COMPARE",
  "file_changes": [
    {
      "file_key": "lib_rtavfs:lef:core",
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
      },
      "source_changed": true
    }
  ]
}
```
