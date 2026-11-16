# FileFacts · v3 字段字典与完整示例

> 设计契约和合成数据；表格来自 v3 逐字段确认表，不代表已完成业务确认。`是` / `LEF` / `Liberty` 原样保留，条件必需性需结合对应 Schema 验证。

| 字段路径 | 必需性 / 适用视图 | 类型 | 含义和检查要点 |
|---|---|---|---|
| `schema_version` | 是 | string | 本文示例适配层为 `file_facts.v1`，实际可以保留现有语义事实模型 |
| `facts_id` | 是 | string | 单次解析事实记录 ID；Check 可复用它 |
| `source_ref` | 是 | object | 哪份 RAW 或正式来源对应这份事实 |
| `view` | 是 | enum | 示例 LEF / LIBERTY；其他 View 沿用各自既有 Parser |
| `parse_status` | 是 | enum | COMPLETE/PARTIAL/FAILED，但限定在 `covered_sections` 已声明的能力范围 |
| `covered_sections[]` | 是 | array | 例如 MACRO_SIZE、PIN_NAME、PIN_DIRECTION；没有列的内容不宣称被解析 |
| `units` | 是 | object | 例如 LEF 长度 um、Liberty time ns/capacitance pf；需由解析器证明并归一化 |
| `objects.macros[]` | LEF | array | Macro 名称、SIZE、PINS；必要时从既有事实补充 ORIGIN/SYMMETRY/PG/OBS 等 |
| `objects.macros[].name` | LEF | string | Macro 唯一名（文件内部范围） |
| `objects.macros[].size_um` | LEF | number[2] | 尺寸，统一 um；示例只包含明确已解析的属性 |
| `objects.macros[].pins[].name` | LEF | string | Pin 名称（可扩展多个 PORT） |
| `objects.macros[].pins[].direction` | LEF | string | 方向；不得用默认值填补缺失字段 |
| `objects.cells[]` | Liberty | array | Liberty Cell 名称及属性 |
| `objects.cells[].name` | Liberty | string | Cell 名称，对应 Macro 需通过匹配规则比较 |
| `objects.cells[].pins[].name/direction` | Liberty | string | Cell 信号 Pin；PG Pin、Timing Arc 应由更完整解析范围承载 |

## 完整合成示例

来源：`ai_lib_qor_contract_v3/examples/file_facts/facts_core_v08.json`

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

## Liberty 事实示例

```json
{
  "schema_version": "file_facts.v1",
  "facts_id": "facts_tt_v08",
  "source_ref": {
    "kind": "delivery_file",
    "source_library_id": "lib_rtavfs",
    "delivery_id": "dlv_20261019_001",
    "file_id": "f002"
  },
  "view": "LIBERTY",
  "parser": {
    "name": "liberty_parser",
    "version": "demo-1"
  },
  "parse_status": "COMPLETE",
  "covered_sections": [
    "CELL_NAME",
    "PIN_NAME",
    "PIN_DIRECTION"
  ],
  "units": {
    "time": "ns",
    "capacitance": "pf"
  },
  "objects": {
    "cells": [
      {
        "name": "MAC_A",
        "pins": [
          {
            "name": "A",
            "direction": "input"
          },
          {
            "name": "B",
            "direction": "output"
          },
          {
            "name": "C",
            "direction": "input"
          }
        ]
      }
    ]
  }
}
```

## 补充：原 CSV 未单列的解析器子字段

| 字段 | 类型 | 含义 |
|---|---|---|
| `parser.name` | string | 解析器名称，如 `lef_parser`。 |
| `parser.version` | string | 解析器版本，如 `demo-1`。 |

它们可在 v3 Schema 与完整示例中核对；不计入原 CSV 的 116 行。
