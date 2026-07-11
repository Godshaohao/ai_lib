Status: current

# CLI 参考

这份文档是命令字典。第一次完整演练请看
[基础教程](basic_tutorial.md)。

## 文档契约

| 项 | 说明 |
| --- | --- |
| 目标读者 | 需要查命令副作用、参数和专家入口的人 |
| 推荐入口 | `$PROJ/scripts/lg.csh` 或 source `scripts/lg_complete.csh` 后使用 `lg` |
| 底层入口 | `python -m lib_guard.cli`，仅用于自动化、调试和测试 |
| 禁止假设 | 命令成功不等于 Catalog 首页已全量刷新；先看 `render_summary` |
| 命名规则 | 日常命令只输入正式 `LIBRARY` 和 `VERSION`，不要手敲 typed id / report slug |

## 命令入口分层

日常使用优先走短命令 wrapper：

```csh
$PROJ/scripts/lg.csh <COMMAND>
```

底层 `python -m lib_guard.cli` 是工程自动化和调试入口，不作为普通用户主路径。

在 csh/tcsh 中可以 source 补全脚本，获得 `lg` alias、短命令补全、子命令补全和常用参数补全：

```csh
source $PROJ/scripts/lg_complete.csh
lg <TAB>
lg library <TAB>
```

库名和版本名是 workspace catalog 里的运行时数据。为了避免 Tab 时反复读取大工程目录，
补全脚本默认不动态扫 catalog；复制正式名字请用：

```csh
lg library list --plain
lg library list <LIBRARY> --versions --plain
```

| 短命令 | 作用 |
| --- | --- |
| `init` | 创建 workspace 配置 |
| `library add` | 已知库根时直接加入人工确认 registry |
| `library discover` / `library accept` / `library apply` | 发现候选库、合并人工确认、生成正式 library map |
| `library list` | 列出正式库名和版本名 |
| `library override` | 人工确认版本 stage/base/package 关系 |
| `cat` | 渲染已有 catalog/HTML；显式 `--refresh-catalog` 时重建 catalog 投影 |
| `scan` | 扫描一个版本或一批版本 |
| `cmp` | 手动对比更新版本和指定 base 版本 |
| `next` | 小白入口：查看下一步、预演 FULL/增量流程、执行接入、接受 candidate effective |
| `worklist` | 专家别名：批量查看哪些库可执行、需人工确认或无新版本 |
| `intake` | 专家入口：预演/执行新版本接入窗口，自动串起 scan、effective compare 和 Version Detail 刷新 |
| `window` / `accept-window` | 专家入口：查看接入窗口、接受 candidate effective |
| `effective rollback` | 错误 accept 后把 current effective 指回旧 manifest |
| `fd` | 运行单文件两两 diff |
| `rv check` / `rv list` | 查看 Review Gate 状态 |
| `rv accept` / `rv waive` | 记录 owner 决策 |
| `rel` | 执行 release check/link/verify 规划 |
| `action` | 执行一个 workspace action 文件 |

旧短命令 `catalog/diff/file-diff/release/refresh/override/rv-check` 仅作为兼容改写保留，
不再出现在推荐 help 中。

## 常用示例

```csh
lg.csh library add vendor_A.openroad_platform.openroad_asap7 --root /path/to/vendor_A/openroad_asap7 --apply --refresh-catalog
lg.csh library discover
gvim $WORK/config/library_candidates/latest.tsv
lg.csh library accept
lg.csh library apply
lg.csh library list
lg.csh library list vendor_A.openroad_platform.openroad_asap7 --versions
lg.csh library list --plain
lg.csh library list vendor_A.openroad_platform.openroad_asap7 --versions --plain
lg.csh cat --refresh-catalog
lg.csh next
lg.csh next --ready
lg.csh next ucie
lg.csh next ucie --apply
lg.csh next ucie --accept --by lib_owner --note "review passed"
lg.csh worklist
lg.csh library override ucie stable_20250608 --stage stable --base stable_20250601
lg.csh intake ucie --plan-only
lg.csh intake ucie
lg.csh accept-window ucie --accepted-by lib_owner --note "review passed"
lg.csh effective rollback ucie --to E_old --by lib_owner --reason "wrong accept"
lg.csh scan ucie stable_20250608 --parse-file-types lef,cdl
lg.csh cmp ucie stable_20250608 --base stable_20250601 --scan-if-missing
lg.csh fd ucie stable_20250608 lef/ucie.lef --base stable_20250601 --type lef
lg.csh rv check ucie stable_20250608 --gate current
lg.csh rv accept ucie stable_20250608 --item metadata.db.changed:db/ucie.db --by lib_owner --reason "DB hash change accepted for current."
lg.csh action ucie
lg.csh rel ucie stable_20250608
lg.csh rel ucie stable_20250608 --apply --overwrite
```

