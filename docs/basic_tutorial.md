Status: current

# 基础教程：从新库入库到 Release

这份教程是普通用户的主入口。只按这里走，就能完成：

```text
新库入库 -> catalog -> next 预演 -> next 执行 -> version review -> release
```

## 文档契约

| 项 | 说明 |
| --- | --- |
| 目标读者 | 库管理员、IP 使用者、首次接入新版本的人 |
| 目标判断 | 新库/新版本是否能进入审查、是否能成为当前有效版、是否能 release |
| 允许输入 | RAW 库根、人工确认的库名/版本名、package type/Base 修正、review 决策 |
| 主要输出 | `catalog.json`、scan evidence、diff evidence、Version Detail、current effective、release manifest |
| 禁止做法 | 手改生成 HTML、手改 `catalog.json` 的 scan/diff 字段、用全量 discover 代替已知库入库 |

底层 `python -m lib_guard.cli` 是自动化和调试入口；日常使用优先用
`$PROJ/scripts/lg.csh`。

如果在 csh/tcsh 里长期手动操作，先开启短命令补全和 `lg` alias：

```csh
source $PROJ/scripts/lg_complete.csh
```

之后可以用 `lg <TAB>`、`lg library <TAB>` 补全短命令、子命令和常用参数。
库名和版本名来自运行时 catalog，不建议每次 Tab 都触发 Python 读取大 workspace；
需要复制正式名字时用：

```csh
lg library list --plain
lg library list <LIBRARY> --versions --plain
```

## 0. 初始化 Workspace

```csh
setenv PROJ /path/to/ai_lib/repo
setenv WORK $PROJ/work/review
setenv RAW  /path/to/raw_delivery

$PROJ/scripts/lg.csh init $WORK --raw-root $RAW --library-type ip
cd $WORK
```

`$WORK/lib_guard.yml` 是短命令默认配置。后续不在 `$WORK` 下执行时，可以设置：

```csh
setenv LIB_GUARD_CONFIG $WORK/lib_guard.yml
```

初始化后先确认三件事：

```csh
test -f $WORK/lib_guard.yml
test -d $WORK/config
$PROJ/scripts/lg.csh --help
```

如果 `lg.csh` 报 Python module 冲突，先修 shell 环境，再继续业务流程。不要在失败环境里
反复运行 discover/scan。

## 1. 新库入库

如果已经知道库根目录，直接写入人工确认 registry，并立即生成正式
`library_catalog.yml` 和局部 catalog 投影：

```csh
$PROJ/scripts/lg.csh library add vendor_A.openroad_platform.openroad_asap7 \
  --root /path/to/vendor_A/openroad_asap7 \
  --vendor vendor_A \
  --display-name openroad_asap7 \
  --apply \
  --refresh-catalog
```

如果不加 `--refresh-catalog`，`library add --apply` 只更新人工确认 registry 和正式
`library_catalog.yml`，还不会生成 `$WORK/catalog/catalog.json`。第一次入库后必须再生成
catalog 投影：

```csh
$PROJ/scripts/lg.csh cat --refresh-catalog --with-evidence
```

否则直接执行 `library list` 会看到类似错误：

```text
FileNotFoundError: .../catalog/catalog.json
```

如果不知道库根目录，先发现候选，再人工确认：

```csh
$PROJ/scripts/lg.csh library discover
gvim $WORK/config/library_candidates/latest.tsv
$PROJ/scripts/lg.csh library accept
$PROJ/scripts/lg.csh library apply
```

`library discover` 只生成候选快照，不覆盖人工 registry。真正可信的库来源是：

```text
$WORK/config/library_registry.tsv
$WORK/config/library_catalog.yml
```

### 入库工程原则

| 场景 | 推荐动作 | 原因 |
| --- | --- | --- |
| 已知库根 | `library add ... --apply --refresh-catalog` | 最小、可解释、不会扫整棵 RAW |
| 不知道库根 | `library discover -> accept -> apply` | discover 只产生候选，需要人确认 |
| 大型内网库 | 先单库 `library add`，再 `next <LIBRARY>` | 避免 5000 个误候选和长时间递归 |
| 新增一个库 | 不重跑全量 discover | 已确认 registry 才是事实源 |

`library_catalog.yml` 是 catalog 的正式输入；`catalog.json` 是它的投影和运行时状态。
如果二者不一致，先检查 registry/apply，不要手改 `catalog.json`。

大 RAW 树上不要把 discover 当成日常刷新。默认 discover 是浅层、有上限的候选发现：

```csh
$PROJ/scripts/lg.csh library discover --max-depth 4 --max-dirs 5000 --max-candidates 200
```

如果已经知道库根，优先用 `library add ... --apply --refresh-catalog`，不要递归扫整棵树。

discover 的最小规则是：

