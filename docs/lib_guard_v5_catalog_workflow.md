# lib_guard v5 catalog 工作流

`catalog` 是 v5 的库资产入口。它先发现 raw root 下面有哪些库和版本，再驱动 scan、diff、HTML 控制台和 release dry-run。目标是让用户少拼长命令，先看一个总入口页面，再进入具体报告。

## 1. 发现库资产

```csh
python -m lib_guard.cli catalog scan \
  --root "$RAW_ROOT" \
  --out "$WORK/catalog" \
  --policy "$PROJ/configs/catalog_policy.json" \
  --render
```

输出：

```text
$WORK/catalog/catalog.json
$WORK/catalog/libraries/<library>.json
$WORK/catalog/reports/catalog_summary.json
$WORK/catalog/reports/scan_candidates.json
$WORK/catalog/reports/diff_candidates.json
$WORK/catalog/html/index.html
```

`catalog scan` 会写入：

- `manual_overrides`：人工修正的阶段、parent/base、release line。
- `runtime_state`：scan、diff、release check/link 的运行结果和 HTML 路径。
- `detected.inventory`：轻量文件类型统计，用来辅助判断目录是否真的是库版本。
- `detected.confidence`：名称、结构规则、文件证据综合后的识别置信度。

## 2. 配置真实目录结构

默认配置在：

```text
$PROJ/configs/catalog_policy.json
```

核心字段：

```json
{
  "library_type": "ip",
  "version_path_rules": [
    {"pattern": "{library}/{version}"},
    {"pattern": "bundles/{library}/releases/{version}"},
    {"pattern": "raw/{library}/{version}"}
  ],
  "marker_files": ["README.md", "VERSION", "release_note.txt"],
  "stage_rules": [
    {"match": "*initial*", "stage": "initial"},
    {"match": "*stable*", "stage": "stable"},
    {"match": "*final*", "stage": "final"},
    {"match": "*ad-hoc*", "stage": "ad-hoc"}
  ]
}
```

真实环境里建议先把 UCIe 的目录模式补进 `version_path_rules`。如果配置了结构规则，catalog 会优先按结构规则识别，避免把 `bundles`、`releases` 这类中间目录误判成库名。

## 3. 查看资产入口 HTML

打开：

```text
$WORK/catalog/html/index.html
```

这个页面是总入口。版本矩阵里会显示：

- 原始路径
- 阶段和识别状态
- scan 状态和 Scan HTML 链接
- Console HTML 链接
- adjacent/cumulative diff HTML 链接
- release check/link JSON 链接
- parent/base 推导结果
- 下一步推荐动作

后续不需要记住多个 HTML 的路径，优先从 catalog HTML 跳转。

## 4. 人工修正误判

如果阶段或 parent/base 不准：

```csh
python -m lib_guard.cli catalog override \
  --catalog "$WORK/catalog/catalog.json" \
  --version ip/ucie/ad-hoc_fix_20250612 \
  --stage ad-hoc \
  --parent stable_20250608 \
  --base stable_20250608 \
  --note "人工确认该 ad-hoc 归属 stable_20250608"
```

重新生成入口页：

```csh
python -m lib_guard.cli catalog render \
  --catalog "$WORK/catalog/catalog.json" \
  --out "$WORK/catalog/html"
```

## 5. 单版本扫描

```csh
python -m lib_guard.cli run \
  --catalog "$WORK/catalog/catalog.json" \
  --library ucie \
  --version stable_20250608 \
  --workdir "$WORK" \
  --mode signature \
  --parse-jobs 4 \
  --skip-cache
```

这个命令会执行：

- scan
- summary rebuild
- scan HTML
- console HTML
- 回写 `runtime_state.<version>.scan`

## 6. 批量扫描

扫描还没有跑过的 stable 版本：

```csh
python -m lib_guard.cli run-batch \
  --catalog "$WORK/catalog/catalog.json" \
  --library ucie \
  --stage stable \
  --only-missing \
  --limit 20 \
  --workdir "$WORK" \
  --mode signature \
  --parse-jobs 4
```

建议第一次先加 `--limit 5` 或 `--limit 20`，确认速度和结果后再扩大范围。

## 7. 单版本 diff

