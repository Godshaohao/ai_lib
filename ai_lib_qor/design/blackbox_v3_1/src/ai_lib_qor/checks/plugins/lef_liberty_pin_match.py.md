# checks/plugins/lef_liberty_pin_match.py · 设计伪代码

> **拟议，非可执行代码。** 以下接口名、内部结构和错误策略供评审，不声称当前已实现。

- **职责**：比较选定 LEF 与 Liberty 逻辑引脚。
- **接口**：`run(context, params) → CheckContribution`
- **输入**：明确配对的 LEF Macro 与 Liberty Cell、Pin 事实、覆盖。
- **输出**：quality_checks 贡献。
- **配置 / 依赖**：compare: pin_name、direction；关联范围。

## 算法与处理顺序

```text
过程 run(context, params) → CheckContribution
    按已确认 Macro/Cell 匹配；规范化方向；比较 Pin 名称集合和共同 Pin 的方向；完整且无差异 PASS，否则 FAIL
    返回上述输出或明确失败
```

## 异常与边界

事实缺失 NOT_RUN；覆盖不足 INCONCLUSIVE；不覆盖 PG/时序等未声明范围。所有正式业务记录仅通过统一 Publisher 或其事件追加入口发布；本文件只有设计内容。

## 单对比较（伪代码）

```text
if 选定 LEF 或 Liberty Facts 缺失: result = NOT_RUN; coverage = UNKNOWN
elif 对应 Macro/Cell 关系不唯一: result = INCONCLUSIVE; coverage = UNKNOWN
elif 需要的 Pin 名称或方向覆盖不完整: result = INCONCLUSIVE; coverage = PARTIAL/UNKNOWN
else:
    lhs = 选定 LEF Macro 的信号 Pin 名称到方向映射
    rhs = 选定 Liberty Cell 的信号 Pin 名称到方向映射
    delta = (lhs 名称差集, rhs 名称差集, 共同名称的方向差异)
    result = FAIL if delta 非空 else PASS
    coverage = COMPLETE  # 仅对选定对象及所请求字段
return quality_checks[{check_id, scope_file_keys, result, coverage, facts_refs, detail}]
```

方向转换、大小写和信号/电源 Pin 的归一规则需与实际 Parser 确认；没有证据不得扩大匹配范围。

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
| `objects.macros[]` | LEF | array | Macro 名称、SIZE、PINS；必要时从既有事实补充 ORIGIN/SYMMETRY/PG/OBS 等 |
| `objects.cells[]` | Liberty | array | Liberty Cell 名称及属性 |

### [CheckResult 字段字典与完整示例](../../../../contracts/check.md)

| 字段 | 适用 / 必需性 | 类型 | 中文含义与边界 |
|---|---|---|---|
| `quality_checks[].check_id` | 是 | string | 例如 `LEF_LIBERTY_PIN_MATCH` |
| `quality_checks[].scope_file_keys[]` | 是 | array | 本次检查的相关文件范围 |
| `quality_checks[].result` | 是 | enum | PASS/FAIL/INCONCLUSIVE/NOT_RUN |
| `quality_checks[].coverage` | 是 | enum | COMPLETE/PARTIAL/UNKNOWN；PASS 不能在证据不足时给出 |
| `quality_checks[].facts_refs[]` | 是 | array | 此质量检查实际消费的解析证据 |
| `quality_checks[].detail` | 是 | string | 面向使用者的一句解释，注明排除项 |

术语和 source_ref 的完整定义见[中英文术语表](../../../../contracts/术语表.md)。

## 本脚本输出的内存贡献示例

以下是拟议的临时片段，不是完整 v3 JSON；由 Runner 绑定 plan、目标、范围后交给汇总器。片段中缺失字段表示“本插件未贡献”，不表示 JSON null，也不允许直接发布。

```json
{
  "check_id": "LEF_LIBERTY_PIN_MATCH",
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
  ]
}
```
