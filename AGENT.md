# lib_guard Agent Rules

## Mode

This project is now in Engineering Mode.

Use MVP Mode only for isolated experiments under `work/` or one-off validation scripts. Production code under `src/lib_guard` should keep clear source-of-truth boundaries.

## Source Of Truth

- Catalog asset state: `src/lib_guard/catalog/`
- Scan file inventory and parsing: `src/lib_guard/scan/`
- Format parsers: `src/lib_guard/scan/parsers/`
- Summary aggregation: `src/lib_guard/summary/`
- Structural diff: `src/lib_guard/diff/`
- Package classification and assembly: `src/lib_guard/package/`
- Release manifests and file-level link/verify: `src/lib_guard/release/`
- HTML/UI rendering: `src/lib_guard/render/`
- CLI parser wiring: `src/lib_guard/cli.py`
- CLI command handlers: `src/lib_guard/cli_commands/`
- Generated output: `work/`, `reports/`, scan/diff/release HTML

Generated HTML is a preview artifact. Do not edit generated HTML as source.

## UI Boundary

UI work may change:

- `src/lib_guard/render/`
- renderer-facing view-model helpers
- HTML text, layout, CSS, lightweight JS in renderer code

UI work must not change parser behavior, validation policy, summary metrics, status definitions, or raw JSON schema unless the user explicitly asks for a data contract change.

## Data Boundary

Data/rule work may change:

- scanner, parser, classifier, policy, state/cache
- summary builders and readiness checks
- diff/package/release logic
- configs and focused tests

Data/rule work should not redesign HTML layout unless it needs to expose a new field.

## Documentation Rule

Do not rewrite long-term docs after every small change.

Update docs only when the user explicitly asks for workflow/documentation consolidation, or when a repeated temporary rule becomes stable.

## Verification

Prefer:

```powershell
$env:PYTHONPATH='src'
$py='C:\Users\Polaris\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
& $py -m py_compile <changed python files>
& $py -m unittest discover -s src\lib_guard\test -p 'test*.py'
```

For UI/report changes, also regenerate a demo HTML under `work/` and inspect the output path.
