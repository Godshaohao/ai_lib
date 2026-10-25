# 指定正式阶段 IP 文件核查

- IP：`sg13g2_stdcell`
- 正式阶段：`lib_NL2.5_3`（阶段编号；不表示最新或次新）
- 正式 IP 路径：`/home/polaris/proj/mx/ai_lib/lib_NL2.5_3/IP`
- 原始 IP 路径：`/home/polaris/proj/mx/ai_lib/3rd_IP/IHP/sg13g2_stdcell`
- 盘点状态：完成
- 方式：只读遍历文件和链接；不读取文件内容、不计算 Hash。

## 阶段内容统计

本次只核查指定阶段 `lib_NL2.5_3`，不进行正式阶段之间的比较。
视图数量表示该阶段下可见文件路径数；数量为 0 只表示没有发现该类文件，不自动判定缺交付。

| 文件类型 | 可见路径数 |
| --- | ---: |
| lef | 2 |
| liberty | 6 |
| db | 0 |
| gds | 0 |
| cdl | 1 |
| verilog | 2 |
| oas | 0 |
| spice | 0 |
| ndm | 0 |
| other | 0 |
| **可见路径合计** | **11** |
| **不同来源路径** | **11** |

## 正式链接来自哪些原始版本

| 原始版本目录 | 正式可见路径 | 去重来源路径 |
| --- | ---: | ---: |
| `20260311_5cccb161` | 11 | 11 |

## 正式路径 → 原始来源

展示正式目录中的相对路径及其链接解析后的原始绝对路径；这里只核对路径来源，不比较文件内容。

| 正式相对路径 | 类型 | 原始版本目录 | 原始绝对路径 |
| --- | --- | --- | --- |
| `CDL/sg13g2_stdcell.cdl` | cdl | `20260311_5cccb161` | `/home/polaris/proj/mx/ai_lib/3rd_IP/IHP/sg13g2_stdcell/20260311_5cccb161/CDL/sg13g2_stdcell.cdl` |
| `LEF/sg13g2_stdcell.lef` | lef | `20260311_5cccb161` | `/home/polaris/proj/mx/ai_lib/3rd_IP/IHP/sg13g2_stdcell/20260311_5cccb161/LEF/sg13g2_stdcell.lef` |
| `LEF/sg13g2_tech.lef` | lef | `20260311_5cccb161` | `/home/polaris/proj/mx/ai_lib/3rd_IP/IHP/sg13g2_stdcell/20260311_5cccb161/LEF/sg13g2_tech.lef` |
| `LIB/sg13g2_stdcell_fast_1p32V_m40C.lib` | liberty | `20260311_5cccb161` | `/home/polaris/proj/mx/ai_lib/3rd_IP/IHP/sg13g2_stdcell/20260311_5cccb161/LIB/NLDM/sg13g2_stdcell_fast_1p32V_m40C.lib` |
| `LIB/sg13g2_stdcell_fast_1p65V_m40C.lib` | liberty | `20260311_5cccb161` | `/home/polaris/proj/mx/ai_lib/3rd_IP/IHP/sg13g2_stdcell/20260311_5cccb161/LIB/NLDM/sg13g2_stdcell_fast_1p65V_m40C.lib` |
| `LIB/sg13g2_stdcell_slow_1p08V_125C.lib` | liberty | `20260311_5cccb161` | `/home/polaris/proj/mx/ai_lib/3rd_IP/IHP/sg13g2_stdcell/20260311_5cccb161/LIB/NLDM/sg13g2_stdcell_slow_1p08V_125C.lib` |
| `LIB/sg13g2_stdcell_slow_1p35V_125C.lib` | liberty | `20260311_5cccb161` | `/home/polaris/proj/mx/ai_lib/3rd_IP/IHP/sg13g2_stdcell/20260311_5cccb161/LIB/NLDM/sg13g2_stdcell_slow_1p35V_125C.lib` |
| `LIB/sg13g2_stdcell_typ_1p20V_25C.lib` | liberty | `20260311_5cccb161` | `/home/polaris/proj/mx/ai_lib/3rd_IP/IHP/sg13g2_stdcell/20260311_5cccb161/LIB/NLDM/sg13g2_stdcell_typ_1p20V_25C.lib` |
| `LIB/sg13g2_stdcell_typ_1p50V_25C.lib` | liberty | `20260311_5cccb161` | `/home/polaris/proj/mx/ai_lib/3rd_IP/IHP/sg13g2_stdcell/20260311_5cccb161/LIB/NLDM/sg13g2_stdcell_typ_1p50V_25C.lib` |
| `VERILOG/sg13g2_stdcell.v` | verilog | `20260311_5cccb161` | `/home/polaris/proj/mx/ai_lib/3rd_IP/IHP/sg13g2_stdcell/20260311_5cccb161/VERILOG/sg13g2_stdcell.v` |
| `VERILOG/sg13g2_udp.v` | verilog | `20260311_5cccb161` | `/home/polaris/proj/mx/ai_lib/3rd_IP/IHP/sg13g2_stdcell/20260311_5cccb161/VERILOG/sg13g2_udp.v` |

