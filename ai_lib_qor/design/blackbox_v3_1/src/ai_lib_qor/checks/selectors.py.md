# checks/selectors.py · 设计伪代码

> **拟议，非可执行代码。** 以下接口名、内部结构和错误策略供评审，不声称当前已实现。

- **职责**：按 profile 精确选择检查输入。
- **接口**：`select(selector_id, target, baseline, records) → SelectedInputs`
- **输入**：目标、基线、已登记来源和 selector。
- **输出**：固定文件对/LEF 与相关 Liberty 范围；或选择失败原因。
- **配置 / 依赖**：checks.yaml input_selector、归属与范围。

## 算法与处理顺序

```text
过程 select(selector_id, target, baseline, records) → SelectedInputs
    实现最近两次真实出现、变更 LEF 对父版、选定 LEF 对关联 Liberty；确保同一 file_key 和限定范围
    返回上述输出或明确失败
```

## 异常与边界

无前次出现或关系不明返回不足；不遍历全库猜测。所有正式业务记录仅通过统一 Publisher 或其事件追加入口发布；本文件只有设计内容。

## 选择规则（伪代码）

```text
raw_latest_vs_previous_same_file:
    筛选指定 library、file_key 的真实交付出现记录
    按已确认 delivery_order 排序；取目标记录及其前一出现
    少于两次 → 返回输入不足；不能以供应商版本字符串推断顺序
changed_lef_vs_parent:
    从目标 Rev 及 parent members 建立 file_key → 固定来源的映射
    仅返回来源变化、且旧新成员都能确定的 LEF 对
    首版或新增/删除 → 明确无可比较配对，不伪造旧来源
one_lef_with_related_liberty:
    在选定目标和业务关联范围内固定一个 LEF
    根据已确认的配对与 corner/mode 规则选取相关 Liberty
    匹配不唯一或缺失 → 返回不足，不全库猜测
```

## 对应 v3 JSON 字段与术语

下列字段是本模块**读取、贡献或校验的范围**，并不表示该模块独立写入整份 JSON。字段必需性来自 v3 文档；完整结构及示例见对应字典。

### [DeliveryRecord 字段字典与完整示例](../../../contracts/delivery.md)

| 字段 | 适用 / 必需性 | 类型 | 中文含义与边界 |
|---|---|---|---|
| `delivery_order` | 是 | integer | 此库内的交付顺序；优先使用已确认的 `delivery_order.yaml`，不能仅按字符串版本或文件 mtime 排序 |
| `files[].file_key` | 是 | string/null | 跨多次交付关联同一个逻辑文件位；未知为 null |
| `files[].file_id` | 是 | string | 本交付中的文件行 ID |

### [EffectiveVersion 字段字典与完整示例](../../../contracts/effective.md)

| 字段 | 适用 / 必需性 | 类型 | 中文含义与边界 |
|---|---|---|---|
| `revision_id` | 是 | string | `rev_0001`、`rev_0002`，只在当前 Effective Set 内有序 |
| `parent_revision_id` | 是 | string/null | 继承的上一个 Rev，初次构建可为 null |
| `members[].file_key` | 是 | string | 不允许重复；同时引用相同文件位不同来源时属于冲突，需先解决 |
| `members[].source_ref` | 是 | object | 这个文件位最终选用的 RAW 或正式来源 |

### [FileFacts 字段字典与完整示例](../../../contracts/facts.md)

| 字段 | 适用 / 必需性 | 类型 | 中文含义与边界 |
|---|---|---|---|
| `facts_id` | 是 | string | 单次解析事实记录 ID；Check 可复用它 |
| `source_ref` | 是 | object | 哪份 RAW 或正式来源对应这份事实 |
| `covered_sections[]` | 是 | array | 例如 MACRO_SIZE、PIN_NAME、PIN_DIRECTION；没有列的内容不宣称被解析 |

术语和 source_ref 的完整定义见[中英文术语表](../../../contracts/术语表.md)。
