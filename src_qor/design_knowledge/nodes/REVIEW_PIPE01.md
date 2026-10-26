+++
id = "REVIEW_PIPE01"
title = "按需检查与结果编排"
type = "pipeline"
status = "unknown"
origin = "../lib_guard/review_runner.py"
summary = "编排正式目录盘点、Macro/View 索引、LEF 双文件核查和 LEF–Liberty 接口核查，并保存运行 Evidence。"

[[links]]
to = "RAW01"
relation = "requires"

[[links]]
to = "FORMAL01"
relation = "requires"

[[links]]
to = "FACT01"
relation = "produces"

[[links]]
to = "REPORT01"
relation = "produces"
+++

## 实现清单
- `formal_nl`：正式 NL 链接清单核查。
- `macro_index`：Macro 与多类 View 的文件关联索引。
- `lef_review`：两份 LEF 的结构化差异。
- `lef_liberty_check`：指定 LEF 与逐个 Liberty 文件的接口核查。

## 编排边界
- 检查项可按需选择；每项执行状态与质量状态分离。
- 检查成功不代表所有输入视图已覆盖，也不代表正式发布门禁通过。
- 检查器语义由各自模块负责；此处记录编排，不替代解析器合同。
