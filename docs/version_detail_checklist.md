Status: current

# Version Detail 专项验收清单

## 目的

这份清单只验收 Version Detail 页面。它回答三个问题：

1. 页面是否给 IP 使用者一个可信的接入判断。
2. 页面中的数量、基准、变化和文件是否互相对应。
3. 调试证据是否被收敛到合适的位置，没有污染首屏。

它不替代根目录 `check.list`。scan、cmp、window、effective、release 和大规模性能必须按根清单单独验收。

## 验收对象

| 对象 | 来源 | 页面职责 |
| --- | --- | --- |
| IP 使用者视图模型 | `version_review_model.py` | 生成判断、基准、变化、影响和证据分层 |
| Version Detail 渲染 | `version_detail_report.py`、`version_review_render.py` | 组织页面层级，不重新扫描 RAW |
| 文件结构 | `version_file_evidence.py` | 在详情页内提供目录树、状态、搜索和有限滚动 |
| 现有 UI 契约测试 | `test_version_detail_ui_contract.py`、`test_version_detail_report.py` | 锁定数据和页面行为 |

## P0：必须通过

| 编号 | 检查项 | 通过标准 | 自动证据 |
| --- | --- | --- | --- |
| VD-P0-01 | 主判断唯一 | 页面只有一个 IP 接入主状态；正式放行状态不冒充 IP 可用状态 | `test_page_has_one_primary_decision_and_one_matrix_heading` |
| VD-P0-02 | 基准可信 | `current_effective`、显式基准和缺失基准的语义不混淆；首版本自引用 Base 必须进入首版模式；缺少 diff 不能显示为“无变化” | `test_current_effective_wins_over_stale_diff_base`、`test_self_referential_full_base_enters_first_version_mode`、`test_missing_diff_is_blocked_instead_of_presented_as_normal_review` |
| VD-P0-03 | 变化数量自洽 | 新增、删除、修改、重点文件和视图矩阵不出现互相矛盾的文案 | `test_change_status_is_separate_from_usage_decision`、`test_view_delta_is_a_structured_comparison_table` |
| VD-P0-04 | 单版本可读 | 没有 Base 时展示自身交付文件、视图和证据等级，不虚构空 diff | `test_first_full_version_without_base_uses_scan_coverage_not_empty_diff` |
| VD-P0-05 | 页面入口唯一 | 文件结构直接合并到详情页；不再生成或依赖独立完整文件证据页 | `test_version_detail_includes_compact_file_structure_section`、`test_version_detail_page_removes_stale_standalone_file_evidence` |
| VD-P0-06 | 事实源边界 | HTML 不读取 RAW、不展示绝对路径、不把 HTML 当作数据源 | `test_version_detail_uses_scan_evidence_for_release_notes_without_raw_rglob`、`test_version_detail_does_not_expose_absolute_raw_paths` |
| VD-P0-07 | 必需 View 联动 | `delivery_completeness.status == MISSING` 时，IP 主状态必须为“不可接入”，并列出缺失 View | `test_missing_required_view_blocks_ip_user_decision` |

## P1：必须有明确证据

| 编号 | 检查项 | 通过标准 | 自动证据 |
| --- | --- | --- | --- |
| VD-P1-01 | 影响范围 | View Matrix 按 canonical view 和使用场景聚合；没有重复的使用场景解释 | `test_ip_view_renders_usage_impact_without_repeating_usage_sections`、`test_ip_view_aggregates_raw_file_types_to_canonical_views` |
| VD-P1-02 | 重点变化文件 | 文件表有变化、类型、路径、审查级别、匹配状态和说明；最多 120 行 | `test_path_migration_evidence_is_attached_to_focus_rows`、`test_large_diff_caps_inline_rows_and_keeps_full_evidence_link` |
| VD-P1-03 | 文件结构可核对 | 文件树显示当前/新增/删除/修改，支持搜索、状态过滤、展开收起和有限高度滚动 | `test_file_tree_keeps_deleted_paths_and_has_bounded_scroll`、`test_file_evidence_section_exposes_a_status_annotated_tree` |
| VD-P1-04 | 版本关系和交付完整度 | 页面能看到当前版本、基准、基准来源、扫描输入和已有必需 View 交付事实 | `test_page_prioritizes_decision_summary_and_lineage`、`test_ip_view_projects_delivery_completeness_without_inventing_missing_views` |
| VD-P1-05 | 证据分层 | Parser、raw JSON、release gate 和调试入口默认折叠；Summary-only / Metadata-only 不自动变成 blocker | `test_lightweight_evidence_does_not_force_usage_review`、`test_ip_view_omits_duplicate_usage_and_policy_explanations` |
| VD-P1-06 | 未知文件可追溯 | Unknown 数量必须有文件路径、代表文件或完整证据入口 | `test_unknown_count_always_has_path_or_full_evidence_link` |
| VD-P1-07 | 扫描聚合来源 | `scan_evidence.file_total/counts/unknown_count` 必须与真实 `scan_summary.json`、`manifest.json` 或 inventory 文件一致 | `test_scan_evidence_uses_scan_summary_counts_when_inventory_has_no_counts` |

