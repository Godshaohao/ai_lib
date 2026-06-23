"""
Safe update commands for lib_guard v4.

This first version does not attempt complex in-place summary merging. It resolves
latest scan, determines affected summary types, writes an update record, and can
trigger summary rebuild for affected types.
"""

from __future__ import annotations

from pathlib import Path
from datetime import datetime, timezone
from typing import Any
import json
import os
import tempfile

from lib_guard.history.index import HistoryIndex, resolve_scan_dir
from lib_guard.summary.builder import affected_summary_types, rebuild_summary_from_scan


def utc_now() -> str:
    return datetime.now(tz=timezone.utc).isoformat().replace("+00:00", "Z")


def atomic_write_json(path: str | Path, data: Any) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=p.name, suffix=".tmp", dir=str(p.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.replace(tmp_name, p)
    finally:
        try:
            if os.path.exists(tmp_name):
                os.remove(tmp_name)
        except OSError:
            pass


def infer_file_type(path: str | Path) -> str:
    name = Path(path).name.lower()
    if name.endswith((".lef", ".lef.gz", ".tlef", ".tlef.gz")):
        return "lef"
    if name.endswith((".lib", ".lib.gz")):
        return "liberty"
    if name.endswith((".v", ".sv", ".vg", ".vp", ".vh", ".svh")):
        return "verilog"
    if name.endswith((".cdl", ".sp", ".spi", ".spice")):
        return "cdl"
    if name.endswith(".sdc"):
        return "sdc"
    if name.endswith(".upf"):
        return "upf"
    if name.endswith(".cpf"):
        return "cpf"
    if name.endswith((".spef", ".spef.gz")):
        return "spef"
    if "readme" in name or "release" in name or name.endswith((".md", ".txt", ".pdf", ".doc", ".docx")):
        return "doc"
    return "unknown"


def _update_run_dir(workdir: str | Path, library_id: str, run_name: str) -> Path:
    parts = library_id.split("/")
    while len(parts) < 3:
        parts.append("unknown")
    return Path(workdir) / "scan_out" / parts[0] / parts[1] / parts[2] / "runs" / run_name


def update_type(
    *,
    library_id: str,
    file_type: str,
    scope: str = "summary",
    mode: str = "signature",
    workdir: str | Path = "work",
    policy_path: str | Path | None = None,
    skip_cache: bool = False,
    rebuild_summary: bool = True,
) -> dict[str, Any]:
    scan_dir = resolve_scan_dir(latest=True, library_id=library_id, mode=mode, workdir=workdir)
    affected = affected_summary_types(file_type, policy_path=policy_path)
    run_id = f"update_type_{file_type}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    out_dir = _update_run_dir(workdir, library_id, run_id)
    out_dir.mkdir(parents=True, exist_ok=True)

    summary_result = None
    if rebuild_summary and scope in {"summary", "parser-summary", "all"}:
        summary_result = rebuild_summary_from_scan(scan_dir, types=affected, all_summaries=False, policy_path=policy_path)

    result = {
        "schema_version": "1.0",
        "status": "PASS",
        "generated_at": utc_now(),
        "kind": "update_type",
        "library_id": library_id,
        "source_scan": str(scan_dir),
        "file_type": file_type,
        "scope": scope,
        "skip_cache": skip_cache,
        "affected_summaries": affected,
        "summary_result": summary_result,
        "note": "v4 safe update: summary rebuild is supported. Parser-only type update should be handled by scan --skip-cache / future --only-type integration.",
    }
    atomic_write_json(out_dir / "update_type.json", result)
    HistoryIndex(workdir).register_run(
        library_id=library_id,
        kind="update",
        mode=mode,
        scan_id=datetime.now().strftime("%Y%m%d_%H%M%S"),
        out_dir=out_dir,
        status=result["status"],
        source_scan=str(scan_dir),
        update_latest=True,
        summary={"file_type": file_type, "scope": scope, "affected_summaries": affected},
    )
    return result


def update_file(
    *,
    library_id: str,
    file: str | Path,
    scope: str = "summary",
    mode: str = "signature",
    workdir: str | Path = "work",
    policy_path: str | Path | None = None,
    rebuild_summary: bool = True,
) -> dict[str, Any]:
    file = Path(file)
    file_type = infer_file_type(file)
    scan_dir = resolve_scan_dir(latest=True, library_id=library_id, mode=mode, workdir=workdir)
    affected = affected_summary_types(file_type, policy_path=policy_path)
    run_id = f"update_file_{file_type}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    out_dir = _update_run_dir(workdir, library_id, run_id)
    out_dir.mkdir(parents=True, exist_ok=True)

    summary_result = None
    if rebuild_summary and scope in {"summary", "parser-summary", "all"}:
        summary_result = rebuild_summary_from_scan(scan_dir, types=affected, all_summaries=False, policy_path=policy_path)

    stat = None
    if file.exists():
        st = file.stat()
        stat = {"size_bytes": st.st_size, "mtime": st.st_mtime}

    result = {
        "schema_version": "1.0",
        "status": "PASS" if file.exists() else "WARNING",
        "generated_at": utc_now(),
        "kind": "update_file",
        "library_id": library_id,
        "source_scan": str(scan_dir),
        "file": str(file),
        "file_exists": file.exists(),
        "file_type": file_type,
        "file_stat": stat,
        "scope": scope,
        "affected_summaries": affected,
        "summary_result": summary_result,
        "note": "v4 safe update: this records file-level update intent and rebuilds affected summaries from latest scan. Full parser-cache update will require parser result persistence or scan --only-file integration.",
    }
    atomic_write_json(out_dir / "update_file.json", result)
    HistoryIndex(workdir).register_run(
        library_id=library_id,
        kind="update",
        mode=mode,
        scan_id=datetime.now().strftime("%Y%m%d_%H%M%S"),
        out_dir=out_dir,
        status=result["status"],
        source_scan=str(scan_dir),
        update_latest=True,
        summary={"file": str(file), "file_type": file_type, "scope": scope, "affected_summaries": affected},
    )
    return result
