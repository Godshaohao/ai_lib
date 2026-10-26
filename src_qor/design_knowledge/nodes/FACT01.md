+++
id = "FACT01"
title = "检查事实与质量范围"
type = "fact"
status = "unknown"
summary = "检查输出记录来源、对象、范围、证据覆盖及结果类别；缺少证据时保留未验证，不推成无变化。"

[[links]]
to = "REVIEW_PIPE01"
relation = "derives_from"

[[links]]
to = "REPORT01"
relation = "displays"

[[links]]
to = "BOUNDARY01"
relation = "supports"
+++

## 已落实的原则
- `COMPLETE` 表示所选检查执行结束，不等同于 IP 全面质量通过。
- 质量摘要只对本次选择的检查和输入范围负责；未运行项必须可见。
- finding 的机器结果、证据状态和人工判断不能混为一列或互相覆盖。
- 文件路径/名称线索、成功解析任务和语义验证属于不同证据强度。

## 待核实
- 每个解析器的“覆盖完整”含义应逐个对照其支持语法与真实库样本。
- 跨视图配对不充分时，需要保留待核实对象，而不是推断接口一致。
