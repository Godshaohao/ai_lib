Status: archived
Archive reason: moved out of current lib_guard documentation.

# lib_guard C Shell 使用与测试手册

本文面向真实内网环境。日常入口优先使用 `scripts/lg.csh`；底层
`python -m lib_guard.cli ...` 只用于调试、审计和定位问题。

## 1. 当前主线

lib_guard 现在按下面这条链路工作：

```text
raw_root -> catalog discovery -> catalog.json -> scan/diff/file-diff/release
```

关键原则：

- `raw_root` 只是发现入口，不等于库根目录。
- 真实库根目录是 `library_root`。
- 真实版本目录是 `version_path` / `raw_path`。
- `scan`、`diff`、`file-diff`、`release` 都必须从 catalog 读取路径。
- 短命令 `lg.csh` 只负责编排命令，不理解物理目录结构。

这解决了旧问题：不能再默认所有库都是 `raw/<library>/<version>` 两层结构。

## 2. 推荐目录

简单项目可以继续使用两层结构：

```text
$RAW/
  ucie/
    initial_20250601/
    stable_20250608/
  ddr/
    initial_20250601/
    stable_20250608/
```

真实生产库建议使用 `library_map.yml` 明确登记：

```text
$RAW/
  vendorA/
    analog_ip/
      UVIP/
        initial_20250601/
        stable_20250608/
```

示例 `library_map.yml`：

```yaml
libraries:
  vendorA.analog_ip.UVIP:
    root: raw/vendorA/analog_ip/UVIP
    display_name: UVIP
    vendor: vendorA
    category: analog_ip
    library_type: ip
    aliases:
      - ucie
```

在 catalog policy 中启用：

```json
{
  "library_type": "ip",
  "discovery": {
    "mode": "map_first",
    "library_map": "library_map.yml",
    "pattern_fallback": true
  }
}
```

命令里可以继续使用 alias：

```csh
$PROJ/scripts/lg.csh scan ucie stable_20250608
$PROJ/scripts/lg.csh diff ucie stable_20250608
```

catalog 中会保存 canonical identity：

```text
library_id    ip/vendorA.analog_ip.UVIP
library_name  vendorA.analog_ip.UVIP
aliases       ucie
library_root  .../raw/vendorA/analog_ip/UVIP
raw_path      .../raw/vendorA/analog_ip/UVIP/stable_20250608
```

## 3. 初始化

```csh
setenv PROJ /path/to/ai_lib
setenv WORK $PROJ/work/manual_flow_testlib
setenv RAW  $WORK/raw

$PROJ/scripts/lg.csh init $WORK --raw-root $RAW
cd $WORK
```

如果不能 `cd $WORK`：

```csh
setenv LIB_GUARD_CONFIG $WORK/lib_guard.yml
```

检查入口：

```csh
$PROJ/scripts/lg.csh --help
$PROJ/scripts/lg.csh --dry-run scan
$PROJ/scripts/lg.csh --dry-run diff ucie stable_20250608 --base initial_20250601 --auto-scan
```

`lg.csh` 会自动设置：

```csh
setenv PYTHONPATH "$PROJ/src:$PYTHONPATH"
setenv LIB_GUARD_PROJECT_ROOT "$PROJ"
```

因此短命令默认会使用项目里的：

```text
$PROJ/configs/catalog_policy.json
```

## 4. Catalog 发现

扫描所有库和版本：

```csh
$PROJ/scripts/lg.csh scan
```

查看结果：

```text
$WORK/catalog/catalog.json
$WORK/catalog/html/index.html
$WORK/catalog/html/libraries/<library>.html
```

Catalog HTML 重点看：

- 库 ID
- 别名
- Vendor
- 分类
- 库根目录
- 版本路径
- 发现方式
- scan/diff/release 报告入口

如果目录误判，优先补 `library_map.yml`，不要改 scan/diff/release 脚本。

## 5. Scan

扫描某个库全部版本：

```csh
$PROJ/scripts/lg.csh scan ucie
```

扫描某个版本：

```csh
$PROJ/scripts/lg.csh scan ucie stable_20250608
```

主要输出：

