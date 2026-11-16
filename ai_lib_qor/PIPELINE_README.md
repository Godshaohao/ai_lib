# ai_lib_qor · 交付、事实、检查与报告 MVP

此版对接现有 `versions` 模块，输入输出使用项目 `schemas/` 中的 v3 设计 Schema。它是可执行的最小链路，尚不是全功能生产工作台。

## 运行准备

Python 3.10+，`python3 -m pip install -r requirements-pipeline.txt`。仅生成 JSON / HTML 时需要 `jsonschema`；生成 Excel 另外需要 `XlsxWriter`。在项目根执行：

```bash
export PYTHONPATH="$PWD/src${PYTHONPATH:+:$PYTHONPATH}"
python3 -m ai_lib_qor --help
python3 -m ai_lib_qor.versions --help
```

## 1. 登记一次交付

手工准备 `delivery-config.json`，明确交付事件、顺序以及**每个文件**的逻辑身份，不从版本名称或文件修改时间猜测。

```json
{
  "metadata": {
    "delivery_id": "delivery_008", "vendor_id": "vendor_a", "source_library_id": "library_x",
    "supplier_version": "V08", "delivery_order": 8, "received_at": "2026-10-20T12:00:00+08:00",
    "package_mode": "INCREMENTAL", "scope_confirmed": true,
    "scope_file_keys": ["library_x:lef:core", "library_x:liberty:func_tt"],
    "explicit_removed_file_keys": []
  },
  "file_mapping": {
    "lef/core.lef": {"file_key": "library_x:lef:core", "view": "LEF", "corner": null, "mode": null},
    "lib/func_tt.lib": {"file_key": "library_x:liberty:func_tt", "view": "LIBERTY", "corner": "tt", "mode": "func"}
  }
}
```

```bash
python3 -m ai_lib_qor delivery --root /path/to/RAW/V08 \
  --config /path/to/delivery-config.json --out /path/to/work/deliveries/delivery_008.json
```

扫描严格不跟随符号链接；未映射文件保留为 `UNRESOLVED`，而现有 `versions` 会拒绝应用包含未解决文件的交付。`scope_confirmed` 必须由操作人依据交付信息填写，不由扫描自动证明；建议显式填写 `scope_file_keys`。不可将输出放在 RAW 来源内。交付 ID、顺序和包语义须由上游确认。

## 2. 记录正式 NL 快照

准备包含 `metadata`、`link_mapping`、`deliveries` 的 JSON 配置：

```json
{
  "metadata": {
    "formal_nl_id": "NL2.5.3", "formal_snapshot_id": "snap_0001", "previous_snapshot_id": null,
    "observed_at": "2026-10-21T10:00:00+08:00", "source_library_ids": ["library_x"],
    "views": ["LEF"], "note": "仅示例 LEF", "scope_confirmed": true
  },
  "link_mapping": {"lef/core.lef": "library_x:lef:core"},
  "deliveries": ["/path/to/work/deliveries/delivery_008.json"]
}
```

```bash
python3 -m ai_lib_qor snapshot --root /path/to/formal/NL2.5.3 \
  --config /path/to/formal-config.json --out /path/to/work/formal_nl/NL2.5.3/snapshots/snap_0001/snapshot.json
```

当前只接受明确列出的**文件符号链接**，拒绝目录符号链接。确认完整范围时，扫描根目录中的文件必须与清单一致；未唯一匹配的来源记录为 `UNMATCHED`，不会虚构 RAW。正式 NL 的 `index.json` 尚未实现。

## 3. 提取文件事实

```bash
python3 -m ai_lib_qor facts --delivery /path/to/work/deliveries/delivery_008.json \
  --file-id <交付记录中的file_id> --out /path/to/work/file_facts/facts_001.json
```

