from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from lib_guard.atomic import atomic_write_json
from lib_guard.effective.pointer import load_current_pointer, safe_name
from lib_guard.identity import canonical_digest

SCHEMA_VERSION = "release_set_manifest.v1"
COMPARE_SCHEMA_VERSION = "release_set_compare.v1"


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _row_identity(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "library_id": row.get("library_id"),
        "current_effective_id": row.get("current_effective_id"),
        "effective_digest": row.get("effective_digest"),
        "manifest_sha256": row.get("manifest_sha256"),
    }


def _set_identity(rows: Sequence[Mapping[str, Any]]) -> str:
    payload = {
        "schema_version": SCHEMA_VERSION,
        "libraries": [_row_identity(row) for row in sorted(rows, key=lambda item: str(item.get("library_id") or ""))],
    }
    return canonical_digest(payload)


def _set_id(rows: Sequence[Mapping[str, Any]]) -> str:
    digest = _set_identity(rows)
    return "set_" + digest.removeprefix("sha256:")[:12]


def _library_compare_key(row: Mapping[str, Any] | None) -> tuple[str, ...]:
    if not row:
        return ("absent",)
    digest = str(row.get("effective_digest") or row.get("manifest_sha256") or "")
    if digest:
        return ("digest", digest)
    current_id = str(row.get("current_effective_id") or "")
    manifest = str(row.get("manifest") or "")
    if current_id or manifest:
        return ("pointer", current_id, manifest)
    return (
        "missing",
        str(row.get("status") or ""),
        str(row.get("source") or ""),
        str(row.get("effective_integrity_status") or ""),
    )


def _current_effective_row(catalog_html: str | Path, library_id: str) -> dict[str, Any]:
    pointer = load_current_pointer(catalog_html, library_id)
    if not pointer:
        return {
            "library_id": library_id,
            "status": "MISSING_CURRENT",
            "source": "missing_current_effective",
            "current_effective_id": "",
            "base_full_version": "",
            "accepted_updates": [],
            "manifest": "",
            "manifest_sha256": "",
            "effective_digest": "",
            "effective_integrity_status": "MISSING",
            "html": "",
        }
    current_id = str(pointer.get("current_effective_id") or "")
    return {
        "library_id": str(pointer.get("library_id") or library_id),
        "status": "READY" if current_id else "MISSING_CURRENT",
        "source": "current_effective_pointer",
        "current_effective_id": current_id,
        "base_full_version": str(pointer.get("base_full_version") or ""),
        "accepted_updates": [str(item) for item in pointer.get("accepted_updates", []) or [] if str(item)],
        "manifest": str(pointer.get("manifest") or ""),
        "manifest_sha256": str(pointer.get("manifest_sha256") or ""),
        "effective_digest": str(pointer.get("effective_digest") or ""),
        "effective_integrity_status": str(pointer.get("effective_integrity_status") or ""),
        "effective_evidence_source": str(pointer.get("effective_evidence_source") or ""),
        "effective_evidence_trust": str(pointer.get("effective_evidence_trust") or ""),
        "html": str(pointer.get("html") or ""),
        "pointer_revision": int(pointer.get("revision") or 0),
    }


def build_release_set_manifest(
    catalog_html: str | Path,
    libraries: Sequence[str],
    *,
    set_id: str | None = None,
    note: str = "",
) -> dict[str, Any]:
    rows = [_current_effective_row(catalog_html, str(library)) for library in libraries if str(library).strip()]
    status_counts = Counter(str(row.get("status") or "UNKNOWN") for row in rows)
    digest = _set_identity(rows)
    return {
        "schema_version": SCHEMA_VERSION,
        "set_id": set_id or _set_id(rows),
        "created_at": now_iso(),
        "source": "current_effective_pointers",
        "catalog_html": str(Path(catalog_html)),
        "identity": {
            "schema_version": "release_set_identity.v1",
            "digest": digest,
            "source": "library_current_effective_digest",
        },
        "summary": {
            "library_count": len(rows),
            "ready_libraries": int(status_counts.get("READY", 0)),
            "missing_current_effective": int(status_counts.get("MISSING_CURRENT", 0)),
        },
        "libraries": rows,
        "note": note,
    }


def write_release_set_manifest(path: str | Path, manifest: Mapping[str, Any]) -> Path:
    return atomic_write_json(path, dict(manifest), lock=True)


def compare_release_sets(old: Mapping[str, Any], new: Mapping[str, Any], *, compare_id: str | None = None) -> dict[str, Any]:
    old_by_lib = {
        str(row.get("library_id") or ""): row
        for row in old.get("libraries", []) or []
        if isinstance(row, Mapping) and str(row.get("library_id") or "")
    }
    new_by_lib = {
        str(row.get("library_id") or ""): row
        for row in new.get("libraries", []) or []
        if isinstance(row, Mapping) and str(row.get("library_id") or "")
    }
    rows: list[dict[str, Any]] = []
    actions: Counter[str] = Counter()
    for library_id in sorted(set(old_by_lib) | set(new_by_lib)):
        old_row = old_by_lib.get(library_id)
        new_row = new_by_lib.get(library_id)
        if old_row and not new_row:
            action = "REMOVE_LIBRARY"
        elif new_row and not old_row:
            action = "ADD_LIBRARY"
        else:
            action = "KEEP_LIBRARY" if _library_compare_key(old_row) == _library_compare_key(new_row) else "CHANGE_EFFECTIVE"
        actions[action] += 1
        old_effective = str((old_row or {}).get("current_effective_id") or "")
        new_effective = str((new_row or {}).get("current_effective_id") or "")
        rows.append(
            {
                "library_id": library_id,
                "action": action,
                "old_effective_id": old_effective,
                "new_effective_id": new_effective,
                "old_digest": str((old_row or {}).get("effective_digest") or ""),
                "new_digest": str((new_row or {}).get("effective_digest") or ""),
                "old_manifest": str((old_row or {}).get("manifest") or ""),
                "new_manifest": str((new_row or {}).get("manifest") or ""),
                "old_target": f"effective:{old_effective}" if old_effective else "",
                "new_target": f"effective:{new_effective}" if new_effective else "",
                "drilldown": {
                    "old_html": str((old_row or {}).get("html") or ""),
                    "new_html": str((new_row or {}).get("html") or ""),
                    "compare_hint": "digest_changed_run_effective_compare" if action == "CHANGE_EFFECTIVE" else "",
                },
            }
        )
    return {
        "schema_version": COMPARE_SCHEMA_VERSION,
        "compare_id": compare_id or f"release_set_{safe_name(str(old.get('set_id') or 'old'))}_to_{safe_name(str(new.get('set_id') or 'new'))}",
        "created_at": now_iso(),
        "source": "release_set_digest_compare",
        "old_set": {"set_id": old.get("set_id"), "identity": old.get("identity", {})},
        "new_set": {"set_id": new.get("set_id"), "identity": new.get("identity", {})},
        "summary": {
            "library_count_old": len(old_by_lib),
            "library_count_new": len(new_by_lib),
            "changed_libraries": sum(actions[action] for action in ("ADD_LIBRARY", "REMOVE_LIBRARY", "CHANGE_EFFECTIVE")),
            "actions": dict(sorted(actions.items())),
        },
        "libraries": rows,
    }
