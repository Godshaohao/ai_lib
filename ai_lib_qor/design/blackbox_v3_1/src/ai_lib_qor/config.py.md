# config.py · 设计伪代码

> **拟议，非可执行代码。** 以下接口名、内部结构和错误策略供评审，不声称当前已实现。

- **职责**：加载和验证配置。
- **接口**：`load_config(project_path, cli_overrides, env) → RuntimeConfig`
- **输入**：project、ownership、delivery_rules、checks 四类配置与覆盖项。
- **输出**：不可变的运行配置对象。
- **配置 / 依赖**：路径、来源、身份映射、顺序和插件 profile。

## 算法与处理顺序

```text
过程 load_config(project_path, cli_overrides, env) → RuntimeConfig
    合并覆盖；确认路径规范化后 work_root 与来源根不相同、无危险重叠；验证关联关系、注册 ID 和 profile
    返回上述输出或明确失败
```

## 异常与边界

路径不可访问或归属冲突报错；来源按只读使用；未知规则不猜测。所有正式业务记录仅通过统一 Publisher 或其事件追加入口发布；本文件只有设计内容。

## 对应 v3 JSON 字段与术语

下列字段是本模块**读取、贡献或校验的范围**，并不表示该模块独立写入整份 JSON。字段必需性来自 v3 文档；完整结构及示例见对应字典。

### [DeliveryRecord 字段字典与完整示例](../../contracts/delivery.md)

| 字段 | 适用 / 必需性 | 类型 | 中文含义与边界 |
|---|---|---|---|
| `vendor_id` | 是 | string | 可解析回 Vendor 登记 |
| `source_library_id` | 是 | string | 可解析回 SourceLibrary 登记 |
| `delivery_order` | 是 | integer | 此库内的交付顺序；优先使用已确认的 `delivery_order.yaml`，不能仅按字符串版本或文件 mtime 排序 |
| `source_root` | 是 | path string | 该交付的只读来源路径；不得依赖目前仍存在来证明历史内容可读 |

### [EffectiveVersion 字段字典与完整示例](../../contracts/effective.md)

| 字段 | 适用 / 必需性 | 类型 | 中文含义与边界 |
|---|---|---|---|
| `owner.owner_type` | 是 | enum | BUSINESS_IP 或 SOURCE_LIBRARY |
| `owner.owner_id` | 是 | string | 对应 IP ID 或无 IP 的来源库 ID |
| `owner.home_source_library_id` | 是 | string | 唯一权威文件存放位置的来源库 |

术语和 source_ref 的完整定义见[中英文术语表](../../contracts/术语表.md)。
