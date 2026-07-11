import unittest

from lib_guard.identity import (
    build_diff_identity,
    build_effective_identity,
    build_snapshot_identity,
    canonical_digest,
)


class ArtifactIdentityTest(unittest.TestCase):
    def test_canonical_digest_ignores_mapping_order(self):
        self.assertEqual(canonical_digest({"b": 2, "a": 1}), canonical_digest({"a": 1, "b": 2}))

    def test_canonical_digest_rejects_unsupported_values(self):
        with self.assertRaises(TypeError):
            canonical_digest({"unsupported": {"value"}})

    def test_canonical_digest_rejects_nan(self):
        with self.assertRaises(TypeError):
            canonical_digest({"non_finite": float("nan")})

    def test_canonical_digest_rejects_positive_infinity(self):
        with self.assertRaises(TypeError):
            canonical_digest({"non_finite": float("inf")})

    def test_canonical_digest_rejects_negative_infinity(self):
        with self.assertRaises(TypeError):
            canonical_digest({"non_finite": float("-inf")})

    def test_snapshot_identity_contains_expected_payload(self):
        identity = build_snapshot_identity(
            input_fingerprint={"source": "sha256:input"},
            policy_identity={"ruleset": "policy.v1"},
            tool_version="lib-guard 1.0",
            strength="strong",
        )
        self.assertEqual(identity["schema_version"], "delivery_snapshot_identity.v1")
        self.assertEqual(
            identity["payload"],
            {
                "input_fingerprint": {"source": "sha256:input"},
                "policy": {"ruleset": "policy.v1"},
                "tool_version": "lib-guard 1.0",
            },
        )
        self.assertEqual(identity["digest"], canonical_digest(identity["payload"]))

    def test_snapshot_identity_digest_changes_when_payload_changes(self):
        first = build_snapshot_identity(
            input_fingerprint={"source": "sha256:input"},
            policy_identity={"ruleset": "policy.v1"},
            tool_version="lib-guard 1.0",
            strength="strong",
        )
        changed = build_snapshot_identity(
            input_fingerprint={"source": "sha256:changed"},
            policy_identity={"ruleset": "policy.v1"},
            tool_version="lib-guard 1.0",
            strength="strong",
        )
        self.assertNotEqual(first["digest"], changed["digest"])

    def test_snapshot_identity_preserves_strength(self):
        identity = build_snapshot_identity(
            input_fingerprint={},
            policy_identity={},
            tool_version="lib-guard 1.0",
            strength="weak",
        )
        self.assertEqual(identity["strength"], "weak")

    def test_diff_identity_changes_only_when_evidence_changes(self):
        first = build_diff_identity("sha256:old", "sha256:new", "scan_diff.v1")
        second = build_diff_identity("sha256:old", "sha256:new", "scan_diff.v1")
        changed = build_diff_identity("sha256:old", "sha256:new2", "scan_diff.v1")
        self.assertEqual(first, second)
        self.assertNotEqual(first["digest"], changed["digest"])

    def test_effective_identity_excludes_paths_and_timestamps(self):
        left = {
            "base_full_version": "v1",
            "components": [{"version_id": "v1", "snapshot_digest": "sha256:a"}],
            "created_at": "A",
        }
        right = {**left, "created_at": "B", "manifest_path": "/other/host/file.json"}
        self.assertEqual(build_effective_identity(left)["digest"], build_effective_identity(right)["digest"])


if __name__ == "__main__":
    unittest.main()
