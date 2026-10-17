Status: current

# Macro 索引与按需 LEF 检查事实

使用者：核查 IP 有效组合的库管理者。
判断：哪些 Macro、物理摘要与接口发生变化，几何/OBS 是否实际检查完整。
输入：有效组合、已有 scan ParserResult；真实验收从本机样本扫描生成新的证据。
输出：原有诊断快照中的轻量 Macro 索引、Delta、中文摘要；几何检查事实只在单次任务中复用。
边界：沿用 semantic 模块，不另建 checks 框架，不修改 Release Gate，不推送远端。

## 本轮阶段

1. LEF Macro Index：实体与来源关联、Size/Class/Pin Count，同名冲突与不完整状态。
2. RECT 范围的 LEF Delta：Macro 增删、Size/Class/Origin/Symmetry、Pin Name/Direction/Use、PORT 分组、RECT、OBS。
3. 保持已有 View Binding/接口检查，新增部分不扩展 Liberty/RTL 语法能力。
4. 高级质量检查不纳入本轮。

## 检查项

- [x] 逐对象 Macro 索引与独立 Cadence Reader 的名称、数量、Size、Class、Pin Count 对齐。
- [x] 多 LEF、多 Macro 与同名冲突不错误合并；解析失败不能 READY。
- [x] Pin Count 不变时名称、方向、Use 变化仍可识别。
- [x] PORT 分组改变、同长度坐标改变、OBS 坐标改变可识别。
- [x] 注释与无意义排列改变不产生语义 Delta。
- [x] POLYGON/VIA/MASK/ITERATE 等未支持语法及截断输入不能 UNCHANGED。
- [x] 缺旧版本或缺扫描事实不能误报 Macro 全部新增/删除。
- [x] 每个来源 ParserResult 在单次任务中仅保留一份，规则复用 Interface/Physical/Obstruction 事实。
- [x] 共享文件 Facts 不新增完整几何对象，旧快照保留且可回读。
- [x] 真实 SRAM、多 Macro、多文件样本、受控接口变化场景均有可复现证据。
- [x] 定向测试、全量回归、编译与差异检查通过。

成熟 Reader 验证依赖仅安装在 `work/lef_reader_validation_20261016/vendor`。
接口参考：https://github.com/ruykaji/lefdef-python 。
OpenDB 对象接口参考：https://openroad.readthedocs.io/en/latest/doxygen_output/html/classodb_1_1dbMaster.html 。
当前本机无真实 UCIE IP 交付数据，不能将模拟 UCIE 验收描述为真实 UCIE 验收。

## 验收记录（2026-10-16）

本轮完成阶段 1、阶段 2 的有界实现。保留已有跨 View Binding 检查，不声称已升级 Liberty/RTL 解析器；阶段 3 的真实多 Corner/RTL 验收、阶段 4 的高级质量检查尚未完成。

### 独立 Reader 对照

| 真实交付样本 | Macro 数 | Pin 数 | 名称/Size/Class/Pin Count/接口 | RECT/PORT/OBS |
| --- | ---: | ---: | --- | --- |
| fakeram7_128x64.lef | 1 | 140 | 一致 | 一致 |
| fakeram7_64x256.lef | 1 | 523 | 一致 | 一致 |
| NangateOpenCellLibrary.macro.lef | 134 | 801 | 一致 | 存在 POLYGON，不授予完整几何结论 |

共 136 个 Macro、1464 个 Pin。Reader 为隔离安装的 `lefdef==0.6.0`，调用其 Cadence 原生 LEF Reader；不是用本项目 Parser 自证。该包装器只暴露 RECT 几何，不能据此验证 POLYGON 完整语义。

### 端到端场景

从样本复制出隔离 RAW，重新扫描，再构建两个 Effective，执行 `lef_basic`，最后回读不可变快照。

