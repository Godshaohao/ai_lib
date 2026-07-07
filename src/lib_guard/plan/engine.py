from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Callable, Mapping

from lib_guard.atomic import atomic_write_json
from lib_guard.effective.pointer import safe_name
from lib_guard.window.resolver import now_iso

PLAN_SCHEMA = "lib_guard.plan.v1"


def plan_path_for(workdir: str | Path, library: str) -> Path:
    return Path(workdir) / "state" / safe_name(library) / "current_plan.json"


def _command_arg(command: list[str], name: str) -> str:
    try:
        idx = command.index(name)
    except ValueError:
        return ""
    if idx + 1 >= len(command):
        return ""
    return str(command[idx + 1])


def _command_fingerprint(command: list[str]) -> str:
    payload = json.dumps(command, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _task_from_command(command: list[str], depends_on: list[str]) -> dict[str, Any]:
    head = command[:2]
    kind = "command"
    task_id = "command:" + _command_fingerprint(command)[:16]
    version = ""
    artifacts: dict[str, Any] = {}
    if command and command[0] == "run":
        kind = "scan"
        version = _command_arg(command, "--version")
        task_id = f"scan:{safe_name(version)}"
        artifacts = {"scan_version": version, "catalog_html_out": _command_arg(command, "--catalog-html-out")}
    elif head == ["effective", "build"]:
        kind = "effective_build"
        effective_id = _command_arg(command, "--effective-id")
        task_id = f"effective_build:{safe_name(effective_id)}"
        artifacts = {"manifest": _command_arg(command, "--out"), "html": _command_arg(command, "--html")}
    elif head == ["effective", "compare"]:
        kind = "effective_compare"
        compare_id = _command_arg(command, "--compare-id")
        task_id = f"effective_compare:{safe_name(compare_id)}"
        artifacts = {"out_dir": _command_arg(command, "--out-dir"), "html": _command_arg(command, "--html")}
    return {
        "id": task_id,
        "kind": kind,
        "command": command,
        "depends_on": list(depends_on),
        "status": "PENDING",
        "input_fingerprint": _command_fingerprint(command),
        "artifact_paths": artifacts,
        "version": version,
        "started_at": None,
        "finished_at": None,
        "exit_code": None,
        "retry_count": 0,
        "failure_reason": "",
    }


def _next_action(tasks: list[Mapping[str, Any]]) -> str:
    for task in tasks:
        if str(task.get("status") or "") == "FAILED":
            return f"retry_{task.get('kind') or 'task'}"
    for task in tasks:
        if str(task.get("status") or "") == "PENDING":
            return f"run_{task.get('kind') or 'task'}"
    return "none"


def _plan_state(tasks: list[Mapping[str, Any]]) -> str:
    if any(str(task.get("status") or "") == "FAILED" for task in tasks):
        return "BLOCKED"
    if any(str(task.get("status") or "") == "RUNNING" for task in tasks):
        return "RUNNING"
    if tasks and all(str(task.get("status") or "") == "DONE" for task in tasks):
        return "DONE"
    return "PENDING" if tasks else "EMPTY"


def _merge_existing_tasks(new_tasks: list[dict[str, Any]], existing_tasks: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    existing_by_id = {str(task.get("id") or ""): task for task in existing_tasks}
    merged: list[dict[str, Any]] = []
    for task in new_tasks:
        old = existing_by_id.get(str(task.get("id") or ""))
        if old and old.get("input_fingerprint") == task.get("input_fingerprint"):
            status = str(old.get("status") or "")
            if status == "DONE":
                carry = dict(task)
                carry.update(
                    {
                        "status": "DONE",
                        "started_at": old.get("started_at"),
                        "finished_at": old.get("finished_at"),
                        "exit_code": old.get("exit_code"),
                        "retry_count": old.get("retry_count", 0),
                        "failure_reason": "",
                    }
                )
                merged.append(carry)
                continue
            if status == "FAILED":
                task["retry_count"] = int(old.get("retry_count") or 0)
        merged.append(task)
    return merged


def load_plan(path: str | Path) -> dict[str, Any]:
    p = Path(path)
    if not p.exists():
        return {}
    data = json.loads(p.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def save_plan(path: str | Path, plan: Mapping[str, Any]) -> Path:
    return atomic_write_json(path, plan, lock=True)


def build_plan_from_window(
    *,
    workdir: str | Path,
    library: str,
    window: Mapping[str, Any],
    existing: Mapping[str, Any] | None = None,
    blocked_reason: str = "",
) -> dict[str, Any]:
    commands = [list(item) for item in window.get("commands", []) or [] if isinstance(item, list)]
    scan_task_ids: list[str] = []
    tasks: list[dict[str, Any]] = []
    build_task_id = ""
    for command in commands:
        depends_on: list[str] = []
        if command and command[0] == "run":
            task = _task_from_command(command, depends_on)
            scan_task_ids.append(str(task["id"]))
        elif command[:2] == ["effective", "build"]:
            task = _task_from_command(command, scan_task_ids)
            build_task_id = str(task["id"])
        elif command[:2] == ["effective", "compare"]:
            task = _task_from_command(command, [build_task_id] if build_task_id else scan_task_ids)
        else:
            task = _task_from_command(command, [str(tasks[-1]["id"])] if tasks else [])
        tasks.append(task)
    if existing:
        tasks = _merge_existing_tasks(tasks, list(existing.get("tasks", []) or []))
    plan = {
        "schema_version": PLAN_SCHEMA,
        "library": library,
        "plan_id": f"intake_{safe_name(str(window.get('last_seen_version') or 'empty'))}",
        "window_path": window.get("pending_window_path"),
        "window_state": window.get("state"),
        "created_at": (existing or {}).get("created_at") or now_iso(),
        "updated_at": now_iso(),
        "state": "BLOCKED" if blocked_reason else _plan_state(tasks),
        "next_action": "confirm_package_type" if blocked_reason else _next_action(tasks),
        "blocked_reason": blocked_reason,
        "tasks": tasks,
    }
    return plan


def execute_plan(
    *,
    plan_path: str | Path,
    plan: dict[str, Any],
    runner: Callable[[list[str]], int],
) -> tuple[int, dict[str, Any]]:
    tasks = [dict(task) for task in plan.get("tasks", []) or []]
    if plan.get("blocked_reason"):
        plan["state"] = "BLOCKED"
        plan["next_action"] = "confirm_package_type"
        save_plan(plan_path, plan)
        return 2, plan
    done: set[str] = {str(task.get("id")) for task in tasks if task.get("status") == "DONE"}
    exit_code = 0
    for task in tasks:
        task_id = str(task.get("id") or "")
        if task.get("status") == "DONE":
            done.add(task_id)
            continue
        missing_dep = [dep for dep in task.get("depends_on", []) or [] if dep not in done]
        if missing_dep:
            task["status"] = "FAILED"
            task["failure_reason"] = "missing dependencies: " + ", ".join(missing_dep)
            exit_code = 2
            break
        task["status"] = "RUNNING"
        task["started_at"] = now_iso()
        task["retry_count"] = int(task.get("retry_count") or 0) + 1
        plan["state"] = "RUNNING"
        plan["next_action"] = f"run_{task.get('kind') or 'task'}"
        plan["updated_at"] = now_iso()
        save_plan(plan_path, {**plan, "tasks": tasks})
        code = int(runner(list(task.get("command", []) or [])))
        task["exit_code"] = code
        task["finished_at"] = now_iso()
        if code == 0:
            task["status"] = "DONE"
            task["failure_reason"] = ""
            done.add(task_id)
            continue
        task["status"] = "FAILED"
        task["failure_reason"] = f"command exited with {code}"
        exit_code = code
        break
    plan["tasks"] = tasks
    plan["state"] = _plan_state(tasks)
    plan["next_action"] = _next_action(tasks)
    plan["updated_at"] = now_iso()
    save_plan(plan_path, plan)
    return exit_code, plan
