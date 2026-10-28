"""Small, auditable file-content comparison helper."""

from __future__ import annotations

import gzip
import os
import stat
import zlib
from contextlib import ExitStack
from pathlib import Path
from typing import Any


_STAT_FIELDS = (
    "st_mode",
    "st_ino",
    "st_dev",
    "st_nlink",
    "st_uid",
    "st_gid",
    "st_size",
    "st_atime_ns",
    "st_mtime_ns",
    "st_ctime_ns",
)
_CHANGE_FIELDS = tuple(field for field in _STAT_FIELDS if field != "st_atime_ns")


def _stat_snapshot(path: os.PathLike[str] | str) -> dict[str, int]:
    info = os.stat(path)
    if not stat.S_ISREG(info.st_mode):
        raise OSError(f"not a regular file: {path}")
    return {field: int(getattr(info, field)) for field in _STAT_FIELDS}


def _empty_stats() -> dict[str, Any]:
    return {"base": None, "target": None}


def _result(
    *,
    status: str,
    comparison_mode: str,
    bytes_read: int,
    stat_before: dict[str, Any],
    stat_after: dict[str, Any],
    reason: str | None,
) -> dict[str, Any]:
    return {
        "status": status,
        "comparison_mode": comparison_mode,
        "bytes_read": bytes_read,
        "stat_before": stat_before,
        "stat_after": stat_after,
        "reason": reason,
    }


def _changed(before: dict[str, int], after: dict[str, int]) -> bool:
    return any(before[field] != after[field] for field in _CHANGE_FIELDS)


def _open_content(path: Path):
    return gzip.open(path, "rb") if path.suffix.lower() == ".gz" else path.open("rb")


def compare_files(
    base_path: os.PathLike[str] | str,
    target_path: os.PathLike[str] | str,
    *,
    chunk_size: int = 1024 * 1024,
) -> dict[str, Any]:
    """Compare two files while retaining enough evidence to audit the read."""
    base = Path(base_path)
    target = Path(target_path)
    decompressed = base.suffix.lower() == ".gz" or target.suffix.lower() == ".gz"
    comparison_mode = "DECOMPRESSED_CONTENT" if decompressed else "RAW_BYTES"
    stat_before = _empty_stats()
    stat_after = _empty_stats()

    if not isinstance(chunk_size, int) or isinstance(chunk_size, bool) or chunk_size <= 0:
        return _result(
            status="FAILED",
            comparison_mode=comparison_mode,
            bytes_read=0,
            stat_before=stat_before,
            stat_after=stat_after,
            reason="invalid_chunk_size",
        )

    try:
        stat_before["base"] = _stat_snapshot(base)
        stat_before["target"] = _stat_snapshot(target)
    except (OSError, TypeError, ValueError):
        return _result(
            status="FAILED",
            comparison_mode=comparison_mode,
            bytes_read=0,
            stat_before=stat_before,
            stat_after=stat_after,
            reason="path_error",
        )

    status = "SAME"
    reason = None
    bytes_read = 0
    try:
        with ExitStack() as stack:
            base_stream = stack.enter_context(_open_content(base))
            target_stream = stack.enter_context(_open_content(target))
            while True:
                base_chunk = base_stream.read(chunk_size)
                target_chunk = target_stream.read(chunk_size)
                bytes_read += len(base_chunk) + len(target_chunk)
                if base_chunk != target_chunk:
                    status = "DIFF"
                    break
                if not base_chunk:
                    break
    except (gzip.BadGzipFile, EOFError, zlib.error):
        status = "FAILED"
        reason = "invalid_gzip"
    except (OSError, ValueError):
        status = "FAILED"
        reason = "read_error"

    try:
        stat_after["base"] = _stat_snapshot(base)
        stat_after["target"] = _stat_snapshot(target)
    except (OSError, TypeError, ValueError):
        return _result(
            status="FAILED",
            comparison_mode=comparison_mode,
            bytes_read=bytes_read,
            stat_before=stat_before,
            stat_after=stat_after,
            reason="path_error",
        )

    if _changed(stat_before["base"], stat_after["base"]) or _changed(
        stat_before["target"], stat_after["target"]
    ):
        status = "UNVERIFIED"
        reason = "source_changed_during_read"

    return _result(
        status=status,
        comparison_mode=comparison_mode,
        bytes_read=bytes_read,
        stat_before=stat_before,
        stat_after=stat_after,
        reason=reason,
    )


def compare_projection_files(
    projection: dict[str, Any],
    *,
    selected_keys: list[str] | None = None,
) -> dict[str, Any]:
    """Compare the uniquely bound files in one projection in place."""
    scope = projection.get("scope") or {}
    base_version = str(scope.get("base_version") or "")
    target_version = str(scope.get("target_version") or "")
    selected = set(selected_keys or [])
    eligible = 0
    compared = 0
    for row in projection.get("files") or []:
        if selected and str(row.get("file_key") or "") not in selected:
            continue
        comparison = row.setdefault("comparison", {})
        if comparison.get("delivery_relation") != "READY_TO_COMPARE":
            continue
        occurrences = row.get("occurrences") or []
        base_paths = [item.get("source_path") for item in occurrences if item.get("version") == base_version]
        target_paths = [item.get("source_path") for item in occurrences if item.get("version") == target_version]
        eligible += 1
        if len(base_paths) != 1 or len(target_paths) != 1:
            comparison.update({"content_status": "UNVERIFIED", "comparison_mode": "UNKNOWN", "comparison_reason": "non_unique_source"})
            continue
        result = compare_files(base_paths[0], target_paths[0])
        status = {"SAME": "BYTE_SAME", "DIFF": "BYTE_DIFFERENT"}.get(result["status"], result["status"])
        comparison.update({"content_status": status, "comparison_mode": result["comparison_mode"],
                           "comparison_reason": result.get("reason"), "comparison_evidence": result})
        compared += 1
    projection.setdefault("coverage", {})["content_comparison"] = (
        "NOT_COMPARED" if not eligible else ("COMPLETE" if eligible == compared else "PARTIAL")
    )
    summary = projection.setdefault("summary", {})
    summary["content_compared"] = compared
    summary["not_compared"] = sum((row.get("comparison") or {}).get("content_status") == "NOT_COMPARED" for row in projection.get("files") or [])
    return projection
