"""Data model for the single-library Catalog workspace page.

The library workspace is a navigation surface, not the deep review report.
It should make three concepts explicit and keep them separate:

* current effective pointer: what the user should treat as current;
* latest candidate delivery: what needs review now;
* effective evidence: composed effective manifests discovered on disk.
"""

from __future__ import annotations

from typing import Any, Mapping

from lib_guard.render import catalog_render_common as common
from lib_guard.render import catalog_report as catalog


def version_id(version: Mapping[str, Any] | None) -> str:
    if not isinstance(version, Mapping):
        return ""
    return str(version.get("version_id") or version.get("version") or "")


def find_version(versions: list[Mapping[str, Any]], wanted: Any) -> Mapping[str, Any] | None:
    target = str(wanted or "")
    if not target:
        return None
    return next((version for version in versions if version_id(version) == target), None)


def current_effective_version(
    lib: Mapping[str, Any],
    versions: list[Mapping[str, Any]],
    effective_items: list[dict[str, Any]],
    latest_effective_ref: str = "",
) -> tuple[str, Mapping[str, Any] | None, str]:
    for item in effective_items:
        if item.get("is_current_effective") or item.get("effective_status") == "current":
            effective_id = str(item.get("effective_id") or "")
            if effective_id:
                return effective_id, None, "effective_manifest"

    for value in [
        latest_effective_ref,
        lib.get("current_effective_ref"),
        lib.get("latest_effective_ref"),
        lib.get("current_effective_version"),
        lib.get("approved_version"),
    ]:
        found = find_version(versions, value)
        if found:
            return version_id(found), found, "catalog_current"
        if value:
            return str(value), None, "catalog_current"

    for version in reversed(versions):
        if common.truthy(version.get("current_effective")):
            return version_id(version), version, "version_flag"

    current_version = lib.get("current_version")
    found = find_version(versions, current_version)
    if found:
        return version_id(found), found, "current_version_fallback"
    if current_version:
        return str(current_version), None, "current_version_fallback"

    if versions:
        return "", None, "unconfirmed"
    return "", None, "missing"


def latest_effective_evidence(effective_items: list[dict[str, Any]]) -> dict[str, Any]:
    return catalog._latest_effective_item(effective_items) or (effective_items[-1] if effective_items else {})


def latest_candidate_version(
    lib: Mapping[str, Any],
    versions: list[Mapping[str, Any]],
    current_ref: str,
) -> Mapping[str, Any] | None:
    explicit = find_version(versions, lib.get("latest_candidate_version") or lib.get("latest_version"))
    if explicit:
        return explicit
    for version in reversed(versions):
        if version_id(version) != current_ref:
            return version
    return versions[-1] if versions else None


def diff_label(version: Mapping[str, Any] | None) -> tuple[str, str]:
    if not isinstance(version, Mapping):
        return "UNKNOWN", "未知"
    status = common.status_key(version.get("diff_status") or (version.get("diff") or {}).get("status"))
    if status in {"DIFF", "CHANGED", "REVIEW_REQUIRED"}:
        return status, "有变化"
    if status in {"PASS", "SAME", "NO_DIFF", "UNCHANGED"}:
        return status, "无变化"
    if status in {"FAILED", "ERROR", "BLOCKED"}:
        return status, "失败"
    return status or "COMPARE_PENDING", "待对比"


def base_for_candidate(candidate: Mapping[str, Any] | None, current_ref: str) -> str:
    if not isinstance(candidate, Mapping):
        return current_ref or ""
    return (
        common.previous_effective_version(candidate)
        or str((candidate.get("diff") or {}).get("base_version") or "")
        or common.base_full_version(candidate)
        or current_ref
        or ""
    )


def candidate_action_text(candidate: Mapping[str, Any] | None, current_ref: str, *, current_confirmed: bool = True) -> str:
    candidate_id = version_id(candidate)
    if not candidate_id:
        return "暂无待审版本"
    if not current_confirmed:
        return "先确认当前有效版，再审查最新待审版"
    if candidate_id == current_ref:
        return "最新版本已是当前有效版"
    scan_status, _scan_text = catalog._scan_label(candidate or {})
    _diff_status, diff_text = diff_label(candidate)
    if scan_status == "NOT_SCANNED":
        return "先扫描最新待审版，再进入版本详情"
    if diff_text == "待对比":
        return "先和当前有效版对比，再进入版本详情"
    return "进入版本详情审查视图变化和证据等级"


def build_library_workspace_model(
    lib: Mapping[str, Any],
    effective_items: list[dict[str, Any]],
    *,
    timeline: list[dict[str, Any]] | None = None,
    latest_effective_ref: str = "",
) -> dict[str, Any]:
    versions = list(lib.get("versions", []) or [])
    timeline_items = list(timeline or [])
    current_ref, current_version, current_source = current_effective_version(
        lib,
        versions,
        effective_items,
        latest_effective_ref,
    )
    current_confirmed = bool(current_ref and current_source not in {"unconfirmed", "missing"})
    candidate = latest_candidate_version(lib, versions, current_ref if current_confirmed else "")
    candidate_ref = version_id(candidate)
    scan_status, scan_text = catalog._scan_label(candidate or {})
    diff_status, diff_text = diff_label(candidate)
    base_ref = base_for_candidate(candidate, current_ref)
    effective = latest_effective_evidence(effective_items)
    release_status = common.status_key((candidate or {}).get("release_status") or effective.get("release_status"))
    changed = "changed" in catalog._version_tags(candidate or {}) or diff_text == "有变化"
    evidence_needs_review = scan_status == "NOT_SCANNED" or diff_text != "无变化" or changed
    needs_review = bool(candidate_ref and (not current_confirmed or candidate_ref != current_ref or evidence_needs_review))
    if not current_confirmed:
        decision = "需确认当前有效版"
    elif scan_status == "NOT_SCANNED":
        decision = "需补扫描证据"
    elif diff_text != "无变化" or changed:
        decision = "需审查"
    else:
        decision = "可使用"
    return {
        "library_id": str(lib.get("library_id") or lib.get("display_name") or lib.get("library_name") or ""),
        "current_effective_ref": current_ref if current_confirmed else "未确认",
        "current_effective_source": current_source,
        "current_effective_confirmed": current_confirmed,
        "current_effective_version": current_version,
        "latest_candidate_ref": candidate_ref or "-",
        "latest_candidate_version": candidate,
        "base_ref": base_ref or "-",
        "scan_status": scan_status,
        "scan_text": scan_text,
        "diff_status": diff_status,
        "diff_text": diff_text,
        "release_status": release_status or "UNKNOWN",
        "decision": decision,
        "needs_review": needs_review,
        "candidate_action_text": candidate_action_text(candidate, current_ref, current_confirmed=current_confirmed),
        "timeline_count": len(timeline_items),
        "version_count": len(versions),
        "effective_evidence_ref": str(effective.get("effective_id") or ""),
        "effective_evidence_manifest": str(effective.get("manifest") or ""),
        "effective_evidence_html": str(effective.get("html") or ""),
        "effective_evidence_release_preview": str(effective.get("release_preview") or ""),
    }
