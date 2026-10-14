from __future__ import annotations

import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path


class ReviewOverridesConcurrencyTest(unittest.TestCase):
    def test_concurrent_review_override_writes_preserve_distinct_items(self) -> None:
        from lib_guard.review.overrides import read_review_overrides, write_review_override

        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "review_overrides.json"

            def write_item(index: int) -> None:
                write_review_override(
                    path,
                    library="vendor.demo",
                    version="v1",
                    item_id=f"item_{index}",
                    decision="accepted",
                    by=f"user_{index}",
                    reason="多人审查并发写入回归测试",
                )

            with ThreadPoolExecutor(max_workers=16) as executor:
                futures = [executor.submit(write_item, index) for index in range(80)]
                for future in as_completed(futures):
                    future.result()

            loaded = read_review_overrides(path)

        self.assertEqual(len(loaded["items"]), 80)
        self.assertEqual(set(loaded["items"]), {f"item_{index}" for index in range(80)})


if __name__ == "__main__":
    unittest.main()
