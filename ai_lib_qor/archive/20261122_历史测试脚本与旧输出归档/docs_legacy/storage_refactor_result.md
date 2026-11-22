# 精简存储与 JSON 驱动版本：实施记录

状态：部分实施，未完成规格 G0–G5；不能作为规格全部验收通过报告。

## 实际改动

- 版本解析默认只读已归档 JSON；`versions init/apply --verify-files` 才显式检查实体 RAW。选中的已确认文件位可在来源离线时更新，保留其他成员；采纳仍由人工事件决定。
- 来源证据表明文件位来自 `filename_unique_candidate` 时，未显式选择不能自动纳入有效集；Web 自动筛选会排除此类候选。旧 v1 缺旁证时尚不能可靠识别候选，仍需后续治理。
- `application/source_repository.py` 读取两种 v1 RAW / Formal 布局及 v1 evidence，比较相同 ID 的记录；相同对象去重，不同内容作为冲突而不是任选。`LibraryCatalog` / `load_catalog` 已通过它读取来源，支持没有 IP 的来源库。
- 内存 `file_history()` 在 evidence 不能证明顺序或文件位确认时输出 `ORDER_UNCONFIRMED`，不选择最新/次新；现有所有 Web 矩阵尚未改用此新方法，不能认为全系统的排序问题已经解决。

## 测试证据

- `PYTHONPATH="/tmp/ai_lib_qor_test_deps:$PWD/src:$PWD/../src" python3 -m unittest discover -s tests -q`：196 项通过（2026-11-18；如后续修改需重跑）。
- `python3 -m compileall -q src`：通过。
- 旧 `lib_guard` 的 `test_formal_inventory.py`：4 项通过。使用 unittest 运行旧库全部测试：832 项中 39 失败、33 错误（日志 `/tmp/ai_lib_guard_storage_regression.log`）；至少部分失败涉及当前工作区缺少 `pyproject.toml`、`scripts/lg.csh`、`work/single_library_smoke_20260805/lib_guard.yml` 等旧仓库文件和测试数据，另有 Web 返回 503 等现象；尚未逐项判定全部根因，不能宣称通过。当前解释器未安装 pytest，因此规格原始 pytest 命令不可用。
- 真实公开样本 `archive/20261119_历史测试输出/formal_five_library_review_0eaz9nea/work`：只读 `catalog-refresh` 得到 2 Vendor、5 库、21 Delivery、5 Formal 快照、0 IP、0 warning；不重新扫描原始来源。
- 版本离线测试使用不存在的 RAW 路径并禁止 `os.walk`，验证初始化、选中 LEF 更新、继承和人工采纳指针；实体文件校验单独测试。
- 本工作目录的 `.git` 不是可用 Git 元数据：`git status`、`git diff --check` 和 `git rev-parse HEAD` 失败；不能提供提交、分支、diff stat 或 push 结果。

## 规格验收状态

下表只对已实际覆盖的范围标 PASS，其余不推断为通过。

| 项目 | 状态与证据 |
|---|---|
| T01 | 部分：旁证合并、候选依据和原文件未修改有单元测试；指定 8 文件真实样本逐项断言未完成。 |
| T02 | 部分：旧 Formal 快照通过 v1 Schema 读取、真实五库查询；完整字段逐项核验未完成。 |
| T03–T04 | 未完成：v2 Delivery / Formal Schema、写入及消费者未实现。 |
| T05 | PASS（模拟数据）：连续 10 次同步只有一份交付记录，原地修改后发现漂移且不覆写；`test_storage_sync_idempotence.py`。 |
| T06–T08 | 部分：现有版本回归覆盖继承、选中更新和显式移除；规格中的全部具体输入未逐项重跑。 |
| T09 | 部分：新 Repository 对未知顺序不返回 latest；现有各个矩阵未统一接入。 |
| T10–T16 | 部分已有旧功能或测试；未按规格逐项验收。特别是 Formal 无 file_key 的物理来源仍受 v1 表达限制。 |
| T17 | 部分：有效版本离线构建有测试；Formal 对照、Web 和 Excel 完整离线矩阵未完成。 |
| T18 | 部分：既有有效版本/采纳回归通过，旧 Release 全量回归未完成。 |
| T19 | 部分：已有跨 Vendor 歧义回归；需对 v2 与双布局补全验证。 |
| T20–T21 | 部分：已有来源变更、失败处理测试；未按规定逐项验收。 |
| T22 | 部分：Repository 双布局相同去重与不同内容冲突有测试；未覆盖全部对象类型及写入路径。 |
| T23–T24 | 未完成：PVT 候选结构化和 MANIFEST 类别尚未实现。 |

## 重要未完成项

v2 Schema 与新记录写入；物理 RAW 关联与逻辑文件身份分离；Formal 断链原始链接文字记录；可信顺序贯穿全部查询；跨库完整 JSON-only Builder；EffectiveSet 顶层布局；CLI/Web/Excel 统一查询改造；24 项完整验收；全量 `lib_guard` 回归；Git 分支和提交。这些不能用已通过的局部测试代替。
