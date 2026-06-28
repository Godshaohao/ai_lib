Status: current

# Scripts Manifest

| Path | Status | Role |
| --- | --- | --- |
| `scripts/lg.csh` | current | csh wrapper for `lib_guard.short_cli` |
| `scripts/lg.ps1` | current | PowerShell wrapper for `lib_guard.short_cli` |
| `scripts/lg.cmd` | current | Windows cmd wrapper for `lib_guard.short_cli` |
| `docs/archive/workflow_pack/scripts/` | archived | Former workflow helper scripts |

The current scripts are thin wrappers only. Product behavior belongs in
`src/lib_guard/cli.py`, `src/lib_guard/short_cli.py`, and `src/lib_guard/cli_commands/`.

