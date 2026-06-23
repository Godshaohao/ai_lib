# lib_guard Release HTML UI Upgrade Plan

## Scope

This plan updates `src/lib_guard/render/release_report.py` UI only.
Do not change release manifest generation, link/copy behavior, postcheck policy, catalog schema, scan parser, diff generation, or CLI.

## Page Intent

Release HTML should answer:

1. What release area was verified?
2. Did the linked/copied files match the manifest?
3. Which libraries have missing, broken, mismatch, or extra files?
4. Where are the manifest, link result, and postcheck evidence files?
5. What should the reviewer inspect next?

It should not become policy authoring UI, catalog discovery UI, or a final signoff page.

## Target Page Structure

1. **Release Brief / 发布概览**
   - release_id
   - release_root
   - manifest_path
   - link_result_path
   - postcheck_path
   - library_count
   - expected_file_count
   - linked_file_count
   - issue_count

2. **Verification Summary / 校验摘要**
   - Expected files
   - Linked files
   - Missing files
   - Broken links
   - Mismatches
   - Extra files
   - Manual review items

3. **Release Attention / 发布关注**
   - Only show missing / broken / mismatch / extra / manual review issues.
   - Use neutral review wording: `Needs review`, `Missing`, `Mismatch`, `Broken link`.
   - Avoid `approved`, `rejected`, `final signoff`.

4. **Library Verification Table / 库级校验表**
   - One row per library.
   - Columns:
     - Library
     - Expected
     - Linked
     - Missing
     - Broken
     - Mismatch
     - Extra
     - Evidence
   - Do not expand all files by default.

5. **Evidence Drawer / 证据抽屉**
   - Folded by default.
   - Include:
     - release manifest
     - link result
     - postcheck JSON
     - full expected file list
     - full linked file list
     - raw issue table

## Component Use

Reuse shared components from `product_theme.py`:

- `page_shell()`
- `panel()`
- `collapsible_panel()`
- `brief_grid()`
- `tile_grid()`
- `attention_items()`
- `trace_link_list()`
- `table()` / `filterable_table()`
- `badge()`

## Suggested Helpers in release_report.py

```python
def _release_brief_items(postcheck): ...
def _release_summary_tiles(postcheck): ...
def _release_attention_items(postcheck): ...
def _library_verification_rows(postcheck): ...
def _release_trace_links(postcheck): ...
def _full_issue_rows(postcheck): ...
```

## Acceptance

- Page starts with release context, not raw file tables.
- Missing/broken/mismatch/extra files are surfaced before full evidence.
- One row per library by default.
- Full file-level details are folded.
- Manifest/link/postcheck evidence is easy to open.
- Existing `render_release_html()` and `render_release_html_from_json()` entry points remain unchanged.
