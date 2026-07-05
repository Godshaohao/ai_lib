Status: current

# Data Contract

The review pipeline exchanges JSON artifacts between stages:

| Artifact | Producer | Consumer |
| --- | --- | --- |
| `catalog.json` | catalog refresh | short CLI, renderer, batch scan, compare |
| `file_inventory.json` | scan | version review, readiness, diff |
| `parser_manifest.json` | scan | parser executor, version review |
| `parser_results.json` | parser executor | summary, diff, version review |
| `release_readiness.json` | release/readiness | release checks, version review, diff |
| `diff_summary.json` | compare | catalog, version review, comparison review |
| `view_diff.json` | compare | version review, comparison review |
| `type_diff.json` | compare | version review, comparison review |
| `release_readiness_diff.json` | compare | version review, comparison review |
| `release_evidence_diff.json` | compare | version review, comparison review |
| `diff_issues.json` | compare | version review, comparison review |
| `file_diff.json` | compare / file-diff | version review, comparison review, focused file review |
| `catalog_state.json` | catalog renderer | Catalog, Library Workspace, Version Review |
| `manager_tasks.json` | catalog renderer | library manager next-action queue |
| `review_gate.json` | review gate | release-check, Version Review |
| `review_overrides.json` | review CLI | review gate, release-check |
| `release_manifest.json` | release preview/batch | release linker, release HTML |
| `release_link_result.json` | release linker | release result, postcheck |
| `release_result.json` | release checker/linker | catalog state, release HTML |

Policies in `configs/` define current catalog and release behavior. The active
project policy files are `catalog_policy.json` and `release_policy.json`.

## Model boundaries

Keep the review data model split into three layers:

| Layer | Owner | Meaning |
| --- | --- | --- |
| Source facts | user config and tool artifacts | User-confirmed library map, raw path, scan inventory, parser results, diff JSON, release readiness, and review overrides |
| Derived review model | review/model/render adapter | Base selection, normalized file changes, review lanes, evidence quality, path-restructure hints, and the single `usage_decision` |
| Presentation model | HTML renderer | Cards, tables, folded evidence, links, and Chinese copy |

`library_registry.tsv` is the user-confirmed library root registry.
`library_catalog.yml` is generated from that registry and is the catalog/scan/diff
library map source. `library_candidates/latest.tsv` is only a discovery review
queue; it is not a source fact until accepted into the registry.
`catalog.json` is a generated catalog index plus merged runtime facts. Users
should not manually edit runtime scan/diff/release fields inside `catalog.json`;
manual corrections should go through catalog override/review commands so the
generated model can be rebuilt.

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

`catalog_state.json`, `manager_tasks.json`, and `report_index.json` are render
artifacts. They must not become source facts for scan, diff, or release logic.

`review_gate.json` is a lightweight gate summary. `blocking_items` can block
`current`; `attention_items`, including focused File Diff recommendations, do
not block `current` by default. Human decisions are written through CLI into
`review_overrides.json`.

## Version update detail model

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
