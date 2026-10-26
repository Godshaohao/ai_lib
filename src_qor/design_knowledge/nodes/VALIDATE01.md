+++
id = "VALIDATE01"
title = "设计与输出验收"
type = "validation"
status = "proposed"
origin = "../test/test_workbench.py"
summary = "同时验证程序行为、证据范围和用户能否正确理解输出；单元测试通过不替代真实用户验收。"

[[links]]
to = "REVIEW_PIPE01"
relation = "validates"

[[links]]
to = "WORKBENCH01"
relation = "validates"

[[links]]
to = "REPORT01"
relation = "validates"

[[links]]
to = "OPERATOR01"
relation = "validates"

[[links]]
to = "READER01"
relation = "validates"
+++

## 可自动验证
- `src_qor/test/` 覆盖目录发现、结果统计、证据完整性、Workbook 和 Web 工作台行为。
- Web 实际操作应检查选库、切换 RAW、选择文件、提交任务、查看结果及报告下载的完整链路。
- 对失败、部分覆盖、多 Corner、多文件和路径不可访问提供反例。

## 需要人参与
- 操作者是否知道选择了哪些输入和检查范围。
- 阅读者能否区分已确认变化、待核实和未运行检查。
- 真实项目对 View/Corner/接口约束是否与当前检查规则一致。
