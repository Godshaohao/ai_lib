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
OVERLAY_PACKAGE_TYPES = {"PARTIAL_UPDATE", "HOTFIX", "DOC_UPDATE", "DOC_ONLY"}

# These names are view directories, not delivery-package roots.  A single
# non-view top-level directory can safely be removed from the logical path
# when comparing two version-root scans.
VIEW_ROOT_NAMES = {
    "lef",
    "lib",
    "liberty",
    "rtl",
    "verilog",
    "systemverilog",
    "cdl",
    "spice",
    "spi",
    "sdc",
    "upf",
    "cpf",
    "sdf",
    "spef",
    "db",
    "ndm",
    "gds",
    "gdsii",
    "oas",
    "oasis",
    "ibis",
    "waiver",
    "doc",
    "docs",
    "package",
}


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


def _parser_result_signatures(scan: Path) -> dict[str, dict[str, str]]:
    manifest = _read_json(scan / "parser_manifest.json", {"files": []}) or {}
    out: dict[str, dict[str, str]] = {}
    for item in manifest.get("files", []) or []:
        path = str(item.get("file") or "")
        if not path:
            continue
        task_signatures: list[dict[str, Any]] = []
        task_contracts: list[dict[str, Any]] = []
        for task in item.get("parser_tasks", []) or []:
            rel = task.get("result_path")
            if not rel:
                continue
            result = _read_json(scan / str(rel), {}) or {}
            parser_name = result.get("parser_name") or task.get("parser_name")
            parser_version = result.get("parser_version") or task.get("parser_version")
            parser_schema_version = result.get("parser_schema_version") or task.get("parser_schema_version")
            status = result.get("status") or task.get("result_status") or task.get("status")
            if status != "PASS" or not parser_name or not parser_version or not parser_schema_version:
                continue
            task_signatures.append(
                {
                    "parser_name": parser_name,
                    "data": _strip_path_fields(result.get("data")),
                }
            )
            task_contracts.append(
                {
                    "parser_name": parser_name,
                    "parser_version": parser_version,
                    "parser_schema_version": parser_schema_version,
                    "status": status,
                }
            )
        if task_signatures:
            out[path] = {
                "semantic_signature": "parser:" + _stable_hash(task_signatures),
                "semantic_signature_contract": "parser-contract:" + _stable_hash(task_contracts),
            }
    return out


def _compare_file_evidence(old: Mapping[str, Any], new: Mapping[str, Any]) -> tuple[str, str]:
    if old.get("file_type") != new.get("file_type"):
        return "changed", "file_type_changed"
    old_size = old.get("size_bytes")
    new_size = new.get("size_bytes")
    if old_size is not None and new_size is not None and old_size != new_size:
        return "changed", "size_changed"
    old_hash = old.get("hash")
    new_hash = new.get("hash")
    if old_hash and new_hash:
        if old_hash == new_hash:
            return "same", "content_hash_match"
        return "changed", "content_hash_changed"
    old_semantic = old.get("semantic_signature")
    new_semantic = new.get("semantic_signature")
    if old_semantic and new_semantic:
        old_contract = old.get("semantic_signature_contract")
        new_contract = new.get("semantic_signature_contract")
        if old_contract and new_contract:
            if old_contract != new_contract:
                return "unverified", "parser_contract_mismatch"
            if old_semantic != new_semantic:
                return "changed", "semantic_signature_changed"
    return "unverified", "missing_content_evidence"


def _logical_file_key(path: str, *, strip_root: str | None = None) -> str:
    parts = [part for part in str(path or "").replace("\\", "/").split("/") if part]
    if len(parts) <= 1:
        return "/".join(parts)
    wrapper = parts[0].lower()
    if strip_root and wrapper == str(strip_root).lower():
        return "/".join(parts[1:])
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


def _candidate_package_root(
    items: Mapping[str, Mapping[str, Any]],
    *,
    release_version: str | None = None,
) -> str | None:
    roots = _root_counts(items)
    version_root = str(release_version or "").strip().replace("\\", "/").strip("/")
    if version_root and version_root in roots and version_root.lower() not in VIEW_ROOT_NAMES:
        return version_root
    if len(roots) != 1:
        return None
    root = next(iter(roots))
    if root.lower() in VIEW_ROOT_NAMES:
        return None
    return root


