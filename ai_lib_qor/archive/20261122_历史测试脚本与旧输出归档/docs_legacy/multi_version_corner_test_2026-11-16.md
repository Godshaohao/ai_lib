# 多供应商、版本和 Corner 验证记录

## 验证数据与范围

测试使用临时目录中的合成 RAW，不是真实生产库。V07 为 FULL，包含 LEF、TT、FF；V08 为 INCREMENTAL，包含 LEF、TT；V09 为 INCREMENTAL，包含 LEF、SS。三份 LEF 和 Liberty 文件由测试生成。各 Corner 的文件位通过明确 mapping 设定，未从文件名推断身份。

## 实测结果

- 新增 `tests/test_multiversion_corners.py`：生成 rev_0001、rev_0002、rev_0003；确认 rev_0003 的 TT 来自 V08，FF 来自 V07，SS 来自 V09；最新计算为 rev_0003，已采纳仍为 rev_0001。
- 以 rev_0002 为基线，使用已生成的 LEF / Liberty 事实自动配对三个 Corner；TT 和 SS 的信号 Pin 一致（PASS），FF 的 Z Pin 方向有意设置不一致（FAIL），汇总为 1 项失败；HTML 和 Excel 都包含三个 Corner 文件位与 FAIL。
- 检查前后计算全部模拟 RAW 文件 SHA-256，确认测试没有修改输入文件。
- `tests/test_workbench.py` 使用两个供应商、两个源库和同名 IP，确认侧栏分组及选择后的记录隔离；验证有效版本的 Corner 筛选。
- 全部测试命令：`PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="src:<bundled-site-packages>" python3 -m unittest discover -s tests -q`；本次 **69 项通过**。

## 已有边界与尚未落地的测试

- 这里的 Corner 是交付 mapping 中记录的分类标签；检查只覆盖当前 LEF / Liberty 信号 Pin 名称和方向，**不等于 PVT 数值、时序、PG 或几何验收**。
- 尚未对真实生产 RAW、不同厂商命名及大型库做端到端验收；还需要用真实输入核对 parser 覆盖、错误处理和报告性能。
- 上一轮列出的旧版功能，如 RAW 自动发现和登记、一键检查与后台任务、旧版完整几何/PG 规则、两类 Excel 逐项等价、事实防篡改等仍未完整实现或验收。现有 69 项通过不代表这些功能已经完成。
- 工作台运行计划/历史尚未强制按所选 IP 绑定；操作前仍需确认计划目标。自动配对只消费明确给出的 facts，不扫描所有 RAW 文件。