- RAW root 第一层 `Vendor*` 目录只当供应商分组，不作为库候选。
- 候选库根必须直接包含多个版本/交付实例目录。
- 版本/交付实例目录是搜索边界。
- `phys_ver`、`dft`、`lef`、`lib` 等版本内部 view/实现目录不会作为库候选。
- 同一个 resolved root 只输出一次；被更深层候选覆盖的祖先目录不会写进候选 TSV。
- 如果真实库结构是“版本目录在上、IP block 在下”的倒置结构，自动 discover 只能给出上层候选；
  具体 IP block 应通过 `library add <LIBRARY> --root <LIBRARY_ROOT> --apply --refresh-catalog` 人工确认。

### 已有很多库时新增一个库

已有 20/100/500 个库时，不要重新 discover 整棵 RAW，也不要全量 scan。最小闭环是：

```csh
# 1. 只把新库写进人工 registry 和正式 library_catalog.yml
lg library add Vendor_Z.npu --root /path/to/Vendor_Z/npu --vendor Vendor_Z --display-name npu --apply --refresh-catalog

# 2. 先看多库工作清单；日常先处理“可执行”，异常库再单独看修正提示
lg next
lg next --ready

# 3. 确认正式库名和版本名
lg library list --plain
lg library list Vendor_Z.npu --versions --plain

# 4. 单库预演：不执行 scan/diff，只看 FULL/增量、Base、候选有效版
lg next Vendor_Z.npu

# 5. 如果提示需要修正包类型/Base，先看修正建议
lg next Vendor_Z.npu --fix

# 6. 确认 Base、Catalog类型、需扫描版本后执行 scan/effective compare/render
lg next Vendor_Z.npu --apply

# 7. Version Detail 审查通过后接受候选有效版
lg next Vendor_Z.npu --accept --by <USER> --note "review passed"
```

注意：如果只用了 `library add --apply`，`library list` 仍读取旧的
`$WORK/catalog/catalog.json`，新库可能暂时看不到。这不是入库失败，而是 catalog
投影尚未刷新。补跑 `lg cat <LIBRARY> --refresh-catalog` 后再查。

安全检查：

```csh
lg library list --plain
lg library list <LIBRARY> --versions --plain
```

如果新增库后旧库数量变少，先不要继续 scan。检查：

```text
$WORK/config/library_registry.tsv
$WORK/config/library_catalog.yml
$WORK/catalog/catalog.json
```

## 2. 获取正式库名和版本名

确认 `$WORK/catalog/catalog.json` 已经存在后，再列库和版本：

```csh
test -f $WORK/catalog/catalog.json
```

不要手猜 `_` 和 `.`。命令里使用 catalog 认可的正式名字：

```csh
$PROJ/scripts/lg.csh library list
$PROJ/scripts/lg.csh library list vendor_A.openroad_platform.openroad_asap7 --versions
```

日常只需要两个名字：

- `LIBRARY`：例如 `vendor_A.openroad_platform.openroad_asap7`
- `VERSION`：例如 `20260627_asap7`

如果只想复制名字，不要看 JSON：

```csh
$PROJ/scripts/lg.csh library list --plain
$PROJ/scripts/lg.csh library list <LIBRARY> --versions --plain
```

命名约定只让用户记两种：

| 用户需要输入 | 示例 | 不需要手敲 |
| --- | --- | --- |
| `LIBRARY` | `vendor_A.openroad_platform.openroad_asap7` | `ip/vendor_A.openroad_platform.openroad_asap7`、`ip_vendor_A...` |
| `VERSION` | `20260627_asap7` | `version_uid`、HTML 目录名 |

如果 UI 或 JSON 同时出现 typed id、slug、uid，日常命令仍只用 `LIBRARY` 和 `VERSION`。

## 2.1 FULL 流程和增量流程

日常不需要分别记两套命令。系统会在 `lg next <LIBRARY>` 里判断：

| 场景 | 判断方式 | 推荐命令 |
| --- | --- | --- |
| FULL 流程 | 最新交付本身是完整包，作为新的完整基线 | `lg next <LIBRARY>` 预演，确认后 `lg next <LIBRARY> --apply` |
| 增量流程 | 最新 FULL 作为基线，后续 FIX/HOTFIX 叠加成 candidate effective | `lg next <LIBRARY>` 预演，确认后 `lg next <LIBRARY> --apply` |
| 包类型不确定 | 有版本被识别为 `UNKNOWN_PACKAGE` 或 Base 不可信 | `lg next <LIBRARY> --fix` 看修正建议，再 `lg mark ...` 或 `lg library override ...` |
| 审查通过 | Version Detail 确认可用后写入当前有效版 | `lg next <LIBRARY> --accept --by <USER> --note "review passed"` |

`lg next <LIBRARY>` 默认只读，不执行 scan/diff，不改 current effective。它会显示：

```text
基线确认
流程判断：FULL流程 / FULL流程 + 增量流程
版本选择表
建议修正命令
当前组合
执行计划
```

