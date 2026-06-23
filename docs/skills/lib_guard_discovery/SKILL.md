---
name: lib-guard-discovery
description: Use when modifying lib_guard catalog discovery, library_map.yml, scan/diff/file-diff/release path resolution, or raw library directory handling. Prevents hardcoding raw/<library>/<version> and requires catalog/resolver based path resolution.
---

# lib_guard Discovery Boundary

`raw_root` is only the entry point for discovery. It is not a library root and must not be treated as `raw/<library>/<version>`.

Use this resolution chain:

```text
raw_root -> library_root -> version_root
```

## Required Rules

- Prefer `library_map.yml` for known production libraries.
- Store canonical identity in catalog as `library_id` / `library_name`; user commands may use aliases.
- Scan, diff, file-diff, and release must read `raw_path`, `library_root`, and relationship fields from catalog.
- Short CLI wrappers may orchestrate commands, but must not infer physical raw directory structure.
- Pattern fallback is allowed only as discovery input. Runtime workflows still use catalog paths.

## Anti-Patterns

- Do not join paths as `raw_root / library / version`.
- Do not make diff or release rediscover library directories.
- Do not encode vendor/category assumptions inside renderers.
- Do not let UI convenience fields become source-of-truth path rules.

## Verification

Run catalog tests after discovery changes:

```bash
python -m unittest src.lib_guard.test.test_v5_catalog
```

For csh workflow changes, dry-run the short CLI:

```csh
$PROJ/scripts/lg.csh --config $WORK/lib_guard.yml --dry-run scan <alias> <version>
$PROJ/scripts/lg.csh --config $WORK/lib_guard.yml --dry-run diff <alias> <version>
```
