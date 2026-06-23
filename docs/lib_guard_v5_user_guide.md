# lib_guard v5 使用文档

## v6 Current Update

This guide was written for v5. The current code also includes the v6 review-navigation and File Diff upgrade:

- Catalog is a navigation map. It does not directly expose full File Diff command lists.
- The primary review route is `Catalog -> Diff Timeline -> Selected Diff -> recommended File Diff`.
- File Diff is recommendation-based and no longer uses `File Diff 2/5` or `done/total` counters.
- Large or ambiguous comparisons first require base/comparison confirmation.
- Pairwise File Diff supports `lef`, `liberty`, `verilog`, `cdl`, `sdc`, `upf`, `cpf`, `spef`, `db`, `waiver`, `ibis`, `pwl`, `snp`, and `cpm`.
- Liberty extracts `is_macro` and `is_pad`; SDC/UPF now include semantic fields; waiver/IBIS/PWL/SNP/CPM parsers are wired into scan and File Diff.

本文档说明 lib_guard v5 当前项目如何配置、启动和执行 release guard 流程。目标读者是不熟悉代码的人，也包括后续回看时的自己。

## 1. 工具定位

lib_guard v5 用来检查 IC/PD library release 包是否可以被挂载、使用或批准归档。

它的核心链路是：

```text
raw library
  -> scan
  -> summary / release_readiness
  -> version register
  -> diff
  -> release check
  -> release link
  -> console review
```

它不是简单复制 release 包，而是先生成结构化证据：

- 文件清单：`file_inventory.json`
- parser 结果：`parser_results/`
- 汇总结果：`summaries/`
- parser 质量：`summary/parser_quality.json`
- 发布就绪度：`summary/release_readiness.json`
- diff 结果：`diff_summary.json`、`diff_issues.json`
- release gate：`release/release_check.json`
- link 计划：`release/release_link.json`

## 2. 当前目录结构

```text
configs/
  release_policy.json       release 准入策略
  summary_policy.json       summary 重建影响关系

docs/
  lib_guard_v5_user_guide.md
  lib_guard_v5_architecture_patch.md

src/lib_guard/
  cli.py                    CLI 入口
  scan/                     扫描、分类、hash、parser 执行
  scan/parsers/             ParserResult v2 解析器
  summary/                  summary rebuild
  release/                  readiness/check/link
  diff/                     scan output diff
  version/                  版本索引
  render/                   HTML report / console
  test/                     unittest 验收测试

work/
  默认工作目录，保存 history、cache、scan/diff/console 输出
```

当前项目还没有安装成 Python package，所以直接运行 `python -m lib_guard.cli` 前必须设置 `PYTHONPATH=src`。

## 3. 启动前准备

### 3.1 Windows PowerShell

在项目根目录执行：

```powershell
cd C:\Users\Polaris\Documents\opencode\ai_lib
$env:PYTHONPATH = "src"
```

然后查看 CLI：

```powershell
python -m lib_guard.cli --help
```

如果系统 `python` 不可用，可以使用 Codex bundled Python：

```powershell
$env:PYTHONPATH = "src"
& "C:\Users\Polaris\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" -m lib_guard.cli --help
```

### 3.2 推荐固定几个变量

```powershell
$env:PYTHONPATH = "src"
$PY = "C:\Users\Polaris\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
$RAW = "C:\path\to\raw_library"
$WORK = "work"
$RELROOT = "C:\path\to\release_root"
```

后续命令可以写成：

```powershell
& $PY -m lib_guard.cli scan --root $RAW --profile ip --name demo --version v1 --mode signature --workdir $WORK
```

## 4. 核心配置

### 4.1 release_policy.json

路径：[configs/release_policy.json](../configs/release_policy.json)

核心字段：