这也是排查入口：如果流程判断不符合真实交付关系，先不要执行 `--apply`。

### 小白主路径

日常新版本到了，优先只记三步：

```csh
lg next <LIBRARY>
lg next <LIBRARY> --apply
lg next <LIBRARY> --accept --by <USER> --note "review passed"
```

第一步只读，第二步执行 scan/diff/effective compare 并刷新 Version Detail，第三步在审查通过后
写入 current effective。遇到异常再看 `lg next <LIBRARY> --fix`。

## 2.2 手动测试最小闭环

第一次演练不要直接跑全量。先用 `--dry-run` 看短命令会展开成哪些底层动作：

```csh
$PROJ/scripts/lg.csh --dry-run library list
$PROJ/scripts/lg.csh --dry-run library list <LIBRARY> --versions
$PROJ/scripts/lg.csh --dry-run cat <LIBRARY> <VERSION>
$PROJ/scripts/lg.csh --dry-run scan <LIBRARY> <VERSION>
$PROJ/scripts/lg.csh --dry-run cmp <LIBRARY> <VERSION> --base <BASE_VERSION> --scan-if-missing
$PROJ/scripts/lg.csh --dry-run next <LIBRARY>
$PROJ/scripts/lg.csh --dry-run next <LIBRARY> --apply
```

确认展开命令合理后，再按这个小闭环执行：

```csh
# 1. 确认正式库名和版本名
$PROJ/scripts/lg.csh library list
$PROJ/scripts/lg.csh library list <LIBRARY> --versions

# 2. 只渲染一个版本详情页，不重新 scan
$PROJ/scripts/lg.csh cat <LIBRARY> <VERSION>

# 3. 扫描一个版本；完成后会通过 Render Impact 刷新该版本详情页
$PROJ/scripts/lg.csh scan <LIBRARY> <VERSION>

# 4. 手动指定 base 做结构对比；完成后刷新 target 版本详情页
$PROJ/scripts/lg.csh cmp <LIBRARY> <VERSION> --base <BASE_VERSION> --scan-if-missing

# 5. 打开 Version Detail 检查第一屏
# 优先打开命令 JSON 里的 render_summary.open_first；
# 没有该字段时再打开 Catalog 首页导航。
firefox <render_summary.open_first>
```

第一屏只看五个判断：接入判断、审查对象、对比上下文、View 变化、证据状态。
如果这里显示 `STALE_OR_MISSING` 或 `NEEDS_BASE_CONFIRM`，先不要看 parser 明细，
先回到库名、版本名、base/effective 是否正确。

短命令副作用速查：

| 短命令 | 会 scan | 会 diff | 会刷新 Version Detail | 用途 |
| --- | --- | --- | --- | --- |
| `library list` | 否 | 否 | 否 | 找正式库名/版本名 |
| `cat` | 否 | 否 | 否 | 只用已有 `catalog.json` 重渲染 Catalog 导航页 |
| `cat <LIBRARY>` | 否 | 否 | 是，最新版本 | 只用已有证据重新投影该库最新版本详情页，不覆盖 Catalog 首页 |
| `cat <LIBRARY> <VERSION>` | 否 | 否 | 是，仅该版本 | 只用已有证据重新投影详情页 |
| `cat <LIBRARY> --update-detail` | 按需 | 是 | 是，按 update-detail 目标 | 刷新日常更新证据 |
| `scan <LIBRARY> <VERSION>` | 是 | 否 | 是，仅该版本 | 生成 scan evidence |
| `scan <LIBRARY> --missing` | 是，批量缺失项 | 否 | 是，成功版本集合 | 补齐 scan evidence |
| `next` | 否 | 否 | 否 | 小白入口：批量查看库下一步 |
| `next <LIBRARY>` | 否 | 否 | 否 | 预演该库 FULL/增量流程、Base 和 candidate |
| `next <LIBRARY> --apply` | 是，window 内版本 | 是，effective compare | 是，window 内版本 | 确认后执行 scan、effective compare、刷新详情页 |
| `next <LIBRARY> --accept --by ...` | 否 | 否 | 是，window 内版本 | 接受 candidate effective |
| `worklist` | 否 | 否 | 否 | 专家别名：批量查看哪些库可执行、需人工确认或无新版本 |
| `cmp <LIBRARY> <VERSION> --base ...` | 仅 `--scan-if-missing/--rescan` 时 | 是 | 是，target 版本 | 手动 compare/debug |
| `intake <LIBRARY> --plan-only` | 否 | 否 | 否 | 专家入口：生成接入计划；默认人工可读，`--json` 才输出机器 JSON |
| `intake <LIBRARY>` | 是，window 内版本 | 是，effective compare | 是，window 内版本 | 专家入口：执行接入计划 |
| `window <LIBRARY>` | 否 | 否 | 否 | 专家入口：查看 Base、候选版本、Catalog 类型和建议修正命令 |
| `accept-window <LIBRARY>` | 否 | 否 | 是，window 内版本 | 接受 candidate effective |
| `effective rollback <LIBRARY> --to <ID>` | 否 | 否 | 是，库级页面 | 错误 accept 后把 current effective 指回旧 manifest |
| `mark <LIBRARY> <VERSION>` | 否 | 否 | 是，该版本 | 修正 package type |
| `rv ...` | 否 | 否 | 否 | Review Gate 决策 |
| `rel ...` | 否 | 否 | 否 | release check/link/verify |

