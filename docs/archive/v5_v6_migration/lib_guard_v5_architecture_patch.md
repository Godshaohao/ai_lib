Status: archived
Archive reason: moved out of current lib_guard documentation.

# lib_guard v5 架构补丁：Console、Parser v2 与 Scan 全流程修正

## 0. 文档目标

本文档补充 lib_guard v5 的设计依据和落地边界，重点解释为什么 v5 需要新增：

- `parser_results/` 正式产物
- `ParserResult` 统一格式
- `PASS_EMPTY` 与 parser quality
- `combined_extension` 和压缩文件统一识别
- `summary rebuild` 独立化
- `scan_history/latest`
- `release_input_summary`
- HTML 控制台

这些不是零散功能，而是为了解决 scan 全流程中的结构性问题。

## 1. Scan 全流程十五大不足与 v5 修正策略

| 编号 | 不足 | 影响 | v5 修正策略 | 人工确认 | 脚本自动处理 | 优先级 |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | scan 职责膨胀 | scan 同时承担解析、汇总、展示、发布判断，边界不清 | `scanner` 只 orchestrate；summary/release/render/console 独立 | 确认模块边界 | 模块拆分与 CLI 分层 | P0 |
| 2 | 事实源不清 | 下游不知道以哪个 JSON 为准 | 固定 `file_inventory`、`parser_results`、`summaries`、`summary` 四层事实源 | 确认目录契约 | scan 自动生成 | P0 |
| 3 | parser 质量不可验 | parser PASS 但可能没有抽到对象 | 新增 parser quality，正式引入 `PASS_EMPTY` | 定义空结果阈值 | 自动统计与评分 | P0 |
| 4 | 压缩文件支持不统一 | `.v.gz` 等文件可能被识别成 unknown 或不能 parse | 统一 `io_utils`、`combined_extension`、`compression` | 确认支持后缀 | 自动识别和读取 | P0 |
| 5 | scan mode 不清晰 | hash/parse/signature 行为不可预测 | scan policy 配置化 | 确认 mode 行为 | policy 自动执行 | P0 |
| 6 | cache 不可信 | parser 代码升级后可能复用旧结构 | cache key 加 parser/schema/config version | 版本升级纪律 | 自动失效旧 cache | P0 |
| 7 | parser_manifest 解释不足 | 无法追踪为何 parse、为何跳过、结果在哪 | 增加 reason/result_path/cache_invalid_reason | 确认展示字段 | 自动记录 | P0 |
| 8 | summary 与 scan 耦合 | summary 代码变更需要重跑 scan | `summary rebuild` 独立，只读 parser_results | 确认覆盖策略 | 自动 backup 和重建 | P0 |
| 9 | 缺少正式 parser_results | 无法重建 summary、定位单文件 parser 质量 | `parser_results/` 成为 scan_output 正式产物 | 确认保存范围 | 自动写入 | P0 |
| 10 | latest 不稳定 | 下游找不到当前有效 scan | `scan_history/index.json` 维护 latest | 确认 failed 是否更新 latest | 自动维护 | P1 |
| 11 | 失败策略不清 | warning/error/blocker 对 release 影响不稳定 | 统一 status/severity 映射 | 确认 release 阻断规则 | 自动生成 issue | P1 |
| 12 | file_type/library_type 混淆 | selector/release policy 难以稳定工作 | 标准 FileRecord 字段 | 确认 role/corner 规则 | 自动初判 | P0 |
| 13 | 大文件策略滞后 | 大文件 parse/hash 成本不可控 | classifier/policy 前置 metadata-only 策略 | 确认 hash 大小限制 | 自动跳过或降级 | P1 |
| 14 | 配置不主导 | 行为散落在代码里 | scan/summary/release policy 配置化 | 确认配置项 | 自动读取 | P1 |
| 15 | 下游输入不冻结 | render/release 随 parser 内部结构变动而坏 | release/render/check 输入固定 JSON | 确认接口 | 自动消费稳定 JSON | P1 |

## 2. Parser v2 重构原则

