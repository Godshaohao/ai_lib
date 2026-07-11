from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from lib_guard.atomic import atomic_write_json
from lib_guard.effective.pointer import load_current_pointer, safe_name

SCHEMA_VERSION = "review_window.v1"

FULL_TYPES = {"FULL", "FULL_PACKAGE", "BASE_FULL", "BASE", "COMPLETE"}
FIX_TYPES = {"FIX", "HOTFIX", "PARTIAL", "PARTIAL_UPDATE", "DOC_UPDATE", "UPDATE"}
IGNORE_TYPES = {"IGNORE", "IGNORED"}
UNKNOWN_TYPES = {"UNKNOWN", "UNKNOWN_PACKAGE", "UNCLASSIFIED", "NEEDS_CONFIRM"}


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def read_json(path: str | Path, default: Any = None) -> Any:
    p = Path(path)
    if not p.exists() or not p.is_file():
        return default
    return json.loads(p.read_text(encoding="utf-8"))


def write_json(path: str | Path, data: Mapping[str, Any]) -> Path:
    return atomic_write_json(path, data, lock=True)


def _libraries(catalog: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = catalog.get("libraries", [])
    return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []


def find_library(catalog: Mapping[str, Any], library: str) -> dict[str, Any]:
    query = str(library or "")
    scored: list[tuple[int, dict[str, Any]]] = []
    for row in _libraries(catalog):
        exact = {
            str(row.get("formal_library_id") or ""),
            str(row.get("typed_library_id") or ""),
            str(row.get("library_id") or ""),
            str(row.get("library_name") or ""),
            str(row.get("display_name") or ""),
        }
        aliases = {str(alias) for alias in row.get("aliases", []) or [] if str(alias)}
        if query in exact:
            scored.append((100, row))
        elif query in aliases or any(value.endswith("/" + query) for value in exact if value):
            scored.append((10, row))
    if not scored:
        raise ValueError(f"library not found in catalog: {library}")
    best = max(score for score, _ in scored)
    matches = [row for score, row in scored if score == best]
    if len(matches) > 1:
        choices = ", ".join(str(row.get("library_id") or row.get("library_name")) for row in matches)
        raise ValueError(f"ambiguous library alias {library!r}; matched: {choices}")
    return matches[0]


def version_id(version: Mapping[str, Any]) -> str:
    return str(version.get("version_id") or version.get("version") or "")


def version_index(versions: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    return {version_id(item): idx for idx, item in enumerate(versions) if version_id(item)}


def version_map(versions: Sequence[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    return {version_id(item): item for item in versions if version_id(item)}


def package_kind(version: Mapping[str, Any]) -> str:
    explicit = str(version.get("package_type") or version.get("delivery_type") or "").strip().upper()
    if explicit in UNKNOWN_TYPES or explicit.startswith("UNKNOWN"):
        return "UNKNOWN"
    if explicit in FULL_TYPES or "FULL" in explicit:
        return "FULL"
    if explicit in FIX_TYPES or "HOTFIX" in explicit or "PARTIAL" in explicit or explicit.endswith("UPDATE"):
        return "FIX"
    if explicit in IGNORE_TYPES:
        return "IGNORE"
    if explicit:
        return "UNKNOWN"
    return "UNKNOWN"


def guessed_package_kind(version: Mapping[str, Any]) -> str:
    name = version_id(version).lower()
    if any(token in name for token in ["full", "initial", "base", "final", "release"]):
        return "FULL"
    if any(token in name for token in ["fix", "hotfix", "patch", "update"]):
        return "FIX"
    return "UNKNOWN"


def _scan_evidence_exists(version: Mapping[str, Any]) -> bool:
    scan = version.get("scan") if isinstance(version.get("scan"), Mapping) else {}
    status = str(scan.get("status") or version.get("scan_status") or "").upper()
    if status in {"", "NOT_SCANNED", "STALE_SCAN", "FAILED"}:
        return False
    scan_dir = scan.get("scan_dir") or version.get("scan_dir")
    if scan_dir and Path(str(scan_dir)).exists():
        return True
    for key in ["file_inventory", "file_inventory_json", "inventory_json"]:
        value = scan.get(key) or version.get(key)
        if value and Path(str(value)).exists():
            return True
    return False


def _library_report_key(library: Mapping[str, Any], fallback: str) -> str:
    return safe_name(str(library.get("library_id") or library.get("library_name") or fallback))


def default_window_path(catalog_html_out: str | Path, library_row: Mapping[str, Any], library: str) -> Path:
    return Path(catalog_html_out) / "libraries" / _library_report_key(library_row, library) / "window" / "pending_window.json"


def _effective_dir(catalog_html_out: str | Path, library_row: Mapping[str, Any], library: str, effective_id: str) -> Path:
    return Path(catalog_html_out) / "libraries" / _library_report_key(library_row, library) / "effective" / safe_name(effective_id)


def _compare_dir(catalog_html_out: str | Path, library_row: Mapping[str, Any], library: str, compare_id: str) -> Path:
    return Path(catalog_html_out) / "libraries" / _library_report_key(library_row, library) / "compare" / safe_name(compare_id)


def _target_label(target: str) -> str:
    text = str(target or "").strip()
    return text.replace(":", "_") if text else "base"


def _summary_ref(library_row: Mapping[str, Any], keys: Sequence[str]) -> str:
    summary = library_row.get("summary") if isinstance(library_row.get("summary"), Mapping) else {}
    for key in keys:
        value = str(summary.get(key) or library_row.get(key) or "")
        if value and value.lower() not in {"true", "false", "none", "null"}:
            return value.replace("raw:", "").replace("effective:", "")
    return ""


def _current_anchor(pointer: Mapping[str, Any], library_row: Mapping[str, Any], versions: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    base_full = str(pointer.get("base_full_version") or "")
    accepted_updates = [str(item) for item in pointer.get("accepted_updates", []) or [] if str(item)]
    current_effective_id = str(pointer.get("current_effective_id") or "")
    manifest = str(pointer.get("manifest") or "")
    if base_full or current_effective_id:
        checkpoint = accepted_updates[-1] if accepted_updates else base_full
        return {
            "source": "current_effective_pointer",
            "old_target": f"effective:{current_effective_id or manifest}",
            "base_full": base_full,
            "accepted_updates": accepted_updates,
            "checkpoint_version": checkpoint,
            "current_effective_id": current_effective_id,
            "pointer_revision": int(pointer.get("revision") or 0),
            "manifest": manifest,
        }

    explicit = _summary_ref(library_row, ["current_effective_ref", "latest_effective_ref", "current_version", "approved_version"])
    if explicit:
        return {
            "source": "catalog_summary",
            "old_target": f"raw:{explicit}",
            "base_full": explicit,
            "accepted_updates": [],
            "checkpoint_version": explicit,
            "current_effective_id": "",
            "pointer_revision": 0,
            "manifest": "",
        }

    for item in reversed(list(versions)):
        if package_kind(item) == "FULL":
            vid = version_id(item)
            return {
                "source": "latest_full_fallback",
                "old_target": f"raw:{vid}",
                "base_full": vid,
                "accepted_updates": [],
                "checkpoint_version": vid,
                "current_effective_id": "",
                "pointer_revision": 0,
                "manifest": "",
            }
    if versions:
        vid = version_id(versions[0])
        return {
            "source": "first_catalog_version",
            "old_target": f"raw:{vid}",
            "base_full": vid,
            "accepted_updates": [],
            "checkpoint_version": vid,
            "current_effective_id": "",
            "pointer_revision": 0,
            "manifest": "",
        }
    raise ValueError("library has no versions")


def _after_checkpoint(versions: Sequence[Mapping[str, Any]], checkpoint: str, *, since: str | None = None) -> list[Mapping[str, Any]]:
    indexes = version_index(versions)
    start = indexes.get(since, -1) if since else indexes.get(checkpoint, -1)
    return [item for idx, item in enumerate(versions) if idx > start and version_id(item)]


def _window_item(version: Mapping[str, Any], *, role: str) -> dict[str, Any]:
    scan = version.get("scan") if isinstance(version.get("scan"), Mapping) else {}
    kind = package_kind(version)
    guessed = guessed_package_kind(version) if kind == "UNKNOWN" else kind
    return {
        "version": version_id(version),
        "package_type": str(version.get("package_type") or ""),
        "kind": kind,
        "guessed_kind": guessed,
        "requires_package_type_confirmation": kind == "UNKNOWN",
        "role": role,
        "scan_status": scan.get("status") or version.get("scan_status") or "",
    }


def _resolve_candidate(anchor: Mapping[str, Any], item_ids: Sequence[str], versions_by_id: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    last_full_idx = None
    for idx, vid in enumerate(item_ids):
        if package_kind(versions_by_id.get(vid, {})) == "FULL":
            last_full_idx = idx
    if last_full_idx is not None:
        base_full = item_ids[last_full_idx]
        overlays = [vid for vid in item_ids[last_full_idx + 1 :] if package_kind(versions_by_id.get(vid, {})) != "IGNORE"]
        intermediate = list(item_ids[:last_full_idx])
        rule = "latest_full_in_window"
    else:
        base_full = str(anchor.get("base_full") or "")
        overlays = [*list(anchor.get("accepted_updates", []) or []), *[vid for vid in item_ids if package_kind(versions_by_id.get(vid, {})) != "IGNORE"]]
        intermediate = []
        rule = "append_to_current_effective"
    unknowns = [vid for vid in item_ids if package_kind(versions_by_id.get(vid, {})) == "UNKNOWN"]
    last = overlays[-1] if overlays else (base_full or (item_ids[-1] if item_ids else "candidate"))
    return {
        "base_full": base_full,
        "overlays": overlays,
        "intermediate_items": intermediate,
        "rule": rule,
        "unknown_package_versions": unknowns,
        "last_material_version": last,
    }


def _scan_command(
    catalog: str,
    library: str,
    version: str,
    workdir: str,
    catalog_html_out: str,
    *,
    parse_jobs: str = "",
    hash_policy: str = "",
    parse_file_types: str = "",
    parse_exclude_file_types: str = "",
) -> list[str]:
    cmd = [
        "run",
        "--catalog",
        catalog,
        "--library",
        library,
        "--version",
        version,
        "--workdir",
        workdir,
        "--console-progress",
        "--progress-interval",
        "1",
        "--catalog-html-out",
        catalog_html_out,
    ]
    if parse_jobs:
        cmd.extend(["--parse-jobs", str(parse_jobs)])
    if hash_policy:
        cmd.extend(["--hash-policy", str(hash_policy)])
    if parse_file_types:
        cmd.extend(["--parse-file-types", str(parse_file_types)])
    if parse_exclude_file_types:
        cmd.extend(["--parse-exclude-file-types", str(parse_exclude_file_types)])
    return cmd


def _effective_build_command(catalog: str, library: str, candidate: Mapping[str, Any], effective_id: str, manifest: Path, html: Path) -> list[str]:
    cmd = [
        "effective",
        "build",
        "--catalog",
        catalog,
        "--library",
        library,
        "--base-full",
        str(candidate.get("base_full") or ""),
        "--effective-id",
        effective_id,
        "--out",
        str(manifest),
        "--html",
        str(html),
    ]
    for version in candidate.get("overlays", []) or []:
        cmd.extend(["--include", str(version)])
    return cmd


def _effective_compare_command(catalog: str, library: str, old_target: str, new_effective_id: str, compare_id: str, out_dir: Path, catalog_html_out: str) -> list[str]:
    return [
        "effective",
        "compare",
        "--catalog",
        catalog,
        "--library",
        library,
        "--old",
        old_target,
        "--new",
        f"effective:{new_effective_id}",
        "--out-dir",
        str(out_dir),
        "--html",
        str(out_dir / "index.html"),
        "--compare-id",
        compare_id,
        "--search-root",
        catalog_html_out,
    ]


def resolve_review_window(
    *,
    catalog_path: str | Path,
    library: str,
    workdir: str | Path,
    catalog_html_out: str | Path,
    since: str | None = None,
    window_path: str | Path | None = None,
    force_rebuild: bool = False,
    parse_jobs: str = "",
    hash_policy: str = "",
    parse_file_types: str = "",
    parse_exclude_file_types: str = "",
) -> dict[str, Any]:
    catalog = read_json(catalog_path, {}) or {}
    library_row = find_library(catalog, library)
    versions = [item for item in library_row.get("versions", []) or [] if isinstance(item, Mapping) and version_id(item)]
    versions_by_id = version_map(versions)
    if not versions:
        raise ValueError(f"library has no versions: {library}")

    html_out = str(catalog_html_out)
    pending_path = Path(window_path) if window_path else default_window_path(html_out, library_row, library)
    pending = read_json(pending_path, {}) or {}
    has_pending = bool(pending and str(pending.get("state") or "").upper() not in {"ACCEPTED", "CLOSED"})

    lib_id = str(library_row.get("library_id") or library_row.get("library_name") or library)
    pointer = load_current_pointer(html_out, lib_id) or load_current_pointer(html_out, library)
    anchor = _current_anchor(pointer, library_row, versions)

    existing_ids: list[str] = []
    if has_pending:
        base = dict(pending.get("base_effective") or {})
        anchor.update(
            {
                "old_target": str(base.get("target") or anchor.get("old_target") or ""),
                "base_full": base.get("base_full") or anchor.get("base_full"),
                "accepted_updates": base.get("accepted_updates") or anchor.get("accepted_updates", []),
                "checkpoint_version": pending.get("last_seen_version") or anchor.get("checkpoint_version"),
                "source": base.get("source") or anchor.get("source"),
                "current_effective_id": base.get("current_effective_id", anchor.get("current_effective_id")),
                "pointer_revision": base.get("pointer_revision") if "pointer_revision" in base else None,
                "manifest": base.get("manifest", anchor.get("manifest")),
            }
        )
        existing_ids = [str(item.get("version") or item.get("version_id") or "") for item in pending.get("items", []) or []]
        existing_ids = [vid for vid in existing_ids if vid in versions_by_id]

    new_versions = _after_checkpoint(versions, str(anchor.get("checkpoint_version") or ""), since=since)
    seen_existing = set(existing_ids)
    new_ids = [version_id(item) for item in new_versions if version_id(item) not in seen_existing]
    item_ids = [*existing_ids, *new_ids]
    if not item_ids:
        window = dict(pending if has_pending else {})
        window.update(
            {
                "schema_version": SCHEMA_VERSION,
                "library": library,
                "library_id": lib_id,
                "state": "EMPTY",
                "changed": False,
                "pending_window_path": str(pending_path),
                "base_effective": {
                    "source": anchor.get("source"),
                    "target": anchor.get("old_target"),
                    "base_full": anchor.get("base_full"),
                    "accepted_updates": list(anchor.get("accepted_updates", []) or []),
                    "checkpoint_version": anchor.get("checkpoint_version"),
                    "current_effective_id": anchor.get("current_effective_id"),
                    "pointer_revision": anchor.get("pointer_revision"),
                    "manifest": anchor.get("manifest"),
                },
                "last_seen_version": anchor.get("checkpoint_version"),
                "new_versions": [],
                "items": [],
                "kind_counts": {},
                "scan_versions": [],
                "warnings": [],
                "commands": [],
                "message": "当前没有新的待审查版本",
            }
        )
        return window

    candidate = _resolve_candidate(anchor, item_ids, versions_by_id)
    last_material = str(candidate.get("last_material_version") or item_ids[-1])
    effective_id = f"candidate_{safe_name(last_material)}"
    old_target = str(anchor.get("old_target") or "")
    compare_id = f"window_{safe_name(_target_label(old_target or str(anchor.get('checkpoint_version') or anchor.get('base_full') or 'base')))}_to_{safe_name(effective_id)}"
    eff_dir = _effective_dir(html_out, library_row, library, effective_id)
    compare_dir = _compare_dir(html_out, library_row, library, compare_id)
    manifest = eff_dir / "effective_manifest.json"

    scan_versions: list[str] = []
    if old_target.startswith("raw:"):
        base_vid = old_target.split(":", 1)[1]
        if base_vid in versions_by_id and not _scan_evidence_exists(versions_by_id[base_vid]):
            scan_versions.append(base_vid)
    for vid in item_ids:
        if vid in versions_by_id and not _scan_evidence_exists(versions_by_id[vid]):
            scan_versions.append(vid)
    dedup_scan = list(dict.fromkeys(scan_versions))

    commands: list[list[str]] = [
        _scan_command(
            str(catalog_path),
            library,
            vid,
            str(workdir),
            html_out,
            parse_jobs=parse_jobs,
            hash_policy=hash_policy,
            parse_file_types=parse_file_types,
            parse_exclude_file_types=parse_exclude_file_types,
        )
        for vid in dedup_scan
    ]
    if force_rebuild or not manifest.exists() or new_ids:
        commands.append(_effective_build_command(str(catalog_path), library, candidate, effective_id, manifest, eff_dir / "index.html"))
    if force_rebuild or not (compare_dir / "compare_manifest.json").exists() or new_ids:
        commands.append(_effective_compare_command(str(catalog_path), library, old_target, effective_id, compare_id, compare_dir, html_out))

    overlays = set(candidate.get("overlays", []) or [])
    items = []
    for vid in item_ids:
        role = "candidate_base" if vid == candidate.get("base_full") and candidate.get("rule") == "latest_full_in_window" else "candidate_overlay" if vid in overlays else "intermediate"
        items.append(_window_item(versions_by_id[vid], role=role))

    warnings: list[str] = []
    if candidate.get("unknown_package_versions"):
        warnings.append("存在 UNKNOWN package_type；请先用 lg mark 或 lg library override 确认类型，再执行 lg next --plan-only / --apply。")
    if candidate.get("intermediate_items"):
        warnings.append("Versions before the latest FULL are kept as window evidence and are not overlaid on the candidate FULL.")

    return {
        "schema_version": SCHEMA_VERSION,
        "library": library,
        "library_id": lib_id,
        "state": "PENDING",
        "changed": bool(new_ids),
        "created_at": pending.get("created_at") or now_iso(),
        "updated_at": now_iso(),
        "pending_window_path": str(pending_path),
        "base_effective": {
            "source": anchor.get("source"),
            "target": old_target,
            "base_full": anchor.get("base_full"),
            "accepted_updates": list(anchor.get("accepted_updates", []) or []),
            "checkpoint_version": anchor.get("checkpoint_version"),
            "current_effective_id": anchor.get("current_effective_id"),
            "pointer_revision": anchor.get("pointer_revision"),
            "manifest": anchor.get("manifest"),
        },
        "last_seen_version": item_ids[-1],
        "new_versions": new_ids,
        "items": items,
        "kind_counts": dict(Counter(package_kind(versions_by_id.get(vid, {})) for vid in item_ids)),
        "candidate_effective": {
            "effective_id": effective_id,
            "base_full": candidate.get("base_full"),
            "overlays": list(candidate.get("overlays", []) or []),
            "intermediate_items": list(candidate.get("intermediate_items", []) or []),
            "rule": candidate.get("rule"),
            "unknown_package_versions": list(candidate.get("unknown_package_versions", []) or []),
            "manifest": str(manifest),
            "html": str(eff_dir / "index.html"),
        },
        "compare": {
            "compare_id": compare_id,
            "old": old_target,
            "new": f"effective:{effective_id}",
            "out_dir": str(compare_dir),
            "html": str(compare_dir / "index.html"),
        },
        "scan_versions": dedup_scan,
        "commands": commands,
        "warnings": warnings,
    }
