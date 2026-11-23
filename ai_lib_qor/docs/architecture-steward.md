# ai_lib_qor 项目架构与维护基线

更新：2026-11-22。本文按当前本地源码和自动化测试结果整理；本工作区未识别为 Git 工作树，分支、HEAD 与未提交状态为**未知**。本文记录代码事实与工程边界，不是生产验收报告。

## 项目目标与核心数据链

面向 Vendor、来源库与有效版本，自动或受控地推进三层数据链（L1 来源 → L2 有效版本 → L3 文件索引），按需解析可信 FileFacts，执行可插拔 QoR 检查，并为 CLI、Web 页面、只读 JSON API 与 Excel 报告提供一致的只读查询语义。系统为**文件驱动的模块化单体**（无外部数据库依赖；SQLite 仍仅为 [ADR-0002](decisions/ADR-0002-persistent-projection-choice.md) 候选）。

```text
L1 来源层（只读扫描外部目录，追加不可变归档）
  RAW 总目录 ──> delivery/delivery_*.json + raw_observations.tsv
  Formal NL ──> formal/formal_*.json + formal_observations.tsv（无变化时仅写 UNCHANGED 心跳行）
                      │
                      ▼
L2 有效版本层（纯基于 L1 自动演进或显式预览发布；计算与采纳指针分离）
  effective/effective_<lib>_NNN.json + latest_effective.json
  人工显式采纳 ──> log/acceptance_events.jsonl + accepted_effective.json
                      │
                      ▼
L3 统一索引层（按归档内容 SHA-256 指纹校验；未变库自动跳过重建）
  file_index.json + .file_index_manifest.json
                      │
                      ▼
QoR 检查与报告层（数据持久化与报表渲染解耦）
  按需解析 ──> facts/fact_ca_<VIEW>_<hash16>.json.gz（内容寻址 gzip 共享池，跨版本/跨运行免重解析）
  插件检查 ──> log/check_rev_*_run_*.json（仅存轻量指针，不重复内嵌大对象）
  按需渲染 ──> log/check_rev_*_run_*.xlsx（支持 --no-excel / 懒生成 + 原子落盘缓存）
```

## 存储职责分离（权威历史 vs 可重建缓存）

| 分类 | 目录 / 文件 | 权威性 | 清理与重建策略 |
|---|---|---|---|
| **权威不可变历史** | `delivery/delivery_*.json`、`formal/formal_*.json`、`effective/effective_*.json` | 权威业务记录 | 严禁覆写或自动删除 |
| **权威检查与审计** | `log/check_rev_*_run_*.json`、`log/overall_run_*.json`、`log/*.tsv`、`log/*.jsonl`、`work/formal_observations.tsv` | 不可变结论与审计 | 严禁覆写或被缓存清理删除 |
| **状态指针** | `latest_delivery.json`、`latest_formal_*.json`、`latest_effective.json`、`accepted_effective.json`、`latest_check.json` | 指向权威文件的相对软链接 | 计算最新与人工采纳严格分离 |
| **可重建派生缓存** | `file_index.json`、`.file_index_manifest.json`、`facts/fact_ca_*.json.gz`、`log/check_rev_*_run_*.xlsx` | 派生投影/缓存 | 可通过 `storage-stats` 统计、`cache-clean` 安全演练/清理并按需重建 |

## 模块与代码职责（路径式主线）

