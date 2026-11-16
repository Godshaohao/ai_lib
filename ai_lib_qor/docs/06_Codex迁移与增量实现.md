# Codex 实施指导：从现有 ai_lib_qor 迁移到 v3.0

> 目标不是一口气重写所有模块，而是先用**现有扫描器、Parser、审查、Excel** 映射到四个稳定业务记录。下面的步骤按优先级顺序安排，可逐项验收。

## P0：先确认数据源及其权威性

1. 读取现有 `ip_registry.simulation.yml`、`roster_config.json`、`library_ownership.yaml`、`delivery_order.yaml`，列出字段、谁负责写、读者是谁。
2. 只保留每种权威事实一个来源：库及路径登记、业务归属、交付顺序、交付模式。`ip_to_library.json` 若为反向索引，不能再次人工改。
3. 对现有 `discovery / file_history / formal_nl / current_file_sets / effective_baseline / review_result / Excel` 标注当前输入、输出、写入路径和被谁读取，形成迁移映射。
4. 对每个现存原始产物先建立 Adapter：返回 v3.0 模型，现有目录先不移动。新增 JSON 先输出到独立 `work_v3_preview/`，不覆盖生产结果。

## P1：先跑一个 IP 的完整垂直切片

- 选择一个含正式 NL、两次 RAW 更新的 IP（真实例子中可以是 rtavfs），以及一个 RAW-only 库做反例。
- 用 `DeliveryRecord` 输出每次交付的文件集合。严格保留 `supplier_version` 原名和 `delivery_id` 唯一身份。
- 从正式 NL 实际链接内容输出 `FormalSnapshot`，并与最近固定 Snapshot 比较；只在文件状态确认不同时生成新 Snapshot。
- 初始 `EffectiveVersion` 以固定正式 Snapshot 或 RAW 历史建立，不再依赖 `formal_nl/overview/latest.json` 的可变内容。
- 按交付顺序构建 Rev N+1：复制 Rev N 的 `members`，用已明确归属的新来源替换，生成 `changes`，校验两者相符。不产生变化时不生成新 Rev。
- 用现有 LEF/Liberty/Macro Parser 产生可引用的解析事实，不为所有 View 造空 JSON。
- `CheckResult` 对新增交付或新 Rev 执行，区分来源变化与真实内容变化；保证同一 Rev 可再次检查。
- 先根据上述数据生成原有 Excel，保持已有 Macro/Pin 重点验收 Sheet 的信息不减少。

## P2：增量 Runner 最小算法

```python
# 伪代码；直接调用已有 Scanner/Parser/Diff，不另造新全栈。
def handle_raw_delivery(vendor_id, source_library_id, delivery_path):
    delivery = scan_one_delivery(delivery_path)
    delivery_id = stable_delivery_event_id(delivery)  # 与供应商版号分开
    if already_ingested(delivery_id):
        return existing_ingest_result(delivery_id)

    inventory = build_delivery_record(delivery)
    write_immutable(inventory)

    changed_file_keys = find_resolved_files(inventory)
    for file in changed_file_keys:
        ensure_parser_facts(file)  # 按源、Parser 版本复用缓存
        compare_with_last_occurrence_if_requested(file)

    for owner in affected_owners(changed_file_keys):
        old_rev = get_latest_calculated_revision(owner)
        new_members = copy_members(old_rev)
        apply_confirmed_updates(new_members, inventory, owner)
        delta = compare_members(old_rev, new_members)
        if not delta:
            continue

        new_rev = create_immutable_revision(owner, new_members, delta)
        run_checks_for_changed_scope(new_rev, delta)
        validate_revision_and_refs(new_rev)
        atomic_publish_latest_revision(owner, new_rev)
        # 不自动修改 current_accepted_revision
```

**不要在 `scan_one_delivery()` 后无条件构建 Rev，也不要让某个 `review PASS` 自动采纳有效版本。**

正式 NL 增量路径应独立：盘点链接与可验证事实 → 比较上一个固定 Snapshot → 确认状态变化才新增 Snapshot → 失效受影响 IP 的正式对照缓存。若决定采用正式文件更改，才生成新的 EffectiveVersion。

## P3：文件存储实施规则

1. `work/vendors/<vendor>/libraries/<source_lib>/deliveries/<delivery_id>/delivery.json` 只写一次，之后仅追加新交付文件，不回写旧交付。
2. `work/formal_nl/<nl>/snapshots/<snapshot_id>.json` 按不同固定状态新增，旧引用不漂移。
3. `.../ips/<ip>/effective/versions/rev_0001.json` 存完整文件成员与本次改变；不创建 `rev_0001/version.json` 的额外层级。
4. `.../ips/<ip>/checks/<rev>/run_001.json` 保存针对有效 Rev 的检查结果；RAW 检查放对应交付自己的 `checks/`。
5. `index.json` 原子替换。除非业务明确实施采纳，否则 Index 的 `current_accepted_revision` 允许为空。
6. 若 SourceLibrary 无 BusinessIP，在库根 `effective/` 建相同结构并标记 `owner_type=SOURCE_LIBRARY`。
7. 跨库 BusinessIP 唯一指定 `home_source_library_id`，所有旧/新源仍在各自原始库；版本中使用 typed `source_ref` 引用，不复制源 JSON。

## P4：验收用例（必须具有真实代码测试）

- T01 V08 只送两个 Liberty，未出现的 LEF 自动沿用旧 Rev，而不是被删除。
- T02 “最近两次出现”能跨多个未包含此文件的交付回溯。
- T03 `file_key` 区分 Corner/Mode，不因同名文件错配不同角。
- T04 FULL/UNKNOWN 包的删除语义不能被猜测。
- T05 当前最新 Rev 可以在未采纳状态下查看；accepted 指针保持不变。
- T06 正式 NL 同名内换链接：新 Snapshot 创建、旧 Rev 无变化。
- T07 RAW-only 的初始有效版本不依赖 Formal NL。
- T08 CheckResult 由旧 Parser Facts 读取 Macro/Pin/Cell 事实，字段与单位可核查。
- T09 CheckResult 规则升级只产生新 Run，不产生新 Rev。
- T10 增量重跑与失败后恢复，不得重复生成同 ID 的记录或在校验失败后更新 Index。
- T11 Excel 宏/Pin 表和内容差异报告与旧流程比对，核心信息不得消失。

## 本设计包的测试使用

```bash
python build_examples.py
python build_schemas.py
python tools/validate_examples.py
```

测试脚本使用 Python + `jsonschema`（仅开发期校验依赖）；它不包含联网操作、不读取企业真实库、不会改写 ai_lib 项目。

本包 `validation_results.json` 记录合成示例 7 类 Schema 的校验结果和故意注入错误的检出情况。**这些 PASS 不应被解读为生产系统已经验收。**

## 明确不做

- 不因为这次契约调整删除以前的大量 Raw Fact、Macro Index、质量检查和 Excel 证据。
- 不为所有模块都增添各自的数据库、时间线和永久 JSON。
- 不要求第一版引入消息总线、分布式作业队列、GraphRAG 或复杂审批工作流。
- 不要求重新解析未变化的所有文件，也不要求为了 File History 强制计算所有历史文件 Hash。
