from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


class EffectivePointerTest(unittest.TestCase):
    @staticmethod
    def _manifest(*, snapshot: str | None = "sha256:full") -> dict[str, object]:
        from lib_guard.effective.manifest import build_effective_manifest

        scan = {"snapshot_identity": {"digest": snapshot, "strength": "full"}} if snapshot else {}
        catalog = {
            "libraries": [
                {
                    "library_id": "ip/ucie",
                    "library_name": "ucie",
                    "versions": [{"version_id": "full1", "scan": scan}],
                }
            ]
        }
        return build_effective_manifest(catalog, "ucie", "full1", [], effective_id="E1")

    def test_normalize_effective_ref_uses_canonical_prefixes(self) -> None:
        from lib_guard.effective.pointer import normalize_effective_ref

        self.assertEqual(normalize_effective_ref("stable_20250608"), "raw:stable_20250608")
        self.assertEqual(normalize_effective_ref("raw:stable_20250608"), "raw:stable_20250608")
        self.assertEqual(normalize_effective_ref("effective:ucie_effective_20260627_01"), "effective:ucie_effective_20260627_01")
        self.assertEqual(normalize_effective_ref(""), "")

    def test_latest_effective_ref_for_library_prefers_summary_and_reads_legacy(self) -> None:
        from lib_guard.effective.pointer import latest_effective_ref_for_library

        self.assertEqual(
            latest_effective_ref_for_library({"summary": {"latest_effective_ref": "effective:E2"}, "current_version": "stale_raw"}),
            "effective:E2",
        )
        self.assertEqual(
            latest_effective_ref_for_library({"current_version": "stable_20250608"}),
            "raw:stable_20250608",
        )
        self.assertEqual(
            latest_effective_ref_for_library({"current_effective_version": "E1_20260624"}),
            "effective:E1_20260624",
        )

    def test_write_latest_effective_ref_only_writes_library_summary(self) -> None:
        from lib_guard.effective.pointer import write_latest_effective_ref

        catalog = {
            "libraries": [
                {
                    "library_id": "ip/ucie",
                    "library_name": "ucie",
                    "latest_effective_ref": "legacy",
                    "summary": {"current_version": "old"},
                }
            ]
        }

        updated = write_latest_effective_ref(catalog, "ip/ucie", "effective:E3")
        lib = updated["libraries"][0]

        self.assertEqual(lib["summary"]["latest_effective_ref"], "effective:E3")
        self.assertEqual(lib["latest_effective_ref"], "legacy")
        self.assertEqual(lib["summary"]["current_version"], "old")
        self.assertNotIn("current_effective_ref", lib)

    def test_write_current_pointer_records_digest_revision_and_cas(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            eff_dir = root / "effective" / "E1"
            eff_dir.mkdir(parents=True)
            manifest = eff_dir / "effective_manifest.json"
            manifest.write_text(json.dumps({"effective_id": "E1", "library_id": "ip/ucie"}), encoding="utf-8")
            pointer_path = eff_dir.parent / "current_effective.json"
            pointer_path.write_text(
                json.dumps({"current_effective_id": "E0", "revision": 7, "manifest_sha256": "old"}),
                encoding="utf-8",
            )

            from lib_guard.effective.pointer import sha256_file, write_current_pointer

            written = write_current_pointer(
                manifest,
                expected_previous_effective_id="E0",
                expected_revision=7,
                review_approval=root / "approval.json",
                approval_sha256="approval-digest",
            )
            data = json.loads(written.read_text(encoding="utf-8"))

            self.assertEqual(data["current_effective_id"], "E1")
            self.assertEqual(data["previous_effective_id"], "E0")
            self.assertEqual(data["previous_revision"], 7)
            self.assertEqual(data["revision"], 8)
            self.assertEqual(data["manifest_sha256"], sha256_file(manifest))
            self.assertEqual(data["review_approval"], str(root / "approval.json"))
            self.assertEqual(data["approval_sha256"], "approval-digest")

            with self.assertRaisesRegex(ValueError, "current effective changed"):
                write_current_pointer(manifest, expected_previous_effective_id="E0", expected_revision=7)

    def test_concurrent_pointer_cas_allows_exactly_one_writer(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            effective_dir = root / "effective" / "E1"
            effective_dir.mkdir(parents=True)
            manifest = effective_dir / "effective_manifest.json"
            manifest.write_text(json.dumps({"effective_id": "E1", "library_id": "ip/ucie"}), encoding="utf-8")
            pointer_path = effective_dir.parent / "current_effective.json"
            pointer_path.write_text(json.dumps({"current_effective_id": "E0", "revision": 7}), encoding="utf-8")

            import lib_guard.effective.pointer as pointer_module

            original_read_json = pointer_module.read_json
            reads_aligned = threading.Barrier(2)

            def synchronized_read_json(path: str | Path, default: object = None) -> object:
                data = original_read_json(path, default)
                if Path(path) == pointer_path:
                    try:
                        reads_aligned.wait(timeout=0.5)
                    except threading.BrokenBarrierError:
                        pass
                return data

            start = threading.Barrier(2)

            def write_once() -> str:
                start.wait()
                try:
                    pointer_module.write_current_pointer(
                        manifest,
                        expected_previous_effective_id="E0",
                        expected_revision=7,
                    )
                except ValueError as exc:
                    return str(exc)
                return "PASS"

            with mock.patch.object(pointer_module, "read_json", side_effect=synchronized_read_json):
                with ThreadPoolExecutor(max_workers=2) as pool:
                    results = list(pool.map(lambda _: write_once(), range(2)))

            self.assertEqual(results.count("PASS"), 1)
            self.assertEqual(sum("current effective changed" in result for result in results), 1)
            pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
            self.assertEqual(pointer["current_effective_id"], "E1")
            self.assertEqual(pointer["previous_revision"], 7)
            self.assertEqual(pointer["revision"], 8)

    def test_pointer_write_failure_restores_existing_approval(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            effective_dir = root / "effective" / "E1"
            effective_dir.mkdir(parents=True)
            manifest = effective_dir / "effective_manifest.json"
            manifest.write_text(json.dumps({"effective_id": "E1", "library_id": "ip/ucie"}), encoding="utf-8")
            approval_path = effective_dir / "review_approval.json"
            old_approval = '{"approved_by": "previous"}\n'
            approval_path.write_text(old_approval, encoding="utf-8")
            pointer_path = effective_dir.parent / "current_effective.json"
            original_pointer = {
                "current_effective_id": "E0",
                "revision": 7,
                "review_approval": str(approval_path),
            }
            pointer_path.write_text(json.dumps(original_pointer), encoding="utf-8")

            import lib_guard.effective.pointer as pointer_module

            original_atomic_write_json = pointer_module.atomic_write_json

            def fail_pointer_write(path: str | Path, data: object, **kwargs: object) -> Path:
                if Path(path) == pointer_path:
                    raise OSError("injected pointer write failure")
                return original_atomic_write_json(path, data, **kwargs)

            with mock.patch.object(pointer_module, "atomic_write_json", side_effect=fail_pointer_write):
                with self.assertRaisesRegex(OSError, "injected pointer write failure"):
                    pointer_module.write_current_pointer(
                        manifest,
                        expected_previous_effective_id="E0",
                        expected_revision=7,
                        review_approval=approval_path,
                        review_approval_data={"approved_by": "new"},
                    )

            self.assertEqual(json.loads(pointer_path.read_text(encoding="utf-8")), original_pointer)
            self.assertEqual(approval_path.read_text(encoding="utf-8"), old_approval)

    def test_approval_write_failure_leaves_pointer_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            effective_dir = root / "effective" / "E1"
            effective_dir.mkdir(parents=True)
            manifest = effective_dir / "effective_manifest.json"
            manifest.write_text(json.dumps({"effective_id": "E1", "library_id": "ip/ucie"}), encoding="utf-8")
            approval_path = effective_dir / "review_approval.json"
            pointer_path = effective_dir.parent / "current_effective.json"
            original_pointer = '{"current_effective_id": "E0", "revision": 7}\n'
            pointer_path.write_text(original_pointer, encoding="utf-8")

            import lib_guard.effective.pointer as pointer_module

            original_atomic_write_json = pointer_module.atomic_write_json

            def fail_approval_write(path: str | Path, data: object, **kwargs: object) -> Path:
                if Path(path) == approval_path:
                    raise OSError("injected approval write failure")
                return original_atomic_write_json(path, data, **kwargs)

            with mock.patch.object(pointer_module, "atomic_write_json", side_effect=fail_approval_write):
                with self.assertRaisesRegex(OSError, "injected approval write failure"):
                    pointer_module.write_current_pointer(
                        manifest,
                        expected_previous_effective_id="E0",
                        expected_revision=7,
                        review_approval=approval_path,
                        review_approval_data={"approved_by": "new"},
                    )

            self.assertEqual(pointer_path.read_text(encoding="utf-8"), original_pointer)
            self.assertFalse(approval_path.exists())

    def test_pointer_keeps_integrity_separate_from_unavailable_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            manifest_path = root / "libraries" / "ip_ucie" / "effective" / "E1" / "effective_manifest.json"
            manifest_path.parent.mkdir(parents=True)
            manifest_path.write_text(json.dumps(self._manifest(snapshot=None)), encoding="utf-8")

            from lib_guard.effective.pointer import load_current_pointer, write_current_pointer

            write_current_pointer(manifest_path)
            pointer = load_current_pointer(root, "ip/ucie")

            self.assertEqual(pointer["effective_integrity_status"], "MATCH")
            self.assertEqual(pointer["effective_evidence_status"], "UNAVAILABLE")
            self.assertEqual(pointer["effective_evidence_source"], "missing_evidence")
            self.assertEqual(pointer["effective_evidence_trust"], "UNAVAILABLE")
            self.assertEqual(pointer["effective_identity_status"], "MATCH")

    def test_pointer_normalizes_mixed_evidence_without_changing_manifest_compatibility(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            manifest_path = root / "libraries" / "ip_ucie" / "effective" / "E1" / "effective_manifest.json"
            manifest_path.parent.mkdir(parents=True)
            from lib_guard.effective.manifest import build_effective_manifest

            catalog = {
                "libraries": [
                    {
                        "library_id": "ip/ucie",
                        "library_name": "ucie",
                        "versions": [
                            {"version_id": "full1", "scan": {"snapshot_identity": {"digest": "sha256:full", "strength": "full"}}},
                            {"version_id": "fix1", "scan": {"input_fingerprint": {"hash": "legacy-fix"}}},
                        ],
                    }
                ]
            }
            manifest = build_effective_manifest(catalog, "ucie", "full1", [("fix1", ["lef"])], effective_id="E1")
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            from lib_guard.effective.pointer import load_current_pointer, write_current_pointer

            write_current_pointer(manifest_path)
            pointer = load_current_pointer(root, "ip/ucie")
            self.assertEqual(manifest["identity_status"], "MIXED_EVIDENCE")
            self.assertEqual(pointer["effective_integrity_status"], "MATCH")
            self.assertEqual(pointer["effective_evidence_status"], "MIXED")

    def test_legacy_pointer_validates_manifest_sha256_and_fallback_field(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            effective = root / "libraries" / "ip_ucie" / "effective"
            manifest_path = effective / "E1" / "effective_manifest.json"
            manifest_path.parent.mkdir(parents=True)
            manifest_path.write_text(json.dumps({"effective_id": "E1", "library_id": "ip/ucie"}), encoding="utf-8")

            from lib_guard.effective.pointer import load_current_pointer, sha256_file

            pointer_path = effective / "current_effective.json"
            pointer_path.write_text(
                json.dumps({"current_effective_id": "E1", "manifest": str(manifest_path), "manifest_sha256": sha256_file(manifest_path)}),
                encoding="utf-8",
            )
            self.assertEqual(load_current_pointer(root, "ip/ucie")["effective_integrity_status"], "MATCH")

            pointer_path.write_text(
                json.dumps(
                    {
                        "current_effective_id": "E1",
                        "manifest": str(manifest_path),
                        "manifest_sha256_fallback": sha256_file(manifest_path),
                    }
                ),
                encoding="utf-8",
            )
            self.assertEqual(load_current_pointer(root, "ip/ucie")["effective_integrity_status"], "MATCH")

            manifest_path.write_text(json.dumps({"effective_id": "E1", "library_id": "ip/changed"}), encoding="utf-8")
            self.assertEqual(load_current_pointer(root, "ip/ucie")["effective_integrity_status"], "MISMATCH")

    def test_pointer_reports_approval_integrity_independently(self) -> None:
        from lib_guard.effective.pointer import load_current_pointer, sha256_file, write_current_pointer

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            effective = root / "libraries" / "ip_ucie" / "effective"
            manifest_path = effective / "E1" / "effective_manifest.json"
            manifest_path.parent.mkdir(parents=True)
            manifest = self._manifest()
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            compare_path = effective / "compare_manifest.json"
            compare_path.write_text(json.dumps({"compare_id": "cmp1"}), encoding="utf-8")
            approval_path = manifest_path.parent / "review_approval.json"
            approval_path.write_text(
                json.dumps(
                    {
                        "candidate_effective_manifest": str(manifest_path),
                        "candidate_effective_sha256": "wrong",
                        "candidate_effective_digest": manifest["identity"]["digest"],
                        "compare_manifest": str(compare_path),
                        "compare_manifest_sha256": sha256_file(compare_path),
                    }
                ),
                encoding="utf-8",
            )

            write_current_pointer(
                manifest_path,
                review_approval=approval_path,
                approval_sha256=sha256_file(approval_path),
            )
            pointer = load_current_pointer(root, "ip/ucie")
            self.assertEqual(pointer["effective_integrity_status"], "MATCH")
            self.assertEqual(pointer["approval_integrity_status"], "MISMATCH")

            approval_path.write_text(
                json.dumps(
                    {
                        "candidate_effective_manifest": str(manifest_path),
                        "candidate_effective_sha256": sha256_file(manifest_path),
                        "candidate_effective_digest": "sha256:wrong",
                        "compare_manifest": str(compare_path),
                        "compare_manifest_sha256": sha256_file(compare_path),
                    }
                ),
                encoding="utf-8",
            )
            pointer_path = effective / "current_effective.json"
            pointer_data = json.loads(pointer_path.read_text(encoding="utf-8"))
            pointer_data["approval_sha256"] = sha256_file(approval_path)
            pointer_path.write_text(json.dumps(pointer_data), encoding="utf-8")
            self.assertEqual(load_current_pointer(root, "ip/ucie")["approval_integrity_status"], "MISMATCH")

            approval_path.write_text(
                json.dumps(
                    {
                        "candidate_effective_manifest": str(manifest_path),
                        "candidate_effective_sha256": sha256_file(manifest_path),
                    }
                ),
                encoding="utf-8",
            )
            pointer_data["approval_sha256"] = sha256_file(approval_path)
            pointer_path.write_text(json.dumps(pointer_data), encoding="utf-8")
            self.assertEqual(load_current_pointer(root, "ip/ucie")["approval_integrity_status"], "MATCH")

            pointer_data["approval_sha256"] = "wrong"
            pointer_path.write_text(json.dumps(pointer_data), encoding="utf-8")
            self.assertEqual(load_current_pointer(root, "ip/ucie")["approval_integrity_status"], "MISMATCH")

            approval_path.unlink()
            pointer = load_current_pointer(root, "ip/ucie")
            self.assertEqual(pointer["effective_integrity_status"], "MATCH")
            self.assertEqual(pointer["approval_integrity_status"], "MISSING")

    def test_approval_accepts_relative_declared_manifest_for_absolute_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            manifest_path = root / "effective_manifest.json"
            manifest_path.write_text("manifest", encoding="utf-8")
            approval_path = root / "review_approval.json"

            from lib_guard.effective.pointer import approval_integrity_for_manifest, sha256_file

            approval_path.write_text(
                json.dumps(
                    {
                        "candidate_effective_manifest": manifest_path.name,
                        "candidate_effective_sha256": sha256_file(manifest_path),
                    }
                ),
                encoding="utf-8",
            )

            self.assertEqual(approval_integrity_for_manifest(approval_path, manifest_path), "MATCH")

    def test_approval_accepts_absolute_declared_manifest_for_relative_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            manifest_path = root / "effective_manifest.json"
            manifest_path.write_text("manifest", encoding="utf-8")
            approval_path = root / "review_approval.json"

            from lib_guard.effective.pointer import approval_integrity_for_manifest, sha256_file

            approval_path.write_text(
                json.dumps(
                    {
                        "candidate_effective_manifest": str(manifest_path),
                        "candidate_effective_sha256": sha256_file(manifest_path),
                    }
                ),
                encoding="utf-8",
            )

            previous_cwd = Path.cwd()
            try:
                import os

                os.chdir(root)
                self.assertEqual(
                    approval_integrity_for_manifest(approval_path, Path("effective_manifest.json")),
                    "MATCH",
                )
            finally:
                os.chdir(previous_cwd)

    def test_declared_compare_manifest_controls_approval_and_pointer_integrity(self) -> None:
        from lib_guard.effective.pointer import (
            approval_integrity_for_manifest,
            load_current_pointer,
            sha256_file,
            write_current_pointer,
        )

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            effective_dir = root / "libraries" / "ip_ucie" / "effective" / "E1"
            effective_dir.mkdir(parents=True)
            manifest_path = effective_dir / "effective_manifest.json"
            manifest_path.write_text(json.dumps(self._manifest()), encoding="utf-8")
            compare_path = root / "compare_manifest.json"
            compare_path.write_text(json.dumps({"compare_id": "cmp1"}), encoding="utf-8")
            approval_path = effective_dir / "review_approval.json"
            approval_path.write_text(
                json.dumps(
                    {
                        "candidate_effective_manifest": str(manifest_path),
                        "candidate_effective_sha256": sha256_file(manifest_path),
                        "compare_manifest": str(compare_path),
                        "compare_manifest_sha256": sha256_file(compare_path),
                    }
                ),
                encoding="utf-8",
            )
            write_current_pointer(
                manifest_path,
                review_approval=approval_path,
                approval_sha256=sha256_file(approval_path),
            )

            self.assertEqual(approval_integrity_for_manifest(approval_path, manifest_path), "MATCH")
            self.assertEqual(load_current_pointer(root, "ip/ucie")["approval_integrity_status"], "MATCH")

            compare_path.unlink()
            self.assertEqual(approval_integrity_for_manifest(approval_path, manifest_path), "MISSING")
            self.assertEqual(load_current_pointer(root, "ip/ucie")["approval_integrity_status"], "MISSING")

            compare_path.write_text(json.dumps({"compare_id": "cmp1", "tampered": True}), encoding="utf-8")
            self.assertEqual(approval_integrity_for_manifest(approval_path, manifest_path), "MISMATCH")
            self.assertEqual(load_current_pointer(root, "ip/ucie")["approval_integrity_status"], "MISMATCH")

            approval = json.loads(approval_path.read_text(encoding="utf-8"))
            del approval["compare_manifest_sha256"]
            approval_path.write_text(json.dumps(approval), encoding="utf-8")
            self.assertEqual(approval_integrity_for_manifest(approval_path, manifest_path), "MISSING")

            approval_path.write_text(
                json.dumps(
                    {
                        "candidate_effective_manifest": str(manifest_path),
                        "candidate_effective_sha256": sha256_file(manifest_path),
                    }
                ),
                encoding="utf-8",
            )
            self.assertEqual(approval_integrity_for_manifest(approval_path, manifest_path), "MATCH")

    def test_digest_approval_requires_complete_candidate_and_compare_locks(self) -> None:
        from lib_guard.effective.pointer import approval_integrity_for_manifest, sha256_file

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            manifest_path = root / "effective_manifest.json"
            manifest_path.write_text(json.dumps(self._manifest()), encoding="utf-8")
            compare_path = root / "compare_manifest.json"
            compare_path.write_text(json.dumps({"compare_id": "cmp1"}), encoding="utf-8")
            approval_path = root / "review_approval.json"
            complete = {
                "candidate_effective_manifest": str(manifest_path),
                "candidate_effective_sha256": sha256_file(manifest_path),
                "candidate_effective_digest": self._manifest()["identity"]["digest"],
                "compare_manifest": str(compare_path),
                "compare_manifest_sha256": sha256_file(compare_path),
            }

            for missing in [
                "candidate_effective_manifest",
                "candidate_effective_sha256",
                "compare_manifest",
                "compare_manifest_sha256",
            ]:
                with self.subTest(missing=missing):
                    approval = dict(complete)
                    del approval[missing]
                    approval_path.write_text(json.dumps(approval), encoding="utf-8")
                    self.assertEqual(
                        approval_integrity_for_manifest(
                            approval_path,
                            manifest_path,
                            effective_digest=complete["candidate_effective_digest"],
                        ),
                        "MISSING",
                    )

    def test_legacy_relative_compare_manifest_supports_both_historical_bases(self) -> None:
        from lib_guard.effective.pointer import approval_integrity_for_manifest, sha256_file

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            approval_dir = root / "approval"
            approval_dir.mkdir()
            manifest_path = approval_dir / "effective_manifest.json"
            manifest_path.write_text("manifest", encoding="utf-8")
            approval_path = approval_dir / "review_approval.json"
            cwd_compare = root / "cwd_compare.json"
            cwd_compare.write_text("cwd compare", encoding="utf-8")
            approval_compare = approval_dir / "approval_compare.json"
            approval_compare.write_text("approval compare", encoding="utf-8")

            previous_cwd = Path.cwd()
            try:
                os.chdir(root)
                for declared, compare_path in [
                    (cwd_compare.name, cwd_compare),
                    (approval_compare.name, approval_compare),
                ]:
                    with self.subTest(declared=declared):
                        approval_path.write_text(
                            json.dumps(
                                {
                                    "candidate_effective_sha256": sha256_file(manifest_path),
                                    "compare_manifest": declared,
                                    "compare_manifest_sha256": sha256_file(compare_path),
                                }
                            ),
                            encoding="utf-8",
                        )
                        self.assertEqual(
                            approval_integrity_for_manifest(approval_path, manifest_path),
                            "MATCH",
                        )

                approval_path.write_text(
                    json.dumps(
                        {
                            "candidate_effective_sha256": sha256_file(manifest_path),
                            "compare_manifest": cwd_compare.name,
                            "compare_manifest_sha256": sha256_file(approval_compare),
                        }
                    ),
                    encoding="utf-8",
                )
                self.assertEqual(
                    approval_integrity_for_manifest(approval_path, manifest_path),
                    "MISMATCH",
                )
            finally:
                os.chdir(previous_cwd)


if __name__ == "__main__":
    unittest.main()