## 新 RAW 文件与正式来源配对

正式阶段：`lib_NL2.5_3`；新 RAW：`20260311_5cccb161`。
新文件 12 个：唯一匹配 11，待人工确认 0，歧义 0，未匹配 1。
另有 0 个正式链接无法归属到配置的 RAW 版本；这些来源不参与自动配对。
只按 View 内相对路径和文件名配对；不读取内容、不计算 Hash、不作放行结论。

| 新 RAW 文件 | 配对状态 | 正式 RAW 来源 | 正式目录路径 | 匹配依据 |
| --- | --- | --- | --- | --- |
| `CDL/sg13g2_stdcell.cdl` | 路径唯一匹配 | `/home/polaris/proj/mx/ai_lib/3rd_IP/IHP/sg13g2_stdcell/20260311_5cccb161/CDL/sg13g2_stdcell.cdl` | `/home/polaris/proj/mx/ai_lib/lib_NL2.5_3/IP/CDL/sg13g2_stdcell.cdl` | VIEW_RELATIVE_PATH |
| `LEF/sg13g2_stdcell.lef` | 路径唯一匹配 | `/home/polaris/proj/mx/ai_lib/3rd_IP/IHP/sg13g2_stdcell/20260311_5cccb161/LEF/sg13g2_stdcell.lef` | `/home/polaris/proj/mx/ai_lib/lib_NL2.5_3/IP/LEF/sg13g2_stdcell.lef` | VIEW_RELATIVE_PATH |
| `LEF/sg13g2_tech.lef` | 路径唯一匹配 | `/home/polaris/proj/mx/ai_lib/3rd_IP/IHP/sg13g2_stdcell/20260311_5cccb161/LEF/sg13g2_tech.lef` | `/home/polaris/proj/mx/ai_lib/lib_NL2.5_3/IP/LEF/sg13g2_tech.lef` | VIEW_RELATIVE_PATH |
| `LIB/NLDM/sg13g2_stdcell_fast_1p32V_m40C.lib` | 路径唯一匹配 | `/home/polaris/proj/mx/ai_lib/3rd_IP/IHP/sg13g2_stdcell/20260311_5cccb161/LIB/NLDM/sg13g2_stdcell_fast_1p32V_m40C.lib` | `/home/polaris/proj/mx/ai_lib/lib_NL2.5_3/IP/LIB/sg13g2_stdcell_fast_1p32V_m40C.lib` | VIEW_RELATIVE_PATH |
| `LIB/NLDM/sg13g2_stdcell_fast_1p65V_m40C.lib` | 路径唯一匹配 | `/home/polaris/proj/mx/ai_lib/3rd_IP/IHP/sg13g2_stdcell/20260311_5cccb161/LIB/NLDM/sg13g2_stdcell_fast_1p65V_m40C.lib` | `/home/polaris/proj/mx/ai_lib/lib_NL2.5_3/IP/LIB/sg13g2_stdcell_fast_1p65V_m40C.lib` | VIEW_RELATIVE_PATH |
| `LIB/NLDM/sg13g2_stdcell_slow_1p08V_125C.lib` | 路径唯一匹配 | `/home/polaris/proj/mx/ai_lib/3rd_IP/IHP/sg13g2_stdcell/20260311_5cccb161/LIB/NLDM/sg13g2_stdcell_slow_1p08V_125C.lib` | `/home/polaris/proj/mx/ai_lib/lib_NL2.5_3/IP/LIB/sg13g2_stdcell_slow_1p08V_125C.lib` | VIEW_RELATIVE_PATH |
| `LIB/NLDM/sg13g2_stdcell_slow_1p35V_125C.lib` | 路径唯一匹配 | `/home/polaris/proj/mx/ai_lib/3rd_IP/IHP/sg13g2_stdcell/20260311_5cccb161/LIB/NLDM/sg13g2_stdcell_slow_1p35V_125C.lib` | `/home/polaris/proj/mx/ai_lib/lib_NL2.5_3/IP/LIB/sg13g2_stdcell_slow_1p35V_125C.lib` | VIEW_RELATIVE_PATH |
| `LIB/NLDM/sg13g2_stdcell_typ_1p20V_25C.lib` | 路径唯一匹配 | `/home/polaris/proj/mx/ai_lib/3rd_IP/IHP/sg13g2_stdcell/20260311_5cccb161/LIB/NLDM/sg13g2_stdcell_typ_1p20V_25C.lib` | `/home/polaris/proj/mx/ai_lib/lib_NL2.5_3/IP/LIB/sg13g2_stdcell_typ_1p20V_25C.lib` | VIEW_RELATIVE_PATH |
| `LIB/NLDM/sg13g2_stdcell_typ_1p50V_25C.lib` | 路径唯一匹配 | `/home/polaris/proj/mx/ai_lib/3rd_IP/IHP/sg13g2_stdcell/20260311_5cccb161/LIB/NLDM/sg13g2_stdcell_typ_1p50V_25C.lib` | `/home/polaris/proj/mx/ai_lib/lib_NL2.5_3/IP/LIB/sg13g2_stdcell_typ_1p50V_25C.lib` | VIEW_RELATIVE_PATH |
| `UPSTREAM_COMMIT` | 未找到对应正式来源 | — | — | NONE |
| `VERILOG/sg13g2_stdcell.v` | 路径唯一匹配 | `/home/polaris/proj/mx/ai_lib/3rd_IP/IHP/sg13g2_stdcell/20260311_5cccb161/VERILOG/sg13g2_stdcell.v` | `/home/polaris/proj/mx/ai_lib/lib_NL2.5_3/IP/VERILOG/sg13g2_stdcell.v` | VIEW_RELATIVE_PATH |
| `VERILOG/sg13g2_udp.v` | 路径唯一匹配 | `/home/polaris/proj/mx/ai_lib/3rd_IP/IHP/sg13g2_stdcell/20260311_5cccb161/VERILOG/sg13g2_udp.v` | `/home/polaris/proj/mx/ai_lib/lib_NL2.5_3/IP/VERILOG/sg13g2_udp.v` | VIEW_RELATIVE_PATH |


