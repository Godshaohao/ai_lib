# application/update.py · 设计伪代码

> **拟议，非可执行代码。** 以下接口名、内部结构和错误策略供评审，不声称当前已实现。

- **职责**：组织交付或正式来源更新。
- **接口**：`update(config, scope) → UpdateResult`
- **输入**：配置、指定库与来源范围。
- **输出**：已发布交付/快照 ID 和可解释的跳过/错误。
- **配置 / 依赖**：sources、delivery_rules、ownership。

## 算法与处理顺序

```text
过程 update(config, scope) → UpdateResult
    固定扫描范围；调用扫描和分类或匹配；构建记录；经校验与 publisher 发布；是否生成 Rev 由明确选择驱动
    返回上述输出或明确失败
```

## 异常与边界

无法确定身份或顺序时不自动采用；发布失败保留旧记录。所有正式业务记录仅通过统一 Publisher 或其事件追加入口发布；本文件只有设计内容。

## 对应 v3 JSON 字段与术语

下列字段是本模块**读取、贡献或校验的范围**，并不表示该模块独立写入整份 JSON。字段必需性来自 v3 文档；完整结构及示例见对应字典。

### [DeliveryRecord 字段字典与完整示例](../../../contracts/delivery.md)

| 字段 | 适用 / 必需性 | 类型 | 中文含义与边界 |
|---|---|---|---|
| `delivery_id` | 是 | string | 单次交付唯一；不得简单等于供应商的 V08 |
| `package_mode` | 是 | enum | FULL/INCREMENTAL/PATCH/UNKNOWN |
| `files[]` | 是 | array | 本次**实际出现**的文件记录 |

### [FormalSnapshot 字段字典与完整示例](../../../contracts/formal.md)

| 字段 | 适用 / 必需性 | 类型 | 中文含义与边界 |
|---|---|---|---|
| `formal_nl_id` | 是 | string | NL 标签，不能作为唯一时间状态身份 |
| `formal_snapshot_id` | 是 | string | 固定状态 ID，历史版本引用它 |
| `coverage` | 是 | enum | COMPLETE_IN_SCOPE/PARTIAL/UNKNOWN，不能把某个 IP 完整误报为整个 NL 完整 |
| `linked_files[]` | 是 | array | 本次状态实际链接的文件集合 |

术语和 source_ref 的完整定义见[中英文术语表](../../../contracts/术语表.md)。
