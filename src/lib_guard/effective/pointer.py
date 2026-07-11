from __future__ import annotations

import json
import hashlib
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from lib_guard.atomic import atomic_write_json

POINTER_SCHEMA = "current_effective.v1"


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def safe_name(value: Any) -> str:
    text = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value or "item")).strip("._")
    return text or "item"


def read_json(path: str | Path, default: Any = None) -> Any:
    p = Path(path)
    if not p.exists() or not p.is_file():
        return default
    return json.loads(p.read_text(encoding="utf-8"))


def write_json(path: str | Path, data: Mapping[str, Any]) -> Path:
    return atomic_write_json(path, data, lock=True)


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalize_effective_ref(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if text.startswith("raw:") or text.startswith("effective:"):
        return text
    return f"raw:{text}"


def _legacy_ref_value(lib: Mapping[str, Any]) -> tuple[str, str]:
    summary = lib.get("summary", {}) if isinstance(lib.get("summary"), Mapping) else {}
    for key in ["latest_effective_ref", "current_effective_ref"]:
        value = str(summary.get(key) or "")
        if value:
            return value, "effective" if "effective" in key else "raw"
    for key in ["current_effective", "current_effective_version"]:
        value = str(summary.get(key) or lib.get(key) or "")
        if value and value.lower() not in {"true", "false"}:
            return value, "effective"
    for key in ["latest_effective_ref", "current_effective_ref"]:
        value = str(lib.get(key) or "")
        if value:
            return value, "effective"
    for key in ["current_version", "approved_version", "latest_version"]:
        value = str(summary.get(key) or lib.get(key) or "")
        if value:
            return value, "raw"
    return "", "raw"


def latest_effective_ref_for_library(lib: Mapping[str, Any]) -> str:
    value, default_kind = _legacy_ref_value(lib)
    if not value:
        return ""
    if value.startswith("raw:") or value.startswith("effective:"):
        return value
    return f"{default_kind}:{value}"


def write_latest_effective_ref(catalog: Mapping[str, Any], library_id: str, ref: str) -> dict[str, Any]:
    updated = dict(catalog)
    libraries = []
    matched = False
    for lib in catalog.get("libraries", []) or []:
        if not isinstance(lib, Mapping):
            libraries.append(lib)
            continue
        row = dict(lib)
        if library_id in {str(row.get("library_id") or ""), str(row.get("library_name") or "")}:
            summary = dict(row.get("summary", {}) or {})
            summary["latest_effective_ref"] = normalize_effective_ref(ref)
            row["summary"] = summary
            matched = True
        libraries.append(row)
    if not matched:
        raise ValueError(f"library not found: {library_id}")
    updated["libraries"] = libraries
    return updated


def rel_href(base: str | Path, path: Any) -> str:
    if not path:
        return ""
    try:
        base_p = Path(base)
        target = Path(str(path))
        if target.is_absolute():
            return Path(os.path.relpath(target, base_p)).as_posix()
    except Exception:
        pass
    return str(path).replace("\\", "/")


def default_pointer_path_for_effective(effective_manifest: str | Path) -> Path:
    """Return <...>/effective/current_effective.json for a manifest in <...>/effective/<E>/effective_manifest.json."""
    manifest = Path(effective_manifest)
    # expected: reports/libraries/<lib>/effective/<effective_id>/effective_manifest.json
    if manifest.parent.parent.name == "effective":
        return manifest.parent.parent / "current_effective.json"
    return manifest.parent / "current_effective.json"


def make_current_pointer(
    effective_manifest: str | Path,
    *,
    html: str | Path | None = None,
    release_preview: str | Path | None = None,
    status: str = "accepted",
    accepted_by: str = "manual",
    note: str | None = None,
    revision: int = 1,
    previous_effective_id: str = "",
    previous_revision: int = 0,
    review_approval: str | Path | None = None,
    approval_sha256: str = "",
) -> dict[str, Any]:
    manifest_path = Path(effective_manifest)
    manifest = read_json(manifest_path, {}) or {}
    effective_id = str(manifest.get("effective_id") or manifest_path.parent.name)
    library_id = str(manifest.get("library_id") or manifest.get("library_name") or "")
    html_path = Path(html) if html else manifest_path.parent / "index.html"
    release_html = Path(release_preview) if release_preview else manifest_path.parent / "release_preview" / "index.html"
    return {
        "schema_version": POINTER_SCHEMA,
        "library_id": library_id,
        "current_effective_id": effective_id,
        "revision": revision,
        "previous_effective_id": previous_effective_id,
        "previous_revision": previous_revision,
        "status": status,
        "manifest": str(manifest_path),
        "manifest_sha256": sha256_file(manifest_path) if manifest_path.exists() else "",
        "html": str(html_path) if html_path.exists() or html else "",
        "release_preview": str(release_html) if release_html.exists() or release_preview else "",
        "review_approval": str(review_approval) if review_approval else "",
        "approval_sha256": approval_sha256,
        "base_full_version": manifest.get("base_full_version"),
        "accepted_updates": list(manifest.get("accepted_updates", []) or []),
        "summary": manifest.get("summary", {}) or {},
        "accepted_at": now_iso(),
        "accepted_by": accepted_by,
        "note": note or "",
    }


def write_current_pointer(
    effective_manifest: str | Path,
    *,
    out: str | Path | None = None,
    html: str | Path | None = None,
    release_preview: str | Path | None = None,
    status: str = "accepted",
    accepted_by: str = "manual",
    note: str | None = None,
    expected_previous_effective_id: str | None = None,
    expected_revision: int | None = None,
    review_approval: str | Path | None = None,
    approval_sha256: str = "",
) -> Path:
    out_path = Path(out) if out else default_pointer_path_for_effective(effective_manifest)
    existing = read_json(out_path, {}) or {}
    previous_effective_id = str(existing.get("current_effective_id") or "")
    previous_revision = int(existing.get("revision") or 0)
    if expected_previous_effective_id is not None and previous_effective_id != str(expected_previous_effective_id or ""):
        raise ValueError(
            "current effective changed; rerun lg next <LIBRARY> --apply to rebuild compare evidence "
            f"(expected {expected_previous_effective_id or '-'}, found {previous_effective_id or '-'})"
        )
    if expected_revision is not None and previous_revision != int(expected_revision):
        raise ValueError(
            "current effective changed; rerun lg next <LIBRARY> --apply to rebuild compare evidence "
            f"(expected revision {expected_revision}, found {previous_revision})"
        )
    pointer = make_current_pointer(
        effective_manifest,
        html=html,
        release_preview=release_preview,
        status=status,
        accepted_by=accepted_by,
        note=note,
        revision=previous_revision + 1,
        previous_effective_id=previous_effective_id,
        previous_revision=previous_revision,
        review_approval=review_approval,
        approval_sha256=approval_sha256,
    )
    return write_json(out_path, pointer)


def pointer_search_paths(out: str | Path, lib_id: str) -> list[Path]:
    out_p = Path(out)
    safe = safe_name(lib_id)
    names = [lib_id, safe]
    paths: list[Path] = []
    for name in names:
        paths.extend([
            out_p / "libraries" / safe_name(name) / "effective" / "current_effective.json",
            out_p / "effective" / safe_name(name) / "current_effective.json",
            out_p.parent / "effective" / safe_name(name) / "current_effective.json",
        ])
    dedup: list[Path] = []
    seen = set()
    for p in paths:
        key = str(p)
        if key not in seen:
            dedup.append(p)
            seen.add(key)
    return dedup


def load_current_pointer(out: str | Path, lib_id: str) -> dict[str, Any]:
    for path in pointer_search_paths(out, lib_id):
        data = read_json(path, {}) or {}
        if data:
            data["_pointer_path"] = str(path)
            return data
    return {}


def mark_current_effective_items(out: str | Path, effective_by_lib: Mapping[str, list[dict[str, Any]]]) -> dict[str, list[dict[str, Any]]]:
    """Mark items using current_effective.json. Does not delete historical/candidate snapshots."""
    result: dict[str, list[dict[str, Any]]] = {}
    for lib_id, items in effective_by_lib.items():
        pointer = load_current_pointer(out, lib_id)
        current_id = str(pointer.get("current_effective_id") or "")
        current_manifest = str(pointer.get("manifest") or "")
        updated: list[dict[str, Any]] = []
        for item in items:
            row = dict(item)
            is_current = False
            if current_id and str(row.get("effective_id") or "") == current_id:
                is_current = True
            if current_manifest and str(row.get("manifest") or "") == current_manifest:
                is_current = True
            row["effective_status"] = "current" if is_current else row.get("effective_status", "history")
            row["is_current_effective"] = is_current
            if is_current:
                row["current_pointer"] = pointer
                row["html"] = row.get("html") or pointer.get("html") or ""
                row["release_preview"] = row.get("release_preview") or pointer.get("release_preview") or ""
            updated.append(row)
        # If pointer exists but manifest was outside discovered roots, add a lightweight row.
        if pointer and current_id and not any(x.get("is_current_effective") for x in updated):
            summary = pointer.get("summary", {}) or {}
            updated.append({
                "effective_id": current_id,
                "manifest": pointer.get("manifest") or "",
                "html": pointer.get("html") or "",
                "release_preview": pointer.get("release_preview") or "",
                "base_full_version": pointer.get("base_full_version"),
                "accepted_updates": list(pointer.get("accepted_updates", []) or []),
                "summary": summary,
                "conflict_count": int(summary.get("conflict_count", 0) or 0),
                "file_count": int(summary.get("file_count", 0) or 0),
                "component_count": int(summary.get("component_count", 0) or 0),
                "operation_summary": summary.get("operation_summary", {}) or {},
                "file_type_summary": summary.get("file_type_summary", {}) or {},
                "source_summary": summary.get("source_summary", {}) or {},
                "created_at": pointer.get("accepted_at") or "",
                "effective_status": "current",
                "is_current_effective": True,
                "current_pointer": pointer,
            })
        updated.sort(key=lambda x: (0 if x.get("is_current_effective") else 1, str(x.get("created_at") or x.get("effective_id") or "")))
        result[lib_id] = updated
    return result
