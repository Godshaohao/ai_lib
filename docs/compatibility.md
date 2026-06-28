Status: current

# 兼容层说明

兼容 wrapper 只用于让旧 import 或旧生成物继续可运行。新产品逻辑不应继续
写入兼容模块。

每个兼容项都需要说明：

- 当前状态
- 替代路径
- 保留原因
- 删除条件
- 测试覆盖

## Import Wrapper

| 模块 | 状态 | 替代路径 | 删除条件 | 测试覆盖 |
| --- | --- | --- | --- | --- |
| `lib_guard.scan.file_walker` | 兼容 wrapper | `lib_guard.scan.inventory.FileWalker` | 下游 import 迁移后 | `test_compat_imports` |
| `lib_guard.scan.file_classifier` | 兼容 wrapper | `lib_guard.scan.inventory.FileClassifier` | 下游 import 迁移后 | `test_compat_imports` |
| `lib_guard.scan.hashing` | 兼容 wrapper | `lib_guard.scan.inventory.HashManager` | 下游 import 迁移后 | `test_compat_imports` |
| `lib_guard.scan.parser_registry` | 兼容 wrapper | `lib_guard.scan.parser_engine.ParserRegistry` | 下游 import 迁移后 | `test_compat_imports` |
| `lib_guard.scan.parser_executor` | 兼容 wrapper | `lib_guard.scan.parser_engine.ParserExecutor` | 下游 import 迁移后 | `test_compat_imports` |
| `lib_guard.scan.selector` | 兼容 wrapper | `lib_guard.scan.parser_engine.ParserSelector` | 下游 import 迁移后 | `test_compat_imports` |
| `lib_guard.release.readiness` | 兼容 wrapper | `lib_guard.summary.readiness` | 下游 import 迁移后 | `test_compat_imports` |

## Console 兼容

`src/lib_guard/render/control_console.py` 保留为旧 review-console 链接和 JSON
消费者的兼容导出。当前用户路线是：

```text
Catalog HTML -> Library Workspace -> Version Review
```

## 历史说明

历史迁移文档保留在 `docs/archive/`。当前文档不应依赖 archive 里的旧指令。
