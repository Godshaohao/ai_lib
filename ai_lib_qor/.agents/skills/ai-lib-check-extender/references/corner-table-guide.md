# Corner 验收表维护指南（极简业务 IP 版）

文件位置：`<work>/corner_acceptance.json`（示例见 `examples/corner_acceptance.example.json`，Schema 见 `schemas/corner_acceptance.schema.json`）。

## 1. 标准写法（内置 `_note` 备注，仅 2 个符号）

```json
{
  "_note": [
    "Corner 验收表（仅需 2 个符号，路径匹配忽略大小写）：",
    "1. groups：每组列出必选 Corner。普通词如 'ss_125c'；'+' 表示同时包含（如 'ss+125c'）；'|' 表示任一匹配（如 'tt|typ+25c'）。",
    "2. ip_groups：直接写 '业务IP（或单轨库名，支持 * 通配符）: 分组名（或分组数组）'。精确名优先于通配符；未配置的 IP 报无结论，不静默通过。"
  ],
  "groups": {
    "SRAM_G1":    ["tt|typ+25c", "ss|slow+125c", "ff|fast+-40c"],
    "STDCELL_G1": ["tt|typ+25c", "ss|slow+125c", "ff|fast+m40c"],
    "PHY_G1":     ["ssg+125c", "tt+25c", "ffg+m40c"]
  },
  "ip_groups": {
    "sram22_256x16m8w8":  "SRAM_G1",
    "sram22_512x32m4w8":  "SRAM_G1",
    "sram22_1024x32m8w8": "SRAM_G1",
    "sg13g2_stdcell":     "STDCELL_G1"
  }
}
```

## 2. 匹配规则

1. **`groups`**：列出该分组下每条**必选 Corner**，忽略大小写匹配 `.lib` 相对路径：
   - 普通关键词：`"ssg_0p675v_125c"`（包含即命中）
   - **`+`**（且）：`"ss+125c"`（同时包含 `ss` 与 `125c`）
   - **`|`**（或）：`"tt|typ+25c"`（`tt` 或 `typ`，且包含 `25c`）
   - 不需要某个 Corner 直接从数组删掉即可。
2. **`ip_groups`**（只面向业务 IP，不按 `@ip_type` 间接匹配）：
   - 多轨库匹配 `business_ip`，单轨库匹配 `library` 名。
   - 精确名优先于通配符（如 `sram22_256x16*`）；一个 IP 可归属单个组 `"SRAM_G1"` 或多个组 `["SRAM_G1", "EXTRA_G2"]`。
   - 未命中任何规则的业务 IP 返回 `INCONCLUSIVE`（绝不静默 PASS）。
