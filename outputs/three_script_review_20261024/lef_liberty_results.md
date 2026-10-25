# LEF–Liberty 联动结果

**对象：** 指定 ASAP7 LEF 与 3 个 Liberty 文件；TT、SS、FF 分别核查，不跨 Corner 合并。

## 主要结果

| 项目 | 结果 |
|---|---:|
| Liberty 文件 | 3（TT、SS、FF 各 1） |
| 每个文件中的 Cell | 56 |
| 每个文件与 LEF 同名 Cell | 56 / 212（26.4%） |
| 每个文件的 LEF-only 名称 | 156 |
| 信号 Pin 对照 / 差异 | 648 / 0 |
| 电源/地 Pin 对照 / 问题 | 336 / 0 |
| 有接口差异 / 证据不足的文件 | 0 / 0 |
| 无 RC 角文件名标记 | 3 |

56/212 是**单个 Liberty 文件**相对 LEF 的同名 Cell 覆盖范围。三份文件各有相同的 156 个 LEF-only 名称；这不等于已证明交付缺失，需结合该库的 Liberty 分片/交付约定判断。Pin 对照只对每个文件中 56 个同名 Cell 执行。

## Corner 明细

| Corner（文件名/Library 线索） | PVT（解析值） | 同名 Cell | 信号 Pin 差异 | 电源/地 Pin 问题 |
|---|---|---:|---:|---:|
| TT | 0.70 V / 25 °C | 56 / 212 | 0 | 0 |
| SS | 0.63 V / 100 °C | 56 / 212 | 0 | 0 |
| FF | 0.77 V / 0 °C | 56 / 212 | 0 | 0 |

Corner 为文件名/Library 识别线索；RC 角未识别。本检查不比较时序弧、时序数值、功耗、跨 Corner 等价性，也不构成正式放行。每个 Liberty 文件的路径、解析及 PVT 详表见 [Excel「Lib接口核查」页](three_script_results.xlsx)；完整机器数据：`/tmp/ai_lib_report_review_20261023/lef_liberty/lef_liberty_check.json`。
