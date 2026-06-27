# ai_lib / lib_guard

`lib_guard` is a catalog-driven review toolkit for IC library and IP delivery.
It discovers raw delivery trees, scans selected versions, compares version
updates, renders review HTML, and prepares release evidence.

## Current Workflow

```text
Catalog -> Library Workspace -> Version Review -> Comparison Review -> File Diff -> Release
```

- Catalog is the asset map and report hub.
- Library Workspace shows the version timeline for one library.
- Version Review combines release notes, scan evidence, parser summaries,
  count-only/corner summaries, readiness, and embedded diff evidence.
- Comparison Review shows structural changes between a selected base and update.
- File Diff is a focused downstream review for selected files, not a progress
  scoreboard.
- Review Gate records only real blockers and owner accept/waive decisions. It is
  not a multi-department approval workflow.
- Release commands use manifest-driven file-level symlink by default and build
  link/verify evidence only after scan and comparison evidence is available.

The normal daily interface is the short command wrapper in `scripts/lg.csh`,
`scripts/lg.ps1`, or `scripts/lg.cmd`. The lower-level `python -m lib_guard.cli`
entry remains available for debugging and automation.

## Repository Map

```text
configs/                 Current catalog and release policies
docs/                    Current documentation and archived migration notes
scripts/                 Thin user-facing wrappers
examples/                Copyable action/file examples
src/lib_guard/           Product source
src/lib_guard/test/      Active automated tests
tests/                   Integration fixtures and repository-level notes
work/                    Generated local output, not source of truth
```

Historical migration notes and workflow-pack material live under
`docs/archive/`. They are not part of the current operating path.

## Common csh Commands

```csh
setenv PROJ /path/to/ai_lib/repo
setenv WORK $PROJ/work/review
setenv RAW  /path/to/raw_delivery

$PROJ/scripts/lg.csh init $WORK --raw-root $RAW --library-type ip
$PROJ/scripts/lg.csh cat --full --with-evidence
$PROJ/scripts/lg.csh scan <LIBRARY> <VERSION>
$PROJ/scripts/lg.csh cmp <LIBRARY> <VERSION> --base <BASE_VERSION> --scan-if-missing
$PROJ/scripts/lg.csh cmp <LIBRARY> <VERSION> --base <BASE_VERSION> --rescan
$PROJ/scripts/lg.csh fd <LIBRARY> <VERSION> <REL_PATH> --base <BASE_VERSION> --type <FILE_TYPE>
$PROJ/scripts/lg.csh rv-check <LIBRARY> <VERSION> --gate current
$PROJ/scripts/lg.csh rv-accept <LIBRARY> <VERSION> --item <ITEM_ID> --by <USER> --reason "..."
$PROJ/scripts/lg.csh rel <LIBRARY> <VERSION> --check-first --link-mode symlink
```

If `$WORK/lib_guard.yml` exists, `lg.csh` will use it automatically. You can
also point at a config explicitly:

```csh
setenv LIB_GUARD_CONFIG $WORK/lib_guard.yml
```

## Low-Level Commands

```bash
PYTHONPATH=src python -m lib_guard.cli catalog scan --root "$RAW" --out "$WORK/catalog" --render --html-out "$WORK/catalog/html" --policy configs/catalog_policy.json
PYTHONPATH=src python -m lib_guard.cli run-batch --catalog "$WORK/catalog/catalog.json" --mode candidate --workdir "$WORK" --parse-jobs 8
PYTHONPATH=src python -m lib_guard.cli compare --catalog "$WORK/catalog/catalog.json" --library <LIBRARY> --new <VERSION> --base <BASE_VERSION> --workdir "$WORK"
PYTHONPATH=src python -m unittest discover -s src/lib_guard/test -p "test*.py"
```

## Documentation

- [Documentation index](docs/index.md)
- [Architecture](docs/architecture.md)
- [User guide](docs/user_guide.md)
- [CLI reference](docs/cli_reference.md)
- [Data contract](docs/data_contract.md)
- [Review gate](docs/review_gate.md)
- [Test plan](docs/test_plan.md)
- [Deprecation policy](docs/deprecation_policy.md)
