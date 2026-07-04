Status: current

# 人工确认与 Action 流程

`lib_guard` 不是全自动发布工具。它会自动生成 catalog、scan、diff、parser、
release evidence 和 HTML 页面，但以下判断必须由人确认。

## 人工确认点

| 阶段 | 人工确认内容 | 命令/文件 |
| --- | --- | --- |
| Library Map | 哪些候选目录是真正的库，vendor/category/library 如何归属 | `lg.csh library add` 或 `lg.csh library discover` 后确认 `$WORK/config/library_candidates/latest.tsv`，再合并到 `$WORK/config/library_registry.tsv` |
| 版本关系 | stage、base、package type、update scope、是否 current effective | `lg.csh library override` |
| Review Gate | blocking item 是否 accept/waive | `lg.csh rv accept` / `lg.csh rv waive` |
| Action 编排 | 哪些版本需要 scan、哪些 effective 组合需要构建、哪些 diff/release 要跑 | `$WORK/actions/<library>.action` |

## Library Map 确认

```csh
$PROJ/scripts/lg.csh library add vendor_A.openroad_platform.openroad_asap7 --root /path/to/vendor_A/openroad_asap7
$PROJ/scripts/lg.csh library apply
```

不知道库根时：

```csh
$PROJ/scripts/lg.csh library discover
gvim $WORK/config/library_candidates/latest.tsv
$PROJ/scripts/lg.csh library accept
$PROJ/scripts/lg.csh library apply
```

`library discover` 只负责发现候选项，不覆盖人工确认 registry；`library accept`
只合并候选 TSV 中标为 OK/ENABLE 的行；`library apply` 只从
`$WORK/config/library_registry.tsv` 生成正式 `library_catalog.yml`。

## 版本关系 Override

当自动推断结果不可信时，用 `library override` 固化人工判断：

```csh
$PROJ/scripts/lg.csh library override sky130ram 20260626_sky130ram_update \
  --stage stable \
  --base 20260619_sky130ram \
  --package-type PARTIAL_UPDATE \
  --update-scope lef,lib \
  --note "Confirmed by library owner."
```

常见使用场景：

- 自动 stage 识别错误。
- base 版本无法可靠推断。
- 更新包是 partial/hotfix/doc update，不应按 full package 处理。
- 某个版本需要标记为 manual review。

## Review Gate 决策

先查看 gate：

```csh
$PROJ/scripts/lg.csh rv check <LIBRARY> <VERSION> --gate current
$PROJ/scripts/lg.csh rv list  <LIBRARY> <VERSION> --gate current
```

再由 owner 记录决策：

```csh
$PROJ/scripts/lg.csh rv accept <LIBRARY> <VERSION> \
  --item metadata.db.changed:db/ucie.db \
  --by lib_owner \
  --reason "DB hash change accepted for current."

$PROJ/scripts/lg.csh rv waive <LIBRARY> <VERSION> \
  --item doc.release_note.missing \
  --by lib_owner \
  --reason "Release note waived for internal test drop."
```

这些决策写入：

```text
$WORK/review/<library>/<version>/review_overrides.json
$WORK/review/<library>/<version>/review_gate.json
```

## Action 文件

Action 文件用于把人工确定的一组动作稳定记录下来，适合重复执行或团队交接。

默认位置：

```text
$WORK/actions/<library>.action
```

示例：

```text
@effect rec_20260624 lib1 lib2 lib3
@scan auto lib4
@diff current rec_20260624 main
@release rec_20260624
```

执行：

```csh
$PROJ/scripts/lg.csh action <LIBRARY>
```

## Action 语法

| Action | 含义 |
| --- | --- |
| `@effect NAME VERSION...` | 用多个 raw version 构建一个推荐组合 |
| `@scan auto VERSION...` | 扫描版本；`auto` 会展开 `@effect` 使用到的版本 |
| `@rescan VERSION...` | 强制重扫，即使已有 scan evidence |
| `@diff OLD NEW NAME` | 对比两个 raw/effective target；已有输出则跳过 |
| `@rediff OLD NEW NAME` | 强制重新对比 |
| `@release TARGET` | 生成 release preview；已有输出则跳过 |
| `@rerelease TARGET` | 强制重新生成 release preview |
| `@ALL redo` | 强制重做文件中所有动作 |

默认策略是保守的：已有输出时跳过，避免误覆盖人工审查证据。

Action 语法只保留上表动词。`@ALL redo` 会在 action plan 中标记
`force_all_redo: true`，并提示所有既有输出都可能被重新生成。

以下 workflow 风格动词不是 Action 语法的一部分，也不会被支持：
`@if`、`@depends`、`@retry`、`@group`、`@include`、`@owner`、
`@approve`、`@loop`、`@notify`。

## 自动化与人工边界

自动化会做：

- 发现候选库和版本。
- 扫描文件、解析可解析格式、统计 count-only 文件。
- 生成 Version Review、Comparison Review、File Diff 和 release evidence。
- 给出建议和 gate 状态。

人工必须做：

- 确认 library map。
- 确认不可靠的 base/stage/package 关系。
- 对 blocking item 做 accept/waive。
- 决定 action 文件中应该批量执行哪些动作。
