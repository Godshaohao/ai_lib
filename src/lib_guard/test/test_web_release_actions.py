from __future__ import annotations

import unittest


class WebReleaseActionContractTest(unittest.TestCase):
    def test_named_release_defaults_to_overwrite_and_validates_names(self):
        from lib_guard.web.release_actions import build_release_web_args
        args = build_release_web_args("release-apply", {"acknowledged": True, "publish_name": "lib_NL7", "latest_name": "latest_NL7"})
        self.assertIn("--overwrite", args)
        self.assertIn("lib_NL7", args)
        self.assertIn("latest_NL7", args)
        with self.assertRaises(ValueError):
            build_release_web_args("release-apply", {"acknowledged": True, "publish_name": "../escape"})
    def test_normal_apply_requires_confirmation_and_never_forces(self) -> None:
        from lib_guard.web.release_actions import build_release_web_args
        with self.assertRaisesRegex(ValueError, "确认"):
            build_release_web_args("release-apply", {})
        args = build_release_web_args("release-apply", {"acknowledged": True})
        self.assertIn("--apply", args)
        self.assertNotIn("--force", args)
        self.assertNotIn("--no-verify", args)
        with self.assertRaises(ValueError):
            build_release_web_args("release-apply", {"acknowledged": True, "force": True})

    def test_force_release_builds_audited_verified_cli_arguments(self) -> None:
        from lib_guard.web.release_actions import build_release_web_args

        args = build_release_web_args(
            "release-force",
            {
                "alias": "current",
                "link_mode": "symlink",
                "force_reason": "紧急修复已人工确认",
                "force_by": "release_owner",
                "acknowledged": True,
            },
        )

        self.assertEqual(
            args,
            [
                "--alias", "current", "--link-mode", "symlink", "--no-render",
                "--overwrite", "--apply", "--force",
                "--force-reason", "紧急修复已人工确认",
                "--force-by", "release_owner",
            ],
        )
        self.assertNotIn("--no-verify", args)

    def test_force_release_rejects_missing_audit_or_confirmation(self) -> None:
        from lib_guard.web.release_actions import build_release_web_args

        for payload in (
            {"force_by": "owner", "acknowledged": True},
            {"force_reason": "人工确认", "acknowledged": True},
            {"force_reason": "人工确认", "force_by": "owner"},
        ):
            with self.assertRaisesRegex(ValueError, "强制发布"):
                build_release_web_args("release-force", payload)

    def test_preview_never_builds_apply_force_or_skip_verify(self) -> None:
        from lib_guard.web.release_actions import build_release_web_args

        args = build_release_web_args(
            "release-overwrite-preview",
            {"alias": "stage", "link_mode": "copy", "overwrite": True},
        )

        self.assertEqual(args, ["--alias", "stage", "--link-mode", "copy", "--no-render", "--overwrite"])
