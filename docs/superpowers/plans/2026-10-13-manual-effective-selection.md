Status: current

# 人工选择有效组合实施计划

**目标：** 完整包单选、增量包多选和顺序调整贯通预览、执行、覆盖核对与确认生效。

**架构：** 扩展现有 next/intake 输入为 base_full + ordered includes。显式选择优先于推荐，候选标识包含组成指纹。复用现有 manifest、compare、plan 和 accept 校验，不增加工作流或事实来源。

**边界：** 不修改 discover、parser、release；候选不自动生效、不自动发布；只补缺失扫描证据。界面使用中文，桌面表格、单选与勾选组件。

## 任务与验收

- [x] Resolver 测试先行：旧完整包人工选中不会被最新完整包替换；有序增量包、未勾选排除、完整包单独组合、非法/重复/跨库版本拒绝；自动流程不变。
- [x] 扩展 resolver 和 next/intake 参数传播，候选标识区分组成及顺序；已保存人工选择不被后台推荐替换。
- [x] Web 选择编辑器：单选完整包、勾选增量、上移下移、显示来源；预览与执行使用同一选择；更改后清除旧预览并阻止误确认旧候选。
- [x] Web/CLI 联动测试；隔离真实文件组合试验：预览不写、只补缺失扫描、组成/覆盖顺序可核对、当前指针与发布链接不变。
- [x] 全量 unittest、compileall、JS 检查、浏览器点击回归；记录实际结果，不用评分替代证据。

## 实际核对

- 最终全量回归：785 项 unittest 通过（22.815 秒）；compileall、node --check、git diff --check 均通过。日志：/tmp/ai_lib_manual_effective_final_acceptance.log。
- 浏览器验证包含完整选择、顺序调整、失效预览阻止执行、候选生成、覆盖报告、确认生效和重新读取；真实工作区只读核对，无控制台错误。

- 真实文件模拟：完整包含 a.v/b.v，FIX 替换 a.v；结果保留 b.v，a.v 来源为 FIX。
- 两个补丁重复覆盖 a.v：记录叠加顺序，最终文件来自最后一个补丁；现有重复覆盖冲突规则保留，accept 拒绝，当前指针不变。
- Web：单选、勾选、调序、预览、执行、报告和确认已实际使用；重开恢复组成，重复预览需补扫 0。
- 预览/执行快照同时包含扫描策略；更改勾选或顺序使旧预览失效。
- 候选确认新增 expected-effective-id，防止确认时替换为他人候选。已有指针修订号与证据校验保持不变。
- 选择表最大高度 280px、顺序表最大高度 200px；全部版本按需读取，不自动扫描历史。

修改范围：window/resolver.py、window/cli.py、short_cli.py、web/app.py、web/read_model.py、Web 模板/JS/CSS，及对应回归测试和教程。
未修改：discover、catalog 资产事实、scan/parser、diff 算法、release/link 规则、静态审查门禁。
已知边界：这是单库 FULL+增量组合，不是跨库任意混合；未执行真实工作区确认或发布，写操作使用隔离模拟库。
