# Schema 演进与兼容策略

本文档定义 `schemas/*.schema.json` 的版本控制与读写兼容规则，适用于路径式主线全部权威与派生契约（`delivery_minimal`、`formal_path`、`effective_path`、`file_index_path`、`file_facts_path`、`check_result_path`）。

## 1. 同主版本（`*.v1`）只增不删原则

在主版本号保持 `*.v1` 不变的前提下，仅允许以下**向后兼容的增量演进**：
1. **新增可选属性**：所有新字段必须是非必填（不加入 `required`），历史已归档的旧版本 JSON 必须继续通过新版 Schema 校验。
   - 示例：`check_result.path.v1` 新增可选 `tooling`（含 `parser_signatures`、`plugins`、`plugin_versions`）与 `checks[].severity`、`checks[].findings[]`；`file_facts.path.v1` 在 `LIBERTY.objects` 下预留可选 `operating_conditions` 与 `pg_pins`。
2. **放宽值域但保留内置强约束**：例如 `file_facts_path.schema.json` 将顶层 `view` 放宽为大写标识正则 `^[A-Z][A-Z0-9_]{1,31}$` 以支持新 View 扩展，同时通过 `allOf` 保留 5 类内置 View（`LEF`/`LIBERTY`/`VERILOG`/`CDL`/`SPICE`）的严格结构校验。
3. **禁止破坏性修改**：同主版本内不得删除必填字段、重命名字段、改变既有字段类型或收紧已有值域。

**Formal 快照标识。** FileIndex 的 `nl_snapshots[]` 与每条 `views.*.*.nl[]` 记录新增可选字段 `snapshot_id`，值为当前库内的 Formal 归档文件名。新版从归档重建时写入此字段，旧索引经归档对账后可在内存补齐，再由显式索引刷新持久化。Web 与 Excel 按同一快照标识确定链接归属。历史检查如已固定快照文件名，则按原标识重建。更早、未记录快照标识的检查仍按归档时间上界兼容读取。

## 2. 降级与回滚注意（Downgrade Caveat）

- 当前所有 `*.v1` Schema 顶层均设置了 `"additionalProperties": false` 以拦截拼写错误与脏数据。
- **重要边界**：这意味着“新版代码可无损读取全部旧版 `*.v1` 归档”，但**将代码回滚到不包含新增可选字段的旧版本时，旧版本 Schema 校验会拒绝包含新字段（如 `tooling`、`findings`）的新产出 JSON**。
- 若未来需要支持多版本代码并行混合读写同一 `work/` 目录，应通过新主版本号（如 `check_result.path.v2`）与独立 Schema 文件显式区分，而不在旧主版本内做不兼容切换。

## 3. 何时必须升级主版本号（`*.v2`）

出现以下任一变化时，必须启用 `*.v2` 与独立 Schema 文件，禁止原地覆盖 `*.v1`：
- 删除或重命名任意已有字段；
- 改变既有字段含义、单位或数据结构；
- 修改必填字段集合导致历史归档无法通过校验。
