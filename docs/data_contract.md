Status: current

# 数据契约

本文定义 `lib_guard` 各阶段交换的数据契约。契约的目标不是记录所有字段，而是固定
哪些 artifact 是事实源、哪些是派生模型、哪些只是用户投影。

## 单向数据流

```text
人工确认配置
  -> catalog.json + catalog_runtime.json
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
| `catalog/catalog.json` | catalog refresh | short CLI, scan, compare, renderer, intake | 库/版本资产快照；不承载新的运行时写入 |
| `catalog/catalog_runtime.json` | scan/diff/release status updates | `load_catalog_view`, review/render, window, release manifest | 运行时状态 sidecar；sidecar 优先，旧嵌入字段回退 |
| `scan_out/**/file_inventory.json` | scan | Version Detail, readiness, diff | 单版本文件事实 |
| `scan_out/**/parser_manifest.json` | scan | parser executor, Version Detail | parser 任务事实 |
| `scan_out/**/parser_results/<view>/*.json` | parser executor | summary, diff, Version Detail | 默认机器结果；按需读取，不作为人工主界面 |
| `scan_out/**/parser_results.json` | parser executor（旧策略） | summary, diff, Version Detail | 兼容/调试结果；新 CLI 默认不生成 |
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
| `catalog/html/**/effective/*/review_approval.json` | accept-window | current effective pointer, audit | 人工接受凭证；绑定 candidate effective digest 和 compare digest |
| `catalog/html/**/window/pending_window.json` | intake/window | Version Detail, accept-window | 当前接入窗口 |
| `catalog/html/**/current_effective.json` | accept-window / rollback | Version Detail, library workspace | 当前有效版指针 |
| `catalog/html/catalog_state.json` | renderer | Catalog, Library Workspace | 页面状态模型，不是上游事实源 |
| `catalog/html/manager_tasks.json` | renderer | library manager queue | 管理任务投影，不是 scan/diff 输入 |
| `catalog/html/report_index.json` | renderer | navigation, report links, legacy list fallback | 报告索引，不是事实源；命令不能把它当作 current effective 判断来源 |
| `review_gate.json` | review gate | release-check, Version Detail | 轻量门禁摘要 |
| `review_overrides.json` | review CLI | review gate, release-check | 人工 accept/waive 决策 |
| `release_manifest.json` | release preview/batch | release linker, release HTML | release 文件清单；普通 `lg rel <LIBRARY>` 从当前 accepted effective 生成 file-level 清单，显式 VERSION 才走 raw catalog version |
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

### Version Detail Review Report

`review_report` 是 `version_review_model` 生成的有界派生模型，不是第五类事实源，也不读取
RAW 或 Markdown。它必须保持以下固定分组，供 Version Detail 折叠渲染和显式 Markdown 导出共同使用：

| 字段 | 内容 | 事实来源 |
| --- | --- | --- |
| `base_analysis` | Target、Base、来源、对比语义、可信状态 | review context、catalog lineage、diff metadata |
| `delivery_analysis` | 包类型、交付文件数、必需视图覆盖和缺失项 | scan inventory、readiness |
| `view_delta_analysis` | 统一视图类型行、增删改总计、汇总核对状态，以及 `file_diff -> View Delta -> Focus Files -> File Tree` 对账 | `file_diff`、`view_diff`、`type_diff`、IP view model |
| `focus_file_analysis` | 有界重点文件、匹配/证据字段和截断状态 | `file_diff`、review lanes |
| `unknown_analysis` | 未知文件数量、代表路径、分类状态 | scan inventory |
| `evidence_assessment` | scan/diff 状态、scan id、来源路径、新鲜度 | scan context、comparison context、evidence state |
| `open_questions` | 当前事实仍无法回答的问题 | 上述各分组的缺失/阻塞条件 |
| `recommended_actions` | 已有建议动作或由未决问题派生的动作 | diff summary、review model |

IP 使用者模型另外固定提供 `decision.next_action` 和顶层 `next_action`。它们是首屏的
单一结构化下一步，不是自动命令计划；当状态为待确认、阻塞或首版审查时，必须能在
Decision HTML 直接看到动作和简短说明。

`view_delta_analysis.evidence_reconciliation` 至少包含：`file_diff_declared`、
`file_diff_items`、`visible_file_diff_items`、`view_matrix`、`focus_files`、
`file_tree_changes` 和 `checks`。`MISMATCH` 只能表示证据链需要复核，不能被渲染成
正常无变化。

报告渲染必须只消费这个模型；页面使用 `data-section` 标记固定
`decision-summary`、`comparison-context`、`impact-summary`、`view-delta`、
`focus-files`、`file-structure`、`review-report` 和 `evidence-status`，供浏览器验收和后续
投影维护使用。

`version_evidence_state` 是 Version Detail 的事实源索引，不是新的事实源。它把
`catalog.json`、scan evidence、diff/compare evidence、effective/window evidence
和 HTML projection 的关系显式列出来，用来说明哪些判断来自机器事实、哪些只是页面投影。
HTML 永远不能反向成为 scan、diff 或 release 的输入。

`library_registry.tsv` 是用户确认的库根 registry。`library_catalog.yml` 由 registry
生成，是 catalog/scan/diff 的库 map 来源。`library_candidates/latest.tsv` 只是 discover
候选审查队列；只有 accept/apply 后才成为事实。

`catalog.json` 是生成的 Catalog 资产快照；`catalog_runtime.json` 是 scan/diff/release
运行状态 sidecar。业务代码通过 `load_catalog_view()` 读取合并视图，sidecar 优先，旧
`catalog.json` 内嵌 runtime 只作为迁移期回退。用户不应手改生成文件；人工修正必须通过
`library override`、`mark`、review command 或 policy，使模型可重建。

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

`current_effective.json` 是可并发检查的当前有效版指针，至少包含
`current_effective_id`、`revision`、`previous_effective_id`、`previous_revision`、
`manifest`、`manifest_sha256`、`review_approval` 和 `approval_sha256`。`accept-window`
写入前必须确认 pending window 的 base 仍等于当前指针；如果期间有人改过 current，
命令必须失败并要求重新执行 `lg next <LIBRARY> --apply` 重建 compare 证据。

`review_approval.json` 是 `review_approval.v1` 人工接受凭证。它必须记录候选
`effective_manifest.json` 的 sha256、compare manifest 的 sha256、接受人、接受时间和备注。
它不是新的事实源，只是把“我接受的是哪一份 candidate 与哪一次 compare”固化下来，
防止后续 release 消费到已经漂移的 effective。

`review_gate.json` is a derived gate summary. The recommended static review
workflow writes it only from `Review Packet` source records. The older
`review_overrides.json` path remains a compatibility input for existing
projects, but it is not the new department response record.

页面和数据合同始终分开表达四个状态维度：

- `technical_decision`：scan/diff/evidence 得出的 IP 使用判断；
- `review_gate`：仅为 `WAITING`、`BLOCKED`、`APPROVED` 的专业审查完成度；
- `effective_state`：`accept-window` 受控写入的当前工程有效组合 / review baseline；
- `release_state`：release check、link、postcheck 的正式发布事实。

其中 `APPROVED` 不自动写 `current_effective`，`current_effective` 也不等价于
`Released`；HTML 只能展示这些已有事实，不能根据任意一个状态自行推断其他状态。

## 静态 Review Packet 数据合同

静态审查不引入数据库、服务端或第二个 HTML 入口。目录固定为：

```text
reviews/<library_id>/<target_version>/<packet_id>/
  packet.json
  review_items.tsv
  responses/*.tsv
  review_gate.json
  review_report.md
```

其中：

| 记录 | 写入方 | 作用 | 是否事实源 |
| --- | --- | --- | --- |
| `packet.json` | `review prepare` | 冻结 Target、Base、Compare 和策略版本 | 是 |
| `review_items.tsv` | `review prepare` | 面向部门的问题，不是文件清单 | 是 |
| `responses/*.tsv` | `review submit` | 追加式 PASS/BLOCK/QUESTION 与备注 | 是 |
| `review_gate.json` | `review collect` | 汇总 WAITING/BLOCKED/APPROVED | 否，派生 |
| `review_report.md` | `review collect` | 人类可读的完整审查记录 | 否，派生 |

`packet_id` 由以下身份共同决定：

```text
library_id + target_version + target_manifest_sha256
+ base_version + base_manifest_sha256 + compare_sha256
+ review_policy_version + review_policy_sha256 + machine_facts_sha256
```

任何一个身份输入变化都必须生成新的 Packet；旧响应保留为历史记录，但不能参与新
Gate。提交时系统重新验证当前 Packet，不能靠 reviewer 手工填写 packet/hash 字段。

Review Item 是可直接回答的问题，并通过 `evidence_ref` 指向 Version Detail 或已有
证据，不把 raw JSON、完整 diff 或文件列表复制给 reviewer。机器可以判断的缺失
manifest、失败 scan、缺失 compare 等事实直接成为 machine blocker，不伪装成“请人批准”。

Response 只允许三种决策：`PASS`、`BLOCK`、`QUESTION`。`BLOCK` 和 `QUESTION` 必须
填写 note；每次提交写一个新 TSV，不覆盖旧记录。同一 reviewer 的当前意见按内容字段
`submitted_at` 选择，不能依赖 mtime；不同 reviewer 只要有一个有效 `BLOCK`，Gate 就是
`BLOCKED`。

豁免不是普通 reviewer decision。它必须来自受控的 waiver 记录，包含
`authorized_by` 和 `reason`，且只能解除一个已经存在的有效 `BLOCK`；原始 BLOCK 和提交历史
仍保留在 response/report 中。未知 item、缺授权人或缺理由的 waiver 不改变 Gate。

Gate 汇总规则固定为：

```text
machine blocker 或 active BLOCK -> BLOCKED
required response 缺失或 QUESTION -> WAITING
其他全部 required PASS -> APPROVED
```

`review_policy_sha256` 是规范化后的完整策略内容摘要；即使管理员忘记递增
`review_policy_version`，只要 View/风险路由或必要规则发生变化，也会生成新的
Packet，旧 response 不会复用于新 Gate。`review_gate.json` 不包含采集时钟等非事实
字段，因此相同 source records 多次 collect 的结果是确定且幂等的。

`current_effective` 仍然表示当前人工接受的工程有效组合 / review baseline，不等价于
正式发布完成。`APPROVED` 也不自动写 current effective；`accept-window`、release check、
link、postcheck 仍是独立受控步骤。HTML 只能展示这些已有事实，不能推断 Released。

删除 `review_gate.json` 或 `review_report.md` 后，重新运行 `lg review collect` 即可从
source records 重建；普通 render、cat、review submit 不会删除 responses。当前信任边界是
内部受控文件系统和用户身份，reviewer 字段提供内部可追溯性，但不是法规级数字签名。

## 版本详情页审查模型

`version_update_detail_model` 是版本详情页用于渲染“更新详情”的结构化内存模型。
HTML 必须直接由该模型生成；`current_lib_diff.md` 只是同一模型的可选导出，不是页面输入。

普通版本详情页的更新详情由 `cat --update-detail` 填充。
基准版默认依次使用 `current_effective`、`previous_effective`；手动 `cmp` 仍用于显式基准版、相邻版本或累计对比调查。
指定文件的 `fd` 输出是人工下钻证据，不是主模型输入。

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
| `path_changes_same_content[]` | `file_diff.renamed_or_moved` 的页面投影；只保存去除 RAW、版本和包装根之后仍不同的旧/新逻辑路径、文件类型和匹配依据，按视图展示为“路径变化且内容相同”，不并入内容修改 |
| `path_restructure` | Heuristic review hint for likely repackaging or root-path movement; it must not claim content equivalence by itself |

HTML renders from this model directly. Markdown export is optional evidence
generated from the same model and is never an HTML input.

`review_context` is projection context, not a new workflow entry. It lets Version
Detail explain whether the current page is showing a standalone version or an
active review window member, and whether candidate effective / compare evidence
is fresh enough to trust. Missing freshness must be shown as stale or partial;
it must not be silently replaced with adjacent comparison output.

路径变化有两个不同口径。系统先去掉 RAW 根、版本目录和已识别的包装根，再比较逻辑
路径。归一化后路径相同且内容一致的文件属于 `unchanged`；包装前缀变化只写入
`file_diff.package_root_migrations`，不得写入 `renamed_or_moved`。只有归一化后旧、新逻辑
路径仍不同，并且存在唯一内容 Hash 匹配时，才写入 `file_diff.renamed_or_moved`，再投影到
`path_changes_same_content[]`。该类别不并入新增、删除或内容修改；缺少 Hash、Hash 不唯一
或证据不足的文件不得进入。包根迁移按旧、新包根聚合，并报告
`matched_logical_paths`、`old_root_file_count` 和 `new_root_file_count`。

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
