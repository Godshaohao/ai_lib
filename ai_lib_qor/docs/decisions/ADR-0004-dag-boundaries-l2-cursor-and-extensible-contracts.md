# ADR-0004：分层 DAG 边界、L2 高水位游标与可扩展 View/插件契约

日期：2026-11-23；状态：已实施，单元测试（115 项，含独立代码审查复现的全部 6 项 P1/P2 问题回归与 4 项收敛校验）与本地只读校验通过（非生产全量验收）。

## 1. 背景与问题

在前期三层自动刷新（L1/L2/L3）与模块化工作台落地后，源码审计暴露出以下结构与流程缺陷：
1. **L2 自动演化状态路径分裂与手工回退被覆写**：`sources/root_inventory.py` 将 `.auto_effective_state.json` 写入 `log/`，而 `application/path_refresh.py` 读写库根目录，导致跨层状态分裂；且 `refresh_l2` 扫描全量已归档交付版本，会在下次刷新时覆写用户通过 `restore_revision` / `apply_update` 手工回退或锁定的有效版本。
2. **多版本批量刷新冗余与单库 L1+Formal 范围泄漏**：多交付批量推进时逐个版本重建 L3 `file_index.json`；指定单库且启用 Formal 盘点时仍退化为全量 RAW 遍历。
3. **反向/环形包依赖**：`sources` / `application` 反向导入 `workbench.jobs`（取消与进度原语），`application/path_batch.py` 反向导入 `reporting/qor_views.py`，`sources/root_inventory.py` 与 `application/path_refresh.py` 存在重复的 L2/L3 自动演化实现。
4. **工具链升级不可见与新 View/插件契约受锁**：解析器升级后已有检查结果缺少显式过时标记（`STALE_TOOLING`）；`file_facts_path.schema.json` 与 `check_result_path.schema.json` 硬编码了 View 枚举，限制新 View（如 SPEF/UPF/SDC）与自定义检查插件落地。

## 2. 决策

1. **严格分层 DAG 与模块拆分**：
   - 将进度回调与协作式终止原语下沉至零依赖的 `versions/runtime.py`（`workbench/jobs.py` 保持兼容重导出），消除全部 `* -> workbench` 反向依赖。
   - 纯交付排序逻辑下沉至 `sources/minimal_delivery.py:order_deliveries`；纯 L1 盘点逻辑收口为 `sources/root_inventory.py:inventory_sources`（零 `application` 依赖），`build_from_roots` 保留为兼容薄封装并统一委托 `application/path_refresh.py` 执行 L2/L3，消除重复逻辑。
   - 将只读检查检索（`latest_check_for_scope`、`latest_check_for_revision`）、工具链过时判定（`check_tooling_status`）及未纳入新文件统计（`unadopted_new_files`）统一收口至 `application/path_query.py`，消除 `application -> reporting` 查询环与重复实现。
   - 拆解超大模块：`facts_pool.py`（共享池 I/O）、`workbook_diff.py`（差异解包与去重）、`routes_pages.py` / `routes_actions.py` / `routes_api.py`（保持全部 Flask 端点名不变）。
2. **L2 权威状态与高水位游标（`processed`）**：
   - 统一 `.auto_effective_state.json` 权威路径至 `log/.auto_effective_state.json`（读取时自动兼容合并旧库根目录文件并清理分裂副本），字段扩展为 `{"pending": [...], "processed": [...]}`。
   - `refresh_l2` 仅对 `pending` 及未出现在 `processed` 的新交付自动推进；手工执行 `restore_revision` / `apply_update` / `update_effective` 时将当前已归档非 `pending` 交付记入 `processed`，确保手工回退/锁版不被后续自动刷新覆写，同时真正新到的交付仍可正常推进。
   - 单库多交付批量 L2 推进期间通过 `_save(..., refresh_idx=False)` 延迟索引刷新，仅在库循环结束后执行一次 `refresh_index_locked`。
   - 单库 L1+Formal 盘点仅遍历目标 `raw/<vendor>/<library>`，在 Formal 阶段跳过指向同 RAW 树其他库的软链接，不误判为 `UNMATCHED` 且不覆盖全局去重状态。
3. **工具链升级可见性、未纳入新文件提示与并发作业防重**：
   - 新增 `check_tooling_status()`（兼容新 `CheckResult.tooling` 字段及历史 `facts_evidence[].parser`），识别 `STALE_TOOLING`；`check-pending` 默认保守跳过并统计 `outdated_tooling_count`，加 `--include-outdated` 时显式重检。
   - 保持“不自动推断纳入新文件”的保守红线，通过 `unadopted_new_files` 在 L2 汇总、状态查询、Web 库页与 API 中透明提示最新交付中的未纳入文件数。
   - `JobManager.submit` 支持 `scope_key` 防重，Web 同范围重复异步任务返回 HTTP `409` 并携带 `active_job`，前端自动重连进度面板。
