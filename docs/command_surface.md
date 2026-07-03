Status: current

# 命令入口分层

`lib_guard` 有两层命令入口：

- 日常用户入口：`scripts/lg.csh`、`scripts/lg.ps1`、`scripts/lg.cmd`
- 底层自动化入口：`PYTHONPATH=src python -m lib_guard.cli ...`

正常审查和交付流程应优先使用短命令。底层 CLI 保留给自动化、调试、
测试和脚本编排，不要求普通用户手写长命令。

## 日常用户命令

| 命令 | 作用 |
| --- | --- |
| `init` | 创建 workspace 级 `lib_guard.yml` |
| `library discover` / `library apply` | 发现候选库并应用人工确认后的 library map |
| `cat` | 刷新 catalog JSON 和 catalog HTML |
| `override` | 人工确认或修正版本 stage/base/package 关系 |
| `scan` | 为一个版本或一批版本生成 Version Review evidence |
| `refresh` | 刷新 Version Review 的日常更新详情 |
| `cmp` | 手动将一个更新版本和指定 base 版本做结构对比 |
| `fd` | 对关键文件运行两两 File Diff |
| `rv-check` / `rv-list` | 检查 Review Gate 状态 |
| `rv-accept` / `rv-waive` | 记录 owner 人工 accept/waive 决策 |
| `rel` | 执行 release check/link/verify 规划 |
| `action` | 执行 workspace action 文件 |

推荐流程：

```csh
$PROJ/scripts/lg.csh init $WORK --raw-root $RAW --library-type ip
$PROJ/scripts/lg.csh library discover
# 人工审查并编辑 $WORK/config/library.list
$PROJ/scripts/lg.csh library apply
$PROJ/scripts/lg.csh cat --with-evidence

# 如 catalog 自动推断的 stage/base/package 关系不可靠，先人工确认
$PROJ/scripts/lg.csh override <LIBRARY> <VERSION> --stage stable --base <BASE_VERSION>

$PROJ/scripts/lg.csh scan <LIBRARY> <VERSION>
$PROJ/scripts/lg.csh refresh <LIBRARY>
# 手动 compare/debug 时再显式指定 base 或 adjacent/cumulative
$PROJ/scripts/lg.csh cmp <LIBRARY> <VERSION> --base <BASE_VERSION> --scan-if-missing
$PROJ/scripts/lg.csh fd <LIBRARY> <VERSION> <REL_PATH> --base <BASE_VERSION> --type <FILE_TYPE>
$PROJ/scripts/lg.csh rv-check <LIBRARY> <VERSION> --gate current
$PROJ/scripts/lg.csh rel <LIBRARY> <VERSION> --check-first --link-mode symlink
$PROJ/scripts/lg.csh rel <LIBRARY> <VERSION> --check-first --explain
```

## 不是全自动

当前流程不是全自动发布。自动化负责发现、扫描、对比、生成页面和建议；
人工负责确认以下内容：

- `library.list` 中哪些候选库应该进入正式 library map。
- 版本 stage、base、package type、update scope 是否可信。
- Review Gate 中的 blocking item 是否 accept 或 waive。
- action 文件中需要批量执行哪些 scan/diff/effective/release 动作。
- force release 是否有明确 owner reason；`--force` 必须同时提供 `--force-reason`。

这些人工确认会写入 workspace 或 catalog 状态文件，后续重新生成 HTML 时会继续使用。

`--scan-if-missing` 和 `scan --missing` 只补缺少或已过期的 scan evidence。catalog 会保存版本输入文件指纹；RAW 内容变化后旧证据会显示为 `STALE_SCAN`，不会被当作有效增量缓存。

## 底层自动化 CLI

短命令会展开到底层 CLI。以下底层命令仍然保留，因为它们是自动化边界：

| 命令 | 使用位置 |
| --- | --- |
| `catalog scan/render/list/override` | catalog 刷新、人工关系修正 |
| `run` / `run-batch` | scan workflow 执行 |
| `compare` / `compare-batch` | 结构 diff workflow 执行 |
| `file-diff` | 单文件两两 diff 引擎 |
| `review` | Review Gate 引擎 |
| `release` / `release-batch` / `package` / `effective` / `version` | release/package/effective-version 自动化 |
| `console` | 兼容旧 review console 的 JSON/HTML 导出 |

`release-batch --force --force-reason ...` 会保留强制发布入口，并写入
`release_override.json` 审计文件。`rel --explain` 只解释 release check 阻塞原因，
不执行 link/apply。

已移出当前命令面：

| 旧入口 | 替代方式 |
| --- | --- |
| `lg.csh filediff` | `lg.csh fd` |
| `lg.csh refresh-diff` | `lg.csh refresh` |
| `lg.csh lib` | `lg.csh library` |
| `lg.csh act` / `lg.csh review` | `lg.csh action` |
| `lg.csh compare` | `lg.csh cmp` |
| `lg.csh rf` | `lg.csh refresh` |
| `python -m lib_guard.cli update file/type` | 修复 parser/policy 后运行 `lg.csh scan <LIBRARY> <VERSION> --rescan` |

## 配置归属

默认 workspace 路径和项目 policy 文件名定义在
`src/lib_guard/project_config.py`。

项目级 policy：

- `configs/catalog_policy.json`
- `configs/release_policy.json`

workspace 本地文件：

- `$WORK/lib_guard.yml`
- `$WORK/config/library.list`
- `$WORK/config/library_catalog.yml`
- `$WORK/config/library_versions.tsv`
- `$WORK/actions/<library>.action`
