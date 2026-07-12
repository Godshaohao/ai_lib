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


def _clean_runtime_item(item: Mapping[str, Any]) -> dict[str, Any]:
    cleaned = {str(key): deepcopy(value) for key, value in item.items()}
    scan = cleaned.get("scan")
    if isinstance(scan, Mapping):
        cleaned["scan"] = {str(key): value for key, value in scan.items() if key != "console_html"}
    return cleaned


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
            version_key = str(version.get("version_key") or version.get("version_uid") or "")
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
        return runtime
    source = catalog if isinstance(catalog, Mapping) else _read_json(catalog_path, {}) or {}
    return collect_embedded_runtime(source) if isinstance(source, Mapping) else {}


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
            version_key = str(version_view.get("version_key") or version_view.get("version_uid") or "")
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
    payload = {
        "schema_version": RUNTIME_SCHEMA_VERSION,
        "updated_at": _now(),
        "runtime_state": {
            str(key): _clean_runtime_item(value)
            for key, value in runtime_state.items()
            if isinstance(value, Mapping)
        },
    }
    atomic_write_json(path, payload, lock=True)
    return path
