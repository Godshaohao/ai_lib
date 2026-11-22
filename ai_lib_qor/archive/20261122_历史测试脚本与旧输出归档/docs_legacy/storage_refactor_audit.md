# 精简存储与 JSON 驱动版本：事实审计

审计日期：2026-11-18，下表描述审计时的基线；其后用户决定平铺新写入，现状见 [扁平库目录与 JSON 命名](2026-11-18_扁平库目录与JSON命名.md)。此目录下 `.git` 为受限环境暴露的空目录，`git status`、`git rev-parse HEAD` 均返回 `not a git repository`；本次无法核验本地分支、HEAD 或未提交变更，不能将规格中的 `97acef8` 当作当前事实。可读上游路径存在 Git 仓库，但不能假定其内容等于当前工作副本。

## 实际现状

| 项目 | 证据与状态 |
|---|---|
| SourceSync 补丁 | 当前 `src/ai_lib_qor/sources/` 无 `source_sync.py`、`source_catalog.py`；已有 `auto_ingest.py`、`formal_sync.py`、`source_discovery.py` 等，不能假定旧补丁已安装。 |
| RAW 写入 | `auto_ingest.py` 写 `vendors/<vendor>/libraries/<library>/deliveries/<id>/delivery.json` 及 `source_evidence.json`；`registration.py` 管理显式登记。记录不可变。 |
| Formal 写入 | `formal_sync.py` 按已确认的 NL / Vendor / 来源库分组，写入对应库 `formal_nl/<NL>/snapshots/<id>/snapshot.json`；旧全局 `formal_nl/<NL>/snapshots/` 由 Catalog 兼容读取。 |
| 版本与采纳 | `versions/service.py`、`store.py` 写入 `ips/<ip>/effective/versions/`、`index.json`、`acceptance.jsonl`，以事件区分最新计算和人工采纳。`_inputs/deliveries` 保存使用过的记录副本。 |
| 契约 | `schemas/` 存在七类 v1 Schema。Delivery / Formal / Effective 的来源引用分别使用 delivery+file 或 NL+snapshot+file ID；当前 v1 源引用不携带 Vendor，跨 Vendor 同名组合需检测。 |
| 顺序和身份 | `auto_ingest.py` 保存 `order_basis` 旁证；自动顺序可能是首次观察顺序而非供应商顺序。`classifier_adapter.py` 的文件名候选目前可标 `RESOLVED`，不等于人工确认。 |
| 数据源范围 | `archive/20261119_历史测试输出/formal_five_library_review_0eaz9nea` 是隔离测试：五库、21 份交付、五份部分 NL 快照；不是生产数据。可信 BusinessIP 名单及跨库映射的生产真实性未核实。 |
| 查询 | `application/catalog.py` 加载旧有效版本和新旧 Formal 位置；`LibraryCatalog` 另扫描已登记 delivery 的 JSON 路径，可列未建立 IP 的库。读取 JSON 路径不等于扫描 RAW。 |
| 输入与产出 | CLI、Web、Excel 依赖既有 v1 结构；`versions/slot_resolver.py` 原先默认验证 RAW 文件存在，无法离线计算。后续修改和结果见 `storage_refactor_result.md`。 |

## 影响边界

- 可复用：版本 `composer`、锁及原子写、AcceptanceEvent、已有分类器和来源同步；旧 v1 JSON 与旁证原样保留。
- 需要适配：旧 / 新布局读取、v1 evidence 归一化、来源引用冲突检测、未知顺序与身份标注、Formal 的物理路径匹配和逻辑文件位分离。
- 需修改：离线版本构建、统一查询和新契约写入；同时验证 CLI、Web、Excel、Release 以及历史重建。
- 暂不处理：第二层解析、FileFacts/CheckResult 重新生成、数据库、破坏性迁移和删除历史。

规格提出 Formal 在 `formal/<NL>/` 统一保存，与用户此前要求同一来源库目录集中存放不同。用户已确认：两种位置都读取，新写入仍放 Vendor / 来源库。各库独立快照历史和稳定作用域不得因兼容读目录而消失。
