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

Desktop UI command policy:

- Catalog command examples use `cat`, `scan`, `cmp`, and `rel`.
- Scan "next action" uses `cmp ... --scan-if-missing`, not the older `lg diff ...` text.
- Selected Diff and Effective Compare expose File Diff commands only as focused recommendations using `fd ... --base ... --type ...`.
- Generated HTML should not show the old completion wording `File Diff 2/5` or `done/total`.
- Generated HTML should not expose low-level `python -m lib_guard.cli file-diff ...` commands except inside JSON/debug evidence.

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

Preferred short commands:

```csh
setenv PROJ /path/to/ai_lib
setenv WORK $PROJ/work/review
setenv RAW  /path/to/raw_delivery

$PROJ/scripts/lg.csh init $WORK --raw-root $RAW
cd $WORK

$PROJ/scripts/lg.csh cat
$PROJ/scripts/lg.csh scan <LIBRARY> <VERSION>
$PROJ/scripts/lg.csh cmp <LIBRARY> <VERSION> --base <BASE_VERSION> --scan-if-missing
$PROJ/scripts/lg.csh fd <LIBRARY> <VERSION> lef/<FILE>.lef --base <BASE_VERSION>
$PROJ/scripts/lg.csh fd <LIBRARY> <VERSION> model/<FILE>.ibs --base <BASE_VERSION>
$PROJ/scripts/lg.csh fd <LIBRARY> <VERSION> touch/<FILE>.s2p --type snp --base <BASE_VERSION>
$PROJ/scripts/lg.csh rel <LIBRARY> <VERSION> --check-first
```

Short aliases are intended for daily csh use:

```text
cat -> catalog
cmp -> diff
fd  -> file-diff
rel -> release
```

Use `--dry-run` before expensive work:

```csh
$PROJ/scripts/lg.csh --dry-run cmp <LIBRARY> <VERSION> --base <BASE_VERSION>
$PROJ/scripts/lg.csh --dry-run fd <LIBRARY> <VERSION> waiver/<FILE>.waiver --base <BASE_VERSION>
```

The short CLI still resolves paths from `catalog.json`; do not pass paths relative to `$RAW`.
`file-diff` relpaths are relative to the selected version root and support:
`lef`, `liberty`, `verilog`, `cdl`, `sdc`, `upf`, `cpf`, `spef`, `db`, `waiver`, `ibis`, `pwl`, `snp`, and `cpm`.

Low-level commands remain useful for debugging:

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

## Latest Desktop UI Verification

The desktop review smoke set covers:

```text
catalog/html/index.html
scan_html/index.html
diff_html/index.html
effective_E3.html
compare_E2_vs_E3/index.html
release_preview/index.html
release_html/index.html
```

The current audit checks for:

- no stale `lg diff`, `lg.csh file-diff`, or `python -m lib_guard.cli file-diff` in user-facing HTML;
- no placeholder/debug copy such as `TODO`, `TBD`, `FIXME`, `Lorem ipsum`, `File Diff 2/5`, or `done/total`;
- desktop layout readability at 1440 px width, including long path/version truncation and scrollable tables.
