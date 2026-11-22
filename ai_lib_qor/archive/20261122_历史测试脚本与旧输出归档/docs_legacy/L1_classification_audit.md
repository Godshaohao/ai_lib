# L1 分类与来源审计（2026-11-17）

基线：GitHub `codex/ai-lib-qor-workbench` 的 `63b9c89`。审查基线为该提交。旧 `lib_guard` 位于仓库根 `src/`，不在 `ai_lib_qor/src` 中。实测同时设置两个 `src` 的 PYTHONPATH 可以导入 `discover_versions`、`FileClassifier`、`inventory_directory`；不能依赖临时检出目录作为长期部署路径。

| 对象 | 现有旧代码 | 新代码入口 | 真实输入 | 输出字段 | 可复用性 | 未实现差距 | 反例 | 本次修改决定 |
|---|---|---|---|---|---|---|---|---|
| 供应商、源库 | `discovery.load_library_map` | `workbench.scans.sources` | 显式 library map 或 `work/scan_sources.json` | vendor、library、root | 可复用已确认根目录 | 配置不自动证明业务 IP | 同名库来自不同 vendor | 以显式配置为准，冲突保留未知 |
| BusinessIP 及跨库 | 旧 map 中 library/alias，并非可靠 IP 名单 | `catalog.load_catalog` | 已有版本索引中的 owner；实际业务映射待提供 | vendor/library/ip | 已有目录可读取 | 未找到可证明业务 IP 与跨库关系的名单 | 同 IP 同时关联多个库 | 不从名字猜 IP；未知展示未归属 |
| 版本目录 | `discovery.discover_versions`、`catalog.index` 的 `version_path_rules` | 当前 `registration.register_delivery` | 库根、配置规则 | version id、path | 可复用但要区分两个入口 | `discover_versions` 只枚举库根的直接子目录；深层规则在 catalog | `bundles/lib/releases/V07` | 必须按真实配置定位，不能用固定第一层 |
| 文件分类 | `scan.inventory.FileClassifier`、`extract_filename_corner` | `delivery_builder.build_delivery` | 路径、名称、配置 | type、role、corner 提示 | 不读取内容即可调用旧分类器 | 旧提示不充分识别 mode/PVT 与业务归属 | func_tt 与 scan_tt；不同电压的 tt | 提示与已确认映射分开，未知保留 |
| file_key | 旧分类器未给出 v3 稳定 key | `build_delivery` 接受显式映射；`slot_resolver.delivery_members` 严格验证 | 已确认文件映射 | file_key / RESOLVED 或 UNRESOLVED | schema 允许未知 | 无可信业务对象与文件位规则不能生成 key | 两个 IP 的 core.lef 同名 | 不猜 key，不绕过有效版本严格校验 |
| FULL/PARTIAL | `package.classifier.classify_package` | `build_delivery` | 文件集合与 package metadata | 推测类别 / package_mode | 仅候选 | 不能证明 scope 已确认 | 缺失的 FF 可能继承 | UNKNOWN、scope_confirmed=false，不推断删除 |
| RAW 观察与历史 | `scan.inventory` | `workbench.scans.run_scan`、`sources.update_scan` | 已配置源根 | 路径、size、mtime_ns、状态、错误 | 快扫已实现，immutable 写入 | 尚无分类后自动纳管及顺序语义 | 部分扫描或原地修改 | 不读取内容，不覆盖旧观察和交付 |
| Delivery | 旧包分类器 | `sources.delivery_builder`、`workbench.registration` | 扫描结果、明确 mapping、交付元数据 | v3 delivery_record | builder 可保存未解析项；注册器现要求逐项确认 | 新事件身份、稳定接收顺序、二次校验需设计 | 同版本重交、写入中断 | 无事件证据时保留观察，不伪造交付 |
| Formal 来源 | `release.inventory.inventory_directory` | `sources.snapshot_builder` | NL 根与旧 catalog 中 RAW 版本路径 | 链接、目标、匹配状态 | 可盘点路径，无内容 hash | 旧匹配按目录祖先，不能证明唯一文件/IP；builder 不容纳坏链 | 链接失效、多库指向同一路径 | 观察与合规快照分开；歧义与坏链保留 |
| 部署与导入 | 根仓库 `src/lib_guard` | 独立 `ai_lib_qor` 包 | PYTHONPATH 中两个源码根 | Python 模块 | 联合检出可导入 | 工作副本仅包含新包；临时克隆不可靠 | 只设置 `ai_lib_qor/src` | 必须明确旧包稳定位置与启动配置，不能静默实现第二套分类器 |

