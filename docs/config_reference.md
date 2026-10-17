Status: current

# 配置参考

`lib_guard` 当前只有两类配置：

- 项目级策略：放在 `configs/`，随代码维护。
- Workspace 配置：由 `lg init` 生成，随一次审查工作区维护。

## 文档契约

| 项 | 说明 |
| --- | --- |
| 目标读者 | 需要修改库发现、扫描策略、release policy 或 workspace 默认值的人 |
| 可手改 | `configs/*.json`、`$WORK/lib_guard.yml`、`$WORK/config/library_registry.tsv`、override 文件 |
| 不手改 | `catalog.json` 的运行时字段、scan/diff/release 输出、HTML |
| 修改原则 | 策略改源码配置，项目实例改 workspace 配置，人工事实改 registry/override |
| 验证 | 改策略后至少跑 dry-run、单库 scan/cmp 和 repository cleanup 测试 |

默认路径、策略文件名和 workspace 派生路径集中定义在
`src/lib_guard/project_config.py`。命令和渲染代码应复用这些常量，避免散落字符串。

生成的 HTML、scan、diff、release 输出不是源码；`work/`、`reports/`、
`manual_preview/` 都是本地产物。

## 根目录

| 路径 | 作用 | 是否手改 |
| --- | --- | --- |
| `src/` | Python 源码 | 是 |
| `configs/` | 默认项目策略 | 是 |
| `examples/` | 可复制到 workspace 的示例 | 是，复制后再改 |
| `docs/` | 当前产品和配置文档 | 是 |
| `manual_preview/` | 本地浏览器预览 | 重新生成，不当源码 |
| `work/` | 本地 scan/diff/release 输出 | 生成物 |
| `reports/` | 本地报告输出 | 生成物 |

## 项目策略

| 文件 | 控制内容 | 合理修改 |
| --- | --- | --- |
| `configs/catalog_policy.json` | RAW 发现、版本路径模式、stage 规则、忽略目录 | 增加真实 RAW pattern，调整 ignored dirs/stage 匹配 |
| `configs/release_policy.json` | 必需/可选 View、Mode、Corner、校验等级、release alias gate | 按库类型调整交付要求；不要把扫描模式或链接方式写进 required_modes |
| `configs/semantic_review.json` | 跨视图诊断方案：宏、文件、Corner/Mode、规则、属性期望和尺寸容差 | 由 `python -m lib_guard.semantic.cli` 读取；检查方案独立于正式发布门禁 |
| `configs/library_versions.example.tsv` | 版本引用表示例 | 复制到 workspace 作为 `config/library_versions.tsv` 使用 |

## Workspace 配置

### 跨视图诊断方案

`configs/semantic_review.json` 提炼了 Facts / 按需组装 / Python 规则方案中当前可执行的配置。
配置只选择已有扫描事实和已实现规则，不修改解析覆盖声明。无需再建立 `check/` 或插件框架，
执行代码集中在 `src/lib_guard/semantic/`。

