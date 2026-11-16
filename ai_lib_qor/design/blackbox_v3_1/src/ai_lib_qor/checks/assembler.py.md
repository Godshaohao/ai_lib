# checks/assembler.py · 设计伪代码

> **拟议，非可执行代码。** 以下接口名、内部结构和错误策略供评审，不声称当前已实现。

- **职责**：把检查贡献组装成 v3 检查结果。
- **接口**：`assemble(plan, contributions) → CheckResult`
- **输入**：统一目标/基线/规则的贡献、诊断和事实引用。
- **输出**：check_result.v1 候选或映射阻断。
- **配置 / 依赖**：v3 Schema、字段归属策略。

## 算法与处理顺序

```text
过程 assemble(plan, contributions) → CheckResult
    核对插件 ID、目标与计划；按 file_key + old/new source_ref 聚合对象变化；按 check_id 和范围归集质量项；冲突拒绝；从明细计算 v3 summary 四项
    返回上述输出或明确失败
```

## 异常与边界

禁止直接输出 v5 checks；v3 无法表达的关键证据/状态先阻断或另提扩展；不凭 DIFF 推导 PASS。所有正式业务记录仅通过统一 Publisher 或其事件追加入口发布；本文件只有设计内容。

## 合并步骤（伪代码）

```text
assert 每条 contribution.plan_id 与当前 plan 一致
assert 每个启用的插件执行实例（plugin_id + 固定 scope）恰好一个贡献或明确失败
创建 files_by_key[(file_key, old_source_ref, new_source_ref)]
for 每个 file_changes 贡献:
    不同 old/new 引用对应同一 file_key → 拒绝
    仅合并已提供的字段；未提供不等于 null；明确提供且不可协调的结论 → 拒绝
    按 (object_type, object_name, attribute) 合并 object_changes
    相同对象属性内容或证据冲突 → 拒绝，不覆盖
for 每个 quality_checks 贡献:
    以 (check_id, scope_file_keys) 为候选身份；重复或冲突 → 拒绝
    assert result 与 coverage 符合 v3 约束及证据规则
summary = 按完整明细统计来源变化、确认内容变化、FAIL、INCONCLUSIVE 数量
组装 v3 必填字段；验证 Schema 与跨引用一致性；返回候选
```

`NOT_RUN` 及执行错误在 v3 四个 summary 计数字段中不能当作 FAIL 或 INCONCLUSIVE 自动混算；报告必须保留结果明细，是否发布失败 Run 需项目确认。插件版本/params/完整证据若无法进入 v3 字段，先核实可追溯承载方式；未确认前阻止静默发布。

## 对应 v3 JSON 字段与术语

下列字段是本模块**读取、贡献或校验的范围**，并不表示该模块独立写入整份 JSON。字段必需性来自 v3 文档；完整结构及示例见对应字典。

### [CheckResult 字段字典与完整示例](../../../contracts/check.md)

| 字段 | 适用 / 必需性 | 类型 | 中文含义与边界 |
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
| `quality_checks[]` | 是 | array | 具体质量规则及结果；没有执行可以为空 |
| `summary` | 是 | object | 本 Run 的简单计数：文件来源更新数、已证实内容变化数、失败数、不确定数 |
| `evidence_note` | 是 | string | 本次证据范围和局限，例如只检查 Pin，不含时序弧 |

术语和 source_ref 的完整定义见[中英文术语表](../../../contracts/术语表.md)。

## 本脚本交付的完整 v3 候选示例

下列内容逐字来自 v3 合成示例；它是经组装后的业务记录格式，实际发布须通过 Schema 与跨记录验证。

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

## 多脚本增量贡献到一份 Run 的过程（拟议）

```text
plan 固定 target=rev_0002、baseline=rev_0001、file_key 及两侧 source_ref
CONTENT_COMPARE → 提供 file_key、两侧来源与 source_changed=true
LEF_MACRO_DIFF → 同一 file_key/两侧来源，贡献 MAC_A.SIZE 与 PIN C 的 object_changes
LEF_LIBERTY_PIN_MATCH → 提供一个独立的 quality_checks 明细
assembler:
    以 file_key 与明确的 old/new source_ref 匹配同一比较对
    验证同一个字段的多个明确声明；不同值且无法证明兼容时拒绝
    按对象类型、名称、属性及范围去重；冲突拒绝
    由充分支持的对象差异确定内容变化；未比较的 tt 维持 UNKNOWN
    汇入质量明细，重新计算 summary；先校验后生成 run_001.json
```

内存片段不是 Schema 完整记录：缺席、显式 null、UNKNOWN 各自不同。对同一字段的 UNKNOWN 与有证据的 CHANGED 是否允许细化，应由实现的合并规则和贡献来源确认；已明确的 UNCHANGED 与 CHANGED 则冲突。计划输入以及全部细节无法以 v3 表达时，不得静默丢弃。

新增插件或参数后创建 `run_002.json`，重新执行相关检查并完整组装本轮结果；**不改写已发布的 run_001**。首版不假设可复用旧插件结果；若需复用，必须先证明输入、事实、算法、参数、依赖和环境一致并确定 v3 的证据承载方式。

注意：v3 随包验证器对 `content_status=CHANGED` 要求至少一条 `object_changes`，这是示例验证器的具体限制，并非 JSON Schema 本身要求。若只有字节变化而无结构化对象差异，需确认语义或修订验证策略，不能捏造变化，也不能误报 UNCHANGED。
