from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from .commands import derive_next_action
from .io import read_json, utc_now


def _versions(lib: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    return list(lib.get("versions", []) or [])


def _status_scan(version: Mapping[str, Any]) -> str:
    scan = version.get("scan", {}) or {}
    raw = str(scan.get("status") or "").upper()
    if not scan.get("scan_dir") and not scan.get("scan_html"):
        return "NOT_SCANNED"
    if raw in {"PASS", "SCANNED", "DONE"}:
        return "SCAN_PASS"
    if raw in {"PASS_WITH_WARNING", "WARNING", "WARN"}:
        return "SCAN_WARN"
    if raw in {"BLOCK", "BLOCKED"}:
        return "SCAN_BLOCK"
    if raw in {"FAILED", "ERROR"}:
        return "SCAN_FAILED"
    return "SCAN_PASS" if scan.get("scan_dir") or scan.get("scan_html") else "NOT_SCANNED"


def _diff_dir(version: Mapping[str, Any]) -> str:
    diff = version.get("diff", {}) or {}
    return str(diff.get("base_diff_dir") or diff.get("adjacent_diff_dir") or diff.get("cumulative_diff_dir") or diff.get("diff_dir") or "")


def _diff_html(version: Mapping[str, Any]) -> str:
    diff = version.get("diff", {}) or {}
    return str(diff.get("base_diff_html") or diff.get("adjacent_diff_html") or diff.get("cumulative_diff_html") or diff.get("diff_html") or "")


def _status_diff(version: Mapping[str, Any], scan_status: str) -> str:
    diff = version.get("diff", {}) or {}
    raw_values = [
        str(diff.get("base_status") or "").upper(),
        str(diff.get("adjacent_status") or "").upper(),
        str(diff.get("cumulative_status") or "").upper(),
        str(diff.get("status") or "").upper(),
    ]
    ignored = {"PENDING", "DIFF_PENDING", "NOT_APPLICABLE", "N/A", "NA"}
    raw = next((value for value in raw_values if value and value not in ignored), "")
    if raw in {"SAME", "DIFF_SAME"}:
        return "DIFF_SAME"
    if raw in {"DIFF", "DIFF_DONE", "PASS_WITH_WARNING"}:
        return "DIFF_REVIEW"
    if raw in {"BLOCK", "BLOCKED"}:
        return "DIFF_BLOCK"
    if raw in {"FAILED", "ERROR"}:
        return "DIFF_FAILED"
    if scan_status == "NOT_SCANNED":
        return "DIFF_NOT_READY"
    return "DIFF_PENDING"


def _pairwise_results_for_task(task: Mapping[str, Any]) -> Mapping[str, Any] | None:
    expected = task.get("expected_output")
    if not expected:
        return None
    out = Path(str(expected))
    result = read_json(out / "pairwise_result.json", None)
    if result:
        return result
    if (out / "file_diff_summary.json").exists():
        summary = read_json(out / "file_diff_summary.json", {}) or {}
        return {"status": "DONE", "result": summary.get("status"), "change_count": 1 if summary.get("changed") else 0, "html": str(out / "index.html")}
    return None


def _pairwise(version: Mapping[str, Any]) -> tuple[str, list[dict[str, Any]], dict[str, int]]:
    diff_dir = _diff_dir(version)
    if not diff_dir:
        return "PAIRWISE_EMPTY", [], {"total": 0, "done": 0, "pending": 0, "failed": 0}
    payload = read_json(Path(diff_dir) / "manual_pairwise_tasks.json", None) or read_json(Path(diff_dir) / "pairwise_diff_tasks.json", {"tasks": []}) or {"tasks": []}
    tasks = []
    done = failed = pending = 0
    for task in payload.get("tasks", []) or []:
        item = dict(task)
        result = _pairwise_results_for_task(item)
        if result:
            item["status"] = str(result.get("status") or "DONE")
            item["result"] = result
            if item["status"] == "FAILED":
                failed += 1
            else:
                done += 1
        else:
            item["status"] = item.get("status") or "PENDING"
            pending += 1
        tasks.append(item)
    total = len(tasks)
    if not total:
        return "PAIRWISE_EMPTY", tasks, {"total": 0, "done": 0, "pending": 0, "failed": 0}
    if failed:
        status = "PAIRWISE_FAILED"
    elif done == total:
        status = "PAIRWISE_DONE"
    elif done:
        status = "PAIRWISE_PARTIAL"
    else:
        status = "PAIRWISE_PENDING"
    return status, tasks, {"total": total, "done": done, "pending": pending, "failed": failed}


def _release_result(version: Mapping[str, Any]) -> Mapping[str, Any]:
    release = version.get("release", {}) or {}
    for key in ["release_result", "postcheck_json", "link_json", "manifest_json", "check_json"]:
        value = release.get(key)
        if not value:
            continue
        path = Path(str(value))
        candidate = path if path.name == "release_result.json" else path.parent / "release_result.json"
        result = read_json(candidate, None)
        if result:
            return result
    return {}


def _has_release_evidence(version: Mapping[str, Any]) -> bool:
    release = version.get("release", {}) or {}
    release_status = str(version.get("release_status") or "").upper()
    if version.get("release_candidate") or version.get("selected_for_release"):
        return True
    if release_status and release_status not in {"UNKNOWN", "RELEASE_NOT_CHECKED", "RELEASE_NOT_APPLICABLE", "NOT_APPLICABLE", "NONE"}:
        return True
    for key in [
        "status",
        "check_status",
        "link_status",
        "release_html",
        "release_dir",
        "manifest_json",
        "postcheck_json",
        "release_result",
        "link_json",
        "check_json",
    ]:
        value = release.get(key)
        if value not in (None, "", "UNKNOWN", "RELEASE_NOT_CHECKED", "RELEASE_NOT_APPLICABLE", "NOT_APPLICABLE", "NONE"):
            return True
    return bool(_release_result(version))


def _status_release(version: Mapping[str, Any]) -> str:
    if not _has_release_evidence(version):
        return "RELEASE_NOT_APPLICABLE"
    result = _release_result(version)
    raw = str(result.get("status") or (version.get("release", {}) or {}).get("status") or (version.get("release", {}) or {}).get("check_status") or "").upper()
    if raw in {"APPLIED", "DONE", "FORCED_DONE"}:
        return "RELEASE_APPLIED"
    if raw in {"PASS", "PASS_WITH_WARNING", "READY", "DRY_RUN"}:
        return "RELEASE_READY"
    if raw in {"BLOCK", "BLOCKED"}:
        return "RELEASE_BLOCKED"
    if raw in {"FAILED", "ERROR"}:
        return "RELEASE_VERIFY_FAILED"
    return "RELEASE_NOT_CHECKED"


def _catalog_status(version: Mapping[str, Any]) -> str:
    stage = str(version.get("stage") or "").lower()
    lineage = version.get("lineage", {}) or {}
    parent = lineage.get("parent_candidate") or lineage.get("parent")
    base = version.get("base_version") or lineage.get("base_candidate") or lineage.get("base")
    if stage in {"", "unknown", "unknown_stage"}:
        return "UNKNOWN_STAGE"
    if version.get("manual_review") or (version.get("base_required") and not (parent or base)):
        return "NEED_CONFIRM"
    return "OK"


def _overall(scan: str, diff: str, pairwise: str, release: str, catalog: str) -> str:
    if catalog in {"NEED_CONFIRM", "UNKNOWN_STAGE"}:
        return "REVIEW"
    release_blocks = release not in {"RELEASE_NOT_APPLICABLE", "RELEASE_NOT_CHECKED"} and release in {"RELEASE_BLOCKED", "RELEASE_VERIFY_FAILED"}
    if scan in {"SCAN_BLOCK", "SCAN_FAILED"} or diff in {"DIFF_BLOCK", "DIFF_FAILED"} or pairwise == "PAIRWISE_FAILED" or release_blocks:
        return "BLOCK"
    if diff == "DIFF_REVIEW" and pairwise in {"PAIRWISE_PENDING", "PAIRWISE_PARTIAL"}:
        return "REVIEW"
    if scan == "NOT_SCANNED" or diff in {"DIFF_NOT_READY", "DIFF_PENDING"}:
        return "UNKNOWN"
    if release == "RELEASE_APPLIED" or (scan == "SCAN_PASS" and diff in {"DIFF_SAME", "DIFF_REVIEW"} and pairwise in {"PAIRWISE_EMPTY", "PAIRWISE_DONE"}):
        return "OK"
    return "REVIEW"


def _version_links(out_dir: str | Path | None, lib_name: str, version_id: str, version: Mapping[str, Any]) -> dict[str, str]:
    safe_lib = _safe_name(lib_name)
    safe_ver = _safe_name(version_id)
    return {
        "version_review_html": f"versions/{safe_lib}/{safe_ver}/index.html",
        "scan_html": str((version.get("scan", {}) or {}).get("scan_html") or ""),
        "diff_html": _diff_html(version),
        "pairwise_html": (_diff_html(version) + "#pairwise") if _diff_html(version) else "",
        "release_html": str((version.get("release", {}) or {}).get("release_html") or (version.get("release", {}) or {}).get("postcheck_json") or ""),
    }


def _safe_name(value: Any) -> str:
    import re

    text = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value or "item")).strip("._")
    return text or "item"