| 位置 | 当前职责 | 边界与说明 |
|---|---|---|
| `pyproject.toml`、`.github/workflows/ci.yml`、`docs/schema-compatibility.md` | 标准 PEP 621 打包配置（`ai-lib-qor` 入口与 `schemas` 数据文件）、CI 测试流水线与 Schema 兼容演进规范 | 支持 `pip install -e .` 与 `PYTHONPATH=src` 双模式；`*.v1` 遵循只增不删原则。 |
| `versions/runtime.py`、`versions/store.py` | 零依赖运行时进度/取消原语（`JobCancelledError`/`check_cancel`/`emit_progress`）、本机内核态 `fcntl.flock`（含运行时锁序强制校验：先库锁后根锁、禁止同线程重入与同级逆序，不做超时抢锁）及带 `lru_cache` 缓存的 Schema 校验 | 最底层基础设施，不依赖任何上层业务或 UI 模块；跨主机 NFS 分布式锁留待真实部署环境专项验证。 |
| `cli.py` | 统一 CLI 入口（自动装载 `plugin_modules`；支持 `--format json\|table`、`check-pending --include-outdated`、检查 `--plugins` 与 `path-unadopted-ignore/unignore`） | 主线涵盖 `refresh*`、`check-pending`、`minimal-check-*`、`export-overview-excel`、`accept-revision`、`storage-stats`、`cache-clean`。 |
| `sources/root_inventory.py`、`sources/config_reader.py`、`sources/minimal_delivery.py`、`sources/layout.py` | 纯 L1 盘点 `inventory_sources`（单库 L1+Formal 精准作用域、可扩展 `VIEW_EXTENSIONS` 与 `.view_extensions_state.json` 映射漂移告警）、单一来源配置读取 `read_registration_times`、纯交付排序 `order_deliveries`、受控 5 子目录布局与 `formal_observations.tsv` 去重 | 绝不读取 `.gds`/`.db` 等原始文件内容；`build_from_roots` 仅作兼容薄封装，L2/L3 编排统一归口 `application/path_refresh.py`。 |
| `application/minimal_effective.py`、`application/path_acceptance.py` | L2 有效版本初始化/演化/预览/恢复、基于不可变 `effective/*.json` + `effective_operations.tsv` 权威推导已处理水位（`.auto_effective_state.json` 降级为可重建缓存）、独立人工采纳与回退（`accepted_effective.json`） | `CheckResult PASS` 绝不自动改写采纳指针；即使删除 `.auto_effective_state.json`，手工 `restore_revision`/`apply_update` 仍受不可变历史与审计日志保护。 |
| `application/minimal_file_index.py`、`application/path_query.py`、`application/path_refresh.py`、`application/plugin_loader.py` | L3 FileIndex 与单一合并 `fast_stat` 摘要（含 `size/mtime_ns/ctime_ns/ino` + 50ms racy-git 窗口与 O(Δ) 增量指纹，兼容旧 3 字段清单）、统一只读检查查询 `find_latest_check`（按 `(revision, baseline, plugins)` 精确匹配 + `runs.jsonl` 64KB tail-seek O(1)）、`check_tooling_status` 与 `plugin_modules` 装载器 | 打开页面/只读查询不扫描 RAW、未变库跳过重建；成熟归档免全量 SHA-256 重算且拦截保 `mtime` 篡改；`verify='strict'` / `--verify` 保留全量位级哈希复核。 |
| `facts/registry.py`、`facts/parsers.py`、`facts/_compat/` | 可插拔 View → Parser 注册表、签名（`parser_signature`）与 `current_parser_info` | `file_facts_path.schema.json` 支持扩展 View（`^[A-Z][A-Z0-9_]{1,31}$`）并保留 5 类内置严格校验；已支持 LEF、Liberty（含 `type()` + `bus()` SRAM 端口展开）、Verilog/CDL/SPICE（`PARTIAL`）。 |
| `checks/path_plugins.py`、`application/facts_pool.py`、`application/minimal_checks.py`、`application/path_batch.py` | 带版本号与元数据的可插拔检查插件、原子共享池+检查结果同锁发布边界（防并发 `clean_cache` 误删在途证据）、定点 `report_context` 上下文切片（重建 Excel 不混入后续交付）、单次 RAW 哈希取证、零项检查强制 `INCONCLUSIVE/PARTIAL`、`latest_check.json/.xlsx` 严格配对、增量批量检查 `check_pending`（严格校验插件集合与 `STALE_TOOLING`） | `CheckResult` 记录 `tooling` 与 `report_context`；`log/runs.jsonl` 同步记录 `baseline` 与 `plugins`；共享池存放于库下第 5 受控子目录 `facts/`（见 [ADR-0004](decisions/ADR-0004-dag-boundaries-l2-cursor-and-extensible-contracts.md)）。 |
| `application/path_storage.py` | 只读磁盘占用统计（区分权威历史与可重建缓存，含 `.auto_effective_state.json`/`.view_extensions_state.json`）与安全缓存清理 | `clean_cache` 默认 `dry_run=True`，仅清理有完好 JSON 支撑的 Excel 缓存或无引用孤儿共享事实。 |
| `reporting/check_renderer.py`、`reporting/qor_views.py`、`reporting/workbook_diff.py`、`reporting/path_workbook_model.py`、`reporting/work_overview_excel.py`、`reporting/excel.py`、`reporting/overall_excel.py` | 报告层 Excel 渲染编排（彻底承接单版/库级渲染）、可插拔 FileFacts 视图适配器、服务端分页/筛选、差异解包与多 Corner Pin 去重、通用插件 `findings[]` 渲染、v3 全工作区总览 Excel | 严格只读已保存结果；全库总览导出提示 `STALE_TOOLING` 升级待办而不扭曲原质检结论。 |
| `workbench/path_app.py`、`workbench/routes_{pages,actions,api}.py`、`workbench/jobs.py`、`workbench/templates/path_*.html`、`workbench/static/` | 启动自动装载 `plugin_modules`、模块化拆分的页面/动作/API 路由、只读 `/api/v1/*` JSON API、本机磁盘持久化作业管理（`work/.jobs/` 持久化历史、仅凭本机 PID+进程启动 tick 判定孤儿退出、绝不按超时误杀静默活任务、`O_CREAT\|O_EXCL` 本机跨 Worker 防重与 `.cancel` 取消信号） | 仅监听本机回环地址并强制 CSRF 校验；纯展示层（全 AST 守护测试确保零下层模块反向依赖 `workbench`，仅保留白名单内 2 处历史兼容代理）。 |
| 旧代模块与 Schema 归档 | 已全部无损归档至 `archive/20261122_旧代源码与Schema归档/` | 源码包收口为纯路径式主线并符合 [ADR-0004](decisions/ADR-0004-dag-boundaries-l2-cursor-and-extensible-contracts.md) 分层 DAG 约束（115 项自动化测试通过）。 |

