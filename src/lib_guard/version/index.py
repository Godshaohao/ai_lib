from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import json

from lib_guard.atomic import atomic_write_json

def _utc_now() -> str:
    return datetime.now(tz=timezone.utc).isoformat().replace("+00:00", "Z")


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _atomic_write_json(path: Path, data: Any) -> None:
    atomic_write_json(path, data, lock=True)


@dataclass
class VersionIndex:
    workdir: str | Path = "work"

    @property
    def path(self) -> Path:
        return Path(self.workdir) / "index" / "version_history" / "index.json"

    def load(self) -> dict[str, Any]:
        data = _read_json(self.path, None)
        if not data:
            return {"schema_version": "1.0", "updated_at": _utc_now(), "libraries": {}}
        data.setdefault("schema_version", "1.0")
        data.setdefault("libraries", {})
        return data

    def save(self, data: dict[str, Any]) -> None:
        data["updated_at"] = _utc_now()
        _atomic_write_json(self.path, data)

    def register(
        self,
        *,
        library_id: str,
        version_id: str,
        version_type: str,
        release_line: str | None,
        scan_dir: str | Path | None = None,
        raw_root: str | Path | None = None,
        parent_version: str | None = None,
        base_version: str | None = None,
        release_status: str | None = None,
        scan_status: str | None = None,
        bundle_status: str | None = None,
        release_channel: str | None = None,
        scan_id: str | None = None,
        overwrite: bool = False,
    ) -> dict[str, Any]:
        if not scan_dir and not raw_root:
            raise ValueError("version register requires at least one of scan_dir or raw_root")
        if version_type not in {"full", "hotfix", "candidate", "daily", "milestone"}:
            raise ValueError(f"invalid version_type={version_type}")
        data = self.load()
        libraries = data.setdefault("libraries", {})
        lib = libraries.setdefault(library_id, {"library_id": library_id, "versions": {}})
        versions = lib.setdefault("versions", {})
        if version_id in versions and not overwrite:
            raise ValueError(f"version_id={version_id} already exists; use overwrite=True")
        if version_type == "hotfix":
            if not parent_version:
                raise ValueError("hotfix version requires parent_version")
            if not base_version:
                raise ValueError("hotfix version requires base_version")
        if parent_version and parent_version not in versions and parent_version != version_id:
            raise ValueError(f"parent_version={parent_version} does not exist")
        if base_version and base_version not in versions and base_version != version_id:
            raise ValueError(f"base_version={base_version} does not exist")
        if parent_version and release_line:
            parent = versions.get(parent_version, {})
            if parent.get("release_line") and parent.get("release_line") != release_line:
                raise ValueError("release_line does not match parent_version")
        if base_version and release_line:
            base = versions.get(base_version, {})
            if base.get("release_line") and base.get("release_line") != release_line:
                raise ValueError("release_line does not match base_version")
        record = {
            "version_id": version_id,
            "version_type": version_type,
            "release_line": release_line,
            "parent_version": parent_version,
            "base_version": base_version,
            "raw_root": str(raw_root) if raw_root is not None else versions.get(version_id, {}).get("raw_root"),
            "scan_dir": str(scan_dir) if scan_dir is not None else None,
            "scan_id": scan_id,
            "scan_status": scan_status,
            "release_status": release_status,
            "release_channel": release_channel,
            "bundle_status": bundle_status,
            "latest_scan_by_mode": versions.get(version_id, {}).get("latest_scan_by_mode", {}),
            "all_scans": versions.get(version_id, {}).get("all_scans", []),
            "created_at": versions.get(version_id, {}).get("created_at") or _utc_now(),
            "updated_at": _utc_now(),
        }
        if scan_dir is not None:
            mode = "unknown"
            record["latest_scan_by_mode"][mode] = str(scan_dir)
            record["all_scans"].append({"scan_dir": str(scan_dir), "scan_id": scan_id, "scan_status": scan_status, "mode": mode, "created_at": _utc_now()})
        versions[version_id] = record
        lib["latest_version"] = version_id
        self.save(data)
        return record

    def get(self, library_id: str, version_id: str) -> dict[str, Any]:
        data = self.load()
        record = data.get("libraries", {}).get(library_id, {}).get("versions", {}).get(version_id)
        if not record:
            raise FileNotFoundError(f"No version record found for library_id={library_id}, version_id={version_id}")
        return record

    def list_versions(self, library_id: str | None = None) -> list[dict[str, Any]]:
        data = self.load()
        rows: list[dict[str, Any]] = []
        for lid, lib in data.get("libraries", {}).items():
            if library_id and lid != library_id:
                continue
            for item in lib.get("versions", {}).values():
                row = dict(item)
                row["library_id"] = lid
                rows.append(row)
        return sorted(rows, key=lambda item: (item.get("library_id") or "", item.get("created_at") or "", item.get("version_id") or ""))