def _unique_logical_index(
    items: Mapping[str, Mapping[str, Any]],
    *,
    strip_root: str | None = None,
) -> dict[str, str]:
    logical_to_paths: dict[str, list[str]] = {}
    for path in items:
        logical_to_paths.setdefault(_logical_file_key(path, strip_root=strip_root), []).append(path)
    return {logical: paths[0] for logical, paths in logical_to_paths.items() if len(paths) == 1}


def _inventory_coverage(meta: Mapping[str, Any] | None, count: int) -> dict[str, Any]:
    meta = meta or {}
    fingerprint = meta.get('input_fingerprint') or {}
    complete = (meta.get('status') in {'PASS', 'PASS_WITH_WARNING'} and fingerprint.get('mode') == 'scan_inventory'
                and fingerprint.get('truncated') is False and fingerprint.get('entry_count') == count
                and (meta.get('inventory_walk') or {}).get('complete', True))
    return {'complete': complete, 'file_count': count,
            'reason': 'successful_untruncated_inventory' if complete else 'inventory_scope_not_confirmed'}


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
            row.update(parser_signatures[key])
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


def _classify_common_files(
    old_items: Mapping[str, Mapping[str, Any]],
    new_items: Mapping[str, Mapping[str, Any]],
) -> tuple[list[str], list[str], list[dict[str, Any]]]:
    changed: list[str] = []
    unchanged: list[str] = []
    unverified: list[dict[str, Any]] = []
    for key in sorted(set(old_items) & set(new_items)):
        comparison, reason = _compare_file_evidence(old_items[key], new_items[key])
        if comparison == "changed":
            changed.append(key)
        elif comparison == "same":
            unchanged.append(key)
        else:
            unverified.append({"logical_path": key, "old": key, "new": key, "reason": reason})
    return changed, unchanged, unverified


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
        if path in excluded_old or path in new_items:
            continue
        digest = str(item.get("hash") or "")
        if digest:
            old_by_hash.setdefault(digest, []).append(path)
    new_by_hash: dict[str, list[str]] = {}
    for path, item in new_items.items():
        if path in excluded_new or path in old_items:
            continue
        digest = str(item.get("hash") or "")
        if digest:
            new_by_hash.setdefault(digest, []).append(path)
    moved = []
    for digest in sorted(set(old_by_hash) & set(new_by_hash)):
        old_candidates = old_by_hash[digest]
        new_candidates = new_by_hash[digest]
        if len(old_candidates) != 1 or len(new_candidates) != 1:
            continue
        moved.append(
            {
                "old": old_candidates[0],
                "new": new_candidates[0],
                "hash": digest,
                "reason": "unique_hash_match",
            }
        )
    return moved


