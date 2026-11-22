# DeliveryRecord · v3 字段字典与完整示例

> 设计契约和合成数据；表格来自 v3 逐字段确认表，不代表已完成业务确认。`是` / `LEF` / `Liberty` 原样保留，条件必需性需结合对应 Schema 验证。

| 字段路径 | 必需性 / 适用视图 | 类型 | 含义和检查要点 |
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
| `files[].file_id` | 是 | string | 本交付中的文件行 ID |
| `files[].file_key` | 是 | string/null | 跨多次交付关联同一个逻辑文件位；未知为 null |
| `files[].classification` | 是 | enum | RESOLVED/UNRESOLVED；不确定不自动采用 |
| `files[].relative_path` | 是 | string | 相对 `source_root` 的真实文件路径，保留实际名字 |
| `files[].view` | 是 | enum | LEF/LIBERTY/VERILOG/CDL/SDC/UPF/CPF/SPEF/DB/GDS/OTHER |
| `files[].corner` | 是 | string/null | corner 可解析时写值；不适用的视图为 null |
| `files[].mode` | 是 | string/null | func/scan 等，未知或不适用为 null |

## 完整合成示例

来源：`ai_lib_qor_contract_v3/examples/work/vendors/vendor_orion/libraries/lib_rtavfs/deliveries/dlv_20261019_001/delivery.json`

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
