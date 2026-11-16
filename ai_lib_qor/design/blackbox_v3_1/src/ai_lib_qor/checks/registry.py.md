# checks/registry.py · 设计伪代码

> **拟议，非可执行代码。** 以下接口名、内部结构和错误策略供评审，不声称当前已实现。

- **职责**：加载可信插件注册表。
- **接口**：`resolve_plugin(plugin_id, registry) → PluginHandle`
- **输入**：注册表 ID 与模块入口。
- **输出**：已安装可信本地插件句柄及版本。
- **配置 / 依赖**：checks.yaml plugins。

## 算法与处理顺序

```text
过程 resolve_plugin(plugin_id, registry) → PluginHandle
    只解析明确登记且在可信本地包中的入口；核验 ID、版本及 run 接口
    返回上述输出或明确失败
```

## 异常与边界

缺失、重复或不可信入口报错；不接受任意外部脚本路径。所有正式业务记录仅通过统一 Publisher 或其事件追加入口发布；本文件只有设计内容。

## 对应 v3 JSON 字段与术语

下列字段是本模块**读取、贡献或校验的范围**，并不表示该模块独立写入整份 JSON。字段必需性来自 v3 文档；完整结构及示例见对应字典。

### [CheckResult 字段字典与完整示例](../../../contracts/check.md)

| 字段 | 适用 / 必需性 | 类型 | 中文含义与边界 |
|---|---|---|---|
| `quality_checks[].check_id` | 是 | string | 例如 `LEF_LIBERTY_PIN_MATCH` |

术语和 source_ref 的完整定义见[中英文术语表](../../../contracts/术语表.md)。
