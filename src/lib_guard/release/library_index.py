"""Index already published libraries without treating releases as RAW inputs."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any, Mapping
import json
import os

from lib_guard.atomic import atomic_write_json


SCHEMA_VERSION = "release_library_index.v1"
_IGNORED_DIRS = frozenset({".staging", "release_runs", "reports", "scan_out", "diff", "html", "history"})


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _is_under(root: Path, path: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def _manifest_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _library_id(component: Mapping[str, Any]) -> str:
    explicit = str(component.get("library_id") or "").strip()
    if explicit:
        return explicit
    library_type = str(component.get("library_type") or "ip").strip() or "ip"
    library_name = str(component.get("library_name") or "").strip()
    return f"{library_type}/{library_name}" if library_name else ""


def _published_at(manifest: Mapping[str, Any], path: Path) -> str:
    value = str(manifest.get("published_at") or manifest.get("created_at") or "").strip()
    if value:
        return value
    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _alias_is_active(root: Path, manifest: Mapping[str, Any], path: Path) -> bool:
    release_root = str(manifest.get("release_root") or "").strip()
    alias = str(manifest.get("alias") or "current").strip() or "current"
    if not release_root:
        return False
    declared_root = Path(release_root).expanduser()
    if not declared_root.is_absolute():
        declared_root = root / declared_root
    if not _is_under(root, declared_root):
        return False
    alias_path = declared_root / str(manifest.get("latest_name") or alias)
    if not (alias_path.exists() or alias_path.is_symlink()):
        return False
    try:
        return alias_path.resolve() == path.parent.resolve()
    except OSError:
        return False


def _release_row(root: Path, manifest_path: Path, manifest: Mapping[str, Any], component: Mapping[str, Any]) -> dict[str, Any]:
    alias = str(manifest.get("alias") or "current").strip() or "current"
    return {
        "release_id": str(manifest.get("release_id") or manifest_path.parent.name).strip(),
        "version_id": str(component.get("version_id") or "").strip(),
        "alias": alias,
        "link_mode": str(manifest.get("link_mode") or "unknown").strip() or "unknown",
        "manifest": str(manifest_path.resolve()),
        "manifest_sha256": _manifest_sha256(manifest_path),
        "status": "READY",
        "published_at": _published_at(manifest, manifest_path),
        "alias_link_active": _alias_is_active(root, manifest, manifest_path),
        "source": "release_manifest",
    }


def _release_sort_key(row: Mapping[str, Any]) -> tuple[str, str]:
    return (str(row.get("published_at") or ""), str(row.get("manifest") or ""))


def build_release_library_index(
    release_root: str | Path,
    *,
    max_depth: int = 8,
    max_manifests: int = 2000,
) -> dict[str, Any]:
    """Read release manifests below one root and group their published libraries."""

    root = Path(release_root).expanduser().resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"正式发布根目录不存在或不是目录: {root}")
    if max_depth < 0 or max_manifests < 1:
        raise ValueError("发布库读取范围必须为非负深度和正的清单上限")

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    invalid: list[dict[str, str]] = []
    warnings: list[str] = []
    found = 0
    truncated = False
    stages: list[dict[str, Any]] = []

    for directory, dirnames, filenames in os.walk(root, followlinks=False):
        current = Path(directory)
        try:
            depth = len(current.relative_to(root).parts)
        except ValueError:
            continue
        dirnames[:] = [name for name in dirnames if name not in _IGNORED_DIRS and depth < max_depth]
        if "release_manifest.json" not in filenames:
            continue
        manifest_path = current / "release_manifest.json"
        found += 1
        if found > max_manifests:
            truncated = True
            warnings.append(f"达到发布清单读取上限 {max_manifests}，未继续读取其余目录。")
            break
        if not _is_under(root, manifest_path):
            invalid.append({"manifest": str(manifest_path), "error": "清单路径越界，已忽略。"})
            continue
        try:
            loaded = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            invalid.append({"manifest": str(manifest_path), "error": f"清单无法读取：{exc}"})
            continue
        if not isinstance(loaded, Mapping):
            invalid.append({"manifest": str(manifest_path), "error": "清单顶层必须是 JSON 对象。"})
            continue
        components = loaded.get("release_components") or loaded.get("libraries")
        if loaded.get('publish_name') == current.name and current.parent == root:
            files = loaded.get('files') or []
            stages.append({
                'publish_name': current.name, 'path': str(current),
                'latest_name': str(loaded.get('latest_name') or 'latest'),
                'is_latest': _alias_is_active(root, loaded, manifest_path),
                'library_count': len(components) if isinstance(components, list) else 1,
                'libraries': components or [], 'file_count': len(files),
                'delivery_status': loaded.get('delivery_status') or 'APPLIED',
                'skipped_count': len(loaded.get('skipped_files') or []),
                'published_at': _published_at(loaded, manifest_path),
                'manifest': str(manifest_path),
                'broken_links': sum(1 for item in files if not (current / str(item.get('target_relpath') or '')).is_file()),
            })
        if not isinstance(components, list) or not components:
            invalid.append({"manifest": str(manifest_path), "error": "清单缺少 libraries 组件列表。"})
            continue
        valid_components = 0
        for component in components:
            if not isinstance(component, Mapping):
                continue
            library_id = _library_id(component)
            if not library_id:
                continue
            grouped[library_id].append(_release_row(root, manifest_path, loaded, component))
            valid_components += 1
        if not valid_components:
            invalid.append({"manifest": str(manifest_path), "error": "清单组件缺少 library_name 或 library_id。"})
    # Only report explicit stage directories and installed pointers; do not
    # reconstruct library/version provenance from RAW paths.
    unregistered: dict[str, dict[str, Any]] = {}
    pointers: list[tuple[str, Path]] = []
    for entry in root.iterdir():
        if entry.name in _IGNORED_DIRS or not entry.is_dir():
            continue
        destination = entry.resolve()
        if not _is_under(root, destination):
            continue
        if entry.is_symlink():
            pointers.append((entry.name, destination))
        if (entry.name.startswith('lib_NL') or (entry.is_symlink() and destination.parent.name == 'releases')) and not (destination / 'release_manifest.json').is_file():
            unregistered.setdefault(str(destination), {
                'name': destination.name, 'path': str(destination), 'pointers': [],
                'status': 'MISSING_MANIFEST',
            })
    for name, destination in pointers:
        if str(destination) in unregistered:
            unregistered[str(destination)]['pointers'].append(name)
    libraries: list[dict[str, Any]] = []
    for library_id in sorted(grouped):
        releases = sorted(grouped[library_id], key=_release_sort_key, reverse=True)
        # ``current`` is a named delivery channel.  An active ``stage`` or
        # ``approved`` link is useful history, but must not replace the
        # production current selection merely because it was published later.
        current_alias_rows = [row for row in releases if row.get("alias") == "current"]
        current = next((row for row in current_alias_rows if row["alias_link_active"]), None)
        current_source = "alias_link" if current else "manifest_fallback"
        current = current or (current_alias_rows[0] if current_alias_rows else (releases[0] if releases else None))
        libraries.append(
            {
                "library_id": library_id,
                "source_type": "正式发布库",
                "release_count": len(releases),
                "releases": releases,
                "current": (
                    {
                        "release_id": current["release_id"],
                        "version_id": current["version_id"],
                        "alias": current["alias"],
                        "link_mode": current["link_mode"],
                        "published_at": current["published_at"],
                        "manifest": current["manifest"],
                        "source": current_source,
                    }
                    if current
                    else None
                ),
            }
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "release_root": str(root),
        "refreshed_at": _now_iso(),
        "summary": {
            "library_count": len(libraries),
            "release_count": sum(len(row["releases"]) for row in libraries),
            "invalid_manifest_count": len(invalid),
            "raw_candidate_count": 0,
        },
        "libraries": libraries,
        "unregistered_deliveries": sorted(unregistered.values(), key=lambda row: row['path']),
        "stages": sorted(stages, key=lambda item: item['publish_name']),
        "invalid_manifests": invalid,
        "warnings": warnings,
        "truncated": truncated,
    }


def write_release_library_index(path: str | Path, index: Mapping[str, Any]) -> Path:
    return atomic_write_json(path, dict(index), lock=True)


def load_release_library_index(path: str | Path) -> dict[str, Any]:
    source = Path(path)
    if not source.is_file():
        return {"status": "MISSING", "libraries": [], "count": 0}
    loaded = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(loaded, Mapping) or loaded.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"正式发布库目录格式无效: {source}")
    rows = loaded.get("libraries")
    if not isinstance(rows, list):
        raise ValueError(f"正式发布库目录缺少 libraries: {source}")
    return {
        "status": "READY",
        "source": str(source.resolve()),
        "release_root": str(loaded.get("release_root") or ""),
        "refreshed_at": str(loaded.get("refreshed_at") or ""),
        "summary": dict(loaded.get("summary") or {}),
        "libraries": [dict(row) for row in rows if isinstance(row, Mapping)],
        "stages": [dict(row) for row in loaded.get('stages', []) if isinstance(row, Mapping)],
        "unregistered_deliveries": [dict(row) for row in loaded.get('unregistered_deliveries', []) if isinstance(row, Mapping)],
        "invalid_manifests": [dict(row) for row in loaded.get("invalid_manifests", []) if isinstance(row, Mapping)],
        "warnings": [str(row) for row in loaded.get("warnings", []) if str(row).strip()],
        "truncated": bool(loaded.get("truncated")),
    }
