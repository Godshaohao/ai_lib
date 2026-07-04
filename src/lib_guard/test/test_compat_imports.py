from __future__ import annotations

import unittest


class CompatImportTest(unittest.TestCase):
    def test_scan_public_imports_use_owner_modules(self) -> None:
        from lib_guard.scan.artifacts import IntegrityBuilder, ScanStateStore, SignatureBuilder
        from lib_guard.scan.inventory import FileClassifier, FileWalker, HashManager
        from lib_guard.scan.parser_engine import ParserExecution, ParserExecutor, ParserRegistry, ParserSelector, ParserTask

        self.assertIsNotNone(IntegrityBuilder)
        self.assertIsNotNone(ScanStateStore)
        self.assertIsNotNone(SignatureBuilder)
        self.assertIsNotNone(FileClassifier)
        self.assertIsNotNone(FileWalker)
        self.assertIsNotNone(HashManager)
        self.assertIsNotNone(ParserExecution)
        self.assertIsNotNone(ParserExecutor)
        self.assertIsNotNone(ParserRegistry)
        self.assertIsNotNone(ParserSelector)
        self.assertIsNotNone(ParserTask)

    def test_scan_support_artifacts_are_not_split_into_tiny_modules(self) -> None:
        from pathlib import Path

        scan_dir = Path(__file__).resolve().parents[1] / "scan"

        for name in ["integrity.py", "signatures.py", "state.py"]:
            self.assertFalse((scan_dir / name).exists(), f"{name} should live in scan/artifacts.py")

    def test_release_readiness_owner_import(self) -> None:
        import lib_guard.summary.readiness as release_readiness

        self.assertTrue(hasattr(release_readiness, "build_release_readiness"))


if __name__ == "__main__":
    unittest.main()
