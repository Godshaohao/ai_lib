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
| `cli.py` | 统一 CLI 入口（主线命令分四组呈现，支持 `--format json\|table`；历史 v1/v2/v3 命令隐藏但保持兼容） | 主线涵盖 `refresh*`、`check-pending`、`minimal-check-*`、`accept-revision`、`storage-stats`、`cache-clean`。 |
| `sources/root_inventory.py`、`sources/layout.py` | L1 RAW/Formal 盘点、受控 5 子目录布局、`formal_observations.tsv` 去重 | 拒绝符号链接越界；观察不完整（存在 `unresolved`）时不替换前序 Formal 快照且记录全量明细。 |
| `application/minimal_effective.py`、`application/path_acceptance.py` | L2 有效版本初始化/演化/预览/恢复；独立的人工采纳与回退（`accepted_effective.json`） | `CheckResult PASS` 绝不自动改写采纳指针；历史版本只读不可篡改。 |
| `application/minimal_file_index.py`、`application/path_query.py`、`application/path_refresh.py` | L3 FileIndex 与 SHA-256 manifest 校验、只读统一查询、三层自动刷新编排 | 打开 Web 页面或查询时直接按内容指纹验真，未变库跳过重建；可拦截保持 `mtime` 不变的篡改。 |
| `facts/registry.py`、`facts/parsers.py`、`facts/_compat/` | 可插拔 View → Parser 注册表与签名（`parser_signature`） | 已支持 LEF、Liberty（含 `type()` + `bus()` SRAM 端口展开）、Verilog/CDL/SPICE（`PARTIAL`）；未覆盖 View 明确标为 `NOT_CHECKED`。 |
| `checks/path_plugins.py`、`application/minimal_checks.py`、`application/path_batch.py` | 可插拔检查插件编排、内容寻址共享池复用、原子懒渲染 Excel、增量批量检查 `check_pending` | `load_check_bundle()` 透明还原共享池事实并兼容旧内嵌格式。 |
| `application/path_storage.py` | 只读磁盘占用统计（区分权威历史与可重建缓存）与安全缓存清理 | `clean_cache` 默认 `dry_run=True`，仅清理有完好 JSON 支撑的 Excel 缓存或无引用孤儿共享事实。 |
| `reporting/qor_views.py`、`reporting/excel.py` | 可插拔 FileFacts 视图适配器、服务端分页/筛选、单版本对比视图与 Excel 渲染 | `paginate_facts_view` / `paginate_facts_diff` 避免大工艺库数千 Pin 一次性撑爆浏览器 DOM。 |
| `workbench/path_app.py`、`workbench/jobs.py`、`workbench/templates/path_*.html`、`workbench/static/` | 拆分的模块化 Web 模板、静态资源、只读 `/api/v1/*` JSON API 与有界异步后台任务队列 | 仅监听本机回环地址并强制 CSRF 校验；长耗时刷新/检查支持后台异步提交与轮询。 |
| 旧代兼容模块（`workbench/app.py`、`application/v2_*`、`v3_*`、`versions/` 等） | 保留旧测试与历史迁移兼容 | 未获明确下线授权前保留兼容，不作为新功能开发主线。 |

## 核心状态分离红线

- RAW 扫描观察 ≠ 可信交付；Formal 链接记录 ≠ 内容字节一致。
- 版本来源变化 ≠ 内容变化；运行 `SUCCEEDED` ≠ 质检 `PASS` ≠ 人工采纳（`accepted_effective.json`）。
- 未解析/部分解析（`NOT_CHECKED` / `PARTIAL` / `INCONCLUSIVE`）不得伪装为通过。

## 已知边界与后续待决项

1. **跨库 Business IP 聚合检查**：路径式主线当前为单库有效版本与库内多版本整体汇总，跨多来源库组装 Business IP 维度仍待后续明确定义与实现。
2. **旧代 v1/v2/v3 模块收口**：现有测试仍覆盖旧代模块，在确认生产历史数据全部迁至路径式结构后，可规划分批归档下线。
3. **锁与分布式存储**：`versions/store.py` 使用单机 POSIX `fcntl.flock`（不可重入）；若未来迁移到跨主机 NFS/HPC 并发写入同一 `work/`，需先做专项并发压测与锁方案评审。
4. **Parser 深度**：Liberty 尚未覆盖 PVT Corner、PG Pin 与时序/功耗表；GDS/SPEF/UPF 等尚未纳入解析。
5. **生产验收边界**：开源 PDK 沙箱压测与单元测试不替代真实生产全量工艺库、大并发与故障恢复验收。
