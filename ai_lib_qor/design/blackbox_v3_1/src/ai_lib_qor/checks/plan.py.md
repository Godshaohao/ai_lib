# checks/plan.py · 设计伪代码

> **拟议，非可执行代码。** 以下接口名、内部结构和错误策略供评审，不声称当前已实现。

- **职责**：固定一次检查的输入和参数。
- **接口**：`make_plan(target, baseline, profile, selectors, facts) → CheckPlan`
- **输入**：已发布目标、基线、profile、来源和事实引用。
- **输出**：内存 CheckPlan，含每个启用插件的固定范围、版本及 params。
- **配置 / 依赖**：checks.yaml profiles。

## 算法与处理顺序

```text
过程 make_plan(target, baseline, profile, selectors, facts) → CheckPlan
    验证启用插件与参数；调用 selector；固定来源引用和事实；对缺项保留原因；插件不自行选版本
    返回上述输出或明确失败
```

## 异常与边界

重复计划 ID 或目标不一致拒绝；缺失不能当 PASS。所有正式业务记录仅通过统一 Publisher 或其事件追加入口发布；本文件只有设计内容。

## 输入上下文草案

```text
CheckContext（内存，非业务 JSON）:
  target / baseline: v3 kind + 固定 ID；baseline 可为空
  scope: file_key、source_ref、指定对象 / corner / mode
  facts: 已解析 FileFacts，含 facts_ref、实际覆盖、来源身份
  params: 所选 profile 的该插件配置
  plan_id: 本轮固定输入和选择结果的运行内身份（实现方式待定）
```

同一个 profile 可以返回多个独立 scope；同一插件 ID 对多个 scope 的实例身份应在实现时定义并与 v3 `check_id` / `scope_file_keys` 兼容。

## 对应 v3 JSON 字段与术语

下列字段是本模块**读取、贡献或校验的范围**，并不表示该模块独立写入整份 JSON。字段必需性来自 v3 文档；完整结构及示例见对应字典。

### [CheckResult 字段字典与完整示例](../../../contracts/check.md)

| 字段 | 适用 / 必需性 | 类型 | 中文含义与边界 |
|---|---|---|---|
| `target.kind` | 是 | enum | `RAW_DELIVERY` / `EFFECTIVE_REVISION` |
| `target.id` | 是 | string | 所检查的交付 ID 或 Rev ID |
| `baseline.kind` | 是 | enum/null | 旧交付或旧 Rev，与 target 同类型；不需要比较时 baseline 为 null |
| `baseline.id` | 是 | string/null | 前一次选定的比较目标 ID |
| `effective_set_id` | 是 | string/null | 有效版本检查时必填；交付前检查可为 null |
| `ruleset_id` | 是 | string | 使用的规则版本；换规则可以重跑同一个 Rev |

### [FileFacts 字段字典与完整示例](../../../contracts/facts.md)

| 字段 | 适用 / 必需性 | 类型 | 中文含义与边界 |
|---|---|---|---|
| `facts_id` | 是 | string | 单次解析事实记录 ID；Check 可复用它 |
| `source_ref` | 是 | object | 哪份 RAW 或正式来源对应这份事实 |
| `covered_sections[]` | 是 | array | 例如 MACRO_SIZE、PIN_NAME、PIN_DIRECTION；没有列的内容不宣称被解析 |

术语和 source_ref 的完整定义见[中英文术语表](../../../contracts/术语表.md)。
