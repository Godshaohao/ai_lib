Status: current

# Scripts Manifest

| Path | Status | Role |
| --- | --- | --- |
| `scripts/lg.csh` | current | csh wrapper for `lib_guard.short_cli` |
| `scripts/lg_complete.csh` | current | csh/tcsh alias; tcsh-only static completion helper for `lg.csh` |
| `scripts/lg.ps1` | current | PowerShell wrapper for `lib_guard.short_cli` |
| `scripts/lg.cmd` | current | Windows cmd wrapper for `lib_guard.short_cli` |
| `scripts/validate_version_detail_browser.cjs` | current | 使用本地 Chrome/Chromium 对生成的 Version Detail 做截图和交互冒烟验收 |

The current scripts are thin wrappers or shell helpers only. Product behavior
belongs in `src/lib_guard/cli.py`, `src/lib_guard/short_cli.py`, and
`src/lib_guard/cli_commands/`.
