# BUGFIX · 不同 Vendor 同名库共用分轨配置文件撞号修复说明

- **编号**：`BUG-20261125-ip-partition-cross-vendor-collision`
- **日期**：2026-11-25
- **修复方案**：方案 A（库内目录双主键隔离 `work/libraries/<vendor>/<library>/ip_partition.json` + 旧路径无损兼容认领）

---

## 一、问题现象与根因

### 1. 现象
当 RAW 根目录中存在**不同 Vendor 下的同名真实物理库**（例如 `Vendor_A/rtavfs` 与 `Vendor_B/rtavfs`、`Vendor_B/pvt` 与 `Vendor_G/pvt`）且均启用多业务 IP 分轨（`ip_list`）时，后分轨的库会触发跨供应商冲突报错，或导致两个不同 Vendor 的库争用同一份分轨文件。

### 2. 根因
- 全系统其他数据与配置均按 **`(vendor, library)` 双主键**隔离（如 `work/path_sources.json` 中的 `libraries.<vendor>.<library>` 以及 `work/libraries/<vendor>/<library>/` 目录树）。
- 唯独分轨配置文件在 `application/ip_partition.py` 中使用单键命名 `work/ip_partition_<library>.json` 平铺在工作区根目录，不含 `vendor` 维度；同时 `application/path_query.py` 的 JSON 产物盘点也直接按 `work/ip_partition_<lib>.json` 匹配，造成同名不同 Vendor 的库互相撞号。

---

## 二、修复设计（方案 A）

1. **权威路径收口到库目录（双主键物理隔离）**：
   - 新权威路径：`work/libraries/<vendor>/<library>/ip_partition.json`，与 `file_index.json`、`delivery/`、`effective/`、`log/`、`facts/` 同级，天然通过目录分隔彻底消除跨 Vendor 同名库撞号与下划线拼接歧义。
   - 在 `application/path_storage.py` 中将 `ip_partition.json` 归入权威配置桶（`AUTHORITATIVE_BUCKETS` 的 `config` 类别），**严禁被 `cache-clean` 清理，也不计入 `legacy_root_file_count`**。
2. **无损向后兼容与存量迁移**：
   - **读取优先级（`resolve_existing_partition_path`）**：
     1. 优先读取 `work/libraries/<vendor>/<library>/ip_partition.json`。
     2. 若不存在，回退检查旧路径 `work/ip_partition_<library>.json`；检查文件内 `"vendor"` 字段：
        - **若 `stored_vendor == vendor`** → 认领读取，100% 保留原有人工确认的 `tracks` 与版本顺序。
        - **若 `stored_vendor != vendor`** → 视为属于其他 Vendor 的旧文件，**不认领、不报错阻断**，当前库从干净状态独立建轨。
   - **写入与自动迁移**：
     - `partition_library_ips` 与可视化编排器保存（`save_partition_payload`）统一原子写入新路径 `work/libraries/<vendor>/<library>/ip_partition.json`，并通过 `schemas/ip_partition.schema.json` 校验。
     - 若原库从旧路径认领读入，首次运行 `partition-ips` 时自动无损落盘至新路径（返回 `migrated_from_legacy: true`），**不删除旧根文件**。
   - **API 签名兼容**：`partition_path(work, vendor, library)` 为新标准调用；保留 2 参数 `partition_path(work, library)` 回退到 `legacy_partition_path(work, library)`，防止外部脚本瞬间崩溃。
   - **损坏文件防护保留**：若库目录内自身的 `ip_partition.json` 被篡改为错误 `vendor` 或出现同一版本跨轨道重复，`load_partition` 依然严格拦截报错。

---

## 三、修改代码清单

