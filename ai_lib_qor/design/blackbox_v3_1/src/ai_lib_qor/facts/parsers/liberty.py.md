# facts/parsers/liberty.py · 设计伪代码

> **拟议，非可执行代码。** 以下接口名、内部结构和错误策略供评审，不声称当前已实现。

- **职责**：适配 Liberty 解析能力。
- **接口**：`parse(source_ref, source_file, requested_sections) → FactContribution`
- **输入**：单个固定 Liberty 来源与请求范围。
- **输出**：Cell、逻辑 Pin、单位及覆盖等事实。
- **配置 / 依赖**：可信解析器映射、corner/mode 来源上下文。

## 算法与处理顺序

```text
过程 parse(source_ref, source_file, requested_sections) → FactContribution
    调用现有可复用解析能力并规范化已知方向；保留 parser 标识和覆盖
    返回上述输出或明确失败
```

## 异常与边界

不确定 Cell 对应关系或方向时保留未知；不得声称覆盖时序弧。所有正式业务记录仅通过统一 Publisher 或其事件追加入口发布；本文件只有设计内容。

## 对应 v3 JSON 字段与术语

下列字段是本模块**读取、贡献或校验的范围**，并不表示该模块独立写入整份 JSON。字段必需性来自 v3 文档；完整结构及示例见对应字典。

### [FileFacts 字段字典与完整示例](../../../../contracts/facts.md)

| 字段 | 适用 / 必需性 | 类型 | 中文含义与边界 |
|---|---|---|---|
| `facts_id` | 是 | string | 单次解析事实记录 ID；Check 可复用它 |
| `source_ref` | 是 | object | 哪份 RAW 或正式来源对应这份事实 |
| `view` | 是 | enum | 示例 LEF / LIBERTY；其他 View 沿用各自既有 Parser |
| `parse_status` | 是 | enum | COMPLETE/PARTIAL/FAILED，但限定在 `covered_sections` 已声明的能力范围 |
| `covered_sections[]` | 是 | array | 例如 MACRO_SIZE、PIN_NAME、PIN_DIRECTION；没有列的内容不宣称被解析 |
| `units` | 是 | object | 例如 LEF 长度 um、Liberty time ns/capacitance pf；需由解析器证明并归一化 |
| `objects.cells[]` | Liberty | array | Liberty Cell 名称及属性 |
| `objects.cells[].name` | Liberty | string | Cell 名称，对应 Macro 需通过匹配规则比较 |
| `objects.cells[].pins[].name/direction` | Liberty | string | Cell 信号 Pin；PG Pin、Timing Arc 应由更完整解析范围承载 |

术语和 source_ref 的完整定义见[中英文术语表](../../../../contracts/术语表.md)。

### 解析器标识补充

| 字段 | 类型 | 含义 |
|---|---|---|
| `parser.name` | string | 本次解析器名称，例如 `lef_parser`。 |
| `parser.version` | string | 本次解析器版本，例如 `demo-1`；来源或算法发生变化时需识别事实是否仍可用。 |

这两个字段在 v3 Schema 和示例中存在；原 116 条 CSV 未拆成独立确认行。多个解析器版本无法塞入单个 `parser` 对象时，应阻止无损发布并确认扩展。