```text
$WORK/reports/ucie/stable_20250608/scan_html/index.html
$WORK/scan_out/ucie/stable_20250608/<mode>_<scan_id>/
```

Scan HTML 只看交付结构和关键证据。非文档类 parser 的粗糙结果不进入
`Review Attention`；文档类 parser 仍可进入审阅关注。

文档类包括：

```text
doc
readme
release_note
update_note
changelog
known_issue
integration_guide
delivery_note
version_note
waiver
```

## 6. Structural Diff

使用 catalog 推导 base：

```csh
$PROJ/scripts/lg.csh diff ucie stable_20250608
```

手动指定 base：

```csh
$PROJ/scripts/lg.csh diff ucie stable_20250608 --base initial_20250601
```

diff 前自动补扫 base/new：

```csh
$PROJ/scripts/lg.csh diff ucie stable_20250608 --base initial_20250601 --auto-scan
```

主要输出：

```text
$WORK/diff/ucie/stable_20250608/diff_html/index.html
$WORK/diff/ucie/stable_20250608/adjacent/
$WORK/diff/ucie/stable_20250608/base_initial_20250601/
```

Structural Diff 只回答结构变化：

- view 是否新增/删除
- file type 数量是否变化
- release note / waiver / README 等发布证据是否变化
- 哪些文件需要人工 pairwise diff
- metadata-only 文件是否需要人工复核

## 7. File Diff

对关键文件做内容级复核：

```csh
$PROJ/scripts/lg.csh file-diff ucie stable_20250608 rtl/ucie_top.v --base initial_20250601
$PROJ/scripts/lg.csh file-diff ucie stable_20250608 lef/ucie.lef --base initial_20250601
$PROJ/scripts/lg.csh file-diff ucie stable_20250608 lib/ucie.lib --base initial_20250601
$PROJ/scripts/lg.csh file-diff ucie stable_20250608 cdl/ucie.cdl --base initial_20250601
$PROJ/scripts/lg.csh file-diff ucie stable_20250608 sdc/ucie.sdc --base initial_20250601
$PROJ/scripts/lg.csh file-diff ucie stable_20250608 upf/ucie.upf --base initial_20250601
$PROJ/scripts/lg.csh file-diff ucie stable_20250608 cpf/ucie.cpf --base initial_20250601
$PROJ/scripts/lg.csh file-diff ucie stable_20250608 spef/ucie.spef --base initial_20250601
$PROJ/scripts/lg.csh file-diff ucie stable_20250608 db/ucie.db --base initial_20250601
```

csh 中建议统一使用 `/`，不要使用 Windows 风格 `\`。

支持类型：

```text
lef
liberty
verilog
cdl
sdc
upf
cpf
spef
db
```

v6 also supports:

```text
waiver
ibis
pwl
snp
cpm
```

Current File Diff routing rule:

- Catalog does not directly expose full File Diff command lists.
- Open Diff Timeline from Catalog, then open Selected Diff for one comparison.
- Run File Diff from Selected Diff's key recommendation queue, or manually for a known old/new file pair during debugging.
- Large or ambiguous comparisons should confirm base/comparison first and should not generate a full File Diff command batch.

策略：

- Verilog：关注 module/port 增删、方向变化、位宽变化。
- LEF：关注 macro、pin、direction、layer、size。
- Liberty：关注 cell、pin、corner、timing arc。
- CDL：关注 subckt、pin、instance。
- SDC/UPF/CPF：关注 clock、constraint、电源域。
- DB/GDS/OAS：当前只做 metadata/hash，必须标记为 metadata-only。

主要输出：

```text
$WORK/file_diff/ucie/stable_20250608/<type>_<name>/index.html
```

## 8. Release

Release 是把已扫描、已审阅的版本按文件级别发布到 `release_area`。

Dry-run：

```csh
$PROJ/scripts/lg.csh release ucie stable_20250608
```

真实执行：

```csh
$PROJ/scripts/lg.csh release ucie stable_20250608 --apply --overwrite
```

当前 release 目标结构取消 `current/ucie/ddr` 这类中间层，直接进入 view 级目录：

```text
$WORK/release_area/
  rtl/
  lef/
  lib/
  cdl/
  sdc/
  doc/