def build_review_state(catalog: Mapping[str, Any], *, out_dir: str | Path | None = None) -> dict[str, Any]:
    libraries = []
    for lib in catalog.get("libraries", []) or []:
        lib_name = str(lib.get("library_name") or lib.get("library_id") or "unknown")
        versions = []
        for version in _versions(lib):
            version_id = str(version.get("version_id") or version.get("version_key") or "unknown")
            catalog_status = _catalog_status(version)
            scan_status = _status_scan(version)
            diff_status = _status_diff(version, scan_status)
            pairwise_status, pairwise_tasks, pairwise_summary = _pairwise(version)
            release_status = _status_release(version)
            overall_status = _overall(scan_status, diff_status, pairwise_status, release_status, catalog_status)
            lineage = version.get("lineage", {}) or {}
            item: dict[str, Any] = {
                "version_id": version_id,
                "version_key": version.get("version_key"),
                "stage": version.get("stage") or "unknown",
                "raw_path": version.get("raw_path"),
                "base_version": version.get("base_version") or lineage.get("base_candidate") or lineage.get("base"),
                "parent_version": lineage.get("parent_candidate") or lineage.get("parent"),
                "package_type": version.get("package_type"),
                "catalog_status": catalog_status,
                "scan_status": scan_status,
                "diff_status": diff_status,
                "pairwise_status": pairwise_status,
                "pairwise_summary": pairwise_summary,
                "release_status": release_status,
                "risk_level": overall_status,
                "overall_status": overall_status,
                "library_name": lib_name,
                "display_name": lib_name,
                "library_id": lib.get("library_id"),
                "links": _version_links(out_dir, lib_name, version_id, version),
                "pairwise_tasks": pairwise_tasks,
                "release_result": _release_result(version),
            }
            item.update(derive_next_action(item))
            versions.append(item)
        latest = versions[-1]["version_id"] if versions else None
        approved = next((v["version_id"] for v in reversed(versions) if v.get("release_status") == "RELEASE_APPLIED"), None)
        overall = "OK" if versions and all(v.get("overall_status") == "OK" for v in versions) else "REVIEW" if versions else "UNKNOWN"
        if any(v.get("overall_status") == "BLOCK" for v in versions):
            overall = "BLOCK"
        libraries.append(
            {
                "library_id": lib.get("library_id"),
                "display_name": lib_name,
                "vendor": lib.get("vendor") or "",
                "category": lib.get("category") or lib.get("library_type") or "",
                "middle_path": lib.get("middle_path") or "",
                "library_root": lib.get("library_root") or "",
                "latest_version": latest,
                "approved_version": approved,
                "version_count": len(versions),
                "overall_status": overall,
                "versions": versions,
            }
        )
    return {"generated_at": utc_now(), "schema_version": "review_state.v1", "libraries": libraries}
