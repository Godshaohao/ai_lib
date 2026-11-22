# 2026-11-22 旧代 v1/v2/v3 源码、旧模板与旧 Schema 归档

经用户明确确认不再需要从旧 v1/v2 格式迁移历史库后，已将 `src/ai_lib_qor/` 中与路径式主线平行的旧代 v1/v2/v3 源码模块、25 个旧 HTML 模板、旧静态资源及 12 份旧 Schema 无损移入本目录（未删除任何文件）。

## 归档清单

- `src_legacy/application/`：20 个旧代模块（`v2_check_adapter.py`、`v3_checks.py`、`library_catalog.py`、`file_index.py`、`file_index_v3.py`、`data_query.py`、`path_migration.py`、`runs.py`、`scans.py` 等）
- `src_legacy/checks/`：6 个旧计划/组装模块（`assembler.py`、`evidence.py`、`plan.py`、`registry.py`、`runner.py`、`selectors.py`）
- `src_legacy/facts/`：`rich_evidence.py`
- `src_legacy/reporting/`：4 个旧报表模块（`evidence_html.py`、`html.py`、`view.py`、`workbook_model.py`）
- `src_legacy/sources/`：7 个旧扫描与注册模块（`auto_ingest.py`、`classifier_adapter.py`、`delivery_builder.py`、`formal_sync.py`、`registration.py`、`snapshot_builder.py`、`update_scan.py`）
- `src_legacy/versions/`：8 个旧版本服务模块（`acceptance.py`、`cli.py`、`composer.py`、`delivery_policy.py`、`index_projector.py`、`service.py`、`slot_resolver.py`、`__main__.py`）+ `store_with_legacy.py` 备份
- `src_legacy/workbench/`：7 个旧工作台模块 + `app_legacy.py` + 25 个旧 HTML 模板 + 旧 `workbench.css` / `operation_progress.js`
- `src_legacy/cli_with_legacy.py`：简化前的全量 CLI 备份
- `schemas_legacy/`：12 份旧代 v1/v2/v3 JSON Schema（`schemas/` 现仅保留 6 份活跃路径式 Schema）
