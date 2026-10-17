Status: current

# 现有库技术检查缺口修复计划

**Goal:** 修复真实 ASAP7 技术 LEF 误判，并让人工确认的上下文与绑定配置真正进入 CLI/Web 报告。

**Architecture:** 保留 Facts → 按需 Model → Rules → Results。引号感知的语句迭代器只修正 LEF 输入边界；人工上下文在任务 Model 阶段附加，不污染缓存 Facts、扫描事实或有效组合。Web 冻结服务端配置和映射，仍只交付文件。

**Tech Stack:** Python 标准库、现有 unittest、Flask 和后台 Job。

## 边界

- 使用现有分支和未提交改动；不提交、不推送，不改变 Release Gate。
- 不增加完整哈希，不自动补扫，不把旧 ParserResults 标成新版。
- 不模糊匹配、不静默选角、不将缺少视图当相同。
- 真实验收补取 LEF 写入新的隔离扫描；原 Liberty/RTL 证据可以复用，但不得伪造其覆盖声明。

## 任务与检查项

### 1. LEF 输入边界（已完成）

- [x] 先增加失败测试：带引号分号/井号、同一行多个分号语句、转义与未闭合字符串、真实技术 LEF。
- [x] 运行 `PYTHONPATH=src python3 -m unittest lib_guard.test.test_lef_check_facts -q`，保留 RED 证据。
- [x] `scan/parsers/lef.py` 增加保留行号的引号/注释感知语句边界，更新解析器版本；不扩大 RECT 几何能力声明。
- [x] 同组测试 GREEN；tech LEF 的层信息与独立清点相符，不包含 Macro 时保留空对象而非发明对象。

### 2. 已确认上下文与绑定（已完成）

- [x] 在 `test_semantic_profile.py` 增加失败测试：confirmed/basis、文件路径范围、Corner/Mode、冲突、未命中、旧事实不变。
- [x] 使用现有 mapping JSON 增加 `file_contexts`，在 `binding.py` / `profile.py` 的模型选择前应用；只接受显式已确认的配置。
- [x] 保留精确对象名和既有 macro_aliases，不通过自动降级 required_views 掩盖缺失视图。

### 3. Web 配置接线（已完成）

- [x] 在 `test_web_semantic_review.py` 锁定工作区检查配置路径和映射冻结、错误配置不产生任务、跨库配置不能串用。
- [x] 工作区可选 `semantic_review_config`；检查配置按库指定 mapping 路径；复用现有 profile/rules 选择，不新增入口。
- [x] 客户端仍不能提交任意脚本/路径；任务复制配置与映射，运行中源配置变化不影响已提交选择。

### 实测发现的上游解析问题（已修复并完成最终回归）

- [x] Liberty 原解析器未维护未知嵌套组，真实 NLDM 文件 cell_count=0。增加保留引号/注释边界的组栈，提取标量 pin/pg_pin，旧缓存通过版本号隔离。
- [x] Verilog 原声明应用到所有同名端口，且 ANSI 继承错误。修复 module 作用域、常量范围、简单 ANSI 声明。
- [x] 区分 module 接口条件编译与文件中独立 UDP 的条件编译；不推断展开结果，不忽略真正受宏控制的端口。
- [x] 真实 INVBUF 中缺分号的 area 语句吞掉 pg_pin 组，不得误报 PG_ROLE_MISMATCH；记录输入语法行号并保留未检查。
- [x] 已确认新增对象只报告 presence 新增，不生成其余七条无旧对象的伪“不完整”；无基准/不完整发现的保护不变。
- [x] Markdown 写入输入证据限制、实际对象名；输出仍仅文件，不投影到 Web/详情正文。

### 4. 真实库与回归

- [x] 新隔离目录补取 LEF，复用上一轮非 LEF 扫描证据；不覆盖原取证目录。
- [x] 默认全 LEF 范围重跑，区分共有、真实新增、不完整；与选定 3 文件结果对照。
- [x] 根据实际对象、工艺角和视图文件设置显式配置，重跑跨视图关联；真实缺失和旧解析器覆盖缺口逐项报告，不伪造 PASS。
- [x] API/真实 Web 子进程提交、下载与配置快照校验；浏览器回归与截图。
- [x] 全量 unittest、compileall、JS 语法、git diff --check；记录具体数量、失败案例、耗时和剩余限制。

最终验收说明见 [findings.md](/home/polaris/proj/mx/ai_lib/repo/work/web_existing_acceptance_20261016/findings.md)。

本阶段的结论是“软件链路通过、真实数据仍有明确未通过项”，不是“全库质量通过”。

完整验收不是“所有规则 PASS”：真实不一致应为 FAIL，缺少资料必须明确未检查；不能以成功退出码证明可放行。
