# LEF 双文件结果

**对象：** ASAP7 `asap7sc7p5t_28_SL_1x_220121a.lef`，仅比较指定旧、新两份文件。

## 结论

两文件完整 SHA-256 相同，字节内容一致。解析器在两侧均提取到 212 个 Macro、1326 个 Pin；Macro 名称新增/移除均为 0，已比较字段变化为 0，未验证项为 0。

| 统计项 | 旧文件 | 新文件 |
|---|---:|---:|
| Macro / Pin | 212 / 1326 | 212 / 1326 |
| POWER / GROUND 覆盖 Macro | 212 / 212 | 212 / 212 |
| Pin RECT / OBS RECT | 2900 / 2797 | 2900 / 2797 |
| 使用层 | 5 | 5 |
| 解析限制 | 0 | 0 |

因此就这对 LEF 而言，没有新增的文件内容差异需要核对。该结论不外推到其他 LEF、其他 View 或整个库，也不代表 LEF 语义及跨视图检查通过。

完整的 212 个 Macro 明细适合在 Excel 中筛选；见 [Excel「LEF比较」页](three_script_results.xlsx)。原始解析数据：`/tmp/ai_lib_report_review_20261023/lef/lef_analysis.json`。
