"""Small, explicit output contracts for scan/compare/release runs.

The evidence files remain in their existing directories.  This module only
adds a stable manifest and a shared path helper so callers do not have to
guess which files were produced or where the next projection lives.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from lib_guard.atomic import atomic_write_json


RUN_MANIFEST_FILENAME = "run_manifest.json"
RUN_MANIFEST_SCHEMA_VERSION = "run_manifest.v1"
RUN_MANIFEST_PRODUCER = "lib_guard"


def _now() -> str:
    return datetime.now(tz=timezone.utc).isoformat().replace("+00:00", "Z")


def canonical_scan_dir(
    workdir: str | Path,
    *,
    library_type: str,
    library_name: str,
    version: str,
    mode: str,
    scan_id: str,
) -> Path:
    """Return the one default scan path shared by direct and catalog scans."""

    return (
        Path(workdir)
        / "scan_out"
        / str(library_type or "unknown")
        / str(library_name or "unknown")
        / str(version or "unknown")
        / "runs"
        / f"{mode or 'scan'}_{scan_id}"
    )


def canonical_diff_dir(
    workdir: str | Path,
    *,
    library_name: str,
    version: str,
    relation_mode: str,
    base_version: str | None = None,
) -> Path:
    """Return the stable default compare evidence path."""

    leaf = f"base_{base_version}" if relation_mode == "base" and base_version else relation_mode
    return Path(workdir) / "diff" / str(library_name or "unknown") / str(version or "unknown") / leaf


def build_run_manifest(
    *,
    operation: str,
    status: str,
    run_id: str,
    library_type: str | None,
    library_name: str | None,
    version: str | None,
    inputs: Mapping[str, Any] | None = None,
    comparison: Mapping[str, Any] | None = None,
    artifacts: Mapping[str, Any] | None = None,
    phase_timings: list[Mapping[str, Any]] | None = None,
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    """Build a concise machine-readable map of one operation's outputs."""

    generated_at = _now()
    normalized_run_id = str(run_id)
    normalized_operation = str(operation)
    return {
        "schema_version": RUN_MANIFEST_SCHEMA_VERSION,
        "producer": RUN_MANIFEST_PRODUCER,
        "generated_at": generated_at,
        "created_at": generated_at,
        "operation": normalized_operation,
        "status": str(status),
        "run_id": normalized_run_id,
        "identity": {
            "library_id": str(library_name or ""),
            "version_id": str(version or ""),
            "run_id": normalized_run_id,
            "evidence_id": f"{normalized_operation}:{normalized_run_id}",
        },
        "library": {
            "type": str(library_type or ""),
            "name": str(library_name or ""),
            "version": str(version or ""),
        },
        "inputs": dict(inputs or {}),
        "comparison": dict(comparison or {}),
        "artifacts": dict(artifacts or {}),
        "phase_timings": [dict(item) for item in (phase_timings or [])],
        "warnings": list(warnings or []),
    }


def write_run_manifest(
    run_root: str | Path,
    *,
    operation: str,
    status: str,
    run_id: str,
    library_type: str | None,
    library_name: str | None,
    version: str | None,
    inputs: Mapping[str, Any] | None = None,
    comparison: Mapping[str, Any] | None = None,
    artifacts: Mapping[str, Any] | None = None,
    phase_timings: list[Mapping[str, Any]] | None = None,
    warnings: list[str] | None = None,
) -> Path:
    """Write ``run_manifest.json`` without touching any other evidence."""

    root = Path(run_root)
    path = root / RUN_MANIFEST_FILENAME
    payload = build_run_manifest(
        operation=operation,
        status=status,
        run_id=run_id,
        library_type=library_type,
        library_name=library_name,
        version=version,
        inputs=inputs,
        comparison=comparison,
        artifacts=artifacts,
        phase_timings=phase_timings,
        warnings=warnings,
    )
    # A run directory is immutable after completion; a lock file would only
    # become another unexplained output artifact.
    atomic_write_json(path, payload, lock=False)
    return path


def scan_artifacts(scan_dir: str | Path, *, scan_html: str | None = None) -> dict[str, Any]:
    scan = Path(scan_dir)
    facts = {
        name: str(scan / name)
        for name in (
            "scan_meta.json",
            "file_inventory.json",
            "manifest.json",
            "parser_manifest.json",
            "parser_task_list.json",
            "integrity.json",
            "scan_issues.json",
            "scan_summary.json",
            "state_delta.json",
            "type_distribution.json",
            "version_profile.json",
            "review",
            "summary",
            "signatures",
            "logs",
        )
        if (scan / name).exists()
    }
    reports = {"scan_html": str(scan_html)} if scan_html else {}
    return {"facts": facts, "reports": reports}


def compare_artifacts(diff_dir: str | Path, *, compare_html: str | None = None) -> dict[str, Any]:
    """List the bounded, human-relevant facts emitted by a compare run."""

    diff = Path(diff_dir)
    facts = {
        name: str(diff / name)
        for name in (
            "diff_meta.json",
            "diff_summary.json",
            "view_diff.json",
            "type_diff.json",
            "diff_issues.json",
            "file_diff.json",
            "release_readiness_diff.json",
            "release_evidence_diff.json",
            "component_diff.json",
            "signature_diff.json",
            "metadata_review_tasks.json",
            "manual_pairwise_tasks.json",
            "pairwise_diff_tasks.json",
            "pairwise_diff_task_status.json",
            "diff_report.md",
        )
        if (diff / name).exists()
    }
    reports = {"compare_html": str(compare_html)} if compare_html else {}
    return {"facts": facts, "reports": reports}


__all__ = [
    "RUN_MANIFEST_FILENAME",
    "RUN_MANIFEST_SCHEMA_VERSION",
    "RUN_MANIFEST_PRODUCER",
    "build_run_manifest",
    "canonical_diff_dir",
    "canonical_scan_dir",
    "compare_artifacts",
    "scan_artifacts",
    "write_run_manifest",
]
