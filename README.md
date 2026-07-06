# ai_lib / lib_guard

`lib_guard` 是面向 IC library / IP 交付的 catalog 驱动审查工具。它负责发现
raw delivery、扫描版本、生成结构化更新证据、渲染 HTML，并在 release 前准备
可追溯证据。

## 当前主流程

```text
库目录 -> 版本审查 -> Release
```

- 库目录是库资产地图和报告入口。
- 版本审查是普通 reviewer 的主页面。
- Release 使用 manifest 驱动的文件级 symlink/copy 规划。
- Comparison Review 是手动 compare/debug 入口，不是普通用户查看更新详情的唯一入口。
- File Diff 只用于推荐下钻的关键文件，不是全量完成度 scoreboard。
- Review Gate 只记录真实 blocker 和 owner accept/waive 决策。

日常使用优先走短命令：`scripts/lg.csh`、`scripts/lg.ps1`、`scripts/lg.cmd`。
底层 `python -m lib_guard.cli` 入口保留给自动化、调试和测试。

## 最短入口

```csh
setenv PROJ /path/to/ai_lib/repo
setenv WORK $PROJ/work/review
setenv RAW  /path/to/raw_delivery

$PROJ/scripts/lg.csh init $WORK --raw-root $RAW --library-type ip
cd $WORK
source $PROJ/scripts/lg_complete.csh
$PROJ/scripts/lg.csh library add <LIBRARY> --root <LIBRARY_ROOT> --apply --refresh-catalog
$PROJ/scripts/lg.csh intake <LIBRARY> --plan-only
$PROJ/scripts/lg.csh intake <LIBRARY>
$PROJ/scripts/lg.csh accept-window <LIBRARY> --accepted-by <USER> --note "review passed"
$PROJ/scripts/lg.csh rel <LIBRARY> <VERSION>
```

`source $PROJ/scripts/lg_complete.csh` 会提供 `lg` alias 和 csh/tcsh Tab 补全。
库名/版本名用 `lg library list --plain`、`lg library list <LIBRARY> --versions --plain`
获取，避免手猜 `_` 和 `.`。

完整流程见 [基础教程](docs/basic_tutorial.md)。

## Repository Map

```text
configs/                 Current catalog and release policies
docs/                    Current documentation
scripts/                 Thin user-facing wrappers
examples/                Copyable action/file examples
src/lib_guard/           Product source
src/lib_guard/test/      Active automated tests
tests/                   Integration fixtures and repository-level notes
work/                    Generated local output, not source of truth
```

Historical migration notes and workflow-pack material are not kept in the
current repository path. Current behavior is defined by the docs listed below.

## Documentation

- [Documentation index](docs/index.md)
- [基础教程](docs/basic_tutorial.md)
- [CLI 参考](docs/cli_reference.md)
- [配置参考](docs/config_reference.md)
- [Architecture](docs/architecture.md)
- [Data contract](docs/data_contract.md)
- [Test plan](docs/test_plan.md)
- [Compatibility](docs/compatibility.md)
