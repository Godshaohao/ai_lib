# ADR-0002: Catalog 持久化查询投影的实现选型

- 状态：IMPLEMENTED（2026-11-26 获用户明确授权落地）
- 日期：2026-11-18（更新：2026-11-26）
- 范围：LibraryCatalog / Query Service 的跨库聚合性能、持久查询投影与共享读语义

## 背景

在 500 库、15,000 次交付本地容量实测中，纯文件扫描路径下的冷总览（1.58 s）、全工作区 JSON 产物盘点（1.10 s，3 万+ 文件）与跨库组合质检检索仍需遍历大量目录和元数据文件；在 NFS/GPFS 共享盘与多 Worker 场景下，重复跨网 `os.stat` 成本会进一步放大。

## 决策

采用 **方案 C：基于 Python 3.11+ 标准库 `sqlite3` 的可重建查询投影层**（实现模块：`src/ai_lib_qor/application/catalog_projection.py`，位于 7 层单向 DAG 的 Layer 4 `application`）：

1. **权威真相严格不变**：`delivery/`、`formal/`、`effective/`、`log/check_*.json`、`log/*.tsv`、`path_sources.json`、`ip_partition.json` 仍是唯一权威业务真相；SQLite 仅作为与 `file_index.json`、`facts/fact_ca_*.json.gz` 同级的**可重建派生缓存**。
2. **两层共 10 张派生投影表（`PROJECTION_VERSION = '2'`）**：
   - **第一层（工作区运营目录，6 表）**：`catalog_meta`、`libraries`、`deliveries`、`revisions`、`checks`（含 Schema 损坏记录 `is_corrupt=1, quality_code='CORRUPT'` 显式标记）、`artifacts`。
   - **第二层（中粒度跨库摘要，4 表）**：
     - `check_items`：按规则项（`check_id` / `result` / `is_latest_check` / `is_latest_revision`）支撑跨库风险榜单与规则维度统计；
     - `object_change_events`：仅存跨版本对象变更 Delta（面积/Pin/模块增删等），不存全量静态副本；
     - `effective_views`：仅索引各轨道 `latest` 与 `accepted` 有效版的 View 与 Corner 文件名提示，支撑 `+` 组合词全局搜 Corner；
     - `effective_objects`：仅从已落盘 `facts/fact_ca_*.json.gz` 只读提取 `latest` 与 `accepted` 有效版去重后的 Cell/Macro/Module/Subckt 名称、尺寸与 `pin_count`/`corner_file_count` 汇总（零 RAW 解析、零逐条 Pin 行）。
   - **第三层（明细池留在文件系统）**：海量 `FileFacts` 内部逐条 Pin / PG Pin / 完整对象细节继续按 `(source_sha256, parser_sig)` 压缩留在 `facts/fact_ca_*.json.gz` 共享池，避免 `.sqlite` 膨胀。
3. **写穿增量 + 外部变更自愈 + 原子重建**：
   - L1/L2/L3、有效版本更新/恢复、人工采纳、单版/库级检查、IP 分轨在提交权威 JSON 后，于库锁外按单库最佳努力增量 `sync_library_projection`（投影失败绝不影响权威提交）。
   - 纯只读查询与导出（`refresh_status`、`workspace_activity_and_readiness`、`collect_json_inventory`、`export-overview-excel`）保持零落盘：仅当 `projection.sqlite` 已存在且 `folder_sig` 一致时走只读 SQLite 快路径，否则无副作用降级到既有 JSON 读取。
   - 显式目录接口（`catalog-rebuild`、`catalog-query`、`/api/v1/catalog/*`、`ensure_projection_fresh`）按 `folder_sig` 检测外部 CLI/脚本变更并仅增量重投影变化的库；表结构版本变更或重建时采用临时库 + `os.replace` 原子切换。
4. **共享盘（NFS/GPFS）部署边界与降级**：
   - 默认路径 `work/.catalog/projection.sqlite`（本机 SSD 自动开启 `WAL`，不支持 WAL 的文件系统自动回退 `DELETE` 日志模式）。
   - 若 `work/` 位于 NFS/GPFS 共享盘，应通过 `AI_LIB_QOR_CATALOG_DB` 环境变量或 `path_sources.json -> workbench.catalog_db_path` 将投影库重定向至 Web 节点本机 SSD，避免多机共享盘 WAL `-shm` 与文件锁问题。
   - 设置 `AI_LIB_QOR_CATALOG_SQLITE=0` 或数据库不可用时，所有查询自动降级至既有纯 JSON 读路径。
   - `storage-stats` 将 `.catalog/` 归入 `rebuildable_cache_bytes`；`cache-clean --clean-catalog` 可安全演练并清理。

## 边界与待验证项

- 本机 SSD 上 500 库实测与单元测试通过，**不等价于真实生产 NFS/GPFS 多主机并发验收**；生产共享盘部署前仍需在目标主机核实 `AI_LIB_QOR_CATALOG_DB` 本地路径策略与并发读写延迟。
