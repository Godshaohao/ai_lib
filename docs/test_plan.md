Status: current

# 测试计划

## 基础回归

每轮代码或文档整理后至少跑：

```bash
PYTHONPATH=src python3 -m compileall -q src
PYTHONPATH=src python3 -m unittest discover -s src/lib_guard/test -p "test*.py" -q
PYTHONPATH=src python3 -m lib_guard.cli --help
PYTHONPATH=src python3 -m lib_guard.short_cli --help
scripts/lg.csh --help
```

## 按变更类型加测

| 修改范围 | 额外检查 |
| --- | --- |
| Renderer / HTML | 在 `work/` 下重新生成 catalog，手动检查 HTML |
| Review Gate | 跑 `src.lib_guard.test.test_review_gate` |
| Release Gate / symlink release | 做一次 `rel --explain` 和 dry-run/preview |
| Scan/parser | 跑 scan pipeline 相关测试，并用小 fixture 重扫 |
| Diff/lane | 跑 scan diff、pairwise 和 Version Detail 相关测试 |
| 文档整理 | 跑 repository cleanup 测试，确认没有旧流程入口 |

## Version Detail 投影回归

Version Detail 是唯一审查投影。涉及 scan、compare、intake、accept-window、
mark 或 update-detail 的修改，必须额外跑：

```bash
PYTHONPATH=src python3 -m unittest \
  src.lib_guard.test.test_version_detail_review_context \
  src.lib_guard.test.test_render_impact \
  src.lib_guard.test.test_window_intake \
  src.lib_guard.test.test_version_detail_report -q
```

这组测试锁定：

- `VersionDetailReviewContext` 是否正确识别 pending window、candidate effective、
  compare manifest 和 freshness。
- scan、batch scan、compare、batch compare、intake、accept-window、mark 是否通过
  Render Impact 刷新受影响的 Version Detail，而不是全量或裸刷新。
- Version Detail 第一屏是否仍按“接入判断、审查对象、对比上下文、View 变化、证据状态”
  五组信息展示。

复杂度边界：

- 单版本 scan / compare 只刷新当前库当前版本投影。
- batch scan / compare 按成功版本集合刷新，复杂度为 O(K)。
- intake / accept-window 按 review window 内版本集合刷新，复杂度为 O(W)。
- 全 catalog render 只作为显式 catalog 页面刷新或低频重建动作。

## 文档守卫

`src/lib_guard/test/test_repository_cleanup.py` 会检查：

- 当前文档都有 `Status: current`。
- README 不再膨胀成完整教程。
- 当前文档索引只指向保留文档。
- 旧 workflow、旧命令入口、旧迁移说明不会重新出现在用户主路径。

这组测试是文档清理的防回潮护栏。
