from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping
import json
from datetime import datetime, timezone

from lib_guard.catalog.runtime import load_catalog_view


def _now() -> str:
    return datetime.now(tz=timezone.utc).isoformat().replace("+00:00", "Z")


def _write_json(path: str | Path, data: Mapping[str, Any]) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _match_version(version: Mapping[str, Any], key: str) -> bool:
    return key in {str(version.get("version_key")), str(version.get("version_id"))}


def attach_base(
    catalog_path: str | Path,
    *,
    package_key: str,
    base_version: str,
    updated_by: str = "package.attach",
) -> dict[str, Any]:
    data = load_catalog_view(catalog_path)
    found: dict[str, Any] | None = None
    for lib in data.get("libraries", []) or []:
        for version in lib.get("versions", []) or []:
            if _match_version(version, package_key):
                found = version
                break
        if found:
            break
    if found is None:
        raise FileNotFoundError(f"package not found in catalog: {package_key}")

    found["base_version"] = base_version
    found["standalone"] = False
    found["base_required"] = True
    found["manual_review"] = False
    found.setdefault("lineage", {})["base_candidate"] = base_version
    found.setdefault("lineage", {})["source"] = "manual"
    found["updated_by"] = updated_by
    found["updated_at"] = _now()

    overrides = data.setdefault("manual_overrides", {})
    override = dict(overrides.get(str(found.get("version_key") or package_key), {}) or {})
    override.update(
        {
            "base_version": base_version,
            "standalone": False,
            "base_required": True,
            "manual_review": False,
            "updated_by": updated_by,
            "updated_at": found["updated_at"],
        }
    )
    overrides[str(found.get("version_key") or package_key)] = override
    _write_json(catalog_path, data)
    return {"status": "PASS", "catalog_path": str(catalog_path), "package": found, "base_version": base_version}
