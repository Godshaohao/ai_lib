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

## 文档守卫

`src/lib_guard/test/test_repository_cleanup.py` 会检查：

- 当前文档都有 `Status: current`。
- README 不再膨胀成完整教程。
- 当前文档索引只指向保留文档。
- 旧 workflow、旧命令入口、旧迁移说明不会重新出现在用户主路径。

这组测试是文档清理的防回潮护栏。
