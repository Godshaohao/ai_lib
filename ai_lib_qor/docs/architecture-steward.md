# ai_lib_qor 项目架构与维护基线

更新：2026-11-24。本文按当前本地源码和自动化测试结果整理；本工作区未识别为 Git 工作树，分支、HEAD 与未提交状态为**未知**。本文记录代码事实与工程边界，不是生产验收报告。

## 项目目标与核心数据链

面向 Vendor、来源库与有效版本（含单物理库多业务 IP 分轨），自动或受控地推进三层数据链（L1 来源 → 业务 IP 分轨 → L2 有效版本 → L3 文件索引），按需解析可信 FileFacts，执行可插拔 QoR 检查，并为 CLI、Web 页面、只读 JSON API 与 Excel 报告提供一致的只读查询语义。系统为**文件驱动的模块化单体**（无外部数据库依赖；SQLite 仍仅为 [ADR-0002](decisions/ADR-0002-persistent-projection-choice.md) 候选）。

```text
L1 来源层（只读扫描外部目录，追加不可变归档；物理层零感知业务 IP）
  RAW 总目录 ──> delivery/delivery_*.json + raw_observations.tsv
  Formal NL ──> formal/formal_*.json + formal_observations.tsv（无变化时仅写 UNCHANGED 心跳行）
                      │
                      ▼
业务 IP 分轨层（可选，仅在 work/path_sources.json 配置 ip_list 时启用；增量保护人工已确认 tracks）
  work/libraries/<vendor>/<library>/ip_partition.json（按双主键隔离，只读兼容旧 work/ip_partition_<lib>.json；tracks + needs_review[conflicts/unassigned] + auto_trace）
                      │
                      ▼
L2 有效版本层（纯基于 L1 自动演进或显式预览发布；计算与采纳指针按轨道独立）
  单轨库：effective/effective_<lib>_NNN.json + latest_effective.json / accepted_effective.json
  多轨库：effective/effective_<lib>__<ip>_NNN.json + latest_effective__<ip>.json / accepted_effective__<ip>.json
                      │
                      ▼
L3 统一索引层（按归档内容 SHA-256 指纹校验；未变库自动跳过重建；多轨视图由 path_query 只读投影）
  file_index.json + .file_index_manifest.json
                      │
                      ▼
QoR 检查与报告层（数据持久化与报表渲染解耦；严格限定在同一业务 IP 轨道内比对）
  按需解析 ──> facts/fact_ca_<VIEW>_<hash16>.json.gz（按物理文件跨轨道/跨版本共享，免重解析）
  插件检查 ──> log/check_<lib>_rev_*_<YYYYMMDD>.json 或 log/check__<ip>__rev_*_<YYYYMMDD>.json（结果一致自动复用，同日变更补 _2）
  按需渲染 ──> 对应 .xlsx（支持 --no-excel / 懒生成 + 原子落盘缓存）
```

## 存储职责分离（权威历史 vs 可重建缓存）

| 分类 | 目录 / 文件 | 权威性 | 清理与重建策略 |
|---|---|---|---|
| **权威不可变历史** | `delivery/delivery_*.json`、`formal/formal_*.json`、`effective/effective_<lib>_NNN.json`、`effective/effective_<lib>__<ip>_NNN.json` | 权威业务记录 | 严禁覆写或自动删除 |
| **业务分轨与来源配置** | `work/path_sources.json`、`work/libraries/<vendor>/<library>/ip_partition.json`（兼容旧 `work/ip_partition_<lib>.json`） | 人工可编辑权威配置 | 增量匹配严格保留已确认 `tracks`，禁止覆写人工归属与顺序 |
| **权威检查与审计** | `log/check_*_run_*.json`、`log/overall_*run_*.json`、`log/*.tsv`、`log/*.jsonl`、`work/formal_observations.tsv` | 不可变结论与审计 | 严禁覆写或被缓存清理删除 |
| **状态指针** | `latest_delivery.json`、`latest_formal_*.json`、`latest_effective[__<ip>].json`、`accepted_effective[__<ip>].json`、`latest_check[__<ip>].json`、`latest_overall[__<ip>].xlsx` | 指向权威文件的相对软链接 | 计算最新与人工采纳按轨道严格分离 |
| **可重建派生缓存** | `file_index.json`、`.file_index_manifest.json`、`facts/fact_ca_*.json.gz`、`log/check_*_run_*.xlsx`、`log/.auto_effective_state[__<ip>].json` | 派生投影/缓存 | 可通过 `storage-stats` 统计、`cache-clean` 安全演练/清理并按需重建 |

