# lib_guard v5 diff/release/html incremental notes

## v6 Selected Diff And File Diff Update

The current diff/release/html flow includes the v6 navigation and recommendation model:

- Catalog no longer directly enters File Diff.
- Diff Timeline groups comparisons before one Selected Diff is opened.
- Selected Diff owns the key File Diff recommendation queue.
- File Diff is not a completion model and should not render `File Diff 2/5` or `done/total`.
- Large or ambiguous changes require base/comparison confirmation before command generation.
- File Diff output includes `summary.json`, `semantic_diff.json`, `raw_text_diff.html`, and `index.html`.

New pairwise types:

```text
waiver
ibis
pwl
snp
cpm
```

Semantic parser upgrades:

- Liberty: `is_macro`, `is_pad`, and cell attributes.
- SDC: clocks, generated clocks, uncertainty, loads, driving cells, IO delays, and grouping/exception command evidence.
- UPF: power domains, supply nets/ports, domain supply, isolation, level shifters, retention, and power-state evidence.

本说明对应旧增量包 `lib_guard_v5_diff_raw_p2_incremental.part001-of002.json` 和 `lib_guard_v5_diff_raw_p2_incremental.part002-of002.json` 之后的新一轮增量修改。

## 本次增量文件

- `src/lib_guard/cli.py`
- `src/lib_guard/release/linker.py`
- `src/lib_guard/render/control_console.py`
- `src/lib_guard/render/diff_report.py`
- `src/lib_guard/test/test_v5_scan_pipeline.py`
- `docs/lib_guard_v5_diff_release_html_incremental_usage.md`

## 修改说明

### 1. Diff HTML

新增 `lib_guard.render.diff_report.render_diff_html()`，用于把 `diff scan`、`diff adjacent` 或 `diff cumulative` 生成的 `diff_output` 渲染为 HTML。

新增 CLI:

```csh
python -m lib_guard.cli diff render \
  --diff "$WORK/diff_adjacent_hotfix_v1_0_1" \
  --out "$WORK/diff_html_hotfix_v1_0_1"
```

输出入口：

```text
$WORK/diff_html_hotfix_v1_0_1/index.html
```

页面主要展示：

- `Diff Overview`：整体 diff 状态、风险等级、文件变化数、对象变化数、breaking changes、manual review 数。
- `Version Relation`：相邻版本、累计版本或显式版本对比关系。
- `File Diff`：基于 `file_inventory.json` 的文件新增、删除、内容 hash 变化、metadata-only 变化。
- `Component Diff`：组件级状态、channel、required view 变化。
- `LEF / Verilog / Liberty ParserResult Evidence`：基于 `parser_result_diff` 的对象级证据。
- `Release Readiness Diff`：发布准入状态变化。
- `Review Items`：需要人工处理的 diff blocker/warning。

### 2. Parser 结果与 diff 的关系

Parser 结果是 diff 的结构化事实源。

- `parser_results/<type>/*.json`：保存单次 scan 的对象事实，例如 LEF macro/pin、Verilog module/port、Liberty cell/pin。
- `parser_result_diff/*.json`：保存两个 scan 之间的对象级变化。
- `diff_issues.json`：把对象级变化提升为 release 风险项，例如 port removed、cell pin removed、macro pin removed。
- `diff HTML`：把上述对象级变化展示为可审计页面。

因此：

```text
scan HTML = 一个版本自己的扫描快照
diff HTML = 两个版本之间的结构化变化和 release 风险
```

### 3. 强制 release

`release link` 现在支持在 gate 被 BLOCK/FAILED 时强制发布，但必须显式提供原因，并且必须真正执行 `--apply`。

```csh
python -m lib_guard.cli release link \
  --scan "$WORK/scan_hotfix_v1_0_1" \
  --release-root "$WORK/release_area" \
  --alias current \
  --policy "$PROJ/configs/release_policy.json" \
  --apply \
  --force \
  --force-reason "manual waiver approved for emergency hotfix"
```

限制：

- `--force` 必须配合 `--force-reason`。
- `--force` 必须配合 `--apply`。
- 强制发布会写入 `release/release_override.json`，用于审计。
- 如果 gate 没过但强制发布，状态返回 `FORCED_DONE`。

### 4. Console 文案修正

`control_console.py` 修正了之前中文乱码和难理解标题，当前主要模块名为：

- `Library Overview / 库基本信息`
- `Flow Status / 流程状态`
- `Run Statistics / 本次扫描统计`
- `Recommended Actions / 建议处理动作`
- `Run History / 运行历史`
- `Manual Review Items / 待人工确认项`

