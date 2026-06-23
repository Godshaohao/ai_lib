# lib_guard Engineering Delivery

## Architecture Boundary

```text
Scanner    -> src/lib_guard/scan
Parser     -> src/lib_guard/scan/parsers
Validator  -> src/lib_guard/scan/policy, summary/readiness, release/checker
Storage    -> scan state/cache/history/catalog runtime state
Summary    -> src/lib_guard/summary
ViewModel  -> renderer-facing builders and product_theme helpers
Exporter   -> src/lib_guard/render, release manifest/link output, bundle output
```

These are responsibility boundaries, not mandatory directory names. Keep existing names when they are already clear.

## Current Directory Structure

```text
src/lib_guard/
  cli.py     CLI parser wiring only; command behavior lives in cli_commands/
  cli_commands/
            scan/catalog/diff/release/package/render command handlers
  catalog/   catalog discovery, manual overrides, runtime state, catalog CLI model
  scan/      scan main pipeline, file walking, classification, hashing, parser execution
  scan/parsers/
  summary/  aggregate scan/parser evidence into dashboard and release readiness JSON
  diff/     scan output diff and explicit pairwise file diff
  package/  delivery package classification, base binding, snapshot assembly
  release/  release policy, manifest, file-level link, postcheck
  render/   catalog/scan/diff/release HTML renderers and shared product theme
  history/  scan history index
  update/   incremental update helpers
  version/  version graph/index helpers
  test/     unit and workflow tests
```

## CLI Runbook

```powershell
$env:PYTHONPATH='src'
$py='C:\Users\Polaris\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'

& $py -m lib_guard.cli catalog scan --root <raw-root> --out <work/catalog> --library-type ip --render
& $py -m lib_guard.cli run-batch --catalog <catalog.json> --library <name> --mode full --workdir <work> --parse-jobs 4 --console-progress
& $py -m lib_guard.cli compare-batch --catalog <catalog.json> --library <name> --mode adjacent --workdir <work> --only-ready
& $py -m lib_guard.cli release-batch --catalog <catalog.json> --library <name> --release-root <release-root> --apply --overwrite
```

## Debug Rules

- Unknown files must be visible in inventory or issues.
- Parser errors must be written to logs or manifest status.
- Release output must contain manifest/link/postcheck evidence.
- Catalog HTML should link to scan/diff/release evidence instead of duplicating all details.
