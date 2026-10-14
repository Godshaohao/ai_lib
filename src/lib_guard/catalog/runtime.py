"""Runtime sidecar storage for catalog scan, diff, and release evidence."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping
import json

from lib_guard.atomic import atomic_write_json


RUNTIME_FILENAME = "catalog_runtime.json"
RUNTIME_SCHEMA_VERSION = "catalog_runtime.v1"

# Generated evidence is portable with a workspace; RAW source paths are not.
# Keep absolute fields for compatibility and persist a relative sibling for the
# artifact fields that must survive a complete workspace relocation.
_ARTIFACT_PATH_KEYS = frozenset(
    {
        "scan_dir",
        "scan_html",
        "adjacent_diff_dir",
        "adjacent_diff_html",
        "base_diff_dir",
        "base_diff_html",
        "cumulative_diff_dir",
        "cumulative_diff_html",
        "current_effective_diff_dir",
        "current_effective_diff_html",
        "previous_effective_diff_dir",
        "previous_effective_diff_html",
        "result_path",
        "release_dir",
        "manifest_path",
        "postcheck_path",
        "html_path",
    }
)
_ARTIFACT_ROOTS = frozenset({"scan_out", "diff", "reports", "file_diff", "release_area", "catalog"})


def _now() -> str:
    return datetime.now(tz=timezone.utc).isoformat().replace("+00:00", "Z")


def _read_json(path: str | Path, default: Any = None) -> Any:
    candidate = Path(path)
    if not candidate.exists() or not candidate.is_file():
        return default
    try:
        return json.loads(candidate.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError):
        return default


def catalog_runtime_path(catalog_path: str | Path) -> Path:
    """Return the sidecar path paired with a catalog asset file."""

    return Path(catalog_path).with_name(RUNTIME_FILENAME)


def _workspace_root(catalog_path: str | Path) -> Path:
    """Infer the workspace paired with the conventional ``work/catalog`` file."""

    catalog = Path(catalog_path).expanduser().resolve()
    return catalog.parent.parent if catalog.parent.name == "catalog" else catalog.parent


def _artifact_relative_path(value: object, workspace: Path) -> str | None:
    """Return a workspace-relative artifact path without touching RAW paths."""

    text = str(value or "").strip()
    if not text:
        return None
    path = Path(text).expanduser()
    try:
        return path.resolve().relative_to(workspace).as_posix()
    except ValueError:
        pass
    for index, part in enumerate(path.parts):
        if part in _ARTIFACT_ROOTS:
            return Path(*path.parts[index:]).as_posix()
    return None


def _store_relative_artifact_paths(value: object, workspace: Path) -> object:
    if isinstance(value, Mapping):
        stored = {str(key): _store_relative_artifact_paths(item, workspace) for key, item in value.items()}
        for key, item in tuple(stored.items()):
            if key not in _ARTIFACT_PATH_KEYS:
                continue
            relative = _artifact_relative_path(item, workspace)
            if relative:
                stored.setdefault(f"{key}_relative", relative)
        return stored
    if isinstance(value, list):
        return [_store_relative_artifact_paths(item, workspace) for item in value]
    return value


def _rebase_artifact_paths(value: object, workspace: Path) -> object:
    """Prefer a present workspace-relative artifact over a stale absolute path."""

    if isinstance(value, Mapping):
        rebased = {str(key): _rebase_artifact_paths(item, workspace) for key, item in value.items()}
        for key in _ARTIFACT_PATH_KEYS:
            absolute = rebased.get(key)
            relative = str(rebased.get(f"{key}_relative") or "").strip()
            if not relative:
                relative = _artifact_relative_path(absolute, workspace) or ""
                if relative:
                    rebased[f"{key}_relative"] = relative
            if relative:
                candidate = workspace / relative
                if candidate.exists():
                    rebased[key] = str(candidate)
        return rebased
    if isinstance(value, list):
        return [_rebase_artifact_paths(item, workspace) for item in value]
    return value


def inspect_catalog_runtime(
    catalog_path: str | Path,
    catalog: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Describe whether the catalog's runtime sidecar is usable.

    The catalog asset and runtime sidecar are intentionally separate, but a
    consumer must be able to tell the difference between a clean empty state,
    a legacy embedded state, and a missing or corrupt sidecar.  This helper is
    read-only and is used by the Web boundary to expose that distinction.
    """

    path = catalog_runtime_path(catalog_path)
    if path.exists():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, TypeError, ValueError):
            return {"status": "INVALID", "source": path.name, "path": str(path), "entry_count": 0}
        sidecar_exists, runtime = _sidecar_runtime(payload)
        if not sidecar_exists:
            return {"status": "INVALID", "source": path.name, "path": str(path), "entry_count": 0}
        return {"status": "AVAILABLE", "source": path.name, "path": str(path), "entry_count": len(runtime)}

    embedded = collect_embedded_runtime(catalog or {})
    if embedded:
        return {"status": "EMBEDDED_FALLBACK", "source": "catalog.json", "path": str(path), "entry_count": len(embedded)}
    return {"status": "MISSING", "source": path.name, "path": str(path), "entry_count": 0}


def _clean_runtime_item(item: Mapping[str, Any]) -> dict[str, Any]:
    cleaned = {str(key): deepcopy(value) for key, value in item.items()}
    scan = cleaned.get("scan")
    if isinstance(scan, Mapping):
        cleaned["scan"] = {str(key): value for key, value in scan.items() if key != "console_html"}
    return cleaned


