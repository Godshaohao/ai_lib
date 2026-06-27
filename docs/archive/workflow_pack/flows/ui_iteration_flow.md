Status: archived
Archive reason: moved out of current lib_guard documentation.

# UI Iteration Flow

## 目标

让 AI 或其他人只迭代 UI 渲染，不污染数据解析、校验和汇总逻辑。

## 核心原则

```text
reports/index.html 是预览产物，不是源头。
源头是 render_dashboard.py / j2 / css / js。
UI 任务禁止改 parser / validator / summary。
UI 输入使用 reports/ui_context.md 和必要样例数据。
```

## MVP 阶段输入

```text
1. scripts/render_dashboard.py
2. reports/ui_context.md
3. 用户反馈
4. 当前截图或 reports/index.html 作为参考
```

## 工程化阶段输入

```text
1. reports/ui_context.md
2. data/view_model.sample.json 或 data/view_model.json
3. templates/index.html.j2
4. assets/dashboard.css
5. assets/dashboard.js
6. 用户反馈
```

## UI 允许修改

```text
布局
卡片
图表位置
表格展示
折叠 / 展开
颜色和样式
文案
轻量 JS 交互
```

## UI 禁止修改

```text
parser
validator
summary
metric calculation
status definition
raw data schema
data contract
```

## reports/ui_context.md 应包含

```text
UI 目标
页面用户和决策意图
CSV 文件清单
每个 CSV 的用途
字段说明
样例行
当前 UI 问题
允许修改文件
禁止修改逻辑
期望输出
```

## UI 迭代完成标准

```text
1. 重新生成 reports/index.html
2. 页面区域仍能正确渲染
3. 数据字段未被重新解释
4. 数据计算逻辑未改变
5. debug / evidence 信息仍可访问
```
