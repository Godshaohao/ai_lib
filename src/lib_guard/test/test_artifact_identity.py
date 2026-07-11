import unittest

from lib_guard.identity import build_diff_identity, build_effective_identity, canonical_digest


class ArtifactIdentityTest(unittest.TestCase):
    def test_canonical_digest_ignores_mapping_order(self):
        self.assertEqual(canonical_digest({"b": 2, "a": 1}), canonical_digest({"a": 1, "b": 2}))

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
