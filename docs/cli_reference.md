Status: current

# CLI Reference

Daily aliases:

| Alias | Meaning |
| --- | --- |
| `cat` | catalog refresh and render |
| `scan` | scan one library version or selected batch |
| `cmp` | compare an update against a base |
| `fd` | run pairwise file diff |
| `rv-check` / `rv-list` | inspect lightweight review gate status |
| `rv-accept` / `rv-waive` | record owner decisions for blocking gate items |
| `rel` | run release checks and manifest-driven symlink link/verify planning |

Examples:

```csh
lg.csh cmp ucie stable_20250608 --base stable_20250601 --scan-if-missing
lg.csh fd ucie stable_20250608 lef/ucie.lef --base stable_20250601 --type lef
lg.csh rv-check ucie stable_20250608 --gate current
lg.csh rv-accept ucie stable_20250608 --item metadata.db.changed:db/ucie.db --by lib_owner --reason "DB hash change accepted for current."
lg.csh rel ucie stable_20250608 --check-first --link-mode symlink
```

`lg.csh review` is still the action-file runner alias. Manual gate decisions use
the `rv-*` commands.

Low-level entry points:

```bash
PYTHONPATH=src python -m lib_guard.cli --help
PYTHONPATH=src python -m lib_guard.short_cli --help
```

Shell wrappers are thin path/config adapters:

```text
scripts/lg.csh
scripts/lg.ps1
scripts/lg.cmd
```
