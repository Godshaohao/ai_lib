# ai_lib_qor · v3.1 黑盒插件源码设计

> **这是可评审的设计骨架，不是可执行程序。** 所有 `.py.md` 描述对应拟议 Python 脚本，内容为中文逻辑及伪代码；实际 `.py` 文件尚未创建。v3 JSON Schema 是设计基准，其生产权威性仍待确认。

## 从这里开始

1. 配置 `project.yaml` 指定工作目录及只读来源；`ownership`、`delivery_rules`、`checks` 各管一类规则。
2. 固定核心处理来源、版本、采纳和发布；检查通过插件扩展。Parser 采用 Adapter，不默认变成插件平台。
3. 插件只返回当前检查的临时贡献；`assembler` 合并成一份 v3 `check_result.v1` 候选，经证据和合同校验后由 Publisher 发布。
4. 几个报告共用固定 Run 的只读视图。检查通过、正式 NL 更新和人工采纳相互独立。

```text
来源 → Scanner / 归属 → Delivery 或 FormalSnapshot ─┐
                                                   ├→ Composer → EffectiveVersion
固定文件 → Parser Adapter → FileFacts ───────────────┘       │
                                                             ▼
配置 profile → Plan / Selector → 多个检查插件 → Contributions → Assembler
                                                            ↓
                  v3 Schema + 跨记录 + Evidence → Publisher → CheckResult
                                                            ↓
                                   同一 Run → ReportModel → HTML / Excel
人工采纳 → AcceptanceEvent → EffectiveIndex（与最新计算指针分开）
```

## 文件目录和脚本入口

每个链接均指向真实存在的设计文件。它们逐项提供职责、接口、输入、输出、配置、伪代码和失败边界。


### application

- [application/accept.py](src/ai_lib_qor/application/accept.py.md)
- [application/check.py](src/ai_lib_qor/application/check.py.md)
- [application/report.py](src/ai_lib_qor/application/report.py.md)
- [application/update.py](src/ai_lib_qor/application/update.py.md)

### checks

- [checks/assembler.py](src/ai_lib_qor/checks/assembler.py.md)
- [checks/evidence.py](src/ai_lib_qor/checks/evidence.py.md)
- [checks/plan.py](src/ai_lib_qor/checks/plan.py.md)

### checks/plugins

- [checks/plugins/content_compare.py](src/ai_lib_qor/checks/plugins/content_compare.py.md)
- [checks/plugins/lef_liberty_pin_match.py](src/ai_lib_qor/checks/plugins/lef_liberty_pin_match.py.md)
- [checks/plugins/lef_macro_diff.py](src/ai_lib_qor/checks/plugins/lef_macro_diff.py.md)

### checks

- [checks/registry.py](src/ai_lib_qor/checks/registry.py.md)
- [checks/runner.py](src/ai_lib_qor/checks/runner.py.md)
- [checks/selectors.py](src/ai_lib_qor/checks/selectors.py.md)

### 入口

- [cli.py](src/ai_lib_qor/cli.py.md)
- [config.py](src/ai_lib_qor/config.py.md)

### facts

- [facts/facts_assembler.py](src/ai_lib_qor/facts/facts_assembler.py.md)

### facts/parsers

- [facts/parsers/lef.py](src/ai_lib_qor/facts/parsers/lef.py.md)
- [facts/parsers/liberty.py](src/ai_lib_qor/facts/parsers/liberty.py.md)

### reporting

- [reporting/excel.py](src/ai_lib_qor/reporting/excel.py.md)
- [reporting/html.py](src/ai_lib_qor/reporting/html.py.md)
- [reporting/view.py](src/ai_lib_qor/reporting/view.py.md)

### sources

- [sources/delivery_builder.py](src/ai_lib_qor/sources/delivery_builder.py.md)
- [sources/file_classifier.py](src/ai_lib_qor/sources/file_classifier.py.md)
- [sources/formal_scanner.py](src/ai_lib_qor/sources/formal_scanner.py.md)
- [sources/raw_scanner.py](src/ai_lib_qor/sources/raw_scanner.py.md)
- [sources/snapshot_builder.py](src/ai_lib_qor/sources/snapshot_builder.py.md)
- [sources/source_matcher.py](src/ai_lib_qor/sources/source_matcher.py.md)

### storage

- [storage/paths.py](src/ai_lib_qor/storage/paths.py.md)
- [storage/publisher.py](src/ai_lib_qor/storage/publisher.py.md)

### versions

- [versions/acceptance.py](src/ai_lib_qor/versions/acceptance.py.md)
- [versions/composer.py](src/ai_lib_qor/versions/composer.py.md)
- [versions/delivery_policy.py](src/ai_lib_qor/versions/delivery_policy.py.md)
- [versions/index_projector.py](src/ai_lib_qor/versions/index_projector.py.md)
- [versions/slot_resolver.py](src/ai_lib_qor/versions/slot_resolver.py.md)

## 配置与验收

