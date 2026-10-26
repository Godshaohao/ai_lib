+++
id = "WORKBENCH01"
title = "Web 工作台交互"
type = "component"
status = "proposed"
origin = "../lib_guard/templates/workbench.html"
summary = "独立 Flask 工作台串联 RAW 发现、库选择、版本检查、任务运行与报告查询。"

[[links]]
to = "OPERATOR01"
relation = "enables"

[[links]]
to = "REVIEW_PIPE01"
relation = "supports"

[[links]]
to = "VALIDATE01"
relation = "validates"
+++

## 当前组件
- 目录筛选：Vendor 与库过滤。
- 检查范围：RAW 目标/基准版本、检查项勾选和范围摘要。
- 文件选择：LEF 可搜索的纵向列表；Liberty 可按范围筛选并多选。
- 运行反馈：状态、进度/耗时、日志与任务产物链接。

## 设计问题
工作台服务维护者任务，不应将所有解析细节塞进默认界面。高级输入、调试来源和历史产物应保持可访问但不压过主操作。