| 配置项 | 用途 | 默认值或约束 |
| --- | --- | --- |
| `default_profile` | 省略 `--profile` 时使用的方案 | `default` |
| `profiles.<名称>.mapping` | 人工确认的对象/端口别名与文件上下文配置 | null 时不用映射；相对路径相对于检查配置文件 |
| `facts_cache.reuse` | 复用已有文件 Facts；设为 false 可重算验证 | 默认 true；关闭时仍持久化 Facts，且不重新读取 RAW |
| `facts_cache.directory` | 多次诊断共享的 Facts 存储目录 | null 时为 `<out>/facts`；相对路径相对于本配置文件 |
| `profiles.<名称>.macros` | 选定宏；匹配确认别名后的名称 | 空列表表示全部宏；区分大小写 |
| `required_views` | 本次纳入组装且要求具备的视图 | `lef/liberty/verilog`；这些视图缺失时绑定不能确认 |
| `files` | 按视图限制文件路径，如 `{"lef": ["lef/*.lef"]}` | 省略的视图使用 `*`；使用有效组合内的相对路径，`*` 可以跨目录 |
| `liberty.selected` | Liberty 上下文选择列表 | 空列表不限制；各项之间取并集 |
| `liberty.selected[].files` | 该上下文的文件候选模式 | 字符串或列表；同一项内与 Corner/Mode 条件同时满足 |
| `liberty.selected[].corner` | 选择确认过的工艺角 | 如 `TT`，与扫描语义证据精确匹配 |
| `liberty.selected[].mode` | 选择确认过的运行模式 | 如 `functional`，与扫描语义证据精确匹配 |
| `checks` | 本次执行并报告的 Python 规则 | 只接受下表已有的规则名，拼写错误会提示 |
| `flag_policy` | Liberty 属性的项目期望 | 如 `{"is_macro": true, "is_pad": false}`；空对象不作属性要求 |
| `tolerance_um` | LEF 尺寸、原点比较的绝对容差，单位微米 | 默认 `0.000001`，不改变端口和几何集合的规则 |

| 规则名称 | 已实现的检查 |
| --- | --- |
| `MACRO_BINDING` | 宏与跨视图来源能否唯一对应 |
| `SIGNAL_PORT_SET` | 当前组合的信号端口集合一致性 |
| `SIGNAL_PORT_DIRECTION` | 当前组合的信号端口方向一致性 |
| `PG_PORT_LEF_LIB` | LEF / Liberty 电源地端口一致性 |
| `LIB_MACRO_FLAGS` | Liberty `is_macro/is_pad` 是否满足本方案期望 |
| `LEF_SIZE_DELTA` | 新旧组合的宽、高、原点变化 |
| `LEF_PIN_DELTA` | 已有规则支持的 LEF 引脚集合、层和几何变化；覆盖不足时为 UNKNOWN |
| `PORT_DECLARATION_DELTA` | 已有 Verilog 端口声明方向变化 |
| `LIB_PORT_DELTA` | 分 Corner 比较 Liberty 信号端口集合/方向，以及电源地端口角色 |
| `LEF_MACRO_DELTA` | 完整发现、无歧义的 LEF Macro 增删；无旧有效组合时为 INCOMPLETE |
| `LEF_PHYSICAL_DELTA` | Size / Class / Origin / Symmetry 变化 |
| `LEF_INTERFACE_DELTA` | Pin Name / Direction / Use 变化，总线按明确 BUSBITCHARS 归一化 |
| `LEF_GEOMETRY_DELTA` | 显式 PORT 分组下的 RECT 变化；POLYGON/VIA/MASK/ITERATE 等为 INCOMPLETE |
| `LEF_OBS_DELTA` | RECT 范围的 OBS 变化；未支持或遗漏几何不授予 UNCHANGED |

`lef_basic` 是 LEF-first 验收方案，仅纳入 LEF；不要求提前具备 Liberty/Verilog 绑定。
Web 的“有效组合 → 技术检查报告”读取本文件中的方案与规则，支持本次任务勾选规则子集。
工作区 `lib_guard.yml` 可设置 `semantic_review_config: config/semantic_review.json`，路径相对于工作区；
不设置时继续使用仓库 `configs/semantic_review.json`。Web 默认方案遵循配置的 `default_profile`。
每次执行固定目标/基准并写入任务内 `review_config.json`，有映射时还冻结 `review_mapping.json`，不改全局配置；不接受任意脚本、
输出路径、补扫或发布参数。报告仅保存为 Markdown/JSON 文件，运行台只提供状态、日志和下载。
本方案在原结果索引中增加 `macro_index`，列出 Macro、Variant、Size、Class、Pin Count、
来源候选和状态。READY 仅表示该 LEF 对象的关联与摘要可用，不是几何、IP 质量或发布通过。
持久文件 Facts 不复制完整 Pin/OBS 几何；`LefCheckFacts` 在本次任务内复用已读取的源 ParserResult，
按需提供接口、物理和阻挡检查数据，结束后释放。旧扫描或 counts-only 证据不足时输出 INCOMPLETE，
不会自动重读 RAW 或偷偷补扫；需要完整范围时由操作者明确更新扫描证据。