## 正式文件与候选文件集合

未配置 Catalog，无法取得已确认的 FULL/FIX 包类型与叠加关系；不生成累积候选文件集合。

## 原始版本目录

按原始版本目录名中的数字字段排序（自然降序）；每个版本均已盘点文件路径与类型。排序是路径命名推断，不证明内容完整或已经生效。
| 原始版本 | 路径 | 本次状态 | 可见路径数 |
| --- | --- | --- | ---: |
| `20260311_5cccb161` | `/home/polaris/proj/mx/ai_lib/3rd_IP/IHP/sg13g2_stdcell/20260311_5cccb161` | 已盘点 | 12 |
| `20250705_ddd1179c` | `/home/polaris/proj/mx/ai_lib/3rd_IP/IHP/sg13g2_stdcell/20250705_ddd1179c` | 已盘点 | 11 |
| `20250306_73cef962` | `/home/polaris/proj/mx/ai_lib/3rd_IP/IHP/sg13g2_stdcell/20250306_73cef962` | 已盘点 | 11 |
| `20240326_b1e235f1` | `/home/polaris/proj/mx/ai_lib/3rd_IP/IHP/sg13g2_stdcell/20240326_b1e235f1` | 已盘点 | 11 |
| `20230628_2db4084d` | `/home/polaris/proj/mx/ai_lib/3rd_IP/IHP/sg13g2_stdcell/20230628_2db4084d` | 已盘点 | 11 |

## RAW 原始版本逐级演进

已对 5 个原始版本的相邻目录逐级比较，共 4 组。比较对象是各版本的相对文件路径及视图数量，不读取内容或 Hash；路径相同不代表文件内容相同。
正式阶段引用来源仍单独列在上方；本表用于判断新到 RAW 版本相对前序目录的文件构成变化。

