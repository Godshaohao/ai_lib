# ai_lib / lib_guard

`lib_guard` is a catalog-driven library asset management toolkit for IC library/IP delivery review.

The current workflow focuses on:

- Discovering libraries and version chains from RAW delivery trees.
- Running lightweight catalog refresh before deeper scan work.
- Scanning selected versions for inventory, required views, documentation evidence, readiness, and parser quality.
- Comparing adjacent or selected versions with structural diff reports.
- Supporting recommended pairwise file diff for LEF, Liberty, Verilog, CDL, SDC, UPF, CPF, SPEF, DB, waiver, IBIS, PWL, SNP, and CPM views.
- Preparing release checks and file-level release link/verify manifests.
- Rendering catalog, scan, diff, file-diff, and release HTML for review.

## Current v5/v6 Review Flow

The current review UI uses a guided navigation model:

```text
Catalog -> Diff Timeline -> Selected Diff -> recommended File Diff
```

- Catalog is the asset map and report hub. It no longer expands direct File Diff commands.
- Selected Diff is the review surface for one comparison. It shows structural domains, release evidence changes, and the "key File Diff recommendation" queue.
- File Diff is a recommendation model, not a completion scoreboard. The UI no longer shows `File Diff 2/5` or `done/total`.
- Large or ambiguous comparisons first ask the reviewer to confirm base/comparison context. They do not generate a full File Diff command batch.
- File Diff HTML shows structured field changes, raw text fallback, and best-effort source location from parser evidence.

Key v6 parser/diff additions:

- Liberty now extracts `is_macro`, `is_pad`, and cell attribute lines.
- SDC/UPF keep command counts and add semantic fields for clocks, uncertainty, loads, power domains, supplies, isolation, retention, and level shifters.
- Waiver, IBIS, PWL, SNP/Touchstone, and CPM are available through scan parsers and the pairwise `file-diff` CLI.
- DB remains metadata-only unless an external semantic parser is added.

## Workflow Pack Integration

This repository has absorbed the useful parts of `pd_agent_workflow_pack`:

- `AGENT.md` defines the agent working rules and source-of-truth boundaries.
- `docs/00_index.md` is the project navigation entry.
- `docs/01_product_scope.md` captures lib_guard-specific product scope and users.
- `docs/02_data_rule_contract.md` through `docs/06_manual_test_flow.md` document data, engineering, UI, handoff, and manual testing.
- `flows/` keeps the reusable MVP, engineering, memory refresh, and UI iteration flows.
- `scripts/build_ui_context.py` and `scripts/render_dashboard.py` remain generic workflow helpers for CSV-based UI experiments.

Generated HTML under `work/` or `reports/` is output, not source of truth.

## Common Commands

```powershell
$env:PYTHONPATH='src'
$PY='C:\Users\Polaris\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'

& $PY -m lib_guard.cli catalog scan --root <RAW_ROOT> --out <WORK>\catalog --render --html-out <WORK>\catalog\html --policy configs\catalog_policy.json
& $PY -m lib_guard.cli run-batch --catalog <WORK>\catalog\catalog.json --mode signature --workdir <WORK> --parse-jobs 8
& $PY -m lib_guard.cli compare --catalog <WORK>\catalog\catalog.json --library <LIBRARY> --new <VERSION> --workdir <WORK>
& $PY -m lib_guard.cli file-diff sdc --old <OLD.sdc> --new <NEW.sdc> --out <WORK>\file_diff\sdc_case
& $PY -m unittest discover -s src\lib_guard\test -p 'test*.py'
```

For shell wrappers, see `scripts/lg.csh`, `scripts/lg.ps1`, and `scripts/lg.cmd`.
