"""Build a read-only file/version projection from explicitly supplied inventories."""

from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import Any, Callable
from uuid import uuid4

from .effective_file_tracker import _view_for_path, _view_relative_key, longest_registered_path_match
from .file_status import TRACKED_VIEWS


def _identity(relative: str, view: str) -> tuple[str, tuple[str, ...]]:
    """Drop known view wrappers without case-folding file identities."""
    _, normalized_parts = _view_relative_key(relative, view)
    parts = Path(relative).parts
    return view, tuple(parts[-len(normalized_parts):]) if normalized_parts else ()


def _version_date(version: dict[str, Any]) -> str | None:
    value = str(version.get("delivery_date") or version.get("date") or version.get("id") or "")
    match = re.search(r"(?<!\d)(20\d{2})[-/]?(\d{2})[-/]?(\d{2})(?!\d)", value)
    if not match:
        return None
    try:
        return datetime.strptime("".join(match.groups()), "%Y%m%d").date().isoformat()
    except ValueError:
        return None


def resolve_version_order(versions: list[dict[str, Any]]) -> dict[str, Any]:
    """Resolve only explicit delivery order or unique date hints.

    Registry order, path names without a date, filesystem mtime, and scan time
    are intentionally excluded because they do not prove delivery order.
    """
    ids = [str(item.get("id") or "") for item in versions]
    warnings: list[str] = []
    explicit = [item.get("delivery_order") for item in versions]
    if ids and all(value is not None and str(value) != "" for value in explicit):
        try:
            if any(isinstance(value, bool) or not re.fullmatch(r"[+-]?\d+", str(value).strip()) for value in explicit):
                raise ValueError("invalid order")
            pairs = list(zip(ids, [int(str(value).strip()) for value in explicit]))
            values = [value for _, value in pairs]
            if len(set(values)) != len(values):
                raise ValueError("duplicate")
            ordered = [item_id for item_id, _ in sorted(pairs, key=lambda pair: pair[1])]
            return {"status": "KNOWN", "basis": "EXPLICIT", "ordered_ids": ordered, "warnings": []}
        except (TypeError, ValueError):
            return {"status": "UNKNOWN", "basis": "UNKNOWN", "ordered_ids": [], "warnings": ["EXPLICIT_ORDER_INVALID"]}
    elif any(value is not None and str(value) != "" for value in explicit):
        return {"status": "UNKNOWN", "basis": "UNKNOWN", "ordered_ids": [], "warnings": ["EXPLICIT_ORDER_INCOMPLETE"]}

    if len(ids) == 1:
        return {"status": "KNOWN", "basis": "SINGLE", "ordered_ids": ids, "warnings": []}

    dated = [(item_id, _version_date(version)) for item_id, version in zip(ids, versions)]
    dates = [value for _, value in dated]
    if ids and all(value is not None for value in dates) and len(set(dates)) == len(dates):
        ordered = [item_id for item_id, _ in sorted(dated, key=lambda pair: pair[1])]
        return {"status": "KNOWN", "basis": "DATE_HINT", "ordered_ids": ordered, "warnings": warnings}
    if len(set(value for value in dates if value is not None)) != len([value for value in dates if value is not None]):
        warnings.append("DATE_HINT_DUPLICATE")
    elif any(value is None for value in dates):
        warnings.append("DATE_HINT_MISSING")
    return {"status": "UNKNOWN", "basis": "UNKNOWN", "ordered_ids": [], "warnings": warnings}