`facts_id` 根据固定来源、文件字节摘要及 Parser 版本生成。当前从旧 `src_qor` 移植 LEF 解析器与 Liberty 接口解析函数到 `facts/_compat`，并通过 `facts/parsers.py` 转为 v3；不依赖旧目录运行。原始文件必须是有效 UTF-8（支持 `.gz`），解析中对原始字节摘要做前后比较。当前只提供 LEF Macro SIZE / Pin 和 Liberty Cell / Pin；缺失尺寸、方向、结构不完整、或 LEF 出现 `USE POWER/GROUND` 时拒绝生成可能失真的 v3 事实。暂不支持 SDC 事实、PG Pin 或时序弧。

## 4. 版本与检查

先参考 `VERSIONS_README.md` 用交付或 FormalSnapshot 创建 Rev。检查计划是明确列出目标与基线、FileFacts 路径和待比较文件位的 JSON；[合成示例](examples/pipeline/check_effective.example.json) 从项目根目录可直接使用：

```bash
python3 -m ai_lib_qor check --plan examples/pipeline/check_effective.example.json \
  --out /path/to/work/checks/run_001.json
```

计划可以指定 `target_delivery` / `baseline_delivery`，或 `target_revision` / `baseline_revision`。正式成员引用指向 RAW 事实时，需要提供 `formal_snapshots`，并通过快照的固定文件行验证。结果使用 v3 `check_result.v1`，单次汇总：

- LEF Macro 的增加/移除、SIZE、Pin 增加/移除及 Pin 方向变化；
- 明确指定的一组 LEF Macro / Liberty Cell 的信号 Pin 名称和方向；
- 来源、范围、结果、引用与 v3 `summary`。

未发现已覆盖对象差异时目前显示 `UNKNOWN`，不会错误宣布文件内容 `UNCHANGED`。不完整、空 Pin 集合等不能输出 PASS。仅针对调用方明确列出的比较和配对，不自动搜索全库；`checks/selectors.py` 单独提供按交付排序的最新/次新查询，要求调用方传入扫描覆盖状态。

**证据边界**：CheckResult 检查 FileFacts 与交付/版本/正式快照的 ID 和文件行引用是否一致，但无法从 v3 FileFacts 重新证明事实 JSON 未被人为修改，也不自动读取 RAW 验证其当前字节。它的 PASS 只是对所提供事实及声明范围的判断；真实生产使用前需建立可信产物、字节摘要和证据保护链。v3 示例 Schema 本身不是生产验收证明。

## 5. HTML 和 Excel

```bash
python3 -m ai_lib_qor report --check /path/to/work/checks/run_001.json \
  --html /path/to/reports/run_001.html --excel /path/to/reports/run_001.xlsx
```

HTML 和 Excel 由同一 CheckResult 构建，列出文件变化、Macro/Pin 对象变化、质量检查及证据边界。所有 JSON 历史、报告输出均拒绝覆盖同名文件。检查和报告不触发采纳。

## 测试与尚未完成

```bash
python3 -m unittest discover -s tests -v
```

测试使用临时 RAW 文件和合成示例；未在真实生产库验收。当前还没有通用 YAML 检查插件自动发现 / 注册执行器、生产级输入事实认证、SDC 解析、自动增量缓存、目录符号链接扫描、正式 NL 索引、统一应用服务或工作台 UI。`checks/plugins/` 已按两个独立算法模块组织，当前由汇总器显式调用，不代表 v3.1 的动态插件系统已完成。跨库授权和采纳权限由使用者 / 上层系统负责。

### 按旧版检查报告结构导出 Excel

Excel 现按旧工作台的阅读顺序提供概览、文件版本矩阵、工程检查、执行记录、问答、关注项、Macro/View、正式文件、LEF/Liberty 明细及对象变化。只传 `--check` 也能导出，但 CheckResult 未包含的盘点和解析详情会标为“未提供”。

要填充更多内容，在 `report` 命令上按需增加：

