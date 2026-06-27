Status: current

# CLI Reference

Daily aliases:

| Alias | Meaning |
| --- | --- |
| `cat` | catalog refresh and render |
| `scan` | scan one library version or selected batch |
| `cmp` | compare an update against a base |
| `fd` | run pairwise file diff |
| `rel` | run release checks and link/verify planning |

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