## 模块与代码职责（路径式主线）

| 位置 | 当前职责 | 边界与说明 |
|---|---|---|
| `pyproject.toml`、`.github/workflows/ci.yml`、`docs/schema-compatibility.md` | 标准 PEP 621 打包配置（`ai-lib-qor` 入口与 `schemas` 数据文件）、CI 测试流水线与 Schema 兼容演进规范 | 支持 `pip install -e .` 与 `PYTHONPATH=src` 双模式；`effective_path` 与 `check_result_path` 已按只增不删原则扩展可选 `business_ip` / `ip_type` / `track_id`。 |
| `versions/runtime.py`、`versions/store.py` | 零依赖运行时进度/取消原语（`JobCancelledError`/`check_cancel`/`emit_progress`）、组合根依赖注入 Hook 注册表（`register_hook`/`get_hook`）、本机内核态 `fcntl.flock`（含运行时锁序强制校验：先库锁后根锁、禁止同线程重入与同级逆序，不做超时抢锁）及带 `lru_cache` 缓存的 Schema 校验（含 `path_sources.schema.json` 与 `ip_partition.schema.json`） | 最底层基础设施，不依赖任何上层业务或 UI 模块；跨主机 NFS 分布式锁留待真实部署环境专项验证。 |
| `cli.py` | 统一 CLI 入口（自动装载 `plugin_modules`；支持 `--format json\|table`、`partition-ips`、`path-tracks`、`--ip` / `--ip-type`、`check-pending --include-outdated`、检查 `--plugins` 与 `path-unadopted-ignore/unignore`） | 主线涵盖 `refresh*`、`partition-ips`、`path-tracks`、`check-pending`、`minimal-check-*`、`export-overview-excel`、`accept-revision`、`storage-stats`、`cache-clean`。 |
| `sources/root_inventory.py`、`sources/config_reader.py`、`sources/minimal_delivery.py`、`sources/layout.py` | 纯 L1 盘点 `inventory_sources`（单库 L1+Formal 精准作用域、新交付按 `delivery_<lib>__<version>.json` 命名且无 `_001` 仅碰撞时补序、记录 `directory_mtime`、可扩展 `VIEW_EXTENSIONS` 与 `.view_extensions_state.json` 映射漂移告警）、单一来源配置读取 `read_registration_times`、纯交付排序 `order_deliveries`（优先目录日期 `version_date`，无日期或同日依次回退 `version_registration_times` → `directory_mtime`，同秒冲突拒绝猜测）、受控 5 子目录布局与 `formal_observations.tsv` 去重 | 物理事实层严禁感知业务 IP；绝不读取 `.gds`/`.db` 等原始文件内容；`build_from_roots` 仅作兼容薄封装，L2/L3 编排统一归口 `application/path_refresh.py`。 |
| `application/ip_partition.py`、`application/path_config.py` | 单物理库多业务 IP 两阶段自动划分引擎（阶段 1 版本名长名优先+跨度 subsumption 匹配 → 阶段 2 核心 EDA 文件 `.lef/.lib/.db/.v/.cdl` → 兜底全文件名）、`work/ip_partition_<lib>.json` 增量读写（严格保留人工已确认 `tracks`，仅匹配新版本；输出 `needs_review` 冲突/未归类与 `auto_trace`）、`ip_type`/`ip_list` 配置解析、`skip_parse_views` 视图解析跳过策略（默认跳过 `CDL`/`SPICE`/`VERILOG`，支持全局与单库覆盖），以及 `liberty_parse_filter` 大库 `.lib` 阈值+关键词抽样策略（支持全局默认与单库覆盖） | 未配置 `ip_list` 的库 100% 保持单轨行为与原文件命名；`skip_parse_views` 默认跳过网表与 Verilog 解析（保留在 L1/L2/L3 清单中，检查时零磁盘读取并显式标为 `NOT_CHECKED`，设 `[]` 可按需恢复）；`liberty_parse_filter` 超阈值跳过文件同样零磁盘读取并标为 `NOT_CHECKED`（`state='PARTIAL'`）。 |
| `application/minimal_effective.py`、`application/path_acceptance.py` | L2 有效版本初始化/演化/预览/恢复（支持 Formal 优先初始化，以及无 Formal 覆盖的单轨/多轨库按 A+ 历史折叠窗口 `initial_delivery_tail`（默认 3）将早期 `max(1, N-k)` 版按序叠加为完整 `rev_0001`、最近 `k` 版逐版演进；支持按 `(library, business_ip)` 隔离多份 Effective 历史、指针、审计日志与水位，禁止跨轨道手工引用；高版本 RAW 自动推进时既升级已有成员也自动合并该高版本新增文件路径，跳过 `ignored_unadopted_files` 且不回拉旧版本未链入文件）、独立人工采纳/回退及按 `ip_type` 聚合汇总（`acceptance_summary_by_ip_type`） | `CheckResult PASS` 绝不自动改写采纳指针；即使删除 `.auto_effective_state[__<ip>].json`，手工 `restore_revision`/`apply_update` 及折叠基线水位仍受不可变历史与审计日志保护。 |
| `application/minimal_file_index.py`、`application/path_query.py`、`application/path_refresh.py`、`application/plugin_loader.py` | L3 物理 FileIndex 与单一合并 `fast_stat` 摘要、只读多轨投影 `build_track_index_view` 与 `PathDataQuery.list_tracks()`、统一只读检查查询 `find_latest_check`（按 `(revision, baseline, plugins, business_ip)` 精确匹配 + `runs.jsonl` 64KB tail-seek O(1)）、`check_tooling_status` 与 `plugin_modules` 装载器 | `minimal_file_index.py` 保持物理层纯净，多轨视图完全通过 `path_query.py` 只读投影；打开页面/只读查询不扫描 RAW、不重跑分轨、未变库跳过重建。 |
| `facts/registry.py`、`facts/parsers.py`、`facts/_compat/` | 可插拔 View → Parser 注册表、签名（`parser_signature`）与 `current_parser_info` | 物理文件共享解析事实，不感知业务 IP；`file_facts_path.schema.json` 支持扩展 View（`^[A-Z][A-Z0-9_]{1,31}$`）并保留 5 类内置严格校验；已支持 LEF、Liberty（含 `type()` + `bus()` SRAM 端口展开）、Verilog/CDL/SPICE（`PARTIAL`）。 |
| `checks/path_plugins.py`、`application/facts_pool.py`、`application/minimal_checks.py`、`application/path_batch.py` | 带版本号与元数据的可插拔检查插件、轨道严格隔离检查与 Diff（禁止不同业务 IP 互相 Diff；`facts_pool.load_check_bundle` 自动按 `report['business_ip']` 投影索引）、原子共享池+检查结果同锁发布边界、定点 `report_context` 上下文切片、增量批量检查 `check_pending`（支持 `--ip` / `--ip-type`） | `CheckResult` 记录 `tooling`、`report_context` 及可选 `business_ip`/`ip_type`/`track_id`；`log/runs.jsonl` 同步记录 `business_ip`/`baseline`/`plugins`；共享池存放于库下第 5 受控子目录 `facts/`（见 [ADR-0004](decisions/ADR-0004-dag-boundaries-l2-cursor-and-extensible-contracts.md)）。 |
| `application/path_storage.py` | 只读磁盘占用统计（区分权威历史与可重建缓存，涵盖多轨 Effective/Check/Overall/State）与安全缓存清理 | `clean_cache` 默认 `dry_run=True`，仅清理有完好 JSON 支撑的 Excel 缓存或无引用孤儿共享事实（保护所有多轨检查引用的共享池文件）。 |
| `reporting/check_renderer.py`、`reporting/qor_views.py`、`reporting/workbook_diff.py`、`reporting/path_workbook_model.py`、`reporting/work_overview_excel.py`、`reporting/excel.py`、`reporting/overall_excel.py` | 报告层 Excel 渲染编排（单版/库级/多轨渲染与只读重渲染）、可插拔 FileFacts 视图适配器、服务端分页/筛选、差异解包与多 Corner Pin 去重、v3 全工作区总览 Excel（支持多轨逐轨道展开、`P2 · 分轨` 待办及按 `ip_type` 生成 `02-IP类型汇总`） | 严格只读已保存结果；无 `ip_type`/多轨库的工作区维持原 2-Sheet 与前 16 列索引 100% 兼容。 |
| `workbench/path_app.py`、`workbench/routes_{pages,actions,api}.py`、`workbench/refresh_forms.py`、`workbench/jobs.py`、`workbench/templates/path_*.html`、`workbench/static/` | 启动自动装载 `plugin_modules`、支持配置/环境变量控制 `max_workers` 与分页大小、薄页面适配层 + 完备无状态 `/api/v1/*` 读写 API（含 `inventory`/`index`/`overall`/`config`/`acceptance`/`effective/{preview,apply}`/`unadopted/ignore`/`partition`/`organizer`）、单库配置只读/编辑抽屉、本机磁盘持久化作业管理 | 默认监听本机回环地址，支持按工作目录配置监听和客户端/Host 白名单，并强制 CSRF 校验；纯展示层，全 AST 守护测试零白名单强制保障 7 层严格单向 DAG（`versions → sources → facts → checks → application → reporting → workbench`）。 |
| 旧代模块与 Schema 归档 | 已全部无损归档至 `archive/20261122_旧代源码与Schema归档/` | 源码包收口为纯路径式主线并符合 [ADR-0004](decisions/ADR-0004-dag-boundaries-l2-cursor-and-extensible-contracts.md) 分层 DAG 约束。 |

