from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping
from datetime import datetime, timezone
import json


def _read_json(path: str | Path, default: Any = None) -> Any:
    p = Path(path)
    if not p.exists():
        return default
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return default


def _write_json(path: str | Path, data: Any) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")


def _utc_now() -> str:
    return datetime.now(tz=timezone.utc).isoformat().replace("+00:00", "Z")


def _library_match(lib: Mapping[str, Any], library: str | None) -> bool:
    if not library:
        return True
    names = {str(lib.get("library_id") or ""), str(lib.get("library_name") or ""), str(lib.get("display_name") or "")}
    names.update(str(a) for a in lib.get("aliases", []) or [] if a)
    return library in names


def _file_diff_recommendation_from_diff(diff_dir: Any) -> dict[str, int | str]:
    if not diff_dir:
        return {"comparison_quality": "COMPARE_PENDING", "recommended_total": 0, "result_generated": 0, "needs_run": 0, "candidate_total": 0, "suppressed_total": 0}
    path = Path(str(diff_dir))
    review = _read_json(path / "comparison_review.json", None)
    if isinstance(review, dict) and isinstance(review.get("file_diff_recommendation"), dict):
        rec = review["file_diff_recommendation"]
        return {
            "comparison_quality": rec.get("comparison_quality") or "NORMAL",
            "recommended_total": int(rec.get("recommended_total", 0) or 0),
            "result_generated": int(rec.get("result_generated", 0) or 0),
            "needs_run": int(rec.get("needs_run", 0) or 0),
            "candidate_total": int(rec.get("candidate_total", 0) or 0),
            "suppressed_total": int(rec.get("suppressed_total", 0) or 0),
        }
    tasks = _read_json(path / "manual_pairwise_tasks.json", None) or _read_json(path / "pairwise_diff_tasks.json", {"tasks": []}) or {"tasks": []}
    raw_tasks = list(tasks.get("tasks", []) or [])
    recommended = len(raw_tasks)
    generated = 0
    for item in raw_tasks:
        expected = item.get("expected_output") or item.get("out") or item.get("out_dir")
        if expected and (Path(str(expected)) / "pairwise_result.json").exists():
            generated += 1
    return {
        "comparison_quality": "NORMAL",
        "recommended_total": recommended,
        "result_generated": generated,
        "needs_run": max(recommended - generated, 0),
        "candidate_total": recommended,
        "suppressed_total": 0,
    }


def build_diff_index_from_catalog(catalog: str | Path | Mapping[str, Any], library: str | None = None) -> dict[str, Any]:
    data = _read_json(catalog, {}) if not isinstance(catalog, Mapping) else dict(catalog)
    selected = [lib for lib in data.get("libraries", []) or [] if _library_match(lib, library)]
    if not selected:
        return {"schema_version": "diff_index.v1", "generated_at": _utc_now(), "library_id": library or "", "versions": [], "comparisons": []}
    # For a single library render, use the first matched library. Multi-library consumers can call per library.
    lib = selected[0]
    versions = []
    comparisons = []
    for ver in lib.get("versions", []) or []:
        versions.append({
            "version_id": ver.get("version_id"),
            "stage": ver.get("stage"),
            "scan_status": (ver.get("scan") or {}).get("status") or "NOT_SCANNED",
            "release_status": (ver.get("release") or {}).get("status") or (ver.get("release") or {}).get("check_status") or "UNKNOWN",
        })
        diff = ver.get("diff", {}) or {}
        for mode, old_key, dir_key, html_key, status_key in [
            ("adjacent", "adjacent_old_version", "adjacent_diff_dir", "adjacent_html", "adjacent_status"),
            ("cumulative", "cumulative_base_version", "cumulative_diff_dir", "cumulative_html", "cumulative_status"),
        ]:
            old = diff.get(old_key)
            if not old:
                continue
            diff_dir = diff.get(dir_key)
            rec = _file_diff_recommendation_from_diff(diff_dir)
            status = diff.get(status_key) or "COMPARE_PENDING"
            comparisons.append({
                "comparison_id": f"{mode}__{old}__{ver.get('version_id')}",
                "library_id": lib.get("library_id") or lib.get("library_name"),
                "mode": mode,
                "old_version": old,
                "new_version": ver.get("version_id"),
                "status": status,
                "diff_dir": diff_dir,
                "diff_html": diff.get(html_key) or diff.get("diff_html"),
                "comparison_quality": rec.get("comparison_quality"),
                "recommended_total": rec.get("recommended_total"),
                "result_generated": rec.get("result_generated"),
                "needs_run": rec.get("needs_run"),
                "candidate_total": rec.get("candidate_total"),
                "suppressed_total": rec.get("suppressed_total"),
                "release_impact": "RELEASE_CHECK_REQUIRED",
            })
    return {
        "schema_version": "diff_index.v1",
        "generated_at": _utc_now(),
        "library_id": lib.get("library_id") or lib.get("library_name"),
        "display_name": lib.get("display_name") or lib.get("library_name"),
        "vendor": lib.get("vendor"),
        "middle_path": lib.get("middle_path"),
        "versions": versions,
        "comparisons": comparisons,
    }


def write_diff_index_from_catalog(catalog: str | Path | Mapping[str, Any], out_path: str | Path, library: str | None = None) -> dict[str, Any]:
    data = build_diff_index_from_catalog(catalog, library=library)
    _write_json(out_path, data)
    return {"status": "PASS", "out": str(out_path), "library_id": data.get("library_id"), "comparison_count": len(data.get("comparisons", []) or [])}
