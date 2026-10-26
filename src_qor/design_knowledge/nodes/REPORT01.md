+++
id = "REPORT01"
title = "检查报告与证据视图"
type = "view"
status = "unknown"
origin = "../lib_guard/export_review_excel.py"
summary = "以单 IP Workbook、全局 HTML 总览和原始 Evidence 支撑筛选、阅读与溯源；每种视图承担不同任务。"

[[links]]
to = "FACT01"
relation = "displays"

[[links]]
to = "OPERATOR01"
relation = "supports"

[[links]]
to = "READER01"
relation = "supports"

[[links]]
to = "VALIDATE01"
relation = "validates"
+++

## 当前产物
- 每 IP Workbook：按 IP 隔离，包含总览、关注项和类型明细；字段结构在 `export_review_excel.py` 中定义。
- HTML 总览：提供跨 IP 导航与 Workbook 入口，不应复制成第二套事实库。
- Evidence JSON：保留机器检查明细和输入身份；Workbook/HTML 是可重建投影。

## 待核实
- 阅读者是否应以 Workbook 为主、HTML 为导航，需按实际交付流程确认。
- 动态长文本、证据链接和历史 Workbook 的定位需用目标办公环境复验。