运行示例：

```bash
PYTHONPATH=src python3 -m lib_guard.semantic.cli \
  --effective-manifest /path/to/new/effective_manifest.json \
  --base-effective-manifest /path/to/old/effective_manifest.json \
  --catalog /path/to/catalog.json --profile lef_basic --out /path/to/lef_review
```

LEF Parser 2.5 保留 RECT 的 PORT 分组并隔离 PROPERTYDEFINITIONS；识别引号内的分号/井号、
跨行属性字符串和同行多条分号语句。VIARULE/VIA/SITE 内的 LAYER 引用不会覆盖技术层定义。
不支持的几何语法、重复名称和截断结构都有覆盖限制。LEF 坐标按微米解释，DATABASE MICRONS
表示数据库分辨率，不能因文件省略该语句就丢掉真实 SIZE。

独立 Reader 交叉验收采用 `lefdef 0.6.0` 的 Cadence Reader 封装，仅安装在隔离验收目录，
不是项目的强制运行依赖。其矩形封装不作为 POLYGON 全语义相同的证明。
可复现实验见 `python -m lib_guard.test.lef_review_rehearsal --out <验收目录>`，需在该实验的
PYTHONPATH 中加入安装了 lefdef 的目录。它不会被日常 scan 自动执行。

内置 `default` 保持原有诊断范围；`ip_basic` 为 TT/SS、functional、`is_macro=true` 的可选方案。
项目实际不需要这些条件时应编辑或另建方案，不能将示例当作所有 IP 的统一要求。
`liberty.selected` 选择的是本次语义检查范围，不是“全部必交 Corner 清单”；交付完整性要求仍在
`release_policy.json`。同一旧/新对比共用一份方案；文件级 Delta 仍由原有 `cmp` 覆盖全部有效文件。

文件路径只用于选择候选，不为 Corner/Mode 背书。上下文必须来自扫描结果中
`semantic_context.confirmed=true`、明确 `basis` 及相应 `corner/mode`，或来自显式人工配置。
两者均未提供上下文时，报告显示所选上下文不可用，不能仅凭 `*tt*.lib` 输出通过。
配置也不能让未声明完整覆盖的解析结果获得端口集合 PASS。

人工上下文映射文件示例：

```json
{
  "confirmed": true,
  "library_id": "ip/Vendor_A.demo",
  "basis": "负责人核对交付说明与 library 声明后确认 TT 功能视图",
  "file_contexts": [
    {"view": "liberty", "files": ["lib/functional/*_TT.lib"], "corner": "TT", "mode": "functional"}
  ],
  "macro_aliases": [{"view": "verilog", "object": "renamed_top", "macro": "original_top"}]
}
```

`file_contexts` 的 `files` 是有效组合内相对路径模式列表；`view` 限 lef/liberty/verilog，
每项至少设置 corner/mode/variant 之一。多个规则命中同一文件、与已确认扫描上下文冲突、
配置未命中可用事实时明确报错。`macro_aliases` 只在名称确实不同且已确认对应关系时设置；唯一精确名称不需要手工逐个登记。
配置只作用于本次 Model，原扫描及共享 Facts 不改写。Web 要求映射的 library_id 与当前库一致，
其他库的方案不会混入选项；提交后修改配置不影响已冻结的任务。

