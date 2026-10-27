"""Read-only projection of Formal NL LEFs against registered RAW deliveries."""

from __future__ import annotations

from datetime import datetime
import os
from pathlib import Path
import re
from typing import Any

from .effective_file_tracker import _view_for_path, _view_relative_key, longest_registered_path_match

TRACKED_VIEWS = frozenset({"lef", "liberty", "db", "gds", "oas", "verilog", "cdl", "spice"})

_MAX_DIRECTORIES = 200
_MAX_ENTRIES = 2000
_MAX_DEPTH = 8


def _resolved(value: Any) -> Path | None:
    raw = str(value or "").strip()
    return Path(raw).expanduser().resolve(strict=False) if raw else None


def _version_date(version_id: str) -> datetime | None:
    match = re.search(r"(?<!\d)(20\d{6})(?!\d)", version_id)
    if not match:
        return None
    try:
        return datetime.strptime(match.group(1), "%Y%m%d")
    except ValueError:
        return None


def _path_identity(relative_path: str, view: str) -> tuple[str, tuple[str, ...]]:
    return _view_relative_key(relative_path, view)


def _scan_registered_raw(registered_versions: list[dict[str, Any]], views: frozenset[str]) -> list[dict[str, Any]]:
    inventories: list[dict[str, Any]] = []
    for version in registered_versions:
        version_id = str(version.get("id") or "")
        root = _resolved(version.get("path"))
        files: list[str] = []
        errors: list[str] = []
        status = "COMPLETE"
        if root is None or not root.is_dir():
            status = "INCOMPLETE"
            errors.append("VERSION_ROOT_UNAVAILABLE")
        else:
            visited = 0
            directories = 0

            def onerror(error: OSError) -> None:
                errors.append("ACCESS_ERROR")

            for current, dirs, names in os.walk(root, followlinks=False, onerror=onerror):
                directories += 1
                relative_dir = Path(current).relative_to(root)
                symlink_dirs = [name for name in dirs if (Path(current) / name).is_symlink()]
                if symlink_dirs:
                    errors.append("SYMLINK_DIRECTORY_NOT_FOLLOWED")
                dirs[:] = sorted(name for name in dirs if name not in symlink_dirs)
                if directories > _MAX_DIRECTORIES or len(relative_dir.parts) > _MAX_DEPTH:
                    status = "PARTIAL"
                    errors.append("LIMIT")
                    break
                for name in sorted(names):
                    visited += 1
                    item = Path(current) / name
                    if _view_for_path(item.relative_to(root)) in views:
                        try:
                            resolved_item = item.resolve(strict=True)
                            resolved_item.relative_to(root)
                            files.append(str(resolved_item))
                        except (OSError, ValueError):
                            errors.append("SOURCE_UNAVAILABLE")
                    if visited >= _MAX_ENTRIES:
                        status = "PARTIAL"
                        errors.append("LIMIT")
                        break
                if status == "PARTIAL":
                    break
            if errors and status == "COMPLETE":
                status = "INCOMPLETE"
        inventories.append({
            "version_id": version_id,
            "root": str(root) if root else "",
            "files": sorted(set(files)),
            "status": status,
            "errors": sorted(set(errors)),
        })
    return inventories