```

更新同一版本或覆盖旧发布时使用：

```csh
$PROJ/scripts/lg.csh release ucie stable_20250608 --apply --overwrite
```

主要输出：

```text
$WORK/release_runs/<release_id>/index.html
$WORK/release_runs/<release_id>/release_manifest.json
$WORK/release_area/
```

## 9. 常见报错

### 9.1 No module named lib_guard

不要直接运行底层 CLI，先用：

```csh
$PROJ/scripts/lg.csh --help
```

必须调试底层 CLI 时：

```csh
setenv PYTHONPATH $PROJ/src
python -m lib_guard.cli --help
```

### 9.2 catalog not found

先运行：

```csh
$PROJ/scripts/lg.csh scan
```

### 9.3 library not found

检查 catalog 里真实身份：

```text
$WORK/catalog/catalog.json
```

如果命令使用 alias，确认 `library_map.yml` 中有：

```yaml
aliases:
  - ucie
```

### 9.4 version not found

确认版本目录是否是 catalog 识别出的 `version_id`。真实版本 ID 以 catalog 为准。

### 9.5 cannot resolve base version

手动指定 base：

```csh
$PROJ/scripts/lg.csh diff ucie stable_20250608 --base initial_20250601 --auto-scan
```

### 9.6 file-diff 找不到文件

`relpath` 是相对于版本目录的路径，例如：

```text
lef/ucie.lef
rtl/ucie_top.v
```

不是绝对路径，也不是相对于 `$RAW` 的路径。

## 10. 底层 CLI 对照

日常不推荐直接使用，但排查时可用。

Catalog：

```csh
python -m lib_guard.cli catalog scan \
  --root $RAW \
  --out $WORK/catalog \
  --library-type ip \
  --policy $PROJ/configs/catalog_policy.json \
  --render \
  --html-out $WORK/catalog/html
```

Scan：

```csh
python -m lib_guard.cli run \
  --catalog $WORK/catalog/catalog.json \
  --library ucie \
  --version stable_20250608 \
  --workdir $WORK \
  --mode candidate \
  --parse-jobs 4 \
  --skip-cache \
  --console-progress \
  --progress-interval 1 \
  --catalog-html-out $WORK/catalog/html
```

Diff：

```csh
python -m lib_guard.cli compare \
  --catalog $WORK/catalog/catalog.json \
  --library ucie \
  --new stable_20250608 \
  --base initial_20250601 \
  --workdir $WORK \
  --catalog-html-out $WORK/catalog/html
```

File Diff：

```csh
python -m lib_guard.cli file-diff lef \
  --old $OLD_VERSION_ROOT/lef/ucie.lef \
  --new $NEW_VERSION_ROOT/lef/ucie.lef \
  --out $WORK/file_diff/ucie/stable_20250608/lef_ucie

python -m lib_guard.cli file-diff sdc \
  --old $OLD_VERSION_ROOT/sdc/ucie.sdc \
  --new $NEW_VERSION_ROOT/sdc/ucie.sdc \
  --out $WORK/file_diff/ucie/stable_20250608/sdc_ucie

python -m lib_guard.cli file-diff ibis \
  --old $OLD_VERSION_ROOT/model/old.ibs \
  --new $NEW_VERSION_ROOT/model/new.ibs \
  --out $WORK/file_diff/ucie/stable_20250608/ibis_model
```

Expected File Diff outputs:

```text
summary.json
semantic_diff.json
raw_text_diff.html
index.html
```

The HTML should show field changes and location hints when parser evidence contains `line`, `line_start`, or `raw`.

Release：

```csh
python -m lib_guard.cli release-batch \
  --catalog $WORK/catalog/catalog.json \
  --library ucie \
  --version stable_20250608 \
  --release-root $WORK/release_area \
  --alias current \
  --apply \
  --overwrite \
  --catalog-html-out $WORK/catalog/html
