# 第三方 IP 入库与正式 NL 目录检查矩阵

Status: current

日期：2026-10-23
范围：按当前仓库代码与自动化测试梳理已有检查；不代表本次读取或验收了内网生产库。

## 测试结论

| 检查项 | 本次结果 | 证据 |
| --- | --- | --- |
| 全量 Python 单元测试 | 通过，1198 项 | `/tmp/ai_lib_formal_ip_regression_20261023.log` |
| 正式 NL 链接脚本专项 | 31 项通过；覆盖目录发现、原始版本自然排序、50 版本模拟、路径与来源盘点、最新/次新清单比较、Corner/RC 统计、LIB/DB 配对 | `repo/src/lib_guard/test/test_formal_nl_link_discovery.py` |
| 本次可见报告演练 | 通过；单阶段 `lib_NL2.10_0/IP` 输入，输出 Markdown 和 JSON，盘点状态 `COMPLETE` | [单阶段 Markdown 报告](/tmp/ai_lib_formal_nl_acceptance_20261023/scoped_nl_ip.md)、[JSON 数据](/tmp/ai_lib_formal_nl_acceptance_20261023/scoped_nl_ip.json) |
| 真实内网目录验收 | 本次未执行 | 样例为临时构造的受控目录，不应解读为生产目录结果 |

正式 NL 脚本按一次配置核查一个阶段；`lib_NL2.5_3/IP` 中的 `2.5_3` 只标识阶段，不用于判断新旧。原始版本新旧按 `library.root` 下的版本目录名数字字段排序，报告比较原始最新与次新两份目录的相对路径清单、各 View 数量，并显示正式阶段实际引用的原始版本。受控样例报告得到最新 `v02`、次新 `v01`，正式阶段引用 `v02` 的 7 条路径；两份清单共有 5 个相对路径，`v02` 独有 2 个。该比较不读取内容、不计算 Hash，因此不声称同路径文件内容一致，也不证明目录名对应完整包或有效版。

## 第三方 IP 入库检查

| 类别 | 当前实现检查什么 | 结果如何使用 | 覆盖与限制 | 主要测试证据 |
| --- | --- | --- | --- | --- |
| 库发现与登记 | 从指定根目录发现候选库/版本；支持单版本候选；登记后更新 Catalog | 形成可管理的库、版本和源路径记录 | 发现结果不等于技术验收；目录命名不典型或权限不足时需修正路径/识别 | `test_intake_permission_first_release.py`、`test_formal_inventory.py` |
| 路径与权限 | 检查根目录可读、遍历及链接读取异常；把权限错误留在任务结果 | 阻止把不可读目录当成空库或成功扫描 | 依赖运行 Web/CLI 的系统账号权限；没有替代访问权限的机制 | `test_intake_permission_first_release.py` |
| 文件清单与类型归类 | 遍历版本文件并按后缀/目录识别 LEF、LIB、DB、GDS、CDL、Verilog 等 | 生成 Scan inventory，显示每类文件及数量 | 类型识别是文件路径/后缀分类；不能证明文件可被 EDA 工具使用 | `test_scan_pipeline.py` |
| 包类型与版本关系 | 识别/人工修正 FULL、PARTIAL、HOTFIX、DOC 等包类型；建立基准、前序有效版和叠加关系 | 决定本包与已有 FULL/Effective 的组合语义 | UNKNOWN 或错误标注应由操作者确认；不应把 PARTIAL 未携带视图直接视为最终组合缺失 | `test_window_intake.py`、`test_partial_delivery_projection.py` |
| Scan 与解析证据 | 对配置要求的视图检查逐文件扫描/Parser 状态、结果文件存在性和路径范围 | Readiness 展示通过、阻塞、缺证据；按文件留证 | 必需 View/Mode/Corner 由策略决定；默认策略不是所有 IP 的完整合同 | `test_delivery_requirements.py`、`test_scan_pipeline.py` |
| 版本文件对比 | 对照扫描清单；使用路径、归一化关系及已有内容证据识别变化、删除、未验证等 | 支撑版本变化矩阵与审查定位 | 内容证据不足时保留未验证；不同打包目录造成的路径差异不保证都能语义配对 | `test_scan_pipeline.py` |
| LEF 独立核查 | 两个指定 LEF 的字节摘要与可解析事实；Macro、Class、尺寸、Site、Pin/方向/用途/层、几何/OBS 等统计和差异 | 产生独立提取事实与问答式报告 | 只覆盖所选文件和解析支持的语法；不是全库发布放行 | `test_lef_review.py` |
| LEF–Liberty 联动 | 读取 LEF 核查报告和逐个 LIB/LIB.GZ；比对 Cell/Macro 名、信号 Pin、PG Pin；记录 Corner/PVT 标签及解析覆盖 | 定位对象覆盖差异、Pin/电源脚差异和证据不足 | 各 Corner 独立核查；文件名/PVT 标签不代表完整时序等价；不自动合并 Corner | `test_lef_liberty_check.py` |
| Effective 组合技术检查 | 将 FULL 与有序增量组合后检查继承视图、对象/接口变化和来源 | 判断检查对象是组合而非孤立增量包 | 无可信组合或证据不足时显示待核对；建议性检查不替代正式 Release Gate | `test_semantic_effective.py`、`test_semantic_checks.py` |
| Review / Release Gate | Readiness、Diff、Review Gate 与正式发布规则分层判定 | 技术审查建议和正式放行结论保持区分 | 本矩阵不宣称所有检查自动覆盖真实 IP 的业务合同；正式门禁行为另有专门回归 | `test_partial_delivery_projection.py`、`test_delivery_requirements.py`、`test_release_decoupled_review.py`、`test_release_levels.py` |

