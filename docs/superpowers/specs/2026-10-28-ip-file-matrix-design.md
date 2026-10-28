# IP 多版本文件矩阵设计

## 目标与边界

目标用户是 IP 使用者，当前审查场景是打开一个已登记 IP 后，回答四个问题：某个关键 LEF/Liberty 的最新和次新来源在哪里；正式 NL 实际观察到使用哪份来源；指定两次交付后文件内容是相同、不同、新提供、未提供还是未比较；已经定位的文件能否直接进入既有质量检查。

本次修改限定在现有 `src_qor` 独立工作台、Projection、Runner、Excel 导出和检查器。RAW 与正式 NL 输入只读，所有快照和结果写入既有 `out-dir`。不增加数据库、后台扫描、发布审批、Effective 自动替换、第二套业务系统、模糊相似度配对或 Hash 驱动的用户结论。

## 数据契约

`file_version_projection.v1` 继续作为当前默认输出并保持可读；读取器同时接受向后兼容的 `file_version_projection.v2`。文件行保留 `file_key`、`view`、大小写敏感的规范化相对路径、`occurrences`、`formal_usage`、`comparison`、`quality_checks` 和证据引用，并增加：

- `version_order`: `status`、`basis`、`ordered_ids`、`warnings`。
- `coverage`: RAW 盘点、Formal 快照和内容比较的覆盖状态。
- `latest` / `previous`: 由 occurrences、可信顺序和 coverage 派生；可能为 `CONFIRMED`、`LATEST_OBSERVED`、`UNKNOWN_ORDER` 或 `NONE`。
- `comparison.delivery_relation`: `READY_TO_COMPARE`、`NEWLY_PROVIDED`、`NOT_PROVIDED_IN_TARGET`、`NOT_PROVIDED_BOTH`、`UNKNOWN_COVERAGE`、`AMBIGUOUS` 或 `CANDIDATE_MATCH`。
- `comparison.content_status`: `BYTE_SAME`、`BYTE_DIFFERENT`、`NOT_COMPARED`、`FAILED` 或 `UNVERIFIED`；压缩文本额外记录 `comparison_mode`。

顺序证据严格按显式 `delivery_order`、完整且不重复的日期线索、UNKNOWN 的顺序降级。不得使用 mtime、目录字符串、Registry 顺序或扫描时间。文件身份为 `IP + View + 规范化相对路径`，不 casefold；重复出现、Corner 无法区分、改名/拆分/合并均保持歧义或候选。

## 数据流

GET 只读取快照，不扫描、不计算全部文件内容。显式刷新扫描登记版本并发布不可变 Projection 快照；Formal 快照缺失只影响 Formal 列，不阻断 RAW-only。显式比较只读取所选唯一配对，按块比较普通文件，`.gz` 默认比较解压后的有效内容，并在读取前后检查 stat；变化的 LEF 才调用现有 `lef_review.analyze()`。所有比较和检查记录携带 snapshot、scope、时间和 evidence refs，不覆盖原始盘点事实。

## Web 与 Excel

现有“文件状态”页改为主入口：顶部显示顺序依据和覆盖警告，主表固定展示最新、次新、Formal、所选范围、内容/语义状态和检查状态；历史出现记录与完整路径折叠在详情中。Base/Target 是可选的比较动作，RAW-only 可用；未知状态必须显示原因。历史 Review 通过 review_id 打开，且不能启动新检查。

Excel 的 `文件版本矩阵` 只渲染 Projection；Web 和 Excel 不各自计算排名。`08-LEF宏` 按 `file_key/pair_id` 读取每对批量证据，失败 pair 不丢弃其他成功 pair。COMPLETE 是执行状态，质量状态仍独立为 PASS/ISSUE/UNVERIFIED/NOT_RUN。

## 验收与风险

新增真实目录 fixture 覆盖五版本、PARTIAL、同内容重复、无 Formal、Formal 指向旧版本、Corner/大小写/同名路径、改名候选、gzip、批量 LEF 一失败和历史 Review。验收必须运行 `src_qor` 单测、编译、JS 语法检查和 Workbench CLI help，并输出实际统计。无完整 EDA 环境时只声明合成 fixture 验证，不声称全面质量或发布批准。