## 完整使用流程

### 1. 设置环境

```csh
setenv PROJ /path/to/ai_lib
setenv RAW /path/to/raw_library
setenv WORK /path/to/work
setenv LIB_TYPE ip
setenv LIB_NAME demo
setenv LIB_VER v1_0_1
setenv MODE release
cd $PROJ
setenv PYTHONPATH $PROJ/src
```

### 2. 扫描当前版本

```csh
python -m lib_guard.cli scan \
  --root "$RAW" \
  --profile "$LIB_TYPE" \
  --name "$LIB_NAME" \
  --version "$LIB_VER" \
  --mode "$MODE" \
  --out "$WORK/scan_hotfix_v1_0_1" \
  --workdir "$WORK" \
  --parse-jobs 4 \
  --skip-cache \
  --progress-interval 1
```

查看扫描状态：

```csh
python -m lib_guard.cli scan status \
  --scan "$WORK/scan_hotfix_v1_0_1"
```

### 3. 重建 summary

全部重建：

```csh
python -m lib_guard.cli summary rebuild \
  --scan "$WORK/scan_hotfix_v1_0_1" \
  --all
```

按类型重建：

```csh
python -m lib_guard.cli summary rebuild \
  --scan "$WORK/scan_hotfix_v1_0_1" \
  --type lef
```

### 4. 生成 scan HTML

```csh
python -m lib_guard.cli render \
  --scan "$WORK/scan_hotfix_v1_0_1" \
  --out "$WORK/scan_html_hotfix_v1_0_1"
```

输出：

```text
$WORK/scan_html_hotfix_v1_0_1/index.html
```

### 5. 生成 console HTML

```csh
python -m lib_guard.cli console build \
  --scan "$WORK/scan_hotfix_v1_0_1" \
  --out "$WORK/console_hotfix_v1_0_1" \
  --config-dir "$PROJ/configs"
```

输出：

```text
$WORK/console_hotfix_v1_0_1/index.html
```

### 6. 注册版本

首次 full 版本：

```csh
python -m lib_guard.cli version register \
  --scan "$WORK/scan_full_v1_0_0" \
  --library-id "$LIB_TYPE/$LIB_NAME/v1_0_0" \
  --version-id v1_0_0 \
  --version-type full \
  --release-line main \
  --workdir "$WORK" \
  --overwrite
```

hotfix 版本：

```csh
python -m lib_guard.cli version register \
  --scan "$WORK/scan_hotfix_v1_0_1" \
  --library-id "$LIB_TYPE/$LIB_NAME/v1_0_1" \
  --version-id v1_0_1 \
  --version-type hotfix \
  --release-line main \
  --parent-version v1_0_0 \
  --base-version v1_0_0 \
  --workdir "$WORK" \
  --overwrite
```

### 7. 生成 diff

显式对比：

```csh
python -m lib_guard.cli diff scan \
  --old "$WORK/scan_full_v1_0_0" \
  --new "$WORK/scan_hotfix_v1_0_1" \
  --out "$WORK/diff_hotfix_v1_0_1" \
  --diff-mode explicit \
  --old-version-type full \
  --new-version-type hotfix \
  --release-line main \
  --parent-version v1_0_0 \
  --base-version v1_0_0
```

按版本索引做相邻版本对比：

```csh
python -m lib_guard.cli diff adjacent \
  --library-id "$LIB_TYPE/$LIB_NAME/v1_0_1" \
  --new-version v1_0_1 \
  --workdir "$WORK" \
  --out "$WORK/diff_adjacent_hotfix_v1_0_1"
```

按 base version 做累计对比：

```csh
python -m lib_guard.cli diff cumulative \
  --library-id "$LIB_TYPE/$LIB_NAME/v1_0_1" \
  --new-version v1_0_1 \
  --workdir "$WORK" \
  --out "$WORK/diff_cumulative_hotfix_v1_0_1"
```

### 8. 生成 diff HTML

```csh
python -m lib_guard.cli diff render \
  --diff "$WORK/diff_adjacent_hotfix_v1_0_1" \
  --out "$WORK/diff_html_hotfix_v1_0_1"
```

输出：

```text
$WORK/diff_html_hotfix_v1_0_1/index.html
```

### 9. release check

不带 diff gate：

```csh
python -m lib_guard.cli release check \
  --scan "$WORK/scan_hotfix_v1_0_1" \
  --policy "$PROJ/configs/release_policy.json"
```

带 diff gate：

```csh
python -m lib_guard.cli release check \
  --scan "$WORK/scan_hotfix_v1_0_1" \
  --diff "$WORK/diff_adjacent_hotfix_v1_0_1" \
  --policy "$PROJ/configs/release_policy.json"
```