## 2.3 单库新版本：FIX 和 FULL 怎么走

单个库有新版本时，先不要急着全量刷新。核心问题只有两个：

- 这是依附旧有效版的 `FIX/HOTFIX/PARTIAL_UPDATE`，还是新的完整交付 `FULL_PACKAGE`？
- 本次详情页应该和哪个基准比？

### FIX / HOTFIX 更新

FIX 不是独立交付，它需要基准完整包或当前 effective。日常最小流程是先预演，
确认后执行：

```csh
# 1. 局部刷新该库目录投影
lg cat <LIBRARY> --refresh-catalog

# 2. 看版本名和自动识别的 package_type
lg library list <LIBRARY> --versions

# 3. 如果自动识别不对，先修正类型和关系
lg library override <LIBRARY> <FIX_VERSION> \
  --package-type PARTIAL_UPDATE \
  --base-full <BASE_FULL_VERSION> \
  --compare-default full_baseline \
  --note "manual confirmed fix package"

# 4. 预演：确认 Base、候选版本、Catalog 类型、scan_versions
lg next <LIBRARY>

# 5. 执行：自动 scan、构建 candidate effective、对比并刷新 Version Detail
lg next <LIBRARY> --apply
```

`intake` 会把这次窗口写成可恢复执行计划：

```text
$WORK/state/<LIBRARY>/current_plan.json
```

如果中途失败，重新运行 `lg next <LIBRARY> --apply` 会复用同一计划，跳过同一输入指纹下
已经 `DONE` 的 task，从失败点继续。命令输出里的 `plan_state`、`next_action` 和
`blocked_reason` 是判断下一步的主入口。

`lg next <LIBRARY>` 默认输出人工可读表；如果要给脚本解析，使用：

```csh
lg next <LIBRARY> --json
```

如果窗口里存在 `UNKNOWN_PACKAGE` 或缺失 `package_type` 的版本，`intake` 只会生成
计划并返回 `NEEDS_PACKAGE_CONFIRM`，不会执行 scan/effective compare。先用下面任一
方式确认类型，再重新 `intake`：

```csh
lg mark <LIBRARY> <VERSION> --type FULL --note "confirmed full package"
lg mark <LIBRARY> <VERSION> --type FIX  --note "confirmed partial update"
```

如果已经有 `current effective`，`cat --update-detail` 优先用 current/previous
effective；如果没有 effective 指针，但版本是 FIX/HOTFIX 并记录了
`base_full_version`，会回退到完整包基线，页面显示为“完整包基线”，不会伪装成
“上一有效版”。

### 批量库处理和错误 accept 回退

多库场景不要逐个进入专家 `window`。先跑：

```csh
lg next
lg next --ready
lg next --blocked
```

`next` 不传库名时只读 catalog/current effective/window 信息，不运行 scan/diff。它把库分成：

- `可执行`：系统已能推导 candidate/base，建议运行 `lg next <LIBRARY> --apply`。
- `可接受`：candidate 已生成且没有待执行 task，建议运行 `lg next <LIBRARY> --accept --by <USER>`。
- `需确认包类型` / `需确认Base`：只对这些异常库运行 `lg next <LIBRARY> --fix`，再用
  `mark` 或 `library override` 修正。
- `无新版本`：无需执行。

如果误执行了 `next <LIBRARY> --accept`，不要删 catalog、scan 或 HTML。把 current effective 指回旧 manifest：

```csh
lg effective rollback <LIBRARY> --to <OLD_EFFECTIVE_ID> --by $USER --reason "wrong candidate accepted"
```

`--to` 是 `$WORK/catalog/html/libraries/<LIB>/effective/<OLD_EFFECTIVE_ID>/effective_manifest.json`
所在目录名。

### FULL 更新

FULL 是新的完整交付候选，不应该和前一个 FIX 目录做默认相邻对比。日常最小流程：

```csh
# 1. 局部刷新该库目录投影
lg cat <LIBRARY> --refresh-catalog

# 2. 确认最新版本被识别为 FULL_PACKAGE
lg library list <LIBRARY> --versions

# 3. 如果识别不对，修正为完整包
lg mark <LIBRARY> <FULL_VERSION> --type FULL --note "manual confirmed full package"

# 4. 预演，再执行
lg next <LIBRARY>
lg next <LIBRARY> --apply
```

