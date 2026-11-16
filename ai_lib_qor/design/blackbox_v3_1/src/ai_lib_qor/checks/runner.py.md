# checks/runner.py · 设计伪代码

> **拟议，非可执行代码。** 以下接口名、内部结构和错误策略供评审，不声称当前已实现。

- **职责**：按计划调用检查插件。
- **接口**：`run_plan(plan, registry) → Contributions`
- **输入**：固定 CheckPlan 与已注册插件。
- **输出**：每个启用检查的内存贡献和执行诊断。
- **配置 / 依赖**：checks.yaml；先串行，无任务队列。

## 算法与处理顺序

```text
过程 run_plan(plan, registry) → Contributions
    逐项调用 run(context, params)；隔离错误；附加运行上下文但不改插件判断；校验贡献对应计划
    返回上述输出或明确失败
```

## 异常与边界

插件异常记录诊断并按发布策略返回 NOT_RUN 或拒绝；禁用项不进入本轮。所有正式业务记录仅通过统一 Publisher 或其事件追加入口发布；本文件只有设计内容。

## 对应 v3 JSON 字段与术语

下列字段是本模块**读取、贡献或校验的范围**，并不表示该模块独立写入整份 JSON。字段必需性来自 v3 文档；完整结构及示例见对应字典。

### [CheckResult 字段字典与完整示例](../../../contracts/check.md)

| 字段 | 适用 / 必需性 | 类型 | 中文含义与边界 |
|---|---|---|---|
| `quality_checks[].check_id` | 是 | string | 例如 `LEF_LIBERTY_PIN_MATCH` |
| `quality_checks[].result` | 是 | enum | PASS/FAIL/INCONCLUSIVE/NOT_RUN |
| `quality_checks[].coverage` | 是 | enum | COMPLETE/PARTIAL/UNKNOWN；PASS 不能在证据不足时给出 |
| `quality_checks[].facts_refs[]` | 是 | array | 此质量检查实际消费的解析证据 |

术语和 source_ref 的完整定义见[中英文术语表](../../../contracts/术语表.md)。
