Status: current

# 配置参考

`lib_guard` 当前只有两类配置：

- 项目级策略：放在 `configs/`，随代码维护。
- Workspace 配置：由 `lg init` 生成，随一次审查工作区维护。

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
| `configs/release_policy.json` | 必需/可选 view、校验等级、release alias gate | 按库类型调整 required views、doc policy、alias gate 严格度 |
| `configs/library_versions.example.tsv` | 版本引用表示例 | 复制到 workspace 作为 `config/library_versions.tsv` 使用 |

## Workspace 配置

`lg init` 会在 workspace 下写出 `lib_guard.yml`。常用字段如下：

```yaml
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
```

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

## Parser Evidence

Version Review 从这些产物读取 parser 证据：

- `parser_manifest.json`
- `parser_results.json`
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
- Version Review 会展示 `Parser Summary`、`Diff Summary`、`Count-only + Corner Summary`；
  这些都来自 scan 和 diff artifacts。
- `manual_preview/**` 只是本地浏览器预览，已被 git 忽略。
- Parser 或 summary evidence 必须通过
  `lg.csh scan <LIBRARY> <VERSION> --rescan` 重建。

## 本地预览

本地浏览器预览通常位于：

```text
manual_preview/catalog/html/index.html
```

这个目录只用于人工检查页面效果，不作为源码维护。
