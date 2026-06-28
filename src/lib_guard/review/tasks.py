from __future__ import annotations

from typing import Any, Mapping
import hashlib

from .io import utc_now


def _task_id(*parts: Any) -> str:
    text = "|".join(str(part or "") for part in parts)
    digest = hashlib.sha1(text.encode("utf-8")).hexdigest()[:10]
    stem = "_".join(str(part or "item").replace("/", "_").replace(" ", "_") for part in parts[:3])
    return f"task_{stem}_{digest}"


def build_review_tasks(review_state: Mapping[str, Any]) -> dict[str, Any]:
    tasks: list[dict[str, Any]] = []
    for lib in review_state.get("libraries", []) or []:
        for version in lib.get("versions", []) or []:
            review_gate = version.get("review_gate") if isinstance(version.get("review_gate"), Mapping) else {}
            for item in (review_gate or {}).get("blocking_items", []) or []:
                if not isinstance(item, Mapping):
                    continue
                category = str(item.get("category") or "")
                task_type = "FIX_RELEASE_BLOCKER" if category in {"release", "scan", "diff", "catalog_trust"} or item.get("fatal") else "ACCEPT_RISK"
                tasks.append(
                    {
                        "task_id": _task_id(lib.get("display_name"), version.get("version_id"), task_type, item.get("id")),
                        "library_id": lib.get("library_id"),
                        "display_name": lib.get("display_name"),
                        "version_id": version.get("version_id"),
                        "task_type": task_type,
                        "priority": "P0" if item.get("fatal") else "P1",
                        "status": "PENDING",
                        "reason": item.get("message") or item.get("title"),
                        "command": "",
                        "expected_output": (review_gate or {}).get("override_file", ""),
                        "source_page": (version.get("links") or {}).get("version_review_html", ""),
                        "review_item_id": item.get("id"),
                    }
                )
            action = version.get("next_action")
            command = version.get("next_command") or ""
            if action in {"DONE"}:
                continue
            if action == "RUN_PAIRWISE":
                priority = "P2"
            else:
                priority = "P0" if version.get("overall_status") == "BLOCK" else "P1" if version.get("overall_status") == "REVIEW" else "P2"
            task_type = {
                "CONFIRM_VERSION_RELATION": "CONFIRM_VERSION_RELATION",
                "RUN_SCAN": "RUN_SCAN",
                "RUN_DIFF": "RUN_DIFF",
                "RUN_PAIRWISE": "PAIRWISE_DIFF",
                "FIX_SCAN_ISSUE": "MANUAL_REVIEW",
                "MANUAL_REVIEW": "MANUAL_REVIEW",
            }.get(str(action), "MANUAL_REVIEW")
            if task_type not in {"CONFIRM_VERSION_RELATION", "RUN_SCAN", "RUN_DIFF", "PAIRWISE_DIFF", "MANUAL_REVIEW"}:
                continue
            tasks.append(
                {
                    "task_id": _task_id(lib.get("display_name"), version.get("version_id"), task_type),
                    "library_id": lib.get("library_id"),
                    "display_name": lib.get("display_name"),
                    "version_id": version.get("version_id"),
                    "task_type": task_type,
                    "priority": priority,
                    "status": "PENDING",
                    "reason": version.get("next_reason"),
                    "command": command,
                    "expected_output": "",
                    "source_page": (version.get("links") or {}).get("version_review_html", ""),
                }
            )
    return {"generated_at": utc_now(), "schema_version": "review_tasks.v1", "tasks": tasks}
