# LEF 双文件核查

- 旧文件：`/home/polaris/proj/mx/ai_lib/3rd_IP/SRAM22/sram22_256x16m8w8/20241117_cb95ccae/LEF/sram22_256x16m8w8.lef`
- 新文件：`/home/polaris/proj/mx/ai_lib/3rd_IP/SRAM22/sram22_256x16m8w8/20261024_de0a9a7/LEF/sram22_256x16m8w8.lef`
- 范围：仅比较上述两个 LEF，不代表整个库、所有视图或发布放行。

## 两个 LEF 文件内容相同吗？

不同；两侧完整 SHA-256 不一致。

## 这两个文件分别包含什么？

统计来自本次 LEF 解析；“仅已提取”不代表文件内容完整覆盖。

| 指标 | 旧文件 | 新文件 |
| --- | ---: | ---: |
| Macro | 1 | 1 |
| Pin | 48 | 48 |
| 已识别层 | 2 | 2 |
| 已用层 | 2 | 2 |
| Pin RECT | 1122 | 1138 |
| OBS RECT | 2 | 2 |
| 解析限制 | 0 | 0 |

| 内容 | 旧文件 | 新文件 |
| --- | --- | --- |
| Macro 清单覆盖 | 完整 | 完整 |
| Macro 类别 | BLOCK：1 | BLOCK：1 |
| Site | 未提供：1 | 未提供：1 |
| 尺寸范围 | 396.36～396.36 × 225.68～225.68 μm（1 个有尺寸） | 396.36～396.36 × 225.68～225.68 μm（1 个有尺寸） |
| Pin 方向 | INPUT：30、OUTPUT：16、INOUT：2 | INPUT：30、OUTPUT：16、INOUT：2 |
| Pin 用途 | 未提供：46、GROUND：1、POWER：1 | 未提供：46、GROUND：1、POWER：1 |
| 含供电/接地 Pin 的 Macro | POWER 1/1；GROUND 1/1 | POWER 1/1；GROUND 1/1 |
| 已用层名称 | met1, met2 | met1, met2 |

## Macro 名称有哪些变化？

两侧共有 1 个同名 Macro。
- 新增：无。
- 移除：无。

## 共同 Macro 的规格和接口有什么变化？

已提取且可核查的规格和接口字段未发现变化；这不代表未解析字段相同。

## 几何与 OBS 有什么变化？

共 2 项已确认的 RECT 几何/OBS 变化：
- `sram22_256x16m8w8` 几何（`pins.vdd.rects`）发生变化；旧新坐标见 `lef_analysis.json`。
- `sram22_256x16m8w8` 几何（`pins.vss.rects`）发生变化；旧新坐标见 `lef_analysis.json`。

## 对接入有什么提示？

- Pin 定义变化：核对实例连接、端口方向及所用层。
- 几何或 OBS 变化：核对布局布线和阻挡区域；必要时运行物理验证。
- 其他视图未比较；本报告不判断时序、逻辑、跨视图一致性或正式放行。

## 哪些内容不能确认？

本命令选择的字段均具有两侧解析覆盖；其他 LEF 语法及跨视图一致性未检查。

完整提取事实、Pin 明细、旧新值和证据覆盖保存在 `lef_analysis.json`。

## 附录：Macro 逐项索引（完整 Macro 索引，目标文件 1 个）

供电脚覆盖结论已列在前面的统计摘要；此处用于按 Macro 查找 Pin/尺寸/几何细节。没有 POWER/GROUND 声明的 Macro 单独列出，是否属于预期黑盒需按库约定判断。

| Macro | 类别 | Site | 尺寸 (μm) | Pin | 信号/时钟 | 电源脚 | 地脚 | 用途未标注 | Pin RECT | OBS RECT |
| --- | --- | --- | ---: | ---: | --- | --- | --- | ---: | ---: | ---: |
| `sram22_256x16m8w8` | BLOCK | 未提供 | 396.36 × 225.68 | 48 | 0 | `vdd` | `vss` | 46 | 1138 | 2 |

本索引复核：POWER 1/1；GROUND 1/1。
目标文件中所有 Macro 均声明 POWER 和 GROUND Pin。
