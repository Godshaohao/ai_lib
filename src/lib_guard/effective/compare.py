from __future__ import annotations

import json
import os
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from lib_guard.effective.manifest import (
    canonical_relpath,
    find_library,
    find_version,
    infer_file_type,
    inventory_for_version,
    read_json,
    short_name,
    write_json,
)
from lib_guard.effective.pointer import safe_name

COMPARE_SCHEMA_VERSION = "effective_compare.v1"


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_target(spec: str | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(spec, Mapping):
        target_type = str(spec.get("type") or spec.get("target_type") or "").strip()
        target_id = str(spec.get("id") or spec.get("target_id") or spec.get("path") or "").strip()
        return {"type": target_type, "id": target_id, **dict(spec)}
    text = str(spec or "").strip()
    if ":" not in text:
        raise ValueError(f"target must be TYPE:ID/PATH, got: {spec}")
    target_type, target_id = text.split(":", 1)
    return {"type": target_type.strip(), "id": target_id.strip(), "spec": text}


def _raw_file_records(version_id: str, version: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    raw_root = str(version.get("raw_path") or version.get("version_path") or "")
    result: dict[str, dict[str, Any]] = {}
    for item in inventory_for_version(version):
        path = item.get("relpath") or item.get("path") or item.get("relative_path") or item.get("name")
        if not path:
            continue
        rel = canonical_relpath(str(path))
        source_path = str(item.get("path") or rel)
        source_abs = f"{raw_root.rstrip('/')}/{source_path}" if raw_root else source_path
        result[rel] = {
            "relpath": rel,
            "file_type": infer_file_type(rel, item.get("file_type")),
            "target_type": "raw",
            "target_id": version_id,
            "source_version": version_id,
            "source_path": source_path,
            "source_abs": source_abs,
            "raw_root": raw_root,
            "hash": item.get("sha256") or item.get("hash") or item.get("content_hash"),
            "size_bytes": item.get("size_bytes") or item.get("size"),
        }
    return dict(sorted(result.items()))


def _effective_file_records(manifest: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for rel, info in (manifest.get("effective_files", {}) or {}).items():
        rel2 = canonical_relpath(str(rel))
        raw_root = str(info.get("raw_root") or "")
        source_path = str(info.get("source_path") or rel2)
        source_abs = str(info.get("source_abs") or (f"{raw_root.rstrip('/')}/{source_path}" if raw_root else source_path))
        result[rel2] = {
            "relpath": rel2,
            "file_type": info.get("file_type") or infer_file_type(rel2),
            "target_type": "effective",
            "target_id": manifest.get("effective_id"),
            "source_version": info.get("source_version"),
            "source_path": source_path,
            "source_abs": source_abs,
            "raw_root": raw_root,
            "hash": info.get("hash"),
            "size_bytes": info.get("size_bytes"),
            "operation": info.get("operation"),
            "replaced_from": info.get("replaced_from"),
        }
    return dict(sorted(result.items()))


def _release_file_records(release_manifest: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    files = release_manifest.get("release_files", {}) or release_manifest.get("files", {}) or {}
    for rel, info in files.items():
        rel2 = canonical_relpath(str(rel))
        result[rel2] = {
            "relpath": rel2,
            "file_type": info.get("file_type") or infer_file_type(rel2),
            "target_type": "release",
            "target_id": release_manifest.get("release_id") or release_manifest.get("effective_id"),
            "source_version": info.get("source_version"),
            "source_path": info.get("source_path") or rel2,
            "source_abs": info.get("source_abs") or info.get("release_path") or info.get("source_path") or rel2,
            "release_path": info.get("release_path"),
            "hash": info.get("hash"),
            "size_bytes": info.get("size_bytes"),
        }
    return dict(sorted(result.items()))


def _candidate_effective_paths(library: str, effective_id: str, search_roots: Sequence[str | Path] | None = None) -> list[Path]:
    safe_lib = safe_name(library)
    roots = [Path(x) for x in (search_roots or [])]
    if not roots:
        roots = [Path.cwd(), Path.cwd() / "reports", Path.cwd() / "catalog"]
    candidates: list[Path] = []
    for root in roots:
        candidates.extend([
            root / "libraries" / safe_lib / "effective" / safe_name(effective_id) / "effective_manifest.json",
            root / "effective" / safe_lib / safe_name(effective_id) / "effective_manifest.json",
            root / safe_lib / "effective" / safe_name(effective_id) / "effective_manifest.json",
        ])
        if root.exists():
            # Bounded search: only under common effective folders.
            for base in [root / "libraries" / safe_lib / "effective", root / "effective" / safe_lib, root / safe_lib / "effective"]:
                if base.exists():
                    candidates.extend(base.glob(f"*/effective_manifest.json"))
    dedup: list[Path] = []
    seen = set()
    for path in candidates:
        key = str(path)
        if key not in seen:
            dedup.append(path)
            seen.add(key)
    return dedup


def find_effective_manifest_path(library: str, effective_id_or_path: str, search_roots: Sequence[str | Path] | None = None) -> Path:
    raw = Path(effective_id_or_path)
    if raw.exists() and raw.is_file():
        return raw
    if raw.exists() and raw.is_dir() and (raw / "effective_manifest.json").exists():
        return raw / "effective_manifest.json"
    for path in _candidate_effective_paths(library, effective_id_or_path, search_roots):
        if not path.exists() or not path.is_file():
            continue
        data = read_json(path)
        if str(data.get("effective_id") or path.parent.name) == str(effective_id_or_path) or path.parent.name == safe_name(effective_id_or_path):
            return path
    raise FileNotFoundError(f"effective manifest not found: {effective_id_or_path}")


def target_file_map(
    catalog: Mapping[str, Any] | None,
    library: str,
    target: str | Mapping[str, Any],
    *,
    search_roots: Sequence[str | Path] | None = None,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    spec = parse_target(target)
    ttype = str(spec.get("type") or "").lower()
    tid = str(spec.get("id") or "")
    if ttype == "raw":
        if catalog is None:
            raise ValueError("catalog is required for raw target")
        lib = find_library(catalog, library)
        version = find_version(lib, tid)
        meta = {"type": "raw", "id": tid, "label": f"raw:{tid}", "path": version.get("raw_path") or version.get("version_path") or ""}
        return meta, _raw_file_records(tid, version)
    if ttype == "effective":
        path = find_effective_manifest_path(library, tid, search_roots)
        manifest = read_json(path)
        effective_id = str(manifest.get("effective_id") or path.parent.name)
        meta = {
            "type": "effective",
            "id": effective_id,
            "label": f"effective:{effective_id}",
            "manifest": str(path),
            "html": str(path.parent / "index.html") if (path.parent / "index.html").exists() else "",
            "base_full_version": manifest.get("base_full_version"),
            "accepted_updates": list(manifest.get("accepted_updates", []) or []),
        }
        return meta, _effective_file_records(manifest)
    if ttype == "release":
        path = Path(tid)
        if path.is_dir():
            path = path / "release_manifest.json"
        if not path.exists():
            raise FileNotFoundError(f"release manifest not found: {tid}")
        manifest = read_json(path)
        release_id = str(manifest.get("release_id") or path.parent.name)
        meta = {"type": "release", "id": release_id, "label": f"release:{release_id}", "manifest": str(path)}
        return meta, _release_file_records(manifest)
    raise ValueError(f"unsupported target type: {ttype}")


def _same_file(old: Mapping[str, Any], new: Mapping[str, Any]) -> bool:
    # Prefer hash when available. Fall back to source identity and size.
    old_hash = old.get("hash")
    new_hash = new.get("hash")
    if old_hash and new_hash:
        return str(old_hash) == str(new_hash)
    return (
        str(old.get("source_version") or "") == str(new.get("source_version") or "")
        and str(old.get("source_path") or "") == str(new.get("source_path") or "")
        and str(old.get("size_bytes") or "") == str(new.get("size_bytes") or "")
    )


def _action_for(rel: str, old_map: Mapping[str, Mapping[str, Any]], new_map: Mapping[str, Mapping[str, Any]]) -> str:
    old = old_map.get(rel)
    new = new_map.get(rel)
    if old and not new:
        return "remove"
    if new and not old:
        return "add"
    if old and new and _same_file(old, new):
        return "keep"
    return "replace"


def _deep_diff_command(library: str, rel: str, old: Mapping[str, Any] | None, new: Mapping[str, Any] | None) -> str:
    if not old or not new:
        return ""
    old_version = str(old.get("source_version") or "")
    new_version = str(new.get("source_version") or "")
    if old_version and new_version and old_version != new_version and rel == canonical_relpath(rel):
        file_type = infer_file_type(rel, new.get("file_type") or old.get("file_type"))
        return f"$PROJ/scripts/lg.csh fd {library} {new_version} {rel} --base {old_version} --type {file_type}"
    old_abs = str(old.get("source_abs") or old.get("source_path") or "")
    new_abs = str(new.get("source_abs") or new.get("source_path") or "")
    if old_abs and new_abs:
        return f"diff -u {old_abs} {new_abs}"
    return ""


def _infer_mode(old_meta: Mapping[str, Any], new_meta: Mapping[str, Any]) -> str:
    old_t = old_meta.get("type")
    new_t = new_meta.get("type")
    if old_t == "effective" and new_t == "effective":
        return "patch_delta"
    if old_t == "effective" and new_t == "raw":
        return "full_absorb_check"
    if old_t == "release" or new_t == "release":
        return "release_delta_reference"
    return "manual_compare"


def make_compare_id(old_meta: Mapping[str, Any], new_meta: Mapping[str, Any], *, prefix: str | None = None) -> str:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    old = safe_name(f"{old_meta.get('type')}_{old_meta.get('id')}")
    new = safe_name(f"{new_meta.get('type')}_{new_meta.get('id')}")
    return safe_name(f"{prefix or stamp}__{old}__vs__{new}")


def compare_file_maps(
    library: str,
    old_meta: Mapping[str, Any],
    old_map: Mapping[str, Mapping[str, Any]],
    new_meta: Mapping[str, Any],
    new_map: Mapping[str, Mapping[str, Any]],
    *,
    mode: str | None = None,
    compare_id: str | None = None,
    owner_target: str | None = None,
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    action_counts: Counter[str] = Counter()
    by_type: dict[str, Counter[str]] = {}
    transitions: Counter[str] = Counter()
    for rel in sorted(set(old_map) | set(new_map)):
        old = old_map.get(rel)
        new = new_map.get(rel)
        action = _action_for(rel, old_map, new_map)
        file_type = str((new or old or {}).get("file_type") or "other")
        action_counts[action] += 1
        by_type.setdefault(file_type, Counter())[action] += 1
        old_src = str((old or {}).get("source_version") or "-")
        new_src = str((new or {}).get("source_version") or "-")
        transitions[f"{old_src} -> {new_src}"] += 1
        row = {
            "relpath": rel,
            "action": action,
            "file_type": file_type,
            "old_source_version": None if not old else old.get("source_version"),
            "new_source_version": None if not new else new.get("source_version"),
            "old_source_path": None if not old else old.get("source_path"),
            "new_source_path": None if not new else new.get("source_path"),
            "old_source_abs": None if not old else old.get("source_abs"),
            "new_source_abs": None if not new else new.get("source_abs"),
            "old_hash": None if not old else old.get("hash"),
            "new_hash": None if not new else new.get("hash"),
            "old_size_bytes": None if not old else old.get("size_bytes"),
            "new_size_bytes": None if not new else new.get("size_bytes"),
            "deep_diff_command": _deep_diff_command(library, rel, old, new) if action == "replace" else "",
        }
        if action != "keep":
            rows.append(row)
    risk_flags = []
    if action_counts.get("remove", 0):
        risk_flags.append({"type": "REMOVED_FILES", "count": action_counts["remove"], "message": "new target 缺少 old target 中存在的文件"})
    if action_counts.get("replace", 0):
        risk_flags.append({"type": "REPLACED_FILES", "count": action_counts["replace"], "message": "存在来源或 hash/size 变化的文件"})
    if any(row.get("old_hash") is None or row.get("new_hash") is None for row in rows if row.get("action") == "replace"):
        risk_flags.append({"type": "HASH_INCOMPLETE", "message": "部分 replace 文件缺少 hash，当前以 source/size 兜底判断"})
    readable_risk_messages = {
        "REMOVED_FILES": "new target 缺少 old target 中存在的文件",
        "REPLACED_FILES": "存在来源、hash 或 size 变化的文件",
        "HASH_INCOMPLETE": "部分 replace 文件缺少 hash，当前以 source/size 兜底判断",
    }
    for risk in risk_flags:
        risk_type = str(risk.get("type") or "")
        if risk_type in readable_risk_messages:
            risk["message"] = readable_risk_messages[risk_type]
    summary = {
        "total_files_old": len(old_map),
        "total_files_new": len(new_map),
        "changed_files": len(rows),
        "actions": dict(sorted(action_counts.items())),
        "by_type": {k: dict(sorted(v.items())) for k, v in sorted(by_type.items())},
        "source_transitions": dict(transitions.most_common(30)),
        "risk_count": len(risk_flags),
    }
    actual_mode = mode or _infer_mode(old_meta, new_meta)
    cid = compare_id or make_compare_id(old_meta, new_meta)
    return {
        "schema_version": COMPARE_SCHEMA_VERSION,
        "library_id": library,
        "compare_id": cid,
        "mode": actual_mode,
        "old_target": dict(old_meta),
        "new_target": dict(new_meta),
        "owner_target": owner_target or new_meta.get("label") or f"{new_meta.get('type')}:{new_meta.get('id')}",
        "summary": summary,
        "changed_files": rows,
        "deep_diff_commands": [row["deep_diff_command"] for row in rows if row.get("deep_diff_command")][:100],
        "risk_flags": risk_flags,
        "created_at": now_iso(),
    }


def build_compare_manifest(
    catalog: Mapping[str, Any] | None,
    library: str,
    old_target: str | Mapping[str, Any],
    new_target: str | Mapping[str, Any],
    *,
    search_roots: Sequence[str | Path] | None = None,
    mode: str | None = None,
    compare_id: str | None = None,
    owner_target: str | None = None,
) -> dict[str, Any]:
    resolved_library = library
    if catalog is not None:
        try:
            lib = find_library(catalog, library)
            resolved_library = str(lib.get("library_id") or lib.get("library_name") or library)
        except Exception:
            resolved_library = library
    old_meta, old_map = target_file_map(catalog, resolved_library, old_target, search_roots=search_roots)
    new_meta, new_map = target_file_map(catalog, resolved_library, new_target, search_roots=search_roots)
    return compare_file_maps(
        resolved_library,
        old_meta,
        old_map,
        new_meta,
        new_map,
        mode=mode,
        compare_id=compare_id,
        owner_target=owner_target,
    )


def write_compare_manifest(out_dir: str | Path, manifest: Mapping[str, Any]) -> Path:
    root = Path(out_dir)
    root.mkdir(parents=True, exist_ok=True)
    return write_json(root / "compare_manifest.json", manifest)


def discover_compare_reports(out: str | Path, libraries: Sequence[Mapping[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    out_p = Path(out)
    result: dict[str, list[dict[str, Any]]] = {}
    for lib in libraries:
        lib_id = str(lib.get("library_id") or lib.get("display_name") or lib.get("library_name") or "")
        safe_lib = safe_name(lib_id)
        rows: list[dict[str, Any]] = []
        roots = [out_p / "libraries" / safe_lib / "compares", out_p / "compares" / safe_lib]
        seen = set()
        for root in roots:
            if not root.exists():
                continue
            for path in root.glob("*/compare_manifest.json"):
                if path in seen:
                    continue
                seen.add(path)
                try:
                    data = read_json(path)
                except Exception:
                    continue
                summary = data.get("summary", {}) or {}
                html = path.parent / "index.html"
                rows.append({
                    "compare_id": data.get("compare_id") or path.parent.name,
                    "mode": data.get("mode") or "manual_compare",
                    "old_target": data.get("old_target", {}) or {},
                    "new_target": data.get("new_target", {}) or {},
                    "owner_target": data.get("owner_target") or "",
                    "summary": summary,
                    "risk_flags": data.get("risk_flags", []) or [],
                    "risk_count": int(summary.get("risk_count", len(data.get("risk_flags", []) or [])) or 0),
                    "changed_files": int(summary.get("changed_files", len(data.get("changed_files", []) or [])) or 0),
                    "actions": summary.get("actions", {}) or {},
                    "manifest": str(path),
                    "html": str(html) if html.exists() else "",
                    "created_at": data.get("created_at") or "",
                })
        rows.sort(key=lambda x: str(x.get("created_at") or x.get("compare_id") or ""), reverse=True)
        result[lib_id] = rows
    return result
