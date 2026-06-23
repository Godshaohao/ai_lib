# lib_guard UI Handoff

## Purpose

This document is the handoff note for people or AI agents who continue UI/report work.

The UI source of truth is Python renderer code plus the JSON inputs it reads. Generated HTML under `work/`, `reports/`, or release preview directories is output only.

## UI Source Files

| Page | Source file | Main entry | Role |
|---|---|---|---|
| Catalog | `src/lib_guard/render/catalog_report.py` | `render_catalog_html()` | Asset entry page, library detail pages, report links |
| Scan | `src/lib_guard/render/html_report.py` | `render_scan_html()` | Delivery structure review for one scanned version |
| Diff | `src/lib_guard/render/html_report.py` | `render_diff_html()` | Structure change review between two scan outputs |
| Release | `src/lib_guard/render/release_report.py` | `render_release_html()` | File-level release/link verification report |
| Compatibility console | `src/lib_guard/render/control_console.py` | `render_console()` | Legacy wrapper that points to the scan review page |
| Shared theme/components | `src/lib_guard/render/product_theme.py` | `page_shell()`, `panel()`, `table()`, `badge()` | Shared layout, CSS, badges, panels, tables |

Related non-UI entry:

| Area | Source file | Role |
|---|---|---|
| Catalog state and render adapter | `src/lib_guard/catalog/index.py` | Owns catalog JSON updates and delegates HTML rendering to `render/catalog_report.py` |
| CLI handlers | `src/lib_guard/cli_commands/` | Calls scan/diff/release/catalog renderers from CLI workflows |
| CLI parser wiring | `src/lib_guard/cli.py` | Registers command arguments only |

## UI Context

The product UI is a static review console for IC/PD library management. It is not a web app with a backend.

The current user workflow is:

```text
raw library folders
  -> catalog scan
  -> scan selected versions
  -> compare adjacent/cumulative versions
  -> release manifest/link/check
  -> static HTML reports for review
```

The page responsibilities are intentionally separated:

| Page | Primary question | Should not become |
|---|---|---|
| Catalog | Which libraries and versions exist, and where are their reports? | Full debug console or release operation center |
| Scan | What did this version deliver by file type/view? | Final signoff page |
| Diff | What structure changed between two versions? | Raw changed-file dump |
| Release | Which files were linked/copied, and does the release area match the manifest? | Policy authoring UI |

Manual confirmation in Catalog should only show items that affect asset index trust:

- `stage unknown`
- unclear `parent` / `base`
- scan blocked or failed
- release blocked or failed

Parser details, command debug text, and low-level JSON evidence should be linkable or folded, not promoted as the first page content.

## View Model Ownership

There is no separate `src/lib_guard/view_model/` package yet.

Current view-model shaping is local to renderer helper functions. These helpers read normalized JSON data, group it for the page, and emit HTML-ready rows/cards. They are UI-facing adapters, not parser or policy logic.

### Catalog View Model

Source file:

```text
src/lib_guard/render/catalog_report.py
```

Primary JSON input:

```text
catalog.json
```

Renderer entry:

```text
render_catalog_html(catalog_path, out_dir, max_report_rows=16)
```

Helper map:

| Helper | Input | UI output | Responsibility |
|---|---|---|---|
| `_latest_catalog_version()` | one `library` object | latest version object | Pick the latest version for summary display |
| `_catalog_version_report_counts()` | one `library` object | `{scan, diff, release}` counts | Count how many versions already have report evidence |
| `_catalog_stage_mix()` | one `library` object | compact stage text | Show `initial/stable/final/ad-hoc/dated/unknown` mix |
| `_catalog_priority_items()` | full catalog, optional library filter | priority item list | Build the manual-confirmation queue for asset trust only |
| `_catalog_attention_table()` | full catalog | HTML table | Render high-priority catalog trust issues |
| `_catalog_library_rows()` | `libraries[]` | table rows | Build the main library asset index |
| `_catalog_diff_entry()` | version diff object | compact diff link/status HTML | Show adjacent/cumulative diff evidence in version rows |
| `_catalog_report_rows()` | `libraries[]` | report entry rows | Build high-value report shortcuts |
| `_version_simple_rows()` | one `library` object | version table rows | Render one library detail page version list |
| `_render_library_page()` | full catalog, one library, output path | `libraries/<name>.html` | Build single-library drilldown page |