```json
{
  "required_views": {
    "ip": ["verilog"],
    "hard_ip": ["verilog", "lef", "liberty"],
    "stdcell": ["liberty", "db", "lef", "gds", "verilog", "cdl"],
    "sram": ["liberty", "db", "lef", "gds", "verilog", "cdl"]
  }
}
```

含义：不同 library type 必须具备哪些 view。`release_readiness` 和 `release check` 会根据它判断 required view 是否缺失。

```json
{
  "validation_levels": {
    "verilog": "parsed_required",
    "lef": "parsed_required",
    "liberty": "parsed_required",
    "db": "metadata_required",
    "gds": "metadata_required",
    "doc": "doc_review_required",
    "unknown": "pass_through_allowed"
  }
}
```

含义：

- `parsed_required`：必须有 parser 结果，parser `FAILED` / `PASS_EMPTY` 会影响 release。
- `metadata_required`：只要求记录 metadata，不做深解析。
- `doc_review_required`：文档必须进入 review。
- `pass_through_allowed`：允许透传，但进入 manual review。

```json
{
  "alias_gate": {
    "stage": { "required_release_level": "L0" },
    "current": { "required_release_level": "L1" },
    "approved": { "required_release_level": "L2" }
  }
}
```

含义：发布别名和 release level 绑定。

### 4.2 summary_policy.json

路径：[configs/summary_policy.json](../configs/summary_policy.json)

它定义某类文件变化后，需要重建哪些 summary。例如：

```json
{
  "affected_summary_map": {
    "lef": ["lef_summary", "macro_summary", "port_summary"],
    "verilog": ["verilog_summary", "port_summary"]
  }
}
```

如果只更新 `verilog`，可以只重建 `verilog_summary` 和 `port_summary`。

## 5. Release Level 策略

当前分三档：

| Level | 含义 | 典型用途 | 可用 alias |
| --- | --- | --- | --- |
| L0 | Inventory Release：包能挂出来，可追踪，但不声明内容已验证 | 快速接入、临时 stage | stage |
| L1 | Readiness Release：required view 齐全，P0 diff 可解释 | hotfix、项目 current | stage, current |
| L2 | Verified Release：parser quality 和 P2 deep diff 完成 | approved、baseline、归档 | stage, current, approved |

别名规则：

```text
stage    requires L0
current  requires L1
approved requires L2
```

diff 规则：

```text
P0 diff 支持 L0/L1，适合 stage/current
P2 deep diff 支持 L2，适合 approved
```

## 6. 常用运行流程

### 6.1 L0：快速 stage 挂载

适用于先把包挂出来、验证路径和文件存在性。

```powershell
$env:PYTHONPATH = "src"
& $PY -m lib_guard.cli scan `
  --root $RAW `
  --profile ip `
  --name demo `
  --version v1 `
  --mode inventory `
  --workdir work
```

默认输出路径类似：

```text
work/scan_out/ip/demo/v1/runs/inventory_<scan_id>
```

检查 stage：

```powershell
& $PY -m lib_guard.cli release check `
  --scan work/scan_out/ip/demo/v1/runs/inventory_<scan_id> `
  --alias stage `
  --policy configs/release_policy.json
```

dry-run link：

```powershell
& $PY -m lib_guard.cli release link `
  --scan work/scan_out/ip/demo/v1/runs/inventory_<scan_id> `
  --release-root $RELROOT `
  --alias stage
```

真正 apply：

```powershell
& $PY -m lib_guard.cli release link `
  --scan work/scan_out/ip/demo/v1/runs/inventory_<scan_id> `
  --release-root $RELROOT `
  --alias stage `
  --apply
```

注意：apply 必须满足 `release_check.allowed_to_apply = true`。

### 6.2 L1：current release

适用于项目默认可用版本。

```powershell
& $PY -m lib_guard.cli scan `
  --root $RAW `
  --profile ip `
  --name demo `
  --version v1 `
  --mode signature `
  --workdir work
```

如果是 hotfix，需要先登记 parent/full 和 hotfix：

