Status: current

# 有效组合表格编辑

目标用户：库管理者。判断：核对包类型、基准和组成后生成候选。输入：表格草稿；输出：现有 override 审计与 next 计划。不新增事实文件或 CLI 名称，不改 scan/diff/release 算法。

- [x] 添加 Node 回归：属性编辑使旧预览失效；按行保存成功后才预览；失败保留未保存行并停止。
- [x] app.js 复用 override 与任务日志，表格编辑包类型和对比基准；人工组成不受后台刷新替换。
- [x] index.html/styles.css 合并入口为版本配置表，保留阶段等低频维护，不重复展示类型标记与基准文本框。
- [x] 全量 unittest、JS/编译检查、浏览器实际操作；记录验证结果。

结果：786 项测试通过（12.795 秒）；JS 语法、compileall 和 diff 格式检查通过。浏览器在正式目录生成器产出的隔离库中完成包类型、对比基准修改与保存后自动预览，需补扫 0，未切换有效指针。错误返回保留待保存行，不提交后续计划。控制台无错误。

改动文件：web/static/app.js、styles.css、web/templates/index.html、test_web_ui_contract.py、basic_tutorial.md。本轮未修改后端、CLI 名称、scan/diff 算法和发布规则。
边界：批量保存按行执行，不是数据库事务；已成功行不回滚，失败行及后续草稿保留。未读取的历史版本通过“读取全部版本”补入选择列表。阶段与默认对比策略仍在低频维护区。

验证命令：PYTHONPATH=src python3 -m unittest discover -s src/lib_guard/test -p 'test*.py' -q；node --check src/lib_guard/web/static/app.js；PYTHONPATH=src python3 -m compileall -q src。