def _library_id_without_version(scan_meta: dict[str, Any]) -> str:
    library_type = str(scan_meta.get("library_type") or "unknown")
    library_name = str(scan_meta.get("library_name") or "unknown")
    return str(scan_meta.get("bundle_id") or scan_meta.get("library_family_id") or f"{library_type}/{library_name}")


def register_scan_version(
    scan_dir: str | Path | None,
    *,
    workdir: str | Path = "work",
    library_id: str | None = None,
    version_id: str | None = None,
    version_type: str = "full",
    release_line: str | None = None,
    parent_version: str | None = None,
    base_version: str | None = None,
    raw_root: str | Path | None = None,
    overwrite: bool = False,
) -> dict[str, Any]:
    scan = Path(scan_dir) if scan_dir is not None else None
    meta = _read_json(scan / "scan_meta.json", {}) if scan is not None else {}
    readiness = _read_json(scan / "summary" / "release_readiness.json", {}) if scan is not None else {}
    resolved_library_id = library_id or _library_id_without_version(meta)
    resolved_version_id = version_id or str(meta.get("release_version") or meta.get("version") or "unknown")
    return VersionIndex(workdir).register(
        library_id=resolved_library_id,
        version_id=resolved_version_id,
        version_type=version_type,
        release_line=release_line,
        parent_version=parent_version,
        base_version=base_version,
        scan_dir=scan,
        raw_root=raw_root,
        release_status=readiness.get("release_status"),
        scan_status=meta.get("status"),
        bundle_status=readiness.get("bundle_status"),
        release_channel=readiness.get("release_channel"),
        scan_id=meta.get("scan_id"),
        overwrite=overwrite,
    )


def _require_scan(record: dict[str, Any], version_id: str) -> str:
    scan_dir = record.get("scan_dir")
    if scan_dir:
        return str(scan_dir)
    raw_root = record.get("raw_root")
    if raw_root:
        raise ValueError(
            f"version {version_id} has raw_root={raw_root} but no scan_dir. "
            f"Run lib_guard scan --root {raw_root} and then version register --scan <scan_out> --version-id {version_id} --overwrite."
        )
    raise ValueError(f"version {version_id} has no scan_dir")


def resolve_adjacent_pair(library_id: str, new_version: str, *, workdir: str | Path = "work") -> dict[str, Any]:
    index = VersionIndex(workdir)
    new = index.get(library_id, new_version)
    parent_version = new.get("parent_version")
    if not parent_version:
        raise ValueError(f"version_id={new_version} has no parent_version")
    old = index.get(library_id, parent_version)
    return {
        "old_scan": _require_scan(old, parent_version),
        "new_scan": _require_scan(new, new_version),
        "version_relation": {
            "diff_mode": "adjacent",
            "old_version": old.get("version_id"),
            "new_version": new.get("version_id"),
            "old_version_type": old.get("version_type"),
            "new_version_type": new.get("version_type"),
            "release_line": new.get("release_line") or old.get("release_line"),
            "parent_version": parent_version,
            "base_version": new.get("base_version"),
        },
    }


def resolve_cumulative_pair(library_id: str, new_version: str, *, workdir: str | Path = "work") -> dict[str, Any]:
    index = VersionIndex(workdir)
    new = index.get(library_id, new_version)
    base_version = new.get("base_version") or new.get("parent_version")
    if not base_version:
        raise ValueError(f"version_id={new_version} has no base_version or parent_version")
    old = index.get(library_id, base_version)
    return {
        "old_scan": _require_scan(old, base_version),
        "new_scan": _require_scan(new, new_version),
        "version_relation": {
            "diff_mode": "cumulative",
            "old_version": old.get("version_id"),
            "new_version": new.get("version_id"),
            "old_version_type": old.get("version_type"),
            "new_version_type": new.get("version_type"),
            "release_line": new.get("release_line") or old.get("release_line"),
            "parent_version": new.get("parent_version"),
            "base_version": base_version,
        },
    }
