Status: current

## 2026-10-14 匹配减负与深度核查联动

- 根因不是 108 个文件都需要手工比对：此演练基准 Liberty 清单及原始目录只有 4 个文件，本版为 112 个。包装目录变化不应把完整基准中不存在的文件一律归为待核对。
- 新规则依据清单范围与明确候选判断；一个歧义路径不影响同目录其他新增文件。普通解析警告不降低清单完整性，已知遍历错误则记录警告并限制新增/删除判断。
- 实际浏览器已确认 Liberty 显示“基准 4、本版 112、新增 108”；全库剩余待核对 1 项。
- LEF 矩阵入口可定位已有代表文件结果，明确“仅所选文件；未检出差异”。不会把这个结果推广到 27 个 LEF，也不重新运行这份单文件对比。
- 演练使用已有扫描完成 `cmp`，未补扫、未自动计算 RAW 大文件 hash、未发布。
- 规则及限制详见 `docs/superpowers/plans/2026-10-14-inventory-diff-deep-link.md`。下方 2026-10-13 数字为修改前的验收快照，不是当前计数。

## 2026-10-13 读者报告专项复核

静态报告面向 IP 使用者；命令执行和配置留在 Web 工作台。判断仍使用已有模型，不新增第二套使用结论。

| 检查项 | 本轮证据 | 结果 |
| --- | --- | --- |
| 待核对数量不冒充新增/删除 | `test_reader_report.py`；真实 Liberty 行显示“待核对 / 本版 108” | 通过 |
| 矩阵、重点文件、文件树展示分类一致 | 共用变化展示函数；完整报告保留原始分类并附展示分类 | 通过 |
| 逻辑路径不重复计入扫描文件 | 单测复现去重；真实文件树从 211 项降为 206 项 | 通过 |
| 基准文件不混入当前交付 | 浏览器基准待核对筛选 1 项，切换当前交付后 0 项 | 通过 |
| 实际文件路径可用 | 浏览器复制真实 LEF 绝对路径；代表文件报告可打开 | 通过 |
| 首版、缺少对比、轻量检查不产生虚假结论 | 单元测试及全量回归 | 代码验证通过 |
| 不重扫、不发布、不替换有效组合 | 本轮仅调用单版本报告重建 | 未执行这些动作 |

全量回归：819 项通过，日志 `/tmp/reader_report_verified.log`。桌面浏览器本轮验证的是 ASAP7 当前页面及上述交互，不代表已重新执行下文全部 A-H 浏览器业务场景。历史保存的单文件报告没有批量改写；包根目录匹配兜底机制也没有改动。

截图：`/tmp/ai_lib_reader_report_matrix_20261013.png`。

## 四层验收 Gate

所有 Version Detail 结论必须按同一条链路验收，不允许只凭页面截图或单元测试宣布完成：

| Gate | 验收对象 | 必须证明的事实 |
| --- | --- | --- |
| Gate 1 | Upstream Facts | catalog、scan、diff、effective/window 的输入已形成，状态和来源可追溯 |
| Gate 2 | 审查模型 | `build_version_update_detail_model()`、`build_ip_user_view_model()` 和 `build_review_report()` 口径一致；证据对账不为 `MISMATCH` |
| Gate 3 | 版本详情页投影 | 首屏有唯一判断、主因和结构化下一步；视图变化矩阵、重点文件、文件树来自同一模型 |
| Gate 4 | Real Browser User Path | 桌面 Chrome 实际打开当前真实页面，并逐页验证 A-H 业务场景和交互 |

Gate 1/2/3 通过而 Gate 4 未执行时，只能称为“代码回归通过”，不能称为完整页面验收通过。

评估快照：2026-08-18；代码工作区包含未提交修改，以下状态以当前工作区代码和已留存的真实数据验收记录为准。

# 版本详情页专项验收清单

## 统一术语

页面和终端摘要以中文为主；括号中的英文只保留为机器字段或行业缩写，避免同一概念出现多种叫法。