def _catalog_version_key(lib: Mapping[str, Any], version: Mapping[str, Any]) -> str:
    version_key = str(version.get("version_key") or version.get("version_uid") or "")
    if version_key:
        return version_key
    version_id = str(version.get("version_id") or "")
    typed_library_id = str(
        version.get("typed_library_id")
        or lib.get("typed_library_id")
        or lib.get("library_id")
        or ""
    )
    if typed_library_id and "/" in typed_library_id and version_id:
        return f"{typed_library_id}/{version_id}"
    library_name = str(
        version.get("library_name")
        or version.get("formal_library_id")
        or lib.get("library_name")
        or lib.get("formal_library_id")
        or ""
    )
    if not library_name or not version_id:
        return ""
    library_type = str(version.get("library_type") or lib.get("library_type") or "ip").lower()
    return f"{library_type}/{library_name}/{version_id}"


def collect_embedded_runtime(data: Mapping[str, Any]) -> dict[str, Any]:
    """Collect runtime from the legacy embedded catalog representation."""

    runtime: dict[str, Any] = {}
    embedded = data.get("runtime_state")
    if isinstance(embedded, Mapping):
        runtime.update(
            {
                str(key): _clean_runtime_item(value)
                for key, value in embedded.items()
                if isinstance(value, Mapping)
            }
        )

    for lib in data.get("libraries", []) or []:
        if not isinstance(lib, Mapping):
            continue
        for version in lib.get("versions", []) or []:
            if not isinstance(version, Mapping):
                continue
            version_key = _catalog_version_key(lib, version)
            if not version_key:
                continue
            legacy = {
                key: version.get(key)
                for key in ("scan", "diff", "release")
                if isinstance(version.get(key), Mapping)
            }
            if not legacy:
                continue
            current = dict(runtime.get(version_key, {}) or {})
            for key, value in legacy.items():
                current[key] = dict(value or {}) | dict(current.get(key, {}) or {})
            runtime[version_key] = _clean_runtime_item(current)
    return runtime


def _sidecar_runtime(data: Any) -> tuple[bool, dict[str, Any]]:
    if not isinstance(data, Mapping):
        return False, {}
    if isinstance(data.get("runtime_state"), Mapping):
        return True, {
            str(key): _clean_runtime_item(value)
            for key, value in data["runtime_state"].items()
            if isinstance(value, Mapping)
        }
    runtime = {
        str(key): _clean_runtime_item(value)
        for key, value in data.items()
        if isinstance(value, Mapping) and "/" in str(key)
    }
    return bool(runtime), runtime


def load_catalog_runtime(catalog_path: str | Path, catalog: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Load sidecar runtime, falling back to legacy embedded runtime."""

    sidecar_exists, runtime = _sidecar_runtime(_read_json(catalog_runtime_path(catalog_path), None))
    if sidecar_exists:
        return _rebase_artifact_paths(runtime, _workspace_root(catalog_path))
    source = catalog if isinstance(catalog, Mapping) else _read_json(catalog_path, {}) or {}
    embedded = collect_embedded_runtime(source) if isinstance(source, Mapping) else {}
    return _rebase_artifact_paths(embedded, _workspace_root(catalog_path))


def merge_catalog_runtime(catalog: Mapping[str, Any], runtime_state: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Return a catalog view with runtime fields merged onto each version."""

    view = deepcopy(dict(catalog))
    runtime = runtime_state if isinstance(runtime_state, Mapping) else collect_embedded_runtime(view)
    normalized_runtime = {
        str(key): _clean_runtime_item(value)
        for key, value in runtime.items()
        if isinstance(value, Mapping)
    }
    view["runtime_state"] = normalized_runtime
    libraries: list[Any] = []
    for lib in view.get("libraries", []) or []:
        if not isinstance(lib, Mapping):
            libraries.append(lib)
            continue
        lib_view = dict(lib)
        versions: list[Any] = []
        for version in lib_view.get("versions", []) or []:
            if not isinstance(version, Mapping):
                versions.append(version)
                continue
            version_view = dict(version)
            version_key = _catalog_version_key(lib_view, version_view)
            runtime_item = normalized_runtime.get(version_key, {})
            for key, value in runtime_item.items():
                if key in {"scan", "diff", "release"} and isinstance(value, Mapping):
                    current = version_view.get(key) if isinstance(version_view.get(key), Mapping) else {}
                    version_view[key] = dict(current) | dict(value)
                else:
                    version_view[key] = deepcopy(value)
            versions.append(version_view)
        lib_view["versions"] = versions
        libraries.append(lib_view)
    if "libraries" in view:
        view["libraries"] = libraries
    return view


def load_catalog_view(catalog_path: str | Path) -> dict[str, Any]:
    """Load a catalog asset and overlay sidecar runtime with legacy fallback."""

    catalog = _read_json(catalog_path, {}) or {}
    if not isinstance(catalog, Mapping):
        return {}
    runtime = load_catalog_runtime(catalog_path, catalog)
    return merge_catalog_runtime(catalog, runtime)


def write_catalog_runtime(catalog_path: str | Path, runtime_state: Mapping[str, Any]) -> Path:
    """Atomically replace the catalog runtime sidecar."""

    path = catalog_runtime_path(catalog_path)
    portable_runtime = _store_relative_artifact_paths(runtime_state, _workspace_root(catalog_path))
    payload = {
        "schema_version": RUNTIME_SCHEMA_VERSION,
        "updated_at": _now(),
        "runtime_state": {
            str(key): _clean_runtime_item(value)
            for key, value in portable_runtime.items()
            if isinstance(value, Mapping)
        },
    }
    atomic_write_json(path, payload, lock=True)
    return path
