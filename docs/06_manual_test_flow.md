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
  --mode signature \
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
```

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

