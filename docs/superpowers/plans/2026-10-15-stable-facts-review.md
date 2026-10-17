Status: current

# 稳定事实与按需检查验收

目标用户：维护多版本 IP 的库管理者及检查规则维护者。

主要判断：本次有效组合检查了哪些事实；哪些文件可复用；结果能否在配置、解析器或规则更新后追溯。

输入：已确认 Effective Manifest、Catalog/runtime、已有逐文件解析证据、semantic_review.json。
输出：共享文件 Facts、按需组装的内存 Model、规则检查与变化结果、不可覆盖的结果快照及中文摘要。
边界：不增加数据库、插件系统、任务调度或 Release Gate；不重新扫描和计算原始文件 hash。

## 实施与检查项

- [x] Facts 独立于来源路径、版本、Corner 和报告位置，保留视图原生对象及覆盖声明。
- [x] 依据解析输出内容、Parser 版本、Facts schema 和转换代码标识复用 Facts；不将其称为原始文件内容验证。
- [x] 同一事实以不同来源装配时，证据仍指向各自来源，不污染历史引用。
- [x] 解析器/转换代码更新产生新事实身份；缓存损坏可以从现有 ParserResult 重建。
- [x] Model 只在本次检查范围内组装，运行后不维护全局可变模型。
- [x] Rules 仍为显式 Python 函数，禁用的规则不执行；配置只允许已实现的规则。
- [x] 所选 Liberty Corner 的端口变化可下钻；不完整解析不输出通过。
- [x] Results 绑定双方 Effective、Scope、确认映射、规则版本/代码指纹和 Facts 引用。
- [x] 同内容运行复用快照；已完成快照文件不重写；失败不切换结果入口。
- [x] 从快照与 Facts 回读历史结果，不依赖原始目录、Web Job 或 HTML。
- [x] 相同输入下，复用与强制重算得到相同语义检查及 Delta。
- [x] 验证 FULL + FIX、变更所选/未选 Corner、单版本、旧解析器及真实库证据。
- [x] 运行语义模块测试、全量回归、编译与差异检查；记录失败案例和验收证据。

Facts 缓存仅避免重复适配扫描解析结果；原始文件解析复用继续由 ScanCache 管理。
未带可靠原始内容 hash 的 ParserResult 不会因为进入 Facts 存储而变成内容已确认。

## 实施文件

| 文件 | 责任 |
| --- | --- |
| `semantic/facts.py` | 稳定文件事实、内容身份、Parser/转换版本隔离、来源分离与负载校验 |
| `semantic/binding.py::build_effective_model` | 按 Effective 和 Scope 临时组装 Model |
| `semantic/checks.py` | 选中规则执行与按 Corner 的 Liberty 端口 Delta |
| `semantic/results.py` | 引用式快照、不可覆盖发布、独立历史回读 |
| `semantic/runner.py` | 组合四层并在完整发布后切换入口 |
| `scan/scanner.py` | 有内容 hash 的 Parser 缓存重新绑定当前来源；无 hash 缓存不跨来源路径复用 |
| `configs/semantic_review.json` | 方案、规则、容差及共享事实目录 |

## 回归与失败案例

测试：`PYTHONPATH=src python3 -m unittest discover -s src/lib_guard/test -p 'test_semantic*.py' -q`。
全量：`PYTHONPATH=src python3 -m unittest discover -s src/lib_guard/test -p 'test*.py' -q`。

新增架构测试覆盖：共享事实来源隔离、Parser/转换版本变化、缓存损坏、重算对账、禁用规则不执行、
所选 TT 端口变化及跨视图不一致、未选 FF 变化保留在完整索引、快照不重写、移除上游后的历史回读、
规则代码指纹变化、快照中途写失败、事实目录写入权限失败，以及真实 Parser 的跨路径缓存复用。

测试驱动暴露并修正的实际失败：

1. 旧缓存键未区分同相对路径/大小/mtime 的不同 RAW 根，现已绑定来源路径。
2. Parser 内容缓存命中仍携带旧文件名，现已重绑定当前 file/abs_path/file_type/compression。
3. 事实目录权限失败曾被归为普通证据缺失并发布不完整替代结果，现报告存储失败且保持原入口。
4. 首次全量回归唯一失败为新计划缺少 `Status: current`，补齐后 917 项通过。

## 现有数据验收

证据：`work/stable_facts_validation_20261015/validation.json`。

| 数据 | 结果 | 重复运行 | 历史回读 |
| --- | --- | --- | --- |
| 真实 Parser 的 FULL + FIX | 3 个当前文件，4 个独立 Facts；LEF 尺寸变化 1 项 | 转换总数保持 4，新增命中 6 | 与原结果完全一致 |
| 现有 ASAP7 扫描 | 205 个当前文件，已有可用解析证据生成 28 个 Facts | 转换总数保持 28，新增命中 28 | 与原结果完全一致 |

两组案例均未改动 Catalog/runtime/有效组合输入。ASAP7 冷/热耗时约 1.70/1.72 秒；
当前收益是避免重复 Facts 转换，不宣称整体诊断已经提速。大量 UNKNOWN/NOT_CHECKED 来源于旧解析器
及缺失/不完整覆盖，不能用文件缓存命中率替代检查质量验收。只有受控完整解析证据的端口检查通过/失败
才用于验证端口规则；生产旧解析器的完整端口提取仍需独立迭代。