| 文件 | 变更内容 |
| --- | --- |
| `src/ai_lib_qor/application/ip_partition.py` | 新增 `legacy_partition_path`、`resolve_existing_partition_path`；将 `partition_path(work, vendor, library)` 与 `save_partition_payload(work, vendor, library, payload)` 切至 `work/libraries/<vendor>/<library>/ip_partition.json`；`load_partition`、`partition_library_ips`（含 `migrated_from_legacy` 标记）与 `active_tracks_for_library` 接入双路径解析与按 `vendor` 认领旧文件逻辑 |
| `src/ai_lib_qor/application/path_storage.py` | `AUTHORITATIVE_BUCKETS` 增加 `'config'`；`_classify_file` 将 `ip_partition.json` 归为权威配置；`_measure_folder` 将 `ip_partition.json` 纳入合法库根文件白名单（不计入旧版遗留文件、不受 `clean_cache` 影响） |
| `src/ai_lib_qor/application/sequence_organizer.py` | 更新 `partition_path(root, vendor, library)` 与 `save_partition_payload(root, vendor, library, part_payload)` 调用，确保编排器读写落入库内独立路径 |
| `src/ai_lib_qor/application/path_query.py` | `collect_json_inventory` 改为调用 `resolve_existing_partition_path(root, v, lib)`，杜绝同名不同 Vendor 在 JSON 产物盘点表中互相串显，并在仍使用旧路径时标注迁移提示 |
| `src/ai_lib_qor/reporting/work_overview_excel.py` | 待办清单分轨提示路径更新为 `libraries/<vendor>/<library>/ip_partition.json` |
| `src/ai_lib_qor/cli.py` | `partition-ips --dry-run` 帮助文案更新为新路径 |
| `src/ai_lib_qor/workbench/templates/path_library.html` | 分轨待复核提示与维护卡片文案更新为 `libraries/<vendor>/<library>/ip_partition.json` |
| `src/ai_lib_qor/workbench/templates/sequence_organizer_panel.html` | 编排器说明文案更新为 `libraries/<vendor>/<library>/ip_partition.json` |
| `.agents/skills/ai-lib-check-extender/scripts/verify_extension.py` | Schema 自检同时扫描新路径 `work/libraries/*/*/ip_partition.json` 与旧路径 `work/ip_partition_*.json` |
| `docs/architecture-steward.md` | 同步更新权威分轨配置路径说明 |
| `tests/test_ip_partition.py` | 新增 `test_same_library_name_across_vendors_isolated_and_legacy_migrated`，完整覆盖同名跨 Vendor 隔离、旧文件按 Vendor 无损认领迁移、盘点隔离、存储分类保护与异常篡改拦截 |

---

## 四、已有撞号工作区的现场处置步骤

若生产/测试工作区中已存在旧文件（如 `work/ip_partition_rtavfs.json`、`work/ip_partition_pvt.json`）：

1. **无需手动删除旧文件**，升级代码后对两个同名库依次执行一次分轨（Web 库页点「重新分轨」或命令行）：
   ```bash
   ai-lib-qor partition-ips --work <work> --vendor Vendor_A --library rtavfs
   ai-lib-qor partition-ips --work <work> --vendor Vendor_B --library rtavfs
   ```
2. **预期结果**：
   - 原归属方（旧文件内 `"vendor"` 匹配的库）自动继承原有人工 `tracks` 并生成 `work/libraries/<vendor_1>/rtavfs/ip_partition.json`（返回 `migrated_from_legacy: true`）。
   - 另一方自动忽略旧文件，独立生成 `work/libraries/<vendor_2>/rtavfs/ip_partition.json`。
3. 确认两边新文件与 L2/L3 刷新正常后，旧根目录下的 `work/ip_partition_rtavfs.json`、`work/ip_partition_pvt.json` 可自行移入归档备份目录清理。

---

## 五、验证结果

- **专项回归**：`PYTHONPATH=src:tests python3 -m unittest tests.test_ip_partition tests.test_sequence_organizer tests.test_api_and_config_contracts -v` → **15 tests OK**
- **全量回归 + 严格 0 白名单 AST DAG 守护**：`PYTHONPATH=src python3 -m unittest discover -s tests -p "test_*.py" -q` → **173 tests OK**
- **Skill 扩展自检**：`PYTHONPATH=src python3 .agents/skills/ai-lib-check-extender/scripts/verify_extension.py --work sandbox_multi_ip/work` → **5/5 ALL EXTENSION CHECKS PASSED**
- **适用边界说明**：以上验证基于自动化单元测试与开源多 IP 沙箱，真实生产工作区（`Vendor_A/rtavfs`、`Vendor_B/rtavfs`、`Vendor_B/pvt`、`Vendor_G/pvt`）需在目标环境按第四节步骤现场执行并复核。
