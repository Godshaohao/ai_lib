from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping
from collections import Counter
import hashlib
import json

from lib_guard.project_config import BINARY_METADATA_ONLY_TYPES, DEFAULT_FILE_DIFF_TYPES, SUMMARY_ONLY_TYPES

from .pairwise import build_pairwise_diff_tasks, build_pairwise_task_status


METADATA_ONLY_TYPES = set(BINARY_METADATA_ONLY_TYPES)
SUMMARY_ONLY_DIFF_TYPES = set(SUMMARY_ONLY_TYPES)
RELEASE_EVIDENCE_TYPES = {"doc", "waiver"}


REQUIRED_SCAN_FILES = [
    "scan_meta.json",
    "manifest.json",
    "file_inventory.json",
    "parser_manifest.json",
    "parser_results",
    "summary/parser_quality.json",
    "summary/release_readiness.json",
    "signatures",
    "scan_issues.json",
]


def _utc_now() -> str:
    return datetime.now(tz=timezone.utc).isoformat().replace("+00:00", "Z")


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")


def _snapshot_digest(scan_meta: Mapping[str, Any], file_inventory: Mapping[str, Any]) -> tuple[str, str]:
    for evidence in (scan_meta, file_inventory):
        identity = evidence.get("snapshot_identity")
        if not isinstance(identity, Mapping):
            continue
        digest = identity.get("digest")
        if isinstance(digest, str) and digest:
            return digest, "snapshot_identity"
    for evidence in (scan_meta, file_inventory):
        fingerprint = evidence.get("input_fingerprint")
        if not isinstance(fingerprint, Mapping):
            continue
        digest = fingerprint.get("hash")
        if isinstance(digest, str) and digest:
            return digest, "input_fingerprint_fallback"
    return "", "missing_evidence"


def _diff_identity_provenance(old_source: str, new_source: str) -> tuple[str, str, str, dict[str, dict[str, str]]]:
    trust_by_source = {
        "snapshot_identity": "TRUSTED",
        "input_fingerprint_fallback": "LEGACY_FALLBACK",
        "missing_evidence": "UNAVAILABLE",
    }
    identity_sources = {
        "old": {"source": old_source, "trust": trust_by_source[old_source]},
        "new": {"source": new_source, "trust": trust_by_source[new_source]},
    }
    if "missing_evidence" in {old_source, new_source}:
        return "UNAVAILABLE", "missing_evidence", "UNAVAILABLE", identity_sources
    if old_source == new_source == "snapshot_identity":
        return "TRUSTED", "snapshot_identity", "HOMOGENEOUS_TRUSTED", identity_sources
    if old_source == new_source == "input_fingerprint_fallback":
        return "LEGACY_FALLBACK", "input_fingerprint_fallback", "HOMOGENEOUS_LEGACY_FALLBACK", identity_sources
    return "MIXED_EVIDENCE", "mixed_evidence", "NON_HOMOGENEOUS", identity_sources