## 命令副作用矩阵

| 命令 | 主要事实输入 | 写入事实 | 写入投影 | 默认复杂度 |
| --- | --- | --- | --- | --- |
| `library add ... --apply` | 用户提供库根 | registry、library_catalog | 可选 catalog 投影 | O(1) |
| `library discover` | RAW root | candidates | 候选 HTML/TSV | 受 `max-*` 限制 |
| `library apply` | registry/candidates | library_catalog | 无 | O(库数) |
| `cat` | catalog.json | 无 | Catalog 首页/导航 | O(库数 + 版本数) |
| `cat <LIBRARY> <VERSION>` | catalog、已有 scan/diff/effective | 无 | 单个 Version Detail | O(1) |
| `scan <LIBRARY> <VERSION>` | catalog、raw path | scan_out、catalog runtime 指针 | scan HTML、Version Detail | O(版本文件数) |
| `cmp <LIBRARY> <VERSION>` | catalog、scan_out、base | diff、catalog runtime 指针 | target Version Detail | O(两版本文件数) |
| `next <LIBRARY>` | catalog、effective/window | 无 | 无 | O(该库版本数) |
| `next <LIBRARY> --apply` | catalog、raw、scan/diff/effective | scan_out、effective、diff、plan state | window 内 Version Detail | O(window) |
| `next <LIBRARY> --accept` | pending window、candidate effective | current_effective | 相关 Version Detail | O(window) |
| `rel ... --apply` | release manifest、scan/diff/gate | release area、release result | release HTML | O(manifest 文件数) |

所有热路径都应通过 Render Impact 局部刷新 Version Detail。只有显式 `cat --refresh-catalog`
才应低频重建 catalog 投影。

`library discover` 是候选发现，不是正式入库动作。默认浅层、有上限：

```csh
lg.csh library discover --max-depth 4 --max-dirs 5000 --max-candidates 200
```

大目录下已知库根时，优先使用：

```csh
lg.csh library add <LIBRARY> --root <LIBRARY_ROOT> --apply --refresh-catalog
```

discover 不会把版本目录内部的 `phys_ver`、`dft`、`lef`、`lib` 等目录当成库。
它只识别“直接包含多个版本/交付实例”的候选根；倒置 release 树需要人工 `library add`。

## `intake`、`cat --update-detail` 和 `cmp`

多库日常先看 `next`，不要逐库排障：

```csh
lg.csh next
lg.csh next --ready
lg.csh next --blocked
```

`next` 不传库名时不运行 scan/diff，只根据 catalog、current effective 和 review window 归类：
`可执行`、`可接受`、`需确认包类型`、`需确认Base`、`无新版本`。

单库新版本接入优先用 `next` 两段式：

```csh
lg.csh next ucie
lg.csh next ucie --apply
```

`lg next <LIBRARY>` 只输出 candidate/base/scan_versions、FULL/增量流程判断和确认后执行命令；
确认后运行 `lg next <LIBRARY> --apply`，系统会自动 scan 缺失版本、构建 candidate effective、做 effective
compare，并刷新受影响 Version Detail。Version Review 仍是唯一主审查投影。

`intake` 同时会维护：

```text
$WORK/state/<LIBRARY>/current_plan.json
```

该文件按 task 记录 `scan`、`effective_build`、`effective_compare` 的状态、输入指纹、
依赖和 artifact。重复运行 `intake <LIBRARY>` 会跳过同输入指纹下已 `DONE` 的 task，
从 `FAILED/PENDING` 位置继续。输出里的 `plan_state` 和 `next_action` 是日常排查入口。

如果窗口里有 `UNKNOWN_PACKAGE` 或缺失 `package_type` 的版本，`intake` 会返回
`NEEDS_PACKAGE_CONFIRM`，不会执行后续任务；`accept-window` 和 release 也会拒绝这种
未确认类型。先用 `lg mark <LIBRARY> <VERSION> --type FULL|FIX|HOTFIX` 或
`lg library override ... --package-type ...` 修正。

