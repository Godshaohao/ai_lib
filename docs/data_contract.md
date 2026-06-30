Status: current

# Data Contract

The review pipeline exchanges JSON artifacts between stages:

| Artifact | Producer | Consumer |
| --- | --- | --- |
| `catalog.json` | catalog scan | short CLI, renderer, batch scan, compare |
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

`review_gate.json` is a lightweight gate summary. `blocking_items` can block
`current`; `attention_items`, including focused File Diff recommendations, do
not block `current` by default. Human decisions are written through CLI into
`review_overrides.json`.

## Version update detail model

`version_update_detail_model` is the structured in-memory model used by Version
Review to render “更新详情”. HTML must be generated from this model directly;
`current_lib_diff.md` is only an optional export from the same model and is not a
page input.

The normal Version Review update detail is populated by `refresh`. Base
selection defaults to `current_effective`, then `previous_effective`; manual
`cmp` remains the compare/debug path for explicit base, adjacent, or cumulative
investigation. Focused `fd` output is a manual drill-down artifact, not the
primary model input.

The model aggregates:

| Field | Source |
| --- | --- |
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

HTML renders from this model directly. Markdown export is optional evidence
generated from the same model and is never an HTML input.

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
