# LEF–Liberty 多文件联动核查

- LEF 核查报告：`/home/polaris/proj/mx/ai_lib/repo/src_qor/test-results/formal_nl_20261024/libraries/SRAM22.sram22_256x16m8w8__cc3957909056/runs/review_20261024T164723Z_d91a0632/evidence/lef_review/lef_analysis.json`
- LEF 目标文件：`/home/polaris/proj/mx/ai_lib/3rd_IP/SRAM22/sram22_256x16m8w8/20261024_de0a9a7/LEF/sram22_256x16m8w8.lef`
- Liberty 文件：3 个；逐文件独立核查，不跨角合并。
- 角标统计：工艺角 FF 1、SS 1、TT 1；RC 角 未识别。工艺角未识别 0 个，未标 RC 角 3 个；标签冲突 0 个文件。
- 工艺角和 RC 角仅按文件名/Library 名标注；不代表角条件完整，也不代替人工确认。
- 同名 Cell 接口存在已确认不一致：0 个文件。
- 同名 Cell 接口核查有证据不足：0 个文件。

- 单个 Liberty 文件未覆盖全部 LEF 名称：0 个；这些单文件名称差异归并为 0 组。
- 信号 Pin 对照：138 项，差异 0 项；电源/地脚对照：6 项，差异 0 项。

## 各 Liberty 文件的名称覆盖

本节先给出本次输入文件集合的并集，再列单文件覆盖。单文件未包含的 Macro 不直接等于交付缺失。
信号 Pin 与电源/地脚差异只对该 Liberty 文件中的同名 Cell 统计；未匹配对象不在该项对照范围内。

### 本次输入 Liberty 集合覆盖

按识别到的工艺角/RC 角分组统计，不跨组补齐；角标来自文件名或 Library 名，未人工确认。
- **FF / 未识别**：1 个输入文件；集合覆盖 1/1（100.0%）；Cell 并集 1 个。
  - LEF 有、该组文件未包含：0 个；Liberty 有、LEF 未列出：0 个。
  - 文件：sram22_256x16m8w8_ff_n40C_1v95.lib。
- **SS / 未识别**：1 个输入文件；集合覆盖 1/1（100.0%）；Cell 并集 1 个。
  - LEF 有、该组文件未包含：0 个；Liberty 有、LEF 未列出：0 个。
  - 文件：sram22_256x16m8w8_ss_100C_1v60.lib。
- **TT / 未识别**：1 个输入文件；集合覆盖 1/1（100.0%）；Cell 并集 1 个。
  - LEF 有、该组文件未包含：0 个；Liberty 有、LEF 未列出：0 个。
  - 文件：sram22_256x16m8w8_tt_025C_1v80.lib。
- “未包含”描述的是本次传入的对应角标组，不自动判定交付缺失；未识别角标文件单独作为未识别组。
- `sram22_256x16m8w8_ff_n40C_1v95.lib`：同名 Cell 覆盖 1/1（100.0%）；LEF 有、当前 Liberty 文件未包含 0 个 Macro；Pin 差异只适用于这 1 个同名对象。
- `sram22_256x16m8w8_ss_100C_1v60.lib`：同名 Cell 覆盖 1/1（100.0%）；LEF 有、当前 Liberty 文件未包含 0 个 Macro；Pin 差异只适用于这 1 个同名对象。
- `sram22_256x16m8w8_tt_025C_1v80.lib`：同名 Cell 覆盖 1/1（100.0%）；LEF 有、当前 Liberty 文件未包含 0 个 Macro；Pin 差异只适用于这 1 个同名对象。

| Liberty 文件 | 同名 Cell 覆盖 | LEF 有、当前 Liberty 文件未包含 | 同名对象 Pin 差异 |
| --- | ---: | ---: | ---: |
| `sram22_256x16m8w8_ff_n40C_1v95.lib` | 1/1（100.0%） | 0 | 信号 0；电源/地 0 |
| `sram22_256x16m8w8_ss_100C_1v60.lib` | 1/1（100.0%） | 0 | 信号 0；电源/地 0 |
| `sram22_256x16m8w8_tt_025C_1v80.lib` | 1/1（100.0%） | 0 | 信号 0；电源/地 0 |

名称覆盖统计只回答“此文件包含哪些 LEF 同名对象”，不能单独作为交付完整性结论。

## LEF 基准规模

| Macro | Pin | Signal / Power / Ground | 使用层数 | 尺寸范围（宽 × 高） | Pin 几何 | OBS 几何 |
| ---: | ---: | ---: | ---: | --- | ---: | ---: |
| 1 | 48 | 0 / 1 / 1 | 2（met1, met2） | 396.36–396.36 × 225.68–225.68 μm | 1138 | 2 |
- Macro 类别：BLOCK: 1.

以下 Liberty 数量只覆盖该文件实际包含且与 LEF 同名的 Cell；LEF 基准规模不代表本文件交付覆盖。

| Liberty 文件 | Library | 工艺角 / RC 角 | Cell 数（LEF/LIB/同名） | LEF-only / LIB-only | 信号 Pin 对照 / 差异 | 电源地脚对照 / 差异 | 未验证 |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |
| `sram22_256x16m8w8_ff_n40C_1v95.lib` | `sram22_256x16m8w8` | FF / 无 RC 角标; process=1, voltage=1.95, temperature=-40 | 1 / 1 / 1 | 0 / 0 | 46 / 0 | 2 / 0 | 0 |
| ↳ Liberty 解析总量 | — | — | 1 Cell / 46 信号 Pin / 2 电源地 Pin | — | — | — | — |
| `sram22_256x16m8w8_ss_100C_1v60.lib` | `sram22_256x16m8w8` | SS / 无 RC 角标; process=1, voltage=1.6, temperature=100 | 1 / 1 / 1 | 0 / 0 | 46 / 0 | 2 / 0 | 0 |
| ↳ Liberty 解析总量 | — | — | 1 Cell / 46 信号 Pin / 2 电源地 Pin | — | — | — | — |
| `sram22_256x16m8w8_tt_025C_1v80.lib` | `sram22_256x16m8w8` | TT / 无 RC 角标; process=1, voltage=1.8, temperature=25 | 1 / 1 / 1 | 0 / 0 | 46 / 0 | 2 / 0 | 0 |
| ↳ Liberty 解析总量 | — | — | 1 Cell / 46 信号 Pin / 2 电源地 Pin | — | — | — | — |

## 核查范围与未检查项

- 信号 Pin 解析覆盖不完整：0 个文件；电源/地脚解析覆盖不完整：0 个文件。
- “解析覆盖已提取”只表示当前抽取器支持范围内读到了接口事实，不等于完整 Liberty 语法验证或全部 Pin 集合的独立证明。
- 每个 Liberty 文件独立核对；不会用其他工艺角或 RC 角的 Cell、Pin 补齐本文件。
- 本报告未检查时序弧与时序数值、功耗数值、跨 Corner 等价性或正式发布放行。

每个文件的结论仅适用于该文件与指定 LEF 的同名对象；不同工艺角或 RC 角不互相补齐或合并。
角标只按文件名和 Library 名识别，未识别时不作推断；PVT 数值另列于逐文件行。
完整差异、解析覆盖和绝对来源路径保存在 JSON。
