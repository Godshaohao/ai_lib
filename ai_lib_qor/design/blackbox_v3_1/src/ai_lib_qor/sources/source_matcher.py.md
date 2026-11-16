# sources/source_matcher.py · 设计伪代码

> **拟议，非可执行代码。** 以下接口名、内部结构和错误策略供评审，不声称当前已实现。

- **职责**：将正式链接匹配到固定交付行。
- **接口**：`match(formal_files, delivery_catalog) → MatchResults`
- **输入**：正式路径/目标与已登记交付记录。
- **输出**：每个正式链接的来源匹配结果。
- **配置 / 依赖**：来源匹配策略须明确。

## 算法与处理顺序

```text
过程 match(formal_files, delivery_catalog) → MatchResults
    优先使用可验证固定身份；比较候选目标；无法唯一匹配保持未匹配
    返回上述输出或明确失败
```

## 异常与边界

冲突或证据不足不虚构 delivery_file 引用。所有正式业务记录仅通过统一 Publisher 或其事件追加入口发布；本文件只有设计内容。

## 对应 v3 JSON 字段与术语

下列字段是本模块**读取、贡献或校验的范围**，并不表示该模块独立写入整份 JSON。字段必需性来自 v3 文档；完整结构及示例见对应字典。

### [FormalSnapshot 字段字典与完整示例](../../../contracts/formal.md)

| 字段 | 适用 / 必需性 | 类型 | 中文含义与边界 |
|---|---|---|---|
| `linked_files[].file_key` | 是 | string/null | 归属明确的逻辑文件位 |
| `linked_files[].source_match` | 是 | enum | 是否已匹配 RAW 文件来源 |
| `linked_files[].source_ref` | 是 | object/null | 能匹配时引用对应 `delivery_file`；未知时 null，不得编造交付记录 |

### [DeliveryRecord 字段字典与完整示例](../../../contracts/delivery.md)

| 字段 | 适用 / 必需性 | 类型 | 中文含义与边界 |
|---|---|---|---|
| `delivery_id` | 是 | string | 单次交付唯一；不得简单等于供应商的 V08 |
| `source_library_id` | 是 | string | 可解析回 SourceLibrary 登记 |
| `files[].file_id` | 是 | string | 本交付中的文件行 ID |
| `files[].file_key` | 是 | string/null | 跨多次交付关联同一个逻辑文件位；未知为 null |

术语和 source_ref 的完整定义见[中英文术语表](../../../contracts/术语表.md)。