Version Detail 审查通过后接受当前候选有效版：

```csh
lg.csh next ucie --accept --by lib_owner --note "review passed"
```

如果错误执行了接受操作，使用：

```csh
lg.csh effective rollback <LIBRARY> --to <OLD_EFFECTIVE_ID> --by <USER> --reason "wrong accept"
```

该命令只把 `current_effective.json` 指回已有 effective manifest，不删除 scan/diff/effective
历史证据。

`cat <LIBRARY> --update-detail` 是兼容的单版本更新证据入口。默认行为是：

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

scan、batch scan、cmp、batch compare、intake、accept-window 和 mark 会声明
Render Impact，并刷新受影响的 Version Detail、库工作台和目录索引。日常不要用
全量 catalog render 代替单版本投影刷新：

```csh
lg.csh cat ucie stable_20250608
lg.csh scan ucie stable_20250608
lg.csh cmp ucie stable_20250608 --base stable_20250601 --scan-if-missing
lg.csh intake ucie
lg.csh accept-window ucie --accepted-by lib_owner
lg.csh mark ucie stable_20250608 --type FULL
```

这些命令更新的是 Version Detail 这个唯一审查投影；`window`、`effective`、`compare`
不是新的主审查入口。

命令输出里应优先看：

| 字段 | 如何理解 |
| --- | --- |
| `status` | 本命令业务是否成功 |
| `phase_timings` | 诊断 scan/render 慢在哪里 |
| `render_summary.message` | 页面是否刷新、是否延迟刷新导航 |
| `render_summary.open_first` | 审查时优先打开的详情页 |
| `render_summary.deferred_file` | 哪些导航页延迟刷新 |

如果 `scan` 或 `cmp` 后库工作台看起来没变，但 `open_first` 指向的 Version Detail 已更新，
这是预期的热路径行为，不是证据丢失。

## `scan`

`scan` 只有一种用户态动作：生成当前版本的 scan evidence。扫描深度由策略参数控制，
不是由多个 mode 控制。

| 策略参数 | 作用 |
| --- | --- |
| `--parse-file-types lef,cdl` | 只让指定类型进入 parser 任务 |
| `--parse-exclude-file-types verilog,liberty,spef` | 从 parser 任务里排除指定类型 |
| `--hash-policy smart` | 默认策略，小文件 hash，大型 EDA 文件按 metadata 处理 |
| `--hash-policy full` | 专家/调试场景，强制计算内容 hash |
| `--parse-jobs 8` | parser 并行度 |

scan 输出分两层：

| 层 | 文件 | 用途 |
| --- | --- | --- |
| 机器事实 | `file_inventory.json`, `parser_manifest.json`, `parser_results.json`, `summary/*.json` | diff、release、自动化 |
| 人工证据 | `review/view_coverage.tsv`, `review/files_by_view.tsv`, `review/unknown_files.tsv`, `review/large_metadata_files.tsv`, `review/parser_evidence.tsv` | Scan HTML 和 Version Detail |

人工审查优先看 `review/*.tsv`。JSON 可以保留，但不应该被复制到主页面正文里。

## 文件类型 Lane

默认 File Diff 推荐只覆盖 `DEFAULT_FILE_DIFF_TYPES`，避免把大文件、多文件集合和
二进制工艺视图当作普通文本 diff：

| Lane | 类型 | 默认行为 |
| --- | --- | --- |
| `DEFAULT_FILE_DIFF_TYPES` | `lef`, `cdl`, `spice`, `sp`, `sdc`, `upf`, `cpf`, `waiver`, `ibis`, `pwl`, `snp`, `touchstone`, `cpm` | 可以生成推荐 File Diff |
| `SUMMARY_ONLY_TYPES` | `verilog`, `systemverilog`, `liberty`, `lib`, `spef` | 只做 summary/count/corner/metadata，不默认生成 fd command |
| `BINARY_METADATA_ONLY_TYPES` | `db`, `gds`, `oas`, `layout`, `milkyway`, `ndm` | 只做二进制 metadata/hash/路径证据，不默认生成 fd command |

### 专家 Opt-In：`fd --force-large`

`SUMMARY_ONLY_TYPES` 和 `BINARY_METADATA_ONLY_TYPES` 只能在人工确认必要时手动运行。
不加 `--force-large` 会报错，并提示该类型默认走 summary-only 或 metadata-only 审查。

