# CheckResult · v3 字段字典与完整示例

> 设计契约和合成数据；表格来自 v3 逐字段确认表，不代表已完成业务确认。`是` / `LEF` / `Liberty` 原样保留，条件必需性需结合对应 Schema 验证。

| 字段路径 | 必需性 / 适用视图 | 类型 | 含义和检查要点 |
|---|---|---|---|
| `schema_version` | 是 | string | `check_result.v1` |
| `check_run_id` | 是 | string | 在目标目录下唯一，允许 `run_001`、`run_002` 重跑 |
| `target.kind` | 是 | enum | `RAW_DELIVERY` / `EFFECTIVE_REVISION` |
| `target.id` | 是 | string | 所检查的交付 ID 或 Rev ID |
| `baseline.kind` | 是 | enum/null | 旧交付或旧 Rev，与 target 同类型；不需要比较时 baseline 为 null |
| `baseline.id` | 是 | string/null | 前一次选定的比较目标 ID |
| `effective_set_id` | 是 | string/null | 有效版本检查时必填；交付前检查可为 null |
| `run_at` | 是 | ISO 时间 | 本次检查实际执行时间 |
| `ruleset_id` | 是 | string | 使用的规则版本；换规则可以重跑同一个 Rev |
| `file_changes[]` | 是 | array | 文件层来源变化、内容变化结论 |
| `file_changes[].file_key` | 是 | string | 哪个逻辑文件位 |
| `file_changes[].old_source_ref` | 是 | object/null | 比较前来源；引用旧交付或旧 Rev 的文件成员 |
| `file_changes[].new_source_ref` | 是 | object/null | 比较后来源 |
| `file_changes[].source_changed` | 是 | bool | 两份来源引用是否不同（不等于内容变化） |
| `file_changes[].content_status` | 是 | enum | CHANGED/UNCHANGED/UNKNOWN/NOT_CHECKED |
| `file_changes[].object_changes[]` | 是 | array | 例如 MACRO SIZE、PIN 名称/方向、Cell 属性变化；只有查明内容差异时才填 |
| `object_changes[].object_type` | 是 | enum | MACRO/PIN/CELL/ATTRIBUTE/OTHER |
| `object_changes[].object_name` | 是 | string | 精确对象名，如 `MAC_A` 或 `MAC_A/C` |
| `object_changes[].attribute` | 是 | string | SIZE/PRESENCE/DIRECTION/... |
| `object_changes[].old_value/new_value` | 是 | JSON value | 差异两侧值，值类型依赖属性；不能用无说明的摘要代替 |
| `object_changes[].unit` | 是 | string/null | SIZE 用 um 等，布尔存在性为 null |
| `object_changes[].facts_refs[]` | 是 | array | 对应 Parser 事实 ID，能复核结果 |
| `quality_checks[]` | 是 | array | 具体质量规则及结果；没有执行可以为空 |
| `quality_checks[].check_id` | 是 | string | 例如 `LEF_LIBERTY_PIN_MATCH` |
| `quality_checks[].scope_file_keys[]` | 是 | array | 本次检查的相关文件范围 |
| `quality_checks[].result` | 是 | enum | PASS/FAIL/INCONCLUSIVE/NOT_RUN |
| `quality_checks[].coverage` | 是 | enum | COMPLETE/PARTIAL/UNKNOWN；PASS 不能在证据不足时给出 |
| `quality_checks[].facts_refs[]` | 是 | array | 此质量检查实际消费的解析证据 |
| `quality_checks[].detail` | 是 | string | 面向使用者的一句解释，注明排除项 |
| `summary` | 是 | object | 本 Run 的简单计数：文件来源更新数、已证实内容变化数、失败数、不确定数 |
| `evidence_note` | 是 | string | 本次证据范围和局限，例如只检查 Pin，不含时序弧 |

## 完整合成示例

来源：`ai_lib_qor_contract_v3/examples/work/vendors/vendor_orion/libraries/lib_rtavfs/ips/rtavfs/checks/rev_0002/run_001.json`

```json
{
  "schema_version": "check_result.v1",
  "check_run_id": "run_001",
  "target": {
    "kind": "EFFECTIVE_REVISION",
    "id": "rev_0002"
  },
  "baseline": {
    "kind": "EFFECTIVE_REVISION",
    "id": "rev_0001"
  },
  "effective_set_id": "rtavfs_primary",
  "run_at": "2026-10-20T14:00:00+08:00",
  "ruleset_id": "qor_rules_202610",
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
      "source_changed": true,
      "content_status": "CHANGED",
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
    },
    {
      "file_key": "lib_rtavfs:liberty:func_tt",
      "old_source_ref": {
        "kind": "formal_file",
        "formal_nl_id": "NL2.5.3",
        "formal_snapshot_id": "snap_nl253_0001",
        "file_id": "nf002"
      },
      "new_source_ref": {
        "kind": "delivery_file",
        "source_library_id": "lib_rtavfs",
        "delivery_id": "dlv_20261019_001",
        "file_id": "f002"
      },
      "source_changed": true,
      "content_status": "UNKNOWN",
      "object_changes": []
    }
  ],
  "quality_checks": [
    {
      "check_id": "LEF_LIBERTY_PIN_MATCH",
      "scope_file_keys": [
        "lib_rtavfs:lef:core",
        "lib_rtavfs:liberty:func_tt"
      ],
      "result": "PASS",
      "coverage": "COMPLETE",
      "facts_refs": [
        "facts_core_v08",
        "facts_tt_v08"
      ],
      "detail": "示例规则比较 MAC_A 的逻辑 Pin 名称与方向；未覆盖时序弧和 PG Pin"
    }
  ],
  "summary": {
    "files_with_new_source": 2,
    "files_with_confirmed_content_change": 1,
    "failed_checks": 0,
    "inconclusive_checks": 0
  },
  "evidence_note": "演示数据，PASS 仅对应所述 Pin 检查范围"
}
```

## 补充：summary 的四个计数字段

| 字段 | 含义 |
|---|---|
| `summary.files_with_new_source` | `file_changes` 中 `source_changed=true` 的条目数。 |
| `summary.files_with_confirmed_content_change` | `content_status=CHANGED` 的条目数。 |
| `summary.failed_checks` | `quality_checks` 中结果为 `FAIL` 的条目数。 |
| `summary.inconclusive_checks` | `quality_checks` 中结果为 `INCONCLUSIVE` 的条目数。 |

四项均为非负整数；`NOT_RUN` 不自动计入 FAIL 或 INCONCLUSIVE。原字段确认表将 summary 汇总为一行，此处按 Schema 展开。
