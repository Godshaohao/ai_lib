from __future__ import annotations

from typing import Any, Mapping


def _text(value: Any, default: str = "") -> str:
    text = str(value or "").strip()
    return text or default


def _blockers_from_review_gate(review_gate: Mapping[str, Any]) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    for item in review_gate.get("blocking_items", []) or []:
        if not isinstance(item, Mapping):
            continue
        blockers.append(
            {
                "id": _text(item.get("id"), "unknown"),
                "category": _text(item.get("category"), "review_gate"),
                "title": _text(item.get("title"), "Release review blocker"),
                "reason": _text(item.get("why") or item.get("message"), "Release is blocked by review gate."),
                "next_action": _text(item.get("next_action"), "accept/waive the item or force release with audit reason"),
            }
        )
    return blockers


def _blockers_from_release_check(result: Mapping[str, Any]) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    for idx, reason in enumerate(result.get("block_reasons", []) or [], start=1):
        blockers.append(
            {
                "id": f"release_check.block_reason:{idx}",
                "category": "release_check",
                "title": "Release check blocked",
                "reason": str(reason),
                "next_action": "fix release evidence or force release with audit reason",
            }
        )
    for idx, issue in enumerate(result.get("issues", []) or [], start=1):
        if not isinstance(issue, Mapping):
            continue
        blockers.append(
            {
                "id": _text(issue.get("id"), f"release_check.issue:{idx}"),
                "category": _text(issue.get("category"), "release_check"),
                "title": _text(issue.get("title"), "Release check issue"),
                "reason": _text(issue.get("message") or issue.get("reason"), "Release check issue requires attention."),
                "next_action": _text(issue.get("next_action"), "fix release evidence or force release with audit reason"),
            }
        )
    return blockers


def _failed_phase(result: Mapping[str, Any]) -> str:
    catalog_status = str(result.get("catalog_status") or "").upper()
    if catalog_status in {"NEED_CONFIRM", "UNKNOWN_STAGE", "CATALOG_NOT_READY"}:
        return "CATALOG_NOT_READY"
    scan_status = str(result.get("scan_status") or "").upper()
    if scan_status in {"NOT_SCANNED", "SCAN_MISSING", "DIFF_NOT_READY"} or result.get("scan_missing"):
        return "SCAN_MISSING"
    review_gate = result.get("review_gate") if isinstance(result.get("review_gate"), Mapping) else {}
    if review_gate and (review_gate.get("status") in {"REVIEW_REQUIRED", "BLOCKED"} or review_gate.get("blocking_items")):
        return "REVIEW_GATE_BLOCKED"
    status = str(result.get("release_check_status") or result.get("status") or "").upper()
    verify_status = str(result.get("verify_status") or "").upper()
    if status in {"VERIFY_FAILED"} or verify_status in {"FAILED", "BLOCK", "VERIFY_FAILED"}:
        return "VERIFY_FAILED"
    for item in result.get("failed_links", []) or []:
        if not isinstance(item, Mapping):
            continue
        item_status = str(item.get("status") or "").upper()
        error = str(item.get("error") or "").lower()
        if "source does not exist" in error or "no such file" in error:
            return "MANIFEST_SOURCE_MISSING"
        if item_status == "TARGET_EXISTS" or "target exists" in error or "already exists" in error:
            return "TARGET_EXISTS"
        if "permission denied" in error or "access is denied" in error:
            return "PERMISSION_DENIED"
    if status in {"BLOCK", "BLOCKED"}:
        return "RELEASE_CHECK_BLOCKED"
    if status in {"FAILED", "ERROR"}:
        return "LINK_FAILED"
    return "UNKNOWN"


def explain_release_check(result: Mapping[str, Any]) -> dict[str, Any]:
    library = _text(result.get("library_name") or result.get("library") or result.get("library_id"), "<LIBRARY>")
    version = _text(result.get("version") or result.get("version_id") or result.get("release_version"), "<VERSION>")
    review_gate = result.get("review_gate") if isinstance(result.get("review_gate"), Mapping) else {}
    blockers = _blockers_from_review_gate(review_gate)
    if not blockers:
        blockers = _blockers_from_release_check(result)
    phase = _failed_phase(result)
    status = "BLOCKED" if phase != "UNKNOWN" else _text(result.get("release_check_status") or result.get("status"), "UNKNOWN")
    return {
        "status": status,
        "failed_phase": phase,
        "blockers": blockers,
        "safe_actions": [
            f"lg.csh rv-check {library} {version} --gate current",
            f"lg.csh rel {library} {version} --check-first --explain",
        ],
        "force_actions": [
            f"lg.csh rel {library} {version} --apply --force --force-reason <REASON> --force-by <USER>",
        ],
    }
