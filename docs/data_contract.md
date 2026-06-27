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

Policies in `configs/` define current catalog and release behavior.
`configs/summary_policy.json` is retained only for compatibility with the old
update path.