相邻比较：

```csh
python -m lib_guard.cli compare \
  --catalog "$WORK/catalog/catalog.json" \
  --library ucie \
  --new stable_20250608 \
  --mode adjacent \
  --workdir "$WORK"
```

累计比较：

```csh
python -m lib_guard.cli compare \
  --catalog "$WORK/catalog/catalog.json" \
  --library ucie \
  --new final_20250610 \
  --mode cumulative \
  --workdir "$WORK"
```

diff 会回写：

```text
runtime_state.<version>.diff.adjacent_diff_dir
runtime_state.<version>.diff.adjacent_diff_html
```

## 8. 批量 diff

只比较 old/new 都已经扫描完成的版本：

```csh
python -m lib_guard.cli compare-batch \
  --catalog "$WORK/catalog/catalog.json" \
  --library ucie \
  --mode adjacent \
  --only-ready \
  --only-pending \
  --limit 20 \
  --workdir "$WORK"
```

`compare` 和 `compare-batch` 即使发现 diff blocker，也会尽量生成 JSON 和 HTML。风险状态写在 diff 报告里，便于审计人员打开查看。

## 9. 从 catalog 做 release check

不带 diff gate：

```csh
python -m lib_guard.cli catalog release-check \
  --catalog "$WORK/catalog/catalog.json" \
  --library ucie \
  --version stable_20250608 \
  --policy "$PROJ/configs/release_policy.json"
```

带相邻 diff gate：

```csh
python -m lib_guard.cli catalog release-check \
  --catalog "$WORK/catalog/catalog.json" \
  --library ucie \
  --version stable_20250608 \
  --policy "$PROJ/configs/release_policy.json" \
  --diff-mode adjacent
```

结果会写到：

```text
<scan_dir>/release/release_check.json
runtime_state.<version>.release.check_status
runtime_state.<version>.release.check_json
```

## 10. 从 catalog 做 release link dry-run

默认是 dry-run：

```csh
python -m lib_guard.cli catalog release-link \
  --catalog "$WORK/catalog/catalog.json" \
  --library ucie \
  --version stable_20250608 \
  --release-root "$WORK/release_area" \
  --policy "$PROJ/configs/release_policy.json"
```

真正发布需要显式加 `--apply`：

```csh
python -m lib_guard.cli catalog release-link \
  --catalog "$WORK/catalog/catalog.json" \
  --library ucie \
  --version stable_20250608 \
  --release-root "$WORK/release_area" \
  --policy "$PROJ/configs/release_policy.json" \
  --apply
```

强制发布仍然要求审计原因：

```csh
python -m lib_guard.cli catalog release-link \
  --catalog "$WORK/catalog/catalog.json" \
  --library ucie \
  --version stable_20250608 \
  --release-root "$WORK/release_area" \
  --policy "$PROJ/configs/release_policy.json" \
  --apply \
  --force \
  --force-reason "人工签核通过，允许本次临时发布"
```

## 11. 常见问题

### 目录识别误判

先看 `catalog.json` 里对应版本的：

```text
detected.structure_rule
detected.inventory.file_type_counts
detected.confidence
```

如果中间目录被识别成库名，优先补 `version_path_rules`，再重新运行 `catalog scan`。

### catalog HTML 没有跳转链接

说明该版本还没有对应运行结果。先跑：

```csh
python -m lib_guard.cli run --catalog "$WORK/catalog/catalog.json" --library ucie --version <version> --workdir "$WORK"
```

再重新渲染：

```csh
python -m lib_guard.cli catalog render --catalog "$WORK/catalog/catalog.json" --out "$WORK/catalog/html"
```

### release link 看起来没有发布

检查输出状态：

- `DRY_RUN`：没有加 `--apply`，只是预演。
- `BLOCKED`：release gate 没过。
- `DONE`：发布动作已执行。
- `FORCED_DONE`：gate 没过但使用了强制发布。

### 大量版本跑不动

先用批量命令的 `--limit` 小步跑：

```csh
python -m lib_guard.cli run-batch --catalog "$WORK/catalog/catalog.json" --library ucie --only-missing --limit 10
```

确认后再提高 limit。后续可以继续扩展 `--jobs` 做多进程批量调度。
