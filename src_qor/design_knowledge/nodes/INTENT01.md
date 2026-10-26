+++
id = "INTENT01"
title = "项目目标与范围"
type = "intent"
status = "proposed"
summary = "以可追溯证据帮助维护者检查 IP 交付；不把工具执行状态等同于质量通过或正式放行。"

[[links]]
to = "BOUNDARY01"
relation = "questions"

[[links]]
to = "OPERATOR01"
relation = "drives"

[[links]]
to = "READER01"
relation = "drives"
+++

## 用户目标（提议）
- 操作者能选择库、RAW 版本和检查项，理解输入范围，查看任务进度和可追溯结果。
- IP 阅读者能从报告理解交付内容、已确认变化、证据不足和适用范围。

## 非目标
- 本项目不替代 EDA 工具的完整语义验证，也不自动作正式发布批准。
- 不为图谱完整而把所有原始文件或每个解析记录复制到设计知识库。

## 证据
- `src_qor/README.md` 描述检查范围、证据和质量判断边界。
- 以上用户目标仍是产品要求提议，需由项目负责人和真实使用者复核。
