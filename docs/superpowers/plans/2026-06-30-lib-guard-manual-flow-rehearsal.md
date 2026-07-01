# Lib Guard Manual Flow Rehearsal Implementation Plan

Status: current

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 演练 `lib_guard` 从 raw 工艺库发现、人工确认、catalog、scan、refresh、cmp、fd、Review Gate 到 release preview 的完整手动流程。

**Architecture:** 使用仓库内 OpenROAD fixture 作为 raw 输入，在 `work/manual_flow_rehearsal` 创建全新的 workspace，避免污染当前 `work/openroad_manual_review`。日常入口只使用 `scripts/lg.csh`，底层 `python -m lib_guard.cli` 只用于 dry-run 观察展开命令。

**Tech Stack:** csh wrapper, Python 3.11/3, `lib_guard.short_cli`, static HTML catalog/version detail pages, OpenROAD ASAP7/SKY130RAM fixture data.

---

## 文件与目录职责

- Read: `scripts/lg.csh`，日常命令入口，自动选择 `python3.11`、`python3` 或 `python`。
- Read: `docs/command_surface.md`，确认推荐命令面和人工边界。
- Read: `docs/manual_confirmation_action.md`，确认 library map、override、Review Gate、action 的人工步骤。
- Read: `docs/review_gate.md`，确认 gate 检查和 accept/waive 命令。
- Input: `tests/fixtures/raw`，本次演练 raw root。
- Create: `work/manual_flow_rehearsal/lib_guard.yml`，本次演练 workspace 配置。
- Create/Edit: `work/manual_flow_rehearsal/config/library.list`，人工确认后的 library map。
- Create: `work/manual_flow_rehearsal/catalog/catalog.json`，catalog 数据源。
- Create: `work/manual_flow_rehearsal/catalog/html/index.html`，catalog 首页。
- Create: `work/manual_flow_rehearsal/catalog/html/libraries/.../versions/.../index.html`，版本详情页。
- Create: `work/manual_flow_rehearsal/reports`，scan/parser evidence 页面。
- Create: `work/manual_flow_rehearsal/diff`，结构 diff 输出。
- Create: `work/manual_flow_rehearsal/file_diff`，单文件 diff 输出。
- Create: `work/manual_flow_rehearsal/review`，Review Gate 和 owner accept/waive 记录。
- Create: `work/manual_flow_rehearsal/release_area`，release check/link/verify 演练输出。
- Create/Edit: `work/manual_flow_rehearsal/actions/vendor_C.openroad_platform.openroad_sky130ram.action`，批处理动作脚本。

## 关键约定

- 正式 library 参数使用 catalog 中的 `library_name`，例如 `vendor_A.openroad_platform.openroad_asap7`，不是 HTML 目录名里的 `ip_vendor_A...`。
- `refresh` 是日常“更新详情”入口，默认优先 current/previous effective，不应默认 adjacent。
- `cmp` 是手动 compare/debug 入口，需要显式 `--base` 或 `--mode adjacent/cumulative`。
- `fd` 默认只用于推荐 file diff 类型；Verilog/SystemVerilog、Liberty/Lib、SPEF、DB、GDS、OAS 等默认不做深读。
- HTML 页面是输出物；刷新页面前先重新跑 `cat`、`scan`、`refresh` 或 `cmp`。

### Task 1: 准备干净 workspace

**Files:**
- Create: `work/manual_flow_rehearsal/lib_guard.yml`
- Read: `scripts/lg.csh`

- [ ] **Step 1: 进入仓库并设置 csh 环境变量**

Run in csh:

```csh
cd /home/polaris/proj/mx/ai_lib/repo
setenv PROJ /home/polaris/proj/mx/ai_lib/repo
setenv RAW /home/polaris/proj/mx/ai_lib/repo/tests/fixtures/raw
setenv WORK /home/polaris/proj/mx/ai_lib/repo/work/manual_flow_rehearsal
```

Expected:

```text
没有输出；后续命令都使用 $PROJ/$RAW/$WORK。
```

- [ ] **Step 2: 确认短命令可用**

Run:

```csh
$PROJ/scripts/lg.csh --help
```

Expected:

```text
看到 init, scan, catalog/cat, override, library, diff/cmp, refresh, file-diff/fd, release/rel, action, rv-*。
```

- [ ] **Step 3: 初始化 workspace**

Run:

```csh
$PROJ/scripts/lg.csh init $WORK --raw-root $RAW --library-type ip
cd $WORK
```

Expected:

```text
$WORK/lib_guard.yml 已生成。
```

- [ ] **Step 4: 检查配置是否指向本次 workspace**

Run:

```csh
cat $WORK/lib_guard.yml
```

Expected:

```text
workspace: /home/polaris/proj/mx/ai_lib/repo/work/manual_flow_rehearsal
raw_root: /home/polaris/proj/mx/ai_lib/repo/tests/fixtures/raw
library_type: ip
```

### Task 2: 演练 Library Map 人工确认

**Files:**
- Create/Edit: `work/manual_flow_rehearsal/config/library.list`
- Create: `work/manual_flow_rehearsal/config/library_catalog.yml`

- [ ] **Step 1: 发现候选库**

Run:

```csh
$PROJ/scripts/lg.csh library discover
```

Expected:

```text
$WORK/config/library.list 已生成，包含 vendor_A/vendor_B/vendor_C 下的候选库。
```

- [ ] **Step 2: 人工审查并编辑 library.list**

Run:

```csh
gvim $WORK/config/library.list
```

Manual edit rules:

```text
保留 OK: vendor_A_openroad_asap7
保留 OK: vendor_C_openroad_sky130ram
将纯 vendor 聚合目录改为 IGNORE: vendor_A, vendor_B, vendor_C
将嵌套 source_package/gds 这类误识别目录改为 IGNORE
本轮只保留 2 个库，便于快速演练和人工检查。
```

Expected:

```text
library.list 中只剩需要演练的真实库为 OK，其余聚合/嵌套误识别项为 IGNORE。
```

- [ ] **Step 3: 应用人工确认后的 library map**

Run:

```csh
$PROJ/scripts/lg.csh library apply
```

Expected:

```text
$WORK/config/library_catalog.yml 已生成。
```

- [ ] **Step 4: 刷新 catalog 并生成首页**

Run:

```csh
$PROJ/scripts/lg.csh cat --with-evidence
```

Expected:

```text
$WORK/catalog/catalog.json 已生成。
$WORK/catalog/html/index.html 已生成。
```

- [ ] **Step 5: 确认正式 library 参数**

Run:

```csh
python3 -c "import json; d=json.load(open('catalog/catalog.json')); [print(x['library_name']) for x in d['libraries']]"
```

Expected:

```text
如果没有编辑 library.list 过滤库，会看到 9 个 OpenROAD fixture 库：
vendor_A.openroad_platform.openroad_asap7
vendor_A.openroad_platform.openroad_gf180
vendor_A.openroad_platform.openroad_nangate45
vendor_B.openroad_platform.openroad_gt2n
vendor_B.openroad_platform.openroad_ihp_sg13g2
vendor_B.openroad_platform.openroad_sky130hd
vendor_C.openroad_platform.openroad_sky130hs
vendor_C.openroad_platform.openroad_sky130io
vendor_C.openroad_platform.openroad_sky130ram

如果你在 library.list 里只保留 ASAP7 和 SKY130RAM 为 OK，则只应看到：
vendor_A.openroad_platform.openroad_asap7
vendor_C.openroad_platform.openroad_sky130ram
```

### Task 3: 演练 Catalog 与 Version Detail 页面刷新

**Files:**
- Create/Update: `work/manual_flow_rehearsal/catalog/catalog.json`
- Create/Update: `work/manual_flow_rehearsal/catalog/html/index.html`
- Create/Update: `work/manual_flow_rehearsal/catalog/html/libraries/.../versions/.../index.html`

