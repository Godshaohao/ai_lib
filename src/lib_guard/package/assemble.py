from __future__ import annotations

from collections import OrderedDict
from pathlib import Path
from typing import Any, Mapping
import json

from .classifier import file_type_to_view


def _read_json(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _write_json(path: str | Path, data: Mapping[str, Any]) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _versions(catalog: Mapping[str, Any], library: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for lib in catalog.get("libraries", []) or []:
        if library not in {str(lib.get("library_name")), str(lib.get("library_id"))}:
            continue
        for version in lib.get("versions", []) or []:
            item = dict(version)
            item.setdefault("library_type", lib.get("library_type"))
            item.setdefault("library_name", lib.get("library_name"))
            rows.append(item)
    return rows


def _find_version(rows: list[Mapping[str, Any]], version_id: str) -> dict[str, Any]:
    for item in rows:
        if version_id in {str(item.get("version_id")), str(item.get("version_key"))}:
            return dict(item)
    raise FileNotFoundError(f"catalog package not found: {version_id}")


def _file_record(package: Mapping[str, Any], source_root: Path, file_path: Path, *, source_kind: str) -> dict[str, Any] | None:
    from lib_guard.release.bundle import release_relative_path
    from lib_guard.scan.inventory import FileClassifier

    rel = file_path.relative_to(source_root).as_posix()
    classified = FileClassifier().classify({"path": rel, "name": file_path.name})
    file_type = str(classified.get("file_type") or "unknown")
    if file_type == "unknown" and not package.get("manual_include"):
        return None
    target_relpath = release_relative_path(source_root, file_path).as_posix()
    view = target_relpath.split("/", 1)[0] if "/" in target_relpath else file_type_to_view(file_type)
    return {
        "target_relpath": target_relpath,
        "source_package": package.get("version_id") or package.get("version_key"),
        "source_path": str(file_path),
        "file_type": file_type,
        "view": view,
        "source_kind": source_kind,
    }


def _records_for(package: Mapping[str, Any], *, source_kind: str) -> list[dict[str, Any]]:
    root = Path(str(package.get("raw_path") or package.get("source_path") or ""))
    if not root.exists():
        return []
    files = [root] if root.is_file() else [item for item in root.rglob("*") if item.is_file()]
    records = []
    for file_path in sorted(files, key=lambda p: p.as_posix().lower()):
        record = _file_record(package, root if root.is_dir() else root.parent, file_path, source_kind=source_kind)
        if record:
            records.append(record)
    return records


def assemble_snapshot(
    catalog_path: str | Path,
    *,
    library: str,
    base_version: str,
    updates: list[str],
    out_path: str | Path | None = None,
    snapshot_id: str | None = None,
) -> dict[str, Any]:
    catalog = _read_json(catalog_path)
    rows = _versions(catalog, library)
    base = _find_version(rows, base_version)
    update_items = [_find_version(rows, item) for item in updates]

    selected: OrderedDict[str, dict[str, Any]] = OrderedDict()
    issues: list[dict[str, Any]] = []
    for record in _records_for(base, source_kind="base"):
        selected[record["target_relpath"]] = record

    for update in update_items:
        scope = set(str(v) for v in update.get("update_scope", []) or [])
        update_records = _records_for(update, source_kind="update")
        if scope:
            for target in [key for key, value in selected.items() if value.get("view") in scope]:
                selected.pop(target, None)
        for record in update_records:
            if scope and record.get("view") not in scope:
                continue
            if record["target_relpath"] in selected:
                issues.append(
                    {
                        "severity": "error",
                        "category": "target_collision",
                        "target_relpath": record["target_relpath"],
                        "source_package": record["source_package"],
                        "collides_with": selected[record["target_relpath"]].get("source_package"),
                    }
                )
            selected[record["target_relpath"]] = record

    resolved_views: dict[str, str] = {}
    for record in selected.values():
        resolved_views[str(record.get("view"))] = str(record.get("source_package"))

    snapshot = {
        "schema_version": "1.0",
        "status": "PASS" if not any(i.get("severity") == "error" for i in issues) else "FAILED",
        "snapshot_id": snapshot_id or Path(str(out_path)).stem if out_path else f"{library}_snapshot",
        "library_type": base.get("library_type"),
        "library_name": base.get("library_name") or library,
        "base_package": base.get("version_id"),
        "updates": [item.get("version_id") for item in update_items],
        "resolved_views": dict(sorted(resolved_views.items())),
        "resolved_files": list(selected.values()),
        "issues": issues,
    }
    if out_path:
        _write_json(out_path, snapshot)
    return snapshot
