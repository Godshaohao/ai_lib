# sources/delivery_builder.py · 设计伪代码

> **拟议，非可执行代码。** 以下接口名、内部结构和错误策略供评审，不声称当前已实现。

- **职责**：组装交付记录。
- **接口**：`build_delivery(identity, observations, classification, policy) → DeliveryRecord`
- **输入**：固定 ID、范围、顺序、观察及分类。
- **输出**：符合 v3 delivery_record.v1 的候选对象。
- **配置 / 依赖**：delivery_rules.yaml。

## 算法与处理顺序

```text
过程 build_delivery(identity, observations, classification, policy) → DeliveryRecord
    填入文件行、包模式和明确删除；检查 file_id 唯一及 scope 与覆盖声明；交由 Publisher
    返回上述输出或明确失败
```

## 异常与边界

同 ID 内容冲突或不确定顺序停止；增量包遗漏不构成删除。所有正式业务记录仅通过统一 Publisher 或其事件追加入口发布；本文件只有设计内容。

## 对应 v3 JSON 字段与术语

下列字段是本模块**读取、贡献或校验的范围**，并不表示该模块独立写入整份 JSON。字段必需性来自 v3 文档；完整结构及示例见对应字典。

### [DeliveryRecord 字段字典与完整示例](../../../contracts/delivery.md)

| 字段 | 适用 / 必需性 | 类型 | 中文含义与边界 |
|---|---|---|---|
| `schema_version` | 是 | string | `delivery_record.v1`；解析契约版本 |
| `delivery_id` | 是 | string | 单次交付唯一；不得简单等于供应商的 V08 |
| `vendor_id` | 是 | string | 可解析回 Vendor 登记 |
| `source_library_id` | 是 | string | 可解析回 SourceLibrary 登记 |
| `supplier_version` | 是 | string | 原始供应商版本号，原样展示 |
| `delivery_order` | 是 | integer | 此库内的交付顺序；优先使用已确认的 `delivery_order.yaml`，不能仅按字符串版本或文件 mtime 排序 |
| `received_at` | 是 | ISO 时间 | 交付被接收时间，不等于文件修改时间 |
| `source_root` | 是 | path string | 该交付的只读来源路径；不得依赖目前仍存在来证明历史内容可读 |
| `package_mode` | 是 | enum | FULL/INCREMENTAL/PATCH/UNKNOWN |
| `package_scope.file_keys[]` | 是 | array | 已声明的交付覆盖范围（本例用明确的逻辑文件位）；复杂真实包可由现有配置进一步限定 View/Corner/Mode |
| `package_scope.scope_confirmed` | 是 | boolean | 是否人工/来源确认覆盖范围；未知时不能推断隐式删除 |
| `explicit_removed_file_keys[]` | 是 | array | 供应商明确声明移除的文件位，默认为空；不要由“包里缺失”自动推断 |
| `files[]` | 是 | array | 本次**实际出现**的文件记录 |

术语和 source_ref 的完整定义见[中英文术语表](../../../contracts/术语表.md)。

## 本脚本交付的完整 v3 候选示例

下列内容逐字来自 v3 合成示例；它是经组装后的业务记录格式，实际发布须通过 Schema 与跨记录验证。

```json
{
  "schema_version": "delivery_record.v1",
  "delivery_id": "dlv_20261019_001",
  "vendor_id": "vendor_orion",
  "source_library_id": "lib_rtavfs",
  "supplier_version": "V08",
  "delivery_order": 8,
  "received_at": "2026-10-19T15:00:00+08:00",
  "source_root": "/example/raw/vendor_orion/lib_rtavfs/V08",
  "package_mode": "INCREMENTAL",
  "package_scope": {
    "file_keys": [
      "lib_rtavfs:lef:core",
      "lib_rtavfs:liberty:func_tt"
    ],
    "scope_confirmed": true
  },
  "explicit_removed_file_keys": [],
  "files": [
    {
      "file_id": "f001",
      "file_key": "lib_rtavfs:lef:core",
      "classification": "RESOLVED",
      "relative_path": "lef/core.lef",
      "view": "LEF",
      "corner": null,
      "mode": null
    },
    {
      "file_id": "f002",
      "file_key": "lib_rtavfs:liberty:func_tt",
      "classification": "RESOLVED",
      "relative_path": "lib/func_tt.lib",
      "view": "LIBERTY",
      "corner": "tt",
      "mode": "func"
    }
  ]
}
```