Catalog view model rules:

- Manual confirmation must stay limited to `stage unknown`, unclear `parent/base`, scan blocked, and release blocked.
- Catalog should link to Scan/Diff/Release reports instead of duplicating their detail.
- `raw_path`, `scan_dir`, `scan_html`, `diff_html`, and `release_html` are navigation/evidence fields, not page conclusions.

### Scan View Model

Source file:

```text
src/lib_guard/render/html_report.py
```

Primary JSON inputs:

```text
scan_meta.json
file_inventory.json
parser_manifest.json
scan_issues.json
summary/dashboard_summary.json
summary/release_readiness.json
```

Renderer entry:

```text
render_scan_html(scan_dir, out_dir)
```

Helper map:

| Helper | Input | UI output | Responsibility |
|---|---|---|---|
| `_type_group()` | `file_type` string | group label | Map file types to delivery groups |
| `_type_meaning()` | `file_type` string | short explanation | Explain what each file type means in review |
| `_type_counts()` | inventory, parser manifest, dashboard | `{file_type: count}` | Build the central file type count map |
| `_group_counts()` | file type counts | `{group: count}` | Aggregate counts into implementation/constraint/layout/doc groups |
| `_structure_cards()` | file type counts | card HTML | Render delivery structure cards |
| `_type_matrix_rows()` | file type counts | table rows | Render file type matrix |
| `_key_view_rows()` | file type counts | checklist rows | Show key view presence and counts |
| `_attention_summary()` | file type counts, scan issues | status + notes | Build compact unknown/missing/issue attention summary |
| `_simple_note_list()` | note strings | HTML list | Render attention notes |
| `_parser_summary_rows()` | parser manifest | table rows | Summarize parser result status counts |
| `_parser_detail_rows()` | parser manifest | detail rows | Render parser file-level details, capped by limit |
| `_issue_rows()` | scan issues | table rows | Render scan warnings/errors/manual review items |
| `_file_rows()` | inventory files | file rows | Render folded full file inventory |

Scan view model rules:

- Scan page answers what this version delivered by type/view.
- Parser information is supporting evidence. Keep it folded unless failed, empty, or requested.
- Release readiness is reference data on this page, not the main conclusion.

### Diff View Model

Source file:

```text
src/lib_guard/render/html_report.py
```

Primary JSON inputs:

```text
diff_meta.json
diff_summary.json
view_diff.json
type_diff.json
release_evidence_diff.json
metadata_review_tasks.json
manual_pairwise_tasks.json
release_readiness_diff.json
diff_issues.json
file_inventory_diff.json
```

Renderer entry:

```text
render_diff_html(diff_dir, out_dir)
```

Helper map:

| Helper | Input | UI output | Responsibility |
|---|---|---|---|
| `_summary_count()` | diff summary + key aliases | integer | Read normalized count fields with fallback keys |
| `_diff_view_rows()` | `view_diff.json` | table rows | Render required/optional view changes |
| `_diff_type_rows()` | `type_diff.json` | table rows | Render file type count/structure changes |
| `_release_evidence_rows()` | `release_evidence_diff.json` | table rows | Render README/release note/waiver evidence changes |
| `_metadata_rows()` | `metadata_review_tasks.json` | table rows | Render metadata-only review tasks for DB/GDS/OAS/etc. |
| `_pairwise_summary_rows()` | `manual_pairwise_tasks.json` | summary rows | Group manual pairwise tasks by type/priority |
| `_pairwise_detail_rows()` | `manual_pairwise_tasks.json` | command detail rows | Show pairwise commands and old/new file pairs |
| `_diff_issue_rows()` | `diff_issues.json` | issue rows | Render blocker/warning/manual review items |
| `_file_diff_rows()` | `file_inventory_diff.json` | folded rows | Provide low-level file evidence only as traceability |