Liberty Parser 2.4 按实际嵌套组读取 cell、pin、pg_pin，不把模板/时序组闭合当作 library 结束；
只声明标量端口集合覆盖，不证明时序表等价。缺分号、截断、重复声明或未支持总线仍保留覆盖不足，
源位置会写入 Markdown 的“输入证据限制”。Verilog Parser 2.3 按 module 隔离端口，支持简单 ANSI 声明继承和常量范围；
条件编译接口、参数求值、连接关系不授予完整检查结论。
Liberty 明确声明 `direction: internal` 的节点不计入外部信号接口，但仍完整保留在源 ParserResult 中；
未知方向不作此排除。Macro 的工艺角覆盖按 `(名称, variant)` 分别核对，不允许不同 variant 相互补足缺项。

文件 Facts 现在独立保存在 `facts_cache.directory`，按解析输出内容、Parser 版本、Facts schema
和转换代码指纹复用。来源版本、原始路径与 Corner/Mode 在读取时绑定到独立来源引用，
不复制进共享 Facts。其内容指纹针对已有 ParserResult，不代表原始文件内容已经验证。
配置不控制重新解析或自动补扫；原始文件解析仍使用 ScanCache，诊断不读取 RAW 内容或计算 RAW hash。
未具备内容 hash 的 ScanCache 不跨来源路径复用；具备相同内容 hash 的 Parser 缓存命中后，
结果来源重新绑定到当前文件。外部 EDA 工具验证仍是独立后续工作。

每次快照的 `summary.json.review_profile` 保存归一化后的完整方案及指纹，`scope.current/base`
记录双方选中文件、排除文件、选中 Corner/Mode、缺少宏和逐宏上下文缺项。配置变化产生新快照，
旧快照保留。Markdown 摘要同步显示方案及覆盖范围；未选中项不具有本次语义检查结论。
`rules_identity` 保存规则版本及实际 Python 代码指纹，`mapping` 保存当次确认映射。
`snapshot.json` 校验同快照全部产物；相同快照不重写，写入失败保持旧 `summary.json` 指针。

共享配置示例（新增到配置顶层，与 `profiles` 同级）：

```json
"facts_cache": {"reuse": true, "directory": "../work/index/semantic_facts"}
```

Facts 一旦被历史结果引用，就属于需要保留的诊断证据。迁移或备份时携带该目录，
不要按临时缓存随意删除。快照的索引及宏来源保存 Facts 引用，不为每版复制完整解析对象。
历史回读只依赖快照与 Facts，不需要 Catalog、RAW、扫描目录、Web Job 或 HTML：

```python
from lib_guard.semantic.results import load_review_snapshot
result = load_review_snapshot("work/semantic_review")
# 读取指定历史快照时传入 generation=<summary 中的 64 位指纹>。
```

### 交付要求 View / Mode / Corner

`release_policy.json` 中的 `required_views` 继续负责文件类型检查；新增的
`required_modes` 和 `required_corners` 只表示这个库实际必须交付的运行模式和工艺角，
不等同于扫描命令的 `scan_mode`，也不等同于 `symlink/copy` 链接方式。例如：

```json
{
  "required_views": {
    "ip": ["lef", "liberty", "verilog", "cdl"]
  },
  "required_modes": {
    "ip": ["functional", "scan"]
  },
  "required_corners": {
    "ip": ["tt_0p8v_25c", "ss_0p7v_125c"]
  }
}
```

扫描会把三类要求统一写入 `summary/release_readiness.json`。`parsed_required` 的 View
必须逐一关联清单文件、成功 Parser Task 和实际解析结果文件；缺任务、跳过、失败、空结果、仅元数据或结果文件缺失均不能判为解析通过。`metadata_required` 只表示文件已登记，不代表内容或语义解析通过。版本详情页会显示解析覆盖数及未完成文件。

