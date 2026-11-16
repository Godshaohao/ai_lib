# cli.py · 设计伪代码

> **拟议，非可执行代码。** 以下接口名、内部结构和错误策略供评审，不声称当前已实现。

- **职责**：命令入口与参数边界。
- **接口**：`main(argv) → ExitStatus`
- **输入**：子命令 update/check/accept/report、目标 ID、配置路径及可选 --work-root。
- **输出**：统一状态码和诊断，不直接写业务记录。
- **配置 / 依赖**：project.yaml；work_root 优先级 CLI > 环境变量 > YAML。

## 算法与处理顺序

```text
过程 main(argv) → ExitStatus
    解析参数；加载并校验配置；根据子命令调用对应用例；输出生成记录 ID 与诊断
    返回上述输出或明确失败
```

## 异常与边界

参数或配置错误时停止；不暴露虚假的成功状态。所有正式业务记录仅通过统一 Publisher 或其事件追加入口发布；本文件只有设计内容。

## 对应 v3 JSON 字段与术语

下列字段是本模块**读取、贡献或校验的范围**，并不表示该模块独立写入整份 JSON。字段必需性来自 v3 文档；完整结构及示例见对应字典。

### [DeliveryRecord 字段字典与完整示例](../../contracts/delivery.md)

| 字段 | 适用 / 必需性 | 类型 | 中文含义与边界 |
|---|---|---|---|
| `delivery_id` | 是 | string | 单次交付唯一；不得简单等于供应商的 V08 |
| `source_library_id` | 是 | string | 可解析回 SourceLibrary 登记 |

### [CheckResult 字段字典与完整示例](../../contracts/check.md)

| 字段 | 适用 / 必需性 | 类型 | 中文含义与边界 |
|---|---|---|---|
| `target.kind` | 是 | enum | `RAW_DELIVERY` / `EFFECTIVE_REVISION` |
| `target.id` | 是 | string | 所检查的交付 ID 或 Rev ID |
| `check_run_id` | 是 | string | 在目标目录下唯一，允许 `run_001`、`run_002` 重跑 |

### [EffectiveVersion 字段字典与完整示例](../../contracts/effective.md)

| 字段 | 适用 / 必需性 | 类型 | 中文含义与边界 |
|---|---|---|---|
| `effective_set_id` | 是 | string | 有效文件集标识；默认一个 IP 一套 |
| `revision_id` | 是 | string | `rev_0001`、`rev_0002`，只在当前 Effective Set 内有序 |

### [AcceptanceEvent 字段字典与完整示例](../../contracts/acceptance.md)

| 字段 | 适用 / 必需性 | 类型 | 中文含义与边界 |
|---|---|---|---|
| `action` | 是 | enum | ACCEPT/ROLLBACK/REVOKE；对应界面“采用/回退/撤销采用” |
| `actor` | 是 | string | 作出决策的责任人/角色 |
| `revision_id` | 是 | string | 作用于哪个固定 Rev |

术语和 source_ref 的完整定义见[中英文术语表](../../contracts/术语表.md)。
