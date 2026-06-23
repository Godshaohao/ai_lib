# lib_guard Project Index

## Project Status

```text
Project: lib_guard
Mode: Engineering
Current Focus: Catalog-driven library/package management, scan/diff/release evidence, and HTML review pages
Latest Stable Output: catalog -> scan -> diff -> release file-level link workflow
Last Updated: 2026-06-21
```

## Source Map

| Area | Source |
|---|---|
| Agent rules | `AGENT.md` |
| Product scope | `docs/01_product_scope.md` |
| Data and status contract | `docs/02_data_rule_contract.md` |
| Engineering structure and runbook | `docs/03_engineering_delivery.md` |
| UI/report boundary | `docs/04_ui_iteration.md` |
| UI handoff source/context/view-model | `docs/05_ui_handoff.md` |
| Catalog workflow details | `docs/lib_guard_v5_catalog_workflow.md` |
| Current architecture summary | `docs/lib_guard_current_architecture_and_library_management.md` |

## Generated Outputs

Generated scan/diff/release/catalog HTML under `work/` is preview output. The source of truth is code and JSON data under `src/lib_guard`.

## Workflow Pack

The reusable PD agent workflow pack has been merged into this repository in a lib_guard-specific form. Keep generic workflow helpers separate from production lib_guard renderers:

- Production reports: `src/lib_guard/render/`
- Workflow helpers: `scripts/build_ui_context.py`, `scripts/render_dashboard.py`
- Long-term flow docs: `flows/`

## Current Open Questions

| ID | Question | Owner | Status |
|---|---|---|---|
| Q001 | Whether old catalog renderer backup files can be removed permanently | user/dev | open |
| Q002 | Whether shared JSON IO helpers should be extracted into `storage` | dev | open |
