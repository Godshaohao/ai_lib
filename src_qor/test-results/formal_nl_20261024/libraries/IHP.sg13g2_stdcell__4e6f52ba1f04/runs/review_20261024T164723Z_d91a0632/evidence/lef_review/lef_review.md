# LEF 双文件核查

- 旧文件：`/home/polaris/proj/mx/ai_lib/3rd_IP/IHP/sg13g2_stdcell/20230628_2db4084d/LEF/sg13g2_stdcell.lef`
- 新文件：`/home/polaris/proj/mx/ai_lib/3rd_IP/IHP/sg13g2_stdcell/20260311_5cccb161/LEF/sg13g2_stdcell.lef`
- 范围：仅比较上述两个 LEF，不代表整个库、所有视图或发布放行。

## 两个 LEF 文件内容相同吗？

不同；两侧完整 SHA-256 不一致。

## 这两个文件分别包含什么？

统计来自本次 LEF 解析；“仅已提取”不代表文件内容完整覆盖。

| 指标 | 旧文件 | 新文件 |
| --- | ---: | ---: |
| Macro | 78 | 84 |
| Pin | 405 | 451 |
| 已识别层 | 3 | 3 |
| 已用层 | 已提取 3（不完整） | 已提取 3（不完整） |
| Pin RECT | 未确认 | 未确认 |
| OBS RECT | 未确认 | 1538 |
| 解析限制 | 158 | 168 |

| 内容 | 旧文件 | 新文件 |
| --- | --- | --- |
| Macro 清单覆盖 | 完整 | 完整 |
| Macro 类别 | CORE：78 | CORE：77、CORE SPACER：6、CORE ANTENNACELL：1 |
| Site | CoreSite：78 | CoreSite：84 |
| 尺寸范围 | 0.48～16.8 × 3.78～3.78 μm（78 个有尺寸） | 0.48～19.2 × 3.78～3.78 μm（84 个有尺寸） |
| Pin 方向 | INPUT：172、INOUT：159、OUTPUT：74 | INPUT：201、INOUT：167、OUTPUT：83 |
| Pin 用途 | SIGNAL：241、POWER：79、GROUND：78、ANALOG：7 | SIGNAL：283、GROUND：84、POWER：84 |
| 含供电/接地 Pin 的 Macro | POWER 78/78；GROUND 78/78 | POWER 84/84；GROUND 84/84 |
| 已用层名称 | Metal1, Metal2, Via1 | Metal1, Metal2, Via1 |

## Macro 名称有哪些变化？

两侧共有 78 个同名 Macro。
- 新增（6）：`sg13g2_dfrbpq_1`、`sg13g2_dfrbpq_2`、`sg13g2_sdfrbp_1`、`sg13g2_sdfrbp_2`、`sg13g2_sdfrbpq_1`、`sg13g2_sdfrbpq_2`
- 移除：无。

## 共同 Macro 的规格和接口有什么变化？

