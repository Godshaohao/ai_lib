# application/check.py · 设计伪代码

> **拟议，非可执行代码。** 以下接口名、内部结构和错误策略供评审，不声称当前已实现。

- **职责**：组织一次检查用例。
- **接口**：`check(config, target, baseline, profile) → CheckRunRef`
- **输入**：固定目标、基线、检查 profile 和运行配置。
- **输出**：已发布 run 引用或可追溯失败。
- **配置 / 依赖**：checks.yaml、paths。

## 算法与处理顺序

```text
过程 check(config, target, baseline, profile) → CheckRunRef
    固定上下文；plan 解析 profile 与输入；runner 顺序调用可信插件；assembler 合并；evidence/Schema 校验；publisher 发布
    返回上述输出或明确失败
```

## 异常与边界

无效注册或上下文冲突停止；插件异常按策略形成 NOT_RUN/拒绝发布，不能视为 PASS。所有正式业务记录仅通过统一 Publisher 或其事件追加入口发布；本文件只有设计内容。

## 对应 v3 JSON 字段与术语

下列字段是本模块**读取、贡献或校验的范围**，并不表示该模块独立写入整份 JSON。字段必需性来自 v3 文档；完整结构及示例见对应字典。

### [CheckResult 字段字典与完整示例](../../../contracts/check.md)

| 字段 | 适用 / 必需性 | 类型 | 中文含义与边界 |
|---|---|---|---|
| `target.kind` | 是 | enum | `RAW_DELIVERY` / `EFFECTIVE_REVISION` |
| `target.id` | 是 | string | 所检查的交付 ID 或 Rev ID |
| `baseline.kind` | 是 | enum/null | 旧交付或旧 Rev，与 target 同类型；不需要比较时 baseline 为 null |
| `baseline.id` | 是 | string/null | 前一次选定的比较目标 ID |
| `ruleset_id` | 是 | string | 使用的规则版本；换规则可以重跑同一个 Rev |
| `file_changes[]` | 是 | array | 文件层来源变化、内容变化结论 |
| `quality_checks[]` | 是 | array | 具体质量规则及结果；没有执行可以为空 |
| `summary` | 是 | object | 本 Run 的简单计数：文件来源更新数、已证实内容变化数、失败数、不确定数 |

术语和 source_ref 的完整定义见[中英文术语表](../../../contracts/术语表.md)。