- [ ] **Step 1: 先 dry-run catalog，确认不会跑 scan**

Run:

```csh
$PROJ/scripts/lg.csh --dry-run cat vendor_A.openroad_platform.openroad_asap7 --with-evidence
```

Expected:

```text
只展开 catalog scan/render 命令，不展开 run/compare/file-diff。
```

- [ ] **Step 2: 刷新 ASAP7 catalog**

Run:

```csh
$PROJ/scripts/lg.csh cat vendor_A.openroad_platform.openroad_asap7 --with-evidence
```

Expected:

```text
ASAP7 的 20260624_asap7 和 20260627_asap7 两个版本出现在 catalog HTML。
```

- [ ] **Step 3: 用本地 HTTP 服务查看 HTML**

Run:

```csh
python3 -m http.server 18080 --directory $WORK/catalog/html
```

Expected:

```text
浏览器打开 http://127.0.0.1:18080/ 可以看到 catalog 首页。
手动检查版本详情页是否包含：文件概览、视图覆盖、Parser Summary、更新详情区域。
```

Stop server after inspection:

```text
在运行 http.server 的终端按 Ctrl-C。
```

### Task 4: 演练 Scan 与 Parser Evidence

**Files:**
- Create/Update: `work/manual_flow_rehearsal/reports/vendor_A.openroad_platform.openroad_asap7/20260627_asap7`
- Create/Update: `work/manual_flow_rehearsal/catalog/html/libraries/ip_vendor_A.openroad_platform.openroad_asap7/versions/20260627_asap7/index.html`

- [ ] **Step 1: dry-run scan，确认展开命令**

Run:

```csh
$PROJ/scripts/lg.csh --dry-run scan vendor_A.openroad_platform.openroad_asap7 20260627_asap7
```

Expected:

```text
先展开 catalog refresh，再展开 python -m lib_guard.cli run。
```

- [ ] **Step 2: 扫描 ASAP7 最新版本**

Run:

```csh
$PROJ/scripts/lg.csh scan vendor_A.openroad_platform.openroad_asap7 20260627_asap7
```

Expected:

```text
scan 完成。
$WORK/reports/vendor_A.openroad_platform.openroad_asap7/20260627_asap7/scan_html/index.html 存在。
Version Detail 的 Parser Summary 有 LEF/CDL 等可解析 evidence。
Verilog/Liberty/SPEF/DB/GDS/OAS 不应作为默认深解析对象出现。
```

- [ ] **Step 3: 重新打开版本详情页检查质量**

Open:

```text
$WORK/catalog/html/libraries/ip_vendor_A.openroad_platform.openroad_asap7/versions/20260627_asap7/index.html
```

Expected manual checks:

```text
页面中文为主，专业词汇保留英文。
Parser Summary 展示聚合计数和代表对象，而不是重复的 Detail 列。
文件类型覆盖能区分可解析、summary-only、metadata-only、unknown。
未知类型文件能看到路径或类型提示。
PVT/corner 信息可以折叠或滚动查看，不把页面撑乱。
```

### Task 5: 演练 refresh 更新详情默认语义

**Files:**
- Create/Update: `work/manual_flow_rehearsal/diff/vendor_A.openroad_platform.openroad_asap7/20260627_asap7`
- Create/Update: `work/manual_flow_rehearsal/catalog/html/libraries/ip_vendor_A.openroad_platform.openroad_asap7/versions/20260627_asap7/index.html`

- [ ] **Step 1: dry-run refresh，确认默认不是 adjacent**

Run:

```csh
$PROJ/scripts/lg.csh --dry-run refresh vendor_A.openroad_platform.openroad_asap7
```

Expected:

```text
展开 compare 命令时应带 --base 20260624_asap7。
不应出现 --mode adjacent，除非你显式传 --mode adjacent。
```

- [ ] **Step 2: 执行 refresh**

Run:

```csh
$PROJ/scripts/lg.csh refresh vendor_A.openroad_platform.openroad_asap7
```

Expected:

```text
20260627_asap7 的更新详情重新生成。
Version Detail 中显示 “更新详情（vs 20260624_asap7）” 或等价文案。
页面不应暗示普通用户必须进入 Comparison Review 才能看 diff。
```

- [ ] **Step 3: 检查 HTML 不依赖 current_lib_diff.md**

Run:

```csh
find $WORK -name current_lib_diff.md -print
```

Expected:

```text
即使没有 current_lib_diff.md，版本详情页仍能生成并显示更新详情。
如果存在 current_lib_diff.md，它只是显式导出物，不是 HTML 数据源。
```

### Task 6: 演练手动 compare/debug 模式

**Files:**
- Create/Update: `work/manual_flow_rehearsal/diff/vendor_A.openroad_platform.openroad_asap7/20260627_asap7/base_20260624_asap7`

- [ ] **Step 1: dry-run 显式 base compare**

Run:

```csh
$PROJ/scripts/lg.csh --dry-run cmp vendor_A.openroad_platform.openroad_asap7 20260627_asap7 --base 20260624_asap7 --scan-if-missing
```

Expected:

```text
展开 compare 命令，包含 --base 20260624_asap7。
这是手动 compare/debug，不是日常 refresh 默认语义。
```

- [ ] **Step 2: 执行显式 base compare**

Run:

```csh
$PROJ/scripts/lg.csh cmp vendor_A.openroad_platform.openroad_asap7 20260627_asap7 --base 20260624_asap7 --scan-if-missing
```

Expected:

```text
$WORK/diff/vendor_A.openroad_platform.openroad_asap7/20260627_asap7/base_20260624_asap7/diff_html/index.html 存在。
Version Detail 的更新详情继续使用同一套 version_update_detail_model 数据。
```

- [ ] **Step 3: 只在明确需要时演练 adjacent**

Run:

```csh
$PROJ/scripts/lg.csh --dry-run refresh vendor_A.openroad_platform.openroad_asap7 --mode adjacent
```

Expected:

```text
此时才允许展开 --mode adjacent。
用这个步骤验证 adjacent 是显式 compare/debug 模式，不是普通 refresh 默认值。
```

### Task 7: 演练 File Diff 类型分层

**Files:**
- Create/Update: `work/manual_flow_rehearsal/file_diff/vendor_C.openroad_platform.openroad_sky130ram`

- [ ] **Step 1: 扫描 SKY130RAM 两个版本**

Run:

```csh
$PROJ/scripts/lg.csh scan vendor_C.openroad_platform.openroad_sky130ram 20260619_sky130ram
$PROJ/scripts/lg.csh scan vendor_C.openroad_platform.openroad_sky130ram 20260626_sky130ram_update
```

Expected:

```text
两个版本都有 scan evidence。
```

- [ ] **Step 2: 对 LEF 做默认允许的 fd**

Run:

```csh
$PROJ/scripts/lg.csh fd vendor_C.openroad_platform.openroad_sky130ram 20260626_sky130ram_update sky130ram_source_package/sky130_sram_1rw1r_128x256_8/sky130_sram_1rw1r_128x256_8.lef --base 20260619_sky130ram --type lef
```

Expected:

```text
fd 成功。
$WORK/file_diff/vendor_C.openroad_platform.openroad_sky130ram/20260626_sky130ram_update/... 下生成 HTML/JSON 输出。
```

- [ ] **Step 3: 验证 Verilog 默认被挡住**

Run:

```csh
$PROJ/scripts/lg.csh fd vendor_C.openroad_platform.openroad_sky130ram 20260626_sky130ram_update sky130ram_source_package/sky130_sram_1rw1r_128x256_8/sky130_sram_1rw1r_128x256_8.v --base 20260619_sky130ram --type verilog
```

Expected:

```text
命令失败，并提示 verilog is summary-only; pass --force-large only for expert manual review.
这是正确行为。
```

