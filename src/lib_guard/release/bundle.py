"""Manifest helpers for manifest-driven release bundles."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping
import getpass
import json

from lib_guard.atomic import atomic_write_json
from lib_guard.view_types import RELEASE_VIEW_DIR_ALIASES, release_view_dir

VIEW_DIR_ALIASES = RELEASE_VIEW_DIR_ALIASES
VIEW_DIRS = set(VIEW_DIR_ALIASES)


def utc_now() -> str:
    return datetime.now(tz=timezone.utc).isoformat().replace("+00:00", "Z")


def read_json(path: str | Path, default: Any = None) -> Any:
    p = Path(path)
    if not p.exists():
        return default
    return json.loads(p.read_text(encoding="utf-8-sig"))


def write_json(path: str | Path, data: Any) -> None:
    atomic_write_json(path, data, lock=True)


def manifest_run_dir(manifest_path: str | Path, out_dir: str | Path | None = None) -> Path:
    return Path(out_dir) if out_dir else Path(manifest_path).parent


def load_release_manifest(
    manifest_path: str | Path,
    *,
    release_root: str | Path | None = None,
    alias: str | None = None,
) -> dict[str, Any]:
    path = Path(manifest_path)
    data = read_json(path, {})
    if not isinstance(data, Mapping):
        raise ValueError(f"release manifest must be a JSON object: {path}")
    manifest = dict(data)
    manifest.setdefault("schema_version", "1.0")
    manifest.setdefault("release_id", path.parent.name or f"release_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
    if alias:
        manifest["alias"] = alias
    manifest.setdefault("alias", "current")
    if release_root:
        manifest["release_root"] = str(release_root)
    if not manifest.get("release_root"):
        raise ValueError("release manifest requires release_root")
    libraries = manifest.get("libraries")
    files = manifest.get("files")
    if (not isinstance(libraries, list) or not libraries) and (not isinstance(files, list) or not files):
        raise ValueError("release manifest requires non-empty libraries or files")
    normalized = []
    for idx, item in enumerate(libraries or []):
        if not isinstance(item, Mapping):
            raise ValueError(f"release manifest libraries[{idx}] must be an object")
        entry = dict(item)
        entry.setdefault("library_type", "unknown")
        package_type = str(entry.get("package_type") or entry.get("delivery_type") or "").strip().upper()
        if package_type.startswith("UNKNOWN") or entry.get("requires_package_type_confirmation"):
            raise ValueError(
                f"release manifest libraries[{idx}] has unconfirmed package_type; "
                "confirm package_type before release"
            )
        if not entry.get("library_name"):
            raise ValueError(f"release manifest libraries[{idx}] requires library_name")
        if not entry.get("version_id"):
            entry["version_id"] = str(entry.get("version_key") or "unknown").split("/")[-1]
        if not entry.get("source_path"):
            raise ValueError(f"release manifest libraries[{idx}] requires source_path")
        entry.setdefault("version_key", f"{entry.get('library_type')}/{entry.get('library_name')}/{entry.get('version_id')}")
        entry.setdefault("manual_accept", False)
        normalized.append(entry)
    manifest["libraries"] = normalized
    normalized_files = []
    for idx, item in enumerate(files or []):
        if not isinstance(item, Mapping):
            raise ValueError(f"release manifest files[{idx}] must be an object")
        entry = dict(item)
        if not entry.get("source_path"):
            raise ValueError(f"release manifest files[{idx}] requires source_path")
        if not entry.get("target_relpath") and not entry.get("relative_path"):
            raise ValueError(f"release manifest files[{idx}] requires target_relpath")
        entry["target_relpath"] = normalize_release_relpath(
            str(entry.get("target_relpath") or entry.get("relative_path")).replace("\\", "/"),
            file_type=entry.get("file_type"),
        ).as_posix()
        entry.setdefault("relative_path", entry["target_relpath"])
        entry.setdefault("library_type", manifest.get("library_type", "unknown"))
        entry.setdefault("library_name", manifest.get("library_name", "unknown"))
        entry.setdefault("version_id", manifest.get("snapshot_id") or manifest.get("release_id"))
        normalized_files.append(entry)
    manifest["files"] = normalized_files
    return manifest


def release_dir_for(manifest: Mapping[str, Any]) -> Path:
    return Path(str(manifest.get("release_root")))


def target_for_library(manifest: Mapping[str, Any], library: Mapping[str, Any]) -> Path:
    return release_dir_for(manifest) / str(library.get("library_name") or "unknown")


def _classify_file_type(source_root: Path, file_path: Path) -> str:
    from lib_guard.scan.inventory import FileClassifier

    rel = file_path.relative_to(source_root).as_posix()
    record = FileClassifier().classify({"path": rel, "name": file_path.name})
    return str(record.get("file_type") or "unknown")


def canonical_view_dir(value: Any) -> str:
    return release_view_dir(value)


def _release_view_for_file_type(file_type: Any) -> str:
    return release_view_dir(file_type)


def normalize_release_relpath(relpath: str | Path, *, file_type: Any = None) -> Path:
    rel = Path(str(relpath).replace("\\", "/"))
    parts = [part for part in rel.parts if part not in {"", "."}]
    for idx, part in enumerate(parts):
        view = VIEW_DIR_ALIASES.get(part.lower())
        if view:
            tail = parts[idx + 1 :]
            return Path(view, *tail) if tail else Path(view)
    view = _release_view_for_file_type(file_type)
    return Path(view, *parts) if parts else Path(view)


def release_relative_path(source_root: str | Path, file_path: str | Path) -> Path:
    source = Path(source_root)
    file = Path(file_path)
    rel = file.relative_to(source)
    file_type = _classify_file_type(source, file)
    return normalize_release_relpath(rel, file_type=file_type)


def iter_release_files(manifest: Mapping[str, Any]) -> list[dict[str, Any]]:
    planned: list[dict[str, Any]] = []
    seen_targets: dict[str, dict[str, Any]] = {}
    for entry in manifest.get("files", []) or []:
        rel_text = str(entry.get("target_relpath") or entry.get("relative_path") or "").replace("\\", "/")
        source = Path(str(entry.get("source_path") or ""))
        item = {
            "library_type": entry.get("library_type") or manifest.get("library_type"),
            "library_name": entry.get("library_name") or manifest.get("library_name"),
            "version_id": entry.get("version_id") or manifest.get("snapshot_id"),
            "version_key": entry.get("version_key"),
            "snapshot_id": entry.get("snapshot_id") or manifest.get("snapshot_id"),
            "source_package": entry.get("source_package"),
            "source_kind": entry.get("source_kind"),
            "source_root": str(source.parent),
            "source_path": str(source),
            "relative_path": rel_text,
            "target_path": str(release_dir_for(manifest) / rel_text),
            "file_type": entry.get("file_type") or (_classify_file_type(source.parent, source) if source.exists() else None),
            "view": entry.get("view") or (rel_text.split("/", 1)[0] if rel_text else None),
            "scan_html": entry.get("scan_html"),
            "diff_html": entry.get("diff_html"),
        }
        if rel_text in seen_targets:
            item["error"] = f"release target collision: {rel_text}"
            item["collides_with"] = seen_targets[rel_text].get("source_path")
        else:
            seen_targets[rel_text] = item
        planned.append(item)
    for entry in manifest.get("libraries", []) or []:
        source = Path(str(entry.get("source_path") or ""))
        if not source.exists():
            planned.append(
                {
                    "library_type": entry.get("library_type"),
                    "library_name": entry.get("library_name"),
                    "version_id": entry.get("version_id"),
                    "version_key": entry.get("version_key"),
                    "source_path": str(source),
                    "relative_path": None,
                    "target_path": None,
                    "file_type": None,
                    "error": f"release source does not exist: {source}",
                }
            )
            continue
        files = [source] if source.is_file() else [item for item in source.rglob("*") if item.is_file()]
        for file_path in sorted(files, key=lambda item: item.as_posix().lower()):
            rel = release_relative_path(source if source.is_dir() else source.parent, file_path)
            rel_text = rel.as_posix()
            file_type = _classify_file_type(source if source.is_dir() else source.parent, file_path)
            item = {
                "library_type": entry.get("library_type"),
                "library_name": entry.get("library_name"),
                "version_id": entry.get("version_id"),
                "version_key": entry.get("version_key"),
                "source_root": str(source),
                "source_path": str(file_path),
                "relative_path": rel_text,
                "target_path": str(release_dir_for(manifest) / rel),
                "file_type": file_type,
                "scan_html": entry.get("scan_html"),
                "diff_html": entry.get("diff_html"),
                "source_package": entry.get("source_package") or entry.get("version_id"),
                "source_kind": entry.get("source_kind") or "package",
                "snapshot_id": entry.get("snapshot_id") or manifest.get("snapshot_id"),
                "view": rel_text.split("/", 1)[0] if rel_text else None,
            }
            if rel_text in seen_targets:
                item["error"] = f"release target collision: {rel_text}"
                item["collides_with"] = seen_targets[rel_text].get("source_path")
            else:
                seen_targets[rel_text] = item
            planned.append(item)
    return planned


def _selected_versions(catalog: Mapping[str, Any], library: str | None, versions: set[str], stage: str | None) -> list[tuple[Mapping[str, Any], Mapping[str, Any]]]:
    selected: list[tuple[Mapping[str, Any], Mapping[str, Any]]] = []
    for lib in catalog.get("libraries", []) or []:
        if library and library not in {str(lib.get("library_name")), str(lib.get("library_id"))}:
            continue
        for version in lib.get("versions", []) or []:
            if versions and str(version.get("version_id")) not in versions and str(version.get("version_key")) not in versions:
                continue
            if stage and version.get("stage") != stage:
                continue
            if not versions and not (version.get("scan", {}) or {}).get("scan_dir"):
                continue
            selected.append((lib, version))
    return selected


def create_manifest_template_from_catalog(
    catalog_path: str | Path,
    out_path: str | Path,
    *,
    release_root: str | Path,
    alias: str = "current",
    release_id: str | None = None,
    library: str | None = None,
    versions: list[str] | None = None,
    stage: str | None = None,
    created_by: str | None = None,
) -> dict[str, Any]:
    catalog = read_json(catalog_path, {}) or {}
    requested = {str(v) for v in versions or []}
    selected = _selected_versions(catalog, library, requested, stage)
    if not selected:
        raise ValueError("no catalog versions selected for release manifest")
    if requested:
        seen_libraries: set[str] = set()
        for lib, version in selected:
            lib_key = str(lib.get("library_id") or version.get("library_name") or lib.get("library_name"))
            if lib_key in seen_libraries:
                raise ValueError(f"multiple versions for one library selected in release manifest: {lib_key}")
            seen_libraries.add(lib_key)
    else:
        latest_by_library: dict[str, tuple[Mapping[str, Any], Mapping[str, Any]]] = {}
        for lib, version in selected:
            lib_key = str(lib.get("library_id") or version.get("library_name") or lib.get("library_name"))
            latest_by_library[lib_key] = (lib, version)
        selected = list(latest_by_library.values())
    libraries = []
    for lib, version in selected:
        scan = version.get("scan", {}) or {}
        diff = version.get("diff", {}) or {}
        scan_dir = scan.get("scan_dir")
        scan_meta = read_json(Path(scan_dir) / "scan_meta.json", {}) if scan_dir else {}
        source_path = scan_meta.get("root_path") or version.get("raw_path")
        libraries.append(
            {
                "library_type": version.get("library_type") or lib.get("library_type"),
                "library_name": version.get("library_name") or lib.get("library_name"),
                "version_id": version.get("version_id"),
                "version_key": version.get("version_key"),
                "scan_dir": scan_dir,
                "source_path": source_path,
                "scan_html": scan.get("scan_html"),
                "diff_html": diff.get("adjacent_diff_html") or diff.get("cumulative_diff_html"),
                "manual_accept": False,
                "note": "请人工确认该版本进入本次 release 组合",
            }
        )
    manifest = {
        "schema_version": "1.0",
        "release_id": release_id or f"{str(alias).upper()}_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
        "alias": alias,
        "release_root": str(release_root),
        "created_by": created_by or getpass.getuser(),
        "created_at": utc_now(),
        "catalog_path": str(catalog_path),
        "libraries": libraries,
    }
    write_json(out_path, manifest)
    return manifest


def create_manifest_from_snapshot(
    snapshot_path: str | Path,
    out_path: str | Path,
    *,
    release_root: str | Path,
    alias: str = "current",
    release_id: str | None = None,
    created_by: str | None = None,
) -> dict[str, Any]:
    snapshot = read_json(snapshot_path, {}) or {}
    files = []
    for item in snapshot.get("resolved_files", []) or []:
        if not isinstance(item, Mapping):
            continue
        target_relpath = normalize_release_relpath(
            str(item.get("target_relpath") or ""),
            file_type=item.get("file_type"),
        ).as_posix()
        files.append(
            {
                "target_relpath": target_relpath,
                "source_path": item.get("source_path"),
                "source_package": item.get("source_package"),
                "source_kind": item.get("source_kind"),
                "library_type": snapshot.get("library_type"),
                "library_name": snapshot.get("library_name"),
                "snapshot_id": snapshot.get("snapshot_id"),
                "file_type": item.get("file_type"),
                "view": item.get("view"),
            }
        )
    if not files:
        raise ValueError(f"snapshot has no resolved_files: {snapshot_path}")
    manifest = {
        "schema_version": "1.0",
        "release_id": release_id or f"{str(alias).upper()}_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
        "alias": alias,
        "release_root": str(release_root),
        "created_by": created_by or getpass.getuser(),
        "created_at": utc_now(),
        "snapshot_path": str(snapshot_path),
        "snapshot_id": snapshot.get("snapshot_id"),
        "library_type": snapshot.get("library_type"),
        "library_name": snapshot.get("library_name"),
        "base_package": snapshot.get("base_package"),
        "updates": snapshot.get("updates", []),
        "resolved_views": snapshot.get("resolved_views", {}),
        "files": files,
        "libraries": [],
    }
    write_json(out_path, manifest)
    return manifest
