---
name: release-manifest-builder
description: Use when selected library versions have already been reviewed and Codex needs to build or check a file-level release_manifest.json for release_area layouts such as rtl, lef, lib, gds, oas, doc, db, cdl, and constraints.
---

# Release Manifest Builder

## Core Principle

Build a file-level release manifest only after the user has selected versions for release. The manifest is an orchestration artifact, not a release approval decision.

The target layout is view-level:

```text
release_area/
  rtl/
  lef/
  lib/
  db/
  gds/
  oas/
  cdl/
  sdc/
  upf/
  cpf/
  doc/
```

Do not introduce `current/<library>/...` or `<library>/...` levels in the formal release area.

## Inputs

Accept any of:

- `catalog.json`
- Selected library/version keys.
- Existing scan directories.
- Manual version list.
- Desired `release_root`.
- Release alias or release id for audit naming only.

## Manifest Build Steps

1. Read selected versions from catalog or user input.
2. Resolve each version to its scan result and raw source path.
3. Read `file_inventory.json` and parser evidence when available.
4. Map each file to a release target folder by view or file type.
5. Preserve source view-relative paths when they already start with `rtl`, `lef`, `lib`, `gds`, `oas`, `doc`, and similar view folders.
6. Check target path collisions before generating commands.
7. Flag ambiguous names such as repeated `README.md`, `release_note.txt`, or `block.lef`.
8. Write or propose `release_manifest.json`.
9. Generate dry-run, apply, overwrite, and verify commands.

## File Type Mapping

Use this default mapping unless project policy overrides it:

| File Type | Release Folder |
| --- | --- |
| verilog | `rtl` |
| lef | `lef` |
| liberty | `lib` |
| db | `db` |
| gds | `gds` |
| oas | `oas` |
| cdl/spice | `cdl` |
| sdc | `sdc` |
| upf | `upf` |
| cpf | `cpf` |
| doc/release_note/waiver | `doc` |
| package/manifest/checksum | `doc` or policy-defined evidence folder |

## Required Output

Always return five sections:

1. Conclusion
2. Evidence
3. Risks
4. Recommended Commands
5. Manual Confirmation

Recommended command pattern:

```bash
python -m lib_guard.cli release manifest-template \
  --catalog "$WORK/catalog/catalog.json" \
  --release-root "$WORK/release_area" \
  --alias current \
  --out "$WORK/release_runs/PD_LIB_CURRENT_YYYYMMDD/release_manifest.json"

python -m lib_guard.cli release link \
  --manifest "$WORK/release_runs/PD_LIB_CURRENT_YYYYMMDD/release_manifest.json" \
  --link-mode copy

python -m lib_guard.cli release link \
  --manifest "$WORK/release_runs/PD_LIB_CURRENT_YYYYMMDD/release_manifest.json" \
  --link-mode copy \
  --apply \
  --overwrite

python -m lib_guard.cli release verify \
  --manifest "$WORK/release_runs/PD_LIB_CURRENT_YYYYMMDD/release_manifest.json" \
  --render
```

## Collision Policy

Treat target collisions as blocking until manually resolved.

Examples:

- Two selected libraries both map to `release_area/doc/README.md`.
- Two LEF files from different raw roots both map to `release_area/lef/block.lef`.
- A generated target path would overwrite an unrelated existing release file.

When collision exists, propose a deterministic rename or policy rule, but do not apply it without confirmation.

## Execution Policy

Default to dry-run command generation.

May execute:

- Manifest inspection.
- Dry-run `release link`.
- `release verify` on an already-applied release.

Ask before executing:

- `release link --apply`
- `--overwrite`
- Any operation that modifies `release_area`.

## Boundaries

This skill does not choose which version should be released. It does not judge scan quality. It does not bypass manual approval. It does not auto-apply release changes.

## Common Mistakes

- Building a release tree with `current/ucie/...` under the formal release area.
- Linking whole library folders instead of file-level targets.
- Ignoring target path collisions.
- Treating alias as a directory layout requirement instead of audit metadata.
