Status: current

# 文档索引

这里是 `lib_guard` 当前文档入口。本文档集按软件工程职责划分：教程负责操作闭环，
CLI 参考负责命令契约，配置参考负责可修改项，数据契约负责事实源边界，架构说明负责
模块职责，测试计划负责验收标准。生成的 HTML、JSON、scan/diff/release 输出不是文档源。

## 阅读顺序

| 读者 | 先读 | 目的 |
| --- | --- | --- |
| 普通库管理员 | [基础教程](basic_tutorial.md) | 从新库/新版本到审查和接受有效版 |
| 命令使用者 | [CLI 参考](cli_reference.md) | 查短命令、副作用和参数 |
| 工程维护者 | [架构说明](architecture.md) -> [数据契约](data_contract.md) | 理清事实源、状态模型和渲染边界 |
| 策略维护者 | [配置参考](config_reference.md) | 修改 policy、workspace 配置和扫描策略 |
| 测试/发布维护者 | [测试计划](test_plan.md) | 确认修改满足回归和手工验收 |

## 当前文档

- [基础教程：从新库入库到 Release](basic_tutorial.md)
- [CLI 参考](cli_reference.md)
- [配置参考](config_reference.md)
- [数据契约](data_contract.md)
- [Scan 证据分层与人工审查口径](scan_evidence_review.md)
- [架构说明](architecture.md)
- [架构与主流程总览图](lib_guard_architecture_flow.svg)
- [测试计划](test_plan.md)
- [兼容层说明](compatibility.md)

## 第一性边界

`lib_guard` 有多类事实输入，但只有一个用户主投影：

```text
catalog.json        库和版本资产地图
scan_out            单版本扫描事实
diff / compare      相对基准的变化事实
effective / window  当前有效版和接入窗口
HTML render         用户看到的投影，不是事实源
```

如果页面内容和证据源不一致，先检查证据源和 Render Impact，再重新渲染；不要手改 HTML
或把 HTML 当作上游输入。

历史迁移说明和 workflow-pack 材料不再作为当前仓库内容维护；当前行为以本索引列出的文档为准。