## 正式 NL 目录检查

| 类别 | 当前实现检查什么 | 可回答的问题 | 明确不回答什么 | 主要测试证据 |
| --- | --- | --- | --- | --- |
| 正式根目录与入口 | 只读正式根目录；读取 `current/latest` 等入口状态；识别断链或目标不是 `lib_NL*` | 正式根目录是否可读、入口指向是否有效、包含多少正式包 | 不据此证明版本经过审批或是系统 Effective Pointer | `test_formal_directory_audit.py`、`test_formal_inventory.py` |
| 正式包/视图文件统计 | 按正式包和视图目录遍历文件/链接，统计 LEF、LIB、DB、GDS、CDL、Verilog 等数量；输出未知类型/视图和附属内容 | 每个正式包当前可见哪些类型、各有多少路径；哪些路径无法识别/链接失效 | 不配置“必需视图”门槛；0 只是未看到该类型，不自动判缺失 | `test_formal_directory_audit.py` |
| 指定正式阶段与 IP 文件链接 | 根直接指向一个 `lib_NL<阶段号>/IP`；按配置的 IP 原始根过滤链接目标并盘点该阶段 | 查看指定阶段中的文件清单、View 数量、其链接使用的原始版本，以及原始版本新旧参考 | `2.5_3` 是阶段编号，不用于新旧排序；不做正式阶段之间比较，也不判断 Effective/Current。多阶段扫描仅保留兼容回归路径，不是正式目录的实际模型 | `test_formal_nl_link_discovery.py` |
| 原始版本最新/次新参考 | 对配置原始 IP 根下的直接版本目录名按数字字段自然降序；仅盘点正式链接引用的版本及原始最新两份 | 当前正式阶段引用的是较新还是较旧的原始版本；最新与次新目录各有哪些 View、路径清单增减 | 目录名只是排序依据，不证明完整包、审批或有效状态；相对路径相同不代表内容相同；不计算 Hash | `test_formal_nl_link_discovery.py` |
| 原始来源追溯 | 解析正式文件链接目标，并与原始 IP 根下的直接版本目录对应；分别统计可见路径和去重来源 | 正式文件来自哪个原始版本；最新原始来源中哪些路径被本阶段采用；被引用源目录还有哪些路径未链接 | 未引用不等于交付遗漏；路径清单比较不等于文件内容差异 | `test_formal_nl_link_discovery.py` |
| 指定阶段 View 数量 | 统计选定阶段各 View 文件路径数，空类型显式为 0 | 查看这个阶段有哪些类型、各有多少路径 | 不判断该库应当包含哪些类型；0 不自动等于交付缺失 | `test_formal_nl_link_discovery.py` |
| LIB/DB Corner 文件名统计 | 从 LIB/DB 文件名识别 TT/SS/FF/SF/FS 等标签；按完整去扩展名文件名配对；单列未识别/冲突 | LIB、DB 文件名中出现了哪些角标；哪些有同名配对或只有一侧 | 仅是名称线索，不解析文件内容，不证明内部 Corner、cell 覆盖或可用性；单侧文件不是自动错误 | `test_formal_nl_link_discovery.py` |
| RC 标签统计 | 从文件名识别 SIGRCMIN/SIGRCMAX，并按 LIB/DB 统计 | 链接名称标注了哪些 RC 标签 | 未标注不代表没有 RC 条件；不解析 RC 内容 | `test_formal_nl_link_discovery.py` |
| 原始来源与未链接文件 | 对该阶段引用的原始版本统计来源路径与未被链接的文件 | 查看正式阶段从哪些原始版本取文件、原始目录还有哪些文件未被选入 | 未链接不等于交付遗漏；本脚本不跨正式阶段比较 | `test_formal_nl_link_discovery.py` |
| 报告与图表数据 | 输出人类可读 Markdown 和结构化 JSON，提供逐文件绝对路径、旧新来源、统计单位/范围和 chart rows | 查看结论、追溯文件、后续按版本/View绘图 | `COMPLETE` 表示目录遍历和来源映射完成，不是 IP 质量 PASS 或发布许可 | 本次受控运行报告及该专项测试 |

