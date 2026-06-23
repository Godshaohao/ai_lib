from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping
import json


@dataclass(frozen=True)
class LibraryRef:
    library_id: str
    root: Path
    library_type: str | None = None
    display_name: str | None = None
    vendor: str | None = None
    category: str | None = None
    middle_path: str | None = None
    aliases: tuple[str, ...] = field(default_factory=tuple)
    discovery_source: str = "library_map"


@dataclass(frozen=True)
class VersionRef:
    library: LibraryRef
    version_id: str
    path: Path
    discovery_source: str = "library_map"
    structure_rule: str = "library_map:{version}"


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_simple_library_map_yaml(path: Path) -> dict[str, Any]:
    """Read the small library_map.yml schema without requiring PyYAML."""
    data: dict[str, Any] = {"libraries": {}}
    section: str | None = None
    current_id: str | None = None
    current_list: str | None = None
    for raw in path.read_text(encoding="utf-8").splitlines():
        if "#" in raw:
            raw = raw.split("#", 1)[0]
        if not raw.strip():
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        line = raw.strip()
        if indent == 0 and line.endswith(":"):
            section = line[:-1].strip()
            continue
        if section != "libraries":
            continue
        if indent == 2 and line.endswith(":"):
            current_id = line[:-1].strip().strip("\"'")
            data["libraries"].setdefault(current_id, {})
            current_list = None
            continue
        if current_id is None:
            continue
        item = data["libraries"][current_id]
        if indent == 4 and ":" in line:
            key, value = line.split(":", 1)
            key = key.strip()
            value = value.strip().strip("\"'")
            if value == "":
                item[key] = []
                current_list = key
            else:
                item[key] = value
                current_list = None
            continue
        if indent >= 6 and line.startswith("- ") and current_list:
            item.setdefault(current_list, []).append(line[2:].strip().strip("\"'"))
    return data


def _load_mapping_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"libraries": {}}
    if path.suffix.lower() == ".json":
        data = _read_json(path)
    else:
        data = _read_simple_library_map_yaml(path)
    return data if isinstance(data, dict) else {"libraries": {}}


def _resolve_map_path(policy: Mapping[str, Any], policy_path: str | Path | None) -> Path | None:
    discovery = policy.get("discovery") if isinstance(policy.get("discovery"), Mapping) else {}
    raw_value = discovery.get("library_map") or policy.get("library_map")
    if not raw_value:
        return None
    path = Path(str(raw_value))
    if path.is_absolute():
        return path
    if policy_path:
        return Path(policy_path).resolve().parent / path
    return path


def _resolve_library_root(raw_root: Path, map_path: Path, value: str) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    normalized = value.replace("\\", "/")
    if normalized == raw_root.name or normalized.startswith(f"{raw_root.name}/"):
        return raw_root.parent / path
    return raw_root / path


def load_library_map(raw_root: str | Path, policy: Mapping[str, Any], policy_path: str | Path | None = None) -> list[LibraryRef]:
    raw = Path(raw_root).resolve()
    map_path = _resolve_map_path(policy, policy_path)
    if not map_path:
        return []
    map_path = map_path.resolve()
    data = _load_mapping_file(map_path)
    libraries = data.get("libraries") if isinstance(data.get("libraries"), Mapping) else {}
    refs: list[LibraryRef] = []
    for library_id, item in libraries.items():
        if not isinstance(item, Mapping):
            continue
        enabled = str(item.get("enabled", "true")).strip().lower()
        if enabled in {"false", "0", "no", "off", "disabled"}:
            continue
        root_value = item.get("root_abs") or item.get("root")
        if not root_value:
            continue
        if item.get("root_abs"):
            root = Path(str(item.get("root_abs"))).expanduser().resolve()
        else:
            root = _resolve_library_root(raw, map_path, str(root_value)).resolve()
        if not root.exists() or not root.is_dir():
            continue
        aliases = item.get("aliases") or []
        if isinstance(aliases, str):
            aliases = [aliases]
        refs.append(
            LibraryRef(
                library_id=str(library_id),
                root=root,
                library_type=str(item.get("library_type")) if item.get("library_type") else None,
                display_name=str(item.get("display_name")) if item.get("display_name") else None,
                vendor=str(item.get("vendor")) if item.get("vendor") else None,
                category=str(item.get("category")) if item.get("category") else None,
                middle_path=str(item.get("middle_path")) if item.get("middle_path") else None,
                aliases=tuple(str(a) for a in aliases if str(a)),
            )
        )
    return refs


def discover_versions(library: LibraryRef, ignore_dirs: set[str] | None = None) -> list[VersionRef]:
    ignore = ignore_dirs or set()
    versions: list[VersionRef] = []
    for item in sorted(library.root.iterdir(), key=lambda p: p.name.lower()):
        if not item.is_dir() or item.name.lower() in ignore:
            continue
        versions.append(VersionRef(library=library, version_id=item.name, path=item))
    return versions


def resolve_library_id(catalog: Mapping[str, Any], name_or_alias: str) -> str | None:
    for item in catalog.get("libraries", []) or []:
        names = {
            str(item.get("library_id") or ""),
            str(item.get("library_name") or ""),
            *(str(a) for a in item.get("aliases", []) or []),
        }
        if name_or_alias in names:
            return str(item.get("library_id") or "")
    return None