- [project.yaml 设计](config/project.yaml.md)：工作根、来源、路径优先级。
- [checks.yaml 设计](config/checks.yaml.md)：可信插件注册、场景、选择器与参数。
- [ownership.yaml 设计](config/ownership.yaml.md)：跨库归属及 home。
- [delivery_rules.yaml 设计](config/delivery_rules.yaml.md)：顺序、范围与删除规则。
- [验收场景](tests/验收场景.md)：功能、失败与一致性；目前是计划而非测试结果。

## 字段、示例与审查入口

- [多脚本增量协作与审查结论](增量协作与审查.md)：贡献合并、不可变历史、已知缺口。
- [完整中英文术语表](contracts/术语表.md)：业务对象、字段和工程术语。
- 七类字段字典与完整 v3 合成示例： [Delivery](contracts/delivery.md)、[Formal Snapshot](contracts/formal.md)、[File Facts](contracts/facts.md)、[Effective Version](contracts/effective.md)、[Check Result](contracts/check.md)、[Effective Index](contracts/index.md)、[Acceptance Event](contracts/acceptance.md)。

每份脚本设计同时包含本模块相关字段的中文含义和对应字典链接；生成业务记录的主要脚本包含完整 JSON 输出示例。

## 一次检查的调用接口

```text
application.check(config, target, baseline, profile)
  → checks.plan.make_plan(target, baseline, profile, selectors, facts)
  → checks.runner.run_plan(plan, registry)
  → plugin.run(context, params) → CheckContribution（内存）
  → checks.assembler.assemble(plan, contributions) → CheckResult 候选
  → checks.evidence.verify(plan, result, artifact_store)
  → storage.publisher.publish(candidate, schema, refs, destination)
  → reporting.view.build_view(run_ref, records) → HTML / Excel
```

调用签名和类型均为拟议接口；`CheckPlan`、`CheckContext`、`CheckContribution` 和 `ReportModel` 是内存概念，不是新增权威 JSON。异步队列、数据库、插件自动发现及结果缓存均不是首版前提。

### 贡献与 v3 字段

| 贡献者 | 贡献数据 | 进入 v3 `check_result.v1` |
|---|---|---|
| 文件比较插件 | 来源是否改变、内容状态 | `file_changes[].source_changed` / `content_status` |
| LEF 差异插件 | Macro / Pin 属性新旧值及事实引用 | 对应 `file_changes[].object_changes[]` |
| LEF–Liberty 插件 | 检查 ID、文件范围、结果、覆盖、事实引用与说明 | `quality_checks[]` 的六个必填字段 |
| 汇总器 | 根据上述明细计算 | `summary` 的四个计数字段 |

多个插件若针对同一 `file_key`，需确认 old/new source_ref 相同并按对象键合并；不能简单拼出互相矛盾的重复文件行。v3 Schema 使用 `additionalProperties: false`，插件版本、参数、运行失败细节和完整证据未必都有位置；如无法无损映射，暂停发布并单独确认契约或证据承载方案，不能伪造字段或静默舍弃。v5 `check_run.v1` 不能直接当作 v3。

## 运行数据目录（建议，work_root 可配置）

```text
<work_root>/
├── vendors/<vendor_id>/libraries/<library_id>/
│   ├── deliveries/<delivery_id>.json
│   ├── file_facts/<facts_id>.json
│   ├── delivery_checks/<delivery_id>/run_001.json
│   ├── ips/<ip_id>/
│   │   ├── effective/index.json
│   │   ├── effective/versions/rev_0001.json
│   │   ├── effective/versions/rev_0002.json
│   │   ├── effective/acceptance.jsonl
│   │   └── checks/rev_0002/run_001.json
│   └── effective/                                 # 无 IP 的库级集合，细节待确认
├── formal_nl/NL2.5.3/
│   ├── index.json                                # 拟议：字段与更新/重建规则待确认
│   └── snapshots/
│       ├── snap_0001/snapshot.json
│       └── snap_0002/snapshot.json
├── staging/<job_id>/                             # 可选临时贡献，不是权威业务记录
└── reports/                                      # 可配置到其他根
```

以上保留此前明确提出的 IP 目录及 `formal_nl` 层级。v3.1 文档建议 `effective/<set_id>/` 和 `shared/formal_nl`；两者与此前约定不同，**本设计暂不悄悄更改用户给定路径**。多有效集如何与旧路径兼容、无 IP 目录、跨库 IP 的唯一 home，以及 formal 索引字段仍需确定。v3 示例快照为 `snapshots/<snapshot_id>.json`，迁移需适配路径，并不改变 v3 Schema。

## 来源和约束

- v3.1 设计包：`ai_lib_qor_blackbox_plugin_design_v3_1/ai_lib_qor_plugin_design_v3_1/`，示例插件是独立演示。
- v3 Schema 与字段定义：`ai_lib_qor_contract_v3/schemas/` 和 `docs/`，是设计材料及合成样例。
- v5/v5.1：有合成汇总器和证据检查原型，未证明接入实际数据；已知 v5.1 Gate 依赖检查存在反例。
- 不以旧 `src_qor` 的目录作为新组织方式；现有 Parser 可在核对输入、输出和覆盖后通过 Adapter 复用。

正式实施前应确认路径与多有效集、v3 与插件贡献的字段映射、版本及证据承载、事件幂等/并发恢复、真实 Parser 覆盖。本文不声称已经运行或验证这些功能。