Diff view model rules:

- Diff page must lead with structure change, not raw changed files.
- Verilog/LEF/Liberty/CDL/SDC/UPF/CPF require domain-level pairwise review when needed.
- DB/GDS/OAS and other binary artifacts are metadata-only unless an external pairwise tool is provided.
- Release note, waiver, README, and doc changes are release evidence changes, not ordinary text diff.

### Release View Model

Source file:

```text
src/lib_guard/render/release_report.py
```

Primary input:

```text
release_postcheck.json or postcheck mapping returned by release verify
```

Renderer entries:

```text
render_release_html(postcheck, out_dir)
render_release_html_from_json(postcheck_json, out_dir)
```

Helper map:

| Helper | Input | UI output | Responsibility |
|---|---|---|---|
| `_status_class()` | status string | CSS class | Map release status to badge style |
| `_badge()` | status value | badge HTML | Render release/link status badge |
| `_href()` | path | href string | Convert file paths to clickable links |
| `_link()` | label + path | link HTML | Render evidence links |
| `_table()` | headers + rows | table HTML | Render release tables |
| `_metric()` | label/value/status | metric card HTML | Render release overview metrics |
| `_counts_text()` | count mapping | compact count text | Summarize file type/source counts |
| local `library_rows` builder | `postcheck.libraries[]` | table rows | Render expected vs linked files per library |
| local `issue_rows` builder | `postcheck.issues[]` | table rows | Render missing/broken/mismatch release issues |
| local `evidence_rows` builder | manifest/link/postcheck paths | evidence rows | Render release evidence files |

Release view model rules:

- Release report is file-level link/copy verification.
- It should show manifest, link result, postcheck, expected files, linked files, broken links, mismatches, and extra files.
- It should not become policy editing or catalog discovery UI.

### Console Compatibility View Model

Source file:

```text
src/lib_guard/render/control_console.py
```

Primary input:

```text
scan_dir
```

Renderer entry:

```text
render_console(scan_dir, out_dir, config_dir=None)
```

Helper map:

| Helper/source | Input | UI/output | Responsibility |
|---|---|---|---|
| `build_config_view()` from `control_data.py` | config directory | `data/config_view.json` | Export config evidence for compatibility |
| `build_review_items()` from `control_data.py` | scan dir + config dir | `data/review_items.json` | Export review items for compatibility |
| `build_recommended_actions()` from `control_data.py` | review items + scan dir | `data/recommended_actions.json` | Export suggested actions for compatibility |
| `render_scan_html()` | scan dir | `index.html` | Reuse Scan review page as the real UI |
| `_redirect_page()` | legacy page name | legacy redirect HTML | Redirect old console pages to `index.html` |

Console view model rules:

- `control_console.py` is a compatibility wrapper.
- Do not add new product sections here. Add real Scan UI changes in `html_report.py`.

### Shared Theme And Component Layer

Source file:

```text
src/lib_guard/render/product_theme.py
```

This file owns reusable UI primitives:

| Function | Role |
|---|---|
| `page_shell()` | Full HTML document shell, shared CSS/JS, nav |
| `panel()` | Standard visible section |
| `collapsible_panel()` | Folded evidence/detail section |
| `product_summary()` | Metric card group |
| `evidence_grid()` | Evidence link cards |
| `table()` | Basic table |
| `filterable_table()` | Table with client-side filtering |
| `badge()` | Shared status badge |
| `action_bar()` | Link/action button row |

Keep visual polish, spacing, color, and component behavior here when the change should apply across Catalog/Scan/Diff.

Rule for future work:

- If a field is only for display wording, grouping, badge color, or table layout, keep it in the renderer/view-model layer.
- If a field changes parser output, scan status, diff meaning, release policy, or JSON schema, update data/rule code and contract docs first.
- If the same view-model logic is reused by two or more renderers, extract a small helper module before adding another copy.

Project Memory Refresh classification:

| Category | Conclusion |
|---|---|
| Stable conclusion | View model currently lives inside renderer helper functions, not in an independent package |
| Stable conclusion | Catalog/Scan/Diff/Release each have different review responsibilities and should not be merged into one page |
| Stable conclusion | Shared visual components belong in `product_theme.py` |
| Temporary exploration | A future `render/view_models.py` may be useful if helper duplication grows |
| Not recommended now | Creating a broad `src/lib_guard/view_model/` package before repeated duplication appears |

## Renderer Inputs

### Catalog HTML

Entry command:

```powershell
$env:PYTHONPATH='src'
$py='C:\Users\Polaris\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
& $py -m lib_guard.cli catalog render --catalog <work>\catalog\catalog.json --out <work>\catalog\html
```

Primary input:

```text
<work>/catalog/catalog.json
```

Important fields:

```text
libraries[].library_id
libraries[].library_name
libraries[].versions[]
versions[].version_id
versions[].version_key
versions[].stage
versions[].raw_path
versions[].scan.scan_dir
versions[].scan.scan_html
versions[].diff.adjacent_diff_html
versions[].release.release_html
versions[].manual_review
versions[].lineage
```

Primary outputs:

```text
<work>/catalog/html/index.html
<work>/catalog/html/libraries/<library>.html
```

### Scan HTML

Entry command:

```powershell
& $py -m lib_guard.cli render --scan <scan_dir> --out <report_dir>\scan_html
```

Primary inputs:

```text
<scan_dir>/scan_meta.json
<scan_dir>/file_inventory.json
<scan_dir>/parser_manifest.json
<scan_dir>/scan_issues.json
<scan_dir>/summary/dashboard_summary.json
<scan_dir>/summary/release_readiness.json
```

Primary outputs:

```text
<report_dir>/scan_html/index.html
<report_dir>/scan_html/scan_report.html
```

### Diff HTML

Entry command:

```powershell
& $py -m lib_guard.cli diff render --diff <diff_dir> --out <diff_dir>\..\diff_html
```

Primary inputs:

```text
<diff_dir>/diff_meta.json
<diff_dir>/diff_summary.json
<diff_dir>/view_diff.json
<diff_dir>/type_diff.json
<diff_dir>/release_evidence_diff.json
<diff_dir>/metadata_review_tasks.json
<diff_dir>/manual_pairwise_tasks.json
<diff_dir>/release_readiness_diff.json
<diff_dir>/diff_issues.json
<diff_dir>/file_inventory_diff.json
```

Primary output:

```text
<diff_html_dir>/index.html
```

### Release HTML

Entry command:

```powershell
& $py -m lib_guard.cli release verify --manifest <release_manifest.json> --release-root <release_area> --html-out <release_html_dir>
```

Primary input:

```text
release_postcheck.json or the postcheck object produced by release verify
```

Important fields:

```text
release_id
summary
libraries[]
issues[]
manifest_path
link_result_path
postcheck_path
```

Primary output:

```text
<release_html_dir>/index.html
```

## Handoff Checklist

Before giving UI work to another person or AI agent, provide:

1. The source files listed in `UI Source Files`.
2. One representative `catalog.json`.
3. One representative `scan_dir`.
4. One representative `diff_dir`.
5. One representative `release_postcheck.json` or release run directory.
6. The expected generated HTML paths.
7. A clear statement of whether the task is UI-only or data/rule-changing.

## Verification

For UI-only changes:

```powershell
$env:PYTHONPATH='src'
$py='C:\Users\Polaris\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'

& $py -m py_compile src\lib_guard\render\catalog_report.py src\lib_guard\render\html_report.py src\lib_guard\render\release_report.py src\lib_guard\render\product_theme.py src\lib_guard\render\control_console.py
& $py -m lib_guard.cli catalog render --catalog <work>\catalog\catalog.json --out <work>\catalog\html
```

For data/rule changes that affect UI inputs:

```powershell
& $py -m unittest discover -s src\lib_guard\test -p 'test*.py'
```

## Known Follow-Up

The renderer-local view-model helpers are acceptable for the current size.

If Catalog, Scan, and Diff begin sharing more grouping logic, create a small view-model layer such as:

```text
src/lib_guard/render/view_models.py
```

Do not create it until there is real duplication across pages.