当没有 current effective 指针时，FULL 默认和上一完整包比较，页面显示为
“完整包基线 / 上一完整包”。如果中间有 FIX，它会作为窗口证据，不会被当成
FULL 的默认 base。

如果你要审查一个窗口内“旧 full + 若干 fix + 新 full”的组合关系，优先用：

```csh
lg next <LIBRARY>
lg next <LIBRARY> --apply
```

`next` 会给出 candidate effective：FIX 场景会把 FIX 叠加到基线；FULL 场景会把
最新 FULL 作为候选完整基线，并把它之前的 FIX 作为证据说明。

## 3. 生成 Catalog 页面

```csh
$PROJ/scripts/lg.csh cat --refresh-catalog --with-evidence
```

打开：

```text
$WORK/catalog/html/index.html
```

Catalog 首页只负责“找库”和进入库工作台。普通 `cat` 不重新 discover、不改
`catalog.json`；只有显式 `cat --refresh-catalog ...` / `cat --with-evidence ...`
才会重建 catalog 投影。

进入某个库后，二级库页默认只展示：

- 当前有效版：当前建议使用/已接受的版本或 effective 组合。
- 最新待审版：最新 raw 交付或候选版本。
- 本次审查：最新待审版相对当前/上一有效版的 scan/diff 状态。
- 证据入口：进入 Version Detail、Effective、Release Preview。

历史版本、历史 scan/diff 和 compare 记录默认折叠。不要把库工作台当成全版本
scan/diff 仪表盘；详细 View Delta、文件变化、parser evidence 仍以 Version Detail 为准。

库工作台的数据口径固定为三类，不能混：

| 字段 | 含义 | 典型来源 |
| --- | --- | --- |
| 当前有效版 | 当前建议接入/已接受的 raw 版本或 effective 组合 | `current_effective.json`、catalog current 指针、版本 `current_effective` 标记 |
| 最新待审版 | 最新 raw 交付或候选版本 | `latest_version`，否则取非当前有效版的最新版本 |
| Effective 证据 | 已生成的 effective manifest/release preview 证据入口 | `$WORK/catalog/html/libraries/.../effective/...` |

Effective 证据存在不等于它一定是当前有效版；只有被 current 指针或 manifest 标记为
current 时，才会升级为“当前有效版”。

`cat --refresh-catalog --with-evidence` 的作用是从正式 `library_catalog.yml` 重新生成
`$WORK/catalog/catalog.json` 和 Catalog HTML，并顺手收集轻量文件类型 evidence。
它是“低频重建 catalog 投影”，不是 scan/diff 的深度审查命令。

它会覆盖这些生成物：

- `$WORK/catalog/catalog.json`
- `$WORK/catalog/html/index.html`
- 受本次 catalog render 影响的 library/version HTML

它不会删除这些事实证据：

- `$WORK/config/library_registry.tsv`
- `$WORK/config/library_catalog.yml`
- `$WORK/scan_out/...`
- `$WORK/diff/...`
- `$WORK/file_diff/...`
- `$WORK/release/...`

所以它不会“打乱”已经完成的 scan/diff 证据，但会用当前 catalog 状态重新投影页面。
如果你手工改过生成 HTML 或 `catalog.json`，下一次 `cat --refresh-catalog --with-evidence` 会覆盖这些手改。
人工修正应写到 `library override`、registry 或 policy 里，不要改生成物。

面对很多库时，优先用单库命令：

```csh
$PROJ/scripts/lg.csh cat <LIBRARY> --refresh-catalog --with-evidence
```

第一次入库、registry/apply 后，需要提前跑一次 `cat --refresh-catalog`，否则
`library list` 没有 `$WORK/catalog/catalog.json` 可读。

如果 `cat` 后库数量从很多个突然变成 1 个，先不要继续扫描。真实来源通常不是 HTML，
而是当前正式清单 `$WORK/config/library_catalog.yml` 只剩一个库，或者被最近一次
`library apply` / `library add --apply` 用单库输入覆盖了。现在 `library apply` 和
`cat --refresh-catalog` 都会阻止 library count shrink 并保留旧文件；如果确实要删除
旧库，先人工修改 registry/library_catalog，再按错误信息确认，不要用普通扫描命令顺手覆盖。

快速检查：

```csh
grep '^  [^ ].*:$' $WORK/config/library_catalog.yml
python3 -c "import json; d=json.load(open('$WORK/catalog/catalog.json')); print(len(d.get('libraries', [])))"
```

### 事实源排查顺序

页面看起来不对时，按这个顺序排查：

```text
1. library_registry.tsv / library_catalog.yml：库是否还在正式清单里
2. catalog.json：版本是否被 catalog 识别
3. scan_out：目标版本是否有 scan evidence
4. diff：目标版本是否有相对正确 base 的 diff evidence
5. effective/window：当前有效版和候选窗口是否正确
6. HTML：是否只是投影陈旧
```