### 10. release link

先 dry-run：

```csh
python -m lib_guard.cli release link \
  --scan "$WORK/scan_hotfix_v1_0_1" \
  --release-root "$WORK/release_area" \
  --alias current \
  --policy "$PROJ/configs/release_policy.json"
```

真正落地：

```csh
python -m lib_guard.cli release link \
  --scan "$WORK/scan_hotfix_v1_0_1" \
  --release-root "$WORK/release_area" \
  --alias current \
  --policy "$PROJ/configs/release_policy.json" \
  --apply
```

强制落地：

```csh
python -m lib_guard.cli release link \
  --scan "$WORK/scan_hotfix_v1_0_1" \
  --release-root "$WORK/release_area" \
  --alias current \
  --policy "$PROJ/configs/release_policy.json" \
  --apply \
  --force \
  --force-reason "manual waiver approved for emergency hotfix"
```

## 测试方案

### 1. 语法检查

```csh
python -m compileall -q "$PROJ/src/lib_guard"
```

### 2. 单元测试

```csh
python -m unittest discover -s "$PROJ/src/lib_guard/test" -p "test*.py"
```

期望：

```text
Ran 60 tests
OK
```

### 3. Diff HTML 定向测试

```csh
python -m unittest src.lib_guard.test.test_v5_scan_pipeline.V5ScanPipelineTest.test_diff_render_writes_html_with_parser_result_evidence
```

期望：

```text
OK
```

### 4. CLI help smoke test

```csh
python -m lib_guard.cli diff render --help
python -m lib_guard.cli release link --help
```

期望：

- `diff render` 显示 `--diff` 和 `--out`。
- `release link` 显示 `--force` 和 `--force-reason`。

### 5. 真实流程 smoke test

建议最小样例准备两个 scan：

- old 版本包含一个 Verilog module，端口为 `a` 和 `data[31:0]`。
- new 版本删除 `a`，把 `data` 改为 `[63:0]`。

然后执行：

```csh
python -m lib_guard.cli diff scan \
  --old "$WORK/old_scan" \
  --new "$WORK/new_scan" \
  --out "$WORK/diff_smoke" \
  --diff-mode explicit

python -m lib_guard.cli diff render \
  --diff "$WORK/diff_smoke" \
  --out "$WORK/diff_smoke_html"
```

检查 `$WORK/diff_smoke_html/index.html` 中应出现：

- `Diff Overview`
- `Verilog ParserResult Evidence`
- `port removed`

## 可能遇到的问题

### 1. `python` 命令不可用

如果内网机器没有把 Python 加到 PATH，需要用真实 Python 路径执行，或先设置别名。关键是保证：

```csh
python -c "import sys; print(sys.version)"
```

可运行。

### 2. `ModuleNotFoundError: No module named lib_guard`

需要设置：

```csh
setenv PYTHONPATH "$PROJ/src"
```

### 3. `diff render` 页面没有 ParserResult Evidence

通常是 diff 目录里没有对象 diff：

```text
$WORK/diff_xxx/parser_result_diff/verilog_diff.json
$WORK/diff_xxx/parser_result_diff/lef_diff.json
$WORK/diff_xxx/parser_result_diff/liberty_diff.json
```

需要确认 scan 阶段已生成 parser 结果，并且 diff 是在两个有效 scan output 之间执行的。

### 4. `release link --apply` 看起来没有发布

先看命令返回 JSON：

- `status=DRY_RUN`：说明没有加 `--apply`。
- `status=BLOCKED`：说明 release gate 没过。
- `status=DONE`：正常发布。
- `status=FORCED_DONE`：强制发布成功。

如果被 gate 拦截，需要先处理 blocker，或使用带审计原因的强制发布命令。

### 5. `--force` 报错

强制发布必须同时满足：

```text
--apply
--force
--force-reason "..."
```

缺少任意一个都会报错，这是为了避免误发布。

### 6. HTML 里中文乱码

本次已修正新增 HTML 和 console 的主要乱码。若浏览器仍显示乱码，确认文件是 UTF-8，并通过本地浏览器打开 `index.html`，不要经过会改编码的中间工具。

### 7. Diff 误报

如果输入 scan 的 parser 结果不完整，object diff 也会不完整。先用：

```csh
python -m lib_guard.cli scan status --scan "$WORK/scan_xxx"
```

检查：

- `parser_task_list`
- `parser_manifest`
- `parser_results_json`
- `parser_results_dir`
- `parser_quality`

这些输出是否存在。
