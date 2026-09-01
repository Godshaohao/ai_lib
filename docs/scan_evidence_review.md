Status: current

# 扫描证据分层与人工审查口径

`scan` 的核心职责是把一个版本目录转成可复用的证据包。证据包同时服务两类对象：

- 机器流程：后续 `diff`、Version Detail、release check、cache 和自动化调度。
- 人工审查：IP 使用者、库管理员和 release owner 快速判断版本是否可继续接入。

这两类对象不能混在一个页面里。JSON 是机器事实源，不应成为人工 review 的主要界面。

## 文档契约

| 项 | 说明 |
| --- | --- |
| 目标读者 | 扫描维护者、版本详情页维护者、需要检查扫描证据的审查人员 |
| 事实源 | scan 生成的 `file_inventory.json`、`parser_manifest.json`、`parser_results/<view>/*.json`、summary JSON；旧扫描可继续使用 `parser_results.json` |
| 人工证据 | 扫描生成的 `review/*.tsv` 和扫描 HTML 聚合表 |
| 禁止做法 | 把 raw JSON、parser 原始结果、cache/progress 日志直接放到主审查页面 |
| 验证 | 扫描流程测试、扫描 HTML 测试、版本详情页测试 |

## 设计结论

默认审查页面只展示可决策信息：

- scan 是否成功。
- 关键 view 是否存在。
- 未知文件是否需要分类。
- 大文件采用哪种证据等级。
- parser 是否失败。
- 每个 view 下面有哪些文件。
- 下一步应该进入 diff、补分类、重扫，还是阻塞。

原始 JSON、hash、cache、progress、parser 原始结果只作为调试证据折叠或下沉。

## 产品输出契约

扫描输出不是“把所有扫描中间结果都给人看”，而是一个分层证据包：

| 层级 | 默认入口 | 解决的问题 | 是否进入首屏 |
| --- | --- | --- | --- |
| 人工摘要 | `review/scan_review.md`、扫描 `index.html` | 这个版本能否继续审查、有哪些异常 | 是 |
| 人工证据 | `review/*.tsv` | 数量对应哪些具体文件、哪些 View 使用什么证据等级 | 文件证据表进入，原始表按需打开 |
| 机器事实 | `manifest.json`、`file_inventory.json`、`parser_manifest.json`、`state_delta.json`、`signatures/` | 供 diff、release、缓存和详情页消费 | 否 |
| 调试材料 | `logs/`、原始解析器 JSON | 排查性能、失败和实现问题 | 否 |

这四层不能互相冒充：

- `scan_review.md` 是人工阅读摘要，不是机器事实源。
- `*.tsv` 是人工证据索引，不替代完整 inventory。
- JSON 是机器接口，不作为人工主页面。
- 日志只解释“系统怎么运行”，不能用来判断“库是否可用”。

扫描页面只保留一个真实页面：`index.html`。历史入口 `scan_report.html` 继续保留，但只做兼容跳转，不再复制完整 HTML。重新渲染旧扫描目录时，如果缺少 `review/scan_review.md`，渲染器会按现有 TSV/JSON 生成它，避免出现死链接。

## 证据分层

| 层级 | 面向对象 | 内容 | 展示方式 |
| --- | --- | --- | --- |
| L1 审查摘要 | IP 使用者 / 库管理员 | 扫描结论、视图覆盖、未知文件、解析器失败、下一步 | 版本详情页 / 扫描 HTML 第一屏 |
| L2 人工证据表 | 审查人员 | 视图文件表、未知文件表、大文件表、解析器证据表 | TSV/HTML，可筛选、可复制 |
| L3 机器事实 | 自动化流程 | inventory、parser manifest、signatures、issues、readiness | JSON，供 diff/render/release 读取 |
| L4 调试日志 | 工程调试 | progress、cache events、parser errors、raw parser results | debug 区域，默认不展示 |

## 当前产物分层

当前 scan 仍保留部分历史 JSON 文件以兼容已有流程。它们不是都无效，但默认暴露给人会淹没重点。
新的人工审查入口是 `review/*.tsv`。

| 当前文件 | 问题 | 建议 |
| --- | --- | --- |
| `manifest.json` | 历史机器入口 | 兼容保留；新人工页面不直接展示 |
| `scan_summary.json` | 名字像人工摘要，实际偏机器摘要 | 兼容保留；人工摘要来自 `review/scan_review.json` |
| `type_distribution.json` | 只是派生计数 | 用 `review/view_coverage.tsv` / `files_by_view.tsv` 给人看 |
| `version_profile.json` | 从 manifest 拆出的局部信息 | 兼容保留；不作为主页面内容 |
| `parser_results.json` | 聚合结果可能非常大，人工无意义 | 旧扫描兼容/显式调试；新 CLI 默认不写，统一从 `parser_results/<view>/*.json` 读取 |
| `file_inventory.json` | 完整文件清单，机器需要但人难读 | 生成 `files_by_view.tsv` 给人看 |
| `parser_manifest.json` | parser 任务细节 | 生成 `parser_evidence.tsv` 给人看 |
| `signatures/signatures.json` | diff/cache 需要 | 机器事实，不进默认页面 |
| `logs/cache_events.json` | 性能调试 | debug only |
| `logs/scan_progress.jsonl` | 进度追踪 | debug only |
| `summary/release_readiness.json` | release 检查参考 | Version Detail 聚合后展示，不在 scan 页面默认展开 |

## 输出结构

当前兼容期仍会写旧文件名；新代码和页面应按下面的分层读取：

```text
scan_<id>/
  review/
    scan_review.json
    scan_review.md
    view_coverage.tsv
    files_by_view.tsv
    unknown_files.tsv
    large_metadata_files.tsv
    parser_evidence.tsv
    required_view_check.tsv

  file_inventory.json
  parser_manifest.json
  parser_results/          # 默认逐文件 Parser 结果
    <view>/*.json
  summary/
  signatures/
  logs/
```

