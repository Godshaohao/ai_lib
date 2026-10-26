+++
id = "IP_OBJECT01"
title = "IP 与版本检查对象"
type = "object"
status = "proposed"
summary = "工作台以单个 IP 为报告隔离边界；其下登记 RAW 版本、正式目录上下文、检查运行和报告。"

[[links]]
to = "RAW01"
relation = "derives_from"

[[links]]
to = "FORMAL01"
relation = "derives_from"

[[links]]
to = "REVIEW_PIPE01"
relation = "organizes"

[[links]]
to = "REPORT01"
relation = "organizes"
+++

## 代码可见事实
- Registry 中的 IP 记录包含库标识、RAW 根和版本列表，以及可选正式 NL 根。
- `review_runner.py` 将运行按 library ID 隔离保存，并记录各检查输入身份。
- 混合显式来源会标记为 `MIXED_EXPLICIT`，不应悄然合并成单一 RAW 版本事实。

## 设计提议
报告和链接应持续显示 IP、版本/阶段、基准范围与来源身份，避免跨 IP 或跨输入串用结果。
