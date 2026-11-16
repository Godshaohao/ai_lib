# checks/evidence.py · 设计伪代码

> **拟议，非可执行代码。** 以下接口名、内部结构和错误策略供评审，不声称当前已实现。

- **职责**：校验检查来源、证据与覆盖。
- **接口**：`verify(plan, result, artifact_store) → Verification`
- **输入**：固定输入、结果引用、来源记录与检查证据。
- **输出**：可发布判断及逐项问题。
- **配置 / 依赖**：证据策略、可访问来源、规则版本。

## 算法与处理顺序

```text
过程 verify(plan, result, artifact_store) → Verification
    验证来源与 facts_refs 指向存在的固定对象；核对范围、解析覆盖和 PASS 推导条件；若存在指标依赖，必须校验其确切上游检查、指标、上下文与可用状态
    返回上述输出或明确失败
```

## 异常与边界

空/伪造引用、证据变化、依赖不存在或 Gate 引用普通 facts 冒充 metric 均不可通过；原型不是生产实现。所有正式业务记录仅通过统一 Publisher 或其事件追加入口发布；本文件只有设计内容。

## 对应 v3 JSON 字段与术语

下列字段是本模块**读取、贡献或校验的范围**，并不表示该模块独立写入整份 JSON。字段必需性来自 v3 文档；完整结构及示例见对应字典。

### [CheckResult 字段字典与完整示例](../../../contracts/check.md)

| 字段 | 适用 / 必需性 | 类型 | 中文含义与边界 |
|---|---|---|---|
| `file_changes[].old_source_ref` | 是 | object/null | 比较前来源；引用旧交付或旧 Rev 的文件成员 |
| `file_changes[].new_source_ref` | 是 | object/null | 比较后来源 |
| `object_changes[].facts_refs[]` | 是 | array | 对应 Parser 事实 ID，能复核结果 |
| `quality_checks[].result` | 是 | enum | PASS/FAIL/INCONCLUSIVE/NOT_RUN |
| `quality_checks[].coverage` | 是 | enum | COMPLETE/PARTIAL/UNKNOWN；PASS 不能在证据不足时给出 |
| `quality_checks[].facts_refs[]` | 是 | array | 此质量检查实际消费的解析证据 |

### [FileFacts 字段字典与完整示例](../../../contracts/facts.md)

| 字段 | 适用 / 必需性 | 类型 | 中文含义与边界 |
|---|---|---|---|
| `facts_id` | 是 | string | 单次解析事实记录 ID；Check 可复用它 |
| `source_ref` | 是 | object | 哪份 RAW 或正式来源对应这份事实 |
| `parse_status` | 是 | enum | COMPLETE/PARTIAL/FAILED，但限定在 `covered_sections` 已声明的能力范围 |
| `covered_sections[]` | 是 | array | 例如 MACRO_SIZE、PIN_NAME、PIN_DIRECTION；没有列的内容不宣称被解析 |

术语和 source_ref 的完整定义见[中英文术语表](../../../contracts/术语表.md)。