| 统一中文称呼 | 机器字段/专业缩写 | 使用边界 |
| --- | --- | --- |
| 版本详情页 | Version Detail | 唯一主审查投影 |
| 视图 | `view_type` | `timing_lib`、`physical_abstract` 等统一视图类型 |
| 视图变化矩阵 | View Delta Matrix | 展示视图级新增、删除、修改、路径变化且内容相同和证据等级 |
| 基准版 | Base | 当前版本进行对比时使用的可信版本 |
| 当前有效版 | Effective | 已被人工接受的组合指针，不等同于候选组合 |
| 候选组合 | Candidate effective | 接入窗口根据完整包和增量包生成的待确认组合 |
| 摘要级证据 | `Summary-only` | 只展示结构、数量、路径等摘要，不代表不完整 |
| 元数据级证据 | `Metadata-only` | 只展示路径、大小、哈希和分类等元数据，不代表不完整 |
| 未知文件 | `unknown` / `UNKNOWN_PACKAGE` | 尚未归入统一类型，必须可追溯到路径或证据入口 |
| 工艺角 | PVT corner | 文件名/目录识别值是候选提示；只有显式确认元数据才计入交付覆盖 |
| 深度文件对比 | File Diff / pairwise diff | 人工指定文件后进行的专家下钻，不是默认主流程 |

## 目的

这份清单只验收 Version Detail 页面。它回答三个问题：

1. 页面是否给 IP 使用者一个可信的接入判断。
2. 页面中的数量、基准、变化和文件是否互相对应。
3. 调试证据是否被收敛到合适的位置，没有污染首屏。

它不替代根目录 `check.list`。scan、cmp、window、effective、release 和大规模性能必须按根清单单独验收。

## 需求边界

### 当前真正要解决的问题

| 需求 | 页面或流程必须回答的问题 | 最小可见结果 |
| --- | --- | --- |
| IP 接入判断 | 这个版本从 IP 使用角度能不能接入？ | 一个唯一的 IP 主状态和主因 |
| 版本关系 | 当前版本和哪个可信版本比较？ | Target、Base、Base 来源、缺失 Base 状态 |
| 变化理解 | 哪些视图发生了新增、删除、修改或已确认的同内容路径变化？ | 视图变化矩阵和变化数量 |
| 文件核对 | 数量对应的具体文件是什么？ | 状态标记文件树、重点文件表、未知文件路径 |
| 证据理解 | 这些结论来自哪里，证据强度是什么？ | 扫描、对比、交付完整度和证据等级 |
| 有效版联动 | 当前有效版或接入窗口是否影响本次判断？ | 当前有效版、候选组合和未确认事实 |

### 明确不是当前目标

- 不在 Version Detail 中执行完整人工审批工作流；页面当前是信息展示和证据入口。
- 不把 `scan HTML`、`diff HTML`、`effective manifest` 当成新的主审查页面；它们是证据来源。
- 不把版本名中的 `final`、`release`、`stable` 当成完整包事实。
- 不把路径相似、文件名相同或哈希相同自动解释为真实 rename/equivalence。
- 不要求所有大文件进入内容解析；Liberty、SPEF、DB、GDS、OAS 等按既定证据等级处理。

## 当前解决状态总览

状态含义：

- **已解决**：代码已有明确实现，并有自动测试或真实数据证据。
- **已解决但需刷新产物**：代码已正确，旧 Catalog/HTML 必须重新生成才能看到结果。
- **部分解决**：主路径已存在，但仍依赖人工确认、真实内网数据或性能复测。
- **未纳入**：有意保留为证据、调试或后续工作，不属于当前 Version Detail 主线。

