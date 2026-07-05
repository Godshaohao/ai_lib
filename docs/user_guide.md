Status: current

# 用户使用指南

日常工作请使用短命令 wrapper：

```csh
setenv PROJ /path/to/ai_lib/repo
setenv WORK $PROJ/work/review
setenv RAW  /path/to/raw_delivery

$PROJ/scripts/lg.csh init $WORK --raw-root $RAW --library-type ip
```

## 1. 建立并确认 Library Map

如果已经知道库根，直接加入人工确认 registry：

```csh
$PROJ/scripts/lg.csh library add vendor_A.openroad_platform.openroad_asap7 \
  --root /path/to/vendor_A/openroad_asap7 \
  --vendor vendor_A \
  --display-name openroad_asap7 \
  --apply
```

如果不知道库根，先生成候选快照，再只把人工确认 OK 的候选合并进 registry：

```csh
$PROJ/scripts/lg.csh library discover
gvim $WORK/config/library_candidates/latest.tsv
$PROJ/scripts/lg.csh library accept
$PROJ/scripts/lg.csh library apply
```

这一步不是全自动。目录命名、vendor/category/library 归属、需要忽略的候选项，
都应该由人确认后再 apply。稳定人工确认文件是
`$WORK/config/library_registry.tsv`；`library discover` 只写候选快照，不覆盖
这个 registry。

日常命令只需要两个名字：

- 库名：命令里复制使用，例如 `vendor_A.openroad_platform.openroad_asap7`。
- 版本名：原始版本目录名，例如 `20260627_asap7`。

不要手猜 `_` 和 `.`。用下面命令查看当前 catalog 认可的库名和版本名：

```csh
$PROJ/scripts/lg.csh library list
$PROJ/scripts/lg.csh library list vendor_A.openroad_platform.openroad_asap7 --versions
```

## 2. 刷新 Catalog

```csh
$PROJ/scripts/lg.csh cat --with-evidence
```

刷新后打开：

```text
$WORK/catalog/html/index.html
```

## 3. 人工确认版本关系

如果 catalog 自动推断的 stage、base、package type、update scope 不可信，
使用 `library override` 写入人工确认。

```csh
$PROJ/scripts/lg.csh library override <LIBRARY> <VERSION> --stage stable --base <BASE_VERSION>
$PROJ/scripts/lg.csh library override <LIBRARY> <VERSION> --package-type PARTIAL_UPDATE --update-scope lef,lib
```

这一步会写入 catalog 的 manual override 状态。不要直接手改生成后的
`libraries[].versions[]`，因为它会在下一次 catalog render 时重建。

## 4. 扫描与更新详情

```csh
$PROJ/scripts/lg.csh scan <LIBRARY> <VERSION>
$PROJ/scripts/lg.csh cat <LIBRARY> --update-detail
# 手动 compare/debug 时再显式指定 base 或 adjacent/cumulative
$PROJ/scripts/lg.csh cmp <LIBRARY> <VERSION> --base <BASE_VERSION> --scan-if-missing
```

使用规则：

- `scan`：只有一种用户态动作。扫描深度通过策略配置，不再选择多个 mode。
- 常用策略：`--parse-file-types lef,cdl`、`--parse-exclude-file-types verilog,liberty,spef`、
  `--hash-policy smart/full`、`--parse-jobs 8`。
- `$WORK/lib_guard.yml` 中的策略是默认值；短命令上的同名策略参数只覆盖本次扫描。
- `cat <LIBRARY> --update-detail`：刷新 Version Review 的日常更新详情，默认先使用 `current_effective`，
  没有当前有效库时再使用 `previous_effective`。
- `cmp`：手动 structural compare/debug，适合显式指定 base 或 adjacent/cumulative。
- `--scan-if-missing`：只补缺少或已过期的 scan evidence，适合手动对比。
- catalog 会保存每个版本输入文件的轻量指纹；RAW 版本内容变化后，旧 scan 会标记为 `STALE_SCAN`，`--scan-if-missing` 会重新补扫。
- `--rescan`：强制重扫，适合 parser、policy 或输入数据修正后刷新证据。

Version Review 是正常的单版本详情页；独立 `scan_html` 只作为 debug evidence。

## 5. 文件级 Diff

File Diff 是针对重点文件的下游审查，不是必须跑完整个库的进度条。

```csh
$PROJ/scripts/lg.csh fd <LIBRARY> <VERSION> <REL_PATH> --base <BASE_VERSION> --type <FILE_TYPE>
```

Version Review 中的 File Diff lane 表示审查方式：

- 推荐 File Diff：适合直接阅读的小到中等文本视图，可以用 `fd` 做手动 file drill-down。
- `summary-only`：大型逻辑视图已经通过 summary/count/corner evidence 审查，不是漏跑。
- `metadata-only`：二进制、layout、database 视图已经通过 hash、size、path、count
  等 metadata evidence 审查，不是漏跑。

`--force-large` 只用于专家显式手动 `fd`。它表示人工接受大文件、集合文件或二进制
metadata lane 的下钻成本，不会影响 `cat --update-detail`、`cmp` 或自动 pairwise 推荐。

## 6. Review Gate 人工决策

Review Gate 只记录真正会阻塞 release 的问题和 owner 决策。

```csh
$PROJ/scripts/lg.csh rv check  <LIBRARY> <VERSION> --gate current
$PROJ/scripts/lg.csh rv list   <LIBRARY> <VERSION> --gate current
$PROJ/scripts/lg.csh rv accept <LIBRARY> <VERSION> --item <ITEM_ID> --by <USER> --reason "..."
$PROJ/scripts/lg.csh rv waive  <LIBRARY> <VERSION> --item <ITEM_ID> --by <USER> --reason "..."
```

`current` 默认要求 blocking item 关闭，但不要求所有 File Diff recommendation
都完成。`approved` 可以按 policy 设置更严格条件。

## 7. Action 文件批处理

当一个库需要重复执行多步 scan/diff/effective/release 时，把动作写入：

```text
$WORK/actions/<library>.action
```

然后执行：

```csh
$PROJ/scripts/lg.csh action <LIBRARY>
```

Action 文件是当前人工编排入口。详见
[人工确认与 Action 流程](manual_confirmation_action.md)。

## 8. Release

```csh
$PROJ/scripts/lg.csh rel <LIBRARY> <VERSION>
$PROJ/scripts/lg.csh rel <LIBRARY> <VERSION> --explain
```

`rel <LIBRARY> <VERSION>` 默认先执行 release-check，再生成 symlink release 规划；
不会自动 apply。Release 使用 manifest-driven file-level symlink/copy 规划，正式目录是扁平大写
View 目录，例如 `LEF/`、`LIB/`、`RTL/`、`GDS/`。raw 包里的
`upstream_xxx/lef/...`、`source_package/lef/...` 这类包装目录不会进入正式
release 路径。

`--overwrite` 只替换 manifest 中列出的目标文件，不会清空 release root 中其他
库文件。只有完整组合 release 的 manifest 显式设置 `mirror_release_root=true`
时，才按 manifest 镜像删除未列出的旧文件。默认不会因为存在 File Diff
recommendation 就阻塞 `current`，除非 release policy 明确要求。

`--explain` 只输出 release check 的阻塞解释，不执行 link/apply。强制发布入口仍然
保留，但必须显式写明原因：

```csh
$PROJ/scripts/lg.csh rel <LIBRARY> <VERSION> --force --force-reason "owner accepted metadata-only change" --force-by <USER>
```

底层 `release-batch` 会把 force 决策写入 `release_override.json`，用于审计这次
绕过了哪些 gate/check 证据。