```powershell
& $PY -m lib_guard.cli version register `
  --scan work/scan_out/ip/demo/full_v1.0/runs/signature_<scan_id> `
  --version-id full_v1.0 `
  --version-type full `
  --release-line v1.0 `
  --workdir work

& $PY -m lib_guard.cli version register `
  --scan work/scan_out/ip/demo/hotfix_v1.0.1/runs/signature_<scan_id> `
  --version-id hotfix_v1.0.1 `
  --version-type hotfix `
  --release-line v1.0 `
  --parent-version full_v1.0 `
  --base-version full_v1.0 `
  --workdir work
```

做 adjacent diff：

```powershell
& $PY -m lib_guard.cli diff adjacent `
  --library-id ip/demo `
  --new-version hotfix_v1.0.1 `
  --workdir work `
  --out work/diff_out/hotfix_v1.0.1_adjacent
```

检查 current：

```powershell
& $PY -m lib_guard.cli release check `
  --scan work/scan_out/ip/demo/hotfix_v1.0.1/runs/signature_<scan_id> `
  --diff work/diff_out/hotfix_v1.0.1_adjacent `
  --alias current `
  --policy configs/release_policy.json
```

link current：

```powershell
& $PY -m lib_guard.cli release link `
  --scan work/scan_out/ip/demo/hotfix_v1.0.1/runs/signature_<scan_id> `
  --diff work/diff_out/hotfix_v1.0.1_adjacent `
  --release-root $RELROOT `
  --alias current `
  --apply
```

### 6.3 L2：approved release

适用于 approved、baseline、归档版本。

```powershell
& $PY -m lib_guard.cli scan `
  --root $RAW `
  --profile ip `
  --name demo `
  --version v1 `
  --mode full `
  --workdir work
```

重建 summary：

```powershell
& $PY -m lib_guard.cli summary rebuild `
  --scan work/scan_out/ip/demo/v1/runs/full_<scan_id> `
  --all `
  --policy configs/summary_policy.json
```

生成 P2 diff 后检查 approved：

```powershell
& $PY -m lib_guard.cli release check `
  --scan work/scan_out/ip/demo/v1/runs/full_<scan_id> `
  --diff work/diff_out/v1_p2 `
  --alias approved `
  --policy configs/release_policy.json
```

如果 `diff_summary.json` 没有 `deep_diff_completed = true`，`approved` 会被 BLOCK。

## 7. Console 使用

生成 HTML console：

```powershell
& $PY -m lib_guard.cli console build `
  --scan work/scan_out/ip/demo/v1/runs/signature_<scan_id> `
  --out work/reports/ip_demo_v1_console `
  --workdir work `
  --config-dir configs
```

打开：

```text
work/reports/ip_demo_v1_console/index.html
```

主要页面：

- Dashboard：整体状态和推荐动作。
- Config：配置项视图。
- Quality：parser quality。
- Release：release level、alias gate、limitations、doc summary。
- History：历史记录。
- Review：人工审查项。

## 8. 输出目录说明

一次 scan 的典型输出：

```text
scan_out/
  scan_meta.json
  manifest.json
  file_inventory.json
  parser_task_list.json
  parser_manifest.json
  parser_results.json
  parser_results/
  summaries/
  summary/
    parser_quality.json
    release_readiness.json
    release_input_summary.json
  signatures/
    signatures.json
  scan_issues.json
  integrity.json
  logs/
```

一次 diff 的典型输出：

```text
diff_out/
  diff_meta.json
  diff_summary.json
  file_diff.json
  component_diff.json
  summary_diff.json
  signature_diff.json
  release_readiness_diff.json
  diff_issues.json
  parser_result_diff/
  diff_report.md
```

一次 release check/link 的典型输出：

```text
scan_out/release/
  release_check.json
  release_link.json
```

## 9. 排查方法

### 9.1 找不到 `lib_guard`