Mode/Corner 的路径和文件名提取值只是候选提示，不等于已确认的交付覆盖。只有显式写入
`scan_meta.json` 的 `delivery_modes` / `required_modes_observed` 和
`delivery_corners` / `required_corners_observed` 才参与已确认匹配；报告会分别呈现确认值、
路径提示和证据来源。当前命令行没有独立的人工确认写入命令，因此若策略配置了必需 Mode/Corner，
但扫描输入未提供显式确认值，结果会保持未满足并指出可用提示，不能仅凭文件名通过。
配置为空时明确显示“未配置口径”，不会自动推断为全面通过。

`lg init` 会在 workspace 下写出 `lib_guard.yml`。常用字段如下：

```yaml
config_version: lib_guard_config.v1
workspace: <work root>
raw_root: <raw library root>
catalog: <workspace>/catalog/catalog.json
catalog_html: <workspace>/catalog/html
reports: <workspace>/reports
diff: <workspace>/diff
file_diff: <workspace>/file_diff
release_root: <workspace>/release_area
versions: <workspace>/config/library_versions.tsv
actions_dir: <workspace>/actions
library_type: ip
mode: scan
parse_jobs: 8
hash_policy: smart
parse_file_types: lef,cdl
parse_exclude_file_types: verilog,liberty,spef
render_detail: true
```

`config_version` 是配置契约版本。旧配置缺少该字段时按
`lib_guard_config.v1` 读取；未知版本会立即失败，避免新旧语义被静默混用。
`load_workspace_config()` 提供类型化的 `parse_jobs`、`render_detail` 等字段；
现有调用方仍可通过 `load_config()` 读取兼容字典。

也支持 `config_dir`、`library_list`、`library_catalog`、`library_versions`。
如果自定义 `config_dir`，除非显式覆盖，派生配置文件会跟随这个目录。

`mode` 仍保留在配置里，是为了识别旧脚本和历史 scan evidence。当前用户态只使用
一种 `scan`，扫描深度通过策略字段控制：

- `hash_policy`
- `parse_file_types`
- `parse_exclude_file_types`
- `parse_jobs`

短命令会读取这些字段并传给底层 `run` / `run-batch` / compare 预扫描；
`lg scan` 命令行上的同名参数只覆盖本次扫描。

## 配置优先级

从高到低：

| 优先级 | 来源 | 说明 |
| --- | --- | --- |
| 1 | 命令行参数 | 只影响本次命令，例如 `--parse-jobs 16` |
| 2 | Workspace `lib_guard.yml` | 当前工作区默认值 |
| 3 | Workspace registry / overrides | 人工确认库根、版本关系、package type/Base |
| 4 | 项目 `configs/*.json` | 默认策略 |
| 5 | 代码默认值 `project_config.py` | 最后兜底，不应散落在业务代码里 |

实现代码必须使用 `merge_config_overrides()` 合并本次运行参数。值为 `None` 表示
“未覆盖”，不能清空 workspace 配置；未知覆盖项必须失败。

如果命令行为不符合预期，先用 `lg --dry-run ...` 看短命令展开，再检查上述顺序。

## 解析器证据

Version Review 从这些产物读取 parser 证据：

- `parser_manifest.json`
- `parser_results/<view>/*.json`（默认逐文件 Parser 事实；旧版聚合 `parser_results.json` 仅兼容/调试）
- `summary/parser_quality.json`

默认页面不会读取重型 view 内容。`.lib/.lib.gz`、`.db`、`.spef` 和 layout/binary
文件会走 count-only、summary-only 或 metadata-only 证据：统计、分类、hash、size、
路径、corner hint，而不是打开全文。

Verilog parser 是轻量 parser，只记录：

- `module`
- `port`
- `direction`
- `width`
- `declared_range`
- `module_count`
- `port_count`

它不解析 `instance`、`parameter_value`、`generate_block`、`always_block`、
`assign_expression`、`gate_netlist_connectivity`。大型综合网表默认应按
summary/metadata 策略处理，除非后续明确引入专用 netlist parser。

## Scan Evidence 输出策略

scan 同时输出机器事实和人工证据。配置和页面必须区分这两类：

