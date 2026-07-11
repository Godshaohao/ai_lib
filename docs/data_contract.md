Status: current

# 数据契约

本文定义 `lib_guard` 各阶段交换的数据契约。契约的目标不是记录所有字段，而是固定
哪些 artifact 是事实源、哪些是派生模型、哪些只是用户投影。

## 单向数据流

```text
人工确认配置
  -> catalog.json
  -> scan_out/review TSV
  -> diff/compare JSON
  -> review/effective/window 派生模型
  -> HTML / report_index / manager_tasks 投影
```

禁止反向依赖：

- HTML 不能作为 scan/diff/release 输入。
- `catalog_state.json` 不能替代 `catalog.json`、scan 或 diff。
- `manager_tasks.json` 不能成为有效版判断来源。
- 缺失 diff 不能渲染成真实“无变化”。

Scan 阶段的 JSON 是机器事实源，不是人工 review 的主要界面。人工可读证据的分层、
TSV/HTML 表和默认页面展示口径见
[Scan 证据分层与人工审查口径](scan_evidence_review.md)。

## Artifact 总表

| Artifact | Producer | Consumer | 契约 |
| --- | --- | --- |
| `config/library_registry.tsv` | user / library commands | library apply | 人工确认库根，不由 discover 自动覆盖 |
| `config/library_catalog.yml` | library apply | catalog refresh | 正式库 map，catalog 的库来源 |
| `catalog/catalog.json` | catalog refresh and runtime updates | short CLI, scan, compare, renderer, intake | 库/版本资产地图和运行时指针；用户不手改 |
| `scan_out/**/file_inventory.json` | scan | Version Detail, readiness, diff | 单版本文件事实 |
| `scan_out/**/parser_manifest.json` | scan | parser executor, Version Detail | parser 任务事实 |
| `scan_out/**/parser_results.json` | parser executor | summary, diff, Version Detail | 机器结果；默认不作为人工主界面 |
| `scan_out/**/review/*.tsv` | scan evidence exporter | Scan HTML, Version Detail | 人工可读 scan 证据 |
| `scan_out/**/summary/release_readiness.json` | summary/readiness | release checks, Version Detail, diff | 单版本 release/readiness 摘要 |
| `diff/**/diff_summary.json` | compare | catalog, Version Detail, Comparison Review | 对比结论摘要 |
| `diff/**/view_diff.json` | compare | Version Detail, Comparison Review | View 级变化 |
| `diff/**/type_diff.json` | compare | Version Detail, Comparison Review | file_type 级变化 |
| `diff/**/release_readiness_diff.json` | compare | Version Detail, Comparison Review | readiness 变化 |
| `diff/**/release_evidence_diff.json` | compare | Version Detail, Comparison Review | release evidence 变化 |
| `diff/**/diff_issues.json` | compare | Version Detail, Comparison Review | 对比问题 |
| `diff/**/file_diff.json` | compare / fd | Version Detail, Comparison Review, focused file review | 文件变化事实；added/removed 不等于真实 rename |
| `catalog/html/**/effective/*/effective_manifest.json` | intake/effective | Version Detail, release | 候选或当前有效组合 |
| `catalog/html/**/window/pending_window.json` | intake/window | Version Detail, accept-window | 当前接入窗口 |
| `catalog/html/**/current_effective.json` | accept-window / rollback | Version Detail, library workspace | 当前有效版指针 |
| `catalog/html/catalog_state.json` | renderer | Catalog, Library Workspace | 页面状态模型，不是上游事实源 |
| `catalog/html/manager_tasks.json` | renderer | library manager queue | 管理任务投影，不是 scan/diff 输入 |
| `catalog/html/report_index.json` | renderer | navigation, report links, legacy list fallback | 报告索引，不是事实源；命令不能把它当作 current effective 判断来源 |
| `review_gate.json` | review gate | release-check, Version Detail | 轻量门禁摘要 |
| `review_overrides.json` | review CLI | review gate, release-check | 人工 accept/waive 决策 |
| `release_manifest.json` | release preview/batch | release linker, release HTML | release 文件清单 |
| `release_link_result.json` | release linker | release result, postcheck | link 执行结果 |
| `release_result.json` | release checker/linker | catalog state, release HTML | release 检查/执行结果 |

Policies in `configs/` define current catalog and release behavior. The active
project policy files are `catalog_policy.json` and `release_policy.json`.

## 模型边界

审查数据模型固定为三层：

| Layer | Owner | Meaning |
| --- | --- | --- |
| Source facts | user config and tool artifacts | 人工确认 library map、raw path、scan inventory、parser results、diff JSON、release readiness、review overrides |
| Derived review model | review/model/render adapter | Base selection、normalized file changes、review lanes、evidence quality、path-restructure hints、单一 `usage_decision` |
| Presentation model | HTML renderer | Cards、tables、folded evidence、links、中文文案 |

