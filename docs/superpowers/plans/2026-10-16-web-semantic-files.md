Status: current

# Web 执行技术检查，仅生成报告文件

目标使用者：已生成有效组合的库管理者。
主判断：明确选择当前/候选/已保存组合、可选基准及规则，并能找到本次报告。
输入：服务端登记的有效组合、已有扫描证据、configs/semantic_review.json 中的检查方案。
输出：既有 Web Job 状态/日志、独立任务目录中的 Markdown/JSON 文件及下载入口。
禁止：新报告页面、检查结果正文投影到 Web/版本详情、自动补扫、切换有效指针、发布或改变 Release Gate。

采用既有后台任务调用 semantic.cli；不新建执行服务。选择提交时复制成任务输入，规则写入任务配置，不修改全局配置。Web 仅允许已登记组合，不接收任意绝对路径或 shell 参数。

## 实施与检查项

- [x] TDD：GET 返回本库有效组合及配置方案；POST 原先缺失的接口需从 404 变成可执行任务。
- [x] 接线：白名单仅新增 semantic-review；复用现有 Job 启动/轮询与 artifact 下载。
- [x] 输入：目标必选、基准可空、不能选择同一组合；规则限于配置方案，拒绝任意路径与未知参数。
- [x] 固定输入：记录提交时的目标/基准清单与实际规则；不改 configs/semantic_review.json。
- [x] UI：有效组合区域中显示目标/基准/方案/规则勾选；忙碌、空组合、切换库、请求失败有明确状态。
- [x] 报告：保存 Markdown/JSON，可下载；界面不嵌入正文或新增技术判断。
- [x] 端到端：通过 Web 实际启动子进程，报告可读、无基准不误报全部新增、缺证据不补扫。
- [x] 边界：原始输入、有效指针、现有 HTML 和发布目录不被修改。
- [x] 浏览器：点击、规则选择、任务完成、文件入口回归与截图。
- [x] 定向/全量测试、编译、JavaScript 语法及 diff 检查。

验证命令：

```bash
PYTHONPATH=src python3 -m unittest lib_guard.test.test_web_semantic_review lib_guard.test.test_web_ui_contract lib_guard.test.test_architecture_invariants -q
PYTHONPATH=src python3 -m unittest discover -s src/lib_guard/test -p 'test*.py' -q
python3 -m compileall -q src
node --check src/lib_guard/web/static/app.js
git diff --check
```

工作区已有未提交修改，禁止顺带提交或推送。

## 验收证据

- 新增 Web 定向测试 9 项通过；Web/UI/架构约束联合 57 项通过；全量回归 946 项通过（16.100 秒）。
- 初始接口未接入时的 RED：`/tmp/ai_lib_web_semantic_red_20261016.log`。
- 全量日志：`/tmp/ai_lib_web_semantic_full_20261016.log`；编译、JS 语法、diff 检查通过。
- 实际浏览器：隔离配置 `work/web_semantic_review_20261016/lib_guard.yml`，地址 `http://127.0.0.1:5071/?library=demo`。
- 1440×1000 桌面验证截图：`work/web_semantic_review_20261016/desktop-review.jpg`。
- 浏览器先仅勾选接口规则，刷新选项仍保持选择；任务 `semantic-review_fe8cfbec399a` 确认 1 项接口变化。
- 无基准任务 `semantic-review_986d2d201a80`：接口变化为 INCOMPLETE，不伪报新增。
- 完整 LEF 规则任务 `semantic-review_c3a8eac59972`：1 项接口变化、7 项未变化；三次均未额外读取/哈希 RAW。
- 浏览器实际下载 Markdown 和 JSON；修复最初 target=_blank 导致无法在原标签捕获下载的问题，语义任务产物改为 download 属性并返回 attachment，其他 HTML 产物仍保持原行为。
- 缺证据测试同时去掉分片和现有 aggregate，报告未检查/不完整；只缺分片时存在合法 aggregate 可复用，不应误判成无证据。
- 独立复核发现并修复“当前指针记录不一致仍默认选作基准”，新反例先失败后通过；只禁用不一致的组合，不新增发布阻塞。
- 原始输入与当前指针的内容指纹测试保持一致；无新增报告页/正文、自动补扫、有效版确认、发布或 Release Gate 变更。

修改模块：`web/semantic_actions.py` 负责固定选择和配置；`web/app.py` 仅接线任务、状态和文件下载；
`project_config.py` 只新增一个明确动作；现有模板/JS 增加执行控件；检查算法与报告引擎保持原样。

## 现有库补充验收（2026-10-16）

- 不是只用合成 M 样例：选取已有 ASAP7 的 20260624 / 20260627 两个真实测试交付，分别 33 / 205 个文件。
- 复用旧扫描、显式隔离取证分开验证；隔离扫描分别 31.880 / 97.635 秒，哈希文件均为 0；报告任务不自行补扫。
- 6 项 API/真实子进程场景完成；实际浏览器另执行 LEF / 跨视图两个任务，Markdown 和 JSON 下载内容与快照一致，无浏览器 warn/error。
- 全库 LEF 仍为 INCOMPLETE：技术 LEF 多语句超出覆盖，不能证明对象发现完整；跨视图还需明确范围、角与绑定。执行成功不是质量通过。
- 既有 CLI 明确限定 3 份共同 LEF 时，636 个对象的 5,088 项属性未变化；未将外层目录改名误判为新增。该结果不覆盖其余文件，不冒称 Web 已支持范围编辑。
- 全量回归重新执行：946 项通过（最近一次 15.671 秒，日志位于本次验收目录 `regression.log`）；compileall、JS 语法及 diff 检查通过。
- 输出与逐项检查：`work/web_existing_library_20261016/findings.md`、`validation.json`、`validation.md`；浏览器截图 `browser-existing-library.jpg`。
- 原始 357 个文件大小/mtime 与源 Catalog 内容校验不变；未改变 Release Gate、当前有效指针或发布，不推送远端。
- 可重复验收脚本：`src/lib_guard/test/web_existing_rehearsal.py`；明确只支持本次已有两完整包场景，不自动猜测增量组成。
