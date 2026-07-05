from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path


def _write_json(path: Path, data: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _library() -> dict[str, str]:
    return {
        "library_id": "ip/ucie",
        "formal_library_id": "Vendor_A.ucie",
        "library_name": "ucie",
    }


def _version(version_id: str, scan_dir: Path) -> dict[str, object]:
    return {
        "version_id": version_id,
        "scan": {"status": "PASS", "scan_dir": str(scan_dir)},
    }


def _write_active_window(root: Path) -> dict[str, Path]:
    html = root / "html"
    lib_dir = html / "libraries" / "ip_ucie"
    effective_dir = lib_dir / "effective" / "candidate_fix2"
    compare_dir = lib_dir / "compare" / "window_raw_full1_to_candidate_fix2"
    scan_dir = root / "scan" / "fix2"
    scan_dir.mkdir(parents=True)
    effective_dir.mkdir(parents=True)
    compare_dir.mkdir(parents=True)
    candidate_manifest = effective_dir / "effective_manifest.json"
    candidate_html = effective_dir / "index.html"
    compare_manifest = compare_dir / "compare_manifest.json"
    compare_html = compare_dir / "index.html"
    candidate_manifest.write_text("{}", encoding="utf-8")
    candidate_html.write_text("<html></html>", encoding="utf-8")
    compare_manifest.write_text("{}", encoding="utf-8")
    compare_html.write_text("<html></html>", encoding="utf-8")
    window_file = lib_dir / "window" / "pending_window.json"
    _write_json(
        window_file,
        {
            "schema_version": "review_window.v1",
            "library": "ucie",
            "library_id": "ip/ucie",
            "state": "COMPARED",
            "items": [
                {"version": "fix1", "role": "intermediate", "kind": "PARTIAL"},
                {"version": "full2", "role": "candidate_base", "kind": "FULL"},
                {"version": "fix2", "role": "candidate_overlay", "kind": "PARTIAL"},
            ],
            "base_effective": {"target": "raw:full1"},
            "candidate_effective": {
                "effective_id": "candidate_fix2",
                "base_full": "full2",
                "overlays": ["fix2"],
                "manifest": str(candidate_manifest),
                "html": str(candidate_html),
            },
            "compare": {
                "compare_id": "window_raw_full1_to_candidate_fix2",
                "old": "raw:full1",
                "new": "effective:candidate_fix2",
                "out_dir": str(compare_dir),
                "html": str(compare_html),
            },
            "warnings": ["window evidence warning"],
        },
    )
    return {
        "html": html,
        "scan_dir": scan_dir,
        "window_file": window_file,
        "candidate_manifest": candidate_manifest,
        "candidate_html": candidate_html,
        "compare_dir": compare_dir,
        "compare_manifest": compare_manifest,
        "compare_html": compare_html,
    }


class VersionDetailReviewContextTest(unittest.TestCase):
    def test_candidate_base_context_uses_active_window_candidate_and_compare(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            paths = _write_active_window(root)

            from lib_guard.render.version_detail_context import build_version_detail_review_context

            ctx = build_version_detail_review_context(
                catalog_html_out=paths["html"],
                library_row=_library(),
                version_row=_version("full2", paths["scan_dir"]),
            )

            self.assertEqual(ctx["schema_version"], "version_detail_review_context.v1")
            self.assertEqual(ctx["status"], "IN_ACTIVE_WINDOW")
            self.assertEqual(ctx["library"], "ucie")
            self.assertEqual(ctx["library_id"], "ip/ucie")
            self.assertEqual(ctx["target_version"], "full2")
            self.assertEqual(ctx["role_in_window"], "candidate_base")
            self.assertEqual(ctx["window_state"], "COMPARED")
            self.assertEqual(ctx["window_file"], str(paths["window_file"]))
            self.assertEqual([item["version"] for item in ctx["window_items"]], ["fix1", "full2", "fix2"])
            self.assertEqual(ctx["old_target"], "raw:full1")
            self.assertEqual(ctx["old_label"], "raw:full1")
            self.assertEqual(ctx["candidate_effective_id"], "candidate_fix2")
            self.assertEqual(ctx["candidate_effective_base_full"], "full2")
            self.assertEqual(ctx["candidate_effective_overlays"], ["fix2"])
            self.assertEqual(ctx["candidate_effective_manifest"], str(paths["candidate_manifest"]))
            self.assertEqual(ctx["candidate_effective_html"], str(paths["candidate_html"]))
            self.assertEqual(ctx["compare_id"], "window_raw_full1_to_candidate_fix2")
            self.assertEqual(ctx["compare_old"], "raw:full1")
            self.assertEqual(ctx["compare_new"], "effective:candidate_fix2")
            self.assertEqual(ctx["compare_dir"], str(paths["compare_dir"]))
            self.assertEqual(ctx["compare_html"], str(paths["compare_html"]))
            self.assertEqual(ctx["compare_manifest"], str(paths["compare_manifest"]))
            self.assertEqual(
                ctx["freshness"],
                {
                    "window_exists": True,
                    "candidate_manifest_exists": True,
                    "compare_manifest_exists": True,
                    "compare_html_exists": True,
                    "scan_evidence_exists": True,
                    "status": "FRESH",
                },
            )
            self.assertEqual(ctx["warnings"], ["window evidence warning"])

    def test_candidate_overlay_context_uses_candidate_overlays(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            paths = _write_active_window(root)

            from lib_guard.render.version_detail_context import build_version_detail_review_context

            ctx = build_version_detail_review_context(
                catalog_html_out=paths["html"],
                library_row=_library(),
                version_row=_version("fix2", paths["scan_dir"]),
            )

            self.assertEqual(ctx["status"], "IN_ACTIVE_WINDOW")
            self.assertEqual(ctx["role_in_window"], "candidate_overlay")
            self.assertEqual(ctx["candidate_effective_base_full"], "full2")
            self.assertEqual(ctx["candidate_effective_overlays"], ["fix2"])
            self.assertEqual(ctx["compare_old"], "raw:full1")
            self.assertEqual(ctx["compare_new"], "effective:candidate_fix2")
            self.assertEqual(ctx["freshness"]["status"], "FRESH")

    def test_intermediate_context_preserves_window_but_marks_non_candidate_role(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            paths = _write_active_window(root)

            from lib_guard.render.version_detail_context import build_version_detail_review_context

            ctx = build_version_detail_review_context(
                catalog_html_out=paths["html"],
                library_row=_library(),
                version_row=_version("fix1", paths["scan_dir"]),
            )

            self.assertEqual(ctx["status"], "IN_ACTIVE_WINDOW")
            self.assertEqual(ctx["role_in_window"], "intermediate")
            self.assertEqual(ctx["candidate_effective_id"], "candidate_fix2")
            self.assertEqual(ctx["compare_manifest"], str(paths["compare_manifest"]))

    def test_standalone_context_is_returned_when_target_is_not_in_active_window(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            paths = _write_active_window(root)

            from lib_guard.render.version_detail_context import build_version_detail_review_context

            ctx = build_version_detail_review_context(
                catalog_html_out=paths["html"],
                library_row=_library(),
                version_row=_version("legacy0", paths["scan_dir"]),
            )

            self.assertEqual(ctx["status"], "STANDALONE")
            self.assertEqual(ctx["role_in_window"], "standalone")
            self.assertEqual(ctx["window_state"], "COMPARED")
            self.assertEqual(ctx["candidate_effective_id"], "candidate_fix2")
            self.assertEqual(ctx["compare_id"], "window_raw_full1_to_candidate_fix2")
            self.assertEqual(ctx["freshness"]["window_exists"], True)
            self.assertEqual(ctx["freshness"]["status"], "PARTIAL")

    def test_standalone_context_is_returned_when_pending_window_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)

            from lib_guard.render.version_detail_context import build_version_detail_review_context

            ctx = build_version_detail_review_context(
                catalog_html_out=root / "html",
                library_row=_library(),
                version_row=_version("orphan", root / "missing_scan"),
            )

            self.assertEqual(ctx["status"], "STANDALONE")
            self.assertEqual(ctx["role_in_window"], "standalone")
            self.assertEqual(ctx["window_state"], "")
            self.assertEqual(ctx["window_file"], "")
            self.assertEqual(ctx["candidate_effective_id"], "")
            self.assertEqual(ctx["compare_manifest"], "")
            self.assertEqual(
                ctx["freshness"],
                {
                    "window_exists": False,
                    "candidate_manifest_exists": False,
                    "compare_manifest_exists": False,
                    "compare_html_exists": False,
                    "scan_evidence_exists": False,
                    "status": "STALE_OR_MISSING",
                },
            )


if __name__ == "__main__":
    unittest.main()
