+++
id = "READER01"
title = "IP 阅读者任务"
type = "audience"
status = "proposed"
summary = "阅读者需要理解 IP 提供什么、哪些检查发现值得关注、结论覆盖到哪里、哪些内容尚未确认。"

[[links]]
to = "REPORT01"
relation = "requires"

[[links]]
to = "FACT01"
relation = "questions"

[[links]]
to = "VALIDATE01"
relation = "validates"
+++

## 期望回答（产品提议）
- 本次报告对象和版本范围是什么？
- 已确认的接口/几何/文件来源变化是什么？
- 哪些输入或检查没有覆盖，哪些结论只适用于单个文件？
- 可通过哪个证据入口追溯到源文件或运行报告？

## 验收限制
目前项目有 Workbook、静态 HTML 和 Web 工作台等表达面。必须通过阅读任务测试确定哪些是主要交付入口，不可把“报告生成”当作“阅读者理解”。