4. **可扩展 View 与插件契约**：
   - `file_facts_path.schema.json` 将顶层 `view` 放宽为大写标识正则 `^[A-Z][A-Z0-9_]{1,31}$`（保留 LEF/LIBERTY/VERILOG/CDL/SPICE 五类内置严格校验，并在 LIBERTY 下预留可选 `operating_conditions` / `pg_pins`）；`check_result_path.schema.json` 放宽 `partial_comparisons[].view` 并新增可选 `checks[].severity`、`checks[].findings[]` 与顶层 `tooling`。
   - 提供 `register_view_extension` 与 `path_sources.json` `view_extensions` 配置、`checks/path_plugins.py` 元数据与动态 `describe_check_note`、CLI `--plugins` 开关，以及 Excel `03-对象与接口差异` 对任意自定义插件 `findings[]` 的自动渲染。

## 3. 二期加固补充决策（2026-11-22）

针对首版评审暴露的深层隐患，补充落地以下 6 项加固：
1. **L2 防覆写水位权威化**：`derive_processed_versions()` 直接从不可变 `effective/*.json` 与 `log/effective_operations.tsv`（含手工 `UPDATE`/`RESTORE` 写入的 `watermark=[...]` 及无变更 `AUTO_ACK`）推导已处理集合，`.auto_effective_state.json` 降级为可重建缓存（删除后防覆写机制依然生效）。
2. **工程化打包与 Schema 缓存**：新增 `pyproject.toml`（PEP 621、`ai-lib-qor` 入口、`share/ai_lib_qor/schemas` 数据文件）与 `.github/workflows/ci.yml`；`versions/store.py` 改为 `importlib.resources`/wheel/源码路径解析 + `lru_cache` 编译校验器缓存，并书面固化“先库锁、后工作区根锁”锁序不变量。
3. **运行时插件装载与插件版本化**：新增 `application/plugin_loader.py`（支持 `path_sources.json` `plugin_modules` 与 `AI_LIB_QOR_PLUGIN_MODULES` 自动导入并调用 `register(api)`，以及测试用 `isolated_registries()`）；检查插件增加 `version` 元数据并写入 `CheckResult.tooling.plugin_versions`，插件规则升级同样触发 `STALE_TOOLING`。
4. **读路径性能加固**：
   - `.file_index_manifest.json` 增设 `strict_stat`（含 `size/mtime_ns/ctime_ns/ino`）与 `written_at_ns`，采用 50ms racy-git 防护窗口：成熟归档在未变更时跳过全量 SHA-256（同时因 Linux `st_ctime_ns` 不可由 `os.utime()` 伪造，仍可 100% 拦截同字节长度 + 保留 `mtime` 的篡改）；`archive_fingerprint` 在增量刷新时按 O(Δ) 复用未变文件哈希；`verify='strict'` / `--verify` 保留无条件全量哈希复核。
   - `run_library` 与 `_run` / `build_facts` 复用已校验索引并通过 `strict_stat` 执行运行中漂移检查，将多版本库级检查的索引加载与构建从 `3N + 文件数` 次降至单次。
   - `log/runs.jsonl` 补充记录 `baseline`，`latest_check_for_scope` / `latest_check_for_revision` 优先 64KB tail-seek O(1) 命中（目录 `mtime_ns` 有带外变更时自动回退）；`.file_index_manifest.json` 缓存 `unadopted_new_files_count` 与忽略清单摘要，无有效版本库 0 JSON 读取短路。
5. **持久化跨进程后台作业、锁序运行时强制与 NFS 原子锁**：
   - `workbench/jobs.py:JobManager(work_root=...)` 将任务状态原子持久化至 `work/.jobs/jobs/<job_id>.json`（服务重启后任务历史保留，且自动识别死进程/超时租约孤儿任务标为 `INTERRUPTED` 并回收租约），通过 `O_CREAT|O_EXCL` 独占租约文件（`work/.jobs/leases/`）实现跨进程 `scope_key` 防重，通过 `.cancel` 标记文件实现跨进程安全终止。
   - `versions/store.py:locked()` 引入线程局部锁栈在运行时强制“先库锁、后工作区根锁”、禁止同线程重入与同级逆序，并提供 `AI_LIB_QOR_LOCK_MODE=mkdir` 原子目录锁后端以适配 NFS 环境。
