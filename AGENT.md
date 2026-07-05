# lib_guard Agent Rules

## Mode

This project is in Engineering Mode. Production changes should preserve source
of truth boundaries and include focused verification.

## Source Of Truth

- Catalog state: `src/lib_guard/catalog/`
- Scan inventory and parsing: `src/lib_guard/scan/`
- Format parsers: `src/lib_guard/scan/parsers/`
- Summary aggregation: `src/lib_guard/summary/`
- Structural diff: `src/lib_guard/diff/`
- Package classification and assembly: `src/lib_guard/package/`
- Release manifests and link/verify: `src/lib_guard/release/`
- HTML/UI rendering: `src/lib_guard/render/`
- CLI parser wiring: `src/lib_guard/cli.py`
- CLI handlers: `src/lib_guard/cli_commands/`
- Short wrappers: `scripts/lg.csh`, `scripts/lg.ps1`, `scripts/lg.cmd`

Generated output under `work/`, `reports/`, scan, diff, and release HTML is not
source. Regenerate it instead of editing it directly.

## Boundary Rules

UI work may change renderer code and renderer-facing view models. It should not
change parser behavior, validation policy, summary metrics, status definitions,
or raw JSON schema unless the task explicitly asks for a data contract change.

Data/rule work may change scanner, parser, classifier, policy, state/cache,
summary builders, readiness checks, diff/package/release logic, configs, and
focused tests. It should not redesign HTML layout unless a new field must be
exposed.

## Documentation Rule

Update current docs when workflow, command behavior, data contracts, or
repository structure changes. Do not add historical migration bundles or
workflow-pack copies to the current repository path.

## Verification

Prefer portable commands:

```bash
PYTHONPATH=src python -m py_compile <changed python files>
PYTHONPATH=src python -m unittest discover -s src/lib_guard/test -p "test*.py"
PYTHONPATH=src python -m lib_guard.cli --help
PYTHONPATH=src python -m lib_guard.short_cli --help
```

For UI/report changes, regenerate a demo HTML under `work/` and inspect the
resulting path.