| 功能域 | 当前状态 | 已解决内容 | 主要实现/证据 |
| --- | --- | --- | --- |
| IP 使用者主判断 | 已解决 | 首屏只保留一个 IP 接入主状态；正式放行状态与其分离 | `version_review_model.py`、`version_review_render.py`、`VD-P0-01` |
| 基准版选择 | 已解决 | 显式基准版、当前有效版、上一有效版优先；相邻版本只作回退；缺失基准版不伪装为无变化 | `review/model_rules.py`、`test_version_detail_report.py` |
| 首版本展示 | 已解决 | 无可信基准版时展示首版交付、文件和视图覆盖，不虚构对比结果 | `VD-P0-04`、`test_first_full_version_without_base_uses_scan_coverage_not_empty_diff` |
| 交付完整度 | 已解决 | 必需视图缺失会影响 IP 主状态，并列出缺失项 | `build_ip_user_view_model()`、`VD-P0-07` |
| 视图变化矩阵 | 已解决 | 按统一视图类型聚合新增、删除、修改、路径变化且内容相同、证据等级和使用场景；路径变化不计入内容修改 | `version_review_model.py`、`VD-P1-01` |
| 文件结构 | 已解决 | 文件树合并到 Version Detail，支持状态、搜索、展开收起和有限滚动 | `version_file_evidence.py`、`VD-P1-03` |
| 未知文件 | 已解决 | 未知文件数量必须能回到具体路径或证据入口 | `VD-P1-06`、`test_unknown_count_always_has_path_or_full_evidence_link` |
| Scan/Diff 事实边界 | 已解决 | 页面消费 scan/diff evidence，不从 RAW 重新扫描，不把 HTML 当事实源 | `VD-P0-06`、`docs/data_contract.md` |
| Scan/Cmp 刷新详情页 | 已解决 | 热路径刷新受影响 Version Detail；Catalog 首页和库导航页可延迟刷新 | `RenderImpact`、`test_window_intake_and_accept_refresh_version_detail_projection` |
| 包类型识别 | 已解决但需刷新产物 | 完整包必须满足结构要求；版本名不再升格；截断结果为 UNKNOWN | `package/types.py`、`package/classifier.py`、`test_package_flow.py` |
| 有效版组合 | 已解决 | 只组合明确的 FULL + FIX/DOC；UNKNOWN 不自动叠加 | `window/resolver.py`、`test_window_intake.py` |
| 分类规则缓存失效 | 已解决但需刷新产物 | `package_rules.v2` 变化会使旧 Catalog 不再被增量跳过 | `catalog/index.py`、`test_catalog_scan_writes_state_and_skips_unchanged_default_refresh` |
| 证据分层 | 已解决 | 解析器、原始 JSON、发布门禁默认折叠；轻量证据不自动等于阻塞 | `VD-P1-05` |
| 结构化审查报告 | 已解决 | 由现有 review model 生成固定八组报告：对比范围、交付分析、视图变化、重点文件、未知项、证据评估、待确认、建议动作；默认在本页折叠 | `version_review_model.py::build_review_report()`、`version_review_render.py::render_review_report()` |
| 页面语义分区 | 已解决 | 首屏和证据区提供稳定 `data-section` 标记，浏览器校验不依赖视觉文案猜测 | `validate_version_detail_browser.cjs`、`VD-P0-08`、`VD-P1-09` |
| 浏览器交互 | 已解决 | 基础交互和 A-H 业务语义均已由本机 Chrome 实测；真实 ASAP7 页面与 8 个场景页面均留存截图和 JSON | `work/version_detail_review_report_20260818/browser`、`browser_a_h` |
| 大规模性能 | 部分解决 | 18 个版本真实渲染约 4.679 秒；20 库/500 版本仍未完成内网基准 | `docs/version_detail_evaluation.md`；需补性能验收 |
| 人工审查动作 | 未纳入主页面 | `window/intake/accept-window/release` 仍是命令和证据流程，不在页面内完成 | 本清单边界，不作为 Version Detail P0 |

## 功能到代码的对应关系