## 核心状态分离红线

- RAW 扫描观察 ≠ 可信交付；Formal 链接记录 ≠ 内容字节一致。
- 物理库交付归档 ≠ 业务 IP 轨道切分；自动匹配结果 ≠ 人工已确认 `tracks`（增量重跑禁止覆盖人工确认项）。
- 版本来源变化 ≠ 内容变化；运行 `SUCCEEDED` ≠ 质检 `PASS` ≠ 人工采纳（`accepted_effective[__<ip>].json`）。
- 未解析/部分解析（`NOT_CHECKED` / `PARTIAL` / `INCONCLUSIVE`）不得伪装为通过。

## 已知边界与后续待决项

1. **跨多物理库 Business IP 聚合检查**：当前已完成**单物理来源库内**的多业务 IP 分轨有效版本、独立检查、采纳与按 `ip_type` 汇总；若需跨多个独立物理来源库组装同一个 Business IP，仍待后续专项定义与实现。
2. **旧代 v1/v2/v3 模块收口**：现有测试仍覆盖旧代模块，在确认生产历史数据全部迁至路径式结构后，可规划分批归档下线。
3. **锁与分布式存储**：`versions/store.py` 聚焦本机内核态 `fcntl.flock` 并强制运行时锁序（先库锁后工作区根锁，禁止同线程重入与同级逆序），`JobManager` 仅依据本机 OS PID 与 `/proc/<pid>/stat` 启动 tick 回收已退出进程孤儿，绝不按超时强杀活进程；跨主机 NFS/HPC 高并发写入留待真实目标环境专项设计与压测，不以未验证的超时抢锁替代。
4. **Parser 深度**：Liberty 尚未覆盖 PVT Corner、PG Pin 与时序/功耗表；GDS/SPEF/UPF 等尚未纳入解析。
5. **生产验收边界**：开源 PDK 沙箱压测与单元测试不替代真实生产全量工艺库、大并发与故障恢复验收。
