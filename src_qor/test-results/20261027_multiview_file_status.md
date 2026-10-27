# 多 View 文件状态与 LEF 联动验收

- 基线：`a5a3627`，工作区包含本次修改。
- 验证时间：2026-10-27。
- 自动化：`PYTHONPATH=src_qor:<bundled-python-site-packages> python3 -m unittest discover -s src_qor/test`，214 项通过，10.303 秒。
- `python3 -m compileall -q src_qor/lib_guard`、`node --check src_qor/lib_guard/static/workbench.js` 和 `git diff --check` 通过。
- 负例：LEF 对比目标与接口检查显式 LEF 不一致时，Web 拒绝入队；Runner 对不同 LEF 路径或不同 LEF 报告来源拒绝静默复用。
- 临时五版本联动：正式 LEF 来自 V01、正式 LIB 来自 V03，检查 V05 中 TT/SS 两个 Liberty，生成结果 JSON 和 Excel；正式链接保持不变。
- 浏览器模拟验收：独立预览使用 IHP.sg13g2_stdcell，文件状态显示 11 个文件；选择 LIBERTY 后显示 6 个。此数据标记为模拟数据，不用于 EDA 或发布。
- 日期重复、RAW 范围不完整、多 LEF、文件枚举截断、权限错误、同 IP 并发和失败保留旧结果由现有自动化用例覆盖。
- 限制：文件状态按路径与版本日期提供线索，不做内容验证；本次没有对真实大库执行极限耗时测试，也未验证所有浏览器和移动端。
- 增量包：`bundle/src_qor_delta_a5a3627_20261027_multiview/src_qor_delta_a5a3627_multiview.json`，包含 5 个运行文件，不含测试。
