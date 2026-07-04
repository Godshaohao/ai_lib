from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from lib_guard.project_config import DEFAULT_FILE_DIFF_TYPES


SUPPORTED_PAIRWISE_TYPES = {
    "lef",
    "liberty",
    "verilog",
    "cdl",
    "sdc",
    "upf",
    "cpf",
    "spef",
    "db",
    "waiver",
    "ibis",
    "pwl",
    "snp",
    "cpm",
}

DEFAULT_PAIRWISE_FILE_DIFF_TYPES = set(DEFAULT_FILE_DIFF_TYPES)


def _file_key(item: Mapping[str, Any]) -> str:
    return str(item.get("path") or item.get("file") or item.get("rel_path") or "")


def _file_type(item: Mapping[str, Any]) -> str:
    return str(item.get("file_type") or "unknown").lower()


def _abs_path(item: Mapping[str, Any], scan_dir: Path) -> str:
    value = item.get("abs_path")
    if value:
        return str(value)
    root = item.get("root_path")
    if root:
        return str(Path(str(root)) / _file_key(item))
    meta_root = scan_dir / _file_key(item)
    return str(meta_root)


def _task_id(file_type: str, index: int) -> str:
    return f"pair_{file_type}_{index:04d}"


def build_pairwise_diff_tasks(
    old_scan: str | Path,
    new_scan: str | Path,
    file_diff: Mapping[str, Any],
    *,
    output_root: str | Path | None = None,
) -> dict[str, Any]:
    old = Path(old_scan)
    new = Path(new_scan)
    output = Path(output_root) if output_root else Path("work") / "file_diff"
    old_items = file_diff.get("_old_items") or {}
    new_items = file_diff.get("_new_items") or {}
    tasks: list[dict[str, Any]] = []
    counters: dict[str, int] = {}
    paired_old: set[str] = set()
    paired_new: set[str] = set()

    def add_task(file_type: str, old_key: str, old_item: Mapping[str, Any], new_key: str, new_item: Mapping[str, Any], *, reason: str, confidence: str) -> None:
        counters[file_type] = counters.get(file_type, 0) + 1
        task_id = _task_id(file_type, counters[file_type])
        expected = output / task_id
        old_file = _abs_path(old_item, old)
        new_file = _abs_path(new_item, new)
        tasks.append(
            {
                "task_id": task_id,
                "file_type": file_type,
                "priority": "P1",
                "reason": reason,
                "old_file": old_file,
                "new_file": new_file,
                "old_path": old_key,
                "new_path": new_key,
                "pairing_confidence": confidence,
                "expected_output": str(expected),
                "status": "PENDING",
            }
        )
        paired_old.add(old_key)
        paired_new.add(new_key)

    for rel in file_diff.get("changed", []) or []:
        old_item = old_items.get(rel)
        new_item = new_items.get(rel)
        if not isinstance(old_item, Mapping) or not isinstance(new_item, Mapping):
            continue
        old_type = _file_type(old_item)
        new_type = _file_type(new_item)
        if old_type != new_type or old_type not in DEFAULT_PAIRWISE_FILE_DIFF_TYPES:
            continue
        add_task(old_type, rel, old_item, rel, new_item, reason="changed_file", confidence="path_exact")

    for file_type in sorted(DEFAULT_PAIRWISE_FILE_DIFF_TYPES):
        old_candidates = [
            (key, item)
            for key, item in old_items.items()
            if key not in paired_old and _file_type(item) == file_type
        ]
        new_candidates = [
            (key, item)
            for key, item in new_items.items()
            if key not in paired_new and _file_type(item) == file_type
        ]
        if len(old_candidates) == 1 and len(new_candidates) == 1:
            old_key, old_item = old_candidates[0]
            new_key, new_item = new_candidates[0]
            if old_key in (file_diff.get("removed") or []) or new_key in (file_diff.get("added") or []):
                add_task(file_type, old_key, old_item, new_key, new_item, reason="unique_file_type_added_removed", confidence="unique_file_type")

    return {
        "schema_version": "1.0",
        "status": "PENDING" if tasks else "EMPTY",
        "tasks": tasks,
        "summary": {
            "total": len(tasks),
            "pending": len([t for t in tasks if t.get("status") == "PENDING"]),
            "by_type": {key: len([t for t in tasks if t.get("file_type") == key]) for key in sorted(DEFAULT_PAIRWISE_FILE_DIFF_TYPES)},
        },
    }


def build_pairwise_task_status(tasks: Mapping[str, Any]) -> dict[str, Any]:
    items = list(tasks.get("tasks") or [])
    return {
        "schema_version": "1.0",
        "status": "PENDING" if items else "EMPTY",
        "tasks": [
            {
                "task_id": item.get("task_id"),
                "status": item.get("status", "PENDING"),
                "expected_output": item.get("expected_output"),
            }
            for item in items
        ],
        "summary": {
            "total": len(items),
            "pending": len([item for item in items if item.get("status", "PENDING") == "PENDING"]),
            "done": len([item for item in items if item.get("status") == "DONE"]),
        },
    }