def scan_registered_raw_lefs(registered_versions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Compatibility entry point for LEF-only inventory."""
    return _scan_registered_raw(registered_versions, frozenset({"lef"}))


def scan_registered_raw_files(registered_versions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Inventory supported views without reading file contents."""
    return _scan_registered_raw(registered_versions, TRACKED_VIEWS)


def build_lef_file_status(
    formal_files: list[dict[str, Any]],
    registered_versions: list[dict[str, Any]],
    raw_lef_inventory: list[dict[str, Any]],
    *,
    context: dict[str, Any],
    include_raw_only: bool = False,
) -> dict[str, Any]:
    """Build a cacheable observation; it never establishes content or release status."""
    versions_by_root: dict[Path, list[dict[str, Any]]] = {}
    for version in registered_versions:
        root = _resolved(version.get("path"))
        if root is not None:
            versions_by_root.setdefault(root, []).append(version)

    inventory_by_id = {str(item.get("version_id") or ""): item for item in raw_lef_inventory}
    raw_scope_status = "COMPLETE"
    if not registered_versions:
        raw_scope_status = "NOT_REGISTERED"
    elif any(item.get("status") != "COMPLETE" for item in raw_lef_inventory):
        raw_scope_status = "PARTIAL" if any(item.get("status") == "PARTIAL" for item in raw_lef_inventory) else "INCOMPLETE"

    dated_versions = [(version, _version_date(str(version.get("id") or "")))
                      for version in registered_versions]
    dates = [date for _, date in dated_versions]
    ordering_known = bool(dates) and all(date is not None for date in dates) and len(set(dates)) == len(dates)
    ordered_versions = ([version for version, _ in sorted(dated_versions, key=lambda item: item[1])]
                        if ordering_known else [])
    order_index = {str(version.get("id") or ""): index
                   for index, version in enumerate(ordered_versions)}

    raw_index: dict[tuple[str, tuple[str, ...]], dict[str, list[str]]] = {}
    for version in registered_versions:
        version_id = str(version.get("id") or "")
        root = _resolved(version.get("path"))
        if root is None:
            continue
        for raw_path in (inventory_by_id.get(version_id) or {}).get("files") or []:
            candidate = _resolved(raw_path)
            if candidate is None:
                continue
            try:
                relative = candidate.relative_to(root).as_posix()
            except ValueError:
                continue
            view = _view_for_path(Path(relative))
            raw_index.setdefault(_path_identity(relative, view), {}).setdefault(version_id, []).append(str(candidate))

    rows: list[dict[str, Any]] = []
    for formal in formal_files:
        view = str(formal.get("view") or "").casefold()
        published_path = str(formal.get("published_path") or formal.get("relative_path") or "")
        source_path = str(formal.get("source_path") or "")
        source = _resolved(source_path)
        candidates = [(root, owner) for root, owners in versions_by_root.items() for owner in owners]
        matched, ambiguous = (longest_registered_path_match(source, candidates)
                              if source is not None else (None, False))
        if ambiguous:
            identity_status = "AMBIGUOUS_SOURCE"
            source_version = ""
            relative_source = ""
        elif matched is None:
            identity_status = "UNREGISTERED_SOURCE"
            source_version = ""
            relative_source = ""
        else:
            root, owner = matched
            source_version = str(owner.get("id") or "")
            try:
                relative_source = source.relative_to(root).as_posix()
                identity_status = "UNIQUE"
            except ValueError:
                relative_source = ""
                identity_status = "UNREGISTERED_SOURCE"

        identity = _path_identity(relative_source, view) if relative_source else None
        related: list[dict[str, Any]] = []
        duplicate_key = False
        if identity is not None:
            for version in registered_versions:
                version_id = str(version.get("id") or "")
                occurrences = raw_index.get(identity, {}).get(version_id, [])
                if len(occurrences) > 1:
                    duplicate_key = True
                elif occurrences:
                    related.append({"delivery_label": version_id, "source_path": occurrences[0],
                                    "record_status": "APPEARED"})
        if duplicate_key:
            identity_status = "AMBIGUOUS"

        related_by_id = {item["delivery_label"]: item for item in related}
        source_record = related_by_id.get(source_version)
        if source_record is None and identity_status == "UNIQUE":
            identity_status = "SOURCE_FILE_NOT_IN_RAW_INVENTORY"

        recent_raw_source = None
        older_source = None
        if ordering_known and source_version in order_index and identity_status == "UNIQUE":
            base_index = order_index[source_version]
            later = [item for item in related if order_index.get(item["delivery_label"], -1) > base_index]
            earlier = [item for item in related if order_index.get(item["delivery_label"], -1) < base_index]
            if later:
                recent_raw_source = max(later, key=lambda item: order_index[item["delivery_label"]])
            if earlier:
                older_source = max(earlier, key=lambda item: order_index[item["delivery_label"]])
            relation = "LATER_DELIVERY_HINT" if recent_raw_source else (
                "NO_LATER_DELIVERY_HINT" if raw_scope_status == "COMPLETE" else "UNDETERMINED")
            history = sorted(related, key=lambda item: order_index[item["delivery_label"]], reverse=True)[:5]
        else:
            relation = "UNDETERMINED"
            history = [{**item, "order_status": "UNDETERMINED"} for item in related[:5]]
        rows.append({
            "view": view,
            "file_key": "/".join(identity[1]) if identity else "",
            "display_name": Path(published_path or source_path).name or "未命名 LEF",
            "identity_status": identity_status,
            "nl_source": {"published_path": published_path, "source_path": source_path,
                          "delivery_label": source_version or None},
            "recent_raw_source": recent_raw_source,
            "older_observed_source": older_source,
            "accepted_effective_source": None,
            "delivery_relation": relation,
            "effective_relation": "NOT_CONFIGURED",
            "content_check": "NOT_RUN",
            "compare_evidence": None,
            "history": history,
            "warnings": list(formal.get("warnings") or []),
        })

    if include_raw_only:
        known = {(row["view"], row["file_key"]) for row in rows if row["file_key"]}
        groups: dict[tuple[str, str], list[dict[str, str]]] = {}
        for (view, parts), versions in raw_index.items():
            key = "/".join(parts)
            if view not in TRACKED_VIEWS or (view, key) in known:
                continue
            for version_id, paths in versions.items():
                for path in paths:
                    groups.setdefault((view, key), []).append({"delivery_label": version_id,
                                                                "source_path": path,
                                                                "record_status": "APPEARED"})
        for (view, key), records in groups.items():
            unique_versions = len({item["delivery_label"] for item in records}) == len(records)
            ordered = sorted(records, key=lambda item: order_index[item["delivery_label"]], reverse=True) if ordering_known else records
            candidate = ordered[0] if ordering_known and unique_versions else None
            rows.append({"view": view, "file_key": key, "display_name": Path(key).name,
                         "identity_status": "RAW_UNMATCHED" if unique_versions else "AMBIGUOUS",
                         "nl_source": {"published_path": "", "source_path": "", "delivery_label": None},
                         "recent_raw_source": candidate, "older_observed_source": None,
                         "accepted_effective_source": None, "delivery_relation": "RAW_ONLY",
                         "effective_relation": "NOT_CONFIGURED", "content_check": "NOT_RUN",
                         "compare_evidence": None, "history": ordered[:5], "warnings": []})

    rows.sort(key=lambda row: (row["display_name"].casefold(), row["file_key"].casefold(),
                               row["nl_source"]["published_path"].casefold()))
    return {
        "schema_version": "lef_file_status.v1",
        "library_id": str(context.get("library_id") or ""),
        "nl_context": {"stage": str(context.get("stage") or ""),
                       "root": str(context.get("root") or ""),
                       "snapshot_generated_at": str(context.get("snapshot_generated_at") or ""),
                       "status": str(context.get("status") or "UNKNOWN")},
        "raw_scope": {"registered_deliveries": len(registered_versions),
                      "scan_status": raw_scope_status,
                      "ordering_basis": "DATE_HINT" if ordering_known else "UNKNOWN"},
        "files": rows,
    }


def build_file_status(formal_files: list[dict[str, Any]], registered_versions: list[dict[str, Any]],
                      raw_inventory: list[dict[str, Any]], *, context: dict[str, Any]) -> dict[str, Any]:
    return build_lef_file_status(formal_files, registered_versions, raw_inventory,
                                 context=context, include_raw_only=True)
