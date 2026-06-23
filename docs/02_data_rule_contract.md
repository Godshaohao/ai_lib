# lib_guard Data Rule Contract

## Primary Data Objects

| Object | Producer | Consumer |
|---|---|---|
| `catalog.json` | `catalog.scan`, catalog overrides, runtime updates | catalog HTML, run/compare/release batch |
| `scan_meta.json` | scan pipeline | summary, render, release |
| `file_inventory.json` | scan inventory | summary, diff, scan HTML |
| `parser_manifest.json` | parser executor | summary, scan HTML |
| `parser_results.json` | parser executor | summary builders, structural diff |
| `dashboard_summary.json` | summary builder | scan HTML |
| `diff_summary.json` and diff evidence JSON | diff pipeline | diff HTML, release check |
| `release_manifest.json` | release manifest builder | release link and verify |

## Status Semantics

| Status | Meaning |
|---|---|
| `PASS` | Usable without blocking issue |
| `WARNING` / `PASS_WITH_WARNING` | Usable with visible review note |
| `BLOCK` / `BLOCKED` / `FAILED` | Must not be silently promoted |
| `PENDING` | Expected action has not run |
| `NOT_APPLICABLE` | No action needed for this version |
| `UNKNOWN` | Missing evidence or unsupported state |

## Package Semantics

| Package Type | Meaning |
|---|---|
| `FULL_PACKAGE` | Standalone usable delivery package |
| `PARTIAL_UPDATE` | Requires a base package/version |
| `DOC_UPDATE` | Release evidence or documentation-only change |
| `UNKNOWN_PACKAGE` | Needs manual classification |

## Manual Review Scope

Catalog manual review is only for items affecting asset-index trust:

- stage unknown
- parent/base unclear
- scan blocked
- release check/link blocked

Do not use manual review as a generic bucket for every warning.
