# facts/facts_assembler.py · 设计伪代码

> **拟议，非可执行代码。** 以下接口名、内部结构和错误策略供评审，不声称当前已实现。

- **职责**：组合单个来源的解析事实。
- **接口**：`assemble(source_ref, contributions) → FileFacts`
- **输入**：同一物理来源的事实片段。
- **输出**：v3 file_facts 候选或无法表达的冲突。
- **配置 / 依赖**：字段归属与适配规则。

## 算法与处理顺序

```text
过程 assemble(source_ref, contributions) → FileFacts
    核验每个贡献的来源身份；按对象稳定键合并；拒绝属性冲突；检查 Schema 对 parser 及覆盖的表达能力
    返回上述输出或明确失败
```

## 异常与边界

多个解析器无法无损表达时阻断并提出契约扩展，不静默丢失。所有正式业务记录仅通过统一 Publisher 或其事件追加入口发布；本文件只有设计内容。

## 对应 v3 JSON 字段与术语

下列字段是本模块**读取、贡献或校验的范围**，并不表示该模块独立写入整份 JSON。字段必需性来自 v3 文档；完整结构及示例见对应字典。

### [FileFacts 字段字典与完整示例](../../../contracts/facts.md)

| 字段 | 适用 / 必需性 | 类型 | 中文含义与边界 |
|---|---|---|---|
| `schema_version` | 是 | string | 本文示例适配层为 `file_facts.v1`，实际可以保留现有语义事实模型 |
| `facts_id` | 是 | string | 单次解析事实记录 ID；Check 可复用它 |
| `source_ref` | 是 | object | 哪份 RAW 或正式来源对应这份事实 |
| `view` | 是 | enum | 示例 LEF / LIBERTY；其他 View 沿用各自既有 Parser |
| `parse_status` | 是 | enum | COMPLETE/PARTIAL/FAILED，但限定在 `covered_sections` 已声明的能力范围 |
| `covered_sections[]` | 是 | array | 例如 MACRO_SIZE、PIN_NAME、PIN_DIRECTION；没有列的内容不宣称被解析 |
| `units` | 是 | object | 例如 LEF 长度 um、Liberty time ns/capacitance pf；需由解析器证明并归一化 |
| `objects.macros[]` | LEF | array | Macro 名称、SIZE、PINS；必要时从既有事实补充 ORIGIN/SYMMETRY/PG/OBS 等 |
| `objects.cells[]` | Liberty | array | Liberty Cell 名称及属性 |

术语和 source_ref 的完整定义见[中英文术语表](../../../contracts/术语表.md)。

## 本脚本交付的完整 v3 候选示例

下列内容逐字来自 v3 合成示例；它是经组装后的业务记录格式，实际发布须通过 Schema 与跨记录验证。

```json
{
  "schema_version": "file_facts.v1",
  "facts_id": "facts_core_v08",
  "source_ref": {
    "kind": "delivery_file",
    "source_library_id": "lib_rtavfs",
    "delivery_id": "dlv_20261019_001",
    "file_id": "f001"
  },
  "view": "LEF",
  "parser": {
    "name": "lef_parser",
    "version": "demo-1"
  },
  "parse_status": "COMPLETE",
  "covered_sections": [
    "MACRO_NAME",
    "MACRO_SIZE",
    "PIN_NAME",
    "PIN_DIRECTION"
  ],
  "units": {
    "distance": "um"
  },
  "objects": {
    "macros": [
      {
        "name": "MAC_A",
        "size_um": [
          124.0,
          80.0
        ],
        "pins": [
          {
            "name": "A",
            "direction": "INPUT"
          },
          {
            "name": "B",
            "direction": "OUTPUT"
          },
          {
            "name": "C",
            "direction": "INPUT"
          }
        ]
      }
    ]
  }
}
```

### 解析器标识补充

| 字段 | 类型 | 含义 |
|---|---|---|
| `parser.name` | string | 本次解析器名称，例如 `lef_parser`。 |
| `parser.version` | string | 本次解析器版本，例如 `demo-1`；来源或算法发生变化时需识别事实是否仍可用。 |

这两个字段在 v3 Schema 和示例中存在；原 116 条 CSV 未拆成独立确认行。多个解析器版本无法塞入单个 `parser` 对象时，应阻止无损发布并确认扩展。
