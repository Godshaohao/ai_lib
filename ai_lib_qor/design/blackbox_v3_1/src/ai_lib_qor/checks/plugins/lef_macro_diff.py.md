# checks/plugins/lef_macro_diff.py · 设计伪代码

> **拟议，非可执行代码。** 以下接口名、内部结构和错误策略供评审，不声称当前已实现。

- **职责**：比较 LEF Macro 和 Pin 事实。
- **接口**：`run(context, params) → CheckContribution`
- **输入**：同逻辑文件的新旧 LEF Facts、覆盖与属性列表。
- **输出**：file_changes[].object_changes 贡献。
- **配置 / 依赖**：attributes: SIZE、PIN_NAME、PIN_DIRECTION。

## 算法与处理顺序

```text
过程 run(context, params) → CheckContribution
    按 Macro/Pin 稳定名称比较已覆盖属性；记录 old/new、单位和 facts_refs；新增/缺失依覆盖判定
    返回上述输出或明确失败
```

## 异常与边界

覆盖不足时不声称对象不存在；冲突交 assembler 处理。所有正式业务记录仅通过统一 Publisher 或其事件追加入口发布；本文件只有设计内容。

## 对应 v3 JSON 字段与术语

下列字段是本模块**读取、贡献或校验的范围**，并不表示该模块独立写入整份 JSON。字段必需性来自 v3 文档；完整结构及示例见对应字典。

### [FileFacts 字段字典与完整示例](../../../../contracts/facts.md)

| 字段 | 适用 / 必需性 | 类型 | 中文含义与边界 |
|---|---|---|---|
| `facts_id` | 是 | string | 单次解析事实记录 ID；Check 可复用它 |
| `covered_sections[]` | 是 | array | 例如 MACRO_SIZE、PIN_NAME、PIN_DIRECTION；没有列的内容不宣称被解析 |
| `objects.macros[].name` | LEF | string | Macro 唯一名（文件内部范围） |
| `objects.macros[].size_um` | LEF | number[2] | 尺寸，统一 um；示例只包含明确已解析的属性 |

### [CheckResult 字段字典与完整示例](../../../../contracts/check.md)

| 字段 | 适用 / 必需性 | 类型 | 中文含义与边界 |
|---|---|---|---|
| `file_changes[].file_key` | 是 | string | 哪个逻辑文件位 |
| `object_changes[].object_type` | 是 | enum | MACRO/PIN/CELL/ATTRIBUTE/OTHER |
| `object_changes[].object_name` | 是 | string | 精确对象名，如 `MAC_A` 或 `MAC_A/C` |
| `object_changes[].attribute` | 是 | string | SIZE/PRESENCE/DIRECTION/... |
| `object_changes[].old_value/new_value` | 是 | JSON value | 差异两侧值，值类型依赖属性；不能用无说明的摘要代替 |
| `object_changes[].unit` | 是 | string/null | SIZE 用 um 等，布尔存在性为 null |
| `object_changes[].facts_refs[]` | 是 | array | 对应 Parser 事实 ID，能复核结果 |

术语和 source_ref 的完整定义见[中英文术语表](../../../../contracts/术语表.md)。

## 本脚本输出的内存贡献示例

以下是拟议的临时片段，不是完整 v3 JSON；由 Runner 绑定 plan、目标、范围后交给汇总器。片段中缺失字段表示“本插件未贡献”，不表示 JSON null，也不允许直接发布。

```json
{
  "check_id": "LEF_MACRO_DIFF",
  "file_changes": [
    {
      "file_key": "lib_rtavfs:lef:core",
      "old_source_ref": {
        "kind": "formal_file",
        "formal_nl_id": "NL2.5.3",
        "formal_snapshot_id": "snap_nl253_0001",
        "file_id": "nf001"
      },
      "new_source_ref": {
        "kind": "delivery_file",
        "source_library_id": "lib_rtavfs",
        "delivery_id": "dlv_20261019_001",
        "file_id": "f001"
      },
      "object_changes": [
        {
          "object_type": "MACRO",
          "object_name": "MAC_A",
          "attribute": "SIZE",
          "old_value": [
            120.0,
            80.0
          ],
          "new_value": [
            124.0,
            80.0
          ],
          "unit": "um",
          "facts_refs": [
            "facts_core_v07",
            "facts_core_v08"
          ]
        },
        {
          "object_type": "PIN",
          "object_name": "MAC_A/C",
          "attribute": "PRESENCE",
          "old_value": false,
          "new_value": true,
          "unit": null,
          "facts_refs": [
            "facts_core_v07",
            "facts_core_v08"
          ]
        }
      ]
    }
  ]
}
```