| 用户看到的功能 | 数据入口 | 模型/规则 | HTML 组件 | 验证方式 |
| --- | --- | --- | --- | --- |
| 接入判断 | catalog、scan、diff、delivery completeness | `build_ip_user_view_model()` | 判断摘要 | `test_ip_decision_matrix_uses_evidence_state_instead_of_page_defaults` |
| Base 与对比范围 | catalog lineage、current effective、diff summary | `resolve_review_base()` | 版本关系与对比范围 | `test_current_effective_wins_over_stale_diff_base`、`test_adjacent_is_fallback_and_missing_base_needs_confirmation` |
| 首版信息 | scan inventory、scan summary | first-version branch | 首版交付摘要 | `test_first_full_version_without_base_uses_scan_coverage_not_empty_diff` |
| View 变化 | `view_diff.json`、`type_diff.json`、`file_diff.json`、scan inventory | canonical view aggregation；先去除 RAW/版本/包装根，只有归一化逻辑路径仍不同且唯一 Hash 一致时，`renamed_or_moved` 才单独投影为“路径变化且内容相同” | 视图变化矩阵 | `test_diff_ignores_package_wrapper_prefix_when_logical_path_and_content_match`、`test_diff_keeps_real_logical_rename_as_content_confirmed_move`、`test_view_delta_shows_content_preserving_path_change_as_its_own_category` |
| 重点文件 | `file_diff.json`、match evidence | review lane、match reason、confidence | 重点变化文件表 | `test_path_migration_evidence_is_attached_to_focus_rows` |
| 文件树 | inventory、file diff | status annotated tree | 文件结构 | `test_file_tree_keeps_deleted_paths_and_has_bounded_scroll` |
| Parser/证据 | parser manifest、scan review、readiness | evidence level aggregation | 折叠证据入口 | `test_version_detail_shows_unified_evidence_source_state` |
| 有效版上下文 | `pending_window.json`、effective manifest、current pointer | window resolver | 版本关系/侧栏摘要 | `test_window_intake_and_accept_refresh_version_detail_projection` |
| 交付状态 | release readiness、release gate | IP 判断与 release gate 分离 | 正式放行管理折叠区 | `test_change_status_is_separate_from_usage_decision` |
| 结构化审查报告 | 已有 scan/diff/review model | `build_review_report()` | 折叠报告区、可选 Markdown 导出 | `test_review_report_has_fixed_sections_and_reconciled_counts` |

## 算法与数据口径验收

### 包类型

当前规则是可解释的结构判定，不是版本名猜测：

| 输入结构 | 结果 | 是否可作为有效基线 |
| --- | --- | --- |
| IP 同时包含 RTL、LEF、Liberty | `FULL_PACKAGE` | 可以，仍需后续扫描/人工确认 |
| 只有部分核心 View | `PARTIAL_UPDATE` | 不可以，必须绑定 FULL Base |
| 只有文档或 waiver | `DOC_UPDATE` | 不可以，作为增量证据 |
| 文件过多导致分类截断 | `UNKNOWN_PACKAGE` | 不可以，必须确认 |
| 没有可识别 View | `UNKNOWN_PACKAGE` | 不可以，必须确认 |

版本名中的 `final`、`release`、`stable` 只用于阶段或排序，不得直接覆盖结构分类。人工确认时才允许通过 `mark` 或 `library override` 写入明确包类型。

### 有效版组合

组合链路固定为：

```text
明确 FULL 基线
  -> 只叠加明确 FIX/HOTFIX/DOC
  -> UNKNOWN 留在待确认项
  -> 生成候选组合
  -> compare
  -> 人工确认后写 current_effective
```

以下情况必须阻塞或等待人工确认：

- 没有明确的 FULL 基线。
- 包类型是 `UNKNOWN_PACKAGE`。
- Base 只来自相邻版本，且没有当前有效版或显式 Base。
- Diff 证据缺失或目标不是当前 candidate。
- 交付缺少 IP 必需 View。

## 当前验收结论

