# sources/file_classifier.py · 设计伪代码

> **拟议，非可执行代码。** 以下接口名、内部结构和错误策略供评审，不声称当前已实现。

- **职责**：识别逻辑文件位。
- **接口**：`classify(observation, rules) → ClassifiedFiles`
- **输入**：候选路径、view/corner/mode 规则。
- **输出**：file_key 和分类结果或未解析状态。
- **配置 / 依赖**：delivery_rules、归属配置。

## 算法与处理顺序

```text
过程 classify(observation, rules) → ClassifiedFiles
    对每个文件应用已确认规则；区分同 basename 的不同角色；保留无法判定项
    返回上述输出或明确失败
```

## 异常与边界

歧义标为 UNRESOLVED；不得自动采用。所有正式业务记录仅通过统一 Publisher 或其事件追加入口发布；本文件只有设计内容。

## 对应 v3 JSON 字段与术语

下列字段是本模块**读取、贡献或校验的范围**，并不表示该模块独立写入整份 JSON。字段必需性来自 v3 文档；完整结构及示例见对应字典。

### [DeliveryRecord 字段字典与完整示例](../../../contracts/delivery.md)

| 字段 | 适用 / 必需性 | 类型 | 中文含义与边界 |
|---|---|---|---|
| `files[].file_key` | 是 | string/null | 跨多次交付关联同一个逻辑文件位；未知为 null |
| `files[].classification` | 是 | enum | RESOLVED/UNRESOLVED；不确定不自动采用 |
| `files[].view` | 是 | enum | LEF/LIBERTY/VERILOG/CDL/SDC/UPF/CPF/SPEF/DB/GDS/OTHER |
| `files[].corner` | 是 | string/null | corner 可解析时写值；不适用的视图为 null |
| `files[].mode` | 是 | string/null | func/scan 等，未知或不适用为 null |

术语和 source_ref 的完整定义见[中英文术语表](../../../contracts/术语表.md)。
