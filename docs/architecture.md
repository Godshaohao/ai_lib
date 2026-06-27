Status: current

# Architecture

`lib_guard` is organized around review evidence:

```text
raw delivery -> catalog -> scan -> parser results -> summary/readiness -> diff
  -> review_gate + owner overrides when needed -> manifest-driven symlink release
```

The current source-of-truth modules are:

| Area | Path |
| --- | --- |
| Catalog state | `src/lib_guard/catalog/` |
| Scan inventory and parsers | `src/lib_guard/scan/` |
| Summary builders | `src/lib_guard/summary/` |
| Structural comparison | `src/lib_guard/diff/` |
| Package/effective composition | `src/lib_guard/package/`, `src/lib_guard/effective/` |
| Release evidence | `src/lib_guard/release/` |
| Review gate aggregation | `src/lib_guard/review/` |
| Review rendering | `src/lib_guard/render/` |
| CLI | `src/lib_guard/cli.py`, `src/lib_guard/short_cli.py`, `src/lib_guard/cli_commands/` |

Generated HTML and JSON under `work/` are review artifacts. They should be
recreated from source data and policies.

Catalog HTML writes `catalog_state.json`, `manager_tasks.json`, and
`report_index.json`. Version-level `review_gate` data is embedded in
`catalog_state.json` and can also be written to
`review/<library>/<version>/review_gate.json`.

File Diff recommendations are attention items by default. Metadata-only binary
changes, catalog trust problems, and release fatal issues are the normal sources
of blocking review gate items.