| 较新 RAW 版本 | 前一 RAW 版本 | 共同相对路径 | 仅新版本路径 | 仅前版路径 | 盘点状态 |
| --- | --- | ---: | ---: | ---: | --- |
| `20260311_5cccb161` | `20250705_ddd1179c` | 11 | 1 | 0 | 完整 |
| `20250705_ddd1179c` | `20250306_73cef962` | 11 | 0 | 0 | 完整 |
| `20250306_73cef962` | `20240326_b1e235f1` | 11 | 0 | 0 | 完整 |
| `20240326_b1e235f1` | `20230628_2db4084d` | 11 | 0 | 0 | 完整 |

各版本视图数量与逐版本文件清单保存在 JSON 的 `chart_data.raw_view_counts`、`raw_library.inventories`；此处的路径变化不能单独证明文件内容变化或交付质量。

## 原始版本新旧参考

按原始目录名推断的最新候选：`20260311_5cccb161`；次新候选：`20250705_ddd1179c`。
这用于快速查看当前正式链接采用的原始版本新旧；不是有效库确认，也不把正式阶段号当作原始版本号。

- `20260311_5cccb161`：原始清单 12 条路径；本正式阶段引用 11 条。
- `20250705_ddd1179c`：原始清单 11 条路径；本正式阶段引用 0 条。

最新与次新原始目录的路径清单对照：相同相对路径 11 条，仅最新目录有 1 条，仅次新目录有 0 条。
同路径只代表路径相同；未读取文件内容，不能据此断言内容未变。

| 文件类型 | 最新目录 | 次新目录 | 数量差 |
| --- | ---: | ---: | ---: |
| cdl | 1 | 1 | +0 |
| lef | 2 | 2 | +0 |
| liberty | 6 | 6 | +0 |
| other | 1 | 1 | +0 |
| verilog | 2 | 1 | +1 |

仅最新目录有的路径（最多显示 20 条，完整清单见 JSON）：
- `VERILOG/sg13g2_udp.v`

## 被引用原始版本中，哪些文件未链接到本阶段

以下只对正式链接实际引用的原始版本统计；未链接不代表缺失或错误。

| 原始版本 | 文件类型 | 原始不同来源 | 正式引用来源 | 未引用来源 |
| --- | --- | ---: | ---: | ---: |
| `20260311_5cccb161` | cdl | 1 | 1 | 0 |
| `20260311_5cccb161` | lef | 2 | 2 | 0 |
| `20260311_5cccb161` | liberty | 6 | 6 | 0 |
| `20260311_5cccb161` | other | 1 | 0 | 1 |
| `20260311_5cccb161` | verilog | 2 | 2 | 0 |

未链接文件示例（完整路径见 JSON）：
- `20260311_5cccb161` / `UPSTREAM_COMMIT`（other）

## LIB / DB 文件名角标

角标仅从链接文件名识别，不读取 LIB/DB 内容。

| 文件名角标 | LIB 文件数 | DB 文件数 |
| --- | ---: | ---: |
| FAST | 2 | 0 |
| SLOW | 2 | 0 |
| TYP | 2 | 0 |

RC 文件名标签：
- `未标注`：LIB 6 个，DB 0 个

LIB/DB 同名对照异常（只作名称核对提示，不判定缺交付）：

- `sg13g2_stdcell_fast_1p32v_m40c`：LIB 1 个，DB 0 个，只有 LIB
- `sg13g2_stdcell_fast_1p65v_m40c`：LIB 1 个，DB 0 个，只有 LIB
- `sg13g2_stdcell_slow_1p08v_125c`：LIB 1 个，DB 0 个，只有 LIB
- `sg13g2_stdcell_slow_1p35v_125c`：LIB 1 个，DB 0 个，只有 LIB
- `sg13g2_stdcell_typ_1p20v_25c`：LIB 1 个，DB 0 个，只有 LIB
- `sg13g2_stdcell_typ_1p50v_25c`：LIB 1 个，DB 0 个，只有 LIB

## 结论边界

本报告核查的是指定 `lib_NL<阶段号>/IP` 目录中的文件路径、链接来源、类型数量和文件名角标。
不比较不同正式阶段，不读取内容或 Hash，不判断 Macro 粒度完整性、文件语义正确性、必需交付项或正式放行。
正式与原始目录均可用于核对文件构成；某类文件为 0 或原始文件未被链接，需结合该 IP 的交付要求由使用者判断。
