# 2026-11-22 历史测试、旧脚本与过时输出归档说明

本目录保存已由「路径式三层架构（L1 来源 → L2 有效版本 → L3 统一索引 + 内容寻址 FileFacts 共享池）」替代的旧代 v1/v2/v3 测试、模拟脚本、历史临时输出与早期设计草稿。归档过程仅执行移动（`mv`），**未删除任何历史文件，也未修改真实 `work/` 归档历史**。

## 归档清单

| 子目录 | 内容说明 | 数量 / 体量 |
|---|---|---|
| `tests_legacy/` | 依赖旧版 v1/v2/v3 架构（`workbench/app.py`、`v2_check_adapter`、`v3_checks`、`library_catalog`、`scans`、`formal_sync`、`exports/` 等）的旧测试 | 48 个测试文件 |
| `scripts_legacy/` | 旧版 v3/Formal 模拟与基准脚本（原 `scripts/*`、`tools/benchmark_catalog.py`、`examples/build_scale_synthetic.py`） | 6 个脚本 |
| `outputs_legacy/` | 历史阶段性模拟输出、审阅导出与旧运行目录（原 `exports/`、`workbench_runs/`、`review/`） | 约 23 MB（60+ 历史输出目录） |
| `design_drafts_legacy/` | 早期 v3.1/v5/v5.1 设计草稿、静态架构图、旧 README 与根目录编码异常草稿文件 | 原 `ai_lib_qor_artifact_first_v5`、`diagrams-*`、`design`、`architecture*` 等 |
| `examples_legacy/` | 旧版 v1/v2/v3 合成演示数据（含 214 MB `legacy_scale_demo`、`acceptance_20261117`、`scale_synthetic_v1` 等） | 约 219 MB |
| `docs_legacy/` | 2026-11-13 至 11-19 的旧代 v1/v2/v3/v5 过程文档与早期评审记录 | 35+ 份过程文档 |

## 说明

- 当前有效主线测试位于仓库根目录 [tests/](file:///home/polaris/文档/ChatGPT/ai_lib/ai_lib_qor/tests)（13 个文件、82 项用例），仅需 `PYTHONPATH=src` 即可独立运行，不再依赖外部 `../src/lib_guard` 或 `exports/`。
- `src/ai_lib_qor/` 内仍保留旧代兼容模块（供历史库迁移 `path_migration.py` 与旧 CLI 兼容调用），未做破坏性删除；待确认不再需要历史数据迁移后可另行安排下线。
