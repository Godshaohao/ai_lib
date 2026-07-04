# ai_lib / lib_guard

`lib_guard` 是面向 IC library / IP 交付的 catalog 驱动审查工具。它负责发现
raw delivery、扫描版本、生成结构化更新证据、渲染 HTML，并在 release 前准备
可追溯证据。

## 当前主流程

```text
库目录 -> 版本审查 -> Release
```

- 库目录是库资产地图和报告入口。
- 版本审查是普通 reviewer 的主页面，包含 release notes、scan evidence、
  parser summary、count/corner summary、readiness，以及相对当前有效库的更新证据。
- Release 使用 manifest 驱动的文件级 symlink，只有 scan/diff/review gate 证据满足
  条件后才进入 link/verify。
- Force release 入口保留，但必须提供 `--force-reason`，并写入
  `release_override.json` 审计绕过的 gate/check 证据。
- 库工作台是高级账本，用来查看单库 timeline、effective 组合和历史报告。
- Comparison Review 是手动 compare / debug 入口，不是普通用户查看更新详情的唯一入口。
- File Diff 只用于推荐下钻的关键文件，不是全量完成度 scoreboard。
- Review Gate 只记录真实 blocker 和 owner accept/waive 决策，不是多部门审批流。

日常使用优先走短命令：`scripts/lg.csh`、`scripts/lg.ps1`、`scripts/lg.cmd`。
底层 `python -m lib_guard.cli` 入口保留给自动化、调试和测试。

## Repository Map

```text
configs/                 Current catalog and release policies
docs/                    Current documentation and archived migration notes
scripts/                 Thin user-facing wrappers
examples/                Copyable action/file examples
src/lib_guard/           Product source
src/lib_guard/test/      Active automated tests
tests/                   Integration fixtures and repository-level notes
work/                    Generated local output, not source of truth
```

Historical migration notes and workflow-pack material live under
`docs/archive/`. They are not part of the current operating path.

## 常用 csh 命令

```csh
setenv PROJ /path/to/ai_lib/repo
setenv WORK $PROJ/work/review
setenv RAW  /path/to/raw_delivery

$PROJ/scripts/lg.csh init $WORK --raw-root $RAW --library-type ip
$PROJ/scripts/lg.csh cat --full --with-evidence
$PROJ/scripts/lg.csh scan <LIBRARY> <VERSION>
$PROJ/scripts/lg.csh refresh <LIBRARY>
$PROJ/scripts/lg.csh cmp <LIBRARY> <VERSION> --base <BASE_VERSION> --scan-if-missing
$PROJ/scripts/lg.csh cmp <LIBRARY> <VERSION> --base <BASE_VERSION> --rescan
$PROJ/scripts/lg.csh fd <LIBRARY> <VERSION> <REL_PATH> --base <BASE_VERSION> --type <FILE_TYPE>
$PROJ/scripts/lg.csh rv-check <LIBRARY> <VERSION> --gate current
$PROJ/scripts/lg.csh rv-accept <LIBRARY> <VERSION> --item <ITEM_ID> --by <USER> --reason "..."
$PROJ/scripts/lg.csh rel <LIBRARY> <VERSION> --check-first --link-mode symlink
$PROJ/scripts/lg.csh rel <LIBRARY> <VERSION> --check-first --explain
```

`refresh` 用于刷新 Version Review 的更新详情，默认选择 `current_effective` 或
`previous_effective` 作为 base；`cmp` 用于手动指定 base 或 adjacent/cumulative 等比较。

## Version Review lane policy

`refresh` 是普通 Version Review 更新详情入口。它默认先使用 `current_effective`
作为 base；如果当前有效库不存在，再退到 `previous_effective`。找不到可信 base 时，
页面会要求人工确认，而不是把 adjacent 结果伪装成日常更新详情。

`cmp` 是手动 compare/debug 工具，适合显式指定 base、调试 adjacent/cumulative，
或生成独立 Comparison Review。`fd` 是手动 file drill-down，只用于 reviewer 或 owner
确认需要逐文件查看的重点文件。

`rel --explain` 只解释 release check 为什么 blocked，不执行 link/apply。

File Diff lane 的含义是审查方式，不是漏跑检查。`summary-only` 表示大型逻辑视图已经
通过 summary/count/corner 等证据审查；`metadata-only` 表示二进制、layout 或 database
视图通过 hash、size、path、count 等 metadata 证据审查。

`--force-large` 只允许专家在显式手动 `fd` 时 opt in 大文件、集合文件或二进制 metadata
lane 的人工下钻成本。它不会改变 `refresh`、`cmp` 或自动 pairwise 推荐的默认 lane
策略。

如果 `$WORK/lib_guard.yml` 存在，`lg.csh` 会自动使用它。也可以显式指定：

```csh
setenv LIB_GUARD_CONFIG $WORK/lib_guard.yml
```

## 底层命令与验证

```bash
PYTHONPATH=src python -m lib_guard.cli catalog scan --root "$RAW" --out "$WORK/catalog" --render --html-out "$WORK/catalog/html" --policy configs/catalog_policy.json
PYTHONPATH=src python -m lib_guard.cli run-batch --catalog "$WORK/catalog/catalog.json" --workdir "$WORK" --parse-jobs 8
PYTHONPATH=src python -m lib_guard.cli compare --catalog "$WORK/catalog/catalog.json" --library <LIBRARY> --new <VERSION> --base <BASE_VERSION> --workdir "$WORK"
PYTHONPATH=src python -m compileall -q src
PYTHONPATH=src python -m unittest discover -s src/lib_guard/test -p "test*.py"
```

## Documentation

- [Documentation index](docs/index.md)
- [Command surface](docs/command_surface.md)
- [Manual confirmation and action flow](docs/manual_confirmation_action.md)
- [Architecture](docs/architecture.md)
- [User guide](docs/user_guide.md)
- [CLI reference](docs/cli_reference.md)
- [Data contract](docs/data_contract.md)
- [Review gate](docs/review_gate.md)
- [Test plan](docs/test_plan.md)
- [Compatibility](docs/compatibility.md)
