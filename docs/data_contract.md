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
| `diff_issues.json` | compare | version review, comparison review |
| `catalog_state.json` | catalog renderer | Catalog, Library Workspace, Version Review |
| `manager_tasks.json` | catalog renderer | library manager next-action queue |
| `review_gate.json` | review gate | release-check, Version Review |
| `review_overrides.json` | review CLI | review gate, release-check |
| `release_manifest.json` | release preview/batch | release linker, release HTML |
| `release_link_result.json` | release linker | release result, postcheck |
| `release_result.json` | release checker/linker | catalog state, release HTML |

Policies in `configs/` define current catalog and release behavior.
`configs/legacy_summary_policy.json` is retained only for compatibility with the
old update path.

`review_gate.json` is a lightweight gate summary. `blocking_items` can block
`current`; `attention_items`, including focused File Diff recommendations, do
not block `current` by default. Human decisions are written through CLI into
`review_overrides.json`.
