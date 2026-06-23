# lib_guard UI Iteration

## Principle

Generated HTML is not source. It is a preview and review artifact.

## UI Source Files

Detailed handoff notes are in `docs/05_ui_handoff.md`.

| Page | Source |
|---|---|
| Catalog HTML | `src/lib_guard/render/catalog_report.py` |
| Scan HTML | `src/lib_guard/render/html_report.py` |
| Diff HTML | `src/lib_guard/render/html_report.py` |
| File Diff HTML | `src/lib_guard/diff/file_diff.py` |
| Release HTML | `src/lib_guard/render/release_report.py` |
| Compatibility console | `src/lib_guard/render/control_console.py` |
| Shared UI components/theme | `src/lib_guard/render/product_theme.py` |

## UI Allowed Changes

- layout
- table/card composition
- Chinese page text
- report entry grouping
- CSS and lightweight JS emitted by renderers
- view-model shaping for display-only fields

## UI Forbidden Changes

For UI-only tasks, do not modify:

- parser logic
- validator/policy definitions
- summary metric meaning
- status vocabulary
- raw data schema
- release link behavior

## UI Acceptance

For report changes:

1. Run `py_compile` for changed render files.
2. Regenerate a demo HTML under `work/`.
3. Confirm the page uses the expected source renderer, not edited generated HTML.

## v6 Review UI Rules

- Catalog is a map and navigation hub, not the File Diff command page.
- Diff Timeline leads to one Selected Diff.
- Selected Diff owns recommended File Diff commands.
- File Diff HTML should show structured field differences, location hints, and raw text fallback.
- Do not use `File Diff 2/5` or `done/total` progress labels.
