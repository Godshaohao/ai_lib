"""
lib_guard.history.index

Maintains work/index/scan_history/index.json.

Purpose:
- Keep every scan/summary/update/release run traceable.
- Maintain latest pointers per library_id and mode.
- Provide a stable entry point for summary/render/release commands.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path
from datetime import datetime, timezone
from typing import Any, Mapping
import json
import os
import tempfile


def utc_now() -> str:
    return datetime.now(tz=timezone.utc).isoformat().replace("+00:00", "Z")


def plain(obj: Any) -> Any:
    if isinstance(obj, Path):
        return str(obj)
    if isinstance(obj, Mapping):
        return {str(k): plain(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [plain(v) for v in obj]
    if hasattr(obj, "to_dict"):
        return plain(obj.to_dict())
    if hasattr(obj, "__dict__"):
        return {k: plain(v) for k, v in obj.__dict__.items() if not k.startswith("_")}
    return obj


def read_json(path: str | Path, default: Any = None) -> Any:
    p = Path(path)
    if not p.exists():
        return default
    with p.open("r", encoding="utf-8") as f:
        return json.load(f)


def atomic_write_json(path: str | Path, data: Any) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=p.name, suffix=".tmp", dir=str(p.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(plain(data), f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.replace(tmp_name, p)
    finally:
        try:
            if os.path.exists(tmp_name):
                os.remove(tmp_name)
        except OSError:
            pass


def library_id_from_parts(library_type: str | None, library_name: str | None, version: str | None) -> str:
    return "/".join([str(library_type or "unknown"), str(library_name or "unknown"), str(version or "unknown")])


@dataclass
class RunRecord:
    run_id: str
    kind: str
    mode: str | None
    status: str
    out_dir: str
    scan_id: str | None = None
    source_scan: str | None = None
    created_at: str = ""
    summary: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        if not data["created_at"]:
            data["created_at"] = utc_now()
        return data


class HistoryIndex:
    def __init__(self, workdir: str | Path = "work") -> None:
        self.workdir = Path(workdir)
        self.index_path = self.workdir / "index" / "scan_history" / "index.json"

    def load(self) -> dict[str, Any]:
        data = read_json(self.index_path, default=None)
        if not data:
            return {"schema_version": "1.0", "updated_at": utc_now(), "libraries": {}}
        data.setdefault("schema_version", "1.0")
        data.setdefault("libraries", {})
        return data

    def save(self, data: dict[str, Any]) -> None:
        data["updated_at"] = utc_now()
        atomic_write_json(self.index_path, data)

    def register_run(
        self,
        *,
        library_id: str,
        library_type: str | None = None,
        library_name: str | None = None,
        version: str | None = None,
        root_path: str | None = None,
        kind: str,
        mode: str | None,
        scan_id: str | None,
        out_dir: str | Path,
        status: str,
        source_scan: str | None = None,
        update_latest: bool = True,
        summary: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        data = self.load()
        libraries = data.setdefault("libraries", {})
        lib = libraries.setdefault(library_id, {})
        lib.setdefault("library_id", library_id)
        if library_type is not None:
            lib["library_type"] = library_type
        if library_name is not None:
            lib["library_name"] = library_name
        if version is not None:
            lib["version"] = version
        if root_path is not None:
            lib["root_path"] = root_path
        lib.setdefault("latest", {})
        lib.setdefault("runs", [])

        sid = str(scan_id or utc_now().replace(":", "").replace("-", "").replace("T", "_").replace("Z", ""))
        run_id = f"{kind if kind != 'scan' else (mode or 'scan')}_{sid}"
        record = RunRecord(
            run_id=run_id,
            kind=kind,
            mode=mode,
            status=status,
            out_dir=str(out_dir),
            scan_id=scan_id,
            source_scan=source_scan,
            created_at=utc_now(),
            summary=summary or {},
        ).to_dict()
        lib["runs"].append(record)

        if update_latest:
            if kind == "scan" and mode:
                lib["latest"][mode] = str(out_dir)
            elif kind == "summary":
                lib["latest"]["summary"] = str(out_dir)
                if mode:
                    lib["latest"][f"summary:{mode}"] = str(out_dir)
            elif kind == "update":
                lib["latest"]["update"] = str(out_dir)
            elif kind == "release":
                lib["latest"]["release"] = str(out_dir)

        self.save(data)
        return record

    def latest(self, library_id: str, mode: str | None = None, kind: str | None = None) -> str | None:
        data = self.load()
        lib = data.get("libraries", {}).get(library_id, {})
        latest = lib.get("latest", {})
        if mode and mode in latest:
            return latest[mode]
        if kind and kind in latest:
            return latest[kind]
        if mode and f"summary:{mode}" in latest:
            return latest[f"summary:{mode}"]
        return None

    def list_runs(self, library_id: str | None = None) -> list[dict[str, Any]]:
        data = self.load()
        out: list[dict[str, Any]] = []
        libraries = data.get("libraries", {})
        if library_id:
            lib = libraries.get(library_id, {})
            for run in lib.get("runs", []):
                item = dict(run)
                item["library_id"] = library_id
                out.append(item)
            return out
        for lid, lib in libraries.items():
            for run in lib.get("runs", []):
                item = dict(run)
                item["library_id"] = lid
                out.append(item)
        return out


def resolve_scan_dir(
    *,
    scan: str | Path | None = None,
    latest: bool = False,
    library_id: str | None = None,
    mode: str | None = None,
    workdir: str | Path = "work",
) -> Path:
    if scan:
        return Path(scan)
    if latest:
        if not library_id:
            raise ValueError("--library-id is required when using --latest")
        if not mode:
            raise ValueError("--mode is required when using --latest")
        found = HistoryIndex(workdir).latest(library_id=library_id, mode=mode)
        if not found:
            raise FileNotFoundError(f"No latest scan found for library_id={library_id}, mode={mode}")
        return Path(found)
    raise ValueError("Either --scan or --latest must be provided")


def register_scan_run(scan_dir: str | Path, workdir: str | Path = "work", update_latest: bool = True) -> dict[str, Any]:
    scan_dir = Path(scan_dir)
    meta = read_json(scan_dir / "scan_meta.json", default={}) or {}
    library_id = meta.get("library_id") or library_id_from_parts(meta.get("library_type"), meta.get("library_name"), meta.get("release_version"))
    return HistoryIndex(workdir).register_run(
        library_id=library_id,
        library_type=meta.get("library_type"),
        library_name=meta.get("library_name"),
        version=meta.get("release_version"),
        root_path=meta.get("root_path"),
        kind="scan",
        mode=meta.get("scan_mode"),
        scan_id=meta.get("scan_id"),
        out_dir=str(scan_dir),
        status=meta.get("status", "UNKNOWN"),
        update_latest=update_latest,
        summary=meta.get("stats", {}),
    )