## 状态词的解释

| 显示状态/现象 | 正确解释 |
| --- | --- |
| `COMPLETE`（正式 NL 报告） | 指本报告所选 link/目录可遍历、来源映射符合脚本条件；不代表交付完整、质量合格或正式放行 |
| 某 View 数量为 `0` | 已盘点的正式目录没有识别到此类文件；是否缺失由 IP 自身交付要求决定 |
| `LIB_ONLY` / `DB_ONLY` | 文件名配对规则只找到一侧；供核对命名和交付范围，不自动判错 |
| Corner `TT/SS/FF` | 由文件名识别出的标签，不是读取 `.lib/.db` 内部条件后的结论 |
| `source_updated` | 同一个正式相对路径的链接目标绝对路径改变，不代表文件字节改变 |
| `NOT_SCANNED` 原始版本 | 本次正式目录未引用该原始版本，因此没有盘点其文件清单；不是空目录 |
| Readiness `PASS/BLOCKED` | 对应当前配置的交付规则及证据状态；不能外推为所有库类型共用的完整合同 |

## 当前应明确保留的边界

1. 第三方入库侧可以做技术文件解析和 LEF–Liberty 对象级核对；正式 NL 脚本只读路径、链接、文件类型、名称标签及数量，不重复 Macro 粒度解析。
2. 正式目录的“有没有某种类型”和“数量多少”可由 link 清单回答；“是否缺必需交付”必须由具体 IP 的交付要求定义，本脚本不擅自推断。
3. Corner 当前由正式链接文件名统计；这是目录管理信息，不是 Liberty/DB 内部语义验证。
4. 两套报告职责不同：入库检查解释源库的扫描/技术证据；正式目录检查解释当前正式树的构成、来源和路径变化。正式目录检查不替代入库技术检查，也不改变正式 Release Gate。
5. 本次受控演练仅验证脚本和报告链路。生产环境权限、命名例外、实际 IP 交付合同仍需用真实路径单独验收。

## 相关代码入口

- 入库 Readiness：`repo/src/lib_guard/summary/readiness.py`
- Scan/Diff：`repo/src/lib_guard/scan/`、`repo/src/lib_guard/diff/scan_diff.py`
- LEF 独立核查：`repo/scripts/lef_review.py`
- LEF–Liberty 联动核查：`repo/scripts/lef_liberty_check.py`
- 正式目录盘点：`repo/src/lib_guard/release/inventory.py`
- 正式 NL IP/link 追踪：`repo/scripts/effective_file_tracker.py`