`version_evidence_state` 是 Version Detail 的事实源索引，不是新的事实源。它把
`catalog.json`、scan evidence、diff/compare evidence、effective/window evidence
和 HTML projection 的关系显式列出来，用来说明哪些判断来自机器事实、哪些只是页面投影。
HTML 永远不能反向成为 scan、diff 或 release 的输入。

`library_registry.tsv` 是用户确认的库根 registry。`library_catalog.yml` 由 registry
生成，是 catalog/scan/diff 的库 map 来源。`library_candidates/latest.tsv` 只是 discover
候选审查队列；只有 accept/apply 后才成为事实。

`catalog.json` 是生成的 catalog index 加运行时指针。用户不应手改其中 scan/diff/release
字段；人工修正必须通过 `library override`、`mark`、review command 或 policy，使模型可重建。

Catalog 内部命名契约。日常命令和主 UI 只展示“库名”和“版本名”；下面字段用于
内部索引、兼容和报告路径，不要求用户记忆。

| 字段 | 含义 | 示例 |
| --- | --- | --- |
| `formal_library_id` | 用户可复制的库名 | `vendor_A.openroad_platform.openroad_asap7` |
| `typed_library_id` | 带 library type 的内部完整键，不在日常命令中展示 | `ip/vendor_A.openroad_platform.openroad_asap7` |
| `version_id` | 原始版本目录名 | `20260627_asap7` |
| `version_uid` | 内部全局版本键；旧字段 `version_key` 与它保持一致，不在日常命令中展示 | `ip/vendor_A.openroad_platform.openroad_asap7/20260627_asap7` |
| `report_slug` | HTML 和文件系统目录名，只用于路径，不作为用户输入 | `ip_vendor_A.openroad_platform.openroad_asap7` |
| `display_name` | UI 显示名，不作为高优先级查找键 | `openroad_asap7` |

`catalog_state.json`、`manager_tasks.json` 和 `report_index.json` 是 render artifacts。
它们不能成为 scan、diff、release 或有效版判断的事实输入。

`library list --effective` 的有效版状态必须优先读取
`current_effective.json` 和对应 `effective_manifest.json`。`report_index.json` 只作为旧报告兼容
回退，用于补充导航链接；如果 `report_index.json` 缺失或 stale，不能导致当前有效版被判断为
不存在。

`review_gate.json` is a lightweight gate summary. `blocking_items` can block
`current`; `attention_items`, including focused File Diff recommendations, do
not block `current` by default. Human decisions are written through CLI into
`review_overrides.json`.

## Version Detail Review Model

`version_update_detail_model` is the structured in-memory model used by Version
Review to render “更新详情”. HTML must be generated from this model directly;
`current_lib_diff.md` is only an optional export from the same model and is not a
page input.

The normal Version Review update detail is populated by `cat --update-detail`.
Base selection defaults to `current_effective`, then `previous_effective`; manual
`cmp` remains the compare/debug path for explicit base, adjacent, or cumulative
investigation. Focused `fd` output is a manual drill-down artifact, not the
primary model input.

The model aggregates:

| Field | Source |
| --- | --- |
| `review_context` | pending review window, candidate effective manifest, compare manifest, and scan evidence freshness |
| `diff_summary` | `diff_summary.json` |
| `view_diff` | `view_diff.json` |
| `type_diff` | `type_diff.json` |
| `release_readiness_diff` | `release_readiness_diff.json` |
| `release_evidence_diff` | `release_evidence_diff.json` when present |
| `diff_issues` | `diff_issues.json` |
| `file_diff` | `file_diff.json` |
| `release_notes` | version metadata and release note artifacts |

If no trusted base is available, the model status is `NEEDS_BASE_CONFIRM`.
If compare has not run, the status is `DIFF_NOT_RUN`. These states must not be
rendered as a real diff.

## Version Update Detail Reviewer Fields

The Version Update Detail reviewer surface uses these model fields as the
reviewer's source of truth:

| Field | Meaning |
| --- | --- |
| `headline` | One-line summary of base relationship, changed-file count, recommended file-diff count, and already-reviewed lane count |
| `confidence_note` | Compact provenance note for base source, base reference, comparison semantics, and delete semantics |
| `primary_next_action` | Structured next action with `kind`, display label, and command count |
| `recommended_file_diff` | P0/P1 text-like file changes that should receive focused File Diff review |
| `summary_only_reviewed` | Large logical text views reviewed at summary level without default full file diff |
| `metadata_only_reviewed` | Binary/layout/database views reviewed through metadata, hash, path, and summary evidence |
| `lane_counts` | Counts for recommended file diff, `summary-only`, `metadata-only`, and blocking issue lanes shown in Version Review |
| `summary_only_changes` | Alias for the reviewed `summary-only` lane so downstream reviewers can read changes without treating them as missed `fd` work |
| `metadata_only_reviewed_changes` | Alias for only the reviewed `metadata-only` lane so binary/layout/database changes stay tied to metadata evidence |
| `metadata_only_changes` | Backward-compatible aggregate of `summary_only_reviewed + metadata_only_reviewed`; kept for older downstream readers that treat both lanes as reviewed without default `fd` work |
| `base_trust_status` | Trust state for the selected base, such as `PASS`, `WARNING`, or `BLOCKING` |
| `base_trust_note` | Human-readable explanation of whether the selected base is release-grade evidence |
| `status_message` | Actionable copy for the current update-detail status |
| `usage_decision` | Single user-facing decision: `READY`, `USAGE_REVIEW_REQUIRED`, or `BLOCKED` |
| `usage_decision_reasons` | Machine-readable reasons behind `usage_decision`, for example `diff_changed`, `recommended_file_diff`, `release_note_missing`, or `base_not_confirmed` |
| `review_context.status` | `IN_ACTIVE_WINDOW` when the version belongs to the active pending window; otherwise `STANDALONE` |
| `review_context.role_in_window` | `candidate_base`, `candidate_overlay`, `intermediate`, or `standalone` |
| `review_context.freshness` | Existence checks for window, candidate effective manifest, compare manifest/html, and scan evidence |
| `file_changes[].identity` | Lightweight file identity hints: basename, suffix, size, sha/hash, parser signature, and deterministic match key |
| `path_restructure` | Heuristic review hint for likely repackaging or root-path movement; it must not claim content equivalence by itself |

HTML renders from this model directly. Markdown export is optional evidence
generated from the same model and is never an HTML input.

`review_context` is projection context, not a new workflow entry. It lets Version
Detail explain whether the current page is showing a standalone version or an
active review window member, and whether candidate effective / compare evidence
is fresh enough to trust. Missing freshness must be shown as stale or partial;
it must not be silently replaced with adjacent comparison output.

Path movement has two separate meanings. `file_diff.renamed_or_moved` is a
file-level match list and may be small when hashes are missing, duplicated, or
summary-only. `file_diff.package_root_migrations` is the package-level signal:
it groups logical-path pairs by old/new wrapper root and reports
`matched_logical_paths`, `old_root_file_count`, and `new_root_file_count`.
Version Review must use `package_root_migrations` when explaining repackaging;
it must not present `renamed_or_moved` alone as the package migration scale.

`file_changes[].identity` supports human review of added/removed path churn. It
is not a fuzzy-match or equivalence algorithm. A matching basename/size/parser
signature may justify a focused manual check, but the model must still label the
raw compare result as added/removed until a real pairwise or owner review closes
the question.

## Render Impact Contract

`RenderImpact` 是投影刷新协议，不是调度状态机。命令完成后只声明受影响对象：

```json
{
  "kind": "version_detail",
  "library": "Vendor_A.ucie",
  "version": "20260624_adhoc_ucie_netlists_t7_release",
  "reason": "scan_updated"
}
```

finalizer 根据影响集合刷新页面：

| 影响类型 | 刷新对象 |
| --- | --- |
| `version_detail` | 单个 Version Detail |
| `library_page` | 单个库工作台，可延迟到下一次低频 render |
| `catalog_index` | Catalog 首页，可延迟到下一次低频 render |

命令输出里的 `render_summary` 是用户判断页面是否更新的契约：

| 字段 | 含义 |
| --- | --- |
| `status` | `PASS`, `SKIPPED`, `FAILED` |
| `message` | 中文摘要，例如“版本详情已刷新 1 个版本；Catalog 导航页延迟刷新” |
| `open_first` | 建议打开的第一个 Version Detail |
| `version_detail_htmls` | 本次直接刷新的详情页 |
| `deferred_file` | 延迟刷新 library/catalog 导航的记录 |

`render_summary` 可以告诉用户页面是否 stale，但它不是事实源。

## File type lanes

File types are split by review lane in `src/lib_guard/project_config.py`:

| Lane | Meaning |
| --- | --- |
| `DEFAULT_FILE_DIFF_TYPES` | Text-like review files that may receive default focused File Diff recommendations |
| `SUMMARY_ONLY_TYPES` | Large or multi-file logical views such as Verilog/SystemVerilog, Liberty/Lib, and SPEF; summarize/count/classify only |
| `BINARY_METADATA_ONLY_TYPES` | Binary or layout database views such as DB/GDS/OAS/Layout/Milkyway/NDM; metadata/hash/path evidence only |

`pairwise.py`, `scan_diff.py`, and `version_detail_report.py` must use the same
lane constants so the command recommendation, scan summary, and Version Review
page cannot disagree.

The lane labels are reviewer evidence semantics. `summary-only` means large
logical views were reviewed through summary/count/corner evidence; `metadata-only`
means binary, layout, or database views were reviewed through hash, size, path,
count, and related metadata. These lanes must not be converted into default
pairwise or `refresh` work just because a file changed. `--force-large` is only
an explicit expert opt-in for manual `fd`; it must not affect `refresh`, `cmp`,
or automatic pairwise recommendation generation.