```csh
lg.csh fd ucie patch_20260630 rtl/top.v --type verilog --force-large
lg.csh fd ucie patch_20260630 timing/top.lib --type liberty --force-large
lg.csh fd ucie patch_20260630 db/ucie.db --type db --force-large
```

## Review Gate

Review Gate 是轻量 release 风险门禁，不是多部门审批系统。

| 字段 | 含义 |
| --- | --- |
| `blocking_items` | 会阻塞当前 gate 的真实问题 |
| `attention_items` | 需要关注但不阻塞的项目 |
| `accepted_items` | owner 明确接受的项目 |
| `waived_items` | owner 明确豁免的项目 |

常用命令：

```csh
lg.csh rv check  <LIBRARY> <VERSION> --gate current
lg.csh rv list   <LIBRARY> <VERSION> --gate current
lg.csh rv accept <LIBRARY> <VERSION> --item <ITEM_ID> --by <USER> --reason "..."
lg.csh rv waive  <LIBRARY> <VERSION> --item <ITEM_ID> --by <USER> --reason "..."
```

## Action 文件

Action 文件位于：

```text
$WORK/actions/<library>.action
```

支持的动词：

| Action | 含义 |
| --- | --- |
| `@scan VERSION` | 扫描指定版本 |
| `@rescan VERSION` | 强制重扫指定版本 |
| `@diff OLD NEW NAME` | 生成对比 |
| `@rediff OLD NEW NAME` | 强制重新对比 |
| `@release VERSION` | 生成 release preview/规划 |
| `@rerelease VERSION` | 强制重新生成 release preview/规划 |
| `@ALL redo` | 标记后续动作全部重做 |

执行：

```csh
lg.csh action <LIBRARY>
```

## Release

```csh
lg.csh rel <LIBRARY>
lg.csh rel <LIBRARY> <VERSION> --explain
lg.csh rel <LIBRARY> --apply
lg.csh rel <LIBRARY> --apply --overwrite
```

`rel <LIBRARY>` 默认发布已接受的 current effective：读取 `current_effective.json` 指向的
`effective_manifest.json`，生成 file-level release manifest，再生成 symlink release 规划；
不会自动 apply。`rel <LIBRARY> <VERSION>` 是专家 raw catalog version 入口，会先执行
release-check。

release batch 默认 fail-closed：没有当前 `PASS` / `PASS_WITH_WARNING` 检查状态的版本不会被
选择。`BLOCK` / `FAILED` 会停止短命令链路；只有显式 `--force --force-reason --force-by`
会走审计绕过。Force 路径会直接进入 release batch，避免被前置 check 的非零退出码提前中止。

注意：显式写 VERSION 时发布的是 catalog raw version。若库采用 FULL + FIX/HOTFIX
组合，普通流程应使用不带 VERSION 的 `rel <LIBRARY>`，避免把单个 FIX raw 包误当完整组合。

`--overwrite` 只替换 manifest 中列出的目标文件，不会清空 release root 中其他库文件。

强制发布必须写明原因和操作者：

```csh
lg.csh rel <LIBRARY> --apply --force \
  --force-reason "owner accepted metadata-only change" \
  --force-by <USER>
```

`--apply` 会立即执行 postcheck。link/copy 成功但 postcheck 失败时，顶层 `status=FAILED`
且退出码非零；自动化脚本不能只看 link 阶段是否成功。

## 不推荐继续使用的入口

| 入口 | 状态 | 替代 |
| --- | --- | --- |
| 旧 `refresh` | 兼容改写 | `cat <LIBRARY> --update-detail` 或 `scan/cmp` 热路径 |
| 旧 `compare` | 兼容改写 | `cmp` |
| 旧文件级对比长命令 | 移除或兼容期 | `fd` |
| 手改 `catalog.json` | 禁止 | `library override`、`mark`、policy/registry |
| 手改 HTML | 禁止 | 重新 `cat` 或触发 Render Impact |

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
PYTHONPATH=src python3 -m lib_guard.cli --help
PYTHONPATH=src python3 -m lib_guard.short_cli --help
scripts/lg.csh --help
```

`lg.csh --help` 是面向日常用户的入口。`python -m lib_guard.cli --help`
是底层自动化/调试入口。
