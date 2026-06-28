Status: archived
Archive reason: moved out of current lib_guard documentation.

# Project Memory Refresh Flow

## 目标

手动触发项目记忆刷新，避免 Agent 在日常开发中自动过度工程化。

该 Flow 用于阶段性整理，而不是每次开发都运行。

## 触发方式

用户明确说：

```text
使用 Project Memory Refresh Flow，回顾最近变更，判断哪些内容需要写入 docs。
```

## 触发时机

```text
同类修改重复出现 3 次以上
临时规则变成稳定规则
从 MVP 切到工程化
准备交给其他 AI 或同事
准备阶段性汇报
UI / 数据 / 架构边界发生稳定变化
```

## 工作流程

```text
1. 回顾最近对话和变更
2. 分类：
   - 稳定结论
   - 临时探索
   - 已废弃方案
   - 待确认问题
3. 判断项目阶段：
   - MVP
   - 工程化
4. 判断需要更新哪些文档
5. 先输出更新建议，不直接大改
6. 用户确认后，再执行文档更新
```

## 文档映射

### 更新 AGENT.md

当变化涉及：

```text
Agent 工作模式
允许 / 禁止修改范围
source of truth 规则
文档更新策略
```

### 更新 docs/01_product_scope.md

当变化涉及：

```text
用户
决策动作
MVP 边界
产品目标
```

### 更新 docs/02_data_rule_contract.md

当变化涉及：

```text
字段
指标
状态
异常
数据口径
质量门禁
```

### 更新 docs/03_engineering_delivery.md

当变化涉及：

```text
目录结构
CLI
模块边界
运行方式
debug 方法
中间产物
```

### 更新 docs/04_ui_iteration.md

当变化涉及：

```text
UI 源文件
UI 上下文
view model
页面结构
生成 HTML 与源文件关系
UI 修改边界
```

## 输出格式

```text
建议更新：
1.
2.
3.

不建议更新：
1.
2.

待确认问题：
1.
2.

需要用户确认：
是否执行这些文档更新？
```
