# ai_lib_steward 本地整理记录 · 2026-11-18

## 范围与依据

- 核对本地 `ai_lib_qor/src`、`schemas`、相关测试及 CLI/Catalog 文档；没有扫描或修改真实 RAW、Formal NL 与业务历史。
- 当前环境中的项目目录未被 Git 识别为工作树；无法确认分支、HEAD、差异或是否存在未提交修改。
- 旧包所引 GitHub `97acef8` 是历史参考，不代表当前本地实现。

## 结果

| 项目 | 结果与证据 |
| --- | --- |
| Skill 包完整性 | 包自检通过；5 项 Skill 工具测试通过。 |
| 静态结构巡检 | 扫描 56 个 Python 文件；提示 `application/pipeline.py` 和 `application/runs.py` 的 `argparse`/`Namespace` 耦合，以及来源发现和 Formal 同步中的 `lib_guard` 直接导入。启发式提示不等于缺陷已复现。 |
| 项目自动化回归 | 169 项通过；使用项目 `src`、同级 `src` 和 `/tmp/ai_lib_qor_test_deps` 中的 Excel 测试依赖。是指定环境中的自动化结果，不是生产验收。 |
| 查询一致性 | 本次只核对代码和已有测试入口，没有独立证明所有 Web / Excel 对同一 Run 的展示完全一致。 |
| 真实库与部署 | 未对真实 RAW/Formal 数据、HPC/NFS、并发锁、生产规模性能和恢复流程做验收。 |

项目架构、生产者/消费者与优先处理问题见 [architecture-steward.md](architecture-steward.md)。共享数据原则与查询投影选型分别见 [ADR-0001](decisions/ADR-0001-shared-data-catalog.md) 和 [ADR-0002](decisions/ADR-0002-persistent-projection-choice.md)。

## 后续建议

1. 用同一 IP、Rev、Run 的样例，对照 Web、单版本 Excel 和整体 Excel 的来源及检查范围。
2. 将应用服务与 CLI 参数对象解耦，回归 CLI / Web 对相同输入的行为一致性。
3. 在确认业务规则后测试候选父版本、跨库 IP 归属，以及 RAW 原地修改时的可追溯边界。
4. 使用代表性数据测量 Catalog 查询耗时；只有确认瓶颈后再选择缓存或持久投影。