def _stable_hash(data: Any) -> str:
    raw = json.dumps(data, sort_keys=True, ensure_ascii=False, default=str, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _scan_file_hash(scan: Path, rel: str) -> str | None:
    path = scan / rel
    if not path.exists() or not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _file_key(item: Mapping[str, Any]) -> str:
    return str(item.get("path") or item.get("file") or item.get("rel_path") or "")


def _strip_path_fields(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(k): _strip_path_fields(v)
            for k, v in value.items()
            if str(k) not in {"source", "abs_path", "file", "path", "root_path", "out_dir"}
        }
    if isinstance(value, list):
        return [_strip_path_fields(item) for item in value]
    return value


def _parser_result_signatures(scan: Path) -> dict[str, str]:
    manifest = _read_json(scan / "parser_manifest.json", {"files": []}) or {}
    out: dict[str, str] = {}
    for item in manifest.get("files", []) or []:
        path = str(item.get("file") or "")
        if not path:
            continue
        task_signatures: list[dict[str, Any]] = []
        for task in item.get("parser_tasks", []) or []:
            rel = task.get("result_path")
            if not rel:
                continue
            result = _read_json(scan / str(rel), {}) or {}
            task_signatures.append(
                {
                    "parser_name": result.get("parser_name") or task.get("parser_name"),
                    "parser_version": result.get("parser_version") or task.get("parser_version"),
                    "status": result.get("status") or task.get("result_status") or task.get("status"),
                    "stats": result.get("stats"),
                    "data": _strip_path_fields(result.get("data")),
                    "issues": _strip_path_fields(result.get("issues")),
                }
            )
        if task_signatures:
            out[path] = "parser:" + _stable_hash(task_signatures)
    return out


def _content_signature(item: Mapping[str, Any]) -> Any:
    return item.get("hash") or item.get("semantic_signature")


def _file_signature(item: Mapping[str, Any]) -> tuple[Any, Any, Any]:
    return (item.get("file_type"), item.get("size_bytes"), _content_signature(item))


def _logical_file_key(path: str) -> str:
    parts = [part for part in str(path or "").replace("\\", "/").split("/") if part]
    if len(parts) <= 1:
        return "/".join(parts)
    wrapper = parts[0].lower()
    if (
        wrapper == "source_package"
        or wrapper.endswith("_source_package")
        or wrapper.startswith("upstream_")
    ):
        return "/".join(parts[1:])
    return "/".join(parts)


def _path_root(path: str) -> str:
    parts = [part for part in str(path or "").replace("\\", "/").split("/") if part]
    return parts[0] if parts else "-"


def _root_counts(items: Mapping[str, Mapping[str, Any]]) -> Counter[str]:
    return Counter(_path_root(path) for path in items)


def _unique_logical_index(items: Mapping[str, Mapping[str, Any]]) -> dict[str, str]:
    logical_to_paths: dict[str, list[str]] = {}
    for path in items:
        logical_to_paths.setdefault(_logical_file_key(path), []).append(path)
    return {logical: paths[0] for logical, paths in logical_to_paths.items() if len(paths) == 1}


def _inventory_index(scan: Path) -> dict[str, dict[str, Any]]:
    inventory = _read_json(scan / "file_inventory.json", {"files": []}) or {}
    parser_signatures = _parser_result_signatures(scan)
    out: dict[str, dict[str, Any]] = {}
    for item in inventory.get("files", []) or []:
        key = _file_key(item)
        if not key:
            continue
        row = dict(item)
        if parser_signatures.get(key):
            row["semantic_signature"] = parser_signatures[key]
        out[key] = row
    return out


def _scan_support(scan: Path) -> dict[str, Any]:
    missing = []
    for rel in REQUIRED_SCAN_FILES:
        if not (scan / rel).exists():
            missing.append(rel)
    return {
        "scan_dir": str(scan),
        "missing": missing,
        "supports_parser_v2_diff": (scan / "parser_results").exists() and (scan / "parser_manifest.json").exists(),
        "supports_release_readiness_diff": (scan / "summary" / "release_readiness.json").exists(),
    }


def _changed_files(old_items: dict[str, dict[str, Any]], new_items: dict[str, dict[str, Any]]) -> list[str]:
    changed: list[str] = []
    for key in sorted(set(old_items) & set(new_items)):
        if _file_signature(old_items[key]) != _file_signature(new_items[key]):
            changed.append(key)
    return changed


def _moved_files(
    old_items: dict[str, dict[str, Any]],
    new_items: dict[str, dict[str, Any]],
    *,
    exclude_old: set[str] | None = None,
    exclude_new: set[str] | None = None,
) -> list[dict[str, Any]]:
    excluded_old = set(exclude_old or set())
    excluded_new = set(exclude_new or set())
    old_by_hash: dict[str, list[str]] = {}
    for path, item in old_items.items():
        if path in excluded_old:
            continue
        digest = str(item.get("hash") or "")
        if digest:
            old_by_hash.setdefault(digest, []).append(path)
    used_old: set[str] = set()
    moved = []
    for new_path, new in sorted(new_items.items()):
        if new_path in excluded_new:
            continue
        digest = str(new.get("hash") or "")
        candidates = [
            old_path
            for old_path in old_by_hash.get(digest, [])
            if old_path not in used_old and old_path != new_path and old_path not in new_items
        ]
        if candidates:
            basename = Path(new_path).name
            old_path = next((path for path in candidates if Path(path).name == basename), candidates[0])
            used_old.add(old_path)
            moved.append({"old": old_path, "new": new_path, "hash": digest, "reason": "hash_match"})
    return moved


def _package_root_migrations(
    old_items: Mapping[str, Mapping[str, Any]],
    new_items: Mapping[str, Mapping[str, Any]],
    logical_pairs: list[dict[str, Any]],
    *,
    raw_added: set[str],
    raw_removed: set[str],
) -> list[dict[str, Any]]:
    old_counts = _root_counts(old_items)
    new_counts = _root_counts(new_items)
    by_pair: dict[tuple[str, str], dict[str, Any]] = {}
    for pair in logical_pairs:
        old_path = str(pair.get("old") or "")
        new_path = str(pair.get("new") or "")
        old_root = _path_root(old_path)
        new_root = _path_root(new_path)
        if not old_path or not new_path or old_root == new_root or old_root == "-" or new_root == "-":
            continue
        key = (old_root, new_root)
        row = by_pair.setdefault(
            key,
            {
                "old_root": old_root,
                "new_root": new_root,
                "matched_logical_paths": 0,
                "changed_logical_paths": 0,
                "same_signature_paths": 0,
                "old_root_file_count": old_counts[old_root],
                "new_root_file_count": new_counts[new_root],
                "raw_added_under_new_root": sum(1 for path in raw_added if _path_root(path) == new_root),
                "raw_removed_under_old_root": sum(1 for path in raw_removed if _path_root(path) == old_root),
                "sample_mappings": [],
            },
        )
        row["matched_logical_paths"] += 1
        if pair.get("signature_changed"):
            row["changed_logical_paths"] += 1
        else:
            row["same_signature_paths"] += 1
        if len(row["sample_mappings"]) < 10:
            row["sample_mappings"].append(
                {
                    "logical_path": pair.get("logical_path"),
                    "old": old_path,
                    "new": new_path,
                    "signature_changed": bool(pair.get("signature_changed")),
                }
            )
    return sorted(by_pair.values(), key=lambda item: (-int(item["matched_logical_paths"]), str(item["old_root"]), str(item["new_root"])))


def _file_diff(old_scan: Path, new_scan: Path) -> dict[str, Any]:
    old_files = _inventory_index(old_scan)
    new_files = _inventory_index(new_scan)
    physical_old_files = dict(old_files)
    physical_new_files = dict(new_files)
    raw_added = set(new_files) - set(old_files)
    raw_removed = set(old_files) - set(new_files)
    changed = _changed_files(old_files, new_files)
    logical_path_changes: list[dict[str, Any]] = []
    logical_path_moves: list[dict[str, Any]] = []
    logical_pairs: list[dict[str, Any]] = []
    old_logical = _unique_logical_index(old_files)
    new_logical = _unique_logical_index(new_files)
    logical_changed: list[str] = []
    paired_old: set[str] = set()
    paired_new: set[str] = set()
    for logical in sorted(set(old_logical) & set(new_logical)):
        old_path = old_logical[logical]
        new_path = new_logical[logical]
        if old_path == new_path:
            continue
        old_item = old_files[old_path]
        new_item = new_files[new_path]
        signature_changed = _file_signature(old_item) != _file_signature(new_item)
        logical_pairs.append(
            {
                "logical_path": logical,
                "old": old_path,
                "new": new_path,
                "signature_changed": signature_changed,
            }
        )
        paired_old.add(old_path)
        paired_new.add(new_path)
        if not signature_changed:
            logical_path_moves.append(
                {
                    "old": old_path,
                    "new": new_path,
                    "hash": _content_signature(new_item) or _content_signature(old_item),
                    "logical_path": logical,
                    "reason": "logical_path_same_signature",
                }
            )
            continue
        logical_changed.append(logical)
        logical_path_changes.append({"logical_path": logical, "old": old_path, "new": new_path})
        old_files[logical] = {**old_item, "path": logical, "physical_path": old_path, "logical_path": logical, "abs_path": old_item.get("abs_path")}
        new_files[logical] = {**new_item, "path": logical, "physical_path": new_path, "logical_path": logical, "abs_path": new_item.get("abs_path")}
    changed = sorted(set(changed) | set(logical_changed))
    metadata_only = []
    for key in changed:
        old = old_files[key]
        new = new_files[key]
        if _content_signature(old) == _content_signature(new) and old.get("size_bytes") == new.get("size_bytes"):
            metadata_only.append(key)
    moved = logical_path_moves + _moved_files(old_files, new_files, exclude_old=paired_old, exclude_new=paired_new)
    moved_old = {str(item.get("old")) for item in moved if item.get("old")}
    moved_new = {str(item.get("new")) for item in moved if item.get("new")}
    added = sorted(raw_added - moved_new - paired_new)
    removed = sorted(raw_removed - moved_old - paired_old)
    unchanged = sorted((set(old_files) & set(new_files)) - set(changed))
    package_root_migrations = _package_root_migrations(
        physical_old_files,
        physical_new_files,
        logical_pairs,
        raw_added=raw_added,
        raw_removed=raw_removed,
    )
    package_root_migration_matched_files = sum(int(item.get("matched_logical_paths") or 0) for item in package_root_migrations)
    return {
        "schema_version": "1.0",
        "added": added,
        "removed": removed,
        "changed": changed,
        "renamed_or_moved": moved,
        "logical_path_changes": logical_path_changes,
        "package_root_migrations": package_root_migrations,
        "unchanged": unchanged,
        "metadata_only_changed": metadata_only,
        "counts": {
            "added": len(added),
            "removed": len(removed),
            "changed": len(changed),
            "renamed_or_moved": len(moved),
            "logical_path_changed": len(logical_path_changes),
            "package_root_migrations": len(package_root_migrations),
            "package_root_migration_matched_files": package_root_migration_matched_files,
            "unchanged": len(unchanged),
            "metadata_only_changed": len(metadata_only),
        },
        "by_type": {
            "old": dict(Counter(str(item.get("file_type", "unknown")) for item in old_files.values())),
            "new": dict(Counter(str(item.get("file_type", "unknown")) for item in new_files.values())),
        },
        "_old_items": old_files,
        "_new_items": new_files,
    }


def _type_counts(items: Mapping[str, Mapping[str, Any]]) -> Counter[str]:
    return Counter(str(item.get("file_type", "unknown")) for item in items.values())


def _paths_by_type(items: Mapping[str, Mapping[str, Any]]) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for path, item in items.items():
        out.setdefault(str(item.get("file_type", "unknown")), set()).add(path)
    return out


def _type_diff(file_diff: Mapping[str, Any]) -> dict[str, Any]:
    old_items = file_diff.get("_old_items") or {}
    new_items = file_diff.get("_new_items") or {}
    old_counts = _type_counts(old_items)
    new_counts = _type_counts(new_items)
    old_by_type = _paths_by_type(old_items)
    new_by_type = _paths_by_type(new_items)
    changed_by_type: Counter[str] = Counter()
    for path in file_diff.get("changed", []) or []:
        item = new_items.get(path) or old_items.get(path) or {}
        changed_by_type[str(item.get("file_type", "unknown"))] += 1
    by_type: dict[str, Any] = {}
    changed_types = 0
    added_paths = set(file_diff.get("added") or [])
    removed_paths = set(file_diff.get("removed") or [])
    moved_by_type: Counter[str] = Counter()
    for item in file_diff.get("renamed_or_moved", []) or []:
        new_path = str((item or {}).get("new") or "")
        old_path = str((item or {}).get("old") or "")
        entry = new_items.get(new_path) or old_items.get(old_path) or {}
        moved_by_type[str(entry.get("file_type", "unknown"))] += 1
    for file_type in sorted(set(old_counts) | set(new_counts) | set(changed_by_type)):
        added = sorted(path for path in added_paths if str((new_items.get(path) or {}).get("file_type", "unknown")) == file_type)
        removed = sorted(path for path in removed_paths if str((old_items.get(path) or {}).get("file_type", "unknown")) == file_type)
        changed = [p for p in file_diff.get("changed", []) or [] if str((new_items.get(p) or old_items.get(p) or {}).get("file_type", "unknown")) == file_type]
        changed_flag = bool(added or removed or changed or old_counts[file_type] + moved_by_type[file_type] != new_counts[file_type] + moved_by_type[file_type])
        if changed_flag:
            changed_types += 1
        by_type[file_type] = {
            "old_count": old_counts[file_type],
            "new_count": new_counts[file_type],
            "added_count": len(added),
            "removed_count": len(removed),
            "changed_count": len(changed),
            "moved_count": moved_by_type[file_type],
            "added": added[:50],
            "removed": removed[:50],
            "changed": changed[:50],
            "status": "CHANGED" if changed_flag else "SAME",
            "review_mode": "metadata_only" if file_type in METADATA_ONLY_TYPES else "summary_only" if file_type in SUMMARY_ONLY_DIFF_TYPES else "manual_pairwise" if file_type in DEFAULT_FILE_DIFF_TYPES else "governance",
        }
    return {
        "schema_version": "1.0",
        "status": "DIFF" if changed_types else "SAME",
        "by_type": by_type,
        "summary": {
            "old_type_count": len(old_counts),
            "new_type_count": len(new_counts),
            "changed_types": changed_types,
            "metadata_only_changed_types": len([t for t, row in by_type.items() if t in METADATA_ONLY_TYPES and row["status"] == "CHANGED"]),
        },
    }


def _readiness_view_map(scan: Path) -> dict[str, dict[str, Any]]:
    readiness = _read_json(scan / "summary" / "release_readiness.json", {}) or {}
    out: dict[str, dict[str, Any]] = {}
    for component in readiness.get("components", []) if isinstance(readiness, Mapping) else []:
        required = set(component.get("required_views") or [])
        optional = set(component.get("optional_views") or [])
        for view, result in (component.get("required_view_results") or {}).items():
            out[str(view)] = {"view": str(view), "requirement": "required", **(result if isinstance(result, Mapping) else {})}
        for view, result in (component.get("optional_view_results") or {}).items():
            out.setdefault(str(view), {"view": str(view), "requirement": "optional", **(result if isinstance(result, Mapping) else {})})
        for view in required:
            out.setdefault(str(view), {"view": str(view), "requirement": "required", "found": False, "status": "BLOCK"})
        for view in optional:
            out.setdefault(str(view), {"view": str(view), "requirement": "optional", "found": False, "status": "INFO"})
    return out


def _view_diff(old_scan: Path, new_scan: Path, type_diff: Mapping[str, Any]) -> dict[str, Any]:
    old_views = _readiness_view_map(old_scan)
    new_views = _readiness_view_map(new_scan)
    rows: list[dict[str, Any]] = []
    blockers = 0
    warnings = 0
    changed = 0
    for view in sorted(set(old_views) | set(new_views) | set(type_diff.get("by_type", {}))):
        old = old_views.get(view, {})
        new = new_views.get(view, {})
        type_row = (type_diff.get("by_type") or {}).get(view, {})
        requirement = str(new.get("requirement") or old.get("requirement") or "observed")
        row_changed = (
            old.get("found") != new.get("found")
            or old.get("status") != new.get("status")
            or old.get("parser_status") != new.get("parser_status")
        )
        severity = "info"
        if requirement == "required" and (new.get("found") is False or str(new.get("status")) == "BLOCK"):
            severity = "blocker"
            blockers += 1
        elif row_changed:
            severity = "warning"
            warnings += 1
        if row_changed:
            changed += 1
        rows.append(
            {
                "view": view,
                "requirement": requirement,
                "old_found": old.get("found"),
                "new_found": new.get("found"),
                "old_status": old.get("status"),
                "new_status": new.get("status"),
                "old_parser_status": old.get("parser_status"),
                "new_parser_status": new.get("parser_status"),
                "old_count": type_row.get("old_count", 0),
                "new_count": type_row.get("new_count", 0),
                "changed_count": type_row.get("changed_count", 0),
                "severity": severity,
                "changed": row_changed,
            }
        )
    status = "BLOCK" if blockers else "WARNING" if warnings else "PASS"
    return {"schema_version": "1.0", "status": status, "views": rows, "summary": {"total": len(rows), "changed": changed, "blockers": blockers, "warnings": warnings}}


def _evidence_role(item: Mapping[str, Any]) -> str | None:
    file_type = str(item.get("file_type") or "")
    role = str(item.get("doc_type") or item.get("role") or "")
    name = str(item.get("name") or item.get("path") or "").lower()
    if file_type == "waiver" or "waiver" in name:
        return "waiver"
    if file_type != "doc":
        return None
    if role:
        return role
    if "release" in name:
        return "release_note"
    if "readme" in name:
        return "readme"
    if "change" in name:
        return "changelog"
    return "doc"


def _release_evidence_diff(file_diff: Mapping[str, Any]) -> dict[str, Any]:
    old_items = file_diff.get("_old_items") or {}
    new_items = file_diff.get("_new_items") or {}
    roles = sorted({r for item in list(old_items.values()) + list(new_items.values()) for r in [_evidence_role(item)] if r})
    by_role: dict[str, Any] = {}
    changed_roles = 0
    for role in roles:
        old_paths = {p for p, item in old_items.items() if _evidence_role(item) == role}
        new_paths = {p for p, item in new_items.items() if _evidence_role(item) == role}
        changed = sorted(p for p in file_diff.get("changed", []) or [] if _evidence_role(new_items.get(p) or old_items.get(p) or {}) == role)
        added = sorted(new_paths - old_paths)
        removed = sorted(old_paths - new_paths)
        status = "CHANGED" if added or removed or changed else "SAME"
        if status == "CHANGED":
            changed_roles += 1
        by_role[role] = {
            "old_count": len(old_paths),
            "new_count": len(new_paths),
            "added": added,
            "removed": removed,
            "changed": changed,
            "status": status,
            "release_meaning": "release evidence changed" if role in {"release_note", "waiver", "readme", "changelog"} else "documentation changed",
        }
    return {"schema_version": "1.0", "status": "DIFF" if changed_roles else "SAME", "by_role": by_role, "summary": {"roles": len(roles), "changed_roles": changed_roles}}


def _metadata_review_tasks(file_diff: Mapping[str, Any]) -> dict[str, Any]:
    old_items = file_diff.get("_old_items") or {}
    new_items = file_diff.get("_new_items") or {}
    tasks: list[dict[str, Any]] = []
    idx = 1
    for change_type in ["added", "removed", "changed"]:
        for path in file_diff.get(change_type, []) or []:
            item = new_items.get(path) or old_items.get(path) or {}
            file_type = str(item.get("file_type", "unknown"))
            if file_type not in METADATA_ONLY_TYPES:
                continue
            tasks.append(
                {
                    "task_id": f"metadata_review_{idx:04d}",
                    "file_type": file_type,
                    "path": path,
                    "change_type": change_type,
                    "status": "PENDING",
                    "reason": "metadata-only/binary view changed; content semantics are not interpreted automatically",
                    "recommended_action": "manual review required before approved release",
                }
            )
            idx += 1
    return {"schema_version": "1.0", "status": "PENDING" if tasks else "EMPTY", "tasks": tasks, "summary": {"total": len(tasks), "pending": len(tasks)}}


def _component_id(scan_meta: Mapping[str, Any]) -> str:
    return str(scan_meta.get("library_id") or "/".join([
        str(scan_meta.get("library_type") or "unknown"),
        str(scan_meta.get("library_name") or "unknown"),
        str(scan_meta.get("release_version") or "unknown"),
    ]))


def _component_key(component_id: str) -> str:
    parts = component_id.split("/")
    if len(parts) >= 2:
        return "/".join(parts[:2])
    return component_id


def _readiness_components(scan: Path, meta: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    readiness = _read_json(scan / "summary" / "release_readiness.json", {}) or {}
    components = readiness.get("components") if isinstance(readiness, Mapping) else None
    if components:
        return {str(item.get("component_id") or _component_id(meta)): dict(item) for item in components}
    cid = _component_id(meta)
    return {
        cid: {
            "component_id": cid,
            "status": readiness.get("bundle_status") if isinstance(readiness, Mapping) else meta.get("status"),
            "release_channel": readiness.get("release_channel") if isinstance(readiness, Mapping) else None,
            "required_views": [],
            "required_view_results": {},
        }
    }


def _component_diff(old_scan: Path, new_scan: Path, old_meta: Mapping[str, Any], new_meta: Mapping[str, Any]) -> dict[str, Any]:
    old_components = _readiness_components(old_scan, old_meta)
    new_components = _readiness_components(new_scan, new_meta)
    old_by_key = {_component_key(cid): item for cid, item in old_components.items()}
    new_by_key = {_component_key(cid): item for cid, item in new_components.items()}
    added = []
    removed = []
    changed = []
    for key in sorted(set(new_by_key) - set(old_by_key)):
        added.append(new_by_key[key].get("component_id"))
    for key in sorted(set(old_by_key) - set(new_by_key)):
        removed.append(old_by_key[key].get("component_id"))
    for key in sorted(set(old_by_key) & set(new_by_key)):
        old = old_by_key[key]
        new = new_by_key[key]
        old_views = set(old.get("required_views") or [])
        new_views = set(new.get("required_views") or [])
        view_results = {}
        for view in sorted(old_views | new_views):
            old_result = (old.get("required_view_results") or {}).get(view, {})
            new_result = (new.get("required_view_results") or {}).get(view, {})
            old_status = old_result.get("status")
            new_status = new_result.get("status")
            old_parser = old_result.get("parser_status")
            new_parser = new_result.get("parser_status")
            if old_status != new_status or old_parser != new_parser or view not in old_views or view not in new_views:
                view_results[view] = {
                    "old_status": old_status,
                    "new_status": new_status,
                    "old_parser_status": old_parser,
                    "new_parser_status": new_parser,
                    "change": "added" if view not in old_views else "removed" if view not in new_views else "changed",
                }
        if (
            old.get("status") != new.get("status")
            or old.get("release_channel") != new.get("release_channel")
            or old.get("component_id") != new.get("component_id")
            or view_results
        ):
            changed.append(
                {
                    "component_key": key,
                    "old_component_id": old.get("component_id"),
                    "new_component_id": new.get("component_id"),
                    "old_status": old.get("status"),
                    "new_status": new.get("status"),
                    "old_channel": old.get("release_channel"),
                    "new_channel": new.get("release_channel"),
                    "required_view_changes": view_results,
                }
            )
    return {
        "schema_version": "1.0",
        "added": added,
        "removed": removed,
        "changed": changed,
        "counts": {"added": len(added), "removed": len(removed), "changed": len(changed)},
    }


def _release_readiness_diff(old_scan: Path, new_scan: Path) -> dict[str, Any]:
    old = _read_json(old_scan / "summary" / "release_readiness.json", {}) or {}
    new = _read_json(new_scan / "summary" / "release_readiness.json", {}) or {}
    old_blockers = old.get("blocking_items", []) if isinstance(old, Mapping) else []
    new_blockers = new.get("blocking_items", []) if isinstance(new, Mapping) else []
    old_manual = old.get("manual_review_items", []) if isinstance(old, Mapping) else []
    new_manual = new.get("manual_review_items", []) if isinstance(new, Mapping) else []
    return {
        "schema_version": "1.0",
        "bundle_status": {"old": old.get("bundle_status") if isinstance(old, Mapping) else None, "new": new.get("bundle_status") if isinstance(new, Mapping) else None},
        "release_channel": {"old": old.get("release_channel") if isinstance(old, Mapping) else None, "new": new.get("release_channel") if isinstance(new, Mapping) else None},
        "blocking_count": {"old": len(old_blockers), "new": len(new_blockers), "delta": len(new_blockers) - len(old_blockers)},
        "manual_review_count": {"old": len(old_manual), "new": len(new_manual), "delta": len(new_manual) - len(old_manual)},
        "new_blocking_items": new_blockers[len(old_blockers):] if len(new_blockers) > len(old_blockers) else [],
        "new_manual_review_items": new_manual[len(old_manual):] if len(new_manual) > len(old_manual) else [],
    }


def _signature_diff(old_scan: Path, new_scan: Path) -> dict[str, Any]:
    rel = "signatures/signatures.json"
    old_hash = _scan_file_hash(old_scan, rel)
    new_hash = _scan_file_hash(new_scan, rel)
    return {"schema_version": "1.0", "changed": old_hash != new_hash, "old_hash": old_hash, "new_hash": new_hash}


def _parser_quality_diff(old_scan: Path, new_scan: Path) -> dict[str, Any]:
    old_quality = _read_json(old_scan / "summary" / "parser_quality.json", {})
    new_quality = _read_json(new_scan / "summary" / "parser_quality.json", {})
    return {
        "schema_version": "1.0",
        "changed": _stable_hash(old_quality) != _stable_hash(new_quality),
        "old_status": old_quality.get("status") if isinstance(old_quality, dict) else None,
        "new_status": new_quality.get("status") if isinstance(new_quality, dict) else None,
    }


def _issue(severity: str, category: str, title: str, message: str, **extra: Any) -> dict[str, Any]:
    return {"severity": severity, "category": category, "title": title, "message": message, **extra}


def _diff_issues(
    file_diff: dict[str, Any],
    component_diff: dict[str, Any],
    readiness_diff: dict[str, Any],
    support: dict[str, Any],
    view_diff: Mapping[str, Any] | None = None,
    release_evidence_diff: Mapping[str, Any] | None = None,
    metadata_review_tasks: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []
    if support["old"].get("missing") or support["new"].get("missing"):
        issues.append(_issue("warning", "compatibility", "Diff is degraded", "One or both scan outputs are missing v5 diff inputs.", support=support))
    for path in file_diff.get("removed", []) or []:
        issues.append(_issue("warning", "file", "File removed", f"removed file: {path}", file=path))
    for path in file_diff.get("metadata_only_changed", []) or []:
        issues.append(_issue("warning", "file", "Metadata-only file change needs review", f"metadata changed without content hash change: {path}", file=path))
    for component in component_diff.get("changed", []) or []:
        for view, change in (component.get("required_view_changes") or {}).items():
            if change.get("new_parser_status") in {"FAILED", "PASS_EMPTY"}:
                issues.append(_issue("blocker", "component", "Required view parser regressed", f"{component.get('new_component_id')} {view}: {change.get('old_parser_status')} -> {change.get('new_parser_status')}", component_id=component.get("new_component_id"), file_type=view))
    for view in (view_diff or {}).get("views", []) or []:
        if view.get("severity") == "blocker":
            issues.append(
                _issue(
                    "blocker",
                    "view_diff",
                    "Required view is not release-ready",
                    f"{view.get('view')}: {view.get('old_status')} -> {view.get('new_status')}",
                    file_type=view.get("view"),
                )
            )
        elif view.get("changed") and view.get("requirement") == "required":
            issues.append(
                _issue(
                    "warning",
                    "view_diff",
                    "Required view changed",
                    f"{view.get('view')}: count {view.get('old_count')} -> {view.get('new_count')}",
                    file_type=view.get("view"),
                )
            )
    for role, item in ((release_evidence_diff or {}).get("by_role") or {}).items():
        if item.get("status") == "CHANGED":
            issues.append(
                _issue(
                    "warning",
                    "release_evidence",
                    "Release evidence changed",
                    f"{role}: +{len(item.get('added') or [])}/-{len(item.get('removed') or [])}/~{len(item.get('changed') or [])}",
                    role=role,
                )
            )
    metadata_total = ((metadata_review_tasks or {}).get("summary") or {}).get("total", 0)
    if metadata_total:
        issues.append(
            _issue(
                "warning",
                "metadata_review",
                "Metadata-only views need manual review",
                f"{metadata_total} binary/metadata-only changes require manual confirmation.",
            )
        )
    old_status = readiness_diff.get("bundle_status", {}).get("old")
    new_status = readiness_diff.get("bundle_status", {}).get("new")
    if old_status != new_status:
        severity = "blocker" if new_status == "BLOCK" else "warning"
        issues.append(_issue(severity, "release_readiness", "Release readiness status changed", f"bundle_status: {old_status} -> {new_status}"))
    if readiness_diff.get("blocking_count", {}).get("delta", 0) > 0:
        issues.append(_issue("blocker", "release_readiness", "New blocking release items", f"blocking_items delta={readiness_diff['blocking_count']['delta']}"))
    if readiness_diff.get("manual_review_count", {}).get("delta", 0) > 0:
        issues.append(_issue("warning", "release_readiness", "More manual review items", f"manual_review_items delta={readiness_diff['manual_review_count']['delta']}"))
    counts = Counter(item["severity"] for item in issues)
    return {"schema_version": "1.0", "issues": issues, "summary": dict(counts)}


def _status_from_issues(issues: dict[str, Any], has_diff: bool) -> str:
    counts = issues.get("summary", {}) or {}
    if counts.get("blocker", 0) > 0:
        return "BLOCK"
    if counts.get("error", 0) > 0:
        return "FAILED"
    return "DIFF" if has_diff else "SAME"


def _diff_summary(
    status: str,
    file_diff: dict[str, Any],
    component_diff: dict[str, Any],
    readiness_diff: dict[str, Any],
    issues: dict[str, Any],
    view_diff: Mapping[str, Any],
    type_diff: Mapping[str, Any],
    release_evidence_diff: Mapping[str, Any],
    metadata_review_tasks: Mapping[str, Any],
    pairwise_tasks: int = 0,
) -> dict[str, Any]:
    counts = issues.get("summary", {}) or {}
    risk_level = "blocker" if counts.get("blocker", 0) else "warning" if counts.get("warning", 0) else "info"
    metadata_tasks = ((metadata_review_tasks or {}).get("summary") or {}).get("total", 0)
    evidence_changes = ((release_evidence_diff or {}).get("summary") or {}).get("changed_roles", 0)
    view_changes = ((view_diff or {}).get("summary") or {}).get("changed", 0)
    type_changes = ((type_diff or {}).get("summary") or {}).get("changed_types", 0)
    return {
        "schema_version": "1.0",
        "status": status,
        "risk_level": risk_level,
        "added_files": file_diff["counts"]["added"],
        "removed_files": file_diff["counts"]["removed"],
        "changed_files": file_diff["counts"]["changed"],
        "renamed_or_moved": file_diff["counts"].get("renamed_or_moved", 0),
        "package_root_migrations": file_diff["counts"].get("package_root_migrations", 0),
        "package_root_migration_matched_files": file_diff["counts"].get("package_root_migration_matched_files", 0),
        "added_components": component_diff["counts"]["added"],
        "removed_components": component_diff["counts"]["removed"],
        "changed_components": component_diff["counts"]["changed"],
        "view_changes": view_changes,
        "type_changes": type_changes,
        "release_evidence_changes": evidence_changes,
        "metadata_review_tasks": metadata_tasks,
        "object_changes": 0,
        "manual_pairwise_tasks": pairwise_tasks,
        "pairwise_tasks": pairwise_tasks,
        "breaking_changes": counts.get("blocker", 0) + counts.get("error", 0),
        "compatible_changes": file_diff["counts"]["added"],
        "manual_review_items": readiness_diff.get("manual_review_count", {}).get("new", 0) + metadata_tasks + pairwise_tasks,
        "recommended_actions": _recommended_actions(status, issues),
    }


def _recommended_actions(status: str, issues: dict[str, Any]) -> list[str]:
    if status == "BLOCK":
        return ["先处理 blocker，再进入 release link。"]
    if status == "PASS_WITH_WARNING":
        return ["发布前复核 warning，并补齐人工确认记录。"]
    if status == "DIFF":
        return ["确认重点文件证据，并把确认结果作为 release evidence 归档。"]
    return ["无差异动作要求。"]


def _report(meta: dict[str, Any], summary: dict[str, Any], issues: dict[str, Any]) -> str:
    lines = [
        "# lib_guard Diff Report",
        "",
        f"- status: {summary.get('status')}",
        f"- risk_level: {summary.get('risk_level')}",
        f"- old_scan: {meta.get('old_scan')}",
        f"- new_scan: {meta.get('new_scan')}",
        f"- version_relation: {json.dumps(meta.get('version_relation', {}), ensure_ascii=False)}",
        "",
        "## Summary",
        "",
        f"- files added/removed/changed: {summary.get('added_files')}/{summary.get('removed_files')}/{summary.get('changed_files')}",
        f"- components added/removed/changed: {summary.get('added_components')}/{summary.get('removed_components')}/{summary.get('changed_components')}",
        f"- breaking_changes: {summary.get('breaking_changes')}",
        f"- manual_review_items: {summary.get('manual_review_items')}",
        f"- view_changes: {summary.get('view_changes')}",
        f"- type_changes: {summary.get('type_changes')}",
        f"- release_evidence_changes: {summary.get('release_evidence_changes')}",
        f"- manual_pairwise_tasks: {summary.get('manual_pairwise_tasks')}",
        "",
        "## Issues",
        "",
    ]
    for item in issues.get("issues", []) or []:
        lines.append(f"- [{item.get('severity')}] {item.get('category')}: {item.get('title')} - {item.get('message')}")
    if not issues.get("issues"):
        lines.append("- none")
    lines.append("")
    return "\n".join(lines)


def _write_diff_output(out: Path, payload: dict[str, Any]) -> None:
    out.mkdir(parents=True, exist_ok=True)
    (out / "logs").mkdir(exist_ok=True)
    file_diff = dict(payload["file_diff"])
    file_diff.pop("_old_items", None)
    file_diff.pop("_new_items", None)
    _write_json(out / "diff_meta.json", payload["diff_meta"])
    _write_json(out / "diff_summary.json", payload["diff_summary"])
    _write_json(out / "file_diff.json", file_diff)
    _write_json(out / "component_diff.json", payload["component_diff"])
    _write_json(out / "signature_diff.json", payload["signature_diff"])
    _write_json(out / "view_diff.json", payload["view_diff"])
    _write_json(out / "type_diff.json", payload["type_diff"])
    _write_json(out / "release_evidence_diff.json", payload["release_evidence_diff"])
    _write_json(out / "metadata_review_tasks.json", payload["metadata_review_tasks"])
    _write_json(out / "release_readiness_diff.json", payload["release_readiness_diff"])
    _write_json(out / "diff_issues.json", payload["diff_issues"])
    _write_json(out / "pairwise_diff_tasks.json", payload["pairwise_diff_tasks"])
    _write_json(out / "manual_pairwise_tasks.json", payload["manual_pairwise_tasks"])
    _write_json(out / "pairwise_diff_task_status.json", payload["pairwise_diff_task_status"])
    (out / "diff_report.md").write_text(_report(payload["diff_meta"], payload["diff_summary"], payload["diff_issues"]), encoding="utf-8")


def diff_scan_outputs(
    old_scan: str | Path,
    new_scan: str | Path,
    out_path: str | Path | None = None,
    version_relation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    old = Path(old_scan)
    new = Path(new_scan)
    old_meta = _read_json(old / "scan_meta.json", {}) or {}
    new_meta = _read_json(new / "scan_meta.json", {}) or {}
    old_inventory = _read_json(old / "file_inventory.json", {}) or {}
    new_inventory = _read_json(new / "file_inventory.json", {}) or {}
    old_snapshot_digest, old_identity_source = _snapshot_digest(old_meta, old_inventory)
    new_snapshot_digest, new_identity_source = _snapshot_digest(new_meta, new_inventory)
    identity_status, identity_source, identity_trust, identity_sources = _diff_identity_provenance(
        old_identity_source,
        new_identity_source,
    )
    identity = None
    diff_id = None
    if identity_status != "UNAVAILABLE":
        from lib_guard.identity import build_diff_identity

        identity = build_diff_identity(
            old_snapshot_digest,
            new_snapshot_digest,
            f"scan_diff.v1|old:{old_identity_source}|new:{new_identity_source}",
        )
        diff_id = identity["digest"].split(":", 1)[1][:16]
    relation = {
        "diff_mode": "explicit",
        "old_version": old_meta.get("release_version"),
        "new_version": new_meta.get("release_version"),
        "old_version_type": None,
        "new_version_type": None,
        "release_line": None,
        "parent_version": None,
        "base_version": None,
    }
    relation.update(version_relation or {})
    file_diff = _file_diff(old, new)
    component_diff = _component_diff(old, new, old_meta, new_meta)
    signature_diff = _signature_diff(old, new)
    parser_quality = _parser_quality_diff(old, new)
    readiness_diff = _release_readiness_diff(old, new)
    support = {"old": _scan_support(old), "new": _scan_support(new)}
    type_diff = _type_diff(file_diff)
    view_diff = _view_diff(old, new, type_diff)
    release_evidence_diff = _release_evidence_diff(file_diff)
    metadata_review_tasks = _metadata_review_tasks(file_diff)
    pairwise_tasks = build_pairwise_diff_tasks(old, new, file_diff, output_root=(Path(out_path) / "pairwise_file_diff") if out_path and not Path(out_path).suffix else None)
    manual_pairwise_tasks = {
        **pairwise_tasks,
        "governance_role": "manual_deep_diff",
        "description": "Deep semantic file comparison is intentionally manual and pairwise. Scan diff records focused evidence candidates but does not provide executable script commands.",
    }
    pairwise_task_status = build_pairwise_task_status(pairwise_tasks)
    issues = _diff_issues(
        file_diff,
        component_diff,
        readiness_diff,
        support,
        view_diff=view_diff,
        release_evidence_diff=release_evidence_diff,
        metadata_review_tasks=metadata_review_tasks,
    )
    has_diff = any(
        [
            file_diff["counts"]["added"],
            file_diff["counts"]["removed"],
            file_diff["counts"]["changed"],
            component_diff["counts"]["added"],
            component_diff["counts"]["removed"],
            component_diff["counts"]["changed"],
            signature_diff["changed"],
            parser_quality["changed"],
            type_diff["summary"]["changed_types"],
            view_diff["summary"]["changed"],
            release_evidence_diff["summary"]["changed_roles"],
            metadata_review_tasks["summary"]["total"],
            readiness_diff.get("bundle_status", {}).get("old") != readiness_diff.get("bundle_status", {}).get("new"),
        ]
    )
    status = _status_from_issues(issues, has_diff)
    diff_created_at = _utc_now()
    meta = {
        "schema_version": "1.0",
        "diff_id": diff_id,
        "diff_type": "scan_output_diff",
        "diff_created_at": diff_created_at,
        "identity": identity,
        "identity_source": identity_source,
        "identity_status": identity_status,
        "identity_trust": identity_trust,
        "identity_sources": identity_sources,
        "old_scan": str(old),
        "new_scan": str(new),
        "old_scan_id": old_meta.get("scan_id"),
        "new_scan_id": new_meta.get("scan_id"),
        "old_library_id": old_meta.get("library_id"),
        "new_library_id": new_meta.get("library_id"),
        "version_relation": relation,
        "support": support,
    }
    summary = _diff_summary(
        status,
        file_diff,
        component_diff,
        readiness_diff,
        issues,
        view_diff,
        type_diff,
        release_evidence_diff,
        metadata_review_tasks,
        pairwise_tasks=len(pairwise_tasks.get("tasks") or []),
    )
    payload = {
        "diff_meta": meta,
        "diff_summary": summary,
        "file_diff": file_diff,
        "component_diff": component_diff,
        "signature_diff": signature_diff,
        "view_diff": view_diff,
        "type_diff": type_diff,
        "release_evidence_diff": release_evidence_diff,
        "metadata_review_tasks": metadata_review_tasks,
        "parser_quality": parser_quality,
        "parser_result_diff": {},
        "pairwise_diff_tasks": pairwise_tasks,
        "manual_pairwise_tasks": manual_pairwise_tasks,
        "pairwise_diff_task_status": pairwise_task_status,
        "release_readiness_diff": readiness_diff,
        "diff_issues": issues,
    }
    if out_path:
        out = Path(out_path)
        if out.suffix.lower() == ".json":
            _write_json(out, {"status": status, **payload})
        else:
            _write_diff_output(out, payload)
    return {
        "schema_version": "1.0",
        "diff_type": "scan_output_diff",
        "status": status,
        "old_scan": str(old),
        "new_scan": str(new),
        "version_relation": relation,
        "inventory": {
            "added": file_diff["added"],
            "removed": file_diff["removed"],
            "changed": file_diff["changed"],
            "added_count": file_diff["counts"]["added"],
            "removed_count": file_diff["counts"]["removed"],
            "changed_count": file_diff["counts"]["changed"],
        },
        "summary": summary,
        "parser_quality": parser_quality,
        "component_diff": component_diff,
        "view_diff": view_diff,
        "type_diff": type_diff,
        "release_evidence_diff": release_evidence_diff,
        "metadata_review_tasks": metadata_review_tasks,
        "parser_result_diff": {},
        "pairwise_diff_tasks": pairwise_tasks,
        "manual_pairwise_tasks": manual_pairwise_tasks,
        "pairwise_diff_task_status": pairwise_task_status,
        "release_readiness_diff": readiness_diff,
        "diff_issues": issues,
        "outputs": str(out_path) if out_path else None,
    }
