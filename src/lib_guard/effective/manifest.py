from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from lib_guard.atomic import atomic_write_json
from lib_guard.identity import build_effective_identity
from lib_guard.release.bundle import normalize_release_relpath

SCHEMA_VERSION = "effective_manifest.v2"
RELEASE_SCHEMA_VERSION = "effective_release_preview.v1"
DEFAULT_VIEW_ORDER = [
    "liberty",
    "lef",
    "db",
    "gds",
    "oas",
    "verilog",
    "cdl",
    "sdc",
    "upf",
    "cpf",
    "spef",
    "sdf",
    "doc",
    "waiver",
    "other",
]
VIEW_ALIASES = {
    "lib": "liberty",
    "libs": "liberty",
    "liberty": "liberty",
    "timing": "liberty",
    "lef": "lef",
    "tlef": "lef",
    "db": "db",
    "gds": "gds",
    "gdsii": "gds",
    "oas": "oas",
    "oasis": "oas",
    "rtl": "verilog",
    "v": "verilog",
    "verilog": "verilog",
    "cdl": "cdl",
    "spice": "cdl",
    "spi": "cdl",
    "sdc": "sdc",
    "upf": "upf",
    "cpf": "cpf",
    "spef": "spef",
    "sdf": "sdf",
    "doc": "doc",
    "docs": "doc",
    "readme": "doc",
    "note": "doc",
    "waiver": "waiver",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def read_json(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path: str | Path, data: Mapping[str, Any]) -> Path:
    return atomic_write_json(path, data, lock=True)


def norm_view(value: Any) -> str:
    text = str(value or "other").strip().lower()
    return VIEW_ALIASES.get(text, text or "other")


def normalize_scope(scope: Any) -> list[str]:
    if scope is None:
        return []
    if isinstance(scope, str):
        raw = scope.replace(";", ",").replace("|", ",").split(",")
    elif isinstance(scope, (list, tuple, set)):
        raw = list(scope)
    else:
        raw = [scope]
    result: list[str] = []
    seen: set[str] = set()
    for item in raw:
        view = norm_view(item)
        if view and view not in seen:
            result.append(view)
            seen.add(view)
    return result


def short_name(name: str, head: int = 20, tail: int = 16) -> str:
    text = str(name or "")
    if len(text) <= head + tail + 3:
        return text
    return f"{text[:head]}...{text[-tail:]}"


def canonical_relpath(path: str) -> str:
    raw = str(path or "").replace("\\", "/")
    parts = [p for p in raw.split("/") if p not in {"", "."}]
    if len(parts) >= 2:
        # If a path includes an inventory root prefix, keep common library view dirs onward.
        lower = [p.lower() for p in parts]
        view_dirs = {
            "lib", "libs", "liberty", "lef", "db", "gds", "oas", "rtl", "verilog",
            "cdl", "spice", "sdc", "upf", "cpf", "spef", "sdf", "doc", "docs", "waiver",
        }
        for i, p in enumerate(lower):
            if p in view_dirs:
                return "/".join(parts[i:])
    return "/".join(parts)


def infer_file_type(relpath: str, explicit: Any = None) -> str:
    if explicit:
        return norm_view(explicit)
    p = relpath.lower()
    if p.endswith((".lib", ".lib.gz")):
        return "liberty"
    if p.endswith((".lef", ".lef.gz", ".tlef", ".tlef.gz")):
        return "lef"
    if p.endswith(".db"):
        return "db"
    if p.endswith((".gds", ".gds.gz")):
        return "gds"
    if p.endswith((".oas", ".oas.gz")):
        return "oas"
    if p.endswith((".v", ".sv", ".v.gz", ".sv.gz")):
        return "verilog"
    if p.endswith((".cdl", ".spi", ".sp", ".cdl.gz", ".spi.gz")):
        return "cdl"
    if p.endswith(".sdc"):
        return "sdc"
    if p.endswith(".upf"):
        return "upf"
    if p.endswith(".cpf"):
        return "cpf"
    if p.endswith((".spef", ".spef.gz")):
        return "spef"
    if p.endswith((".sdf", ".sdf.gz")):
        return "sdf"
    if any(x in p for x in ["readme", "release", "changelog", "note", "doc"]):
        return "doc"
    if "waiver" in p:
        return "waiver"
    first = p.split("/", 1)[0]
    return norm_view(first)


def _libraries(catalog: Mapping[str, Any]) -> list[dict[str, Any]]:
    libraries = catalog.get("libraries", [])
    return libraries if isinstance(libraries, list) else []


def find_library(catalog: Mapping[str, Any], library: str) -> dict[str, Any]:
    query = str(library)
    for lib in _libraries(catalog):
        candidates = {
            str(lib.get("library_id") or ""),
            str(lib.get("library_name") or ""),
            str(lib.get("display_name") or ""),
        }
        candidates.update(str(x) for x in lib.get("aliases", []) or [])
        if query in candidates or any(c.endswith("/" + query) for c in candidates):
            return lib
    raise KeyError(f"library not found: {library}")


def find_version(library_obj: Mapping[str, Any], version_id: str) -> dict[str, Any]:
    query = str(version_id)
    for v in library_obj.get("versions", []) or []:
        if str(v.get("version_id") or "") == query:
            return v
    raise KeyError(f"version not found: {version_id}")


def _inventory_candidates(version: Mapping[str, Any]) -> list[Path]:
    scan = version.get("scan", {}) or {}
    candidates: list[Path] = []
    for key in ["file_inventory", "file_inventory_json", "inventory_json"]:
        if scan.get(key):
            candidates.append(Path(str(scan[key])))
        if version.get(key):
            candidates.append(Path(str(version[key])))
    scan_dir = scan.get("scan_dir") or version.get("scan_dir")
    if scan_dir:
        for name in ["file_inventory.json", "inventory.json", "files.json"]:
            candidates.append(Path(str(scan_dir)) / name)
    raw_path = version.get("raw_path") or version.get("version_path")
    if raw_path:
        candidates.append(Path(str(raw_path)) / "file_inventory.json")
    return candidates


def _load_inventory_json(path: Path) -> list[dict[str, Any]]:
    if not path.exists() or not path.is_file():
        return []
    try:
        data = read_json(path)
    except Exception:
        return []
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    for key in ["files", "inventory", "items", "file_inventory"]:
        items = data.get(key)
        if isinstance(items, list):
            return [x for x in items if isinstance(x, dict)]
    return []


def inventory_for_version(version: Mapping[str, Any]) -> list[dict[str, Any]]:
    for candidate in _inventory_candidates(version):
        items = _load_inventory_json(candidate)
        if items:
            return items
    raw_path = version.get("raw_path") or version.get("version_path")
    if raw_path and Path(str(raw_path)).exists():
        root = Path(str(raw_path))
        result: list[dict[str, Any]] = []
        for p in root.rglob("*"):
            if p.is_file():
                rel = p.relative_to(root).as_posix()
                result.append({
                    "path": rel,
                    "relpath": rel,
                    "file_type": infer_file_type(rel),
                    "size_bytes": p.stat().st_size,
                })
        return result
    return []


def _file_records(version_id: str, version: Mapping[str, Any]) -> list[dict[str, Any]]:
    records = []
    raw_path = str(version.get("raw_path") or version.get("version_path") or "")
    for item in inventory_for_version(version):
        path = item.get("relpath") or item.get("path") or item.get("relative_path") or item.get("name")
        if not path:
            continue
        rel = canonical_relpath(str(path))
        records.append({
            "relpath": rel,
            "file_type": infer_file_type(rel, item.get("file_type")),
            "source_version": version_id,
            "source_path": str(item.get("path") or rel),
            "raw_root": raw_path,
            "hash": item.get("sha256") or item.get("hash") or item.get("content_hash"),
            "size_bytes": item.get("size_bytes") or item.get("size"),
        })
    return records


def _component(
    version_id: str,
    role: str,
    scope: Sequence[str] | str | None,
    order: int,
    version: Mapping[str, Any],
) -> dict[str, Any]:
    component = {
        "version_id": version_id,
        "version_short": short_name(version_id),
        "role": role,
        "scope": normalize_scope(scope) or (["all"] if role == "base_full" else []),
        "order": order,
    }
    scan = version.get("scan", {}) or {}
    snapshot_identity = scan.get("snapshot_identity") if isinstance(scan, Mapping) else None
    if not isinstance(snapshot_identity, Mapping):
        snapshot_identity = version.get("snapshot_identity")
    if isinstance(snapshot_identity, Mapping) and str(snapshot_identity.get("digest") or ""):
        component.update(
            {
                "snapshot_digest": str(snapshot_identity["digest"]),
                "evidence_strength": str(snapshot_identity.get("strength") or "unknown"),
                "identity_source": "snapshot_identity",
            }
        )
        return component
    fingerprint = scan.get("input_fingerprint") if isinstance(scan, Mapping) else None
    if not isinstance(fingerprint, Mapping):
        fingerprint = version.get("input_fingerprint")
    if isinstance(fingerprint, Mapping) and str(fingerprint.get("hash") or ""):
        component.update(
            {
                "snapshot_digest": str(fingerprint["hash"]),
                "evidence_strength": "legacy",
                "identity_source": "legacy_input_fingerprint",
            }
        )
        return component
    component.update(
        {
            "snapshot_digest": None,
            "evidence_strength": "unavailable",
            "identity_source": "missing_evidence",
        }
    )
    return component


def _effective_identity_provenance(components: Sequence[Mapping[str, Any]]) -> tuple[str, str, str]:
    sources = {str(component.get("identity_source") or "missing_evidence") for component in components}
    if "missing_evidence" in sources:
        return "UNAVAILABLE", "missing_evidence", "UNAVAILABLE"
    if sources == {"snapshot_identity"}:
        return "TRUSTED", "snapshot_identity", "HOMOGENEOUS_TRUSTED"
    if sources == {"legacy_input_fingerprint"}:
        return "LEGACY_FALLBACK", "legacy_input_fingerprint", "HOMOGENEOUS_LEGACY_FALLBACK"
    return "MIXED_EVIDENCE", "mixed_evidence", "NON_HOMOGENEOUS"


def _component_provenance_is_valid(component: Mapping[str, Any]) -> bool:
    source = str(component.get("identity_source") or "missing_evidence")
    digest = str(component.get("snapshot_digest") or "")
    strength = str(component.get("evidence_strength") or "")
    if source == "snapshot_identity":
        return bool(digest) and strength not in {"", "legacy", "unavailable"}
    if source == "legacy_input_fingerprint":
        return bool(digest) and strength == "legacy"
    if source == "missing_evidence":
        return not digest and strength == "unavailable"
    return False


def validate_effective_manifest(manifest: Mapping[str, Any]) -> dict[str, Any]:
    """Recompute and validate the complete effective identity and evidence provenance."""
    stored_identity = manifest.get("identity")
    if stored_identity is None:
        return {
            "integrity_status": "MISSING",
            "valid": False,
            "digest": "",
            "identity_source": "manifest_sha256_fallback",
            "evidence_status": "LEGACY_FALLBACK",
            "evidence_source": "manifest_sha256_fallback",
            "evidence_trust": "LEGACY_FALLBACK",
        }

    components = manifest.get("components", [])
    if (
        not isinstance(components, Sequence)
        or isinstance(components, (str, bytes, bytearray))
        or not all(isinstance(component, Mapping) for component in components)
    ):
        return {
            "integrity_status": "MISMATCH",
            "valid": False,
            "digest": "",
            "identity": {},
            "identity_source": "effective_manifest_identity",
            "evidence_status": "UNAVAILABLE",
            "evidence_source": "invalid_components",
            "evidence_trust": "UNAVAILABLE",
        }

    recomputed_identity = build_effective_identity(manifest)
    provenance = _effective_identity_provenance(components)
    stored_provenance = (
        str(manifest.get("identity_status") or ""),
        str(manifest.get("identity_source") or ""),
        str(manifest.get("identity_trust") or ""),
    )
    valid = (
        isinstance(stored_identity, Mapping)
        and dict(stored_identity) == recomputed_identity
        and all(isinstance(component, Mapping) and _component_provenance_is_valid(component) for component in components)
        and stored_provenance == provenance
    )
    return {
        "integrity_status": "MATCH" if valid else "MISMATCH",
        "valid": valid,
        "digest": recomputed_identity["digest"],
        "identity": recomputed_identity,
        "identity_source": "effective_manifest_identity",
        "evidence_status": provenance[0],
        "evidence_source": provenance[1],
        "evidence_trust": provenance[2],
    }


def _version_evidence(version_id: str, role: str, version: Mapping[str, Any]) -> dict[str, Any]:
    scan = version.get("scan", {}) or {}
    diff = version.get("diff", {}) or {}
    release = version.get("release", {}) or {}
    parser_summary = (
        scan.get("parser_summary")
        or scan.get("parser")
        or version.get("parser_summary")
        or version.get("parser")
        or {}
    )
    diff_summary = diff.get("summary") or version.get("diff_summary") or {}
    return {
        "version_id": version_id,
        "role": role,
        "stage": version.get("stage") or "",
        "package_type": version.get("package_type") or "",
        "raw_path": str(version.get("raw_path") or version.get("version_path") or ""),
        "scan_status": scan.get("status") or version.get("scan_status") or "",
        "scan_mode": scan.get("mode") or scan.get("scan_mode") or version.get("scan_mode") or "",
        "scan_dir": str(scan.get("scan_dir") or version.get("scan_dir") or ""),
        "scan_html": str(scan.get("scan_html") or version.get("scan_html") or ""),
        "parser_summary": parser_summary,
        "diff_status": diff.get("adjacent_status") or diff.get("status") or version.get("diff_status") or "",
        "adjacent_old_version": diff.get("adjacent_old_version") or version.get("base_version") or "",
        "adjacent_diff_html": str(diff.get("adjacent_diff_html") or diff.get("diff_html") or ""),
        "diff_summary": diff_summary,
        "release_status": release.get("status") or version.get("release_status") or "",
        "release_html": str(release.get("html") or release.get("release_html") or ""),
    }


def _version_evidence_summary(components: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    return {
        "component_count": len(components),
        "scanned_components": sum(1 for item in components if item.get("scan_status")),
        "diff_ready_components": sum(1 for item in components if item.get("diff_status") or item.get("adjacent_diff_html")),
        "parser_components": sum(1 for item in components if item.get("parser_summary")),
        "release_components": sum(1 for item in components if item.get("release_status") or item.get("release_html")),
    }


def build_effective_manifest(
    catalog: Mapping[str, Any],
    library: str,
    base_full_version: str,
    includes: Sequence[tuple[str, Sequence[str] | str | None]],
    *,
    effective_id: str | None = None,
    delete_files: Sequence[str] | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    lib = find_library(catalog, library)
    library_id = str(lib.get("library_id") or lib.get("library_name") or library)
    base = find_version(lib, base_full_version)
    effective_files: dict[str, dict[str, Any]] = {}
    components: list[dict[str, Any]] = [_component(base_full_version, "base_full", ["all"], 0, base)]
    evidence_components: list[dict[str, Any]] = [_version_evidence(base_full_version, "base_full", base)]
    conflicts: list[dict[str, Any]] = []
    replacement_counts: Counter[str] = Counter()

    for record in _file_records(base_full_version, base):
        effective_files[record["relpath"]] = {
            **record,
            "operation": "base",
            "replaced_from": None,
            "component_order": 0,
        }

    for order, (version_id, scope) in enumerate(includes, start=1):
        version = find_version(lib, version_id)
        scope_list = normalize_scope(scope) or normalize_scope(version.get("update_scope"))
        components.append(_component(version_id, "accepted_update", scope_list, order, version))
        evidence_components.append(_version_evidence(version_id, "accepted_update", version))
        records = _file_records(version_id, version)
        actual_types = {r["file_type"] for r in records}
        if scope_list and "all" not in scope_list:
            extra = sorted(t for t in actual_types if t not in set(scope_list))
            for t in extra:
                conflicts.append({
                    "type": "SCOPE_MISMATCH",
                    "version_id": version_id,
                    "file_type": t,
                    "message": f"update_scope 未声明 {t}，但包内包含该类型文件",
                })
        for record in records:
            rel = record["relpath"]
            previous = effective_files.get(rel)
            if previous:
                replacement_counts[rel] += 1
                op = "replace"
                replaced_from = previous.get("source_version")
            else:
                op = "add"
                replaced_from = None
            effective_files[rel] = {
                **record,
                "operation": op,
                "replaced_from": replaced_from,
                "component_order": order,
            }

    tombstones: dict[str, dict[str, Any]] = {}
    for rel in delete_files or []:
        canonical = canonical_relpath(rel)
        previous = effective_files.pop(canonical, None)
        tombstones[canonical] = {
            "operation": "delete",
            "deleted_from": previous.get("source_version") if previous else None,
        }
        if not previous:
            conflicts.append({
                "type": "DELETE_MISSING",
                "file": canonical,
                "message": "显式删除的文件在当前有效组合中不存在",
            })

    for rel, count in replacement_counts.items():
        if count >= 2:
            conflicts.append({
                "type": "REPEATED_REPLACEMENT",
                "file": rel,
                "count": count,
                "message": "同一文件在有效组合中被多次替换，需要关注是否为连续补丁",
            })

    file_type_summary = Counter(item.get("file_type", "other") for item in effective_files.values())
    operation_summary = Counter(item.get("operation", "unknown") for item in effective_files.values())
    source_summary = Counter(item.get("source_version") for item in effective_files.values())
    if not effective_id:
        last = includes[-1][0] if includes else base_full_version
        effective_id = f"effective_{short_name(last, 18, 8)}"

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "library_id": library_id,
        "library_name": lib.get("library_name") or library,
        "effective_id": effective_id,
        "base_full_version": base_full_version,
        "accepted_updates": [v for v, _ in includes],
        "components": components,
        "version_evidence": {
            "summary": _version_evidence_summary(evidence_components),
            "components": evidence_components,
        },
        "effective_files": dict(sorted(effective_files.items())),
        "tombstones": tombstones,
        "conflicts": conflicts,
        "summary": {
            "file_count": len(effective_files),
            "component_count": len(components),
            "conflict_count": len(conflicts),
            "file_type_summary": dict(sorted(file_type_summary.items())),
            "operation_summary": dict(sorted(operation_summary.items())),
            "source_summary": dict(sorted((str(k), v) for k, v in source_summary.items())),
        },
        "note": note or "",
        "created_at": now_iso(),
    }
    identity_status, identity_source, identity_trust = _effective_identity_provenance(components)
    manifest["identity"] = build_effective_identity(
        {
            "library_id": library_id,
            "base_full_version": base_full_version,
            "components": components,
            "tombstones": tombstones,
        }
    )
    manifest["identity_status"] = identity_status
    manifest["identity_source"] = identity_source
    manifest["identity_trust"] = identity_trust
    return manifest


def add_update_to_manifest(
    current_manifest: Mapping[str, Any],
    catalog: Mapping[str, Any],
    library: str,
    version_id: str,
    scope: Sequence[str] | str | None,
    *,
    effective_id: str | None = None,
) -> dict[str, Any]:
    base = str(current_manifest.get("base_full_version"))
    includes = [(str(v), []) for v in current_manifest.get("accepted_updates", [])]
    includes.append((version_id, scope))
    return build_effective_manifest(catalog, library, base, includes, effective_id=effective_id)


def release_preview(
    manifest: Mapping[str, Any],
    *,
    previous_release: Mapping[str, Any] | None = None,
    release_root: str | Path | None = None,
    release_id: str | None = None,
    link_mode: str = "link",
) -> dict[str, Any]:
    release_id = release_id or f"release_{manifest.get('effective_id', 'effective')}"
    release_root_text = str(release_root or "release_area")
    files = manifest.get("effective_files", {}) or {}
    previous_files = {}
    if previous_release:
        previous_files = {
            normalize_release_relpath(rel, file_type=(info or {}).get("file_type")).as_posix(): info
            for rel, info in (previous_release.get("release_files", {}) or previous_release.get("files", {}) or {}).items()
        }

    release_files: dict[str, dict[str, Any]] = {}
    delta: list[dict[str, Any]] = []
    actions = Counter()
    for rel, info in sorted(files.items()):
        release_rel = normalize_release_relpath(rel, file_type=info.get("file_type")).as_posix()
        release_path = f"{release_root_text.rstrip('/')}/{release_rel}"
        source_version = info.get("source_version")
        source_path = info.get("source_path") or rel
        raw_root = info.get("raw_root") or ""
        source_abs = f"{raw_root.rstrip('/')}/{source_path}" if raw_root else source_path
        previous = previous_files.get(release_rel)
        if not previous:
            action = "add"
        elif previous.get("source_version") != source_version or previous.get("source_path") != source_path:
            action = "replace"
        else:
            action = "keep"
        actions[action] += 1
        row = {
            "release_path": release_path,
            "relpath": release_rel,
            "source_version": source_version,
            "source_version_short": short_name(str(source_version)),
            "source_path": source_path,
            "source_abs": source_abs,
            "file_type": info.get("file_type"),
            "action": action,
            "link_mode": link_mode,
        }
        release_files[release_rel] = row
        if action != "keep":
            delta.append(row)

    if previous_files:
        for rel, old in sorted(previous_files.items()):
            if rel not in release_files:
                actions["delete"] += 1
                delta.append({
                    "release_path": old.get("release_path") or rel,
                    "relpath": rel,
                    "source_version": old.get("source_version"),
                    "source_version_short": short_name(str(old.get("source_version") or "")),
                    "source_path": old.get("source_path"),
                    "file_type": old.get("file_type"),
                    "action": "delete",
                    "link_mode": link_mode,
                })

    return {
        "schema_version": RELEASE_SCHEMA_VERSION,
        "release_id": release_id,
        "effective_id": manifest.get("effective_id"),
        "library_id": manifest.get("library_id"),
        "library_name": manifest.get("library_name"),
        "release_root": release_root_text,
        "release_files": release_files,
        "delta": delta,
        "summary": {
            "total_files": len(release_files),
            "delta_files": len(delta),
            "actions": dict(sorted(actions.items())),
        },
        "created_at": now_iso(),
    }


def update_scope_heatmap(manifest: Mapping[str, Any]) -> dict[str, Any]:
    components = manifest.get("components", []) or []
    files = manifest.get("effective_files", {}) or {}
    matrix: dict[str, Counter[str]] = {str(c.get("version_id")): Counter() for c in components}
    for item in files.values():
        version = str(item.get("source_version") or "")
        matrix.setdefault(version, Counter())[str(item.get("file_type") or "other")] += 1
    views = [v for v in DEFAULT_VIEW_ORDER if any(counter.get(v, 0) for counter in matrix.values())]
    rows = []
    for comp in components:
        vid = str(comp.get("version_id"))
        counter = matrix.get(vid, Counter())
        rows.append({
            "version_id": vid,
            "version_short": short_name(vid),
            "role": comp.get("role"),
            "scope": comp.get("scope", []),
            "counts": {v: counter.get(v, 0) for v in views},
            "total": sum(counter.values()),
        })
    return {"views": views, "rows": rows}


def compare_matrix(manifest: Mapping[str, Any]) -> dict[str, Any]:
    components = {str(c.get("version_id")): c for c in manifest.get("components", []) or []}
    files = manifest.get("effective_files", {}) or {}
    rows: dict[str, dict[str, Any]] = {}
    for item in files.values():
        version = str(item.get("source_version") or "")
        if version not in rows:
            comp = components.get(version, {})
            rows[version] = {
                "version_id": version,
                "version_short": short_name(version),
                "role": comp.get("role", "unknown"),
                "base": 0,
                "add": 0,
                "replace": 0,
                "delete": 0,
                "by_type": Counter(),
            }
        op = str(item.get("operation") or "unknown")
        if op in rows[version]:
            rows[version][op] += 1
        rows[version]["by_type"][str(item.get("file_type") or "other")] += 1
    out = []
    for comp in manifest.get("components", []) or []:
        vid = str(comp.get("version_id"))
        row = rows.get(vid)
        if row:
            row = dict(row)
            row["by_type"] = dict(sorted(row["by_type"].items()))
            row["total"] = row["base"] + row["add"] + row["replace"] + row["delete"]
            out.append(row)
    return {"rows": out}


def write_release_preview_outputs(out_dir: str | Path, preview: Mapping[str, Any]) -> dict[str, str]:
    root = Path(out_dir)
    root.mkdir(parents=True, exist_ok=True)
    release_manifest = write_json(root / "release_manifest.json", preview)
    release_delta = write_json(root / "release_delta.json", {"delta": preview.get("delta", []), "summary": preview.get("summary", {})})
    csh = root / "release_preview.csh"
    lines = ["#!/bin/csh", "# Preview generated by lib_guard effective release-preview", ""]
    for row in preview.get("delta", []):
        action = row.get("action")
        if action == "delete":
            lines.append(f"# DELETE {row.get('release_path')}")
        else:
            lines.append(f"# {str(action).upper()} {row.get('relpath')}")
            lines.append(f"mkdir -p `dirname {row.get('release_path')}`")
            if row.get("link_mode") == "copy":
                lines.append(f"cp -f {row.get('source_abs')} {row.get('release_path')}")
            else:
                lines.append(f"ln -sfn {row.get('source_abs')} {row.get('release_path')}")
        lines.append("")
    csh.write_text("\n".join(lines), encoding="utf-8")
    return {"release_manifest": str(release_manifest), "release_delta": str(release_delta), "release_preview_csh": str(csh)}
