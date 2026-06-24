from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import json


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _auto_run_id(batch_type: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return f"{batch_type}_{stamp}"


def _write_json(path: Path, payload: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    return path


def make_batch_run_dir(workdir: str | Path, batch_type: str, run_id: str | None = None) -> Path:
    resolved_run_id = run_id or _auto_run_id(batch_type)
    run_dir = Path(workdir) / "batch_runs" / resolved_run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def write_selection_manifest(run_dir: Path, payload: dict[str, Any]) -> Path:
    data = dict(payload)
    data.setdefault("schema_version", "batch_selection.v1")
    data.setdefault("created_at", _utc_now())
    return _write_json(run_dir / "selection_manifest.json", data)


def init_progress(run_dir: Path, total: int, run_id: str) -> Path:
    return _write_json(
        run_dir / "progress.json",
        {
            "schema_version": "batch_progress.v1",
            "run_id": run_id,
            "status": "RUNNING",
            "total": int(total or 0),
            "done": 0,
            "failed": 0,
            "current": None,
            "items": [],
            "updated_at": _utc_now(),
        },
    )


def update_progress(run_dir: Path, item: dict[str, Any]) -> None:
    progress_path = run_dir / "progress.json"
    progress = json.loads(progress_path.read_text(encoding="utf-8")) if progress_path.exists() else {
        "schema_version": "batch_progress.v1",
        "run_id": run_dir.name,
        "status": "RUNNING",
        "total": 0,
        "done": 0,
        "failed": 0,
        "current": None,
        "items": [],
    }
    entry = dict(item)
    progress["items"].append(entry)
    progress["done"] = len(progress["items"])
    progress["failed"] = sum(1 for row in progress["items"] if str(row.get("status") or "").upper() in {"FAILED", "ERROR", "BLOCK", "BLOCKED"} or int(row.get("exit_code", 0) or 0) != 0)
    progress["current"] = {
        "library_name": entry.get("library_name"),
        "version_id": entry.get("version_id"),
        "version_key": entry.get("version_key"),
    }
    progress["status"] = "FAILED" if progress["failed"] else "RUNNING"
    progress["updated_at"] = _utc_now()
    _write_json(progress_path, progress)


def write_result(run_dir: Path, payload: dict[str, Any]) -> Path:
    data = dict(payload)
    data.setdefault("schema_version", "batch_result.v1")
    data.setdefault("run_id", run_dir.name)
    data.setdefault("created_at", _utc_now())
    progress_path = run_dir / "progress.json"
    if progress_path.exists():
        progress = json.loads(progress_path.read_text(encoding="utf-8"))
        progress["status"] = str(data.get("status") or progress.get("status") or "UNKNOWN")
        progress["updated_at"] = _utc_now()
        _write_json(progress_path, progress)
    return _write_json(run_dir / "result.json", data)


def write_failed(run_dir: Path, failures: list[dict[str, Any]]) -> Path:
    return _write_json(
        run_dir / "failed.json",
        {
            "schema_version": "batch_failed.v1",
            "run_id": run_dir.name,
            "failed": failures,
            "created_at": _utc_now(),
        },
    )


def write_rerun_failed_csh(run_dir: Path, failures: list[dict[str, Any]], batch_type: str) -> Path:
    script = run_dir / "rerun_failed.csh"
    lines = [
        "#!/bin/csh",
        "",
        "if (! $?PROJ) then",
        "  setenv PROJ `pwd`",
        "endif",
        "",
    ]
    for item in failures:
        library = item.get("library_name") or item.get("library") or ""
        version = item.get("version_id") or item.get("version") or ""
        if not library or not version:
            continue
        if batch_type == "compare":
            lines.append(f"$PROJ/scripts/lg.csh diff {library} {version} --scan-if-missing")
        else:
            lines.append(f"$PROJ/scripts/lg.csh scan {library} {version}")
    script.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return script
