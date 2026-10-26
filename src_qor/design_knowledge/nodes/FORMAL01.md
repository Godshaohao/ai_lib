+++
id = "FORMAL01"
title = "正式 NL 只读盘点"
type = "source"
status = "unknown"
origin = "../lib_guard/effective_file_tracker.py"
summary = "读取正式 NL 的链接和目标文件清单，汇总 IP、版本线索与视图文件分布；盘点不修改正式目录。"

[[links]]
to = "IP_OBJECT01"
relation = "organizes"

[[links]]
to = "REPORT01"
relation = "supports"
+++

## 代码可见事实
- 盘点逻辑位于 `src_qor/lib_guard/effective_file_tracker.py`，由工作台正式 NL 区域调用。
- 文件类型和 Corner 统计来自链接路径、文件名及目录线索；这类统计不等同于解析文件内容。
- 正式目录盘点与候选 RAW 检查是不同输入范围，不能混成同一结论。

## 待核实
- 真实正式树中的链接约定是否全部被识别；异常链接和不可读目录需单独看报告状态。
- 链接名称推断出的版本/Corner 需要使用者核对，不应标为内容语义验证。