共 27 项已确认字段变化：
- `sg13g2_a22oi_1` 原点（`origin`）：{"x": 0.01, "y": 0.01} → {"x": 0.0, "y": 0.0}
- `sg13g2_a22oi_1` 方向（`pins.A1.direction`）："INOUT" → "INPUT"
- `sg13g2_a22oi_1` 方向（`pins.A2.direction`）："INOUT" → "INPUT"
- `sg13g2_a22oi_1` 方向（`pins.B1.direction`）："INOUT" → "INPUT"
- `sg13g2_a22oi_1` 方向（`pins.B2.direction`）："INOUT" → "INPUT"
- `sg13g2_a22oi_1` 方向（`pins.Y.direction`）："INOUT" → "OUTPUT"
- `sg13g2_antennanp` 类别（`class`）："CORE" → "CORE ANTENNACELL"
- `sg13g2_decap_4` 类别（`class`）："CORE" → "CORE SPACER"
- `sg13g2_decap_8` 类别（`class`）："CORE" → "CORE SPACER"
- `sg13g2_dfrbp_1` 尺寸（`size`）：{"x": 12.48, "y": 3.78} → {"x": 13.92, "y": 3.78}
- `sg13g2_ebufn_2` 方向（`pins.Z.direction`）："INOUT" → "OUTPUT"
- `sg13g2_ebufn_4` 尺寸（`size`）：{"x": 6.72, "y": 3.78} → {"x": 7.2, "y": 3.78}
- `sg13g2_fill_1` 类别（`class`）："CORE" → "CORE SPACER"
- `sg13g2_fill_2` 类别（`class`）："CORE" → "CORE SPACER"
- `sg13g2_fill_4` 类别（`class`）："CORE" → "CORE SPACER"
- `sg13g2_fill_8` 类别（`class`）："CORE" → "CORE SPACER"
- `sg13g2_inv_1` 方向（`pins.VDD.direction`）："INPUT" → "INOUT"
- `sg13g2_inv_1` 方向（`pins.VSS.direction`）："INPUT" → "INOUT"
- `sg13g2_nand2b_1` 用途（`pins.A_N.use`）："ANALOG" → "SIGNAL"
- `sg13g2_nand2b_1` 用途（`pins.B.use`）："ANALOG" → "SIGNAL"
- `sg13g2_nand2b_1` 用途（`pins.Y.use`）："ANALOG" → "SIGNAL"
- `sg13g2_o21ai_1` 用途（`pins.Y.use`）："POWER" → "SIGNAL"
- `sg13g2_or2_1` 用途（`pins.A.use`）："ANALOG" → "SIGNAL"
- `sg13g2_or2_1` 用途（`pins.B.use`）："ANALOG" → "SIGNAL"
- `sg13g2_or2_2` 用途（`pins.A.use`）："ANALOG" → "SIGNAL"
- `sg13g2_or2_2` 用途（`pins.B.use`）："ANALOG" → "SIGNAL"
- `sg13g2_sdfbbp_1` 方向（`pins.RESET_B.direction`）："OUTPUT" → "INPUT"

## 几何与 OBS 有什么变化？

几何/OBS 提取不完整，本次不判断是否变化；具体覆盖限制见下。

## 对接入有什么提示？

- Macro 清单变化：核对设计实例依赖的 Macro 是否仍在目标 LEF 中。
- 物理规格变化：核对布局、站点兼容性以及相关放置约束；不能仅凭 LEF 推断设计失效。
- Pin 定义变化：核对实例连接、端口方向及所用层。
- 部分字段证据不足；请先补充相应解析或人工核对，不能当作“未变化”。
- 其他视图未比较；本报告不判断时序、逻辑、跨视图一致性或正式放行。

## 哪些内容不能确认？

以下字段至少一侧缺少完整解析覆盖，未作为“无变化”结论：`obs_geometry`、`pin_geometry`、`pin_layers`、`pins.shape`。
- 旧文件解析限制记录：158 项；最多前 100 条样例见 JSON 的 `extraction.old.data.parse_limitations`。
- 新文件解析限制记录：168 项；最多前 100 条样例见 JSON 的 `extraction.new.data.parse_limitations`。

完整提取事实、Pin 明细、旧新值和证据覆盖保存在 `lef_analysis.json`。

## 附录：Macro 逐项索引（完整 Macro 索引，目标文件 84 个）

供电脚覆盖结论已列在前面的统计摘要；此处用于按 Macro 查找 Pin/尺寸/几何细节。没有 POWER/GROUND 声明的 Macro 单独列出，是否属于预期黑盒需按库约定判断。