## 核心状态分离红线

- RAW 扫描观察 ≠ 可信交付；Formal 链接记录 ≠ 内容字节一致。
- 版本来源变化 ≠ 内容变化；运行 `SUCCEEDED` ≠ 质检 `PASS` ≠ 人工采纳（`accepted_effective.json`）。
- 未解析/部分解析（`NOT_CHECKED` / `PARTIAL` / `INCONCLUSIVE`）不得伪装为通过。

## 已知边界与后续待决项

1. **跨库 Business IP 聚合检查**：路径式主线当前为单库有效版本与库内多版本整体汇总，跨多来源库组装 Business IP 维度仍待后续明确定义与实现。
2. **旧代 v1/v2/v3 模块收口**：现有测试仍覆盖旧代模块，在确认生产历史数据全部迁至路径式结构后，可规划分批归档下线。
3. **锁与分布式存储**：`versions/store.py` 聚焦本机内核态 `fcntl.flock` 并强制运行时锁序（先库锁后工作区根锁，禁止同线程重入与同级逆序），`JobManager` 仅依据本机 OS PID 与 `/proc/<pid>/stat` 启动 tick 回收已退出进程孤儿，绝不按超时强杀活进程；跨主机 NFS/HPC 高并发写入留待真实目标环境专项设计与压测，不以未验证的超时抢锁替代。
4. **Parser 深度**：Liberty 尚未覆盖 PVT Corner、PG Pin 与时序/功耗表；GDS/SPEF/UPF 等尚未纳入解析。
5. **生产验收边界**：开源 PDK 沙箱压测与单元测试不替代真实生产全量工艺库、大并发与故障恢复验收。
