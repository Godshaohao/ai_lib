# sources/formal_scanner.py · 设计伪代码

> **拟议，非可执行代码。** 以下接口名、内部结构和错误策略供评审，不声称当前已实现。

- **职责**：观察正式 NL 文件链接。
- **接口**：`observe_formal(root, scope) → FormalObservation`
- **输入**：正式 NL 根与扫描范围。
- **输出**：链接路径、目标、观察时间及覆盖。
- **配置 / 依赖**：project.yaml 的 formal_nl。

## 算法与处理顺序

```text
过程 observe_formal(root, scope) → FormalObservation
    盘点指定范围；解析链接目标；记录缺失/不可读；不把同名 NL 自动视为相同固定状态
    返回上述输出或明确失败
```

## 异常与边界

链接断裂或范围不完整如实记录，不能声称完整快照。所有正式业务记录仅通过统一 Publisher 或其事件追加入口发布；本文件只有设计内容。

## 对应 v3 JSON 字段与术语

下列字段是本模块**读取、贡献或校验的范围**，并不表示该模块独立写入整份 JSON。字段必需性来自 v3 文档；完整结构及示例见对应字典。

### [FormalSnapshot 字段字典与完整示例](../../../contracts/formal.md)

| 字段 | 适用 / 必需性 | 类型 | 中文含义与边界 |
|---|---|---|---|
| `source_root` | 是 | string | 正式 NL 根路径 |
| `observed_at` | 是 | ISO 时间 | 本次盘点时刻 |
| `coverage` | 是 | enum | COMPLETE_IN_SCOPE/PARTIAL/UNKNOWN，不能把某个 IP 完整误报为整个 NL 完整 |
| `scope.source_library_ids[]` | 是 | array | 此 Snapshot 统计了哪些来源库，或实际适用的已定义范围 |
| `scope.views[]` | 是 | array | 覆盖的视图；可为空但不能同时声称无依据的完全覆盖 |
| `linked_files[].link_path` | 是 | string | 相对正式 NL 根的链接位置 |
| `linked_files[].resolved_path` | 是 | string | 扫描当时所解析的实际目标路径 |

术语和 source_ref 的完整定义见[中英文术语表](../../../contracts/术语表.md)。