后续如果移动到 `machine/` / `debug/` 子目录，必须先提供兼容读取层和迁移测试，不能让
diff/release/render 断链。

## 人工表定义

### `view_coverage.tsv`

用于回答“这个版本有哪些可用 view”。

| 字段 | 含义 |
| --- | --- |
| `view_type` | 规范化 view 类型，如 `LEF`, `Liberty`, `Verilog`, `GDS`, `SDC` |
| `file_type` | 原始分类，如 `lef`, `liberty`, `verilog` |
| `count` | 文件数量 |
| `required` | 当前库类型/策略下是否必需 |
| `evidence_level` | `parsed`, `summary_only`, `metadata_only`, `count_only`, `unknown` |
| `status` | `PASS`, `WARNING`, `BLOCKING`, `INFO` |
| `meaning` | 中文审查含义 |

### `files_by_view.tsv`

用于回答“数量背后的文件在哪里”。

| 字段 | 含义 |
| --- | --- |
| `view_type` | 规范化 view 类型 |
| `file_type` | 原始分类 |
| `role` | `tech_lef`, `gate_netlist`, `release_note` 等轻量角色 |
| `size_bytes` | 文件大小 |
| `evidence_level` | 证据等级 |
| `path` | 相对版本根目录路径 |

### `unknown_files.tsv`

用于回答“哪些文件没识别，是否要补规则”。

| 字段 | 含义 |
| --- | --- |
| `path` | 相对路径 |
| `extension` | 文件扩展名 |
| `size_bytes` | 文件大小 |
| `suggested_action` | `classify`, `ignore`, `add_rule`, `owner_confirm` |
| `reason` | 中文原因 |

### `large_metadata_files.tsv`

用于回答“大文件是否被误当成没审查”。

| 字段 | 含义 |
| --- | --- |
| `view_type` | `GDS`, `DB`, `OAS`, `SPEF`, `Liberty`, `Verilog` 等 |
| `path` | 相对路径 |
| `size_bytes` | 文件大小 |
| `evidence_level` | `summary_only` 或 `metadata_only` |
| `review_policy` | 为什么不做内容级 parser / 默认 file diff |

### `parser_evidence.tsv`

用于回答“parser 到底做了什么”。

| 字段 | 含义 |
| --- | --- |
| `file_type` | 原始分类 |
| `parser` | parser 名称 |
| `tasks` | 任务数 |
| `parsed` | 成功解析数 |
| `empty` | 空结果数 |
| `failed` | 失败数 |
| `status` | `PASS`, `PASS_EMPTY`, `FAILED`, `SKIPPED` |

## 页面展示规则

Scan 页面第一屏只保留四块：

1. 扫描结论：`PASS / WARNING / FAILED`。
2. 视图覆盖矩阵：按 view 聚合数量、证据等级、状态。
3. 需要处理的问题：unknown、parser failed、required view missing。
4. 下一步：进入 diff、补分类、重扫或停止。

默认不要展示：

- 原始 `file_inventory.json`。
- 完整 parser 原始结果。
- cache events。
- signatures hash 明细。
- progress JSONL。
- 大量 module/macro/pin 代表对象。

这些内容应在“调试证据”折叠区或单独 evidence 页面中提供链接。

## 与 Version Detail 的关系

版本详情页是唯一主审查投影。扫描页面只是单版本扫描证据页。

Version Detail 应读取 scan 的人工证据表和机器事实，组合成：

- 当前版本基本覆盖情况。
- 相对 base 的 view delta。
- 使用场景影响。
- 必须确认项。
- 调试证据入口。

如果没有 diff，Version Detail 仍应展示 scan 覆盖，而不是空白或伪装成“无变化”。

Version Detail 页面不应内嵌 scan raw 绝对路径、`scan_html` 绝对路径或完整 JSON 内容。
它只展示证据状态和人工表名；需要调试时打开 scan HTML 或 JSON artifact。

## 后续落地顺序

已落地：

- `scan/evidence_export.py` 从 scan bundle 生成人工 TSV。
- `scan/evidence_export.py` 同时生成一页人工可读的 `review/scan_review.md`。
- `render/html_report.py` 优先读取人工证据表。
- `render/html_report.py` 只生成一个完整的 `index.html`；`scan_report.html` 仅作为兼容跳转。
- 扫描页面不再重复嵌入旧版完整文件清单，工艺角/解析器明细默认折叠。
- 版本详情页通过 `version_evidence_state` 说明事实源状态，但不展示 raw 绝对路径。

待收敛：

1. 统一 `file_type -> view_type -> evidence_level` 映射。
2. 每个 view 数量都必须能展开到文件列表。
3. unknown 文件必须给出建议动作。
4. 已收紧 `parser_results.json` 的写出策略：`lg scan` 和目录驱动扫描默认不生成聚合文件；旧扫描仍可读取，逐文件结果保持为唯一默认 Parser 事实。
5. `manifest.json` / `scan_summary.json` / `type_distribution.json` 制定废弃或兼容窗口。

P2：

1. 增加配置：

```yaml
scan_output_policy:
  debug_json: false
  write_raw_parser_results: false
  max_inline_files_per_view: 50
```

2. 将 raw JSON 移到单独 evidence/debug 页面，减少主 HTML 搜索噪音。

## 审查原则

- 数量不能替代文件清单。
- JSON 不能替代人工证据表。
- `summary-only` / `metadata-only` 是证据等级，不自动代表不完整。
- 算法推断只能作为提示，不能作为事实结论。
- 默认页面应让用户做判断，而不是要求用户读完整数据结构。
