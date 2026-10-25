# 指定正式阶段 IP 文件核查

- IP：`sram22_256x16m8w8`
- 正式阶段：`lib_NL2.5_3`（阶段编号；不表示最新或次新）
- 正式 IP 路径：`/home/polaris/proj/mx/ai_lib/lib_NL2.5_3/IP`
- 原始 IP 路径：`/home/polaris/proj/mx/ai_lib/3rd_IP/SRAM22/sram22_256x16m8w8`
- 盘点状态：完成
- 方式：只读遍历文件和链接；不读取文件内容、不计算 Hash。

## 阶段内容统计

本次只核查指定阶段 `lib_NL2.5_3`，不进行正式阶段之间的比较。
视图数量表示该阶段下可见文件路径数；数量为 0 只表示没有发现该类文件，不自动判定缺交付。

| 文件类型 | 可见路径数 |
| --- | ---: |
| lef | 1 |
| liberty | 3 |
| db | 0 |
| gds | 1 |
| cdl | 0 |
| verilog | 1 |
| oas | 0 |
| spice | 1 |
| ndm | 0 |
| other | 0 |
| **可见路径合计** | **7** |
| **不同来源路径** | **7** |

## 正式链接来自哪些原始版本

| 原始版本目录 | 正式可见路径 | 去重来源路径 |
| --- | ---: | ---: |
| `20261024_de0a9a7` | 7 | 7 |

## 正式路径 → 原始来源

展示正式目录中的相对路径及其链接解析后的原始绝对路径；这里只核对路径来源，不比较文件内容。

| 正式相对路径 | 类型 | 原始版本目录 | 原始绝对路径 |
| --- | --- | --- | --- |
| `GDS/sram22_256x16m8w8.gds.gz` | gds | `20261024_de0a9a7` | `/home/polaris/proj/mx/ai_lib/3rd_IP/SRAM22/sram22_256x16m8w8/20261024_de0a9a7/GDS/sram22_256x16m8w8.gds.gz` |
| `LEF/sram22_256x16m8w8.lef` | lef | `20261024_de0a9a7` | `/home/polaris/proj/mx/ai_lib/3rd_IP/SRAM22/sram22_256x16m8w8/20261024_de0a9a7/LEF/sram22_256x16m8w8.lef` |
| `LIB/sram22_256x16m8w8_ff_n40C_1v95.lib` | liberty | `20261024_de0a9a7` | `/home/polaris/proj/mx/ai_lib/3rd_IP/SRAM22/sram22_256x16m8w8/20261024_de0a9a7/LIB/NLDM/sram22_256x16m8w8_ff_n40C_1v95.lib` |
| `LIB/sram22_256x16m8w8_ss_100C_1v60.lib` | liberty | `20261024_de0a9a7` | `/home/polaris/proj/mx/ai_lib/3rd_IP/SRAM22/sram22_256x16m8w8/20261024_de0a9a7/LIB/NLDM/sram22_256x16m8w8_ss_100C_1v60.lib` |
| `LIB/sram22_256x16m8w8_tt_025C_1v80.lib` | liberty | `20261024_de0a9a7` | `/home/polaris/proj/mx/ai_lib/3rd_IP/SRAM22/sram22_256x16m8w8/20261024_de0a9a7/LIB/NLDM/sram22_256x16m8w8_tt_025C_1v80.lib` |
| `SPICE/sram22_256x16m8w8.spice` | spice | `20261024_de0a9a7` | `/home/polaris/proj/mx/ai_lib/3rd_IP/SRAM22/sram22_256x16m8w8/20261024_de0a9a7/SPICE/sram22_256x16m8w8.spice` |
| `VERILOG/sram22_256x16m8w8.v` | verilog | `20261024_de0a9a7` | `/home/polaris/proj/mx/ai_lib/3rd_IP/SRAM22/sram22_256x16m8w8/20261024_de0a9a7/VERILOG/sram22_256x16m8w8.v` |

## 新 RAW 文件与正式来源配对

正式阶段：`lib_NL2.5_3`；新 RAW：`20261024_de0a9a7`。
新文件 7 个：唯一匹配 7，待人工确认 0，歧义 0，未匹配 0。
另有 0 个正式链接无法归属到配置的 RAW 版本；这些来源不参与自动配对。
只按 View 内相对路径和文件名配对；不读取内容、不计算 Hash、不作放行结论。