不要从第 6 步反推前 5 步；HTML 只是投影。

### 3.1 哪些命令会覆盖 HTML 报告

| 操作 | 会覆盖哪些页面 | 是否重跑 scan | 是否重跑 diff | 备注 |
| --- | --- | --- | --- | --- |
| `cat` | Catalog 首页和导航状态 | 否 | 否 | 只 render 已有 `catalog.json`；不会 discover，不会减少库 |
| `cat <LIBRARY>` | 该库最新版本的 Version Detail | 否 | 否 | 不刷新二层库工作台；不会 discover，不会减少库 |
| `cat --refresh-catalog --with-evidence` | Catalog 首页、library 页、version 页投影 | 否 | 否 | 低频全局 catalog 重建 |
| `cat <LIBRARY> --refresh-catalog --with-evidence` | 指定库二层工作台和相关 Version Detail | 否 | 否 | 推荐用于大库日常局部刷新；仍受 shrink guard 保护 |
| `cat <LIBRARY> <VERSION>` | 指定 Version Detail | 否 | 否 | 只重新投影页面，不更新证据 |
| `cat <LIBRARY> --update-detail` | update-detail 目标版本 | 按需 | 是 | 用上一有效版/当前有效版生成更新详情 |
| `scan <LIBRARY> <VERSION>` | 该版本 Version Detail、scan HTML | 是 | 否 | Catalog 导航页可能延迟刷新 |
| `scan <LIBRARY> <VERSION> --no-render` | 只更新 scan HTML | 是 | 否 | 诊断慢 scan；Version Detail 不刷新 |
| `cmp <LIBRARY> <VERSION> --base ...` | target Version Detail | 仅 `--scan-if-missing/--rescan` | 是 | 手动 compare/debug |
| `intake/accept-window/mark` | 受影响 Version Detail | 视命令而定 | 视命令而定 | Version Detail 是唯一审查投影 |
| `rv` / `rel --check-first` | 默认不刷新 Version Detail | 否 | 否 | 只做决策/放行检查 |

判断页面是否刚刷新，不要只看 Catalog 首页。优先看命令输出：

```text
render_summary.message
render_summary.open_first
render_summary.version_detail_htmls
render_summary.deferred_file
```

如果 `message` 是 `版本详情已刷新 ...；Catalog 导航页延迟刷新`，说明 Version Detail
已经更新；首页导航可由下一次普通 `cat` 基于已有 catalog 重渲染，或由显式
`cat --refresh-catalog ...` 重建 catalog 后再渲染。

库工作台如果看起来没有最新 scan/diff，不要先怀疑 scan 丢了。先检查：

```text
Version Detail 是否已刷新：render_summary.open_first
库工作台是否只是导航延迟：render_summary.deferred_file
当前有效版/最新待审版是否选择正确：库工作台第一屏
```

## 4. 人工确认版本关系

如果自动推断的 stage、base、package type、update scope 不可信，使用 override：

```csh
$PROJ/scripts/lg.csh library override <LIBRARY> <VERSION> --stage stable --base <BASE_VERSION>
$PROJ/scripts/lg.csh library override <LIBRARY> <VERSION> --package-type PARTIAL_UPDATE --update-scope lef,lib
```

不要直接手改生成后的 `catalog.json` 版本字段；下一次 render 可能重建。

## 5. 扫描版本

扫描单个版本：

```csh
$PROJ/scripts/lg.csh scan <LIBRARY> <VERSION>
```

只补缺少或过期的版本：

```csh
$PROJ/scripts/lg.csh scan <LIBRARY> --missing
```

扫描深度通过策略参数控制，不再选择多个 scan mode：

```csh
$PROJ/scripts/lg.csh scan <LIBRARY> <VERSION> --parse-file-types lef,cdl
$PROJ/scripts/lg.csh scan <LIBRARY> <VERSION> --parse-exclude-file-types verilog,liberty,spef
$PROJ/scripts/lg.csh scan <LIBRARY> <VERSION> --parse-jobs 8
```

正常 `scan` 会在完成后通过 Render Impact 自动刷新对应 Version Detail。命令输出里的
`render_summary.message` 会直接说明是否刷新，`render_summary.open_first` 是建议打开的
第一个详情页，例如：

```text
版本详情已刷新 1 个版本；Catalog 导航页延迟刷新
```

这表示 scan/cmp 热路径已经刷新 Version Detail；Catalog 首页和 library 导航页会写入
`render_deferred.json`，等下一次 `cat` 或显式 catalog refresh 再低频重建。日常审查先看 Version Detail，
不要把导航页延迟理解成扫描结果没有更新。

如果感觉 `scan <LIBRARY> <VERSION>` 很慢，先不要直接加深扫描。按下面顺序排查：

