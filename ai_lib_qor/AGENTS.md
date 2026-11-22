# ai_lib_qor · 项目补充指令（与仓库根 AGENTS.md 并用）

此文件适用于 `ai_lib_qor/`。当前环境未核实到仓库根 AGENTS.md；如未来存在，需同时遵循其适用约束。用户当前明确授权的任务优先；不擅自引入新数据库或大规模重构。

## 1. 项目重心

以库来源、有效版本、文件解析和质量检查的可信数据链为中心。多个 Web HTML、Excel、Agent 共享已保存业务数据和查询语义，不因为打开页面就扫描 RAW、改写版本、重新解析整库或重新检查。

## 2. 开发前最小核对

1. 确认本地分支、HEAD 和未提交工作树；远端 GitHub 只能是参考。
2. 阅读相关 `schemas/`、模块、测试及 `docs/architecture-steward.md`；老设计 `.py.md` 是提案，不是代码事实。
3. 若涉及版本、来源或检查，明确生产者、权威存储、消费者和失效路径。
4. 优先调用已有 application/use case 与查询模型，避免新增重复扫描/解析/“latest”推断。

## 3. 核心状态分离

- RAW 扫描观察 ≠ 可信交付；正式链接观察 ≠ 可信快照。
- 交付缺失文件 ≠ 已删除；文件名提示 ≠ 业务身份确权。
- 版本来源变化 ≠ 内容变化；CheckResult PASS ≠ 人工采纳。
- EffectiveVersion `members` 为全集，`changes` 为相对父 Rev 差异；最新计算与采纳指针分离。
- JSON/JSONL 历史、检查结果与可重建查询投影职责独立。**SQLite 只是候选，未获具体实施授权。**

## 4. 变更与验收

局部 UI 调整不修改来源、Parser、Schema；新 HTML 首先查现有 ReadModel/Catalog。中高影响变更使用 `/home/polaris/.codex/skills/ai-lib-steward/SKILL.md` 的流程；只有改变核心边界/契约/数据权威时才更新架构文档和 ADR。

不得覆写真实 RAW/Formal 及不可变历史，不把模拟测试表述为生产验收。Codex 的实际结果写出改动文件、影响范围、验证命令/结果及未验收项。
