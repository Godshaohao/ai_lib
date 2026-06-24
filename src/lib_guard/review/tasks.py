from __future__ import annotations

from typing import Any, Mapping

from .io import utc_now


def build_review_tasks(review_state: Mapping[str, Any]) -> dict[str, Any]:
    tasks: list[dict[str, Any]] = []
    for lib in review_state.get("libraries", []) or []:
        for version in lib.get("versions", []) or []:
            action = version.get("next_action")
            command = version.get("next_command") or ""
            if action in {"DONE"}:
                continue
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
                    "task_id": f"task_{lib.get('display_name')}_{version.get('version_id')}_{task_type}".replace("/", "_").replace(" ", "_"),
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
