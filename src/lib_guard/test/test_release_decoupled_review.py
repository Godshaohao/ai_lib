from __future__ import annotations

import unittest

from src.lib_guard.review.commands import derive_next_action
from src.lib_guard.review.state import _status_release, build_review_state


class ReleaseDecoupledReviewTest(unittest.TestCase):
    def test_plain_version_without_release_evidence_is_not_applicable(self) -> None:
        version = {"release": {}}

        self.assertEqual(_status_release(version), "RELEASE_NOT_APPLICABLE")

    def test_plain_review_ready_version_does_not_recommend_release_check(self) -> None:
        next_step = derive_next_action(
            {
                "display_name": "ucie",
                "version_id": "stable_20250608",
                "catalog_status": "OK",
                "scan_status": "SCAN_PASS",
                "diff_status": "DIFF_SAME",
                "pairwise_status": "PAIRWISE_EMPTY",
                "release_status": "RELEASE_NOT_APPLICABLE",
            }
        )

        self.assertNotEqual(next_step["next_action"], "RELEASE_CHECK")
        self.assertEqual(next_step["next_action"], "REVIEW_READY")

    def test_release_ready_requires_explicit_review(self) -> None:
        next_step = derive_next_action(
            {
                "display_name": "ucie",
                "version_id": "stable_20250608",
                "catalog_status": "OK",
                "scan_status": "SCAN_PASS",
                "diff_status": "DIFF_SAME",
                "pairwise_status": "PAIRWISE_EMPTY",
                "release_status": "RELEASE_READY",
            }
        )

        self.assertEqual(next_step["next_action"], "RELEASE_REVIEW")
        self.assertEqual(next_step["next_command"], "")

    def test_catalog_review_state_does_not_add_release_noise(self) -> None:
        catalog = {
            "libraries": [
                {
                    "library_id": "ip/ucie",
                    "library_name": "ucie",
                    "versions": [
                        {
                            "version_id": "stable_20250608",
                            "version_key": "ip/ucie/stable_20250608",
                            "stage": "stable",
                            "scan": {"status": "PASS", "scan_dir": "scan/stable"},
                            "diff": {"status": "SAME", "diff_dir": "diff/stable"},
                            "release": {},
                        }
                    ],
                }
            ]
        }

        state = build_review_state(catalog)
        version = state["libraries"][0]["versions"][0]

        self.assertEqual(version["release_status"], "RELEASE_NOT_APPLICABLE")
        self.assertNotEqual(version["next_action"], "RELEASE_CHECK")


if __name__ == "__main__":
    unittest.main()