| 输出 | 是否事实源 | 是否人工主界面 | 说明 |
| --- | --- | --- | --- |
| `file_inventory.json` | 是 | 否 | 完整文件事实，供 diff/release/render 读取 |
| `parser_manifest.json` | 是 | 否 | parser 任务事实 |
| `parser_results/<view>/*.json` | 是 | 否 | 原始 parser 结果，按文件保存，供摘要/详情页按需读取 |
| `parser_results.json` | 旧版 | 否 | 聚合 Parser 结果；新 CLI 默认不生成，仅兼容旧扫描和调试 |
| `review/view_coverage.tsv` | 派生证据 | 是 | view 覆盖矩阵 |
| `review/files_by_view.tsv` | 派生证据 | 是 | 数量背后的文件清单 |
| `review/unknown_files.tsv` | 派生证据 | 是 | unknown 文件分类入口 |
| `review/large_metadata_files.tsv` | 派生证据 | 是 | summary-only / metadata-only 文件 |
| `review/parser_evidence.tsv` | 派生证据 | 是 | parser 覆盖和失败摘要 |

后续新增 scan 输出时必须先判断它属于 machine、review 还是 debug；不能继续把所有 JSON
平铺到主页面。

## Version List

版本列表把短引用映射到真实版本名；它按单个 library 生效。

```text
library_id	version_ref	version_id
ucie	lib1	stable_20260601
ucie	lib2	adhoc_01
ucie	lib3	adhoc_02
```

允许修改：

- 新增或删除行。
- 改 `version_ref`。
- RAW 目录名变化时改 `version_id`。

V1 不建议把这些字段塞进 version list：

- `enabled`
- `scope`
- `package_type`
- `stage`
- `status`

这些应该由 catalog 推断，或通过小型 override 文件处理，不要混入主版本列表。

## Action 文件

Action 文件位于：

```text
$WORK/actions/<library>.action
```

支持的 action verb 和用户流程见 [基础教程](basic_tutorial.md) 与
[CLI 参考](cli_reference.md)。可复制示例位于 `examples/ucie.action.example`。

## 不要手改的生成物

这些文件是输出，应重新生成，不应手改：

- `catalog/catalog.json`
- `catalog/catalog_runtime.json`
- `catalog/html/index.html`
- `catalog/html/catalog_state.json`
- `catalog/html/manager_tasks.json`
- `catalog/html/report_index.json`
- `scan_out/**`
- `diff/**`
- `release_area/**`
- `manual_preview/**`

说明：

- `catalog_state.json` 是 Catalog HTML 的页面状态模型。
- `manager_tasks.json` 是管理者视角的缺失 scan/diff/relation evidence 任务列表；
  它有效，但不是普通 IP 使用者消费更新的主路径。
- 版本详情页会展示“解析器摘要”“对比摘要”“仅计数与工艺角摘要”；
  这些都来自 scan 和 diff artifacts。
- `manual_preview/**` 只是本地浏览器预览，已被 git 忽略。
- Parser 或 summary evidence 必须通过
  `lg.csh scan <LIBRARY> <VERSION> --rescan` 重建。

## 配置修改检查清单

修改配置后按顺序确认：

```csh
lg --dry-run library list
lg --dry-run scan <LIBRARY> <VERSION>
lg --dry-run cmp <LIBRARY> <VERSION> --base <BASE_VERSION> --scan-if-missing
```

然后至少执行一个小闭环：

```csh
lg scan <LIBRARY> <VERSION> --no-render
lg cat <LIBRARY> <VERSION>
```

如果修改了 discover 策略，还要确认候选数量和正式库数量没有异常收缩：

```csh
lg library discover --max-depth 4 --max-dirs 5000 --max-candidates 200
lg library list --plain
```

## 本地预览

本地浏览器预览通常位于：

```text
manual_preview/catalog/html/index.html
```

这个目录只用于人工检查页面效果，不作为源码维护。