| Macro | 类别 | Site | 尺寸 (μm) | Pin | 信号/时钟 | 电源脚 | 地脚 | 用途未标注 | Pin RECT | OBS RECT |
| --- | --- | --- | ---: | ---: | --- | --- | --- | ---: | ---: | ---: |
| `sg13g2_a21o_1` | CORE | CoreSite | 3.36 × 3.78 | 6 | 4 | `VDD` | `VSS` | 0 | 未确认 | 9 |
| `sg13g2_a21o_2` | CORE | CoreSite | 3.84 × 3.78 | 6 | 4 | `VDD` | `VSS` | 0 | 未确认 | 8 |
| `sg13g2_a21oi_1` | CORE | CoreSite | 2.4 × 3.78 | 6 | 4 | `VDD` | `VSS` | 0 | 未确认 | 3 |
| `sg13g2_a21oi_2` | CORE | CoreSite | 3.84 × 3.78 | 6 | 4 | `VDD` | `VSS` | 0 | 未确认 | 9 |
| `sg13g2_a221oi_1` | CORE | CoreSite | 3.84 × 3.78 | 8 | 6 | `VDD` | `VSS` | 0 | 未确认 | 6 |
| `sg13g2_a22oi_1` | CORE | CoreSite | 2.88 × 3.78 | 7 | 5 | `VDD` | `VSS` | 0 | 未确认 | 3 |
| `sg13g2_and2_1` | CORE | CoreSite | 2.4 × 3.78 | 5 | 3 | `VDD` | `VSS` | 0 | 未确认 | 5 |
| `sg13g2_and2_2` | CORE | CoreSite | 2.88 × 3.78 | 5 | 3 | `VDD` | `VSS` | 0 | 未确认 | 5 |
| `sg13g2_and3_1` | CORE | CoreSite | 3.36 × 3.78 | 6 | 4 | `VDD` | `VSS` | 0 | 未确认 | 5 |
| `sg13g2_and3_2` | CORE | CoreSite | 3.36 × 3.78 | 6 | 4 | `VDD` | `VSS` | 0 | 未确认 | 5 |
| `sg13g2_and4_1` | CORE | CoreSite | 3.84 × 3.78 | 7 | 5 | `VDD` | `VSS` | 0 | 未确认 | 7 |
| `sg13g2_and4_2` | CORE | CoreSite | 4.32 × 3.78 | 7 | 5 | `VDD` | `VSS` | 0 | 未确认 | 7 |
| `sg13g2_antennanp` | CORE ANTENNACELL | CoreSite | 1.44 × 3.78 | 3 | 1 | `VDD` | `VSS` | 0 | 未确认 | 0 |
| `sg13g2_buf_1` | CORE | CoreSite | 1.92 × 3.78 | 4 | 2 | `VDD` | `VSS` | 0 | 未确认 | 6 |
| `sg13g2_buf_16` | CORE | CoreSite | 12 × 3.78 | 4 | 2 | `VDD` | `VSS` | 0 | 未确认 | 10 |
| `sg13g2_buf_2` | CORE | CoreSite | 2.4 × 3.78 | 4 | 2 | `VDD` | `VSS` | 0 | 未确认 | 8 |
| `sg13g2_buf_4` | CORE | CoreSite | 3.84 × 3.78 | 4 | 2 | `VDD` | `VSS` | 0 | 未确认 | 7 |
| `sg13g2_buf_8` | CORE | CoreSite | 6.24 × 3.78 | 4 | 2 | `VDD` | `VSS` | 0 | 未确认 | 8 |
| `sg13g2_decap_4` | CORE SPACER | CoreSite | 1.92 × 3.78 | 2 | 0 | `VDD` | `VSS` | 0 | 未确认 | 0 |
| `sg13g2_decap_8` | CORE SPACER | CoreSite | 3.36 × 3.78 | 2 | 0 | `VDD` | `VSS` | 0 | 未确认 | 0 |
| `sg13g2_dfrbp_1` | CORE | CoreSite | 13.92 × 3.78 | 7 | 5 | `VDD` | `VSS` | 0 | 未确认 | 68 |
| `sg13g2_dfrbp_2` | CORE | CoreSite | 14.4 × 3.78 | 7 | 5 | `VDD` | `VSS` | 0 | 未确认 | 69 |
| `sg13g2_dfrbpq_1` | CORE | CoreSite | 12.96 × 3.78 | 6 | 4 | `VDD` | `VSS` | 0 | 未确认 | 67 |
| `sg13g2_dfrbpq_2` | CORE | CoreSite | 13.44 × 3.78 | 6 | 4 | `VDD` | `VSS` | 0 | 未确认 | 69 |
| `sg13g2_dlhq_1` | CORE | CoreSite | 8.16 × 3.78 | 5 | 3 | `VDD` | `VSS` | 0 | 未确认 | 47 |
| `sg13g2_dlhr_1` | CORE | CoreSite | 8.64 × 3.78 | 7 | 5 | `VDD` | `VSS` | 0 | 未确认 | 39 |
| `sg13g2_dlhrq_1` | CORE | CoreSite | 7.2 × 3.78 | 6 | 4 | `VDD` | `VSS` | 0 | 未确认 | 38 |
| `sg13g2_dllr_1` | CORE | CoreSite | 9.12 × 3.78 | 7 | 5 | `VDD` | `VSS` | 0 | 未确认 | 48 |
| `sg13g2_dllrq_1` | CORE | CoreSite | 7.68 × 3.78 | 6 | 4 | `VDD` | `VSS` | 0 | 未确认 | 33 |
| `sg13g2_dlygate4sd1_1` | CORE | CoreSite | 3.84 × 3.78 | 4 | 2 | `VDD` | `VSS` | 0 | 未确认 | 17 |
| `sg13g2_dlygate4sd2_1` | CORE | CoreSite | 3.84 × 3.78 | 4 | 2 | `VDD` | `VSS` | 0 | 未确认 | 17 |
| `sg13g2_dlygate4sd3_1` | CORE | CoreSite | 4.32 × 3.78 | 4 | 2 | `VDD` | `VSS` | 0 | 未确认 | 14 |
| `sg13g2_ebufn_2` | CORE | CoreSite | 4.8 × 3.78 | 5 | 3 | `VDD` | `VSS` | 0 | 未确认 | 21 |
| `sg13g2_ebufn_4` | CORE | CoreSite | 7.2 × 3.78 | 5 | 3 | `VDD` | `VSS` | 0 | 未确认 | 28 |
| `sg13g2_ebufn_8` | CORE | CoreSite | 12 × 3.78 | 5 | 3 | `VDD` | `VSS` | 0 | 未确认 | 40 |
| `sg13g2_einvn_2` | CORE | CoreSite | 4.32 × 3.78 | 5 | 3 | `VDD` | `VSS` | 0 | 未确认 | 14 |
| `sg13g2_einvn_4` | CORE | CoreSite | 6.24 × 3.78 | 5 | 3 | `VDD` | `VSS` | 0 | 未确认 | 17 |
| `sg13g2_einvn_8` | CORE | CoreSite | 10.56 × 3.78 | 5 | 3 | `VDD` | `VSS` | 0 | 未确认 | 27 |
| `sg13g2_fill_1` | CORE SPACER | CoreSite | 0.48 × 3.78 | 2 | 0 | `VDD` | `VSS` | 0 | 未确认 | 0 |
| `sg13g2_fill_2` | CORE SPACER | CoreSite | 0.96 × 3.78 | 2 | 0 | `VDD` | `VSS` | 0 | 未确认 | 0 |
| `sg13g2_fill_4` | CORE SPACER | CoreSite | 1.92 × 3.78 | 2 | 0 | `VDD` | `VSS` | 0 | 未确认 | 0 |
| `sg13g2_fill_8` | CORE SPACER | CoreSite | 3.84 × 3.78 | 2 | 0 | `VDD` | `VSS` | 0 | 未确认 | 0 |
| `sg13g2_inv_1` | CORE | CoreSite | 1.44 × 3.78 | 4 | 2 | `VDD` | `VSS` | 0 | 未确认 | 0 |
| `sg13g2_inv_16` | CORE | CoreSite | 9.12 × 3.78 | 4 | 2 | `VDD` | `VSS` | 0 | 未确认 | 0 |
| `sg13g2_inv_2` | CORE | CoreSite | 1.92 × 3.78 | 4 | 2 | `VDD` | `VSS` | 0 | 未确认 | 0 |
| `sg13g2_inv_4` | CORE | CoreSite | 2.88 × 3.78 | 4 | 2 | `VDD` | `VSS` | 0 | 未确认 | 0 |
| `sg13g2_inv_8` | CORE | CoreSite | 4.8 × 3.78 | 4 | 2 | `VDD` | `VSS` | 0 | 未确认 | 0 |
| `sg13g2_lgcp_1` | CORE | CoreSite | 7.2 × 3.78 | 5 | 3 | `VDD` | `VSS` | 0 | 未确认 | 33 |
| `sg13g2_mux2_1` | CORE | CoreSite | 4.8 × 3.78 | 6 | 4 | `VDD` | `VSS` | 0 | 未确认 | 18 |
| `sg13g2_mux2_2` | CORE | CoreSite | 5.28 × 3.78 | 6 | 4 | `VDD` | `VSS` | 0 | 未确认 | 18 |
| `sg13g2_mux4_1` | CORE | CoreSite | 10.08 × 3.78 | 9 | 7 | `VDD` | `VSS` | 0 | 未确认 | 50 |
| `sg13g2_nand2_1` | CORE | CoreSite | 1.92 × 3.78 | 5 | 3 | `VDD` | `VSS` | 0 | 未确认 | 0 |
| `sg13g2_nand2_2` | CORE | CoreSite | 2.88 × 3.78 | 5 | 3 | `VDD` | `VSS` | 0 | 未确认 | 5 |
| `sg13g2_nand2b_1` | CORE | CoreSite | 2.4 × 3.78 | 5 | 3 | `VDD` | `VSS` | 0 | 未确认 | 6 |
| `sg13g2_nand2b_2` | CORE | CoreSite | 3.84 × 3.78 | 5 | 3 | `VDD` | `VSS` | 0 | 未确认 | 9 |
| `sg13g2_nand3_1` | CORE | CoreSite | 2.4 × 3.78 | 6 | 4 | `VDD` | `VSS` | 0 | 未确认 | 0 |
| `sg13g2_nand3b_1` | CORE | CoreSite | 3.36 × 3.78 | 6 | 4 | `VDD` | `VSS` | 0 | 未确认 | 6 |
| `sg13g2_nand4_1` | CORE | CoreSite | 2.88 × 3.78 | 7 | 5 | `VDD` | `VSS` | 0 | 未确认 | 0 |
| `sg13g2_nor2_1` | CORE | CoreSite | 1.92 × 3.78 | 5 | 3 | `VDD` | `VSS` | 0 | 未确认 | 0 |
| `sg13g2_nor2_2` | CORE | CoreSite | 2.88 × 3.78 | 5 | 3 | `VDD` | `VSS` | 0 | 未确认 | 5 |
| `sg13g2_nor2b_1` | CORE | CoreSite | 2.4 × 3.78 | 5 | 3 | `VDD` | `VSS` | 0 | 未确认 | 4 |
| `sg13g2_nor2b_2` | CORE | CoreSite | 3.36 × 3.78 | 5 | 3 | `VDD` | `VSS` | 0 | 未确认 | 5 |
| `sg13g2_nor3_1` | CORE | CoreSite | 2.4 × 3.78 | 6 | 4 | `VDD` | `VSS` | 0 | 未确认 | 0 |
| `sg13g2_nor3_2` | CORE | CoreSite | 4.32 × 3.78 | 6 | 4 | `VDD` | `VSS` | 0 | 未确认 | 7 |
| `sg13g2_nor4_1` | CORE | CoreSite | 2.88 × 3.78 | 7 | 5 | `VDD` | `VSS` | 0 | 未确认 | 0 |
| `sg13g2_nor4_2` | CORE | CoreSite | 5.76 × 3.78 | 7 | 5 | `VDD` | `VSS` | 0 | 未确认 | 12 |
| `sg13g2_o21ai_1` | CORE | CoreSite | 2.4 × 3.78 | 6 | 4 | `VDD` | `VSS` | 0 | 未确认 | 3 |
| `sg13g2_or2_1` | CORE | CoreSite | 2.4 × 3.78 | 5 | 3 | `VDD` | `VSS` | 0 | 未确认 | 6 |
| `sg13g2_or2_2` | CORE | CoreSite | 2.88 × 3.78 | 5 | 3 | `VDD` | `VSS` | 0 | 未确认 | 6 |
| `sg13g2_or3_1` | CORE | CoreSite | 3.36 × 3.78 | 6 | 4 | `VDD` | `VSS` | 0 | 未确认 | 8 |
| `sg13g2_or3_2` | CORE | CoreSite | 3.84 × 3.78 | 6 | 4 | `VDD` | `VSS` | 0 | 未确认 | 8 |
| `sg13g2_or4_1` | CORE | CoreSite | 3.84 × 3.78 | 7 | 5 | `VDD` | `VSS` | 0 | 未确认 | 10 |
| `sg13g2_or4_2` | CORE | CoreSite | 4.32 × 3.78 | 7 | 5 | `VDD` | `VSS` | 0 | 未确认 | 8 |
| `sg13g2_sdfbbp_1` | CORE | CoreSite | 16.8 × 3.78 | 10 | 8 | `VDD` | `VSS` | 0 | 未确认 | 90 |
| `sg13g2_sdfrbp_1` | CORE | CoreSite | 18.24 × 3.78 | 9 | 7 | `VDD` | `VSS` | 0 | 未确认 | 91 |
| `sg13g2_sdfrbp_2` | CORE | CoreSite | 19.2 × 3.78 | 9 | 7 | `VDD` | `VSS` | 0 | 未确认 | 91 |
| `sg13g2_sdfrbpq_1` | CORE | CoreSite | 16.8 × 3.78 | 8 | 6 | `VDD` | `VSS` | 0 | 未确认 | 89 |
| `sg13g2_sdfrbpq_2` | CORE | CoreSite | 17.28 × 3.78 | 8 | 6 | `VDD` | `VSS` | 0 | 未确认 | 88 |
| `sg13g2_sighold` | CORE | CoreSite | 2.4 × 3.78 | 3 | 1 | `VDD` | `VSS` | 0 | 未确认 | 3 |
| `sg13g2_slgcp_1` | CORE | CoreSite | 8.16 × 3.78 | 6 | 4 | `VDD` | `VSS` | 0 | 未确认 | 45 |
| `sg13g2_tiehi` | CORE | CoreSite | 1.92 × 3.78 | 3 | 1 | `VDD` | `VSS` | 0 | 未确认 | 6 |
| `sg13g2_tielo` | CORE | CoreSite | 1.92 × 3.78 | 3 | 1 | `VDD` | `VSS` | 0 | 未确认 | 4 |
| `sg13g2_xnor2_1` | CORE | CoreSite | 3.84 × 3.78 | 5 | 3 | `VDD` | `VSS` | 0 | 未确认 | 11 |
| `sg13g2_xor2_1` | CORE | CoreSite | 3.84 × 3.78 | 5 | 3 | `VDD` | `VSS` | 0 | 未确认 | 9 |

本索引复核：POWER 84/84；GROUND 84/84。
目标文件中所有 Macro 均声明 POWER 和 GROUND Pin。