| 范围 | 当前结果 | 证据 | 备注 |
| --- | --- | --- | --- |
| 版本详情页定向测试 | PASS | `test_version_detail_ui_contract.py`、`test_version_detail_report.py` | 页面模型、Base、首版、视图变化矩阵、文件树均覆盖 |
| 包类型/有效版定向测试 | PASS | `test_package_flow.py`、`test_window_intake.py` | 新增结构分类、截断、UNKNOWN 隔离和最新 FULL 选择覆盖 |
| 全量 Python 测试 | PASS | 以本轮最终命令输出为准 | 2026-08-18 当前工作区结果 |
| Python 编译 | PASS | `python3 -m compileall -q src` | 无语法错误 |
| Diff 格式检查 | PASS | `git diff --check` | 无空白错误 |
| 真实 OpenROAD 页面 | PASS | `work/version_detail_review_report_20260818/catalog/html` | 使用既有单库真实 Catalog 重新生成 20260627_asap7 详情页 |
| 浏览器截图与交互 | PASS | `work/version_detail_review_report_20260818/browser/browser_validation.json` | 1 页、27/27 断言；包含 8 个语义分区、报告折叠、文件树和重点表筛选 |
| 20 库/500 版本性能 | NOT_READY | 无当前内网基准 | 不能用 18 版本结果替代 |

## 必须重新验证的场景

以下不是已解决项，不能用单元测试替代：

1. 内网真实目录中存在多个 vendor、category、package 层级时，library map 是否保持库身份稳定。
2. 同一库同时存在 FULL、FIX、DOC、UNKNOWN，且版本顺序不规则时，window 是否只组合明确包。
3. 一个库包含数百版本和大量 DB/GDS/Liberty 时，scan、catalog refresh、Version Detail render 的分阶段耗时。
4. 代码更新后，旧 `catalog_state.json`、旧 scan evidence 和旧 HTML 是否按规则版本正确刷新。
5. 任一 Version Detail model/renderer 变更后，必须重新生成真实页面并重跑基础交互与 A-H 业务场景；不能复用历史截图结论。

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
| VD-P0-07 | 必需视图联动 | `delivery_completeness.status == MISSING` 时，IP 主状态必须为“不可接入”，并列出缺失视图 | `test_missing_required_view_blocks_ip_user_decision` |
| VD-P0-08 | 首屏可行动性 | 当主状态不是“可接入”时，首屏直接显示唯一主因和结构化“下一步”；不依赖展开 Report/Evidence 才能知道下一动作。READY 也必须有事实核对动作 | `test_missing_diff_is_blocked_instead_of_presented_as_normal_review`、`test_version_detail_has_stable_semantic_sections`、浏览器 `hasNextAction` |
| VD-P0-09 | 证据可核对 | `file_diff evidence -> Review Model -> View Delta Matrix -> Focus Files -> File Tree` 对账；增删改、路径变化且内容相同、重点文件子集和缺失/过期状态必须可解释 | `test_review_report_has_fixed_sections_and_reconciled_counts`、`test_review_report_marks_declared_file_diff_mismatch`、`test_update_detail_model_projects_confirmed_path_changes`、A-H 浏览器场景 |

## P1：必须有明确证据