验证：`PYTHONPATH="$PWD/src:$PWD/../src" python3 -c 'from lib_guard.discovery import discover_versions,load_library_map; from lib_guard.scan.inventory import FileClassifier,extract_filename_corner; from lib_guard.release.inventory import inventory_directory'` 成功。仓库中的 `tests/fixtures/raw/library_map.yml` 是测试夹具而非业务名单；现有 `examples/acceptance_20261117/work/scan_sources.json` 是模拟配置。旧 `catalog_policy.json` 中有深层版本规则，但单独调用 `discover_versions()` 不会执行它们。观察文件名的路径 SHA 用于构造标识时不属于内容 hash。

## 当前实现与边界

在仓库内应通过 `PYTHONPATH="$PWD/src:$PWD/../src"`（从 ai_lib_qor 目录运行）使用仓库根目录的 `src/lib_guard`。

新增 `sources/classifier_adapter.py`：仅针对完整 size/mtime 扫描做内存分类，调用 `FileClassifier`；版本目录须由 `version_paths` 显式给出，支持深层路径；`file_mapping` 中经确认的精确路径映射才会产生 file_key。交付内重复 key 均回退 UNRESOLVED；跨版本相同 key 可保留。分类提示不是确认的 corner/mode、包范围或 IP 关系。扫描失败/部分完成不能进入分类。适配器已接入 Web 扫描，纳管限制见下文。

本阶段仍有下文列出的未完成项，不能将此阶段称为 L1 全部验收完成。

## 本次继续实施（2026-11-17）

- 新增 `sources/auto_ingest.py`：对 `scan_sources.json` 中**明确配置的** `version_paths`，使用旧分类器提示和显式 `file_mapping` 建档。生成 UNKNOWN 包、未确认范围、未解析项；系统接收顺序写入证据。重复扫描跳过；来源原地变化只提示，不覆盖旧记录；发布前后用元数据重新核验。路径、size、mtime 用于观察，不计算内容哈希。
- `workbench/scans.py` 保留不可变扫描记录，独立写入 `runs/ingest/<scan_id>.json` 记录分类和纳管情况；扫描失败、缺少版本配置、旧分类器不可导入均不宣称纳管成功。
- 新增 `sources/formal_sync.py`：调用旧正式盘点，保存不可变链接观察；唯一精确匹配已登记 RAW 才显示来源。坏链接、普通文件、歧义不生成完整快照；所有链接满足条件时可生成 v3 快照，范围未显式确认默认为 PARTIAL。观察和 v3 快照为不同对象。
- Web 首页展示 RAW、Formal NL 和输出目录；旧手动登记路由保留供兼容，但不再作为首页正常流程。目录浏览限定 work/runs 并拒绝软链接目录和 `..`。
- 本阶段未实现：Library Map 自动导入及深层规则自动发现、显式供应商重交事件、自动 BusinessIP / 跨库映射、Formal IP 筛选与完整日期统计、目录数量及分页、100+ 库基准、真实企业库验收。当前必须给出 `version_paths` 才自动发布交付，不能将未知版本目录冒充已确认事件。

配置示意：`work/scan_sources.json` 的每项填写 `vendor_id`、`source_library_id`、`root`、`version_paths`（版本 ID 到相对目录）；`file_mapping` 可按扫描根相对路径给出经确认 `file_key`。没有映射的文件保留 UNRESOLVED。`work/formal_sources.json` 格式为 `{"sources":[{"formal_nl_id":"NL2.5.3","root":"/实际/正式库/根目录"}]}`。所有路径仅为说明，须替换为用户自己的配置。启动必须同时包含新旧源码：`PYTHONPATH="$PWD/src:$PWD/../src" python3 -m ai_lib_qor.workbench --plans examples/pipeline --work <work> --runs <runs> --port 5052`。
