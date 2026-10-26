+++
id = "BOUNDARY01"
title = "自动判断与人工责任边界"
type = "decision"
status = "proposed"
summary = "自动检查提供有来源、有范围的工程证据；正式 IP 使用判断和放行责任不能由执行成功或推断线索替代。"

[[links]]
to = "FACT01"
relation = "supports"

[[links]]
to = "REPORT01"
relation = "questions"

[[links]]
to = "VALIDATE01"
relation = "requires"
+++

## 需要保持的区分
- 文件存在、路径命名、内容 Hash、Parser 提取、跨视图匹配和人工接受是不同层次的证据。
- 未检查不等于通过；证据不足不等于已确认异常。
- 建议性技术检查与正式发布/放行机制分开；是否接入门禁需要明确业务决策与回归。

## 状态
本节点整理了项目反复强调的边界，仍标为提议，等待维护者确认是否作为长期原则。
