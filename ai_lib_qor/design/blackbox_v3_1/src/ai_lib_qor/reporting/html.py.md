# reporting/html.py · 设计伪代码

> **拟议，非可执行代码。** 以下接口名、内部结构和错误策略供评审，不声称当前已实现。

- **职责**：渲染 HTML。
- **接口**：`render_html(report_model, destination) → ReportRef`
- **输入**：固定 ReportModel、模板及目标路径。
- **输出**：可再生成的 HTML 报告。
- **配置 / 依赖**：reports_root、模板。

## 算法与处理顺序

```text
过程 render_html(report_model, destination) → ReportRef
    仅格式化同一 ReportModel；展示检查范围、状态和来源
    返回上述输出或明确失败
```

## 异常与边界

渲染失败不修改业务 JSON。所有正式业务记录仅通过统一 Publisher 或其事件追加入口发布；本文件只有设计内容。

## 对应 v3 JSON 字段与术语

下列字段是本模块**读取、贡献或校验的范围**，并不表示该模块独立写入整份 JSON。字段必需性来自 v3 文档；完整结构及示例见对应字典。

### [CheckResult 字段字典与完整示例](../../../contracts/check.md)

| 字段 | 适用 / 必需性 | 类型 | 中文含义与边界 |
|---|---|---|---|
| `target.id` | 是 | string | 所检查的交付 ID 或 Rev ID |
| `file_changes[]` | 是 | array | 文件层来源变化、内容变化结论 |
| `quality_checks[]` | 是 | array | 具体质量规则及结果；没有执行可以为空 |
| `summary` | 是 | object | 本 Run 的简单计数：文件来源更新数、已证实内容变化数、失败数、不确定数 |

### [EffectiveIndex 字段字典与完整示例](../../../contracts/index.md)

| 字段 | 适用 / 必需性 | 类型 | 中文含义与边界 |
|---|---|---|---|
| `latest_calculated_revision` | 是 | string/null | 当前最新**计算成功并发布**的 Rev |
| `current_accepted_revision` | 是 | string/null | 当前已采纳 Rev；可落后于最新计算，未启用采纳时为 null |

术语和 source_ref 的完整定义见[中英文术语表](../../../contracts/术语表.md)。
