from __future__ import annotations

from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[3]


class RepositoryCleanupTest(unittest.TestCase):
    def test_docs_have_status_header(self) -> None:
        missing: list[str] = []
        for path in (ROOT / "docs").rglob("*.md"):
            text = path.read_text(encoding="utf-8", errors="ignore")[:300]
            if "Status: current" not in text and "Status: archived" not in text:
                missing.append(path.relative_to(ROOT).as_posix())
        self.assertFalse(missing, "docs missing status header:\n" + "\n".join(missing))

    def test_current_user_facing_text_has_no_stale_workflow_copy(self) -> None:
        tokens = [
            "File Diff 2/5",
            "done/total",
            "codex-runtimes",
            "lg_effective.csh",
            "lib_guard CLI v5",
            "Build v5 HTML",
        ]
        roots = [ROOT / "README.md", ROOT / "AGENT.md", ROOT / "docs", ROOT / "scripts", ROOT / "src" / "lib_guard"]
        old_policy_name = re.compile(r"(?<!legacy_)summary_policy\.json")
        hits: list[str] = []
        for root in roots:
            paths = [root] if root.is_file() else list(root.rglob("*"))
            for path in paths:
                if not path.is_file():
                    continue
                rel = path.relative_to(ROOT).as_posix()
                if rel.startswith("docs/archive/") or "/test/" in rel:
                    continue
                if path.suffix.lower() not in {".py", ".md", ".csh", ".ps1", ".cmd"}:
                    continue
                text = path.read_text(encoding="utf-8", errors="ignore")
                for token in tokens:
                    if token in text:
                        hits.append(f"{rel}: {token}")
                if not rel.startswith("src/lib_guard/") and old_policy_name.search(text):
                    hits.append(f"{rel}: summary_policy.json")
        self.assertFalse(hits, "stale workflow copy found:\n" + "\n".join(hits))


if __name__ == "__main__":
    unittest.main()
