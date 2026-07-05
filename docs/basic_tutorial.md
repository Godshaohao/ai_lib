Status: current

# 基础教程：从新库入库到 Release

这份教程是普通用户的主入口。只按这里走，就能完成：

```text
新库入库 -> catalog -> scan -> version review -> diff/fd -> review gate -> release
```

底层 `python -m lib_guard.cli` 是自动化和调试入口；日常使用优先用
`$PROJ/scripts/lg.csh`。

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

## 1. 新库入库

如果已经知道库根目录，直接写入人工确认 registry，并立即生成正式
`library_catalog.yml`：

```csh
$PROJ/scripts/lg.csh library add vendor_A.openroad_platform.openroad_asap7 \
  --root /path/to/vendor_A/openroad_asap7 \
  --vendor vendor_A \
  --display-name openroad_asap7 \
  --apply
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

大 RAW 树上不要把 discover 当成日常刷新。默认 discover 是浅层、有上限的候选发现：

```csh
$PROJ/scripts/lg.csh library discover --max-depth 4 --max-dirs 5000 --max-candidates 200
```

如果已经知道库根，优先用 `library add ... --apply`，不要递归扫整棵树。

discover 的最小规则是：

- RAW root 第一层 `Vendor*` 目录只当供应商分组，不作为库候选。
- 候选库根必须直接包含多个版本/交付实例目录。
- 版本/交付实例目录是搜索边界。
- `phys_ver`、`dft`、`lef`、`lib` 等版本内部 view/实现目录不会作为库候选。
- 同一个 resolved root 只输出一次；被更深层候选覆盖的祖先目录不会写进候选 TSV。
- 如果真实库结构是“版本目录在上、IP block 在下”的倒置结构，自动 discover 只能给出上层候选；
  具体 IP block 应通过 `library add <LIBRARY> --root <LIBRARY_ROOT> --apply` 人工确认。

## 2. 获取正式库名和版本名

不要手猜 `_` 和 `.`。命令里使用 catalog 认可的正式名字：

```csh
$PROJ/scripts/lg.csh library list
$PROJ/scripts/lg.csh library list vendor_A.openroad_platform.openroad_asap7 --versions
```

日常只需要两个名字：

- `LIBRARY`：例如 `vendor_A.openroad_platform.openroad_asap7`
- `VERSION`：例如 `20260627_asap7`

## 3. 生成 Catalog 页面

```csh
$PROJ/scripts/lg.csh cat --with-evidence
```

打开：

```text
$WORK/catalog/html/index.html
```

`cat --with-evidence` 会刷新 catalog 和轻量 evidence。面对很多库时，优先用单库命令：

```csh
$PROJ/scripts/lg.csh cat <LIBRARY> --with-evidence
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
$PROJ/scripts/lg.csh scan <LIBRARY> <VERSION> --hash-policy full
$PROJ/scripts/lg.csh scan <LIBRARY> <VERSION> --parse-jobs 8
```

## 6. 刷新版本详情页

```csh
$PROJ/scripts/lg.csh cat <LIBRARY> <VERSION>
$PROJ/scripts/lg.csh cat <LIBRARY> --update-detail
```

`cat <LIBRARY> <VERSION>` 只重渲染一个版本详情页，不重新 scan。

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
