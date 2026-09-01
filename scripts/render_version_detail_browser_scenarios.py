#!/usr/bin/env python3
"""Generate bounded Version Detail pages for the browser A-H acceptance set."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from unittest.mock import patch

from lib_guard.render.version_detail_report import render_version_detail_page
from lib_guard.render.version_review_model import build_ip_user_view_model, build_version_review_model


def _base_model(name: str) -> dict:
    return {
        "library_id": "ip/demo",
        "formal_library_id": "ip/demo",
        "typed_library_id": "ip/demo",
        "report_slug": "ip_demo",
        "library_name": "demo",
        "version_id": name,
        "target_version": name,
        "base_ref": "previous_effective",
        "base_version": "full_v1",
        "base_source": "previous_effective_version",
        "base_trust_status": "PASS",
        "base_trust_note": "基准已确认。",
        "review_mode": "baseline",
        "status": "CHANGED",
        "usage_decision": "USAGE_REVIEW_REQUIRED",
        "package_type": "FULL_PACKAGE",
        "comparison_semantics": "full",
        "delete_semantics": "real_delete",
        "diff_dir": "",
        "comparison_context": {"diff_status": "CHANGED", "base_version": "full_v1"},
        "diff_summary": {"status": "DIFF", "changed_files": 1},
        "file_diff": {"counts": {"added": 0, "removed": 0, "changed": 1}},
        "file_changes": [
            {"change": "CHANGED", "file_type": "lef", "path": "LEF/core.lef", "review_lane": "P0"}
        ],
        "added_files": 0,
        "removed_files": 0,
        "changed_files": 1,
        "lane_counts": {"recommended_file_diff": 1, "summary_only": 0, "metadata_only": 0},
        "recommended_file_diff": [],
        "recommended_actions": [],
        "release_notes": [],
        "package_composition": ["FULL"],
        "review_gate": {},
        "evidence_state": {"status": "PASS", "scan": {"status": "PASS"}, "diff": {"status": "PASS"}},
        "scan_evidence": {
            "file_total": 1,
            "unknown_total": 0,
            "counts": {"lef": 1},
            "inventory": {"files": [{"path": "LEF/core.lef", "file_type": "lef"}]},
            "context": {"scan_id": f"scan-{name}", "scan_status": "SCAN_PASS", "scan_dir": "scan"},
        },
    }


def _scenario(name: str) -> dict:
    model = _base_model(name)
    if name == "normal_full_update":
        model["file_changes"].append(
            {"change": "ADDED", "file_type": "verilog", "path": "RTL/core.v", "review_lane": "Summary-only"}
        )
        model["scan_evidence"]["counts"] = {"lef": 1, "verilog": 1}
        model["scan_evidence"]["file_total"] = 2
        model["scan_evidence"]["inventory"]["files"].append({"path": "RTL/core.v", "file_type": "verilog"})
        model["file_diff"]["counts"]["added"] = 1
        model["added_files"] = 1
    elif name == "first_version":
        model.update(
            review_mode="first_version",
            status="FIRST_VERSION_REVIEW",
            base_ref="",
            base_version="",
            base_source="",
            base_trust_status="INFO",
            usage_decision="USAGE_REVIEW_REQUIRED",
            file_changes=[],
            file_diff={},
            diff_summary={},
            comparison_context={"diff_status": "FIRST_VERSION_REVIEW"},
            lane_counts={},
        )
    elif name == "missing_required_view":
        model["scan_evidence"]["release_readiness"] = {
            "required_view_status": "MISSING",
            "components": [{
                "required_views": ["lef", "liberty"],
                "required_view_results": {
                    "lef": {"found": True, "status": "PASS"},
                    "liberty": {"found": False, "status": "MISSING"},
                },
            }],
        }
    elif name == "missing_diff":
        model.update(
            status="DIFF_NOT_RUN",
            diff_summary={},
            file_diff={},
            file_changes=[],
            changed_files=0,
            lane_counts={},
            comparison_context={"diff_status": "DIFF_NOT_RUN", "base_version": "full_v1"},
        )
    elif name == "adjacent_fallback":
        model.update(base_ref="adjacent_fallback", base_source="adjacent_fallback", base_trust_status="WARNING")
    elif name == "unknown_package":
        model.update(
            package_type="UNKNOWN_PACKAGE",
            scan_evidence={
                "file_total": 1,
                "unknown_total": 1,
                "counts": {"unknown": 1},
                "inventory": {"files": [{"path": "misc/payload.bin", "file_type": "unknown"}]},
                "context": {"scan_id": "scan-unknown", "scan_status": "SCAN_PASS", "scan_dir": "scan"},
            },
            file_changes=[],
            file_diff={"counts": {"added": 0, "removed": 0, "changed": 0}},
            changed_files=0,
            lane_counts={},
        )
    elif name == "full_fix_doc":
        model["package_composition"] = ["FULL", "FIX", "DOC"]
        model["release_notes"] = [{"path": "RELEASE.md"}]
    elif name == "stale_evidence":
        model["scan_evidence"]["context"].update(scan_status="STALE", scan_id="scan-old")
        model["evidence_state"] = {"status": "STALE", "scan": {"status": "STALE"}, "diff": {"status": "PASS"}}
    return model


def render(out: Path) -> dict[str, str]:
    lib = {"library_id": "ip/demo", "library_name": "demo", "display_name": "demo", "report_slug": "ip_demo"}
    manifest: dict[str, str] = {}
    for name in (
        "first_version",
        "normal_full_update",
        "missing_required_view",
        "missing_diff",
        "adjacent_fallback",
        "unknown_package",
        "full_fix_doc",
        "stale_evidence",
    ):
        model = _scenario(name)
        model["version_review_model"] = build_version_review_model(model)
        model["ip_user_view_model"] = build_ip_user_view_model(model)
        model["review_report"] = model["version_review_model"]["review_report"]
        with patch("lib_guard.render.version_detail_report.build_version_update_detail_model", return_value=model):
            page = render_version_detail_page(out / name, lib, {"version_id": name, "review_gate": {}})
        manifest[name] = str(Path(page).resolve())
    out.mkdir(parents=True, exist_ok=True)
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="work/version_detail_browser_scenarios")
    args = parser.parse_args()
    manifest = render(Path(args.out).resolve())
    print(json.dumps(manifest, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