v5 起 parser 应从 scan 内部工具升级为可复用基础能力，支持：

1. scan 批量调用
2. 单文件手动解析
3. 多文件解析
4. 两个文件 diff
5. parser quality 检查
6. summary rebuild
7. update-file / update-type
8. HTML 控制台展示 parser 原始结果

Parser v2 不再兼容 parser v1 的自由 dict 输出。所有 parser 必须返回统一 `ParserResult`。

### 2.1 统一工作流

```text
file path
  -> detect file type / combined extension
  -> open_text_auto 支持普通文本和 .gz
  -> parse_xxx_file(path)
  -> ParserResult
  -> optional diff_xxx_result(old, new)
  -> scan / summary / quality / render / update 共用
```

示例：

```python
parse_lef_file("a.lef")
parse_lef_file("a.lef.gz")
parse_many_lef_files(["a.lef", "b.lef.gz"])
diff_lef_files("old.lef", "new.lef")
```

## 3. ParserResult 统一格式

所有 parser 必须输出：

```json
{
  "schema_version": "1.0",
  "result_type": "parser_result",
  "parser_name": "LefParser",
  "parser_version": "2.0",
  "parser_schema_version": "1.0",
  "file": "lef/a.lef",
  "abs_path": "/proj/.../lef/a.lef",
  "file_type": "lef",
  "compression": null,
  "status": "PASS",
  "stats": {
    "object_count": 1,
    "warning_count": 0,
    "error_count": 0
  },
  "data": {},
  "issues": []
}
```

状态固定为：

```text
PASS
PASS_EMPTY
FAILED
SKIPPED
UNSUPPORTED
```

具体对象必须放在 `data` 内，顶层只放通用控制字段。

## 4. 不再兼容旧格式

### 4.1 好处

1. summary builder 不再猜字段。
2. parser_quality 可以统一判断。
3. release_input_summary 更稳定。
4. HTML 控制台可以统一展示。
5. update-file 可以替换单个 parser_result。
6. diff 可以统一读取 old/new ParserResult。

### 4.2 代价

1. 旧 extractor / summary 脚本必须更新。
2. 旧 parser cache 必须失效。
3. parser_version 必须升级到 `2.0`。
4. summary rebuild 必须基于新 parser_results。
5. parser_manifest 要记录新 `result_path`。

v5 起不再兼容 parser v1 result。历史 v1 scan_output 只能作为历史报告查看，不建议继续 summary rebuild。

## 5. 压缩文件支持策略

后端库中压缩文件是常态，Parser v2 必须统一支持：

```text
.lib.gz
.lef.gz
.tlef.gz
.v.gz
.sv.gz
.vg.gz
.vp.gz
.cdl.gz
.sp.gz
.spi.gz
.sdc.gz
.upf.gz
.cpf.gz
.sdf.gz
.spef.gz
```

统一工具建议放在：

```text
src/lib_guard/scan/parsers/io_utils.py
```

提供：

```text
detect_combined_extension(path)
detect_compression(path)
open_text_auto(path)
iter_lines_auto(path)
read_text_auto(path)
```

所有 parser 都通过这些工具读取文件，保证 `a.v` 和 `a.v.gz` 在 parser 行为上一致。

## 6. Classifier 同步要求

FileRecord 必须标准化压缩文件字段：

```json
{
  "path": "netlist/top.v.gz",
  "extension": ".gz",
  "combined_extension": ".v.gz",
  "compression": "gzip",
  "file_type": "verilog",
  "role": "gate_netlist"
}
```

如果 classifier 只识别 `.gz`，selector 就无法选择正确 parser。因此 compressed extension 识别必须发生在 parser selector 之前。

## 7. Parser 与 Summary 新边界

对外术语统一为：

```text
parser 阶段：单文件解析，输出 ParserResult
summary 阶段：业务聚合，输入 parser_results，输出 scan_output/summaries/*.json
```

建议后续代码结构：

```text
src/lib_guard/summary/
  builders/
    lef_summary.py
    liberty_summary.py
    verilog_summary.py
    macro_summary.py
    port_summary.py
    doc_summary.py
```