现象：

```text
ModuleNotFoundError: No module named 'lib_guard'
```

解决：

```powershell
$env:PYTHONPATH = "src"
```

### 9.2 current 被 BLOCK

检查：

```text
release/release_check.json
  block_reasons
  diff_level
  actual_release_level
```

常见原因：

- 没有传 `--diff`。
- scan 是 `inventory`，只有 L0。
- required view 缺失。
- diff status 是 BLOCK。

### 9.3 approved 被 BLOCK

常见原因：

- `diff_level` 不是 `P2`。
- `deep_diff_completed = false`。
- 有 `manual_review_items`。
- release readiness 有 blocking items。

### 9.4 parser PASS_EMPTY

检查：

```text
summary/parser_quality.json
parser_manifest.json
parser_results/<type>/*.json
```

可尝试：

```powershell
& $PY -m lib_guard.cli update type `
  --library-id ip/demo/v1 `
  --type verilog `
  --scope parser-summary `
  --skip-cache `
  --workdir work
```

## 10. 当前建议优化项

### 10.1 项目启动方式需要工程化

当前必须手动设置：

```powershell
$env:PYTHONPATH = "src"
```

建议新增：

- `pyproject.toml`
- console script：`lib_guard = lib_guard.cli:main`
- 可编辑安装方式：`pip install -e .`

这样用户可以直接运行：

```powershell
lib_guard scan ...
```

### 10.2 release_policy 字段命名需要统一

现在代码里存在几类相近字段：

- `required_views`
- `required_file_types`
- `link_views`

建议长期统一为：

```text
required_views      release 准入必需 view
optional_views      可选 view
link_views          release link 时需要实际挂载的 view
```

并让 `required_file_types` 只作为兼容输入，不再作为主配置名。

### 10.3 scan mode 语义需要更清晰

当前 scan mode 包括：

```text
quick / inventory / signature / candidate / release / diff / refresh / full
```

建议明确每个 mode 的行为矩阵：

| mode | hash | parse | summary | readiness | 典型 level |
| --- | --- | --- | --- | --- | --- |
| inventory | no | no | yes | yes | L0 |
| signature | key files | yes | yes | yes | L1 |
| candidate | key files | yes | yes | yes | L1 |
| full | all files | yes | yes | yes | L2 candidate |

### 10.4 doc parser 仍偏弱

当前 doc summary 主要依赖文件名、role、doc_type 识别。

建议增强：

- 提取 title。
- 提取 version/date。
- 提取 change section。
- 提取 known issue / waiver section。
- 判断 release note 是否覆盖 diff 中的主要变化。

### 10.5 approved 的 manual review 关闭机制还需要正式化

现在 `approved` 会检查 `manual_review_items`，但还没有正式 approval/waiver 输入文件。

建议新增：

```text
release/approval.json
```

字段包括：

- reviewer
- approved_at
- approved_review_ids
- waiver_ids
- expiration
- reason

### 10.6 diff P2 覆盖面还需扩展

当前对象级 deep diff 主要覆盖：

- LEF
- Verilog
- Liberty

建议后续扩展：

- CDL subckt / pin order
- SDC clock / constraint
- UPF / CPF power domain / supply

### 10.7 work 输出目录需要生命周期策略

当前 `work/` 会积累 scan、diff、console、cache。

建议新增：

- 保留最近 N 次 scan。
- cache prune。
- console/report archive。
- history index compact。

### 10.8 文档入口需要更显眼

建议新增根目录 `README.md`，内容只保留：

- 工具是什么。
- 3 条快速启动命令。
- 链接到本文档。

## 11. 验证命令

修改代码或配置后，建议运行：

```powershell
$env:PYTHONPATH = "src"
& "C:\Users\Polaris\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" -m unittest discover -s src\lib_guard\test -p "test_*.py"
```

当前已验证：

```text
Ran 60 tests
OK
```
