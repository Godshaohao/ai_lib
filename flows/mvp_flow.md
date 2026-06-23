# MVP Flow

## 目标

快速验证真实数据、脚本逻辑或页面方向。

MVP Flow 不是随便写，而是有底线的快速开发。

## 适用场景

- 写一两个脚本
- 临时解析一个数据源
- 快速生成 HTML
- 快速验证 UI 布局
- 快速修复一个算法问题
- 项目还没有稳定到需要完整工程化

## 流程

```text
1. 明确本轮目标
2. 读取最小上下文
3. 写最小可运行脚本
4. 输出中间数据
5. 输出报告或结果
6. 暴露异常
7. 不自动更新长期文档
```

## 必须保留的底线

```text
输入输出清楚
中间数据可检查
异常不能静默丢弃
数据计算不要写死在 HTML 中
generated HTML 不是源头
```

## 推荐最小结构

```text
scripts/
  run_xxx.py
  render_dashboard.py

data/
  parsed/
  summary/

reports/
  index.html
  ui_context.md
```

## MVP 完成标准

```text
1. 可以运行
2. 有可检查输出
3. 有 debug 或异常输出
4. 下一步问题清楚
```

## 不强制

```text
不强制完整 src 分层
不强制完整 docs 更新
不强制完整测试体系
不强制复杂模板结构
```