输出目录仍为：

```text
scan_output/summaries/
  lef_summary.json
  verilog_summary.json
  macro_summary.json
```

也就是：

```text
summary/builders/ = 代码
scan_output/summaries/ = 结果
```

## 8. 单文件、多文件 parser 与 diff 能力

### 8.1 单文件解析

```text
parse_any_file(path)
parse_lef_file(path)
parse_verilog_file(path)
parse_liberty_file(path)
```

用途：

```text
debug 单个文件
验证 parser 质量
update-file
HTML 控制台单文件预览
```

### 8.2 多文件解析

```text
parse_many_files(paths)
parse_many_lef_files(paths)
```

用途：

```text
scan 批量 parser
update-type
局部重建 parser_results
```

### 8.3 单文件 diff

```text
diff_lef_files(old, new)
diff_verilog_files(old, new)
diff_liberty_files(old, new)
diff_sdc_files(old, new)
```

parser diff 是轻量单文件调试能力，不替代正式版本比较。正式版本比较应走：

```text
old scan_output
new scan_output
  -> diff engine
```

## 9. 人工可控项 vs 脚本自动项

### 9.1 需要人工确认

1. parser v2 不兼容旧格式是否接受。
2. required view 定义。
3. PASS_EMPTY 在 release 下是否阻断。
4. 哪些压缩后缀必须支持。
5. 哪些大文件只 metadata-only。
6. summary rebuild 是否排除 doc。
7. parser quality 分数阈值。
8. release warning 是否允许放行。
9. role/corner 的路径识别规则。
10. 单文件 diff 结果是正式证据还是仅 debug。

### 9.2 脚本自动处理

1. 文件类型识别。
2. gzip 读取。
3. parser result 生成。
4. parser manifest 记录。
5. summary rebuild。
6. parser quality 评分。
7. history latest 更新。
8. HTML 控制台展示。
9. release check dry-run。

## 10. v5 最终确认策略

建议定版为：

```text
A. v5 文档补充十五大不足。
B. parser 重构进入 Parser v2。
C. Parser v2 不兼容旧格式。
D. 所有 parser 支持普通文件和 .gz 文件一致效果。
E. parser_results/ 成为正式 scan_output。
F. summary 阶段替代 extractor 术语。
G. summary rebuild 只读 parser_results。
H. 单文件 parser 和单文件 diff 成为正式工具能力。
I. release 只读 release_input_summary。
J. HTML 控制台展示所有人工可控项和自动判断项。
```

## 11. 当前代码落地状态

截至本补丁文档创建时：

- 已有 v5 控制台 P0：`console build/config/review`
- 已有基础 `control_data/config_view/review_items/recommended_actions`
- 已有 scan 主链路骨架和 `parser_results.json`
- 已有 `summary rebuild --type`
- 已完成 Parser v2 统一格式切换：`parse_*_file()` 与 scan parser 均返回 `ParserResult`
- 已迁移 summary 代码源头到 `summary/builders`
- 已移除 `scan.extractors`、`lib_guard.extractors` 与 `scan.parsers.*_parser` 兼容入口
- 已实现 `parser_results/` 目录化 result_path，`parser_manifest.json` 记录 result/cache/status 字段
- 已实现 `summary/parser_quality.json`，`PASS_EMPTY` 会进入 `scan_issues.json` 并影响 scan status
- 已实现 `summary/release_readiness.json`，支持 bundle/component、required view、validation level、release channel 与 manual review items
- 已实现 Progress v2 基础结构：`parser_task_list.json`、worker-aware `scan_progress_latest.json`、parse task JSONL events
- 已引入 `ParserExecutor` 并行层，`--parse-jobs N` 使用 thread worker pool，主线程统一 commit parser results/cache/manifest
- 已在 `parsers/base.py` 落地 gzip 读取、combined extension 与 compression 检测基础能力

下一阶段应补齐 `parser_results/` 目录化 result_path，并把 parser quality 与 release/check 规则接到控制台展示。