```csh
# 1. 只看短命令会展开成什么；正常 scan 不应额外触发 catalog refresh
$PROJ/scripts/lg.csh --dry-run scan <LIBRARY> <VERSION>

# 2. 诊断专用：只跑 scan + scan HTML，跳过 catalog/版本详情页刷新
$PROJ/scripts/lg.csh scan <LIBRARY> <VERSION> --no-render

# 3. 查看 scan 内部当前阶段、耗时和 parser 最慢文件
python3 -m json.tool <SCAN_DIR>/logs/scan_progress_latest.json
```

正常策略是 `hash-policy=smart`：大体量 `.lib/.db/.spef/.gds/.oas/.gz` 等不会默认读内容。
`--hash-policy full` 会强制读取文件内容生成 hash，面对真实工艺库通常会非常慢，只在
需要验证内容 hash 时临时使用：

```csh
$PROJ/scripts/lg.csh scan <LIBRARY> <VERSION> --hash-policy full --no-render
```

单次 `scan` 的 JSON 输出会包含 `phase_timings`，用于区分耗时来自 `scan_runner`、
`render_scan_html`、`update_catalog_scan_status` 还是 `render_impacted_catalog_html`。
如果使用 `--no-render`，输出会显示 `版本详情未刷新：no_catalog_render`；这时需要再
执行 `cat <LIBRARY> <VERSION>` 才会更新页面。

scan 完成后会写两类证据：

| 证据 | 面向对象 | 默认查看方式 |
| --- | --- | --- |
| `scan_out/**/*.json` | 机器流程和调试 | 不直接人工审查 |
| `scan_out/**/review/*.tsv` | 人工 review | Scan HTML / Version Detail 聚合 |

如果页面只显示数量但不知道文件在哪里，优先打开 `review/files_by_view.tsv`；
如果出现 unknown，打开 `review/unknown_files.tsv`。

## 6. 刷新版本详情页

```csh
$PROJ/scripts/lg.csh cat <LIBRARY>
$PROJ/scripts/lg.csh cat <LIBRARY> <VERSION>
$PROJ/scripts/lg.csh cat <LIBRARY> --update-detail
```

`cat <LIBRARY>` 只基于已有 `catalog.json` 刷新该库最新版本的 Version Detail，
不重新 discover，不写 `catalog.json`，也不覆盖 Catalog 首页。需要刷新 Catalog
首页导航时运行不带库名的 `cat`；如果你确实需要重新读取 `library_catalog.yml` 和
RAW 目录，使用：

```csh
$PROJ/scripts/lg.csh cat <LIBRARY> --refresh-catalog
```

`cat <LIBRARY> <VERSION>` 只重渲染一个版本详情页，不重新 scan，也不补齐其它
`versions/<VERSION>` 目录。已有的其它版本目录不会被删除；如果在一个新的 `$WORK`
里只跑这个命令，页面目录里只出现这个版本是正常的。

`cat <LIBRARY> --update-detail` 刷新 Version Review 的更新详情，默认使用
`current_effective`，没有当前有效库时退到 `previous_effective`。找不到可信 base
时页面会要求人工确认。

scan、cmp、intake、accept-window 和 mark 会通过 Render Impact 自动刷新受影响的
Version Detail 投影；不需要为了一个版本每次手动全量 `cat --full`。如果只想重新
打开某一个版本详情页，使用：

```csh
$PROJ/scripts/lg.csh cat <LIBRARY> <VERSION>
```

Version Detail 第一屏固定看五件事：接入判断、审查对象、对比上下文、View 变化、
证据状态。review window、candidate effective、compare manifest 只作为这个页面的
证据来源，不是新的主审查入口。

### 只有一个版本时

只有一个版本并不意味着页面应该空白。没有 base/diff 时，Version Detail 仍应展示：

- 版本和库名。
- scan 是否存在。
- View 覆盖矩阵。
- unknown 文件。
- summary-only / metadata-only 证据等级。
- 下一步是否需要建立 FULL baseline 或等待新版本。

此时状态应是“首版审查”或“缺少基准”，不能显示成“无变化”。
上下文证据，不是新的审查入口。

## 7. 结构对比

普通更新详情优先看版本详情页。需要手动 compare/debug 时再运行：

```csh
$PROJ/scripts/lg.csh cmp <LIBRARY> <VERSION> --base <BASE_VERSION> --scan-if-missing
```

如果 parser、policy 或 RAW 输入修正过，需要强制重扫：

```csh
$PROJ/scripts/lg.csh cmp <LIBRARY> <VERSION> --base <BASE_VERSION> --rescan
```

`adjacent` 只用于手动 compare 场景：

```csh
$PROJ/scripts/lg.csh cmp <LIBRARY> <VERSION> --mode adjacent --scan-if-missing
```

## 8. 深度文件对比