| 编号 | 检查项 | 通过标准 | 自动证据 |
| --- | --- | --- | --- |
| VD-P1-01 | 影响范围 | 视图变化矩阵按统一视图类型和使用场景聚合新增、删除、修改及“路径变化且内容相同”；旧/新路径必须是去除 RAW、版本和包装根后的逻辑路径，该类别可展开且不并入内容修改 | `test_ip_view_renders_usage_impact_without_repeating_usage_sections`、`test_ip_view_aggregates_raw_file_types_to_canonical_views`、`test_diff_ignores_package_wrapper_prefix_when_logical_path_and_content_match`、`test_view_delta_shows_content_preserving_path_change_as_its_own_category` |
| VD-P1-02 | 重点变化文件 | 文件表有变化、类型、路径、审查级别、匹配状态和说明；最多 120 行 | `test_path_migration_evidence_is_attached_to_focus_rows`、`test_large_diff_caps_inline_rows_and_keeps_full_evidence_link` |
| VD-P1-03 | 文件结构可核对 | 文件树显示当前/新增/删除/修改，支持搜索、状态过滤、展开收起和有限高度滚动 | `test_file_tree_keeps_deleted_paths_and_has_bounded_scroll`、`test_file_evidence_section_exposes_a_status_annotated_tree` |
| VD-P1-04 | 版本关系和交付完整度 | 页面能看到当前版本、基准、基准来源、扫描输入和已有必需视图交付事实 | `test_page_prioritizes_decision_summary_and_lineage`、`test_ip_view_projects_delivery_completeness_without_inventing_missing_views` |
| VD-P1-05 | 证据分层 | 解析器、原始 JSON、发布门禁和调试入口默认折叠；摘要级证据 / 元数据级证据不自动变成阻塞 | `test_lightweight_evidence_does_not_force_usage_review`、`test_ip_view_omits_duplicate_usage_and_policy_explanations` |
| VD-P1-06 | 未知文件可追溯 | 未知文件数量必须有文件路径、代表文件或完整证据入口 | `test_unknown_count_always_has_path_or_full_evidence_link` |
| VD-P1-07 | 扫描聚合来源 | `scan_evidence.file_total/counts/unknown_count` 必须与真实 `scan_summary.json`、`manifest.json` 或 inventory 文件一致 | `test_scan_evidence_uses_scan_summary_counts_when_inventory_has_no_counts` |
| VD-P1-08 | 报告完整性 | 报告固定包含对比范围、交付分析、视图变化分析、重点文件分析、未知项/证据评估、待确认和建议动作，并展示证据对账；不嵌入原始 JSON | `test_review_report_has_fixed_sections_and_reconciled_counts`、`test_review_report_marks_declared_file_diff_mismatch` |
| VD-P1-09 | 信息层级 | 页面使用稳定语义分区；报告、管理门禁和原始证据默认折叠，文件树仍是本页核对入口 | `test_version_detail_has_stable_semantic_sections`、`validate_version_detail_browser.cjs` |

## P2：体验和维护质量

| 编号 | 检查项 | 通过标准 |
| --- | --- | --- |
| VD-P2-01 | 信息顺序 | 首屏顺序为判断摘要、影响范围、视图变化矩阵、重点文件、文件结构；管理和调试信息在侧栏折叠 |
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
  src.lib_guard.test.test_version_detail_report \
  src.lib_guard.test.test_package_flow \
  src.lib_guard.test.test_window_intake -q

PYTHONPYCACHEPREFIX=/tmp/lib_guard_pycache \
PYTHONPATH=src python3 -m compileall -q src

PYTHONPYCACHEPREFIX=/tmp/lib_guard_pycache \
PYTHONPATH=src python3 -m unittest discover \
  -s src/lib_guard/test -p 'test*.py' -q

git diff --check
```

当前工作区最近一次结果：`477 tests ... OK`、`compileall PASS`、`git diff --check PASS`。

分类规则或 Catalog 状态结构变化后，必须重新执行 `lg cat`；`catalog_state.json` 中的
`package_rules_version` 不匹配时，增量刷新不得跳过分类重建。

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

执行 A-H 业务语义验收。脚本会用同一个 Version Detail renderer 生成页面夹具，
然后由 Chrome 实际打开每一个 `index.html`，不是用 Python 表格测试代替浏览器：

```bash
PYTHONPATH=src python3 scripts/render_version_detail_browser_scenarios.py \
  --out work/version_detail_review_report_20260818/scenarios

SCENARIO_DIR=work/version_detail_review_report_20260818/scenarios
node scripts/validate_version_detail_browser.cjs \
  --scenario first_version="$SCENARIO_DIR/first_version/libraries/ip_demo/versions/first_version/index.html" \
  --scenario normal_full_update="$SCENARIO_DIR/normal_full_update/libraries/ip_demo/versions/normal_full_update/index.html" \
  --scenario missing_required_view="$SCENARIO_DIR/missing_required_view/libraries/ip_demo/versions/missing_required_view/index.html" \
  --scenario missing_diff="$SCENARIO_DIR/missing_diff/libraries/ip_demo/versions/missing_diff/index.html" \
  --scenario adjacent_fallback="$SCENARIO_DIR/adjacent_fallback/libraries/ip_demo/versions/adjacent_fallback/index.html" \
  --scenario unknown_package="$SCENARIO_DIR/unknown_package/libraries/ip_demo/versions/unknown_package/index.html" \
  --scenario full_fix_doc="$SCENARIO_DIR/full_fix_doc/libraries/ip_demo/versions/full_fix_doc/index.html" \
  --scenario stale_evidence="$SCENARIO_DIR/stale_evidence/libraries/ip_demo/versions/stale_evidence/index.html" \
  --out work/version_detail_review_report_20260818/browser_a_h