def _metadata_match_candidates(
    old_items: Mapping[str, Mapping[str, Any]],
    new_items: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Pair cheap, hashless candidates without claiming content equality.

    Large views often omit full hashes by policy.  A unique basename + file
    type + size match is useful evidence for package re-layout, but it is not
    strong enough to call a file unchanged.  Keep it in ``unverified`` so the
    review gate can remain conservative without manufacturing add/remove noise.
    """

    def key(path: str, item: Mapping[str, Any]) -> tuple[str, str, int | None]:
        basename = Path(str(path).replace("\\", "/")).name.lower()
        file_type = str(item.get("file_type") or "unknown").lower()
        size = item.get("size_bytes")
        try:
            normalized_size = int(size) if size is not None else None
        except (TypeError, ValueError):
            normalized_size = None
        return basename, file_type, normalized_size

    old_by_key: dict[tuple[str, str, int | None], list[str]] = {}
    new_by_key: dict[tuple[str, str, int | None], list[str]] = {}
    for path, item in old_items.items():
        if not isinstance(item, Mapping) or item.get("hash") or item.get("sha256"):
            continue
        old_by_key.setdefault(key(path, item), []).append(path)
    for path, item in new_items.items():
        if not isinstance(item, Mapping) or item.get("hash") or item.get("sha256"):
            continue
        new_by_key.setdefault(key(path, item), []).append(path)

    candidates: list[dict[str, Any]] = []
    for match_key in sorted(set(old_by_key) & set(new_by_key)):
        old_paths = old_by_key[match_key]
        new_paths = new_by_key[match_key]
        if len(old_paths) != 1 or len(new_paths) != 1:
            continue
        old_path, new_path = old_paths[0], new_paths[0]
        if old_path == new_path:
            continue
        candidates.append(
            {
                "old": old_path,
                "new": new_path,
                "reason": "metadata_name_size_candidate",
                "match_reason": "same_basename_file_type_size",
                "confidence": "candidate",
            }
        )
    return candidates


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
    raw_added_by_root = Counter(_path_root(path) for path in raw_added)
    raw_removed_by_root = Counter(_path_root(path) for path in raw_removed)
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
                "raw_added_under_new_root": raw_added_by_root[new_root],
                "raw_removed_under_old_root": raw_removed_by_root[old_root],
                "sample_mappings": [],
            },
        )
        row["matched_logical_paths"] += 1
        comparison = str(pair.get("comparison") or "")
        if comparison == "changed":
            row["changed_logical_paths"] += 1
        elif comparison == "same":
            row["same_signature_paths"] += 1
        else:
            row.setdefault("unverified_logical_paths", 0)
            row["unverified_logical_paths"] += 1
        if len(row["sample_mappings"]) < 10:
            row["sample_mappings"].append(
                {
                    "logical_path": pair.get("logical_path"),
                    "old": old_path,
                    "new": new_path,
                    "signature_changed": comparison == "changed",
                    "comparison": comparison or "unverified",
                }
            )
    return sorted(by_pair.values(), key=lambda item: (-int(item["matched_logical_paths"]), str(item["old_root"]), str(item["new_root"])))


def _file_diff(
    old_scan: Path,
    new_scan: Path,
    *,
    old_meta: Mapping[str, Any] | None = None,
    new_meta: Mapping[str, Any] | None = None,
    new_version_type: str | None = None,
) -> dict[str, Any]:
    old_files = _inventory_index(old_scan)
    new_files = _inventory_index(new_scan)
    physical_old_files = dict(old_files)
    physical_new_files = dict(new_files)
    inventory_coverage = {'old': _inventory_coverage(old_meta, len(old_files)),
                          'new': _inventory_coverage(new_meta, len(new_files))}
    raw_added = set(new_files) - set(old_files)
    raw_removed = set(old_files) - set(new_files)
    changed, unchanged, unverified = _classify_common_files(old_files, new_files)
    logical_path_changes: list[dict[str, Any]] = []
    logical_pairs: list[dict[str, Any]] = []
    old_package_root = _candidate_package_root(
        old_files,
        release_version=str((old_meta or {}).get("release_version") or ""),
    )
    new_package_root = _candidate_package_root(
        new_files,
        release_version=str((new_meta or {}).get("release_version") or ""),
    )
    old_logical = _unique_logical_index(old_files, strip_root=old_package_root)
    new_logical = _unique_logical_index(new_files, strip_root=new_package_root)
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
        comparison, reason = _compare_file_evidence(old_item, new_item)
        logical_pairs.append(
            {
                "logical_path": logical,
                "old": old_path,
                "new": new_path,
                "signature_changed": comparison == "changed",
                "comparison": comparison,
            }
        )
        paired_old.add(old_path)
        paired_new.add(new_path)
        if comparison == "same":
            # A version/package wrapper is outside the library's logical file
            # path. Matching files beneath different wrappers are unchanged,
            # while the wrapper transition remains package migration evidence.
            unchanged.append(logical)
            continue
        if comparison == "unverified":
            unverified.append(
                {
                    "logical_path": logical,
                    "old": old_path,
                    "new": new_path,
                    "reason": reason,
                }
            )
            continue
        logical_changed.append(logical)
        logical_path_changes.append({"logical_path": logical, "old": old_path, "new": new_path})
        old_files.pop(old_path, None)
        new_files.pop(new_path, None)
        old_files[logical] = {**old_item, "path": logical, "physical_path": old_path, "logical_path": logical, "abs_path": old_item.get("abs_path")}
        new_files[logical] = {**new_item, "path": logical, "physical_path": new_path, "logical_path": logical, "abs_path": new_item.get("abs_path")}
    changed = sorted(set(changed) | set(logical_changed))
    metadata_only = []
    for key in changed:
        old = old_files[key]
        new = new_files[key]
        old_hash = old.get("hash")
        new_hash = new.get("hash")
        if old_hash and old_hash == new_hash and old.get("size_bytes") == new.get("size_bytes"):
            metadata_only.append(key)
    moved = _moved_files(old_files, new_files, exclude_old=paired_old, exclude_new=paired_new)
    for item in moved:
        item["old_logical_path"] = _logical_file_key(
            str(item.get("old") or ""),
            strip_root=old_package_root,
        )
        item["new_logical_path"] = _logical_file_key(
            str(item.get("new") or ""),
            strip_root=new_package_root,
        )
    moved_old = {str(item.get("old")) for item in moved if item.get("old")}
    moved_new = {str(item.get("new")) for item in moved if item.get("new")}
    metadata_candidates = _metadata_match_candidates(
        {
            path: physical_old_files[path]
            for path in raw_removed - moved_old - paired_old
            if path in physical_old_files
        },
        {
            path: physical_new_files[path]
            for path in raw_added - moved_new - paired_new
            if path in physical_new_files
        },
    )
    metadata_old = {str(item.get("old")) for item in metadata_candidates if item.get("old")}
    metadata_new = {str(item.get("new")) for item in metadata_candidates if item.get("new")}
    for item in metadata_candidates:
        old_path = str(item.get("old") or "")
        new_path = str(item.get("new") or "")
        unverified.append(
            {
                "logical_path": _logical_file_key(new_path, strip_root=new_package_root),
                "old": old_path,
                "new": new_path,
                "reason": str(item.get("reason") or "metadata_name_size_candidate"),
                "match_reason": str(item.get("match_reason") or "same_basename_file_type_size"),
                "confidence": str(item.get("confidence") or "candidate"),
            }
        )
    added = sorted(raw_added - moved_new - paired_new)
    normalized_version_type = str(new_version_type or "").upper()
    overlay_mode = normalized_version_type in OVERLAY_PACKAGE_TYPES
    old_inventory_count = len(old_files)
    new_inventory_count = len(new_files)
    suspicious_full_shrink = (
        normalized_version_type == "FULL_PACKAGE"
        and old_inventory_count >= 20
        and new_inventory_count * 2 < old_inventory_count
    )
    omitted_from_overlay = (
        sorted(raw_removed - moved_old - paired_old - metadata_old)
        if overlay_mode or suspicious_full_shrink
        else []
    )
    removed = [] if overlay_mode or suspicious_full_shrink else sorted(raw_removed - moved_old - paired_old)
    added = sorted(set(added) - metadata_new)
    removed = sorted(set(removed) - metadata_old)
    unchanged = sorted(unchanged)
    unverified = sorted(unverified, key=lambda item: (str(item.get("logical_path") or ""), str(item.get("old") or "")))
    package_root_migrations = _package_root_migrations(
        physical_old_files,
        physical_new_files,
        logical_pairs,
        raw_added=raw_added,
        raw_removed=raw_removed,
    )
    package_root_migration_matched_files = sum(int(item.get("matched_logical_paths") or 0) for item in package_root_migrations)
    unmatched_added_under_package_root: list[str] = []
    unmatched_removed_under_package_root: list[str] = []
    if package_root_migrations:
        new_roots = {str(item.get("new_root") or "") for item in package_root_migrations if item.get("new_root")}
        old_roots = {str(item.get("old_root") or "") for item in package_root_migrations if item.get("old_root")}
        unmatched_added_under_package_root = sorted(path for path in added if _path_root(path) in new_roots)
        unmatched_removed_under_package_root = sorted(path for path in removed if _path_root(path) in old_roots)
        if all(side['complete'] for side in inventory_coverage.values()):
            # Absence from a complete inventory is a file-list addition/removal,
            # not a request to match every file by hand. Retain real candidates.
            old_keys = {_logical_file_key(path, strip_root=old_package_root) for path in physical_old_files}
            new_keys = {_logical_file_key(path, strip_root=new_package_root) for path in physical_new_files}
            old_names = {(Path(path).name, item.get('file_type')) for path, item in physical_old_files.items()}
            new_names = {(Path(path).name, item.get('file_type')) for path, item in physical_new_files.items()}
            unmatched_added_under_package_root = [path for path in unmatched_added_under_package_root
                if _logical_file_key(path, strip_root=new_package_root) in old_keys
                or (Path(path).name, physical_new_files[path].get('file_type')) in old_names]
            unmatched_removed_under_package_root = [path for path in unmatched_removed_under_package_root
                if _logical_file_key(path, strip_root=old_package_root) in new_keys
                or (Path(path).name, physical_old_files[path].get('file_type')) in new_names]
    return {
        "schema_version": "1.0",
        "added": added,
        "inventory_coverage": inventory_coverage,
        "removed": removed,
        "changed": changed,
        "renamed_or_moved": moved,
        "metadata_match_candidates": metadata_candidates,
        "logical_path_changes": logical_path_changes,
        "package_root_migrations": package_root_migrations,
        "unmatched_added_under_package_root": unmatched_added_under_package_root,
        "unmatched_removed_under_package_root": unmatched_removed_under_package_root,
        "unchanged": unchanged,
        "unverified": unverified,
        "comparison_semantics": (
            "overlay"
            if overlay_mode
            else "needs_package_confirmation"
            if suspicious_full_shrink
            else "complete_snapshot"
        ),
        "omitted_from_overlay": omitted_from_overlay,
        "package_scope_suspect": suspicious_full_shrink,
        "metadata_only_changed": metadata_only,
        "logical_package_roots": {
            "old": old_package_root,
            "new": new_package_root,
        },
        "counts": {
            "added": len(added),
            "removed": len(removed),
            "changed": len(changed),
            "renamed_or_moved": len(moved),
            "logical_path_changed": len(logical_path_changes),
            "package_root_migrations": len(package_root_migrations),
            "package_root_migration_matched_files": package_root_migration_matched_files,
            "unmatched_added_under_package_root": len(unmatched_added_under_package_root),
            "unmatched_removed_under_package_root": len(unmatched_removed_under_package_root),
            "unchanged": len(unchanged),
            "unverified": len(unverified),
            "omitted_from_overlay": len(omitted_from_overlay),
            "raw_removed": len(raw_removed),
            "package_scope_suspect": int(suspicious_full_shrink),
            "old_inventory": old_inventory_count,
            "new_inventory": new_inventory_count,
            "metadata_match_candidates": len(metadata_candidates),
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
    unverified_by_type: Counter[str] = Counter()
    for item in file_diff.get("unverified", []) or []:
        new_path = str((item or {}).get("new") or "")
        old_path = str((item or {}).get("old") or "")
        entry = new_items.get(new_path) or old_items.get(old_path) or {}
        unverified_by_type[str(entry.get("file_type", "unknown"))] += 1
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
    for file_type in sorted(set(old_counts) | set(new_counts) | set(changed_by_type) | set(unverified_by_type)):
        added = sorted(path for path in added_paths if str((new_items.get(path) or {}).get("file_type", "unknown")) == file_type)
        removed = sorted(path for path in removed_paths if str((old_items.get(path) or {}).get("file_type", "unknown")) == file_type)
        changed = [p for p in file_diff.get("changed", []) or [] if str((new_items.get(p) or old_items.get(p) or {}).get("file_type", "unknown")) == file_type]
        changed_flag = bool(added or removed or changed or old_counts[file_type] + moved_by_type[file_type] != new_counts[file_type] + moved_by_type[file_type])
        unverified_count = unverified_by_type[file_type]
        if changed_flag:
            changed_types += 1
        by_type[file_type] = {
            "old_count": old_counts[file_type],
            "new_count": new_counts[file_type],
            "added_count": len(added),
            "removed_count": len(removed),
            "changed_count": len(changed),
            "unverified_count": unverified_count,
            "moved_count": moved_by_type[file_type],
            "added": added[:50],
            "removed": removed[:50],
            "changed": changed[:50],
            "status": "CHANGED" if changed_flag else "UNVERIFIED" if unverified_count else "SAME",
            "review_mode": "metadata_only" if file_type in METADATA_ONLY_TYPES else "summary_only" if file_type in SUMMARY_ONLY_DIFF_TYPES else "manual_pairwise" if file_type in DEFAULT_FILE_DIFF_TYPES else "governance",
        }
    return {
        "schema_version": "1.0",
        "status": "DIFF" if changed_types else "UNVERIFIED" if unverified_by_type else "SAME",
        "by_type": by_type,
        "summary": {
            "old_type_count": len(old_counts),
            "new_type_count": len(new_counts),
            "changed_types": changed_types,
            "unverified_types": len(unverified_by_type),
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
    old_paths_by_role: dict[str, set[str]] = {}
    new_paths_by_role: dict[str, set[str]] = {}
    for path, item in old_items.items():
        role = _evidence_role(item)
        if role:
            old_paths_by_role.setdefault(role, set()).add(path)
    for path, item in new_items.items():
        role = _evidence_role(item)
        if role:
            new_paths_by_role.setdefault(role, set()).add(path)
    role_events: dict[str, dict[str, Any]] = {}

    def events(role: str | None) -> dict[str, Any] | None:
        if not role:
            return None
        return role_events.setdefault(
            role,
            {"added": set(), "removed": set(), "changed": set(), "unverified": []},
        )

    def item_for(items: Mapping[str, Mapping[str, Any]], path: str, logical_path: str = "") -> Mapping[str, Any]:
        return items.get(path) or (items.get(logical_path) if logical_path else None) or {}

    for path in file_diff.get("added", []) or []:
        row = events(_evidence_role(new_items.get(path) or {}))
        if row is not None:
            row["added"].add(path)
    for path in file_diff.get("removed", []) or []:
        row = events(_evidence_role(old_items.get(path) or {}))
        if row is not None:
            row["removed"].add(path)
    for path in file_diff.get("changed", []) or []:
        old_item = old_items.get(path) or {}
        new_item = new_items.get(path) or {}
        old_role = _evidence_role(old_item)
        new_role = _evidence_role(new_item)
        old_event_path = str(old_item.get("physical_path") or path)
        new_event_path = str(new_item.get("physical_path") or path)
        if old_role and new_role and old_role != new_role:
            events(old_role)["removed"].add(old_event_path)  # type: ignore[index]
            events(new_role)["added"].add(new_event_path)  # type: ignore[index]
        else:
            row = events(new_role or old_role)
            if row is not None:
                row["changed"].add(new_event_path)

    pair_rows: list[Mapping[str, Any]] = []
    for path in sorted(set(old_items) & set(new_items)):
        old_item = old_items[path]
        new_item = new_items[path]
        pair_rows.append(
            {
                "old": str(old_item.get("physical_path") or path),
                "new": str(new_item.get("physical_path") or path),
                "logical_path": path,
            }
        )
    pair_rows.extend(file_diff.get("renamed_or_moved", []) or [])
    pair_rows.extend(file_diff.get("logical_path_changes", []) or [])
    pair_rows.extend(file_diff.get("unverified", []) or [])
    seen_pairs: set[tuple[str, str]] = set()
    for pair in pair_rows:
        old_path = str(pair.get("old") or "")
        new_path = str(pair.get("new") or "")
        logical_path = str(pair.get("logical_path") or "")
        pair_key = (old_path, new_path)
        if not old_path or not new_path or pair_key in seen_pairs:
            continue
        seen_pairs.add(pair_key)
        old_role = _evidence_role(item_for(old_items, old_path, logical_path))
        new_role = _evidence_role(item_for(new_items, new_path, logical_path))
        if old_role and new_role and old_role != new_role:
            events(old_role)["removed"].add(old_path)  # type: ignore[index]
            events(new_role)["added"].add(new_path)  # type: ignore[index]

    evidence_unverified_pairs: set[tuple[str, str]] = set()
    for item in file_diff.get("unverified", []) or []:
        old_path = str((item or {}).get("old") or "")
        new_path = str((item or {}).get("new") or "")
        logical_path = str((item or {}).get("logical_path") or "")
        old_role = _evidence_role(item_for(old_items, old_path, logical_path))
        new_role = _evidence_role(item_for(new_items, new_path, logical_path))
        for role in {old_role, new_role} - {None}:
            events(role)["unverified"].append(dict(item))  # type: ignore[index]
            evidence_unverified_pairs.add((old_path, new_path))

    roles = sorted(set(role_events) | set(old_paths_by_role) | set(new_paths_by_role))
    by_role: dict[str, Any] = {}
    changed_roles = 0
    unverified_roles = 0
    for role in roles:
        old_paths = old_paths_by_role.get(role, set())
        new_paths = new_paths_by_role.get(role, set())
        role_event = events(role) or {}
        changed = sorted(role_event.get("changed") or set())
        added = sorted(role_event.get("added") or set())
        removed = sorted(role_event.get("removed") or set())
        unverified = list(role_event.get("unverified") or [])
        status = "CHANGED" if added or removed or changed else "UNVERIFIED" if unverified else "SAME"
        if status == "CHANGED":
            changed_roles += 1
        if unverified:
            unverified_roles += 1
        by_role[role] = {
            "old_count": len(old_paths),
            "new_count": len(new_paths),
            "added": added,
            "removed": removed,
            "changed": changed,
            "unverified": unverified,
            "status": status,
            "release_meaning": "release evidence changed" if role in {"release_note", "waiver", "readme", "changelog"} else "documentation changed",
        }
    return {
        "schema_version": "1.0",
        "status": "DIFF" if changed_roles else "UNVERIFIED" if unverified_roles else "SAME",
        "by_role": by_role,
        "summary": {
            "roles": len(roles),
            "changed_roles": changed_roles,
            "unverified_roles": unverified_roles,
            "unverified_files": len(evidence_unverified_pairs),
        },
    }


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

    def stable_quality(value: Any) -> dict[str, Any]:
        if not isinstance(value, Mapping):
            return {}
        parsers = []
        for item in value.get("parsers", []) or []:
            if not isinstance(item, Mapping):
                continue
            parsers.append(
                {
                    key: item.get(key)
                    for key in (
                        "file_type",
                        "file_types",
                        "parser_name",
                        "parser_version",
                        "file_count",
                        "parsed_count",
                        "failed_count",
                        "pass_empty_count",
                        "object_count",
                        "quality_score",
                        "status",
                    )
                }
            )
        parsers.sort(key=lambda item: (str(item.get("file_type") or ""), str(item.get("parser_name") or "")))
        return {"status": value.get("status"), "parsers": parsers}

    old_stable = stable_quality(old_quality)
    new_stable = stable_quality(new_quality)
    return {
        "schema_version": "1.0",
        "changed": _stable_hash(old_stable) != _stable_hash(new_stable),
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
        issues.append(_issue("warning", "compatibility", "对比能力降级", "一个或两个扫描输出缺少完整对比输入。", support=support))
    unverified_count = int((file_diff.get("counts") or {}).get("unverified") or 0)
    if unverified_count:
        issues.append(
            _issue(
                "warning",
                "content_evidence",
                "部分文件缺少内容证据",
                f"{unverified_count} 个已配对文件只有路径和元数据证据，未判定为相同或变化。",
                count=unverified_count,
            )
        )
    if (file_diff.get("counts") or {}).get("package_scope_suspect"):
        counts = file_diff.get("counts") or {}
        issues.append(
            _issue(
                "blocker",
                "package_scope",
                "完整包文件数量显著缩小，暂不判定旧文件删除",
                (
                    f"完整包扫描文件数从 {counts.get('old_inventory', '?')} 缩小到 "
                    f"{counts.get('new_inventory', '?')}；请确认这是完整替换还是增量包。"
                ),
                omitted_files=counts.get("omitted_from_overlay", 0),
                recommended_action="确认包类型后重新对比",
            )
        )
    for path in file_diff.get("removed", []) or []:
        issues.append(_issue("warning", "file", "文件缺失", f"removed file: {path}", file=path))
    for path in file_diff.get("metadata_only_changed", []) or []:
        issues.append(_issue("warning", "file", "元数据级文件发生变化，需要确认", f"metadata changed without content hash change: {path}", file=path))
    for component in component_diff.get("changed", []) or []:
        for view, change in (component.get("required_view_changes") or {}).items():
            if change.get("new_parser_status") in {"FAILED", "PASS_EMPTY"}:
                issues.append(_issue("blocker", "component", "必需视图解析结果退化", f"{component.get('new_component_id')} {view}: {change.get('old_parser_status')} -> {change.get('new_parser_status')}", component_id=component.get("new_component_id"), file_type=view))
    for view in (view_diff or {}).get("views", []) or []:
        if view.get("severity") == "blocker":
            issues.append(
                _issue(
                    "blocker",
                    "view_diff",
                    "必需视图尚未达到发布条件",
                    f"{view.get('view')}: {view.get('old_status')} -> {view.get('new_status')}",
                    file_type=view.get("view"),
                )
            )
        elif view.get("changed") and view.get("requirement") == "required":
            issues.append(
                _issue(
                    "warning",
                    "view_diff",
                    "必需视图发生变化",
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
                    "发布证据发生变化",
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
                "元数据级视图需要人工确认",
                f"{metadata_total} 个二进制或元数据级变化需要人工确认。",
            )
        )
    old_status = readiness_diff.get("bundle_status", {}).get("old")
    new_status = readiness_diff.get("bundle_status", {}).get("new")
    if old_status != new_status:
        severity = "blocker" if new_status == "BLOCK" else "warning"
        issues.append(_issue(severity, "release_readiness", "发布准备状态发生变化", f"bundle_status: {old_status} -> {new_status}"))
    if readiness_diff.get("blocking_count", {}).get("delta", 0) > 0:
        issues.append(_issue("blocker", "release_readiness", "新增发布阻塞项", f"blocking_items delta={readiness_diff['blocking_count']['delta']}"))
    if readiness_diff.get("manual_review_count", {}).get("delta", 0) > 0:
        issues.append(_issue("warning", "release_readiness", "人工审查项增加", f"manual_review_items delta={readiness_diff['manual_review_count']['delta']}"))
    counts = Counter(item["severity"] for item in issues)
    return {"schema_version": "1.0", "issues": issues, "summary": dict(counts)}


def _status_from_issues(issues: dict[str, Any], has_diff: bool, has_unverified: bool = False) -> str:
    counts = issues.get("summary", {}) or {}
    if counts.get("blocker", 0) > 0:
        return "BLOCK"
    if counts.get("error", 0) > 0:
        return "FAILED"
    return "DIFF" if has_diff else "UNVERIFIED" if has_unverified else "SAME"


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
        "unverified_files": file_diff["counts"].get("unverified", 0),
        "renamed_or_moved": file_diff["counts"].get("renamed_or_moved", 0),
        "comparison_semantics": file_diff.get("comparison_semantics", "complete_snapshot"),
        "omitted_from_overlay_files": file_diff["counts"].get("omitted_from_overlay", 0),
        "raw_removed_files": file_diff["counts"].get("raw_removed", file_diff["counts"].get("removed", 0)),
        "package_scope_suspect": file_diff["counts"].get("package_scope_suspect", 0),
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
        "manual_review_items": readiness_diff.get("manual_review_count", {}).get("new", 0) + metadata_tasks + pairwise_tasks + file_diff["counts"].get("unverified", 0),
        "recommended_actions": _recommended_actions(status, issues),
    }


def _recommended_actions(status: str, issues: dict[str, Any]) -> list[str]:
    if status == "BLOCK":
        return ["先处理 blocker，再进入 release link。"]
    if status == "PASS_WITH_WARNING":
        return ["发布前复核 warning，并补齐人工确认记录。"]
    if status == "DIFF":
        return ["确认重点文件证据，并把确认结果作为 release evidence 归档。"]
    if status == "UNVERIFIED":
        return ["确认缺少内容证据的文件，再判断是否发生变化。"]
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
        f"- files unverified: {summary.get('unverified_files')}",
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
            f"scan_diff.v2.inventory_coverage|old:{old_identity_source}|new:{new_identity_source}",
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
    file_diff = _file_diff(
        old,
        new,
        old_meta=old_meta,
        new_meta=new_meta,
        new_version_type=str(relation.get("new_version_type") or ""),
    )
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
        "description": "深度语义文件对比必须由人工逐对执行。扫描对比只记录重点证据候选，不生成可执行脚本命令。",
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
            type_diff["summary"]["changed_types"],
            view_diff["summary"]["changed"],
            release_evidence_diff["summary"]["changed_roles"],
            metadata_review_tasks["summary"]["total"],
            readiness_diff.get("bundle_status", {}).get("old") != readiness_diff.get("bundle_status", {}).get("new"),
        ]
    )
    has_unverified = bool(file_diff["counts"].get("unverified", 0))
    status = _status_from_issues(issues, has_diff, has_unverified)
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
            "unverified": file_diff.get("unverified", []),
            "added_count": file_diff["counts"]["added"],
            "removed_count": file_diff["counts"]["removed"],
            "changed_count": file_diff["counts"]["changed"],
            "unverified_count": file_diff["counts"].get("unverified", 0),
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
