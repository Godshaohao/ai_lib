# ai_lib / lib_guard

`lib_guard` is a catalog-driven library asset management toolkit for IC library/IP delivery review.

The current workflow focuses on:

- Discovering libraries and version chains from RAW delivery trees.
- Running lightweight catalog refresh before deeper scan work.
- Scanning selected versions for inventory, required views, documentation evidence, readiness, and parser quality.
- Comparing adjacent or selected versions with structural diff reports.
- Supporting manual pairwise file diff for LEF, Liberty, Verilog, SDC, UPF, CPF, CDL, SPEF, and related text views.
- Preparing release checks and file-level release link/verify manifests.
- Rendering catalog, scan, diff, and release HTML for review.

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
& $PY -m unittest discover -s src\lib_guard\test -p 'test*.py'
```

For shell wrappers, see `scripts/lg.csh`, `scripts/lg.ps1`, and `scripts/lg.cmd`.
