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

先发现候选库，再人工审查 `library.list`，最后应用为正式
`library_catalog.yml`。

```csh
$PROJ/scripts/lg.csh library discover
gvim $WORK/config/library.list
$PROJ/scripts/lg.csh library apply
```

这一步不是全自动。目录命名、vendor/category/library 归属、需要忽略的候选项，
都应该由人确认后再 apply。

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
使用 `override` 写入人工确认。

```csh
$PROJ/scripts/lg.csh override <LIBRARY> <VERSION> --stage stable --base <BASE_VERSION>
$PROJ/scripts/lg.csh override <LIBRARY> <VERSION> --package-type PARTIAL_UPDATE --update-scope lef,lib
```

这一步会写入 catalog 的 manual override 状态。不要直接手改生成后的
`libraries[].versions[]`，因为它会在下一次 catalog render 时重建。

## 4. 扫描与对比

```csh
$PROJ/scripts/lg.csh scan <LIBRARY> <VERSION>
$PROJ/scripts/lg.csh cmp <LIBRARY> <VERSION> --base <BASE_VERSION> --scan-if-missing
```

使用规则：

- `--scan-if-missing`：只补缺少的 scan evidence，适合日常对比。
- `--rescan`：强制重扫，适合 parser、policy 或输入数据修正后刷新证据。

Version Review 是正常的单版本详情页；独立 `scan_html` 只作为 debug evidence。

## 5. 文件级 Diff

File Diff 是针对重点文件的下游审查，不是必须跑完整个库的进度条。

```csh
$PROJ/scripts/lg.csh fd <LIBRARY> <VERSION> <REL_PATH> --base <BASE_VERSION> --type <FILE_TYPE>
```

## 6. Review Gate 人工决策

Review Gate 只记录真正会阻塞 release 的问题和 owner 决策。

```csh
$PROJ/scripts/lg.csh rv-check  <LIBRARY> <VERSION> --gate current
$PROJ/scripts/lg.csh rv-list   <LIBRARY> <VERSION> --gate current
$PROJ/scripts/lg.csh rv-accept <LIBRARY> <VERSION> --item <ITEM_ID> --by <USER> --reason "..."
$PROJ/scripts/lg.csh rv-waive  <LIBRARY> <VERSION> --item <ITEM_ID> --by <USER> --reason "..."
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

Action 文件是人工编排入口，不是废弃功能。详见
[人工确认与 Action 流程](manual_confirmation_action.md)。

## 8. Release

```csh
$PROJ/scripts/lg.csh rel <LIBRARY> <VERSION> --check-first --link-mode symlink
```

Release 使用 manifest-driven file-level symlink/copy 规划。默认不会因为存在
File Diff recommendation 就阻塞 `current`，除非 release policy 明确要求。