```

## 11. 测试清单

### 11.1 最小冒烟

```csh
$PROJ/scripts/lg.csh init $WORK --raw-root $RAW
cd $WORK
$PROJ/scripts/lg.csh scan
$PROJ/scripts/lg.csh scan ucie stable_20250608
$PROJ/scripts/lg.csh diff ucie stable_20250608 --base initial_20250601 --auto-scan
$PROJ/scripts/lg.csh file-diff ucie stable_20250608 lef/ucie.lef --base initial_20250601
$PROJ/scripts/lg.csh release ucie stable_20250608
```

### 11.2 alias 场景

使用 `library_map.yml` 配置 canonical ID 和 alias，然后确认下面命令都能命中同一库：

```csh
$PROJ/scripts/lg.csh scan ucie stable_20250608
$PROJ/scripts/lg.csh diff ucie stable_20250608 --base initial_20250601
$PROJ/scripts/lg.csh release ucie stable_20250608
```

### 11.3 Python 单测

```csh
setenv PYTHONPATH $PROJ/src
python -m unittest src.lib_guard.test.test_v5_catalog
python -m unittest discover -s src/lib_guard/test
```

当前验证结果：

```text
src.lib_guard.test.test_v5_catalog: Ran 10 tests OK
discover -s src/lib_guard/test: Ran 57 tests OK
```

## 12. 文件职责

- `src/lib_guard/discovery.py`：库发现和 library_map 解析。
- `src/lib_guard/catalog/index.py`：catalog source-of-truth、版本关系、runtime state。
- `src/lib_guard/short_cli.py`：短命令编排，不猜目录。
- `src/lib_guard/cli.py`：底层 argparse 命令入口。
- `src/lib_guard/cli_commands/catalog.py`：catalog-driven scan/diff/release 命令实现。
- `src/lib_guard/render/catalog_report.py`：catalog HTML 展示。
- `configs/catalog_policy.json`：默认发现策略。
- `scripts/lg.csh`：真实 csh 环境入口。

## 13. Short CLI csh shortcuts

Daily csh entry should stay short and catalog-driven:

```csh
$PROJ/scripts/lg.csh cat
$PROJ/scripts/lg.csh scan <library> <version>
$PROJ/scripts/lg.csh cmp <library> <version> --base <base_version> --scan-if-missing
$PROJ/scripts/lg.csh fd <library> <version> lef/<file>.lef --base <base_version>
$PROJ/scripts/lg.csh fd <library> <version> model/<file>.ibs --base <base_version>
$PROJ/scripts/lg.csh fd <library> <version> touch/<file>.s2p --type snp --base <base_version>
$PROJ/scripts/lg.csh rel <library> <version> --check-first
```

Shortcut mapping:

```text
cat -> catalog
cmp -> diff
fd  -> file-diff
rel -> release
```

Use `--dry-run` before expensive scan or diff work:

```csh
$PROJ/scripts/lg.csh --dry-run cmp <library> <version> --base <base_version>
$PROJ/scripts/lg.csh --dry-run fd <library> <version> waiver/<file>.waiver --base <base_version>
```

`file-diff` relpath is always relative to the selected catalog version `raw_path`,
not relative to `$RAW` and not an absolute path. The short CLI normalizes `/` and
`\` separators before joining the relpath to old/new catalog `raw_path` values.

Supported pairwise file-diff types through `lg.csh fd`:

```text
lef liberty verilog cdl sdc upf cpf spef db waiver ibis pwl snp cpm
```

When catalog cannot infer the old version, pass `--base <base_version>`.

## 14. Desktop UI and command text audit

Run this smoke set after UI, short CLI, or report-rendering changes. This section
uses the current short command model and intentionally checks desktop output only.

### 14.0 Unified library timeline model

Catalog should organize each library as one mixed timeline:

```text
Library Version Timeline