| 新 RAW 文件 | 配对状态 | 正式 RAW 来源 | 正式目录路径 | 匹配依据 |
| --- | --- | --- | --- | --- |
| `GDS/sram22_256x16m8w8.gds.gz` | 路径唯一匹配 | `/home/polaris/proj/mx/ai_lib/3rd_IP/SRAM22/sram22_256x16m8w8/20261024_de0a9a7/GDS/sram22_256x16m8w8.gds.gz` | `/home/polaris/proj/mx/ai_lib/lib_NL2.5_3/IP/GDS/sram22_256x16m8w8.gds.gz` | VIEW_RELATIVE_PATH |
| `LEF/sram22_256x16m8w8.lef` | 路径唯一匹配 | `/home/polaris/proj/mx/ai_lib/3rd_IP/SRAM22/sram22_256x16m8w8/20261024_de0a9a7/LEF/sram22_256x16m8w8.lef` | `/home/polaris/proj/mx/ai_lib/lib_NL2.5_3/IP/LEF/sram22_256x16m8w8.lef` | VIEW_RELATIVE_PATH |
| `LIB/NLDM/sram22_256x16m8w8_ff_n40C_1v95.lib` | 路径唯一匹配 | `/home/polaris/proj/mx/ai_lib/3rd_IP/SRAM22/sram22_256x16m8w8/20261024_de0a9a7/LIB/NLDM/sram22_256x16m8w8_ff_n40C_1v95.lib` | `/home/polaris/proj/mx/ai_lib/lib_NL2.5_3/IP/LIB/sram22_256x16m8w8_ff_n40C_1v95.lib` | VIEW_RELATIVE_PATH |
| `LIB/NLDM/sram22_256x16m8w8_ss_100C_1v60.lib` | 路径唯一匹配 | `/home/polaris/proj/mx/ai_lib/3rd_IP/SRAM22/sram22_256x16m8w8/20261024_de0a9a7/LIB/NLDM/sram22_256x16m8w8_ss_100C_1v60.lib` | `/home/polaris/proj/mx/ai_lib/lib_NL2.5_3/IP/LIB/sram22_256x16m8w8_ss_100C_1v60.lib` | VIEW_RELATIVE_PATH |
| `LIB/NLDM/sram22_256x16m8w8_tt_025C_1v80.lib` | 路径唯一匹配 | `/home/polaris/proj/mx/ai_lib/3rd_IP/SRAM22/sram22_256x16m8w8/20261024_de0a9a7/LIB/NLDM/sram22_256x16m8w8_tt_025C_1v80.lib` | `/home/polaris/proj/mx/ai_lib/lib_NL2.5_3/IP/LIB/sram22_256x16m8w8_tt_025C_1v80.lib` | VIEW_RELATIVE_PATH |
| `SPICE/sram22_256x16m8w8.spice` | 路径唯一匹配 | `/home/polaris/proj/mx/ai_lib/3rd_IP/SRAM22/sram22_256x16m8w8/20261024_de0a9a7/SPICE/sram22_256x16m8w8.spice` | `/home/polaris/proj/mx/ai_lib/lib_NL2.5_3/IP/SPICE/sram22_256x16m8w8.spice` | VIEW_RELATIVE_PATH |
| `VERILOG/sram22_256x16m8w8.v` | 路径唯一匹配 | `/home/polaris/proj/mx/ai_lib/3rd_IP/SRAM22/sram22_256x16m8w8/20261024_de0a9a7/VERILOG/sram22_256x16m8w8.v` | `/home/polaris/proj/mx/ai_lib/lib_NL2.5_3/IP/VERILOG/sram22_256x16m8w8.v` | VIEW_RELATIVE_PATH |


## 正式文件与候选文件集合

未配置 Catalog，无法取得已确认的 FULL/FIX 包类型与叠加关系；不生成累积候选文件集合。

## 原始版本目录

按原始版本目录名中的数字字段排序（自然降序）；每个版本均已盘点文件路径与类型。排序是路径命名推断，不证明内容完整或已经生效。
| 原始版本 | 路径 | 本次状态 | 可见路径数 |
| --- | --- | --- | ---: |
| `20261024_de0a9a7` | `/home/polaris/proj/mx/ai_lib/3rd_IP/SRAM22/sram22_256x16m8w8/20261024_de0a9a7` | 已盘点 | 7 |
| `20260506_75cbe961` | `/home/polaris/proj/mx/ai_lib/3rd_IP/SRAM22/sram22_256x16m8w8/20260506_75cbe961` | 已盘点 | 8 |
| `20250620_7ab0e2d9` | `/home/polaris/proj/mx/ai_lib/3rd_IP/SRAM22/sram22_256x16m8w8/20250620_7ab0e2d9` | 已盘点 | 8 |
| `20250201_cb8361d9` | `/home/polaris/proj/mx/ai_lib/3rd_IP/SRAM22/sram22_256x16m8w8/20250201_cb8361d9` | 已盘点 | 8 |
| `20241117_cb95ccae` | `/home/polaris/proj/mx/ai_lib/3rd_IP/SRAM22/sram22_256x16m8w8/20241117_cb95ccae` | 已盘点 | 8 |