- [ ] **Step 4: 验证 Liberty/GDS 默认不做 fd**

Run:

```csh
$PROJ/scripts/lg.csh fd vendor_C.openroad_platform.openroad_sky130ram 20260626_sky130ram_update sky130ram_source_package/sky130_sram_1rw1r_128x256_8/sky130_sram_1rw1r_128x256_8_TT_1p8V_25C.lib --base 20260619_sky130ram --type liberty
$PROJ/scripts/lg.csh fd vendor_C.openroad_platform.openroad_sky130ram 20260626_sky130ram_update sky130ram_source_package/sky130_sram_1rw1r_128x256_8/sky130_sram_1rw1r_128x256_8.gds --base 20260619_sky130ram --type gds
```

Expected:

```text
liberty 提示 summary-only，需要 --force-large 才能专家手动审查。
gds 提示 metadata-only 或 binary metadata lane，需要 --force-large 才能专家手动审查。
默认 pairwise/fd 不应为这类文件生成深 diff。
```

### Task 8: 演练 Review Gate 人工决策

**Files:**
- Create/Update: `work/manual_flow_rehearsal/review/vendor_A.openroad_platform.openroad_asap7/20260627_asap7/review_gate.json`
- Create/Update: `work/manual_flow_rehearsal/review/vendor_A.openroad_platform.openroad_asap7/20260627_asap7/review_overrides.json`

- [ ] **Step 1: 构建并检查 current gate**

Run:

```csh
$PROJ/scripts/lg.csh rv-check vendor_A.openroad_platform.openroad_asap7 20260627_asap7 --gate current
$PROJ/scripts/lg.csh rv-list vendor_A.openroad_platform.openroad_asap7 20260627_asap7 --gate current
```

Expected:

```text
输出 blocking_items、attention_items、accepted_items、waived_items。
ASAP7 20260627_asap7 相对 20260624_asap7 增加了 metadata-only GDS，通常会出现 metadata.gds.added:* blocking item。
```

- [ ] **Step 2: 对一个已知 metadata-only GDS item 做 accept**

Run:

```csh
$PROJ/scripts/lg.csh rv-accept vendor_A.openroad_platform.openroad_asap7 20260627_asap7 --item metadata.gds.added:upstream_ae9a8ed9/gds/asap7sc7p5t_28_L_220121a.gds --by polaris --reason "Manual rehearsal accepted this metadata-only GDS addition."
```

Expected:

```text
$WORK/review/vendor_A.openroad_platform.openroad_asap7/20260627_asap7/review_overrides.json 已更新。
再次运行 rv-list 时，该 item 出现在 accepted_items。
```

- [ ] **Step 3: 重新生成页面并检查 gate 状态**

Run:

```csh
$PROJ/scripts/lg.csh cat vendor_A.openroad_platform.openroad_asap7 --with-evidence
```

Expected:

```text
版本详情页反映 Review Gate 最新状态。
```

### Task 9: 演练 release check/link/verify

**Files:**
- Create/Update: `work/manual_flow_rehearsal/release_area`
- Create/Update: `work/manual_flow_rehearsal/catalog/html`

- [ ] **Step 1: 先只跑 release check**

Run:

```csh
$PROJ/scripts/lg.csh rel vendor_C.openroad_platform.openroad_sky130ram 20260626_sky130ram_update --check-only
```

Expected:

```text
只生成 release-check 结果，不创建正式 release link。
```

- [ ] **Step 2: 演练 symlink release preview**

Run:

```csh
$PROJ/scripts/lg.csh rel vendor_C.openroad_platform.openroad_sky130ram 20260626_sky130ram_update --check-first --link-mode symlink
```

Expected:

```text
$WORK/release_area 下生成 release preview。
如果 Review Gate blocking 未处理，命令应阻止或提示需要人工确认。
```

- [ ] **Step 3: 检查 release 输出没有复制大文件**

Run:

```csh
find $WORK/release_area -maxdepth 4 -type l -print | head
```

Expected:

```text
能看到 symlink；本轮演练不应复制大体积工艺库文件。
```

### Task 10: 演练 Action 文件批处理

**Files:**
- Create/Edit: `work/manual_flow_rehearsal/actions/vendor_C.openroad_platform.openroad_sky130ram.action`

- [ ] **Step 1: 创建 action 文件**

Run:

```csh
mkdir -p $WORK/actions
gvim $WORK/actions/vendor_C.openroad_platform.openroad_sky130ram.action
```

Write exactly:

```text
@scan auto 20260619_sky130ram 20260626_sky130ram_update
@diff 20260619_sky130ram 20260626_sky130ram_update sky130ram_update
@release 20260626_sky130ram_update
```

Expected:

```text
action 文件保存成功。
```

- [ ] **Step 2: dry-run action**

Run:

```csh
$PROJ/scripts/lg.csh --dry-run action vendor_C.openroad_platform.openroad_sky130ram
```

Expected:

```text
输出将执行的 scan/diff/release 命令，不实际覆盖已有 evidence。
```

- [ ] **Step 3: 执行 action**

Run:

```csh
$PROJ/scripts/lg.csh action vendor_C.openroad_platform.openroad_sky130ram
```

Expected:

```text
已有输出会被保守跳过；缺失输出会被生成。
这一步验证 action 是人工编排的重复执行入口，不是全自动发布。
```

### Task 11: 最终人工验收清单

**Files:**
- Inspect: `work/manual_flow_rehearsal/catalog/html/index.html`
- Inspect: `work/manual_flow_rehearsal/catalog/html/libraries/.../versions/.../index.html`

- [ ] **Step 1: 检查 catalog 首页**

Open:

```text
$WORK/catalog/html/index.html
```

Expected:

```text
只显示人工确认保留的库。
每个库有清晰版本数量、scan/diff/release 状态。
```

- [ ] **Step 2: 检查 ASAP7 版本详情页**

Open:

```text
$WORK/catalog/html/libraries/ip_vendor_A.openroad_platform.openroad_asap7/versions/20260627_asap7/index.html
```

Expected:

```text
更新详情显示与 20260624_asap7 的关系。
Parser Summary、文件类型覆盖、summary-only、metadata-only、unknown 信息能被读懂。
页面不出现 “Comparison Review 是唯一 diff 入口” 这类旧文案。
```

- [ ] **Step 3: 检查 SKY130RAM 版本详情页**

Open:

```text
$WORK/catalog/html/libraries/ip_vendor_C.openroad_platform.openroad_sky130ram/versions/20260626_sky130ram_update/index.html
```

Expected:

```text
LEF/CDL/SPICE 的 parser evidence 可见。
Verilog/Liberty/GDS 被归入 summary-only 或 metadata-only，不作为默认深解析。
Review Gate 的 accept/waive 决策能在页面或对应 JSON 中追踪。
```

- [ ] **Step 4: 保存演练记录**

Run:

```csh
date > $WORK/manual_rehearsal_notes.txt
echo "ASAP7 refresh/cmp checked" >> $WORK/manual_rehearsal_notes.txt
echo "SKY130RAM fd/review/release checked" >> $WORK/manual_rehearsal_notes.txt
```

Expected:

```text
$WORK/manual_rehearsal_notes.txt 记录本轮人工演练结论。
```

## 自查结论

- Spec coverage: 覆盖 init、library、cat、scan、refresh、cmp、fd、rv、rel、action，以及 HTML 手动查看。
- Placeholder scan: 没有保留待填写占位符；Review Gate 使用 ASAP7 fixture 中已知的 metadata-only GDS item。
- Type consistency: 计划使用的正式 library 参数为 `vendor_A.openroad_platform.openroad_asap7` 和 `vendor_C.openroad_platform.openroad_sky130ram`，与 catalog 的 `library_name` 形式一致。