Version Review 会把文件变化分成不同 lane。默认只推荐小到中等规模、可直接阅读的文本
view 进入 `fd`：

```csh
$PROJ/scripts/lg.csh fd <LIBRARY> <VERSION> <REL_PATH> --base <BASE_VERSION>
```

显式指定类型：

```csh
$PROJ/scripts/lg.csh fd <LIBRARY> <VERSION> lef/ucie.lef --base <BASE_VERSION> --type lef
```

大文件、逻辑集合或二进制 metadata lane 不默认做深读。确实需要人工下钻时：

```csh
$PROJ/scripts/lg.csh fd <LIBRARY> <VERSION> rtl/top.v --base <BASE_VERSION> --type verilog --force-large
$PROJ/scripts/lg.csh fd <LIBRARY> <VERSION> db/top.db --base <BASE_VERSION> --type db --force-large
```

`--force-large` 只影响这一次手动 `fd`，不会改变 Version Review 或 pairwise 默认策略。
`summary-only` 和 `metadata-only` 是证据等级，不自动代表不完整，也不自动构成 blocker。

## 9. Review Gate 人工决策

Review Gate 只记录真正会阻塞 release 的问题和 owner 决策，不是多部门审批流。

```csh
$PROJ/scripts/lg.csh rv check  <LIBRARY> <VERSION> --gate current
$PROJ/scripts/lg.csh rv list   <LIBRARY> <VERSION> --gate current
$PROJ/scripts/lg.csh rv accept <LIBRARY> <VERSION> --item <ITEM_ID> --by <USER> --reason "..."
$PROJ/scripts/lg.csh rv waive  <LIBRARY> <VERSION> --item <ITEM_ID> --by <USER> --reason "..."
```

`current` 默认要求 blocking item 关闭，但不要求所有 File Diff recommendation 都完成。

## 10. Action 批处理

如果一个库需要重复执行一组 scan/diff/release，把动作写入：

```text
$WORK/actions/<library>.action
```

常用 action：

```text
@scan 20260627_asap7
@diff 20260627_asap7 base=20260624_asap7 scan_if_missing=true
@release 20260627_asap7
```

执行：

```csh
$PROJ/scripts/lg.csh action <LIBRARY>
```

Action 是人工编排记录，不是全自动 workflow engine。

## 11. Release 预检查和规划

```csh
$PROJ/scripts/lg.csh rel <LIBRARY> <VERSION>
$PROJ/scripts/lg.csh rel <LIBRARY> <VERSION> --explain
```

`rel <LIBRARY> <VERSION>` 默认先执行 release-check，再生成 symlink release 规划；
不会自动 apply。

正式 release 路径是扁平大写 View 目录，例如：

```text
LEF/
LIB/
RTL/
GDS/
```

raw 包里的 `upstream_xxx/lef/...`、`source_package/lef/...` 不会进入正式 release
路径。

## 12. 落地 Release 和覆盖

真正落地 release link：

```csh
$PROJ/scripts/lg.csh rel <LIBRARY> <VERSION> --apply
```

覆盖 manifest 中列出的已有目标文件：

```csh
$PROJ/scripts/lg.csh rel <LIBRARY> <VERSION> --apply --overwrite
```

`--overwrite` 只替换 manifest 中列出的目标文件，不会清空 release root 里的其他库文件。
只有完整组合 release 的 manifest 显式设置 `mirror_release_root=true` 时，才按 manifest
镜像删除未列出的旧文件。

## 13. Force Release

强制发布入口保留，但必须写明原因和操作者：

```csh
$PROJ/scripts/lg.csh rel <LIBRARY> <VERSION> --apply --force \
  --force-reason "owner accepted metadata-only change" \
  --force-by <USER>
```

底层会写入 `release_override.json`，用于审计这次绕过了哪些 gate/check 证据。

## 14. 常用排查

如果 csh/module 环境报 Python 冲突，例如：

```text
python/3.6.8 conflicts with currently loaded module python/3.11.10
```

直接指定 Python 可执行文件：

```csh
setenv LIB_GUARD_PYTHON /tools/dk/tools/python/python-3.11.10/bin/python3.11
$PROJ/scripts/lg.csh library discover
```

`LIB_GUARD_PYTHON` 必须是可执行文件路径，不是 module 名。

查看短命令展开，不执行：

```csh
$PROJ/scripts/lg.csh --dry-run scan <LIBRARY> <VERSION>
$PROJ/scripts/lg.csh --dry-run rel <LIBRARY> <VERSION>
```

查看帮助：

```csh
$PROJ/scripts/lg.csh --help
PYTHONPATH=src python3 -m lib_guard.cli --help
```

刷新页面后优先看：

```text
$WORK/catalog/html/index.html
$WORK/catalog/html/libraries/<LIBRARY_PAGE>/versions/<VERSION>/index.html
```