## RAW 原始版本逐级演进

已对 5 个原始版本的相邻目录逐级比较，共 4 组。比较对象是各版本的相对文件路径及视图数量，不读取内容或 Hash；路径相同不代表文件内容相同。
正式阶段引用来源仍单独列在上方；本表用于判断新到 RAW 版本相对前序目录的文件构成变化。

| 较新 RAW 版本 | 前一 RAW 版本 | 共同相对路径 | 仅新版本路径 | 仅前版路径 | 盘点状态 |
| --- | --- | ---: | ---: | ---: | --- |
| `20261024_de0a9a7` | `20260506_75cbe961` | 7 | 0 | 1 | 完整 |
| `20260506_75cbe961` | `20250620_7ab0e2d9` | 8 | 0 | 0 | 完整 |
| `20250620_7ab0e2d9` | `20250201_cb8361d9` | 8 | 0 | 0 | 完整 |
| `20250201_cb8361d9` | `20241117_cb95ccae` | 8 | 0 | 0 | 完整 |

各版本视图数量与逐版本文件清单保存在 JSON 的 `chart_data.raw_view_counts`、`raw_library.inventories`；此处的路径变化不能单独证明文件内容变化或交付质量。

## 原始版本新旧参考

按原始目录名推断的最新候选：`20261024_de0a9a7`；次新候选：`20260506_75cbe961`。
这用于快速查看当前正式链接采用的原始版本新旧；不是有效库确认，也不把正式阶段号当作原始版本号。

- `20261024_de0a9a7`：原始清单 7 条路径；本正式阶段引用 7 条。
- `20260506_75cbe961`：原始清单 8 条路径；本正式阶段引用 0 条。

最新与次新原始目录的路径清单对照：相同相对路径 7 条，仅最新目录有 0 条，仅次新目录有 1 条。
同路径只代表路径相同；未读取文件内容，不能据此断言内容未变。

| 文件类型 | 最新目录 | 次新目录 | 数量差 |
| --- | ---: | ---: | ---: |
| gds | 1 | 1 | +0 |
| lef | 1 | 1 | +0 |
| liberty | 3 | 3 | +0 |
| other | 0 | 1 | -1 |
| spice | 1 | 1 | +0 |
| verilog | 1 | 1 | +0 |

仅次新目录有的路径（最多显示 20 条，完整清单见 JSON）：
- `UPSTREAM_COMMIT`

## 被引用原始版本中，哪些文件未链接到本阶段

以下只对正式链接实际引用的原始版本统计；未链接不代表缺失或错误。

| 原始版本 | 文件类型 | 原始不同来源 | 正式引用来源 | 未引用来源 |
| --- | --- | ---: | ---: | ---: |
| `20261024_de0a9a7` | gds | 1 | 1 | 0 |
| `20261024_de0a9a7` | lef | 1 | 1 | 0 |
| `20261024_de0a9a7` | liberty | 3 | 3 | 0 |
| `20261024_de0a9a7` | spice | 1 | 1 | 0 |
| `20261024_de0a9a7` | verilog | 1 | 1 | 0 |

## LIB / DB 文件名角标

角标仅从链接文件名识别，不读取 LIB/DB 内容。

| 文件名角标 | LIB 文件数 | DB 文件数 |
| --- | ---: | ---: |
| FF | 1 | 0 |
| SS | 1 | 0 |
| TT | 1 | 0 |

RC 文件名标签：
- `未标注`：LIB 3 个，DB 0 个

LIB/DB 同名对照异常（只作名称核对提示，不判定缺交付）：

- `sram22_256x16m8w8_ff_n40c_1v95`：LIB 1 个，DB 0 个，只有 LIB
- `sram22_256x16m8w8_ss_100c_1v60`：LIB 1 个，DB 0 个，只有 LIB
- `sram22_256x16m8w8_tt_025c_1v80`：LIB 1 个，DB 0 个，只有 LIB

## 结论边界

本报告核查的是指定 `lib_NL<阶段号>/IP` 目录中的文件路径、链接来源、类型数量和文件名角标。
不比较不同正式阶段，不读取内容或 Hash，不判断 Macro 粒度完整性、文件语义正确性、必需交付项或正式放行。
正式与原始目录均可用于核对文件构成；某类文件为 0 或原始文件未被链接，需结合该 IP 的交付要求由使用者判断。
