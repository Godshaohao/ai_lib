Status: current

# Compatibility Manifest

These modules are compatibility wrappers kept for old imports. Do not add new
product logic here.

| Module | Status | Replacement | Remove after | Test coverage |
| --- | --- | --- | --- | --- |
| `lib_guard.scan.file_walker` | compatibility wrapper | `lib_guard.scan.inventory.FileWalker` | after downstream imports migrate | `test_compat_imports` |
| `lib_guard.scan.file_classifier` | compatibility wrapper | `lib_guard.scan.inventory.FileClassifier` | after downstream imports migrate | `test_compat_imports` |
| `lib_guard.scan.hashing` | compatibility wrapper | `lib_guard.scan.inventory.HashManager` | after downstream imports migrate | `test_compat_imports` |
| `lib_guard.scan.parser_registry` | compatibility wrapper | `lib_guard.scan.parser_engine.ParserRegistry` | after downstream imports migrate | `test_compat_imports` |
| `lib_guard.scan.parser_executor` | compatibility wrapper | `lib_guard.scan.parser_engine.ParserExecutor` | after downstream imports migrate | `test_compat_imports` |
| `lib_guard.scan.selector` | compatibility wrapper | `lib_guard.scan.parser_engine.ParserSelector` | after downstream imports migrate | `test_compat_imports` |
| `lib_guard.release.readiness` | compatibility wrapper | `lib_guard.summary.readiness` | after downstream imports migrate | `test_compat_imports` |

