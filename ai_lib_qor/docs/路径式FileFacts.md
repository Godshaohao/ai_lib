# 路径式 FileFacts

`minimal-facts` 消费新路径式 `file_index.json`，按明确的交付版本或 Effective Revision 选择一个文件，生成同库独立 `file_facts.path.v1` JSON。来源包含 `vendor`、`library`、`version`、`relative_path`、`absolute_path`；不创建 `delivery_id` 或 `file_id`。`selection` 记录按交付还是有效版本选择，`parsed_at` 为 UTC 时间。

```bash
PYTHONPATH=src:../src python3 -m ai_lib_qor minimal-facts \
  --work /path/to/work --vendor SRAM22 --library sram22_256x16m8w8 \
  --view LEF --path LEF/sram22_256x16m8w8.lef --revision rev_0002
```

也可用 `--version 20261024_de0a9a7` 指定精确交付版本；如果该版本没有该文件，不沿用更早的文件。输出在对应 Library 下，命名为 `facts_<VIEW>_<UTC时间>_<序号>.json`；同一文件重复执行会产生新记录，目前尚未跨运行缓存复用。

当前支持 LEF Macro 名称、SIZE、Pin 名称、方向与 USE（包括 POWER/GROUND），以及 Liberty Cell、信号 Pin 名称和方向。`parse_status=COMPLETE` 仅表示 `covered_sections` 中标注的解析范围完成，不表示整个格式的所有语义已覆盖，也不表示质量检查通过。Verilog 模块／端口和 CDL、SPICE 子电路／实例已接入路径式 Facts；沿用轻量解析器，始终标为 `PARTIAL`，不保证预处理、展开、网表语义或实例齐全。GDS 暂不解析。

读取索引前会完整校验其与同库归档一致；解析前后对**所选文件**的元信息和 SHA-256 进行比较，检测解析期间的变化，保存前再次校验索引。不会对 RAW 全库计算 SHA-256。`source.historical_content=UNVERIFIED` 表示无法证明当前文件字节与交付时完全一致；稳定的当前读取不等于历史内容已验证。

新命令 `minimal-check-revision` 和 `minimal-check-library` 消费路径式索引和 Facts，分别生成单版本与整体 Excel。整体运行对每个版本调用同一检查流程，并读取其 CheckResult 汇总；结果、Facts 和报告均写入同库目录。单版本报告保留原有概览、版本矩阵、Macro View、LEF、Liberty 和来源对照等工作表名称；整体报告是版本汇总与逐项检查。详细字段以生成结果为准，并非旧 Excel 每个单元格均已迁移。

```bash
PYTHONPATH=src:../src python3 -m ai_lib_qor minimal-check-revision --work /path/to/work --vendor SRAM22 --library sram22_256x16m8w8 --revision rev_0002
PYTHONPATH=src:../src python3 -m ai_lib_qor minimal-check-library --work /path/to/work --vendor SRAM22 --library sram22_256x16m8w8
```

当前复用 LEF Macro SIZE／Pin 存在及方向对比、LEF–Liberty 信号 Pin 检查，以及旧解析器的 Verilog 模块端口和 CDL／SPICE 子电路引脚摘要对比。后者只列出 `PARTIAL` 观察差异，不能推断完整网表一致。电源／地 Pin 从信号检查排除；GDS 等未解析成员在报告明确标 `NOT_CHECKED`。多个 LEF 与一个 Liberty 无法唯一配对时标 `INCONCLUSIVE`，尚无交互式指定配对入口。只做部分解析或存在未检查成员时运行状态为 `PARTIAL`；`SUCCEEDED` 是本次执行状态，不是整库质量通过。

旧 v3 检查入口仍消费原 `file_facts.v1`；新入口消费 `file_facts.path.v1`。旧 Web、旧插件全量范围和跨 BusinessIP 的聚合尚未切换到新入口。