## P2：体验和维护质量

| 编号 | 检查项 | 通过标准 |
| --- | --- | --- |
| VD-P2-01 | 信息顺序 | 首屏顺序为判断摘要、影响范围、View Matrix、重点文件、文件结构；管理和调试信息在侧栏折叠 |
| VD-P2-02 | 中文和专业词 | 中文为主，仅保留 LEF、Liberty、SPEF、GDS、PVT、FULL、FIX 等必要专业词 |
| VD-P2-03 | 长列表 | 大量文件不会把页面无限撑长；表格和文件树有固定高度和滚动入口 |
| VD-P2-04 | 静态页面质量 | HTML 可离线打开，链接相对化，脚本可解析，不依赖开发机绝对路径 |
| VD-P2-05 | 浏览器检查 | 桌面浏览器下检查首屏层级、横向表格滚动、折叠区和文件树操作；截图或 Playwright 结果必须留存 |

## 标准命令

在仓库根目录执行：

```bash
PYTHONPYCACHEPREFIX=/tmp/lib_guard_pycache \
PYTHONPATH=src python3 -m unittest \
  src.lib_guard.test.test_version_detail_ui_contract \
  src.lib_guard.test.test_version_detail_report -q

PYTHONPYCACHEPREFIX=/tmp/lib_guard_pycache \
PYTHONPATH=src python3 -m compileall -q src

git diff --check
```

## 浏览器验收命令

浏览器验收使用仓库内的可重复脚本。它会启动本机 Chrome/Chromium，生成截图和
`browser_validation.json`，并验证文件树、状态过滤、文件名搜索、展开/收起、重点变化表
搜索、折叠面板和横向滚动。

第一次准备依赖（依赖下载环境执行一次即可）：

```bash
HOME=/tmp/lib_guard_npm_home \
npm_config_cache=/tmp/lib_guard_npm_cache \
npm install --prefix /tmp/lib_guard_playwright playwright-core@latest
```

执行真实页面验收：

```bash
node scripts/validate_version_detail_browser.cjs \
  <FIRST_VERSION>/index.html \
  <UPDATED_VERSION>/index.html \
  --out work/browser_validation
```

内网机器的 Chrome 路径不是默认路径时，增加：

```bash
LG_CHROME_PATH=/path/to/chrome \
node scripts/validate_version_detail_browser.cjs <VERSION_DETAIL>/index.html
```

受限沙箱可能禁止 Chrome Crashpad 或 Snap Firefox 的运行目录。脚本会使用临时
`HOME`/`XDG_RUNTIME_DIR`，并以 `--no-sandbox` 启动仅用于验收的无头 Chrome；这不改变
产品运行时，也不把浏览器配置写入仓库。若环境策略禁止沙箱内启动浏览器，应在同一工作区
的宿主 shell 执行上述命令，而不是把截图结果标记为通过。

通过标准：输出 JSON 中 `status: true`，每个页面 `assertions.allPassed: true`，并且
输出目录同时存在每个页面的 PNG 截图。

真实页面检查至少确认：

```bash
test -f <VERSION_DETAIL>/index.html
test ! -e <VERSION_DETAIL>/file-evidence.html
rg -F "文件证据清单" <VERSION_DETAIL>/index.html && exit 1 || true
rg -F "scan_empty" <VERSION_DETAIL>/index.html && exit 1 || true
rg -F "判断摘要" <VERSION_DETAIL>/index.html
rg -F "影响范围" <VERSION_DETAIL>/index.html
rg -F "视图变化矩阵" <VERSION_DETAIL>/index.html
rg -F "文件结构" <VERSION_DETAIL>/index.html
```

## 结果记录规则

每次评估填写：

| 字段 | 内容 |
| --- | --- |
| 代码版本 | commit 或工作区标识 |
| 页面路径 | 实际打开的 `index.html` |
| 测试数量 | 目标测试和全量测试 |
| P0 | PASS / FAIL，并附证据 |
| P1 | PASS / FAIL，并附证据 |
| P2 | PASS / SKIP，并解释原因 |
| 剩余风险 | 只写未覆盖的真实场景 |

P0 任一失败，不得把 Version Detail 标记为可接受。浏览器检查未执行时，可以交付代码回归，
但必须明确标记为 SKIP，不能写成完整 UI 验收通过。
