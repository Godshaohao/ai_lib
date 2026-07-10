Status: current

# Scan 证据分层与人工审查口径

`scan` 的核心职责是把一个版本目录转成可复用的证据包。证据包同时服务两类对象：

- 机器流程：后续 `diff`、Version Detail、release check、cache 和自动化调度。
- 人工审查：IP 使用者、库管理员和 release owner 快速判断版本是否可继续接入。

这两类对象不能混在一个页面里。JSON 是机器事实源，不应成为人工 review 的主要界面。

## 文档契约

| 项 | 说明 |
| --- | --- |
| 目标读者 | scan 维护者、Version Detail 维护者、需要检查扫描证据的 reviewer |
| 事实源 | scan 生成的 `file_inventory.json`、`parser_manifest.json`、`parser_results.json`、summary JSON |
| 人工证据 | scan 生成的 `review/*.tsv` 和 Scan HTML 聚合表 |
| 禁止做法 | 把 raw JSON、parser 原始结果、cache/progress 日志直接放到主审查页面 |
| 验证 | scan pipeline 测试、Scan HTML 测试、Version Detail 测试 |

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

## 证据分层

| 层级 | 面向对象 | 内容 | 展示方式 |
| --- | --- | --- | --- |
| L1 审查摘要 | IP 使用者 / 库管理员 | scan 结论、view 覆盖、unknown、parser 失败、下一步 | Version Detail / Scan HTML 第一屏 |
| L2 人工证据表 | reviewer | view 文件表、unknown 文件表、大文件表、parser evidence 表 | TSV/HTML，可筛选、可复制 |
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
| `parser_results.json` | 经常为空，人工无意义 | 机器/debug 证据；人工看 `review/parser_evidence.tsv` |
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
    view_coverage.tsv
    files_by_view.tsv
    unknown_files.tsv
    large_metadata_files.tsv
    parser_evidence.tsv
    required_view_check.tsv

  file_inventory.json
  parser_manifest.json
  parser_results.json
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
2. View 覆盖矩阵：按 view 聚合数量、证据等级、状态。
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

Version Detail 是唯一主审查投影。Scan 页面只是单版本 scan 证据页。

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
- `render/html_report.py` 优先读取人工证据表。
- Version Detail 通过 `version_evidence_state` 说明事实源状态，但不展示 raw 绝对路径。

待收敛：

1. 统一 `file_type -> view_type -> evidence_level` 映射。
2. 每个 view 数量都必须能展开到文件列表。
3. unknown 文件必须给出建议动作。
4. 空 `parser_results.json` 的写出策略继续收紧。
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
