Status: current

# CLI 参考

## 日常短命令

| 命令 | 作用 |
| --- | --- |
| `init` | 创建 workspace 配置 |
| `library add` | 已知库根时直接加入人工确认 registry |
| `library discover` / `library accept` / `library apply` | 发现候选库、合并人工确认、生成正式 library map |
| `library override` | 人工确认版本 stage/base/package 关系 |
| `cat` | 刷新 catalog/HTML；加 `--update-detail` 时刷新版本详情更新证据 |
| `scan` | 扫描一个版本或一批版本 |
| `cmp` | 手动对比更新版本和指定 base 版本 |
| `fd` | 运行单文件两两 diff |
| `rv check` / `rv list` | 查看 Review Gate 状态 |
| `rv accept` / `rv waive` | 记录 owner 决策 |
| `rel` | 执行 release check/link/verify 规划 |
| `action` | 执行一个 workspace action 文件 |

旧短命令 `catalog/diff/file-diff/release/refresh/override/rv-check` 仅作为兼容改写保留，
不再出现在推荐 help 中。

## 常用示例

```csh
lg.csh library add vendor_A.openroad_platform.openroad_asap7 --root /path/to/vendor_A/openroad_asap7
lg.csh library discover
gvim $WORK/config/library_candidates/latest.tsv
lg.csh library accept
lg.csh library apply
lg.csh library list
lg.csh library list vendor_A.openroad_platform.openroad_asap7 --versions
lg.csh cat --with-evidence
lg.csh library override ucie stable_20250608 --stage stable --base stable_20250601
lg.csh scan ucie stable_20250608
lg.csh scan ucie stable_20250608 --parse-file-types lef,cdl
lg.csh scan ucie stable_20250608 --hash-policy full
lg.csh cat ucie --update-detail
lg.csh cmp ucie stable_20250608 --base stable_20250601 --scan-if-missing
lg.csh fd ucie stable_20250608 lef/ucie.lef --base stable_20250601 --type lef
lg.csh rv check ucie stable_20250608 --gate current
lg.csh rv accept ucie stable_20250608 --item metadata.db.changed:db/ucie.db --by lib_owner --reason "DB hash change accepted for current."
lg.csh action ucie
lg.csh rel ucie stable_20250608
```

## `cat --update-detail` 和 `cmp` 的边界

## `scan` 的边界

`scan` 只有一种用户态动作：生成当前版本的 scan evidence。扫描深度由策略参数控制，
不是由多个 mode 控制。

| 策略参数 | 作用 |
| --- | --- |
| `--parse-file-types lef,cdl` | 只让指定类型进入 parser 任务 |
| `--parse-exclude-file-types verilog,liberty,spef` | 从 parser 任务里排除指定类型 |
| `--hash-policy smart` | 默认策略，小文件 hash，大型 EDA 文件按 metadata 处理 |
| `--hash-policy full` | 专家/调试场景，强制计算内容 hash |
| `--parse-jobs 8` | parser 并行度 |

新命令保持 `scan` 这一种用户态动作，用策略参数表达扫描深度。

`cat <LIBRARY> --update-detail` 是版本详情页更新证据的日常入口。默认行为是：

- 优先使用 `current_effective`。
- 没有当前有效库时使用 `previous_effective`。
- 找不到可信 base 时让状态进入 `NEEDS_BASE_CONFIRM`，不伪装成真实 diff。

`adjacent` 只用于手动 compare 场景，必须显式指定：

```csh
lg.csh cat ucie --update-detail --mode adjacent
lg.csh cmp ucie stable_20250608 --mode adjacent --scan-if-missing
```

`cmp` 是手动比较工具，适合指定 `--base`、调试 adjacent/cumulative，或生成独立
Comparison Review。

## 文件类型 lane

默认 File Diff 推荐只覆盖 `DEFAULT_FILE_DIFF_TYPES`，避免把大文件、多文件集合和
二进制工艺视图当作普通文本 diff：

| Lane | 类型 | 默认行为 |
| --- | --- | --- |
| `DEFAULT_FILE_DIFF_TYPES` | `lef`, `cdl`, `spice`, `sp`, `sdc`, `upf`, `cpf`, `waiver`, `ibis`, `pwl`, `snp`, `touchstone`, `cpm` | 可以生成推荐 File Diff |
| `SUMMARY_ONLY_TYPES` | `verilog`, `systemverilog`, `liberty`, `lib`, `spef` | 只做 summary/count/corner/metadata，不默认生成 fd command |
| `BINARY_METADATA_ONLY_TYPES` | `db`, `gds`, `oas`, `layout`, `milkyway`, `ndm` | 只做二进制 metadata/hash/路径证据，不默认生成 fd command |

默认 Version Review / pairwise 推荐只会展开 `DEFAULT_FILE_DIFF_TYPES`。这条默认线
适合小到中等规模、可直接阅读的文本视图；`verilog`、`liberty`、`spef`、`db`、
`gds`、`oas` 等 lane 不会自动生成 `fd` 命令。

### 专家 opt-in：`fd --force-large`

`SUMMARY_ONLY_TYPES` 和 `BINARY_METADATA_ONLY_TYPES` 只能在人工确认必要时手动运行。
不加 `--force-large` 会报错，并提示该类型默认走 summary-only 或 metadata-only 审查。

```csh
lg.csh fd ucie patch_20260630 rtl/top.v --type verilog --force-large
lg.csh fd ucie patch_20260630 timing/top.lib --type liberty --force-large
lg.csh fd ucie patch_20260630 db/ucie.db --type db --force-large
```

这类命令表示 owner/专家明确接受大文件、集合文件或二进制 metadata lane 的人工审查
成本；默认推荐列表仍必须遵守安全 lane。`--dry-run` 打印的是可直接执行的底层
`python -m lib_guard.cli file-diff ...` 命令，不会把短命令内部的 opt-in 审计标记当作
底层 CLI 参数输出。

## 配置默认值

- `lg.csh init` 写出 workspace 级 `lib_guard.yml`。
- 默认 workspace 路径和项目 policy 文件名集中在 `src/lib_guard/project_config.py`。
- 项目 policy 在 `configs/`。
- workspace review/action 文件在 `$WORK/config/` 和 `$WORK/actions/`。
- scan 策略可以写在 `lib_guard.yml`，短命令会自动传给底层 scan：

```yaml
hash_policy: smart
parse_file_types: lef,cdl
parse_exclude_file_types: verilog,liberty,spef
parse_jobs: 8
```

`mode: scan` 只保留为兼容字段；日常不要通过 mode 区分扫描深度。

## Help 命令

```bash
PYTHONPATH=src python -m lib_guard.cli --help
PYTHONPATH=src python -m lib_guard.short_cli --help
scripts/lg.csh --help
```

`lg.csh --help` 是面向日常用户的入口。`python -m lib_guard.cli --help`
是底层自动化/调试入口。

详见 [命令入口分层](command_surface.md)。