| 场景 | 核对结果 |
| --- | --- |
| 真实三文件组合，受控修改一个 SRAM 尺寸 | 1 项变化、689 项未变化、398 项不完整 |
| Pin 方向改变 | 接口变化 |
| RECT 不变但 PORT 分组改变 | 几何变化 |
| 文件长度不变但 RECT 坐标改变 | 几何变化 |
| OBS 坐标改变 | 阻挡变化 |
| 仅注释改变 | 8 项均未变化 |
| 引入 POLYGON | 几何检查不完整 |
| 文件截断 | 索引不完整，8 项均不完整 |

398 是属性检查数，不是错误文件数：接口 128、Pin Geometry 134、OBS 134、Origin 2。接口缺少显式 Direction/Use 等信息时不自动补默认值；Nangate 几何含未支持表达；两个 SRAM 没有显式 Origin。READY 只说明对象关联可用，不表示这些检查已经通过。

全部 8 个端到端场景均成功回读相同快照，受保护的 RAW/Catalog/Effective 内容指纹未改变。真实多文件诊断为亚秒级，仅为本机此规模样本、复用已扫描证据的测量（每轮具体耗时见 validation.json），不代表扫描耗时或大型工艺库性能承诺。诊断未新增 RAW 内容读取/哈希；验收脚本另外计算输入指纹以验证无修改。

### 反例驱动修复

- `PROPERTYDEFINITIONS` 内的 `MACRO width INTEGER` 曾被误当成物理 Macro；独立 Reader 对照发现后修复。
- `CLASS core` 的大小写差异曾导致对照失败；现规范化关键字，不改 Macro/Pin 名称大小写。
- PORT 未闭合、结束名错误、Pin 使用无名 END 三种反例曾错误授予完整覆盖；现均不完整。
- 仅启用物理摘要时不生成接口/几何，未生成的事实不能返回未变化。
- 仅启用 Delta 的检查方案不再误报“没有语义对象”。
- Markdown 改为变化优先、未完成项其次；未变化只汇总，并明确截断数量及完整结果位置，避免重要变化被前 100 行淹没。
- 不完整接口的结果只保存数量和最多 20 个缺属性 Pin 样例，不序列化两侧完整接口字典。
- 独立代码复核新增三个失败反例：筛选 Macro 不能丢失空文件的发现限制；确认名称映射需与 Binding 同源；缺失的所选文件不能被当作不存在同名 Macro。三例均先失败后修复，重名候选保留原始对象名。

### 复现命令与产物

以下命令在仓库根目录执行。独立 Reader 必须预先安装到上述隔离目录，它不是运行时必需依赖。

```bash
PYTHONPATH=src python3 -m unittest lib_guard.test.test_lef_check_facts -q
PYTHONPATH=work/lef_reader_validation_20261016/vendor:src python3 -m lib_guard.test.lef_review_rehearsal --out work/lef_reader_validation_20261016/acceptance
PYTHONPATH=src python3 -m unittest discover -s src/lib_guard/test -p 'test*.py' -q
python3 -m compileall -q src
git diff --check
```

最终结果：定向 20 项通过；全量 937 项通过（14.737 秒）；编译与差异检查通过。另实际执行诊断 CLI，`lef_basic` 返回码为 0，属性结果与验收脚本一致；这表示诊断执行成功，不表示所有检查完整或 IP 质量通过。独立复核确认上述三例已解决，含跨文件别名冲突与候选原始名称保留。

- 验收数据：`work/lef_reader_validation_20261016/acceptance/validation.json`，含每个场景的 Markdown 绝对路径。
- 人工摘要：各场景 `review/snapshots/<generation>/summary.md`。
- 完整属性结果：同一快照 `check_results.json`。
- 全量日志：`/tmp/ai_lib_lef_regression_final_20261016.log`。
- Reader/端到端日志：`/tmp/ai_lib_lef_acceptance_final_20261016.log`。
- 三项身份/覆盖反例修复前失败日志：`/tmp/ai_lib_lef_identity_red_20261016.log`。

未修改现有 Release Gate，未提交或推送远端；工作区原有修改保留。
