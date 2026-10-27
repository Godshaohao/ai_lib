"""Build a read-only file/version projection from explicitly supplied inventories."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from .effective_file_tracker import _view_for_path, _view_relative_key, longest_registered_path_match
from .file_status import TRACKED_VIEWS


def _identity(relative: str, view: str) -> tuple[str, tuple[str, ...]]:
    """Drop known view wrappers without case-folding file identities."""
    _, normalized_parts = _view_relative_key(relative, view)
    parts = Path(relative).parts
    return view, tuple(parts[-len(normalized_parts):]) if normalized_parts else ()


def publish_projection(output: str | Path, projection: dict[str, Any], *,
                       before_publish: Callable[[dict[str, Any]], Callable[[], None] | None] | None = None) -> dict[str, Any]:
    """Write an immutable snapshot before atomically advancing its pointer."""
    root = Path(output)
    now = datetime.now(timezone.utc)
    snapshot_id = f"snapshot_{now.strftime('%Y%m%dT%H%M%SZ')}_{uuid4().hex}"
    snapshot = {**projection, "snapshot_id": snapshot_id, "generated_at": now.isoformat()}
    run_dir = root / "runs" / snapshot_id
    run_dir.mkdir(parents=True, exist_ok=False)
    snapshot_path = run_dir / "projection.json"
    snapshot_path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    pointer = {"snapshot_id": snapshot_id, "projection_ref": f"runs/{snapshot_id}/projection.json",
               "generated_at": snapshot["generated_at"]}
    temporary = root / f".latest.{uuid4().hex}.tmp"
    rollback = before_publish(snapshot) if before_publish else None
    try:
        temporary.write_text(json.dumps(pointer, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(root / "latest.json")
    except Exception:
        if rollback is not None:
            rollback()
        raise
    finally:
        temporary.unlink(missing_ok=True)
    return snapshot


def build_projection(library_id: str, versions: list[dict[str, Any]],
                     inventories: list[dict[str, Any]], formal_files: list[dict[str, Any]] | None,
                     *, base_version: str = "", target_version: str = "", formal_stage: str = "") -> dict[str, Any]:
    """Project observations; this function neither scans nor reads file contents."""
    roots = [(Path(str(v["path"])).expanduser().resolve(), v) for v in versions if v.get("path")]
    version_ids = [str(v.get("id") or "") for v in versions]
    if not all(version_ids) or len(set(version_ids)) != len(version_ids):
        raise ValueError("RAW 版本标识为空或重复")
    if any(value and value not in version_ids for value in (base_version, target_version)):
        raise ValueError("基准或目标版本未登记")
    inventory_by_id = {str(i.get("version_id") or ""): i for i in inventories}
    if len(inventory_by_id) != len(inventories):
        raise ValueError("RAW 盘点版本标识重复")
    files: dict[tuple[str, tuple[str, ...]], list[dict[str, Any]]] = defaultdict(list)
    for root, version in roots:
        version_id = str(version["id"])
        for raw_path in (inventory_by_id.get(version_id) or {}).get("files") or []:
            path = Path(str(raw_path)).expanduser().resolve()
            try:
                relative = path.relative_to(root).as_posix()
            except ValueError:
                continue
            view = _view_for_path(Path(relative))
            if view not in TRACKED_VIEWS:
                continue
            key = _identity(relative, view)
            files[key].append({"version": version_id, "source_path": str(path), "present": True, "sha256": None})

    formal_by_key: dict[tuple[str, tuple[str, ...]], list[dict[str, Any]]] = defaultdict(list)
    unbound = []
    for item in formal_files or []:
        source_value = str(item.get("source_path") or "")
        source = Path(source_value).expanduser().resolve() if source_value else None
        match, ambiguous = longest_registered_path_match(source, roots) if source else (None, False)
        if match and not ambiguous:
            root, version = match
            relative = source.relative_to(root).as_posix()
            view = str(item.get("view") or _view_for_path(Path(relative))).casefold()
            key = _identity(relative, view)
            formal_by_key[key].append({"stage": formal_stage, "source_path": source_value,
                                       "source_version": str(version["id"]), "published_path": item.get("published_path"),
                                       "observation_status": "OBSERVED", "approved_effective_status": "NOT_CONFIGURED"})
        else:
            unbound.append({"stage": formal_stage, "source_path": source_value,
                            "view": str(item.get("view") or "other").casefold(),
                            "source_version": None, "published_path": item.get("published_path"),
                            "observation_status": "AMBIGUOUS" if ambiguous else "UNRESOLVED",
                            "approved_effective_status": "NOT_CONFIGURED"})

    def presence(version: str, occurrences: list[dict[str, Any]]) -> str:
        if not version:
            return "NOT_SELECTED"
        if any(item["version"] == version for item in occurrences):
            return "PRESENT"
        inventory = inventory_by_id.get(version)
        return "ABSENT_VERIFIED" if inventory and inventory.get("status") == "COMPLETE" else "UNKNOWN"

    rows = []
    for key in sorted(set(files) | set(formal_by_key)):
        view, parts = key
        occurrences = files.get(key, [])
        counts = [sum(item["version"] == version for item in occurrences) for version in version_ids]
        if any(count > 1 for count in counts) or len(formal_by_key.get(key, [])) > 1:
            identities = "AMBIGUOUS"
        elif not base_version or not target_version:
            identities = "OBSERVED_PATH"
        elif presence(base_version, occurrences) == presence(target_version, occurrences) == "PRESENT":
            identities = "EXACT_RELATIVE_PATH"
        else:
            identities = "UNRESOLVED"
        formal = formal_by_key.get(key, [])
        display_path = (formal[0].get("published_path") if len(formal) == 1 else "") or (
            occurrences[0].get("source_path") if occurrences else "") or (parts[-1] if parts else "")
        rows.append({"file_key": view + ":" + "/".join(parts), "view": view,
                     "display_name": Path(display_path).name, "identity_status": identities,
                     "identity_evidence": "VIEW_AND_RELATIVE_PATH", "occurrences": occurrences,
                     "formal_usage": formal[0] if len(formal) == 1 else {
                         "observation_status": "AMBIGUOUS" if formal else ("UNKNOWN" if formal_files is None else "NOT_OBSERVED"),
                         "approved_effective_status": "NOT_CONFIGURED"},
                     "comparison": {"base_version": base_version, "target_version": target_version,
                                    "base_presence": presence(base_version, occurrences),
                                    "target_presence": presence(target_version, occurrences),
                                    "content_status": "NOT_COMPARED", "semantic_status": "NOT_CHECKED", "evidence_refs": []},
                     "findings": []})
    for index, formal in enumerate(unbound):
        rows.append({"file_key": f"unresolved:{index}", "view": formal["view"],
                     "display_name": Path(formal.get("published_path") or formal.get("source_path") or "").name,
                     "identity_status": "UNRESOLVED", "identity_evidence": "FORMAL_SOURCE_UNBOUND",
                     "occurrences": [], "formal_usage": formal,
                     "comparison": {"base_version": base_version, "target_version": target_version,
                                    "base_presence": "UNKNOWN", "target_presence": "UNKNOWN",
                                    "content_status": "NOT_COMPARED", "semantic_status": "NOT_CHECKED", "evidence_refs": []},
                     "findings": []})
    coverage = ("NOT_AVAILABLE" if not version_ids else "COMPLETE" if all(
        (inventory_by_id.get(v) or {}).get("status") == "COMPLETE" for v in version_ids) else "PARTIAL")
    return {"schema_version": "file_version_projection.v1", "library_id": library_id,
            "scope": {"base_version": base_version, "target_version": target_version,
                      "formal_stage": formal_stage, "registered_versions": version_ids},
            "coverage": {"raw_inventory": coverage, "raw_freshness": "NOT_VERIFIED",
                         "formal_inventory": "SNAPSHOT_ONLY" if formal_files is not None else "NOT_AVAILABLE",
                         "content_comparison": "NOT_COMPARED"},
            "unbound_formal_files": unbound, "files": rows,
            "summary": {"file_count": len(rows), "not_compared": len(rows),
                        "unresolved_identity": sum(row["identity_status"] != "EXACT_RELATIVE_PATH" for row in rows)}}