6. **View 映射漂移告警、Schema 兼容文档与未纳入忽略清单**：L1 持久化 `work/.view_extensions_state.json` 并在扩展名映射变化时显式告警；新增 `docs/schema-compatibility.md`；新增 `ignored_unadopted_files` 配置与 CLI/Web 忽略入口；登记时间读取统一收口至 `sources/config_reader.py`。
7. **彻底解耦 Excel 渲染编排与全 AST 守护**：新建 `reporting/check_renderer.py` 承接单版与库级 Excel 渲染，CLI 与 Web 通过依赖注入传入渲染器；DAG 守护测试升级为递归检查模块顶层及全部函数体内部导入，仅允许冻结的 2 处历史兼容代理白名单。

## 4. 三期可信度修复与过度防御收敛（2026-11-23）

针对独立代码审查复现的 6 项 P1/P2 缺陷、4 项过度防御与 1 项子目录约定漂移，落地如下修订：
1. **按插件记录覆盖与统一结论判定**：`run_path_plugins()` 按插件追踪实际产出并在 `tooling.plugin_coverage` 记录 `EXECUTED` / `NOT_EXECUTED` / `NOT_APPLICABLE`；显式请求的未执行插件、无基线被抑制的对比插件以及整次零输出运行均显式记录 `INCONCLUSIVE` 并置 `state='PARTIAL'`。检查列表、详情页与 `/api/v1/check` API、单版/库级 Excel 全部收口至单一权威函数 `checks/path_plugins.py:evaluate_check_verdict()`，历史零结果 `SUCCEEDED` 记录亦不再显示 `SCOPE_PASS`。
2. **增量检查与整体检查统一按 `(revision, baseline, plugins)` 匹配**：收敛为单一查询入口 `path_query.py:find_latest_check()`（`runs.jsonl` 同步记录 `plugins`）；`check_pending` 与 `run_library` 严格校验插件集合，不再因只跑过部分规则的旧结果而跳过其他规则。
3. **共享池与 CheckResult 共用同一原子发布边界（不重入库锁）**：`minimal_checks.py` 在 `with locked(folder):`（与 `clean_cache` 共用同一把库锁）内经 `PathDataQuery._index_locked()` 复核归档未漂移（避免发布锁内重复加锁报错），随后一次性落盘引用的 `facts/fact_ca_*.json.gz`、`check_*.json`、更新指针并追加 `runs.jsonl`，彻底消除并发 `--orphan-facts` 删空在途检查证据的竞态。
4. **定点 `report_context`（含精确 `formal_snapshots` 标识）隔离历史 Excel 重建**：`check_result_path.schema.json` 增补可选 `report_context`（`deliveries`、`revisions`、`nl_observed_cutoff`、`formal_snapshots`），`facts_pool.py:slice_index_for_report()` 按检查发生时刻及精确 Formal 快照文件名集合切片还原索引，确保同 Run 重建 Excel 绝不混入后续新增交付或同一秒内新增的 Formal 快照。
5. **收敛超时抢锁误杀与无用作业超时字段**：移除易在活进程存活时误回收的 NFS 超时 `mkdir` 锁、作业心跳超时误杀以及已退出判定路径的 `lease_ttl_seconds` / `heartbeat_ts` 字段；`store.py` 收敛为本机内核态 `fcntl.flock` + 运行时锁序栈校验，`jobs.py` 仅凭本机 PID 及 `/proc/<pid>/stat` 启动 tick 识别真正退出的孤儿进程，保留进度、取消与重启记录。
6. **保持 `latest_check.json/.xlsx` 严格配对**：`--no-excel`（`render=False`）发布新检查时清除旧 `latest_check.xlsx` 指针；渲染完成后仅当 `latest_check.json` 仍指向本 Run 才更新 `latest_check.xlsx`。
7. **收敛重复 RAW 哈希、逐文件整库枚举与双份索引摘要**：`minimal_checks.py` 与 `minimal_facts.py` 共享预计算 `(stat_key, sha256)` 证据（成熟文件冷检查降至 1 次 SHA-256/文件）；检查编排内的内存解析保留逐文件身份与稳定校验，将整库归档枚举收口到检查开始与发布前（6 文件冷检查从 9 次降至 2 次；独立单文件导出仍保留完整独立校验）；`minimal_file_index.py` 将 `fast_stat`/`strict_stat` 合并为单次枚举的一份 5 元组 `fast_stat`（向下兼容旧 3 元组清单）。
8. **正式确认库下五子目录约定**：保留并正式确认库目录 5 个受控子目录（`delivery/`、`formal/`、`effective/`、`log/`、`facts/`），其中前 4 个承载不可变权威业务历史与检查/审计记录，`facts/` 专职存放内容寻址可重建共享池缓存（与已有 `work/` 不可变 `check_*.json` 引用路径一致）。

## 5. 保持不变的红线

- 不引入 SQLite 或外部数据库；权威历史文件不可变。
- 不因为打开页面或只读查询触发 RAW 扫描、索引重建或解析；不自动将新交付文件加入 Effective；`CheckResult PASS` 不自动改写 `accepted_effective.json`。
