from __future__ import annotations

import unittest


class CompatImportTest(unittest.TestCase):
    def test_scan_compat_imports(self) -> None:
        from lib_guard.scan.file_classifier import FileClassifier
        from lib_guard.scan.file_walker import FileWalker
        from lib_guard.scan.hashing import HashManager
        from lib_guard.scan.parser_executor import ParserExecution, ParserExecutor
        from lib_guard.scan.parser_registry import ParserRegistry
        from lib_guard.scan.selector import ParserSelector, ParserTask

        self.assertIsNotNone(FileClassifier)
        self.assertIsNotNone(FileWalker)
        self.assertIsNotNone(HashManager)
        self.assertIsNotNone(ParserExecution)
        self.assertIsNotNone(ParserExecutor)
        self.assertIsNotNone(ParserRegistry)
        self.assertIsNotNone(ParserSelector)
        self.assertIsNotNone(ParserTask)

    def test_release_readiness_compat_import(self) -> None:
        import lib_guard.release.readiness as release_readiness

        self.assertTrue(hasattr(release_readiness, "build_release_readiness"))


if __name__ == "__main__":
    unittest.main()
