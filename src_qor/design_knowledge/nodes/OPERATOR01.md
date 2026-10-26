+++
id = "OPERATOR01"
title = "操作者任务"
type = "task"
status = "proposed"
summary = "操作者发现或选择 IP，载入 RAW/正式目录范围，选择检查，观察任务状态，并定位结果与证据。"

[[links]]
to = "IP_OBJECT01"
relation = "requires"

[[links]]
to = "WORKBENCH01"
relation = "supports"

[[links]]
to = "REPORT01"
relation = "produces"

[[links]]
to = "VALIDATE01"
relation = "validates"
+++

## 当前工作台支持
- 左侧按 Vendor/库筛选已登记 IP。
- RAW 版本载入后提供检查输入建议；用户仍选择要运行的检查。
- 后台任务状态、日志入口、单 IP 报告与 Workbook 链接在工作台可见。
- 多 LEF 选择保持显式，不因无法自动唯一配对而抹掉可独立运行的其他检查建议。

## 体验验证仍缺
代码和自动化测试证明交互存在，不证明操作者能快速理解每个选项。需要按真实任务做观察性测试并记录阻塞，而不是仅按组件数量验收。