- `--delivery <delivery.json>`：可重复，提供基准和目标交付；最新/次新只代表这些输入覆盖的范围。
- `--facts <facts.json>`：可重复，提供检查关联的 LEF / Liberty 事实。
- `--formal-snapshot <snapshot.json>`：指定一个固定正式快照。
- `--source-snapshot <snapshot.json>`：可重复，提供目标/基准成员引用的历史正式快照，供事实来源核对；不替代上面的展示快照。
- `--target-revision <rev.json>` 和 `--baseline-revision <rev.json>`：为有效版本检查提供对应成员。
- `--effective-index <index.json>` 与 `--accepted-revision <rev.json>`：提供采纳指针和该版本的成员；两者必须匹配。

例如在项目根目录用内置合成数据生成：

```bash
python3 -m ai_lib_qor report --check exports/pipeline_demo/run_demo_001.json \
  --delivery examples/work/vendors/vendor_orion/libraries/lib_rtavfs/deliveries/dlv_20260907_001/delivery.json \
  --delivery examples/work/vendors/vendor_orion/libraries/lib_rtavfs/deliveries/dlv_20261019_001/delivery.json \
  --facts examples/file_facts/facts_core_v07.json --facts examples/file_facts/facts_core_v08.json \
  --facts examples/file_facts/facts_tt_v08.json \
  --formal-snapshot examples/work/formal_nl/NL2.5.3/snapshots/snap_nl253_0002.json \
  --target-revision examples/work/vendors/vendor_orion/libraries/lib_rtavfs/ips/rtavfs/effective/versions/rev_0002.json \
  --baseline-revision examples/work/vendors/vendor_orion/libraries/lib_rtavfs/ips/rtavfs/effective/versions/rev_0001.json \
  --accepted-revision examples/work/vendors/vendor_orion/libraries/lib_rtavfs/ips/rtavfs/effective/versions/rev_0001.json \
  --effective-index examples/work/vendors/vendor_orion/libraries/lib_rtavfs/ips/rtavfs/effective/index.json \
  --excel /path/to/new-report.xlsx
```

生成的表格恢复了旧版的可筛选表格、冻结表头和内容布局，但不是旧 ReviewResult 的字段全量迁移：如 PVT、RC、PG Pin、完整 RAW 盘点等未被当前 v3 输入提供的内容不会被编造；`MacroView` 的同名关联也不自动证明跨 View 完整或通过。

## 补充解析证据与检查插件

现支持从明确登记的 LEF、Liberty、Verilog、CDL 交付文件生成独立解析证据：

```bash
python3 -m ai_lib_qor facts-evidence --delivery /path/to/delivery.json \
  --file-id <file_id> --out /path/to/work/parser_evidence.json
```

证据为 `parser_evidence.v1`（新工程内部辅助记录），不是 v3 `file_facts.v1`，并不改变原有 v3 合同。它记录原始文件 SHA-256、解析器、旧版解析数据与内容摘要；覆盖统一标记 `PARTIAL`，不代表全面解析或质量通过。摘要可检查意外内容变化，但记录和摘要如果都被修改，不能证明来源可信。工作台的“库与版本”可对已登记文件触发提取，并生成 JSON 和独立 HTML。必须使用可读取的真实源文件；示例中的 `/example/...` 只是占位路径。

检查计划可以指定 `plugins` 为已注册插件 ID 列表；省略时使用 LEF 差异和 LEF–Liberty 检查。注册表位于 `checks/registry.py`，只执行开发者登记的可信函数，不从计划导入任意代码。插件只返回 `file_changes` / `quality_checks` 贡献；当前重叠文件贡献会因重复身份被拒绝，不支持通用合并或独立证据 Gate。

可选 `auto_pair_facts`：

```json
"auto_pair_facts": [
  {"file_key": "lib:lef:core", "facts": "/path/to/lef_facts.json"},
  {"file_key": "lib:liberty:tt", "facts": "/path/to/liberty_facts.json"}
]
```

它只在明确列出的完整名称覆盖事实内，将 LEF 的全部 Macro 与 Liberty Cell 名称配对；多个 LEF 声称同一 Macro、名称缺失或无匹配会报错。结果仍需通过目标版本 / 交付来源校验，不代表检查所有库文件。该步骤不从 RAW 自动生成事实、不推断 PVT/Corner，也不等同旧版一键检查。
