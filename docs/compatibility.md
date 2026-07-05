Status: current

# 兼容层说明

兼容 wrapper 只用于让旧生成物继续可运行。新产品逻辑不应继续写入兼容
模块；一行 import wrapper 已经移除，调用方必须使用 owner module。

每个兼容项都需要说明：

- 当前状态
- 替代路径
- 保留原因
- 删除条件
- 测试覆盖

## 已移除 Import Wrapper

| 旧模块 | 状态 | 替代路径 | 测试覆盖 |
| --- | --- | --- | --- |
| `lib_guard.scan.file_walker` | 已移除 | `lib_guard.scan.inventory.FileWalker` | `test_repository_cleanup`, `test_compat_imports` |
| `lib_guard.scan.file_classifier` | 已移除 | `lib_guard.scan.inventory.FileClassifier` | `test_repository_cleanup`, `test_compat_imports` |
| `lib_guard.scan.hashing` | 已移除 | `lib_guard.scan.inventory.HashManager` | `test_repository_cleanup`, `test_compat_imports` |
| `lib_guard.scan.parser_registry` | 已移除 | `lib_guard.scan.parser_engine.ParserRegistry` | `test_repository_cleanup`, `test_compat_imports` |
| `lib_guard.scan.parser_executor` | 已移除 | `lib_guard.scan.parser_engine.ParserExecutor` | `test_repository_cleanup`, `test_compat_imports` |
| `lib_guard.scan.selector` | 已移除 | `lib_guard.scan.parser_engine.ParserSelector` | `test_repository_cleanup`, `test_compat_imports` |
| `lib_guard.release.readiness` | 已移除 | `lib_guard.summary.readiness` | `test_repository_cleanup`, `test_compat_imports` |
| `lib_guard.render.diff_report` | 已移除 | `lib_guard.render.html_report.render_diff_html` | `test_repository_cleanup` |

`summary/builders/*_summary.py` 这种一行重导出模块也已移除。summary builder
统一从 `lib_guard.summary.builders` 或 `lib_guard.summary.builders.base` 导入。

## 已移除 Console 兼容

旧 `console build/config/review` 和 `render/control_console.py`、`render/control_data.py`
已经移除。当前用户路线是：

```text
Catalog HTML -> Library Workspace -> Version Review
```

## 历史说明

历史迁移文档不再作为当前仓库内容维护。当前文档不应依赖旧迁移说明里的指令。