def rank_occurrences(occurrences: list[dict[str, Any]], version_order: dict[str, Any],
                     inventories: dict[str, dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return latest/previous without treating an incomplete later scan as absence."""
    if version_order.get("status") != "KNOWN":
        return ({"status": "UNKNOWN_ORDER", "occurrences": occurrences},
                {"status": "UNKNOWN_ORDER", "occurrences": occurrences})
    order_index = {version: index for index, version in enumerate(version_order.get("ordered_ids") or [])}
    unique: dict[str, dict[str, Any]] = {}
    for occurrence in occurrences:
        version = str(occurrence.get("version") or "")
        if version in order_index and version not in unique:
            unique[version] = occurrence
    ordered = sorted(unique, key=order_index.get, reverse=True)
    if not ordered:
        status = "NONE" if all(item.get("status") == "COMPLETE" for item in inventories.values()) else "UNKNOWN_COVERAGE"
        empty = {"status": status}
        return empty, {"status": "NONE" if status == "NONE" else "UNKNOWN_COVERAGE"}
    observed_latest = unique[ordered[0]]
    uncertain_later = any(
        item.get("status") != "COMPLETE" and order_index.get(version, -1) > order_index[ordered[0]]
        for version, item in inventories.items()
    )
    status = "UNKNOWN_COVERAGE" if uncertain_later else "CONFIRMED"
    latest = {"status": status, "version": ordered[0], "source_path": observed_latest.get("source_path")}
    if len(ordered) < 2:
        uncertain_earlier = any(item.get("status") != "COMPLETE" and order_index.get(version, -1) < order_index[ordered[0]]
                                for version, item in inventories.items() if version in order_index)
        previous = {"status": "UNKNOWN_COVERAGE" if uncertain_later or uncertain_earlier else "NONE"}
    else:
        observed_previous = unique[ordered[1]]
        uncertain_versions = [version for version, item in inventories.items() if item.get("status") != "COMPLETE" and order_index[ordered[1]] < order_index.get(version, -1) < order_index[ordered[0]]]
        uncertain_between = bool(uncertain_versions)
        previous = {"status": "UNKNOWN_COVERAGE" if uncertain_later or uncertain_between else "CONFIRMED", "version": ordered[1], "source_path": observed_previous.get("source_path")}
        if uncertain_versions:
            previous["uncertain_versions"] = uncertain_versions
    return latest, previous


def derive_file_capabilities(row: dict[str, Any]) -> dict[str, Any]:
    """Expose safe actions independently from the row's delivery identity."""
    comparison = row.get("comparison") or {}
    occurrences = row.get("occurrences") or []
    identity = str(row.get("identity_status") or "")
    latest = row.get("latest") or {}
    locatable = bool(
        (latest.get("source_path") or (latest.get("occurrences") or [])
         or (row.get("previous") or {}).get("source_path")
         or any(item.get("source_path") for item in occurrences))
        and identity != "AMBIGUOUS"
    )
    content_comparable = bool(
        identity == "EXACT_RELATIVE_PATH"
        and comparison.get("base_presence") == "PRESENT"
        and comparison.get("target_presence") == "PRESENT"
        and comparison.get("base_version")
        and comparison.get("target_version")
    )
    single_target = bool(
        latest.get("status") == "CONFIRMED" and latest.get("version") and latest.get("source_path")
    )
    lef_checkable = bool(
        str(row.get("view") or "") == "lef"
        and locatable
        and (content_comparable or (not comparison.get("base_version") and single_target))
    )
    if not locatable:
        reason = "NO_UNIQUE_RAW_SOURCE"
    elif not comparison.get("base_version") or not comparison.get("target_version"):
        reason = "BASE_TARGET_REQUIRED"
    elif not content_comparable:
        reason = "PAIR_NOT_CONFIRMED" if comparison.get("base_version") else "ORDER_REQUIRED"
    elif str(row.get("view") or "") != "lef":
        reason = "VIEW_NOT_LEF"
    else:
        reason = ""
    return {"locatable": locatable, "content_comparable": content_comparable,
            "lef_checkable": lef_checkable, "reason": reason}


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

    version_order = resolve_version_order(versions)
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
        latest, previous = rank_occurrences(occurrences, version_order, inventory_by_id)
        if any(count > 1 for count in counts):
            latest = {"status": "AMBIGUOUS", "occurrences": occurrences}
            previous = {"status": "AMBIGUOUS", "occurrences": occurrences}
        display_path = (formal[0].get("published_path") if len(formal) == 1 else "") or (
            occurrences[0].get("source_path") if occurrences else "") or (parts[-1] if parts else "")
        if not base_version or not target_version:
            delivery_relation = "NOT_SELECTED"
        elif identities == "AMBIGUOUS":
            delivery_relation = "AMBIGUOUS"
        elif presence(base_version, occurrences) == presence(target_version, occurrences) == "PRESENT":
            delivery_relation = "READY_TO_COMPARE" if identities == "EXACT_RELATIVE_PATH" else "CANDIDATE_MATCH"
        elif presence(base_version, occurrences) == "ABSENT_VERIFIED" and presence(target_version, occurrences) == "PRESENT":
            delivery_relation = "NEWLY_PROVIDED"
        elif presence(base_version, occurrences) == "PRESENT" and presence(target_version, occurrences) == "ABSENT_VERIFIED":
            delivery_relation = "NOT_PROVIDED_IN_TARGET"
        elif presence(base_version, occurrences) == presence(target_version, occurrences) == "ABSENT_VERIFIED":
            delivery_relation = "NOT_PROVIDED_BOTH"
        else:
            delivery_relation = "UNKNOWN_COVERAGE"
        rows.append({"file_key": view + ":" + "/".join(parts), "view": view,
                     "display_name": Path(display_path).name, "identity_status": identities,
                     "identity_evidence": "VIEW_AND_RELATIVE_PATH", "occurrences": occurrences,
                     "latest": latest, "previous": previous,
                     "formal_usage": formal[0] if len(formal) == 1 else {
                         "observation_status": "AMBIGUOUS" if formal else ("UNKNOWN" if formal_files is None else "NOT_OBSERVED"),
                         "approved_effective_status": "NOT_CONFIGURED"},
                     "comparison": {"base_version": base_version, "target_version": target_version,
                                    "base_presence": presence(base_version, occurrences),
                                    "target_presence": presence(target_version, occurrences),
                                    "delivery_relation": delivery_relation,
                                    "content_status": "NOT_COMPARED", "semantic_status": "NOT_CHECKED", "evidence_refs": []},
                     "findings": []})
    for index, formal in enumerate(unbound):
        rows.append({"file_key": f"unresolved:{index}", "view": formal["view"],
                     "display_name": Path(formal.get("published_path") or formal.get("source_path") or "").name,
                     "identity_status": "UNRESOLVED", "identity_evidence": "FORMAL_SOURCE_UNBOUND",
                     "occurrences": [], "latest": {"status": "NONE"}, "previous": {"status": "NONE"},
                     "formal_usage": formal,
                     "comparison": {"base_version": base_version, "target_version": target_version,
                                    "base_presence": "UNKNOWN", "target_presence": "UNKNOWN",
                                    "delivery_relation": "UNKNOWN_COVERAGE",
                                    "content_status": "NOT_COMPARED", "semantic_status": "NOT_CHECKED", "evidence_refs": []},
                     "findings": []})
    coverage = ("NOT_AVAILABLE" if not version_ids else "COMPLETE" if all(
        (inventory_by_id.get(v) or {}).get("status") == "COMPLETE" for v in version_ids) else "PARTIAL")
    for row in rows:
        row["capabilities"] = derive_file_capabilities(row)
    return {"schema_version": "file_version_projection.v1", "library_id": library_id,
            "scope": {"base_version": base_version, "target_version": target_version,
                      "formal_stage": formal_stage, "registered_versions": version_ids,
                      "inventory_status": {version_id: (inventory_by_id.get(version_id) or {}).get("status", "UNKNOWN")
                                           for version_id in version_ids}},
            "version_order": version_order,
            "coverage": {"raw_inventory": coverage, "raw_freshness": "NOT_VERIFIED",
                         "formal_inventory": "SNAPSHOT_ONLY" if formal_files is not None else "NOT_AVAILABLE",
                         "content_comparison": "NOT_COMPARED"},
            "unbound_formal_files": unbound, "files": rows,
            "summary": {"file_count": len(rows), "not_compared": len(rows),
                        "unresolved_identity": sum(row["identity_status"] != "EXACT_RELATIVE_PATH" for row in rows)}}


def reproject_projection(projection: dict[str, Any], *, base_version: str = "",
                         target_version: str = "") -> dict[str, Any]:
    """Change only the delivery scope using an existing immutable inventory.

    This deliberately does not inspect the filesystem.  The caller can publish the
    returned view as a new projection snapshot while retaining ``source_snapshot_id``
    as the RAW inventory evidence that was actually scanned.
    """
    result = deepcopy(projection)
    scope = result.setdefault("scope", {})
    scope_changed = (str(scope.get("base_version") or ""), str(scope.get("target_version") or "")) != (base_version, target_version)
    registered = [str(value or "") for value in scope.get("registered_versions") or []]
    if any(value and value not in registered for value in (base_version, target_version)):
        raise ValueError("基准或目标版本未登记")
    source_snapshot_id = str(result.get("source_snapshot_id") or result.get("snapshot_id") or "")
    if source_snapshot_id:
        result["source_snapshot_id"] = source_snapshot_id
    if result.get("snapshot_id"):
        result["input_snapshot_id"] = result["snapshot_id"]
    scope["base_version"] = base_version
    scope["target_version"] = target_version
    inventory_status = {str(key): str(value or "UNKNOWN")
                        for key, value in (scope.get("inventory_status") or {}).items()}

    def presence(version: str, occurrences: list[dict[str, Any]]) -> str:
        if not version:
            return "NOT_SELECTED"
        if any(str(item.get("version") or "") == version for item in occurrences):
            return "PRESENT"
        return "ABSENT_VERIFIED" if inventory_status.get(version) == "COMPLETE" else "UNKNOWN"

    version_order = result.get("version_order") or {"status": "UNKNOWN", "ordered_ids": []}
    for row in result.get("files") or []:
        occurrences = row.get("occurrences") or []
        counts = [sum(str(item.get("version") or "") == version for item in occurrences)
                  for version in registered]
        formal = row.get("formal_usage") or {}
        formal_ambiguous = str(formal.get("observation_status") or "") == "AMBIGUOUS"
        if any(count > 1 for count in counts) or formal_ambiguous:
            identities = "AMBIGUOUS"
        elif not base_version or not target_version:
            identities = "OBSERVED_PATH"
        elif presence(base_version, occurrences) == presence(target_version, occurrences) == "PRESENT":
            identities = "EXACT_RELATIVE_PATH"
        else:
            identities = "UNRESOLVED"
        base_presence = presence(base_version, occurrences)
        target_presence = presence(target_version, occurrences)
        if not base_version or not target_version:
            delivery_relation = "NOT_SELECTED"
        elif identities == "AMBIGUOUS":
            delivery_relation = "AMBIGUOUS"
        elif base_presence == target_presence == "PRESENT":
            delivery_relation = "READY_TO_COMPARE" if identities == "EXACT_RELATIVE_PATH" else "CANDIDATE_MATCH"
        elif base_presence == "ABSENT_VERIFIED" and target_presence == "PRESENT":
            delivery_relation = "NEWLY_PROVIDED"
        elif base_presence == "PRESENT" and target_presence == "ABSENT_VERIFIED":
            delivery_relation = "NOT_PROVIDED_IN_TARGET"
        elif base_presence == target_presence == "ABSENT_VERIFIED":
            delivery_relation = "NOT_PROVIDED_BOTH"
        else:
            delivery_relation = "UNKNOWN_COVERAGE"
        comparison = row.setdefault("comparison", {})
        if scope_changed:
            for key in ("comparison_evidence", "comparison_mode", "comparison_reason", "unverified"):
                comparison.pop(key, None)
            comparison.update({"content_status": "NOT_COMPARED", "semantic_status": "NOT_CHECKED", "evidence_refs": []})
            row["findings"] = []
        comparison.update({"base_version": base_version, "target_version": target_version,
                           "base_presence": base_presence, "target_presence": target_presence,
                           "delivery_relation": delivery_relation})
        row["identity_status"] = identities
        row["identity_evidence"] = "VIEW_AND_RELATIVE_PATH"
        row["capabilities"] = derive_file_capabilities(row)
    if scope_changed:
        result["coverage"] = {**(result.get("coverage") or {}), "content_comparison": "NOT_COMPARED"}
        result.setdefault("summary", {}).pop("content_compared", None)
        result.setdefault("summary", {}).pop("last_comparison", None)
    result["summary"] = {**(result.get("summary") or {}),
                          "file_count": len(result.get("files") or []),
                          "not_compared": sum(row.get("comparison", {}).get("content_status") == "NOT_COMPARED" for row in result.get("files") or []),
                          "unresolved_identity": sum(row.get("identity_status") != "EXACT_RELATIVE_PATH"
                                                     for row in result.get("files") or [])}
    return result
