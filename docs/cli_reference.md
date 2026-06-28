Status: current

# CLI 参考

## 日常短命令

| 命令 | 作用 |
| --- | --- |
| `init` | 创建 workspace 配置 |
| `library discover` / `library apply` | 发现并应用人工确认后的 library map |
| `cat` | 刷新 catalog 和 catalog HTML |
| `override` | 人工确认版本 stage/base/package 关系 |
| `scan` | 扫描一个版本或一批版本 |
| `cmp` | 对比更新版本和 base 版本 |
| `fd` | 运行单文件两两 diff |
| `rv-check` / `rv-list` | 查看 Review Gate 状态 |
| `rv-accept` / `rv-waive` | 记录 owner 决策 |
| `rel` | 执行 release check/link/verify 规划 |
| `action` | 执行一个 workspace action 文件 |

推荐别名只保留：

| 别名 | 原命令 |
| --- | --- |
| `cat` | `catalog` |
| `cmp` | `diff` |
| `fd` | `file-diff` |
| `rel` | `release` |

已经不推荐的旧别名包括：`filediff`、`refresh-diff`、`lib`、`act`、`review`、
`compare`、`rf`。

## 常用示例

```csh
lg.csh library discover
lg.csh library apply
lg.csh cat --with-evidence
lg.csh override ucie stable_20250608 --stage stable --base stable_20250601
lg.csh scan ucie stable_20250608
lg.csh cmp ucie stable_20250608 --base stable_20250601 --scan-if-missing
lg.csh fd ucie stable_20250608 lef/ucie.lef --base stable_20250601 --type lef
lg.csh rv-check ucie stable_20250608 --gate current
lg.csh rv-accept ucie stable_20250608 --item metadata.db.changed:db/ucie.db --by lib_owner --reason "DB hash change accepted for current."
lg.csh action ucie
lg.csh rel ucie stable_20250608 --check-first --link-mode symlink
```

## 配置默认值

- `lg.csh init` 写出 workspace 级 `lib_guard.yml`。
- 默认 workspace 路径和项目 policy 文件名集中在 `src/lib_guard/project_config.py`。
- 项目 policy 在 `configs/`。
- workspace review/action 文件在 `$WORK/config/` 和 `$WORK/actions/`。

## Help 命令

```bash
PYTHONPATH=src python -m lib_guard.cli --help
PYTHONPATH=src python -m lib_guard.short_cli --help
scripts/lg.csh --help
```

`lg.csh --help` 是面向日常用户的入口。`python -m lib_guard.cli --help`
是底层自动化/调试入口。

详见 [命令入口分层](command_surface.md)。
