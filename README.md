# ai_lib

本仓库保留两条独立流程：

- [IP 工程检查工作台](src_qor/README.md)（`src_qor/`）：按 IP 选择正式 NL 盘点、
  Macro/View 索引、LEF 对比和 LEF-Liberty 接口检查；每个 IP 生成独立 Excel，
  HTML 提供多 IP 导航。检查执行完成不等于质量通过或正式放行。
- 既有 Catalog/Release 流程（`src/lib_guard/`）：管理库版本、Scan/Diff、
  Effective 及发布证据。其命令和状态不作为 `src_qor` 检查的隐式输入。

以下是既有 Catalog/Release 流程的使用说明；新 IP 检查的配置、启动和输出
路径以 [src_qor/README.md](src_qor/README.md) 为准。

## Catalog/Release 流程

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

## Catalog/Release 最短入口

```csh
setenv PROJ /path/to/ai_lib/repo
setenv WORK $PROJ/work/review
setenv RAW  /path/to/raw_delivery

$PROJ/scripts/lg.csh init $WORK --raw-root $RAW --library-type ip
cd $WORK
source $PROJ/scripts/lg_complete.csh
$PROJ/scripts/lg.csh library add <LIBRARY> --root <LIBRARY_ROOT> --apply --refresh-catalog
$PROJ/scripts/lg.csh next <LIBRARY>
$PROJ/scripts/lg.csh next <LIBRARY> --apply
$PROJ/scripts/lg.csh next <LIBRARY> --accept --by <USER> --note "review passed"
$PROJ/scripts/lg.csh rel <LIBRARY> <VERSION>
```

`next <LIBRARY>` 是普通用户入口：先只读预演，确认后 `--apply` 执行 scan/effective
compare/render，审查通过后 `--accept` 写入 current effective。底层 `intake`、
`window`、`accept-window` 是专家/调试入口，不作为 README 主路径。

`next --apply` 会维护 `$WORK/state/<LIBRARY>/current_plan.json`，重复运行会跳过同一输入下
已完成 task 并从失败点继续；遇到未确认 `package_type` 会先阻断，要求 `lg mark` 或
`lg library override` 显式确认后再执行。

`source $PROJ/scripts/lg_complete.csh` 会提供 `lg` alias；在 tcsh 中还会启用 Tab 补全，纯 csh 不支持该 shell 内建能力。
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
src_qor/                 Independent IP check scripts and workbench
src_qor/test/            IP check automated tests
tests/                   Integration fixtures and repository-level notes
work/                    Generated local output, not source of truth
```

Historical migration notes and workflow-pack material are not kept in the
current repository path. Current behavior is defined by the docs listed below.

## Documentation

- [Documentation index](docs/index.md)
- [IP check workbench](src_qor/README.md)
- [Generated report publication policy](docs/public_artifact_policy.md)
- [基础教程](docs/basic_tutorial.md)
- [CLI 参考](docs/cli_reference.md)
- [配置参考](docs/config_reference.md)
- [Architecture](docs/architecture.md)
- [Data contract](docs/data_contract.md)
- [Test plan](docs/test_plan.md)
- [Compatibility](docs/compatibility.md)
