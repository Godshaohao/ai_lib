import json
from pathlib import Path
import tempfile
import unittest

from lib_guard.review_artifact_manifest import build_manifest, verify_manifest, write_manifest


class ReviewArtifactManifestTests(unittest.TestCase):
    def test_manifest_uses_relative_paths_and_verifies_after_archive_move(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            archive = base / "acceptance"
            run = archive / "libraries" / "Vendor.IP_A" / "runs" / "review_20261025_abcd"
            evidence = run / "evidence" / "lef_liberty_check.json"
            result = run / "review_result.json"
            workbook = run / "ip_review.xlsx"
            overview = archive / "ip_checks" / "index.html"
            for path in (evidence, result, workbook, overview):
                path.parent.mkdir(parents=True, exist_ok=True)
            evidence.write_text('{"status":"COMPLETE"}\n', encoding="utf-8")
            result.write_text(json.dumps({
                "library_id": "Vendor.IP_A", "review_id": "review_20261025_abcd",
                "source_revision": {"commit": "deadbeef", "working_tree_dirty": False},
            }), encoding="utf-8")
            workbook.write_bytes(b"xlsx")
            overview.write_text(
                '<!doctype html><a href="../libraries/Vendor.IP_A/runs/review_20261025_abcd/ip_review.xlsx">Excel</a>',
                encoding="utf-8")
            relative_paths = [
                overview.relative_to(archive).as_posix(),
                result.relative_to(archive).as_posix(),
                evidence.relative_to(archive).as_posix(),
                workbook.relative_to(archive).as_posix(),
            ]

            manifest_path = write_manifest(archive, "artifact_manifest.json", relative_paths)
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            moved = base / "renamed_archive"
            archive.rename(moved)

            verification = verify_manifest(moved, moved / "artifact_manifest.json")

            self.assertEqual(verification["status"], "COMPLETE", verification["errors"])
            self.assertEqual(verification["checked_count"], 4)
            for item in manifest["artifacts"]:
                self.assertFalse(Path(item["path"]).is_absolute())
                self.assertNotIn("..", Path(item["path"]).parts)
                if item["path"].endswith("review_result.json") or "evidence/" in item["path"]:
                    self.assertEqual(item["review_id"], "review_20261025_abcd")
                    self.assertEqual(item["source_revision"]["commit"], "deadbeef")

    def test_manifest_verification_reports_modified_or_missing_artifact(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            artifact = root / "evidence.json"
            artifact.write_text("original", encoding="utf-8")
            manifest_path = write_manifest(root, "artifact_manifest.json", ["evidence.json"])
            artifact.write_text("changed", encoding="utf-8")

            verification = verify_manifest(root, manifest_path)

            self.assertEqual(verification["status"], "INCOMPLETE")
            self.assertTrue(any("SHA-256 不匹配" in error for error in verification["errors"]))

    def test_manifest_rejects_paths_outside_archive_root(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "archive"
            root.mkdir()
            outside = Path(temp) / "outside.json"
            outside.write_text("{}", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "必须位于归档根目录内"):
                build_manifest(root, [outside])

    def test_manifest_output_cannot_escape_through_symlinked_directory(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            root = base / "archive"
            outside = base / "outside"
            root.mkdir()
            outside.mkdir()
            (root / "reports").symlink_to(outside, target_is_directory=True)
            artifact = root / "evidence.json"
            artifact.write_text("{}", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "清单输出必须位于归档根目录内"):
                write_manifest(root, "reports/artifact_manifest.json", ["evidence.json"])

            self.assertFalse((outside / "artifact_manifest.json").exists())

    def test_manifest_output_must_be_a_file_path_inside_archive(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "evidence.json").write_text("{}", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "清单输出必须是归档根目录内的文件路径"):
                write_manifest(root, ".", ["evidence.json"])

    def test_manifest_writer_rejects_symlink_output_to_selected_artifact(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            artifact = root / "review_result.json"
            artifact.write_text('{"review_id":"keep-me"}', encoding="utf-8")
            (root / "manifest-alias.json").symlink_to(artifact.name)

            with self.assertRaisesRegex(ValueError, "清单输出不能是软链接"):
                write_manifest(root, "manifest-alias.json", ["review_result.json"])

            self.assertEqual(json.loads(artifact.read_text(encoding="utf-8"))["review_id"], "keep-me")

    def test_manifest_writer_rejects_symlink_output_to_other_archive_file(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            evidence = root / "evidence.json"
            evidence.write_text("{}", encoding="utf-8")
            unrelated = root / "unrelated.json"
            unrelated.write_text('{"preserve":true}', encoding="utf-8")
            (root / "manifest-alias.json").symlink_to(unrelated.name)

            with self.assertRaisesRegex(ValueError, "清单输出不能是软链接"):
                write_manifest(root, "manifest-alias.json", ["evidence.json"])

            self.assertEqual(unrelated.read_text(encoding="utf-8"), '{"preserve":true}')

    def test_html_local_dependency_must_be_in_manifest_to_claim_relocatable(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            report = root / "index.html"
            (root / "assets").mkdir()
            (root / "assets" / "report.css").write_text("body{}", encoding="utf-8")
            report.write_text('<link rel="stylesheet" href="assets/report.css">', encoding="utf-8")
            manifest = write_manifest(root, "artifact_manifest.json", ["index.html"])

            verification = verify_manifest(root, manifest)

            self.assertEqual(verification["status"], "INCOMPLETE")
            self.assertTrue(any("未纳入归档清单" in error for error in verification["errors"]))

    def test_html_file_uri_is_reported_as_non_relocatable(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            report = root / "index.html"
            report.write_text('<a href="file:///home/user/private.xlsx">Excel</a>', encoding="utf-8")
            manifest = write_manifest(root, "artifact_manifest.json", ["index.html"])

            verification = verify_manifest(root, manifest)

            self.assertEqual(verification["status"], "INCOMPLETE")
            self.assertTrue(any("本机 file:// 链接不可迁移" in error for error in verification["errors"]))

    def test_invalid_artifact_entry_returns_incomplete_instead_of_raising(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            manifest = root / "artifact_manifest.json"
            manifest.write_text(json.dumps({
                "schema_version": "review_artifact_manifest.v1",
                "artifacts": ["not-an-object"],
            }), encoding="utf-8")

            verification = verify_manifest(root, manifest)

            self.assertEqual(verification["status"], "INCOMPLETE")
            self.assertTrue(verification["errors"])

    def test_non_object_manifest_returns_incomplete_instead_of_raising(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            manifest = root / "artifact_manifest.json"
            manifest.write_text("[]", encoding="utf-8")

            verification = verify_manifest(root, manifest)

            self.assertEqual(verification["status"], "INCOMPLETE")
            self.assertEqual(verification["errors"], ["清单结构或版本无效"])

    def test_empty_manifest_cannot_claim_complete_archive(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            manifest = root / "artifact_manifest.json"
            manifest.write_text(json.dumps({
                "schema_version": "review_artifact_manifest.v1",
                "artifact_count": 0,
                "artifacts": [],
            }), encoding="utf-8")

            verification = verify_manifest(root, manifest)

            self.assertEqual(verification["status"], "INCOMPLETE")
            self.assertTrue(any("至少包含一个文件" in error for error in verification["errors"]))

    def test_duplicate_manifest_paths_cannot_inflate_artifact_count(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            artifact = root / "evidence.json"
            artifact.write_text("{}", encoding="utf-8")
            manifest_path = write_manifest(root, "artifact_manifest.json", ["evidence.json"])
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["artifacts"].append(dict(manifest["artifacts"][0]))
            manifest["artifact_count"] = 2
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            verification = verify_manifest(root, manifest_path)

            self.assertEqual(verification["status"], "INCOMPLETE")
            self.assertTrue(any("重复归档路径" in error for error in verification["errors"]))


if __name__ == "__main__":
    unittest.main()