```

A-H 场景含义：首版、正常 FULL 更新、必需 View 缺失、Diff 缺失、相邻基准回退、
UNKNOWN 包、FULL+FIX/DOC 组合、过期证据。每个页面必须同时满足基础交互断言和业务语义断言。

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

本轮真实页面检查结果：

```text
页面：work/version_detail_review_report_20260818/catalog/html/libraries/ip_vendor_A.openroad_platform.openroad_asap7/versions/20260627_asap7/index.html
截图：work/version_detail_review_report_20260818/browser/ip_vendor_A.openroad_platform.openroad_asap7__20260627_asap7.png
结果：30/30 通过
树文件：211；默认变化文件 179；当前交付 210；全部证据 211
报告：默认折叠，打开/关闭交互通过
语义分区：8/8 存在
```

本轮 A-H 浏览器检查结果：

```text
8 个场景 × 31/31 断言通过
输出：work/version_detail_review_report_20260818/browser_a_h/browser_validation.json
截图：同目录下 8 个场景 PNG
```

## 可复现身份

| 字段 | 本轮记录 |
| --- | --- |
| 基线提交 | `fc59ba4ea5d6634b96bf5a17f51e09c2057da01a` |
| 工作区状态 | dirty；包含本轮代码、测试、文档和计划修改 |
| 验证日期 | 2026-08-18 |
| 验证工作区 | `work/version_detail_review_report_20260818` |
| 代码身份核对 | 以 `git rev-parse HEAD`、`git status --short`、`git diff --stat` 为准 |

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

## 代表文件核查验收（2026-10-13）

| 检查项 | 验收条件 | 自动化证据 |
| --- | --- | --- |
| 每类型一组 | 替换同类型，不覆盖其他类型 | test_representative_files |
| 不同名文件 | 支持旧、新不同文件名，展示双方绝对路径 | test_types_are_independent_and_notes_are_escaped |
| 范围明确 | 不把代表文件通过解释为整个视图通过；列出证据能力与未覆盖字段 | 详情模板、真实浏览器 |
| 来源归属 | 任意文件可对比，但跨库或非当前版本文件不能挂到当前详情 | test_web_attach_validates_scope_and_refreshes_only_selected_page |
| 产物身份 | 旧任务被重跑替换时拒绝保存；复制与重跑共享输出锁 | test_copy_and_rerun_share_one_output_lock |
| 异常重跑 | 覆盖前使旧完成标记失效；中途失败不能保存混合证据，已加入的副本保留 | test_failed_rerun_cannot_leave_old_done_generation_attachable |
| 新鲜度 | 源文件大小或修改时间变化、不可读时提示重新核查 | test_save_replace_stale_and_reconstruct |
| 可重建 | 删除 Web job、HTML 后可从记录及持久证据恢复，含自定义输出目录 | test_web_attach_validates_scope_and_refreshes_only_selected_page |
| 注入防护 | 备注、路径和字段值转义，不执行用户文本 | test_types_are_independent_and_notes_are_escaped |
| 无批量副作用 | 保存不启动扫描、对比或发布；只刷新指定详情 | Web endpoint、架构约束回归 |
| 配套清单 | Liberty/DB 清单进入详情，搜索及对应情况筛选可用 | Scan 既有配套测试、真实浏览器 |

剩余边界：未实现跨视图 pin/corner 一致性；轻量 Verilog 解析不是 HDL elaboration；
大小和修改时间只能提示文件状态，不是重新证明内容一致。
