# storage/paths.py · 设计伪代码

> **拟议，非可执行代码。** 以下接口名、内部结构和错误策略供评审，不声称当前已实现。

- **职责**：统一定位工作目录产物。
- **接口**：`resolve_path(work_root, artifact_kind, ids) → Path`
- **输入**：规范工作根、类型及稳定 ID。
- **输出**：受控根内路径。
- **配置 / 依赖**：project.yaml、CLI/env 覆盖。

## 算法与处理顺序

```text
过程 resolve_path(work_root, artifact_kind, ids) → Path
    验证 ID 安全性；按已选目录规则定位交付、事实、版本、检查、采纳与正式快照
    返回上述输出或明确失败
```

## 异常与边界

拒绝路径穿越、根重叠和不合法 ID；历史引用优先稳定 ID。所有正式业务记录仅通过统一 Publisher 或其事件追加入口发布；本文件只有设计内容。

## 对应 v3 JSON 字段与术语

下列字段是本模块**读取、贡献或校验的范围**，并不表示该模块独立写入整份 JSON。字段必需性来自 v3 文档；完整结构及示例见对应字典。

### [DeliveryRecord 字段字典与完整示例](../../../contracts/delivery.md)

| 字段 | 适用 / 必需性 | 类型 | 中文含义与边界 |
|---|---|---|---|
| `delivery_id` | 是 | string | 单次交付唯一；不得简单等于供应商的 V08 |
| `vendor_id` | 是 | string | 可解析回 Vendor 登记 |
| `source_library_id` | 是 | string | 可解析回 SourceLibrary 登记 |

### [EffectiveVersion 字段字典与完整示例](../../../contracts/effective.md)

| 字段 | 适用 / 必需性 | 类型 | 中文含义与边界 |
|---|---|---|---|
| `effective_set_id` | 是 | string | 有效文件集标识；默认一个 IP 一套 |
| `revision_id` | 是 | string | `rev_0001`、`rev_0002`，只在当前 Effective Set 内有序 |

### [FormalSnapshot 字段字典与完整示例](../../../contracts/formal.md)

| 字段 | 适用 / 必需性 | 类型 | 中文含义与边界 |
|---|---|---|---|
| `formal_nl_id` | 是 | string | NL 标签，不能作为唯一时间状态身份 |
| `formal_snapshot_id` | 是 | string | 固定状态 ID，历史版本引用它 |

### [CheckResult 字段字典与完整示例](../../../contracts/check.md)

| 字段 | 适用 / 必需性 | 类型 | 中文含义与边界 |
|---|---|---|---|
| `check_run_id` | 是 | string | 在目标目录下唯一，允许 `run_001`、`run_002` 重跑 |

术语和 source_ref 的完整定义见[中英文术语表](../../../contracts/术语表.md)。
