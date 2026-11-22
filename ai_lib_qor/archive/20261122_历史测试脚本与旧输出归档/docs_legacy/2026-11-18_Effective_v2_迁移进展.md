# Effective v2 迁移进展

## 本次实现

- `effective-formal-init`：读 `formal.simple.v3` 快照及显式提供的 `raw.simple.v1`，验证所选 View 中每个链接的 RAW 版本、文件路径与唯一交付，生成包含 `formal_baseline` 和 `formal_nl` 的 v2。快照未归属、路径不存在、身份冲突或未授权跨库时失败。所选 View 是人工指定的范围，不能因为成功生成就声称快照覆盖了整个库；原简化快照不保留覆盖等级。
- `effective-build --allow-cross-library`：明确允许跨库时，来源键采用 `@<URL编码vendor>/<URL编码library>/<URL编码version>`，值包含 vendor、library、version、delivery。主库仍使用版本名→交付别名。保留 `@` 为复合键前缀。
- `effective-compare` 和 `effective-timeline`：仅以保存的 JSON 计算来源差异和沿父版本链的来源历史，不读取 RAW 内容；更换来源不等于内容发生变化。
- 旧 v1 的 `data-query --kind simple-effective` 可以将可解析的跨库成员投影到上述复合来源键。来源缺失或重复时拒绝转换；保持已有历史不变。

## 实际边界

`effective.simple.v2` 目前仍是可独立计算的格式和迁移投影，并非 `versions/service.py` 的权威持久化格式。索引重建、采纳日志、Web、原检查计划与 Excel 继续消费旧 v1；不能把 v2 JSON 直接复制到旧版本目录。未完成：完整历史双读/双格式版本发布、变化计算与旧文件位引用兼容、Formal 基准在旧消费链中的无损表达、跨库共享查询与 Web/Excel 接入、端到端采纳与历史回归。v1 投影不包含 `file_key`、旧 `source_ref` 及 `changes`，不应声称能够无损逆向还原全部 v1 或可直接覆盖旧记录。

离线正式基准样例位于 `exports/effective_formal_baseline_review_20261118/final/`，只用于测试，不代表采纳。来源差异及文件时间线样例位于 `exports/effective_v2_simulation_20261118/`，其中 V06 是人为构造。

## 旧历史迁移核验命令（本轮）

`effective-migrate --work <旧work> --runs <runs> --vendor <V> --library <L> --owner <owner> --out <新目录>` 会读取完整 v1 历史、检查父版本链及采纳事件重放结果，将每版导出为 v2，并输出原 v1 索引、事件以及带输出文件摘要的 `migration_report.json`。输出目录不能位于工作目录、RAW 或 Formal 根目录内；已存在则拒绝覆盖；成员无法解析则不发布。这个结果是 **SHADOW_ONLY 核验副本**，原 v1 历史仍是权威，不能直接放进旧工作台的 work 目录。

模拟样例：`exports/effective_history_migration_20261118/`。核验了 rev_0001 与 rev_0002 分别包含 1 和 2 个已记录成员；最新计算 rev_0002、当前采纳 rev_0001，采纳事件 1 条。记录原来的分离状态，不代表此次执行了新的采纳。

`versions/index_projector.py` 现在提供 `project_simple`：对 v2 父版本链和全部来源引用校验后，复用 v1 的采纳/回退/撤销事件重放规则；迁移副本发布前，会将 v2 重放得到的最新计算和当前采纳指针与旧索引比对。该函数尚未接入旧 Web 的版本写入服务。

## v2 消费接入（2026-11-19）

- `data-query --kind effective-v2 --vendor <V> --library <L> --set-id <set> --revision <rev>` 从扁平库目录读取 v2，并关联已保存 Delivery；Web `/api/library-data` 调用同一查询。只显示记录路径，不扫描原始目录；缺失、歧义、候选身份和内容未检查分别保留。
- 库工作台列出可解析的 v2 版本，`/effective-v2` 可查看和筛选成员。v2 页显示的是记录来源，不代表有效集已采纳或文件内容已检查。
- 检查计划可指定 `work_root` 并直接引用库目录中的 v2 目标和基线。适配器仅当所有成员的来源可唯一定位、分类为 RESOLVED 且来源证据为 explicit 时，才映射到旧检查器已有的真实 `file_key/file_id`；否则报错，禁止猜测。检查后沿用现有 CheckResult、HTML 和单次 Excel。v2 的旧版报告成员上下文暂不填充，报告说明会标明；不是整体 IP Excel 已完成。
- 模拟端到端样例：`exports/effective_v2_check_demo_20261119/`。其中 explicit 证据由演示脚本建立，使用项目示例事实，不代表真实库确认或生产采纳。

尚未完成：v2 权威版本写入与已有版本服务的完整切换、工作台原单版本/整体 IP 操作路径及整体 Excel 对 v2 的完整适配；迁移核验副本仍不是权威历史。

## 工作台整合（2026-11-19）

v2 成员和版本切换已并入原库工作台，复用供应商／库侧栏、交付历史、筛选样式及运行进度组件；早期 `/effective-v2` 链接兼容跳转到库工作台。选择版本后，若检查计划准确匹配本工作目录和版本文件，且所有成员身份已确认，可运行现有单版本检查并查看运行记录及 Excel。未确认成员或缺少计划时显示原因。整体 IP 批量检查仍未接入 v2；旧版工作台和 v1 权威版本服务继续使用原数据。
