from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from .io import utc_now, write_json


def release_result_from_check(check: Mapping[str, Any], *, html: str | None = None) -> dict[str, Any]:
    status = str(check.get("release_check_status") or "UNKNOWN")
    if status in {"BLOCK", "FAILED"}:
        release_status = "BLOCKED"
    elif status in {"PASS", "PASS_WITH_WARNING"}:
        release_status = "READY"
    else:
        release_status = "NOT_CHECKED"
    return {
        "schema_version": "release_result.v1",
        "library_id": check.get("library_id"),
        "version_id": check.get("version"),
        "status": release_status,
        "check_status": status,
        "apply_status": "NOT_APPLIED",
        "verify_status": "SKIPPED",
        "manifest": "",
        "release_root": "",
        "planned_files": 0,
        "created_links": 0,
        "failed_links": 0,
        "missing": 0,
        "extra": 0,
        "target_mismatch": 0,
        "html": html or "",
        "generated_at": utc_now(),
    }


def release_result_from_link(link_result: Mapping[str, Any], *, verify_result: Mapping[str, Any] | None = None, html: str | None = None) -> dict[str, Any]:
    summary = link_result.get("summary", {}) or {}
    verify_summary = (verify_result or {}).get("summary", {}) or {}
    link_status = str(link_result.get("status") or "UNKNOWN")
    if verify_result:
        verify_status = str(verify_result.get("status") or "UNKNOWN")
    else:
        verify_status = "SKIPPED"
    if link_status == "APPLIED" and verify_status not in {"FAILED", "BLOCK"}:
        status = "APPLIED"
    elif link_status in {"FAILED", "BLOCKED"}:
        status = "BLOCKED"
    elif link_status == "DRY_RUN":
        status = "READY"
    elif verify_status in {"FAILED", "BLOCK"}:
        status = "VERIFY_FAILED"
    else:
        status = link_status
    return {
        "schema_version": "release_result.v1",
        "library_id": None,
        "version_id": None,
        "status": status,
        "check_status": "",
        "apply_status": link_status,
        "verify_status": verify_status,
        "manifest": link_result.get("manifest_path"),
        "release_root": link_result.get("release_root"),
        "planned_files": summary.get("planned_files", 0),
        "created_links": summary.get("created_files", 0),
        "failed_links": summary.get("failed_files", 0),
        "missing": verify_summary.get("missing_files", 0),
        "extra": verify_summary.get("extra_files", 0),
        "target_mismatch": verify_summary.get("target_mismatch", 0),
        "html": html or "",
        "generated_at": utc_now(),
    }


def write_release_result(path: str | Path, result: Mapping[str, Any]) -> None:
    write_json(path, dict(result))
