from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any, Mapping


def _display_path(value: Any, *, raw_path: Any = None) -> str:
    text = str(value or "-").replace("\\", "/")
    if not raw_path or text in {"", "-"}:
        return text or "-"
    root = str(raw_path).replace("\\", "/").rstrip("/")
    if root and text.startswith(root + "/"):
        return text[len(root) + 1 :]
    return text


def change_paths_for_match(value: Any, *, raw_path: Any = None) -> list[str]:
    if isinstance(value, Mapping):
        iterable = [{"path": key, **(item if isinstance(item, Mapping) else {})} for key, item in value.items()]
    elif isinstance(value, list):
        iterable = value
    else:
        iterable = []
    paths: list[str] = []
    for item in iterable:
        if isinstance(item, Mapping):
            path = _display_path(item.get("path") or item.get("relpath") or item.get("file") or "-", raw_path=raw_path)
        else:
            path = _display_path(item, raw_path=raw_path)
        if path and path != "-":
            paths.append(path)
    return paths


def _match_confidence(reason: str) -> str:
    normalized = reason.lower()
    if any(key in normalized for key in ["hash", "signature", "logical_path"]):
        return "high"
    if "basename" in normalized:
        return "low"
    return "medium"


def path_match_evidence(file_diff: Mapping[str, Any], *, raw_path: Any = None) -> dict[str, dict[str, str]]:
    evidence: dict[str, dict[str, str]] = {}
    for item in file_diff.get("renamed_or_moved", []) or []:
        if not isinstance(item, Mapping):
            continue
        old_path = _display_path(item.get("old") or item.get("base") or "-", raw_path=raw_path)
        new_path = _display_path(item.get("new") or item.get("target") or "-", raw_path=raw_path)
        if old_path == "-" or new_path == "-":
            continue
        reason = str(item.get("reason") or item.get("match_reason") or "matched evidence")
        row_evidence = {
            "match_status": "matched_move",
            "match_kind": "evidence",
            "match_confidence": _match_confidence(reason),
            "base_candidate": old_path,
            "target_candidate": new_path,
            "match_reason": reason,
        }
        evidence[old_path] = dict(row_evidence)
        evidence[new_path] = dict(row_evidence)

    added_by_name: dict[str, list[str]] = defaultdict(list)
    removed_by_name: dict[str, list[str]] = defaultdict(list)
    for path in change_paths_for_match(file_diff.get("added"), raw_path=raw_path):
        added_by_name[Path(path).name].append(path)
    for path in change_paths_for_match(file_diff.get("removed"), raw_path=raw_path):
        removed_by_name[Path(path).name].append(path)
    for basename in sorted(set(added_by_name) & set(removed_by_name)):
        added_paths = sorted(added_by_name[basename])
        removed_paths = sorted(removed_by_name[basename])
        if len(added_paths) != 1 or len(removed_paths) != 1:
            continue
        added_path = added_paths[0]
        removed_path = removed_paths[0]
        if added_path in evidence or removed_path in evidence:
            continue
        row_evidence = {
            "match_status": "candidate_match",
            "match_kind": "evidence",
            "match_confidence": "low",
            "base_candidate": removed_path,
            "target_candidate": added_path,
            "match_reason": "same basename candidate",
        }
        evidence[added_path] = dict(row_evidence)
        evidence[removed_path] = dict(row_evidence)
    return evidence


def default_path_match_evidence(change: str, path: str) -> dict[str, str]:
    if change == "changed":
        return {
            "match_status": "not_applicable",
            "match_kind": "evidence",
            "match_confidence": "exact",
            "base_candidate": path or "-",
            "target_candidate": path or "-",
            "match_reason": "same path changed",
        }
    if change == "removed":
        return {
            "match_status": "unmatched",
            "match_kind": "evidence",
            "match_confidence": "none",
            "base_candidate": path or "-",
            "target_candidate": "-",
            "match_reason": "no deterministic match",
        }
    return {
        "match_status": "unmatched",
        "match_kind": "evidence",
        "match_confidence": "none",
        "base_candidate": "-",
        "target_candidate": path or "-",
        "match_reason": "no deterministic match",
    }
