# reporting/view.py · 设计伪代码

> **拟议，非可执行代码。** 以下接口名、内部结构和错误策略供评审，不声称当前已实现。

- **职责**：为多种报告构建统一只读视图。
- **接口**：`build_view(run_ref, records) → ReportModel`
- **输入**：同一固定 Run、版本、来源及引用事实。
- **输出**：可重建的报告数据对象。
- **配置 / 依赖**：展示筛选设置。

## 算法与处理顺序

```text
过程 build_view(run_ref, records) → ReportModel
    核对引用；组织文件最新/次新、有效/采纳/正式来源和检查明细；保留未知
    返回上述输出或明确失败
```

## 异常与边界

缺失数据明确显示未知或失败，不将最新替换为已采纳。所有正式业务记录仅通过统一 Publisher 或其事件追加入口发布；本文件只有设计内容。

## 对应 v3 JSON 字段与术语

下列字段是本模块**读取、贡献或校验的范围**，并不表示该模块独立写入整份 JSON。字段必需性来自 v3 文档；完整结构及示例见对应字典。

### [DeliveryRecord 字段字典与完整示例](../../../contracts/delivery.md)

| 字段 | 适用 / 必需性 | 类型 | 中文含义与边界 |
|---|---|---|---|
| `supplier_version` | 是 | string | 原始供应商版本号，原样展示 |
| `delivery_order` | 是 | integer | 此库内的交付顺序；优先使用已确认的 `delivery_order.yaml`，不能仅按字符串版本或文件 mtime 排序 |
| `files[].file_key` | 是 | string/null | 跨多次交付关联同一个逻辑文件位；未知为 null |

### [EffectiveVersion 字段字典与完整示例](../../../contracts/effective.md)

| 字段 | 适用 / 必需性 | 类型 | 中文含义与边界 |
|---|---|---|---|
| `revision_id` | 是 | string | `rev_0001`、`rev_0002`，只在当前 Effective Set 内有序 |
| `members[]` | 是 | array | **完整**有效文件成员集合，不只本次变更文件 |

### [CheckResult 字段字典与完整示例](../../../contracts/check.md)

| 字段 | 适用 / 必需性 | 类型 | 中文含义与边界 |
|---|---|---|---|
| `file_changes[]` | 是 | array | 文件层来源变化、内容变化结论 |
| `quality_checks[]` | 是 | array | 具体质量规则及结果；没有执行可以为空 |
| `summary` | 是 | object | 本 Run 的简单计数：文件来源更新数、已证实内容变化数、失败数、不确定数 |

### [EffectiveIndex 字段字典与完整示例](../../../contracts/index.md)

| 字段 | 适用 / 必需性 | 类型 | 中文含义与边界 |
|---|---|---|---|
| `latest_calculated_revision` | 是 | string/null | 当前最新**计算成功并发布**的 Rev |
| `current_accepted_revision` | 是 | string/null | 当前已采纳 Rev；可落后于最新计算，未启用采纳时为 null |

术语和 source_ref 的完整定义见[中英文术语表](../../../contracts/术语表.md)。
