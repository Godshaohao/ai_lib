# sources/raw_scanner.py · 设计伪代码

> **拟议，非可执行代码。** 以下接口名、内部结构和错误策略供评审，不声称当前已实现。

- **职责**：只读发现一次交付的文件。
- **接口**：`scan_delivery(raw_root, scope) → RawObservation`
- **输入**：来源根、已确认范围。
- **输出**：路径、类型候选、访问异常及观察时间。
- **配置 / 依赖**：project.yaml 的 raw_root；delivery_rules.yaml。

## 算法与处理顺序

```text
过程 scan_delivery(raw_root, scope) → RawObservation
    在限定范围内只读遍历；保留相对路径；记录无法访问项；不决定最终有效成员
    返回上述输出或明确失败
```

## 异常与边界

不可访问/范围不完整时返回不完整观察；不把缺失当删除。所有正式业务记录仅通过统一 Publisher 或其事件追加入口发布；本文件只有设计内容。

## 对应 v3 JSON 字段与术语

下列字段是本模块**读取、贡献或校验的范围**，并不表示该模块独立写入整份 JSON。字段必需性来自 v3 文档；完整结构及示例见对应字典。

### [DeliveryRecord 字段字典与完整示例](../../../contracts/delivery.md)

| 字段 | 适用 / 必需性 | 类型 | 中文含义与边界 |
|---|---|---|---|
| `source_root` | 是 | path string | 该交付的只读来源路径；不得依赖目前仍存在来证明历史内容可读 |
| `files[].relative_path` | 是 | string | 相对 `source_root` 的真实文件路径，保留实际名字 |
| `files[].view` | 是 | enum | LEF/LIBERTY/VERILOG/CDL/SDC/UPF/CPF/SPEF/DB/GDS/OTHER |
| `files[].corner` | 是 | string/null | corner 可解析时写值；不适用的视图为 null |
| `files[].mode` | 是 | string/null | func/scan 等，未知或不适用为 null |

术语和 source_ref 的完整定义见[中英文术语表](../../../contracts/术语表.md)。