event_time    version_id           node_kind    package_type    usage_status
2025-06-01    stable_20250601      raw          full            superseded
2025-06-08    patch_20250608       raw          partial         accepted
2025-06-08    effective_20250608   effective    composed        current
2025-07-01    stable_20250701      raw          full            current
```

Rules:

- raw and effective nodes share the same `timeline`; do not split them into
  separate Raw Sources and Effective Versions systems.
- `latest_effective_ref` points to the current usable node.
- `latest_effective_ref` may point to a `raw/full` node or an
  `effective/composed` node.
- A full raw package can directly become the latest effective library.
- A partial raw package cannot become latest effective by itself; after it is
  accepted, create or point to an effective composed node.
- `scan` belongs to raw nodes.
- resolved coverage belongs to effective nodes.
- diff belongs to effective transitions, meaning changes in `latest_effective_ref`.

### 14.1 User-facing command rules

Preferred csh commands:

```csh
$PROJ/scripts/lg.csh cat
$PROJ/scripts/lg.csh scan <library> <version>
$PROJ/scripts/lg.csh cmp <library> <version> --base <base_version> --scan-if-missing
$PROJ/scripts/lg.csh fd <library> <version> <relpath> --base <base_version> --type <file_type>
$PROJ/scripts/lg.csh rel <library> <version> --check-first
```

Expected report behavior:

- Catalog shows navigation and examples, not a full File Diff command list.
- Library Workspace uses `Library Version Timeline` with `node_kind`,
  `package_type`, `usage_status`, and the visible `latest_effective_ref`.
- Scan next action uses `cmp`, not stale `lg diff` wording.
- Selected Diff is the only normal place for key File Diff recommendations.
- Effective Compare File Diff commands include `--type`.
- Large or ambiguous comparisons ask the reviewer to confirm base/comparison before
  generating focused File Diff recommendations.

### 14.1.1 Version Review scan detail model

The raw version detail page is `VERSION REVIEW`. It should embed the important
single-version scan evidence directly instead of behaving like a flat artifact
launcher or sending normal review flow into a separate scan page.

Default scan behavior:

- The first visible section is `更新详情（vs <previous_effective>）`.
- `更新详情` should combine release_note/changelog/update_note text with the
  automatic diff summary for the current version.
- Full packages use full compare semantics. Partial, hotfix, and scoped update
  packages use incremental compare semantics; missing files in the package are
  not treated as deletes.
- All files are inventoried by count, file type, path, and filename-derived corner
  hints.
- Lightweight text and structure files run parsers and expose Parser Summary
  results by default.
- `.lib/.lib.gz`, `.db`, `.spef`, and binary/layout views are Count-only by
  default. Normal scan does not parse their content.
- The visible Version Review UI should show `Count-only + Corner Summary`,
  `Parser Summary`, and pre-diff readiness.
- `Parser Summary` rows should include folded `Parser Details` examples, limited
  to the first 10 extracted objects for each parser.
- The visible Version Review UI should not show `Metadata only` as the main
  concept.
- Standalone `scan_html` may exist as compatibility/debug evidence, but Catalog
  and Library Timeline should treat Version Review as the normal single-version
  detail page.

### 14.2 Desktop HTML smoke targets

Generate or open the representative pages:

```text
work/ui_desktop_audit/catalog/html/index.html
work/ui_desktop_audit/catalog/html/libraries/ip_ucie/versions/stable_20250608/index.html
work/ui_desktop_audit/scan_html/index.html
work/ui_desktop_audit/diff_html/index.html
work/ui_desktop_audit/effective_E3.html
work/ui_desktop_audit/compare_E2_vs_E3/index.html
work/ui_desktop_audit/release_preview/index.html
work/ui_desktop_audit/release_html/index.html
```

Search generated HTML for stale UI strings:

```powershell
rg -n "\$PROJ/scripts/lg\.csh file-diff|python -m lib_guard\.cli file-diff|\blg diff\b|Old Target|New Target|Changed Files|Risk Review|Deep Diff Commands|done/total|File Diff 2/5|TODO|TBD|FIXME|Lorem ipsum|not set" work\ui_desktop_audit -g "*.html"
```

The command should return no user-facing HTML matches. JSON debug fields may still
contain `low_level_command` for traceability, but those should not be the primary
visible command in reports.

### 14.3 Verification commands

```powershell
$env:PYTHONPATH='src'
& 'C:\Users\Polaris\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m compileall -q src\lib_guard
& 'C:\Users\Polaris\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m unittest discover -b -s src\lib_guard\test -p 'test_*.py'
& 'C:\Users\Polaris\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m lib_guard.short_cli --help
```

Current expected unittest result:

```text
Ran 80 tests
OK
```
